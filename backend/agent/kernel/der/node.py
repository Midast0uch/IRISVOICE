# Moved from backend/agent/agent_kernel.py by scripts/kernel_split_check.py move.
# Bodies are byte-identical to the originals (guard: kernel_split_check.py manifest --check).
from __future__ import annotations

import re
import hashlib
import threading
import os
import uuid
from backend.agent.inference.errors import RateLimitedError
from backend.agent.call_context import (
    CallClass,
    set_call_class,
    restores_call_class,
)
from backend.agent.tool_decision import ToolDecisionBox, Decision, DecisionKind, DispatchResult
from typing import Any, Dict, Optional, List, Callable, Tuple, Sequence
import json
import time
from backend.agent.kernel.base import (
    _CLAIM_LOCKS,
    _CLAIM_LOCKS_GUARD,
    _DER_NODE_QUOTA,
    _DER_PARALLEL,
    _NODE_CLAIMS,
    _SCREEN_CLAIM,
    _step_evidence_cap,
    logger,
)
# -- CLM Wave 2 (specs/clm-memory): the node's record / window / event hooks --
# One flag. Unset = NodeContext gets None/0 and the node runs byte for byte as
# before (proven by the parity harnesses). Module level so a stand-in kernel
# that binds only _der_run_node still reaches them (CLAUDE.md STAND-INS).
_CLM_KEEP_CHARS = 2500   # what a later step keeps of one read (NODE_BLOCK_HEAD)
_CLM_NO_RECORD = frozenset({"recall_memory"})  # an expand result is never recorded again


def _clm_offload_on() -> bool:
    return os.environ.get("IRIS_CLM_OFFLOAD") == "1"


_CLM_EXPAND_PARAMS = {
    "expand": {"type": "string", "description": (
        "A reference from a set-aside or cut result, e.g. tool_result:<id>, or an "
        "earlier thread's thread:<id>. Returns the exact text; query is then not needed.")},
    "offset": {"type": "integer", "description": (
        "With expand: the character to start from (default 0); the reply gives "
        "next_offset when more text follows.")},
    "set_aside": {"type": "string", "description": (
        "One or more references (tool_result:<id>, separated by spaces) of results "
        "to replace with a one-line slip that keeps their reference.")},
    "reason": {"type": "string", "description": "With set_aside: why, in a few words."},
    "summary": {"type": "string", "description": (
        "With set_aside: optional note on what the set-aside results showed; it is kept "
        "as a note that links to them.")},
    "audit_pin": {"type": "string", "description": (
        "A note's pin id: returns the results it was written from and whether each "
        "still resolves.")},
}
_CLM_RECALL_FACTS = (
    " Tool results carry [ref tool_result:<id>]; a long result's cut mark names its ref."
    " set_aside=<ref> replaces a result with a one-line slip that keeps the ref;"
    " expand=<ref> returns the exact text."
)


def _clm_recall_menu(tools: list, full: list) -> list:
    """The node menu with recall_memory present and able to expand a reference."""
    import copy

    base = next((t for t in tools if (t.get("function") or {}).get("name") == "recall_memory"), None)
    base = base or next((t for t in full if (t.get("function") or {}).get("name") == "recall_memory"), None)
    if base is None:
        return tools
    spec = copy.deepcopy(base)
    params = spec.setdefault("function", {}).setdefault("parameters", {"type": "object"})
    params.setdefault("properties", {}).update(copy.deepcopy(_CLM_EXPAND_PARAMS))
    params["required"] = [r for r in params.get("required") or [] if r != "query"]
    fn = spec["function"]
    fn["description"] = (fn.get("description") or "") + _CLM_RECALL_FACTS
    out = [t for t in tools if (t.get("function") or {}).get("name") != "recall_memory"]
    return out + [spec]


def _clm_dead_ends(kernel, session: str, turn_id) -> list:
    """The task's dead ends (memory_cases, the key finalize's record_step uses)."""
    try:
        from backend.agent.ontology_recall import resolve_mycelium_conn
        from backend.memory.memory_events import dead_ends_for

        conn = resolve_mycelium_conn(getattr(kernel, "_memory_interface", None))
        return dead_ends_for(conn, f"{session}:{turn_id or ''}") if conn is not None else []
    except Exception as exc:  # noqa: BLE001 - no ledger, logged
        logger.warning("[clm] dead ends unreadable (%r): ledger empty", exc)
        return []


# CLM-5 AC6 (T4.4): a FIXED-SIZE header of the proven claims of the step's topic.
# The topic is the registry rule the sectors use (resolve_topic_domain); a goal in
# "general" or a sector with no proven claim gets an empty header - never padded.
# A stale claim is shown AS stale (re-check before relying on it).
_CLM_HEADER_MAX = 3
_CLM_HEADER_CHARS = 160


_CLM_EVENT_ROW = {"OFFLOADED": "offloaded", "RESTRETCHED": "restretched",
                  "PREMATURE_EVICTION": "premature_eviction"}


def _clm_measure(conv: str, label: str, payload: dict) -> None:
    """T5.2: the view decision as a baseline row (values only; off unless IRIS_CLM_BASELINE=1)."""
    event = _CLM_EVENT_ROW.get(label)
    if not event:
        return
    from backend.agent.inference import clm_baseline as _cb

    p = payload or {}
    _cb.record_event(conv, event, actor=str(p.get("by") or "harness"),
                     trigger=str(p.get("trigger") or ""), tokens=int(p.get("saving") or 0),
                     units=len(p.get("refs") or []))


def _clm_landmark_header(kernel, goal: str) -> list:
    """Up to _CLM_HEADER_MAX claim lines for the goal's sector ([] when none)."""
    try:
        from backend.agent.ontology_recall import resolve_mycelium_conn
        from backend.memory.mycelium.extractor import resolve_topic_domain

        sector = resolve_topic_domain(goal or "")
        if sector == "general":
            return []
        conn = resolve_mycelium_conn(getattr(kernel, "_memory_interface", None))
        if conn is None:
            return []
        # idx_landmark_sectors_sector (sector_key), then the landmark PK per row.
        rows = conn.execute(
            "SELECT l.label, l.tier FROM mycelium_landmark_sectors s "
            "JOIN mycelium_landmarks l ON l.landmark_id = s.landmark_id "
            "WHERE s.sector_key = ? AND l.tier IN ('landmark', 'stale') "
            "AND COALESCE(l.absorbed, 0) = 0 "
            "ORDER BY COALESCE(l.activation_count, 0) DESC, l.cumulative_score DESC LIMIT ?",
            (sector, _CLM_HEADER_MAX)).fetchall()
    except Exception as exc:  # noqa: BLE001 - no header, logged
        logger.warning("[clm] landmark header unreadable (%r): header empty", exc)
        return []
    out = []
    for label, tier in rows:
        text = " ".join(str(label or "").split())[:_CLM_HEADER_CHARS]
        if text:
            out.append(text + (" (stale: re-check before relying on it)" if tier == "stale" else ""))
    return out


# CLM (small-model gate 2026-11-15): on a small window the tool menu is a
# protected block that alone overflowed the shrink limit (Wave 0: p50 1,733,
# p95 5,968 tokens per call). The menu gets 15 % of the window; the core
# coding tools and recall_memory are kept first, the rest in menu order while
# they fit. A 128k window keeps the whole menu (15 % = 19,200 tokens).
_MENU_SHARE = 0.15


def _clm_menu_budget(tools: list, window: int) -> list:
    if not window:
        return tools
    from backend.agent.context_gauge import estimate_tokens

    room = int(window * _MENU_SHARE)
    first = [t for t in tools if (t.get("function") or {}).get("name") in _NODE_CORE_TOOLS
             or (t.get("function") or {}).get("name") == "recall_memory"]
    rest = [t for t in tools if t not in first]
    kept, used = [], 0
    for t in first + rest:
        cost = estimate_tokens([], [t])
        if kept and used + cost > room:
            continue
        kept.append(t)
        used += cost
    if len(kept) < len(tools):
        logger.info("[clm] node menu %d -> %d tools (~%d tokens, window %d)",
                    len(tools), len(kept), used, window)
    order = {id(t): i for i, t in enumerate(tools)}
    return sorted(kept, key=lambda t: order[id(t)])


# -- CLM-11 Workbench code mode (IRIS_WORKBENCH; unset = today's node, byte for byte)
_WB_SYSTEM = (
    "You do ONE step of a task by writing Python and running it with run_python. The "
    "current folder is the project: use relative paths; never chdir; never use an "
    "absolute path. PROJECT FILES lists what is there - do not list the folder again. "
    "Variables persist between your runs. Ready variables: task, goal, steps, memory, "
    "files. The BRIEF names the output variables: write the whole step as ONE script "
    "that assigns every output. The harness runs the brief's check after each run and "
    "closes the step when it passes. Read files with open(); print at most a few lines. "
    "Other languages run from the same script: sh('python -m pytest -q'), sh('node app.js'), "
    "sh('npm test'), or a JavaScript snippet with sh('node -', input=js_code); "
    "sh() returns a dict with code, stdout, stderr. "
    "With no BRIEF, when done answer with a short summary ending `STATUS: done` or "
    "`STATUS: failed: <reason>`."
)
_WB_TOOLS_NOTE = (
    " Inside a script, `tools.<name>(**args)` calls an IRIS tool through the same path "
    "the step's own tool calls take; it returns the result dict, and raises ToolError "
    "when the tool fails or is not available (at most 24 calls per run; later lines "
    "do not run after an uncaught ToolError). Tools: "
)
_WB_TOOLS_PREFER = ("read_file", "grep_files", "glob_files", "edit_file", "write_file", "run_command")
_WB_TOOLS_MAX = 5
# Round 6 (2026-11-16): the browser as a code node's tool. A script may drive the page of the
# conversation (one page, one driver: the node holds the `browser` claim for the whole step).
_WB_BROWSER_TOOLS = frozenset({"browser_open", "browser_read", "browser_observe", "browser_act",
                               "browser_explore"})
_WB_BROWSER_CALLS_MAX = 12   # browser callbacks per run_python (the worker's general cap is 24)
_WB_BROWSER_MARGIN_S = 20.0  # the browser wall budget = the node's budget minus this
_WB_ENDED = "the step ended"
# Exact result fields (2026-11-17 smoke run d03: the script spent 7 runs guessing browser_read's
# keys - it returns both `content` and `text` - and took the digest's "chars cut" mark in its
# printout for a cut page).
_WB_BROWSER_NOTE = (
    " BROWSER: tools.browser_observe() -> marks (id, role, name, disabled): pick by name, then "
    "tools.browser_act(action=..., element_id=...); observe again after a change. "
    "tools.browser_read() -> dict: text (the whole page text), links, url, title - parse text "
    "in the script; printed output is cut, the page is not. Label not in marks: raise "
    "ToolError('needs sight'). Never log in or type credentials."
)
# Round 6 PROTOTYPE: when the side-lane fetch seeded the task's page(s), tell the
# tool model so it parses them in ONE script instead of opening them again.
_WB_PAGE_SEED_NOTE = (
    " PAGE TEXT IS ALREADY HERE: the variable `page_text` holds the task's page(s) "
    "as a list of {'url': ..., 'text': ...} dicts, read before this step. Parse it "
    "directly in your script - do NOT call browser_open/browser_read for a page whose "
    "url is already in page_text. Use browser tools only for pages NOT in page_text. "
    "Write ONE script that computes every output from page_text."
)
# Round 6 option 1 (IRIS_WB_SELF_VERIFY): give the tool model the check expression
# and ask it to verify INSIDE one script, so it does not spend model round trips
# waiting for the harness to tell it the check failed. Flag-gated; off = unchanged.
def _wb_self_verify_on() -> bool:
    return os.environ.get("IRIS_WB_SELF_VERIFY") == "1"


# Round 6 option 3 (2026-11-20): the program owns the two phases. The model emits
# TWO run_python tool calls in ONE response; the loop executes them in order in the
# SAME worker namespace. Call 1 gathers data into variables, call 2 computes and
# assigns the outputs from those variables. One model generate, two executions -
# the second execution is NOT a second model call. Flag-gated; off = unchanged.
def _two_call_on() -> bool:
    return os.environ.get("IRIS_WB_TWO_CALL") == "1"


# Round 6 option 3b (2026-11-20): let the model SEE the gather result before it
# writes compute. Two model calls per code node, but the compute script is written
# against the real data (not blind), so it can assign outputs correctly. The TTS
# logs showed the blind pair's compute phase printed instead of assigning because
# it could not adapt to what gather found. Flag-gated; off = unchanged.
def _see_gather_on() -> bool:
    return os.environ.get("IRIS_WB_SEE_GATHER") == "1"


_WB_SEE_GATHER_SYSTEM = (
    "You do ONE step of a task in TWO scripts. You will be called TWICE.\n"
    "SCRIPT 1 (gather): open the EXACT page the task names with "
    "tools.browser_open(url) then tools.browser_read(), and store the result dict "
    "in a variable named `raw`. Print only a short confirmation (e.g. the page "
    "title and text length). Do NOT assign the output variables yet. "
    "Do NOT use crawler_query - it may return a DIFFERENT page than the one named.\n"
    "After SCRIPT 1 the harness shows you its result, including the page text.\n"
    "SCRIPT 2 (compute): using what SCRIPT 1 found, write ONE script that assigns "
    "EVERY output variable named in the BRIEF. Parse the page text with regex on "
    "plain text (prices look like '£51.77'; use re.findall(r'£([0-9.]+)', text)). "
    "Do NOT write HTML tag regexes - the text has no tags. If the answer needs a "
    "linked page (e.g. an author page), open and read it in SCRIPT 2 before "
    "assigning. Assign your best parse; do NOT add assert statements - the harness "
    "runs the check.\n"
    "Inside a script, tools.<name>(...) calls an IRIS tool and returns its result "
    "dict; positional and keyword arguments both work. "
    "Direct network (urllib, requests, socket) is REFUSED - use the app's tools. "
    "The worker is STDLIB ONLY (no bs4, requests, pandas); use re and json. "
    "Use relative paths; never chdir."
)


_WB_TWO_CALL_SYSTEM = (
    "You do ONE step of a task. Reply with ONE assistant message that contains "
    "EXACTLY TWO run_python tool calls, in this order:\n"
    "  CALL 1 (gather): open/read the pages you need and store the raw text in a "
    "variable such as `raw`. Do NOT print long text and do NOT assign the output "
    "variables yet.\n"
    "  CALL 2 (compute): using the variables CALL 1 left in the SAME namespace, "
    "compute the answer and assign EVERY output variable named in the BRIEF. "
    "CALL 2 may call tools too - if the answer needs another page (e.g. an author "
    "page linked from the first), open and read it here before assigning. "
    "Assign the outputs from your best parse; do NOT add assert statements that "
    "could fail on a slightly different page layout - the harness runs the check.\n"
    "Both calls run in the same persistent namespace, so variables from CALL 1 are "
    "available in CALL 2. The harness runs the brief's check after each call; CALL 2 "
    "must pass it. Do not emit more than two run_python calls. "
    "Inside a script, tools.<name>(...) calls an IRIS tool and returns its result "
    "dict; positional and keyword arguments both work. "
    "FOR A WEB STEP: the PAGE DATA section in your prompt MAY contain the FULL plain "
    "text of the task's page(s) (NOT HTML). In CALL 1, set `raw` defensively: if the "
    "variable `page_text` exists and is non-empty, use page_text[0]['text']; OTHERWISE "
    "fetch it yourself with tools.browser_open(url) then tools.browser_read() and take "
    "the 'text' field. Write it as: "
    "raw = page_text[0]['text'] if 'page_text' in dir() and page_text else "
    "tools.browser_read().get('text',''). "
    "In CALL 2, parse `raw` with regex on plain text to assign every output. "
    "Prices appear as '£51.77'; use re.findall(r'£([0-9.]+)', text). "
    "Do NOT write HTML tag regexes - the text has no tags. "
    "Do NOT use crawler_query - it may return a DIFFERENT page than the one named. "
    "Direct network (urllib, requests, socket) is REFUSED - use the app's tools. "
    "The worker is STDLIB ONLY (no bs4, requests, pandas); use re and json. "
    "Use relative paths; never chdir."
)


def _wb_self_verify_note(check: str) -> str:
    if not check:
        return ""
    return (
        " SELF-CHECK: the step's check is: " + check[:300] + ". The output variables are "
        "in your namespace. Write ONE script that assigns every output, then verify the "
        "check YOURSELF inside the script (e.g. `assert (" + check[:300] + ")`) before you "
        "finish. Do not write a script that only prints or inspects data and leave the check "
        "to the harness - do the whole step, including your own verification, in one script. "
        "The harness will confirm, but you should already know it passes."
    )


_WB_OBS_MARK = "Elements (pass the number as element_id to browser_act):"
_WB_POOR_MARKS = 2           # an observation with this many marks or fewer cannot be scripted
_WB_SKELETON_MAX_LINES = 40
# Room for the provider's hidden reasoning in ONE send: a real repair is a hard debugging
# question - TG-7 v2 full (2026-11-17) measured 4,846-5,988 completion tokens at 4096, cut,
# resent up to 4 times (each resend generates again from the start): 166-177 s per repair.
# The model writes only what it needs, so the larger cap costs nothing when unused.
_WB_REPAIR_MAX_TOKENS = 16384
_WB_REPAIR_PROMPT = (
    "A small model is doing one step of a task in a Python workbench and its result "
    "failed the step's check twice. Write a REPAIR BRIEF: one sentence on the cause, "
    "then one ```python block of at most 40 lines that "
    "fills the outputs so the check passes. Use relative paths and only the names in "
    "the brief.\n\nPROJECT FILES:\n{ground}\n\nBRIEF:\n{brief}\n\nCHECK: {check}\n\n"
    "ITS LAST CODE:\n{code}\n\nWHAT THE WORKBENCH REPORTED:\n{digest}"
)
_WB_PRIOR_HEAD = 300   # earlier results ride in `steps`; the message keeps a head
# W0 (Round 4): wb_wait_s = seconds code nodes waited for the `workbench` claim (D7);
# scripts = run_python calls in code nodes; exploring = runs _is_exploration counted.
_wb_stats = {"code_nodes": 0, "fallback": 0, "unavailable": 0, "seed_failed": 0,
             "wb_wait_s": 0.0, "scripts": 0, "exploring": 0}
# Tools a Python script replaces with open() / glob / re / subprocess: a brief that names
# only these gets no `tools.<name>` note (D6). Anything else it names keeps the note.
_WB_PY_REPLACES = frozenset({"read_file", "grep_files", "glob_files", "run_command",
                             "list_directory", "list_dir", "list_files", "search_files"})


def _wb_on() -> bool:
    return os.environ.get("IRIS_WORKBENCH") == "1"


def wb_stats() -> dict:
    return dict(_wb_stats)


def _wb_code_mode(goal: str, tools: list, workdir: str, item=None) -> bool:
    """The stated entry rule (design "Code mode and fallback", D4): developer mode
    (run_python offered), a step with a brief that has outputs AND a check, or a READ / RUN
    step, no external / screen reference, an interpreter that can run the worker - and NEVER a
    WRITE-class step (file-changing steps stay on the menu path until the read/run gain is
    proven, owner 2026-11-16). `item` (the planner step, optional) carries the brief."""
    if not _wb_on():
        return False
    if not any((t.get("function") or {}).get("name") == "run_python" for t in tools):
        return False
    try:
        from backend.agent import external_reference as _xr
        from backend.agent.tool_choice_action_class import (
            READ, RUN, WRITE, required_class, required_classes)
        from backend.agent.tool_decision import _vision_relevant

        # required_class() reads a fix-verb goal ("Edit config.yaml") as READ; the plural form
        # lists WRITE for it, and for create/write/add/...
        if WRITE in (required_classes(goal) or ()):
            return False
        # S3 (Round 5, owner 2026-11-16): a step after a file-changing step of this turn stays
        # on the menu path - the check after a change belongs with it. `wb_after_change` is
        # set by the caller (_wb_after_change) only when the flag is on.
        if getattr(item, "wb_after_change", False) is True:
            return False
        briefed = bool(getattr(item, "outputs", None)) and bool(
            str(getattr(item, "check", "") or "").strip())
        if not briefed and required_class(goal) not in (READ, RUN):
            return False
        # Round 6 C3: the external-reference exclusion is lifted ONLY for a briefed step that
        # names an offered browser tool; a step about the screen still refuses.
        if _vision_relevant(goal) or (not _wb_browser_step(item, tools)
                                      and _xr.is_external(_xr.classify(goal))):
            return False
        from backend.agent.workbench.client import resolve_interpreter

        if not resolve_interpreter(workdir or "."):
            _wb_stats["unavailable"] += 1
            return False
    except Exception as exc:  # noqa: BLE001 - the fine-grained node runs, logged
        logger.warning("[workbench] entry rule failed (%r): fine-grained node", exc)
        return False
    return True


def _wb_browser_step(item, tools) -> bool:
    """Round 6 C3: a browser code step = a brief with outputs AND a check, whose `tools` names
    a browser tool the node was OFFERED (the web toggle takes the browser tools out of the
    offered list, so it holds). The caller has already refused WRITE / after-change steps.
    Round 6 fix (a): a single-page lookup marked by the planner stays on the menu path even
    when it carries a brief - only multi-page / computed browser work enters code mode."""
    try:
        if getattr(item, "wb_browser_single", False) is True:
            return False
        if not (getattr(item, "outputs", None) and str(getattr(item, "check", "") or "").strip()):
            return False
        named = {str(n).strip() for n in (getattr(item, "tools", None) or ()) if isinstance(n, str)}
        offered = {(t.get("function") or {}).get("name") for t in tools or []}
        return bool(named & _WB_BROWSER_TOOLS & offered)
    except Exception:  # noqa: BLE001 - an item that cannot be read is not a browser step
        return False


def _wb_scratch_dir(conversation_id: str) -> Optional[str]:
    """Round 6 C8: the conversation's private scratch folder when the mode is personal; "" when
    it is not (the workdir stays as it is); None when the folder is refused. A personal
    conversation with no bound folder would otherwise resolve to the IRIS repo, which personal
    mode refuses."""
    try:
        from backend.capabilities import CapabilitySet

        if CapabilitySet.get_mode() != "personal":
            return ""
        from backend.agent.workbench.manager import scratch_workdir

        return scratch_workdir(conversation_id)
    except Exception as exc:  # noqa: BLE001 - the node stays on the menu path, logged
        logger.warning("[workbench] conv=%s scratch folder unavailable: %r", conversation_id, exc)
        return None


def _wb_script_view(raw):
    """Round 6 C6: what a script may see of a tool result: no picture (marked_screenshot or any
    b64 field) and `marks` trimmed to id / role / name / disabled. A copy; the node's own
    bookkeeping keeps the full result."""
    if not isinstance(raw, dict):
        return raw
    out = {}
    for k, v in raw.items():
        if k == "marked_screenshot" or "b64" in str(k).lower() \
                or (isinstance(v, dict) and "b64" in v):
            continue
        if k == "marks" and isinstance(v, list):
            v = [{f: m.get(f) for f in ("id", "role", "name", "disabled")}
                 for m in v if isinstance(m, dict)]
        out[k] = v
    return out


def _wb_after_change(item, queue) -> bool:
    """S3: True when this turn's plan changed files before this step: an earlier step that ran
    a change tool (a direct tool step or a node's call log, outside evidence), or a step it
    depends on whose goal is WRITE class. Never raises; False with no queue."""
    try:
        from backend.agent.node_executor import _CHANGE_TOOLS
        from backend.agent.tool_choice_action_class import WRITE, required_classes

        deps = set(getattr(item, "depends_on", None) or [])
        for other in getattr(queue, "items", None) or []:
            if other is item:
                continue
            if getattr(other, "result", None):
                if getattr(other, "tool", None) in _CHANGE_TOOLS:
                    return True
                if any(c.get("tool") in _CHANGE_TOOLS and c.get("ok", True)
                       for c in (getattr(other, "node_call_log", None) or []) if isinstance(c, dict)):
                    return True
            if getattr(other, "step_id", None) in deps and WRITE in (
                    required_classes(str(getattr(other, "description", "") or "")) or ()):
                return True
    except Exception as exc:  # noqa: BLE001 - counted by the log; the entry rule decides without it
        logger.warning("[workbench] after-change probe failed: %r", exc)
    return False


def _wb_seed(conversation_id: str, workdir: str, task: str, goal: str,
             prior: list, memory: str) -> bool:
    """What ENTERS the workbench (design "Enter/leave policy"): task, goal,
    steps (full results of finished steps), memory - through the policy - and
    `files` (D3: the folder's relative file paths, bounded; [] with no folder)."""
    try:
        from backend.agent.workbench.ground import ground_files
        from backend.agent.workbench.manager import get_manager
        from backend.agent.workbench.policy import admit_put

        client = get_manager().workbench_for(conversation_id, workdir)
        if client is None:
            return False
        for name, value in (("task", task), ("goal", goal), ("steps", list(prior or [])),
                            ("memory", memory or ""),
                            ("files", ground_files(workdir) if workdir else [])):
            # admit_put returns (True, "ok") or (False, reason): the VALUE is `value`. The old
            # code put the second item, so every seeded name read the text "ok" (Round 4 W3).
            if admit_put(name, value)[0]:
                client.put(name, value)
        return True
    except Exception as exc:  # noqa: BLE001 - counted; the node falls back
        _wb_stats["seed_failed"] += 1
        logger.warning("[workbench] conv=%s seed failed: %r", conversation_id, exc)
        return False


def _wb_ground_chars(window: int) -> int:
    """R2 (Round 5): the code node's ground budget in chars: 1,200 at a window of 8,192 or
    less (or unknown), rising linearly to 4,000 at 32,768 or more."""
    if not window or window <= 8192:
        return 1200
    if window >= 32768:
        return 4000
    return 1200 + (window - 8192) * (4000 - 1200) // (32768 - 8192)


def _wb_ground_text(workdir: str, text: str = "", profile: bool = False,
                    max_chars: int = 1200) -> str:
    """D3: the PROJECT FILES text of a folder ("" for none). The one place outside the
    workbench package that reaches `ground` - the code node and the planner (kernel/planning.py)
    both call it, so the package keeps its allowed importers (registration contract).
    The planner keeps profile=False, 1,200 chars; the code node asks for R2's profile."""
    if not workdir:
        return ""
    from backend.agent.workbench.ground import ground

    return ground(workdir, text=text, profile=profile, max_chars=max_chars)


# Round 6 fix (b): the browser analogue of PROJECT FILES. When the conversation ALREADY
# has an open page (a prior step opened it), read that page ONCE at node entry and put its
# shape in the code node's first message, so the script does not spend runs exploring it.
# It NEVER issues browser_open: a needs-sight re-run must reuse the same page (pinned by
# test_workbench_browser_behavior.py). No open page -> no ground, no dispatch, no change.
_WB_BROWSER_GROUND_HEAD = (
    "BROWSER PAGE (already open; its shape is below - do not re-open it, parse the "
    "text/links in your script):"
)
_WB_BROWSER_GROUND_MAX = 2000


def _wb_browser_ground(conversation_id: str, execute, max_chars: int = _WB_BROWSER_GROUND_MAX) -> str:
    """The already-open page's title, url, links and text head, read through the node's
    own dispatch (`execute`, which holds the browser claim). "" when no page is open,
    the read fails, or anything raises - the node then runs with no browser ground."""
    try:
        from backend.agent.tools import browser_tools

        if not browser_tools.has_open_page(conversation_id):
            return ""
        res = execute("browser_read", {})
        if not isinstance(res, dict) or res.get("success") is False:
            return ""
        text = str(res.get("text") or res.get("content") or "")
        title = str(res.get("title") or "")
        page_url = str(res.get("url") or "")
        lines = [_WB_BROWSER_GROUND_HEAD, f"url: {page_url}", f"title: {title}"]
        links = res.get("links") or []
        if isinstance(links, (list, tuple)):
            lines.append("links (href | label):")
            for link in links[:40]:
                if isinstance(link, (list, tuple)) and len(link) >= 2:
                    lines.append(f"  {str(link[0])[:160]} | {str(link[1])[:80]}")
                else:
                    lines.append(f"  {str(link)[:200]}")
        lines.append("page text (head):")
        lines.append(text)
        out = "\n".join(lines)
        return out[:max_chars] if max_chars > 0 else out
    except Exception as exc:  # noqa: BLE001 - a ground never blocks the node
        logger.warning(f"[workbench] browser ground skipped: {exc!r}")
        return ""


# Round 6 PROTOTYPE (2026-11-18, IRIS_WB_PAGE_SEED): fetch the task's page on a
# side lane while the planner call runs, then seed its text into the worker at
# node entry. Flag-gated: off = no fetch, no seed, no behaviour change. This is a
# prototype to measure scripts/node; the manifest that tells the model the text
# is in the worker is deliberately NOT wired yet.
_PAGE_SEED: dict = {}          # conv -> {"done": Event, "pages": list, "urls": tuple}
_PAGE_SEED_LOCK = threading.Lock()
_PAGE_SEED_MAX_URLS = 3
# Round 6 (2026-11-20): raised from 8.0 to 30.0 to match the seed fetch's own
# timeout. At 8s, a fetch taking 8-30s was abandoned by collect (0 pages), so the
# code node's gather had to do browser_open INLINE (~19.5s) - measured in g03
# (67.6s reply). Waiting up to 30s captures the slow fetch that already started
# during planning, keeping it OFF the reply's critical path. A fetch that truly
# times out at 30s costs the same as the old 8s wait + 19.5s inline retry.
_PAGE_SEED_WAIT_S = 30.0


def _page_seed_on() -> bool:
    # The blind pair writes compute without seeing gather's result. Seeding the
    # page text into the PROMPT makes the pair's compute phase informed while
    # keeping it ONE model call (the bar needs calls <= 0.7x off).
    return os.environ.get("IRIS_WB_PAGE_SEED") == "1" or _two_call_on()


def page_seed_start(conversation_id: str, text: str) -> None:
    """Start the side-lane page fetch for this conversation. Idempotent: a fetch
    already running or done is not restarted. No-op unless the flag is on and the
    task names a URL. Never raises - planning never waits on this."""
    if not _page_seed_on() or not conversation_id:
        return
    try:
        from urllib.parse import urljoin

        from backend.agent.external_reference import _URL_RE

        # The shared regex keeps trailing prose punctuation (a URL before a
        # comma becomes "https://host,"). Strip it so browser_open gets a real URL.
        raw = (_u.rstrip(".,;:!?)'\"") for _u in _URL_RE.findall(text or ""))
        absolute = [u for u in dict.fromkeys(raw) if "://" in u]
        if not absolute:
            return
        base = absolute[0]
        # A task often names the site root plus the real target as a relative
        # path (/page/1/) or a "page N" phrase. Resolve those against the base
        # so the seed fetches the page that holds the data, not the homepage.
        import re as _re

        # Resolve ONLY paths the task actually names. Never guess a path from a
        # "page N" phrase - that encodes one site's URL shape and is wrong on
        # others. If the task names no path, seed the base URL it did name; the
        # model uses browser tools for any other page it needs.
        rel = _re.findall(r"/[\w./-]+/", text or "")
        candidates = [urljoin(base, p) for p in rel]
        # A bare host (scheme://host, no path) needs a trailing slash: many
        # servers redirect the slashless form to a stub. Standard HTTP behavior.
        if not candidates and base.count("/") == 2:
            base = base + "/"
        urls = tuple(dict.fromkeys(candidates or [base]))[:_PAGE_SEED_MAX_URLS]
    except Exception:  # noqa: BLE001 - a seed never blocks planning
        return
    if not urls:
        return
    with _PAGE_SEED_LOCK:
        if conversation_id in _PAGE_SEED:
            return
        # Round 6 (2026-11-20): hold the pooled Chromium warm for the whole
        # seed->collect window. The browser code-node path never declared a
        # browser run (the crawler does, orchestrator.py:454), so the pool's idle
        # watchdog could stop Chromium mid-planning and the seed's browser_open
        # cold-started it (~19.5s, 9/49 timeouts). Declaring here keeps the pool
        # warm; page_seed_collect releases it. Best-effort, never raises.
        try:
            from backend.vision import browser_pool as _bp

            _bp.declare_browser_run()
        except Exception:  # noqa: BLE001 - warmth is best-effort
            pass
        state = {"done": threading.Event(), "pages": [], "urls": urls}
        _PAGE_SEED[conversation_id] = state

    def _work():
        try:
            from backend.agent.tools import browser_tools
            from backend.agent.tool_decision import ToolDecisionBox

            _run_async = ToolDecisionBox._run_async
            for url in urls:
                # Round 6 (2026-11-20): bounded retry. A single browser_open
                # timeout used to abandon the URL (9/49 seeds failed), forcing
                # the code node to fetch inline (~19.5s) on the reply's critical
                # path. Retry once with a fresh session (a wedged session is the
                # usual cause of a transient timeout). Both attempts stay in the
                # side lane, off the reply clock.
                for attempt in range(2):
                    try:
                        if attempt == 1:
                            # Drop the possibly-wedged session so the retry opens
                            # a fresh browser context rather than reusing a dead one.
                            try:
                                _run_async(browser_tools.close_conversation_browser(conversation_id),
                                           timeout_s=10)
                            except Exception:  # noqa: BLE001 - best effort
                                pass
                        opened = _run_async(browser_tools.browser_open(conversation_id, url), timeout_s=30)
                        if not isinstance(opened, dict) or opened.get("success") is False:
                            continue
                        read = _run_async(browser_tools.browser_read(conversation_id), timeout_s=30)
                        if isinstance(read, dict) and read.get("success") is not False:
                            state["pages"].append({
                                "url": url,
                                "text": str(read.get("text") or read.get("content") or ""),
                            })
                            break  # success: no retry for this URL
                    except Exception as exc:  # noqa: BLE001 - retry once, then move on
                        logger.warning("[page-seed] conv=%s url=%s attempt=%d failed: %r",
                                       conversation_id, url, attempt, exc)
        except Exception as exc:  # noqa: BLE001 - a seed never blocks the turn
            logger.warning("[page-seed] conv=%s setup failed: %r", conversation_id, exc)
        finally:
            logger.info("[page-seed] conv=%s done: %d pages, chars=%s", conversation_id,
                        len(state["pages"]), [len(p["text"]) for p in state["pages"]])
            state["done"].set()

    threading.Thread(target=_work, daemon=True, name="page-seed").start()


def page_seed_collect(conversation_id: str, timeout_s: float = _PAGE_SEED_WAIT_S) -> list:
    """Return the pages fetched for this conversation, waiting at most timeout_s
    for the side lane. Empty when the flag is off, no fetch ran, or it did not
    finish in time. The slot is removed after collection."""
    if not _page_seed_on() or not conversation_id:
        return []
    with _PAGE_SEED_LOCK:
        state = _PAGE_SEED.pop(conversation_id, None)
    if state is None:
        return []
    try:
        state["done"].wait(timeout_s)
        return list(state["pages"])
    finally:
        # Release the warmth hold taken in page_seed_start. The code node reuses
        # this session, and the pool's idle TTL (180s) keeps it alive through the
        # node; releasing here avoids leaking a permanent hold.
        try:
            from backend.vision import browser_pool as _bp

            _bp.release_browser_run()
        except Exception:  # noqa: BLE001 - warmth is best-effort
            pass


def _wb_page_digest(pages: list, max_chars: int = 2400, sample: int = 500) -> str:
    """A MINIMAL, prompt-visible digest of the seeded page text. The tool model
    cannot read the worker namespace from its prompt, so without any sample it
    spends scripts printing the page. Showing only the SHAPE (a short sample of
    each page) is enough to write the parse; the FULL text stays in the worker
    variable `page_text` for the script to process. Kept small so it does not
    inflate prompt tokens - the bar penalizes prompt tokens."""
    if not pages:
        return ""
    parts = ["PAGE DATA: `page_text` in the worker is a list of {url, text}; the FULL "
             "text of each page is there. A short sample of each follows so you can "
             "see its structure - parse the FULL `page_text[n]['text']` in your script:"]
    used = len(parts[0])
    for i, p in enumerate(pages[:_PAGE_SEED_MAX_URLS]):
        url = str(p.get("url") or "")
        text = " ".join(str(p.get("text") or "").split())
        head = text[:sample]
        block = f"\n- page_text[{i}] {url} ({len(text)} chars): {head}"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts)


def _wb_seed_pages(conversation_id: str, workdir: str, pages: list) -> bool:
    """Put the side-lane page text into the worker under `page_text` through the
    same policy path as _wb_seed. True when at least one page was admitted."""
    if not pages:
        return False
    try:
        from backend.agent.workbench.manager import get_manager
        from backend.agent.workbench.policy import admit_put

        client = get_manager().workbench_for(conversation_id, workdir)
        if client is None:
            return False
        if not admit_put("page_text", pages)[0]:
            return False
        client.put("page_text", pages)
        return True
    except Exception as exc:  # noqa: BLE001 - counted; the node runs without the seed
        _wb_stats["seed_failed"] += 1
        logger.warning("[workbench] conv=%s page seed failed: %r", conversation_id, exc)
        return False


def _wb_brief(item, contract: dict = None) -> tuple:
    """(brief text, check) from the planner's step fields (Round 3 R2); ("", "")
    for a step planned without them - it still runs (closes by STATUS).

    Round 6 (goal contract as north star): when the page-seed flag is on, prepend
    the turn's required facts, the agent-discovered ceiling, and the live open
    facts so the tool model works toward the SAME contract the Brain and the
    harness use. Flag-gated: off = byte-identical brief.
    """
    check = str(getattr(item, "check", "") or "").strip()
    parts = []
    if _page_seed_on():
        _facts = list(getattr(getattr(item, "node_record", None), "required_facts", None) or [])
        if _facts:
            _lines = "\n".join(f"  - {str(f)[:160]}" for f in _facts[:8])
            parts.append("REQUIRED FACTS (the goal contract - the answer must cover these):\n" + _lines)
        # Live contract state from the kernel: ceiling (agent discoveries) and
        # open facts (required but not yet covered). Both are advisory context,
        # never a new floor - the floor stays immutable to the agent.
        if contract:
            _ceil = list(contract.get("ceiling") or ())
            if _ceil:
                _lines = "\n".join(f"  - {str(f)[:160]}" for f in _ceil[:6])
                parts.append("DISCOVERED FACTS (ceiling - useful, not required):\n" + _lines)
            _open = list(contract.get("open") or ())
            if _open:
                _lines = "\n".join(f"  - {str(f)[:160]}" for f in _open[:6])
                parts.append("STILL OPEN (required facts not yet covered):\n" + _lines)
    for label, key in (("inputs", "inputs"), ("outputs", "outputs"),
                       ("approach", "approach"), ("tools", "tools")):
        val = getattr(item, key, None)
        if not val:
            continue
        if isinstance(val, (list, tuple)):
            val = "\n".join(f"  - {v if isinstance(v, str) else json.dumps(v)}" for v in val)
            parts.append(f"{label}:\n{val}")
        else:
            parts.append(f"{label}: {val}")
    if check:
        parts.append(f"check (run by the harness after each run): {check}")
    return ("\n".join(parts)[:2400], check)


def _wb_output_names(item) -> tuple:
    """The brief's output variable names: each planner `outputs` entry is "name" or
    "name: type"; the name is the part before ":", a valid identifier, at most 8."""
    names = []
    for entry in getattr(item, "outputs", None) or ():
        name = str(entry).split(":", 1)[0].strip() if isinstance(entry, str) else ""
        if name.isidentifier() and name not in names:
            names.append(name)
    return tuple(names[:8])


def _wb_repair_tracker(kernel, session: str):
    """T7.15: the node's repair_route shadow tracker (rows for the failed checks), with the
    kernel's ledger sink installed. None if it cannot be built - the node never needs it."""
    try:
        from backend.agent import repair_route_shadow as _rr
        from backend.agent.ontology_recall import resolve_mycelium_conn

        sink = getattr(kernel, "_shadow_row_sink", None)
        if callable(sink):
            _rr.set_row_sink(sink)
        return _rr.RepairTracker(
            thread_id=session,
            conn=resolve_mycelium_conn(getattr(kernel, "_memory_interface", None)))
    except Exception as exc:  # noqa: BLE001 - a shadow never blocks a node
        logger.warning("[workbench] conv=%s repair_route tracker unavailable: %r",
                       getattr(kernel, "conversation_id", ""), exc)
        return None


def _wb_escalate(kernel, conversation_id: str, workdir: str, brief: str, check: str,
                 tracker=None, ground: str = ""):
    """R4: on the second failed check, ONE Brain call writes a repair brief with a
    skeleton; the skeleton is put into the namespace as `skeleton` AND shown in the note.
    `tracker` (T7.15) is told when a brief is going to the next attempt - it only labels
    the shadow rows. `ground` (D3) = the PROJECT FILES text the repair prompt carries.
    D1: a "low" reasoning budget (as the planner) and call_kind "wb_repair"."""
    def _hook(attempt: int, code: str, digest: str):
        import re as _re

        prompt = _WB_REPAIR_PROMPT.format(ground=ground or "", brief=brief or "(none)", check=check,
                                          code=(code or "")[:3000], digest=(digest or "")[:3000])
        text, _think, _ = kernel._router.generate(
            # 4096 like the planner: with 1200 the provider's hidden reasoning cut the
            # answer and the transport resent with a larger budget - TG-7 v2 stage 1
            # measured 17 sends for 5 repair calls, median 52.7 s (2026-11-16).
            "reasoning", [{"role": "user", "content": prompt}], max_tokens=_WB_REPAIR_MAX_TOKENS,
            temperature=0.2, timeout_s=120.0, reasoning_effort="low", call_kind="wb_repair")
        _wb_stats["escalations"] = _wb_stats.get("escalations", 0) + 1
        m = _re.search(r"```python\n(.*?)```", text or "", _re.S)
        skeleton = "\n".join((m.group(1) if m else "").splitlines()[:_WB_SKELETON_MAX_LINES])
        note = _re.sub(r"```python\n.*?```", "", text or "", flags=_re.S).strip()[:1200]
        in_namespace = False
        if skeleton:
            try:
                from backend.agent.workbench.manager import get_manager

                client = get_manager().workbench_for(conversation_id, workdir)
                if client is not None:
                    client.put("skeleton", skeleton)
                    in_namespace = True
            except Exception as exc:  # noqa: BLE001 - the note still goes, logged
                logger.warning("[workbench] conv=%s skeleton put failed: %r", conversation_id, exc)
        logger.info("[workbench] conv=%s escalated to the Brain after %d failed checks",
                    conversation_id, attempt)
        if not (note or skeleton):
            return None
        if tracker is not None:
            tracker.briefed()
        out = "REPAIR BRIEF (from the planner):\n" + note
        if skeleton:   # D1: the tool model SEES the script, not only a variable name
            out += ("\n\nStarting script (also in the variable `skeleton`; run `exec(skeleton)` "
                    "as it is, or send a corrected version):\n" if in_namespace else
                    "\n\nStarting script (run it as it is, or send a corrected version):\n") + skeleton
        return out
    return _hook


def _wb_tool_lines(tools: list, allowed) -> str:
    """<= 5 one-line signatures `name(required, optional=)` of the tools a script may call."""
    by_name = {}
    for t in tools or []:
        fn = t.get("function") or {}
        if fn.get("name") in allowed:
            by_name[fn["name"]] = fn
    order = [n for n in _WB_TOOLS_PREFER if n in by_name]
    order += [n for n in by_name if n not in order]
    lines = []
    for n in order[:_WB_TOOLS_MAX]:
        schema = by_name[n].get("parameters") or {}
        req = list(schema.get("required") or [])
        opt = [k for k in (schema.get("properties") or {}) if k not in req][:3]
        lines.append(f"tools.{n}({', '.join(req + [o + '=' for o in opt])})"[:100])
    return "; ".join(lines)


def _wb_slim_run_python(tools: list) -> list:
    """D6: the run_python schema a code node's model sees: `code` and `purpose` only and a
    one-sentence description. The full schema (timeout_s, fresh, close, a long description)
    cost ~250 tokens of an 8k window for options the harness does not need to offer."""
    for t in tools or []:
        fn = t.get("function") or {}
        if fn.get("name") == "run_python":
            props = (fn.get("parameters") or {}).get("properties") or {}
            slim = {k: props.get(k) or {"type": "string"} for k in ("code", "purpose")}
            return [{**t, "function": {
                **fn,
                "description": "Run Python in this conversation's persistent namespace; "
                               "variables stay between calls.",
                "parameters": {"type": "object", "properties": slim, "required": ["code"]},
            }}]
    return []


def _wb_slim_run_python_pair(tools: list) -> list:
    """Round 6 option 3: the run_python_pair schema - two code fields (gather,
    compute) in ONE tool call. The model must supply both phases in one response."""
    for t in tools or []:
        fn = t.get("function") or {}
        if fn.get("name") == "run_python":
            return [{**t, "function": {
                "name": "run_python_pair",
                "description": (
                    "Run TWO Python phases in ONE call in this conversation's persistent "
                    "namespace. `gather` loads data into variables (no check); `compute` "
                    "then uses those variables to assign every output and is checked. "
                    "Both run in order in the same namespace."),
                "parameters": {"type": "object",
                               "properties": {
                                   "gather": {"type": "string", "description": "Code that loads the data into variables."},
                                   "compute": {"type": "string", "description": "Code that assigns every output from those variables."},
                                   "purpose": {"type": "string"}},
                               "required": ["gather", "compute"]},
            }}]
    return []


def _wb_needed_tools(item, allowed) -> frozenset:
    """D6: the tools the brief names that a Python script cannot replace (not a reader or
    `run_command`) and that the node's menu offers. Empty = no `tools.<name>` note."""
    named = {str(n).strip() for n in (getattr(item, "tools", None) or ()) if isinstance(n, str)}
    return frozenset(n for n in named if n in allowed and n not in _WB_PY_REPLACES)


def _wb_callback_handler(execute, allowed, calls: list, count, *, browser: bool = False,
                         wall_s: Optional[float] = None, on_browser_act=None) -> Callable:
    """handler(tool, args) -> (ok, value, error) for the Workbench `call` frames. It is the
    node's OWN dispatch (`execute`: turn-live check, domain guard, claims, hooks,
    box.dispatch), not a second path. Only tools in `allowed` (the node's mode menu) run.
    Each callback adds one entry to `calls` (via run_python) and counts once as a real
    tool call (`count`).

    Round 6: `.close()` latches it (the node's finally, BEFORE its claims are released): an
    ended node cannot stop its script, so after the latch - or after `wall_s` seconds (the
    browser wall budget) - it answers "the step ended" and dispatches nothing. Browser tools
    run only for a `browser` node, at most 12 per run_python (`.new_exec()` starts the count
    again). The result a script gets has no picture and trimmed marks. After each browser_act
    on an element, `on_browser_act(args, ok, page_text, history)` gets the observation the
    script last saw. `.sight_poor()` = the last observation had too few marks to script."""
    from backend.agent.node_executor import _ID_KEYS, _failed, _output_excerpt, _target

    state = {"closed": False, "n_browser": 0, "obs": "", "marks_n": None, "hist": []}
    deadline = None if wall_s is None else time.monotonic() + wall_s

    def _handler(tool: str, args: dict):
        if state["closed"] or (deadline is not None and time.monotonic() >= deadline):
            return False, None, _WB_ENDED
        if tool in _WB_BROWSER_TOOLS and not browser:
            return False, None, f"{tool}: not available in this step"
        if tool not in allowed or not isinstance(args, dict):
            return False, None, f"{tool}: not available"
        if tool == "recall_memory" and str(args.get("expand") or "").startswith("wb:"):
            return False, None, "read a workbench variable directly; it is in the namespace"
        if tool in _WB_BROWSER_TOOLS:
            if state["n_browser"] >= _WB_BROWSER_CALLS_MAX:
                return False, None, (f"at most {_WB_BROWSER_CALLS_MAX} browser calls per run_python; "
                                     "finish with what you have")
            state["n_browser"] += 1
        try:
            raw = execute(tool, dict(args))
        except Exception as exc:  # noqa: BLE001 - the script sees a ToolError
            raw = {"success": False, "error": f"{type(exc).__name__}: {exc}", "error_type": "exception"}
        failed = _failed(raw)
        calls.append({"tool": tool, "target": _target(args), "ok": not failed, "ok_call": not failed,
                      "out": _output_excerpt(raw), "via": "run_python",
                      "args": {k: args[k] for k in _ID_KEYS if args.get(k)}})
        try:
            count()
        except Exception as exc:  # noqa: BLE001 - bookkeeping never fails a call
            logger.debug("[workbench] callback count failed: %r", exc)
        if tool in _WB_BROWSER_TOOLS:
            # C4: the Oracle's question is asked on the observation the script saw BEFORE this act
            if tool == "browser_act" and args.get("element_id") is not None and on_browser_act:
                try:
                    on_browser_act(dict(args), not failed, state["obs"], "; ".join(state["hist"][-6:]))
                except Exception as exc:  # noqa: BLE001 - a shadow never blocks a call
                    logger.debug("[workbench] browser_next row failed: %r", exc)
            state["hist"].append(" ".join(f"{tool} {args.get('action') or ''} "
                                          f"{args.get('element_id') or ''}".split())
                                 + (" -> FAILED" if failed else " -> ok"))
            del state["hist"][:-12]
            if not failed and isinstance(raw, dict):
                if isinstance(raw.get("marks"), list):
                    state["marks_n"] = len(raw["marks"])
                if _WB_OBS_MARK in str(raw.get("content") or ""):
                    state["obs"] = str(raw["content"])
        if failed:
            err = raw.get("error") if isinstance(raw, dict) else raw
            return False, None, str(err or f"{tool} failed")[:2000]
        value = _wb_script_view(raw if isinstance(raw, dict) else {"result": raw})
        return True, value, None

    def _close() -> None:
        state["closed"] = True
        _handler.closed = True

    def _new_exec() -> None:
        state["n_browser"] = 0

    def _sight_poor() -> bool:
        return state["marks_n"] is not None and state["marks_n"] <= _WB_POOR_MARKS

    _handler.closed = False
    _handler.close = _close
    _handler.new_exec = _new_exec
    _handler.sight_poor = _sight_poor
    return _handler


def _wb_needs_fallback(result, sight_poor: bool = False) -> str:
    """CLM-11 AC4: why a code node re-runs on the fine-grained path ('' = it
    does not): the workbench was unavailable, the sandbox refused, the check did not pass and
    the page needs sight (Round 6 C7: the script raised ToolError('needs sight'), or the last
    observation had too few marks - `sight_poor`), or two run_python calls in a row failed with
    the same exception type."""
    outs = [(bool(c.get("ok")), str(c.get("out") or ""))
            for c in (getattr(result, "calls", None) or [])
            if c.get("tool") in ("run_python", "run_python_pair")]
    if any("workbench_unavailable" in o or "WorkbenchUnavailable" in o for _ok, o in outs):
        return "unavailable"
    if any("PermissionError" in o and "workbench" in o.lower() for ok, o in outs if not ok):
        return "sandbox_refused"
    if getattr(result, "check_passed", False) is not True and (
            sight_poor or any("ToolError" in o and "needs sight" in o.lower() for ok, o in outs if not ok)):
        return "needs_sight"
    kinds = [o.split(":", 1)[0].strip() for ok, o in outs if not ok]
    fails = [ok for ok, _o in outs]
    if len(fails) >= 2 and not fails[-1] and not fails[-2] and len(kinds) >= 2 \
            and kinds[-1] == kinds[-2]:
        return f"twice {kinds[-1] or 'error'}"
    if not outs and not getattr(result, "success", False):
        return "no_execution"
    return ""


def _clm_node_hooks(kernel, item, turn_id, role: str = "tool_execution", session: str = "",
                    goal: str = "") -> dict:
    """record_result / ref_readable / on_clm_event / window for one node."""
    from backend import conversation_store as _cs
    from backend.agent.kernel.base import _emit_event
    from backend.agent.node_executor import _target

    conv = getattr(kernel, "conversation_id", "") or ""
    step = str(getattr(item, "step_id", "") or "")
    read_tools = set(getattr(kernel, "_DER_READ_TOOLS", ()) or ())

    def record_result(name, params, text, call_ord):
        if name in read_tools or name in _CLM_NO_RECORD or len(text or "") <= _CLM_KEEP_CHARS:
            return ""
        rid = _cs.new_tool_result_id()
        ok = _cs.add_tool_result(rid, conv, turn_id or "", step, int(call_ord), name,
                                 _target(params or {}), text)
        return rid if ok else ""

    def ref_readable(rid):
        row = _cs.get_tool_result(rid, wait_s=2.0)
        return bool(row) and not row.get("cut")

    def on_clm_event(label, payload):
        _emit_event(kernel, label, payload=dict(payload, step=step, turn=turn_id or ""))
        _clm_measure(conv, label, payload)

    def write_pin(summary, refs):
        from backend.agent.ontology_recall import resolve_mycelium_conn
        from backend.memory.pin_store import PinStore
        from backend.utils.durability_queue import lane

        conn = resolve_mycelium_conn(getattr(kernel, "_memory_interface", None))
        if conn is None:
            return ""
        store = PinStore(conn=conn)
        pid = store.add(title="model note: " + " ".join(summary.split())[:60],
                        content=summary, pin_type="model_summary",
                        tags=["model_summary", "author:model", "clm", f"conv:{conv}"])

        def _links():
            for ref in refs:
                kind, _, rid = str(ref).partition(":")
                store.link(pid, rid, relationship="derives_from",
                           source_type="pin", target_type=kind)

        # the links off the node thread (finalize.py precedent: a link write
        # waited inline on "database is locked")
        if not lane("memory_events").submit("clm_pin_links", _links):
            logger.warning("[clm] conv=%s pin %s links refused by the lane", conv, pid)
        return pid

    try:
        window = int(kernel.resolve_context_window_with_source(role).tokens)
    except Exception as exc:  # noqa: BLE001 - no window = no in-node shrink, logged
        logger.warning("[clm] conv=%s window for %s unknown (%r): in-node shrink off", conv, role, exc)
        window = 0
    landmarks = _clm_landmark_header(kernel, goal)
    if landmarks:
        from backend.agent.inference import clm_baseline as _cb

        _cb.record_event(conv, "landmark_header", n=len(landmarks),
                         stale=sum(1 for s in landmarks if "(stale:" in s))
    return {"record_result": record_result, "ref_readable": ref_readable,
            "on_clm_event": on_clm_event, "window": window, "write_pin": write_pin,
            "dead_ends": _clm_dead_ends(kernel, session, turn_id),
            "landmarks": landmarks}


from backend.agent.kernel.planning import (
    _voice_turn_note,
)


def _node_claim_of(tool: str) -> Optional[str]:
    for _claim, _tools in _NODE_CLAIMS.items():
        if tool in _tools:
            return _claim
    return None

def _node_call_parallel_ok(name: str, params: dict) -> bool:
    """A node call may run side by side with its siblings: no side effect (the
    permission tier, the one authority on that) and no exclusive resource
    (browser page / screen - two calls of one node would wait on its own claim)."""
    from backend.agent.permissions import PermissionTier, classify_tool

    return (_node_claim_of(name) is None
            and classify_tool(name, params) == PermissionTier.READ_ONLY)

def _der_node_load() -> float:
    """Load of the node domain: the share of the node provider's learned rate
    ceiling in use (the router's own rate meter). Never live Sigma (CT-3/4)."""
    _q = _DER_NODE_QUOTA.get("quota")
    if not _q:
        return 0.0
    from backend.agent.phase_manager import get_registry

    return get_registry()._load_fraction(_q)

def _der_node_domain():
    """The ONE phase domain for DER node starts ("execution.der_nodes"): the
    same black box as the Oracle's. It decides WHEN a ready node starts; the
    DAG decided that it is ready. Fail-open: an error starts the node."""
    from backend.agent.phase_domain import get_phase_domain

    return get_phase_domain(
        "execution.der_nodes",
        # A node runs seconds; its first model call is the burst to spread.
        period_s=0.5, max_wait_s=0.5, k=0.6, load_fn=_der_node_load,
    )

_NODE_CORE_TOOLS = frozenset({
    "read_file", "edit_file", "write_file", "run_command",
    "list_directory", "glob_files", "grep_files",
})

def _narrow_node_tools(tools, goal, engine=None, k=None):
    """Advisory narrowing: keep the CORE coding tools + the Oracle's top picks.

    MEASURED 2026-11-06: a node's menu was 17 tools (~14k chars of JSON) on
    every model call, and most calls only need the basic coding tools. The
    Oracle already ranks the same menu for tool_choice. Keeping the core tools
    plus its top picks cuts the payload without removing basic capability.

    Falls back to the FULL list whenever the engine is unavailable or any step
    fails - a narrowing never removes capability it cannot justify. ``k`` (or
    IRIS_NODE_TOOL_MENU_K) <= 0 disables it.
    """
    try:
        if k is None:
            _k_env = os.environ.get("IRIS_NODE_TOOL_MENU_K", "")
            if not _k_env.strip():
                # With the class decision on, the Oracle narrows EVERY call on
                # the step's live state; this goal-only cut would only remove
                # tools for the whole step with no way back (live 2026-11-09:
                # it dropped screenshot_page from a web step). MEASURED
                # 2026-11-09 (c14, 3 runs each, same code): reply 64/26/42 s
                # with the cut, 35/29/64 s without; the cut saves ~21% prompt
                # tokens (median 2742 vs 3330) and costs one d1 call per step.
                # An explicit IRIS_NODE_TOOL_MENU_K still wins.
                from backend.agent.tool_choice_action_class import (
                    class_decision_enabled,
                )

                if class_decision_enabled():
                    return tools
            k = int(_k_env or 12)
        names = [
            t.get("function", {}).get("name") for t in (tools or [])
        ]
        names = [n for n in names if n]
        if k <= 0 or len(names) <= k:
            return tools
        keep = {n for n in names if n in _NODE_CORE_TOOLS}
        if engine is None:
            try:
                from backend.agent.decision_engine import get_decision_engine

                engine = get_decision_engine()
            except Exception:  # noqa: BLE001 - full menu stands
                engine = None
        ranked = []
        if engine is not None:
            ds = engine.decide(
                "tool_choice", names, {"goal": str(goal or "")[:400]}
            )
            if ds is not None and getattr(ds, "distribution", None):
                ranked = [
                    c.name for c in sorted(
                        ds.distribution, key=lambda c: -float(c.prob))
                ]
        if not ranked:
            # no Oracle ranking: never drop a tool for a reason we cannot state
            return tools
        for n in ranked:
            if len(keep) >= k:
                break
            if n in names:
                keep.add(n)
        kept = [t for t in tools if t.get("function", {}).get("name") in keep]
        if kept and len(kept) < len(tools):
            logger.info(
                "[DER] node tool menu narrowed %d -> %d (dropped=%s)",
                len(tools), len(kept), sorted(set(names) - keep),
            )
        return kept or tools
    except Exception as exc:  # noqa: BLE001 - narrowing never breaks a step
        logger.debug("[DER] tool menu narrowing skipped: %r", exc)
        return tools

def _der_start_node(self, item, run_step, inflight, finished, *, verdict, phase) -> None:
    """Start one node on its own thread (parallel nodes, owner 2026-10-04).

    The phase domain "execution.der_nodes" decides WHEN it starts (its
    position on the dial; fail-open). A direct step whose tool drives an
    exclusive resource (browser, screen) claims it for the whole step; a
    node claims lazily at its first such call (_der_run_node). The thread
    boxes (result, success) or the exception and posts the step id to
    ``finished``; the loop settles it with _der_post_step."""
    from backend.agent.resilience import retry_with_backoff_sync

    try:
        from backend.agent.inference.router import quota_key

        _DER_NODE_QUOTA["quota"] = quota_key(self._router.resolve("tool_execution"))
    except Exception:  # noqa: BLE001 - no quota = no load signal (0.0)
        pass
    box: dict = {}

    def _work() -> None:
        _dom = _der_node_domain()
        _tok = None
        _held: List[str] = []
        try:
            _tok = _dom.enter(f"node:{self.conversation_id or 'default'}")
            _claim = _node_claim_of(item.tool or "") if item.tool else None
            if _claim and _der_claim(self, _claim, item):
                _held.append(_claim)
            box["res"] = retry_with_backoff_sync(
                run_step, max_retries=2, base=1.0, cap=4.0,
                label=f"step_{item.step_number}:{item.tool}",
            )
        except BaseException as _step_exc:  # noqa: BLE001 - boxed, settled by the loop
            box["exc"] = _step_exc
        finally:
            for _c in _held:
                _der_release(self, _c)
            if _tok is not None:
                try:
                    _dom.exit(_tok)
                except Exception:  # noqa: BLE001
                    pass
            finished.put(item.step_id)

    _t = threading.Thread(target=_work, daemon=True, name=f"der-node-{item.step_id}")
    inflight[item.step_id] = {"item": item, "box": box, "verdict": verdict,
                              "phase": phase, "t0": time.perf_counter()}
    _t.start()
    logger.info("[DER] node start step=%s in_flight=%d", item.step_id, len(inflight))

def _der_take_finished(self, finished, inflight, block: bool = False,
                       timeout: Optional[float] = None):
    """The next finished node as (item, step_result, step_success, verdict,
    phase), or None (nothing finished / the wait ran out)."""
    import queue as _queue_mod

    try:
        _sid = finished.get(block=block, timeout=timeout if block else None)
    except _queue_mod.Empty:
        return None
    rec = inflight.pop(_sid, None)
    if rec is None:
        return None
    item, box = rec["item"], rec["box"]
    logger.info("[DER] node done step=%s in %.1fs (in_flight=%d)", _sid,
                time.perf_counter() - rec["t0"], len(inflight))
    if "exc" in box:
        _exc = box["exc"]
        # RateLimitedError carries structured context (provider id, retry
        # count) - preserve it verbatim for the ledger (REQ-3 AC4 / REQ-4
        # AC2). Do NOT stringify into a generic message.
        if isinstance(_exc, RateLimitedError):
            logger.warning(
                "[DER] Step %s rate-limited by provider %s after %d attempts "
                "â€” recording FAILED (no DER-layer retry)",
                item.step_number, _exc.provider_id, _exc.attempts,
            )
            return (item, f"RateLimitedError(provider={_exc.provider_id}, "
                          f"attempts={_exc.attempts}, retry_after={_exc.retry_after})",
                    False, rec["verdict"], rec["phase"])
        return item, str(_exc), False, rec["verdict"], rec["phase"]
    step_result, step_success = box.get("res", ("", False))
    return item, step_result, step_success, rec["verdict"], rec["phase"]

def _der_claim(self, claim: str, item) -> bool:
    """Wait for an exclusive resource (browser page / screen) while the
    node's turn is live. True = held (pair with _der_release)."""
    lock = _SCREEN_CLAIM if claim == "screen" else _der_claim_lock(self, claim)
    t0 = time.perf_counter()
    while not lock.acquire(timeout=0.5):
        if (getattr(self, "_der_stop_requested", False)
                or getattr(item, "_node_cancelled", "")):
            return False
    _w = time.perf_counter() - t0
    if _w >= 0.5:
        logger.info("[DER] node %s waited %.1fs for the %s", item.step_id, _w, claim)
    return True

def _der_release(self, claim: str) -> None:
    lock = _SCREEN_CLAIM if claim == "screen" else _der_claim_lock(self, claim)
    try:
        lock.release()
    except RuntimeError:  # not held - never raise from a finally
        pass

def _der_claim_lock(self, claim: str):
    """The lock of one exclusive resource of this conversation (its browser
    page) - keyed by conversation id at module level, so a stand-in kernel
    gets a real lock too."""
    _key = (str(getattr(self, "conversation_id", "") or ""), claim)
    with _CLAIM_LOCKS_GUARD:
        return _CLAIM_LOCKS.setdefault(_key, threading.Lock())


class DerNodeMixin:
    def _der_tool_deadline(self, tool: Optional[str]) -> float:
        """Session-318 T18 (REQ-11 AC11.1): per-family dispatch deadline in
        seconds. Gather covers the 90s crawler ceilings with margin;
        everything else takes the default. Constants-only tuning (REQ-12).
        Never raises.

        Session-331 (live T3): when a tool will WAIT for user consent, the
        approval window must NOT be charged against the execution budget â€” a
        gated call used to time out at 90s while the permission card's window
        is 120s, so the tool died before a human could approve it. The consent
        wait is not execution, so add the applicable permission window (plus a
        small margin) to the deadline whenever this call will actually gate.
        With Auto-approve ON (the default) nothing waits and the base deadline
        stands unchanged â€” the common path pays nothing.
        """
        try:
            from backend.agent.tool_envelope import tool_family as _tf
            from backend.agent.der_constants import (
                DEADLINE_CRAWL_S, DEADLINE_READ_S, DEADLINE_DEFAULT_S,
                DEADLINE_COMMAND_S, DEADLINE_BROWSER_S,
            )
            _fam = _tf(tool)
            # run_python: a script may run up to tool_bridge._WB_TIMEOUT_MAX_S (300 s)
            # and its clock PAUSES during tools.x() callbacks, so the "direct" default
            # (90 s) stopped waiting on a script that was still running (2026-11-16).
            if (tool or "").lower() in ("run_command", "run_python"):
                _base = max(float(DEADLINE_COMMAND_S), 1.0)
            elif (tool or "").lower().startswith("browser_"):
                _base = max(float(DEADLINE_BROWSER_S), 1.0)
            elif _fam == "gather":
                _base = max(float(DEADLINE_CRAWL_S), 1.0)
            elif _fam == "read":
                _base = max(float(DEADLINE_READ_S), 1.0)
            else:
                _base = max(float(DEADLINE_DEFAULT_S), 1.0)
            # Add the consent window only when this exact call will wait.
            try:
                from backend.agent.permissions import (
                    classify_tool,
                    get_auto_approve,
                    get_permission_action,
                    PERMISSION_TIMEOUT_SIDE_EFFECT,
                    PERMISSION_TIMEOUT_DESTRUCTIVE,
                )

                _tier = classify_tool(tool, None)
                _action = get_permission_action(
                    _tier, auto_approve=get_auto_approve()
                )
                if _action.value == "require_confirmation":
                    _base += float(PERMISSION_TIMEOUT_DESTRUCTIVE) + 15.0
                elif _action.value == "require_approval":
                    _base += float(PERMISSION_TIMEOUT_SIDE_EFFECT) + 15.0
            except Exception:
                pass  # permission read must never break the deadline
            # A new file with no folder chosen asks the user where to save it
            # (tool_bridge._folder_for_new_file): that wait is not execution.
            if (tool or "").lower() in ("write_file", "create_directory"):
                try:
                    from backend.agent.tools.ask_user_tool import ASK_USER_QUESTION_TIMEOUT

                    _base += float(ASK_USER_QUESTION_TIMEOUT) + 15.0
                except Exception:
                    pass
            return _base
        except Exception:
            return 90.0

    def _der_warm_vision_browser(self, _why: str = "") -> None:
        """AC9.6 (session-319): fire-and-forget warm of the pooled vision browser
        when a websearch is requested.

        WHY: the recovery lane is useless if the browser is cold. The pool stops
        the shared browser after ``_IDLE_TIMEOUT`` (180s, browser_pool.py:55) and
        the next vision use then pays a full cold start â€” the live log records
        ``[browser_session] browser acquired in 32918ms (cold pool)``. Boot-time
        warming (main.py:777) only covers the first search after a restart, so
        every later search went cold again. Starting the warm AT DISPATCH means
        the ~33s overlaps the 85-100s crawl instead of blocking recovery.

        Best-effort and non-blocking by design: the crawl must never wait on
        Chromium, and a machine without Playwright degrades on its own terms
        (browser_session.available() == False). Never raises.
        """
        try:
            from backend.vision.browser_pool import acquire_browser
        except Exception:
            return  # vision not installed â€” nothing to warm

        async def _warm() -> None:
            try:
                # Returns (browser, lease) â€” NOT a context manager. The lease
                # must be released on every path or the pool's idle watchdog
                # defers forever and the browser is never reclaimed.
                _browser, lease = await acquire_browser()
                try:
                    logger.debug("[DER] vision browser warmed (%s)", _why)
                finally:
                    lease.release()
            except Exception as _wexc:  # noqa: BLE001 â€” best effort by design
                logger.debug("[DER] vision browser warm skipped: %s", _wexc)

        try:
            import asyncio as _aio_warm
            _loop = getattr(self, "_broadcast_loop", None)
            if _loop is not None and not _loop.is_closed():
                _aio_warm.run_coroutine_threadsafe(_warm(), _loop)
                return
            # No captured loop (e.g. a sync test context): only safe to schedule
            # if THIS thread already owns a running loop.
            _aio_warm.get_running_loop().create_task(_warm())
        except Exception:
            pass  # no loop available â€” recovery simply pays the cold start

    @staticmethod
    def _der_evidence_cap(tool: Optional[str]) -> int:
        """Evidence window for a step result, by tool kind."""
        _t = (tool or "").lower()
        if _t in AgentKernel._DER_GATHER_TOOLS or _t in AgentKernel._DER_SEARCH_TOOLS:
            return 8000
        if _t in AgentKernel._DER_READ_TOOLS:
            return 8000
        # Execution audit B5: command and git output carried 400 chars into
        # later steps, so a test failure's traceback never reached the step
        # that had to fix it. The excerpt keeps head AND tail.
        if _t in AgentKernel._SHELL_RESULT_TOOLS or _t.startswith("git_"):
            return 8000
        return 400

    @staticmethod
    def _der_query_has_reference(query: str) -> bool:
        """Heuristic: does the search query contain an ambiguous reference that
        needs the conversation history to resolve?"""
        import re as _re

        _q = query or ""
        _ref_re = _re.compile(
            r"\b(it|its|they|them|those|that|this|the same|above|earlier|"
            r"previous|mentioned|same)\b",
            _re.IGNORECASE,
        )
        if _ref_re.search(_q):
            return True
        _ql = _q.lower()
        return any(
            _p in _ql
            for _p in (
                "pricing of", "price of", "cost of", "the pricing",
                "the price", "the cost", "do the", "the websearch",
                "the search", "what we",
            )
        )

    def _der_refine_query(self, query: str, _session: str) -> str:
        """
        Phase 2.2: resolve ambiguous references in a search query against the
        full conversation history via a quick LLM call. Returns the refined
        query, or the original on any failure / no change.
        """
        try:
            _history = []
            if self._conversation_memory is not None:
                _history = self._conversation_memory.get_context()
            if not _history:
                return query
            _history_str = "\n".join(
                f"{(m.get('role') or 'user').upper()}: {m.get('content') or ''}"
                for m in _history
            )
            _refine_prompt = (
                "CONVERSATION HISTORY (FULL):\n"
                f"{_history_str}\n\n"
                f"CURRENT QUERY: {query}\n\n"
                "Rewrite the search query to resolve any ambiguous pronouns or "
                "references based on the full conversation history. Output the "
                "query string only."
            )
            _refined = self.infer(
                _refine_prompt, role="reasoning", max_tokens=30, temperature=0.0
            )
            _out = (_refined.raw_text or "").strip().strip('"').strip()
            if _out and _out.lower() != query.lower():
                logger.info("[DER] refined query %r -> %r", query, _out)
                return _out
        except Exception as _e:
            logger.debug("[DER] query refinement failed: %s", _e)
        return query

    @staticmethod
    def _format_tool_result(raw) -> str:
        """Phase 4b: normalize a raw tool-bridge result into clean text for
        downstream consumption (dependent steps, working memory, final answer).

        - strings pass through unchanged
        - dicts: surface errors explicitly; otherwise extract the most useful
          content key (result/results/content/output/text/data/response);
          fall back to compact JSON for unrecognized dicts / lists
        - never raises; any failure falls back to str(raw)

        Note: the full structured result is still captured verbatim by
        _capture_tool_result (document store) â€” this only shapes the textual
        flow, so nothing is lost for later reformatting.
        """
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            try:
                if raw.get("success") is False:
                    _err = raw.get("error") or raw.get("message") or "unknown error"
                    return (
                        _err
                        if isinstance(_err, str)
                        else json.dumps(_err, ensure_ascii=False, default=str)
                    )
                for _key in (
                    "result", "results", "content", "output",
                    "text", "data", "response",
                ):
                    _val = raw.get(_key)
                    if _val is None:
                        continue
                    if isinstance(_val, str):
                        return _val
                    return json.dumps(_val, ensure_ascii=False, default=str)
                # Document envelopes (e.g. get_rendered_documents) carry no
                # content key â€” without this they fell to compact JSON and the
                # raw payload (success/conversation_id/documents) rendered
                # verbatim on task-card rows (live 2026-09-09). Summarize
                # human-side; full data stays in the document store.
                _docs = raw.get("documents")
                if isinstance(_docs, list):
                    _titles = [
                        d.get("title") or d.get("document_id") or ""
                        for d in _docs
                        if isinstance(d, dict)
                    ]
                    _titles = [t for t in _titles if t][:3]
                    _base = (
                        f"{len(_docs)} document(s) retrieved"
                    )
                    return (
                        f"{_base}: {', '.join(_titles)}"
                        if _titles
                        else _base
                    )
                # Conversation index (e.g. list_conversations) carries no
                # content key either â€” without this it fell to compact JSON
                # and the raw index rendered verbatim on task-card rows AND
                # entered working memory with no next-action pointer (live
                # conv-98: the planner read the index as retrieved content
                # and skipped the get_rendered_documents follow-up). The
                # result repeats the pointer the registry description already
                # gives, because the result is what survives into memory.
                _convs = raw.get("conversations")
                if isinstance(_convs, list):
                    _tops = [
                        f"{c.get('conversation_id')} "
                        f"({c.get('doc_count') or 0} docs)"
                        for c in _convs
                        if isinstance(c, dict) and c.get("conversation_id")
                    ][:3]
                    _cbase = (
                        f"{len(_convs)} conversation(s) with documents "
                        f"(index only — call get_rendered_documents("
                        f"conversation_id=...) to read one)"
                    )
                    return (
                        f"{_cbase}: {', '.join(_tops)}"
                        if _tops
                        else _cbase
                    )
                # `diff` (edit diffs) is for the chat, never for the model.
                return json.dumps(
                    {k: v for k, v in raw.items() if k != "diff"},
                    ensure_ascii=False, default=str,
                )
            except Exception:
                return str(raw)
        try:
            return json.dumps(raw, ensure_ascii=False, default=str)
        except Exception:
            return str(raw)

    @staticmethod
    def _format_tool_result_for_step(raw, tool=None) -> str:
        """Step-result shaping for the DER execution path (not card rows).

        Session-323: a rerouted READ (get_rendered_documents after a guard
        REPEAT block) delivers the same gathered bytes through the document
        store â€” but _format_tool_result reduces that envelope to a title
        line ("1 document(s) retrieved"), so the step result starves and
        synthesis honestly reports IDs-only (live B3-repeat). For read
        tools, keep the header line AND append a bounded content excerpt
        per doc (IDs + sources kept). All other tools delegate unchanged,
        so card snapshots and the pinned format contract never move.
        Never raises; falls back to _format_tool_result.
        """
        try:
            _t = (tool or "").lower()
            # Execution audit B4/B5 (2026-09-29): a shell result has no content
            # key, so it fell to compact JSON - output escaped inside a string,
            # exit code buried. Readable text with the exit code FIRST, so the
            # verifier and every later step can see whether the command failed.
            if _t in AgentKernel._SHELL_RESULT_TOOLS and isinstance(raw, dict) \
                    and ("returncode" in raw or "running" in raw or "stdout" in raw):
                _out = "\n".join(
                    s for s in (str(raw.get("stdout") or "").rstrip(),
                                str(raw.get("stderr") or "").rstrip()) if s
                )
                # A command still running (stalled or a server), or one that
                # was stopped / timed out, says so first - with its output.
                if raw.get("running"):
                    _head = f"[still running, handle {raw.get('handle')}] {raw.get('note') or ''}".rstrip()
                elif raw.get("returncode") is not None:
                    _head = f"[exit code {raw.get('returncode')}]"
                elif raw.get("success") is False:
                    _head = f"[{raw.get('error') or 'command failed'}]"
                else:
                    _head = f"[{raw.get('status') or 'done'}]"
                return f"{_head}\n{_out or '(no output)'}"
            if _t in AgentKernel._DER_READ_TOOLS and isinstance(raw, dict):
                _docs = raw.get("documents")
                if isinstance(_docs, list) and _docs:
                    _head = AgentKernel._format_tool_result(raw)
                    _parts = [_head]
                    for _d in _docs[:3]:
                        if not isinstance(_d, dict):
                            continue
                        _did = str(_d.get("document_id") or "")[:12]
                        _title = str(_d.get("title") or _did or "doc")
                        _content = _d.get("content") or ""
                        if not isinstance(_content, str):
                            try:
                                import json as _js323
                                _content = _js323.dumps(_content, ensure_ascii=False, default=str)
                            except Exception:
                                _content = str(_content)
                        if not _content.strip():
                            try:
                                _vars = _d.get("variants") or {}
                                if isinstance(_vars, dict):
                                    for _v in _vars.values():
                                        if isinstance(_v, str) and _v.strip():
                                            _content = _v
                                            break
                            except Exception:
                                pass
                        _srcs = _d.get("sources") or []
                        try:
                            _src_line = ""
                            if isinstance(_srcs, list) and _srcs:
                                _src_line = "sources: " + ", ".join(str(u) for u in _srcs[:5])
                            elif isinstance(_srcs, str) and _srcs.strip():
                                _src_line = "sources: " + _srcs.strip()[:400]
                        except Exception:
                            _src_line = ""
                        _excerpt = AgentKernel._smart_excerpt(_content, 2500) if _content.strip() else "(no stored text)"
                        _block = f"--- Doc {_title} [{_did}] ---\n{_excerpt}"
                        if _src_line:
                            _block += f"\n{_src_line}"
                        _parts.append(_block)
                    return "\n".join(_parts)
        except Exception:
            pass
        return AgentKernel._format_tool_result(raw)

    def _run_step_direct(self, item, context_package, session_id: str) -> str:
        """
        Execute a tool-less DER step via direct model inference.
        Returns the model's response text, or an error placeholder.
        Injects accumulated working memory (prior step findings) into the prompt.
        """
        try:
            cp_str = ""
            if context_package and hasattr(context_package, "get_system_zone_content"):
                try:
                    cp_str = context_package.get_system_zone_content() or ""
                except Exception:
                    pass

            # Working memory: include what earlier steps found this session.
            # Uses ContextManager.render() which applies compression at 80% threshold.
            wm_str = ""
            try:
                if self._memory_interface:
                    wm_str = (
                        self._memory_interface.get_assembled_context(session_id) or ""
                    )
            except Exception:
                pass
            # P1 (live conv-98): working memory enters this prompt unbounded â€”
            # a 15KB+ crawl dump emptied the provider here while the
            # compressed-record final synthesis on the same provider
            # succeeded. Bound with an explicit truncation marker (never a
            # silent amputation); prompts under the cap are byte-identical.
            if len(wm_str) > 6000:
                wm_str = self._smart_excerpt(wm_str, 6000)

            # Phase 1 (D1.6): inject the memory-coupled evidence block so the
            # acting prompt is conditioned on proven paths / failures / state.
            evidence_str = ""
            try:
                from backend.agent.evidence import assemble_evidence

                _mi = getattr(self, "_memory_interface", None)
                _myc = getattr(_mi, "_mycelium", None) if _mi is not None else None
                _task_class = getattr(self, "_der_task_class", "full") or "full"
                _completed = list(getattr(self, "_der_completed_tools", []) or [])
                evidence_str = assemble_evidence(
                    goal=item.description or item.objective_anchor or "",
                    session_id=session_id,
                    myc=_myc,
                    completed_tools=_completed,
                    task_class=_task_class,
                    memory_interface=self._memory_interface,
                )
            except Exception as _ev_err:
                logger.debug("[DER] evidence build failed: %s", _ev_err)

            prompt = (
                f"{cp_str}\n\n"
                + (f"SESSION FINDINGS SO FAR:\n{wm_str}\n\n" if wm_str else "")
                + (f"{evidence_str}\n\n" if evidence_str else "")
                + f"OBJECTIVE: {item.objective_anchor}\n"
                + (f"{_voice_turn_note(self)}\n" if _voice_turn_note(self) else "")
                + f"STEP {item.step_number}: {item.description}\n\n"
                "Complete this step. Respond with the result only."
            ).strip()
            # OBSERVABILITY (2026-10-29, T48): did THIS step prompt carry the
            # memory-of-facts line? Counted per turn and reported with the path.
            if "MEMORY         :" in (evidence_str or ""):
                self._turn_mem_prompts = int(
                    getattr(self, "_turn_mem_prompts", 0)) + 1
            # THINKING RUNS ON THE BRAIN (2026-08-16). This is the tool-less
            # step path â€” there is no tool to execute, only reasoning â€” so it
            # belongs to the reasoning binding. It used to run on
            # role="EXECUTION" (the tool_execution binding), which meant that
            # with Brain and Tool on different models the actual thinking was
            # done by whichever model the user picked for TOOLS. The Tool model
            # executes tools; it does not think.
            result = self.infer(
                prompt, role="reasoning", max_tokens=512, temperature=0.3
            )
            if not (result.raw_text or "").strip():
                # P3 (live conv-98): an Empty response here fell through to
                # the "[step N completed]" placeholder, failed verification,
                # and burned 3 sub-loop retries on the same bloated prompt.
                # Retry ONCE with shrunk context (excerpted findings) before
                # surrendering to the placeholder â€” same provider, bounded
                # prompt is the combination proven to succeed.
                logger.info(
                    "[DER] step-direct infer empty â€” retrying once with "
                    "shrunk context (step %s)", item.step_number,
                )
                _shrunk = (
                    f"{cp_str}\n\n"
                    + (
                        "SESSION FINDINGS SO FAR (excerpted):\n"
                        f"{self._smart_excerpt(wm_str, 1500)}\n\n"
                        if wm_str else ""
                    )
                    + (f"{evidence_str}\n\n" if evidence_str else "")
                    + f"OBJECTIVE: {item.objective_anchor}\n"
                    f"STEP {item.step_number}: {item.description}\n\n"
                    "Complete this step. Respond with the result only."
                ).strip()
                result = self.infer(
                    _shrunk, role="reasoning", max_tokens=512, temperature=0.3
                )
            return result.raw_text or f"[step {item.step_number} completed]"
        except Exception as _e:
            return f"[step {item.step_number} error: {_e}]"

    def _der_note_quick_tier(self, tool: Optional[str], result: Any) -> None:
        """Spec A4: keep the quick-tier -> crawler_query escalation state.

        A `search` result that says ``requires_deep_crawl`` marks this
        conversation so the gather gate (_mem_lookup) resolves the NEXT web goal
        to `crawler_query`; dispatching a `crawler_query` spends that escalation,
        so it happens once. Never raises - bookkeeping must not fail a step.
        """
        try:
            _key = (
                getattr(self, "conversation_id", "")
                or getattr(self, "session_id", "")
                or ""
            )
            _due = set(getattr(self, "_der_quick_insufficient", ()))
            if tool == "crawler_query":
                _due.discard(_key)
            elif (
                tool in ("search", "web_search")
                and isinstance(result, dict)
                and result.get("requires_deep_crawl")
            ):
                _due.add(_key)
                logger.info(
                    "[DER] quick tier insufficient conv=%s -> next web goal escalates "
                    "to crawler_query (once)", _key,
                )
            self._der_quick_insufficient = _due
        except Exception:  # noqa: BLE001
            pass

    def _der_pre_dispatch_guard(self, item: "QueueItem") -> Optional[Dict[str, Any]]:
        """T6B (specs/tool-result-envelope REQ-2/REQ-3 AC3.3, KD-10): the
        pre-dispatch HARD-RULE guard â€” prevention decides, the envelope
        testifies. Runs BEFORE a tool call is paid for; reads turn memory
        (seen dispatches + crawled URLs) and the wall ledger ONLY â€” adds no
        inference and no store writes.

        Hierarchy C hard rules (never overridable in-run):
          * WALLED â€” the target domain has a live wall record (is_walled):
            the tool is NEVER retried; the step fails honestly.
          * CIRCLING â€” this exact tool+params (or an all-known-URLs gather)
            already ran this conversation: NEVER re-executed; the step is
            rerouted to READ the original result via the document store
            (get_rendered_documents), and the original envelope is re-stamped
            confirmed load-bearing (AC1.6 retroactive half).

        Returns None when the call may proceed, or a dict:
          {"reason": ..., "reroute_tool": str|None, "reroute_params": dict,
           "original_step_id": str}
        Never raises â€” a broken guard must not change loop semantics
        (advisory-gate principle).
        """
        try:
            from backend.agent.tool_envelope import (
                mark_consumed, params_digest,
            )
            from backend.agent.tool_errors import is_walled

            _conv = self.conversation_id or ""
            _counters = getattr(self, "_envelope_counters", None)
            if _counters is None:
                _counters = {
                    "written": 0, "raw_ref_fetches": 0,
                    "crit_confirmed": 0, "gate_fired": 0,
                    "gate_blocked": 0, "hard_blocks": 0,
                    "suggest_overrides": 0,
                }
                self._envelope_counters = _counters

            # â”€â”€ HARD RULE 1: walled domain â€” never retried in-run â”€â”€â”€â”€â”€â”€â”€â”€â”€
            _target = ""
            try:
                _p = item.params or {}
                _candidate = str(
                    _p.get("url") or _p.get("base_url") or ""
                )
                if _candidate.startswith("http"):
                    from urllib.parse import urlparse as _urlparse

                    _target = _urlparse(_candidate).hostname or ""
            except Exception:
                _target = ""
            if _target and is_walled(_target):
                _counters["hard_blocks"] += 1
                logger.info(
                    "[DER:guard] WALLED tool refused pre-dispatch "
                    "(conv=%s step=%s tool=%s domain=%s) â€” never retried "
                    "in-run",
                    _conv, getattr(item, "step_id", "?"),
                    getattr(item, "tool", None), _target,
                )
                return {
                    "reason": f"walled domain {_target}",
                    "reroute_tool": None,
                    "reroute_params": {},
                    "original_step_id": "",
                }

            # â”€â”€ HARD RULE 2: repeat â€” never re-executed; read instead â”€â”€â”€â”€â”€
            _digest = params_digest(
                getattr(item, "tool", None), getattr(item, "params", None)
            )
            _seen = getattr(self, "_der_seen_dispatches", {}).get(_conv, {})
            _original_step_id = _seen.get(_digest, "")
            # Execution audit B3 (2026-09-29): the repeat rule protects WEB
            # fetches, whose repeat returns the same page. Local tools read state
            # that changes - re-running the tests after an edit, or re-reading a
            # file after writing it, is the coding loop itself - so they are
            # never blocked as repeats.
            if _original_step_id and str(getattr(item, "tool", "") or "").lower() \
                    not in AgentKernel._REPEAT_GUARDED_TOOLS:
                _original_step_id = ""
            if _original_step_id:
                # Find the original envelope for the doc pointer (bounded
                # scan of the FIFO-capped registry).
                _original_env = None
                _bucket = getattr(self, "_der_envelope_registry", {}).get(
                    _conv, {}
                )
                for _env in _bucket.values():
                    if getattr(_env, "step_id", "") == _original_step_id:
                        _original_env = _env
                        break
                if _original_env is not None:
                    try:
                        _before, _after = mark_consumed(_original_env)
                        _counters["crit_confirmed"] += 1
                        if _before[0] != "load-bearing":
                            logger.info(
                                "[envelope] criticality divergence: step %s "
                                "declared %s but a later step consumed its "
                                "doc (now %s) â€” tuning signal",
                                _original_step_id, _before[0], _after[0],
                            )
                    except Exception:
                        pass
                _counters["hard_blocks"] += 1
                logger.info(
                    "[DER:guard] REPEAT blocked pre-dispatch (conv=%s "
                    "step=%s tool=%s original=%s) â€” rerouting to read the "
                    "gathered documents instead of re-executing",
                    _conv, getattr(item, "step_id", "?"),
                    getattr(item, "tool", None), _original_step_id,
                )
                return {
                    "reason": f"repeat of step {_original_step_id}",
                    "reroute_tool": "get_rendered_documents",
                    "reroute_params": {"conversation_id": _conv},
                    "original_step_id": _original_step_id,
                }

            # â”€â”€ Gather URL-subset check: all fetch targets already crawled â”€
            # Compares NORMALIZED addresses so a trailing slash or fragment
            # drift cannot re-open a visited page (session-321 B-probe fix).
            _p = item.params or {}
            _urls = _p.get("known_urls") or (
                [_p["url"]] if _p.get("url") else []
            )
            _crawled = getattr(self, "_der_crawled_urls", {}).get(_conv, set())
            try:
                from backend.agent.tool_envelope import normalize_url as _norm_guard
                _urls_n = [_norm_guard(str(u)) for u in _urls]
                _crawled_n = set(_norm_guard(str(u)) for u in _crawled)
            except Exception:
                _urls_n = [str(u) for u in _urls]
                _crawled_n = set(str(u) for u in _crawled)
            if _urls and _crawled and all(
                u in _crawled_n for u in _urls_n if u
            ):
                _counters["hard_blocks"] += 1
                logger.info(
                    "[DER:guard] URL-repeat blocked pre-dispatch (conv=%s "
                    "step=%s): all %d fetch targets already crawled this "
                    "conversation â€” rerouting to read",
                    _conv, getattr(item, "step_id", "?"), len(_urls),
                )
                return {
                    "reason": "all fetch targets already crawled this turn",
                    "reroute_tool": "get_rendered_documents",
                    "reroute_params": {"conversation_id": _conv},
                    "original_step_id": "",
                }
            return None
        except Exception as _guard_exc:
            logger.debug(
                "[DER:guard] pre-dispatch guard skipped: %s", _guard_exc
            )
            return None

    def _der_before_call(self, tool: str, _session: str) -> None:
        """Per-call bookkeeping BEFORE one DER tool dispatch - one place for the
        direct step and every node call (a node web call skipped all of it
        until 2026-10-03: no external mark, no browser warm)."""
        # Trust-routing W2: mark external for web/crawler tools
        self.mark_external_tool(tool)
        # pin_42ddd255162d: render tools need the conversation registry on the
        # bridge; DER paths never received it.
        try:
            self._tool_bridge._active_conversation_id[_session] = self.conversation_id or ""
        except Exception:
            pass
        # AC9.6 (session-319): warm the pooled vision browser the moment a WEB
        # tool is dispatched, so its cold start overlaps the crawl instead of
        # blocking recovery later. Fire-and-forget - the crawl never waits.
        if tool in self._WEB_CONTENT_TOOLS:
            self._der_warm_vision_browser(tool)

    def _der_after_call(self, item, tool: str, params, dr, _session: str, _turn_id: Optional[str],
                        capture: bool = True) -> None:
        """Per-call bookkeeping AFTER one DER tool dispatch (direct step or node
        call): crawl budget, ToolCallTree row, quick tier, result capture
        (sources / har_path for the reply). Never raises."""
        if not dr:
            return
        # Edit diffs: the diff rides the tool result from the bridge. It goes
        # onto the step (-> its tool:result event) and OFF the result, so the
        # model and the step text never read it.
        _res = getattr(dr, "result", None)
        if isinstance(_res, dict) and "diff" in _res:
            try:
                _d = _res.pop("diff")
                if isinstance(_d, dict):
                    _eds = getattr(item, "edit_diffs", None)
                    if not isinstance(_eds, list):
                        _eds = []
                        item.edit_diffs = _eds
                    _eds.append(_d)
                    del _eds[:-12]  # bounded: a node makes at most 12 calls
            except Exception:  # noqa: BLE001 - a diff never fails a step
                logger.debug("[DER] edit diff capture skipped", exc_info=True)
        # pin_42ddd255162d: dispatch-time gather sanction - the dispatch runs
        # for EVERY crawl (real or dedupe-hit), so record the query hash here:
        # guaranteed bookkeeping for the per-task crawl budget/veto. A deadline
        # expiry did not crawl.
        if (tool in self._WEB_CONTENT_TOOLS and self.conversation_id
                and getattr(dr, "error_type", None) != "timeout"):
            try:
                from backend.agent.der_execution_ledger import make_action_key

                # D2: same stable action key as the gather gate.
                _gq = make_action_key(item.description or tool)
                with _der_claim_lock(self, "crawl_attempts"):  # parallel nodes
                    _cs = dict(getattr(self, "_der_crawl_attempts", {}))
                    _cs[self.conversation_id] = _cs.get(self.conversation_id, set()) | {_gq}
                    self._der_crawl_attempts = _cs
            except Exception:
                pass
        # â”€â”€ Record tool call for ToolCallTree (REQ-13) â”€â”€
        try:
            _result_str = str(getattr(dr, "result", ""))[:200] or str(getattr(dr, "error", ""))[:200]
            self._get_tool_box().record_tool_call(
                step_id=str(getattr(item, "step_id", "")) or "",
                tool=tool,
                args_hash=hashlib.md5(str(params).encode()).hexdigest()[:12],
                result_summary=_result_str,
                error_type=getattr(dr, "error_type", None),
                source="tool",
                split_depth=int(getattr(item, "depth_layer", 0)) or 0,
                parent_step_id=str(getattr(item, "parent_step_id", "")) or None,
            )
        except Exception as _rc_err:
            logger.warning("[DER] record_tool_call failed: %s", _rc_err)
        self._der_note_quick_tier(tool, getattr(dr, "result", None))
        # W9 (O3): capture structured tool results
        if capture and getattr(dr, "result", None) is not None:
            try:
                _doc = self._capture_tool_result(
                    tool, dr.result, self.conversation_id, _turn_id, _session,
                )
                if _doc:
                    item.captured_doc_id = _doc
            except Exception as _cap_err:
                logger.warning("[DER] tool-result capture failed: %s", _cap_err)

    def _der_run_direct_node(self, item, goal: str, task: str = "") -> tuple:
        """A "direct" node: answer the goal from the model's own knowledge.

        The cheap half of the unification - no plan, no node prompt, no tool
        loop. It is STILL a node, and that is what makes the mode an execution
        detail rather than a second lane:

          * it returns the SAME ``(step_result, success)`` shape ``_der_run_node``
            returns, so the finalize site (Â§5) and the failure seam
            (``_der_handle_step_failure``) are unchanged and still see it;
          * it stamps the SAME bookkeeping the DAG reads (``node_calls`` /
            ``node_call_log`` / ``node_digest``), so repeat detection and the
            step budget count it;
          * the envelope is stamped at the finalize site, not here.

        One model call, no tools. Never raises.
        """
        text = ""
        try:
            _msgs = [{"role": "user", "content": (task or goal)}]
            _text, _thinking, _calls = self._router.generate("reasoning", _msgs)
            text = str(_text or "").strip()
        except Exception as exc:  # noqa: BLE001 â€” a node never crashes the turn
            logger.debug("[DER] direct node failed: %r", exc)
        item.node_calls = []
        item.node_call_log = []
        try:
            from backend.agent.tool_envelope import params_digest

            item.node_digest = params_digest(
                "run_node_direct", {"goal": (goal or "")[:200]}
            )
        except Exception:  # noqa: BLE001 â€” bookkeeping never fails a step
            pass
        return text, bool(text)

    def _der_run_node(self, item, _session: str, _turn_id: Optional[str], _prior_results: list, task: str = "") -> tuple:
        """Adapter for node_executor.run_node: this kernel's router, the box's
        dispatch (ledger rows, deadlines, permissions) and the developer tools."""
        from backend.agent.node_executor import (
            NODE_SCREEN_TOOLS, NODE_TOOLS, NodeContext, run_node,
        )
        from backend.agent.tool_decision import _vision_relevant

        box = self._get_tool_box()

        # A node belongs to ONE turn. Eval C c04 (2026-10-02, conv-622): the
        # 600 s budget sent the reply while a recovery node was starting in a
        # batch thread; the turn's finally then made the router's choke check
        # inert and the node made model and tool calls for 3 more minutes,
        # into the next task. Every node call first checks that its turn is
        # still the live one and was not stopped (budget or user "stop").
        # A stand-in kernel with no DER state counts as live.
        def _turn_live() -> bool:
            if getattr(self, "_der_stop_requested", False):
                return False
            # parallel nodes: the split race was won by a sibling, or the
            # plan / turn this node belongs to was dropped
            if getattr(item, "_race_lost", "") or getattr(item, "_node_cancelled", ""):
                return False
            if getattr(self, "_der_turn_active", True) is False:
                return False
            live_id = getattr(self, "_der_turn_id", None)
            return _turn_id is None or live_id is None or live_id == _turn_id

        _ended = "turn ended (reply sent or stopped); this node does no more work"

        def _generate(role, messages, **kw):
            if not _turn_live():
                logger.info("[run_node] conv=%s turn=%s %s", self.conversation_id, _turn_id, _ended)
                raise RuntimeError(_ended)
            # W0: node model calls read "node" in the baseline rows; a code node's
            # generate (below) passes "code_node" ahead of this default.
            out = self._router.generate(role, messages, **{"call_kind": "node", **kw})
            self._accrue_tokens("", getattr(self._router, "last_usage", None), source="run_node")
            return out

        _held: List[str] = []
        _wb_bound: List[str] = []   # C8: the scratch folder bound to the session for this node

        # One domain correction per step (2026-10-08). Bounded deliberately:
        # unbounded re-steering is the TrailingDirector failure mode.
        _domain_steered = [False]

        def _execute(name, params):
            if not _turn_live():
                return {"success": False, "error": _ended, "error_type": "aborted"}
            # â”€â”€ Domain guard (2026-10-08) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # A step whose goal names an EXTERNAL resource, but which reaches
            # for a LOCAL tool, is searching the wrong domain. Measured live: a
            # plan step "Read the README and main files from the OpenAI math
            # repository" ran glob_files/grep_files INSIDE the project root for
            # ~6 minutes and ended "no dedicated `openai_math` repository folder
            # exists in the project root" - the repo was on GitHub.
            #
            # This corrects the PICK, never the menu: the menu keeps BOTH
            # families so a task can move local -> external -> local freely, and
            # nothing is removed. It only fires when the goal is external AND
            # the pick is local, and only once per step.
            try:
                from backend.agent import external_reference as _xr

                if name in _xr.LOCAL_TOOLS and not _domain_steered[0]:
                    _names = [
                        t.get("function", {}).get("name") for t in tools
                    ]
                    # Provenance, DER-NATIVE FIRST: the step's OWN envelope
                    # records the URLs that step fetched (ToolEnvelope.sources,
                    # REQ-8 AC8.1). Only when the step carries no envelope do we
                    # fall back to the conversation-level set - the envelope is
                    # the DER's per-step truth and must win.
                    _env_srcs = list(
                        getattr(getattr(item, "envelope", None), "sources", [])
                        or []
                    )
                    _srcs = _env_srcs or self._turn_sources()
                    # The predicate is goal-external AND the PICK is local - not
                    # "the menu is all local". The menu legitimately holds both
                    # families, which is what lets a task move between them.
                    _shape = _xr.domain_mismatch(goal, [name], _srcs)
                    _alt = _xr.resolving_tool(_shape) if _shape else None
                    # Params are unambiguous for BOTH steered families:
                    #   search   -> {"query": ...}  (the goal IS the query)
                    #   open_url -> {"url": ...}    (the URL is IN the goal)
                    _steer_params = None
                    if _alt == "search":
                        _steer_params = {"query": goal[:300]}
                    elif _alt == "open_url":
                        _u = _xr.first_url(goal)
                        _steer_params = {"url": _u} if _u else None
                    if _steer_params and _alt in _names:
                        _domain_steered[0] = True
                        logger.info(
                            "[DER] domain guard: goal names an EXTERNAL %s but "
                            "the pick was local (%s) -> steering to %s",
                            _shape, name, _alt,
                        )
                        name, params = _alt, _steer_params
                    elif _alt:
                        logger.info(
                            "[DER] domain guard: goal names an EXTERNAL %s but "
                            "%s is not offered/steerable - local pick %s left "
                            "alone", _shape, _alt, name,
                        )
            except Exception as _dg_exc:  # noqa: BLE001 â€” a guard never blocks a step
                logger.debug("[DER] domain guard skipped: %r", _dg_exc)
            # parallel nodes: the browser page / the screen has one driver - a
            # node claims it at its first such call and keeps it to the end.
            _claim = _node_claim_of(name)
            if _claim and _claim not in _held:
                if not _der_claim(self, _claim, item):
                    return {"success": False, "error": _ended, "error_type": "aborted"}
                _held.append(_claim)
            self._der_before_call(name, _session)
            dr = box.dispatch(
                Decision(kind=DecisionKind.TOOL, tool=name, params=params, source="run_node"),
                session_id=_session, conversation_id=self.conversation_id,
                turn_id=_turn_id, timeout_s=self._der_tool_deadline(name),
            )
            # A node stores only web search/crawl results (sources for the
            # reply): every page list from a click became a 34k-char document
            # + ~39 memory chunks (live 2026-10-03), DB writers for nothing.
            self._der_after_call(item, name, params, dr, _session, _turn_id,
                                 capture=name in self._WEB_CONTENT_TOOLS)
            raw = getattr(dr, "result", None)
            return raw if raw is not None else {"success": False, "error": getattr(dr, "error", "") or "no result"}

        goal = item.description or item.objective_anchor or ""
        # â”€â”€ mode (2026-10-08, unification) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # The node's GOAL decides its mode, exactly as it decides its domain
        # (the domain guard in _execute). Chosen ONCE here, at node entry -
        # never switched mid-step. A "direct" node answers from the model's own
        # knowledge instead of running the planned tool loop, so a simple step
        # does not pay the planning cost, and a turn is no longer locked into
        # one lane: _needs_planning is now only the TURN-LEVEL DEFAULT.
        from backend.agent import external_reference as _xr_mode

        item.mode = _xr_mode.mode_for_goal(goal, self._turn_sources())
        if item.mode == _xr_mode.DIRECT:
            return self._der_run_direct_node(item, goal, task)
        _menu = set(NODE_TOOLS) | (set(NODE_SCREEN_TOOLS) if _vision_relevant(goal) else set())
        tools = [t for t in self._get_openai_tools() if t.get("function", {}).get("name") in _menu]
        # Advisory narrowing (2026-11-06): core coding tools + the Oracle's top
        # picks, so a call does not carry the whole 17-tool menu. Full menu on
        # any failure; IRIS_NODE_TOOL_MENU_K=0 disables it.
        tools = _narrow_node_tools(tools, goal)
        if _clm_offload_on():
            tools = _clm_recall_menu(tools, self._get_openai_tools())
            try:
                tools = _clm_menu_budget(
                    tools, int(self.resolve_context_window_with_source("tool_execution").tokens))
            except Exception as exc:  # noqa: BLE001 - the full menu stays, logged
                logger.warning("[clm] menu budget skipped: %r", exc)
        # The shadow scores the menu the node's model was OFFERED, not the
        # registry's first names (which are vision tools).
        _offered = [t["function"]["name"] for t in tools]
        workdir =(getattr(self._tool_bridge, "_session_workdirs", None) or {}).get(_session, "")

        # The pre-call evidence, computed ONCE for this node: the previous
        # step's result (the most predictive signal for the next tool) and the
        # offered tools' descriptions. Both the tool_choice shadow and the
        # tool_approval consult read them.
        _lr = ""
        try:
            if _prior_results:
                _p = _prior_results[-1]
                _lr = f"{_p.get('description') or ''}: {_p.get('result') or ''}"
        except Exception:  # noqa: BLE001 â€” a shadow never needs context
            _lr = ""
        # tc-frame-v10 (2026-11-04): the option lines are the BARE tool
        # names. MEASURED by replay on the active engine (1200 recorded
        # tc-frame-v8 states, the same rows for both variants): the tools'
        # decision lines measured oof AUROC 0.6569 and the bare names
        # 0.6955, with monotonic confidence bands in both cases. The
        # instruction carries the question; the option text must not argue
        # for a tool (the same lesson as the review_verdict v9 criteria and
        # the tool_choice control labels, oracle.md 7.6).
        _hints = {n: n for n in _offered}
        _hints.update({n: n for n in ("DELEGATE", "NONE")})

        # THE STEP'S OWN STATE (tc-frame-v5 / tool_approval v3, 2026-10-11):
        # the hooks read the node's LIVE pre-call state - the calls this step
        # made so far and the last result the model saw - not `_lr` alone,
        # which is the previous STEP's result computed once per node (every
        # call of a step scored the same frame: 50.9% parity on 395 rows).
        # Read and rendered to strings AT CALL TIME: the list keeps growing.
        _node_state: Dict[str, Any] = {}
        _done_when = str(getattr(item, "expected_output", "") or "")

        def _step_so_far():
            from backend.agent.node_executor import history_text

            _c = _node_state.get("ctx")
            if _c is None:
                return "", _lr
            return history_text(_c.history), (_c.last_result_text or _lr)

        def _facts_now():
            # tc-frame-v7: the read/edit/write/run facts of THIS step, now.
            from backend.agent.node_executor import step_facts

            _c = _node_state.get("ctx")
            return step_facts(goal, _done_when, list(_c.history) if _c is not None else [],
                              workdir or "",
                              last_result=(_c.last_result_text if _c is not None else "") or "")

        # THE ORACLE DECIDES THE TOOL: before each model call, one d1 question
        # over the offered tools on the step's pre-call state, through the
        # enforcement chokepoint (enforced, else sampled). A pick is FORCED at
        # the API; the pending row is labelled by the call that follows
        # (_on_result) or flushed as "finished".
        _decided: Dict[str, Any] = {}

        def _flush_decided():
            _p = _decided.pop("row", None)
            if _p is not None:
                box.label_decided_row(_p, called=None, ok=None,
                                      session_id=self.conversation_id or "voice")

        def _choose_tool():
            _flush_decided()  # the previous pick was never called: finished
            _hist, _last = _step_so_far()
            _c = _node_state.get("ctx")
            _n = len(_c.history) if _c is not None else 0
            got = box.choose_node_tool(
                goal=goal, candidates=_offered,
                scope_key=f"{_turn_id or ''}|{getattr(item, 'step_id', '') or ''}|{goal[:80]}|{_n}",
                last_result=_last or None, option_criteria=_hints or None,
                calls_this_step=_hist or None, done_when=_done_when or None,
                step_facts=_facts_now() or None,
                step_id=getattr(item, "step_id", None), turn_id=_turn_id,
            )
            if got is None:
                return None
            # CANDIDATE COMPRESSION (2026-11-07): the Oracle ranked the menu;
            # the model picks from this shortlist. No single tool is forced, so
            # a bad rank cannot push the model into a wrong tool. The row is
            # labelled by the call that follows (shortlist_served).
            if got[1].get("route") in ("shortlist", "class"):
                _decided["row"] = got[1]
                return got[0]
            # An ENFORCED pick already cleared its calibrated threshold. A
            # SAMPLED pick acts only at raw confidence >= IRIS_ORACLE_FORCE_MIN
            # (default 0.9; measured 96.7% held at >= 0.9 on 90 decided rows).
            # Below it the model decides: an unsure pick that only narrowed
            # the menu pushed the model into the wrong tool (edit_file picks
            # at median confidence 0.46 FAILED 22 times).
            try:
                _floor = float(os.environ.get("IRIS_ORACLE_FORCE_MIN", "0.9"))
            except ValueError:
                _floor = 0.9
            if not (got[1].get("route") == "enforced"
                    or float(got[1].get("confidence") or 0.0) >= _floor):
                return None
            got[1]["binding"] = True
            _decided["row"] = got[1]
            return got[0]

        _bn_sampled: Dict[str, bool] = {}

        def _on_call(name, params):
            # PRE-call (run_node executes the same params dict after this):
            # browser_next's sampled rung may swap the element the model chose
            # for the Oracle's, labelled later by the turn verdict.
            if name != "browser_act" or not isinstance(params, dict) \
                    or params.get("element_id") is None:
                return
            try:
                from backend.agent import browser_next_shadow as _bn

                _hist0, _last0 = _step_so_far()
                pick = _bn.sampled_pick(
                    goal=goal, page_text=_last0 or "",
                    element_id=params.get("element_id"),
                    done_when=_done_when or None, calls_this_step=_hist0 or None)
                if pick is not None:
                    _orig = params.get("element_id")
                    params["element_id"] = int(pick) if isinstance(_orig, int) else pick
                    _bn_sampled["hit"] = True
            except Exception as _bn_err:  # noqa: BLE001 - the model's click stands
                logger.debug("[DER] browser_next sampled pick failed: %r", _bn_err)

        def _on_result(name, params, ok, approval_ok=None):
            # The call's OUTCOME is now known. Every node consult runs HERE,
            # post-hoc, on the PRE-CALL state: run_node calls this BEFORE it
            # appends the call and before it updates the last result, so
            # _step_so_far() still returns what the model saw before the call.
            # (2026-10-11: tool_choice and browser_next moved here from the
            # pre-call hook so their rows carry `brain_ok` - an outcome-checked
            # label and fine-tuning data, not only parity.)
            # v6 (2026-10-17): `approval_ok` is the CALL-level outcome for the
            # tool_approval label (a run_command that RAN counts as a
            # successful call whatever its exit code reported about the WORK);
            # `ok` stays the loop-level outcome every other reader uses.
            _hist, _last = _step_so_far()
            # A real tool call: a card-free turn earns its card at the bound.
            self._der_count_tool_call(item)
            # An Oracle-decided pick is labelled by what THIS call did.
            _pend = _decided.pop("row", None)
            if _pend is not None:
                # v4 (2026-10-21): the tool_choice label reads the CALL-level
                # outcome (`approval_ok`), not the loop's `ok` - the exact
                # tool_approval/v6 precedent. Measured on the grown v3 cohort:
                # binding run_command rows ranked at CHANCE (AUROC 0.4982,
                # 488 rows) because a mid-iteration pytest exit (the command
                # RAN, exit 1, the call did its job) was labeled a wrong
                # pick; 36 of 39 failed run_command calls in the logs were
                # ran-and-exited, not errored. The call-level label takes the
                # honest-key cohort from AUROC 0.657 to 0.7988 offline. For
                # every tool but run_command the two outcomes are identical.
                _label_ok = bool(approval_ok) if approval_ok is not None \
                    else bool(ok)
                box.label_decided_row(_pend, called=name, ok=_label_ok,
                                      params=params if isinstance(params, dict) else None,
                                      session_id=self.conversation_id or "voice")
            if name == "browser_act" and isinstance(params, dict) \
                    and params.get("element_id") is not None \
                    and not _bn_sampled.pop("hit", False):
                # (a sampled click is the Oracle's own element: its row is
                # already held for the turn verdict, so no parity shadow)
                try:
                    from backend.agent import browser_next_shadow as _bn

                    _bn.record_browser_next(
                        goal=goal, page_text=_last or "",
                        element_id=params.get("element_id"),
                        action=str(params.get("action") or ""),
                        done_when=_done_when or None, calls_this_step=_hist or None,
                        brain_ok=bool(ok), conversation_id=self.conversation_id or "",
                    )
                except Exception as _bn_err:  # noqa: BLE001 â€” a shadow never blocks
                    logger.debug("[DER] browser_next row failed: %r", _bn_err)
            try:
                # Same single ledger writer as the direct loop; async_=True runs
                # it on a daemon thread, so the node pays no latency.
                box.record_shadow_tool_choice(
                    goal=goal, observed_tool=name, observed_params=params,
                    candidates=_offered, last_result=_last or None,
                    option_criteria=_hints or None,
                    calls_this_step=_hist or None, done_when=_done_when or None,
                    step_facts=_facts_now() or None,
                    source="der_node", brain_ok=bool(ok),
                    session_id=self.conversation_id or "voice",
                    conversation_id=self.conversation_id or "", async_=True,
                )
            except Exception as _tc_err:  # noqa: BLE001 â€” a shadow never blocks
                logger.debug("[DER] tool_choice row failed: %r", _tc_err)

        # Eval C (owner 2026-10-02): the Brain helps a struggling tool model -
        # only when they are different models (a model cannot help itself).
        _helper = None
        try:
            # Provider AND model: Brain mercury-2.5 and tool mercury-2 share the
            # provider id "inceptionlabs", so comparing ids alone never engaged
            # the helper - a stuck node failed its step instead (live
            # 2026-10-03: 3x unchanged browser_observe -> split + recovery).
            _t = self._router.resolve("tool_execution")
            _r = self._router.resolve("reasoning")
            if (_t.id, getattr(_t, "model", None)) != (_r.id, getattr(_r, "model", None)):
                _helper = "reasoning"
        except Exception as _hr_exc:  # noqa: BLE001 - no helper, the node still runs
            logger.debug("[DER] node helper unresolved: %r", _hr_exc)
        # V8: the browser's marked screenshot reaches a model. The node's own
        # model takes it as an image when it can see; otherwise the resolved
        # vision model (brain / tool / local fallback) reads it as text.
        def _sees(role):
            from backend.agent.inference.router import supports_vision

            return supports_vision(self._router.resolve(role))

        def _look(jpeg_b64, question):
            import base64 as _b64

            from backend.agent.inference.router import resolve_vision_client

            _res, client = resolve_vision_client(self._router)
            return client.analyze_screen(_b64.b64decode(jpeg_b64), (
                "This is a screenshot of a web page. Each numbered box marks an "
                "element; the number is its element_id. Answer in at most five "
                f"short lines: {question}"
            ))

        try:
            # REQ-10/REQ-14 (Wave 5, AC14.3): one node's id per EXECUTION -
            # run_step retries, so a step can execute twice; the superseded
            # execution's claims are UNTESTED (the final execution is the
            # truth). The scope rides a contextvar on THIS node thread; the
            # close-claim probe only ever gets written TO (the closing rule
            # stays the sole judge of the loop - AC10.0's fences).
            from backend.agent import decision_engine as _de

            _key = (str(_turn_id or ""), str(getattr(item, "step_id", "") or ""))
            _exec_counts = getattr(self, "_der_node_exec_counts", None)
            if _exec_counts is None:
                _exec_counts = self._der_node_exec_counts = {}
            _exec_n = _exec_counts.get(_key, 0) + 1
            _exec_counts[_key] = _exec_n
            _exec_id = f"{_key[1]}#{_exec_n}" if _key[1] else ""
            _de.set_scope(turn_id=_turn_id, step_id=_key[1] or None,
                          node_exec_id=_exec_id or None)
            _close_probe = _de.CloseClaimProbe(
                turn_id=_turn_id or "", step_id=_key[1], node_exec_id=_exec_id,
                goal=goal)
            if _exec_n > 1:
                _close_probe.supersede_prior(f"{_key[1]}#{_exec_n - 1}")
        except Exception:  # noqa: BLE001 - measurement never blocks a node
            _close_probe = None
        try:
            # REQ-12 AC2 (T48): the tool steps are the ones that answer, and
            # this is the only executor they use. Give the node the earlier
            # statements with their producer, so a taught fact is available
            # without asking a tool to go and find it.
            try:
                from backend.agent.evidence import _memory_facts as _mf

                _step_facts = _mf(goal, getattr(self, "_memory_interface", None))
            except Exception:  # noqa: BLE001 - memory never blocks a step
                _step_facts = ""
            if _step_facts:
                self._turn_mem_prompts = int(
                    getattr(self, "_turn_mem_prompts", 0)) + 1
            _node_ctx = NodeContext(
            generate=_generate, execute=_execute,
            format_result=lambda name, raw: self._format_tool_result_for_step(raw, name),
            tools=tools, prior_results=_prior_results, task=task, workdir=workdir,
            conv_id=self.conversation_id or "", helper_role=_helper,
            on_result=_on_result, choose_tool=_choose_tool,
            on_call=_on_call,
            sees=_sees, look=_look,
            memory_facts=_step_facts,
            # the step's own criterion, its parent step, the reviewer's reason
            expected=str(getattr(item, "expected_output", "") or ""),
            parent_goal=str(getattr(item, "parent_description", "") or ""),
            review_note=str(getattr(item, "review_feedback", "") or ""),
            parallel_ok=_node_call_parallel_ok if _DER_PARALLEL else None,  # one off switch
            close_probe=_close_probe,
            **(_clm_node_hooks(self, item, _turn_id, session=_session, goal=goal)
               if _clm_offload_on() else {}),
            )
            _node_state["ctx"] = _node_ctx
            _full_tools = self._get_openai_tools() if _wb_on() else []
            _wb_go = False
            _wb_browser = False
            if _wb_on() and _wb_code_mode(goal, _full_tools, workdir, item):
                # D7: ONE code node at a time owns the conversation's namespace. Take that
                # claim BEFORE run_node starts its 300 s clock (parallel code nodes waited
                # 880 s on it INSIDE their budget, measured). It is released in the finally
                # below with the other held claims; _execute sees it in `_held` and does not
                # take it a second time at the first run_python.
                # Round 6 C2: a browser code node takes `browser` THEN `workbench` (the one order
                # every node uses), both before the clock, and keeps `browser` for the menu
                # re-run of a needs_sight fallback.
                _wb_browser = _wb_browser_step(item, _full_tools)
                _wb_t0 = time.perf_counter()
                _wb_go = True
                for _cl in (("browser", "workbench") if _wb_browser else ("workbench",)):
                    _wb_go = _cl in _held or _der_claim(self, _cl, item)
                    if not _wb_go:
                        break
                    if _cl not in _held:
                        _held.append(_cl)
                _wb_wait = time.perf_counter() - _wb_t0
                _wb_stats["wb_wait_s"] += _wb_wait
                if _wb_go and _wb_browser and not workdir:
                    # C8: no bound folder in personal mode = the private scratch folder, bound for
                    # this node so run_python (which reads the session workdir) agrees with the seed
                    _scratch = _wb_scratch_dir(self.conversation_id or "")
                    _wb_go = _scratch is not None
                    if _scratch:
                        workdir = _scratch
                        if hasattr(self._tool_bridge, "set_session_workdir"):
                            self._tool_bridge.set_session_workdir(_session, workdir)
                            _wb_bound.append(workdir)
                if _wb_go and not _wb_seed(
                        self.conversation_id or "", workdir, task, goal, _prior_results, _step_facts):
                    _wb_go = False
                # Round 6 PROTOTYPE: seed the side-lane page text into the worker.
                # Only for a browser code node with the flag on.
                _wb_seeded = False
                _wb_pages = []
                if _wb_go and _wb_browser and _page_seed_on():
                    _wb_pages = page_seed_collect(self.conversation_id or "")
                    if _wb_pages:
                        _wb_seeded = _wb_seed_pages(self.conversation_id or "", workdir, _wb_pages)
                if not _wb_go and "workbench" in _held:
                    _held.remove("workbench")   # a menu node does not keep the namespace
                    _der_release(self, "workbench")
            if _wb_go:
                import dataclasses as _dc

                # Round 6: the live goal-contract view for the brief (north star).
                # Advisory only - never a new floor. Empty when no contract exists.
                _wb_contract = {}
                if _page_seed_on():
                    try:
                        _gc_st = getattr(self, "_goal_contract_state", None) or {}
                        _gc_obj = _gc_st.get("contract")
                        _wb_contract = {
                            "ceiling": list(getattr(_gc_obj, "ceiling", None) or ()),
                            "open": list(self._goal_contract_open_facts() or ()),
                        }
                    except Exception as exc:  # noqa: BLE001 - a contract view never blocks a node
                        logger.debug("[workbench] conv=%s contract view skipped: %r",
                                     self.conversation_id, exc)

                # C3: the node's menu INTERSECTED with the tools it was offered (the web toggle
                # holds); the browser tools (browser_read too) only for a browser code node.
                _wb_offered = {(t.get("function") or {}).get("name") for t in _full_tools}
                _wb_menu = (set(_menu) | _WB_BROWSER_TOOLS) if _wb_browser \
                    else set(_menu) - _WB_BROWSER_TOOLS
                _wb_allowed = frozenset(n for n in _wb_menu if n != "run_python" and n in _wb_offered)
                _wb_need = _wb_needed_tools(item, _wb_allowed)
                _wb_cb_calls: list = []
                _wb_node = uuid.uuid4().hex   # F2: this node's own callback slot
                _wb_rr = _wb_repair_tracker(self, _session) if _wb_brief(item, _wb_contract)[1] else None
                # D3: the ground, ONCE per node - in the first message, and in the repair prompt
                _wb_ground = _wb_ground_text(workdir, profile=True, max_chars=_wb_ground_chars(_node_ctx.window),
                                             text=f"{task}\n{goal}")
                # Round 6 fix (b): a browser code node gets the ALREADY-OPEN page's shape up
                # front (no browser_open), so its script does not spend runs exploring it.
                if _wb_browser and not _wb_seeded:
                    _wb_page = _wb_browser_ground(self.conversation_id or "", _execute)
                    if _wb_page:
                        _wb_ground = (_wb_ground + "\n\n" + _wb_page) if _wb_ground else _wb_page
                # Round 6 page-seed: the model cannot read the worker namespace from
                # its prompt. Show a bounded digest of the seeded page text so it can
                # write the parse in ONE script instead of spending look scripts.
                if _wb_seeded and _wb_pages:
                    _digest = (_wb_page_digest(_wb_pages, max_chars=8000, sample=8000)
                               if _two_call_on() else _wb_page_digest(_wb_pages))
                    if _digest:
                        _wb_ground = (_wb_ground + "\n\n" + _digest) if _wb_ground else _digest
                _wb_hold: list = []
                # 2026-11-22 (CLM audit, c12 A/B): the PAIR path (gather + compute in one
                # response) was built and gated on BROWSER code nodes only; flag-wide it also
                # took coding nodes (c12 on: 2/3, reply median 128 s vs 59 s off). A non-browser
                # code node keeps the single-script path the TG-7 full re-run measured.
                _wb_pair = _two_call_on() and _wb_browser
                try:
                    from backend.agent.decision_engine import scope_now as _scope_now
                    _wb_scope = _scope_now()    # C4: captured HERE, on the node thread
                except Exception:  # noqa: BLE001 - a scope is best-effort
                    _wb_scope = {}

                def _wb_on_result(name, params, ok, approval_ok=None):
                    # a real tool call earns the card (kernel.surface counter); no Oracle labels
                    # in code. A finished run_python starts the browser-call count again (C1).
                    self._der_count_tool_call(item)
                    if name in ("run_python", "run_python_pair") and _wb_hold:
                        _wb_hold[0].new_exec()

                def _wb_browser_row(args, ok, page_text, history):
                    from backend.agent import browser_next_shadow as _bn

                    _bn.record_browser_next(
                        goal=goal, page_text=page_text or "", element_id=args.get("element_id"),
                        action=str(args.get("action") or ""), done_when=_done_when or None,
                        calls_this_step=history or None, brain_ok=bool(ok),
                        scope=_wb_scope, via="run_python",
                        conversation_id=self.conversation_id or "")

                _wb_ctx = _dc.replace(
                    _node_ctx,
                    workdir=workdir,
                    ground=_wb_ground,
                    memory_facts="",      # D3: in code mode the MEMORY text is the `memory` variable only
                    tools=(_wb_slim_run_python_pair(_full_tools)
                           if _wb_pair and not _see_gather_on()
                           else _wb_slim_run_python(_full_tools)),
                    # the tagged generate: a code node's model calls read "code_node" in the
                    # baseline rows (the closure tags every other node call "node")
                    generate=lambda role, messages, **kw: _generate(
                        role, messages, **{"call_kind": "code_node", **kw}),
                    stats={},
                    # Round 3 R1: the TOOL MODEL writes and runs the code; the
                    # Brain briefs (plan time) and steps in once on escalation.
                    role="tool_execution", helper_role=None, max_tokens=1024,
                    # Round 6 (2026-11-21): the pair path used max_calls=1, so a single
                    # failed check closed the node success=False with no retry (g01 r1:
                    # the script used a relative author URL and the node never recovered).
                    # Give it ONE corrected retry. Passing runs still close on their first
                    # check, so calls/prompt/reply medians are unchanged; only failing runs
                    # pay the extra call. _see_gather already uses 2 for the same reason.
                    max_calls=(2 if (_see_gather_on() or _wb_pair) else 6),
                    system=(_WB_SEE_GATHER_SYSTEM if _see_gather_on() else
                            _WB_TWO_CALL_SYSTEM if _wb_pair else
                            _WB_SYSTEM + (_WB_TOOLS_NOTE + _wb_tool_lines(_full_tools, _wb_need)
                                          if _wb_need else "")
                            + (_WB_BROWSER_NOTE if _wb_browser else "")
                            + (_WB_PAGE_SEED_NOTE if _wb_seeded else "")
                            + (_wb_self_verify_note(_wb_brief(item, _wb_contract)[1])
                               if _wb_self_verify_on() else "")),
                    choose_tool=None, on_call=None,
                    on_result=_wb_on_result,
                    brief=_wb_brief(item, _wb_contract)[0], check=_wb_brief(item, _wb_contract)[1],
                    wb_outputs=_wb_output_names(item), wb_node=_wb_node,
                    on_check_failed=(_wb_escalate(self, self.conversation_id or "", workdir,
                                                  *_wb_brief(item, _wb_contract), tracker=_wb_rr,
                                                  ground=_wb_ground)
                                     if _wb_brief(item, _wb_contract)[1] else None),
                    # T7.15: shadow rows only - the rule above still decides
                    on_check=((lambda a, ok, et, ce: _wb_rr.passed() if ok
                               else _wb_rr.failed(a, et or "CheckFailed", ce))
                              if _wb_rr is not None else None),
                    prior_results=[dict(r, result=str(r.get("result") or "")[:_WB_PRIOR_HEAD]
                                        + " [full text: steps]") for r in _prior_results],
                )
                _wb_stats["code_nodes"] += 1
                logger.info("[workbench] conv=%s step=%s code node", self.conversation_id,
                            getattr(item, "step_id", ""))
                _wb_handler = _wb_callback_handler(
                    _execute, _wb_allowed, _wb_cb_calls, lambda: self._der_count_tool_call(item),
                    browser=_wb_browser,
                    wall_s=(max(0.0, _wb_ctx.budget_s - _WB_BROWSER_MARGIN_S) if _wb_browser else None),
                    on_browser_act=_wb_browser_row if _wb_browser else None)
                _wb_hold.append(_wb_handler)
                _wb_conv = self.conversation_id or ""
                from backend.agent.tool_bridge import (
                    clear_workbench_dispatch, set_workbench_dispatch)

                set_workbench_dispatch(_wb_conv, _wb_handler, _wb_node)
                try:
                    result = run_node(goal, _wb_ctx)
                finally:
                    _wb_handler.close()   # C1: first - the claims are released after this
                    clear_workbench_dispatch(_wb_conv, _wb_handler, _wb_node)
                    if _wb_rr is not None:
                        _wb_rr.end()
                    # W0: what this node did, once, at its close (the A/B analysis reads it)
                    _wb_stats["scripts"] += _wb_ctx.stats.get("scripts", 0)
                    _wb_stats["exploring"] += _wb_ctx.stats.get("exploring", 0)
                    logger.info("[workbench] conv=%s step=%s scripts=%d exploring=%d wait_s=%.1f",
                                self.conversation_id, getattr(item, "step_id", ""),
                                _wb_ctx.stats.get("scripts", 0), _wb_ctx.stats.get("exploring", 0),
                                _wb_wait)
                # G1: the verdict reads it (finalize); set per run so a re-run never keeps a stale True
                item.wb_check_passed = getattr(result, "check_passed", False) is True
                _why = _wb_needs_fallback(result, _wb_browser and _wb_handler.sight_poor())
                if _why:
                    _wb_stats["fallback"] += 1
                    logger.info("[workbench] conv=%s step=%s falls back to tools (%s)",
                                self.conversation_id, getattr(item, "step_id", ""), _why)
                    result = run_node(goal, _node_ctx)
                # the tools a script called ran through the node's dispatch: they are
                # this step's calls too (node_call_log, the task card). After a
                # fallback they happened BEFORE the fallback's calls, so they go first.
                if _why:
                    result.calls[:0] = _wb_cb_calls
                else:
                    result.calls.extend(_wb_cb_calls)
            else:
                result = run_node(goal, _node_ctx)
            _flush_decided()  # a last pick the step finished without calling
        finally:
            for _c in _held:
                _der_release(self, _c)
            if _wb_bound:   # C8: the scratch binding lasts for this node only
                _sw = getattr(self._tool_bridge, "_session_workdirs", None)
                if isinstance(_sw, dict) and _sw.get(_session) == _wb_bound[0]:
                    _sw.pop(_session, None)
        # What the node actually did, for the step's physics action (REQ-8 redo).
        try:
            item.node_calls = [
                (str(c.get("tool") or ""), bool(c.get("ok"))) for c in (result.calls or [])
            ]
        except Exception:  # noqa: BLE001 - bookkeeping never fails a step
            item.node_calls = []
        # Every "what did this step do" reader goes through _step_calls(item).
        item.node_call_log = [dict(c) for c in (result.calls or [])]
        # A node's identity for repeat detection is the calls it made: its
        # item has no tool and no params (the planner emits goals only), so
        # params_digest(None, {}) was one key for EVERY node step and any node
        # could read as a repeat of another (c15, 2026-10-01: a replan storm).
        from backend.agent.tool_envelope import params_digest

        item.node_digest = params_digest("run_node", {"calls": [
            [str(c.get("tool") or ""), str(c.get("target") or "")] for c in (result.calls or [])
        ]})
        return result.as_step_result(), result.success

    def _der_run_step_execution(
        self,
        item: "QueueItem",
        context_package,
        _session: str,
        _turn_id: Optional[str],
        plan,
        queue=None,
    ) -> tuple:
        """
        Phase 4: execute a single DER step's tool/direct action.
        Returns (step_result: str, step_success: bool).
        Faithful extraction of the inline execution block from _execute_plan_der.

        Session 245 (synthesis starvation fix): ``queue`` joins the signature
        so the tool-decision evidence for tool-less steps can carry PRIOR
        completed step results â€” previously the evidence was metadata-only
        (session/turn/task_class), so a synthesis step after a successful
        crawl was decided by a model that had never seen a byte of the crawl
        output ("I am unable to access the search results", conv-36).
        """
        step_result = ""
        step_success = True
        try:
            # â”€â”€ Session 245: prior completed step results for the decision
            # evidence (Seam A of the synthesis starvation fix). Bounded per
            # result by tool-aware caps; steps without results are skipped.
            _prior_results: list = []
            if queue is not None:
                try:
                    for _pit in queue.items:
                        if _pit is item:
                            continue
                        _pr = getattr(_pit, "result", None)
                        if not _pr:
                            continue
                        _prior_results.append(
                            {
                                "step": getattr(_pit, "step_number", None),
                                "description": (getattr(_pit, "description", "") or "")[:120],
                                "result": self._smart_excerpt(
                                    _pr,
                                    _step_evidence_cap(_pit),
                                ),
                            }
                        )
                except Exception as _prio_err:
                    logger.debug("[DER] prior-result gather failed: %s", _prio_err)

            # Execution audit Phase 2: a tool-less step runs as a bounded work
            # loop (backend/agent/node_executor.py) instead of one tool picked
            # once. Both modes (owner 2026-10-03, V10: personal mode ran one
            # tool per step - no retry of a failed call, no page screenshot).
            if not item.tool:
                if _wb_on():
                    item.wb_after_change = _wb_after_change(item, queue)   # S3
                return self._der_run_node(item, _session, _turn_id, _prior_results,
                                          task=getattr(plan, "original_task", "") or "")

            # â”€â”€ Phase 2: dispatch (TOOL) or direct (REASON) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Set the phase gate call class so the gate knows whether to wait
            # (REASON/TOOL â†’ gated) or admit immediately (USER_TURN/SPEAK) (T3.7).
            # GRAFT is NOT high-priority (T6.4) â€” recovery-plan generation after
            # a step failure (including 429) must be gated to avoid amplification.
            if item.tool:
                set_call_class(CallClass.TOOL)
            else:
                set_call_class(CallClass.REASON)

            if item.tool and self._tool_bridge is not None:
                self._der_before_call(item.tool, _session)
                # Session-318 T18 (REQ-11 AC11.1): per-family deadline for
                # the dispatch below, plus the monotonic start stamp that
                # feeds elapsed_s and the stall warning at finalize.
                try:
                    _dispatch_deadline = self._der_tool_deadline(item.tool)
                except Exception:
                    _dispatch_deadline = 90.0
                try:
                    import time as _time_dispatch
                    item.dispatch_started_at = _time_dispatch.monotonic()
                except Exception:
                    pass
                try:
                    _dispatch_decision = Decision(
                        kind=DecisionKind.TOOL,
                        tool=item.tool,
                        params=item.params,
                    )
                    _dr = self._get_tool_box().dispatch(
                        _dispatch_decision,
                        session_id=_session,
                        conversation_id=self.conversation_id,
                        turn_id=_turn_id,
                        timeout_s=_dispatch_deadline,
                    )
                except Exception as _maybe_timeout:
                    # Session-318 T18 (REQ-11 AC11.3): deadline expiry settles
                    # honestly â€” synthetic failed DispatchResult so the normal
                    # downstream (record/call/capture/finalize) all run and the
                    # envelope stamps status=timeout via item.timed_out.
                    # Version-proof timeout check (TimeoutError aliases differ
                    # pre-3.11); anything else re-raises to the outer handler.
                    import asyncio as _aio_timeout_mod
                    import concurrent.futures as _fut_timeout_mod
                    if not isinstance(
                        _maybe_timeout,
                        (_aio_timeout_mod.TimeoutError,
                         _fut_timeout_mod.TimeoutError),
                    ):
                        raise
                    _timeout_text = (
                        f"[STEP TIMEOUT after {_dispatch_deadline:g}s "
                        f"(deadline {_dispatch_deadline:g}s) — tool "
                        f"{item.tool} did not settle; continuing without it. "
                        f"The worker was abandoned, not killed (threads "
                        f"cannot be aborted); tool-internal ceilings bound "
                        f"the orphan."
                    )
                    logger.warning(
                        "[DER] step %d tool %r timed out (deadline %.0fs)",
                        item.step_number, item.tool, _dispatch_deadline,
                    )
                    try:
                        item.timed_out = True
                    except Exception:
                        pass
                    try:
                        from backend.agent.write_counters import bump as _bump_dlh
                        _bump_dlh("envelope.deadline_hits")
                    except Exception:
                        pass
                    _dr = DispatchResult(
                        success=False,
                        result={"success": False, "error": _timeout_text,
                                "error_type": "timeout"},
                        error=_timeout_text,
                        error_type="timeout",
                    )
                except RuntimeError as _rte:
                    # asyncio.run() inside box may fail if an event loop is
                    # already running in this thread â€” executor fallback
                    logger.warning(
                        "[DER] box.dispatch RuntimeError for %s: %s â€” using executor",
                        item.tool, _rte,
                    )
                    import concurrent.futures as _cf
                    import asyncio as _asyncio

                    with _cf.ThreadPoolExecutor(max_workers=1) as _pool:
                        _raw_dr = _pool.submit(
                            _asyncio.run,
                            self._tool_bridge.execute_tool(
                                tool_name=item.tool,
                                params=item.params,
                                session_id=_session,
                                plan_title=plan.plan_title if plan else "",
                            ),
                        ).result(timeout=_dispatch_deadline)
                        _dr = DispatchResult(
                            success=isinstance(_raw_dr, dict) and _raw_dr.get("success") is not False,
                            result=_raw_dr,
                        )
                self._der_after_call(item, item.tool, item.params, _dr, _session, _turn_id)
                step_result = self._format_tool_result_for_step(
                    getattr(_dr, "result", None), item.tool,
                ) if _dr else ""
                if _dr and not _dr.success:
                    step_success = False
                    # A CRASHED dispatch returns DispatchResult(success=False,
                    # error=..., result=None) (tool_decision.py:2205): the tool
                    # exception was caught one level deeper, so `result` is
                    # None, `_format_tool_result_for_step` yields "", and the
                    # step reported an EMPTY failure - the message never
                    # reached the DER synthesis. The timeout path above avoids
                    # this by putting its message in `result`. Do the same
                    # here, using this function's own
                    # "[STEP ERROR: ...]" convention (see the outer except).
                    if not step_result:
                        _dr_err = getattr(_dr, "error", None)
                        if _dr_err:
                            step_result = f"[STEP ERROR: {_dr_err}]"
            else:
                # REASON (no tool) or no tool_bridge â€” direct reasoning
                step_result = self._run_step_direct(item, context_package, _session)
        except RateLimitedError:
            # Propagate rate-limit failures untouched so the DER layer can
            # record them honestly (REQ-3 AC4 / REQ-4 AC2). Do NOT wrap in a
            # string â€” the structured provider_id / retry_after fields are
            # needed by the ledger.
            raise
        except Exception as _ex_err:
            step_success = False
            step_result = f"[STEP ERROR: {_ex_err}]"
            logger.warning(
                f"[DER] Step {item.step_number} explorer error: {_ex_err}"
            )
        return step_result, step_success

    def _get_verifier(self):
        if self._VERIFIER is None:
            from backend.agent.verifier import SemanticVerifier as _SV
            AgentKernel._VERIFIER = _SV()
        return self._VERIFIER

    def _verified_fraction(self, expected: Optional[str], result: str) -> float:
        """DER Phase 0 (D0.6): fraction of checkable assertions from expected_output
        that the result satisfies. Deterministic, no LLM. Assertions split on ';'.

        Delegates to SemanticVerifier (Phase 4 LFM2.5 integration) for semantic
        entailment scoring with stub guard + substring fallback.
        """
        frac, _scorer = self._get_verifier().verified_fraction(expected, result)
        # REQ-18 AC1 (T31): correlate the scorer tag + score into the per-task
        # trace. Off the critical path; a trace failure never affects the verdict.
        # The verified_label is attached by the caller (it is only known after
        # the full _verify_step_result classification completes).
        try:
            from backend.agent.der_trace import get_der_trace

            get_der_trace(self._der_trace_task_id()).record(
                "verify",
                scorer_tag=_scorer,
                score=round(float(frac), 4),
            )
        except Exception:
            pass
        return frac

    def _verify_step_result(
        self,
        goal: str,
        expected: Optional[str],
        result: str,
        tool: Optional[str] = None,
        success: bool = False,
    ) -> str:
        """DER Phase 0 (D0.1): classify a step result.
        Returns VERIFIED | UNVERIFIED | FAILED.
        A stub pattern with no real output is ALWAYS FAILED (no silent success).

        pin_517dfcbda150: when ``tool`` is a web/crawl tool, the verdict is
        CONTENT SUFFICIENCY â€” the tool already proved it fetched pages (a
        zero-page crawl returns an error from tool_bridge), so a non-empty,
        non-error result VERIFIEDs. This terminates the crawl step as soon as
        real content exists and prevents pointless re-crawl splits.
        """
        if tool in self._TRUSTED_RESULT_TOOLS:
            # pin_42ddd255162d: display/render tools complete by SUCCESS, and
            # this check runs FIRST â€” the formatted result of the render tool
            # can be an empty/JSON-less string even on success (its dict has no
            # extractable content key), and the old position (after the
            # empty-result check) turned every successful render into a
            # verify-FAILED â†’ split â†’ children re-gathered the SAME urls while
            # the card said "rendering documents". A trusted tool that ran
            # returns "VERIFIED" unconditionally â€” its contract never returns
            # errors on the read-only render path.
            return "VERIFIED"
        if not result:
            return "FAILED"
        # Strip the marker; if nothing substantial remains, it was a bare stub -> FAILED.
        _without_marker = self._STUB_RE.sub("", result).strip()
        if not _without_marker:
            return "FAILED"
        # Execution audit B4 (2026-09-29): run_command reports success=True for
        # a command that ran and exited non-zero (REQ-19, so the output stays
        # readable). "The tool ran" is not "the step worked": a failing test
        # run was VERIFIED. A non-zero exit commits honestly as UNVERIFIED.
        if tool in self._SHELL_RESULT_TOOLS:
            _exit = re.match(r"\[exit code (-?\d+)\]", result)
            if _exit and int(_exit.group(1)) != 0:
                return "UNVERIFIED"
        if tool and tool in self._WEB_CONTENT_TOOLS:
            _low = _without_marker.lower()
            # pin_42ddd255162d: CONTENT SUFFICIENCY must not scan real page
            # text for failure words â€” web pages legitimately contain "failed
            # to"/"no usable" mid-text, and the crawl fallback result may
            # carry an informational worker-timeout note alongside real pages.
            # Session 248 FIX (live conv-53): the failure-word scan below ran
            # on the FULL combined article text (12k chars), so any news page
            # containing "failed to" anywhere FAILED the step -> split ->
            # children re-crawled the SAME query. The tool contract already
            # guarantees the error case (zero usable pages -> error payload),
            # so: error PREFIX always fails; long content always verifies;
            # only SHORT (<80 chars) non-error text may be scanned for
            # failure phrases, and even then it commits as UNVERIFIED rather
            # than triggering a re-gather split.
            if _low.startswith("error"):
                return "FAILED"
            # Session 312 (goal-result alignment, user-directed): a successful
            # fetch that never mentions the step's distinctive subject did NOT
            # serve the goal â€” conv-99 "verified" a Parakeet step with a
            # whisper.cpp dump. Distinctive terms = capitalized words in the
            # goal (proper nouns like model names); if NONE appear in the
            # result, commit honestly as UNVERIFIED so the next decision sees
            # the gap instead of believing the goal is served.
            _subj_terms = [
                w for w in re.findall(r"[A-Z][a-zA-Z0-9]{2,}", goal or "")
                if w.lower() not in {
                    "the", "and", "for", "with", "find", "search", "research",
                    "compare", "whether", "how", "its", "any", "github",
                    "documentation", "authoritative", "information",
                }
            ]
            if _subj_terms and not any(
                t.lower() in _low for t in _subj_terms
            ):
                logger.info(
                    "[DER] gather alignment MISS: goal %r â€” none of %s appear "
                    "in fetched content", goal[:80], _subj_terms[:4],
                )
                return "UNVERIFIED"
            if success:
                return "VERIFIED"
            if len(_without_marker) >= 80:
                return "VERIFIED"
            if "no usable" in _low or "failed to" in _low:
                return "FAILED"
            # Short, non-error text: weak but honest â€” commits as UNVERIFIED,
            # never triggers a re-gather split.
            return "UNVERIFIED"
        if tool in self._TRUSTED_RESULT_TOOLS:
            # pin_42ddd255162d: display/render tools complete by SUCCESS â€” a
            # rendered-card confirmation is a legit completion. The expected
            # assertion text (e.g. "a rendered document card") never matches
            # the short confirmation string, so the assertion path FAILED the
            # step and split it â€” spawning children that re-gathered web pages
            # while the card said "rendering documents".
            return "VERIFIED" if _without_marker else "FAILED"
        _frac = self._verified_fraction(expected, result)
        _expected_text = (expected or "").strip()
        if not _expected_text:
            # pin_42ddd255162d: no explicit expectation (REASON/synthesis and
            # render steps) â€” the assertion fraction is meaningless; the verdict
            # rests on SUBSTANCE: a substantial result VERIFIEDs, short text
            # commits honestly as UNVERIFIED. Only an explicit error/stub FAILs.
            # Live fix 2026-09-24 (conv-145): a real TOOL that reported
            # SUCCESS is verified BY that success - the tool performed its
            # action and said so. write_file returned
            # {"success": true, "message": "Written to eyes_note4.md",
            # "bytes": 103} - 71 chars - and the 80-char substance rule
            # marked the step UNVERIFIED even though the file was on disk and
            # the read-back succeeded. The contract then never covered its
            # required fact (covered=0) and the turn was narrated as an
            # incomplete task. The length rule still governs TOOL-LESS steps
            # (REASON/synthesis), where substance really is the only signal.
            if success and tool:
                return "VERIFIED"
            return "VERIFIED" if len(_without_marker) >= 80 else "UNVERIFIED"
        if _frac >= 0.8:
            return "VERIFIED"
        if _frac >= 0.3:
            return "UNVERIFIED"
        # Explicit expectation, low match: a SUBSTANTIAL result is still a real
        # answer â€” commit honestly as UNVERIFIED; only weak stubs FAIL.
        return "UNVERIFIED" if len(_without_marker) >= 200 else "FAILED"
