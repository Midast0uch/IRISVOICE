"""Node executor — one DER node runs as a bounded work loop (execution audit, Phase 2).

Owner decision (2026-10-01) supersedes the engine choice below: the loaded
TOOL MODEL (role tool_execution) runs node calls; the Brain only for vision.
The 2026-09-29 failure was a small model choosing ONE tool from a goal string;
here it runs the full loop with the request, earlier results and tool results.

Owner decision (2026-09-29): ONE engine. The DER-DAG stays the planner and
brancher; each node runs a bounded loop through ``run_node(goal, ctx)``, in
this module and not in agent_kernel.py. The old seam — "one node = one tool
call picked by the small tool model from a goal string" — is replaced here.

Why: eval re-runs on 2026-09-29 showed the 2.6B tool model resolving
"Fix the off-by-one error in mathutils.py" to read_file six times in a row;
the same task passed only in the run where it happened to pick edit_file.

Inside a node the Brain sees the goal, the earlier node results, and its own
tool calls with their results word for word. It calls tools natively (the
Brain is the pen: it writes file bodies itself). The node ends when the Brain
answers without a tool call, or when the node's time budget runs out — a round
count never ends it. A tool exception becomes a typed tool result the Brain can
react to. The Brain closes each node with `STATUS: done` or `STATUS: failed:
<reason>`; a failing last command is always stated in the step result, so the
verifier and the final answer see it. (An earlier rule failed every node whose
last command exited non-zero; that failed "run the tests to see the errors"
steps and DER retried them four times - coding eval c11/c14, 2026-09-29.)
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from backend.agent.inference.errors import EmptyModelResponseError, MalformedToolCallError

logger = logging.getLogger(__name__)

# The tool menu inside a node - ONE menu in both modes (owner 2026-10-01:
# developer mode differs only by self-modification; 2026-10-03: nodes are
# universal). The mode's capability filter (CapabilitySet.blocked_tools, in
# the tool bridge's list) still takes run_command and git out in personal
# mode; the web toggle alone adds or removes search and the browser.
NODE_TOOLS = (
    "read_file", "edit_file", "write_file", "grep_files", "glob_files",
    "list_directory", "create_directory", "run_command", "git_status", "git_diff",
    "read_command_output", "stop_command",
    # Live browser control (owner 2026-10-02: developer mode too). The base
    # tool list holds these only while the web toggle is ON - the one gate.
    "browser_open", "browser_observe", "browser_act", "browser_explore",
    # Web research (also web-toggle gated) and the user's own desktop.
    "search", "crawler_query",
    "open_url", "launch_app", "open_file", "get_system_info", "recall_memory",
)

# The screen family joins the menu only when the step's goal is about the
# screen (tool_decision._vision_relevant - the rule the decision box used),
# so a coding node is not offered clicks at screen coordinates.
NODE_SCREEN_TOOLS = (
    "take_screenshot", "vision_analyze_screen", "gui_click", "gui_type", "gui_press_key",
)

_SYSTEM = (
    "You are doing ONE step of a larger task. Files are in the project folder "
    "(written `.`). Use the tools to do the step, then answer with a short plain "
    "summary of what you did and what the result was — with no tool call.\n"
    "Rules:\n"
    "- Paths are relative to the project folder: `main.py`, `pkg/mod.py`.\n"
    "- Read a file before you change it.\n"
    "- Change an existing file with edit_file: `old` must be copied exactly from "
    "the file and match once. Use write_file only for a new file or a full rewrite.\n"
    "- When the step is about behaviour, run the tests with run_command and read "
    "the result. A non-zero exit code means it failed.\n"
    "- Do only this step: later steps do the rest of the task. Stop as soon as "
    "this step's goal is met. Do not ask the user questions.\n"
    "End your final answer with one line: `STATUS: done` when the step's goal is "
    "met (a step that only has to OBSERVE failing tests is met once you saw "
    "them), or `STATUS: failed: <reason>` when it is not.\n"
    "When a tool call will finish the step, set its `step_done` argument to true "
    "and put a one-line summary of the step in `step_summary`: if every tool call "
    "in that answer succeeds, the step ends there and you are not asked again."
)

# Every node tool takes these two optional arguments (owner 2026-10-01). A
# model that sends tool calls leaves the text part empty (gemma via Ollama:
# 0 of 15 steps closed through a STATUS line in the tool answer), but it fills
# arguments, so the closing signal rides on the call. Removed before dispatch.
_CLOSE_ARGS = {
    "step_done": {"type": "boolean",
                  "description": "true when this call finishes the step"},
    "step_summary": {"type": "string",
                     "description": "with step_done: one line on what the step did"},
}


# The least of each call's result a closing answer keeps (its head). The
# step's evidence window downstream (agent_kernel._step_evidence_cap) holds
# this much per call.
NODE_BLOCK_HEAD = 2500

# A page with this few marked elements is one the element list cannot carry
# (canvas, images, charts): the vision model reads the screenshot instead.
_POOR_DOM_MARKS = 3
_SCREENSHOT_NOTE = (
    "The marked screenshot of the page: each numbered box is the element_id "
    "for browser_act."
)
_OLD_SCREENSHOT = "[an earlier page screenshot was here; only the newest is kept]"


def _screenshot(raw: Any) -> str:
    """The JPEG base64 of a browser_observe result's marked screenshot, or ""."""
    if not isinstance(raw, dict):
        return ""
    shot = raw.get("marked_screenshot")
    return str(shot.get("b64") or "") if isinstance(shot, dict) else ""


def _drop_old_screenshots(messages: List[Dict[str, Any]]) -> None:
    """Keep at most one image in the history: each costs ~1k tokens and an
    old page state only misleads."""
    for m in messages:
        if isinstance(m.get("content"), list) and any(
                isinstance(p, dict) and p.get("type") == "image_url" for p in m["content"]):
            m["content"] = _OLD_SCREENSHOT


def _with_close_args(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for t in tools:
        fn = dict(t.get("function") or {})
        params = dict(fn.get("parameters") or {"type": "object"})
        params["properties"] = {**(params.get("properties") or {}), **_CLOSE_ARGS}
        fn["parameters"] = params
        out.append({**t, "function": fn})
    return out


@dataclass
class NodeContext:
    generate: Callable[..., tuple]            # router.generate(role, messages, tools=..., ...)
    execute: Callable[[str, dict], Any]       # dispatch one tool -> raw result
    format_result: Callable[[str, Any], str]  # (tool, raw) -> text for the model
    tools: List[Dict[str, Any]]               # OpenAI function schemas
    prior_results: List[Dict[str, Any]] = field(default_factory=list)
    # The user's request word for word. The step goal is the planner's
    # paraphrase and drops details (coding eval c10, 2026-09-29: the goal kept
    # "add, remove and count" but lost "qty <= 0 raises ValueError").
    task: str = ""
    workdir: str = ""
    budget_s: float = 300.0
    # A node is ONE step now (owner 2026-10-03), not the old composite of
    # steps the 300 s budget was sized for. Measured 2026-10-03 over 1,334
    # successful nodes in logs/iris.log: 93% made <= 5 tool calls, 99% <= 12.
    # Live the same day a browser node clicked through linked articles for
    # its whole 300 s (~22 calls). At this many calls the node closes and
    # reports whether its step is met; the DER decides what comes next.
    max_calls: int = 12
    max_tokens: int = 8192
    result_chars: int = 8000
    conv_id: str = ""
    # Owner decision: the Oracle advises and records shadow rows in node
    # loops. Called with (tool, params) for every Brain call; must not block.
    on_call: Optional[Callable[[str, dict], None]] = None
    # Owner 2026-10-01: the loaded tool model does node tool calls; the Brain
    # only for vision work. An unbound tool_execution role falls back to the
    # router's default role (router.resolve), i.e. the Brain.
    role: str = "tool_execution"
    # Eval C (owner 2026-10-02): the Brain helps a STRUGGLING tool model. Set
    # only when the helper is a different model than `role` (a model cannot
    # help itself); None = no helper. One handover per node at most.
    helper_role: Optional[str] = None
    # V8 (audit addendum 2026-10-02): the marked page screenshot that
    # browser_observe returns. `sees(role)` - the model on that role takes
    # images: it gets the screenshot itself. Otherwise `look(jpeg_b64,
    # question)` asks the resolved vision model (any tier) for a short text
    # reading - only on a page the element list cannot carry, or when the
    # model asks. None = no vision on this path.
    sees: Optional[Callable[[str], bool]] = None
    look: Optional[Callable[[str, str], str]] = None
    # What the STEP is graded on and where it comes from (2026-10-02 audit:
    # the verifier grades the node's result against expected_output, which
    # the node never saw; a split child got only a machine "RESOLVE: ..."
    # anchor; a vetoed step lost the reviewer's reason).
    expected: str = ""
    parent_goal: str = ""
    review_note: str = ""
    # Natural split (owner 2026-10-04): the calls ONE model answer asks for
    # are sibling nodes of the DAG. (name, params) -> True when that call may
    # run side by side with its siblings (no side effect, no exclusive
    # resource). None = every batch runs in order.
    parallel_ok: Optional[Callable[[str, dict], bool]] = None


@dataclass
class NodeResult:
    success: bool
    summary: str
    calls: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""
    last_command_failed: bool = False
    helped: str = ""  # why the helper took over ("" = it did not)

    def as_step_result(self) -> str:
        lines = [self.summary.strip() or "(no summary)"]
        if self.calls:
            lines.append("\nActions:")
            lines += [f"- {c['tool']} {c['target']} -> {'ok' if c['ok'] else 'FAILED'}" for c in self.calls]
        if self.last_command_failed:
            lines.append("\nThe last command in this step exited non-zero.")
        if self.error:
            lines.append(f"\n[node error: {self.error}]")
        return "\n".join(lines)


_STATUS = re.compile(r"^\s*STATUS:\s*(done|failed)\b:?\s*(.*)$", re.I | re.M)


def _status(text: str) -> tuple:
    """(ok, reason, text without the STATUS line). No line = done."""
    matches = list(_STATUS.finditer(text or ""))
    if not matches:
        return True, "", text or ""
    m = matches[-1]
    clean = (text[:m.start()] + text[m.end():]).strip()
    return m.group(1).lower() == "done", m.group(2).strip(), clean


def _call_key(name: str, params: Optional[dict]) -> Optional[str]:
    """The identity of one call after the close args are removed - the same
    key the batch loop uses for its repeat check."""
    if params is None:
        return None
    return json.dumps([name, params], sort_keys=True, default=str)


def _prefetch_siblings(ctx: "NodeContext", tool_calls: List[Dict[str, Any]],
                       allowed: set) -> Dict[str, Any]:
    """Natural split (owner 2026-10-04): when EVERY call of one model answer
    may run side by side (ctx.parallel_ok: no side effect, no exclusive
    resource), run them at once and return {call key: raw result}; the batch
    loop then settles them in the model's order exactly as before. Live r09
    (three facts): one node's three searches ran 2.5 + 3.6 + 3.3 s in a row.
    Any other batch -> {} (runs in order)."""
    if ctx.parallel_ok is None or len(tool_calls) < 2:
        return {}
    jobs: Dict[str, tuple] = {}
    for tc in tool_calls:
        fn = tc.get("function") or {}
        name = fn.get("name", "")
        raw_args = fn.get("arguments") or "{}"
        try:
            params = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except (ValueError, TypeError):
            return {}
        if not isinstance(params, dict) or name not in allowed:
            return {}
        params = {k: v for k, v in params.items() if k not in ("step_done", "step_summary")}
        try:
            if not ctx.parallel_ok(name, params):
                return {}
        except Exception:  # noqa: BLE001 - unsure = in order
            return {}
        jobs.setdefault(_call_key(name, params), (name, params))
    if len(jobs) < 2:
        return {}
    from concurrent.futures import ThreadPoolExecutor

    def _run(name: str, params: dict) -> Any:
        try:
            return ctx.execute(name, params)
        except Exception as exc:  # noqa: BLE001 - typed result, as in the loop
            return {"success": False, "error": f"{type(exc).__name__}: {exc}", "error_type": "exception"}

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="node-sibling") as pool:
        futs = {k: pool.submit(_run, n, p) for k, (n, p) in jobs.items()}
        out = {k: f.result() for k, f in futs.items()}
    logger.info("[run_node] conv=%s %d sibling calls ran side by side in %.1fs",
                ctx.conv_id, len(jobs), time.monotonic() - t0)
    return out


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    return text[:head] + f"\n... [{len(text) - limit} chars cut] ...\n" + text[-(limit - head):]


_ID_KEYS = ("path", "file_path", "command", "pattern", "query", "url", "handle")

# Tools that change the project: a step that used one does not close in the
# same answer - the model looks at the effect first.
_CHANGE_TOOLS = frozenset({"edit_file", "write_file", "create_directory"})

# Two repeats show a model is stuck (eval C 2026-10-02: 8-14 repeats per
# struggling task at 3, each repeat one more model call before the handover).
_MAX_REPEATS = 2
_REPEAT_HINT = (
    "REPEATED CALL - not run again: you just made this exact call and its result "
    "is above, unchanged. Use that result and take the NEXT action of the step "
    "(for example edit or write the file), or finish the step."
)

_EMPTY_HINT = (
    "Your last answer was empty. Answer with a tool call that does the next "
    "part of the step, or with a short summary and the STATUS line."
)

_UNCHANGED_HINT = (
    "UNCHANGED RESULT: this call returned exactly what your previous call "
    "returned (above). Repeating it changes nothing - take the NEXT action of "
    "the step, or finish the step."
)

_HANDOVER_NOTE = (
    "A stronger model continues this step from here. Trouble so far: {why}. "
    "Use everything above, do what is still missing, then finish the step."
)

_MAX_MALFORMED = 2
_MALFORMED_HINT = (
    "Your last tool call was rejected: its arguments were not valid JSON. Inside "
    "JSON strings write a line break as \\n, a tab as \\t, and a quote as \\\". "
    "Send the tool call again."
)


def _target(params: dict) -> str:
    for key in ("path", "file_path", "command", "pattern", "query", "handle"):
        if params.get(key):
            return str(params[key])[:80]
    return ""


def _failed(raw: Any) -> bool:
    if isinstance(raw, dict):
        if raw.get("success") is False:
            return True
        rc = raw.get("returncode")
        return rc not in (None, 0)
    return False


def _relative(text: str, workdir: str) -> str:
    """Write the project folder as `.` in what the model reads. A small model
    copied the long absolute path and cut it ("c03_rename_across_f" for
    "c03_rename_across_files", eval 2026-10-01); every failed read followed.
    The bridge anchors relative paths to the session folder."""
    if not text or not workdir:
        return text or ""
    base = workdir.rstrip("\\/")
    if len(base) < 4:
        return text
    for form in {base, base.replace("\\", "/"), base.replace("\\", "\\\\")}:
        for sep in ("\\\\", "\\", "/"):
            text = re.sub(re.escape(form + sep), "./", text, flags=re.I)
        text = re.sub(re.escape(form), ".", text, flags=re.I)
    return text


def _user_message(goal: str, task: str, prior: List[Dict[str, Any]], limit: int,
                  expected: str = "", parent_goal: str = "", review_note: str = "") -> str:
    parts = []
    if task.strip() and task.strip() != goal.strip():
        parts.append("THE WHOLE TASK (the user's request, word for word — every rule in it "
                     "applies to this step's work):\n" + _clip(task.strip(), limit))
    if parent_goal.strip():
        parts.append(f"THE STEP THIS PART BELONGS TO: {parent_goal.strip()}")
    parts.append(f"STEP: {goal}")
    if expected.strip() and expected.strip() != goal.strip():
        parts.append(f"DONE WHEN (this step's result is checked against this): {expected.strip()}")
    if review_note.strip():
        parts.append(f"A REVIEWER STOPPED THIS STEP BEFORE, BECAUSE: {review_note.strip()}")
    if prior:
        done = "\n\n".join(
            f"[step {r.get('step')}] {r.get('description', '')}\n{r.get('result', '')}" for r in prior
        )
        parts.append("RESULTS OF EARLIER STEPS:\n" + _clip(done, limit * 3))
    return "\n\n".join(parts)


def _safe_bool(fn: Callable[[str], bool], role: str) -> bool:
    try:
        return bool(fn(role))
    except Exception as exc:  # noqa: BLE001 - unknown means the model does not see
        logger.debug("[run_node] sees(%s) failed: %r", role, exc)
        return False


def _safe_look(ctx: NodeContext, shot: str, question: str) -> str:
    t0 = time.monotonic()
    try:
        reading = str(ctx.look(shot, question) or "").strip()
    except Exception as exc:  # noqa: BLE001 - no reading; the element list still stands
        logger.info("[run_node] conv=%s vision look failed: %r", ctx.conv_id, exc)
        return ""
    # The reading itself (head): a wrong fact that reached an answer must be
    # traceable to its source (live 2026-10-04: "5,510 metres", unprovable).
    logger.info("[run_node] conv=%s vision look %.1fs, %d chars: %r",
                ctx.conv_id, time.monotonic() - t0, len(reading), reading[:200])
    if reading.startswith("Vision unavailable"):
        return ""
    return reading[:1500]


def run_node(goal: str, ctx: NodeContext) -> NodeResult:
    """Run one node to completion. Never raises."""
    allowed = {t.get("function", {}).get("name") for t in ctx.tools}
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _relative(
            _user_message(goal, ctx.task, ctx.prior_results, ctx.result_chars,
                          ctx.expected, ctx.parent_goal, ctx.review_note), ctx.workdir)},
    ]
    tools = _with_close_args(ctx.tools)
    malformed = 0
    # Stuck detector (2026-10-01): a small local model called read_file on the
    # same file ~230 times in one step, each result unchanged; only the 300 s
    # budget ended it. The SAME call right after itself is not run again; three
    # such repeats in a row end the step. A different call in between (an
    # edit, a test run) breaks the run, so re-reading after a change is fine.
    last_key: Optional[str] = None
    last_res_key: Optional[str] = None
    repeats = 0
    role = ctx.role
    helped = ""
    edit_failures = 0

    def _hand_over(why: str) -> bool:
        """Switch this node to the helper model once; True when it happened."""
        nonlocal role, helped, repeats, malformed, last_key, last_res_key
        if helped or not ctx.helper_role or ctx.helper_role == role:
            return False
        logger.info("[run_node] conv=%s helper takes over (%s): %s -> %s",
                    ctx.conv_id, why, role, ctx.helper_role)
        role, helped = ctx.helper_role, why
        repeats = malformed = 0
        last_key = last_res_key = None
        return True
    calls: List[Dict[str, Any]] = []
    last_command_failed: Optional[bool] = None
    deadline = time.monotonic() + ctx.budget_s
    text = ""
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 5:
                break
            try:
                text, _think, tool_calls = ctx.generate(
                    role, messages, tools=tools, max_tokens=ctx.max_tokens,
                    temperature=0.2, timeout_s=min(remaining, 300.0), thinking=False,
                )
            except (MalformedToolCallError, EmptyModelResponseError) as slip:
                # A model slip, not a dead server: the server rejected the
                # model's own tool-call JSON (raw line breaks inside file text),
                # or the model answered with nothing at all. It goes back to the
                # model; more than two in a row fail the step.
                malformed += 1
                logger.info("[run_node] conv=%s model slip %s (%d in a row)",
                            ctx.conv_id, type(slip).__name__, malformed)
                if malformed > _MAX_MALFORMED:
                    if _hand_over(f"{malformed} model slips in a row"):
                        messages.append({"role": "user", "content": _HANDOVER_NOTE.format(
                            why="the previous model's answers were empty or invalid")})
                        continue
                    raise
                messages.append({"role": "user", "content": (
                    _MALFORMED_HINT if isinstance(slip, MalformedToolCallError) else _EMPTY_HINT)})
                continue
            malformed = 0
            if not tool_calls:
                # The model judges its own step (it knows whether failing tests
                # were the goal or the problem); the failing last command is
                # still stated in the step result for the verifier and the turn.
                ok, reason, summary = _status(text or "")
                if not ok and _hand_over(f"step reported failure: {reason}"[:120]):
                    messages.append({"role": "assistant", "content": text or ""})
                    messages.append({"role": "user", "content": _HANDOVER_NOTE.format(
                        why=f"the step reported failure ({reason or 'no reason'})")})
                    continue
                logger.info("[run_node] conv=%s done: %d call(s), success=%s, last_cmd_failed=%s",
                            ctx.conv_id, len(calls), ok, bool(last_command_failed))
                return NodeResult(ok, summary, calls, reason if not ok else "",
                                  last_command_failed=bool(last_command_failed), helped=helped)
            messages.append({"role": "assistant", "content": text or None, "tool_calls": tool_calls})
            batch_failed = False
            batch_results: List[str] = []
            batch_done = False
            batch_changed = False
            batch_summaries: List[str] = []
            pending_shot = ""
            prefetched = _prefetch_siblings(ctx, tool_calls, allowed)
            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name", "")
                raw_args = fn.get("arguments") or "{}"
                try:
                    params = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except (ValueError, TypeError):
                    params = None
                if isinstance(params, dict):
                    if params.pop("step_done", False) is True:
                        batch_done = True
                    _sum = params.pop("step_summary", None)
                    if isinstance(_sum, str) and _sum.strip():
                        batch_summaries.append(_sum.strip())
                key = json.dumps([name, params], sort_keys=True, default=str) if params is not None else None
                if key is not None and key == last_key:
                    repeats += 1
                    logger.info("[run_node] conv=%s repeated call %s %s (%d in a row)",
                                ctx.conv_id, name, _target(params or {}), repeats)
                    if repeats >= _MAX_REPEATS and not _hand_over(
                            f"stuck repeating {name} {_target(params or {})}".strip()):
                        return NodeResult(False, text or "", calls,
                                          f"stuck repeating {name} {_target(params or {})}".strip(),
                                          last_command_failed=bool(last_command_failed),
                                          helped=helped)
                    messages.append({"role": "tool", "tool_call_id": tc.get("id") or name,
                                     "name": name, "content": _REPEAT_HINT})
                    continue
                last_key = key
                if params is None:
                    raw: Any = {"success": False, "error": "arguments were not valid JSON; send a JSON object"}
                elif name not in allowed:
                    raw = {"success": False, "error": f"unknown tool {name!r}; use one of {sorted(allowed)}"}
                else:
                    if ctx.on_call is not None:
                        try:
                            ctx.on_call(name, params)
                        except Exception as exc:  # noqa: BLE001 — advisory only
                            logger.debug("[run_node] shadow hook failed: %r", exc)
                    if key in prefetched:  # a sibling that already ran side by side
                        raw = prefetched[key]
                    else:
                        try:
                            raw = ctx.execute(name, params)
                        except Exception as exc:  # noqa: BLE001 — typed result, the model reacts
                            raw = {"success": False, "error": f"{type(exc).__name__}: {exc}", "error_type": "exception"}
                failed = _failed(raw)
                if failed:
                    # A FAILED call may be retried as is (live 2026-10-02: a
                    # cold-start browser_open timed out at 90 s, the retry was
                    # blocked as a repeat, and the node closed "done" with no
                    # page open). Identical failures in a row are still caught
                    # by the unchanged-result check below.
                    last_key = None
                batch_failed = batch_failed or failed
                batch_changed = batch_changed or (name in _CHANGE_TOOLS and not failed)
                if failed and name == "edit_file":
                    # exact-quote edits are where a small model fails most
                    edit_failures += 1
                    if edit_failures >= 2:
                        _hand_over("edit_file failed twice")
                if name == "run_command":
                    last_command_failed = failed
                # args: the identifying keys only (never a file body) - what
                # memory events and footprints read as "what this step touched".
                calls.append({"tool": name, "target": _target(params or {}), "ok": not failed,
                              "args": {k: params[k] for k in _ID_KEYS
                                       if isinstance(params, dict) and params.get(k)}})
                logger.info("[run_node] conv=%s %s %s -> %s", ctx.conv_id, name,
                            _target(params or {}),
                            ("FAILED: " + str(raw.get("error") if isinstance(raw, dict) else raw)[:160])
                            if failed else "ok")
                content = _clip(_relative(ctx.format_result(name, raw) or "", ctx.workdir),
                                ctx.result_chars)
                # No progress also shows as the SAME result for the same tool and
                # target right after itself, even when the arguments jitter
                # (2026-10-02: read_file start_line 51 of a 6-line file, 224x).
                res_key = json.dumps([name, _target(params or {}), content])
                if res_key == last_res_key:
                    repeats += 1
                    logger.info("[run_node] conv=%s unchanged result %s %s (%d in a row)",
                                ctx.conv_id, name, _target(params or {}), repeats)
                    if repeats >= _MAX_REPEATS and not _hand_over(
                            f"stuck repeating {name} {_target(params or {})}".strip()):
                        return NodeResult(False, text or "", calls,
                                          f"stuck repeating {name} {_target(params or {})}".strip(),
                                          last_command_failed=bool(last_command_failed),
                                          helped=helped)
                    content = _UNCHANGED_HINT
                else:
                    last_res_key, repeats = res_key, 0
                # An unchanged page needs no second look.
                shot = _screenshot(raw) if not failed and content != _UNCHANGED_HINT else ""
                if shot:
                    if ctx.sees is not None and _safe_bool(ctx.sees, role):
                        pending_shot = shot
                    elif ctx.look is not None:
                        question = str((params or {}).get("question") or "").strip()
                        marks = raw.get("marks") if isinstance(raw.get("marks"), list) else []
                        if question or len(marks) <= _POOR_DOM_MARKS:
                            reading = _safe_look(ctx, shot, question or goal)
                            if reading:
                                content += ("\n\nWhat the vision model sees on the "
                                            "screenshot:\n" + reading)
                batch_results.append(f"[{name} {_target(params or {})}]\n{content}")
                messages.append({
                    "role": "tool", "tool_call_id": tc.get("id") or name, "name": name,
                    "content": content,
                })
            if pending_shot:
                # After the tool messages (a tool message carries text only on
                # most APIs), as the user turn the model reads next.
                _drop_old_screenshots(messages)
                messages.append({"role": "user", "content": [
                    {"type": "text", "text": _SCREENSHOT_NOTE},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{pending_shot}"}},
                ]})
            # Closed in the same answer (owner 2026-10-01): the step's last
            # call used to cost one more model call only to hear "done". The
            # summary was written before the results, so the results go with it
            # (later steps read them instead of reading the files again). Any
            # failed tool still gets the follow-up call.
            # Not after a change (2026-10-02, eval C c12): a small model set
            # step_done on its own edit, the edit "succeeded" as a call, and
            # the step closed with a buggy method nobody ran. A step that
            # changed a file looks at the effect first - one more call.
            if not batch_failed and not batch_changed and (batch_done or _STATUS.search(text or "")):
                ok, _reason, summary = _status(text or "")
                if batch_done:
                    ok = True
                    summary = "\n".join(batch_summaries) or summary
                if ok:
                    logger.info("[run_node] conv=%s done in the tool answer: %d call(s), "
                                "last_cmd_failed=%s", ctx.conv_id, len(calls),
                                bool(last_command_failed))
                    # Each call keeps its own head: the answer sits near the
                    # top of a result (186 stored searches: the fact at char
                    # <= 2,144), and one head+tail window over three joined
                    # 9k results dropped the middle one whole (eval r09
                    # conv-810: three searches, the reply said two were missing).
                    _share = max(ctx.result_chars // max(1, len(batch_results)),
                                 NODE_BLOCK_HEAD)
                    _blocks = [_b if len(_b) <= _share
                               else _b[:_share] + "\n[...rest of this result cut...]"
                               for _b in batch_results]
                    return NodeResult(True, (summary + "\n\nTool results:\n"
                                             + "\n\n".join(_blocks)).strip(),
                                      calls, last_command_failed=bool(last_command_failed),
                                      helped=helped)
            if len(calls) >= ctx.max_calls:
                break
        # Calls or time spent with work still requested: the node closes and
        # says honestly whether its step is met - only an explicit
        # `STATUS: done` counts; the DER verifies and decides what is next.
        why = (f"step call limit reached ({len(calls)} calls)" if len(calls) >= ctx.max_calls
               else "node time budget used up")
        messages.append({"role": "user", "content": (
            f"Stop here: {why}. Say in a few lines what you did and what you found. End "
            "with `STATUS: done` if this step's goal is met, or `STATUS: failed: <what is "
            "missing>`.")})
        text, _think, _ = ctx.generate(role, messages, tools=None, max_tokens=1024,
                                       temperature=0.2, timeout_s=120.0)
        ok, reason, summary = _status(text or "")
        ok = ok and bool(_STATUS.search(text or ""))
        logger.info("[run_node] conv=%s closed (%s): %d call(s), success=%s",
                    ctx.conv_id, why, len(calls), ok)
        return NodeResult(ok, summary if ok else (text or ""), calls,
                          "" if ok else (reason or why),
                          last_command_failed=bool(last_command_failed), helped=helped)
    except Exception as exc:  # noqa: BLE001 — a broken node is a failed step, not a crashed turn
        logger.warning("[run_node] conv=%s failed: %s", ctx.conv_id, exc)
        return NodeResult(False, text or "", calls, f"{type(exc).__name__}: {exc}", helped=helped)
