#!/usr/bin/env python3
"""
Agent Kernel

Orchestrates the dual-LLM system with:
- lfm2-8b for reasoning and planning
- lfm2.5-1.2b-instruct for tool execution
- Inter-model communication and state management
- Model failure fallback to single-model mode
"""

from __future__ import annotations

import re
import hashlib
import threading
import os

from .model_conversation import ModelConversation
from .inter_model_communication import InterModelCommunicator
from .vps_gateway import VPSGateway, VPSConfig
from .personality import PersonalityManager
from .memory import ConversationMemory, TaskRecord
from .model_router import ModelRouter
from .tool_bridge import AgentToolBridge
from .mcm_protocol.actions.pacman_fragment import is_external_tool
# REMOVED 2026-08-26 (session 260): `from backend.llm_service import llm as _llm`.
# MEASURED with `python -X importtime`: that import pulled in litellm, which was
# 6.26s of a 9.63s total -- 65% of the cost of importing this module -- and
# `_llm` was NEVER USED. Its only remaining mention is the docstring below at
# _dispatch_api: "Uses httpx directly instead of _llm.complete() to avoid
# thread-pool hangs." The code was deliberately moved onto httpx and the import
# was left behind. Nothing imports `_llm` from this module (checked).
#
# This is not only a test-suite problem. backend startup imports this module, so
# the same 6.26s was paid on every launch.
from . import streaming as _streaming
from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.errors import RateLimitedError
from backend.agent.call_context import (
    CallClass,
    set_call_class,
    restores_call_class,
)
# GROUND TRUTH REQ-13: named counters for swallowed write-path failures.
# Pure in-process tally (threading only) - safe at module scope.
from backend.agent import write_counters as _write_counters
from backend.agent import row_sequence as _row_sequence






from backend.agent.tool_decision import ToolDecisionBox, Decision, DecisionKind, DispatchResult
from backend.iris_config import load_config
from typing import Any, Dict, Optional, List, Callable, Tuple, Sequence
import json
import asyncio
import logging
import time
from dataclasses import dataclass, field
from backend.utils.observability import (
    TurnMetrics,
    loud_error,
    get_turn_id,
    broadcast_inference_event,
)







_MONITOR_STATEMENT_CHARS = 900


def _monitor_statement(objective: str, completed_items, n: int = 4) -> str:
    """The Oracle's input for the `done` / `on_track` monitors: the objective
    and one bounded status line per recent step (~150-250 tokens).

    They used to score the Brain's whole continuation prompt, cut at the
    engine's 512-id cap: the instructions plus raw step outputs, so every
    call ran the longest input the model takes - `done` p50 2.3 s, max 4.3 s
    over 69 calls of one coding eval (2026-10-01), against ~0.2 s for a short
    input. The question needs the goal and what each step returned, nothing
    more. Shape change = new calibrated identity: rows carry criteria v2.
    """
    # Newest step first: the engine cuts the text at the job's budget (Oracle
    # jobs, judge_goal = 128 ids), and the cut must drop the OLDEST step.
    lines = [f"OBJECTIVE: {str(objective or '')[:200]}", "STEPS (newest first):"]
    for it in reversed(list(completed_items or [])[-n:]):
        env = getattr(it, "envelope", None)
        try:
            state = env.line() if env is not None else (
                str(getattr(it, "result", "") or "")[:160])
        except Exception:  # noqa: BLE001 - a status line is best-effort
            state = ""
        lines.append(
            f"[{getattr(it, 'step_number', '?')}] "
            f"{str(getattr(it, 'description', '') or '')[:80]}: {state[:200]}"
        )
    return "\n".join(lines)[:_MONITOR_STATEMENT_CHARS]


def _der_physics_settle(owner, session_id: str) -> None:
    """Fold-back point of the physics side lane.

    Call this right before a DECISION about the next step's shape reads the
    Caducean state (split width, stuck-streak topology override, plan
    expansion under COMPRESS). It waits until this session's newest update
    has moved the integrator (``fold.ready``; FIFO, so every earlier update
    moved it first) â€” not for that job's bookkeeping. Past
    DER_PHYSICS_FOLD_WAIT_S the decision proceeds on the last settled
    position; the update itself is never cancelled.
    """
    pending = getattr(owner, "_der_physics_pending", None)
    fold = pending.get(session_id) if pending else None
    if fold is None or fold.ready.is_set():
        return
    from backend.utils.durability_queue import lane

    if lane("physics").in_worker():
        return  # the lane never waits on work queued behind itself
    from backend.agent.der_constants import DER_PHYSICS_FOLD_WAIT_S

    t0 = time.monotonic()
    landed = fold.ready.wait(DER_PHYSICS_FOLD_WAIT_S)
    waited = time.monotonic() - t0
    if not landed:
        logger.warning(
            "[DER] physics fold-back session=%s step=%s not landed after %.1fs "
            "- deciding on the last settled position",
            session_id, fold.step, waited,
        )
    elif waited >= 0.5:
        logger.info(
            "[DER] physics fold-back session=%s step=%s waited %.2fs",
            session_id, fold.step, waited,
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




def _plan_step_deps(raw_step: dict, earlier: list) -> list:
    """The edges of one planned step (parallel nodes, owner 2026-10-04):
    ["start"] (or "none") = needs no earlier result; empty or missing = the
    step before (a chain is the safe default); otherwise the named steps."""
    deps = [str(d) for d in (raw_step.get("depends_on") or []) if str(d).strip()]
    if any(d.strip().lower() in ("start", "none") for d in deps):
        return [d for d in deps if d.strip().lower() not in ("start", "none")]
    if deps:
        return deps
    return [earlier[-1].step_id] if earlier else []






def _mycelium_ingest_step_tools(memory, item, step_success: bool, total_steps: int, session_id: str) -> None:
    """Tell the toolpath space which tools a settled step ACTUALLY called: one
    ingest per call, in order, all at the step number. ``item.tool`` is only the
    PLANNED tool and is empty for a node step (the tool model picks its tools
    while the step runs) - recording it stored "tool_none" for 73 of 154 live
    toolpath nodes. A step that made no call still records "none": that is the
    truth. Module level on purpose (stand-in kernels)."""
    if not memory:
        return
    calls = _step_calls(item)
    # (name, success) per call; the call's own ok only ever lowers the step's verdict
    signals = [(str(c.get("tool") or "none"), bool(step_success) and bool(c.get("ok", True)))
               for c in calls] or [("none", step_success)]
    for name, ok in signals:
        memory.mycelium_ingest_tool_call(
            tool_name=name,
            success=ok,
            sequence_position=item.step_number,
            total_steps=total_steps,
            session_id=session_id,
        )


def _plan_steps_open(plan, queue) -> int:
    """How many steps of the ORIGINAL plan are still in the queue and not yet
    settled (pending or running). A steering re-plan removes the steps it
    replaces, so they stop counting. Module level: stand-in kernels."""
    ids = {getattr(s, "step_id", None) for s in (getattr(plan, "steps", None) or [])}
    ids.discard(None)
    if not ids:
        return 0
    settled = set(queue.completed_ids) | set(queue.vetoed_ids) | set(queue.failed_ids)
    present = {getattr(it, "step_id", None) for it in (getattr(queue, "items", None) or [])}
    return len((ids & present) - settled)


def _step_tool_name(item) -> str:
    """The tool a settled step really used, for its tool:result / tool:error.

    A DER-DAG node has no item.tool (the planner writes goals; the node picks
    its tools), so the old ``item.tool or "direct"`` labelled every node
    "direct": the matrix verb read DIRECT and the frontend counted the settled
    card as tool-less and dropped it (live 2026-10-06). The node's decisive
    call names the tool; "direct" stays only for a node that made no call."""
    tool = getattr(item, "tool", None)
    if tool:
        return str(tool)
    call = _step_decisive_call(item)
    return str(call.get("tool")) if call and call.get("tool") else "direct"


# A goal that ACTS on a web page (browser control, not a search). "type of" and
# "press release" are reading phrases, not actions.
_BROWSER_ACTION_RE = re.compile(
    r"\b(?:in\s+the\s+(?:live\s+|in-app\s+)?browser|click|tap|type(?!\s+of)|"
    r"fill(?:\s+(?:in|out))?|scroll|press(?!\s+release)|submit|log\s?in|sign\s?in|"
    r"select|add\s+to\s+(?:cart|basket)|check\s?out|navigate|hover|drag)\b",
    re.IGNORECASE,
)


# The user names the live browser: the request cannot be done without it.
_LIVE_BROWSER_RE = re.compile(
    r"\b(?:live|in-app)\s+browser\b|\bin\s+the\s+browser\b", re.IGNORECASE,
)


_CLAIMS_MISSING_RE = re.compile(
    r"\b(?:did\s+not|didn't|does\s+not|doesn't|do\s+not|could\s+not|couldn't|"
    r"unable\s+to|failed\s+to|not\s+able\s+to)\b[^.\n]{0,60}?\b(?:include|return|"
    r"contain|find|found|provide|verify|confirm|retrieve|give)\b"
    r"|\bmissing\s+information\b|\bnot\s+(?:returned|found|included|available)\b",
    re.IGNORECASE,
)


def _claims_missing(reply: str) -> bool:
    """The reply says part of the answer is missing ("the tool results did not
    include the height...", "failed to verify the year"). Module level
    (stand-in kernels)."""
    return bool(_CLAIMS_MISSING_RE.search(reply or ""))


def _node_failed_after_change(item) -> bool:
    """True when a node step changed files and the LAST command it ran after
    its last change failed. A planner step carries no expected_output (the
    planner emits goals only), so a node step was VERIFIED whenever its tool
    calls ran - also when the tests it ran on its own edit failed. A step that
    only OBSERVES failing tests (no change, eval c14) is not affected. Outside
    evidence only: the call log, not text. Module level (stand-in kernels)."""
    from backend.agent.node_executor import _CHANGE_TOOLS

    log = getattr(item, "node_call_log", None)
    if not isinstance(log, list):
        return False
    changes = [i for i, c in enumerate(log) if c.get("tool") in _CHANGE_TOOLS and c.get("ok", True)]
    if not changes:
        return False
    runs = [c for c in log[changes[-1] + 1:] if c.get("tool") == "run_command"]
    return bool(runs) and not runs[-1].get("ok", True)




def _step_digest(item) -> str:
    """Repeat-detection key of a settled step: a node step is the calls it
    made (``node_digest``, set by ``_der_run_node``); a direct tool step is
    its tool + params. Module level on purpose (stand-in kernels)."""
    _nd = getattr(item, "node_digest", None)
    if isinstance(_nd, str) and _nd:
        return _nd
    from backend.agent.tool_envelope import params_digest

    return params_digest(getattr(item, "tool", None), getattr(item, "params", None))


_TURN_END_FOLD_WAIT_S = 20.0


def _turn_end_submit(owner, session_id: str, job) -> None:
    """C5: run the turn-end bookkeeping (card footprint, plan stats, episode
    + landmark crystallization, skill capture) on lane("memory_events"), the
    store's ordered writer, instead of before the reply's synthesis (measured
    2-8.5 s per task, 2026-10-01). The next turn of this kernel folds back on
    ``owner._turn_end_pending`` before it reads memory. A dropped submit (lane
    full) runs the job inline: an episode is never lost. Module level on
    purpose (stand-in kernels)."""
    import threading as _th

    done = _th.Event()

    def _run():
        try:
            job()
        except Exception as exc:  # noqa: BLE001 - each part logs its own failure
            logger.warning("[DER] turn-end bookkeeping failed session=%s: %r", session_id, exc)
        finally:
            done.set()

    owner._turn_end_pending = done
    from backend.utils.durability_queue import lane

    if not lane("memory_events").submit("turn_end", _run):
        logger.warning("[DER] turn-end lane full session=%s - bookkeeping inline", session_id)
        _run()


# A spoken turn reaches the agent as text, so nothing told the planner or a step that IRIS heard it. Live
# 2026-10-25 22:15: "Okay. Can you hear me?" planned "Verify audio input", every step answered "I cannot
# process audio", the goal contract never covered and the Explorer added 7 steps - 99 s to the first word.
# Module level on purpose: stand-in kernels bind only some methods.
_VOICE_TURN_NOTE = (
    "CHANNEL: the user said this aloud. IRIS heard it through the microphone and speech recognition, "
    "and IRIS's reply is spoken aloud. You can hear the user."
)


_STUB_STOPWORDS = frozenset(
    "the and but for with are was were this that you your our they them their its has have had not "
    "can will would should could let lets just now here there what which who how".split()
)


def _short_reply_carries_results(text: str, step_results) -> bool:
    """A short synthesis is an ANSWER, not a stub, when it repeats what the steps found: at least two of its
    content words (3+ letters, not stopwords), and at least half of them, appear in the step results. A stub
    ("Let's attempt that.") says nothing the steps found. Live 2026-10-26: the correct one-sentence reply
    "My test word is a blue pelican." (31 chars) fell under the 40-char floor twice and the user got the
    deterministic "I've completed the task." close instead - the usual source of that reply."""
    words = {w for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in _STUB_STOPWORDS}
    if len(words) < 2:
        return False
    found = " ".join(str((r or {}).get("result") or "") for r in (step_results or [])).lower()
    hits = sum(1 for w in words if w in found)
    return hits >= 2 and hits * 2 >= len(words)


def _voice_turn_note(owner) -> str:
    return _VOICE_TURN_NOTE if getattr(owner, "_turn_from_voice", False) else ""




def _turn_end_settle(owner) -> None:
    """Fold-back of _turn_end_submit: wait until this kernel's last turn-end
    bookkeeping landed (the episode the planner may recall). Bounded: past
    the wait the turn proceeds on what has landed; the job is never cancelled."""
    done = getattr(owner, "_turn_end_pending", None)
    if done is None or done.is_set():
        return
    from backend.utils.durability_queue import lane

    if lane("memory_events").in_worker():
        return
    t0 = time.monotonic()
    landed = done.wait(_TURN_END_FOLD_WAIT_S)
    waited = time.monotonic() - t0
    if not landed:
        logger.warning("[DER] turn-end fold-back not landed after %.1fs - proceeding", waited)
    elif waited >= 0.5:
        logger.info("[DER] turn-end fold-back waited %.2fs", waited)


def _gc_coverage_label(verified: str, item, step_result) -> str:
    """The label a settled node gives the goal contract's coverage (goal_contract.mark_coverage).

    A DIRECT node (no tool: the node mode rule decided so) has
    nothing outside that could verify it, so a real answer commits UNVERIFIED for ever -
    and a fact it answered could never be covered: the turn pushed "cover the open fact"
    with more tool-less steps, BLOCKED the fact after 2 pushes and told the user it "could
    not cover" what it had just answered. Live 2026-10-27: "Pack sunscreen to protect your
    skin from the sun." for "in one short sentence, name one thing to pack for a beach
    trip" - 3 steps and a false "could not cover" note. Such an answer is ANSWERED: it
    covers a fact under the same own-terms / names rule as a verified result. Coverage
    is "addressed", not evidence - the evidence ladder never sees this label.
    Module level on purpose (stand-in kernels bind only some methods).
    """
    try:
        from backend.agent.external_reference import DIRECT

        if (verified == "UNVERIFIED" and getattr(item, "mode", None) == DIRECT
                and str(step_result or "").strip()):
            return "ANSWERED"
    except Exception as exc:  # noqa: BLE001 - the plain label stands
        logger.debug("[goal-contract] coverage label fell back: %r", exc)
    return verified


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






def _der_budget_exit(tokens_used: int, token_budget: int, elapsed_s: float,
                     turn_budget_s: float, queue) -> Optional[str]:
    """Which budget cut the DER loop short: "tokens", "turn_time" or "steps"; None
    when the plan ran to the end. Mirrors the loop condition, so the BUDGET_HIT
    event is typed by the SAME test that stopped the loop. Module level (stand-ins)."""
    if queue.is_complete():
        return None
    if tokens_used >= token_budget:
        return "tokens"
    if elapsed_s >= turn_budget_s:
        return "turn_time"
    if queue.hit_cycle_limit():
        return "steps"
    return None




def _der_prior_research_delivered(owner, item, step_result, session_id: str) -> None:
    """A PRIOR RESEARCH section at the head of a tool result IS memory delivered to the
    step that ran the tool (research_memory.attach_prior put it there)."""
    try:
        from backend.agent.research_memory import PRIOR_HEADING

        if PRIOR_HEADING in str(step_result or ""):
            _der_recall_delivered(owner, item, "prior_research", [], session_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[memory_events] prior research delivery not typed: %s", exc)


def _der_topology_halt(owner, session_id: str) -> None:
    """Stop the line on a TOPO_VIOLATION (rec==3) at a step boundary.

    The rec==3 raise inside the physics job never reached the loop: finalize's
    broad except (later the lane job) swallowed it, and every shape-decision
    read sits inside an advisory try â€” so _der_execute_with_recovery's targeted
    recovery never ran in production (MCM pin_22b078571d73, option B). Called
    on the loop thread OUTSIDE any broad except. Reads only a LANDED update â€”
    never waits (S3: the answer path does not wait for its physics); a later
    landing is caught at the next boundary. Raises once per update, so the
    recovery run does not halt again on the same stale state.
    """
    pending = getattr(owner, "_der_physics_pending", None)
    fold = pending.get(session_id) if pending else None
    if fold is None or not fold.ready.is_set() or fold.rec != 3:
        return
    with fold.lock:
        if getattr(fold, "halted", False):
            return
        fold.halted = True
    from backend.agent.exceptions import TopologyViolationException

    logger.warning(
        "[DER] TOPO_VIOLATION landed session=%s step=%s - halting for recovery",
        session_id, getattr(fold, "step", None),
    )
    _emit_event(owner, "HALTED", evidence="verifier", thread_id=session_id,
                step_index=str(getattr(fold, "step", "") or ""),
                payload={"cause": "TOPO_VIOLATION"})
    raise TopologyViolationException(session_id=session_id)


def _der_neighbors_block(rows) -> str:
    """K2: the "RELEVANT NEIGHBORS" text for the rows that passed the relevance
    gate; "" when there are none, so nothing is injected. Module level on
    purpose (stand-in kernels bind only some methods). Bounded: 3 rows, 160
    chars each."""
    parts = []
    for n in (rows or [])[:3]:
        text = (n.get("insight") or "").strip()
        outcome = (n.get("result") or "").strip()
        # A step row keeps its text in insight and its outcome in result
        # ("success"/"failure"); a long result is the payload head instead.
        text = "{} [{}]".format(text, outcome[:40]) if text and outcome else (text or outcome)
        if text:
            parts.append("{} ({}/{}): {}".format(
                n.get("chain_id") or "",
                n.get("topic_domain") or "?",
                n.get("execution_domain") or "?",
                text[:160],
            ))
    return " | ".join(parts)





# Session 247: turn wall-clock safety net (seconds). Defined UNCONDITIONALLY
# (outside the der_constants import guard) so it exists on both import paths.
# See the DER main loop â€” last-resort bound only; the sufficiency gate and
# zero-yield cutoff are the rational stops, this catches everything else.
_DER_TURN_BUDGET_S = float(os.environ.get("IRIS_DER_TURN_BUDGET_S", "600"))

# REQ-1 AC8 (T2b, Decision 13 â€” revised 2026-08-19): the user-facing copy for
# the child steps of a sub-loop split. `branchLabel` is free text on the
# wire â€” CardChassis's ChassisBranchBadge renders whatever string arrives
# here, so the wording is owned in this ONE constant, not inlined at each
# emit site. NEVER "Sub-Loop" / "Detour" â€” those remain internal identifiers
# (sub_loop_split / is_subloop) and are UNCHANGED; this is the user-facing
# label only.
DER_SUBLOOP_BRANCH_LABEL = "Diving Deeper"

@dataclass
class TaskContext:
    """
    Carries full context through the entire task pipeline.

    This is the single object that carries context from the user's message
    through planning, execution, and response synthesis. It prevents context
    loss at handoff points between the brain and executor models.
    """

    task_id: str  # unique per user message
    user_message: str  # original user request â€” never lost
    session_id: str
    conversation_history: List[Dict]  # snapshot of memory at task start
    conversation_id: str = "default"
    plan: Optional[Dict] = None  # brain's plan (set after planning)
    # accumulates as steps execute
    step_results: List[Dict] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    def get_results_summary(self) -> str:
        """Get a formatted summary of all step results for the brain."""
        if not self.step_results:
            return "No tool results."

        summary_parts = []
        for i, result in enumerate(self.step_results, 1):
            if isinstance(result, dict):
                if "error" in result:
                    summary_parts.append(f"Step {i}: ERROR - {result.get('error')}")
                elif result.get("success"):
                    tool_name = result.get("tool", "unknown")
                    action = result.get("action", "")
                    result_text = result.get("result", result.get("response", ""))
                    # DER evidence is bounded once, per step, by its own window
                    # (_step_evidence_cap); a second 6,000 head+tail cut here
                    # dropped the middle of a three-search node (eval r09
                    # conv-820: "the tools did not return the other two facts").
                    if not result.get("bounded"):
                        result_text = self._bounded_excerpt(result_text)
                    summary_parts.append(
                        f"Step {i}: {tool_name} ({action}): {result_text}"
                    )

        return "\n".join(summary_parts) if summary_parts else "No tool results."

    @staticmethod
    @staticmethod
    def _bounded_excerpt(text: str, cap: int = 6000) -> str:
        """Session 247 (synthesis starvation, conv-44): the old
        ``result_text[:200]`` here chopped the brain's evidence to a URL â€”
        live: 3 usable pages crawled, browser tabs full of content, and the
        synthesis still said "the tool did not retrieve the paper's content"
        because its entire view of the crawl was 200 characters. This is NOT
        pacman (pacman_store/recall were 0 that run) â€” it was a prompt-size
        guard left far too tight. Head+tail excerpt keeps the prompt bounded
        while the brain actually sees the crawl: intro sentences AND the
        closing citation block."""
        t = (text or "").strip()
        if len(t) <= cap:
            return t
        _head = t[: int(cap * 0.7)]
        _tail = t[-int(cap * 0.3):]
        return f"{_head}\n[...{len(t) - cap} chars truncated...]\n{_tail}"




# Formatting rules appended to every prompt that produces USER-FACING prose.
#
# Models do not reliably structure a long answer on their own â€” a multi-tool
# result came back as one unbroken block, which is unreadable in a chat thread
# (2026-08-16). The reply is rendered as markdown, so ask for the structure
# explicitly, and scale it: a one-line answer must NOT grow headings.
_READABLE_FORMAT_RULES = """FORMATTING (your reply is rendered as markdown in a chat thread):
- Short answer (a sentence or two)? Write it plainly. No headings, no bullets.
- Longer answer? Make it scannable instead of one block of prose:
  - open with a short sentence saying what you found
  - `##` headings to separate distinct topics
  - `-` bullets for lists of findings
  - a markdown table for field/value pairs (specs, settings, counts)
  - `backticks` for paths, commands, filenames and code
  - a blank line between blocks â€” never run sections together
- Structure only where it aids reading. Do not pad a short answer to fill it.
- Report what the tools actually returned. If something was not returned, say
  so plainly rather than filling the gap."""


def _developer_mode(kernel) -> bool:
    """True when the app runs in developer mode. The card bound (artifact_policy)
    is a personal-mode rule: developer mode draws EVERY turn as the live matrix
    (execution audit Phase 4: rows appear / run / fold as nodes do). Live
    2026-10-06: the bound withheld every task/tool event of a 3-step developer
    turn, so it showed no rows at all. Module level: stand-in kernels in tests
    bind only some methods."""
    fn = getattr(kernel, "_effective_launcher_mode", None)
    try:
        return callable(fn) and fn() == "developer"
    except Exception:  # noqa: BLE001 - a mode read never blocks the gate
        logger.debug("[AgentKernel] launcher mode read failed", exc_info=True)
        return False


def _edit_diff_fields(item) -> dict:
    """The ``diff`` / ``diffs`` fields of a step's tool:result data ({} when the
    step edited no file). Module level: stand-in kernels in tests bind only some
    methods."""
    eds = getattr(item, "edit_diffs", None)
    if not isinstance(eds, list) or not eds:
        return {}
    return {"diff": eds[-1], **({"diffs": list(eds)} if len(eds) > 1 else {})}












def _remember_turn_urls(kernel, step_result, _where: str = "") -> int:
    """AC2.1 / AC9.3 / AC10.2 (session-319 fix): harvest every URL a step
    touched into turn memory, on ANY path.

    Turn URL memory used to be written ONLY inside `_der_finalize_step`, which
    the step loop skips entirely for a failed step (the loop branches to
    `_der_handle_step_failure` and `continue`s before finalize). So a crawl that
    came back with partial results and was then judged FAILED recorded nothing,
    and the next step re-fetched the same addresses -- the owner's "it still
    recrawls the same URLs if there's an error" report. Calling this from the
    failure path as well closes that hole: the refusal set learns from failures,
    not just successes.

    Deliberately MODULE-LEVEL, not a method: `_der_finalize_step` is driven by
    hand-rolled kernel doubles in the behavioral suite, and a new method on the
    instance would not exist on those doubles. Taking the kernel as an argument
    keeps one implementation usable from both call sites without touching tests.

    NOTE (honest limit): a TOTAL crash whose result text carries no
    `--- Source:`/`--- Attempted:`/`--- Dead:` lines yields nothing here -- the
    addresses are simply not knowable, because `crawler_query` resolves its seeds
    inside the crawler. That residual case can only be closed by recording the
    dispatch itself; tracked separately.

    Best-effort: URL memory is advisory and must never break the loop.
    Returns the number of addresses now held for this conversation.
    """
    try:
        import re as _re_urls
        from backend.agent.tool_envelope import normalize_url as _norm_url
        _conv = getattr(kernel, "conversation_id", None) or ""
        _fetched = set(getattr(kernel, "_der_crawled_urls", {}).get(_conv, set()))
        _text = str(step_result or "")
        for _m in _re_urls.findall(
            r"---\s*Source:\s*(https?://[^\s]+)", _text
        ):
            _n = _norm_url(_m.strip().rstrip(".,;)]"))
            if _n:
                _fetched.add(_n)
        # Attempted seeds count too: re-paying a parked/failed fetch in-turn is
        # exactly the futile-retry loop we are closing (AC9.3).
        for _tail in _re_urls.findall(r"---\s*Attempted:\s*([^\n]+)", _text):
            for _u in _tail.split():
                _u = _u.strip().rstrip(".,;)]")
                if _u.startswith("http"):
                    _n = _norm_url(_u)
                    if _n:
                        _fetched.add(_n)
        # Explicit dead-address memory (AC10.2): zero-page deaths the Attempted
        # line cannot see. Dead joins the refusal set AND its own set.
        for _tail in _re_urls.findall(r"---\s*Dead:\s*([^\n]+)", _text):
            for _u in _tail.split():
                _u = _u.strip().rstrip(".,;)]")
                if not _u.startswith("http"):
                    continue
                _n = _norm_url(_u)
                if not _n:
                    continue
                _fetched.add(_n)
                try:
                    from backend.agent.write_counters import bump as _bump_dead
                    _bump_dead("envelope.dead_hits")
                except Exception:
                    pass
                try:
                    _du = dict(getattr(kernel, "_der_dead_urls", {}))
                    _dub = set(_du.get(_conv, set()))
                    _dub.add(_n)
                    while len(_dub) > 500:
                        _dub.pop()
                    _du[_conv] = _dub
                    kernel._der_dead_urls = _du
                except Exception:
                    pass
        if _fetched:
            _cu = dict(getattr(kernel, "_der_crawled_urls", {}))
            _cu[_conv] = _fetched
            kernel._der_crawled_urls = _cu
        return len(_fetched)
    except Exception:
        return 0  # URL memory is advisory â€” never block the loop


def _recovery_candidates(step_result, env_sources, visited):
    """Session-319: shared candidate extraction for the recovery lane.

    Returns ``(dead, hosts, cands)``:

      ``dead``  â€” addresses the step attempted but did not fetch successfully
      ``hosts`` â€” the distinct hosts those dead addresses belong to
      ``cands`` â€” unvisited, same-host recovery targets: the page's outlinks
                  plus the parent directory of each dead address

    PURE: no state, no side effects, no I/O. Extracted deliberately so the
    bespoke lane and the router-driven producer compute the SAME candidate set
    while they converge into one lane. Two copies of this logic would drift, and
    a drift here means one lane recovers pages the other thinks are already done.

    Returns empty values when nothing is recoverable â€” callers must treat that as
    "no recovery", never as an error.
    """
    import re as _re_c
    from urllib.parse import urlparse as _up
    _attempted = []
    for _tail in _re_c.findall(
        r"---\s*Attempted:\s*([^\n]+)", str(step_result or "")
    ):
        for _u in _tail.split():
            _u = _u.strip().rstrip(".,;)]")
            if _u.startswith("http") and _u not in _attempted:
                _attempted.append(_u)
    _fetched = set(env_sources or [])
    _dead = [u for u in _attempted if u not in _fetched]
    if not _dead:
        return [], set(), []
    _outlinks = []
    _m = _re_c.search(
        r"--- Outlinks[^\n]*\n((?:  - [^\n]+\n?)*)", str(step_result or "")
    )
    if _m:
        for _ln in _m.group(1).splitlines():
            _ln = _ln.strip()
            if _ln.startswith("- "):
                _u = _ln[2:].strip()
                if _u.startswith("http") and _u not in _outlinks:
                    _outlinks.append(_u)
    _hosts = set()
    for _d in _dead:
        try:
            _hosts.add(_up(_d).hostname or "")
        except Exception:
            continue
    _hosts.discard("")
    if not _hosts:
        return _dead, set(), []
    _visited = set(visited or [])
    _cands = []
    for _u in _outlinks:
        try:
            _h = _up(_u).hostname or ""
        except Exception:
            continue
        if (_h in _hosts and _u not in _visited
                and _u not in _attempted and _u not in _cands):
            _cands.append(_u)
    for _d in _dead:
        try:
            _p = _up(_d)
            if not _p.netloc:
                continue
            _segs = (_p.path or "/").rstrip("/").rsplit("/", 1)
            _pdir = (_segs[0] or "/") if len(_segs) > 1 else "/"
            _parent = f"{_p.scheme}://{_p.netloc}{_pdir}"
            if (_parent not in _visited and _parent not in _attempted
                    and _parent not in _cands and _parent != _d):
                _cands.append(_parent)
        except Exception:
            continue
    return _dead, _hosts, _cands


# â”€â”€ Parallel-node scheduler helpers (module level on purpose: stand-in
# kernels bind only some methods - a helper on the class would be auto-stubbed
# and the loop would silently skip the real code). `self` is the kernel. â”€â”€


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

def _der_post_step(self, item, step_result, step_success, verdict, _phase, *,
                   queue, plan, _session, _turn_id, context_package, completed_items,
                   step_outputs, _tokens_used, _token_budget, is_mature, _live_ctx,
                   from_voice, inflight) -> int:
    """Settle ONE finished node on the loop thread: failure routing / split /
    graft, finalize, missing-artifact grafts, and the split race. Moved out
    of the loop unchanged (parallel nodes, 2026-10-04); returns the tokens
    used so far."""
    # A node that lost its split race, or whose plan or turn was dropped,
    # did work nobody needs: it settles as not needed - no graft, no row.
    _why = getattr(item, "_race_lost", "") or getattr(item, "_node_cancelled", "")
    if _why:
        item.result = f"[not needed: {_why}]"
        queue.mark_complete(item.step_id)
        logger.info("[DER] node %s settled as not needed (%s)", item.step_id, _why)
        return _tokens_used
    if not step_success:
        # tc-decide-v7 (2026-11-07): the step FAILED, so every tool_choice row
        # held for it is a wrong pick - including a recovered step: the pick
        # that failed is what the retry had to replace. Stamp BEFORE routing so
        # the rows are written once even when the recovery finalizes normally.
        try:
            from backend.agent import tool_choice_outcome_label as _tcol

            _tcol.stamp(getattr(item, "step_id", None), _turn_id, False)
        except Exception:  # noqa: BLE001 - a label never blocks a settle
            logger.debug("[DER] tool_choice retry stamp failed")
        # REQ-4 (specs/dag-node-execution-model): before the graft
        # handler runs, consult the node router. A recovery node that
        # advertises this failure's reason executes in place of the
        # failing node; a recovered step finalizes normally below
        # (no branch was written in the failing node's module).
        _recovered = self._der_route_step_failure(
            item, step_result, _session, _turn_id, plan, queue=queue,
        )
        if _recovered is not None:
            step_result = _recovered
            step_success = True
        else:
            # C1 FIX: preserve the real error so the graft recovery prompt
            # receives it (item.result is otherwise only set on success).
            item.result = step_result
            # A3 FIX: fragment the failed output here (the shared
            # _der_finalize_step helper is only reached for successful
            # steps, so failures would otherwise never be stored).
            # D1: on lane("memory_events"), never inline - the recovery waits
            # on nothing this note decides (it embeds, dedups and writes; it
            # held the loop 56 s before s2's graft, conv-1573 2026-10-12).
            try:
                if self._memory_interface and step_result:
                    _ep = self._memory_interface.episodic
                    if hasattr(_ep, "fragment_and_store"):
                        from backend.utils.durability_queue import lane as _durability_lane

                        if not _durability_lane("memory_events").submit(
                            "der_failure_fragment", _ep.fragment_and_store,
                            content=f"[DER FAIL Step {item.step_number}: "
                                    f"{item.description[:80]}]\n{step_result[:500]}",
                            session_id=_session,
                            chunk_type="der_failure",
                            zone="tool",
                        ):
                            logger.warning("[DER] der_failure note for %s not queued "
                                           "(memory_events lane full)", item.step_id)
            except Exception as _frag_exc:  # noqa: BLE001 - a note never blocks recovery
                logger.warning("[DER] der_failure note for %s failed: %r",
                               item.step_id, _frag_exc)
            # Step failed after retry â€” mark, abort downstream, graft.
            self._der_handle_step_failure(
                item, queue, plan, _session, _turn_id, context_package,
                step_result=step_result,
            )
            # A failed split child settles its parent too. Only the success
            # path below called _der_settle_split, so when every child of a
            # graft failed the parent sat in split_pending - neither complete
            # nor failed - and the dependents hold_split_parent revived waited
            # on it. A child that split again is a parent now: its own
            # children settle it.
            try:
                if item.step_id not in (getattr(queue, "split_pending", None) or {}):
                    _der_settle_split(self, item, queue, inflight)
            except Exception as _settle_exc:  # noqa: BLE001 - never block the turn
                logger.warning("[DER] split settle after failure of %s failed: %r",
                               item.step_id, _settle_exc)
            # AC5.6 (session-319 fix): the failure/abort path never
            # reached the completion grade site â€” `_der_report_run_grade`
            # is only called from finalize-complete (which needs
            # queue.is_complete()) and continuation-done, so a run that
            # died on a failed step reported NO grade at all (conv-102
            # and the T21 probe both logged zero "run grade" lines).
            # Grade here when no PENDING work remains: failed, aborted
            # and vetoed steps all count as settled â€” that is the honest
            # reading of "this run is over". Deduped by turn inside the
            # helper, so the normal completion path cannot double-report.
            try:
                _pending_after_fail = [
                    _pi for _pi in (getattr(queue, "items", []) or [])
                    if _pi.step_id not in queue.completed_ids
                    and _pi.step_id not in queue.failed_ids
                    and _pi.step_id not in queue.vetoed_ids
                ]
                if (
                    not _pending_after_fail
                    and (getattr(queue, "items", []) or [])
                ):
                    self._der_report_run_grade(
                        completed_items, _turn_id, "failure-settled"
                    )
            except Exception:
                pass
            return _tokens_used  # grafted steps are now in the queue

    # â”€â”€ Phase 4: finalize this step via the shared helper â”€â”€
    _tokens_used = self._der_finalize_step(
        item,
        step_result,
        step_success,
        step_outputs,
        completed_items,
        _tokens_used,
        _token_budget,
        _session,
        _turn_id,
        _phase,
        is_mature,
        _live_ctx,
        plan,
        context_package,
        queue,
        verdict,
        from_voice,
    )

    # â”€â”€ Partial-artifact completion (live 2026-09-25) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # A step is ONE tool call, so a step naming several files writes only
    # one. Detect the remainder and graft a step per missing file BEFORE
    # the loop settles, so the user gets the files that were asked for.
    _grafted = self._der_graft_missing_artifacts(
        item, plan, queue, _session, _turn_id,
        _token_budget=_token_budget, _tokens_used=_tokens_used,
    )
    # tc-decide-v7 (2026-11-07): a post-finalize artifact graft is a RETRY of
    # this step - the pick wrote only part of the files the step named. The
    # step's tool_choice rows are stamped HERE, after the graft count exists,
    # so "completed" means "no failure, no graft, and the step really is in
    # completed_ids" (a split parent is held, not completed).
    _der_settle_split(self, item, queue, inflight)
    try:
        from backend.agent import tool_choice_outcome_label as _tcol

        _tc_step_ok = (
            not int(_grafted or 0)
            and item.step_id in getattr(queue, "completed_ids", ())
        )
        _tcol.stamp(getattr(item, "step_id", None), _turn_id, _tc_step_ok)
    except Exception:  # noqa: BLE001 - a label never blocks a settle
        logger.debug("[DER] tool_choice completion stamp failed")
    return _tokens_used

def _der_settle_split(self, item, queue, inflight) -> None:
    """The split race (owner 2026-10-04): when a split child settles, the
    first VERIFIED child completes its parent (the parent's dependents run
    on) and its siblings stop; when every child failed the parent fails and
    its dependents are aborted. Recurses up a nested split."""
    _cur = item
    while _cur is not None and queue.parent_of_split_child(_cur.step_id):
        _parent_id = queue.parent_of_split_child(_cur.step_id)
        _kids = list(queue.split_pending.get(_parent_id, []))
        _rec = getattr(_cur, "node_record", None)
        _verified = (_cur.step_id in queue.completed_ids
                     and getattr(_rec, "outcome", "") == "VERIFIED")
        _closed = queue.settle_split(_cur.step_id, _verified)
        if _closed is None:
            return
        _pid, _outcome, _winner = _closed
        logger.info("[DER] split %s resolved: %s (winner=%s)", _pid, _outcome, _winner)
        for _k in _kids:
            if _k == _winner or _k in queue.completed_ids or _k in queue.failed_ids:
                continue
            _sib = next((it for it in queue.items if it.step_id == _k), None)
            if _sib is None:
                continue
            _sib._race_lost = f"sibling {_winner} resolved the blocker"
            if _k not in inflight:  # not started: it never will
                _sib.result = f"[not needed: {_sib._race_lost}]"
                queue.mark_complete(_k)
        _cur = next((it for it in queue.items if it.step_id == _pid), None)





# <kernel-split:imports> generated by scripts/kernel_split_check.py move; do not edit by hand
from backend.agent.kernel.base import (
    AVG_STEP_COST,
    DER_EMERGENCY_STOP,
    DER_FOLD_BACK_MAX,
    DER_MAX_CYCLES,
    DER_MAX_GRAFTS,
    DER_MAX_UNVERIFIED_REPROPOSE,
    DER_MAX_VETO_PER_ITEM,
    DER_TOKEN_BUDGETS,
    ExecutionMode,
    ResolvedWindow,
    _CLAIM_LOCKS,
    _CLAIM_LOCKS_GUARD,
    _DER_NODE_QUOTA,
    _DER_PARALLEL,
    _FILL_NO_TURN,
    _NODE_CLAIMS,
    _SCREEN_CLAIM,
    _STEP_ID_KEYS,
    _der_fold_envelope,
    _der_ledger_storage_path,
    _der_recall_delivered,
    _der_recovery_lock,
    _emit_event,
    _memory_events_submit,
    _step_calls,
    _step_decisive_call,
    _step_evidence_cap,
    _step_tool,
    _turn_in_flight,
    _update_counters,
    _update_counters_lock,
    debit_work_units,
    derive_work_units_0,
    logger,
    resolve_der_token_budget,
)
import backend.agent.kernel.base as _k_base
from backend.agent.kernel.models import (
    _resolve_effective_key,
    ModelsMixin,
)
import backend.agent.kernel.models as _k_models
from backend.agent.kernel.surface import (
    _stamp_row_seq,
    SurfaceMixin,
)
import backend.agent.kernel.surface as _k_surface
from backend.agent.kernel.context import (
    _dedupe_fact_lines,
    _dedupe_fact_rows,
    _fact_line,
    _recent_user_turn_texts,
    _same_fact_unit,
    ContextMixin,
)
import backend.agent.kernel.context as _k_context
# </kernel-split:imports>

class AgentKernel(ModelsMixin, SurfaceMixin, ContextMixin):
    """
    Central orchestrator for the dual-LLM agent system.

    Coordinates:
    - lfm2-8b (reasoning model) for planning and analysis
    - lfm2.5-1.2b-instruct (execution model) for tool execution
    - Inter-model communication and state management
    - Model failure fallback to single-model mode
    """

    def __init__(
        self,
        config_path: str = "./backend/agent/agent_config.yaml",
        session_id: str = "default",
        conversation_id: Optional[str] = None,
    ):
        """
        Initialize AgentKernel with dual-LLM coordination.

        Args:
            config_path: Path to agent configuration YAML
            session_id: Session identifier for WebSocket routing and Mycelium
            conversation_id: Conversation identifier for per-thread context.
                             If None, falls back to session_id.
        """
        self.config_path = config_path
        self.session_id = session_id
        self.conversation_id = conversation_id or session_id

        # REQ-6: per-conversation soft-cancel flag. Set by the gateway when the
        # user switches away from this thread (switch_conversation / sync_state /
        # new_conversation / clear_chat). The DER loop polls this between steps and
        # exits cleanly without emitting further events for this conversation.
        self._cancel_requested = threading.Event()

        # W6 (T27-T29): per-conversation DER lock â€” prevents concurrent DER
        # execution on the same conversation. Accessed via _conversation_der_locks
        # class-level dict keyed by conversation_id.
        self._der_active = False

        # Structured logger (module-level logger bound to the instance so the
        # DER soft-cancel path and any other self._logger call sites work).
        self._logger = logging.getLogger(__name__)

        # Core components
        self._model_router: Optional[ModelRouter] = None
        self._vps_gateway: Optional[VPSGateway] = None
        self._conversation_memory: Optional[ConversationMemory] = None
        self._personality: Optional[PersonalityManager] = None
        self._tool_bridge: Optional[AgentToolBridge] = (
            None  # Will be initialized lazily
        )
        # For brainâ†”executor logging
        self._inter_model_communicator: Optional[InterModelCommunicator] = None

        # State management
        self._single_model_mode = False
        self._available_model_id: Optional[str] = None
        self._initialization_error: Optional[str] = None

        # Model selection (user-configurable dual-LLM)
        # NOTE (2026-08-16): `_model_provider`, `_selected_reasoning_model` and
        # `_selected_tool_execution_model` used to be assigned here and kept in
        # sync by hand from half a dozen call sites. They are now READ-ONLY
        # PROPERTIES derived from the process-wide role-binding table â€” see
        # their definitions below. A stale copy of the user's model choice is
        # not a bug that can be fixed here; it is a bug that can only be made
        # impossible, by there being no copy.

        # OpenAI-compatible endpoint â€” covers lmstudio, llamafile, vllm, or any custom server.
        # Set via configure_lmstudio() (legacy name kept) or configure_openai_compat().
        # Defaults to LM Studio's default port; overridden when the user saves settings.
        self._lmstudio_endpoint: str = "http://localhost:1234"

        # In-process `LocalModelManager` binding â€” non-None when iris_gateway
        # has loaded a model via the in-process path. `_get_lmstudio_client()`
        # checks this before creating a real HTTP client; when set AND the
        # provider is `iris_local`, inference goes through the manager's
        # `InProcessOpenAIAdapter` with zero network hops.
        # In-process `LocalModelManager` binding â€” non-None when iris_gateway
        # has loaded a model via the in-process path. `_get_lmstudio_client()`
        # checks this before creating a real HTTP client; when set AND the
        # provider is `iris_local`, inference goes through the manager's
        # `InProcessOpenAIAdapter` with zero network hops.
        self._inprocess_local_mgr: Any = None

        # T17 (REQ-1 AC1.3): in-flight goal references, keyed by conversation
        # id. Set at plan start; follow-up voice turns mutate the live goal
        # through this â€” never fork into a new plan. Initialized lazily so
        # test doubles built via `__new__` (which never call __init__) still
        # find the attribute.
        self._active_goals = getattr(self, "_active_goals", None) or {}

        # Ollama native API endpoint (used when provider == "local").
        self._ollama_endpoint: str = "http://localhost:11434"

        # Cloud/remote API credentials (used when provider == "api").
        # Supports any OpenAI-compatible remote API: OpenAI, Groq, Together, OpenRouter, etc.
        self._api_key: str = ""
        # Provider id the kernel's _api_key belongs to. `_api_key` is a single
        # shared field; without this, a provider switch reuses the previous
        # provider's key (e.g. a Cerebras key attached to a Cohere instance).
        self._api_key_provider: str = ""
        self._api_base_url: str = "https://api.openai.com/v1"

        # Thinking extracted from the most recent _respond_direct call.
        # Set before returning so iris_gateway can include it in the text_response payload.
        self._pending_thinking: str = ""

        # VPS configuration (loaded from settings)
        self._vps_config: Optional[VPSConfig] = None

        # Internet access is now a global app-wide flag (see
        # set_global_internet_access / get_global_internet_access below).

        # Swarm compound collaboration (default: False â€” enabled via UI toggle)
        self._swarm_enabled: bool = False
        self._swarm_coordinator = None
        self._context_control_handler = None

        # â”€â”€ Inference behaviour fields (wired from inference_mode card) â”€â”€
        self._thinking_style: str = "balanced"  # concise | balanced | thorough
        self._response_length: str = "medium"  # short | medium | long
        self._reasoning_effort: str = "balanced"  # fast | balanced | accurate
        self._tool_mode: str = "auto"  # auto | ask_first | disabled

        # Launcher mode: "personal" (default) or "developer"
        # Developer mode injects PROJECT.md into every system prompt so the
        # local agent has full codebase context and can modify source files.
        self._launcher_mode: str = "personal"
        # cached PROJECT.md content
        self._developer_context: Optional[str] = None

        # â”€â”€ Model context window registry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Maps (provider, model_name_substring) â†’ context window in tokens.
        # Used by resolve_context_window() so memory, conversation history,
        # and MCM budgets are never hardcoded â€” they adapt to the model.
        self._context_window_overrides: dict[str, int] = {}

        # â”€â”€ REQ-3 (T2): backend-declared task-card identity registry â”€â”€â”€â”€â”€â”€â”€â”€
        # Maps DER task_id -> card_id so the SAME task's early-skeleton and
        # DER-queue task:start emits (and every lifecycle event after it)
        # resolve to one Liquid Ink card instead of two. Bounded â€” this is a
        # per-kernel-lifetime dict, not per-turn, so it must not grow forever
        # (see _register_card's eviction).
        self._card_by_task: dict[str, str] = {}
        self._active_card_id: Optional[str] = None
        self._CARD_REGISTRY_CAP: int = 200

        # Domain 4.5 â€” proactive skill creation.
        # Tracks how many times each normalized tool-name sequence (joined with "â†’")
        # has been used this session.  When a pattern hits the threshold, the agent
        # is prompted to codify it as a SKILL.md.
        self._session_tool_patterns: dict[str, int] = {}
        self._skill_trigger_threshold: int = 3
        # Patterns already prompted this session â€” avoid repeating the prompt.
        self._prompted_skill_patterns: set[str] = set()

        # Cached OpenAI client for LM Studio â€” created once, reused on every call.
        # Rebuilding _OpenAI() per-call recreates the full httpx connection pool,
        # adding unnecessary overhead on every message.  Invalidated in
        # configure_lmstudio() whenever the endpoint URL changes.
        self._lmstudio_client: Optional[Any] = None

        # Main event loop â€” captured during startup so background threads can
        # dispatch coroutines via run_coroutine_threadsafe.
        self._broadcast_loop: Optional[Any] = None

        # Initialize components
        self._initialize_components()

        # Auto-apply a provider configured in iris_config.json so the agentic /
        # DER loop does not silently fall back to a local OpenAI-compatible model
        # when a cloud provider is already configured.  Local-only setups (no
        # provider / no key) are left uninitialized â€” the existing wait-for-user
        # (Models-card APPLY / model_selection confirm_card) behaviour is preserved.
        self._router = InferenceRouter(load_config())
        # Context window (2026-09-27): the router asks us for the window of the
        # role it is about to call, so it can (a) offer it to a provider that is
        # able to set one - Ollama, as options.num_ctx - and (b) cap the prompt
        # for the providers that cannot, where the window is fixed and the only
        # thing we control is how much we send. The resolver is our own method
        # on purpose: the window table lives in THIS class, and a copy inside
        # the router would drift away from it. Router-side failures degrade to
        # "no window known" and never break a turn.
        self._router.set_window_resolver(self.resolve_context_window)
        # Wedge fix (session 363, pin_35af67d07c5f): the router calls us back
        # at every model-dispatch entry and inside the transport retry
        # ladders, so the turn budget + client check run INSIDE the blocking
        # paths. The DER loop condition only evaluates BETWEEN cycles, so a
        # turn blocked inside ONE operation never re-evaluated it and the
        # 600 s budget never fired (chain client w1 ran 19+ min while the
        # backend logged nothing for 18). The check is a bound method of THIS
        # kernel â€” the router is per-kernel (not a singleton), so there is no
        # cross-session leakage â€” and it reads per-turn state set in
        # _execute_plan_der. Modeled on set_window_resolver directly above.
        self._router.set_turn_budget_check(self._turn_choke_check)
        # In-process local models (2026-09-27). The gateway attaches the local
        # model manager to the routers that EXIST when a model is loaded, so a
        # kernel created LATER (a new WS session) starts with
        # `_inprocess_mgr = None` and every `local:<model>` planning call dies:
        #   [AgentKernel._plan_task] router planning failed:
        #     No local model loaded for in-process inference
        # No plan means no DER, so the step consumers (review_verdict,
        # sufficient, done, on_track, has_gaps, needs_action,
        # recovery_strategy) never ran and could never reach the Wave 7 bar no
        # matter how much traffic was driven. The manager is a process-wide
        # singleton, so attach it here instead of depending on load-time fan-out
        # reaching every future kernel. get_local_model_manager() constructs the
        # manager object only; it loads no weights.
        try:
            from .local_model_manager import get_local_model_manager

            self._router.set_inprocess_manager(get_local_model_manager())
        except Exception as _mgr_err:  # noqa: BLE001 â€” a missing manager is not fatal
            logger.debug(
                "[AgentKernel] in-process manager attach skipped: %s", _mgr_err
            )

    def _initialize_components(self):
        """Initialize all core components with error handling."""
        try:
            # Initialize Model Router with UNINITIALIZED mode (lazy loading)
            logger.info(
                "[AgentKernel] Initializing Model Router in UNINITIALIZED mode (lazy loading)..."
            )
            from .model_router import InferenceMode

            self._model_router = ModelRouter(
                self.config_path, inference_mode=InferenceMode.UNINITIALIZED
            )
            logger.info(
                "[AgentKernel] Model Router initialized - models will NOT be loaded automatically"
            )
            logger.info(
                "[AgentKernel] Models will be loaded only when user selects Local Model inference mode"
            )

            # In UNINITIALIZED mode, we don't have models yet
            logger.info(
                "[AgentKernel] Waiting for user to configure inference mode (Local/VPS/OpenAI)"
            )
            self._single_model_mode = False

        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Model Router: {e}")
            self._initialization_error = f"Model Router initialization failed: {e}"
            self._model_router = None

        # VPS Gateway is lazy: only created when the user explicitly enables VPS mode
        # via configure_vps(). Creating it per-session at startup is wasteful and triggers
        # health-check loops for every WebSocket reconnect even when VPS is disabled.
        self._vps_config = VPSConfig(enabled=False)
        self._vps_gateway = None
        logger.info(
            "[AgentKernel] VPS Gateway deferred (lazy init â€” awaiting user VPS configuration)"
        )

        try:
            # Initialize Conversation Memory
            logger.info(
                f"[AgentKernel] Initializing Conversation Memory for session {self.session_id}..."
            )
            self._conversation_memory = ConversationMemory(
                session_id=self.session_id,
                conversation_id=self.conversation_id,
                max_messages=10,  # Default from requirements
            )
            logger.info("[AgentKernel] Conversation Memory initialized")

        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Conversation Memory: {e}")
            self._initialization_error = (
                f"Conversation Memory initialization failed: {e}"
            )
            self._conversation_memory = None

        try:
            # Initialize Personality Manager
            logger.info("[AgentKernel] Initializing Personality Manager...")
            self._personality = PersonalityManager()
            logger.info("[AgentKernel] Personality Manager initialized")

        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Personality Manager: {e}")
            self._initialization_error = (
                f"Personality Manager initialization failed: {e}"
            )
            self._personality = None

        try:
            # Initialize Inter-Model Communicator for brainâ†”executor logging (Bug 5 fix)
            logger.info("[AgentKernel] Initializing Inter-Model Communicator...")
            if self._model_router:
                model_conversation = ModelConversation()
                self._inter_model_communicator = InterModelCommunicator(
                    model_router=self._model_router, conversation=model_conversation
                )
                logger.info("[AgentKernel] Inter-Model Communicator initialized")
            else:
                logger.warning(
                    "[AgentKernel] Inter-Model Communicator not initialized: Model Router unavailable"
                )
        except Exception as e:
            logger.error(
                f"[AgentKernel] Failed to initialize Inter-Model Communicator: {e}"
            )
            self._inter_model_communicator = None

        # Tool Bridge will be initialized lazily when needed

        # Memory Foundation integration
        self._memory_interface: Optional[Any] = None

        # MCM Protocol Orchestrator â€” wired after set_memory_interface()
        self._mcm_orch = None

        # Trust-routing (plan W2): whether the current turn touched external/
        # web sources (web_search / crawler_query). When True, turn-pair
        # fragments are stored in the 'reference' zone instead of 'trusted'.
        # Reset at the start of each turn (process_text_message /
        # _execute_plan_der) and set when an external tool runs.
        self._turn_touched_external: bool = False
        # D3 (2026-10-31): set at the top of every turn (process_text_message).
        self._turn_started_monotonic: float = 0.0

        # â”€â”€ DER Loop components â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # DER_MAX_CYCLES / DER_MAX_VETO_PER_ITEM re-exported at module level
        # for spec compliance (Gap 11). Canonical values live in der_constants.
        self._task_classifier = None
        self._reviewer = None
        self._mode_detector = None
        self._der_tokens_used: int = 0

        try:
            from backend.memory.mycelium.kyudo import TaskClassifier as _TC

            self._task_classifier = _TC()
            logger.info("[AgentKernel] TaskClassifier initialized (DER)")
        except Exception as _tc_err:
            logger.warning(f"[AgentKernel] TaskClassifier unavailable: {_tc_err}")

        try:
            from backend.agent.der_loop import Reviewer as _Reviewer

            # memory_interface wired later via set_memory_interface()
            self._reviewer = _Reviewer(adapter=self, memory_interface=None)
            logger.info("[AgentKernel] Reviewer initialized (DER)")
        except Exception as _rv_err:
            logger.warning(f"[AgentKernel] Reviewer unavailable: {_rv_err}")

        try:
            from backend.agent.mode_detector import ModeDetector as _MD

            self._mode_detector = _MD()
            # The `mode` Oracle consumer was REMOVED 2026-10-10 (owner): the
            # detector keeps its keyword classifier only â€” no engine wiring, no
            # row sink (see mode_detector.py).
            logger.info("[AgentKernel] ModeDetector initialized (DER)")
        except Exception as _md_err:
            logger.warning(f"[AgentKernel] ModeDetector unavailable: {_md_err}")

        # REQ-6 AC2 (T9): fire the bounded, latched, background LFM warm-up so
        # the first user turn runs at warm latency. Non-blocking â€” a daemon
        # thread does the load; a failure leaves the normal cold path intact.
        try:
            from backend.agent.semantic_gate import ensure_warm_start

            ensure_warm_start()
        except Exception as _wu_err:
            logger.debug("[AgentKernel] LFM warm-up kick failed: %s", _wu_err)

        # REQ-14 AC14.1 / REQ-29 (T18, T46-T49): install the shadow-row sink.
        # The monitor and surface consumer modules emit their rows to a
        # module-level sink, and NOTHING installed one in production â€” every
        # row fell through to a log line, so no calibration row ever persisted
        # and TG-6's parity clause plus Wave 7's >=100-row flip bar were
        # structurally unreachable. The sink is the SAME single-writer ledger
        # the dispatched decisions use, so one reader sees every consumer.
        try:
            from backend.agent import explorer as _ex_rows
            from backend.agent import monitor_shadow as _ms_rows

            _shadow_sink = self._shadow_row_sink
            _ms_rows.set_row_sink(_shadow_sink)
            # web_intent (2026-09-27): this consumer had criteria and a live call
            # site but no row path at all, so it could never be scored however
            # often it ran. Same single-writer sink as the other two.
            _ex_rows.set_row_sink(_shadow_sink)
            # click_safety (W2): the browser click gate's Oracle shadow rows.
            from backend.agent import click_safety_shadow as _cs_rows

            _cs_rows.set_row_sink(_shadow_sink)
            # event taxonomy step 3: user_feedback / event_family / event_type:*.
            from backend.agent import event_oracle as _eo_rows

            _eo_rows.set_row_sink(_shadow_sink)
            # tool_approval (safety, 2026-11-10): rows from the user's answers
            # to permission prompts. Same single-writer sink.
            from backend.agent import tool_approval_shadow as _ta_rows

            _ta_rows.set_row_sink(_shadow_sink)
            # browser_next (2026-10-11): the element-choice consumer.
            from backend.agent import browser_next_shadow as _bn_rows

            _bn_rows.set_row_sink(_shadow_sink)
            # page_relevance / page_blocked (2026-11-10): the research-path
            # page questions (crawler shadow consults). Same sink.
            from backend.agent import page_shadow as _ps_rows

            _ps_rows.set_row_sink(_shadow_sink)
            # REQ-14 (Wave 5): resolved OUTCOME-labelled rows (the deferred
            # registry) land on the SAME single-writer sink.
            from backend.agent import decision_engine as _de_rows

            _de_rows.set_outcome_sink(_shadow_sink)
            logger.info(
                "[AgentKernel] shadow row sink installed "
                "(monitor + web_intent + the other consumers)"
            )
        except Exception as _sink_err:  # noqa: BLE001 â€” advisory
            logger.warning(
                f"[AgentKernel] shadow row sink install failed: {_sink_err}"
            )

        logger.info("[AgentKernel] Initialization complete")

    def _shadow_row_sink(self, row: Optional[dict]) -> None:
        """Persist ONE shadow-consumer row to the single-writer ledger.

        REQ-14 AC14.1 / REQ-29 (T18, T46-T49). The monitor consumers
        (`sufficient`, `done`) and the other module-sink consumers are
        SHADOW: they must write a calibration row and change no decision.
        (The surface consumers - `needs_action`, `depth_met`, `has_gaps`,
        `escalate_incomplete` - are all retired.)

        Why this method exists: the consumer modules emitted their rows to a
        sink that no production code installed, so a live session produced log
        lines and no rows. Wave 7 flips a consumer only on >= 100 measured
        rows, so the enforcement gate was unreachable without it.

        The parity pair (`chosen` vs `brain_bool`) rides the ledger's decision
        block â€” that is what lets a reader compute precision and ECE for a
        consumer that never dispatches a tool of its own.

        Never raises: an observer must never block a step (AC14.4 shape).
        """
        if not row or not isinstance(row, dict):
            return
        try:
            bridge = getattr(self, "_tool_bridge", None)
            if bridge is None or not hasattr(bridge, "record_decision"):
                return
            meta = dict(row)
            meta.setdefault("route", "shadow")
            if not meta.get("engine"):
                try:
                    from backend.agent.decision_engine import get_decision_engine

                    meta["engine"] = str(
                        getattr(get_decision_engine(), "model_id", "") or ""
                    )
                except Exception:  # noqa: BLE001 â€” attribution is best-effort
                    meta["engine"] = ""
            bridge.record_decision(
                meta, "shadow",
                session_id=str(getattr(self, "session_id", "") or "shadow"),
            )
        except Exception as exc:  # noqa: BLE001 â€” a row never blocks a step
            logger.debug("[AgentKernel] shadow row sink failed: %r", exc)

    def set_main_loop(self, loop: Any) -> None:
        """Capture the running event loop so background threads can dispatch broadcasts."""
        self._broadcast_loop = loop

    def set_memory_interface(self, memory_interface: Any) -> None:
        """
        Set the memory interface for the agent kernel.

        This is called after AgentKernel initialization to wire in
        the Memory Foundation system.

        Args:
            memory_interface: MemoryInterface instance from backend.memory
        """
        self._memory_interface = memory_interface
        # Wire Reviewer's memory reference now that it's available
        if self._reviewer is not None:
            self._reviewer.memory = memory_interface
        logger.info("[AgentKernel] Memory interface connected")
        try:
            from backend.agent.mcm_protocol import MCMOrchestrator

            self._mcm_orch = MCMOrchestrator(
                memory_interface=memory_interface,
                session_id=self.session_id,
                thread_id=getattr(self, "_thread_id", None),
            )
            logger.info("[AgentKernel] MCMOrchestrator initialized")
        except Exception as _mcm_err:
            logger.warning(f"[AgentKernel] MCMOrchestrator unavailable: {_mcm_err}")
            self._mcm_orch = None

    # â”€â”€ Trust-routing helpers (plan W2) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _pacman_zone_for_turn(self) -> Optional[str]:
        """Zone for fragments produced by the current turn.

        Returns 'reference' when the turn touched external/web sources
        (web_search / crawler_query), else None so EpisodicStore applies its
        trusted/tool default. See trust-routing plan W2.
        """
        return "reference" if getattr(self, "_turn_touched_external", False) else None

    def mark_external_tool(self, tool_name: str = "") -> None:
        """Flag the current turn as having touched external/web sources.

        Idempotent: once a turn is marked external it stays external for the
        whole turn (a later local tool must not clear it).
        """
        if is_external_tool(tool_name):
            self._turn_touched_external = True

    def clear_turn_trust_flag(self) -> None:
        """Reset the per-turn external flag. Call at the start of each turn."""
        self._turn_touched_external = False

    def clear_conversation(self, conversation_id: Optional[str] = None) -> None:
        """
        Clear the agent context for a conversation â€” both the in-memory
        conversation history and the persistent store.  Called on 'new
        conversation' or thread switch cleanup so the next turn starts blank.

        Never raises â€” logs warning on failure.
        """
        _cid = conversation_id or getattr(self, "conversation_id", None)
        # Reset in-memory history immediately so a reused kernel instance
        # cannot leak the previous thread's messages into the new one.
        if self._conversation_memory is not None:
            try:
                self._conversation_memory.clear()
            except Exception as _mem_exc:
                logger.warning(
                    f"[AgentKernel] in-memory clear failed for {_cid}: {_mem_exc}"
                )
        try:
            from backend.agent.conversation_context_store import get_context_store

            store = get_context_store()
            store.clear(_cid)
            logger.info(
                f"[AgentKernel] Cleared context for conversation {_cid}"
            )
        except Exception as exc:
            logger.warning(
                f"[AgentKernel] clear_conversation({_cid}) failed: {exc}"
            )

    # â”€â”€ T17 (REQ-1 AC1.3): follow-up mutation wiring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # A voice/text interruption lands on the LIVE GoalAnatomy â€” never a side
    # plan. Each mutation is logged in memory_anchors so the audit trail
    # shows who changed what.

    def _get_active_goal_for(self, conversation_id: str):
        """Return the currently-active goal for this conversation, or None.

        Lazy lookup: a test double built via __new__ never runs __init__, so
        the slot may be unset. Treat that as "no in-flight goal" â€” callers
        decided at plan time what this conversation is doing.
        """
        return getattr(self, "_active_goals", {}).get(conversation_id)

    def _set_active_goal_for(self, conversation_id: str, goal) -> None:
        if not hasattr(self, "_active_goals"):
            self._active_goals = {}
        self._active_goals[conversation_id] = goal

    def apply_follow_up(self, conversation_id: str, text: str) -> bool:
        """Follow-up on the ACTIVE goal: merge new requirements into it.

        Per REQ-1 AC3 the user can revise an in-flight task mid-plan. Parser:
        parse the new instruction into (fields, target, guardrails, anchors) â€”
        anything else is semantic state. A mutation must land on the SAME
        GoalAnatomy instance (the `is` identity check is the contract)."""
        goal = self._get_active_goal_for(conversation_id)
        if goal is None:
            raise LookupError(f"no active goal for conversation {conversation_id}")
        anchor = getattr(goal, "memory_anchors", None)
        if not isinstance(anchor, dict):
            anchor = {}
            goal.memory_anchors = anchor
        anchor.setdefault("mutation_log", [])
        anchor["mutation_log"].append(text[:200])
        goal.memory_anchors = anchor
        prev_fields = [f for f in (getattr(goal, "fields", None) or []) if isinstance(f, str)]
        known = [t for t in (
            "price", "battery", "specs", "availability", "deadline", "query",
            "rating", "source", "warranty", "spec", "benchmark",
        ) if t in text.lower()]
        for t in known:
            if t not in prev_fields:
                prev_fields.append(t)
        # GoalAnatomy.mutate() returns self â€” in-place, never a branch.
        goal.mutate(fields=prev_fields)
        return True





    def _get_memory_context(self, task: str) -> str:
        """
        Get memory-augmented context for a task.

        Args:
            task: Task description

        Returns:
            Context string with memory augmentation
        """
        if self._memory_interface is None:
            return ""

        try:
            context = self._memory_interface.get_task_context(
                task=task, session_id=self.session_id
            )
        except Exception as e:
            logger.warning(f"[AgentKernel] Failed to get memory context: {e}")
            return ""

        # T8c (REQ-10 AC5): emit an episodic memory event so the card's memory
        # slot renders REAL episodic retrieval (never fabricated). Fire-and-
        # forget and OFF the inference hot path â€” a bus failure must never
        # affect the returned context.
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.MEMORY_EVENT,
                data={
                    "kind": "episodic",
                    "data": {
                        "task_summary": (task or "")[:120],
                        "outcome_type": "recall",
                        "duration_ms": 0,
                    },
                },
                session_id=self.session_id,
                # Session 245 (card-sync fix): without this the gateway stamps
                # "default" and the frontend files the event under a
                # conversation bucket the visible card is not in.
                conversation_id=self.conversation_id,
            )
        except Exception:
            pass

        return context

    def _store_task_episode(
        self,
        task_summary: str,
        full_content: str,
        outcome_type: str = "success",
        tool_sequence: Optional[List[Dict[str, Any]]] = None,
        session_id: Optional[str] = None,
        duration_ms: int = 0,
    ) -> None:
        """
        Store a task episode in memory.

        Args:
            task_summary: Brief task description
            full_content: Full conversation/task content
            outcome_type: Task outcome (success, failure, etc.)
            tool_sequence: List of tool calls made
            session_id: Session to attribute the episode to (falls back to self.session_id)
            duration_ms: Wall-clock time the task took in milliseconds
        """
        if self._memory_interface is None:
            return

        try:
            from backend.memory import Episode

            # The episode belongs to the CONVERSATION; the claim graph keeps the session the turn ran on. Live
            # 2026-10-26: every chat turn's episode was filed under the WS session ("session_iris", 185 rows) while
            # its chain rows and events were under "thread:...", so the chat's uses, a forget of the chat and the
            # memory surface could not see its episodes.
            _graph_sid = session_id or self.session_id
            episode = Episode(
                session_id=getattr(self, "conversation_id", None) or _graph_sid,
                graph_session_id=_graph_sid,
                turn_id=getattr(self, "_der_turn_id", None),
                task_summary=task_summary,
                full_content=full_content,
                tool_sequence=tool_sequence or [],
                outcome_type=outcome_type,
                duration_ms=duration_ms,
                source_channel="websocket",
                node_id="local",
                origin="local",
            )

            self._memory_interface.store_episode(episode)
            logger.debug(
                f"[AgentKernel] Stored episode for task: {task_summary[:50]}..."
            )

        except Exception as e:
            logger.warning(f"[AgentKernel] Failed to store episode: {e}")









    # â”€â”€ Context window resolution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Every model has a maximum context window.  Memory, conversation history,
    # and MCM budgets should be derived from it â€” never hardcoded.


    # Known context windows (tokens).  Keyed by (provider, model_substring).
    # Substring match is case-insensitive; first match wins.
    _KNOWN_CONTEXT_WINDOWS: list[tuple[str, str, int]] = [
        # Cohere
        ("cohere", "command-r-plus", 128_000),
        ("cohere", "command-r", 128_000),
        ("cohere", "command-a", 256_000),
        ("cohere", "command", 8_192),
        # OpenAI
        ("openai", "gpt-4o", 128_000),
        ("openai", "gpt-4o-mini", 128_000),
        ("openai", "gpt-4-turbo", 128_000),
        ("openai", "gpt-4", 8_192),
        ("openai", "gpt-3.5", 16_385),
        # Groq
        ("groq", "llama-3.3-70b", 128_000),
        ("groq", "llama-3.1-70b", 128_000),
        ("groq", "llama-3.1-8b", 128_000),
        ("groq", "llama3-70b", 8_192),
        ("groq", "llama3-8b", 8_192),
        ("groq", "mixtral-8x7b", 32_768),
        ("groq", "gemma2-9b", 8_192),
        # DeepSeek
        ("deepseek", "deepseek-chat", 65_536),
        ("deepseek", "deepseek-coder", 16_384),
        # Mistral
        ("mistral", "mistral-large", 128_000),
        ("mistral", "mistral-medium", 32_000),
        ("mistral", "mistral-small", 32_000),
        ("mistral", "mixtral", 32_000),
        # Cerebras â€” value confirmed by the user 2026-07-28.
        # NOTE: no provider-wide ("cerebras", "", N) fallback on purpose. An
        # unlisted model must fall through to the conservative 8k default rather
        # than inherit 256k: the budget is sized at window*0.9, so a default that
        # is too HIGH re-creates the overcommit this table's default exists to
        # prevent. Under-sizing is safe; over-sizing is the bug.
        ("cerebras", "gemma-4-31b", 256_000),
        # Qwen 3.8 27B replaces gemma as the Cerebras offering 2026-09-04.
        # Catalog context is 64k free / 128k paid.
        # CORRECTED 2026-09-05: this is 64_000, not the 128_000 paid tier.
        # Evidence, not an assumption â€” api.cerebras.ai answers every request
        # with 402 "Payment required to access this resource. Visit your
        # billing tab." (type=payment_required_error), i.e. no paid plan is
        # active, so only the 64k free-tier window is actually served.
        # Direction of error matters: the budget is sized at window*0.9, so
        # 128_000 provisions 115.2k against a 64k window and the overage is
        # silently truncated mid-conversation. Under-sizing is safe;
        # over-sizing is the bug (same rule as the gemma row above).
        # Revert to 128_000 only if Cerebras billing is actually enabled.
        # The gemma row above stays: still-true model fact, pinned by the
        # ctx-budget contract tests. ClinePass models stay unlisted on
        # purpose (windows unverified) and take the safe 8k default.
        ("cerebras", "qwen-3.8-27b", 64_000),
        # Inception mercury-2.5: 260_000 is the window Inception itself published in
        # its /models list (logged 2026-10-02 and 2026-10-25, "budget=26000 from
        # window=260000"). On 2026-10-26 /models listed only mercury-3 and
        # mercury-decide - mercury-2.5 still answers but is no longer listed - so
        # the API lookup (case 2b) found nothing, every thread fell to the 8_192
        # default and the chat's context pill went red after one prompt. Evidence,
        # not a guess; case 2b still wins whenever the provider lists the model.
        ("inceptionlabs", "mercury-2.5", 260_000),
        # mercury-3: Inception's /models published context_length 1000000 (2026-10-26).
        ("inceptionlabs", "mercury-3", 1_000_000),
        # OpenRouter: REMOVED 2026-07-29. ("openrouter", "", 32_000) was a
        # bare-substring provider-wide fallback â€” it matched EVERY model from
        # OpenRouter, which fronts models from 4k to 2M windows. A blanket
        # 32_000 meant an 8k-window model got a budget sized for 32k, so DER
        # kept issuing steps while every call silently truncated (REQ-2 AC6,
        # the exact case row 1 of the silent-failure table in specs/PHASES.md
        # describes). This was briefly grandfathered into an allow-list in
        # test_no_raised_provider_default; that was wrong and has been
        # reverted â€” the guard now admits no exceptions. An unlisted
        # openrouter model now falls through to the conservative 8_192
        # default (case 4 below), tagged source="default" per REQ-2 AC4:
        # under-provisioning is safe, over-provisioning truncates silently.
        # Escape hatch: a real window can still be supplied per-model via
        # _context_window_overrides (highest precedence, REQ-2 AC3).
        # Open question: the correct long-term fix is resolving OpenRouter's
        # window from its API metadata (authoritative, REQ-2 AC2) rather than
        # any table guess â€” see specs/phase-1-foundation/requirements.md OQ.
        # LM Studio / IRIS Local â€” common local models
        ("lmstudio", "lfm-2-8b", 32_768),
        ("lmstudio", "llama-3", 8_192),
        ("lmstudio", "llama-3.1", 128_000),
        ("lmstudio", "llama-3.2", 128_000),
        ("lmstudio", "mistral", 32_768),
        ("lmstudio", "qwen2.5", 32_768),
        ("lmstudio", "phi-3", 128_000),
        ("iris_local", "lfm-2-8b", 32_768),
        ("iris_local", "llama-3", 8_192),
        ("iris_local", "llama-3.1", 128_000),
        # Ollama â€” common local models
        ("local", "llama3.1", 128_000),
        ("local", "llama3", 8_192),
        ("local", "mistral", 32_768),
        ("local", "qwen2.5", 32_768),
        ("local", "phi3", 128_000),
        ("local", "gemma2", 8_192),
        # Ollama CLOUD models. Every value below was read from the running
        # Ollama server's own /api/show `context_length` on 2026-08-16 â€” not
        # from a model card, a blog post, or memory. The catalog above this
        # file was once ~80% fabricated, so anything unverifiable is simply
        # absent here rather than guessed.
        #
        # Why these were missing and what it cost: an OLLAMA-kind provider maps
        # to the provider string "local" (see _provider_string_for_instance),
        # and no "local" entry matched any cloud id â€” so gpt-oss:120b-cloud
        # resolved to the conservative 8192 default and DER got a 4000-token
        # budget against a real 131072 window. Observed live: a 3-step task
        # stopped after step 2 with "Token budget exhausted (6091/4000)" while
        # the model had ~32x the headroom it was being given.
        #
        # Deliberately NOT listed: kimi-k2.5:cloud and kimi-k2-thinking:cloud.
        # Ollama's own /api/show returns an error for both, so no authoritative
        # window exists to record. They fall through to the 8192 default, which
        # under-provisions rather than truncates â€” the safe direction, per the
        # cerebras note above.
        ("local", "gpt-oss", 131_072),
        ("local", "nemotron-3-nano", 262_144),
        ("local", "glm-5.1", 202_752),
        # ADDED 2026-09-27. Value read from the running Ollama server's own
        # /api/show on 2026-09-27: gemma4.context_length = 262144 -- same method
        # and same rule as the rows above (the server is the authority, not a
        # model card or memory).
        #
        # What it cost while missing: this is the model the reasoning role is
        # bound to, and no "local" row matched it, so both roles logged
        # "WARN source=default: no context window known for provider=local
        # model=gemma4:31b-cloud -- falling back to 8192" and a 262144-token
        # window was budgeted as 8192, a 32x under-provision. Under-sizing does
        # not truncate, but it ends a long task early with "Token budget
        # exhausted" -- the same failure the gpt-oss note above describes at the
        # same ratio, which is the evidence that this row is worth having.
        #
        # Row order: "gemma2" (above) and "gemma4" do not collide -- first match
        # wins on a substring test, and neither string contains the other.
        ("local", "gemma4", 262_144),
        # OpenCode Zen (opencodego). The live /models endpoint 403s, so the
        # window was MEASURED instead of guessed: deepseek-v4.1-flash accepted
        # a 720k-token prompt (2026-11-03) and OpenRouter lists 1048576 for
        # the same model id. 128k is the value recorded here on purpose: the
        # rule of this table is "under-sizing is safe, over-sizing is the
        # bug" (the budget is window*0.75, so a too-high window over-commits
        # the prompt). 128k is 15x the 8192 default that every opencodego
        # model fell through to before this row, and it ends the message
        # dropping that the 8192 budget caused ("prompt over the window:
        # window=8192 budget=3840 dropped_messages=6").
        ("opencodego", "", 128_000),
    ]

    # Known vision-capable API models. Keyed (provider_id, model_substring),
    # mirroring _KNOWN_CONTEXT_WINDOWS's shape and matching rule directly
    # above: substring match is case-insensitive, first match wins. Sibling
    # table for specs/unified-vision-routing REQ-1 AC2 â€” this is DATA only,
    # not a raise site. A model id that matches no row here is simply absent
    # from the table; the "unknown -> False" behaviour of REQ-1 AC5 is owned
    # by supports_vision() (backend/agent/inference/router.py), which must
    # treat "no row matched" as False rather than erroring.
    #
    # provider_id follows the same vocabulary as _KNOWN_CONTEXT_WINDOWS: the
    # literal instance id registered for an API ProviderInstance (e.g.
    # "openai", "anthropic" â€” see PROVIDER_PRESETS in
    # backend/agent/inference/provider.py), not the ProviderKind enum value.
    _KNOWN_VISION_MODELS: list[tuple[str, str]] = [
        # OpenAI â€” the GPT-4o family and later multimodal generations accept
        # image input natively.
        ("openai", "gpt-4o"),
        ("openai", "gpt-4-turbo"),
        ("openai", "gpt-4.5"),
        # Anthropic â€” every Claude 3 and later model accepts image input.
        ("anthropic", "claude-3"),
        ("anthropic", "claude-opus"),
        ("anthropic", "claude-sonnet"),
        ("anthropic", "claude-haiku"),
        # Gemini â€” multimodal since 1.5. No "gemini" id exists in
        # PROVIDER_PRESETS today (no dedicated Google preset is registered
        # yet); this row is forward-compatible with a directly-configured
        # Gemini-compatible API provider registered under instance id
        # "gemini", and the substring also matches vendor-prefixed ids such
        # as an aggregator's "google/gemini-2.0-flash-001" once such a
        # provider exists. Deliberately NOT guessing at a provider id that
        # is not yet a real preset beyond this one forward-compatible row.
        ("gemini", "gemini"),
    ]

    # â”€â”€ Active-model state: DERIVED from the router, never stored â”€â”€â”€â”€â”€â”€â”€â”€â”€
    #
    # These three read like plain attributes because ~120 call sites across the
    # backend read them that way, and that is fine â€” reading is safe. What is
    # not safe is STORING them, which is what they used to do.
    #
    # The role-binding table and the provider registry are process-wide
    # singletons (REQ-5): one table, shared by every kernel's router. The user's
    # live choice lives there and nowhere else. Every recurring "I picked cohere
    # and it went back to cerebras" report traced to some path re-applying a
    # stored copy of that choice â€” startup config replay, peer inheritance, a
    # module-global snapshot, persisted session field_values. Each was fixed
    # individually and the bug came back through the next copy.
    #
    # Deriving them removes the category. There is no copy to go stale, no sync
    # to forget, and a new conversation kernel â€” or a subagent, or a swarm
    # worker â€” sees the live binding at construction because it shares the
    # table rather than inheriting a snapshot of it.
    #
    # To CHANGE the active model, bind the role: `kernel.set_role_binding(...)`.













    @staticmethod
    def _extract_chunk_text(chunk):
        """Delegate to streaming module."""
        return _streaming.extract_chunk_text(chunk)

    @staticmethod
    def _safe_stream(
        resp, silence_timeout=1.5, total_timeout=90.0, on_first_token=None
    ):
        """Delegate to streaming module."""
        yield from _streaming.safe_stream(
            resp,
            silence_timeout=silence_timeout,
            total_timeout=total_timeout,
            on_first_token=on_first_token,
        )

    # Providers that speak the OpenAI-compatible chat completions API.
    # When the user picks any of these, inference routes through _get_lmstudio_client()
    # using whatever endpoint they configured (LM Studio, llamafile, vllm, etc.).
    _OPENAI_COMPAT_PROVIDERS = frozenset(
        {
            "lmstudio",
            "openai_compatible",
            "llamafile",
            "vllm",
            "llamacpp_server",
            "koboldcpp",
            "textgen_webui",
            "ollama_openai",
            # IRIS-native local model server (llama-cpp-python / ik_llama.cpp on port 8082)
            "iris_local",
        }
    )










    def _get_developer_context(self) -> str:
        """Load and cache the PROJECT.md developer context string.

        Returns empty string if the file cannot be found (non-fatal).
        """
        if self._developer_context is not None:
            return self._developer_context
        import pathlib

        # Walk up from this file's location to find PROJECT.md
        here = pathlib.Path(__file__).parent
        for _ in range(6):
            candidate = here / "PROJECT.md"
            if candidate.exists():
                self._developer_context = candidate.read_text(encoding="utf-8")
                logger.info(f"[AgentKernel] Loaded developer context from {candidate}")
                return self._developer_context
            here = here.parent
        logger.warning(
            "[AgentKernel] PROJECT.md not found â€” developer context unavailable"
        )
        self._developer_context = ""
        return ""

    def _bound_external_project(self) -> str:
        """The turn's bound workdir when it is outside the IRIS repo, else ""."""
        try:
            _sess = getattr(self, "_turn_session_id", None) or self.session_id
            _wd = (getattr(self._tool_bridge, "_session_workdirs", None) or {}).get(_sess) or ""
            if not _wd:
                return ""
            _repo = os.path.normcase(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            _norm = os.path.normcase(os.path.abspath(_wd))
            return "" if _norm == _repo or _norm.startswith(_repo + os.sep) else _wd
        except Exception:
            return ""


    # ------------------------------------------------------------------
    # Domain 4.5 â€” Proactive skill creation
    # ------------------------------------------------------------------

    def _maybe_trigger_skill_creation(
        self,
        tool_sequence: list,
        task_summary: str,
    ) -> None:
        """
        After each task, capture a *verified* reusable skill when the run used
        >= 3 distinct tools and the sequence is not already a known skill.

        Phase 5.1 (research D1): replaces the old count-based heuristic that
        merely prompted the LLM to write a SKILL.md.  The new pipeline is
        deterministic and verified:
          1. Trigger iff >= 3 DISTINCT tools AND similarity to existing skills
             < 0.85 (workflow_capture.should_capture).
          2. Self-test: every step names a tool registered in tool_registry
             (no unknown tools) â€” a safe structural replay, no real execution
             (workflow_capture.self_test_skill).
          3. Register the verified skill in semantic memory
             (workflow_capture.register_verified_skill), mirroring
             SkillCrystalliser's storage so the skill UI / AutoResearchRunner
             pick it up for continuous refinement (MIN_IMPROVEMENT = 0.05).

        tool_sequence is the list of tool-call dicts recorded by the DER loop.
        """
        import json

        if not tool_sequence or len(tool_sequence) < 2:
            return

        # Only capture from successful runs.
        successful = [
            s for s in tool_sequence
            if isinstance(s, dict) and s.get("success", False)
        ]
        if len(successful) < 2:
            return

        # In-session dedupe so we don't re-trigger for the same pattern.
        names = []
        for tc in successful:
            name = (
                tc.get("name")
                or tc.get("tool")
                or tc.get("function", {}).get("name", "")
            )
            if name:
                names.append(name)
        pattern_key = " â†’ ".join(names)
        if pattern_key in self._prompted_skill_patterns:
            return
        self._prompted_skill_patterns.add(pattern_key)

        try:
            from backend.agent.workflow_capture import capture_workflow
            from backend.agent.tool_registry import resolve_tool

            memory = self._memory_interface
            if memory is None or not hasattr(memory, "semantic"):
                return

            # Existing skills (for similarity de-dup).
            existing_skills = []
            try:
                for entry in memory.semantic.get_by_category("named_skills"):
                    try:
                        existing_skills.append(json.loads(entry.value))
                    except Exception:
                        continue
            except Exception:
                existing_skills = []

            # Recurrence (owner 2026-10-01): a skill is a recipe that repeats.
            # Count successful episodes of similar tasks with the SAME call
            # shape (tools in first-use order); this run's own episode was
            # stored just before, so it counts once. A rerun of the same task
            # updates its episode instead of adding one, so reruns do not count.
            from backend.agent.workflow_capture import distinct_tool_names

            _shape = distinct_tool_names(successful)
            _recurrences = 0
            try:
                for _ep in memory.episodic.retrieve_similar(task_summary, limit=10) or []:
                    _seq = _ep.get("tool_sequence") or []
                    if isinstance(_seq, str):
                        _seq = json.loads(_seq)
                    _ok = [s for s in _seq if isinstance(s, dict) and s.get("success", False)]
                    if distinct_tool_names(_ok) == _shape:
                        _recurrences += 1
            except Exception as _rec_exc:  # noqa: BLE001 - no count, no capture
                logger.debug("[AgentKernel] skill recurrence count failed: %r", _rec_exc)
                _recurrences = 0

            key = capture_workflow(
                tool_sequence=successful,
                memory=memory,
                existing_skills=existing_skills,
                is_registered=lambda n: resolve_tool(n) is not None,
                recurrences=_recurrences,
            )
            if key:
                logger.info(
                    "[AgentKernel] Verified skill captured: %s (pattern: %s)",
                    key, pattern_key,
                )
                note = (
                    f"I captured a verified skill from this run "
                    f"({pattern_key}). It will be reused automatically."
                )
                try:
                    if hasattr(self, "_pending_follow_ups"):
                        self._pending_follow_ups.append(note)
                    else:
                        self._pending_follow_ups = [note]
                except Exception:
                    pass
            else:
                logger.debug(
                    "[AgentKernel] Skill capture skipped for pattern: %s", pattern_key
                )
        except Exception as e:
            logger.error("[AgentKernel] Skill capture failed: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # Helpers: thinking-token stripping, planning gate, direct response
    # ------------------------------------------------------------------

    # Endpoints observed to reject the thinking hint. Populated at runtime so a
    # strict provider is asked exactly once and never again this process.
    _THINKING_HINT_REFUSED: set = set()

    @classmethod
    def _thinking_body(cls, use_thinking: bool, endpoint: str = "") -> dict:
        """Provider-agnostic body fields asking a model to skip chain-of-thought.

        WHY THIS IS SHARED (session 260). `_needs_thinking` and the user's
        `_thinking_style` setting already existed, and were wired to the LM
        Studio dispatcher ALONE. Every API-backed model -- which is what the
        product actually runs on -- had no thinking control at all. Measured
        consequence: command-a-plus-05-2026 streamed everything through
        `reasoning_content`, the dispatcher's reasoning fallback returned that
        raw thinking as the answer, and a "~300 word" request came back as
        13,562 characters opening "Thus we must produce a single paragraph...".

        WHY THE OLD FORM DID NOT WORK EITHER. The LM Studio path set
        `_body["extra_body"] = {"chat_template_kwargs": ...}` and then POSTed
        `_body` as raw JSON. `extra_body` is an OpenAI *SDK* concept -- the SDK
        merges its contents into the top level -- so as a literal JSON key it is
        not an API field and servers ignore it. Over raw HTTP the hint belongs
        at the TOP level, which is what this returns.

        Unknown fields make some strict endpoints 400. Callers pass the body
        through `_thinking_retry_body` on failure, which strips the hint and
        remembers the endpoint, so a provider that refuses it is asked once.
        """
        if use_thinking:
            return {}
        if endpoint and endpoint in cls._THINKING_HINT_REFUSED:
            return {}
        # vLLM / LM Studio / SGLang / most OSS OpenAI-compatible servers.
        return {"chat_template_kwargs": {"enable_thinking": False}}

    @classmethod
    def _thinking_retry_body(cls, body: dict, endpoint: str) -> Optional[dict]:
        """Strip the thinking hint after a rejection; None if none was set.

        Remembers the endpoint so the hint is not re-sent for the rest of the
        process -- one wasted request per provider, not one per call.
        """
        if "chat_template_kwargs" not in body:
            return None
        if endpoint:
            cls._THINKING_HINT_REFUSED.add(endpoint)
        _stripped = {k: v for k, v in body.items() if k != "chat_template_kwargs"}
        logger.info(
            "[thinking] endpoint rejected the no-thinking hint; retrying "
            "without it and not re-sending it this process: %s", endpoint,
        )
        return _stripped

    def _needs_thinking(self, text: str) -> bool:
        """
        Return True only for messages that genuinely benefit from chain-of-thought
        reasoning.  Simple conversational questions and greetings skip thinking mode,
        cutting latency from ~30s to ~5s on Qwen3-9B.

        Respects the user's _thinking_style setting:
          concise   â†’ never use thinking
          balanced  â†’ heuristic trigger-based (default)
          thorough  â†’ always use thinking
        """
        style = getattr(self, "_thinking_style", "balanced")
        if style == "concise":
            return False
        if style == "thorough":
            return True

        t = text.lower().strip()

        # Very short messages are almost always conversational
        if len(t.split()) < 7:
            return False

        # Common greetings and social "how are you" patterns
        GREETINGS = [
            "hello",
            "hi",
            "hey",
            "morning",
            "afternoon",
            "evening",
            "greetings",
        ]
        if any(t.startswith(g) for g in GREETINGS) and len(t.split()) < 10:
            return False

        SOCIAL = [
            "how are you",
            "how's it going",
            "how are things",
            "what's up",
            "how have you been",
        ]
        if any(s in t for s in SOCIAL) and len(t.split()) < 12:
            return False

        THINKING_TRIGGERS = [
            # Reasoning keywords
            "why ",
            "how does",
            "how do",
            "explain",
            "analyse",
            "analyze",
            "compare",
            "difference between",
            "pros and cons",
            "trade-off",
            "step by step",
            "walk me through",
            "break down",
            # Code / debugging
            "debug",
            "fix the",
            "what's wrong",
            "error in",
            "refactor",
            "write a function",
            "write code",
            "implement",
            "algorithm",
            # Planning / strategy
            "plan",
            "strategy",
            "best way to",
            "should i",
            "recommend",
            "what would you do",
            "help me design",
            "architect",
            # Math / logic
            "calculate",
            "compute",
            "solve",
            "equation",
            "proof",
            "if ",
            "given that",
            "assuming",
        ]
        return any(trigger in t for trigger in THINKING_TRIGGERS)

    @staticmethod
    def _parse_thinking(text: str) -> tuple:
        """Split model output into (thinking: str, response: str).

        Handles three forms of chain-of-thought output:
        1. <think>â€¦</think> XML tags  (Qwen3 thinking mode)
        2. <thinking>â€¦</thinking> XML tags  (DeepSeek-style)
        3. Untagged preamble paragraphs where the model narrates its reasoning
           ("Okay, the user is askingâ€¦", "Let me thinkâ€¦", etc.) before a blank
           line that separates it from the real answer.

        Returns:
            (thinking, clean_response) â€” thinking is an empty string when none found.
        """
        import re

        thinking_parts: list = []

        # Extract tagged blocks
        for m in re.finditer(r"<think>(.*?)</think>", text, flags=re.DOTALL):
            thinking_parts.append(m.group(1).strip())
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

        for m in re.finditer(r"<thinking>(.*?)</thinking>", text, flags=re.DOTALL):
            thinking_parts.append(m.group(1).strip())
        text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL)

        text = text.strip()

        # Strip untagged reasoning preamble: leading paragraphs that open with
        # known self-narration phrases, separated from the answer by a blank line.
        _PREAMBLE_OPENERS = re.compile(
            r"^(okay[,.]?|alright[,.]?|let me|i need to|i should|i will|"
            r"the user (is|has|wants|asked)|looking at|wait[,.]?|"
            r"so[,.]?\s+(the|i|let)|hmm[,.]?)",
            re.IGNORECASE,
        )
        paragraphs = re.split(r"\n{2,}", text)
        while len(paragraphs) > 1 and _PREAMBLE_OPENERS.match(paragraphs[0].strip()):
            thinking_parts.append(paragraphs.pop(0).strip())
        clean = "\n\n".join(paragraphs).strip()

        return "\n\n".join(thinking_parts), clean

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Return the clean response with all thinking/reasoning removed.
        Convenience wrapper around _parse_thinking for callers that only need
        the response (planning, synthesis, spoken-version calls).
        """
        _, clean = AgentKernel._parse_thinking(text)
        return clean

    # Action/tool intent markers â€” prompts containing these need the DER
    # planning/tool loop. Everything else (simple questions, factual lookups,
    # conversation) takes the fast direct-response path (1 Cerebras call, no
    # "Working on it" filler, no rate-limit burst).
    _ACTION_VERBS = (
        "search", "google", "lookup", "find", "open", "launch", "start",
        "create", "make", "build", "generate", "write", "send", "email",
        "message", "text", "call", "schedule", "remind", "set", "add",
        "delete", "remove", "update", "edit", "change", "list", "play", "show me",
        "book", "order", "buy", "download", "upload", "post", "tweet",
        "run", "execute", "deploy", "install", "configure", "toggle",
        "turn on", "turn off", "switch", "navigate", "go to", "browse",
        "scrape", "fetch", "pull", "sync", "backup", "translate", "summarize",
        "analyze", "compare", "calculate", "convert",
    )

    # Follow-up / anaphora markers â€” these signal the user is continuing a
    # PRIOR task ("now do it for the sales team", "yes, schedule that",
    # "what about the other one"). They carry no action verb of their own but
    # are clearly NOT standalone questions, so they must route to DER (the safe
    # fallback) rather than the dumb direct path. This is the "inertia" the
    # field's routing systems use to avoid misrouting mid-conversation.
    _FOLLOWUP_MARKERS = (
        "now", "then", "also", "too", "as well", "instead", "again",
        "what about", "how about", "and the", "for the", "with the",
        "yes", "yeah", "yep", "sure", "ok", "okay", "do it", "go ahead",
        "proceed", "confirm", "that one", "the other one", "the same",
    )
    _ANAPHORA_PRONOUNS = ("it", "that", "this", "them", "they", "those", "these", "him", "her")

    def _is_followup_to_task(self, text: str, context) -> bool:
        """
        Cheap rule check: does this message continue a prior task rather than
        start a fresh standalone question?  Used to keep multi-turn task flow
        in the DER loop even when the follow-up has no action verb of its own.

        Returns True when the message is short, anaphoric (references "it/that/
        them"), or a confirmation/continuation marker AND the recent context
        shows an active task.  Free (0 model calls).
        """
        t = (text or "").lower().strip()
        if not t or len(t.split()) > 25:
            return False
        # Anaphora: a pronoun with no noun is almost always a continuation.
        words = set(t.split())
        if words & set(self._ANAPHORA_PRONOUNS) and not any(
            v in t for v in self._ACTION_VERBS
        ):
            # "do it", "change that", "what about them" â€” continuation.
            if any(m in t for m in ("do", "change", "update", "edit", "what about",
                                    "how about", "send", "for", "with", "the")):
                return True
        # Explicit continuation/confirmation markers.
        if any(t.startswith(m) or f" {m} " in f" {t} " for m in self._FOLLOWUP_MARKERS):
            return True
        # Prior task context: if the last assistant turn was a plan/tool result,
        # a short user reply is overwhelmingly a follow-up, not a new question.
        if context:
            try:
                last = context[-1] if isinstance(context, (list, tuple)) else None
                if isinstance(last, dict) and last.get("role") == "assistant":
                    c = (last.get("content") or "")
                    if any(k in c.lower() for k in ("plan", "tool", "step", "task", "i'll", "i will")):
                        if len(t.split()) <= 12:
                            return True
            except Exception:
                pass
        return False

    def _classify_intent(self, text: str, context=None) -> str:
        """
        Semantic-logic-gate Tier 0 (REQ-1). Delegates to ``tier0_classify``.

        Preserves the legacy 4-class contract ("chat" | "action" | "followup" |
        "question") for any remaining callers. The authoritative structured
        decision is ``compile_dag().requires_der_kernel``, consumed by
        ``_needs_planning`` below; this method is the compatibility view.
        """
        from backend.agent.semantic_gate import Tier0Intent, tier0_classify

        _v = tier0_classify(text, context)
        return {
            Tier0Intent.CHAT: "chat",
            Tier0Intent.ACTION: "action",
            Tier0Intent.FOLLOWUP: "followup",
            Tier0Intent.QUESTION: "question",
            Tier0Intent.WEB: "action",  # legacy web intent maps to action
        }[_v.intent]

    @property
    def _gate(self):
        """Lazy SemanticLogicGate instance (T7, REQ-1/REQ-8). No model load at
        construction â€” the ontology (Tier 2) is wired via memory_interface."""
        from backend.agent.semantic_gate import SemanticLogicGate

        if getattr(self, "__gate", None) is None:
            self.__gate = SemanticLogicGate(
                tool_mode=getattr(self, "_tool_mode", "auto"),
                memory_interface=getattr(self, "_memory_interface", None),
            )
        return self.__gate

    def register_planning_hook(self, name: str, fn) -> None:
        """Planning-policy hook (REQ-8 AC3): skills/plugins/MCPs register a
        contributor/override that adjusts the draft DAGPlanGraph per task.
        Delegates to the gate's registered-policy store."""
        self._gate.register_policy(name, fn)

    def _web_mode_on(self) -> bool:
        try:
            from backend.agent.agent_gateways import get_global_internet_access

            return bool(get_global_internet_access())
        except Exception:
            return False

    def _needs_planning(self, text: str, context=None) -> bool:
        """
        Planner gate â€” the semantic logic gate (REQ-1, T7, T13).

        ``compile_dag().requires_der_kernel`` is the structured planning
        decision (REQ-8): Tier 0 (deterministic rules) -> Tier 2 (coordinate-
        graph ontology) -> the continuation lens compose the DAGPlanGraph; the
        ``_tool_mode`` policy
        (auto | ask_first | disabled) is applied INSIDE the gate; the web-mode
        gate (``_should_skip_der``) remains the final DER-skip authority
        (REQ-1 AC6).

        T13 gate-proof (tests/behavioral/test_behavioral_intent_routing.py,
        69 cases): equivalence with the legacy router on every non-compound
        prompt (zero regressions) + superiority on compound/multi-concern
        prompts (multi-lane DAGs). The legacy router is retired; this method
        is the permanent routing surface. ``_classify_intent`` remains as the
        legacy 4-class compatibility view (pinned by
        tests/behavioral/test_intent_routing_memory.py).
        """
        _g = self._gate
        _g.tool_mode = getattr(self, "_tool_mode", "auto")
        graph = _g.compile_dag(
            text, context, web_mode=self._web_mode_on(),
            developer=self._effective_launcher_mode() == "developer",
        )
        # REQ-5 AC1 (T8): stash the compiled graph for the [LAYERS] emit
        # (off the hot path â€” the TurnMetrics stamp copies a few attrs).
        self._last_gate_graph = graph
        return bool(graph.requires_der_kernel)

    def _stamp_gate_telemetry(self, metrics) -> None:
        """REQ-5 AC1 (T8): copy the last gate compilation onto the turn's
        TurnMetrics before [LAYERS] emit. Fire-and-forget; defaults when the
        gate never ran (direct calls in tests)."""
        graph = getattr(self, "_last_gate_graph", None)
        if graph is None:
            return
        lanes = ",".join(n.lane.value for n in graph.nodes) if graph.nodes else ""
        domain = graph.nodes[0].domain.value if graph.nodes else ""
        metrics.record_gate(
            domain=domain,
            lanes=lanes,
            latency_ms=graph.latency_ms,
            widen_scope=getattr(graph, "widen_scope", "") or "",
        )

    def _broadcast_inference_event(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        elapsed_s: float,
    ) -> None:
        """Fire-and-forget inference_event broadcast. Delegates to observability module."""
        broadcast_inference_event(
            session_id=self.session_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            elapsed_s=elapsed_s,
            broadcast_loop=self._broadcast_loop,
        )

    # â”€â”€ Token estimation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Rough but fast: 1 token â‰ˆ 4 chars. Real tokenizer adds <5% accuracy gain
    # but costs 10-50ms per call â€” not worth it for windowing decisions.
    _CHARS_PER_TOKEN: int = 4

    # Context budget for direct responses. Keeps the most recent history
    # within the model's 32k window, leaving ~8k for system prompt + response.
    # With episodic injection headroom this sits at ~20k chat tokens max.
    _DIRECT_CTX_BUDGET: int = (
        24_000  # tokens (supports 12k context + system + response)
    )




    @staticmethod
    def _chunk_batcher(
        callback: Optional[Callable[[str], None]],
        interval: float = 0.05,
    ) -> Callable[[str], None]:
        """Delegate to streaming module."""
        return _streaming.chunk_batcher(callback, interval)

    def _stream_and_collect(
        self,
        resp,
        chunk_callback: Optional[Callable[[str], None]],
        reasoning_callback: Optional[Callable[[str], None]] = None,
        on_first_token=None,
    ) -> str:
        """Delegate to streaming module."""
        return _streaming.stream_and_collect(
            resp,
            chunk_callback,
            reasoning_callback=reasoning_callback,
            on_first_token=on_first_token,
        )

    def _respond_direct(
        self,
        text: str,
        context: List[Dict],
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
        tools: Optional[bool] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """
        Respond directly to the user without planning or tool execution.
        Routes to the right backend provider based on IRISConfig routing mode
        or auto-detected provider type.

        Context uses all three memory layers (see CONTEXT_ENGINEERING.md):
          Layer 1: Mycelium coordinates â†’ system prompt
          Layer 2: Episodic store       â†’ memory block prefix
          Layer 3: Full history         â†’ token-aware (not a hard roll window)

        Returns: response text string.
        """
        # The previous turn's rows (chain + chunks) may still be queued on the
        # one writer; this assembly READS them to decide what the model sees, so
        # drain first (bounded). Measured 2026-10-31: without it the newest
        # taught fact was invisible to the next turn.
        try:
            from backend.memory.db import app_flush

            app_flush(2.0)
        except Exception:  # noqa: BLE001 - assembly still runs on settled rows
            pass
        _t_assemble = time.perf_counter()
        messages = self._assemble_direct_context(text, context, session_id=session_id)
        logger.info("[Timing] assemble_direct: %.0f ms",
                    (time.perf_counter() - _t_assemble) * 1000)
        # OBSERVABILITY (2026-10-29, T48): name the path that answered and how
        # much memory reached it. Without this line a pass/fail cannot be
        # attributed to a layer - the memory gate was read three times against
        # the wrong one.
        try:
            _tags = ("<memory>", "<context_memory>", "<mycelium_profile>",
                     "<cross_session_memory>", "<prior_memory>", "<file_memory>")
            _mem_blocks = sum(
                1 for m in messages
                if any(t in (m.get("content") or "") for t in _tags)
            )
            logger.info(
                "[TURN-PATH] session=%s path=direct mem_blocks=%d msgs=%d",
                session_id, _mem_blocks, len(messages),
            )
        except Exception:  # noqa: BLE001 - observability never blocks a reply
            pass
        messages = self._sanitize_messages(messages)

        # Resolve inference behaviour settings
        _max_tokens = {"short": 1024, "medium": 4096, "long": 8192}.get(
            getattr(self, "_response_length", "medium"), 4096
        )
        _temperature = {"fast": 0.9, "balanced": 0.6, "accurate": 0.3}.get(
            getattr(self, "_reasoning_effort", "balanced"), 0.6
        )
        _reasoning_effort_val = getattr(self, "_reasoning_effort", "balanced")

        # === Load IRISConfig for routing ===
        config_mode = getattr(self, "_config_mode", None)
        config = None
        if not config_mode:
            try:
                from backend.iris_config import load_config

                config = load_config()
                config_mode = config.routing.mode
            except Exception as _cfg_err:
                logger.warning(f"[RespondDirect] Config load failed: {_cfg_err}")
                config_mode = "auto"

        # === Tool definitions for function calling (gated by internet access) ===
        # When the web toggle is ON, get_available_tools() includes search /
        # crawler_query; when OFF, those are omitted. The agent decides when to
        # use them via the ReAct loop below. See plan Issue E.
        import json as _json
        # REQ-30 edge (2026-09-26): `tools=False` is the TEXT path. A caller
        # that wants a classification, not an action, must not ship a dozen
        # function definitions with its prompt: the model answers a pure
        # "sort this into topics" question with a tool call, Cohere rejects it
        # (422 HALLUCINATED_ALL_TOOL_CALLS / INVALID_TOOL_GENERATION) and the
        # caller pays a wasted request every time. Measured live in
        # SourceRegistry._extract_topics. None keeps the historical behaviour,
        # so no existing caller changes.
        _tools = self._get_openai_tools(text) if tools is not False else []

        # Local dispatch wrapper â€” routes to the correct backend provider and
        # returns (response_text, thinking_text, tool_calls).
        def _call(_msgs: List[Dict], _tools_arg: Optional[List[Dict]]) -> Tuple[str, str, List[Dict]]:
            _text, _thinking, _tool_calls = self._router.generate(
                "reasoning", _msgs, tools=_tools_arg,
                max_tokens=_max_tokens, temperature=_temperature,
                chunk_callback=chunk_callback, reasoning_callback=reasoning_callback,
            )
            self._accrue_tokens(
                _text, getattr(self._router, "last_usage", None),
                source="_respond_direct",
            )
            return _text, _thinking, _tool_calls

        # === Initial LLM call ===
        _response, _thinking, _tool_calls = _call(messages, _tools)
        self._pending_thinking = _thinking

        # === ReAct tool-call loop ===
        # If the model requested tool calls (e.g. web search / crawler_query),
        # execute them, feed results back, and let the model produce the final
        # answer. Bounded to avoid runaway loops.
        # Execution audit B14 (2026-09-29): 3 rounds cut real work short and the
        # calls requested in round 4 were dropped without a word. The bound is
        # larger, and hitting it ends with one tool-less call (below) so the
        # model says what it has and what is unfinished.
        _MAX_TOOL_ROUNDS = 8
        _round = 0
        # Tools run under the TURN's WebSocket session - the key the project
        # workdir, the session shell and permission routing are bound to (the
        # DER path already does this). The conversation id is not a session.
        _tool_session = (
            getattr(self, "_turn_session_id", None)
            or self.session_id or self.conversation_id or "voice"
        )
        while _tool_calls and _round < _MAX_TOOL_ROUNDS:
            _round += 1
            messages.append({
                "role": "assistant",
                "content": _response or None,
                "tool_calls": _tool_calls,
            })
            for _tc in _tool_calls:
                _tc_id = _tc.get("id")
                _fn = _tc.get("function", {})
                _name = _fn.get("name", "")
                _args_raw = _fn.get("arguments", "{}") or "{}"
                try:
                    _params = _json.loads(_args_raw) if _args_raw.strip() else {}
                except Exception:
                    _params = {"__raw_arguments__": _args_raw}
                # REQ-16 AC16.2 (T20): this ReAct loop picks tools with native
                # function calling, OUTSIDE ToolDecisionBox.resolve() â€” so the
                # engine never saw this traffic and the reliability curve was
                # built on a biased subset. Shadow-score the same choice here
                # (engine pick vs the tool the Brain actually called) and write
                # the row through the box's single ledger writer. `async_=True`
                # = a daemon thread, so the fast chat path pays ZERO added
                # latency; the whole block is best-effort and cannot break it.
                try:
                    # `last_result`: the most recent tool message in the ReAct
                    # conversation - the signal the Brain actually picks on.
                    _lr = ""
                    try:
                        for _m in reversed(messages):
                            if _m.get("role") == "tool":
                                _lr = str(_m.get("content") or "")[:600]
                                break
                    except Exception:  # noqa: BLE001
                        _lr = ""
                    # tc-frame-v5: this turn's calls BEFORE this one, in order
                    # (names + targets; the ReAct transcript holds no ok flag).
                    _hist = ""
                    try:
                        from backend.agent.node_executor import _target as _tgt

                        _prev = []
                        for _m in messages:
                            for _ptc in (_m.get("tool_calls") or []) if _m.get("role") == "assistant" else []:
                                if _ptc is _tc:
                                    raise StopIteration
                                _pf = _ptc.get("function") or {}
                                try:
                                    _pp = _json.loads(_pf.get("arguments") or "{}")
                                except Exception:  # noqa: BLE001
                                    _pp = {}
                                _prev.append(f"{_pf.get('name', '')} "
                                             f"{_tgt(_pp if isinstance(_pp, dict) else {})}".strip())
                    except StopIteration:
                        pass
                    except Exception:  # noqa: BLE001 - a shadow never needs context
                        _prev = []
                    _hist = "; ".join(_prev[-6:])[-400:]
                    # tc-frame-v10 (2026-11-04): the option text is the BARE
                    # tool name. MEASURED by replay on the active engine
                    # (1200 recorded tc-frame-v8 states, the same rows for
                    # both variants): the tools' decision lines measured
                    # oof AUROC 0.6569 and the bare names 0.6955, with
                    # monotonic confidence bands in both cases. The
                    # instruction carries the question; the option text must
                    # not argue for a tool (the same lesson as the
                    # review_verdict v9 criteria and the tool_choice control
                    # labels, oracle.md 7.6).
                    # the menu the Brain was OFFERED this turn. `_offered` was
                    # read here but only defined in the DER node path, so this
                    # row raised NameError and was lost on every direct-path
                    # tool call since tc-frame-v10 (found 2026-11-11).
                    _offered = [
                        (t.get("function") or {}).get("name")
                        for t in (_tools or [])
                    ]
                    _hints = {n: n for n in _offered if n}
                    _hints.update({n: n for n in ("DELEGATE", "NONE")})
                    self._get_tool_box().record_shadow_tool_choice(
                        goal=text,
                        observed_tool=_name,
                        observed_params=_params,
                        candidates=_offered or None,
                        last_result=_lr or None,
                        option_criteria=_hints or None,
                        calls_this_step=_hist or None,
                        session_id=self.conversation_id or "voice",
                        conversation_id=self.conversation_id or "",
                        async_=True,
                    )
                except Exception as _shadow_err:  # noqa: BLE001
                    logger.debug(
                        "[RespondDirect] shadow tool-choice row failed: %r",
                        _shadow_err,
                    )
                try:
                    _raw = asyncio.run(
                        self._tool_bridge.execute_tool(
                            tool_name=_name,
                            params=_params,
                            session_id=_tool_session,
                        )
                    )
                except RuntimeError:
                    # asyncio.run() fails if a loop is already running in this
                    # thread (shouldn't happen in the executor, but guard anyway).
                    import concurrent.futures as _cf
                    with _cf.ThreadPoolExecutor(max_workers=1) as _pool:
                        _raw = _pool.submit(
                            asyncio.run,
                            self._tool_bridge.execute_tool(
                                tool_name=_name,
                                params=_params,
                                session_id=_tool_session,
                            ),
                        ).result(timeout=60)
                _content = self._format_tool_result(_raw)
                messages.append({
                    "role": "tool",
                    "tool_call_id": _tc_id,
                    "name": _name,
                    "content": _content,
                })
            _response, _thinking, _tool_calls = _call(messages, _tools)
            self._pending_thinking = _thinking

        if _tool_calls:
            # Bound reached with calls still requested: never drop them in
            # silence. One final call WITHOUT tools makes the model answer from
            # what it has and name what is left undone.
            logger.info(
                "[RespondDirect] tool-round bound (%d) reached with %d call(s) "
                "pending conv=%s - asking for a final answer",
                _MAX_TOOL_ROUNDS, len(_tool_calls), self.conversation_id,
            )
            messages.append({
                "role": "user",
                "content": (
                    "Tool budget for this turn is used up. Answer now from the "
                    "results you have, and say plainly what is still unfinished."
                ),
            })
            _response, _thinking, _ = _call(messages, None)
            self._pending_thinking = _thinking

        return _response

    # ------------------------------------------------------------------ #
    # Dispatch methods
    # ------------------------------------------------------------------ #

    def _dispatch_api(
        self,
        messages: List[Dict],
        max_tokens: int,
        temperature: float,
        reasoning_effort: str = "balanced",
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
        tools: Optional[List[Dict]] = None,
    ) -> Tuple[str, str, List[Dict]]:
        """Remote API provider â€” direct httpx streaming (Chutes, OpenAI, etc.).

        Uses httpx directly instead of _llm.complete() to avoid thread-pool hangs.
        Returns (response_text, thinking_text).

        Raises RuntimeError on API errors â€” no silent error swallowing.
        """
        import json as _json
        import time as _perf_t
        import httpx as _httpx
        from backend.utils.ssl_context import get_ssl_context

        _api_base = self._api_base_url or "https://api.openai.com/v1"
        _api_key = self._api_key or ""
        sel = self._selected_reasoning_model or "local-model"
        if sel in ("local-model", "Currently Loaded Model", "currently-loaded-model"):
            raise RuntimeError(
                "No reasoning model configured. Set a model in Settings â†’ "
                "Model Selection (e.g. Cerebras gemma-4-31b) before sending messages."
            )

        _url = f"{_api_base.rstrip('/')}/chat/completions"
        _headers = {
            "Content-Type": "application/json",
        }
        # REQ-1 (specs/local-model-lifecycle-sync): never emit `Authorization:
        # Bearer ` with an empty value â€” httpx rejects it as an illegal header
        # and the kernel crashes with `Illegal header value b'Bearer '`. The
        # router raises ProviderNotReadyError(missing_api_key) before this
        # path, but guard here too so a direct call fails closed.
        if _api_key and _api_key.strip():
            _headers["Authorization"] = f"Bearer {_api_key.strip()}"
        _body = {
            "model": sel,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            _body["tools"] = tools
            _body["tool_choice"] = "auto"

        # Session 260: EVERY model that can be told to skip chain-of-thought
        # is now told, not just the LM Studio one. This path had NO thinking
        # control at all, which is why an API-backed reasoning model returned
        # its deliberation as the answer.
        try:
            _body.update(
                self._thinking_body(
                    self._needs_thinking(
                        messages[-1].get("content", "") if messages else ""
                    ),
                    endpoint=str(sel or ""),
                )
            )
        except Exception as _think_exc:  # noqa: BLE001 -- never fail on a hint
            logger.debug("[thinking] hint not applied: %s", _think_exc)
        # â”€â”€ Telemetry: log API request shape (not content) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            _msg_count = len(messages)
            _total_chars = sum(len(str(m.get("content", ""))) for m in messages)
            from backend.core.logging_config import get_agent_logger

            get_agent_logger().info(
                "API request",
                provider=self._model_provider,
                model=sel,
                messages=_msg_count,
                chars=_total_chars,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception:
            pass

        if chunk_callback:
            # Streaming path
            _t0 = _perf_t.perf_counter()
            full_reply = ""
            _reasoning_buf: List[str] = []
            _tool_calls_acc: Dict[int, Dict] = {}
            _tool_calls: List[Dict] = []

            for _attempt in range(3):
                _stream_ok = False
                try:
                    with _httpx.Client(timeout=_httpx.Timeout(60.0), verify=get_ssl_context()) as _client:
                        with _client.stream(
                            "POST", _url, headers=_headers, json={**_body, "stream": True}
                        ) as _resp:
                            if _resp.status_code == 429:
                                # Rate-limited (LM Studio "queue_exceeded" / high
                                # traffic). Discard body and retry with backoff.
                                try:
                                    _resp.read()
                                except Exception:
                                    pass
                                logger.warning(
                                    "[DispatchAPI] 429 rate-limit (attempt %d/3) â€” retrying",
                                    _attempt + 1,
                                )
                                continue
                            if _resp.status_code != 200:
                                # Streaming response: reading .text raises ResponseNotRead
                                # because httpx hasn't consumed the body yet. Read the first
                                # chunk manually for the error detail.
                                try:
                                    _first = next(_resp.iter_bytes(), b"")
                                    _err_detail = _first[:200].decode("utf-8", errors="replace")
                                except Exception:
                                    _err_detail = "(could not read error body)"
                                # Session 260: a provider that refuses the
                                # no-thinking hint must degrade, not fail. The
                                # hint is an optimisation; the turn is not.
                                # Strip it, remember the endpoint so it is
                                # asked exactly once this process, and retry.
                                if _resp.status_code in (400, 422):
                                    _retry_body = self._thinking_retry_body(
                                        _body, str(sel or "")
                                    )
                                    if _retry_body is not None:
                                        _body = _retry_body
                                        continue
                                raise RuntimeError(
                                    f"API returned {_resp.status_code}: {_err_detail}"
                                )
                            for _line in _resp.iter_lines():
                                if not _line or not _line.startswith("data:"):
                                    continue
                                _data = _line[5:].strip()
                                if _data == "[DONE]":
                                    break
                                # Let JSONDecodeError propagate on malformed data
                                _chunk = _json.loads(_data)
                                _choices = _chunk.get("choices", [])
                                if not _choices:
                                    continue
                                _delta = _choices[0].get("delta", {})

                                # Reasoning content â€” field name varies by provider
                                _r = _delta.get("reasoning_content") or _delta.get("reasoning")
                                if _r:
                                    _reasoning_buf.append(_r)
                                    if reasoning_callback:
                                        reasoning_callback(_r)

                                # Text content
                                _c = _delta.get("content")
                                if _c:
                                    full_reply += _c
                                    if chunk_callback:
                                        chunk_callback(_c)

                                # Tool calls (function calling) â€” accumulate across
                                # streaming deltas by index.
                                for _tc_item in (_delta.get("tool_calls") or []):
                                    _idx = _tc_item.get("index", 0)
                                    _acc = _tool_calls_acc.setdefault(
                                        _idx,
                                        {
                                            "id": "",
                                            "type": "function",
                                            "function": {"name": "", "arguments": ""},
                                        },
                                    )
                                    if _tc_item.get("id"):
                                        _acc["id"] = _tc_item["id"]
                                    _fn = _tc_item.get("function") or {}
                                    if _fn.get("name"):
                                        _acc["function"]["name"] = _fn["name"]
                                    if _fn.get("arguments"):
                                        _acc["function"]["arguments"] += _fn["arguments"]
                            _stream_ok = True
                except RuntimeError:
                    raise
                except Exception as _e:
                    logger.warning(
                        "[DispatchAPI] stream error (attempt %d/3): %s",
                        _attempt + 1,
                        _e,
                    )
                    if _attempt == 2:
                        raise
                if _stream_ok:
                    break
                if _attempt < 2:
                    _perf_t.sleep(1.0 * (2 ** _attempt))

            _tool_calls = [v for v in _tool_calls_acc.values()]

            reasoning_text = "".join(_reasoning_buf)
            if reasoning_callback:
                reasoning_callback("")  # end marker
            if chunk_callback:
                chunk_callback("")  # force-flush

            # Reasoning fallback: some models return answer in reasoning_content
            # with empty content. When using reasoning fallback, skip _parse_thinking
            # since the reasoning IS the answer (preamble stripping would kill it).
            if not full_reply.strip() and reasoning_text.strip() and not _tool_calls:
                _elapsed = _perf_t.perf_counter() - _t0
                _ctok = max(1, len(reasoning_text) // 4)
                _ptok = sum(len(m.get("content", "")) for m in messages) // 4
                self._broadcast_inference_event(sel, _ptok, _ctok, _elapsed)
                return reasoning_text, reasoning_text, []

            thinking, clean = self._parse_thinking(full_reply)
            _elapsed = _perf_t.perf_counter() - _t0
            _ctok = max(1, len(full_reply) // 4)
            _ptok = sum(len(m.get("content", "")) for m in messages) // 4
            self._broadcast_inference_event(sel, _ptok, _ctok, _elapsed)
            return clean or "(I see.)", thinking, _tool_calls

        else:
            # Non-streaming path
            _t0 = _perf_t.perf_counter()
            _result = None
            for _attempt in range(3):
                try:
                    with _httpx.Client(timeout=_httpx.Timeout(60.0), verify=get_ssl_context()) as _client:
                        _resp = _client.post(_url, headers=_headers, json=_body)
                        if _resp.status_code == 429:
                            # Rate-limit-aware backoff (REQ-5): wait for the
                            # provider's reset window instead of a fixed 1-2s sleep
                            # that burns attempts without relief. Prefer
                            # x-ratelimit-reset (epoch seconds) or Retry-After
                            # (seconds); fall back to bounded exponential backoff.
                            _reset = _resp.headers.get("x-ratelimit-reset")
                            _retry_after = _resp.headers.get("Retry-After")
                            _wait = None
                            if _retry_after and str(_retry_after).isdigit():
                                _wait = float(_retry_after)
                            elif _reset:
                                try:
                                    _reset_ts = float(_reset)
                                    # x-ratelimit-reset may be epoch seconds or
                                    # seconds-remaining depending on provider.
                                    _now = time.time()
                                    if _reset_ts > _now:  # epoch seconds
                                        _wait = _reset_ts - _now
                                    else:  # seconds remaining
                                        _wait = _reset_ts
                                except (ValueError, TypeError):
                                    _wait = None
                            if _wait is None:
                                _wait = min(1.0 * (2 ** _attempt), 30.0)
                            _wait = max(0.0, min(_wait, 60.0))  # hard cap 60s
                            logger.warning(
                                "[DispatchAPI] 429 rate-limit (attempt %d/3) â€” "
                                "waiting %.1fs for reset window",
                                _attempt + 1,
                                _wait,
                            )
                            if _attempt < 2:
                                _perf_t.sleep(_wait)
                            continue
                        if _resp.status_code != 200:
                            raise RuntimeError(
                                f"API returned {_resp.status_code}: {_resp.text[:200]}"
                            )
                        _result = _resp.json()
                        break
                except RuntimeError:
                    raise
                except Exception as _e:
                    logger.warning(
                        "[DispatchAPI] request error (attempt %d/3): %s",
                        _attempt + 1,
                        _e,
                    )
                    if _attempt == 2:
                        raise
            if _result is None:
                raise RuntimeError("API request failed after retries")

            _msg = _result.get("choices", [{}])[0].get("message", {})
            _reply = _msg.get("content", "")
            _tool_calls = _msg.get("tool_calls") or []

            if not _reply and not _tool_calls:
                raise RuntimeError("Empty response from API")

            # Record usage with real API tokens if available
            _elapsed = _perf_t.perf_counter() - _t0
            _usage = _result.get("usage", {})
            _ptok = _usage.get("prompt_tokens", max(1, sum(len(m.get("content", "")) for m in messages) // 4))
            _ctok = _usage.get("completion_tokens", max(1, len(_reply) // 4))
            self._broadcast_inference_event(sel, _ptok, _ctok, _elapsed)

            # â”€â”€ FIX (session 154): Invoke chunk_callback on non-streaming path â”€â”€
            # When the LLM provider returns the full reply in one shot (Cerebras,
            # Cohere batch mode, etc.), chunk_callback is never called, so the
            # TTS sentence_queue only receives the None sentinel and the
            # producer breaks immediately without synthesizing any audio.
            # Send the full reply as a single chunk, then a force-flush (""),
            # matching the streaming path's end-of-stream semantics.
            if chunk_callback and _reply:
                chunk_callback(_reply)
                chunk_callback("")  # force-flush end-of-stream

            thinking, clean = self._parse_thinking(_reply)
            return clean or "(I see.)", thinking, _tool_calls

    def _dispatch_openai_compat(
        self,
        messages: List[Dict],
        max_tokens: int,
        temperature: float,
        reasoning_effort: str = "balanced",
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
        tools: Optional[List[Dict]] = None,
    ) -> Tuple[str, str, List[Dict]]:
        """LM Studio / local OpenAI-compatible endpoint â€” direct httpx streaming.

        Similar to _dispatch_api but uses _lmstudio_endpoint and LM Studio's
        Extra-body template hints. Returns (response_text, thinking_text).

        Raises RuntimeError on API errors â€” no silent error swallowing.
        """
        import json as _json
        import time as _perf_t
        import httpx as _httpx
        from backend.utils.ssl_context import get_ssl_context

        _api_base = self._lmstudio_endpoint or "http://localhost:1234"
        sel = self._selected_reasoning_model or "local-model"
        use_thinking = self._needs_thinking(
            messages[-1].get("content", "") if messages else ""
        )

        _url = f"{_api_base.rstrip('/')}/v1/chat/completions"

        # LM Studio may serve an older API path
        _url_v1 = f"{_api_base.rstrip('/')}/chat/completions"

        _body = {
            "model": sel,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            _body["tools"] = tools
            _body["tool_choice"] = "auto"

        # Session 260: was `_body["extra_body"] = {...}` -- an OpenAI SDK
        # concept, not an API field. Posted as raw JSON it was ignored, so this
        # path's thinking control never actually did anything. Over raw HTTP the
        # hint belongs at the TOP level. Same helper as the API dispatcher, so
        # both obey `_thinking_style` identically.
        _body.update(self._thinking_body(use_thinking, endpoint=_api_base))

        if chunk_callback:
            # Streaming path
            _t0 = _perf_t.perf_counter()
            full_reply = ""
            _reasoning_buf: List[str] = []
            _tool_calls_acc: Dict[int, Dict] = {}
            _tool_calls: List[Dict] = []

            for _attempt in range(3):
                _stream_ok = False
                try:
                    with _httpx.Client(timeout=_httpx.Timeout(60.0), verify=get_ssl_context()) as _client:
                        # Try the standard v1 path, fall back to v1-less path for older LM Studio
                        for _try_url in [_url, _url_v1]:
                            try:
                                _resp = _client.stream(
                                    "POST",
                                    _try_url,
                                    headers={"Content-Type": "application/json"},
                                    json={**_body, "stream": True},
                                )
                                break
                            except Exception:
                                continue
                        else:
                            raise RuntimeError(f"Could not connect to {_api_base}")

                        with _resp as _stream:
                            if _stream.status_code == 429:
                                try:
                                    _stream.read()
                                except Exception:
                                    pass
                                logger.warning(
                                    "[DispatchLMStudio] 429 rate-limit (attempt %d/3) â€” retrying",
                                    _attempt + 1,
                                )
                                continue
                            if _stream.status_code != 200:
                                # Streaming response: `.text` raises ResponseNotRead
                                # ("Attempted to access streaming response content,
                                # without having called read()"). Read the first
                                # chunk manually for the error detail.
                                try:
                                    _first = next(_stream.iter_bytes(), b"")
                                    _err_detail = _first[:200].decode(
                                        "utf-8", errors="replace"
                                    )
                                except Exception:
                                    _err_detail = "(could not read error body)"
                                raise RuntimeError(
                                    f"{_api_base} returned {_stream.status_code}: {_err_detail}"
                                )
                            for _line in _stream.iter_lines():
                                if not _line or not _line.startswith("data:"):
                                    continue
                                _data = _line[5:].strip()
                                if _data == "[DONE]":
                                    break
                                _chunk = _json.loads(_data)
                                _choices = _chunk.get("choices", [])
                                if not _choices:
                                    continue
                                _delta = _choices[0].get("delta", {})

                                _r = _delta.get("reasoning_content") or _delta.get("reasoning")
                                if _r:
                                    _reasoning_buf.append(_r)
                                    if reasoning_callback:
                                        reasoning_callback(_r)

                                _c = _delta.get("content")
                                if _c:
                                    full_reply += _c
                                    if chunk_callback:
                                        chunk_callback(_c)

                                for _tc_item in (_delta.get("tool_calls") or []):
                                    _idx = _tc_item.get("index", 0)
                                    _acc = _tool_calls_acc.setdefault(
                                        _idx,
                                        {
                                            "id": "",
                                            "type": "function",
                                            "function": {"name": "", "arguments": ""},
                                        },
                                    )
                                    if _tc_item.get("id"):
                                        _acc["id"] = _tc_item["id"]
                                    _fn = _tc_item.get("function") or {}
                                    if _fn.get("name"):
                                        _acc["function"]["name"] = _fn["name"]
                                    if _fn.get("arguments"):
                                        _acc["function"]["arguments"] += _fn["arguments"]
                            _stream_ok = True
                except RuntimeError:
                    raise
                except Exception as _e:
                    logger.warning(
                        "[DispatchLMStudio] stream error (attempt %d/3): %s",
                        _attempt + 1,
                        _e,
                    )
                    if _attempt == 2:
                        raise
                if _stream_ok:
                    break
                if _attempt < 2:
                    _perf_t.sleep(1.0 * (2 ** _attempt))

            _tool_calls = [v for v in _tool_calls_acc.values()]

            reasoning_text = "".join(_reasoning_buf)
            if reasoning_callback:
                reasoning_callback("")
            if chunk_callback:
                chunk_callback("")

            if not full_reply.strip() and reasoning_text.strip() and not _tool_calls:
                return reasoning_text, reasoning_text, []

            thinking, clean = self._parse_thinking(full_reply)
            return clean or "(I see.)", thinking, _tool_calls

        else:
            # Non-streaming path
            _t0 = _perf_t.perf_counter()
            _result = None
            for _attempt in range(3):
                try:
                    with _httpx.Client(timeout=_httpx.Timeout(60.0), verify=get_ssl_context()) as _client:
                        for _try_url in [_url, _url_v1]:
                            try:
                                _resp = _client.post(
                                    _try_url,
                                    headers={"Content-Type": "application/json"},
                                    json=_body,
                                )
                                if _resp.status_code == 429:
                                    logger.warning(
                                        "[DispatchLMStudio] 429 rate-limit (attempt %d/3) â€” retrying",
                                        _attempt + 1,
                                    )
                                    if _attempt < 2:
                                        _perf_t.sleep(1.0 * (2 ** _attempt))
                                    break  # retry outer loop
                                if _resp.status_code < 500:
                                    break
                            except Exception:
                                continue
                        else:
                            raise RuntimeError(f"Could not connect to {_api_base}")

                        if _resp.status_code == 429:
                            continue
                        if _resp.status_code != 200:
                            raise RuntimeError(
                                f"{_api_base} returned {_resp.status_code}: {_resp.text[:200]}"
                            )
                        _result = _resp.json()
                        break
                except RuntimeError:
                    raise
                except Exception as _e:
                    logger.warning(
                        "[DispatchLMStudio] request error (attempt %d/3): %s",
                        _attempt + 1,
                        _e,
                    )
                    if _attempt == 2:
                        raise
            if _result is None:
                raise RuntimeError(f"Request to {_api_base} failed after retries")

            _msg = _result.get("choices", [{}])[0].get("message", {})
            _reply = _msg.get("content", "")
            _tool_calls = _msg.get("tool_calls") or []

            if not _reply and not _tool_calls:
                # SELF-DIAGNOSING (2026-09-28). This raised a bare "Empty
                # response from LM Studio" SIXTEEN times in one session and
                # recorded nothing about the REQUEST, so the cause could not be
                # established afterwards - the label even pointed at another
                # product's port. The three fields below are the whole
                # diagnosis, so the next occurrence carries its own evidence:
                #   finish_reason  'length' -> the reply was cut off by
                #                  max_tokens; 'stop' with empty content -> the
                #                  model emitted EOS immediately, which is what a
                #                  truncated/over-long prompt produces;
                #   usage.prompt_tokens -> compare against the model's n_ctx to
                #                  see whether llama-server truncated the prompt
                #                  (prompt + tool schemas can exceed 16384);
                #   the raw body -> what the server actually said.
                _choice0 = (_result.get("choices") or [{}])[0] or {}
                logger.warning(
                    "[Dispatch] EMPTY completion from %s: messages=%d "
                    "finish_reason=%r usage=%s raw=%r",
                    _api_base, len(messages),
                    _choice0.get("finish_reason"),
                    _result.get("usage"),
                    str(_result)[:300],
                )
                raise RuntimeError(f"Empty response from {_api_base}")

            # Record usage with real API tokens if available
            _usage = _result.get("usage", {})
            _ptok = _usage.get("prompt_tokens", max(1, sum(len(m.get("content", "")) for m in messages) // 4))
            _ctok = _usage.get("completion_tokens", max(1, len(_reply) // 4))
            _elapsed_ns = _perf_t.perf_counter() - _t0
            self._broadcast_inference_event(sel, _ptok, _ctok, _elapsed_ns)

            # â”€â”€ FIX (session 154): Invoke chunk_callback on non-streaming path â”€â”€
            # Same fix as _dispatch_api: when LM Studio returns the full reply
            # in one shot, chunk_callback is never called, so the TTS
            # sentence_queue only receives the None sentinel. Send the full
            # reply as a single chunk, then a force-flush ("").
            if chunk_callback and _reply:
                chunk_callback(_reply)
                chunk_callback("")  # force-flush end-of-stream

            thinking, clean = self._parse_thinking(_reply)
            return clean or "(I see.)", thinking, _tool_calls

    def _dispatch_inprocess(
        self,
        messages: List[Dict],
        max_tokens: int,
        temperature: float,
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, str]:
        """Local in-process model inference.

        Uses the locally loaded model (via _model_router / get_reasoning_model()).
        Falls back to the old `reasoning_model.generate()` if chunk_callback is None.
        Returns (response_text, thinking_text).
        """
        reasoning_model = None
        if self._model_router and self._selected_reasoning_model:
            reasoning_model = self._model_router.models.get(
                self._selected_reasoning_model
            )
        if not reasoning_model and self._model_router:
            reasoning_model = self._model_router.get_reasoning_model()

        if not reasoning_model:
            raise RuntimeError("No local model loaded")

        reply = reasoning_model.generate(
            messages[-1].get("content", "") if messages else ""
        )

        # â”€â”€ FIX (session 154): Invoke chunk_callback on non-streaming path â”€â”€
        # Local in-process models generate the full reply at once. Without
        # this call, the TTS pipeline never sees the response text.
        if chunk_callback and reply:
            chunk_callback(reply)
            chunk_callback("")  # force-flush end-of-stream

        thinking, clean = self._parse_thinking(reply)
        return clean or "(I see.)", thinking, []

    # Word count above which we consider a reply "long" for TTS purposes.
    # Only applied to DOCUMENT-like content; conversational replies are always spoken in full.
    _SPOKEN_WORD_LIMIT: int = 40
    # Maximum spoken word count for document summaries (hard cap).
    _SPOKEN_MAX_WORDS: int = 80


    # â”€â”€ Tool definitions for OpenAI-compatible function calling â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _ensure_tool_bridge(self) -> None:
        """Lazy-initialize the tool bridge on first access.

        The bridge is created as a background task (its initialize() is async
        and wires MCP/server connections); tools from its in-process dict are
        available immediately.  This MUST run before ANY code reads
        ``self._tool_bridge.get_available_tools()`` â€” ``_plan_task`` builds the
        planner's AVAILABLE TOOLS block from it, and a None bridge silently
        produces an empty tool list (planner then emits tool-less speak steps).
        """
        if not self._tool_bridge:
            try:
                from backend.agent.tool_bridge import get_agent_tool_bridge

                self._tool_bridge = get_agent_tool_bridge()
                if not self._tool_bridge._initialized:
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._tool_bridge.initialize())
                    except RuntimeError:
                        # No running event loop â€” run synchronously
                        asyncio.run(self._tool_bridge.initialize())
                logger.info("[AgentKernel] Tool bridge lazy-initialized")
            except Exception as e:
                logger.warning(f"[AgentKernel] Tool bridge init failed: {e}")

    def _get_openai_tools(self, text: str = "") -> List[Dict]:
        """Convert tool_bridge tool list to OpenAI-compatible function-calling format.

        When `text` is provided, web search / crawler tools are included only
        if the text explicitly asks for a web search. This prevents the model
        from calling web tools unnecessarily for simple conversational prompts
        even when the web toggle is ON.

        Each entry becomes:
          {"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}
        """
        self._ensure_tool_bridge()
        if not self._tool_bridge:
            return []
        # Single shared converter (tool_registry.to_function_schema). This used
        # to be an inline copy, and ToolDecisionBox had no conversion at all â€”
        # so the same tools were valid on one code path and a 422 on the other.
        from backend.agent.tool_registry import to_function_schema

        openai_tools: List[Dict] = to_function_schema(
            self._tool_bridge.get_available_tools()
        )
        # â”€â”€ Web tools are NOT filtered out of the model's tool list â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # REMOVED 2026-10-07. This used to strip `search` and `crawler_query`
        # unless `_is_web_search_request(text)` was true, and that predicate
        # reduced to a 16-phrase substring list, because the Oracle can never
        # decide it:
        #     threshold_for("web_intent") -> None   (cfg.thresholds is empty)
        #     oracle_acts("web_intent", conf) -> False at 0.50 .. 0.95
        # The web_intent consumer was denied enforcement after precision 0.41
        # (Stage B, 2026-10-05), and an uncalibrated consumer fails closed, so
        # the KEYWORDS were the sole decider for a capability.
        #
        # MEASURED on the owner's real sentences - all evaluated False, so the
        # web tools were withheld from the model:
        #   "Could you search up the recent repo of the math?"       -> stripped
        #   "Could you look into the one by OpenAI and let me know..." -> stripped
        #   "check the openai/math repository on github"              -> stripped
        # "look into" is not in the trigger list at all.
        #
        # Consequences that made this a defect and not a tuning knob:
        #   - It is not web-specific in spirit but is web-specific in code:
        #     exactly two hard-coded names, while open_url / fetch_url /
        #     browser_explore were never filtered. The model therefore had the
        #     BROWSER tools and not the SEARCH tools, which is the opposite of
        #     what a "search the web" phrasing needs.
        #   - It removed capability rather than adding guidance, so it could
        #     only ever fail in the direction that broke the turn.
        #   - Any new phrasing, tool or vocabulary needed a code edit.
        #
        # The model is already good at not searching when it is not needed - it
        # answered from memory in this same session without reaching for a
        # search tool. The web toggle remains the user's control.
        return openai_tools

    # â”€â”€ ReAct agentic loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    # REQ-28: threshold above which the first-sentence rule below stops being
    # an acceptable spoken form. Same number prepare_spoken_text already uses
    # for its ">120 words" branch, named once so the two cannot drift.
    SPOKEN_BRIEF_WORD_THRESHOLD = 120




    # ------------------------------------------------------------------
    # Issue C.1 â€” structured speak/show response contract
    # ------------------------------------------------------------------












    # â”€â”€ W9 (O3): proactive structured-data capture from ANY tool result â”€â”€â”€â”€â”€â”€
    # Plan W9: extend capture beyond `show` payloads to any tool result
    # (web_search, crawler_query, read_file, ...) so everything the agent
    # touches becomes reformat-able via the same DocumentDataStore. Scoped by a
    # relevance/structure threshold so trivial results are not embedded.

    _MIN_CAPTURE_CHARS = 50       # below this, a result is "trivial"
    _RELEVANCE_THRESHOLD = 0.30   # results carrying a score below this are skipped





    # â”€â”€ W10 (O4): pheromone-reinforced reformat + cross-modal synergy â”€â”€â”€â”€â”€â”€â”€â”€
    # Plan W10: reinforce the reformat action's pheromone edge when used, so
    # frequently-reformatted doc types become "sticky" (the agent can proactively
    # offer a reformat), and expose cross-modal views (vocalize / diagram) that
    # reuse existing channels (SpeakTool, reformat_document's diagram format).






    def _sanitize_task(self, task: str) -> str:
        """
        Filter prompt-injection attempts before the task reaches the DER Director.
        Replaces coordinate-layer protocol markers with [filtered].
        Applied ONLY here â€” not in WebSocket validators.
        """
        import re as _re

        _PACMAN_PATTERNS = (
            r"system://",
            r"trusted://",
            r"tool://",
            r"reference://",
            r"MYCELIUM:",
            r"TOPOLOGY:",
            r"CONTRACT:",
            r"GRADIENT WARNING",
            r"AMBIENT:",
            r"CAUSAL:",
        )
        result = task
        for pattern in _PACMAN_PATTERNS:
            result = _re.sub(pattern, "[filtered]", result)
        return result



    def _build_planning_prompt(
        self,
        task: str,
        tier1_directives: str = "",
        behavior_preds: str = "",
        failure_warnings: str = "None",
        skills_context: str = "",
        permissions_list: str = "",
        strategy_hint: str = "",
        task_class: str = "full",
        context: Optional[List[Dict[str, Any]]] = None,
        episodic_context: Optional[str] = None,
    ) -> str:
        """
        Build the structured planning prompt for _plan_task().
        Returns sections joined with double newlines.
        FAILURE WARNINGS appears exactly once.
        """
        sections = []

        if tier1_directives:
            sections.append(f"DIRECTIVES:\n{tier1_directives}")

        if behavior_preds:
            sections.append(f"BEHAVIOR PREDICTIONS:\n{behavior_preds}")

        sections.append(f"FAILURE WARNINGS:\n{failure_warnings or 'None'}")

        sections.append(f"TASK CLASS: {task_class}")

        if strategy_hint:
            sections.append(f"STRATEGY HINT:\n{strategy_hint}")

        if skills_context:
            sections.append(f"AVAILABLE SKILLS:\n{skills_context}")

        if permissions_list:
            sections.append(f"PERMISSIONS:\n{permissions_list}")

        sections.append(f"TASK:\n{task}")
        _voice = _voice_turn_note(self)
        if _voice:
            sections.append(_voice)

        # â”€â”€ Phase 2.1: full conversation history (no index slicing) â”€â”€
        # The active thread is passed in its entirety so the planner can resolve
        # references like "do the websearch" / "the pricing of those" back to the
        # original query from earlier turns (fixes the toggle-restoration context
        # loss). This is the whole point of the universal DER loop.
        if context:
            history_lines = []
            for msg in context:  # Entire thread history is included
                role = (msg.get("role") or "user").upper()
                content = msg.get("content") or ""
                line = f"{role}: {content}"
                # Provenance (2026-10-08): the URLs this message's references
                # came from. This COMPLETES the existing line - it is not a new
                # section - so a reference is grounded as EXTERNAL instead of
                # read as a local path (`adalso/openai-math` looks like one).
                # Cost is the URL text itself; nothing is looked up or re-fetched.
                _srcs = msg.get("sources") or []
                if _srcs:
                    line += "\n  [sources: " + ", ".join(
                        str(u) for u in _srcs[:8]
                    ) + "]"
                history_lines.append(line)
            if history_lines:
                sections.append(
                    "CONVERSATION HISTORY (full thread):\n"
                    + "\n".join(history_lines)
                )

        # â”€â”€ Phase 2.1: PACMAN semantic recall from past sessions â”€â”€
        if episodic_context:
            sections.append(
                f"RECALLED EPISODIC CONTEXT (PACMAN):\n{episodic_context}"
            )

        # REQ-8 AC8.2: visited-ledger block (pointers only).
        # Degrades to no-block on any failure â€” never break planning
        # (design.md Error Handling: ledger render failure degrades).
        try:
            _visited = self._der_visited_block()
        except Exception:
            _visited = ""
        if _visited:
            sections.append(_visited)

        return "\n\n".join(sections)

    def _turn_sources(self, conversation_id: str = "") -> List[str]:
        """The URLs this conversation's fetches produced (provenance, 2026-10-08).

        Read from the kernel's per-conversation crawled-URL set - the same set
        ``_der_visited_block()`` renders, which (per the note at the DER dispatch
        site) SURVIVES ACROSS TURNS per conversation, so a follow-up turn sees
        the URLs the previous turn fetched. A reference whose URL is recorded
        here is grounded as EXTERNAL by the planner; without it the thread
        carries only a bare ``owner/name`` token, which reads as a local path
        (measured live: a GitHub repo was searched for in the project root).

        ``conversation_id`` lets a caller that resolved the turn's conversation
        ITSELF (the gateway, whose mapping can differ from the kernel's) read the
        right key instead of silently getting [] on a mismatch.

        Never raises: provenance must never break a turn.
        """
        try:
            return sorted(
                (getattr(self, "_der_crawled_urls", None) or {})
                .get(conversation_id or self.conversation_id or "", ()) or ()
            )
        except Exception:  # noqa: BLE001 â€” an observer never blocks a turn
            return []

    def _der_visited_block(self) -> str:
        """REQ-8 AC8.2: bounded VISITED ledger block for planning and
        continuation prompts. Pointers only â€” URLs with the step that
        fetched them (AC8.4 join keys); page bodies never enter prompts
        (AC8.3). Empty ledger renders as "" (callers omit the block).
        Most-recent-first with an explicit +N marker; refusal/exclusion
        logic always uses the FULL in-memory set, never this view."""
        try:
            from backend.agent.der_constants import LEDGER_PROMPT_MAX
            _cap = max(int(LEDGER_PROMPT_MAX), 1)
        except Exception:
            _cap = 20
        try:
            _conv = self.conversation_id or ""
            _crawled = set(
                getattr(self, "_der_crawled_urls", {}).get(_conv, set())
            )
            if not _crawled:
                return ""
            # Insertion-ordered step map (most-recent last) first, then
            # any ledger-only remainder sorted for determinism.
            _stepmap = dict(
                getattr(self, "_der_crawled_steps", {}).get(_conv, {})
            )
            _ordered = [_u for _u in _stepmap if _u in _crawled]
            _ordered += sorted(_crawled - set(_stepmap))
            _ordered = _ordered[::-1][: _cap]
            _lines = [
                "VISITED THIS TURN (do not re-fetch â€” known-only "
                "discovery = pivot: propose a different approach instead):"
            ]
            for _u in _ordered:
                _sid = _stepmap.get(_u, "")
                _lines.append(
                    f"  - {_u}" + (f" (step {_sid})" if _sid else "")
                )
            try:
                from backend.agent.write_counters import bump as _bump_ledger
                _bump_ledger("envelope.ledger_renders")
            except Exception:
                pass
            if len(_crawled) > len(_ordered):
                _lines.append(f"  (+{len(_crawled) - len(_ordered)} more)")
            return "\n".join(_lines)
        except Exception:
            return ""

    def _der_maybe_open_recovery(self, item, step_result, completed_items, queue):
        """Session-318 T16 (REQ-9 AC9.5): open a VLM in-site recovery step
        when a gather step's fetch died but unvisited same-site candidates
        exist. Returns a QueueItem or None. Rules: parent must carry an
        envelope with ZERO stamped sources (nothing usable came back);
        parent must not itself be a recovery (no chains); one recovery per
        dead host per turn; candidates = same-host outlinks + parent-dir of
        dead URLs, minus visited and minus dead, capped by
        RECOVERY_PAGE_BUDGET. Never raises."""
        try:
            from backend.agent.tool_envelope import tool_family
            from backend.agent.der_loop import QueueItem
            try:
                from backend.agent.der_constants import RECOVERY_PAGE_BUDGET
                _budget = max(int(RECOVERY_PAGE_BUDGET), 1)
            except Exception:
                _budget = 5
            if getattr(item, "recovery_of", ""):
                return None  # no chains
            if tool_family(getattr(item, "tool", None)) != "gather":
                return None
            _env = getattr(item, "envelope", None)
            if _env is None or list(getattr(_env, "sources", []) or []):
                return None  # something usable came back â€” no recovery
            _conv = self.conversation_id or ""
            _visited = set(
                getattr(self, "_der_crawled_urls", {}).get(_conv, set())
            )
            # Session-319: candidate extraction is now SHARED with the
            # router-driven producer (_recovery_candidates), so the two lanes
            # cannot drift apart while they converge into one.
            #
            # Do NOT claim the per-host budget here: the claim is made ATOMICALLY
            # below, after candidates are computed, so a concurrent step cannot
            # also pass this check. Claiming early and then returning None (no
            # candidates) would wrongly burn the host's one recovery for the turn.
            _dead, _hosts, _cands = _recovery_candidates(
                step_result, getattr(_env, "sources", []), _visited
            )
            if not _dead or not _hosts:
                return None
            _cands = _cands[:_budget]
            if not _cands:
                return None
            # Session-319: ATOMIC check-and-claim of the per-host-per-turn
            # budget. The old code read this ledger near the top of this method
            # and wrote it here, with no lock in between â€” so under concurrent
            # parallel_safe steps two of them could both see "not yet opened"
            # and each enqueue a recovery for the SAME host. Owner decision
            # (session-319): ONE CREW PER BUILDING. The claim happens only now,
            # when we know an item will be returned, so a no-candidate path
            # never burns the host's recovery for the turn.
            try:
                with _der_recovery_lock:
                    _ro = dict(getattr(self, "_der_recovery_opened", {}))
                    _opened = set(_ro.get(_conv, set()))
                    _claim = {h for h in _hosts if h not in _opened}
                    if not _claim:
                        # Another step claimed every host first â€” this step must
                        # not open a second crew for the same building.
                        return None
                    _ro[_conv] = _opened | _claim
                    self._der_recovery_opened = _ro
                    _hosts = _claim
            except Exception:
                pass
            _host0 = sorted(_hosts)[0]
            _rec = QueueItem(
                step_id=f"recovery_{getattr(item, 'step_id', 's')}",
                step_number=len(completed_items or []) + 1,
                description=(
                    f"Recover dead fetch from {_host0}: crawl "
                    f"{len(_cands)} unvisited in-site page(s) instead "
                    f"({', '.join(sorted(_hosts))})."
                ),
                tool=None,  # resolver keeps authority (F6); seeds enrich post-resolve
                params={},
                parallel_safe=False,
                objective_anchor=getattr(item, "objective_anchor", "") or "",
                expected_output=(
                    f"Usable content from {_host0} covering: "
                    f"{(getattr(item, 'expected_output', '') or '')[:120]}"
                ),
                declared_criticality=(
                    getattr(item, "declared_criticality", "supporting")
                    or "supporting"
                ),
                recovery_of=getattr(item, "step_id", ""),
                recovery_seeds=_cands,
            )
            logger.info(
                "[DER:recovery] trigger: parent=%s dead=%d host=%s seeds=%d",
                getattr(item, "step_id", "?"), len(_dead), _host0, len(_cands),
            )
            return _rec
        except Exception as _rec_exc:
            logger.debug("[DER] recovery trigger failed: %s", _rec_exc)
            return None

    @staticmethod
    def _der_step_error_is_retryable(err: str) -> bool:
        """Whether a failed step's error text is worth another attempt.

        Connection-level errors are. A STEP TIMEOUT is not (execution audit B6,
        2026-09-29): the step already spent its whole deadline, and the
        abandoned worker may still be running the command - a retry starts it
        a second and third time in parallel.
        """
        if not err or err.lstrip().startswith("[STEP TIMEOUT"):
            return False
        return any(
            _k in err
            for _k in ("ConnectionError", "TimeoutError", "timed out",
                       "Connection refused", "timeout")
        )

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
            if (tool or "").lower() == "run_command":
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

    def _der_report_run_grade(self, completed_items, _turn_id, _where):
        """Session-318 T19 (AC5.6 defect fix): done+GRADE reported once per
        turn at completion, on EVERY terminal path â€” not just the
        continuation-done branch (conv-102 proved queue-exhaustion ends
        never take it: zero grade lines). Deduplicated by turn_id so the
        finalize-complete site and the continuation site never double-log.
        Deterministic O(n) over envelopes; zero LLM. Never raises."""
        try:
            _last = getattr(self, "_der_last_run_grade", None) or {}
            if _last.get("turn_id") == (_turn_id or "") and _last.get("turn_id"):
                return _last.get("grade", "")
            from backend.agent.tool_envelope import evaluate_run_grade
            from backend.agent.der_constants import LOAD_BEARING_VETO
            _envs = [
                getattr(i, "envelope", None) for i in (completed_items or [])
            ]
            # Goal contract T10 (REQ-7/REQ-8): grade from coverage when a
            # contract exists â€” C=1.0 no-blocked is a pass; any open
            # unblocked fact caps below pass; all-blocked-and-named is a
            # partial (capped). Advisory: absent contract = legacy grade.
            _gc_state = getattr(self, "_goal_contract_state", None)
            _gc_c = None
            _gc_open: List[str] = []
            _gc_blocked: List[str] = []
            if _gc_state is not None:
                try:
                    _gc_c = float(_gc_state.get("C", 0.0))
                    _gc_open = self._goal_contract_open_facts()
                    _gc_blocked = self._goal_contract_blocked_texts()
                except Exception:
                    _gc_state = None
            _grade, _reasons = evaluate_run_grade(
                [e for e in _envs if e is not None],
                load_bearing_veto=LOAD_BEARING_VETO,
                coverage=_gc_c,
                open_unblocked=_gc_open,
                blocked=_gc_blocked,
            )
            self._der_last_run_grade = {
                "turn_id": _turn_id or "", "grade": _grade,
                "reasons": list(_reasons or []),
            }
            # Wave 5 (REQ-6 AC6.3 + REQ-14 AC14.4): the OUTCOME join. Sampled
            # consults are labelled by THIS turn's grade; any deferred closing
            # claim still pending at turn end sweeps to `abandoned` (counted,
            # never a fabricated negative). Runs once per turn (the grade
            # dedup above guarantees it).
            try:
                from backend.agent import decision_engine as _de_oc

                _de_oc.resolve_turn_pending(_turn_id or "", _grade == "pass")
                _de_oc.sweep_turn_pending(_turn_id or "")
                # tc-decide-v7 (2026-11-07): flush any DECIDED tool_choice row
                # whose step never settled (early turn end, exception). The row
                # is written WITHOUT an outside_label, so a flushed row is
                # counted and never scored - two label semantics never blend.
                try:
                    from backend.agent import tool_choice_outcome_label as _tcol

                    _tc_swept = _tcol.sweep()
                    if _tcol.enabled() and _tc_swept:
                        _tcol_st = _tcol.stats()
                        logger.info(
                            "[Oracle] tool_choice step-completion label: "
                            "swept_unsettled_now=%d flushed_unsettled_total=%d "
                            "dropped_overflow=%d",
                            _tc_swept,
                            _tcol_st.get("flushed_unsettled", 0),
                            _tcol_st.get("dropped_overflow", 0),
                        )
                except Exception:  # noqa: BLE001
                    pass
                # A row the native writer failed or dropped was invisible: app_write
                # returns once it is queued (2026-11-09 audit). One stats read per
                # turn; a WARNING only when the counts grew.
                try:
                    from backend.memory.db import report_native_write_losses

                    report_native_write_losses(getattr(self, "conversation_id", "") or "")
                except Exception:  # noqa: BLE001 - a diagnostic never fails a turn
                    logger.debug("[db] native write loss report skipped")
                # the held consult rows are stamped with what the turn NEEDED,
                # not the keyword list's parity. truth = "yes" when the request
                # named a URL (by rule), else "yes" when a web tool succeeded
                # and the turn passed, "no" when it passed without the web; a
                # failed turn leaves its rows on parity. try/except: a label
                # never blocks a turn.
                try:
                    from backend.agent import explorer as _exp_wi

                    _web_used = False
                    for _wi_it in (completed_items or []):
                        _wi_t = str(getattr(_wi_it, "tool", "") or "")
                        if (
                            _wi_t == "search"
                            or _wi_t == "crawler_query"
                            or _wi_t.startswith("browser")
                        ):
                            _wi_env = getattr(_wi_it, "envelope", None)
                            if _wi_env is not None and str(
                                getattr(_wi_env, "status", "")
                            ) == "success":
                                _web_used = True
                                break
                    # v3 (2026-10-18): the DER items miss the quick-tier /
                    # crawler searches (they run OUTSIDE the DER), so research
                    # turns that used the web were labelled "no web needed"
                    # and d1's correct "yes" answers scored wrong (measured:
                    # r01-r04 passed WITH search, every row outside=no). The
                    # bridge's chokepoint flag covers every dispatch.
                    if not _web_used:
                        try:
                            from backend.agent.tool_bridge import turn_used_web

                            _web_used = turn_used_web(_turn_id or "")
                        except Exception:  # noqa: BLE001
                            pass
                    _wi_n = _exp_wi.resolve_web_intent_turn(
                        _turn_id or "", _grade == "pass", _web_used
                    )
                    if _wi_n:
                        logger.info(
                            "[Oracle] web intent label: turn=%s labelled=%d "
                            "web_used=%s grade=%s",
                            _turn_id or "?", _wi_n, _web_used, _grade,
                        )
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001 - a label never blocks the turn
                pass
            # REQ-7 AC7.2: log the counters the contract introduced, naming
            # the reader for each (AC7.4): seeded/mapped/re-added feed T4;
            # covered/blocked feed T5/T9 + grade; amendments feed T7/T8;
            # stalls/bonus feed T6/T3.
            try:
                if _gc_state is not None:
                    _gc_counters = _gc_state.get("counters") or {}
                    logger.info(
                        "[goal-contract] counters (readers T4/T5/T6/T9/grade): "
                        "seeded=%s mapped=%s readded=%s covered=%s blocked=%s "
                        "amend_user=%s amend_agent=%s stalls=%s bonus=%s "
                        "C=%.3f g=%.3f",
                        _gc_counters.get("facts_seeded", 0),
                        _gc_counters.get("facts_mapped", 0),
                        _gc_counters.get("facts_readded", 0),
                        _gc_counters.get("facts_covered", 0),
                        _gc_counters.get("facts_blocked", 0),
                        _gc_counters.get("amendments_user", 0),
                        _gc_counters.get("amendments_agent", 0),
                        _gc_counters.get("stalls", 0),
                        _gc_counters.get("bonus_passes", 0),
                        float(_gc_state.get("C", 0.0)),
                        float(_gc_state.get("g", 1.0)),
                    )
            except Exception:
                pass
            logger.info(
                "[DER] run grade: %s%s (%s)",
                _grade,
                ("; reasons: " + "; ".join(_reasons)) if _reasons else "",
                _where,
            )
            # Session-326 (goal-contract terminal-signal diag): at every grade
            # chokepoint, settle the card. The grade helper was reachable from
            # three call sites â€” _execute_plan_der (failure-settled),
            # _der_finalize_step (finalize-complete), and _der_plan_next_step
            # (continuation-done) â€” but only _execute_plan_der's
            # _emit_terminal_event emitted a card frame. Without this emit,
            # regressions where the possess motion ran without writing a
            # task:done event left the card in Active Execution forever while
            # the turn had finished; follow-ups were then routed as steering
            # (anyCardWorking=True) into a closed turn.
            self._der_emit_card_settle(_turn_id, completed_items, _grade, _where)
            return _grade
        except Exception as _grade_exc:
            logger.debug("[DER] run grade computation failed: %s", _grade_exc)
            return ""


    def _der_recall_neighborhood(self, item, session_id: str = "") -> list:
        """REQ-20 AC3 (T21): filtered ontology-neighborhood chain recall.

        Builds RecallFilters from THIS node's record (node_type + both
        domain axes) and queries the shared chain with the widen-order
        (relationship -> type -> domain, winning scope logged). Returns
        chain-row dicts, or [] on any failure â€” the step proceeds on live
        state, never an error. Cross-conversation by default (AC1b):
        thread_id ranks, never filters.

        REQ-6 AC3 (semantic gate): the recall execution is the SHARED helper
        ``run_filtered_recall`` (ontology_recall.py) â€” the gate's Tier 2 calls
        the same code path, so the widen-order and telemetry cannot drift.

        REQ-4 AC4.2 (K2): the recalled rows then pass a RELEVANCE GATE - same
        topic AND token overlap with this step's goal (no embedding on the step
        path); survivors rank by state proximity then recency; none passing ->
        [] and the step carries no neighbors block at all (owner rule
        2026-09-30: chain data enters the context only when relevant).
        """
        try:
            from backend.agent.caducean_trajectory import latest_coords_str
            from backend.agent.ontology_recall import (
                CANDIDATE_POOL,
                RecallFilters,
                gated_neighborhood,
                resolve_mycelium_conn,
            )

            _rec = getattr(item, "node_record", None) or getattr(
                item, "footprint", None
            )
            _filters = RecallFilters(
                node_type=getattr(_rec, "node_type", None)
                or getattr(item, "node_type", None),
                topic_domain=getattr(_rec, "topic_domain", None)
                or getattr(item, "topic_domain", None),
                execution_domain=getattr(_rec, "execution_domain", None)
                or getattr(item, "execution_domain", None),
                thread_id=session_id or getattr(item, "session_id", None) or None,
                limit=CANDIDATE_POOL,  # the gate keeps at most 3 of these
            )
            if not _filters.has_any:
                return []  # no ontology axes on this node â€” nothing to filter

            _conn = resolve_mycelium_conn(self._memory_interface)
            if _conn is None:
                return []

            return gated_neighborhood(
                _conn,
                _filters,
                getattr(item, "description", "") or "",
                # Called only when more than one row passed the gate.
                state_fn=lambda: latest_coords_str(
                    self._memory_interface, session_id
                ),
                keep=3,
            )
        except Exception as exc:
            logger.debug("[DER] ontology neighborhood recall failed: %s", exc)
            return []

    @staticmethod
    def _iter_json_objects(raw: str):
        r"""Yield each BALANCED top-level {...} span in `raw`, in order.

        The planner used to extract its JSON with a single greedy
        ``re.search(r"\{[\s\S]+\}")``, which spans from the FIRST brace to the
        LAST one in the whole reply. That is correct only when the model emits
        exactly one object and nothing else. When it emits a preamble, a fenced
        block plus an example, or any prose containing a brace, the captured
        span is not valid JSON and the whole turn dies with "The planner
        returned no valid plan" -- measured live on 2026-08-26 as roughly half
        of all turns.

        This walks the string instead, tracking string literals and escapes so
        a brace inside a quoted value cannot close an object early.
        """
        depth = 0
        start = -1
        in_str = False
        esc = False
        for i, ch in enumerate(raw or ""):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
                continue
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}" and depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    yield raw[start : i + 1]
                    start = -1

    @staticmethod
    def _parse_planner_json(raw: str):
        """Best parseable planner object in `raw`, or None.

        Prefers a candidate that actually looks like a PLAN (carries `steps` or
        `plan_title`) over the first one that merely parses -- a model that
        prefixes its plan with a small example object would otherwise hand back
        the example.
        """
        import json as _json

        _best = None
        for _cand in AgentKernel._iter_json_objects(raw or ""):
            try:
                _obj = _json.loads(_cand)
            except Exception:
                continue
            if not isinstance(_obj, dict):
                continue
            if "steps" in _obj or "plan_title" in _obj:
                return _obj
            if _best is None:
                _best = _obj
        return _best

    @staticmethod
    def _planned_beats(data: dict, n_steps: int) -> list:
        """Clean the planner's `beats` + apply the duration gate (T12).

        Strips blanks; then the duration gate (REQ-10 AC10.10): narration
        earns airtime only when the task outlives the reply, so plans with
        fewer than 2 segments keep no beats (their reply voices everything).
        The 2-segment threshold is tunable via REQ-9 counters, not the model.
        """
        beats = [
            str(b).strip() for b in (data.get("beats", None) or [])
            if str(b or "").strip()
        ]
        if beats and n_steps < 2:
            logger.info(
                "[AgentKernel._plan_task] dropping %d beats "
                "(single-segment plan, duration gate)", len(beats)
            )
            return []
        return beats

    @staticmethod
    def _classify_provider_error(err_text: str) -> Optional[Tuple[object, str]]:
        """Map a fatal provider failure to (ErrorCode, user message).

        Billing (402) and auth (401) failures cannot heal inside the retry
        loop â€” returning them immediately saves ~10 s of doomed retries and,
        more importantly, tells the user the TRUE cause instead of the
        generic "planner returned no valid plan" (observed live 2026-09-05:
        Cerebras 402 surfaced as a planner failure on every prompt). Quota
        errors (429) are NOT fatal â€” windows roll, retries stay. Returns None
        when the error is not a recognized fatal provider failure. Codes come
        from exceptions.ErrorCode (6000-range); the code name rides in the
        user string so every failure is greppable end to end.
        """
        from backend.agent.exceptions import ErrorCode

        t = (err_text or "").lower()
        if ("402" in t and ("pay" in t or "bill" in t)) or "payment required" in t:
            return (
                ErrorCode.PROVIDER_BILLING,
                "[IRIS error] The AI provider refused the request "
                "(402 Payment Required) â€” the planner never ran, so no "
                "prompt reached a model. Switch provider in Models "
                "(local / ClinePass) or check billing, then retry. "
                "(code E_PROVIDER_BILLING)",
            )
        if (
            ("401" in t and ("unauth" in t or "invalid" in t or "key" in t or "auth" in t))
            or "unauthorized" in t
            or "invalid_api_key" in t
            or "invalid api key" in t
        ):
            return (
                ErrorCode.PROVIDER_AUTH,
                "[IRIS error] The AI provider rejected the API key (401). "
                "Check the key in settings (OS keyring), then retry. "
                "(code E_PROVIDER_AUTH)",
            )
        return None

    def _classify_plan_failure(self) -> Tuple[object, str, bool]:
        """Map the recorded plan failure to (ErrorCode, user message, fatal).

        Reads self._last_plan_failure as written by _plan_task. Fatal kinds
        (billing/auth) must fail fast â€” retries cannot heal them. Everything
        else retries and reports specifically at exhaustion, so logs and UI
        always name the true cause instead of a vague planner error.
        """
        from backend.agent.exceptions import ErrorCode

        failure = getattr(self, "_last_plan_failure", None) or {}
        kind = failure.get("kind")
        detail = (failure.get("detail") or "")
        if kind == "router":
            fatal = self._classify_provider_error(detail)
            if fatal is not None:
                return (fatal[0], fatal[1], True)
            low = detail.lower()
            if (
                "429" in low
                or "rate limit" in low
                or "rate_limit" in low
                or "quota" in low
                or "too many requests" in low
                or "overloaded" in low
            ):
                return (
                    ErrorCode.PROVIDER_QUOTA,
                    "[IRIS error] The AI provider is rate-limiting us (429) "
                    "after 3 tries â€” wait a minute for the quota window, or "
                    "switch provider. (code E_PROVIDER_QUOTA)",
                    False,
                )
            if (
                "timeout" in low
                or "timed out" in low
                or "connecterror" in low
                or "connection refused" in low
                or "connection reset" in low
                or "unreachable" in low
                or "dns" in low
            ):
                return (
                    ErrorCode.PROVIDER_TIMEOUT,
                    "[IRIS error] The AI provider request timed out or never "
                    "connected after 3 tries â€” check network/VPN/firewall, or "
                    "switch provider. (code E_PROVIDER_TIMEOUT)",
                    False,
                )
            return (
                ErrorCode.PROVIDER_ERROR,
                "[IRIS error] The provider request failed 3 times (see "
                "backend log for the status). Retry, or switch provider if "
                "it persists. (code E_PROVIDER_ERROR)",
                False,
            )
        if kind == "parse":
            return (
                ErrorCode.PLANNER_PARSE,
                "[IRIS error] The model answered 3 times but never in usable "
                "plan form. Switching models usually fixes this. "
                "(code E_PLANNER_PARSE)",
                False,
            )
        return (
            ErrorCode.PLANNER_EMPTY,
            "[IRIS error] The model returned no plan text 3 times. Retry, "
            "or switch models if it persists. (code E_PLANNER_EMPTY)",
            False,
        )

    def _plan_task(
        self,
        text: str,
        context: Optional[List[Dict[str, Any]]] = None,
        is_mature: bool = False,
        task_class: str = "full",
        context_package=None,
        mode: str = "full",
        session_id: str = "unknown",
        recall_query: Optional[str] = None,
    ) -> Optional[ExecutionPlan]:
        """
        DER-aware planning wrapper. Returns ExecutionPlan (or None on failure).
        ``recall_query``: what episodic recall searches with, when ``text`` is
        not the user's request (a re-plan directive) - default ``text``.
        Mode + maturity-aware temperature:
          debug/review  â†’ 0.0  (deterministic â€” finding bugs, not exploring)
          implement      â†’ 0.1  (low â€” structured code generation)
          research       â†’ 0.3  (higher â€” exploratory synthesis)
          default        â†’ 0.1 if mature else 0.25
        Falls back to a single-step plan on any model or parse failure.
        """
        from backend.core_models import ExecutionPlan, PlanStep
        import uuid as _uuid
        import re as _re

        _MODE_TEMPERATURES = {
            "debug": 0.0,
            "review": 0.0,
            "test": 0.0,
            "implement": 0.1,
            "quick_edit": 0.1,
            "research": 0.3,
            "spec": 0.2,
        }
        temperature = _MODE_TEMPERATURES.get(mode, 0.1 if is_mature else 0.25)

        # â”€â”€ Phase 5: Caducean-governed planning temperature â”€â”€
        # Modulate the base (mode-derived) temperature by the live Caducean
        # recommendation: COMPRESS (rec==1) -> more deterministic (lower temp);
        # EXPAND (rec==0) -> more exploratory (higher temp, capped); MAINTAIN
        # (rec==2) / unknown / TOPO_VIOLATION -> base.  Never raises.
        temperature = self._caducean_modulate_temperature(temperature, session_id)

        # Extract context package fields for the planning prompt
        tier1 = ""
        preds = ""
        strategy_hint = ""
        failure_warnings = "None"
        if context_package is not None:
            _pkg_fields = self._context_package_fields(context_package)
            tier1 = _pkg_fields["tier1"]
            preds = _pkg_fields["preds"]
            strategy_hint = _pkg_fields["strategy_hint"]
            failure_warnings = _pkg_fields["failure_warnings"]

        # Build the CAPABILITIES block.
        #
        # SIZED DOWN 2026-08-26 (session 260), measured: the previous block
        # listed every tool with its full description -- ~1,131 tokens on EVERY
        # planner call -- and instructed the planner to "set its `tool` to the
        # EXACT name below". The parser has not honoured that instruction since
        # Phase 1 (D1.3): it sets `tool=None` unconditionally, because tool
        # selection is a runtime, memory-conditioned policy owned by
        # explorer.propose. So the catalogue bought a field that was thrown
        # away, and the tool was then re-decided per step at ~4.6k tokens.
        #
        # WHAT THE BLOCK IS STILL FOR, and why it is not simply deleted: the
        # planner has to know the agent CAN do these things, or it plans
        # capable requests as trivial speak-only steps (2026-08-12: explicit
        # "use screenshot_page" requests planned as trivial). Names alone carry
        # that; the descriptions never did any work here. ~187 tokens.
        _tools_block = ""
        try:
            # Ensure the tool bridge exists BEFORE reading the tool list â€” a
            # fresh kernel has a None bridge (lazy-init only ran on the OpenAI
            # tools path), which silently yields an empty AVAILABLE TOOLS block
            # and the planner then emits tool-less speak steps (2026-08-12:
            # explicit "use screenshot_page" requests planned as trivial).
            self._ensure_tool_bridge()
            if self._tool_bridge is not None:
                _avail = self._tool_bridge.get_available_tools()
                if _avail:
                    _names = [
                        str(_t.get("name", "")) for _t in _avail
                        if _t.get("name")
                    ]
                    _tools_block = (
                        "CAPABILITIES the agent can call at execution time. "
                        "Do NOT name a tool in a step -- the runtime resolver "
                        "picks it. This list tells you what is POSSIBLE, so "
                        "plan real steps for it instead of answering directly:"
                        + chr(10) + "  " + ", ".join(_names)
                    )
        except Exception as _tb_exc:
            logger.debug("[AgentKernel._plan_task] tools block build failed: %s", _tb_exc)

        # â”€â”€ Phase 2.1: PACMAN semantic recall (best-effort, never blocks) â”€â”€
        episodic_context = ""
        try:
            if self._memory_interface is not None and hasattr(
                self._memory_interface, "episodic"
            ):
                episodic_context = (
                    self._memory_interface.episodic.assemble_episodic_context(
                        recall_query or text
                    )
                    or ""
                )
        except Exception as _ep_exc:
            logger.debug("[AgentKernel._plan_task] episodic recall failed: %s", _ep_exc)

        # Turn-start prior memory (IRIS_TURN_START_RECALL, OFF by default; A/B
        # measured 2026-10-28). Chain rows relevant to the USER'S OWN WORDS, so
        # a fact taught in an earlier thread is in the PLANNER's context
        # before any step exists. The per-step gate compares the STEP the
        # planner invents; a question that "looks like" a tool task never
        # pulls its taught fact in that way (eval m01: the question became
        # file-search steps and the fact never entered the context). FIRST
        # plan only - a re-plan's recall_query is a directive, not the
        # user's question. Same pool, same relevance gate, bounded.
        if recall_query is None:
            try:
                from backend.agent.ontology_recall import (  # noqa: PLC0415
                    TURN_START_MAX_CHARS,
                    resolve_mycelium_conn as _pm_resolve_conn,
                    turn_start_prior_memory,
                )

                _pm_conn = _pm_resolve_conn(self._memory_interface)
                _pm_rows = turn_start_prior_memory(_pm_conn, text, session_id)
                _pm_lines: List[str] = []
                _pm_used = 0
                for _pm_r in _pm_rows:
                    _pm_line = (
                        _pm_r.get("insight")
                        or str(_pm_r.get("result") or "")[:240]
                        or str(_pm_r.get("content") or "")[:240]
                    ).strip()
                    if not _pm_line:
                        continue
                    if _pm_used + len(_pm_line) > TURN_START_MAX_CHARS:
                        break
                    _pm_lines.append(_pm_line)
                    _pm_used += len(_pm_line)
                if _pm_lines:
                    _pm_block = (
                        "PRIOR MEMORY (facts IRIS recalls from earlier threads, "
                        "relevant to this request):\n- " + "\n- ".join(_pm_lines)
                    )
                    episodic_context = (
                        f"{episodic_context}\n\n{_pm_block}"
                        if episodic_context
                        else _pm_block
                    )
            except Exception as _pm_exc:  # noqa: BLE001 - never blocks planning
                logger.debug(
                    "[AgentKernel._plan_task] turn-start prior memory skipped: %s", _pm_exc
                )

            # REQ-12 AC5 (T43): the chain leg only sees chain rows. A fact stored
            # as a trusted user chunk in ANOTHER conversation is reached here,
            # bounded to 3 chunks in the trusted zone.
            try:
                _xs_chunks = (
                    self._memory_interface.episodic.retrieve_context_chunks(
                        query=text, session_id=None, limit=3,
                        min_similarity=0.45,
                        chunk_types=["context_fragment"], zones=["trusted"],
                    ) or []
                )
            except Exception as _xs_exc:  # noqa: BLE001 - never blocks planning
                logger.debug(
                    "[AgentKernel._plan_task] cross-session chunk recall skipped: %s",
                    _xs_exc,
                )
                _xs_chunks = []
            if _xs_chunks:
                _xs_block = (
                    "PRIOR USER FACTS (from other conversations):\n- "
                    + "\n- ".join(_xs_chunks)
                )
                episodic_context = (
                    f"{episodic_context}\n\n{_xs_block}"
                    if episodic_context else _xs_block
                )

        planning_prompt = self._build_planning_prompt(
            task=text,
            tier1_directives=tier1,
            behavior_preds=preds,
            failure_warnings=failure_warnings,
            task_class=task_class,
            strategy_hint=strategy_hint,
            context=context,
            episodic_context=episodic_context,
        )

        system_prompt = ""
        if self._personality:
            try:
                system_prompt = self._personality.get_system_prompt()
            except Exception:
                pass

        full_prompt = (
            f"{system_prompt}\n\n{planning_prompt}\n\n"
            + (f"{_tools_block}\n\n" if _tools_block else "")
            + "Respond with JSON only â€” no prose, no markdown fences:\n"
            '{"strategy":"do_it_myself|spawn_children|delegate_external",'
            '"plan_title":"short 2-3 word summary of what the plan does (e.g. \\"Search web for AI news\\")",'
            '"reasoning":"one sentence explaining the approach",'
            '"beats":["one-line direction statement","one-line time expectation"],'
            '"steps":[{"step_id":"s1","step_number":1,"description":"Search the web for the user request","expected_output":"the concrete result this step must produce","depends_on":["start"],"critical":true,"criticality":"load-bearing|supporting|cosmetic"}]}'
            "\n\n"
        "RULES:\n"
        # T12 (REQ-10 AC10.1/AC10.2/AC10.10/AC10.12): planned-beat authoring.
        # Beats are short spoken lines (direction + time/scale expectations)
        # for MULTI-SEGMENT tasks only â€” emit [] for single-step/trivial work.
        # Kept to six lines by the session-260 sizing discipline: the parser
        # reads exactly these keys, nothing decorative.
        '- "beats": 1-3 one-line narration lines (why this direction, how long '
        'it takes). NEVER narrate mechanics (subtask splitting, tool names, '
        'file-by-file). Omit entirely ([]) for single-step tasks.\n'
        "- Vary phrasing, never the same opening twice. Good: "
        '"Checking current sources â€” usually about half a minute." / '
        '"Comparing the two options, then reporting back." Bad: '
        '"I will now split this into subtasks."\n'
        "- Findings near completion belong in the reply, not beats. Name "
        "artifacts naturally (never identifiers/paths). Failure lines state "
        "the cause at direction level plus the next step.\n"
        # SIZED DOWN 2026-08-26 (session 260): the schema used to demand
        # "tool" and "params" on every step, with three RULES lines telling
        # the model how to fill them. The parser has discarded BOTH since
        # Phase 1 (D1.3) -- it hard-sets tool=None, params={} -- because
        # explorer.propose owns tool selection at execution time. So the
        # model spent OUTPUT tokens on fields that were thrown away, and
        # every extra required field was another chance to emit malformed
        # JSON. A step is a GOAL; the fields kept are the ones the parser
        # actually reads: step_id, step_number, description, expected_output,
        # depends_on, critical.
        '- Describe each step as a GOAL in "description". Do NOT name a tool; '
        'the runtime resolver picks it when the step executes.' + chr(10) +
        # expected_output (2026-10-19): every step's product was empty, so the
        # verifier had nothing to check a node step against (a node step was
        # VERIFIED whenever its calls ran, even when its own tests failed) and
        # the needs_action Oracle saw a goal with no artifact. One short clause
        # per step; the parser caps it at 200 chars.
        "- In 'expected_output', state the concrete product of the step: the "
        "exact answer, file change or number it must produce. One clause, not "
        "a restatement of the goal.\n" +
        # Parallel nodes (owner 2026-10-04): independent steps run side by
        # side, so the planner names the RESULTS a step needs. Empty = the
        # step before (the safe default); ["start"] = needs no earlier result.
        "- In 'depends_on', list the step_ids whose RESULT this step needs. A step "
        "will not start until those steps have completed. Steps that do not need "
        "each other's results run at the same time, so do not chain them. Write "
        "[\"start\"] for a step that needs no earlier result. An empty list means "
        "\"the step before\". Example - compare A and B: s1 read A [\"start\"], "
        "s2 read B [\"start\"], s3 compare them [\"s1\",\"s2\"].\n"
        # T5 (specs/tool-result-envelope, KD-9): planner declares per-step
        # criticality. One word per step â€” intent only, consumption confirms
        # it at finalize (option C). Defaults to "supporting" when omitted.
        "- In 'criticality', state how load-bearing the step is: "
        '"load-bearing" (the task fails without it), "supporting" (helps but '
        'alternatives exist), or "cosmetic" (nice to have). Omit for '
        '"supporting".\n'
        # PLAN SHAPE (2026-11-06): measured on c02_add_slugify, s1 was an
        # "inspect the existing module and project structure" step that ran
        # broad `find`/`ls -R` sweeps and the FULL test suite (17.9 s), then
        # s3 verified anyway - 56-71 s of duplicate work on a one-function
        # task. A step is a GOAL; the runtime resolves one tool for it, so
        # name the artifact, never a survey.
        "- Keep each step MINIMAL. A first step that reads ONE named file is "
        "enough. Do NOT plan a step that inspects the project structure, "
        "sweeps directories, checks git, or runs the test suite to 'see what "
        "exists'.\n"
        # PLAN SHAPE (2026-11-09): measured on c14_run_and_report ("run the
        # tests, tell me how many fail"), every plan added 1-2 steps after the
        # run that only tallied, verified or reported it ("Determine the exact
        # number of failing tests from the completed run", "Report the
        # verified failure count") - each a full tool loop that ran pytest
        # again. Over the logs: 72 'verify' and 29 'report' later steps. The
        # final reply already reports from the earlier step's result. A check
        # still follows a CHANGE (the goal contract needs that run).
        "- Do NOT plan a step that only tallies, restates or reports what an "
        "earlier step already produced; the final reply does that from the "
        "earlier result. Plan a separate check step only after a step that "
        "CHANGES a file. When the answer is the exact output of code (what a "
        "function returns, what a script prints), plan a step that RUNS it "
        "and reads the output; do not work the value out by reading.\n"
    )

        plan_raw: Optional[str] = None
        try:
            # Primary path: route planning through the unified InferenceRouter so
            # API providers (Cerebras, OpenAI, â€¦) are used â€” not just local/Ollama
            # models. Legacy LM Studio / Ollama branches below remain as fallbacks
            # for local-model configurations.
            try:
                _rt_text, _rt_think, _rt_tools = self._router.generate(
                    "reasoning",
                    [{"role": "user", "content": full_prompt}],
                    max_tokens=4096,
                    temperature=temperature,
                    # A plan is 1-3 goal steps: the default hidden reasoning
                    # (~1,300-1,650 tokens on mercury-2.5, ~4 s) bought nothing
                    # a "low" budget (~250 tokens, 2.5-3.2 s) did not; measured
                    # 2026-10-05, 6/6 valid plans. Providers without the
                    # parameter are sent the call unchanged.
                    reasoning_effort="low",
                )
                self._accrue_tokens(
                    _rt_text, getattr(self._router, "last_usage", None),
                    source="_plan_task",
                )
                if _rt_text:
                    plan_raw = _rt_text
                    logger.info(
                        "[AgentKernel._plan_task] planned via InferenceRouter"
                    )
            except Exception as _rt_err:
                logger.warning(
                    f"[AgentKernel._plan_task] router planning failed: {_rt_err}"
                )
                try:
                    self._last_plan_failure = {
                        "kind": "router",
                        "detail": str(_rt_err),
                    }
                except Exception:
                    pass
            if not plan_raw:
                if self._is_openai_compat():
                    _lms = self._get_lmstudio_client()
                    _r = _lms.chat.completions.create(
                        model=self._selected_reasoning_model or "local-model",
                        messages=[{"role": "user", "content": full_prompt}],
                        max_tokens=-1,
                        temperature=temperature,
                        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                    )
                    plan_raw = _r.choices[0].message.content
                    logger.info(
                        "[AgentKernel._plan_task] planner raw response: %s",
                        (plan_raw or "")[:600],
                    )
                elif (
                    self._selected_reasoning_model and ":" in self._selected_reasoning_model
                ):
                    import requests as _req

                    _r2 = _req.post(
                        "http://localhost:11434/api/chat",
                        json={
                            "model": self._selected_reasoning_model,
                            "messages": [{"role": "user", "content": full_prompt}],
                            "stream": False,
                        },
                        timeout=60,
                    )
                    if _r2.status_code == 200:
                        plan_raw = _r2.json().get("message", {}).get("content", "")
        except Exception as _pe:
            logger.warning(f"[AgentKernel._plan_task] inference failed: {_pe}")

        # Parse JSON â†’ ExecutionPlan
        try:
            if plan_raw:
                data = self._parse_planner_json(plan_raw)
                if data is not None:
                    logger.info(
                        "[AgentKernel._plan_task] parsed plan keys=%s "
                        "raw_steps=%s",
                        list(data.keys()),
                        len(data.get("steps", [])),
                    )
                    steps: List[Any] = []
                    for raw_step in data.get("steps", []):
                        steps.append(
                            PlanStep(
                                step_id=str(
                                    raw_step.get("step_id", str(_uuid.uuid4()))
                                ),
                                step_number=int(
                                    raw_step.get("step_number", len(steps) + 1)
                                ),
                                description=str(raw_step.get("description", "")),
                                # Phase 1 (D1.3): planner emits GOALS only. Tool
                                # selection is a runtime, memory-conditioned policy
                                # via explorer.propose â€” never pre-assigned here.
                                tool=None,
                                params={},
                                # 2026-10-19: the planner now declares the step's
                                # product. It was always empty, so verification had
                                # nothing to check and the needs_action Oracle saw
                                # a goal with no artifact. Optional: an older or
                                # non-compliant plan still parses.
                                expected_output=(
                                    str(raw_step.get("expected_output") or "").strip()[:200]
                                    or None
                                ),
                                critical=bool(raw_step.get("critical", True)),
                                depends_on=_plan_step_deps(raw_step, steps),
                                # T5 (KD-9): planner-declared criticality,
                                # validated to the locked vocabulary.
                                criticality=(
                                    str(raw_step.get("criticality", "supporting")).lower()
                                    if str(raw_step.get("criticality", "supporting")).lower()
                                    in ("load-bearing", "supporting", "cosmetic")
                                    else "supporting"
                                ),
                            )
                        )
                    # Parallel nodes (HANDOFF 11 C): the edges the planner
                    # DECLARED. Only the step count was logged, so whether plans
                    # carry real dependencies was unmeasurable.
                    logger.info(
                        "[AgentKernel._plan_task] plan edges steps=%d declared=%s",
                        len(steps), [(s.step_id, s.depends_on) for s in steps],
                    )
                    _beats = self._planned_beats(data, len(steps))
                    return ExecutionPlan(
                        plan_id=str(_uuid.uuid4()),
                        original_task=text,
                        strategy=data.get("strategy", "do_it_myself"),
                        reasoning=data.get("reasoning", ""),
                        plan_title=data.get("plan_title", ""),
                        steps=steps,
                        beats=_beats,
                    )
        except Exception as _parse_err:
            logger.warning(f"[AgentKernel._plan_task] parse failed: {_parse_err}")
            try:
                _raw_text = (plan_raw or "")
                self._last_plan_failure = {
                    "kind": "empty" if not _raw_text.strip() else "parse",
                    "detail": _raw_text[:200],
                }
            except Exception:
                pass
            # Only the LM Studio branch logged `plan_raw`, so on every other
            # provider a parse failure was unobservable -- the reason this bug
            # survived. Log what the model actually said, bounded.
            logger.warning(
                "[AgentKernel._plan_task] planner raw (first 600): %s",
                (plan_raw or "")[:600],
            )

        # Fallback: return None to signal plan error (REQ-2 â€” no silent self-do)
        try:
            if getattr(self, "_last_plan_failure", None) is None:
                # No router error and no parse attempt recorded (e.g. no
                # fallback configured and the router returned empty text):
                # the model simply produced nothing.
                self._last_plan_failure = {"kind": "empty", "detail": ""}
        except Exception:
            pass
        logger.warning(
            "[_plan_task] planner returned no valid plan for: %.150s",
            text,
        )
        return None

    def _note_tool_wait(
        self, *, tool_name: str, wait_id: str, turn_id=None, session_id=None
    ) -> None:
        """Open a narratable tool wait (REQ-10 AC10.11, T13). Never raises.

        Entry lines speak only for known-long waits; every wait carries its
        stated budget so an expectation-miss line fires if crossed with no
        result. Exit (TOOL_RESULT/ERROR site) stays silent â€” results voice
        via the reply path.
        """
        try:
            from backend.agent.conversation_kernel import get_conversation_kernel

            kernel = get_conversation_kernel()
            scheduler = getattr(kernel, "scheduler", None) if kernel else None
            if scheduler is None:
                return
            name = (tool_name or "").lower()
            # Budgets mirror tool_bridge.py:933 (60s vision/gui_automation,
            # else 30s). Entry lines are for known-long waits: the 60s class
            # plus crawl (multi-fetch runs long in practice).
            long_wait = ("vision" in name) or ("gui" in name) or ("crawl" in name)
            budget = 60.0 if (("vision" in name) or ("gui" in name)) else 30.0
            scheduler.note_wait(
                wait_id,
                turn_id=turn_id or "unknown",
                session_id=session_id or "unknown",
                budget_s=budget,
                long_wait=long_wait,
            )
        except Exception:  # noqa: BLE001 â€” narration never blocks tool runs
            pass

    def _end_tool_wait(self, wait_id: str) -> None:
        """Close a narratable tool wait (REQ-10 AC10.11, T13). Never raises."""
        try:
            from backend.agent.conversation_kernel import get_conversation_kernel

            kernel = get_conversation_kernel()
            scheduler = getattr(kernel, "scheduler", None) if kernel else None
            if scheduler is not None and wait_id:
                scheduler.end_wait(wait_id)
        except Exception:  # noqa: BLE001
            pass

    def _admit_planned_beats(self, plan, *, turn_id=None, session_id=None) -> None:
        """Admit beats 2..N as pending narration + pre-synthesize them (T14).

        Hybrid pre-synthesis (REQ-10 AC10.6/AC10.7): each beat is admitted to
        the lane scheduler (pending, subsumable) and, while the lane is idle,
        synthesized immediately with the buffer held by the TTS manager.
        Playback consumes via take_held(); every other exit frees. Any skip
        or failure degrades to on-admission synthesis â€” a beat never dies
        for pre-synthesis. Never raises.
        """
        try:
            beats = list(getattr(plan, "beats", None) or [])[1:]
            if not beats:
                return
            from backend.agent.conversation_kernel import get_conversation_kernel
            from backend.agent.tts import get_tts_manager

            kernel = get_conversation_kernel()
            scheduler = getattr(kernel, "scheduler", None) if kernel else None
            if scheduler is None:
                return
            try:
                tts = get_tts_manager()
            except Exception:
                tts = None
            tid = turn_id or "unknown"
            sid = session_id or "unknown"
            lane_busy = False
            try:
                lane_busy = bool(scheduler.is_playing())
            except Exception:
                lane_busy = False
            for text in beats:
                text = (text or "").strip()
                if not text:
                    continue
                ref = None
                # Lowest-priority invariant: pre-synthesize only while the
                # lane is idle; the manager additionally try-locks, so lane
                # synthesis can never queue behind a hold job.
                if not lane_busy and tts is not None and hasattr(tts, "presynthesize_hold"):
                    try:
                        ref = tts.presynthesize_hold(tid, text)
                    except Exception:
                        ref = None
                try:
                    scheduler.add_beat(
                        text, turn_id=tid, session_id=sid,
                        kind="planned", audio_ref=ref,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[AgentKernel] planned beat admit skipped: %s", exc)
                    if ref is not None and hasattr(tts, "free_held"):
                        try:
                            tts.free_held(ref)
                        except Exception:
                            pass
        except Exception:  # noqa: BLE001 â€” narration never blocks the turn
            pass

    def _admit_first_beat(self, plan, *, turn_id=None, session_id=None) -> None:
        """Speak the first planned beat immediately (REQ-10 AC10.10, T12).

        The planning call authors direction + time beats; the first speaks
        the moment authoring completes through the narration lane. Remaining
        beats stay on the plan for the T13 beat store (pending narration is
        subsumable, so they coalesce rather than stack). Never raises: beats
        are companion speech, never load-bearing for the turn.
        """
        try:
            beats = list(getattr(plan, "beats", None) or [])
            if not beats:
                return
            text = (beats[0] or "").strip()
            if not text:
                return
            from backend.agent.conversation_kernel import get_conversation_kernel
            from backend.agent.speech_lanes import (
                KIND_PLANNED,
                NARRATION,
                Situation,
                build_node,
                route,
            )

            kernel = get_conversation_kernel()
            scheduler = getattr(kernel, "scheduler", None) if kernel else None
            if scheduler is None:
                logger.debug("[AgentKernel] first beat dropped (no lane scheduler)")
                return
            situation = Situation(
                trigger_label=NARRATION,
                source="planned-beat",
                content_shape="prose",
            )
            node = build_node(
                situation,
                route(situation),
                turn_id=turn_id or "unknown",
                session_id=session_id or "unknown",
                content={"kind": "text", "text": text},
                kind=KIND_PLANNED,
            )
            scheduler.admit(node)
            logger.info(
                "[AgentKernel] first planned beat admitted (turn=%s)", turn_id
            )
        except Exception as exc:  # noqa: BLE001 â€” narration never blocks the turn
            logger.debug("[AgentKernel] first beat admit skipped: %s", exc)

    def _is_web_search_request(self, text: str) -> bool:
        """Quick heuristic: does the user message explicitly request a web search?

        REQ-15 AC15.3 (T19): this method's private trigger list was a DUPLICATE
        of ``explorer._WEB_INTENT_TRIGGERS``. Both are now one consumer â€”
        delegated here so there is exactly one place the phrasing list lives,
        with the engine's ``web_intent`` judgment consulted first when an engine
        is available (AC15.4: the keywords remain the fallback).
        """
        try:
            from backend.agent.explorer import AUTO_ENGINE, _is_web_intent
            # The engine is passed EXPLICITLY (2026-09-27). Without it the
            # consumer's verdict is never asked for, so web_intent writes no row
            # and can never reach the Wave 7 bar. `engine=None` still means "no
            # engine" on purpose â€” this is the caller opting in.
            # turn_key: one Oracle score per (turn, goal) - five call sites ask
            # about the same goal, twice a turn (Stage B, 2026-10-05).
            return bool(_is_web_intent(
                text or "", engine=AUTO_ENGINE,
                turn_key=getattr(self, "_current_turn_id", None),
            ))
        except Exception:  # noqa: BLE001 â€” a failed check is simply "no"
            return False

    def _looks_informational(self, text: str) -> bool:
        """Conservative fact-seeking intent signal (used ONLY with web mode ON).

        _is_web_search_request() requires an explicit search phrase, which
        misses factual questions that arrive without one â€” e.g. the frontend
        strips the "websearch:" prefix, so "what are the latest NASA Mars
        rover discoveries this month?" has no trigger phrase (T36 finding
        2026-08-09). This helper catches question-word / current-info
        phrasing so the DER-skip gate does not misroute them as chit-chat.

        Deliberately narrow: it must NOT match greetings or small talk
        ("hello", "how are you", "tell me a joke") â€” those stay on the fast
        path even when web mode is ON.
        """
        if not text:
            return False
        _lower = text.lower().strip()
        _triggers = [
            # question-word openers (fact-seeking, not chit-chat)
            "what is", "what are", "what's", "what was", "when was",
            "when did", "when is", "where is", "where are", "why did",
            "why is", "how many", "how much", "how long", "how big",
            "how far", "how does", "how do", "is there", "are there",
            "what happened", "what's happening", "what's new", "who won",
            # current-info / news phrasing
            "latest", "news", "recent", "today", "this month",
            "this week", "this year", "weather", "forecast", "score",
            "election", "population", "capital of", "price of", "stock",
            "launch", "discovery", "announce", "update on", "status of",
        ]
        return any(t in _lower for t in _triggers)

    def _should_skip_der(
        self,
        plan_steps: list,
        task_clean: str,
        web_on: bool,
    ) -> bool:
        """DER-skip gate (extracted for contract testing, T36 2026-08-09).

        Returns True when the plan may be answered on the direct fast path
        without the DER card machinery:
          - empty plan (nothing to execute), or
          - voice-only plan (only speak steps) AND no web-search intent AND
            NOT (web mode ON + factual/informational question).

        The web-mode clause is the T36 fix: with internet access toggled ON,
        a factual question (which the frontend may strip of its "websearch:"
        prefix) must reach DER so the crawler path stays available. Chit-chat
        still skips DER regardless of web mode.

        F6 interaction (2026-08-12): plan steps are GOALS ONLY â€” the parse
        hardcodes ``tool=None`` and the single resolver (explorer.propose)
        assigns tools at execution time. Therefore step.tool is ALWAYS None
        for production plans, and the empty string must NOT count as a
        "voice-only" tool. With "" in the speak set, every planned task was
        misread as voice-only and DER (task card + tool execution) was
        skipped â€” an explicit "use the screenshot_page tool" prompt produced
        a trivial plan, no task card, and the empty fallback. Only
        EXPLICITLY marked speak steps are voice-only now.
        """
        _voice_only = bool(plan_steps) and all(
            (s.tool or "").lower() in ("speak", "speak_tool", "tts")
            for s in plan_steps
        )
        _is_websearch = self._is_web_search_request(task_clean)
        _informational = self._looks_informational(task_clean)
        return (
            not plan_steps
            or (
                _voice_only
                and not _is_websearch
                and not (web_on and _informational)
            )
        )

    def _empty_der_fallback_message(
        self,
        text: str,
        web_on: bool,
        der_err_text: str = "",
    ) -> str:
        """Empty-DER fallback wording (extracted for contract testing, T36 2026-08-09).

        Produces an AWARE message instead of the old blind
        "IRIS couldn't generate a response. Please try again.":
          - real upstream error detail â†’ surface it (retry / switch model)
          - search-intent turn + web OFF â†’ advise toggling internet access
          - search-intent turn + web ON â†’ honest incomplete-search message
          - otherwise â†’ neutral rephrase guidance
        Never contains the phrase "couldn't generate" (contract: it must not
        reach a chat_message content on a healthy path).
        """
        _searchy = self._is_web_search_request(text) or self._looks_informational(text)
        if der_err_text:
            return (
                f"I hit an error while working on that ({der_err_text}). "
                f"You can try again, or ask me in a different way."
            )
        if _searchy and not web_on:
            return (
                "Web search is currently disabled. You can toggle internet "
                "access on via the dashboard (the web button) to enable "
                "web features."
            )
        if _searchy:
            return (
                "I couldn't complete the web search for that â€” the search "
                "returned nothing usable. Please try again, or ask me "
                "without the web."
            )
        return (
            "I wasn't able to put together an answer for that. You can "
            "try again, or rephrase your question."
        )

    @_turn_in_flight
    @restores_call_class
    def process_text_message(
        self,
        text: str,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
        from_voice: bool = False,
        turn_id: Optional[str] = None,
        card_context: Optional[str] = None,
    ) -> str:
        """
        Main entry point for text messages.
        Decides between direct response and agentic (tool-calling) loop.

        conversation_id: Key for per-thread context persistence. If None,
                         falls back to self.conversation_id (or session_id).
        from_voice: when True the request came from the voice pipeline.
          - Overrides mode detection â†’ "voice_first"
          - Uses DER_TOKEN_BUDGETS["voice_first"] (15k tokens, under 20k)
          - Planning caps at 1 step for fast first-token response
        """
        _t_start = time.perf_counter()
        self._turn_from_voice = bool(from_voice)

        # T6.4: mark the call class as USER_TURN at the real turn entry so the
        # phase gate admits it immediately (high-priority lane).
        set_call_class(CallClass.USER_TURN)

        # Trust-routing W2: each new turn starts unmarked; the external flag is
        # set if a web/crawler tool runs during this turn.
        self.clear_turn_trust_flag()
        # pin_517dfcbda150: the web-gather budget is per-task â€” it resets at the
        # turn boundary so a new task may gather up to _MAX_CRAWLS_PER_TASK
        # distinct (refined) queries again.
        self._der_crawl_attempts = {}
        # Spec A4: the quick-tier escalation flag is per-task like the budget.
        self._der_quick_insufficient = set()

        # Use provided session_id or fall back to instance session_id
        if session_id is None:
            session_id = self.session_id
        # The kernel's own session_id is fixed at creation; the TURN's session
        # (this WebSocket) is what tool calls must run under - see
        # _respond_direct. The DER path already receives it as a parameter.
        self._turn_session_id = session_id
        # tool_approval (safety, 2026-11-10): the permission site knows only the
        # session, so the request rides here for the safety frame.
        try:
            from backend.agent.tool_approval_shadow import note_request

            note_request(session_id, text)
        except Exception:  # noqa: BLE001 - bookkeeping never blocks a turn
            logger.debug("[AgentKernel] tool_approval request note skipped")
        # D3 (2026-10-31): the turn's monotonic start. The reply exit accepts a
        # memory-deletion claim only against a `forget` tool event after this
        # stamp, so a previous turn's delete can never justify this turn's claim.
        self._turn_started_monotonic = time.monotonic()

        # Resolve conversation_id â€” primary key for per-thread context.
        # getattr guard: a kernel may be constructed without __init__ (test
        # stubs, partial init) â€” never raise on a missing attribute. The
        # session_id fallback is the documented behavior (docstring above).
        _conv_id = conversation_id or getattr(self, "conversation_id", None) or session_id
        self.conversation_id = _conv_id

        # Event taxonomy step 3: EVERY user message (text and voice enter here) gets
        # an Oracle `user_feedback` shadow decision. Queues one lane job and returns;
        # never on the answer path, never changes the turn.
        try:
            from backend.agent.event_oracle import observe_user_message

            observe_user_message(
                self, text, thread_id=_conv_id, turn_id=turn_id, from_voice=from_voice,
                episode_id=f"{_conv_id}:{turn_id}" if turn_id else None,
            )
        except Exception as _eo_err:  # noqa: BLE001 - an observer never blocks a turn
            logger.debug("[AgentKernel] event oracle observe skipped: %r", _eo_err)

        # REQ-12 AC1 (T42): the user's own words enter the Immortus chain as a
        # role='user' row, on the fragment lane. Turn entry is the one place both
        # the direct and the DER path pass through.
        self._turn_mem_prompts = 0   # OBSERVABILITY (T48): per-turn path line
        try:
            from backend.agent.mcm_protocol.actions.pacman_fragment import (
                submit_user_turn_entry as _submit_user_turn_entry,
            )

            _submit_user_turn_entry(
                getattr(self, "_memory_interface", None), _conv_id, text,
            )
        except Exception as _ut_err:  # noqa: BLE001 - memory bookkeeping never blocks
            logger.debug("[AgentKernel] user turn chain append skipped: %r", _ut_err)

        # Reset thinking from any previous call so stale data never leaks
        self._pending_thinking = ""

        # Stage 1 observability: per-turn metrics (created early so error paths can log)
        import uuid

        task_id = turn_id or str(uuid.uuid4())
        # The frontend's turn id for everything this turn emits outside the DER
        # parameters (create_artifact cards, tool-bridge rows, card snapshots).
        # 13 sites read it; nothing assigned it, so all of them got None and a
        # rendered card never joined its live turn (HANDOFF 6 finding).
        self._current_turn_id = turn_id
        # REQ-6 AC6.3a (T5.0): the Oracle row scope. Consult sites read it as
        # values at submit time; rows of this turn join on the turn id.
        try:
            from backend.agent.decision_engine import set_scope as _de_set_scope

            _de_set_scope(turn_id=turn_id, step_id=None, node_exec_id=None)
        except Exception:  # noqa: BLE001 - scope is best-effort
            pass
        # Taxonomy events of this turn share one episode id (same as Wave E's task id).
        self._event_episode_id = f"{session_id}:{task_id}"
        metrics = TurnMetrics(turn_id=task_id)
        # REQ-13 AC4 (reply-surface-contract T18): give the reply seam a cheap,
        # fire-and-forget handle on this turn's metrics so the first
        # DOCUMENT_RENDER emit can stamp `card_ms` (time-to-card). Attribute
        # copy only; the seam getattr-guards it, so a missing handle is safe.
        self._active_turn_metrics = metrics
        # REQ-5 AC1 (T8): stamp the semantic-gate compilation onto this turn's
        # [LAYERS] emit (off the hot path â€” attribute copies only).
        self._stamp_gate_telemetry(metrics)
        # REQ-3 T8b AC5: per-turn prompt-token counter accumulated at each DER
        # step's context assembly (forgetting bound), recorded into TurnMetrics.
        self._der_step_prompt_tokens = 0
        # REQ-7 AC3 (T25): per-turn DER call counter (batched groups count once).
        self._der_turn_calls = 0
        # T11 (REQ-12): per-turn DER step count, wired from the DER loop's
        # completed_items at finalize so [LAYERS] der_steps is an observation,
        # not the declared-never-assigned 0 it was until 2026-08-06.
        self._der_step_count = 0
        try:
            from backend.gateway.iris_ffi import _engine

            metrics.engine = (
                "native" if (_engine and getattr(_engine, "_ffi", None)) else "fallback"
            )
        except Exception:
            metrics.engine = "fallback"

        # Wrap chunk_callback to mark TTFT on first contentful chunk
        _original_chunk_cb = chunk_callback

        def _wrapped_chunk_cb(chunk: str):
            metrics.mark_first_token()
            if _original_chunk_cb:
                _original_chunk_cb(chunk)

        # Check if agent is available
        if self._initialization_error:
            error_msg = f"Agent kernel is not available: {self._initialization_error}"
            logger.error(f"[AgentKernel] {error_msg}")
            logger.info(metrics.to_log_line())
            return error_msg

        if not self._model_router or not self._conversation_memory:
            error_msg = "Agent kernel is not available"
            logger.error(f"[AgentKernel] {error_msg}")
            logger.info(metrics.to_log_line())
            return error_msg

        # Create TaskContext to carry full context through pipeline (fixes Bug 3, 4, 5, 6)
        _t_start = time.perf_counter()

        # Gate 3 T4 (REQ-2/D1): shell context is EPHEMERAL â€” it is assembled
        # into THIS turn's outgoing context list below and never persisted to
        # conversation memory. Volatile environmental telemetry does not belong
        # in durable dialogue history: add_message() would re-send the block on
        # every LLM call of every later turn until FIFO eviction dropped it,
        # occupy one of ten window slots, and write raw-ish shell bytes into
        # conversation.json. The drained records stay readable by ref instead
        # (ShellRecordQueue retention + read_shell_output), so nothing is lost.
        _shell_block = ""
        try:
            # Add user message to conversation memory
            self._conversation_memory.add_message("user", text)
            logger.info(f"[AgentKernel] Processing text message: {text[:50]}...")

            # Drain queued shell records at turn assembly â€” the next turn
            # builds on real shell state, never a guess. Redaction/truncation
            # happened at record time; the aggregate budget was enforced in
            # drain(). A failed drain is degraded-but-working (design Error
            # Handling), never fatal.
            try:
                from backend.dev.shell_records import get_shell_record_queue

                _q = get_shell_record_queue()
                _shell_block, _suppressed = _q.drain(session_id)
                # Keyed by session_id on BOTH sides -- the terminal handler
                # records under it and this drains under it. A mismatch is
                # silent (empty block, no error), so name both sides here.
                logger.debug(
                    "[AgentKernel][%s] shell drain -> %d chars (queued sessions: %s)",
                    session_id, len(_shell_block), list(_q.known_sessions()),
                )
            except Exception as _exc:
                logger.debug("[AgentKernel] shell-context drain skipped: %s", _exc)

            # A fresh user turn supersedes any prior soft-cancel (REQ-6
            # client_replace). If the user navigated away mid-task and then
            # returns to send a new message in the SAME conversation, the
            # stale _cancel_requested flag would otherwise halt the DER loop
            # before executing any step â†’ "no usable sources found" with zero
            # steps run.
            try:
                _cancel = getattr(self, "_cancel_requested", None)
                if _cancel is not None and _cancel.is_set():
                    _cancel.clear()
                    logger.info(
                        f"[AgentKernel] Cleared stale _cancel_requested for "
                        f"conv={conversation_id} â€” new user turn supersedes prior soft-cancel"
                    )
            except Exception:
                pass

            # Get conversation context
            context = self._conversation_memory.get_context()
            # Session 246 (@-card-mentions): referenced task-card snapshots
            # arrive as a per-turn system block â€” visible to planning and
            # synthesis for THIS turn only. Appended to the LOCAL context list,
            # never add_message()'d, so conversation memory stays clean.
            if card_context:
                context = list(context) + [
                    {"role": "system", "content": card_context}
                ]
                logger.info(
                    f"[AgentKernel] @-card context injected "
                    f"({len(card_context)} chars) conv={conversation_id}"
                )
            # Gate 3 T4 (REQ-2 AC1): the shell block rides the SAME local
            # channel as the @-card block â€” visible to planning and synthesis
            # for THIS turn only, never add_message()'d.
            if _shell_block:
                context = list(context) + [
                    {"role": "system", "content": _shell_block}
                ]
                logger.info(
                    "[AgentKernel][%s] shell context injected (%d chars, ephemeral)",
                    session_id, len(_shell_block),
                )
        except Exception as e:
            # Handle conversation memory errors gracefully
            logger.warning(f"[AgentKernel] Conversation memory error: {e}")
            context = []  # Continue with empty context

        _t_memory = time.perf_counter()
        logger.debug(
            f"[Timing] memory.get_context: {(_t_memory - _t_start) * 1000:.1f} ms"
        )
        # C5 fold-back: the previous turn's episode lands before planning
        # recalls episodes.
        _turn_end_settle(self)

        # â”€â”€ Direct path (default): skip planning for non-tool messages â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Route shadow (REQ-18, T30): record the fork for every turn, ahead
        # of either branch so both route choices land in the log. The gate
        # answer is computed ONCE here and reused by the branch below â€” the
        # shadow must add no work to the reply path (REQ-18 AC2/AC5).
        # REQ-24: the USER's own phrasing exists only here - the
        # tool-decision ladder sees model-rewritten step goals, so stash
        # the turn text for the bounded-ask veto below.
        self._current_turn_text = text or ""
        _needs_planning = self._needs_planning(text, context)
        # route_v2's decision site (2026-11-10): the Oracle's route acts when
        # the bar lets it decide, or on the sampled rung's bounded share of
        # turns (labelled by the turn verdict). Otherwise the gate's route
        # stands and the Oracle is only shadowed below.
        _oracle_route = self._route_v2_route(text, task_id, _needs_planning)
        if _oracle_route is not None:
            _needs_planning = _oracle_route
        self._log_route_shadow(
            turn_id=task_id,
            text=text,
            planned=_needs_planning,
            web_mode=self._web_mode_on(),
            oracle_acted=_oracle_route is not None,
        )
        # Planning only runs when the message explicitly requests a tool-backed
        # action (search, open, create, etc.).  Everything else â€” greetings,
        # questions, conversation â€” goes straight to _respond_direct() which
        # calls the model with no JSON schema overhead.
        if not _needs_planning:
            logger.info("[AgentKernel] Direct response path (no planning needed)")
            try:
                _t_llm_start = time.perf_counter()
                response = self._respond_direct(
                    text,
                    context,
                    chunk_callback=_wrapped_chunk_cb,
                    reasoning_callback=reasoning_callback,
                    session_id=session_id,
                )
                _t_llm_end = time.perf_counter()
                logger.info(
                    f"[Timing] LLM call (_respond_direct): {(_t_llm_end - _t_llm_start) * 1000:.0f} ms  |  "
                    f"total process_text_message: {(_t_llm_end - _t_start) * 1000:.0f} ms"
                )
            except Exception as e:
                logger.error(f"[AgentKernel] LLM call failed: {e}")
                logger.info(metrics.to_log_line())
                # Re-raise so the caller (_execute_agent in iris_gateway.py)
                # handles it with structured logging and sends a visible
                # error to the UI. No silent error swallowing.
                raise
            # Issue C.1: apply speak/show contract â€” emit document:render for
            # the `show` payload and reduce the stored/returned text to `speak`.
            response = self._process_structured_response(
                response, turn_id=task_id, conversation_id=_conv_id
            )
            # Never store error or empty responses in conversation memory.
            # They break role alternation and accumulate into garbage context
            # on subsequent turns, causing Cohere/OpenAI 400 errors.
            if response and not response.startswith("[IRIS error:"):
                try:
                    self._conversation_memory.add_message(
                        "assistant", response, sources=self._turn_sources(),
                    )
                except Exception as _mem_exc:
                    loud_error(_mem_exc, "conversation_memory.add_message (direct)")
            # Option B / Pacman: fragment this turn-pair into the vector DB so future
            # context assembly can retrieve it semantically (PACMAN.md Â§Digestion).
            # MCM orchestrator handles fragmentation + compression check when available.
            try:
                if response:
                    # Trust-routing W2: route to 'reference' when this turn
                    # touched external/web sources; else keep default 'trusted'.
                    _zone = self._pacman_zone_for_turn()
                    if self._mcm_orch is not None:
                        self._mcm_orch.post_turn(
                            self._conversation_memory.messages
                            if self._conversation_memory
                            else [],
                            response_text=response,
                            zone=_zone,
                        )
                        metrics.pacman_store += 1
                    # REQ-12 AC3 (T42): the USER's own words are stored as a turn
                    # pair on BOTH paths, on the fragment lane, bypassing
                    # _is_fragment_candidate (which drops normal conversation).
                    from backend.agent.mcm_protocol.actions.pacman_fragment import (
                        submit_turn_pair as _submit_turn_pair,
                    )

                    if _submit_turn_pair(
                        getattr(self, "_memory_interface", None),
                        session_id or self.session_id,
                        text, response, zone=_zone,
                    ):
                        metrics.pacman_store += 1
            except Exception as _pac_exc:
                loud_error(_pac_exc, "pacman fragment_and_store")
            if response is None:
                logger.error(
                    "[AgentKernel] _respond_direct returned None â€” returning fallback"
                )
                response = "I wasn't able to generate a response. Please check the model connection."
            metrics.path = "direct"
            logger.info(f"[AgentKernel] Direct response: {response[:50]}...")
            logger.info(metrics.to_log_line())
            # REQ-12 (Wave 9): emit live context usage on every non-DER
            # response so the pill is live from the first reply. Uses the real
            # per-thread self._context_fill (never 0 for an active thread).
            self._emit_context_usage()
            return response

        # â”€â”€ Internet-access gate check (runs before DER to save cost) â”€â”€â”€â”€â”€â”€
        # If web tools are disabled and the user explicitly asked for a web
        # search, respond directly without engaging the expensive DER loop.
        # A request that names the live browser needs the web too: with
        # internet off the node menu has no browser tool, and the turn spent
        # 90 s on curl via an unknown run_command, memory lookups and grafts
        # (live conv-1574, 2026-10-12).
        if not get_global_internet_access() and (
            self._is_web_search_request(text) or _LIVE_BROWSER_RE.search(text or "")
        ):
            return (
                "Web search is currently disabled. You can toggle internet "
                "access on via the dashboard (the web button) to enable "
                "web features."
            )

        # â”€â”€ Thinking feedback: emit a filler utterance so the user hears â”€â”€
        # audio feedback while the agent is "thinking" (DER/ReAct path).
        # Gap-filler exception (REQ-10 AC10.13, T16): fires ONLY when speech
        # would otherwise be silent AND no beat is ready; never the same
        # phrase twice consecutively; subsumed the moment a real beat arrives
        # (scheduler.admit cancels queued speak_tool-sourced narration).
        # Fire-and-forget via the speak tool; ConversationKernel drives TTS
        # (phase defaults to EXPAND in production, so it is never suppressed).
        try:
            from backend.agent.tools.speak_tool import get_speak_tool
            from backend.agent.speech_lanes import filler_allowed, pick_filler
            from backend.agent.conversation_kernel import get_conversation_kernel

            _sched = getattr(get_conversation_kernel(), "scheduler", None)
            if filler_allowed(_sched):
                get_speak_tool().speak(pick_filler(), priority="low")
        except Exception as _filler_err:
            logger.debug("[AgentKernel] thinking filler emit skipped: %s", _filler_err)

        # â”€â”€ Lock gate (W6 T27-T29): prevent concurrent DER on same conversation â”€â”€
        if self._der_active:
            # DER is already running for this conversation. Answer chitchat directly
            # or ask the user to wait for complex tool-backed requests.
            if not self._needs_planning(text, context):
                logger.info("[AgentKernel] DER active â€” answering chitchat directly")
                return self._respond_direct(
                    text, context,
                    chunk_callback=_wrapped_chunk_cb,
                    reasoning_callback=reasoning_callback,
                    session_id=session_id,
                )
            logger.info("[AgentKernel] DER active â€” deferring complex request")
            return "Still working on your previous request â€” one moment."

        # â”€â”€ DER path: sanitize â†’ classify â†’ Mycelium â†’ plan â†’ execute â”€â”€â”€â”€â”€â”€
        # Runs BEFORE the ReAct loop. Falls through to ReAct on any failure.
        _der_response: Optional[str] = None
        self._der_active = True
        _der_lock_cleanup = True  # cleared in finally
        # Session 248: stage timing for the pre-plan pipeline â€” live runs show
        # a ~20s silent stall between message receipt and TaskClassifier on
        # the FIRST DER-path message of a process (chitchat bypasses via
        # _respond_direct, so it never pays this). These logs make the lazy
        # init cost visible instead of silent.
        import time as _der_t
        _t_stage = _der_t.monotonic()

        def _log_stage(label: str) -> None:
            nonlocal _t_stage
            logger.info(
                "[Timing] DER stage %s: %.0f ms", label,
                (_der_t.monotonic() - _t_stage) * 1000,
            )
            _t_stage = _der_t.monotonic()

        try:
            _task_clean = self._sanitize_task(text)
            _log_stage("sanitize_task")
            _task_class = "full"
            if self._task_classifier is not None:
                try:
                    _task_class, _ = self._task_classifier.classify(_task_clean)
                    _log_stage("task_classifier.classify")
                except Exception as _tc_exc:
                    loud_error(_tc_exc, "task_classifier.classify")

            _context_package = None
            _is_mature = False
            if self._memory_interface is not None:
                try:
                    _ctx_result = self._memory_interface.get_task_context_package(
                        task=_task_clean,
                        task_class=_task_class,
                        session_id=session_id or self.session_id,
                    )
                    if isinstance(_ctx_result, tuple) and len(_ctx_result) == 2:
                        _context_package, _is_mature = _ctx_result
                    elif _ctx_result is not None:
                        _context_package = _ctx_result
                    _log_stage("get_task_context_package")
                except Exception as _ctx_exc:
                    loud_error(_ctx_exc, "memory_interface.get_task_context_package")

            # Mode detection â€” runs AFTER Mycelium fetch so mature graph data
            # can suppress clarification mode and improve confidence.
            # Result flows into _plan_task() (temperature) and _execute_plan_der()
            # (token budget via DER_TOKEN_BUDGETS[mode]).
            # Voice requests skip mode detection and lock to "voice_first" so
            # they always get the tight 15k token budget and single-step plan.
            # Confidence defaults to 0.5 for voice â€” memory-derived when mature.
            if from_voice:
                _mode_name = "voice_first"
                _confidence = 0.70 if _is_mature else 0.50
            else:
                _mode_name = "full"  # default maps to DER_TOKEN_BUDGETS["full"]
                _confidence = 0.50
                if self._mode_detector is not None:
                    try:
                        _mode_result = self._mode_detector.detect(
                            task=_task_clean,
                            context_package=_context_package,
                            is_mature=_is_mature,
                        )
                        _mode_name = _mode_result.mode.name.lower()
                        _confidence = _mode_result.confidence
                    except Exception as _md_exc:
                        loud_error(_md_exc, "mode_detector.detect")
                    # The `mode` Oracle consumer was REMOVED 2026-10-10 (owner):
                    # no shadow row to forward any more.

            _plan = None
            try:
                self._last_plan_failure = None
            except Exception:
                pass
            for _plan_attempt in range(3):
                _plan = self._plan_task(
                    text=_task_clean,
                    context=context,
                    is_mature=_is_mature,
                    task_class=_task_class,
                    context_package=_context_package,
                    mode=_mode_name,
                    session_id=session_id or self.session_id,
                )
                if _plan is not None:
                    break
                # Billing/auth failures cannot heal in 5 s â€” fail fast with
                # the true cause instead of burning retries on a dead key.
                _classified = self._classify_plan_failure()
                if _classified[2]:
                    break
                if _plan_attempt < 2:
                    # Planner failure is almost always the provider quota: the
                    # transport already burned its 3x30s retries, so the 60s
                    # provider window has usually ROLLED by now â€” a short gap
                    # and a fresh attempt lands in new quota. Without this, a
                    # single saturated minute returned "[IRIS error] The planner
                    # returned no valid plan" (observed live).
                    logger.info(
                        "[process_text_message] planner attempt %d failed â€” "
                        "retrying after quota-window gap",
                        _plan_attempt + 1,
                    )
                    import time as _time_mod

                    _time_mod.sleep(5)
            if _plan is None:
                # REQ-2: planner failure â†’ return ERROR, no silent self-do.
                # The failure kind (recorded by _plan_task) decides the
                # message, so billing/auth/quota/timeout/parse/empty each
                # report distinctly instead of one vague planner error.
                _code, _msg, _ = self._classify_plan_failure()
                logger.warning("[process_text_message] %s code=%s", _msg, _code.name)
                # Every other _emit_context_usage() site sits on a SUCCESS
                # path, so a turn that died here emitted nothing and the
                # ContextPill kept whatever it had â€” with the old hardcoded
                # 128000 initial state that meant it displayed 128k forever on
                # a Cerebras 402 (billing) loop, which is precisely the case
                # that fails fast above. The denominator costs no model call:
                # resolve_context_window() is a lookup. Emitted on the FAILURE
                # path only, so a successful turn still emits exactly once
                # (REQ-6 AC1, pinned by test_context_usage_on_direct_reply).
                self._emit_context_usage()
                return _msg

            # GAP 5 â€” strategy signal to Mycelium after planning
            try:
                if self._memory_interface:
                    self._memory_interface.mycelium_ingest_statement(
                        statement=f"task required {_plan.strategy}: {_plan.reasoning}",
                        session_id=session_id or self.session_id,
                    )
            except Exception as _ing_exc:
                loud_error(_ing_exc, "mycelium_ingest_statement")

            # GAP 6 â€” register plan address when Mycelium is mature
            try:
                if (
                    _is_mature
                    and _context_package
                    and hasattr(_context_package, "register_address")
                ):
                    _plan_ctx_str = _plan.to_context_string()
                    _context_package.register_address(
                        url=f"system://plan/{_plan.plan_id[:8]}",
                        token_count=len(_plan_ctx_str.split()),
                        summary=f"{_plan.strategy}: {_plan.original_task[:60]}",
                    )
            except Exception as _reg_exc:
                loud_error(_reg_exc, "context_package.register_address")

            # GAP 4 â€” route by strategy (do_it_myself â†’ DER; others â†’ ReAct)
            if _plan.strategy == "do_it_myself":
                # â”€â”€ Emit TASK_START early so the frontend sees the plan
                # skeleton BEFORE the DER thread starts executing tools
                # (fixes Q4 plan-late bug â€” without this, task:start and
                # the first tool:call can arrive in the same WS batch,
                # making the plan card appear to jump straight to "working").
                # Voice-only DER bypass: skip DER/card for trivial chit-chat
                # (plan with only speak steps and no websearch intent).
                # Websearch prompts MUST go through DER so the frontend
                # receives card/render events even when the plan has only
                # speak steps â€” the DER loop resolves speak steps via
                # ToolDecisionBox â†’ _run_step_direct, which produces both
                # voice and card output.
                # NOTE (2026-09-27): the "" in this tuple is gone. The docstring
                # of _should_skip_der (F6, 2026-08-12) records why: production
                # plan steps are GOALS ONLY with tool=None, so counting "" as a
                # speak step made EVERY planned task look voice-only and DER was
                # skipped. That fix was applied inside the method but this
                # call-site copy was left behind. It is dead code today (nothing
                # reads it), which is exactly why it survived a review and why it
                # is worth removing rather than leaving to be "reused" later.
                _voice_only = bool(_plan.steps) and all(
                    (s.tool or "").lower() in ("speak", "speak_tool", "tts")
                    for s in _plan.steps
                )
                _is_websearch = self._is_web_search_request(_task_clean)
                # T36 finding (2026-08-09): the skip gate ignored the
                # internet-access toggle. With web mode ON, a factual
                # question ("what are the latest NASA Mars rover
                # discoveries this month?") must reach DER so the crawler
                # path is available â€” even when the text heuristic misses
                # (frontend strips the "websearch:" prefix). Chit-chat
                # ("hello", "how are you") still skips DER on the fast path.
                _web_on = get_global_internet_access()
                _skip_der = self._should_skip_der(
                    _plan.steps, _task_clean, _web_on
                )
                if _skip_der:
                    logger.info(
                        "[AgentKernel] voice-only/trivial plan (steps=%d, "
                        "websearch=%s, web_on=%s, informational=%s) â€” skipping "
                        "DER/card, falling through to direct response",
                        len(_plan.steps),
                        _is_websearch,
                        _web_on,
                        self._looks_informational(_task_clean),
                    )
                    # REQ-35 AC1/AC4: the planner said this needs no plan.
                    # That is a TERMINAL ANSWER -- it decides what happens
                    # NEXT, and it is not a verdict that anything succeeded.
                    #
                    # The comment here used to read "forces the direct path
                    # below" and set "". It did not: the very next guard is
                    # `if _der_response is not None`, an empty STRING is not
                    # None, so control reached the empty-DER handler and
                    # returned the canned apology. Measured live (conv-59):
                    # the planner answered, the answer was discarded, and the
                    # user was told "I wasn't able to put together an answer
                    # for that."
                    #
                    # So take the direct path FOR REAL. Deliberately NOT the
                    # planner's own incidental `answer` field: _respond_direct
                    # re-asks with the full system prompt, context and tools,
                    # so the reply is a normal direct answer rather than a
                    # by-product trusted because the model volunteered it.
                    # No DER ran, so no task:done and no completion claim
                    # (AC4) -- this is an ANSWER, at the same standing as any
                    # other direct reply.
                    try:
                        _der_response = self._respond_direct(
                            text, context,
                            chunk_callback=chunk_callback,
                            reasoning_callback=reasoning_callback,
                            session_id=session_id,
                        )
                        logger.info(
                            "[AgentKernel] trivial plan -> direct answer "
                            "(%d chars)", len(_der_response or ""),
                        )
                    except Exception as _direct_exc:  # noqa: BLE001
                        # AC7: the canned fallback still exists for a run that
                        # genuinely produced nothing. Fewer arrivals is the
                        # goal; removing the path is not.
                        logger.warning(
                            "[AgentKernel] trivial-plan direct answer failed: %s",
                            _direct_exc,
                        )
                        _der_response = ""
                else:
                    # T12 (REQ-10 AC10.10): planning completed and the turn
                    # proceeds to DER â€” the first planned beat speaks now.
                    # (Skipped entirely on the trivial-plan path above: short
                    # work stays fully voiced via the reply lane.)
                    try:
                        self._admit_first_beat(
                            _plan,
                            turn_id=getattr(self, "_current_turn_id", None),
                            session_id=session_id or self.session_id,
                        )
                        # T14: beats 2..N admit as pending narration with
                        # pre-synthesized buffers (degrades to on-admission).
                        self._admit_planned_beats(
                            _plan,
                            turn_id=getattr(self, "_current_turn_id", None),
                            session_id=session_id or self.session_id,
                        )
                    except Exception:
                        pass
                    try:
                        from backend.agent.event_bus import get_event_bus, IRISStreamEvent

                        _bus = get_event_bus()
                        _steps = [
                            {
                                "id": s.step_id,
                                "description": s.description[:120],
                                "status": "pending",
                                "toolName": s.tool,
                                "stepNumber": s.step_number,
                            }
                            for s in _plan.steps
                        ]
                        logger.info(
                            "[AgentKernel] TASK_CARD ts=%.3f conv=%s turn=%s "
                            "title=%r steps=%d :: %s",
                            time.time(),
                            self.conversation_id,
                            getattr(self, "_current_turn_id", None),
                            (_plan.plan_title or "")[:80],
                            len(_steps),
                            " | ".join(s["description"] for s in _steps)[:300],
                        )
                        # â”€â”€ Card gate (owner bound, 2026-09-25) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                        # Decided BEFORE the first task:start emit. Live
                        # 2026-09-25: the DER-internal decision ran AFTER this
                        # emit, so a card-free turn still showed a card whose
                        # terminal events were then withheld â€” the card appeared
                        # and never reached DONE. Registering here (and again in
                        # DER, which also arms the persist gate) closes that gap.
                        try:
                            from backend.agent.artifact_policy import (
                                card_warranted,
                                clear_card_free_conversation,
                                suppress_card_for_conversation,
                            )
                            self._current_task_text = (
                                getattr(_plan, "original_task", "") or ""
                            )
                            if card_warranted(
                                _plan.steps, getattr(_plan, "original_task", "") or ""
                            ) or _developer_mode(self):
                                # This turn HAS a card: stop gating the thread.
                                self._suppressed_card_turn = None
                                clear_card_free_conversation(self.conversation_id)
                            else:
                                _gated_turn = task_id or getattr(self, "_current_turn_id", None)
                                suppress_card_for_conversation(
                                    self.conversation_id, _gated_turn,
                                )
                                # Arms the persist gate too: without it the
                                # snapshot below saved a "running" card row
                                # for every card-free turn, rehydrated later
                                # as a card that never rendered (2026-10-12).
                                self._suppressed_card_turn = _gated_turn
                        except Exception:
                            pass  # the gate must never block a turn
                        _card_task_id = task_id or _plan.original_task[:40]
                        _card_id, _card_relation = self._resolve_card_identity(
                            _card_task_id, "initial"
                        )
                        _bus.emit(
                            IRISStreamEvent.TASK_START,
                            data=self._task_start_payload(
                                task_id=_card_task_id,
                                description=_plan.original_task[:200],
                                plan_title=self._effective_plan_title(_plan),
                                mode=_mode_name,
                                steps=_steps,
                                total_steps=len(_plan.steps),
                                # REQ-14 (T23): initial plan announcement â€”
                                # revisions re-emit through the same merge-by-id
                                # channel with origin "sub_loop_split" (REQ-4/13)
                                # or "user_steering" (REQ-15).
                                origin="initial",
                                # REQ-3 (T2): backend-declared card identity.
                                card_id=_card_id,
                                card_relation=_card_relation,
                                conversation_id=self.conversation_id,
                                    turn_id=getattr(self, "_current_turn_id", None),
                                **self._multiagent_tags(),
                            ),
                            session_id=session_id or self.session_id,
                        )
                        # T4a (REQ-4 AC1): persist the card at task:start â€”
                        # upsert with terminal_state="running".
                        self._persist_card_snapshot(
                            card_id=_card_id,
                            conversation_id=self.conversation_id,
                            card_relation=_card_relation,
                            plan_title=self._effective_plan_title(_plan),
                            mode=_mode_name,
                            steps=_steps,
                            total_steps=len(_plan.steps),
                            terminal_state="running",
                        )
                    except Exception:
                        pass  # never block execution on an event emission failure

                    # Session 247 FIX (recurring â€” see pin_5b79ddf5f112,
                    # pin_9e97e21340e7): the planner MODE name ("implement",
                    # "debug", â€¦) must size the TOKEN BUDGET only. It used to
                    # REPLACE task_class outright, which (a) sent
                    # _decide_mode down its unrecognized-class AGENTIC
                    # default â€” the legacy card-less path with no card_id on
                    # events, no terminal task:done, frozen verbs (live
                    # conv-42) â€” and (b) made explorer.propose withhold web
                    # tools, since propose assigns them only for research
                    # classes. The classifier's label stays authoritative for
                    # every DECISION; the mode name rides along as
                    # _der_budget_class purely for DER_TOKEN_BUDGETS lookup.
                    _der_task_class = _task_class
                    _der_budget_class = (
                        _mode_name if _mode_name in DER_TOKEN_BUDGETS else _task_class
                    )
                    _der_response = self._der_execute_with_recovery(
                        _plan=_plan,
                        _context_package=_context_package,
                        _is_mature=_is_mature,
                        _der_task_class=_der_task_class,
                        _der_budget_class=_der_budget_class,
                        _session=session_id or self.session_id,
                        from_voice=from_voice,
                        _confidence=_confidence,
                        task_id=task_id,
                    )

        except Exception as _der_err:
            logger.warning(
                f"[AgentKernel] DER path error (falling back to ReAct): {_der_err}",
                exc_info=True,
            )
            # Also log to structured logger so error appears in irisvoice.log
            try:
                from backend.core.logging_config import get_agent_logger

                get_agent_logger().warning(
                    "DER path error",
                    error=str(_der_err),
                    error_type=type(_der_err).__name__,
                )
            except Exception:
                pass
            # Store the actual error in _der_response so the error path below
            # can surface it to the user instead of a generic message.
            _der_response = f"[IRIS error: {_der_err}]"
        finally:
            # W6 (T31): always clear the DER active flag, even on exception.
            self._der_active = False

        if _der_response is not None:
            # Only accept DER response if it produced actual content.
            # Empty plans (0 steps completed) or fallback markers from
            # failed local-model execution should fall through to the
            # agentic loop so the model can use tools via the API.
            #
            # Patterns that indicate DER produced no real response:
            #   - empty string
            #   - "[DER]" prefix with "0/" steps
            #   - "[step X completed]" or "[step X error:]" which mean
            #     the local execution model failed to produce content
            _der_text = _der_response.strip()
            _is_empty = not _der_text or (
                "[DER]" in _der_text[:20] and "0/" in _der_text[:50]
            )
            if not _is_empty:
                try:
                    self._conversation_memory.add_message(
                        "assistant", _der_response, sources=self._turn_sources(),
                    )
                except Exception as _mem_exc:
                    loud_error(_mem_exc, "conversation_memory.add_message (der)")
                metrics.path = "der"
                logger.info(f"[AgentKernel] DER response: {_der_response[:200]}...")
                metrics.step_prompt_tokens = getattr(
                    self, "_der_step_prompt_tokens", 0
                )
                # REQ-7 AC3 (T25): record the per-turn DER call count so the
                # loop's actual call count is visible against the T3 baseline.
                metrics.der_calls = getattr(self, "_der_turn_calls", 0)
                # T11 (REQ-12): record the completed-step count â€” wired at the
                # DER loop finalize (was declared-never-assigned before
                # 2026-08-06, so [LAYERS] reported der_steps=0 while steps ran).
                metrics.der_steps = getattr(self, "_der_step_count", 0)
                # REQ-6 AC1/AC3 (T18): governance-source counts for the [LAYERS]
                # line â€” which signal governed this turn's steering decisions
                # (past-memory / live-state / both) and the alternation ratio
                # (computed in to_log_line).
                _gov = getattr(self, "_der_governance_counts", None) or {}
                metrics.gov_past = int(_gov.get("past", 0) or 0)
                metrics.gov_live = int(_gov.get("live", 0) or 0)
                metrics.gov_both = int(_gov.get("both", 0) or 0)
                # REQ-17 AC1 (T34): the REAL budget source (the source that
                # won in resolve_context_window_with_source â€” override /
                # authoritative / table / default), never a silent 8192.
                try:
                    metrics.budget_source = (
                        self.resolve_context_window_with_source().source or "default"
                    )
                except Exception:
                    metrics.budget_source = "default"
                # REQ-17 AC1 (T34): chain-drop count + 429 count this turn.
                metrics.chain_drop_count = int(
                    getattr(self, "_der_chain_drops", 0) or 0
                )
                # 429 count: the rate meter's per-quota 429 frequency, summed
                # across metered windows (the transport observes 429s there;
                # the kernel never counts them itself). 0 when no metered
                # quota exists or the meter is unavailable â€” never raises.
                metrics.count_429 = 0
                try:
                    from backend.agent.rate_meter import get_rate_meter

                    _meter = get_rate_meter()
                    for _qid, _w in _meter._windows.items():
                        if _w.metered:
                            metrics.count_429 += int(
                                _meter.rate_health(_qid).get(
                                    "count_429_in_window", 0
                                )
                                or 0
                            )
                except Exception:
                    metrics.count_429 = 0
                # REQ-17 AC1 (T34): narration decisions this turn (0 when none).
                # Counts the conversation's narration JSONL entries â€” read-only,
                # best-effort, never raises; a missing log file = 0.
                try:
                    from backend.agent.narration import _NARRATION_LOG_DIR
                    import os as _os

                    _npath = _os.path.join(
                        _NARRATION_LOG_DIR, f"{self.conversation_id}.jsonl"
                    )
                    if _os.path.exists(_npath):
                        with open(_npath, "r", encoding="utf-8") as _nf:
                            metrics.narration_decisions = sum(
                                1 for _l in _nf if _l.strip()
                            )
                except Exception:
                    metrics.narration_decisions = 0
                logger.info(metrics.to_log_line())
                # Log DER metrics to structured logger for verifiable backend data
                try:
                    from backend.core.logging_config import get_agent_logger

                    get_agent_logger().info(
                        "DER completed",
                        path=metrics.path,
                        der_steps=metrics.der_steps,
                        pacman_store=metrics.pacman_store,
                        pacman_recall=metrics.pacman_recall,
                        xi=metrics.xi,
                        traj_rows=metrics.traj_rows,
                        map_events=metrics.map_events,
                        ttft_ms=metrics.ttft_ms,
                        e2e_ms=metrics.e2e_ms,
                    )
                except Exception:
                    pass
                # â”€â”€ FIX (session 154): Invoke chunk_callback on DER path â”€â”€
                # The DER loop generates the full response via internal LLM
                # calls but never invokes chunk_callback. Without this call,
                # the TTS sentence_queue only receives the None sentinel,
                # the producer breaks immediately, and no audio is synthesized.
                logger.info(
                    f"[DER-TTS-FIX] chunk_callback={chunk_callback is not None}, "
                    f"der_response_len={len(_der_response) if _der_response else 0}"
                )
                if chunk_callback and _der_response:
                    self._emit_reply_progressively(
                        _der_response, task_id, chunk_callback=chunk_callback
                    )
                    logger.info("[DER-TTS-FIX] chunk_callback invoked OK")
                else:
                    logger.warning(
                        f"[DER-TTS-FIX] SKIPPED â€” chunk_callback={chunk_callback}, "
                        f"der_response={bool(_der_response)}"
                    )
                # Issue C.1: apply speak/show contract before returning.
                _der_response = self._process_structured_response(
                    _der_response, turn_id=task_id, conversation_id=_conv_id
                )
                # REQ-12 AC3 (T42): the DER path never stored the turn pair. Store
                # it here, on the same fragment lane the direct path uses.
                try:
                    from backend.agent.mcm_protocol.actions.pacman_fragment import (
                        submit_turn_pair as _submit_turn_pair,
                    )

                    _submit_turn_pair(
                        getattr(self, "_memory_interface", None),
                        session_id or self.session_id,
                        text, _der_response,
                        zone=self._pacman_zone_for_turn(),
                    )
                except Exception as _tp_err:  # noqa: BLE001 - never blocks a reply
                    logger.debug("[AgentKernel] DER turn pair store skipped: %r", _tp_err)
                try:
                    logger.info(
                        "[TURN-PATH] session=%s path=der mem_prompts=%d reply=%d",
                        session_id, int(getattr(self, "_turn_mem_prompts", 0)),
                        len(_der_response or ""),
                    )
                except Exception:  # noqa: BLE001 - observability never blocks
                    pass
                return _der_response

        # If DER produced empty/failed response, return error instead of
        # falling through to the agentic loop which would retry the API
        # call multiple times and leave the UI stuck in "thinking..." state.
        metrics.path = "der"

        # Extract the actual error from the step error format:
        # [step N error: {actual_error}]
        _der_err_text = ""
        if _der_response and "error:" in _der_response:
            # Find the error after "error:" prefix
            _err_match = _der_response.split("error:")[-1].strip().rstrip("]")
            if _err_match and _err_match != _der_response:
                _der_err_text = _err_match[:300]
        try:
            from backend.core.logging_config import get_agent_logger

            get_agent_logger().warning(
                "DER produced no response",
                error=_der_err_text or "(no error detail)",
            )
        except Exception:
            pass
        logger.warning(
            f"[AgentKernel] DER produced no response: {_der_err_text or '(empty)'}"
        )
        logger.info(metrics.to_log_line())

        # Aware empty-DER fallback (T36 finding 2026-08-09): never return a
        # blind generic error. The agent knows WHY it produced nothing, so it
        # responds usefully: surface the real error, advise the web-mode
        # toggle when the turn clearly wanted a search, or rephrase guidance.
        # Note: message text deliberately avoids the phrase "couldn't
        # generate" (test_model_routing_contract asserts it never reaches a
        # chat_message content on a healthy path).
        _fallback_msg = self._empty_der_fallback_message(
            text,
            web_on=get_global_internet_access(),
            der_err_text=_der_err_text,
        )
        if chunk_callback:
            chunk_callback(_fallback_msg)
            chunk_callback("")
        return _fallback_msg
        # Truncate to avoid leaking full traceback in chat
        if len(_der_error_detail) > 200:
            _der_error_detail = _der_error_detail[:200] + "..."
        # Log to structured logger for diagnostics
        try:
            from backend.core.logging_config import get_agent_logger

            get_agent_logger().warning(
                "DER produced no response",
                error=_der_error_detail,
                error_type=getattr(type(_der_err), "__name__", "Unknown")
                if "_der_err" in dir() and _der_err
                else "NoError",
            )
        except Exception:
            pass
        logger.warning(f"[AgentKernel] DER produced no response: {_der_error_detail}")
        logger.info(metrics.to_log_line())
        return f"IRIS couldn't generate a response. Error: {_der_error_detail}"

    def plan_task(
        self, task_description: str, context: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Use lfm2-8b (reasoning model) for task planning with timeout and error handling.

        Args:
            task_description: User's task/query
            context: Optional conversation context

        Returns:
            Plan dictionary with steps, or error dictionary

        Raises:
            TimeoutError: If inference exceeds timeout
        """
        start_time = time.time()
        # 120s: LM Studio with a 9B model can take 30-60s for first token on cold start
        timeout_seconds = 120

        try:
            logger.info("[AgentKernel] Planning task with reasoning model...")

            # Get reasoning model
            reasoning_model = None
            if self._model_router:
                try:
                    # Use user-selected reasoning model if available
                    if self._selected_reasoning_model:
                        reasoning_model = self._model_router.models.get(
                            self._selected_reasoning_model
                        )
                        if reasoning_model:
                            logger.info(
                                f"[AgentKernel] Using user-selected reasoning model: {self._selected_reasoning_model}"
                            )
                        else:
                            # Only fall back to the default local stub when neither Ollama
                            # nor VPS will handle this request.  If ":" is in the model ID
                            # it is an Ollama model (e.g. "llama3.2:3b"); if VPS is wired
                            # the VPS block below handles it.  In those cases we MUST NOT
                            # fall back â€” the stub is broken and produces garbage output.
                            _sel_check = self._selected_reasoning_model
                            _ollama_will_handle = ":" in _sel_check
                            _vps_will_handle = bool(self._vps_gateway)
                            _lmstudio_will_handle = self._is_openai_compat()
                            if (
                                not _ollama_will_handle
                                and not _vps_will_handle
                                and not _lmstudio_will_handle
                            ):
                                logger.warning(
                                    f"[AgentKernel] Selected model {_sel_check} unavailable, "
                                    "falling back to default local model"
                                )
                                reasoning_model = (
                                    self._model_router.get_reasoning_model()
                                )
                                if reasoning_model:
                                    default_model_id = getattr(
                                        reasoning_model, "model_id", "unknown"
                                    )
                                    logger.info(
                                        f"[AgentKernel] Fallback: using default reasoning model {default_model_id}"
                                    )
                            else:
                                _dest = (
                                    "LM Studio"
                                    if _lmstudio_will_handle
                                    else ("Ollama" if _ollama_will_handle else "VPS")
                                )
                                logger.info(
                                    f"[AgentKernel] Selected model '{_sel_check}' not in local cache â€” "
                                    f"will route to {_dest}"
                                )
                                # reasoning_model stays None; inference block handles it
                    else:
                        # No model selected â€” use default reasoning model
                        reasoning_model = self._model_router.get_reasoning_model()
                        if reasoning_model:
                            default_model_id = getattr(
                                reasoning_model, "model_id", "unknown"
                            )
                            logger.info(
                                f"[AgentKernel] No model selected, using default reasoning model: {default_model_id}"
                            )
                except Exception as e:
                    logger.error(f"[AgentKernel] Error getting reasoning model: {e}")
                    return {"error": f"Failed to access reasoning model: {e}"}

            # Handle model unavailability
            if not reasoning_model:
                if self._single_model_mode and self._available_model_id:
                    # Fall back to the single available local model
                    logger.warning(
                        "[AgentKernel] Reasoning model unavailable, using fallback model"
                    )
                    try:
                        reasoning_model = self._model_router.models.get(
                            self._available_model_id
                        )
                    except Exception as e:
                        logger.error(
                            f"[AgentKernel] Error accessing fallback model: {e}"
                        )
                        return {"error": f"Failed to access fallback model: {e}"}
                elif self._is_openai_compat():
                    # LM Studio is configured â€” reasoning_model stays None; the LM Studio
                    # inference block below handles it via localhost:1234.
                    logger.info(
                        "[AgentKernel] No local model loaded; delegating planning to LM Studio"
                    )
                elif self._vps_gateway:
                    # VPS Gateway is configured â€” no local model required.
                    # reasoning_model stays None; the VPS inference block below handles it.
                    logger.info(
                        "[AgentKernel] No local reasoning model; delegating planning to VPS Gateway"
                    )
                elif self._selected_reasoning_model and self._model_router:
                    # The user confirmed a model but it isn't in _model_router.models yet.
                    # Two sub-cases:
                    # A) Ollama model â€” ID contains ":" (e.g. "llama3.2:3b")
                    #    â†’ handled in the Ollama inference block below.
                    #    NOTE: provider="local" means LFM local file, NOT Ollama.
                    #    Only ":" in the ID identifies an Ollama model.
                    # B) LFM HuggingFace model (provider="local", no ":" in ID)
                    #    â†’ trigger load_models() now so the model dict is populated.
                    _sel = self._selected_reasoning_model
                    _is_ollama = ":" in _sel  # ONLY colon-format IDs go to Ollama
                    if _is_ollama:
                        logger.info(
                            f"[AgentKernel] Ollama model '{_sel}' selected; "
                            "will infer via localhost:11434"
                        )
                        # reasoning_model stays None â€” Ollama block below handles inference
                    else:
                        # LFM lazy-load path (provider="local", model file on disk)
                        logger.info(
                            f"[AgentKernel] LFM model '{_sel}' not loaded; triggering lazy load..."
                        )
                        try:
                            self._model_router.load_models()
                            reasoning_model = self._model_router.models.get(_sel)
                            if reasoning_model is None:
                                _all = list(self._model_router.models.values())
                                if _all:
                                    reasoning_model = _all[0]
                                    logger.info(
                                        "[AgentKernel] Exact model not found after lazy load; "
                                        f"using first available: {list(self._model_router.models.keys())[0]}"
                                    )
                        except Exception as _lazy_err:
                            logger.warning(
                                f"[AgentKernel] Lazy load failed: {_lazy_err}"
                            )
                        if not reasoning_model:
                            return {
                                "error": (
                                    f"Local model '{_sel}' could not be loaded. "
                                    "Check that the model file exists in the models/ directory, "
                                    "or switch to an Ollama or VPS model in Settings â†’ Configure."
                                )
                            }
                else:
                    return {
                        "error": (
                            "No inference backend configured. "
                            "Please go to Settings â†’ Configure and select a Local, VPS, or OpenAI model."
                        )
                    }

            # Build planning prompt with personality and context
            system_prompt = ""
            if self._personality:
                try:
                    system_prompt = self._personality.get_system_prompt()
                except Exception as e:
                    logger.warning(f"[AgentKernel] Error getting system prompt: {e}")

            context_str = ""
            if context:
                context_str = "\n\nConversation Context:\n" + json.dumps(
                    context[-5:], indent=2
                )

            planning_prompt = f"""{system_prompt}

You are analyzing a user request and creating an execution plan.

Task: {task_description}{context_str}

Create a structured plan with these steps:
1. Analyze what the user wants
2. Determine if tools are needed
3. Break down into actionable steps

Respond with a JSON object:
{{
    "analysis": "brief analysis of the request",
    "requires_tools": true/false,
    "steps": [
        {{
            "step": 1,
            "action": "description",
            "tool": "tool_name or null",
            "parameters": {{}}
        }}
    ]
}}"""

            # Use VPS Gateway for inference if available, otherwise use local model
            plan_response = None
            if self._vps_gateway:
                try:
                    logger.info(
                        "[AgentKernel] Using VPS Gateway for planning inference..."
                    )
                    try:
                        plan_response = asyncio.run(
                            self._vps_gateway.infer(
                                model=self._model_router.get_reasoning_model_id()
                                or "lfm2-8b",
                                prompt=planning_prompt,
                                context={"conversation_history": context}
                                if context
                                else {},
                                params={"max_tokens": 512, "temperature": 0.2},
                                session_id=self.session_id,
                            )
                        )
                        logger.info("[AgentKernel] VPS Gateway inference complete")
                    except RuntimeError as e:
                        if "already running" in str(e):
                            logger.warning(
                                "[AgentKernel] Event loop conflict â€” falling back to local model"
                            )
                            plan_response = None
                        else:
                            raise
                except TimeoutError:
                    logger.error("[AgentKernel] VPS Gateway inference timed out")
                    raise
                except Exception as e:
                    logger.warning(
                        f"[AgentKernel] VPS Gateway inference failed, falling back to direct model: {e}"
                    )
                    plan_response = None

            # LM Studio inference (OpenAI-compatible local API at localhost:1234).
            # Triggered when provider == "lmstudio" and no prior backend produced a response.
            # Uses the openai Python client pointed at the LM Studio local server.
            if plan_response is None and self._is_openai_compat():
                try:
                    _lms = self._get_lmstudio_client()
                    _lms_resp = _lms.chat.completions.create(
                        model=self._selected_reasoning_model or "local-model",
                        messages=[{"role": "user", "content": planning_prompt}],
                        max_tokens=-1,
                        temperature=0.2,  # low temp = faster, more deterministic JSON
                        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                    )
                    plan_response = _lms_resp.choices[0].message.content
                    logger.info(
                        f"[AgentKernel] LM Studio planning inference successful "
                        f"(model: {self._selected_reasoning_model}, endpoint: {self._lmstudio_endpoint})"
                    )
                except Exception as _lms_err:
                    logger.warning(
                        f"[AgentKernel] LM Studio planning inference failed: {_lms_err}"
                    )

            # Ollama local inference â€” runs when the model ID contains ":" which is
            # the Ollama format (e.g. "llama3.2:3b", "mistral:7b", "kimi-k2.5:cloud").
            # NOTE: provider="local" means LFM local file â€” it does NOT go to Ollama.
            # Only colon-format IDs are Ollama models.
            if (
                plan_response is None
                and self._selected_reasoning_model
                and (":" in self._selected_reasoning_model)
            ):
                try:
                    import requests as _req

                    _ollama_resp = _req.post(
                        "http://localhost:11434/api/chat",
                        json={
                            "model": self._selected_reasoning_model,
                            "messages": [{"role": "user", "content": planning_prompt}],
                            "stream": False,
                        },
                        timeout=60,
                    )
                    if _ollama_resp.status_code == 200:
                        plan_response = (
                            _ollama_resp.json().get("message", {}).get("content", "")
                        )
                        logger.info(
                            f"[AgentKernel] Ollama planning inference successful "
                            f"(model: {self._selected_reasoning_model})"
                        )
                    else:
                        logger.warning(
                            f"[AgentKernel] Ollama returned HTTP {_ollama_resp.status_code} "
                            f"for model '{self._selected_reasoning_model}': "
                            f"{_ollama_resp.text[:200]}"
                        )
                except Exception as _ollama_err:
                    logger.warning(
                        f"[AgentKernel] Ollama planning inference failed: {_ollama_err}"
                    )

            # Fall back to direct model access if VPS Gateway not available or failed
            if plan_response is None:
                # If there is no local model to fall back to we cannot continue.
                if reasoning_model is None:
                    # Produce a context-aware error message.
                    _sel_err = self._selected_reasoning_model or ""
                    if self._vps_gateway:
                        _err_msg = (
                            "VPS inference failed and no local model is loaded. "
                            "Check your VPS connection or configure a local model in Settings."
                        )
                    elif ":" in _sel_err:
                        _model_name = _sel_err.split(":")[0]
                        _err_msg = (
                            f"Ollama model '{_sel_err}' is not available. "
                            f"Make sure Ollama is running and the model is pulled: "
                            f"ollama pull {_model_name}"
                        )
                    elif _sel_err:
                        _err_msg = (
                            f"Model '{_sel_err}' could not be loaded. "
                            "Check that the model file exists, or select a different model in Settings â†’ Configure."
                        )
                    else:
                        _err_msg = (
                            "No inference backend configured. "
                            "Please go to Settings â†’ Configure and select a Local, VPS, or OpenAI model."
                        )
                    return {"error": _err_msg}

                # Check timeout before loading model
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    raise TimeoutError(f"Planning timed out after {elapsed:.1f}s")

                # Load model if needed with error handling
                try:
                    if not reasoning_model.is_loaded():
                        logger.info("[AgentKernel] Loading reasoning model...")
                        reasoning_model.load()
                except Exception as e:
                    logger.error(f"[AgentKernel] Failed to load reasoning model: {e}")
                    return {"error": f"Model loading failed: {e}"}

                # Check timeout before inference
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    raise TimeoutError(f"Planning timed out after {elapsed:.1f}s")

                # Generate plan with error handling
                try:
                    plan_response = reasoning_model.generate(
                        planning_prompt, max_tokens=-1, temperature=0.2
                    )
                except Exception as e:
                    logger.error(f"[AgentKernel] Model inference failed: {e}")
                    # Attempt to restart model
                    try:
                        logger.info(
                            "[AgentKernel] Attempting to restart reasoning model..."
                        )
                        reasoning_model.unload()
                        reasoning_model.load()
                        plan_response = reasoning_model.generate(
                            planning_prompt, max_tokens=-1, temperature=0.2
                        )
                        logger.info("[AgentKernel] Model restarted successfully")
                    except Exception as restart_error:
                        logger.error(
                            f"[AgentKernel] Model restart failed: {restart_error}"
                        )
                        return {
                            "error": f"Model crashed and restart failed: {restart_error}"
                        }

            # Check timeout after inference
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Planning timed out after {elapsed:.1f}s")

            # Parse JSON response
            try:
                plan = json.loads(plan_response)
                logger.info(
                    f"[AgentKernel] Plan generated with {len(plan.get('steps', []))} steps in {elapsed:.2f}s"
                )
                return plan
            except json.JSONDecodeError:
                # Model returned free-form text rather than JSON.
                # Treat the entire response as the user-facing reply â€” do NOT use
                # "respond_to_user" as the action string because execute_step would
                # return that keyword verbatim to the frontend.
                logger.warning(
                    "[AgentKernel] Failed to parse plan as JSON, using raw text as response"
                )
                _raw_text = (
                    self._strip_thinking(plan_response)
                    if plan_response
                    else "I'm not sure how to respond to that."
                )
                return {
                    "analysis": _raw_text[:200],
                    "requires_tools": False,
                    "_raw_response": _raw_text,  # consumed by _synthesize_response
                    "steps": [
                        {
                            "step": 1,
                            "action": _raw_text,  # the ACTUAL text, not a keyword
                            "tool": None,
                            "parameters": {},
                        }
                    ],
                }

        except TimeoutError:
            logger.error(f"[AgentKernel] Planning timed out after {timeout_seconds}s")
            raise
        except Exception as e:
            error_msg = f"Error during task planning: {e}"
            logger.error(f"[AgentKernel] {error_msg}", exc_info=True)
            return {"error": error_msg}

    def _der_execute_with_recovery(
        self,
        _plan,
        _context_package,
        _is_mature,
        _der_task_class,
        _session: str,
        from_voice: bool,
        _confidence,
        task_id,
        _der_budget_class: Optional[str] = None,
    ):
        """
        Run the DER plan, catching TopologyViolationException (N.4 + O.6 + RC11)
        with a targeted recovery instead of the blanket ReAct fallback.

        On a topology violation we reset the Caducean session and retry once.
        If the retry also fails, returns None so the caller falls through to
        the agentic (ReAct) loop.
        """
        from backend.agent.exceptions import TopologyViolationException

        # Phase 1 (D1.6): expose task_class so the runtime resolver
        # (explorer.propose) can apply the capability-gated web fallback.
        self._der_task_class = _der_task_class

        # REQ-19 (T20): one DerLinkWriter per DER run â€” writes structural
        # links (part_of / depends_on / relevant_to / failed_like) into the
        # SHARED mycelium link store at finalize. Wired here so it exists for
        # the whole plan; bound to this run's kernel (no cross-session shared
        # mutable state).
        try:
            from backend.agent.der_links import DerLinkWriter

            _mi = getattr(self, "_memory_interface", None)
            _myc = getattr(_mi, "_mycelium", None) if _mi is not None else None
            _store = getattr(_myc, "_store", None)
            self._der_links = DerLinkWriter(_store) if _store is not None else None
        except Exception as _dl_exc:
            logger.debug("[DER] link-writer init failed: %s", _dl_exc)
            self._der_links = None

        # Phase 2 (D2.4): unified termination resource DER_WORK_UNITS_0 derived
        # from the LIVE context window (System Invariant: work units and context
        # window are the SAME resource). Split prepays width; complete/fail/veto
        # consumes 1. This is what makes the Lyapunov potential strictly decrease.
        try:
            from backend.agent.der_constants import derive_work_units_0

            _cw = self.resolve_context_window()
            self._der_work_units = derive_work_units_0(_cw)
        except Exception as _wu_err:
            logger.warning("[DER] work_units derive failed: %s", _wu_err)
            self._der_work_units = 0
        # REQ-7: previous step's |u| magnitude, for physics-event narration
        # transition detection (oscillating -> converged). None until first step.
        self._der_last_u_mag = None

        try:
            return self._execute_plan_der(
                plan=_plan,
                context_package=_context_package,
                is_mature=_is_mature,
                task_class=_der_task_class,
                session_id=_session,
                from_voice=from_voice,
                confidence=_confidence,
                turn_id=task_id,
                budget_class=_der_budget_class,
            )
        except TopologyViolationException:
            logger.warning(
                "[AgentKernel] TopologyViolation â€” attempting targeted recovery"
            )
            try:
                # RC11 FIX: reset Caducean session state before recovery
                from backend.gateway.iris_ffi import ffi_caducean_init_session
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                from backend.agent.coupled_registry import domain_windings

                # REQ-11 AC3: re-init with the domain windings so the engine's
                # c_eff matches what the registry holds after recovery.
                _l, _m = domain_windings("voice" if from_voice else "der")
                ffi_caducean_init_session(_session, _l, _m)
                get_event_bus().emit(
                    IRISStreamEvent.MODE_CHANGED,
                    data={
                        "from_mode": "DER",
                        "to_mode": "DER_RECOVERY",
                        "reason": "Topological violation â€” recovering",
                    },
                    session_id=_session,
                )
                get_event_bus().emit(
                    IRISStreamEvent.TOPOLOGY_RECOVERY,
                    data={
                        "from_mode": "DER",
                        "to_mode": "DER_RECOVERY",
                        "reason": "Topological violation â€” recovering",
                    },
                    session_id=_session,
                )
                return self._execute_plan_der(
                    plan=_plan,
                    context_package=_context_package,
                    is_mature=_is_mature,
                    task_class=_der_task_class,
                    session_id=_session,
                    from_voice=from_voice,
                    confidence=_confidence,
                    turn_id=task_id,
                )
            except Exception as _recovery_err:
                logger.warning(
                    f"[AgentKernel] Recovery failed, falling back to ReAct: {_recovery_err}"
                )
                return None
        finally:
            # Wedge fix (session 363, pin_35af67d07c5f): the turn is over -
            # deactivate the choke check so a stale _der_start_time from this
            # finished turn can never raise on a healthy non-DER call (a
            # simple chat) that runs later. If the turn WEDGED (never
            # returned), this finally never runs and the check stays active -
            # which is the correct direction.
            self._der_turn_active = False


    def _session_has_client_for(self, session: Optional[str]) -> bool:
        """WS disconnect check for *session* - True if at least one live
        client, or on any failure (fail-open, "connected"). Wedge fix
        (session 363): extracted from the closure inside _execute_plan_der so
        _turn_choke_check (a method, which cannot see that closure) runs the
        same check inside the transport retry ladders.
        """
        try:
            from backend.ws_manager import get_websocket_manager

            ws = get_websocket_manager()
            if ws is None:
                return True  # no WS manager: non-WS path, keep running
            # Conversation / thread IDs used as kernel sessions:
            # The WS handler (iris_gateway.py:4450) passes the WS client ID
            # as session_id and the conversation/thread ID as conversation_id,
            # so thread IDs never appear as the kernel session there.
            # The REST handler (chat.py:305) uses the thread/conversation ID
            # as the kernel session_id - these sessions have no WS client and
            # must keep running (their output is returned synchronously).
            if isinstance(session, str) and (
                session.startswith("immortus:") or session.startswith("conv_")
            ):
                return True
            # The prefix list above is a NAMING check, and it silently
            # stopped matching: chat.py mints thread ids as "conv-1"
            # (hyphen) while this only ever accepted "conv_" (underscore).
            # Every REST search therefore hit the disconnect branch and the
            # DER loop broke before executing step 1 - surfacing to the user
            # as "no usable sources found", a network failure that never
            # happened. e2e was ~536 ms with no crawl in the log.
            #
            # Test the STRUCTURE instead of the spelling. chat.py:308 passes
            # session_id=thread_id=conversation_id, whereas the WS handler
            # passes the client id as session_id and the thread id as
            # conversation_id (see the comment above), so the two are equal
            # only on the REST path. That holds regardless of how ids are
            # spelled, so renaming them cannot silently re-break this.
            if isinstance(session, str) and session == getattr(
                self, "conversation_id", None
            ):
                return True
            return len(ws.get_clients_for_session(session)) > 0
        except Exception:
            return True

    def _turn_choke_check(self) -> None:
        """Wedge fix (session 363, pin_35af67d07c5f): choke-point check called
        at every model-dispatch entry (InferenceRouter.generate) and inside
        the transport retry ladders and stream chunk loops. The DER loop
        condition only evaluates BETWEEN cycles, so a turn blocked inside ONE
        operation never re-evaluated it and the 600 s budget never fired
        (chain client w1 ran 19+ min; the backend logged nothing for 18).
        Latches _der_stop_requested BEFORE raising so the loop exits to
        synthesis over completed steps even if a caller catches the error -
        the same contract the loop condition already assumes. Inert unless a
        DER turn is active (_der_turn_active), so a stale start time from a
        finished turn can never raise on a healthy non-DER call.
        """
        if not getattr(self, "_der_turn_active", False):
            return
        start = getattr(self, "_der_start_time", None)
        if start is not None and (time.perf_counter() - start) >= _DER_TURN_BUDGET_S:
            self._der_stop_requested = True
            raise RuntimeError(
                f"[DER] turn budget ({_DER_TURN_BUDGET_S:.0f}s) exhausted - "
                "aborting to synthesis over completed steps"
            )
        session = getattr(self, "_der_session", None)
        if session is None:
            return
        # The client check is throttled: the stream chunk loops call this per
        # SSE line, so the WS lookup must not run per line. Re-check at most
        # every 5 s; the budget half above is nanoseconds-cheap and always
        # runs.
        now = time.perf_counter()
        if now - getattr(self, "_der_last_client_check", 0.0) < 5.0:
            return
        self._der_last_client_check = now
        if not self._session_has_client_for(session):
            self._der_stop_requested = True
            raise RuntimeError(
                "[DER] session has no connected clients - aborting to "
                "synthesis over completed steps"
            )

    def _execute_plan_der(
        self,
        plan,
        context_package=None,
        is_mature: bool = False,
        task_class: str = "full",
        session_id: Optional[str] = None,
        from_voice: bool = False,
        confidence: float = 0.50,
        turn_id: Optional[str] = None,
        budget_class: Optional[str] = None,
    ) -> str:
        """
        DER execution cycle: Director â†’ Reviewer â†’ Explorer â†’ repeat until complete.

        The Director re-reads Mycelium each cycle via ContextPackage.
        The Reviewer gates each step (PASS / REFINE / VETO).
        The Explorer executes via _tool_bridge or direct model call.
        Mycelium signal hooks fire after every step and at outcome.

        Never raises â€” wraps failures as step error text so the response
        always reaches the user.
        """
        # Trust-routing W2: a plan run is one turn â€” start unmarked.
        self.clear_turn_trust_flag()
        # REQ-5 AC3: the amendment bound is PER TASK. _der_amendment_count lives
        # on the kernel, which is cached per CONVERSATION â€” leaving it to
        # accumulate would permanently refuse every graft after the third
        # recovery in a conversation, silently killing DER's existing recovery
        # path. One plan run is one task, so the counter resets here.
        self._der_amendment_count = 0
        # T6.4: mark the call class as USER_TURN at the real turn entry so the
        # phase gate admits it immediately (high-priority lane).
        set_call_class(CallClass.USER_TURN)
        from backend.agent.der_loop import (
            DirectorQueue,
            NodeRecord,
            QueueItem,
            Reviewer,
            ReviewVerdict,
        )
        from backend.agent.der_constants import ExecutionMode
        import uuid as _uuid

        _session = session_id or self.session_id
        # _turn_id threads the request turn id through EventBus emits and
        # escalation calls. It was previously referenced throughout this
        # method but never defined â€” that NameError broke the DER escalation
        # path and forced the "[step N completed]" fallback. See Issue E fix.
        _turn_id = turn_id
        completed_items: List[Any] = []
        step_outputs: List[str] = []
        _der_start_time = time.perf_counter()
        # Wedge fix (session 363, pin_35af67d07c5f): the turn start lives on
        # the INSTANCE too â€” _turn_choke_check is reached from the router and
        # the transports, which cannot see this local. _der_session and
        # _der_turn_active scope the check to THIS turn: without the active
        # flag a stale start time from a FINISHED turn would raise on a
        # healthy non-DER call that runs more than the budget after the turn
        # ended. _der_last_client_check throttles the WS lookup in
        # _turn_choke_check â€” the stream chunk loops call it per SSE line.
        self._der_start_time = _der_start_time
        self._der_session = _session
        self._der_turn_id = _turn_id
        self._der_turn_active = True
        self._der_last_client_check = 0.0

        # Token budget â€” spec [1.2]: enforce DER_TOKEN_BUDGETS[task_class]
        # Tokens are estimated from step result length (4 chars â‰ˆ 1 token).
        # Budget is a ceiling; the loop exits early if exceeded.
        # DER budget is derived from the MODEL'S ACTUAL CONTEXT WINDOW, not a
        # hardcoded per-mode cap. DER exists to execute tasks in alignment with
        # memory (Pacman filters tokens into the context window that then feeds
        # coordinate memory.db) â€” so each model should be allowed to use its full
        # window for reasoning across steps. The flat DER_TOKEN_BUDGETS values
        # are kept only as a SAFETY FLOOR (never go below a sane minimum), never
        # as a ceiling. No upper cap: a 256k model gets ~230k of step budget, a
        # 32k local model gets ~29k â€” each uses its real capacity.
        # Sized by the SMALLEST window among the roles this turn will actually
        # spend against â€” DER issues both reasoning calls and tool_execution
        # calls, and a Brain/Tool split can put them on very different models.
        # Using the reasoning window alone budgeted ~230k for a turn whose tool
        # steps ran on an 8k model (2026-08-16).
        _model_window = self.resolve_turn_context_window()
        # Session 247: budget sizing uses budget_class (the planner MODE name,
        # e.g. "implement") while task_class stays the classifier's label for
        # every decision. See the call site in the DER entry path.
        _token_budget: int = resolve_der_token_budget(
            _model_window, budget_class or task_class
        )
        _tokens_used: int = 0
        logger.info(
            "[DER] budget=%d from window=%d class=%s (work_units=%d)",
            _token_budget,
            _model_window,
            task_class,
            derive_work_units_0(_model_window),
        )

        # â”€â”€ REQ-1: pre-flight â€” is the reasoning provider usable? â”€â”€â”€â”€â”€â”€â”€â”€
        if not getattr(self, "_router", None):
            logger.warning("[DER] pre-flight FAILED â€” no router configured")
            return "[DER unavailable] No inference router configured"
        try:
            _hc = self._router.health_check_provider("reasoning")
        except Exception as _hc_err:
            _hc = {"ok": False, "error": str(_hc_err)[:200]}
        if not _hc.get("ok"):
            _reason = _hc.get("error", "no reason")
            logger.warning(
                "[DER] pre-flight FAILED â€” reasoning provider unavailable: %s",
                _reason,
            )
            return f"[DER unavailable] {_reason}"

        # Build Director queue from ExecutionPlan steps
        # Phase 4b: derive parallel_safe from the tool registry (authoritative
        # source of truth) so concurrency fires for read-only/independent tools
        # without trusting the LLM planner to emit the flag.
        from backend.agent.tool_registry import is_parallel_safe

        items = [
            QueueItem(
                step_id=step.step_id,
                step_number=step.step_number,
                description=step.description,
                tool=step.tool,
                params=step.params if step.params else {},
                critical=step.critical,
                depends_on=list(step.depends_on or []),
                parallel_safe=is_parallel_safe(step.tool),
                objective_anchor=plan.original_task,
                # T5 (specs/tool-result-envelope): planner-declared
                # criticality rides the queue item â€” intent only until the
                # finalize site confirms it (AC1.6).
                declared_criticality=getattr(step, "criticality", "supporting") or "supporting",
                # 2026-10-19: carry the planner's declared product onto the node.
                # It was dropped here, so every node item had expected_output=None
                # (the verifier had nothing to check; the needs_action Oracle saw
                # a goal with no artifact).
                expected_output=getattr(step, "expected_output", None) or None,
                coordinate_signal=(
                    getattr(context_package, "topology_position", "") or ""
                    if context_package
                    else ""
                ),
                # REQ-3 (T8): EVERY node carries its compressed memory record â€”
                # top-level plan steps included, not just split children. The
                # record's Understanding/Awareness/Direction fields are derived
                # from the plan step itself (the node's initial position), and
                # the finalize site stamps outcome/fraction/mediator/coords_to
                # onto it. Without this, plan steps were always memory-sparse
                # and the node record existed only for sub-loop children.
                node_record=NodeRecord(
                    step_id=step.step_id,
                    parent_step_id="",
                    node_type="step",
                    objective_anchor=plan.original_task,
                    content_summary=(step.description or "")[:300],
                    prior_summary="",  # no prior attempts on first landing
                    expected_output=step.expected_output or "",
                    remaining=step.description or "",
                    ruled_out="",
                    coordinate_ref=None,
                    coords_from="",
                    # REQ-18 (T19): both domain axes resolved at construction â€”
                    # topic from the step's own text via the mycelium registry,
                    # execution from the active winding. Registry-backed, never
                    # free text (AC2/AC3). The finalize site re-stamps with the
                    # full step result text so later steps carry the richer
                    # signal; this seed keeps the record typed even if the
                    # step never finalizes.
                    topic_domain=self._der_topic_domain(step.description or ""),
                    execution_domain=self._der_execution_domain(from_voice),
                    committed_decision=False,
                    size_bytes=len((step.description or "").encode("utf-8", "replace")),
                ),
            )
            for step in plan.steps
        ]
        queue = DirectorQueue(objective=plan.original_task, items=items)
        # Taxonomy CONTROL: the plan is accepted. Episode id = Wave E's task id.
        self._event_episode_id = f"{_session}:{_turn_id or ''}"
        _plan_rec = getattr(items[0], "node_record", None) if items else None
        _emit_event(
            self, "PLAN_MADE", thread_id=_session,
            exec_domain=getattr(_plan_rec, "execution_domain", None),
            topic_domain=getattr(_plan_rec, "topic_domain", None),
            payload={"steps": len(items), "strategy": getattr(plan, "strategy", None),
                     "task_class": task_class},
        )

        # â”€â”€ Goal contract T4 (specs/goal-contract-coverage, REQ-1) â”€â”€
        # Build the deterministic required-fact set once per turn, validate
        # the plan against it (an omission is re-added by construction â€” the
        # deterministic set stands alone â€” and logged with the fact text),
        # and stamp required_facts on every step's node record. Advisory:
        # never break plan start on a contract failure.
        self._goal_contract_state = None
        try:
            from backend.agent import goal_contract as _gc_mod

            _gc_facts = _gc_mod.extract_required(plan.original_task or "")
            _gc_omitted = _gc_mod.map_to_steps(_gc_facts, list(plan.steps))
            for _om_fact in _gc_omitted:
                logger.info(
                    "[goal-contract] planner omitted fact, re-added: %r",
                    str(_om_fact)[:160],
                )
            _gc_task_rec = NodeRecord(
                step_id=f"task:{(_turn_id or _session or 'turn')}",
                parent_step_id="",
                node_type="task",
                objective_anchor=plan.original_task or "",
                expected_output=plan.original_task or "",
                required_facts=list(_gc_facts),
                contract_version=1,
            )
            for _gc_item in items:
                try:
                    if getattr(_gc_item, "node_record", None) is not None:
                        _gc_item.node_record.required_facts = list(_gc_facts)
                except Exception:
                    pass
            self._goal_contract_state = {
                "turn_id": _turn_id,
                "contract": _gc_mod.Contract(
                    required=tuple(_gc_facts), ceiling=(), version=1
                ),
                "task_record": _gc_task_rec,
                "covered": [],
                "outcomes": [],
                "results": [],
                "C": 0.0,
                "g": 1.0,
                "prev_c": 0.0,
                "prev_tokens": 0,
                "unmoved": 0,
                "stall_cycles": 0,
                "stalled": False,
                "rho": 0.0,
                # Wave 3 (T7/T8/T9/T10): amendment log, blocked list, REQ-7
                # counters. All advisory â€” absent = legacy behavior.
                "blocked": [],
                "amendments": [],
                "counters": {
                    "facts_seeded": len(_gc_facts),
                    "facts_mapped": len(_gc_facts) - len(_gc_omitted),
                    "facts_readded": len(_gc_omitted),
                    "facts_covered": 0,
                    "facts_blocked": 0,
                    "amendments_user": 0,
                    "amendments_agent": 0,
                    "stalls": 0,
                    "bonus_passes": 0,
                },
            }
            logger.info(
                "[goal-contract] contract built: %d required facts (%d "
                "omitted by planner, re-added)",
                len(_gc_facts), len(_gc_omitted),
            )
        except Exception as _gc_exc:
            logger.debug("[goal-contract] build skipped: %s", _gc_exc)
            self._goal_contract_state = None

        # Force a real tool for web-search steps the planner left tool-less.
        # Without this, web-intent steps fall through to _run_step_direct and the
        # LLM returns empty ("[step N completed]") instead of actually searching.
        # Also catches mode names (agentic / quick / full) that the LLM planner
        # sometimes assigns instead of the actual tool name.
        # Phase 1 (D1.4): web-intent regex override DELETED. Tool selection is
        # now a single runtime authority (explorer.propose), which routes web
        # intent to crawler_query via the registry's alias + capability system
        # (capability-gated fallback for research-class goals). No routing is
        # lost â€” the registry already canonicalizes web aliases to crawler_query.

        # â”€â”€ Phase 3: initialize execution mode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Director decides mode dynamically based on task characteristics.
        # Voice no longer caps to 1 step â€” Director decides based on content.
        voice_preference = getattr(self, "_voice_preference", "auto")
        initial_mode = DirectorQueue._decide_mode(
            task_class=task_class,
            from_voice=from_voice,
            message_text=plan.original_task or "",
            token_budget_remaining=_token_budget,
            confidence=confidence,
            voice_preference=voice_preference,
        )
        queue.set_mode(initial_mode, reason=f"Task class: {task_class}")
        logger.info(
            "[DER] Mode selected: %s (voice=%s, class=%s, budget=%d)",
            initial_mode.value, from_voice, task_class, _token_budget,
        )

        # â”€â”€ Card gate (owner bound, 2026-09-25) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # A card is for MORE THAN THREE tool steps, and never for an artifact ask
        # (the artifact IS the visible result). Below the bound the turn still
        # runs through DER, the tools still fire and a real artifact still
        # renders â€” only card-lifecycle events are withheld, by the WS bridge
        # and by _persist_card_snapshot, both keyed on artifact_policy's gate.
        try:
            from backend.agent.artifact_policy import (
                MIN_TOOL_STEPS_FOR_CARD,
                card_warranted,
                clear_card_free_conversation,
                is_artifact_ask,
                suppress_card_for_conversation,
                tool_step_count,
            )

            _artifact_ask = is_artifact_ask(plan.original_task or "")
            self._current_task_text = plan.original_task or ""
            # The card bound is a personal-mode rule (see _developer_mode).
            self._der_card_hold = None
            if card_warranted(items, plan.original_task or "") or _developer_mode(self):
                # This turn may have a card â€” clear the conversation-scoped
                # marker a previous short turn left behind.
                self._suppressed_card_turn = None
                clear_card_free_conversation(self.conversation_id)
            else:
                suppress_card_for_conversation(self.conversation_id, _turn_id)
                self._suppressed_card_turn = _turn_id
                # A plan step is a NODE now (up to 12 tool calls), so a short
                # plan can still be long work: the card is released at the
                # turn's MIN_TOOL_STEPS_FOR_CARD-th real tool call
                # (_der_count_tool_call). Live 2026-10-12: 3-step plans with
                # 5 real calls (author lookup, pizza form) showed no card.
                if not _artifact_ask:
                    self._der_card_hold = {
                        "turn": _turn_id, "queue": queue, "plan": plan,
                        "session": _session, "calls": 0,
                        "lock": threading.Lock(),
                    }
                logger.info(
                    "[AgentKernel] task card suppressed: tool_steps=%d (bound "
                    ">=%d) artifact_ask=%s turn=%s â€” the turn runs, the artifact "
                    "still renders",
                    tool_step_count(items),
                    MIN_TOOL_STEPS_FOR_CARD,
                    _artifact_ask,
                    _turn_id,
                )
        except Exception as _gate_exc:  # never block the turn on the gate
            logger.debug("[AgentKernel] card gate skipped: %s", _gate_exc)

        # â”€â”€ EventBus: emit task:start â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            bus = get_event_bus()
            _card_task_id = _turn_id or plan.original_task[:40]
            _card_id, _card_relation = self._resolve_card_identity(
                _card_task_id, "initial"
            )
            # T16 (REQ-12 AC4): card-lifecycle observability â€” relation decision
            # is logged here, off the inference hot path (this block only emits
            # an event; a log line can never block the user response).
            logger.info(
                "[AgentKernel] CARD_LIFECYCLE relation=%s card_id=%s task_id=%s conv=%s turn=%s",
                _card_relation, _card_id, _card_task_id, self.conversation_id, _turn_id,
            )
            _start_steps = [
                {
                    "id": it.step_id,
                    "description": it.description,
                    "status": "pending",
                    # Session 247: semantic order for the frontend row sort.
                    "stepNumber": it.step_number,
                    "toolName": _step_tool(it),
                }
                for it in items
            ]
            bus.emit(
                IRISStreamEvent.TASK_START,
                data=self._task_start_payload(
                    task_id=_card_task_id,
                    description=plan.original_task[:200],
                    plan_title=self._effective_plan_title(plan),
                    mode=initial_mode.value,
                    steps=_start_steps,
                    total_steps=len(items),
                    # REQ-14 (T23): execution-start announcement â€” still the
                    # INITIAL plan; revisions re-emit with a distinct origin.
                    origin="initial",
                    # REQ-3 (T2): backend-declared card identity.
                    card_id=_card_id,
                    card_relation=_card_relation,
                    conversation_id=self.conversation_id,
                        turn_id=getattr(self, "_current_turn_id", None),
                    **self._multiagent_tags(),
                ),
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
            # T4a (REQ-4 AC1): persist the card at task:start.
            self._persist_card_snapshot(
                card_id=_card_id,
                conversation_id=self.conversation_id,
                card_relation=_card_relation,
                plan_title=self._effective_plan_title(plan),
                mode=initial_mode.value,
                steps=_start_steps,
                total_steps=len(items),
                terminal_state="running",
            )
        except Exception:
            pass  # EventBus is optional â€” no crash if it fails

        # C.1 LiveContextPackage â€” refreshes ContextPackage mid-loop so the
        # Director always reads current gradient_warnings + tier2_predictions.
        try:
            from backend.memory.live_context import LiveContextPackage

            _live_ctx = LiveContextPackage(
                initial_package=context_package,
                memory_interface=self._memory_interface,
                session_id=_session,
            )
        except Exception:
            _live_ctx = None  # graceful no-op if import fails

        # Reviewer â€” falls back to PASS on any failure (membrane, not gate)
        reviewer = self._reviewer

        # WS disconnect helper - checks if the originating session still has
        # at least one live client. Never raises; defaults to "connected".
        # Wedge fix (session 363): the body moved to _session_has_client_for
        # so _turn_choke_check - a METHOD, which cannot see this closure -
        # runs the same check inside the transport retry ladders. This
        # delegate keeps the loop call site unchanged.
        def _session_has_client() -> bool:
            return self._session_has_client_for(_session)

        # â”€â”€ REQ-15 (T25/T26): per-task steering state reset â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        self._der_stop_requested = False
        self._der_pause_requested = False
        self._der_resume_requested = False

        # dev-cli-ide REQ-25 edge case: the inbox outlives the loop that reads
        # it. Records are drained ONLY inside this loop, so anything queued
        # while no DER task was running would be applied to the NEXT task --
        # a steer aimed at one job silently revising another. Nothing sent to
        # the channel before REQ-25, so this was latent; the UI sender makes it
        # reachable. Drop pre-task records here and acknowledge them, rather
        # than letting them leak forward.
        try:
            from backend.agent.steering import get_steering_inbox as _gsi

            _stale = _gsi().drain(_session)
            for _rec in _stale:
                self._emit_steering_ack(
                    _rec.channel, _rec.message_id, "considered", _session
                )
            if _stale:
                logger.info(
                    "[AgentKernel][%s] dropped %d steering record(s) queued "
                    "before this task started", _session, len(_stale),
                )
        except Exception as _st_exc:
            logger.debug("[AgentKernel] stale-steering sweep skipped: %s", _st_exc)

        # â”€â”€ Parallel nodes (owner 2026-10-04): ONE scheduler for every node -
        # plan steps, split children, grafts, batch children. The DAG decides
        # WHAT is ready (depends_on); the "execution.der_nodes" phase domain
        # decides WHEN a ready node starts; the node's work runs on its own
        # thread while the bookkeeping before and after it stays on this
        # thread, in order. Independent nodes overlap; a dependent node is
        # never ready before its dependencies complete.
        import queue as _queue_mod

        _inflight: Dict[str, dict] = {}
        _finished = _queue_mod.Queue()
        # Bound before the loop: a turn whose loop exits before its first pass
        # (a stop latched at the first boundary, a budget already spent) reached
        # the grading line with `item` unassigned - UnboundLocalError, and the
        # reply became "[IRIS error: cannot access local variable 'item' ...]"
        # (live 2026-10-06, a strand turn). The grading line handles None.
        item = None

        while (
            not queue.is_complete()
            and not queue.hit_cycle_limit()
            and _tokens_used < _token_budget
            # Session 247: TURN WALL-CLOCK â€” the last-resort safety net. The
            # sufficiency gate and zero-yield cutoff stop the *rational*
            # churn; this bounds the total so no future bug can ever again
            # hold a turn open for 30+ minutes (conv-41 ran 18 dispatch
            # rounds unbounded). Generous by design: 10 min of wall time is
            # far beyond any healthy websearch turn, so this only fires on
            # genuine pathology. When it trips, the loop exits to synthesis
            # over completed steps â€” partial results reach the user.
            and (time.perf_counter() - _der_start_time) < _DER_TURN_BUDGET_S
            # REQ-15 AC3: an explicit stop aborts at the next step boundary.
            and not self._der_stop_requested
        ):
            # â”€â”€ DISCONNECT CHECK: stop early if client is gone â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if not _session_has_client():
                logger.info(
                    f"[DER] Session {_session} has no connected clients â€” "
                    "recording partial outcome and stopping"
                )
                break

            # â”€â”€ DOMAIN 19: Caducean phase read â”€â”€
            import math as _math

            _xi = 0.0
            try:
                from backend.gateway.iris_ffi import ffi_caducean_get_xi

                _xi = ffi_caducean_get_xi(_session)
            except Exception as _ffi_exc:
                loud_error(_ffi_exc, "ffi_caducean_get_xi")
            _phase = 0  # 0=[0,Ï€/2], 1=[Ï€/2,Ï€], 2=[Ï€,3Ï€/2], 3=[3Ï€/2,2Ï€]
            if _xi >= 3.0 * _math.pi / 2.0:
                _phase = 3
            elif _xi >= _math.pi:
                _phase = 2
            elif _xi >= _math.pi / 2.0:
                _phase = 1

            # â”€â”€ Parallel nodes: settle a finished node first (in finish order,
            # on this thread), else start the next ready one; with nothing to
            # start, wait for a node in flight to finish. â”€â”€
            _fin = _der_take_finished(self, _finished, _inflight, block=False)
            if _fin is None:
                # IRIS_DER_PARALLEL=0: one node at a time (the off switch and
                # the A/B baseline); default on.
                item = (None if (_inflight and not _DER_PARALLEL)
                        else queue.next_ready(_session, exclude=_inflight))
                if item is None:
                    if not _inflight:
                        break  # dependency deadlock guard
                    # Wait in short slices: a stop, a disconnect or the turn
                    # budget is seen at the loop top, not after a slow node.
                    _fin = _der_take_finished(
                        self, _finished, _inflight, block=True, timeout=0.5,
                    )
                    if _fin is None:
                        continue
            if _fin is not None:
                _tokens_used = _der_post_step(self, 
                    *_fin, queue=queue, plan=plan, _session=_session, _turn_id=_turn_id,
                    context_package=context_package, completed_items=completed_items,
                    step_outputs=step_outputs, _tokens_used=_tokens_used,
                    _token_budget=_token_budget, is_mature=is_mature, _live_ctx=_live_ctx,
                    from_voice=from_voice, inflight=_inflight,
                )
                continue
            queue.cycle_count += 1
            verdict = None

            # â”€â”€ REQ-15 (T25/T26): consume mid-task steering at the NEXT step
            # boundary (AC1 â€” never mid-step). A steering revision replaces
            # the remaining plan (AC2); a stop aborts here (AC3); a pause
            # suspends here until resume/stop (AC4). budget_deadline bounds
            # the re-plan's LLM call by the turn budget (pin_ced7b0dc3b8f).
            # Before it: a landed TOPO_VIOLATION halts the loop into
            # _der_execute_with_recovery (never waits on the physics lane).
            _der_topology_halt(self, _session)
            _steer = self._der_check_steering(
                _session, plan, queue,
                budget_deadline=_der_start_time + _DER_TURN_BUDGET_S,
            )
            if _steer:
                if _steer.get("stop"):
                    break
                if _steer.get("revised"):
                    # The pulled item belongs to the dropped plan â€” re-pull
                    # from the revised queue on the next iteration. Nodes of
                    # the dropped plan still in flight stop at their next call.
                    for _rec in _inflight.values():
                        _rec["item"]._node_cancelled = "plan revised"
                    continue
                if _steer.get("pause"):
                    _suspend = self._der_suspend_task(
                        _session, plan, queue, _turn_id
                    )
                    if _suspend == "stop":
                        break
                    # resumed: the pulled item was never executed â€” re-pull
                    # it from the (unchanged) queue.
                    continue

            # â”€â”€ C.1 LIVE CONTEXT REFRESH â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Re-read Mycelium coordinate signals for the current sub-step.
            # Updates gradient_warnings + tier2_predictions on context_package.
            # < 50ms SLA; silently no-ops on any error.
            if _live_ctx is not None:
                _live_ctx.refresh(item, completed_items)
                context_package = _live_ctx.package  # always valid

            # â”€â”€ C.4 MID-LOOP EPISODIC RETRIEVAL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Query the episodic store for the *current sub-task*, not the
            # parent task.  Injects a hint into item.coordinate_signal so the
            # Reviewer and Explorer both see "I solved this sub-problem before
            # this way".  <50ms: uses cached embeddings after first query.
            try:
                if self._memory_interface and item.description:
                    _retrieval_limit = 2
                    _retrieval_score = 0.55
                    try:
                        from backend.agent.caducean_trajectory import (
                            CaduceanTrajectoryRecorder,
                        )
                        # REQ-16: read per-session cached (eml, x, y) triple
                        _triple = CaduceanTrajectoryRecorder.get_cached_eml(
                            _session
                        )
                        if isinstance(_triple, tuple):
                            _cached_eml = float(
                                _triple[0] if _triple[0] is not None else 1.0
                            )
                            _cached_x = float(_triple[1]) if _triple[1] else 0.0
                            _cached_y = float(_triple[2]) if _triple[2] else 0.0
                        elif isinstance(_triple, (int, float)):
                            _cached_eml = float(_triple)
                            _cached_x = _cached_y = 0.0
                        else:
                            _cached_eml, _cached_x, _cached_y = 1.0, 0.0, 0.0

                        # REQ-17: V-shaped explore pressure, AC1: x/y directional term.
                        # Three anchors (AC3):
                        #   consolidate (eml=0.90, x-dominant): limit=3,  score=0.65
                        #   neutral     (eml=1.20):              limit=2,  score=0.55
                        #   explore     (eml=1.60, y-dominant):  limit=5,  score=0.40
                        _EC, _EN, _EE = 0.90, 1.20, 1.60
                        _LC, _LN, _LE = 3, 2, 5
                        _SC, _SN, _SE = 0.65, 0.55, 0.40
                        _e = max(0.0, _cached_eml)
                        _norm = (_cached_x**2 + _cached_y**2) ** 0.5
                        _dir = _cached_y / _norm if _norm > 1e-9 else 0.0
                        if _e <= _EN:
                            _p = max(0.0, min(1.0, (_e - _EC) / (_EN - _EC)))
                            _retrieval_limit = _LC + (_LN - _LC) * _p
                            _retrieval_score = _SC + (_SN - _SC) * _p
                            _bias = min(1.0, abs(_dir))
                            if _dir < 0:  # consolidate-dominant
                                _retrieval_limit += _bias * (_LC - _retrieval_limit)
                                _retrieval_score += _bias * (_SC - _retrieval_score)
                            elif _dir > 0:  # explore-dominant at low EML
                                _retrieval_limit += _bias * (_LE - _retrieval_limit)
                                _retrieval_score += _bias * (_SE - _retrieval_score)
                        else:
                            _p = max(0.0, min(1.0, (_e - _EN) / (_EE - _EN)))
                            _retrieval_limit = _LN + (_LE - _LN) * _p
                            _retrieval_score = _SN + (_SE - _SN) * _p
                            _bias = min(1.0, abs(_dir))
                            if _dir > 0:  # explore-dominant
                                _retrieval_limit += _bias * (_LE - _retrieval_limit)
                                _retrieval_score += _bias * (_SE - _retrieval_score)
                            elif _dir < 0:  # consolidate-dominant at high EML
                                _retrieval_limit += _bias * (_LC - _retrieval_limit)
                                _retrieval_score += _bias * (_SC - _retrieval_score)
                        _retrieval_limit = max(2, min(5, int(round(_retrieval_limit))))
                        _retrieval_score = max(0.40, min(0.65, _retrieval_score))
                    except Exception as _eml_exc:
                        loud_error(_eml_exc, "caducean_eml_retrieval")
                    _sub_eps = self._memory_interface.episodic.retrieve_similar(
                        task=item.description,
                        limit=_retrieval_limit,
                        min_score=_retrieval_score,
                    )
                    if _sub_eps:
                        _hint_parts = []
                        for ep in _sub_eps:
                            _ts = ep.get("task_summary", "")[:80]
                            if _ts:
                                _hint_parts.append(_ts)
                            # A2 FIX: surface the proven tool_sequence, not just
                            # the summary, so the Explorer repeats a known-good path.
                            _seq = ep.get("tool_sequence", [])
                            if _seq:
                                _approach = " â†’ ".join(
                                    s.get("tool", "?") for s in _seq[:5]
                                )
                                _hint_parts.append(f"PROVEN APPROACH: {_approach}")
                        _hints = "; ".join(_hint_parts)
                        if _hints:
                            _prior = getattr(item, "coordinate_signal", "") or ""
                            item.coordinate_signal = (
                                _prior + f"\nSUB-TASK HINT: {_hints}"
                            ).strip()
                    # â”€â”€ REQ-20 AC3 (T21): the filtered ontology neighborhood
                    # is a first-class step input. Query the DER chain with
                    # THIS node's type + both domain axes and surface the
                    # relevant neighbor records into the step context â€” the
                    # relevant neighborhood, not the whole graph. Zero-hit
                    # widens (relationship -> type -> domain, logged) and
                    # falls back to the live-state-only step (never an error).
                    try:
                        # K2: only rows that passed the relevance gate reach
                        # here; no row -> no block (nothing injected).
                        _nb_rows = self._der_recall_neighborhood(item, _session)
                        _nb_block = _der_neighbors_block(_nb_rows)
                        if _nb_block:
                            _prior = getattr(item, "coordinate_signal", "") or ""
                            item.coordinate_signal = (
                                _prior + "\nRELEVANT NEIGHBORS: " + _nb_block
                            ).strip()
                            _der_recall_delivered(
                                self, item, "neighbors",
                                [r.get("chain_id") for r in _nb_rows[:3]], _session,
                            )
                    except Exception as _nb_exc:
                        loud_error(_nb_exc, "ontology_recall_neighborhood")

                    # REQ-12 AC3 (T48, 2026-10-29): the step's own CHUNK memory.
                    # The neighborhood above is chain rows typed by node_type +
                    # domain, and an episode is not a fact: neither carries a
                    # taught USER statement. That lives in a context_fragment
                    # chunk (the turn pair), so the step that must answer recalls
                    # it HERE, on the node that needs it - not in the planner.
                    # Bounded to 3 x 300 chars, trusted only, cross-conversation.
                    try:
                        _ep_store = getattr(self._memory_interface, "episodic", None)
                        _step_goal = getattr(item, "description", "") or ""
                        if _ep_store is not None and _step_goal:
                            _ch_rows = _ep_store.retrieve_context_chunks(
                                _step_goal,
                                session_id=None,
                                limit=3,
                                min_similarity=0.35,
                                chunk_types=["context_fragment"],
                                zones=["trusted"],
                                with_meta=True,
                            ) or []
                            # REQ-12 AC2 (T48): `trusted` only means "not outside
                            # content". Each row carries its PRODUCER, so the step
                            # can weigh the user's statement above this agent's
                            # own earlier answer instead of treating them alike.
                            _LABELS = {
                                "user_statement": "the user stated",
                                "agent_step": "your earlier answer",
                            }
                            _ch_rows = sorted(
                                _ch_rows,
                                key=lambda r: 0 if r.get("producer") == "user_statement" else 1,
                            )
                            _ch_txt = "\n- ".join(
                                "[{}] {}".format(
                                    _LABELS.get(
                                        r.get("producer"),
                                        str(r.get("producer") or "memory").replace("tool:", "tool "),
                                    ),
                                    str(r.get("content") or "").strip()[:300].replace("\n", " "),
                                )
                                for r in _ch_rows if str(r.get("content") or "").strip()
                            )
                            if _ch_txt:
                                _prior_ch = getattr(item, "coordinate_signal", "") or ""
                                item.coordinate_signal = (
                                    _prior_ch + "\nRELEVANT MEMORY:\n- " + _ch_txt
                                ).strip()
                    except Exception as _ch_exc:
                        loud_error(_ch_exc, "step_chunk_recall")

                    # â”€â”€ REQ-3 T8 AC1/AC3: the node's compressed memory record is
                    # a FIRST-CLASS step input (not opt-in). If this item carries
                    # a NodeRecord (every node does from split/creation on), its
                    # Understanding/Awareness/Direction + the compressed Î£
                    # position are injected into the step input alongside the
                    # episodic hints. When the store has no record for the
                    # node's coordinate, the step proceeds on the live state
                    # alone and is marked memory-sparse in the observability log
                    # (AC3) â€” never an error.
                    try:
                        _rec = getattr(item, "node_record", None) or getattr(
                            item, "footprint", None
                        )
                        # REQ-6 AC1 (T18): OBSERVE which signal governed this
                        # step's steering â€” past-memory (compressed node
                        # record present) vs live-state (memory-sparse: no
                        # record, the decision runs on the live Î£ alone). A
                        # record present AND live Î£ consumed is the "both"
                        # (equal-signals) edge. No hardcoded authority (AC2).
                        try:
                            self._der_record_governance(
                                "both" if _rec is not None else "live"
                            )
                        except Exception:
                            pass
                        if _rec is not None:
                            _rec_parts = []
                            if getattr(_rec, "prior_summary", ""):
                                _rec_parts.append(
                                    # 300 as before; 1600 only for a replan-
                                    # after-failure child whose summary carries
                                    # the bounded case trail (<= 400, D9) and
                                    # chain block (<= 900, K3) - no other node
                                    # grows (owner: no context debt).
                                    "UNDERSTANDING: " + _rec.prior_summary[
                                        :1600 if (
                                            "CHAIN TIMELINE" in _rec.prior_summary
                                            or "MEDIATORS TRIED" in _rec.prior_summary
                                            or "KNOWN CASE" in _rec.prior_summary
                                        ) else 300
                                    ]
                                )
                            if getattr(_rec, "ruled_out", ""):
                                _rec_parts.append(f"RULED OUT: {_rec.ruled_out[:200]}")
                            if getattr(_rec, "expected_output", ""):
                                _rec_parts.append(
                                    f"EXPECTED: {_rec.expected_output[:200]}"
                                )
                            if getattr(_rec, "coords_from", ""):
                                _rec_parts.append(f"BRANCH COORDS: {_rec.coords_from}")
                            # REQ-4 AC4 (T16b): the fold-back observations from
                            # this node's sub-loop children are first-class
                            # step context (REQ-3 AC1) â€” the parent's next
                            # decision reads what the children resolved.
                            if getattr(_rec, "folded_back", None):
                                _rec_parts.append(
                                    "FOLDED-BACK: " + "; ".join(_rec.folded_back[-3:])
                                )
                            if _rec_parts:
                                _prior = getattr(item, "coordinate_signal", "") or ""
                                item.coordinate_signal = (
                                    _prior + "\nNODE RECORD: " + "; ".join(_rec_parts)
                                ).strip()

                            # â”€â”€ REQ-5 AC1/AC3 (T17): SURFACE the branch
                            # candidates to the deciding step. Retrieval ranks
                            # the relevant branches (physics + evidence) and
                            # puts ALL of them in front of the step â€” never
                            # pre-selecting one by score. The step decides with
                            # both branches in view; the chosen one is recorded
                            # at commit (_der_record_coupling_decision).
                            try:
                                _cands = self._der_surface_branch_candidates(item)
                                if _cands:
                                    _cand_parts = [
                                        f"{i+1}. {c.get('label','')}"
                                        for i, c in enumerate(_cands)
                                    ]
                                    _prior = (
                                        getattr(item, "coordinate_signal", "") or ""
                                    )
                                    item.coordinate_signal = (
                                        _prior
                                        + "\nBRANCH CANDIDATES: "
                                        + " | ".join(_cand_parts)
                                    ).strip()
                                    # remember for the commit-time decision
                                    # record (AC2/AC4) â€” bounded provenance.
                                    try:
                                        item._coupled_candidates = list(_cands)
                                    except Exception:
                                        pass
                            except Exception as _surf_exc:
                                logger.debug(
                                    "[DER] branch surfacing failed: %s", _surf_exc
                                )

                            # â”€â”€ REQ-3 T8b AC4/AC5/AC6: wire the FORGETTING. The
                            # step's working context (coordinate_signal) is bounded
                            # to a fraction of the REQ-1 resolved window (OQ-6:
                            # derived, never a literal) â€” content beyond the bound is
                            # DROPPED from the working context and re-read later
                            # only when retrieval selects the node record. The
                            # per-step prompt token count is recorded so the
                            # reduction is a measured number (AC5). AC6: if the
                            # node's chain write FAILED (durability drop counter),
                            # the working context is the ONLY copy â€” do NOT bound
                            # (forget) it. Extracted to _der_bound_step_context so
                            # the contract test drives the REAL code (T8b).
                            self._der_bound_step_context(item)
                        else:
                            # AC3: memory-sparse â€” no record, proceed on live state.
                            logger.info(
                                "[DER] step memory-sparse step_id=%s (no node record "
                                "for this coordinate) â€” proceeding on live state",
                                getattr(item, "step_id", "?"),
                            )
                    except Exception as _rec_exc:
                        loud_error(_rec_exc, "node_record_step_input")
            except Exception as _explore_exc:
                loud_error(_explore_exc, "explorer_sub_episodes")

            # â”€â”€ REVIEWER PHASE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if reviewer is not None:
                # Bind the step id into the measurement scope from here on
                # (first added for review_verdict, retired 2026-11-10; the bind
                # stays because every later row of this step reads its step_id
                # from the scope). Measured live: 2877 of 2877 rows carried an
                # EMPTY step_id - the loop binds turn_id at turn entry but never
                # the step. scope_now() reads these as VALUES at row-build time,
                # so a lane thread still gets them. try/except: measurement must
                # never block a review.
                try:
                    from backend.agent import decision_engine as _de

                    _de.set_scope(
                        step_id=getattr(item, "step_id", None) or None,
                    )
                except Exception:  # noqa: BLE001 â€” measurement never blocks
                    logger.debug("[DER] review scope bind failed")
                try:
                    verdict, feedback = reviewer.review(
                        item=item,
                        completed_steps=completed_items,
                        context_package=context_package,
                        is_mature=is_mature,
                    )
                except Exception:
                    verdict, feedback = ReviewVerdict.PASS, None

                if verdict == ReviewVerdict.VETO:
                    item.veto_count += 1
                    # the next attempt's node sees why (2026-10-02 audit)
                    item.review_feedback = str(feedback or "")[:300]
                    logger.info(
                        f"[DER] Step {item.step_number} VETOED "
                        f"(count={item.veto_count}, reason={feedback})"
                    )
                    # DER Phase 0 (D0.2): a VETO means the action was NEVER executed.
                    # Do NOT emit a tool-outcome record (that would be a lie â€” a
                    # success=False edge for a tool that never ran). The veto decision is
                    # logged for audit only; it is not a tool outcome.
                    logger.debug(
                        f"[DER] veto audit: step {item.step_number} not executed "
                        f"(reason={feedback})"
                    )

                    if item.veto_count <= queue.max_veto_per_item:
                        # Keep in queue for Director to reroute next cycle
                        continue
                    else:
                        queue.mark_vetoed(item.step_id)
                        # â”€â”€ REQ-8 AC3: emit learning signal for avoided step â”€â”€
                        try:
                            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                            get_event_bus().emit(
                                IRISStreamEvent.TASK_LEARNING,
                                data={
                                    "signal": "avoided",
                                    "step_number": item.step_number,
                                    "step_id": item.step_id,
                                    "session_id": _session,
                                },
                            )
                        except Exception:
                            pass
                        continue

                if verdict == ReviewVerdict.REFINE and feedback:
                    item.refined_description = feedback
                    item.description = feedback
                    logger.info(f"[DER] Step {item.step_number} REFINED")
                    # Session-321 (Reviewer claim-coverage): a REFINE whose
                    # text steers to read/compose sets the read tool
                    # directly â€” the same reroute shape the T6B guard uses.
                    # Clearing the tool and hoping the resolver picks read
                    # is words-only; an explicit tool set is enforcement.
                    # get_rendered_documents is idempotent and side-effect
                    # free, so it cannot recrawl by construction.
                    _fb = str(feedback or "").lower()
                    if "do not dispatch another crawl" in _fb or (
                        "read the gathered" in _fb
                        and (item.tool or "") in ("crawler_query", "web_search",
                                                  "search", "search_discovery")
                    ):
                        item.tool = "get_rendered_documents"
                        item.params = {
                            "conversation_id": self.conversation_id or "",
                        }
                        logger.info(
                            f"[DER] Step {item.step_number} rerouted by "
                            f"Reviewer REFINE to get_rendered_documents",
                        )

            # â”€â”€ EXPLORER PHASE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Emit TOOL_CALL event for the frontend / TaskKernel
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                _lifecycle_task_id = _turn_id or item.step_id
                get_event_bus().emit(
                    IRISStreamEvent.TOOL_CALL,
                    data={
                        "task_id": _lifecycle_task_id,
                        "tool_name": item.tool or "direct",
                        "description": item.description[:200],
                        "params": item.params,
                        "step_number": item.step_number,
                        # REQ-3 AC6 (T2): card_id stays stable across every
                        # event of a card's lifetime, not just task:start.
                        **self._card_envelope(_lifecycle_task_id),
                    },
                    turn_id=_turn_id,
                    conversation_id=self.conversation_id,
                )
            except Exception:
                pass
            # T13 (REQ-10 AC10.11): the tool started â€” open its narratable
            # wait (entry line only for known-long waits; miss fires from
            # the scheduler worker if the stated budget is crossed).
            try:
                self._note_tool_wait(
                    tool_name=item.tool or "direct",
                    wait_id=_lifecycle_task_id,
                    turn_id=_turn_id,
                    session_id=_session,
                )
            except Exception:
                pass

            # â”€â”€ RC1 FIX: pre-execution validation (catches tool:null / missing
            # params before runtime). Invalid steps route to graft with the
            # REQ-6 (soft-cancel): if the user switched away from this conversation,
            # stop issuing further steps. An in-flight tool subprocess is allowed to
            # finish once (SOFT cancel) but no subsequent step or recovery narrative
            # is produced for this thread. We check here, at the top of each item
            # iteration, so the loop exits cleanly without emitting further events.
            if self._cancel_requested.is_set():
                self._logger.info(
                    f"[DER] Cancel requested for conversation {self.conversation_id}; "
                    f"halting DER loop after current step."
                )
                break

            # validation error instead of executing-and-failing. â”€â”€
            if item.tool:
                from backend.agent.tool_registry import validate_tool_call
                _valid, _val_err = validate_tool_call(item.tool, item.params or {})
                if not _valid:
                    item.result = f"[VALIDATION] {_val_err}"
                    try:
                        from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                        get_event_bus().emit(
                            IRISStreamEvent.VALIDATION_FAILED,
                            data={
                                "tool_name": item.tool,
                                "error": _val_err,
                                "step_id": item.step_id,
                                "step_number": item.step_number,
                            },
                            session_id=_session,
                            turn_id=_turn_id,
                        )
                    except Exception:
                        pass
                    self._der_handle_step_failure(
                        item, queue, plan, _session, _turn_id, context_package
                    )
                    continue

            # â”€â”€ EXPLORER PHASE: execute primary step with resilience (Phase 1.1) â”€â”€
            # retry_with_backoff_sync retries transient errors (ConnectionError /
            # TimeoutError / OSError) with exponential backoff and fails fast on
            # permanent errors (ValueError / PermissionError / etc). _der_run_step
            # returns (result, success) rather than raising, so _run_step re-raises
            # a classified exception to drive the retry decision. The sync twin is
            # used because _der_run_step_execution calls asyncio.run() internally â€”
            # nesting asyncio.run would raise RuntimeError in the executor thread.
            from backend.agent.resilience import retry_with_backoff_sync

            def _run_step(item=item):
                _res, _ok = self._der_run_step_execution(
                    item, context_package, _session, _turn_id, plan, queue=queue
                )
                if _ok:
                    return _res, _ok
                # RateLimitedError is raised (not returned) by
                # _der_run_step_execution when the transport exhausted its own
                # 429 retries. It must NOT be retried at the DER layer (REQ-4
                # AC1) â€” re-raise so retry_with_backoff_sync's NO_RETRY_ERRORS
                # check surfaces it immediately.
                if isinstance(_res, RateLimitedError):
                    raise _res
                _err = _res or ""
                if AgentKernel._der_step_error_is_retryable(_err):
                    raise ConnectionError(_err)  # transient -> retry
                raise ValueError(_err)  # permanent -> fail fast

            # â”€â”€ Parallel nodes (owner 2026-10-04): the node's work runs on its
            # own thread (it always did - a bounded daemon thread, session 269);
            # the loop no longer joins it here but goes on to the next ready
            # node. _der_post_step settles each node when it finishes. â”€â”€
            _der_start_node(self, item, _run_step, _inflight, _finished,
                                 verdict=verdict, phase=_phase)
            continue

        # Nodes still in flight when the loop ended (budget, stop, cancel,
        # disconnect, cycle limit) stop at their next call; their late results
        # are dropped and they are recorded as not finished (the old bounded
        # join failed the step on the budget the same way).
        for _sid, _rec in list(_inflight.items()):
            _rec["item"]._node_cancelled = "turn ended"
            _rec["item"].result = "[STEP TIMEOUT: the turn ended before this node finished]"
            queue.mark_failed(_sid)
            logger.warning("[DER] node %s still running at the turn end - stopped, not settled", _sid)
        _inflight.clear()

        # Taxonomy CONTROL: a budget (tokens, turn time, steps) cut the loop short.
        _budget_kind = _der_budget_exit(
            _tokens_used, _token_budget, time.perf_counter() - _der_start_time,
            _DER_TURN_BUDGET_S, queue,
        )
        if _budget_kind:
            _emit_event(
                self, "BUDGET_HIT", evidence="verifier", thread_id=_session,
                trigger="budget_exceeded",  # nodes/outcome.Reason.BUDGET_EXCEEDED
                cost={"ms": int((time.perf_counter() - _der_start_time) * 1000)},
                payload={"budget": _budget_kind, "tokens_used": int(_tokens_used),
                         "token_budget": int(_token_budget),
                         "steps_done": len(completed_items)},
            )

        # â”€â”€ OUTCOME RECORDING (ordered per spec: clear â†’ stats â†’ episode)
        # NOTE: _store_task_episode internally calls mycelium_record_outcome
        # and mycelium_crystallize_landmark, so we do NOT duplicate them here.
        # DER Phase 0 (D0.6): coarsen outcome from verified_fraction, not a binary
        # "[STEP ERROR" substring. hit (>=0.8) / partial (0.3-0.8) / miss (<0.3).
        _joined = "\n".join(step_outputs)
        # The loop variable `item` is whatever the LAST pass set - after a
        # re-plan it can be None (live 2026-10-02 run A6: the reply became
        # "[IRIS error: 'NoneType' object has no attribute 'expected_output']").
        # Grade against the last step that completed.
        _last_item = completed_items[-1] if completed_items else item
        _frac = (
            self._verified_fraction(getattr(_last_item, "expected_output", "") or "", _joined)
            if step_outputs else 0.0
        )
        # Session-326: verdict from the FINAL ANSWER, not step colors. A
        # failed step used to force "failure" even when the answer carried
        # verified content (7-min stall: partial answer, red-X card).
        # success = clean run plus verified answer; partial = the answer
        # carries verified content despite failed steps; failure = nothing
        # verified. failed_steps still ride the terminal event, so per-step
        # honesty never moves â€” only the run verdict does.
        if _frac >= 0.8 and not queue.failed_ids:
            outcome = "success"
        elif _frac >= 0.3:
            outcome = "partial"
        else:
            outcome = "failure"

        # â”€â”€ REQ-15 AC3 (T25): an explicit stop persists the lifecycle as
        # `cancelled` (REQ-9 LIFECYCLE_CANCELLED) and reports honestly â€”
        # never a fabricated success or failure.
        if getattr(self, "_der_stop_requested", False):
            outcome = "cancelled"

        # â”€â”€ T6 (REQ-5 / D8): task lifecycle reaches its terminal state HERE,
        # derived from the same honest queue state as the outcome label, and is
        # persisted BEFORE the terminal task:done/task:fail event. completed /
        # partial / failed are decided by execution state (queue terminals +
        # verified fraction), never by physics convergence. A persistence
        # failure is exposed honestly and does not silently claim durable
        # completion.
        try:
            from backend.agent.der_execution_ledger import ExecutionLedger

            _ledger = getattr(self, "_der_ledger", None)
            if _ledger is None:
                _ledger = ExecutionLedger(
                    conversation_id=self.conversation_id or self.session_id or "",
                    storage_path=_der_ledger_storage_path(),  # GROUND TRUTH T9 (REQ-14 AC1)
                )
                self._der_ledger = _ledger
            _task_id = self.conversation_id or self.session_id or "unknown"
            _term = {
                "success": "completed",
                "partial": "partial",
                "failure": "failed",
                "cancelled": "cancelled",
            }.get(outcome, "failed")
            _t = _ledger.transition(_task_id, _term)
            if not _ledger.persist():
                logger.warning(
                    "[DER] task lifecycle persistence FAILED (state=%s) â€” durable completion not claimed",
                    _term,
                )
        except Exception as _lc_exc:  # noqa: BLE001 â€” lifecycle must never block the user response
            _write_counters.bump("ledger.lifecycle_write_failed")
            logger.warning("[DER] task lifecycle write FAILED: %s", _lc_exc)

        # GROUND TRUTH T6 (REQ-3): persist the CARD FOOTPRINT here, at the same
        # honest terminal state the ledger just recorded.
        #
        # backend/memory/card_footprint.py was implemented for
        # specs/task-card-v2-liquid-ink REQ-11 and then never called: the module
        # has ZERO production importers, and save_card_footprint /
        # get_card_footprint appear in exactly one file - their own. So
        # semantic_entries holds 0 rows and no card has ever been addressable
        # by id across conversations. This is the call site it was waiting for,
        # and it unblocks specs/wormhole-aperture REQ-34, which reads footprints
        # as a chain-extraction source.
        # C5: written by the turn-end job on the memory lane (below); the card
        # id is captured now because the next turn may change it.
        _te_card_id = getattr(self, "_active_card_id", None)

        # â”€â”€ EventBus: emit task:done / task:fail â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # T11 (REQ-12): record the completed-step count on the kernel so the
        # caller's TurnMetrics block (metrics.der_steps) reads a real number.
        # len(completed_items) is authoritative here â€” it is appended only in
        # _der_finalize_step, one per actually-completed step.
        self._der_step_count = len(completed_items)
        #
        # Session 247 (live conv-44): this emit used to run HERE, BEFORE
        # synthesis. The card flipped to done while the answer did not exist
        # yet, and the "Synthesizing answer" progress frame arrived ~43s
        # AFTER task:done with no working card to attach to - the frontend
        # fabricated a phantom second card (LEGACY_UNKNOWN, THK, timer
        # running). Done must mean "the answer was delivered": the emit is
        # now a closure fired by every outcome branch BELOW, right before
        # it returns its synthesized response.
        def _emit_terminal_event() -> None:
            # Never raises; EventBus failures must not block the user response.
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                _lifecycle_task_id = _turn_id or plan.original_task[:40]
                get_event_bus().emit(
                    IRISStreamEvent.TASK_DONE if outcome in ("success", "partial") else IRISStreamEvent.TASK_FAIL,
                    data={
                        "task_id": _lifecycle_task_id,
                        "outcome": outcome,
                        # REQ-15 AC3 (T25): a stop is explicit â€” the user sees it.
                        "cancelled": outcome == "cancelled",
                        "steps_completed": len(completed_items),
                        "total_steps": len(plan.steps),
                        "failed_steps": [
                            {
                                "step_id": _fi,
                                "description": next(
                                    (_it.description for _it in queue.items
                                     if _it.step_id == _fi),
                                    _fi,
                                ),
                                "reason": next(
                                    (_it.result for _it in queue.items
                                     if _it.step_id == _fi),
                                    "",
                                ) or "",
                            }
                            for _fi in queue.failed_ids
                        ],
                        # REQ-3 AC6 (T2): card_id stays stable across every
                        # event of a card's lifetime, not just task:start.
                        **self._card_envelope(_lifecycle_task_id),
                    },
                    turn_id=_turn_id,
                    conversation_id=self.conversation_id,
                    session_id=_session,
                )
                # T4a (REQ-4 AC1): persist the terminal state. Mirrors the same
                # outcome == "success" condition used to pick TASK_DONE vs
                # TASK_FAIL above â€” no separate terminal-state taxonomy invented.
                _envelope = self._card_envelope(_lifecycle_task_id)
                self._persist_card_snapshot(
                    card_id=_envelope.get("card_id"),
                    conversation_id=self.conversation_id,
                    card_relation="continues",
                    plan_title=self._effective_plan_title(plan),
                    mode=queue.mode.value if getattr(queue, "mode", None) else None,
                    steps=self._queue_steps_snapshot(queue),
                    total_steps=len(queue.items),
                    terminal_state="done" if outcome == "success" else "fail",
                )
            except Exception:
                pass  # EventBus is optional â€” no crash if it fails

        try:
            if self._memory_interface:
                self._memory_interface.mycelium_clear_session(
                    session_id=_session,
                )
        except Exception as _exc:
            loud_error(_exc, "mycelium_clear_session")

        # â”€â”€ C5: turn-end bookkeeping on the memory lane (2026-10-01) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Card footprint, plan stats, the episode (+ Mycelium outcome and
        # landmark crystallization) and skill capture ran HERE, before the
        # reply's synthesis: 2-8.5 s per coding task (stack dumps: inside
        # crystallize_landmark -> _auto_connect). The reply does not need any
        # of it, so it runs as ONE ordered job on lane("memory_events") after
        # record_task_end (same lane, same order as before). The next turn
        # folds back on it before planning recalls episodes (_turn_end_settle).
        # Everything the job reads is captured now: the next turn changes
        # kernel state.
        if self._memory_interface:
            _der_duration_ms = int((time.perf_counter() - _der_start_time) * 1000)
            _te_items = list(completed_items)
            _avg_step_ms = _der_duration_ms / len(_te_items) if _te_items else 0.0
            _te_stats = dict(
                session_id=_session,
                task_class=task_class,
                strategy=plan.strategy,
                total_steps=len(plan.steps),
                steps_completed=len(_te_items),
                tokens_used=_tokens_used,
                avg_step_duration_ms=_avg_step_ms,
                outcome=outcome,
                graph_mature=is_mature,
            )
            # One entry per call the steps ACTUALLY made (_step_calls): a node
            # step used to record {"tool": "none"}, so episodes held no tools
            # and skill capture (needs successful calls) could never fire.
            _tool_seq = [
                {
                    "tool": c.get("tool") or "none",
                    "params": dict(c.get("args") or {}),
                    "target": c.get("target", ""),
                    "success": bool(c.get("ok", True)),
                    "step": ci.step_number,
                    "description": ci.description,
                }
                for ci in _te_items
                for c in _step_calls(ci)
            ]
            _full_content = "\n".join(
                f"[Step {i + 1}] {o}" for i, o in enumerate(step_outputs) if o
            )
            _te_task = plan.original_task
            # Spec D9: task completion is outside evidence for this task's
            # FIXes (-> VERIFIED_FIX + LESSON candidate); closes its cases.
            _memory_events_submit(
                self, "record_task_end",
                thread_id=_session,
                task_id=f"{_session}:{_turn_id or ''}",
                success=(outcome == "success"),
            )

            def _turn_end_job():
                self._save_card_footprint(plan, _te_items, outcome, card_id=_te_card_id)
                try:
                    self._memory_interface.mycelium_record_plan_stats(**_te_stats)
                except Exception as _exc:
                    loud_error(_exc, "mycelium_record_plan_stats")
                # EPISODIC STORAGE closes the read/write loop:
                # assemble_episodic_context() reads these episodes.
                try:
                    self._store_task_episode(
                        task_summary=_te_task,
                        full_content=_full_content,
                        outcome_type=outcome,
                        tool_sequence=_tool_seq,
                        session_id=_session,
                        duration_ms=_der_duration_ms,
                    )
                except Exception as _exc:
                    loud_error(_exc, "store_task_episode")
                # Skill capture. It never fired while node steps recorded tool
                # "none"; with real calls it saved one task's call list per run
                # (5 in one eval). It now needs the call shape to RECUR in >= 3
                # successful similar episodes (workflow_capture.MIN_RECURRENCES).
                try:
                    self._maybe_trigger_skill_creation(
                        tool_sequence=_tool_seq,
                        task_summary=_te_task,
                    )
                except Exception as _exc:
                    loud_error(_exc, "skill_creation_trigger")

            _turn_end_submit(self, _session, _turn_end_job)

        # â”€â”€ EventBus: emit der:done â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            get_event_bus().emit(
                IRISStreamEvent.DER_DONE,
                data={
                    "task_id": _turn_id or plan.original_task[:40],
                    "outcome": outcome,
                    "mode": queue.mode.value,
                    "total_steps": len(queue.items),
                    "completed": len(completed_items),
                    "tokens_used": _tokens_used,
                    "mode_history": [
                        {
                            "previous": c.previous_mode.value if c.previous_mode else None,
                            "new": c.new_mode.value,
                            "reason": c.reason,
                            "turn_id": c.turn_id,
                        }
                        for c in queue.mode_history
                    ],
                    # ToolCallTree (REQ-13): structured snapshot of all tool calls
                    "tool_call_tree": (
                        self._get_tool_box().get_tool_call_tree(
                            conversation_id=self.conversation_id
                        )
                    ),
                },
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
            )
        except Exception:
            pass

        # REQ-12 (Wave 9): emit final context usage for the DER task.
        # Covers the "zero steps executed" case (plan rejected before any
        # step ran) where the per-step emit never fired. Uses the real
        # per-thread self._context_fill (how full the window is) â€” never 0 for an active thread.
        # All return paths below are preceded by this single emit.
        self._emit_context_usage(
            step_number=len(completed_items),
            total_steps=len(queue.items),
        )

        # Phase 1.5: if any step failed, synthesize a user-facing summary
        # that explains what worked, what failed, and what to do next.
        # Unless the OBJECTIVE is met: a failed intermediate attempt whose facts
        # a later step found is not a failed task (live 2026-10-02 run A7: run
        # grade pass, C=1.000, one failed search step -> "I couldn't complete
        # that task. 3/5 steps finished" with the answer in hand). An open or
        # blocked fact keeps this failure path.
        if queue.failed_ids and not (step_outputs and AgentKernel._goal_contract_met(self)):
            # REQ-16 AC2 (T32): a task with failed steps did NOT exit naturally.
            self._der_stamp_session_exit(False)
            _synthesis = self._der_synthesize_outcome(
                plan, completed_items, queue, _session
            )
            # REQ-18 AC2 (T31): correlate which synthesis path ran.
            try:
                from backend.agent.der_trace import get_der_trace

                get_der_trace(self._der_trace_task_id()).record(
                    "synthesis",
                    path="failure" if _synthesis else "deterministic_failure",
                    ran=bool(_synthesis),
                )
            except Exception:
                pass
            if _synthesis:
                _emit_terminal_event()
                return self._goal_contract_name_blocked(_synthesis)
            # LLM synthesis unavailable (e.g. model rate-limited â€” the very
            # failure that broke the step) -> deterministic fallback so the user
            # is NEVER left with silence (Part B).
            _emit_terminal_event()
            return self._goal_contract_name_blocked(
                AgentKernel._der_deterministic_failure_summary(
                    plan, completed_items, queue
                )
            )

        if step_outputs:
            # REQ-16 AC2 (T32): a task that ran steps to completion exited
            # naturally.
            self._der_stamp_session_exit(True)
            # AC3.6 defense-in-depth (session-334, live T3): the loop-level
            # continuation gate in _der_plan_next_step is bypassable â€” COMPRESS
            # (rec==1) skips it, a non-AGENTIC/FULL mode skips it, and a planner
            # JSON-parse failure returns None. Measured 2026-09-17: grade=capped
            # with 1 open unblocked required fact still produced "I've completed
            # the task. 1/1 steps finished." The spec says the turn SHALL NOT
            # terminate while a required fact is open and unblocked. Guard the
            # FINALIZE boundary itself so a false success claim is impossible no
            # matter which bypass fired.
            try:
                _gc_open_final = list(self._goal_contract_open_facts() or [])
            except Exception:
                _gc_open_final = []
            # Test the COUNT, never truthiness: a non-sequence (or any object
            # with a permissive __bool__) would otherwise trip this branch with
            # zero open facts and suppress a legitimate success claim.
            #
            # Item 2 (2026-09-24, owner-approved): this guard must not narrate a
            # FAILURE for a turn that succeeded. Live conv-145 ("create a file
            # eyes_note3.md ... then read it back to me"): write_file and
            # read_file both returned success, the file on disk matched the
            # request, no step failed â€” and the contract still reported one open
            # required fact (counters: seeded=1 mapped=0 readded=1 covered=0), so
            # this branch appended "I couldn't fully complete the task â€” still
            # open: ..." to a correct, successful answer. A success claim is only
            # FALSE when a step failed, so the suppression now also requires
            # that. The mismatch is still recorded (WARNING above) and the fact
            # stays in the contract â€” nothing is hidden, and no false success
            # can slip through, because any failed or missing step keeps the
            # original suppression.
            _open_ok = bool(completed_items) and not list(
                getattr(queue, "failed_ids", None) or []
            )
            if len(_gc_open_final) > 0 and not _open_ok:
                logger.warning(
                    "[goal-contract] finalize with %d open unblocked fact(s) â€” "
                    "suppressing success claim: %r",
                    len(_gc_open_final), str(_gc_open_final[0])[:160],
                )
                _emit_terminal_event()
                _open_facts_txt = "; ".join(
                    str(_f)[:200] for _f in _gc_open_final[:5]
                )
                # Session-345 (live, conv-135): suppression must not hide what
                # WAS gathered. With completed steps on record, synthesize the
                # partial answer and append the open fact line â€” the fixed
                # string alone told the user nothing about the data the crawl
                # actually found. The failure path takes over if synthesis
                # itself is unavailable (deterministic close).
                _partial = None
                if completed_items:
                    try:
                        _partial = self._der_synthesize_outcome(
                            plan, completed_items, queue, _session
                        )
                    except Exception as _ps_err:
                        logger.warning(
                            "[goal-contract] partial synthesis failed: %s", _ps_err,
                        )
                if _partial:
                    return (
                        _partial.strip()
                        + "\n\nI couldn't fully complete the task â€” still open: "
                        + _open_facts_txt
                        + "\nWhat would you like me to do next?"
                    )
                return (
                    "I couldn't fully complete the task â€” required work is "
                    f"still open: {_open_facts_txt}\n"
                    "What would you like me to do next?"
                )
            # REQ-12 (AC1/AC2/AC3): synthesize the gathered evidence into a
            # final answer instead of raw-concatenating step outputs. Consumes
            # the same evidence the failure path consumes (plan.original_task
            # + completed step descriptions/results) and wires the previously-
            # dead _synthesize_response brain synthesis.
            _synthesis = self._der_synthesize_success_outcome(
                plan, completed_items, queue, _session
            )
            # REQ-18 AC2 (T31): correlate which synthesis path ran.
            try:
                from backend.agent.der_trace import get_der_trace

                get_der_trace(self._der_trace_task_id()).record(
                    "synthesis",
                    path="success" if _synthesis else "deterministic_success",
                    ran=bool(_synthesis),
                )
            except Exception:
                pass
            if _synthesis:
                _emit_terminal_event()
                return self._goal_contract_name_blocked(_synthesis)
            # REQ-12 (AC4): synthesis unavailable (e.g. reasoning provider
            # down) -> deterministic success summary mirroring
            # _der_deterministic_failure_summary so the user is never left
            # with raw concatenation (Part B symmetry).
            _emit_terminal_event()
            return self._goal_contract_name_blocked(
                AgentKernel._der_deterministic_success_summary(
                    plan, completed_items, queue
                )
            )
        # â”€â”€ Zero steps (or zero usable outputs) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # The crawl plan produced no executable URLs (all blocked/filtered
        # by BOT_BLOCKED_DOMAINS, or the LLM couldn't generate any). Return
        # a descriptive message so _plan_task's post-processing can surface
        # an actionable explanation instead of the generic "couldn't generate".
        # REQ-16 AC2 (T32): zero usable steps is NOT a natural exit.
        self._der_stamp_session_exit(False)
        _emit_terminal_event()
        return (
            f"[DER] {plan.strategy} â€” "
            f"{len(completed_items)}/{len(plan.steps)} steps completed.  "
            f"error: no usable sources found for '{getattr(plan, 'title', '') or getattr(plan, 'plan_title', '') or plan.original_task[:40]}'.  "
            + self._build_crawl_failure_explanation(plan)
        )

    # â”€â”€ Phase 1.4: failure handling + plan grafting â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€









    # â”€â”€ REQ-15 (T25): mid-task steering channel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _der_check_steering(self, _session, plan, queue, budget_deadline: Optional[float] = None) -> Optional[dict]:
        """REQ-15 AC1/AC2/AC3/AC6 (T25): consume pending steering at the NEXT
        step boundary â€” never mid-step.

        Drains every record queued for the session since the last boundary
        and applies, in order:
          - stop   -> latch ``_der_stop_requested`` (AC3: the loop aborts
                      here and persists `cancelled`);
          - pause  -> latch ``_der_pause_requested`` (AC4: the loop
                      suspends via ``_der_suspend_task``);
          - resume -> latch ``_der_resume_requested`` (harmless when the
                      task is not suspended; consumed and acked either way);
          - steer  -> revise the remaining plan via REQ-14's revision channel
                      (AC2); the LAST non-empty steering text wins.

        AC6 (channel independence): stop/pause flags are latched BEFORE any
        (potentially slow) revision is applied, and a stop suppresses the
        revision entirely â€” a stop is never delayed behind steering work.

        AC5 (acknowledgement): every consumed record emits ``steering:ack``
        status="considered".

        The stuck-streak gate runs at EVERY boundary, steering or not (owner,
        2026-10-01: c06 pushed 36 times with no brake).

        Returns ``None`` when nothing was queued and the gate did not fire,
        else a dict ``{"stop", "pause", "resume": bool, "steer": str|None,
        "revised": bool}``.
        """
        try:
            from backend.agent.steering import get_steering_inbox
        except Exception:
            get_steering_inbox = None
        records = get_steering_inbox().drain(_session) if get_steering_inbox else []
        if not records:
            if not getattr(self, "_der_stop_requested", False) and self._der_streak_gate(
                plan, queue, _session, budget_deadline=budget_deadline
            ):
                return {"stop": False, "pause": False, "resume": False,
                        "steer": None, "revised": True}
            return None

        stop = False
        pause = False
        resume = False
        steer_text = None
        for rec in records:
            if rec.channel == "stop":
                stop = True
            elif rec.channel == "pause":
                pause = True
            elif rec.channel == "resume":
                resume = True
            elif rec.channel == "steer" and rec.text and rec.text.strip():
                steer_text = rec.text.strip()  # last non-empty steering wins

        # AC6: latch the control flags BEFORE applying any revision so a stop
        # is never delayed behind a slow re-plan.
        if stop:
            self._der_stop_requested = True
        if pause:
            self._der_pause_requested = True
        if resume:
            self._der_resume_requested = True

        revised = False
        if steer_text is not None and not stop:
            revised = self._der_apply_steering(
                steer_text, _session, plan, queue,
                budget_deadline=budget_deadline,
            )
        # â”€â”€ Goal contract T7 (REQ-4 AC4.1): route user steering through
        # amend â€” add/remove/repromote a floor fact in place, preserving task
        # identity. Advisory: runs even when the replan above did nothing.
        try:
            if steer_text and not stop:
                if self._goal_contract_apply_steering(steer_text):
                    revised = True
        except Exception:
            pass

        # â”€â”€ T9 (specs/tool-result-envelope REQ-5): stuck-streak gate at the
        # step boundary, in front of the same replan machinery. Skipped when
        # the user just steered (a fresh revision replaced the plan â€” the
        # gate re-evaluates at the NEXT boundary) or when stopping.
        if not stop and not revised:
            if self._der_streak_gate(
                plan, queue, _session, budget_deadline=budget_deadline
            ):
                revised = True

        # AC5: every consumed record is acknowledged as "considered".
        for rec in records:
            self._emit_steering_ack(rec.channel, rec.message_id, "considered", _session)

        # REQ-18 AC4 (T31): correlate every steering message received â€” channel,
        # acknowledged status, and the step boundary at which it was applied.
        try:
            from backend.agent.der_trace import get_der_trace

            _trace = get_der_trace(self._der_trace_task_id())
            for rec in records:
                _trace.record(
                    "steering",
                    channel=rec.channel,
                    message_id=rec.message_id,
                    ack="considered",
                    boundary_step=getattr(queue, "_last_step_number", None),
                )
        except Exception:
            pass

        return {
            "stop": stop,
            "pause": pause,
            "resume": resume,
            "steer": steer_text,
            "revised": revised,
        }

    def _der_build_step_envelope(
        self,
        item: "QueueItem",
        step_result: str,
        step_success: bool,
        outcome: str,
        completed_items: list,
        _session: str,
        _turn_id: Optional[str],
        coords_from: Optional[str],
        coords_to: Optional[str],
    ) -> None:
        """specs/tool-result-envelope T6 (REQ-1 AC1.2): build the envelope
        ONCE at the finalize site, alongside the node-record stamping
        (outcome/expected_output/fraction/coords all in scope). raw_ref =
        doc-store id ONLY (AC1.3 â€” Pacman chunk ids are async and never
        waited on); criticality confirmed from consumption (AC1.6); coords
        pass through VERBATIM (AC1.5); per-envelope debug log (AC7.1).
        Never raises into the caller: any failure degrades to the minimal
        envelope (AC1.4)."""
        _coords_from = coords_from
        _coords_to = coords_to
        try:
            from backend.agent.tool_envelope import (
                build_envelope, minimal_envelope, params_digest,
                classify_exception_from_message, extract_sources,
                body_hashes_of,
            )
            from backend.agent.tool_errors import resolve_label

            _raw_doc_id = getattr(item, "captured_doc_id", None) or ""
            _env_frac = getattr(
                getattr(item, "node_record", None), "verified_fraction", None
            )
            _prev_frac = None
            if completed_items:
                _prev_rec = getattr(
                    completed_items[-1], "node_record", None
                )
                if _prev_rec is not None:
                    _prev_frac = getattr(
                        _prev_rec, "verified_fraction", None
                    )
            # Turn memory (AC3.1): envelopes + tool/params digests of
            # PRIOR completed steps this run â€” derived from in-scope
            # state, no new store.
            _seen_params: Dict[str, str] = {}
            _step_summaries: List[str] = []
            for _pit in completed_items:
                _pd = _step_digest(_pit)
                if _pd:
                    _seen_params.setdefault(_pd, getattr(_pit, "step_id", ""))
                _pe = getattr(_pit, "envelope", None)
                if _pe is not None:
                    _step_summaries.append(_pe.summary)
            # Session-323: exclude THIS step's own URLs from the novelty
            # comparison. _remember_turn_urls ran earlier in finalize (and at
            # dispatch for seeds), so _der_crawled_urls already holds the
            # current step's addresses â€” comparing the result against a set
            # containing itself makes every first gather read as
            # "repeat_of_gather" (live b323_web1 s1: fresh crawl, zero priors,
            # envelope still stamped repeat/circling). Novelty is vs PRIOR
            # steps only; the step's own URLs rejoin the refusal set after.
            _own_urls323: set = set()
            try:
                import re as _re_own323
                from backend.agent.tool_envelope import normalize_url as _norm_own323
                for _m323 in _re_own323.findall(r"https?://[^\s\"')\]]+", str(step_result or "")):
                    try:
                        _n323 = _norm_own323(str(_m323).rstrip(".,;)]"))
                    except Exception:
                        _n323 = ""
                    if _n323:
                        _own_urls323.add(_n323)
            except Exception:
                _own_urls323 = set()
            _turn_memory = {
                "crawled_urls": set(
                    getattr(self, "_der_crawled_urls", {}).get(
                        self.conversation_id or "", set()
                    )
                ) - _own_urls323,
                "tool_params": _seen_params,
                "step_summaries": _step_summaries,
                "last_gather_step_id": (
                    completed_items[-1].step_id if completed_items else ""
                ),
            }
            # Session-318 T17 (REQ-10 AC10.1): exact body-identity vs turn.
            # Prior hashes ride turn_memory; current hashes join the map
            # after the build (same order as seen-dispatches). A hit is
            # logged here (T19 counts it) and derive_novelty independently
            # reaches the same repeat_of verdict from the same map.
            _turn_memory["body_hashes"] = dict(
                getattr(self, "_der_body_hashes", {}).get(
                    self.conversation_id or "", {}
                )
            )
            _cur_hashes = body_hashes_of(str(step_result or ""))
            _hash_hit = next(
                (_h for _h in _cur_hashes
                 if _h in _turn_memory["body_hashes"]),
                "",
            )
            if _hash_hit:
                logger.info(
                    "[envelope] content-hash hit: step %s repeats %s "
                    "(identical body)",
                    item.step_id,
                    _turn_memory["body_hashes"][_hash_hit],
                )
                try:
                    from backend.agent.write_counters import bump as _bump_hash
                    _bump_hash("envelope.hash_hits")
                except Exception:
                    pass
            # Structured error shape (CT-4 lock): error_type from the
            # tool_errors taxonomy when the step failed.
            _env_error = None
            if not step_success:
                _etype = classify_exception_from_message(
                    str(step_result or "")
                )
                _label = resolve_label(_etype)
                _env_error = {
                    "error_type": _etype,
                    "recovery_hint": (
                        _label.description[:120] if _label else ""
                    ),
                }
            # AC3.4: the Caducean recommendation is read at the SAME
            # finalize point so a TOPO_VIOLATION (rec==3) forces
            # suggestion=stop on the envelope (physics first, KD-4).
            _topo_rec = 2
            try:
                from backend.gateway.iris_ffi import ffi_caducean_recommend

                _topo_rec = ffi_caducean_recommend(_session)
            except Exception:
                _topo_rec = 2
            # REQ-8 AC8.1: the step->URL map for VISITED join keys. The
            # envelope stamps its own (capped, marked) copy inside
            # build_envelope; refusal/exclusion logic always uses the FULL
            # in-memory crawled set â€” caps bound views, never decisions.
            _sources: List[str] = []
            try:
                _sources, _ = extract_sources(str(step_result or ""))
            except Exception:
                _sources = []
            # Session-318 T18 (REQ-11 AC11.2/AC12.2): elapsed vs deadline.
            # Slow completion logs a stall warning (advisory only â€” the
            # deadline alone aborts). In-flight visibility rides the tools'
            # own progress emissions (e.g. crawl phases); this closes the
            # accounting side so every slow step is undeniable in logs.
            _elapsed = 0.0
            try:
                _t0 = float(getattr(item, "dispatch_started_at", 0.0) or 0.0)
                if _t0 > 0:
                    import time as _time_elapsed
                    _elapsed = max(0.0, _time_elapsed.monotonic() - _t0)
                from backend.agent.der_constants import STALL_WARN_S
                if _elapsed > max(float(STALL_WARN_S), 1.0):
                    logger.warning(
                        "[DER] step %s slow: %.1fs elapsed (stall threshold "
                        "%.0fs) â€” advisory; deadline aborts, not this line",
                        getattr(item, "step_id", "?"), _elapsed,
                        float(STALL_WARN_S),
                    )
                    try:
                        from backend.agent.write_counters import bump as _bump_stall
                        _bump_stall("envelope.stalls")
                    except Exception:
                        pass
            except Exception:
                _elapsed = 0.0
            item.envelope = build_envelope(
                result_text=str(step_result or ""),
                step_success=step_success,
                outcome=outcome,
                expected_output=str(
                    getattr(item, "expected_output", None)
                    or item.description
                    or ""
                ),
                tool=getattr(item, "tool", None),
                params_digest=_step_digest(item),
                verified_fraction=_env_frac,
                prev_verified_fraction=_prev_frac,
                raw_doc_id=_raw_doc_id,
                coords_from=_coords_from,
                coords_to=_coords_to,
                turn_memory=_turn_memory,
                error=_env_error,
                recovery_of=getattr(item, "recovery_of", "") or "",
                elapsed_s=_elapsed,
                timeout=bool(getattr(item, "timed_out", False)),
                declared_criticality=getattr(
                    item, "declared_criticality", "supporting"
                )
                or "supporting",
                capture_skipped=bool(getattr(item, "tool", None))
                and not _raw_doc_id,
                topo_violation=(_topo_rec == 3),
                card_id=self._card_envelope(
                    _turn_id or item.step_id
                ).get("card_id", ""),
                step_id=item.step_id,
                session_id=_session or "",
                turn_id=_turn_id or "",
            )
            # AC7.1: scoped per-envelope log line â€” enough to
            # reconstruct a run's stuck trajectory from logs alone.
            logger.debug(
                "[envelope] conv=%s step=%s status=%s match=%s "
                "novelty=%s suggestion=%s shape=%s crit=%s/%s "
                "summary_len=%d",
                self.conversation_id or "?",
                item.step_id,
                item.envelope.status,
                item.envelope.match,
                item.envelope.novelty,
                item.envelope.suggestion,
                item.envelope.stuck_shape,
                item.envelope.criticality,
                item.envelope.criticality_source,
                len(item.envelope.summary),
            )
            if getattr(item.envelope, "criticality_source", "") == "confirmed":
                logger.info(
                    "[envelope] criticality divergence: step %s declared "
                    "%s but consumption confirmed load-bearing (tuning "
                    "signal)",
                    item.step_id,
                    getattr(item, "declared_criticality", "supporting"),
                )
            # AC7.2 counters â€” bounded, per-kernel, advisory.
            try:
                _counters = getattr(self, "_envelope_counters", None)
                if _counters is None:
                    _counters = {
                        "written": 0, "raw_ref_fetches": 0,
                        "crit_confirmed": 0, "gate_fired": 0,
                        "gate_blocked": 0, "hard_blocks": 0,
                        "suggest_overrides": 0,
                    }
                    self._envelope_counters = _counters
                _counters["written"] += 1
                if item.envelope.criticality_source == "confirmed":
                    _counters["crit_confirmed"] += 1
            except Exception:
                pass
            # Session-318 T19 (REQ-12): recovery outcome on the envelope
            # that just settled (recovered = brought usable sources home).
            try:
                if getattr(item, "recovery_of", ""):
                    from backend.agent.write_counters import bump as _bump_rec
                    if list(getattr(item.envelope, "sources", []) or []):
                        _bump_rec("envelope.recovery_recovered")
                    else:
                        _bump_rec("envelope.recovery_empty")
            except Exception:
                pass
            # Join registry for the retroactive criticality confirm and
            # pre-dispatch reroute reads (KD-10: reporter stamps, graph
            # layers read). FIFO-capped â€” memory bounded.
            try:
                _reg = dict(
                    getattr(self, "_der_envelope_registry", {})
                )
                _conv = self.conversation_id or ""
                _bucket = dict(_reg.get(_conv, {}))
                _bucket[item.envelope.raw_ref.get("doc_id") or f"noref:{item.step_id}"] = item.envelope
                while len(_bucket) > 200:
                    _bucket.pop(next(iter(_bucket)))
                _reg[_conv] = _bucket
                self._der_envelope_registry = _reg
                # Turn dispatch memory for the T6B repeat guard: digest
                # -> first step that ran it. FIFO-capped likewise.
                _sd = dict(getattr(self, "_der_seen_dispatches", {}))
                _sdb = dict(_sd.get(_conv, {}))
                _pd_self = _step_digest(item)
                _sdb.setdefault(_pd_self, item.step_id)
                while len(_sdb) > 200:
                    _sdb.pop(next(iter(_sdb)))
                _sd[_conv] = _sdb
                self._der_seen_dispatches = _sd
                # Session-318 T17 (REQ-10 AC10.1): turn body-hash map for
                # exact-identity detection (hash -> first step). FIFO-capped.
                try:
                    _bh = dict(getattr(self, "_der_body_hashes", {}))
                    _bhb = dict(_bh.get(_conv, {}))
                    for _h in _cur_hashes:
                        _bhb.setdefault(_h, item.step_id)
                    while len(_bhb) > 500:
                        _bhb.pop(next(iter(_bhb)))
                    _bh[_conv] = _bhb
                    self._der_body_hashes = _bh
                except Exception:
                    pass
                # REQ-8 AC8.2 join keys: url -> step that fetched it.
                # Additive only â€” `_der_crawled_urls` stays the refusal
                # authority and is never reshaped here. FIFO-capped.
                try:
                    _csm = dict(getattr(self, "_der_crawled_steps", {}))
                    _csb = dict(_csm.get(_conv, {}))
                    for _u in _sources:
                        _csb.setdefault(_u, item.step_id)
                    while len(_csb) > 500:
                        _csb.pop(next(iter(_csb)))
                    _csm[_conv] = _csb
                    self._der_crawled_steps = _csm
                except Exception:
                    pass
            except Exception:
                pass
        except Exception as _env_exc:
            # AC1.4: degrade to the minimal envelope â€” never break the
            # DER loop for shaping.
            logger.warning(
                "[envelope] build failed for step %s: %s",
                getattr(item, "step_id", "?"), _env_exc,
            )
            try:
                item.envelope = minimal_envelope(
                    outcome=outcome,
                    content_summary=str(
                        getattr(
                            getattr(item, "node_record", None),
                            "content_summary",
                            "",
                        )
                        or step_result
                        or ""
                    ),
                    raw_doc_id=getattr(item, "captured_doc_id", None) or "",
                    coords_from=_coords_from if "_coords_from" in dir() else None,
                    coords_to=_coords_to if "_coords_to" in dir() else None,
                    step_id=getattr(item, "step_id", ""),
                    session_id=_session or "",
                    turn_id=_turn_id or "",
                )
            except Exception:
                pass



    def _der_streak_gate(
        self,
        plan,
        queue,
        _session: str,
        budget_deadline: Optional[float] = None,
    ) -> bool:
        """T9 (specs/tool-result-envelope REQ-5 AC5.1â€“AC5.5): the stuck-streak
        gate, evaluated at the step boundary IN FRONT of the existing replan
        machinery. O(envelope count) arithmetic (AC5.5) â€” the LLM replan
        inside ``_der_apply_steering`` is paid ONLY when the gate fires.

        Detector: pure evaluate_streak over the settled envelopes' wrappers
        (consecutive repeat/empty/mismatch, or an idling run), with the
        existing Caducean TOPO_VIOLATION recommendation as the authoritative
        override (AC5.3 â€” reuse the existing physics detection, KD-4).

        Advisory-gate principle: any failure in here is treated as
        "below threshold" â€” a broken gate must not change loop semantics.

        Returns True when a replan revision was applied.
        """
        # A met objective is not stuck: every required fact is covered, so a
        # re-plan can only add work (live 2026-10-02 run A6: C=1.000 at
        # 00:17:42, the gate fired at 00:18:00, the re-plan ran a step and the
        # turn then crashed).
        if AgentKernel._goal_contract_met(self):  # class call: stand-in kernels
            return False
        try:
            from backend.agent.tool_envelope import evaluate_streak
            from backend.agent.der_constants import (
                STUCK_STREAK_N, IDLE_STREAK_N,
            )

            _counters = getattr(self, "_envelope_counters", None)
            if _counters is None:
                _counters = {
                    "written": 0, "raw_ref_fetches": 0,
                    "crit_confirmed": 0, "gate_fired": 0,
                    "gate_blocked": 0, "hard_blocks": 0,
                    "suggest_overrides": 0,
                }
                self._envelope_counters = _counters

            # Settled envelopes for THIS run: completed (+vetoed) queue items.
            _done_ids = set(queue.completed_ids) | set(queue.vetoed_ids)
            # Decide again only after a new step settles: right after a
            # replan the same tail would fire again, a replan per boundary.
            _settled = len(_done_ids | set(queue.failed_ids))
            if _settled == queue.streak_gate_settled:
                return False
            queue.streak_gate_settled = _settled
            _envs = [
                getattr(_it, "envelope", None)
                for _it in getattr(queue, "items", [])
                if getattr(_it, "step_id", "") in _done_ids
            ]
            _wrappers = [e.wrapper_dict() for e in _envs if e is not None]

            # AC5.3: TOPO_VIOLATION rec forces the gate regardless of
            # streak arithmetic (existing physics detection, zero new code
            # on the detection side).
            _topo = False
            try:
                from backend.gateway.iris_ffi import ffi_caducean_recommend

                # Fold-back: the finished steps' physics must have landed
                # before the topology override decides (side lane).
                _der_physics_settle(self, _session)
                _topo = ffi_caducean_recommend(_session) == 3
            except Exception:
                _topo = False

            # Goal contract T6 (REQ-3 AC3.4): feed the stall-rate signal
            # into the idling shape alongside the streak arithmetic. Advisory
            # â€” a missing contract preserves the legacy streak behavior.
            _gcov_state = getattr(self, "_goal_contract_state", None)
            _gcov_c = None
            _gcov_unmoved = 0
            _gcov_rho = None
            _gcov_stall = 0.0
            if _gcov_state is not None:
                try:
                    from backend.agent.der_constants import (
                        GOAL_STALL_RATE as _GOAL_STALL_RATE,
                    )

                    _gcov_c = float(_gcov_state.get("C", 0.0))
                    _gcov_unmoved = int(_gcov_state.get("unmoved", 0))
                    _gcov_rho = float(_gcov_state.get("rho", 0.0))
                    _gcov_stall = float(_GOAL_STALL_RATE)
                except Exception:
                    _gcov_state = None
            # The coverage arms judge "no progress toward the facts". While a
            # step of the ORIGINAL plan has not settled, the plan has not had
            # its chance: live 2026-10-06 two reads settled at C=0.667 with the
            # planned summary step still pending, the rate arm fired, and two
            # re-plans tripled the work (10 steps for 3 goals). The streak arms
            # (repeat / empty / mismatch / topology) still fire at any time.
            _plan_open = _plan_steps_open(plan, queue)
            if _gcov_c is not None and _plan_open:
                logger.debug(
                    "[DER:streak-gate] coverage arms wait: %d planned step(s) "
                    "not settled (C=%.3f)", _plan_open, _gcov_c,
                )
                _gcov_c = None
            fire, reason = evaluate_streak(
                _wrappers, STUCK_STREAK_N, IDLE_STREAK_N,
                topo_violation=_topo,
                coverage=_gcov_c,
                coverage_unmoved_n=_gcov_unmoved,
                coverage_rho=_gcov_rho,
                stall_rate=_gcov_stall,
            )
            if fire and str(reason).startswith("idle_streak"):
                # Shadow only (owner 2026-10-01): the idle arm fired on 5 of 15
                # healthy coding runs (reads and a first red test run verify
                # nothing yet) and its replan dropped c15's fix step. Logged and
                # counted until a measured true positive exists.
                _counters["idle_shadow"] = _counters.get("idle_shadow", 0) + 1
                logger.info(
                    "[DER:streak-gate] SHADOW would fire (%s) - idle arm is "
                    "shadow-only, plan continues", reason,
                )
                return False
            if not fire:
                _counters["gate_blocked"] += 1
                # AC3.3/AC7.2: a stop-suggestion the loop does NOT act on is
                # a suggestion override â€” logged with its reason, counted.
                if _wrappers and _wrappers[-1].get("suggestion") == "stop":
                    _counters["suggest_overrides"] += 1
                    logger.info(
                        "[DER:streak-gate] suggestion override: step %s "
                        "suggested stop but streak arithmetic is below "
                        "threshold â€” continuing current plan",
                        _wrappers[-1].get("step_id", "?"),
                    )
                return False

            # A coverage stall on change facts whose change a step already made is
            # not "stuck": what is missing is one passing run, and the cover push
            # asks for exactly that (goal_contract.cover_goal). A re-plan from the
            # request redid read/edit/check (live c05 2026-10-27: 3 steps, 51 s).
            # If the check fails, C stays open and the gate fires on the next settle.
            if str(reason or "").startswith("coverage_"):
                try:
                    from backend.agent import goal_contract as _gc_gate

                    _gate_open = AgentKernel._goal_contract_open_facts(self)
                    _gate_res = (getattr(self, "_goal_contract_state", None) or {}).get("results") or ()
                    if _gate_open and all(_gc_gate.change_awaits_check(_f, _gate_res) for _f in _gate_open):
                        _counters["gate_check_only"] = _counters.get("gate_check_only", 0) + 1
                        logger.info(
                            "[DER:streak-gate] %s on a change already made - one check "
                            "step instead of a re-plan conv=%s", reason,
                            getattr(self, "conversation_id", ""),
                        )
                        return False
                except Exception as _gco_exc:  # noqa: BLE001 - doubt keeps the re-plan
                    logger.debug("[DER:streak-gate] check-only test failed: %r", _gco_exc)

            from backend.agent.der_constants import STREAK_GATE_MAX_FIRES

            if queue.streak_gate_fires >= STREAK_GATE_MAX_FIRES:
                _counters["gate_capped"] = _counters.get("gate_capped", 0) + 1
                logger.info(
                    "[DER:streak-gate] would fire (%s) but the run already "
                    "replanned %d time(s) - plan continues", reason,
                    queue.streak_gate_fires,
                )
                return False
            queue.streak_gate_fires += 1
            _counters["gate_fired"] += 1
            # Goal contract (REQ-7 AC7.2): a coverage-stall fire is a
            # coverage stall â€” count it on the contract so the stall rate
            # is tunable from measurement. Advisory, never raises.
            try:
                _gc_stall = getattr(self, "_goal_contract_state", None)
                if _gc_stall is not None and str(reason or "").startswith(
                    "coverage_"
                ):
                    _gc_c = _gc_stall.get("counters") or {}
                    _gc_c["stalls"] = int(_gc_c.get("stalls", 0)) + 1
                    _gc_stall["counters"] = _gc_c
            except Exception:
                pass
            # AC5.4: audit â€” the triggering envelopes (step ids + wrapper
            # labels) are logged so the trigger is auditable post-run.
            _tail = _wrappers[-max(STUCK_STREAK_N, IDLE_STREAK_N, 1):]
            _audit = "; ".join(
                f"{w.get('step_id', '?')}: novelty={w.get('novelty')} "
                f"match={w.get('match')} shape={w.get('stuck_shape')}"
                for w in _tail
            )
            logger.info(
                "[DER:streak-gate] FIRED (%s) â€” triggering envelopes: %s",
                reason, _audit,
            )
            _directive = (
                f"Replan required: the run is stuck ({reason}). "
                f"Triggering steps: {_audit}. Revise the remaining plan to "
                "break the streak â€” do NOT repeat a completed step; read "
                "the already-gathered documents instead."
            )
            return self._der_apply_steering(
                _directive, _session, plan, queue,
                budget_deadline=budget_deadline,
            )
        except Exception as _gate_exc:
            logger.debug(
                "[DER:streak-gate] evaluation failed â€” treated as below "
                "threshold (advisory gate): %s", _gate_exc,
            )
            return False

    def _der_apply_steering(
        self, text, _session, plan, queue, budget_deadline: Optional[float] = None
    ) -> bool:
        """REQ-15 AC2: revise the remaining plan via REQ-14's revision
        channel without aborting the task.

        Re-plans from the steering text (single-step fallback on failure),
        REMOVES every not-yet-terminal queue item (they are REPLACED, not
        failed â€” ``queue.failed_ids`` stays honest), appends the revised steps
        as fresh items, and re-emits ``task:start`` with
        ``origin="user_steering"`` carrying the revised step list (REQ-14 AC1
        revision signal; REQ-18 AC3 origin).

        ``budget_deadline`` (session 269, pin_ced7b0dc3b8f): the re-plan is
        an UNBOUNDED LLM call made INSIDE the loop body â€” the turn budget's
        while-condition can never reach a hang here. conv-81's last event was
        the steering ack, then silence for 29 minutes. When a deadline is
        supplied, the re-plan runs on a daemon thread bounded by it; a
        timeout keeps the CURRENT plan (the revision is advisory â€” skipping
        it degrades the turn, it never kills it).

        Returns True when a revision was actually applied.
        """
        try:
            from backend.agent.der_loop import QueueItem
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            _mode = queue.mode.value if getattr(queue, "mode", None) else "full"
            # V12 (2026-10-02 live): the re-plan saw ONLY the directive ("Replan
            # required: the run is stuck ...") - no user request - and recall
            # searched with that header, so other stuck runs' episodes ("Read
            # the existing notes file") became the new plan of a Wikipedia
            # task. The planner gets the request + the directive; recall
            # searches with the request alone.
            _orig = str(getattr(plan, "original_task", "") or "") if plan else ""
            _plan_text = (
                _orig + "\n\n" + text if _orig and _orig not in (text or "") else text
            )
            _recall = _orig or text
            if budget_deadline is not None:
                _timeout_s = budget_deadline - time.perf_counter()
                if _timeout_s <= 0:
                    logger.warning(
                        "[DER] Session %s steering skipped â€” turn budget "
                        "already exhausted", _session,
                    )
                    return False
                _box: dict = {}

                def _replan() -> None:
                    try:
                        _box["plan"] = self._plan_task(
                            _plan_text, session_id=_session, mode=_mode,
                            recall_query=_recall,
                        )
                    except BaseException as _exc:  # noqa: BLE001 â€” boxed, re-raised below
                        _box["exc"] = _exc

                import threading as _threading

                _t = _threading.Thread(
                    target=_replan, daemon=True,
                    name=f"der-steer-replan-{_session}",
                )
                _t.start()
                _t.join(timeout=_timeout_s)
                if _t.is_alive():
                    logger.warning(
                        "[DER] Session %s steering re-plan exceeded the "
                        "remaining turn budget (%.0fs) â€” keeping the current "
                        "plan", _session, _timeout_s,
                    )
                    return False
                if "exc" in _box:
                    raise _box["exc"]
                _rev = _box.get("plan")
            else:
                _rev = self._plan_task(
                    _plan_text,
                    session_id=_session,
                    mode=_mode,
                    recall_query=_recall,
                )
            if _rev is None or not getattr(_rev, "steps", None):
                logger.info(
                    "[DER] Session %s steering produced no plan â€” keeping "
                    "the current plan", _session,
                )
                return False

            _done = (
                set(queue.completed_ids)
                | set(queue.vetoed_ids)
                | set(queue.failed_ids)
            )
            # Replace remaining pending steps: remove them (not failures),
            # then append the revised steps fresh.
            queue.items[:] = [it for it in queue.items if it.step_id in _done]

            _fresh: List["QueueItem"] = []
            _base = len(queue.items) + 1
            for _i, _s in enumerate(_rev.steps):
                # Neutralize dependencies that point at dropped ids so the
                # revised steps are immediately ready.
                _deps = [
                    d for d in (getattr(_s, "depends_on", None) or [])
                    if d in _done
                ]
                _fresh.append(
                    QueueItem(
                        step_id=f"steer-{_base + _i}",
                        step_number=_base + _i,
                        description=_s.description,
                        tool=getattr(_s, "tool", None),
                        params=dict(getattr(_s, "params", None) or {}),
                        depends_on=_deps,
                        critical=getattr(_s, "critical", True),
                        objective_anchor=(
                            getattr(plan, "original_task", "") if plan else ""
                        ),
                    )
                )
            queue.items.extend(_fresh)

            # REQ-14 revision signal with the user_steering origin.
            _card_task_id = self.conversation_id or _session
            _card_id, _card_relation = self._resolve_card_identity(
                _card_task_id, "user_steering"
            )
            get_event_bus().emit(
                IRISStreamEvent.TASK_START,
                data=self._task_start_payload(
                    task_id=_card_task_id,
                    description=text,
                    plan_title=self._effective_plan_title(plan),
                    mode=_mode,
                    steps=[
                        {
                            "id": it.step_id,
                            "description": it.description,
                            "status": "pending",
                            "toolName": _step_tool(it),
                        }
                        for it in _fresh
                    ],
                    total_steps=len(_fresh),
                    origin="user_steering",
                    # REQ-3 (T2): backend-declared card identity.
                    card_id=_card_id,
                    card_relation=_card_relation,
                    conversation_id=self.conversation_id,
                        turn_id=getattr(self, "_current_turn_id", None),
                    **self._multiagent_tags(),
                ),
                turn_id=self.conversation_id or _session,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
            # T4a (REQ-4 AC1): persist the revised card. The WIRE payload
            # above intentionally carries only `_fresh` (the delta the
            # frontend merges) â€” the STORED snapshot must stay the FULL
            # cumulative step list (queue.items, already extended with
            # _fresh), or a restore would show only the newest steps.
            self._persist_card_snapshot(
                card_id=_card_id,
                conversation_id=self.conversation_id,
                card_relation=_card_relation,
                plan_title=self._effective_plan_title(plan),
                mode=_mode,
                steps=self._queue_steps_snapshot(queue),
                total_steps=len(queue.items),
                terminal_state="running",
            )
            # REQ-18 AC3 (T31): correlate the user-steering revision.
            try:
                from backend.agent.der_trace import get_der_trace

                get_der_trace(self._der_trace_task_id()).record(
                    "revision",
                    origin="user_steering",
                    boundary_step=getattr(queue, "_last_step_number", None),
                )
            except Exception:
                pass
            return True
        except Exception as _steer_exc:
            logger.debug("[DER] steering revision failed: %s", _steer_exc)
            return False

    # â”€â”€ REQ-5 (specs/dag-node-execution-model): bounded mid-execution
    # amendment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # The executing graph may be EXTENDED between steps based on outcomes
    # already observed (AC1). Planner-driven ONLY (design D6) â€” a node
    # proposing its own successor would reintroduce hidden control flow.
    # Amendments append fresh steps; they never re-execute satisfied nodes
    # (AC2) and the existing step budget / token accounting stays
    # authoritative (AC4). Bounded per task (AC3) and every amendment /
    # refused amendment is recorded (REQ-9 AC3).
    _AMENDMENT_BOUND = int(os.environ.get("IRIS_NODE_AMENDMENT_BOUND", "3"))

    def _der_amend_graph(
        self,
        new_steps,
        _session: str,
        plan,
        queue,
        _token_budget: int = 0,
        _tokens_used: int = 0,
        _turn_id: str = "",
    ) -> bool:
        """Extend the executing graph with *new_steps* (REQ-5).

        Returns True when the amendment was applied. Refused amendments are
        recorded with their cause (REQ-5 AC5, REQ-9 AC3) and execution
        continues on the existing graph â€” never a hang, never a silent skip.
        """
        from backend.agent.nodes.telemetry import log_amendment

        # getattr, not attribute access: these run on the graft/recovery paths,
        # and a kernel built via __new__ (as the DER test doubles and some
        # recovery paths do) has no conversation_id. A bare access raised
        # AttributeError inside the graft's try/except, silently turning
        # "amend the graph" into "recovery failed" â€” telemetry must never be
        # able to cost a graft.
        _task_id = getattr(self, "conversation_id", None) or _session
        try:
            if not new_steps:
                return False
            # REQ-19 (T34): a turn whose card already reached its terminal state
            # is CLOSED â€” recovery must not extend the graph after the answer is
            # public. The settle emitter (_der_emit_card_settle) marks that
            # moment in _der_card_terminal_emitted; without this guard the graft
            # loop kept crawling long after the reply (live conv-139/141: ~40
            # minutes of activity the user read as a second agent). Refusal is
            # the documented safe path: the cause is recorded and the existing
            # graph keeps running â€” never a hang, never a silent skip.
            _settled = getattr(self, "_der_card_terminal_emitted", None) or ()
            if _settled and (
                (_turn_id and _turn_id in _settled)
                or getattr(self, "_current_turn_id", None) in _settled
            ):
                log_amendment(
                    task_id=_task_id, kind="refused",
                    cause="recovery_stopped_turn_finalized",
                    detail=f"turn={_turn_id or getattr(self, '_current_turn_id', '')}",
                )
                return False
            # AC3: per-task bound on amendments.
            _used = getattr(self, "_der_amendment_count", 0)
            if _used >= self._AMENDMENT_BOUND:
                log_amendment(
                    task_id=_task_id, kind="refused",
                    cause="amendment_bound",
                    detail=f"used={_used} bound={self._AMENDMENT_BOUND}",
                )
                return False
            # AC4: the task budget is authoritative â€” an amendment cannot
            # exceed it. (Amendments add steps; if the budget is already
            # exhausted, adding work would violate the ceiling.)
            if _token_budget > 0 and _tokens_used >= _token_budget:
                log_amendment(
                    task_id=_task_id, kind="refused",
                    cause="budget_exceeded",
                    detail=f"used={_tokens_used} budget={_token_budget}",
                )
                return False

            # AC2: satisfied nodes are preserved. New steps may only depend on
            # already-terminal ids (completed/vetoed/failed); a dependency on a
            # pending node that may never run would stall the graph â€” refuse
            # (REQ-5 edge: amendment that removes/consumes a live node is
            # rejected, recorded, execution unchanged).
            from backend.agent.der_loop import QueueItem

            _done = (
                set(queue.completed_ids)
                | set(queue.vetoed_ids)
                | set(queue.failed_ids)
            )
            _pending = {it.step_id for it in queue.items if it.step_id not in _done}
            for _s in new_steps:
                _deps = list(getattr(_s, "depends_on", None) or [])
                _bad = [d for d in _deps if d in _pending]
                if _bad:
                    log_amendment(
                        task_id=_task_id, kind="refused",
                        cause="invalid_dependency",
                        detail=f"step={getattr(_s, 'description', '')[:60]} deps={_bad}",
                    )
                    return False

            # Append the fresh steps â€” completed work is untouched (AC2).
            _base = len(queue.items) + 1
            _fresh: List["QueueItem"] = []
            for _i, _s in enumerate(new_steps):
                # A graft's split child joins the graph AS ITSELF: its id is
                # what settle_split waits on, and it carries its parent link,
                # depth and node record. A copy ran beside it as "amend-N"
                # (live conv-1574, 2026-10-12: amend-3 and s1_s0 queued for
                # the same browser page, s1_s0 waited 36 s) and its result
                # never settled the failed parent.
                if isinstance(_s, QueueItem) and getattr(_s, "is_subloop", False):
                    _fresh.append(_s)
                    continue
                _fresh.append(
                    QueueItem(
                        step_id=f"amend-{_base + _i}",
                        step_number=_base + _i,
                        description=getattr(_s, "description", ""),
                        tool=getattr(_s, "tool", None),
                        params=dict(getattr(_s, "params", None) or {}),
                        depends_on=[
                            d for d in (getattr(_s, "depends_on", None) or [])
                            if d in _done
                        ],
                        critical=getattr(_s, "critical", True),
                        objective_anchor=(
                            getattr(plan, "original_task", "") if plan else ""
                        ),
                    )
                )
            queue.items.extend(_fresh)
            self._der_amendment_count = _used + 1
            log_amendment(
                task_id=_task_id, kind="amend",
                cause="planner_driven",
                detail=f"steps={len(_fresh)} count={_used + 1}",
            )
            logger.info(
                "[DER] amendment applied: +%d step(s) (count=%d) task=%s",
                len(_fresh), _used + 1, _task_id,
            )

            # Revision signal so the frontend card reflects the extended plan â€”
            # SAME payload shape as steering (no new event types; REQ-3 AC4).
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent

                _mode = queue.mode.value if getattr(queue, "mode", None) else "full"
                # REQ-3 (T2): "amendment" is a fourth, undocumented origin â€”
                # handled generically by the "not initial" rule in
                # _resolve_card_identity rather than special-cased here.
                _card_id, _card_relation = self._resolve_card_identity(
                    _task_id, "amendment"
                )
                get_event_bus().emit(
                    IRISStreamEvent.TASK_START,
                    data=self._task_start_payload(
                        task_id=_task_id,
                        description=(
                            getattr(plan, "original_task", "") or ""
                        )[:120],
                        plan_title=self._effective_plan_title(plan),
                        mode=_mode,
                        steps=[
                            {
                                "id": it.step_id,
                                "description": it.description,
                                "status": (
                                    "done"
                                    if it.step_id in set(queue.completed_ids)
                                    else "failed"
                                    if it.step_id in set(queue.failed_ids)
                                    else "pending"
                                ),
                                "toolName": _step_tool(it),
                            }
                            for it in list(queue.items)
                        ],
                        total_steps=len(queue.items),
                        origin="amendment",
                        # REQ-3 (T2): backend-declared card identity.
                        card_id=_card_id,
                        card_relation=_card_relation,
                        conversation_id=self.conversation_id,
                            turn_id=getattr(self, "_current_turn_id", None),
                        **self._multiagent_tags(),
                    ),
                    turn_id=_task_id,
                    conversation_id=self.conversation_id,
                    session_id=_session,
                )
                # T4a (REQ-4 AC1): persist the amended card â€” full
                # cumulative queue.items (already extended with _fresh
                # above), not the wire delta (same reasoning as the
                # user_steering site).
                self._persist_card_snapshot(
                    card_id=_card_id,
                    conversation_id=self.conversation_id,
                    card_relation=_card_relation,
                    plan_title=self._effective_plan_title(plan),
                    mode=_mode,
                    steps=self._queue_steps_snapshot(queue),
                    total_steps=len(queue.items),
                    terminal_state="running",
                )
            except Exception:
                pass  # never block an amendment on an emit failure
            return True
        except Exception as _amend_exc:  # noqa: BLE001 â€” refusal, never a crash
            log_amendment(
                task_id=_task_id, kind="refused",
                cause="error", detail=str(_amend_exc)[:200],
            )
            return False


    def _emit_steering_ack(self, channel, message_id, status, _session) -> None:
        """REQ-15 AC5 (T26): visible acknowledgement that a steering message
        landed ("queued") or was considered at a step boundary ("considered").
        Best-effort â€” never blocks or breaks the loop."""
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.STEERING_ACK,
                data={
                    "channel": channel,
                    "message_id": message_id,
                    "status": status,
                },
                turn_id=self.conversation_id or _session,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
        except Exception:
            pass

    def _der_suspend_task(self, _session, plan, queue, _turn_id) -> str:
        """REQ-15 AC4 (T26): suspend execution at the next step boundary.

        Persists the in-progress state (ledger lifecycle ``paused`` + a
        ``task:paused`` event), then waits for a ``resume`` or ``stop``
        record. Steer records arriving while suspended STAY queued and are
        applied at the next boundary after resume â€” they are never dropped.
        Idempotent resume: ``completed_ids``/``vetoed_ids``/``failed_ids``
        ARE the persisted in-progress state; ``next_ready`` skips them, so
        no completed side effect is duplicated on resume.

        Returns "resume" or "stop". Runs on the DER worker thread â€” the
        bounded poll (time.sleep) never blocks the event loop.
        """
        from backend.agent.der_execution_ledger import ExecutionLedger
        from backend.agent.event_bus import get_event_bus, IRISStreamEvent
        from backend.agent.steering import get_steering_inbox
        import time as _time

        # getattr, not attribute access: these run on the graft/recovery paths,
        # and a kernel built via __new__ (as the DER test doubles and some
        # recovery paths do) has no conversation_id. A bare access raised
        # AttributeError inside the graft's try/except, silently turning
        # "amend the graph" into "recovery failed" â€” telemetry must never be
        # able to cost a graft.
        _task_id = getattr(self, "conversation_id", None) or _session
        try:
            _ledger = getattr(self, "_der_ledger", None)
            if _ledger is None:
                _ledger = ExecutionLedger(
                    conversation_id=_task_id,
                    storage_path=_der_ledger_storage_path(),  # T9 (REQ-14 AC1)
                )
                self._der_ledger = _ledger
            _ledger.transition(_task_id, "paused")
            _ledger.persist()
        except Exception as _pe:
            logger.debug("[DER] pause lifecycle persist failed: %s", _pe)

        try:
            get_event_bus().emit(
                IRISStreamEvent.TASK_PAUSED,
                data={"task_id": _task_id, "state": "paused"},
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
        except Exception:
            pass  # EventBus optional â€” never block the loop

        inbox = get_steering_inbox()
        self._der_resume_requested = False
        while not self._der_stop_requested:
            if inbox.pending_channel(_session, "stop"):
                for _rec in inbox.drain_channel(_session, "stop"):
                    self._emit_steering_ack(
                        _rec.channel, _rec.message_id, "considered", _session
                    )
                self._der_stop_requested = True
                return "stop"
            if inbox.pending_channel(_session, "resume"):
                for _rec in inbox.drain_channel(_session, "resume"):
                    self._emit_steering_ack(
                        _rec.channel, _rec.message_id, "considered", _session
                    )
                self._der_resume_requested = True
                try:
                    _ledger = getattr(self, "_der_ledger", None)
                    if _ledger is not None:
                        _ledger.transition(_task_id, "running")
                        _ledger.persist()
                except Exception:
                    pass
                try:
                    get_event_bus().emit(
                        IRISStreamEvent.TASK_RESUMED,
                        data={"task_id": _task_id, "state": "running"},
                        turn_id=_turn_id,
                        conversation_id=self.conversation_id,
                        session_id=_session,
                    )
                except Exception:
                    pass
                return "resume"
            try:
                _time.sleep(0.2)  # poll â€” DER runs on a worker thread
            except Exception:
                break
        return "stop"

    def _build_crawl_failure_explanation(self, plan: "CrawlPlan") -> str:
        """User-facing explanation when the crawl plan found no usable sources.

        Called from the zero-steps fallback in ``_execute_plan_der``.  Returns
        a sentence explaining *why* the agent couldn't search the web, which
        ``_plan_task`` surfaces via the structured-response speak field.
        """
        _query = getattr(plan, "title", "") or ""

        # PREFER THE REASON THE PLANNER ACTUALLY RECORDED.
        # CrawlPlanner._empty_plan writes a specific cause into `instructions`
        # (e.g. "the provider rate window was already saturated (recent 429s)
        # ... retry the search shortly") precisely so the failure is reported
        # honestly. This function used to discard it and always emit the
        # bot-blocked guess below â€” so a user hitting a 60-second rate limit
        # was told to REPHRASE THEIR QUERY, which cannot help and sends them
        # down the wrong path. Only fall back to the generic text when the
        # planner did not say why.
        _reason = (getattr(plan, "instructions", "") or "").strip()
        if _reason and "LLM planning was skipped" in _reason:
            return (
                f"The agent could not search the web for {_query!r}. {_reason}"
            )

        _msg = (
            f"The agent was unable to find accessible web sources for "
            f"{_query!r}. This can happen when all generated URLs belong to "
            f"sites that block automated crawlers (academic publishers, "
            f"login-required portals, or bot-protected domains). "
            f"Try rephrasing your query to target public, accessible sites "
            f"such as news articles or Wikipedia."
        )
        return _msg[:400]

    # â”€â”€ REQ-4 (specs/dag-node-execution-model): outcome-driven routing â”€â”€â”€â”€â”€
    # The DER seam the node model adds: when a step fails with a typed reason,
    # consult the router BEFORE the graft/split handler. A recovery node that
    # advertises the reason runs in place of the failing node â€” no branch is
    # written in the failing node's module (design D4). Returns the recovered
    # step result on success, None when routing is disabled / declined / no
    # candidate â€” in which case the caller proceeds exactly as today (REQ-7
    # AC4/AC5 kill-switch parity).
    def _der_enqueue_recovery(
        self, item, recovery, step_result, _session, _turn_id, outcome, tool, queue,
    ) -> Optional[str]:
        """Session-319 (owner decision: "the job board"): enqueue a recovery step
        instead of running it inline.

        Returns ``None`` ALWAYS. The failing step must settle honestly â€” it really
        did fail â€” and the recovery then runs later as its OWN step, carrying its
        own envelope. That is what AC9.5/AC9.6 require: recovery is a separate
        step, and the brain never waits on it.

        Why this replaced the inline form: inline blocked the failing step for the
        whole recovery (including a measured ~33 s Chromium cold start) and built
        no envelope, so the recovery was invisible to the ledger.

        Never raises: a recovery that cannot be queued degrades to the normal
        failure path rather than breaking the DER loop.
        """
        try:
            from backend.agent.der_loop import QueueItem
            from backend.agent.nodes.telemetry import log_routing_decision

            try:
                from backend.agent.der_constants import RECOVERY_PAGE_BUDGET
                _budget = max(int(RECOVERY_PAGE_BUDGET), 1)
            except Exception:
                _budget = 25

            _env = getattr(item, "envelope", None)
            _conv = self.conversation_id or ""
            _visited = set(
                getattr(self, "_der_crawled_urls", {}).get(_conv, set())
            )
            _dead, _hosts, _cands = _recovery_candidates(
                step_result, list(getattr(_env, "sources", []) or []), _visited,
            )
            if not _hosts:
                return None

            # ONE CREW PER BUILDING (owner, session-319): claim the host
            # ATOMICALLY. Same budget the bespoke lane uses, so the two lanes can
            # never both open a crew for one host.
            with _der_recovery_lock:
                _ro = dict(getattr(self, "_der_recovery_opened", {}))
                _opened = set(_ro.get(_conv, set()))
                _claim = {h for h in _hosts if h not in _opened}
                if not _claim:
                    return None
                _ro[_conv] = _opened | _claim
                self._der_recovery_opened = _ro

            _host0 = sorted(_claim)[0]
            _rec_item = QueueItem(
                step_id=f"recovery_{getattr(item, 'step_id', 's')}",
                step_number=int(getattr(item, "step_number", 1) or 1) + 1,
                description=(
                    f"Recover dead fetch from {_host0}: crawl "
                    f"{len(_cands)} unvisited in-site page(s) via "
                    f"{recovery.name} ({', '.join(sorted(_claim))})."
                ),
                # The ROUTER chose the node, so no resolver pass is needed and
                # `tool` is known at build time.
                tool=recovery.name,
                params={
                    "seed_urls": list(_cands)[:_budget],
                    "max_pages": _budget,
                    "recovery_of": getattr(item, "step_id", ""),
                },
                parallel_safe=False,
                objective_anchor=getattr(item, "objective_anchor", "") or "",
                expected_output=(
                    f"Usable content from {_host0} covering: "
                    f"{(getattr(item, 'expected_output', '') or '')[:120]}"
                ),
                declared_criticality=(
                    getattr(item, "declared_criticality", "supporting")
                    or "supporting"
                ),
                recovery_of=getattr(item, "step_id", ""),
                recovery_seeds=list(_cands),
            )
            queue.add_item(_rec_item)
            # Taxonomy CONTROL: the router chose another way after a node failure;
            # trigger = the NodeOutcome Reason (closed lattice).
            _emit_event(
                self, "PIVOT", evidence="verifier", thread_id=_session,
                trigger=outcome.reason.value, step_index=str(getattr(item, "step_id", "") or ""),
                action_signature=f"{recovery.name}:{_host0}",
                payload={"from_tool": tool, "to_tool": recovery.name,
                         "recovery_step": _rec_item.step_id},
            )
            logger.info(
                "[DER:recovery] ENQUEUED (job board): parent=%s node=%s dead=%d "
                "host=%s seeds=%d",
                getattr(item, "step_id", "?"), recovery.name,
                len(_dead), _host0, len(_cands),
            )
            try:
                from backend.agent.write_counters import bump as _bump_ropen
                _bump_ropen("envelope.recovery_opens")
            except Exception:
                pass
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                get_event_bus().emit(
                    IRISStreamEvent.TASK_PROGRESS,
                    data={
                        "add_step": True,
                        "step_id": _rec_item.step_id,
                        "step_number": _rec_item.step_number,
                        "description": _rec_item.description[:200],
                        "tool_name": recovery.name,
                        **self._card_envelope(_turn_id),
                    },
                    turn_id=_turn_id,
                    conversation_id=self.conversation_id,
                )
            except Exception:
                pass
            log_routing_decision(
                task_id=self.conversation_id or _session,
                step_id=item.step_id, node=tool,
                reason=outcome.reason.value,
                candidates=[recovery.name],
                selected=recovery.name,
            )
        except Exception as _enq_exc:  # noqa: BLE001 â€” must never break the loop
            logger.warning(
                "[DER:recovery] enqueue failed for %s: %s",
                getattr(item, "step_id", "?"), _enq_exc,
            )
        return None

    def _der_route_step_failure(
        self,
        item: "QueueItem",
        step_result: str,
        _session: str,
        _turn_id: Optional[str],
        plan,
        queue=None,
    ) -> Optional[str]:
        try:
            from backend.agent.nodes.router import (
                RouteRequest,
                get_node_router,
                routing_enabled,
            )
            from backend.agent.nodes.runner import outcome_from_crawler_error
            from backend.agent.tool_registry import get_node_spec, resolve_tool

            if not routing_enabled():
                return None  # kill switch â€” today's path (REQ-7 AC4/AC5)
            tool = getattr(item, "tool", None)
            if not tool:
                # A node step has no item.tool: route on the call that failed
                # it (its decisive call, only when that call did fail). Before,
                # every node failure skipped the node router (DER_DAG.md seam 2).
                _dc = _step_decisive_call(item)
                tool = _dc.get("tool") if _dc and not _dc.get("ok", True) else None
            if not tool:
                return None  # reasoning steps have no tool to route on
            spec = resolve_tool(tool)
            if spec is None:
                return None  # undeclared legacy tool â€” adapter path (REQ-7 AC1)
            node_spec = get_node_spec(tool)
            if node_spec is None:
                return None  # tool exists but never declared node metadata

            # Map the free-form failure text to a typed reason (REQ-1 AC3).
            outcome = outcome_from_crawler_error(step_result or "", time.time())
            # CT-3 (REQ-1 AC5): the typed reason reaches the EXISTING
            # node-record/error_type machinery, not a parallel structure.
            item.error_type = outcome.reason.value

            req = RouteRequest(
                task_id=self.conversation_id or _session,
                step_id=item.step_id,
                node=tool,
                outcome=outcome,
                # REQ-8 AC1/AC2: a recovery node may not exceed the tier the
                # user approved for THIS step â€” the failing node's own tier.
                approved_tier=node_spec.permission_tier,
            )
            decision = get_node_router().route(req)
            if decision is None or decision.selected is None:
                return None  # honest no-candidate (REQ-4 AC6) or blocked
            if decision.blocked_by in ("permission", "terminal", "bound"):
                # REQ-8 edge: a permission-blocked route is surfaced, never
                # taken silently â€” the caller proceeds on today's path and the
                # normal failure handling (graft / ask) applies.
                return None

            recovery = decision.selected
            # â”€â”€ Session-319 (owner decision: "the job board") â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # ENQUEUE the recovery as its OWN STEP instead of running it inline.
            #
            # WHY: the inline form below blocks the failing step for the whole
            # recovery â€” including a measured ~33 s Chromium cold start â€” which
            # violates AC9.6 ("the brain never waits on the recovery lane"), and
            # it builds no envelope of its own, so the recovery is invisible to
            # the ledger. Queuing fixes both: the failing step settles honestly
            # and the recovery runs as its own step with its own envelope.
            # The old inline form (run the recovery node here, blocking the
            # loop) was removed 2026-10-12: every production caller passes the
            # queue, so it only ran for callers that did not exist.
            if queue is None:
                return None
            return self._der_enqueue_recovery(
                item, recovery, step_result, _session, _turn_id,
                outcome, tool, queue,
            )
        except Exception as _route_err:  # noqa: BLE001 â€” routing must never break the loop
            logger.warning("[DER] routing consultation failed: %s", _route_err)
            return None

    def _der_handle_step_failure(
        self,
        item: "QueueItem",
        queue,
        plan,
        _session: str,
        _turn_id: Optional[str],
        context_package,
        step_result: Optional[str] = None,
    ) -> None:
        """
        Handle a step that failed after its single retry.

        Always marks the step failed and aborts any downstream steps that
        depend on it (so the scheduler skips them). If the step was critical
        and we haven't exhausted the graft budget, asks the LLM to design a
        recovery sub-graph and injects those steps into the queue.
        """
        queue.mark_failed(item.step_id)
        aborted = queue.abort_descendants(item.step_id)
        # â”€â”€ REQ-17 AC17.1 + REQ-11 AC11.1/AC11.2 (T21/T14 wiring) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # This is the ONE failure-triage seam: a step that failed after its
        # retry lands here from both loop sites (the main step loop and the
        # extra-step loop). BEFORE the recovery sub-graph is planned below it
        # consults the `recovery_strategy` triage consumer (AC17.1). The T14
        # graft failure veto that was also seeded here is RETIRED (2026-11-09,
        # tool_decision.resolve docstring has the measurement). The consult is
        #       SHADOW: the row is recorded and the counters / the existing
        #       graft path still decide (AC17.2), so a confident `retry_same`
        #       can never route a repeat the counters would have escalated.
        # Best-effort â€” an advisory triage must never block a recovery.
        try:
            _triage_box = self._get_tool_box()
            _triage_tool = str(_step_tool(item) or "")
            _triage_obj = (
                getattr(item, "objective_anchor", "")
                or getattr(item, "description", "")
                or ""
            )
            _triage_box.recovery_strategy(
                failed_tool=_triage_tool,
                error_snippet=str(step_result or "")[:200],
                objective=_triage_obj,
            )
        except Exception as _triage_err:  # noqa: BLE001 â€” advisory only
            logger.debug("[DER] failure triage consult failed: %r", _triage_err)
        # AC2.1/AC9.3 (session-319 fix): a failed step must still teach turn
        # memory the addresses it touched. Finalize (which used to be the only
        # writer) is skipped on this path, so without this call a partially
        # successful crawl that was then judged FAILED contributed nothing and
        # the next step re-fetched the same URLs â€” the owner's reported symptom.
        try:
            _n_urls = _remember_turn_urls(self, step_result, "step-failure")
            if _n_urls:
                logger.info(
                    "[DER] failure path recorded URLs for %s "
                    "(turn memory now holds %d address(es))",
                    item.step_id, _n_urls,
                )
        except Exception:
            pass
        # Goal contract T9 (REQ-5 AC5.1): the failure path SKIPS finalize, so
        # the finalize-site blocking twin never runs here. A FAILED settle
        # with a terminal typed reason blocks the facts it was working on â€”
        # same helper, same denominator semantics. Advisory, never raises.
        try:
            _gc_reason = str(getattr(item, "error_type", "") or "")
            if _gc_reason:
                self._goal_contract_block_facts(
                    item, _gc_reason, str(step_result or ""),
                )
        except Exception:
            pass
        # Goal contract T15 / REQ-11 AC11.3-AC11.5: a fail-fast or blocked
        # step must TEACH â€” the failure path skips finalize, so none of its
        # learning hooks run here. Gated on blocked reasons only (fail-fast +
        # blocked steps, never ordinary retries): verified_label FAILED feeds
        # the causal scorer (_der_score_step_outcome â†’ edge scoring + AVOID
        # episode), task:learning emits the reviewer's signal, and the
        # failure-class graph walk gets its link. All best-effort, never
        # blocking; a fail-fast with no mediator records "none" via the
        # existing _der_mediator_for path (AC11 edge).
        try:
            _gc_learn_reason = str(getattr(item, "error_type", "") or "")
            _gc_learn = False
            if _gc_learn_reason:
                try:
                    from backend.agent import goal_contract as _gc_learn_mod

                    _gc_learn = bool(
                        _gc_learn_mod.is_blocked(_gc_learn_reason)
                    )
                except Exception:
                    _gc_learn = False
            if _gc_learn:
                try:
                    self._der_score_step_outcome(
                        item, "FAILED", _session, str(step_result or "")
                    )
                except Exception:
                    pass
                try:
                    from backend.agent.event_bus import (
                        get_event_bus as _gleb,
                        IRISStreamEvent as _gl_ev,
                    )

                    _gleb().emit(
                        _gl_ev.TASK_LEARNING,
                        {
                            "session_id": _session,
                            "step_id": getattr(item, "step_id", ""),
                            "step_number": getattr(item, "step_number", 0),
                            "signal": "avoided",
                            "verified_label": "FAILED",
                            "description": getattr(item, "description", "") or "",
                            "is_subloop": bool(
                                getattr(item, "is_subloop", False)
                            ),
                            "reason": _gc_learn_reason,
                        },
                    )
                except Exception:
                    pass
                try:
                    _gc_links = getattr(self, "_der_links", None)
                    _gc_rec = getattr(item, "node_record", None)
                    if _gc_links is not None and _gc_rec is not None:
                        # D1: on the memory lane, never the answer path.
                        from backend.utils.durability_queue import lane as _durability_lane

                        _durability_lane("memory_events").submit(
                            "der_node_links", _gc_links.write_node_links,
                            item,
                            _gc_rec,
                            step_success=False,
                            step_result=str(step_result or ""),
                            execution_domain=getattr(
                                _gc_rec, "execution_domain", "der"
                            ),
                            session_id=_session or "",
                        )
                except Exception:
                    pass
        except Exception:
            pass
        if aborted:
            logger.info(
                "[DER] Aborted %d downstream step(s) after failure of %s: %s",
                len(aborted), item.step_id, aborted,
            )
        # Phase 2 (D2.1) + Spec D1.2: critical failure recovery uses the SAME
        # unified _split_step operator as the physics trigger â€” NOT a separate
        # graft path that assigns tools directly. Children carry tool=None and
        # resolve via the single resolver (explorer.propose) when executed, so
        # there is exactly ONE tool-assignment authority (F6 / System Invariant).
        # D4/REQ-4 (specs/long-horizon-der-execution): classify the failure
        # BEFORE recursive fan-out at the FAILURE site too. The finalize site
        # classifies, but this handler previously split on ANY critical
        # failure â€” a rate-limited crawl (transient) or an empty URL list
        # (empty/permanent) recursively spawned graft children that re-ran the
        # same failing tool until the graft budget was exhausted (observed
        # live: 23-minute websearch loop under a saturated provider window).
        # Only a genuine semantic failure (tool produced content but
        # verification judged it wrong) splits: the step_result then carries
        # real content, not an error prefix. Mirror the finalize site: classify
        # only when the result LOOKS like an error (classify_failure never
        # returns semantic â€” it falls through to permanent), and broaden the
        # error prefixes for failure-site shapes ("RateLimitedError(...)" /
        # "ConnectionError(...)" do not start with "error").
        _split_ok = True
        try:
            from backend.agent.der_execution_ledger import (
                classify_failure,
                ExecutionLedger,
                OUTCOME_TRANSIENT,
                OUTCOME_UNAVAILABLE,
                OUTCOME_INVALID_ARGS,
                OUTCOME_EMPTY,
                OUTCOME_PERMANENT,
            )

            _res_text = (step_result or "").strip()
            _res_low = _res_text.lower()
            _tool_errored = (
                not _res_text
                or _res_low.startswith("error")
                or _res_low.startswith("ratelimitederror")
                or _res_low.startswith("connectionerror")
                or _res_low.startswith("timeouterror")
                or _res_low.startswith("[step error")
                or _res_low.startswith("duplicate call")
                # Session-331: the crawler's terminal park/failure shapes were
                # MISSING here, so they fell through _tool_errored=False and the
                # step was treated as a SEMANTIC failure -> grafted a retry that
                # deterministically failed the same way (live T2: crawler_query
                # "no candidate urls" grafted 3x on a search-engine wall). These
                # are environmental/terminal, never semantic.
                or _res_low.startswith("no candidate")
                or _res_low.startswith("no usable")
                or "sources parked" in _res_low
                or "wall=" in _res_low
                or _res_low.startswith("permission")
                or _res_low.startswith("denied")
            )
            if _tool_errored:
                _fail_class = classify_failure(
                    False,
                    error=_res_text[:400],
                    error_type=getattr(item, "error_type", None),
                    result=step_result,
                )
                if _fail_class in (
                    OUTCOME_TRANSIENT,
                    OUTCOME_UNAVAILABLE,
                    OUTCOME_INVALID_ARGS,
                    OUTCOME_EMPTY,
                    OUTCOME_PERMANENT,
                ):
                    _split_ok = False
                    logger.info(
                        "[DER] step %s failure classified=%s â€” recorded, NOT split (D4)",
                        item.step_id, _fail_class,
                    )
                    try:
                        _ledger = getattr(self, "_der_ledger", None)
                        if _ledger is None:
                            _ledger = ExecutionLedger(
                                conversation_id=self.conversation_id or "",
                                storage_path=_der_ledger_storage_path(),  # GROUND TRUTH T9 (REQ-14 AC1)
                            )
                            self._der_ledger = _ledger
                        _ledger.record_failure(
                            task_id=self.conversation_id or self.session_id or "unknown",
                            step_id=item.step_id,
                            attempt_id=getattr(item, "attempt_id", "") or item.step_id,
                            failure_class=_fail_class,
                            input_summary=(item.description or "")[:200],
                            tool=_step_tool(item),
                            error_type=getattr(item, "error_type", None),
                            error_summary=_res_text[:300],
                            recovered=False,
                        )
                    except Exception as _led_exc:  # noqa: BLE001
                        logger.debug("[DER] failure-evidence record failed: %s", _led_exc)
        except Exception:  # noqa: BLE001 â€” classification must never break recovery
            _split_ok = True
        # Item 3 (2026-09-24, owner-approved): an UNRECOVERABLE failure is not
        # grafted. Live conv-144: a read step failed with "[Errno 2] No such
        # file or directory" and the loop grafted THREE times â€” every sub-loop
        # failed the same way â€” because no retry can create a missing file. One
        # honest failure is the correct outcome; the failure stays recorded and
        # shown (never hidden). Any error here falls through to the graft,
        # preserving the pre-existing behaviour exactly.
        try:
            from backend.agent.tool_decision import _goal_records_terminal_failure

            _terminal_failure = _goal_records_terminal_failure(_res_text)
        except Exception:  # noqa: BLE001 â€” classification must never break recovery
            _terminal_failure = False
        if _terminal_failure:
            logger.info(
                "[DER] critical step %s failed with an unrecoverable cause â€” "
                "no graft, finalizing honestly: %s",
                item.step_id, (_res_text or "")[:120],
            )
            # â”€â”€ FEED recovery_strategy ON THE TERMINAL PATH TOO (2026-09-27) â”€â”€
            # The triage consult lives ONLY on the graft path above, so a
            # terminal failure recorded NO row for recovery_strategy. Measured
            # live: [WinError 3] on an invented path -> "unrecoverable cause -
            # no graft" -> zero recovery rows while TTS announced "I couldn't
            # complete that task. 0/1 steps finished". The consumer was blind to
            # exactly the failures it exists to triage.
            # Safe to consult here: the triage is SHADOW (AC17.1/AC17.2/The
            # documented contract at the graft seam) - it records a row and its
            # verdict decides nothing - so a terminal failure still finalizes
            # honestly, unchanged. A failure that happened is a failure that
            # gets triaged.
            try:
                _tt_box = self._get_tool_box()
                _tt_tool = str(getattr(item, "tool", "") or "")
                _tt_obj = (
                    getattr(item, "objective_anchor", "")
                    or getattr(item, "description", "")
                    or ""
                )
                _tt_box.recovery_strategy(
                    failed_tool=_tt_tool,
                    error_snippet=str(_res_text or "")[:200],
                    objective=_tt_obj,
                )
            except Exception as _tt_err:  # noqa: BLE001 â€” advisory only
                logger.debug(
                    "[DER] terminal-failure triage consult failed: %r", _tt_err
                )
        # ONE repair per failure: the node router may already have queued a
        # recovery step for it (_der_enqueue_recovery, the dead-fetch crawl).
        # The graft split ran beside it with no check - two crews on one
        # failure (ripple map, 2026-10-12).
        _recovery_queued = any(
            getattr(_qi, "recovery_of", "") == item.step_id
            for _qi in (getattr(queue, "items", None) or ())
        )
        if _recovery_queued:
            logger.info("[DER] %s failed - a recovery step is queued; no graft split",
                        item.step_id)
        if (
            _split_ok
            and item.critical
            and not _terminal_failure
            and not _recovery_queued
            and queue.graft_attempts < DER_MAX_GRAFTS
        ):
            # â”€â”€ Session 247: GOAL-SUFFICIENCY GATE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Before grafting another round of gather children, ask the one
            # question the loop never asked: do the findings ALREADY collected
            # satisfy the objective? Live evidence (conv-41, session 247): a
            # websearch task ran 18 dispatch rounds over 30+ minutes because
            # every verify_failed grafted more search steps even after the
            # crawls had returned plenty of usable content â€” per-step
            # verification could see each step in isolation, but nothing ever
            # assessed goal-level sufficiency of the accumulated whole. When
            # the gate says sufficient, skip the graft: the loop proceeds to
            # synthesis over what it has (the failed step stays recorded as a
            # failure â€” failure recorded AND shown, never hidden).
            # Advisory on failure: any gate error falls through to the graft,
            # preserving the pre-existing behavior exactly.
            # What the step DID (_step_calls), not item.tool: a node step has
            # no tool (since 2026-09-29), so this gate - and the `sufficient`
            # consumer behind it - never ran again (last row 2026-09-29;
            # found 2026-11-10).
            if any(str(c.get("tool") or "").lower() in self._DER_GATHER_TOOLS
                   for c in _step_calls(item)):
                try:
                    # Session 248 FIX (live conv-53): the gate digested only
                    # COMPLETED steps - but the failed step ITSELF may carry
                    # the findings (a crawler_query that fetched 3 usable
                    # pages yet failed verification). Excluding it made the
                    # gate judge an empty evidence set, graft a full re-crawl
                    # of the SAME query, and double the search time. The
                    # failing step's own result is appended to the digest so
                    # the gate sees everything the loop has actually seen.
                    # Session 365 FIX: `completed_items` is NOT a parameter of
                    # this method â€” it is a local of `_execute_plan_der` â€” so
                    # this line raised NameError on EVERY failed gather step.
                    # The bare `except` below swallowed it, so the gate
                    # silently returned False forever: `_der_findings_sufficient`
                    # was never actually called and the `sufficient` consumer
                    # could never emit a row, no matter how much gather traffic
                    # was driven at it. Reconstruct the completed items from the
                    # queue, exactly as the rest of this file does
                    # (`step_id in queue.completed_ids`, cf. the step-status
                    # derivation and the budget-exhausted remaining count).
                    _completed_ids = set(
                        getattr(queue, "completed_ids", None) or ()
                    )
                    _gate_items = [
                        _gi for _gi in (getattr(queue, "items", None) or ())
                        if getattr(_gi, "step_id", None) in _completed_ids
                    ] + [item]
                    _suff, _missing = self._der_findings_sufficient(
                        plan.original_task or "", _gate_items
                    )
                except Exception:
                    _suff, _missing = False, ""
                if _suff:
                    logger.info(
                        "[DER] sufficiency gate TRIPPED for %s â€” accumulated "
                        "findings satisfy the objective; graft skipped "
                        "(missing: %s)", item.step_id, (_missing or "none")[:120],
                    )
                    return aborted
                logger.debug(
                    "[DER] sufficiency gate open for %s (missing: %s)",
                    item.step_id, (_missing or "unassessed")[:120],
                )
            try:
                # Fold-back: split width is a shape decision (side lane).
                _der_physics_settle(self, _session)
                _cad = self._der_live_cad_state(_session)
                _wu = getattr(self, "_der_work_units", 0)
                # REQ-4 AC1 (T16): continuous verified fraction as a GRADED
                # steering input at the split decision (mid-band -> bounded
                # probe). Never crash the split on fraction failure.
                try:
                    _vf_split = self._verified_fraction(
                        getattr(item, "expected_output", None),
                        str(step_result or ""),
                    )
                except Exception:
                    _vf_split = 0.0
                _children = self._split_step(
                    item,
                    "verify_failed",
                    _cad,
                    _wu,
                    step_result=step_result,
                    verified_fraction=_vf_split,
                )
                if _children:
                    # REQ-5 (dag-node-execution-model): grafted recovery steps
                    # ARE an amendment of the executing graph, so they go
                    # through the amendment gate rather than around it. This is
                    # _der_amend_graph's production caller â€” without one the
                    # mechanism was built, tested and unreachable.
                    #
                    # Behaviour is unchanged by construction: _AMENDMENT_BOUND
                    # and DER_MAX_GRAFTS are both 3, so the gate admits exactly
                    # the grafts that already ran. What it adds is REQ-5's
                    # guarantees on a path that previously had none â€” validity
                    # checking, the per-task bound, and telemetry for every
                    # applied AND refused amendment (REQ-5 AC5, REQ-9 AC3).
                    if not self._der_amend_graph(
                        _children, _session, plan, queue, _turn_id=_turn_id,
                    ):
                        logger.info(
                            "[DER] amendment refused for failed %s â€” continuing "
                            "on the existing graph (REQ-5 AC5)", item.step_id,
                        )
                        return aborted
                    queue.graft_attempts += 1
                    # The gate queued the children themselves; they run as
                    # nodes (their own tool loops). Routing them again here
                    # queued each child twice.
                    # Fold-back (parallel nodes, 2026-10-04): the failed step
                    # waits for its children instead of failing, and the
                    # dependents its failure aborted wait again - the first
                    # VERIFIED child completes it (_der_settle_split).
                    queue.hold_split_parent(
                        item.step_id, [c.step_id for c in _children], aborted,
                    )
                    aborted = []
                    # REQ-3: debit measured tokens, not a flat child count.
                    _result_len = len(step_result) if step_result else 0
                    _measured = max(200, _result_len // 4)
                    self._der_work_units = debit_work_units(_wu, _measured)
                    try:
                        from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                        get_event_bus().emit(
                            IRISStreamEvent.RECOVERY_START,
                            data={
                                "failed_step": item.step_id,
                                "graft_attempts": queue.graft_attempts,
                                "num_grafted": len(_children),
                                "critical": item.critical,
                            },
                            session_id=_session,
                        )
                    except Exception:
                        pass
                    logger.info(
                        "[DER] Critical-failure recovery -> split into %d sub-loop(s) "
                        "for failed %s (graft_attempts=%d, work_units=%d)",
                        len(_children), item.step_id, queue.graft_attempts,
                        self._der_work_units,
                    )
            except Exception as _graft_exc:
                logger.warning("[DER] critical-failure split failed: %s", _graft_exc)
        # â”€â”€ REQ-5 (specs/long-horizon-der-execution): honest partial finalization â”€â”€
        # When the recovery budget is exhausted, the task does NOT block on a
        # TASK_BLOCKED card / ask_user QuestionCard (that escalation came from
        # the deleted der-loop-integrity-display REQ-10; the long-horizon spec
        # supersedes it: "IF budget ends before completion THEN emit remaining
        # nodes and their last failure class"). The step is already marked
        # failed, descendants already aborted, failure evidence already
        # recorded â€” the DER loop's final summary carries the remaining nodes
        # with their failure classes and the honest incomplete result.
        # Not when THIS failure just spent the last graft: the step waits on
        # its children then (live amend-7, 2026-10-12: this line said
        # "finalizing honestly" in the same second the third graft ran).
        if (item.critical and queue.graft_attempts >= DER_MAX_GRAFTS
                and item.step_id not in (getattr(queue, "split_pending", None) or {})):
            logger.info(
                "[DER] REQ-5: critical step %s failed after %d grafts â€” "
                "finalizing honestly with remaining nodes + failure class",
                item.step_id, queue.graft_attempts,
            )
        # M2 FIX: record non-critical failures to memory and signal Caducean
        # so drift detection accounts for them (otherwise Q never rises on
        # repeated non-critical failures and TOPO_VIOLATION never fires).
        # PACMAN alignment: a failure pattern is the user's own hard-won lesson
        # (corrective action encoded) -> it belongs in the TRUSTED membrane
        # (PACMAN.md: trusted://episodic/failures, Tier 3), NOT an off-membrane
        # "der_failure" zone the router cannot navigate/tier. chunk_type stays
        # "der_failure" as the content-type discriminator; zone is the membrane.
        if not item.critical:
            try:
                if self._memory_interface and item.result:
                    _ep = self._memory_interface.episodic
                    if hasattr(_ep, "fragment_and_store"):
                        # D1: on the memory lane, never the answer path.
                        from backend.utils.durability_queue import lane as _durability_lane

                        _durability_lane("memory_events").submit(
                            "der_failure_fragment", _ep.fragment_and_store,
                            content=f"[NON-CRITICAL FAIL Step {item.step_number}: "
                                    f"{item.description[:80]}]\n{item.result[:500]}",
                            session_id=_session,
                            chunk_type="der_failure",
                            zone="trusted",
                        )
            except Exception as _frag_exc:  # noqa: BLE001 - a note never blocks the loop
                logger.warning("[DER] non-critical der_failure note for %s failed: %r",
                               item.step_id, _frag_exc)
            try:
                from backend.gateway.iris_ffi import ffi_caducean_update

                # REQ-19 vocabulary: this "COMPRESS" (action=1) is the COMPRESS
                # RECOMMENDATION â€” a physics action code that increments the
                # failure accumulator y. It COMPACTS NOTHING. See the REQ-19
                # canonical-vocabulary table in
                # specs/long-horizon-der-execution/design.md (row 3) â€” it is
                # NOT Node Condense, NOT DCP message pruning, NOT mcm_compress.
                ffi_caducean_update(_session, 1, 1.0)
            except Exception:
                pass

    # â”€â”€ Phase 2: Emergent Shape â€” growth-width split/execute operator â”€â”€â”€â”€â”€â”€
    # This is the ONE recursive operator that decides execution-tree *shape*
    # from the live Caducean state (u,xi). It replaces the former mode-driven
    # fan-out AND the separate recovery-graft path: both physics-triggered
    # ("unresolved_u") and verification-failed ("verify_failed") splits use it.
    # MorphoHDL break: the decision is STATEFUL â€” width depends on live |u|,
    # never a fixed stateless predicate.

    def _growth_width(self, u: float) -> int:
        """Map live |u| to a split width (MorphoHDL athlete rule).

        REQ-19 vocabulary: this is STEP EXPANSION â€” the DER sub-loop split
        operator (_growth_width -> _split_step). It is NOT Node Expansion
        (scorer.expand, the mycelium coordinate-graph mechanism), NOT DER
        "COMPRESS" (a physics recommendation code, int 1), NOT DCP message
        pruning, and NOT mcm_compress (external build tooling). See the REQ-19
        vocabulary table in specs/long-horizon-der-execution/design.md.

        Bands (reconciles D2.3 with the split decision):
          |u| < U_SPLIT (0.5)   -> unresolved/oscillating -> split WIDE (3)
          U_SPLIT <= |u| < 0.85 -> mid-band: atomic step, needs LLM rubric (D2.3)
          |u| >= 0.85           -> converged: atomic, deterministic verify only
        """
        from backend.agent.der_constants import U_SPLIT, U_CONVERGED

        au = abs(u)
        if au < U_SPLIT:
            return 3
        if au < U_CONVERGED:
            return 1  # atomic; verification strictness handled by D2.3
        return 1

    def _der_split_width(self, u: float, verified_fraction: float) -> int:
        """REQ-4 AC1/AC2 (T16): GRADED split width â€” a continuous function of
        BOTH |u| and the verified fraction, not a |u|-only gate.

        The pre-T16 split width was binary in the verification dimension:
        ``_growth_width(u)`` returned 3 (wide) or 1 (atomic) purely from |u|,
        while ``verified_fraction`` was computed and then thrown away at the
        split decision. REQ-4 AC1 requires the continuous fraction to be a
        steering input; AC2 requires the graded middle path when the signal is
        mid-band â€” never a threshold coin-flip.

        Bands:
          verified_fraction <= 0.25            -> strong failure: |u| governs
                                                  (delegate to _growth_width)
          0.25 < verified_fraction < 0.75      -> MID-BAND (AC2): bounded probe
                                                  (width 1, probe=True) â€” the
                                                  step produced meaningful but
                                                  insufficient content; a wide
                                                  split would be a retry wearing
                                                  a split costume. The child
                                                  resolves the specific blocker
                                                  (REQ-4 AC4/T16b) at width 1.
          verified_fraction >= 0.75            -> near-pass: atomic (1) â€” the
                                                  result satisfied most of the
                                                  expected output; a wide split
                                                  spends budget re-attempting a
                                                  step that nearly passed.

        The caller marks the child ``probe=True`` when this method returns a
        width-1 mid-band probe (see _split_step).
        """
        if verified_fraction > 0.25:
            if verified_fraction < 0.75:
                return 1  # AC2 graded middle path: bounded probe, not a flip
            return 1  # near-pass: atomic
        return self._growth_width(u)  # strong failure: |u| bands govern

    # â”€â”€ REQ-5 (T17): coupling as decision-provenance â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Retrieval RANKS relevant branches (physics- and evidence-driven, AC3) and
    # SURFACES ALL of them (bounded by the candidate cap) to the deciding step
    # (AC1) â€” never silently pre-selecting one by score. When the step commits,
    # the edge to the branch that informed it is written/strengthened with the
    # decision as provenance (AC2), and the per-decision record (how many
    # candidates surfaced, which was chosen) is stored on the node record (AC4).

    def _der_surface_branch_candidates(
        self, item, cad: Optional[Dict[str, float]] = None, max_candidates: int = 0
    ) -> List[dict]:
        """REQ-5 AC1/AC3 (T17): rank relevant branch candidates and return ALL
        of them (bounded by the candidate cap) â€” never one, never pre-selected.

        Ranking is physics- and evidence-driven (AC3):
          - coordinate proximity to the step's live Î£ position,
          - learned score of the region->candidate edge (if one exists),
          - compression/expansion state via the EXISTING coupling kernel
            ``trig_coupling.align_force`` (AC6 â€” reuse, do not write a second
            implementation): the u term biases candidates whose phase aligns
            with the step's current direction.

        SELECTION is NOT made here â€” the step decides with all candidates in
        view; the chosen one is recorded at commit (see
        ``_der_record_coupling_decision``).

        Returns a list of dicts ``{"node_id", "label", "score"}`` capped at
        ``max_candidates`` (0 -> DER_COUPLING_CANDIDATE_CAP). Never raises:
        any failure returns [] so coupling can never block a step (REQ-10 AC5).
        """
        from backend.agent.der_constants import DER_COUPLING_CANDIDATE_CAP
        from backend.agent.trig_coupling import align_force

        cap = max_candidates or DER_COUPLING_CANDIDATE_CAP
        if cap < 1:
            return []
        if not getattr(self, "_memory_interface", None):
            return []
        try:
            _cad = cad if cad is not None else self._der_live_cad_state(
                self.session_id or ""
            )
            _vec = [
                _cad.get("x", 0.0), _cad.get("y", 0.0),
                _cad.get("xi", 0.0), _cad.get("u", 0.0),
            ]
            _u = _cad.get("u", 0.0)
            # AC6: the EXISTING coupling kernel â€” the u-term in the ranking is
            # align_force as WIRED at coupled_registry.py:287 (full phase list
            # [self, other], N=2 satisfies the mean-field guard; the self term
            # contributes sin(0)=0). The u-term is the signed attraction of the
            # step's phase toward the converged phase 0.0 â€” NOT a new formula.
            _align = align_force(_u, [_u, 0.0], k=1.0)
            # physics term normalized to [0, 1]: aligned (u>0, expanding toward
            # convergence) scores higher; anti-aligned (u<0, compressing) lower.
            _phys = 0.5 + 0.5 * max(-1.0, min(1.0, _align))
            _session = self.session_id or ""
            myc = getattr(self._memory_interface, "_mycelium", None)
            if myc is None:
                return []
            _store = getattr(myc, "_store", None)
            _nav = getattr(myc, "_navigator", None)
            _nodes = []
            # Primary candidate source: the highest-confidence node from each
            # space (navigate_all_spaces) â€” the relevant BRANCHES, one per
            # space. Fallback: active registry nodes.
            try:
                if _nav is not None and hasattr(_nav, "navigate_all_spaces"):
                    _nodes = list(_nav.navigate_all_spaces(_session))
            except Exception:
                _nodes = []
            if not _nodes:
                try:
                    _reg = getattr(myc, "_registry", None)
                    _nids = list(getattr(_reg, "get_active", lambda s: [])(_session))
                    if _nids and _store is not None:
                        _nodes = [
                            _store.get_node_by_id(_nid)
                            for _nid in _nids
                            if _store.get_node_by_id(_nid) is not None
                        ]
                except Exception:
                    _nodes = []
            _nodes = [_c for _c in (_nodes or []) if getattr(_c, "coordinates", None)]
            if not _nodes:
                return []

            _scored = []
            for _n in _nodes:
                try:
                    _coords = list(getattr(_n, "coordinates", None) or [])
                    if len(_coords) < 4:
                        continue
                    _d = sum((a - b) ** 2 for a, b in zip(_vec, _coords[:4])) ** 0.5
                    _prox = max(0.0, 1.0 - _d / 4.0)  # normalized proximity
                    _learned = 0.0
                    _nid = getattr(_n, "node_id", "") or getattr(_n, "id", "") or ""
                    # learned edge score from the region node -> candidate, if
                    # the edge exists (evidence-driven ranking).
                    try:
                        _reg_nid = self._der_region_node_id(_session)
                        if _reg_nid and _nid:
                            _edge = _store.get_edge_by_id(
                                f"{_reg_nid}:{_nid}"
                            ) if hasattr(_store, "get_edge_by_id") else None
                            if _edge is not None:
                                _learned = float(getattr(_edge, "score", 0.0) or 0.0)
                    except Exception:
                        _learned = 0.0
                    _score = _prox * 0.6 + _learned * 0.3 + _phys * 0.1
                    _scored.append({
                        "node_id": _nid,
                        "label": (getattr(_n, "label", None) or _nid)[:120],
                        "score": _score,
                    })
                except Exception:
                    continue
            _scored.sort(key=lambda c: c["score"], reverse=True)
            # REQ-5 AC5 (T17b): record the TOTAL number of relevant branches
            # found (BEFORE the cap) on the item â€” the coverage DENOMINATOR
            # for candidate-surfacing coverage ("how often a decision saw >=2
            # candidates when >=2 EXISTED"). candidates_surfaced is the capped
            # return; candidates_existed is the uncapped count. Both are needed
            # or the coverage metric cannot be measured.
            try:
                item._coupled_candidates_existed = len(_scored)
            except Exception:
                pass
            return _scored[:cap]
        except Exception as _cp_exc:  # noqa: BLE001 â€” coupling never blocks
            logger.debug("[DER] branch-candidate surfacing failed: %s", _cp_exc)
            return []

    def _der_region_node_id(self, session_id: str) -> str:
        """The mycelium node_id of the session's CURRENT region node (the ONE
        active node nearest the live Î£ position â€” REQ-26 AC1 region scoping).
        Empty string if none resolvable. Never raises."""
        try:
            myc = getattr(self._memory_interface, "_mycelium", None)
            if myc is None:
                return ""
            _reg = getattr(myc, "_registry", None)
            if _reg is None:
                return ""
            _nids = list(getattr(_reg, "get_active", lambda s: [])(session_id))
            if not _nids:
                return ""
            _store = getattr(myc, "_store", None)
            if _store is None or not hasattr(_store, "get_node_by_id"):
                return ""
            _cad = self._der_live_cad_state(session_id)
            _vec = [
                _cad.get("x", 0.0), _cad.get("y", 0.0),
                _cad.get("xi", 0.0), _cad.get("u", 0.0),
            ]
            _best, _best_d = "", None
            for _nid in _nids:
                try:
                    _n = _store.get_node_by_id(_nid)
                    if _n is None:
                        continue
                    _c = list(getattr(_n, "coordinates", None) or [])
                    if len(_c) < 4:
                        continue
                    _d = sum((a - b) ** 2 for a, b in zip(_vec, _c[:4])) ** 0.5
                    if _best_d is None or _d < _best_d:
                        _best, _best_d = _nid, _d
                except Exception:
                    continue
            return _best
        except Exception as _reg_exc:  # noqa: BLE001
            logger.debug("[DER] region-node resolve failed: %s", _reg_exc)
            return ""

    def _der_record_governance(self, source: str) -> None:
        """REQ-6 AC1/AC3 (T18): record WHICH signal governed a steering
        decision â€” past-memory | live-state | both.

        Increments the per-turn governance counter on the kernel (read by the
        caller's TurnMetrics block into the [LAYERS] line). Off the hot path
        and lossy-safe: any failure is logged at debug and never raises, and a
        missing counter silently re-initializes (AC1 edge: high-volume turns).
        The alternation ratio (AC3) is derived in TurnMetrics.to_log_line from
        the same counts.

        No decision path hardcodes which signal is authoritative (AC2): the
        recorded source is OBSERVED at the decision point â€” a step whose
        context carried a compressed node record (past-memory) AND live Î£ is
        "both"; memory-sparse (no record) is "live"; record present but no
        live signal is "past".
        """
        try:
            _gov = getattr(self, "_der_governance_counts", None)
            if _gov is None:
                _gov = {"past": 0, "live": 0, "both": 0}
            if source == "past":
                _gov["past"] = _gov.get("past", 0) + 1
            elif source == "live":
                _gov["live"] = _gov.get("live", 0) + 1
            else:  # "both" (and any unknown -> both, the equal-signals edge)
                _gov["both"] = _gov.get("both", 0) + 1
            self._der_governance_counts = _gov
        except Exception as _gov_exc:  # noqa: BLE001
            logger.debug("[DER] governance record failed: %s", _gov_exc)

    def _der_choose_coupling_branch(
        self, item, candidates: List[dict]
    ) -> str:
        """REQ-5 AC4 (T17): determine which surfaced branch the step CHOSE.

        Selection is the step's, not the system's (the rewritten REQ-5 story:
        "awareness of the alternatives, and a recorded decision, is [the
        system's business]"). The step's choice is observed from the outcome:
        the chosen branch is the candidate whose coordinates are nearest the
        step's final Î£ position (``coords_to``), i.e. the branch the step's
        result actually moved toward. Empty string when no candidate is
        nearest (no branches existed / no coords). Never raises.
        """
        from backend.agent.der_constants import DER_COUPLING_CANDIDATE_CAP

        if not candidates:
            return ""
        try:
            _coords_to = getattr(item, "coords_to", "") or ""
            _session = self.session_id or ""
            myc = getattr(self._memory_interface, "_mycelium", None)
            _store = getattr(myc, "_store", None) if myc else None
            if _coords_to and _store is not None and hasattr(
                _store, "get_node_by_id"
            ):
                _v = []
                for _part in _coords_to.strip("()").split(","):
                    try:
                        _v.append(float(_part))
                    except Exception:
                        break
                if len(_v) >= 4:
                    _best, _best_d = "", None
                    for _c in candidates[:DER_COUPLING_CANDIDATE_CAP]:
                        _nid = _c.get("node_id", "")
                        if not _nid:
                            continue
                        try:
                            _n = _store.get_node_by_id(_nid)
                            _cvec = list(getattr(_n, "coordinates", None) or [])
                            if len(_cvec) < 4:
                                continue
                            _d = sum(
                                (a - b) ** 2 for a, b in zip(_v, _cvec[:4])
                            ) ** 0.5
                            if _best_d is None or _d < _best_d:
                                _best, _best_d = _nid, _d
                        except Exception:
                            continue
                    return _best
            # No resolvable coordinates: fall back to the top-ranked candidate
            # (the ranking is physics- and evidence-driven, AC3) so a decision
            # is still RECORDED â€” an empty choice would be an unrecorded one.
            return (candidates[0].get("node_id", "") if candidates else "")
        except Exception as _ch_exc:  # noqa: BLE001
            logger.debug("[DER] coupling-branch choice failed: %s", _ch_exc)
            return ""

    def _der_record_coupling_decision(
        self,
        item,
        candidates: List[dict],
        chosen_node_id: str = "",
        record: Optional["NodeRecord"] = None,
    ) -> None:
        """REQ-5 AC2/AC4 (T17): record a coupling decision AFTER the step
        commits. ``candidates`` is the surfaced list (all of them, capped);
        ``chosen_node_id`` is the branch the step actually committed to.

        AC2: write/strengthen the coupling edge from the step's region node to
        the chosen branch â€” the decision IS the edge's provenance. Uses the
        SAME edge store/scorer as the region->mediator learning (one store,
        one scorer â€” REQ-19 AC4); a decision is a strengthenable observation,
        not a new edge kind.
        AC4: candidates_surfaced / chosen_branch / surfaced_branches are
        stamped on the node record so "was the agent aware of both branches"
        is answerable from data. Never raises: coupling is off the critical
        path (REQ-10 AC5).
        """
        from backend.agent.der_constants import DER_COUPLING_PROVENANCE_MAX

        try:
            _count = len(candidates or [])
            _chosen = chosen_node_id or ""
            if not _count and not _chosen:
                return  # no coupling decision at this node
            _rec = record or getattr(item, "node_record", None)
            if _rec is not None:
                _rec.candidates_surfaced = _count
                _rec.chosen_branch = _chosen
                # REQ-18 AC1b (T19): a node that SURFACED >=1 candidate and
                # CHOSE one is a node that COMMITTED A DECISION â€” a valid
                # coupling endpoint. This is the ROLE marker that makes
                # "which decisions were informed by branch X" a relationship
                # lookup (REQ-20) instead of a table scan. Set only here, at
                # the coupling-decision site, so gathering/executing nodes
                # stay unmarked.
                if _count > 0:
                    _rec.committed_decision = True
                _rec.surfaced_branches = [
                    c.get("label", "") for c in (candidates or [])
                ][:DER_COUPLING_PROVENANCE_MAX]
                # REQ-5 AC5 (T17b): the DENOMINATOR for candidate-surfacing
                # coverage â€” how many relevant branches EXISTED before the cap.
                # candidates_surfaced / candidates_existed is the coverage ratio
                # ("saw >=2 when >=2 existed").
                try:
                    _rec.candidates_existed = int(
                        getattr(item, "_coupled_candidates_existed", _count) or _count
                    )
                except Exception:
                    _rec.candidates_existed = _count
            if _chosen:
                try:
                    _session = self.session_id or ""
                    _reg_nid = self._der_region_node_id(_session)
                    if _reg_nid:
                        myc = getattr(self._memory_interface, "_mycelium", None)
                        _store = getattr(myc, "_store", None) if myc else None
                        if _store is not None and hasattr(
                            _store, "record_observation"
                        ) and hasattr(_store, "get_edge_by_id"):
                            _edge_id = f"{_reg_nid}:{_chosen}"
                            _existing = _store.get_edge_by_id(_edge_id)
                            if _existing is not None:
                                # decision PROVENANCE: the informed-branch edge
                                # is strengthened by a decision observation
                                # (REQ-5 AC2) â€” delta positive, modest.
                                _store.record_observation(_edge_id, 0.1)
                            elif hasattr(_store, "upsert_edge"):
                                _new_eid = _store.upsert_edge(
                                    _reg_nid, _chosen, "informed", 0.5
                                )
                                if _new_eid:
                                    _store.record_observation(
                                        _new_eid or _edge_id, 0.1
                                    )
                except Exception as _edge_exc:  # noqa: BLE001
                    logger.debug(
                        "[DER] coupling-edge write failed: %s", _edge_exc
                    )
        except Exception as _cd_exc:  # noqa: BLE001
            logger.debug("[DER] coupling-decision record failed: %s", _cd_exc)

    def _der_verify_strictness(
        self, u: float, coverage: Optional[float] = None
    ) -> str:
        """Adaptive verification strictness by |u| band (D2.3).

        |u| < U_SPLIT  -> "wide"   : step was split; children verified individually,
                                   parent collapses on child consensus (no LLM rubric).
        U_SPLIT..0.85  -> "rubric" : atomic step, mid-band -> deterministic stub-kill
                                   PLUS LLM rubric verdict (tier-3 empowered check).
        >= 0.85        -> "atomic" : converged -> deterministic verify only (no LLM
                                   rubric; cheap, deterministic).

        Goal contract T6 (REQ-3 AC3.3): task-level coverage C is an optional
        second input. When supplied, the gap g = 1 - C acts as a forcing term
        on the effective magnitude â€” an open goal makes the state read less
        converged (stricter verification), a covered goal lets it settle.
        ``coverage=None`` preserves the exact legacy bands. The parameter is
        optional so every existing (u)-only caller keeps working unchanged.
        """
        from backend.agent.der_constants import U_SPLIT, U_CONVERGED

        au = abs(u)
        if coverage is not None:
            try:
                from backend.agent.der_constants import (
                    GOAL_FORCING_GAIN as _GOAL_GAIN,
                )

                _g = 1.0 - max(0.0, min(1.0, float(coverage)))
                au = au * max(0.0, 1.0 - float(_GOAL_GAIN) * _g)
            except Exception:
                pass
        if au < U_SPLIT:
            return "wide"
        if au < U_CONVERGED:
            return "rubric"
        return "atomic"

    def _der_split_blocker(
        self,
        item: "QueueItem",
        trigger: str,
        step_result: str = "",
    ) -> str:
        """REQ-4 AC4 (T16b): name the SPECIFIC blocker this split resolves.

        Deterministic extraction from the failure evidence (no LLM call on the
        split hot path â€” the blocker is derived, not generated):

          1. error-prefixed step_result  -> the tool failure itself
          2. verify_failed               -> the acceptance criterion that was
             NOT satisfied (expected_output, else the produced result) â€” names
             the specific gap, never the parent goal
          3. unresolved_u (physics)      -> the oscillating state itself
             (decomposition, not a failure â€” still names WHAT it resolves)
          4. empty evidence AND no expected_output -> "" (UNNAMED blocker) â€”
             the split cannot name what it resolves; recorded as such via
             blocker_named=False, surfaced as evidence the failure was not
             understood.

        Returns the blocker text, or "" when nothing can be named.
        """
        _res = (step_result or "").strip()
        _low = _res.lower()
        if _low.startswith("error") or _low.startswith("[step error") or _low.startswith(
            "duplicate"
        ):
            return f"the tool reported: {_res[:200]}"
        if _low.startswith("ratelimited") or _low.startswith("timeout") or _low.startswith(
            "connection"
        ):
            return f"transient infrastructure failure: {_res[:200]}"
        # A node's result opens with the model's summary and ends with the
        # reason it stopped (NodeResult.as_step_result). That reason IS the
        # blocker: "step call limit reached (12 calls)", "no screenshot was
        # taken". Without this line every failed node was named by its
        # expected output, so the child was told only what the parent had
        # been told.
        _node_err = re.search(r"\[node error: ([^\]\n]+)\]", _res)
        if _node_err:
            return f"the step stopped before it was done: {_node_err.group(1)[:200]}"
        if trigger == "verify_failed":
            _exp = (item.expected_output or "").strip()
            if _exp:
                return f"result did not satisfy expected output: {_exp[:200]}"
            if _res:
                return f"result was not verified against the expected output: {_res[:200]}"
            return ""  # UNNAMED â€” no expected output AND no evidence
        if trigger == "unresolved_u":
            return "unresolved oscillating state (|u| below the split threshold)"
        if _res:
            return f"the produced result was judged insufficient: {_res[:200]}"
        return ""

    def _split_step(
        self,
        item: "QueueItem",
        trigger: str,
        cad: Dict[str, float],
        work_units: int,
        step_result: str = "",
        verified_fraction: float = 0.0,
    ) -> List["QueueItem"]:
        """Stateful, physics-driven split operator (D2.1).

        Args:
            item:       step being split.
            trigger:    "unresolved_u" | "verify_failed".
            cad:        live Caducean state {x, y, xi, u, ...}.
            work_units: remaining unified termination budget (DER_WORK_UNITS_0
                        minus what has been prepaid). Split is PERMITTED only if
                        work_units >= width; split PREPAYS ``width`` units up
                        front (this is what makes the Lyapunov potential Phi
                        strictly decrease â€” see Appendix B).
            step_result: the failure evidence (produced result / error text).
                        REQ-4 AC4 (T16b): used to name the SPECIFIC blocker the
                        children exist to resolve â€” the child's objective_anchor
                        is NEVER a restatement of the parent goal.
            verified_fraction: REQ-4 AC1/AC2 (T16): the continuous verification
                        fraction of this step (0..1), consumed as a GRADED
                        steering input at the split decision. Mid-band
                        (0.25 < vf < 0.75) selects the bounded probe path
                        (width 1, probe=True) instead of a full-width
                        re-attempt; strong failure (< 0.25) lets |u| govern.
                        Default 0.0 preserves the pre-T16 binary behavior for
                        callers that do not have the fraction.

        Returns:
            List of child QueueItems (Sub-Loops that collapse back to the parent
            as one COMPRESS). Empty list => split refused, step forced atomic.
        """
        from backend.agent.der_constants import (
            DER_MAX_GRAFTS,
            MAX_DEPTH,
        )

        u = cad.get("u", 0.0)
        # REQ-4 AC1/AC2 (T16): the width is now a GRADED function of BOTH |u|
        # and the verified fraction â€” the continuous signal is a steering
        # input, not a post-hoc label. Mid-band -> bounded probe (width 1).
        # Goal contract T6 (REQ-3 AC3.3): feed task-level coverage C when the
        # per-step fraction is degenerate (0.0 default) so the split width is
        # a continuous function of coverage as well as |u|. Advisory â€” falls
        # back to the per-step fraction exactly when no contract exists.
        _gcov_state = getattr(self, "_goal_contract_state", None)
        _steer_frac = verified_fraction
        if _gcov_state is not None and not (0.0 < verified_fraction < 1.0):
            try:
                _gcov_c = float(_gcov_state.get("C", 0.0))
                if 0.0 < _gcov_c < 1.0:
                    _steer_frac = _gcov_c
            except Exception:
                pass
        width = self._der_split_width(u, _steer_frac)
        # Cap at DER_MAX_GRAFTS AND bounded by remaining work units.
        width = min(width, DER_MAX_GRAFTS, max(0, work_units))
        if width < 1 or item.depth_layer >= MAX_DEPTH:
            return []  # refused -> step forced atomic

        from backend.agent.der_loop import QueueItem, NodeRecord

        # REQ-4 AC2 (T16): a mid-band verified fraction selects the graded
        # middle path â€” a BOUNDED PROBE (width 1, probe=True), not a threshold
        # coin-flip. The child resolves the specific blocker at width 1.
        _probe = 0.25 < verified_fraction < 0.75 and trigger == "verify_failed"

        from backend.agent.der_loop import QueueItem, NodeRecord

        # REQ-4 AC4 (T16b): name the SPECIFIC blocker the split exists to
        # resolve â€” deterministically extracted from the failure evidence (no
        # LLM call on the split hot path). A split that cannot name what it
        # resolves records an UNNAMED blocker (blocker_named=False) â€” surfaced
        # as evidence the failure was not understood, never hidden behind a
        # fresh node id.
        _blocker = self._der_split_blocker(item, trigger, step_result)
        if _blocker:
            _child_anchor = f"RESOLVE: {_blocker}"
            _blocker_named = True
        else:
            _child_anchor = f"[UNNAMED_BLOCKER] {item.description[:160]}"
            _blocker_named = False
            logger.warning(
                "[DER] _split_step trigger=%s step=%s produced an UNNAMED "
                "blocker â€” the split cannot name what it resolves; recorded "
                "as evidence (REQ-4 AC4)",
                trigger, item.step_id,
            )

        # REQ-21 (T41): the compressed footprint each child carries â€”
        # Understanding (what has been attempted/gathered for this goal across
        # ALL prior attempts, bounded â€” never a truncated sample), Awareness
        # (the goal itself), Direction (remaining vs ruled-out), and a
        # coordinate_ref into the ledger/memory for the full prior evidence.
        # Bounded by construction: prior attempts are a deduplicated key set
        # (not per-tool-call transcripts), so cost does NOT grow linearly with
        # tool calls (AC2). Survives DCP pruning because it is durable
        # structured data on the child QueueItem (AC3).
        try:
            _prior_keys = sorted(
                set(getattr(self, "_der_crawl_attempts", {}).get(
                    self.conversation_id or self.session_id or "", set()
                ))
            )
            _prior_summary = (
                f"{len(_prior_keys)} prior gather attempt(s) committed for "
                f"this goal: {', '.join(_prior_keys[:5])}"
                + ("â€¦" if len(_prior_keys) > 5 else "")
            )
            _coordinate_ref = None
            try:
                _ledger = getattr(self, "_der_ledger", None)
                if _ledger is not None:
                    _coordinate_ref = getattr(_ledger, "conversation_id", None)
            except Exception:
                _coordinate_ref = None
        except Exception:
            _prior_summary = ""
            _prior_keys = []
            _coordinate_ref = None

        # REQ-4 AC4.3 (K3): a replan AFTER A FAILURE is a decision point where
        # the Immortus chain changes the decision - this task's own timeline
        # (what was tried, in order) plus the mediators tried near the current
        # state ride in the children's Understanding. ONLY here: a physics
        # split ("unresolved_u") or a normal step carries none of it (owner
        # rule 2026-09-30: no chain data per turn/step). Bounded (<= 900 chars)
        # and never raises; rows the physics lane has not landed yet are simply
        # absent (no wait: the replan is not worth stalling the answer path).
        _recall_sources: List[str] = []
        if trigger == "verify_failed":
            try:
                from backend.agent.caducean_trajectory import latest_coords_str
                from backend.agent.ontology_recall import (
                    replan_chain_context,
                    resolve_mycelium_conn,
                )

                _chain_sid = (
                    getattr(self, "_der_session", None) or self.session_id or ""
                )
                _chain_conn = resolve_mycelium_conn(self._memory_interface)
                if _chain_conn is not None and _chain_sid:
                    _chain_ctx = replan_chain_context(
                        _chain_conn,
                        _chain_sid,
                        latest_coords_str(self._memory_interface, _chain_sid),
                    )
                    # Spec D9 / E3: when this failure matches a KNOWN CASE, its
                    # trail (the verified fix, dead ends to avoid, dependency
                    # status) rides first - the most actionable line (<= 400).
                    from backend.memory.memory_events import case_trail

                    _trail = case_trail(
                        # the same decisive tool record_step writes the case under
                        _chain_conn, _step_tool(item),
                        step_result or str(getattr(item, "result", "") or ""),
                    )
                    if _chain_ctx or _trail:
                        _prior_summary = " ".join(
                            p for p in ((_prior_summary or "")[:300], _trail, _chain_ctx) if p
                        ).strip()
                        _recall_sources = [
                            s for s, t in (("known_case", _trail), ("chain_timeline", _chain_ctx)) if t
                        ]
            except Exception as _chain_exc:  # noqa: BLE001 â€” advisory context
                logger.debug("[DER] replan chain context skipped: %s", _chain_exc)

        children: List["QueueItem"] = []
        # REQ-3 T8: capture the pre-split compressed position so every child's
        # NodeRecord carries the SAME coords_from (the branch point) and each
        # lands a distinct coords_to when it finalizes (REQ-2 chain append).
        _coords_before = ""
        try:
            _live = self._der_live_cad_state(self.session_id or "")
            if _live:
                _coords_before = f"({_live.get('x', 0.0):.4f},{_live.get('y', 0.0):.4f}," \
                                 f"{_live.get('xi', 0.0):.4f},{_live.get('u', 0.0):.4f})"
        except Exception:
            pass
        for i in range(width):
            child = QueueItem(
                step_id=f"{item.step_id}_s{i}",
                step_number=item.step_number,
                # REQ-4 AC4 (T16b): the child's description/objective names the
                # SPECIFIC blocker it resolves â€” NOT a restatement of the
                # parent goal. This is what makes a split a RESOLVE, not a
                # retry wearing a new node id.
                description=f"{_child_anchor} (sub {i + 1})",
                objective_anchor=_child_anchor,
                # the parent's plain text, for the spoken "part done" line
                # (the child's own description is a machine anchor)
                parent_description=item.description or "",
                depth_layer=item.depth_layer + 1,
                expected_output=item.expected_output,
                is_subloop=True,  # collapses back to parent as one COMPRESS
                critical=item.critical,
                independent=True,  # T6.8: subloop children are independent per REQ-18 AC1
                # REQ-3 T8: EVERY node carries its memory record â€” the
                # generalized NodeRecord (was SubLoopFootprint, sub-loop-only).
                node_record=NodeRecord(
                    step_id=f"{item.step_id}_s{i}",
                    parent_step_id=item.step_id,
                    node_type="sub_loop",
                    objective_anchor=_child_anchor,
                    content_summary=_prior_summary,
                    prior_summary=_prior_summary,
                    expected_output=item.expected_output,
                    remaining=_child_anchor,
                    ruled_out="",  # no path is closed until a child proves it
                    coordinate_ref=_coordinate_ref,
                    coords_from=_coords_before,
                    blocker=_blocker,
                    blocker_named=_blocker_named,
                    probe=_probe,
                    # REQ-18 (T19): children INHERIT the parent's two domain
                    # axes â€” they are the same task (topic) run in the same
                    # winding (execution). Registry values by construction.
                    topic_domain=getattr(
                        getattr(item, "node_record", None), "topic_domain", "general"
                    ) or "general",
                    execution_domain=getattr(
                        getattr(item, "node_record", None),
                        "execution_domain",
                        "der",
                    ) or "der",
                    size_bytes=len(_prior_summary.encode("utf-8", "replace")),
                ),
            )
            children.append(child)
        logger.info(
            "[DER] _split_step trigger=%s u=%.2f width=%d depth=%d",
            trigger, u, width, item.depth_layer,
        )
        # Taxonomy v1: the replan recalls were delivered to EVERY child (each carries them).
        for _src in _recall_sources:
            for _child in children:
                _der_recall_delivered(
                    self, _child, _src, [],
                    getattr(self, "_der_session", None) or self.session_id or "",
                )
        # Taxonomy CONTROL: a failed verification changes the plan (REPLAN) by
        # fanning the step out (SPLIT); a physics split is only the SPLIT.
        _ev_rec = getattr(item, "node_record", None)
        _ev = dict(
            evidence="verifier", thread_id=getattr(self, "_der_session", None),
            step_index=str(getattr(item, "step_id", "") or ""),
            exec_domain=getattr(_ev_rec, "execution_domain", None),
            topic_domain=getattr(_ev_rec, "topic_domain", None),
            payload={"trigger": trigger, "width": width, "depth": item.depth_layer,
                     "probe": _probe, "blocker_named": _blocker_named},
        )
        if trigger == "verify_failed":
            _emit_event(self, "REPLAN", **_ev)
        _emit_event(self, "SPLIT", **_ev)
        # Reset failure counters so Sub-Loops aren't penalized as parent continuation (REQ-12 AC3)
        try:
            if hasattr(self, "_get_tool_box"):
                self._get_tool_box().reset_failure_counters()
        except Exception:
            pass
        return children

    def _der_route_subloop_children(
        self, _children: List["QueueItem"], queue, _session: str, _turn_id: str
    ) -> None:
        """Queue split children as NODES: each runs its own tool loop.

        A split child resolves a step that failed - a browser step that hit
        its call limit, a read that came back wrong. That is tool work. The
        REQ-7 batcher answered every child with ONE tool-less text call and
        pre-seeded the answer, so no recovery child ever opened a page or
        read a file: measured 2026-10-12, 7 of 7 grafts in logs/iris.log were
        BATCH_ROUTED, 0 ran a node, and the written guess became the parent's
        result (conv-1573 s2: 12 browser calls -> call limit -> a 272-char
        text answer stood in for the page). The batcher is removed; split
        children are queued here and nothing else answers for them.
        """
        for _c in _children:
            queue.add_item(_c)

    def _der_live_cad_state(self, session_id: str) -> Dict[str, float]:
        """Live Caducean state for the split decision (D2.2).

        Primary: ffi_caducean_get_state (live engine). Fallback: the trajectory
        recorder's last recorded coordinate (so a split can still be decided if
        the engine is unavailable). Never raises â€” returns zeros on total
        failure.
        """
        try:
            from backend.gateway.iris_ffi import ffi_caducean_get_state

            st = ffi_caducean_get_state(session_id) or {}
            if st:
                return {
                    "x": float(st.get("x", 0.0)),
                    "y": float(st.get("y", 0.0)),
                    "xi": float(st.get("xi", 0.0)),
                    "u": float(st.get("u", 0.0)),
                }
        except Exception as _e:
            logger.debug("[DER] live cad state unavailable: %s", _e)
        # Fallback: trajectory recorder's latest coordinate.
        try:
            from backend.agent.caducean_trajectory import (
                get_trajectory_recorder,
            )

            # REQ-20: bind to the APPLICATION store via MemoryInterface, never
            # to the BUILD-memory .mcm/coordinates.db fallback.
            rec = get_trajectory_recorder(self._memory_interface)
            coord = rec.get_latest_coordinate(session_id) or {}
            return {
                "x": float(coord.get("x", 0.0)),
                "y": float(coord.get("y", 0.0)),
                "xi": float(coord.get("xi", 0.0)),
                "u": float(coord.get("u", 0.0)),
            }
        except Exception:
            return {"x": 0.0, "y": 0.0, "xi": 0.0, "u": 0.0}

    def _der_stamp_session_exit(self, natural_exit: bool) -> None:
        """REQ-16 AC2 (T32): stamp the session's exit nature on the
        conversation memory so ``archive_on_session_end`` records an HONEST
        ``natural_exit`` when the session ends (the DER loop is the source of
        truth for whether the task completed).

        Success path -> natural_exit=True (task ran to completion); failure /
        zero-step path -> natural_exit=False (task did NOT complete). Best-
        effort, off the hot path, never raises â€” a missing conversation memory
        is simply skipped.
        """
        try:
            _mem = getattr(self, "_conversation_memory", None)
            if _mem is not None:
                _mem.natural_exit = bool(natural_exit)
        except Exception:
            pass

    # Session 245 (synthesis starvation fix, conv-36 live finding): gather
    # tools whose ENTIRE purpose is delivering content (crawl / search /
    # read) need far larger evidence windows than generic tools. A 3-page
    # crawl compressed to 300-400 chars starves every downstream consumer â€”
    # the tool-decision model then honestly reports "unable to access the
    # search results" because no fragment it sees can answer the goal.
    _DER_GATHER_TOOLS = {
        "crawler_query", "web_search", "search", "fetch_url",
        "read_file", "browser_read",
    }

    # REQ-18 added grep_files / glob_files as the codebase-search surface, but
    # they were never given an evidence window to match. They are not in
    # _DER_GATHER_TOOLS, so their results fell to the 400-char NON-gather cap
    # -- and a search tool exists precisely to return a LIST. Measured live
    # 2026-08-26 (conv-63): "how many backend files mention Porcupine" returned
    # 18 matches; at ~21 chars per entry that is ~420 chars of paths before the
    # JSON envelope, so the agent could not physically see them all and
    # answered "at least six". Truthful, correctly hedged, and wrong.
    #
    # Deliberately a SEPARATE set rather than adding them to _DER_GATHER_TOOLS:
    # that set also drives the sufficiency gate (:9391) and the graft decision
    # (:10623). This changes the evidence WINDOW only, which is the defect.
    _DER_SEARCH_TOOLS = {"grep_files", "glob_files"}

    # Session-323: stored-read tools deliver the SAME gathered bytes through
    # the document store instead of a fresh fetch. A rerouted read that keeps
    # the 400-char generic cap starves every downstream consumer â€” live
    # B3-repeat: guard rerouted to get_rendered_documents, step result held
    # only "1 document(s) retrieved", synthesis honestly reported IDs-only.
    # Kept as a SEPARATE set (same reason as _DER_SEARCH_TOOLS): this set
    # widens the evidence WINDOW only and must not alter the sufficiency
    # gate or graft decision that key off _DER_GATHER_TOOLS.
    _DER_READ_TOOLS = {
        "get_rendered_documents", "get_document", "read_document",
        "get_rendered_document", "recall_research",
    }

    # Tools whose result is a command's output: exit code + stdout/stderr.
    _SHELL_RESULT_TOOLS = {"run_command", "read_shell_output", "read_command_output", "stop_command"}

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

    def _der_findings_sufficient(
        self, objective: str, completed_items: List[Any]
    ) -> tuple:
        """
        Session 247: goal-level sufficiency check â€” the mindful-search gate.

        DER's per-step verifier grades each step in isolation; nothing ever
        asked whether the ACCUMULATED findings already answer the user's
        question. This method does exactly that, once, at the graft decision:
        a bounded digest of completed step results plus the objective goes to
        one cheap reasoning call, which answers
              {"sufficient": bool, "missing": "..."}
        True  -> the caller skips grafting more gather rounds and lets the
                 loop finalize over what it has.
        False -> graft proceeds (missing aspects are logged for targeting).

        NEVER raises. On any inference/parse failure returns (False, "") so
        the gate is advisory and pre-existing behavior is preserved â€” a broken
        gate must not change loop semantics, only a working one may.
        """
        import re as _re2

        if not completed_items:
            return False, ""
        # Bounded digest: head+tail excerpt per result, newest last, capped so
        # the prompt stays small regardless of how many steps completed.
        _parts: List[str] = []
        for _idx, _it in enumerate(completed_items[-6:]):
            _txt = (getattr(_it, "result", "") or "")[:1200]
            if not _txt:
                continue
            _parts.append(f"[{_idx + 1}] {self._smart_excerpt(_txt, 600)}")
        if not _parts:
            return False, ""
        _digest = "\n".join(_parts)
        _prompt = (
            f"OBJECTIVE: {objective[:500]}\n\n"
            f"FINDINGS COLLECTED SO FAR:\n{_digest}\n\n"
            "Do the findings above contain enough information to satisfy the "
            "objective on their own? Judge as a strict editor: sufficient means "
            "the objective could be answered NOW without any further searching.\n"
            'Reply with JSON only: {"sufficient": true or false, "missing": '
            '"what is still missing, or empty string"}'
        )
        try:
            _raw = self.infer(_prompt, role="reasoning", max_tokens=100, temperature=0.0)
            _m = _re2.search(r"\{[\s\S]+\}", _raw.raw_text or "")
            if not _m:
                return False, ""
            _data = json.loads(_m.group())
            _brain_sufficient = bool(_data.get("sufficient"))
            _brain_missing = str(_data.get("missing", ""))[:300]
        except Exception as _gate_exc:
            logger.debug("[DER] sufficiency gate inference failed: %s", _gate_exc)
            return False, ""

        # REQ-14 AC14.1 (T18): shadow-score the `sufficient` consumer and emit
        # the row. The BRAIN's answer still decides, and the gate stays
        # advisory-FAIL-CLOSED (AC14.4): `sufficiency_gate` returns (False, "")
        # on any failure, exactly the shape this method already had. The engine
        # never writes the `missing` text (AC14.2).
        try:
            from backend.agent import monitor_shadow as _ms
            from backend.agent.decision_engine import decides, oracle_acts

            # Stage B: only the chokepoint lets the Oracle replace the Brain's
            # bit; otherwise the score runs on the lane (off the reply path).
            _dec = decides("sufficient") is not None
            _value, _missing = _ms.sufficiency_gate(
                _prompt,
                brain_bool_fn=lambda: _brain_sufficient,
                brain_text_fn=lambda: _brain_missing,
                engine=_ms.AUTO_ENGINE,
                # defer is ignored once enforced: a deciding consumer is waited for.
                enforced=_dec, defer=True,
                acts=lambda c: oracle_acts("sufficient", c),
            )
            return _value, _missing
        except Exception:  # noqa: BLE001 â€” the gate is advisory
            return _brain_sufficient, _brain_missing

    @staticmethod
    def _smart_excerpt(text: str, cap: int) -> str:
        """Head+tail excerpt with an explicit truncation marker â€” never a
        silent amputation, never an unbounded dump."""
        t = (text or "").strip()
        if len(t) <= cap:
            return t
        _head = t[: int(cap * 0.7)]
        _tail = t[-int(cap * 0.3):]
        return f"{_head}\n[...excerpt: {len(t) - cap} chars truncated...]\n{_tail}"

    @staticmethod
    def _der_node_record_evidence(item) -> str:
        """REQ-8 AC1 (T26): compressed synthesis evidence from a node record.

        Session 245 ADDITION: GATHER-tool steps bypass the compression â€”
        their raw output IS the payload the synthesis must read, so a
        content_summary[:300] of a 3-page crawl guarantees the final answer
        starves. They get a bounded-but-generous raw window instead; every
        other tool keeps the compressed-record behavior unchanged. When the
        item carries no node_record (empty memory edge case, REQ-8), falls
        back to the raw result truncated to a bounded window so a step is
        never silent.
        """
        try:
            # Gather tools: raw payload window (head+tail), compression OFF.
            # Session-323: stored-read tools join the wide path â€” a rerouted
            # read delivers the SAME gathered bytes through the document
            # store, and compressing them to a node-record summary re-starves
            # the synthesis the wide gather window was built to feed.
            # What the step DID, not item.tool: a node step (tool=None) that
            # searched got the 300-char record summary, so the synthesis never
            # saw the search results (evals 2026-10-04: r01/r06/r07 0/3,
            # "the results did not return the figures"; 8/8 on 2026-10-01).
            _wide = AgentKernel._DER_GATHER_TOOLS | AgentKernel._DER_READ_TOOLS
            if any(str(c.get("tool") or "").lower() in _wide for c in _step_calls(item)):
                _raw_gather = getattr(item, "result", "") or ""
                if _raw_gather:
                    return AgentKernel._smart_excerpt(_raw_gather, _step_evidence_cap(item))
            _rec = getattr(item, "node_record", None) or getattr(
                item, "footprint", None
            )
            if _rec is not None:
                _parts = []
                _cs = getattr(_rec, "content_summary", "") or ""
                if _cs:
                    _parts.append(f"summary: {_cs[:300]}")
                _eo = getattr(_rec, "expected_output", "") or ""
                if _eo:
                    _parts.append(f"done-when: {_eo[:200]}")
                _rm = getattr(_rec, "remaining", "") or ""
                if _rm:
                    _parts.append(f"remaining: {_rm[:200]}")
                _ro = getattr(_rec, "ruled_out", "") or ""
                if _ro:
                    _parts.append(f"ruled-out: {_ro[:200]}")
                if _parts:
                    return " | ".join(_parts)
            # No node record â€” bounded raw fallback (REQ-8 edge case).
            _raw = getattr(item, "result", "") or ""
            if _raw:
                return _raw[:400]
        except Exception:
            pass
        return ""

    def _der_synthesize_outcome(
        self,
        plan,
        completed_items: list,
        queue,
        _session: str,
    ) -> str:
        """
        Phase 1.5: produce a friendly, user-facing summary when one or more
        steps failed. Explains what was accomplished, what failed, and what
        to do next. Returns "" on any failure (caller falls back to raw output).
        """
        try:
            # REQ-8 AC1 (T26): build the synthesis from COMPRESSED node records
            # (content summary / done-when / remaining / ruled-out), not the raw
            # step outputs. Keeps the final summary bounded and free of
            # interleaved tool noise, and avoids replaying raw history into the
            # model.
            _done = "\n".join(
                f"[Step {ci.step_number}] {ci.description}: "
                f"{self._der_node_record_evidence(ci) or '(no result)'}"
                for ci in completed_items
            ) or "(none)"
            _failed_lines = []
            for _fi in queue.failed_ids:
                _desc = _fi
                for _it in queue.items:
                    if _it.step_id == _fi:
                        _desc = _it.description or _fi
                        break
                _failed_lines.append(f"- {_desc}")
            _failed = "\n".join(_failed_lines) or "(none)"
            _prompt = (
                f"USER TASK: {plan.original_task}\n\n"
                f"STEPS EXECUTED:\n{_done}\n\n"
                f"STEPS THAT FAILED:\n{_failed}\n\n"
                "Provide a friendly, user-facing summary of what was accomplished, "
                "what failed, and what to do next.\n\n"
                "Cover every part of the user's request. If the results lack "
                "some asked part, say which part is missing in one line â€” "
                "never skip it in silence.\n\n"
                + _READABLE_FORMAT_RULES
            )
            # The user-facing outcome summary is THINKING -> Brain (2026-08-16).
            _res = self.infer(_prompt, role="reasoning",
                              max_tokens=self.response_max_tokens(floor=400),
                              temperature=self.response_temperature())
            _out = _res.raw_text or ""
            # Spec A6 (AC3.5): same rule as the success path - a stub answer is
            # retried ONCE with the same inputs before the deterministic close.
            _stub_floor_f = max(80, 40 * (len(completed_items) + len(queue.failed_ids)))
            if _out.strip() and len(_out.strip()) < _stub_floor_f:
                logger.warning(
                    "[DER] failure synthesis stub (%d chars < %d floor) "
                    "â€” retrying once with the same inputs",
                    len(_out.strip()), _stub_floor_f,
                )
                _res = self.infer(_prompt, role="reasoning",
                                  max_tokens=self.response_max_tokens(floor=400),
                                  temperature=self.response_temperature())
                _out = _res.raw_text or ""
            # Session-345 (live, conv-134): with thinking disabled the model
            # may answer the failure-summary prompt with the tool-call ARGS
            # JSON â€” `{"query": ..., "top_n": 10}` went straight to chat AND
            # TTS. A bare-JSON final answer is never a user-facing message;
            # reject it so the deterministic failure close takes over.
            _stripped = _out.strip()
            if _stripped.startswith("{") and _stripped.endswith("}"):
                try:
                    import json as _json
                    _parsed = _json.loads(_stripped)
                    if isinstance(_parsed, dict) and "query" in _parsed:
                        logger.warning(
                            "[DER] failure synthesis returned tool-args JSON â€” "
                            "rejecting for deterministic close"
                        )
                        return ""
                except Exception:
                    pass
            # Session-326 shield 3, failure side: same stub rule as the
            # success path â€” a stub falls through to the deterministic
            # failure close, which names every failed step by shape.
            if _out and _out.strip():
                _stub_floor = max(80, 40 * (len(completed_items) + len(queue.failed_ids)))
                if len(_out.strip()) < _stub_floor:
                    logger.warning(
                        "[DER] failure synthesis stub (%d chars < %d floor) "
                        "â€” deterministic fallback",
                        len(_out.strip()), _stub_floor,
                    )
                    return ""
            # Shield 4 (live 2026-09-25): internal narration is not a summary.
            # A failed three-file turn showed the user "We haven't performed the
            # read yet. Need to call read_file for the three files.Let's run
            # read_file." â€” the model narrated its next move instead of telling
            # the user what happened. Reject it so the deterministic failure
            # close (which names each failed step) answers instead.
            from backend.agent.artifact_policy import looks_like_internal_narration

            if looks_like_internal_narration(_out):
                logger.warning(
                    "[DER] failure synthesis is internal narration â€” "
                    "deterministic close instead: %r", _out.strip()[:140],
                )
                return ""
            return _out
        except Exception as _e:
            logger.warning("[DER] outcome synthesis failed: %s", _e)
            return ""

    def _der_synthesize_success_outcome(
        self,
        plan,
        completed_items: list,
        queue,
        _session: str,
    ) -> str:
        """
        REQ-12 (AC1/AC2/AC3): success-path synthesis.

        Consumes the SAME evidence the failure path (``_der_synthesize_outcome``)
        consumes â€” ``plan.original_task`` plus each completed step's description
        and result â€” and routes it through the previously-dead
        ``_synthesize_response`` brain synthesis (AC3 wiring), which handles the
        InferenceRouter, LM Studio, and Ollama providers. Returns "" when
        synthesis is unavailable so the caller falls back to the deterministic
        success summary (AC4). Mirrors ``_der_synthesize_outcome``'s "" contract.
        """
        # Session 245 (verb progression): announce the SYNTH phase so the
        # working step's verb leaves SEARCH and shows SYNTH while the answer
        # is being composed â€” previously synthesis was invisible on the card.
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.TASK_PROGRESS,
                data={
                    "description": "Synthesizing answer",
                    "action": "Synthesizing",
                    "update_step": True,
                    "detail": "Synthesizing answer",
                    "detail_progress": "",
                    "phase": "synthesizing",
                    "phase_sequence": 90,
                    # GROUND TRUTH T29 (REQ-17 AC4): the synthesis row is a
                    # row like any other and needs the ordering key. T27
                    # flagged this one in EVERY captured trace, including the
                    # non-crawl code task - the defect was never crawl-specific.
                    "seq": _row_sequence.seq_for(
                        self.conversation_id, "phase-synthesizing"
                    ),
                },
                session_id=_session,
                conversation_id=self.conversation_id,
            )
        except Exception:
            pass  # never block synthesis on an emit failure
        try:
            _step_results = [
                {
                    "tool": getattr(ci, "tool", None),
                    "action": getattr(ci, "description", ""),
                    # REQ-8 AC1 (T26): compressed node-record evidence instead of
                    # the raw step output. The brain synthesis reads the bounded
                    # memory record, never the full raw history.
                    "result": self._der_node_record_evidence(ci) or "",
                    "bounded": True,  # already cut to its evidence window
                    "success": True,
                }
                for ci in completed_items
            ]
            _task = TaskContext(
                task_id=_session,
                user_message=plan.original_task,
                session_id=_session,
                conversation_history=[],
                plan={"original_task": getattr(plan, "original_task", "")},
                step_results=_step_results,
            )
            _syn = self._synthesize_response(_task, _step_results)
            if _syn and _syn.strip():
                # Session-326 shield 3 (owner: understudy rule): a stub turn
                # ("Let's attempt that.") counts as a failed synthesis â€” the
                # caller then serves the deterministic per-step close, which
                # covers every step by shape. Floor scales with steps so a
                # true one-liner on a one-step ask still airs.
                _syn_text = _syn.strip()
                # 40 chars per step. The old max(80, ...) contradicted the line
                # above: it rejected a correct one-step one-liner (r02,
                # 2026-09-30: a 46-char answer, twice) and served the raw close.
                # A stub is a NON-answer ("Let's attempt that.", 19 chars), so the
                # floor is about the reply, never the plan: 40 x steps rejected a
                # correct 101-char answer on a 4-step task, twice, and served the
                # raw step dump (live 2026-10-02 run A4: "Mount Kilimanjaro has an
                # elevation of 5,895 metres, and the first recorded ascent took
                # place in 1889."). A short reply carrying a number is an answer.
                _syn_floor = 40
                if (len(_syn_text) < _syn_floor and not re.search(r"\d", _syn_text)
                        and not _short_reply_carries_results(_syn_text, _step_results)):
                    # Spec A6 (AC3.5): a stub is often a one-off (measured: a
                    # 14-token turn on r02). Retry ONCE with the same inputs
                    # before giving up; only a stub that persists falls to the
                    # deterministic close (which never prints raw sources).
                    logger.warning(
                        "[DER] success synthesis stub (%d chars < %d floor) "
                        "â€” retrying once with the same inputs: %r",
                        len(_syn_text), _syn_floor, _syn_text[:120],
                    )
                    _retry = self._synthesize_response(_task, _step_results)
                    _retry_text = (_retry or "").strip()
                    if (len(_retry_text) >= _syn_floor or re.search(r"\d", _retry_text)
                            or _short_reply_carries_results(_retry_text, _step_results)):
                        _syn_text = _retry_text
                    else:
                        logger.warning(
                            "[DER] success synthesis stub persists after retry "
                            "(%d chars < %d floor) â€” deterministic fallback",
                            len(_retry_text), _syn_floor,
                        )
                        return ""
                logger.info(
                    "[DER] success synthesis ran (REQ-12 AC1) â€” steps=%d",
                    len(completed_items),
                )
                # The goal contract proved every asked fact has evidence (each
                # fact's own name in a VERIFIED result), yet the reply says a
                # part is missing: the reply model misread its evidence (r09
                # conv-834 / conv-884: "330 metres", "May 28, 1937" were in the
                # new results). One more write, told that every part is there.
                _gc_st = getattr(self, "_goal_contract_state", None)
                if (isinstance(_gc_st, dict) and float(_gc_st.get("C", 0.0)) >= 1.0
                        and _claims_missing(_syn_text)):
                    _facts = list(getattr(_gc_st.get("contract"), "required", ()) or ())
                    logger.warning(
                        "[DER] reply claims a part is missing but all %d required facts "
                        "have evidence â€” writing once more: %r",
                        len(_facts), _syn_text[:140],
                    )
                    _task.user_message = (
                        f"{plan.original_task}\n\n(CHECK: the tool results contain "
                        "evidence for EVERY asked part: "
                        + "; ".join(str(_f)[:120] for _f in _facts)
                        + ". Find each one in the results - PRIOR RESEARCH lines "
                        "count - and answer every part.)"
                    )
                    _again = (self._synthesize_response(_task, _step_results) or "").strip()
                    if _again:
                        _syn_text = _again
                # Shield 4 (live 2026-09-25): the success summary must be an
                # answer, not the model narrating its own tools. A report card
                # opened with "The tool only returned a partial draft; it omitted
                # full sections ...". Reject narration so the deterministic
                # per-step close answers instead.
                from backend.agent.artifact_policy import looks_like_internal_narration

                if looks_like_internal_narration(_syn_text):
                    logger.warning(
                        "[DER] success synthesis is internal narration â€” "
                        "deterministic close instead: %r", _syn_text[:140],
                    )
                    return ""
                return _syn_text
            return ""
        except Exception as _e:
            logger.warning("[DER] success synthesis failed: %s", _e)
            return ""

    # â”€â”€ Partial-artifact completion (live 2026-09-25) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # One step is ONE tool call (ToolDecisionBox.resolve is single-shot), so a
    # step that names several files can only ever write one of them. Measured:
    # "create three files ... each with one bullet" wrote ONE file, the other two
    # were silently missing, and the user was told the files had been created.
    # The folder stays on the name: "tests/test_geometry.py" read as "test_geometry.py",
    # was "missing" in the project root, and the graft overwrote the real test file
    # (live c11 2026-10-27: "Create the file test_geometry.py ..." -> hidden test failed).
    _ARTIFACT_NAME_RE = re.compile(
        r"\b[\w][\w.\-/\\]*\.(?:md|markdown|txt|json|csv|tsv|ya?ml|py|js|ts|tsx|html|log|rst|tex)\b",
        re.IGNORECASE,
    )

    @classmethod
    def _declared_file_names(cls, text: str) -> list:
        """File names named in the text â€” ordered, deduped, bounded to 8.

        Pure: the caller decides which of them are actually missing.
        """
        out: list = []
        seen: set = set()
        for match in cls._ARTIFACT_NAME_RE.finditer(text or ""):
            name = match.group(0)
            low = name.lower()
            if low in seen:
                continue
            seen.add(low)
            out.append(name)
        return out[:8]

    @staticmethod
    def _artifact_missing(name: str, base: str = "") -> bool:
        """True when the named artifact is absent, or present but empty. A
        relative name is resolved against ``base`` (the session's project
        folder, where node steps write) when one is given."""
        try:
            from pathlib import Path

            p = Path(name)
            if base and not p.is_absolute():
                p = Path(base) / p
            return not (p.exists() and p.stat().st_size > 0)
        except OSError:
            return True

    def _der_graft_missing_artifacts(
        self,
        item,
        plan,
        queue,
        _session: str,
        _turn_id: str,
        _token_budget: int = 0,
        _tokens_used: int = 0,
    ) -> int:
        """Graft a step per artifact the task named but nothing wrote.

        Called after a FILE-WRITING step finalizes. Bounded three ways: only for
        file-writing tools, at most DER_MAX_GRAFTS steps per run, and each file
        name is attempted at most once (``_artifact_graft_attempted``). Never
        raises — a missed graft must not break the turn.

        Returns the number of steps grafted. A non-zero count means this step's
        tool choice did not finish the job, so its tool_choice rows are labelled
        as a retry (tc-decide-v7).
        """
        try:
            # What the step DID (_step_calls), not item.tool: a node step has no
            # tool, so this graft never ran on node work (DER_DAG.md seam 2).
            if not any(
                str(c.get("tool") or "").lower()
                in ("write_file", "create_directory", "edit_file", "append_file")
                and c.get("ok", True)
                for c in _step_calls(item)
            ):
                return 0
            from backend.agent.der_constants import DER_MAX_GRAFTS

            # Node steps write in the session's project folder, not the
            # backend's working directory.
            _base_dir = str(
                (getattr(getattr(self, "_tool_bridge", None), "_session_workdirs", None) or {})
                .get(_session, "") or ""
            )

            _attempted = getattr(self, "_artifact_graft_attempted", None)
            if _attempted is None:
                _attempted = set()
                self._artifact_graft_attempted = _attempted
            if len(_attempted) >= DER_MAX_GRAFTS:
                return 0
            _task_text = str(getattr(plan, "original_task", "") or "")
            _text = " ".join([_task_text, str(getattr(item, "description", "") or "")])
            _done = set(getattr(queue, "completed_ids", ()) or ()) | set(
                getattr(queue, "failed_ids", ()) or ())
            _queued_text = " ".join(
                str(getattr(_it, "description", "") or "")
                for _it in (getattr(queue, "items", []) or [])
                if getattr(_it, "step_id", None) not in _done
                and getattr(_it, "step_id", None) != getattr(item, "step_id", None)
            )
            _missing = [
                n for n in self._declared_file_names(_text)
                if n not in _attempted and self._artifact_missing(n, _base_dir)
                # a step still in the queue names it: that step will write it
                and n not in _queued_text
            ][: max(DER_MAX_GRAFTS - len(_attempted), 0)]
            if not _missing:
                return 0
            # A template helps the model produce the same shape the user asked for
            # ("each with one bullet about tea") and guarantees a body is written.
            _template = ""
            for _n in self._declared_file_names(_text):
                if not self._artifact_missing(_n, _base_dir):
                    try:
                        from pathlib import Path

                        _template = (Path(_base_dir) / _n if _base_dir else Path(_n)).read_text(
                            encoding="utf-8", errors="replace"
                        )[:200]
                    except OSError:
                        _template = ""
                    if _template:
                        _sibling = _n
                        break
            else:
                _sibling = ""

            from backend.agent.der_loop import QueueItem

            _base = len(getattr(queue, "items", []) or [])
            _new_steps = [
                QueueItem(
                    step_id="%s_art%d" % (item.step_id, _i),
                    step_number=_base + _i,
                    # tool stays UNSET: ToolDecisionBox.resolve is
                    # description-driven (tool_decision.resolve reads
                    # step["description"] as its goal). A preset tool with no
                    # params produced no call at all in the first live attempt.
                    description=(
                        "Create the file {name} with the content the user asked for "
                        "in this task: {task}{like}".format(
                            name=_name,
                            task=_task_text[:300],
                            like=(
                                ". Write the same style of content as {sib}, which "
                                "contains: {tpl}".format(sib=_sibling, tpl=_template)
                                if _template else ""
                            ),
                        )
                    ),
                    depends_on=[item.step_id],
                    critical=False,
                    objective_anchor=_task_text[:200],
                    # Mirror the PARENT step's expected output: the run grade
                    # reads each step's expected_output against its result, and a
                    # bespoke claim here ("X exists and is not empty") matched
                    # neither the result nor the parent's, capping the whole run
                    # and telling the user the task had failed when the files
                    # were on disk. Same claim shape, same verdict.
                    expected_output=getattr(item, "expected_output", None),
                    declared_criticality="supporting",
                    node_record=getattr(item, "node_record", None),
                )
                for _i, _name in enumerate(_missing, start=1)
            ]
            if not self._der_amend_graph(
                _new_steps, _session, plan, queue,
                _token_budget=_token_budget, _tokens_used=_tokens_used,
                _turn_id=_turn_id,
            ):
                return 0
            _attempted.update(_missing)
            try:
                queue.graft_attempts += 1
            except Exception:
                pass
            logger.info(
                "[DER] partial artifacts: grafted %d step(s) for %s "
                "(one step = one tool call, so a multi-file step needs the rest)",
                len(_missing), _missing,
            )
            return len(_missing)
        except Exception as _graft_exc:
            logger.warning("[DER] artifact graft skipped: %s", _graft_exc)
        return 0

    @staticmethod
    def _humanize_evidence(text: str) -> str:
        """A tool result the user can read.

        A tool's ``summary`` is often its own JSON envelope. Unwrap it to the
        human field (message / content / text) so the user sees
        ``Written to zz_a.md`` rather than ``{"success": true, ...}``. Anything
        that is not a JSON object passes through unchanged.
        """
        t = (text or "").strip()
        if not (t.startswith("{") and t.endswith("}")):
            return t
        try:
            import json as _json

            _obj = _json.loads(t)
        except Exception:
            return t
        if not isinstance(_obj, dict):
            return t
        for _key in ("message", "content", "text", "result"):
            _val = _obj.get(_key)
            if isinstance(_val, str) and _val.strip():
                return _val.strip()
        return t

    _SOURCE_HEADER_RE = re.compile(r"---\s*Source:\s*(\S+)\s*---")

    @staticmethod
    def _no_raw_source_dump(text: str) -> str:
        """Spec A6 (AC3.5): a gather step's raw page content is never a user answer.

        When a deterministic close would show ``--- Source: URL ---`` page text (the
        r02 reply was exactly that), show which sources were read instead. Text
        without source headers passes through unchanged.
        """
        _urls = AgentKernel._SOURCE_HEADER_RE.findall(text or "")
        if not _urls:
            return text
        _hosts: list = []
        for _u in _urls:
            _h = re.sub(r"^https?://", "", _u).split("/")[0]
            if _h and _h not in _hosts:
                _hosts.append(_h)
        return (
            f"gathered content from {len(_urls)} source(s): "
            + ", ".join(_hosts[:5])
            + " - no written answer was produced from it"
        )

    @staticmethod
    def _der_user_facing_evidence(item) -> str:
        """T8 / fix 7 (specs/tool-result-envelope REQ-2 AC2.3): user-facing
        evidence is the OUTCOME, never internal mechanics.

        This used to return ``ToolEnvelope.line()``, whose own docstring reads
        'success, mismatched, repeat of step_1 â€” try_different, doc ab12ef34'.
        It is a DIAGNOSTIC string, and live 2026-09-25 the user was shown

            - Create zz_a.md ...: success â€” proceed, doc b2299b91-2c3 | {"success": true, ...}
            - Read the contents ...: success, [idling] â€” try_different, doc 43de69cd-343 | - Tea ...

        Verdicts (proceed/retry_same/try_different), stuck shapes ([idling]) and
        doc ids belong in the ledger. The user gets the status and what the step
        actually produced. The envelope's own diagnostics stay available through
        ``ToolEnvelope.to_dict()`` for the ledger and the metrics.
        """
        _env = getattr(item, "envelope", None)
        if _env is not None:
            _summary = AgentKernel._humanize_evidence(
                str(getattr(_env, "summary", "") or "")
            )
            _error = str(getattr(_env, "error_type", "") or "").strip()
            if _summary:
                _out = f"{_summary} (error: {_error})" if _error else _summary
                return AgentKernel._smart_excerpt(
                    AgentKernel._no_raw_source_dump(_out), 400
                )
            _status = str(getattr(_env, "status", "") or "").strip()
            if _status:
                return _status
        _ev = AgentKernel._der_node_record_evidence(item)
        if _ev:
            _ev = AgentKernel._no_raw_source_dump(_ev)
        return AgentKernel._smart_excerpt(_ev, 400) if _ev else ""

    @staticmethod
    def _der_deterministic_failure_summary(plan, completed_items: list, queue) -> str:
        """User-facing 'task incomplete' message that needs NO LLM call (Part B).

        ``_der_synthesize_outcome`` relies on ``infer()`` to write the summary.
        When the model is rate-limited/unavailable â€” the exact failure that
        triggered the research step's failure â€” that synthesis returns "" and the
        user is left with silence. This deterministic fallback guarantees the
        user always gets a clear "I couldn't complete X â€” these steps failed
        (and why)" message even if the LLM is down.
        """
        try:
            _failed = []
            for _fi in queue.failed_ids:
                _desc = _fi
                _reason = ""
                for _it in queue.items:
                    if _it.step_id == _fi:
                        _desc = _it.description or _fi
                        # T8/fix 7 (AC2.3): envelope line, never raw gather.
                        _reason = AgentKernel._der_user_facing_evidence(_it)
                        break
                _failed.append(f"- {_desc}" + (f": {_reason}" if _reason else ""))
            _failed_txt = "\n".join(_failed) or "(unknown step)"
            # No step count in the reply (owner 2026-10-26): "1/1 steps finished" is
            # bookkeeping, not an answer, in personal and developer mode alike.
            return (
                f"I couldn't complete that task. The following step(s) failed:\n{_failed_txt}\n\n"
                f"If a search or source failed, try rephrasing the request or "
                f"pasting the information directly â€” I can continue from where it stopped."
            )
        except Exception as _e:
            logger.warning("[DER] deterministic failure summary failed: %s", _e)
            return (
                "I couldn't complete that task â€” one or more steps failed. "
                "Please try again or rephrase the request."
            )

    @staticmethod
    def _der_deterministic_success_summary(plan, completed_items: list, queue) -> str:
        """User-facing 'task complete' message that needs NO LLM call (REQ-12 AC4).

        Mirrors ``_der_deterministic_failure_summary``: when the brain synthesis
        is unavailable (no reasoning model / providers down), this deterministic
        summary guarantees the user gets a clear statement of what was completed
        â€” never a silent raw concatenation of step outputs.
        """
        try:
            _done_lines = []
            for _ci in completed_items:
                # T8/fix 7 (AC2.3): envelope line + run grade honesty, never
                # the raw gather window.
                _res = AgentKernel._der_user_facing_evidence(_ci)
                _done_lines.append(
                    f"- {getattr(_ci, 'description', '') or _ci}"
                    + (f": {_res}" if _res else "")
                )
            _done_txt = "\n".join(_done_lines) or "(no step output)"
            # AC5.6: report done + grade â€” recomputed statelessly from the
            # envelopes (this is a @staticmethod; no instance state, no
            # shared mutable state). A load-bearing mismatch caps the run
            # below full pass, honestly, in the user-facing fallback too.
            _grade_line = ""
            _capped = False
            try:
                from backend.agent.tool_envelope import evaluate_run_grade
                from backend.agent.der_constants import LOAD_BEARING_VETO

                _envs = [
                    getattr(_ci, "envelope", None) for _ci in completed_items
                ]
                _grade, _reasons = evaluate_run_grade(
                    [e for e in _envs if e is not None],
                    load_bearing_veto=LOAD_BEARING_VETO,
                )
                if _grade == "capped":
                    _capped = True
                    _grade_line = (
                        "\nRun grade: capped below full pass â€” "
                        + "; ".join(_reasons or [])
                        + "\n"
                    )
            except Exception:
                pass
            # AC5.6 honesty (session-334, live T3): the grade is recomputed above
            # and can say "capped ... required fact(s) open and unblocked" while
            # this summary still opened with "I've completed the task". Measured
            # 2026-09-17: grade=capped C=0.000 with an open fact, narration said
            # "I've completed the task. 1/1 steps finished." â€” a false success
            # claim. The narration MUST agree with the grade it just computed.
            if _capped:
                return (
                    f"I couldn't fully complete the task - required work remains open.\n"
                    f"{_done_txt}\n{_grade_line}\n"
                    f"What would you like me to do next?"
                )
            return (
                f"I've completed the task.\n"
                f"{_done_txt}\n{_grade_line}\n"
                f"What would you like to do next?"
            )
        except Exception as _e:
            # AC5.6 honesty: this is the failure path â€” never claim success here.
            logger.warning("[DER] deterministic success summary failed: %s", _e)
            return "I finished running the steps but couldn't verify the result. What would you like me to do next?"

    # â”€â”€ Phase 2.2: context-aware query refinement â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
                        f"(index only â€” call get_rendered_documents("
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

    def _turn_is_bounded_content_ask(self) -> bool:
        """REQ-24: is the CURRENT turn a bounded content ask?

        The gate owns the rule (``semantic_gate.is_bounded_content_ask``);
        this is the kernel-side read of the stashed turn text. Never
        raises - an unknown turn is NOT bounded, so no veto is applied and
        the crawl lane stays exactly as it was before REQ-24.
        """
        try:
            from backend.agent.semantic_gate import is_bounded_content_ask

            return bool(is_bounded_content_ask(getattr(self, "_current_turn_text", "")))
        except Exception:
            return False

    @staticmethod
    def _route_v2_frame(text: Optional[str], web_mode: bool) -> Dict[str, Any]:
        """The ONE frame route_v2 reads - the shadow and the site share it, so
        their rows are one cohort (route_v2/binary-v1)."""
        return {"goal": (text or "")[:200], "task_class": "personal",
                "last_result": "", "chars": len(text or ""),
                "web_mode": bool(web_mode)}

    def _route_v2_route(
        self, text: Optional[str], turn_id: Optional[str], gate_plans: bool
    ) -> Optional[bool]:
        """route_v2's decision site: True = plan (DER), False = answer direct,
        None = the gate's route stands.

        It acts (a) when the bar lets it decide (allow-list + earned bar +
        a confident answer, `oracle_acts`), or (b) on the sampled rung: a
        bounded, deterministic share of turns (`sampled_consult_ok`,
        SAMPLE_FRACTION) where its route drives the turn and the row is held
        for the turn verdict - the outcome label the parity bar lacks (on a
        parity label a "direct" pick the gate would have planned is unscored).
        One synchronous Oracle call (~0.3 s) on those turns only; any fault
        returns None, so the gate decides."""
        try:
            from backend.agent.decision_engine import (
                decides, get_decision_engine, oracle_acts, sampled_consult_ok,
                sampled_row,
            )

            _enforced = decides("route_v2") is not None
            _sampled = (not _enforced) and sampled_consult_ok(
                "route_v2", f"{turn_id or ''}|{(text or '')[:80]}")
            if not (_enforced or _sampled):
                return None
            eng = get_decision_engine()
            if eng is None:
                return None
            frame = self._route_v2_frame(text, self._web_mode_on())
            ds = eng.decide("route_v2", ["direct", "der"], frame)
            if ds is None or ds.chosen not in ("direct", "der"):
                return None
            if _enforced:
                return (ds.chosen == "der") if oracle_acts("route_v2", ds.confidence) else None
            row = sampled_row(
                "route_v2", ds.chosen, float(ds.confidence),
                engine=str(eng.model_id or ""),
                engine_latency_ms=ds.engine_latency_ms,
                brain_choice="der" if gate_plans else "direct",
                # its own cohort: outcome rows never pool with the parity
                # rows (route_v2/binary-v1) in a scoped report
                criteria_version="route_v2/outcome-v1",
                # outcome-labelled from birth: without a verdict (a live turn
                # swept unlabelled) decision_label leaves it unscored, never
                # "right" by default
                label_source="outcome",
                turn_id=str(turn_id or ""), state=frame)
            from backend.agent import turn_verdict_label as _tvl

            if not _tvl.defer(row, self._shadow_row_sink):
                self._shadow_row_sink(row)
            logger.info("[route_v2] sampled turn=%s oracle=%s gate=%s conf=%.3f",
                        turn_id, ds.chosen, "der" if gate_plans else "direct",
                        float(ds.confidence))
            return ds.chosen == "der"
        except Exception as e:  # noqa: BLE001 - the gate decides on any fault
            logger.debug("[route_v2] site failed: %r", e)
            return None

    def _log_route_shadow(
        self,
        *,
        turn_id: Optional[str],
        text: Optional[str],
        planned: bool,
        web_mode: bool,
        oracle_acted: bool = False,
    ) -> None:
        """Route shadow (REQ-18 AC1, task T30) â€” one JSONL row per turn.

        This is the EVIDENCE for the unified-routing flip (T33): every turn
        records which branch ran and whether the gate judged it trivial, so
        direct-vs-DER parity is measured before the direct branch is deleted.
        The classification itself is the semantic gate's answer already
        computed at the fork â€” zero extra work on the reply path. A write
        failure here must never cost a reply.
        """
        try:
            import json as _json
            import time as _time
            from pathlib import Path as _Path

            row = {
                "ts": _time.time(),
                "turn_id": turn_id or "unknown",
                "route_taken": "der" if planned else "direct",
                "would_be_trivial": not planned,
                "chars": len(text or ""),
                "web_mode": bool(web_mode),
            }
            path = (
                _Path(__file__).resolve().parents[2]
                / "data" / "route_shadow.jsonl"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(row, ensure_ascii=False) + "\n")

            # ORACLE ROUTE SHADOW (2026-10-30, reworked 2026-10-30): the
            # Oracle's pick on the ONE fork the kernel actually takes -
            # `"der" if planned else "direct"`. It NEVER acts.
            #
            # BINARY ON PURPOSE. The first cut asked a four-way question
            # (direct/der/memory_recall/memory_write) while the kernel has no
            # memory branches: memory_write and memory_recall both land on the
            # direct path. Two options that produce the same behaviour cannot
            # be calibrated - the report's precision pools them, so the engine
            # could look right on an option that changes nothing.
            #
            # `eng.shadow()` is the standard path: the row goes to
            # `_shadow_row_sink` -> the one ledger, so
            # scripts/consumer_enforcement_report.py can score it. The first
            # cut used `decide()` + a private jsonl and wrote ZERO ledger rows
            # (measured 2026-10-30: 0 route_v2 rows among 115,517 decision
            # rows). A private file is not evidence.
            #
            # The reference is what the rules did, in the same vocabulary, so
            # the row carries a parity label. It is NOT truth: the rules call
            # every memory ask "direct" because the direct path is where those
            # answers are assembled. A flip needs an OUTCOME label (did the
            # turn run a tool?), not this parity number.
            try:
                from backend.agent.decision_engine import get_decision_engine

                _eng = get_decision_engine()
                # A turn the Oracle's route drove has its own sampled row.
                if _eng is not None and not oracle_acted:
                    _incumbent = "der" if planned else "direct"
                    _frame = self._route_v2_frame(text, web_mode)
                    # input_key: the report's honest dedupe key. Without it the
                    # same goal rescored counts as NEW evidence (confidence
                    # jitters on every rescore), so "distinct rows" overstates
                    # the sample. Measured 2026-10-30: 157 route_v2 rows, 0 with
                    # an input_key, 60 distinct (chosen, confidence) pairs.
                    _key = None
                    try:
                        from backend.agent.surface_shadow import (
                            input_key as _input_key,
                        )

                        _key = _input_key("route_v2", (text or "")[:200], _frame)
                    except Exception:  # noqa: BLE001 - a missing key is not fatal
                        _key = None
                    _eng.shadow(
                        "route_v2",
                        ["direct", "der"],
                        _frame,
                        sink=self._shadow_row_sink,
                        reference={"brain_choice": _incumbent,
                                   "criteria_version": "route_v2/binary-v1",
                                   **({"input_key": _key} if _key else {})},
                    )
            except Exception as _route_err:  # noqa: BLE001 - a shadow never blocks
                logger.debug(
                    "[AgentKernel] route_v2 shadow failed: %r", _route_err
                )
        except Exception:  # noqa: BLE001 — shadow logging never blocks a reply
            pass




    @staticmethod
    def _caducean_modulate_temperature(base: float, session_id: str) -> float:
        """Phase 5: modulate planning temperature by the live Caducean recommendation.

        REQ-19 vocabulary: "COMPRESS"/"EXPAND"/"MAINTAIN" here are DER PHYSICS
        RECOMMENDATION CODES (ints 1/0/2) returned by ffi_caducean_recommend.
        They modulate temperature ONLY â€” they compact/expand NOTHING. Actual
        compaction is DCP message pruning (dcp.py) and mycelium condense/expand
        (scorer.py); Step Expansion is _growth_width->_split_step. See the
        REQ-19 vocabulary table in specs/long-horizon-der-execution/design.md.

        - COMPRESS (rec==1) -> more deterministic (temperature halved)
        - EXPAND   (rec==0) -> more exploratory (temperature *1.2, capped at 0.6)
        - MAINTAIN (rec==2) / unknown / TOPO_VIOLATION -> base unchanged

        Pure function of (base, session_id); never raises â€” returns ``base`` on
        any error so planning always proceeds.
        """
        try:
            from backend.gateway.iris_ffi import ffi_caducean_recommend

            _rec = ffi_caducean_recommend(session_id)
            if _rec == 1:  # COMPRESS
                return max(0.0, base * 0.5)
            if _rec == 0:  # EXPAND
                return min(0.6, base * 1.2)
        except Exception:
            pass
        return base

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

    # â”€â”€ ToolDecisionBox lazy factory â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # pin_517dfcbda150 â€” physics-driven web-gather sanction:
    #   _MAX_CRAWLS_PER_TASK  hard budget of DISTINCT queries per task; the
    #                         agent may gather more only by refining the query
    #                         (new hash = new job). Same-query repeats resolve
    #                         to the JobRegistry cache (tool_bridge dedupe).
    #   _GATHER_MIN_AMP       phase-manager amplitude floor: when oscillators
    #                         have collapsed (provider under load, amp relaxes
    #                         toward 1 - load_fraction) new crawls are denied
    #                         and web intent resolves to synthesis (REASON).
    _MAX_CRAWLS_PER_TASK = 3
    _GATHER_MIN_AMP = 0.35

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

    def _get_tool_box(self) -> ToolDecisionBox:
        """Return (caching) the ToolDecisionBox for this conversation.

        Lazy-constructs on first call so the box is available even when
        created before ``set_model_selection`` has run.  All dependencies
        are fetched at construction time from the kernel's current state.
        """
        if hasattr(self, "_tool_box") and self._tool_box is not None:
            return self._tool_box
        from backend.agent.tool_registry import get_registry_tools, validate_tool_call

        # memory_lookup_fn â€” consults mycelium / pheromone for tool suggestions
        # (REQ-4 AC6: memory as pre-filter, not fallback; SourceRegistry-like).
        def _mem_lookup(goal: str) -> Optional[Dict[str, Any]]:
            try:
                from backend.agent.explorer import (
                    AUTO_ENGINE, _is_web_intent, _pheromone_top1, _shape_web_query,
                )

                # â”€â”€ pin_517dfcbda150: physics-driven gather sanction â”€â”€
                # pin_42ddd255162d: the gate runs BEFORE the memory checks â€”
                # it needs no memory (conversation state + engine + scheduler
                # oscillators). Behind the old `mi is None` early return it
                # NEVER ran in the DER (whose kernel has no memory interface):
                # web-intent step 1 resolved REASON (tool=null), its short
                # result failed verification, the step split, and the children
                # re-gathered the same URLs â€” the "keeps going back to
                # searching" loop. The route + sanction below also give the
                # FIRST web-intent resolution a hard crawler_query.
                # Applies to ANY goal flavor (not just web-intent phrasing):
                # synthesis steps like "summarize the findings" are NOT web
                # intent by the classifier, yet must be prevented from
                # re-gathering once the task has committed web content.
                # Once â‰¥1 crawl ran this task:
                #   (a) converged (|u| < U_SPLIT)      -> veto gather tools,
                #   (b) new distinct query + budget hit -> veto (budget),
                #   (c) provider under load (amp low)  -> veto (load).
                # A first crawl is ALWAYS sanctioned (content must be gathered
                # once); the phase scheduler's theta pacing handles 429 load.
                try:
                    from backend.agent.der_constants import U_SPLIT
                except Exception:  # pragma: no cover - constant drift guard
                    U_SPLIT = 0.5
                # pin_42ddd255162d: key the gather-sanction state by the
                # CONVERSATION, not the execution session â€” DER split children
                # run under the placeholder session
                # "unknown", which made every child look like a fresh task and
                # bypassed the converged/budget veto (u=0.00 yet children
                # re-gathered in a 5-11ms recursion).
                _g_session = (
                    getattr(self, "conversation_id", "")
                    or getattr(self, "session_id", "")
                    or ""
                )
                # D2: stable action identity â€” deterministic digest, never
                # builtin hash() (process-randomized). Same query -> same key
                # across restarts and replay fixtures.
                try:
                    from backend.agent.der_execution_ledger import make_action_key
                except Exception:  # pragma: no cover - import drift guard
                    make_action_key = None
                _qkey = (
                    make_action_key(goal)
                    if make_action_key is not None
                    else goal.strip().lower()
                )
                _crawl_state = getattr(self, "_der_crawl_attempts", {})
                _attempted = _crawl_state.get(_g_session, set())
                logger.debug(
                    "[DER] gather gate: session=%s attempted=%d qkey_in_attempted=%s",
                    _g_session, len(_attempted), _qkey in _attempted,
                )
                # D1 (REQ-3): physics and scheduler state never AUTHORIZE here.
                # u/xi convergence and phase-manager amplitude are removed from
                # tool authorization â€” the scheduler paces calls; whether a
                # required web action may run is decided by the execution
                # policy below (fresh-query budget only). A converged oscillator
                # means stable physics, NOT task completion, and a failed step's
                # children must still be allowed to gather their sub-query.
                # D6/REQ-9: the same-query repeat is allowed â€” the JobRegistry
                # dedupe serves the cached crawl (no provider call is paid), so
                # a repeat is a read observation, not a new side effect.
                _is_web_goal = False
                try:
                    _is_web_goal = bool(_is_web_intent(
                        goal, engine=AUTO_ENGINE,
                        turn_key=getattr(self, "_current_turn_id", None),
                    ))
                except Exception:  # noqa: BLE001
                    pass
                # A goal that ACTS on a page ("open X in the browser and click
                # Y", "log in", "add to cart") is browser control, not a web
                # search: the pre-commit below would answer it with `search`
                # and the browser would never open. The tool choice (the
                # Oracle) decides it instead.
                if _is_web_goal and _BROWSER_ACTION_RE.search(goal or ""):
                    logger.info("[DER] browser-action goal -> no web pre-commit goal=%r", goal[:60])
                    _is_web_goal = False
                # Spec A4 (RC4): a quick-tier `search` that came back insufficient
                # (requires_deep_crawl) sanctions ONE escalation to crawler_query.
                # The flag is set when the search result lands and cleared when a
                # crawler_query is dispatched (_der_note_quick_tier), never here -
                # this gate runs more than once per step (session-345 finding).
                _escalate = _is_web_goal and (
                    _g_session in getattr(self, "_der_quick_insufficient", ())
                )
                _veto_reason: Optional[str] = None
                if _is_web_goal:
                    # Explicit resource bound (REQ-3 AC3): a FRESH distinct web
                    # query beyond the per-task crawl budget is vetoed. Same-key
                    # repeats skip the budget â€” but Session 312 (conv-99): a
                    # repeat is steered to an honest READ of the already-gathered
                    # documents instead of a re-dispatch, because the promised
                    # cache-served repeat never existed (D6) and every repeat
                    # re-fetched at full price. The result is already in the
                    # document store; reading it IS the repeat's value.
                    if _qkey in _attempted and not _escalate:
                        logger.info(
                            "[DER] exact-repeat gather %r -> steer "
                            "get_rendered_documents (already gathered this turn)",
                            goal[:60],
                        )
                        return {
                            "tool": "get_rendered_documents",
                            "rationale": "exact-repeat gather; read gathered docs instead of re-crawling",
                        }
                    if _qkey not in _attempted and len(_attempted) >= self._MAX_CRAWLS_PER_TASK:
                        _veto_reason = "budget_exhausted"
                if _veto_reason:
                    logger.info(
                        "[DER] web gather vetoed for goal %r -> REASON "
                        "(execution policy: %s)",
                        goal, _veto_reason,
                    )
                    return {
                        "tool": None,
                        "veto": sorted(self._WEB_CONTENT_TOOLS),
                        "rationale": _veto_reason,
                    }

                # REQ-24: a bounded content ask never acquires the research
                # lane. The user asked for reasoning ("compare OLED versus
                # LCD displays for me"), not for fresh facts, so the heavy web
                # gather tools are vetoed for THIS turn - whatever the planner's
                # step goal says (a rewritten goal like "research X vs Y" must
                # not re-open a crawl the user never asked for).
                # Freshness markers, explicit web phrasing and named evidence
                # objects are handled in the predicate: any of them means the
                # ask is NOT bounded, and the crawl lane stays open (AC3).
                if self._turn_is_bounded_content_ask():
                    logger.info(
                        "[DER] bounded content ask -> veto web gather tools "
                        "(REQ-24) goal=%r", goal[:60],
                    )
                    return {
                        "tool": None,
                        "veto": sorted(self._WEB_CONTENT_TOOLS),
                        "rationale": "bounded_content_ask",
                    }

                # Web-intent â†’ crawler_query (capability-gated, not a silent fallback)
                if _is_web_goal:
                    # Session-345 (live finding conv-124): do NOT mark the
                    # qkey here. This gate is consulted more than once per
                    # step (engine hint pass + kernel re-resolution), and a
                    # mark at PROPOSAL time means the superseded first pass
                    # makes the second pass read "already gathered this turn"
                    # and steer to get_rendered_documents â€” the search then
                    # never runs and the turn ends in an honest-but-wrong
                    # refusal. The mark happens at DISPATCH time (where the
                    # tool is actually paid for), not here.
                    from backend.agent.tool_registry import resolve_tool, capability_allowed
                    # Spec A4 (D2): a factual web goal is answered from the quick
                    # tier first - ONE provider call, no crawl - with the question
                    # shaped out of the goal sentence. crawler_query is the
                    # escalation (below), not the default.
                    if not _escalate:
                        _qspec = resolve_tool("search")
                        if _qspec and capability_allowed(_qspec):
                            _shaped_q = _shape_web_query(goal)
                            logger.info(
                                "[DER] web-intent -> search (quick tier) conv=%s query=%r",
                                _g_session, _shaped_q[:80],
                            )
                            return {
                                "tool": "search",
                                "params": {"query": _shaped_q},
                                "rationale": "web-intent (memory pre-filter)",
                            }
                    spec = resolve_tool("crawler_query")
                    if spec and capability_allowed(spec):
                        params: Dict[str, Any] = {"query": goal}
                        # Consult SourceRegistry for known URLs (learned knowledge)
                        # REQ-12 (T16): OFF the DER thread and bounded. This was
                        # `_asyncio.run(sr.resolve(goal, quick=True))` â€” building
                        # and tearing down an event loop inside the step, before
                        # the engine could even start. Now: TTL cache first, then
                        # submit to the gateway's MAIN loop with a <=100ms budget;
                        # over budget we proceed with an empty hint and the
                        # in-flight lookup's result is cached for the next step.
                        try:
                            from backend.agent.explorer import source_hint
                            _sr_loop = None
                            try:
                                from backend.iris_gateway import get_iris_gateway
                                _sr_loop = getattr(get_iris_gateway(), "_main_loop", None)
                            except Exception:  # noqa: BLE001 â€” no gateway â†’ empty hint
                                _sr_loop = None
                            sr_result = source_hint(goal, loop=_sr_loop)
                        except Exception:  # noqa: BLE001 â€” a hint never fails a step
                            sr_result = {}
                            if sr_result.get("hit") and sr_result.get("sources"):
                                known_urls = [
                                    s["url"] for s in sr_result["sources"]
                                    if isinstance(s, dict) and "url" in s
                                ][:3]
                                # Session 312 (URL-level turn memory): filter
                                # URLs this conversation already fetched â€”
                                # conv-99 served the same 4 URLs to 3 gather
                                # steps. All-filtered -> serve nothing (the
                                # crawler does fresh discovery instead of
                                # re-crawling known pages).
                                _crawled = set(getattr(self, "_der_crawled_urls", {}).get(
                                    self.conversation_id or "", set()
                                ))
                                if _crawled and known_urls:
                                    try:
                                        from backend.agent.tool_envelope import normalize_url as _norm_gate
                                        _crawled_n = set(_norm_gate(str(u)) for u in _crawled)
                                        _fresh = [u for u in known_urls if _norm_gate(str(u)) not in _crawled_n]
                                    except Exception:
                                        _fresh = [u for u in known_urls if u not in _crawled]
                                    if _fresh != known_urls:
                                        logger.info(
                                            "[DER] gather gate filtered %d/%d registry URLs already crawled this conversation",
                                            len(known_urls) - len(_fresh), len(known_urls),
                                        )
                                    known_urls = _fresh
                                if known_urls:
                                    params["known_urls"] = known_urls
                        except Exception:
                            pass  # SourceRegistry failure is non-fatal
                        # Session-318 T21-hotfix: the exclusion attach lives OUTSIDE
                        # the registry try-block above â€” a resolve throw must never
                        # skip it (unproven, but a resolve failure coinciding with
                        # a repeat repeat would re-crawl known pages silently).
                        try:
                            _visited_all = sorted(
                                getattr(
                                    self, "_der_crawled_urls", {}
                                ).get(self.conversation_id or "", set())
                            )
                        except Exception:
                            _visited_all = []
                        if _visited_all:
                            params["excluded_urls"] = _visited_all
                            logger.info(
                                "[DER] attach excluded_urls=%d to %s dispatch",
                                len(_visited_all), params.get("query", "")[:40],
                            )
                        return {
                            "tool": "crawler_query",
                            "params": params,
                            "rationale": "web-intent (memory pre-filter)",
                        }

                # REQ-3 AC4 / REQ-5 (specs/long-horizon-der-execution): once the
                # task has committed web evidence (>=1 crawl), steer SYNTHESIS
                # goals toward READING the gathered documents instead of
                # re-gathering. Advisory only â€” _apply_pre_filter keeps the
                # suggested tool alongside generic utilities, so the LLM still
                # chooses; if the read tool is unavailable the pre-filter falls
                # back to the full list. This cuts the observed 4-gather waste
                # (crawler_query x2 + search x2) and the 429 storm it caused.
                # NOTE: no resolve_tool/capability_allowed here â€” that call in
                # the hot path slowed every gate evaluation by seconds.
                try:
                    _SYNTH_TRIGGERS = (
                        "synthes", "summar", "analy", "evaluat", "compar",
                        "recommend", "conclud", "final", "write up", "explain",
                    )
                    # Session-324: steer on DURABLE conversation URL memory,
                    # not the per-turn _attempted budget. _attempted resets at
                    # every turn boundary (process_text_message), so a
                    # summarize-from-prior turn always saw attempted=0 and the
                    # steer never fired â€” live b324_web1 turn 2 resolved REASON
                    # trusting prior context, then infer returned empty twice.
                    # _der_crawled_urls survives across turns per conversation.
                    _conv_evidence323: set = set()
                    try:
                        _conv_evidence323 = set(
                            getattr(self, "_der_crawled_urls", {}).get(
                                self.conversation_id or "", set()
                            )
                        )
                    except Exception:
                        _conv_evidence323 = set()
                    _evidence_committed = bool(_attempted) or bool(_conv_evidence323)
                    if _evidence_committed and not _is_web_goal and any(
                        t in goal.lower() for t in _SYNTH_TRIGGERS
                    ):
                        logger.info(
                            "[DER] evidence-committed synthesis goal %r -> steer %s",
                            goal[:60], "get_rendered_documents",
                        )
                        return {
                            "tool": "get_rendered_documents",
                            "rationale": "evidence committed; synthesize from gathered docs",
                        }
                except Exception:  # noqa: BLE001 â€” steering is advisory
                    pass

                # Memory pre-filter (REQ-4 AC6) â€” mycelium consulted only
                # after the physics gate, which needs no memory.
                mi = getattr(self, "_memory_interface", None)
                if mi is None:
                    return None
                myc = getattr(mi, "_mycelium", None)
                if myc is None:
                    return None

                # Pheromone top-1 prediction (deterministic backstop)
                _session = getattr(self, "session_id", "") or ""
                _task = getattr(self, "_der_task_class", "full") or "full"
                _completed = list(getattr(self, "_der_completed_tools", []) or [])
                top1 = _pheromone_top1(myc, _session, _task, _completed)
                if top1:
                    return {
                        "tool": top1,
                        "params": {},
                        "rationale": "pheromone top-1 (memory pre-filter)",
                    }
                return None
            except Exception:
                return None

        # specs/tool-decision-engine: inject the resident calibrated decision
        # engine (injected, not lazily global â€” unit suites run engine-free for
        # determinism; the engine degrades to legacy path when its model is
        # absent, AC1.3). Wiring lives here so the box stays snapshot-free.
        try:
            from backend.agent.decision_engine import get_decision_engine

            _de = get_decision_engine()
        except Exception:
            _de = None

        self._tool_box = ToolDecisionBox(
            router=self._router,
            tool_bridge=self._tool_bridge,
            get_available_tools=get_registry_tools,
            validate_tool_call=validate_tool_call,
            infer_fn=self.infer,
            memory_lookup_fn=_mem_lookup,
            decision_engine=_de,
        )
        return self._tool_box

    # â”€â”€ Phase 4: concurrent step execution helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
            out = self._router.generate(role, messages, **kw)
            self._accrue_tokens("", getattr(self._router, "last_usage", None), source="run_node")
            return out

        _held: List[str] = []

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
                        brain_ok=bool(ok),
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
            )
            _node_state["ctx"] = _node_ctx
            result = run_node(goal, _node_ctx)
            _flush_decided()  # a last pick the step finished without calling
        finally:
            for _c in _held:
                _der_release(self, _c)
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
                        f"(deadline {_dispatch_deadline:g}s) â€” tool "
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

    # â”€â”€ DER Phase 0: verification (stub-kill + coarsened outcome) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # SemanticVerifier instance â€” lazy-init so import at module level is safe.
    _VERIFIER: Optional["SemanticVerifier"] = None
    _STUB_RE = re.compile(r"\[step\s+\d+\s+completed\]", re.IGNORECASE)
    # pin_517dfcbda150: web/crawl steps verify by CONTENT SUFFICIENCY â€” the
    # tool itself already proved it fetched real content (zero pages returns
    # an error at the tool boundary in tool_bridge). Assertion matching against
    # crawl output is meaningless under the hash/substring fallback while the
    # Encoder-350M is absent, and false FAILED verdicts drove the step-1
    # re-crawl loop (verify_failed -> split -> children re-crawl same query).
    _WEB_CONTENT_TOOLS = frozenset(
        {"crawler_query", "web_search", "search", "google_search", "exa_search"}
    )
    # Tools the conversation-wide REPEAT rule applies to: web fetches, whose
    # repeat returns the same page. Local tools are re-runnable (audit B3).
    # The live browser tools are NOT here (nor in _WEB_CONTENT_TOOLS): a
    # repeated click or open is a new action on a changed page, and a crawl
    # budget would cut a multi-step browser task short (S39 exempts them from
    # the dispatcher's loop guard for the same reason).
    _REPEAT_GUARDED_TOOLS = _WEB_CONTENT_TOOLS | {"fetch_url", "open_url"}
    # pin_42ddd255162d: display/render tools complete by SUCCESS, not by content
    # volume â€” a rendered-card confirmation is a legit completion, never a
    # candidate for a verify-failure split (which is what made the task card
    # say "rendering documents" while the backend re-searched).
    _TRUSTED_RESULT_TOOLS = frozenset({"get_rendered_documents"})

    def _get_verifier(self):
        if self._VERIFIER is None:
            from backend.agent.verifier import SemanticVerifier as _SV
            AgentKernel._VERIFIER = _SV()
        return self._VERIFIER

    def _der_trace_task_id(self) -> str:
        """Stable per-task key for the REQ-18 trace â€” mirrors the ledger's
        task_id (conversation_id or session_id), so the trace and the ledger
        correlate on the same task."""
        return self.conversation_id or self.session_id or "unknown"

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

    # â”€â”€ REQ-1 AC2/AC3/AC4: per-step edge scoring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    @staticmethod
    def _der_mediator_for(item: "QueueItem") -> tuple:
        """REQ-23 (T37): resolve the MEDIATOR for a finalized step.

        Returns (mediator, source):
          - mediator: ``"<tool>:<args_hash>"`` â€” the resolved tool/action
            identifier plus a stable hash of its arguments (AC1). The args
            hash is the separator between "the same tool with materially
            different arguments" (REQ-23 edge case).
          - source:   ``"explicit"`` (tool chosen by the normal resolver /
                      plan), ``"none"`` (a pure decision/synthesis node with
                      no tool â€” recorded EXPLICITLY, never empty, per AC5).

        The DER loop resolves tools through the plan/explorer path today, so
        the source is always ``"explicit"`` or ``"none"``; the ``"predictor"``
        / ``"fallback"`` sources are reserved for the T17 mediator-ranking
        wiring, which must record WHICH chooser picked the tool or the
        learning credits the wrong one (REQ-23 edge case).

        A node step has no item.tool (HANDOFF 11 B2): its mediator is the call
        that decided it (_step_decisive_call: the last failed call, else the
        last), hashed on that call's identifying args. Reading item.tool gave
        "none" for every node, so REQ-23/REQ-26 edges never learned from one.
        """
        if isinstance(getattr(item, "node_call_log", None), list):
            _call = _step_decisive_call(item)
            if not _call or not _call.get("tool"):
                return "none", "none"
            tool, _params = str(_call["tool"]), _call.get("args") or {}
        else:
            tool = getattr(item, "tool", None) or ""
            _params = getattr(item, "params", None) or {}
        if not tool:
            return "none", "none"
        try:
            _blob = json.dumps(_params, sort_keys=True, default=str)
            _args_hash = hashlib.sha256(_blob.encode("utf-8")).hexdigest()[:12]
        except Exception:
            _args_hash = "unhashable"
        return f"{tool}:{_args_hash}", "explicit"

    def _der_emit_fan_trace(
        self, item: "QueueItem", verified_label: str, session_id: str
    ) -> None:
        """GROUND TRUTH T4 (REQ-1): one der_fan_traces row per executed node.

        Same writer, same row shape, same table as the DCP path - only the CALL
        SITE moves (REQ-1 AC3). Idempotent per (session_id, step_id) so a DCP
        run cannot double-write (AC5).

        REQ-1 AC6: the node's terminal outcome is recorded FAITHFULLY. A FAILED
        node writes a failed row - a missing row and a failed row must never be
        indistinguishable, which is the whole ambiguity this spec exists to
        remove.

        Never blocks and never raises (AC4): a swallowed failure is COUNTED so
        persistent silence becomes a number rather than an absence.
        """
        try:
            _sid = session_id or "unknown"
            _step = str(getattr(item, "step_id", "") or "unknown")
            _guard = (_sid, _step)
            _seen = getattr(self, "_fan_trace_emitted", None)
            if _seen is None:
                _seen = set()
                self._fan_trace_emitted = _seen
            if _guard in _seen:
                return
            # Bounded: a very long run must not grow this without limit.
            if len(_seen) > 4096:
                _seen.clear()
            _seen.add(_guard)

            from backend.agent.caducean_trajectory import get_trajectory_recorder

            _rec = get_trajectory_recorder(self._memory_interface)
            if _rec is None:
                _write_counters.bump("fan_trace.no_recorder")
                return

            try:
                _mediator, _ = self._der_mediator_for(item)
            except Exception:
                _mediator = str(getattr(item, "tool", "") or "unknown")
            _tool = (_mediator or "unknown").split(":", 1)[0]

            _cad = self._der_live_cad_state(_sid) or {}
            _rec.record_fan_trace(
                session_id=_sid,
                step_id=_step,
                tool=_tool,
                args_hash=str(getattr(item, "args_hash", "") or "")[:12],
                outcome=str(verified_label or "UNKNOWN"),
                u=_cad.get("u"),
                xi=_cad.get("xi"),
            )
            _write_counters.bump("fan_trace.written")
        except Exception as _ft_exc:
            _write_counters.bump("fan_trace.write_failed")
            logger.warning(
                "[DER] fan trace write FAILED (session=%s step=%s): %s",
                session_id, getattr(item, "step_id", "?"), _ft_exc,
            )

    def _der_score_step_outcome(
        self,
        item: "QueueItem",
        verified_label: str,
        session_id: str,
        step_result: str,
    ) -> None:
        """Apply this step's edge-score consequence and, for FAILED, feed the
        AVOID header.

        This is deliberately a thin wiring call, not a new scorer: the deltas
        are the SAME generic table already defined in
        ``EdgeScorer._OUTCOME_DELTAS`` (scorer.py) â€” hit=+0.05, partial=+0.02,
        miss=-0.08 â€” now applied EVIDENCE-WEIGHTED (REQ-26/T40): the first
        observation on an edge moves it fully, later observations move it
        less, so belief converges instead of oscillating.

        REQ-26 AC1 (T40c): the scored edge is the (coordinate-region,
        mediator) pair for THIS step, selected by the CALLER â€” not every
        outbound edge of every active node. The REGION is the single active
        Mycelium node whose coordinates are nearest the step's live Caducean
        position Î£ = (x, y, Î¾, u) (the same state the chain row records):
        a step's outcome updates the region it was IN, and only that region.
        Scoring every active node would re-create the global fan-out the
        amendment removes â€” a step cannot fail "in two regions at once".
        The mediator is ``_der_mediator_for(item)`` (REQ-23/T37).
        ``EdgeScorer.record_region_mediator_outcome`` finds-or-creates that
        edge and updates ONLY it, so a tool that works in one region and
        fails in another is representable (a single global score cannot
        express that).

        REQ-1 AC2: VERIFIED  -> hit-scoring only (no crystallization change â€”
                   out of scope; no per-step crystallization exists today).
        REQ-1 AC3: UNVERIFIED -> partial credit, capped at
                   DER_MAX_UNVERIFIED_REPROPOSE + 1 scored attempts per
                   step_id (the original commit plus one re-propose) so an
                   UNVERIFIED step cannot be re-proposed indefinitely to farm
                   credit. Never crystallizes (no code path does today).
        REQ-1 AC4: FAILED    -> miss-scoring, and writes an episode with
                   outcome_type="miss" via the EXISTING ``_store_task_episode``
                   path â€” the same episodic-store write used for whole-task
                   outcomes â€” so evidence.py's AVOID section (which already
                   queries ``outcome_type = 'miss'``) surfaces it on the next
                   acting-prompt assembly. No second AVOID path is added.

        Never raises to the caller (see the try/except at the call site).
        """
        if verified_label not in ("VERIFIED", "UNVERIFIED", "FAILED"):
            return

        outcome = {
            "VERIFIED": "hit",
            "UNVERIFIED": "partial",
            "FAILED": "miss",
        }[verified_label]

        if verified_label == "UNVERIFIED":
            # AC3: enforce the re-propose cap BEFORE scoring â€” this is the
            # load-bearing guard, not advisory. Lazily initialised so this
            # works regardless of how the kernel was constructed (tests build
            # AgentKernel via __new__ without running __init__).
            if not hasattr(self, "_der_unverified_credit_counts"):
                self._der_unverified_credit_counts: Dict[str, int] = {}
            _count = self._der_unverified_credit_counts.get(item.step_id, 0)
            if _count > DER_MAX_UNVERIFIED_REPROPOSE:
                logger.debug(
                    "[DER] UNVERIFIED re-propose cap reached for step %s "
                    "(> %d) â€” no further partial credit",
                    item.step_id, DER_MAX_UNVERIFIED_REPROPOSE,
                )
                return
            self._der_unverified_credit_counts[item.step_id] = _count + 1

        # GROUND TRUTH T4 (REQ-1): write the per-node EXECUTION TRACE here, at
        # the node's terminal outcome - NOT as a side effect of context
        # pruning. record_fan_trace had exactly one production caller,
        # DCP._emit_fan_traces, and DCP is never constructed by the DER loop
        # (zero importers among agent_kernel / der_loop / iris_gateway). So
        # der_fan_traces held 0 rows in production no matter how much work
        # the agent did, while caducean_trajectories accumulated 201 through
        # the SAME recorder - the connection worked, only this path was
        # orphaned. Emitted BEFORE the mycelium block on purpose: the trace
        # must not inherit the edge-scoring guard's fragility (REQ-1 AC2).
        self._der_emit_fan_trace(item, verified_label, session_id)

        myc = getattr(self._memory_interface, "_mycelium", None) if self._memory_interface else None
        if myc is not None:
            try:
                _mediator, _mediator_source = self._der_mediator_for(item)
                if _mediator == "none":
                    # REQ-23 AC5: a node with NO mediator records "none" â€”
                    # there is no (region, mediator) edge to score. Pure
                    # decision/synthesis nodes are not learning events.
                    return
                _mediator_tool = _mediator.split(":", 1)[0]
                node_ids = list(getattr(myc._registry, "get_region", myc._registry.get_active)(session_id))
                # REQ-26 AC1: the step's REGION is the ONE active node whose
                # coordinates are nearest its live Î£ position â€” not every
                # active node (that would be a fan-out in region clothing).
                try:
                    _cad = self._der_live_cad_state(session_id)
                    _cad_vec = [
                        _cad.get("x", 0.0), _cad.get("y", 0.0),
                        _cad.get("xi", 0.0), _cad.get("u", 0.0),
                    ]

                    def _dist(nid: str) -> float:
                        _n = myc._store.get_node_by_id(nid)
                        if _n is None or not _n.coordinates:
                            return float("inf")
                        _c = list(_n.coordinates)[: len(_cad_vec)]
                        _v = _cad_vec[: len(_c)]
                        return sum((a - b) ** 2 for a, b in zip(_c, _v)) ** 0.5

                    # GROUND TRUTH T1 (REQ-5 AC1): distinguish "no active
                    # nodes registered at all" from "nodes exist but none
                    # resolved". Different root causes; only one is a bug
                    # in THIS block.
                    if not node_ids:
                        _write_counters.bump("edge_scoring.no_active_nodes")
                    _region_node = min(node_ids, key=_dist) if node_ids else None
                except Exception:
                    _write_counters.bump("edge_scoring.region_resolve_degraded")
                    _region_node = node_ids[0] if node_ids else None
            except Exception:
                _write_counters.bump("edge_scoring.region_resolve_failed")
                _region_node = None
                _mediator_tool = ""
            # GROUND TRUTH T1 (REQ-5 AC1, REQ-13 AC2): this guard used to
            # skip SILENTLY. mycelium_edges holds 0 rows in production
            # while this very call site exists, so the open question is
            # whether the guard never passes, the write raises, or edge
            # state lives elsewhere. A skip and a failure are DIFFERENT
            # causes and get different names.
            if not _region_node:
                _write_counters.bump("edge_scoring.skipped_no_region")
            if not _mediator_tool:
                _write_counters.bump("edge_scoring.skipped_no_mediator")
            if _region_node and _mediator_tool:
                try:
                    from backend.memory.mycelium.scorer import EdgeScorer

                    # REQ-26 AC1/T40c: the (coordinate-region, mediator)
                    # edge for THIS step â€” never the global fan-out.
                    EdgeScorer(myc._store).record_region_mediator_outcome(
                        region_node_id=_region_node,
                        mediator=_mediator_tool,
                        outcome=outcome,
                    )
                    # The POSITIVE makes the negatives interpretable:
                    # without it, zero writes and zero attempts look
                    # identical.
                    _write_counters.bump("edge_scoring.written")
                except Exception as _edge_exc:
                    # GROUND TRUTH T1: promoted from logger.debug. A
                    # swallowed WRITE failure that nothing counts is why
                    # this table could sit empty for months unnoticed.
                    _write_counters.bump("edge_scoring.write_failed")
                    logger.warning(
                        "[DER] region-scoped edge scoring FAILED "
                        "(session=%s region=%s mediator=%s): %s",
                        session_id, _region_node, _mediator_tool, _edge_exc,
                    )

        if verified_label == "FAILED":
            try:
                self._store_task_episode(
                    task_summary=item.description or "step",
                    full_content=str(step_result)[:500],
                    outcome_type="miss",
                    tool_sequence=[
                        {"tool": c.get("tool"), "step": item.step_number,
                         "success": bool(c.get("ok", True))}
                        for c in _step_calls(item)
                    ] or [{"tool": "reasoning", "step": item.step_number}],
                    session_id=session_id,
                )
            except Exception as _ep_exc:
                logger.debug(
                    "[DER] FAILED-step AVOID episode write failed: %s", _ep_exc
                )

    def _der_topic_domain(self, text: str) -> str:
        """REQ-18 AC2/AC3 (T19): resolve free text to a registry topic_domain.

        Thin wrapper over the mycelium registry resolver (extractor.py
        ``resolve_topic_domain``) so the kernel never touches keyword patterns
        directly and unknown text resolves to the registry's ``general`` bucket
        with a logged mismatch â€” never invented free text. Lazy import keeps
        the mycelium extractor off the module import path (heavy-import rule).
        """
        try:
            from backend.memory.mycelium.extractor import resolve_topic_domain

            return resolve_topic_domain(text or "")
        except Exception as _td_exc:  # noqa: BLE001 â€” never block a step
            logger.debug(
                "[DER] topic_domain resolve failed (%s) â€” falling back to "
                "'general'",
                _td_exc,
            )
            return "general"

    def _der_execution_domain(self, from_voice: bool = False) -> str:
        """REQ-18 AC2 (T19): resolve the node's execution_domain axis.

        Registry-backed: one of ``voice | der | research`` from the ACTIVE
        winding. ``voice`` when the turn entered via voice; ``research`` when
        the task class is research-shaped (research|explore|investigate, the
        same set der_loop._decide_mode uses); otherwise ``der``. This is the
        request-domain axis â€” how the node RUNS, distinct from ``topic_domain``
        (what it is ABOUT). Unknown windings resolve to the session default
        (``der``) â€” never invented free text (REQ-18 AC3).
        """
        if from_voice:
            return "voice"
        _tc = str(getattr(self, "_der_task_class", "") or "").lower()
        # TaskClassifier labels carry a "_task" suffix ("research_task");
        # the bare set never matched them (MEMORY-INTERFACE Part II 13.2).
        if _tc.endswith("_task"):
            _tc = _tc[: -len("_task")]
        if _tc in ("research", "explore", "investigate"):
            return "research"
        return "der"

    # â”€â”€ Phase 4: shared per-step finalize (extracted from _execute_plan_der)


    # â”€â”€ Physics side lane (execution audit, 2026-09-29) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # A step's Caducean update (EML observation -> integrator update -> coupling
    # -> trajectory row -> homeostasis -> controller refit -> Immortus chain ->
    # physics-event narration) is bookkeeping for the NEXT step's shape, not
    # part of this step's answer. It used to run inline in _der_finalize_step:
    # coding eval c10 spent 16-20 s of a 63 s turn inside ffi_calculate_eml on
    # the DER thread while the reply waited (logs/stackdump.log, 21:06:31-47).
    #
    # Now it runs on the ordered durability lane (one consumer, FIFO â€” the
    # physics is a sequential integrator and the chain is order-sensitive, so
    # order is preserved by construction). The CADUCEAN fold-back rule decides
    # who waits: only a DECISION about the next step's shape reads the pending
    # update (_der_physics_settle). Everything else â€” synthesis, scoring,
    # modulation â€” reads the last settled position and never waits.

    def _der_submit_physics(
        self,
        item: "QueueItem",
        *,
        node_record,
        step_success: bool,
        verified: str,
        session: str,
        from_voice: bool,
        n_children: int,
        mediator: str,
        mediator_source: str,
    ):
        """Queue this step's physics on the side lane; return its fold handle.

        Every value the job needs is bound HERE: the job runs later, and the
        step object must not be read from another thread after the loop moved
        on. ``node_record`` (coords_to) and ``item.envelope`` (coords, topology
        stop) are the two places the job writes back, both under ``fold.lock``.
        """
        from types import SimpleNamespace

        from backend.utils.durability_queue import lane as _durability_lane

        # Its own lane: a ledger or durability backlog must never delay the
        # integrator a shape decision folds back on.
        _lane_submit = _durability_lane("physics").submit

        # ready: the integrator state (u, xi, rec) is updated â€” what a shape
        #        decision reads. done: the whole job, bookkeeping included.
        fold = SimpleNamespace(
            ready=threading.Event(), done=threading.Event(), lock=threading.Lock(),
            coords_from=None, coords_to=None, rec=None,
            step=getattr(item, "step_number", None),
        )
        vals = {
            "session": session,
            "step_number": item.step_number,
            "step_id": item.step_id,
            "tool": item.tool,
            # (tool, ok) for every call a NODE step made (set in _der_run_node);
            # the physics action reads what the step did, not item.tool (None).
            "node_calls": list(getattr(item, "node_calls", None) or []),
            "success": bool(step_success),
            "verified": verified,
            "from_voice": bool(from_voice),
            "n_children": int(n_children),
            "is_subloop": bool(getattr(item, "is_subloop", False)),
            # spoken split lines name the step in plain words
            "step_description": item.description or "",
            "parent_description": getattr(item, "parent_description", "") or "",
            "parent_step_id": getattr(getattr(item, "node_record", None), "parent_step_id", "") or "",
            "execution_domain": getattr(item, "execution_domain", None)
            or ("voice" if from_voice else "der"),
            # The sector lives on the NodeRecord (stamped in _der_finalize_step before the
            # physics submit); QueueItem has no topic_domain, so reading the item alone
            # wrote "general" on every caducean_trajectories row (7,089 of 7,089, 2026-10-18).
            "topic_domain": getattr(node_record, "topic_domain", None)
            or getattr(item, "topic_domain", None) or "general",
            "insight": (item.description or "")[:120],
            "file_path": item.params.get("path", "") if item.params else "",
            "mediator": mediator,
            "mediator_source": mediator_source,
            "node_type": getattr(node_record, "node_type", "step") or "step",
            "rec_topic_domain": getattr(node_record, "topic_domain", "general") or "general",
            "rec_execution_domain": getattr(node_record, "execution_domain", "der") or "der",
            "conversation_id": self.conversation_id,
        }

        def _job() -> None:
            t0 = time.monotonic()
            try:
                self._der_physics_step(fold, vals, node_record, item)
            finally:
                fold.ready.set()
                fold.done.set()
                dt = time.monotonic() - t0
                (logger.info if dt >= 1.0 else logger.debug)(
                    "[DER] physics lane session=%s step=%s landed in %.2fs",
                    session, vals["step_number"], dt,
                )

        pending = getattr(self, "_der_physics_pending", None)
        if pending is None:
            pending = {}
            self._der_physics_pending = pending
        # Bounded: only sessions with an update in flight are kept.
        for _sid in [s for s, f in pending.items() if f.done.is_set()]:
            pending.pop(_sid, None)
        pending[session] = fold
        if not _lane_submit(f"der-physics:{session}:step_{vals['step_number']}", _job):
            fold.ready.set()
            fold.done.set()
            logger.warning(
                "[DER] physics lane full - step %s physics dropped (session=%s)",
                vals["step_number"], session,
            )
        return fold

    def _der_physics_step(self, fold, vals: dict, node_record, item) -> None:
        """One step's Caducean physics. Runs on the side lane only.

        Body moved from _der_finalize_step unchanged in effect; it reads the
        bound ``vals``, never the live step object (``item`` is used only to
        reach its envelope under fold.lock).
        """
        _session = vals["session"]
        step_success = vals["success"]
        from_voice = vals["from_voice"]
        # pin_42ddd255162d: physics reads bound BEFORE the try below â€” any early
        # exception must not leave _u/_xi unbound for the narration hook
        # (CADUCEAN_ARCHITECTURE.md Â§10 rule 7).
        _u = 0.0
        _xi = 0.0

        # â”€â”€ CADUCEAN UPDATE + IMMORTUS + TRAJECTORY RECORD â”€â”€
        try:
            from backend.gateway.iris_ffi import (
                ffi_caducean_calculate_eml,
                ffi_caducean_update,
                ffi_immortus_chain_append,
            )
            from backend.agent.caducean_trajectory import (
                format_coords,
                get_trajectory_recorder,
            )

            # REQ-5/REQ-6: capture the coordinate BEFORE this step for
            # coords_from in the Immortus chain append (below).
            _before_coord = get_trajectory_recorder(
                self._memory_interface
            ).get_latest_coordinate(_session)

            # REQ-8 redo (backend/agent/physics_action.py): the action comes from
            # what the step DID - for a node step, the tools it actually called -
            # and the balance from the v2 state EML over the design divisor. The
            # old inputs were constants (action 0, EML 12.51 -> balance 3.0), so
            # Sigma was a step counter; replayed before going live
            # (scripts/replay_sigma.py).
            from backend.agent.physics_action import balance_from_eml, step_action

            _action = step_action(vals["tool"], step_success, vals.get("node_calls"))
            _eml_score, _ex, _ey = ffi_caducean_calculate_eml(_session)
            _balance = balance_from_eml(_eml_score)
            ffi_caducean_update(_session, _action, _balance)

            # v2: fetch recommendation code AFTER the update so we can
            # detect TOPO_VIOLATION (3) and persist the new column.
            from backend.gateway.iris_ffi import (
                ffi_caducean_recommend,
                ffi_caducean_get_state,
            )

            _rec = ffi_caducean_recommend(_session)
            fold.rec = _rec
            _state_snapshot = ffi_caducean_get_state(_session)
            _xi = _state_snapshot.get("xi", 0.0)
            _u = _state_snapshot.get("u", 0.0)
            # Fold-back point: the state a shape decision reads is now
            # current. The bookkeeping below (row, homeostasis, refit, chain,
            # narration) no longer holds any decision up.
            fold.ready.set()
            # â”€â”€ REQ-10 / REQ-11: multi-session coupling (feature-flagged).
            # Register the session once with its domain windings, push live
            # (Î¾, u) into the registry, and apply coupling. The engine is
            # (re)initialized with the domain windings on first registration
            # so engine c_eff and registry c_eff agree (REQ-11 AC3). Any
            # failure logs at debug and never blocks the step (REQ-10 AC5). â”€â”€
            try:
                from backend.agent.coupled_registry import (
                    coupling_enabled,
                    get_coupled_registry,
                    domain_windings,
                )
                from backend.gateway.iris_ffi import ffi_caducean_init_session

                if coupling_enabled():
                    _domain = "voice" if from_voice else "der"
                    _l, _m = domain_windings(_domain)
                    _reg = get_coupled_registry()
                    if _reg.ensure_registered(_session, _l, _m):
                        ffi_caducean_init_session(_session, _l, _m)
                    _reg.update_session_state(_session, _xi, _u)
                    _reg.apply_coupling(_session)
            except Exception as _coupling_exc:
                logger.debug("[DER] coupling wiring skipped: %s", _coupling_exc)

            get_trajectory_recorder(self._memory_interface).record(
                session_id=_session,
                step_num=vals["step_number"],
                # One coherent position AFTER the step (same as the chain's coords_to):
                # x, y from the EML read were taken BEFORE the update while xi, u come
                # from after it, so a row mixed two moments.
                x=_state_snapshot.get("x", _ex),
                y=_state_snapshot.get("y", _ey),
                xi=_xi,
                u=_u,
                action=_action,
                outcome="success" if step_success else "failure",
                eml_after=_eml_score,
                recommendation=_rec,
                # REQ-21 (T22): carry the two ontology axes on the trajectory
                # row so per-domain physics aggregation keys on how the step
                # RAN (execution_domain) and what it was ABOUT (topic_domain).
                execution_domain=vals["execution_domain"],
                topic_domain=vals["topic_domain"],
            )

            # v2: handle TOPO_VIOLATION (rec=3) by recording the anomaly
            # to the Mycelium QuorumSensor and halting the loop.
            if _rec == 3:
                with fold.lock:
                    _der_fold_envelope(item, fold)
                # Phase 5: adapt the Duffing controller on a topological
                # violation so the engine self-corrects instead of repeatedly
                # violating the same boundary.
                try:
                    from backend.agent.trajectory_controller import TrajectoryController

                    _conn = getattr(
                        getattr(self._memory_interface, "episodic", None), "db", None
                    )
                    if _conn is not None:
                        TrajectoryController(_conn).tune_dffing_params(_session)
                except Exception as _tune_exc:
                    logger.warning(
                        "[agent_kernel] tune_dffing_params failed: %s", _tune_exc
                    )
                try:
                    self._memory_interface.mycelium_record_anomaly(
                        _session, "topological_violation"
                    )
                except Exception as _anom_exc:  # never block on this
                    logger.warning(
                        "[agent_kernel] mycelium_record_anomaly failed: %s",
                        _anom_exc,
                    )
                from .exceptions import TopologyViolationException

                # This raise ends THIS update (the lane job) only; it never
                # reaches the loop. The loop halts via _der_topology_halt at
                # the next step boundary, reading fold.rec set above.
                raise TopologyViolationException(
                    session_id=_session,
                    direction_signal=None,  # full signal in DebugPanel
                )

            # â”€â”€ Homeostatic relaxation (REQ-1 AC2) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Fire after every RELAX_EVERY_N_UPDATES (10) updates, or every
            # RELAX_MAX_INTERVAL_S (60 s) wall-clock, whichever first. A
            # relaxation failure cannot abort the trajectory record or chain
            # append below.
            try:
                global _update_counters
                with _update_counters_lock:
                    _update_counters[_session] = (
                        _update_counters.get(_session, 0) + 1
                    )
                    _uc = _update_counters[_session]
                from backend.agent.param_homeostasis import get_param_homeostasis

                get_param_homeostasis().maybe_relax(_session, _uc)
            except Exception as _relax_exc:
                logger.debug(
                    "[agent_kernel] maybe_relax failed: %s", _relax_exc
                )

            # â”€â”€ TrajectoryController refit on DER cadence (REQ-13) â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Calls TrajectoryController.fit() which refits only at milestones
            # (100, 500, 1000 records), in its own try/except so a refit
            # failure cannot abort the record or chain append.
            try:
                from backend.agent.trajectory_controller import TrajectoryController

                _tc_conn = getattr(
                    getattr(self._memory_interface, "episodic", None), "db", None
                )
                if _tc_conn is not None:
                    TrajectoryController(_tc_conn).fit()
            except Exception as _refit_exc:
                logger.debug(
                    "[agent_kernel] maybe_refit failed: %s", _refit_exc
                )

            # REQ-5/REQ-6: coords_from / coords_to in canonical format_coords.
            if _before_coord is not None:
                _coords_from = format_coords(
                    _before_coord["x"], _before_coord["y"],
                    _before_coord["xi"], _before_coord["u"],
                )
            else:
                # REQ-4 AC4.1: no prior coordinate is UNKNOWN -> NULL on the
                # row; "0.00,0.00,0.00,0.00" is a real point in the state space.
                _coords_from = None
            _coords_to = format_coords(
                _state_snapshot.get("x", _ex),
                _state_snapshot.get("y", _ey),
                _state_snapshot.get("xi", 0.0),
                _state_snapshot.get("u", 0.0),
            )
            # REQ-3 AC2 (T37): the landing coordinate on the node's memory
            # record, and on the envelope (whichever of this lane and the
            # envelope build finishes second applies it).
            with fold.lock:
                fold.coords_from = _coords_from
                fold.coords_to = _coords_to
                if node_record is not None:
                    node_record.coords_to = _coords_to
                _der_fold_envelope(item, fold)

            # The Immortus chain is a trajectory (coords_from -> coords_to):
            # appended here, on the single-consumer lane, so appends land in
            # step order.
            ffi_immortus_chain_append(
                thread_id=_session,
                result="success" if step_success else "failure",
                coords_from=_coords_from,
                coords_to=_coords_to,
                nbl_outcome=f"step_{vals['step_number']}",
                insight=vals["insight"],
                file_path=vals["file_path"],
                landmark_id="",
                # REQ-23 AC2: mediator + source ride the same chain row as the
                # Î£ coords, so (Treatment -> Mediator -> Outcome) is queryable
                # together with the coordinates that were in force.
                mediator=vals["mediator"],
                mediator_source=vals["mediator_source"],
                # REQ-18 AC4 (T19): node type + both domain axes ride the
                # chain row so recall (REQ-20) and aggregation (REQ-21) can
                # key on them without a join back to the in-memory record.
                node_type=vals["node_type"],
                topic_domain=vals["rec_topic_domain"],
                execution_domain=vals["rec_execution_domain"],
            )
        except Exception as _cad_exc:
            loud_error(_cad_exc, "caducean_trajectory_immortus")

        # â”€â”€ REQ-7: agent-driven PHYSICS-EVENT narration (post-step hook) â”€â”€
        # The agent speaks ONLY on a physics event â€” a |u| transition
        # (oscillating -> converged) or a structural event (split into
        # Sub-Loops, or a Sub-Loop collapsing). Funneled through SpeakTool
        # (narration lock) so it never conflicts with web-search progress or
        # the final answer. It reads the u/xi this update just produced, so it
        # runs here, on the lane, right after the update.
        # Invariant: spoken âŠ† visible â€” every spoken line is a real transition.
        _n_children = vals["n_children"]
        _is_subloop = vals["is_subloop"]
        _verified = vals["verified"]
        try:
            from backend.agent.der_constants import detect_physics_narration

            _u_mag = abs(float(_u)) if _u is not None else 0.0
            _narrate = detect_physics_narration(
                self._der_last_u_mag, _u_mag, _n_children, _is_subloop,
                step_description=vals.get("step_description", ""),
                parent_description=vals.get("parent_description", ""),
            )
            # "One part done" is spoken once per split, not once per child (a
            # 3-way split spoke the same line three times). A new split of the
            # step allows it again. This job runs on the ordered physics lane.
            _narrated = getattr(self, "_der_part_done_spoken", None)
            if _narrated is None or len(_narrated) > 500:
                _narrated = self._der_part_done_spoken = set()
            if _n_children:
                _narrated.discard((vals.get("session"), vals.get("step_id", "")))
            elif _is_subloop and _narrate:
                _pkey = (vals.get("session"), vals.get("parent_step_id", ""))
                if _pkey in _narrated:
                    _narrate = None
                else:
                    _narrated.add(_pkey)
            _tts_played = False
            if _narrate:
                from backend.agent.tools.speak_tool import get_speak_tool

                get_speak_tool().speak(_narrate, priority="low")
                _tts_played = True
            self._der_last_u_mag = _u_mag
            # REQ-9: record the narration decision (incl. SILENCE) to the
            # conversation-scoped observability log. u/xi carried on
            # split/collapse.
            try:
                from backend.agent.narration import NarrationLog

                _nlog = NarrationLog(vals["conversation_id"])
                _decision = "brief" if _narrate else "silence"
                # u/xi only meaningful on a structural event.
                _has_struct = bool(_n_children) or _is_subloop
                # pin_42ddd255162d: direct sync write (a small JSONL append).
                _nlog._write(
                    {
                        "ts": time.time(),
                        "conversation_id": vals["conversation_id"],
                        "step_id": vals["step_id"],
                        "decision": _decision,
                        "signal": (
                            "retried"
                            if _n_children
                            else (
                                "crystallized"
                                if _verified == "VERIFIED"
                                else "avoided"
                            )
                        )
                        if _has_struct
                        else None,
                        "u": float(_u) if _u is not None else None,
                        "xi": float(_xi) if _xi is not None else None,
                        "text": _narrate or "",
                        "tts_played": _tts_played,
                    },
                )
            except Exception as _nlog_exc:
                logger.debug("[DER] narration log skipped: %s", _nlog_exc)
        except Exception as _narr_exc:
            logger.debug("[DER] physics-event narration skipped: %s", _narr_exc)
            try:
                self._der_last_u_mag = (
                    abs(float(_u)) if _u is not None else 0.0
                )
            except Exception:
                pass

    def _der_finalize_step(
        self,
        item: "QueueItem",
        step_result: str,
        step_success: bool,
        step_outputs: list,
        completed_items: list,
        _tokens_used: int,
        _token_budget: int,
        _session: str,
        _turn_id: Optional[str],
        _phase: int,
        is_mature: bool,
        _live_ctx,
        plan,
        context_package,
        queue,
        verdict,
        from_voice: bool = False,
    ) -> int:
        """
        Phase 4: full post-processing for one completed DER step.
        Faithful extraction of the inline finalize block from _execute_plan_der
        so both the serial path and concurrently-executed parallel_safe steps
        share identical post-processing. Returns the updated _tokens_used.

        ``from_voice`` (pin_517dfcbda150): threaded from the turn entry so the
        multi-session coupling wiring inside this method can classify the
        session domain ("voice" vs "der") instead of raising NameError.
        """
        # Session 312 (Pacman-only context flow, user-directed): the raw step
        # result used to enter the inline flow UNBOUNDED â€” three crawls put
        # 71.5k chars of page text into a 64k window (conv-99). The DB keeps
        # the full text (Pacman fragments + document store); the context
        # window gets the SAME bounded excerpt the evidence path uses
        # (gather tools 8000, others 400). Raw text lives in memory, not in
        # the window.
        # The SAME bounded text the window receives is what the budget must bill
        # (session-366 track C): keep it in a local so the token meter below
        # charges the excerpt, not the raw result.
        _window_evidence = self._smart_excerpt(
            step_result, _step_evidence_cap(item)
        )
        step_outputs.append(_window_evidence)
        # Session 312 / Session-318 / Session-319: turn URL memory is harvested
        # by ONE shared helper so the FAILURE path records addresses too (that
        # path skips this function entirely â€” see _der_handle_step_failure).
        # Behaviour here is unchanged; the body simply moved.
        _remember_turn_urls(self, step_result, "finalize")

        # â”€â”€ EventBus: emit tool:result or tool:error â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            _lifecycle_task_id = _turn_id or item.step_id
            if step_success:
                get_event_bus().emit(
                    IRISStreamEvent.TOOL_RESULT,
                    data={
                        "task_id": _lifecycle_task_id,
                        "result_summary": step_result[:200],
                        "tool_name": _step_tool_name(item),
                        "step_number": item.step_number,
                        # REQ-3 AC6 (T2): card_id stays stable across every
                        # event of a card's lifetime.
                        **self._card_envelope(_lifecycle_task_id),
                        # Edit diffs: `diff` = the step's latest edit; `diffs` =
                        # every edit when the step made more than one.
                        **_edit_diff_fields(item),
                    },
                    turn_id=_turn_id,
                    conversation_id=self.conversation_id,
                    session_id=_session,
                )
            else:
                get_event_bus().emit(
                    IRISStreamEvent.TOOL_ERROR,
                    data={
                        "task_id": _turn_id or item.step_id,
                        "error": step_result[:200],
                        "tool_name": _step_tool_name(item),
                        "step_number": item.step_number,
                    },
                    turn_id=_turn_id,
                    conversation_id=self.conversation_id,
                    session_id=_session,
                )
        except Exception:
            pass
        # T13 (REQ-10 AC10.11): the tool finished â€” close its narratable wait.
        # Results voice via the reply path; exit itself stays silent.
        try:
            self._end_tool_wait(_lifecycle_task_id)
        except Exception:
            pass

        # Option B / Pacman: fragment DER step output into vector DB so it can be
        # retrieved as context in later steps or future sessions.
        # MCM orchestrator handles fragmentation + compression check when available.
        try:
            if step_result and step_success:
                _der_text = (
                    f"[Step {item.step_number}: {item.description[:120]}]"
                    f"\n{step_result}"
                )
                # Trust-routing W2: a DER step that used an external/web
                # tool stores its output in 'reference', not 'tool'.
                _der_zone = (
                    "reference" if is_external_tool(getattr(item, "tool", "")) else None
                )
                if self._mcm_orch is not None:
                    # REQ-22: forward untrusted web scoring into the pacman
                    # fragment so credibility_map / citation_index persist in
                    # the 'reference' zone (only when the step used a web tool).
                    _cm = None
                    _ci = None
                    if isinstance(step_result, dict):
                        _cm = step_result.get("credibility_map")
                        _ci = step_result.get("citation_index")
                    self._mcm_orch.post_turn(
                        [{"role": "assistant", "content": _der_text}],
                        response_text=_der_text,
                        tool_name=getattr(item, "tool_name", ""),
                        zone=_der_zone,
                        credibility_map=_cm,
                        citation_index=_ci,
                    )
                elif (
                    self._memory_interface is not None
                    and hasattr(self._memory_interface, "episodic")
                    and hasattr(
                        self._memory_interface.episodic, "fragment_and_store"
                    )
                ):
                    # Background, same writer as every other fragment path â€”
                    # see the note at the document_data store above.
                    from backend.agent.mcm_protocol.actions.pacman_fragment import (
                        _submit_fragment_job,
                    )

                    _ep = self._memory_interface.episodic
                    _submit_fragment_job(
                        lambda: _ep.fragment_and_store(
                            _der_text,
                            session_id=_session,
                            chunk_type="der_output",
                            zone=_der_zone,
                        ),
                        f"der_output/step{getattr(item, 'step_number', '?')} "
                        f"({len(_der_text)} chars)",
                    )
        except Exception as _frag_exc:
            loud_error(_frag_exc, "der_pacman_fragment")

        # A3 FIX: also fragment FAILED outputs so failures are remembered and can
        # steer future recovery (the success path above skips them). Stored in the
        # 'tool' zone with chunk_type 'der_failure' for later recall.
        try:
            if step_result and not step_success:
                _fail_text = (
                    f"[FAILED Step {item.step_number}: {item.description[:120]}]"
                    f"\n{step_result}"
                )
                if (
                    self._memory_interface is not None
                    and hasattr(self._memory_interface, "episodic")
                    and hasattr(
                        self._memory_interface.episodic, "fragment_and_store"
                    )
                ):
                    from backend.agent.mcm_protocol.actions.pacman_fragment import (
                        _submit_fragment_job,
                    )

                    _ep_f = self._memory_interface.episodic
                    _submit_fragment_job(
                        lambda: _ep_f.fragment_and_store(
                            _fail_text,
                            session_id=_session,
                            chunk_type="der_failure",
                            zone="tool",
                        ),
                        f"der_failure/step{getattr(item, 'step_number', '?')} "
                        f"({len(_fail_text)} chars)",
                    )
        except Exception as _fail_frag_exc:
            loud_error(_fail_frag_exc, "der_pacman_fragment_failure")

        # â”€â”€ TOKEN BUDGET: accumulate estimated tokens from step result â”€â”€
        # 4 chars â‰ˆ 1 token; also count prompt overhead per step (~200 tok)
        # Session 366 (track C): bill the BOUNDED evidence the window actually
        # receives, not the raw tool result. MEASURED: a 16384-token window
        # yields a 13270-token budget; one crawl's RAW result charged ~12k
        # tokens and exhausted the turn after 6 of 10 steps
        # (`plan:budget_exhausted`, 15138/13270) while the window only ever got
        # the bounded excerpt (_window_evidence: gather tools 8000 chars, others
        # 400 - see the note above). Raw text lives in durable memory, not in the
        # window, so metering raw charged the model for tokens it never reads and
        # one large result killed the chain. 4 chars ~= 1 token, + ~200 prompt
        # overhead per step.
        _tokens_used += max(200, len(_window_evidence) // 4)
        # â”€â”€ EventBus: emit context:usage (token budget progress) â”€â”€â”€â”€â”€â”€
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            get_event_bus().emit(
                IRISStreamEvent.CONTEXT_USAGE,
                data={
                    "used_tokens": int(_tokens_used),
                    "max_tokens": int(self.resolve_context_window()),
                    "step_number": item.step_number,
                    "total_steps": len(queue.items),
                },
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
        except Exception:
            pass  # EventBus is optional â€” no crash if it fails
        if _tokens_used >= _token_budget:
            logger.info(
                f"[DER] Token budget exhausted ({_tokens_used}/{_token_budget}) "
                f"after step {item.step_number} â€” stopping early"
            )
            # RC6 FIX: emit explicit event instead of silent stop
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent

                _remaining = len([
                    i for i in queue.items
                    if i.step_id not in queue.completed_ids
                    and i.step_id not in queue.failed_ids
                ])
                get_event_bus().emit(
                    IRISStreamEvent.BUDGET_EXHAUSTED,
                    data={
                        "task_id": _turn_id,
                        "steps_completed": len(completed_items),
                        "steps_remaining": _remaining,
                        "tokens_used": _tokens_used,
                        "token_budget": _token_budget,
                        "message": f"Task incomplete: {_remaining} steps remaining "
                                   f"(budget {_tokens_used}/{_token_budget} exhausted)",
                    },
                    turn_id=_turn_id,
                    session_id=_session,
                )
            except Exception:
                pass  # EventBus is optional â€” no crash if it fails

        # â”€â”€ MYCELIUM SIGNAL: tool call â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            _mycelium_ingest_step_tools(
                self._memory_interface, item, step_success,
                len(queue.items), _session,
            )
        except Exception as _wm_exc:
            loud_error(_wm_exc, "mycelium_working_memory")

        # Phase 0 fix (Gap 5): populate step result on the QueueItem so
        # downstream consumers (reviewer, trace) read real output instead of
        # "no result".
        item.result = step_result

        # DER Phase 0 (D0.1): verify the result. A stub pattern with no real output
        # is FAILED -> step_success forced False so it cannot be marked complete as a
        # success (no silent success edge). This is the honest-signal fix.
        # pin_517dfcbda150: pass the resolved tool so web/crawl steps verify by
        # content sufficiency instead of assertion matching. A node step has
        # no item.tool; its decisive call is the tool (_step_calls chokepoint).
        _verified = self._verify_step_result(
            item.description, item.expected_output, step_result,
            tool=_step_tool(item),
            success=step_success,
        )
        if _verified == "VERIFIED" and _node_failed_after_change(item):
            _verified = "UNVERIFIED"
            logger.info(
                "[DER] step %s UNVERIFIED: it changed files and its last run after "
                "the change failed", getattr(item, "step_id", "?"),
            )
        if _verified == "FAILED":
            step_success = False

        # REQ-18 AC1 (T31): the verified LABEL for this step is only known here
        # (after full classification). Attach it to the verify trace entries
        # recorded by _verified_fraction above, then add the label record.
        try:
            from backend.agent.der_trace import get_der_trace

            get_der_trace(self._der_trace_task_id()).record(
                "verify_label",
                verified_label=_verified,
                step_id=getattr(item, "step_id", ""),
                step_number=getattr(item, "step_number", 0),
                tool=getattr(item, "tool", None),
            )
        except Exception:
            pass

        _der_prior_research_delivered(self, item, step_result, _session)

        # Spec D9 (Wave E): the step becomes a typed event (BUG / ATTEMPT /
        # DEAD_END / FIX ...) with the label the verifier gave it - event-level
        # credit. Values are bound now; the write runs on its own lane.
        _memory_events_submit(
            self, "record_step",
            thread_id=_session,
            task_id=f"{_session}:{_turn_id or ''}",
            step_id=str(getattr(item, "step_id", "") or ""),
            # The decisive call (the last failed one, else the last): a node
            # step has no item.tool, so record_step saw "none" and a coding
            # node's test run never counted as a test command.
            tool=(_step_decisive_call(item) or {}).get("tool") or getattr(item, "tool", None),
            params=(dict((_step_decisive_call(item) or {}).get("args") or {})
                    or (dict(item.params) if isinstance(getattr(item, "params", None), dict) else None)),
            success=bool(step_success),
            verified=str(_verified or ""),
            error_text=(str(step_result or "")[:2000] if not step_success else ""),
            description=str(getattr(item, "description", "") or "")[:300],
            recall_trace_ids=list(getattr(item, "recall_trace_ids", None) or []),
        )

        # â”€â”€ Phase 2 (D2.1): unified recovery â€” verification FAILED uses the
        # SAME _split_step operator as the physics trigger. No separate graft
        # code path remains. Split prepays work units up front (Lyapunov Phi
        # strictly decreases). Children are Sub-Loops (is_subloop=True) that
        # collapse back to this step as ONE COMPRESS. â”€â”€
        # BUGFIX (REQ-8 AC3): this block used to run at the very end of the
        # function (right before `return _tokens_used`), but `_children` is
        # READ much earlier â€” by the REQ-8 task:learning emit below and by the
        # REQ-7 physics-narration hook â€” while it is only ASSIGNED here. Since
        # a name assigned anywhere in a Python function is local for the whole
        # function, every earlier read raised `UnboundLocalError: cannot
        # access local variable '_children' where it is not associated with a
        # value`, silently caught by each call site's own try/except so the
        # task:learning event (and the physics narration) never fired. Moved
        # up so `_children` is a real, already-computed value at every read
        # site. `_children` defaults to `[]` (no split) so the success path â€”
        # which never enters the split branch â€” still has a bound, honestly
        # falsy value instead of leaving the name unbound.
        _children = []
        # REQ-13 (fold forward, not back): only a FAILED verification may enter
        # the split gate. A weak (UNVERIFIED) graded score after evidence
        # gathering folds forward to an honest low-confidence answer instead of
        # spawning another round of gathering the same evidence (AC1). The
        # guard is EXPLICIT, not incidental: an execution-layer `success=False`
        # envelope that still carried content (REQ-1 informational-fallback
        # edge) would otherwise reach _split_step untouched by the D4 taxonomy
        # below (non-errored content skips classification). The D4/REQ-4
        # classes remain the ONLY no-split path for classified
        # transport/provider failures (AC2); _split_step stays reachable for
        # genuine unclassified semantic failure (AC3).
        if not step_success and not item.is_subloop and _verified == "FAILED":
            # D4/REQ-4 (specs/long-horizon-der-execution): classify the failure
            # BEFORE recursive fan-out. Transport/provider/envelope failures
            # (timeout, rate-limit, unavailable tool, bad args, empty result,
            # auth) are recorded as failure evidence and must NOT split the
            # task into children â€” the old `not step_success -> split` rule
            # turned a single transient error into a recursive fan-out. Only a
            # genuine semantic failure (tool produced content but verification
            # judged it wrong) splits: the step_result then carries real
            # content, not an error prefix.
            _split_ok = True
            try:
                from backend.agent.der_execution_ledger import (
                    classify_failure,
                    ExecutionLedger,
                    OUTCOME_TRANSIENT,
                    OUTCOME_UNAVAILABLE,
                    OUTCOME_INVALID_ARGS,
                    OUTCOME_EMPTY,
                    OUTCOME_PERMANENT,
                )

                _res_text = (step_result or "").strip()
                _res_low = _res_text.lower()
                _tool_errored = (
                    not _res_text
                    or _res_low.startswith("error")
                    or _res_low.startswith("[step error")
                    or _res_low.startswith("duplicate call")
                )
                if _tool_errored:
                    _fail_class = classify_failure(
                        False,
                        error=_res_text[:400],
                        error_type=getattr(item, "error_type", None),
                        result=step_result,
                    )
                    if _fail_class in (
                        OUTCOME_TRANSIENT,
                        OUTCOME_UNAVAILABLE,
                        OUTCOME_INVALID_ARGS,
                        OUTCOME_EMPTY,
                        OUTCOME_PERMANENT,
                    ):
                        _split_ok = False
                        logger.info(
                            "[DER] step %s failure classified=%s â€” recorded, NOT split (D4)",
                            item.step_id, _fail_class,
                        )
                        try:
                            _ledger = getattr(self, "_der_ledger", None)
                            if _ledger is None:
                                _ledger = ExecutionLedger(
                                    conversation_id=self.conversation_id or "",
                                    storage_path=_der_ledger_storage_path(),  # GROUND TRUTH T9 (REQ-14 AC1)
                                )
                                self._der_ledger = _ledger
                            _ledger.record_failure(
                                task_id=self.conversation_id or self.session_id or "unknown",
                                step_id=item.step_id,
                                attempt_id=getattr(item, "attempt_id", "") or item.step_id,
                                failure_class=_fail_class,
                                input_summary=(item.description or "")[:200],
                                tool=_step_tool(item),
                                error_type=getattr(item, "error_type", None),
                                error_summary=_res_text[:300],
                                recovered=False,
                            )
                        except Exception as _led_exc:  # noqa: BLE001
                            logger.debug("[DER] failure-evidence record failed: %s", _led_exc)
            except Exception:  # noqa: BLE001 â€” classification must never break recovery
                _split_ok = True
            if _split_ok:
                try:
                    # Fold-back: split width is a shape decision (side lane).
                    _der_physics_settle(self, _session)
                    _cad_split = self._der_live_cad_state(_session)
                    _wu = getattr(self, "_der_work_units", 0)
                    # REQ-4 AC1 (T16): the continuous verified fraction is a
                    # GRADED steering input at the split decision â€” mid-band
                    # selects a bounded probe (width 1) instead of a full-width
                    # re-attempt. Never crash the split on fraction failure.
                    try:
                        _vf_split = self._verified_fraction(
                            getattr(item, "expected_output", None),
                            str(step_result or ""),
                        )
                    except Exception:
                        _vf_split = 0.0
                    _children = self._split_step(
                        item,
                        "verify_failed",
                        _cad_split,
                        _wu,
                        step_result=step_result,
                        verified_fraction=_vf_split,
                    )
                    # REQ-3: debit measured tokens, not a flat child count.
                    # _measured must be bound for the debit even when no child was
                    # created (empty split) â€” a NameError here was silently swallowed
                    # by the broad except, disabling the work-unit debit entirely
                    # (NORTHSTAR defect-shape #1).
                    _measured = 0
                    if _children:
                        # The children run as nodes (their own tool loops).
                        self._der_route_subloop_children(
                            _children, queue, _session, _turn_id
                        )
                        # REQ-3: debit measured tokens, not a flat child count.
                        _measured = max(200, len(step_result) // 4)
                        # REQ-14 (AC1/AC5, T23): a sub-loop split REVISES the
                        # plan mid-task â€” re-emit task:start through the SAME
                        # merge-by-id channel (useTaskProgress.ts:210-227) with
                        # the revision origin so the frontend refreshes
                        # description/tool for new steps without clobbering live
                        # status, and REQ-18's trace can attribute the origin.
                        # The payload keeps the contract keys unchanged
                        # (task_id/description/plan_title/mode/steps/total_steps)
                        # plus `origin`.
                        try:
                            from backend.agent.event_bus import (
                                get_event_bus,
                                IRISStreamEvent,
                            )

                            _rev_mode = (
                                queue.mode.value
                                if getattr(queue, "mode", None)
                                else str(_phase)
                            )
                            # REQ-3 (T2) edge case: a sub-loop split CONTINUES
                            # the parent card â€” it is a branch WITHIN a card,
                            # never a second card. Handled generically by the
                            # "not initial" rule in _resolve_card_identity.
                            _card_task_id = _turn_id or getattr(
                                plan, "original_task", ""
                            )[:40]
                            _card_id, _card_relation = self._resolve_card_identity(
                                _card_task_id, "sub_loop_split"
                            )
                            # T2b (REQ-1 AC8): the badge marks the nested row,
                            # so the label is set on the CHILD steps this
                            # split just produced â€” never on the parent or
                            # any sibling already in the queue. A step
                            # outside `_children` carries no `branchLabel`
                            # key at all (not an empty string), so
                            # ChassisBranchBadge renders on branch rows only.
                            _branch_child_ids = {c.step_id for c in _children}
                            get_event_bus().emit(
                                IRISStreamEvent.TASK_START,
                                data=self._task_start_payload(
                                    task_id=_card_task_id,
                                    description=getattr(
                                        plan, "original_task", ""
                                    )[:200],
                                    plan_title=self._effective_plan_title(plan),
                                    mode=_rev_mode,
                                    steps=[
                                        {
                                            "id": it.step_id,
                                            "description": it.description,
                                            "status": "pending",
                                            "toolName": _step_tool(it),
                                            **(
                                                {"branchLabel": DER_SUBLOOP_BRANCH_LABEL}
                                                if it.step_id in _branch_child_ids
                                                else {}
                                            ),
                                        }
                                        for it in queue.items
                                    ],
                                    total_steps=len(queue.items),
                                    origin="sub_loop_split",
                                    # REQ-3 (T2): backend-declared card identity.
                                    card_id=_card_id,
                                    card_relation=_card_relation,
                                    conversation_id=self.conversation_id,
                                        turn_id=getattr(self, "_current_turn_id", None),
                                    **self._multiagent_tags(),
                                ),
                                turn_id=_turn_id,
                                conversation_id=self.conversation_id,
                                session_id=_session,
                            )
                            # T4a (REQ-4 AC1): persist the split card. Uses
                            # _queue_steps_snapshot (derives done/failed from
                            # queue state) rather than the wire payload's
                            # blanket "pending" â€” a mid-run restore should
                            # show already-finished steps as finished.
                            self._persist_card_snapshot(
                                card_id=_card_id,
                                conversation_id=self.conversation_id,
                                card_relation=_card_relation,
                                plan_title=self._effective_plan_title(plan),
                                mode=_rev_mode,
                                steps=self._queue_steps_snapshot(queue),
                                total_steps=len(queue.items),
                                terminal_state="running",
                            )
                            # REQ-18 AC3 (T31): correlate the sub-loop-split
                            # revision (REQ-4/REQ-13).
                            try:
                                from backend.agent.der_trace import get_der_trace

                                get_der_trace(self._der_trace_task_id()).record(
                                    "revision",
                                    origin="sub_loop_split",
                                    children=len(_children),
                                    boundary_step=getattr(
                                        queue, "_last_step_number", None
                                    ),
                                )
                            except Exception:
                                pass
                        except Exception:
                            pass  # EventBus is optional â€” never break recovery
                    self._der_work_units = debit_work_units(_wu, _measured)
                    logger.info(
                        "[DER] verify_failed -> split into %d sub-loops (work_units=%d)",
                        len(_children), self._der_work_units,
                    )
                except Exception as _split_exc:
                    logger.warning("[DER] split-on-failure failed: %s", _split_exc)

        # â”€â”€ Phase 3 (D3.3 G5): honest commit ledger â”€â”€
        # REQ-1: a commit is recorded for EVERY executed action with its true label
        # (VERIFIED / UNVERIFIED / FAILED) â€” not only VERIFIED. This is the learning
        # signal the outer loop and the AVOID/edge-miss path consume; gating it on
        # VERIFIED starves failure learning. Store write â€” never injected into a
        # prompt.
        # D1 (HANDOFF 11): the write runs on lane("memory_events"), never on
        # the answer path - inline it waited on "database is locked" (live
        # 2026-10-04 r06: a 22 s gap in a 42 s reply). No reader decides on
        # der_commits in the same turn (the outer loop reads it between
        # sessions). The state is read NOW; only the row lands later.
        try:
            from backend.agent.caducean_trajectory import (
                get_trajectory_recorder,
            )
            from backend.utils.durability_queue import lane as _durability_lane

            _cad = self._der_live_cad_state(_session)
            _commit_step = getattr(item, "step_id", "?")
            _commit_kw = dict(
                session_id=_session,
                step_id=item.step_id,
                commit_hash="",
                message=f"{_verified} step {item.step_number}: {item.description[:80]}",
                u=_cad.get("u"),
                xi=_cad.get("xi"),
                verified_label=_verified,
            )
            _commit_mi = self._memory_interface

            def _commit_job():
                try:
                    # REQ-20: DER commits land in the APPLICATION store
                    # (memory_interface episodic db), not .mcm/coordinates.db.
                    get_trajectory_recorder(_commit_mi).record_commit(**_commit_kw)
                    # GROUND TRUTH T5 (REQ-2 AC1/AC4): count commits BY LABEL
                    # at the write, so a failing write and a missing one differ.
                    _write_counters.bump("commit.written")
                    _write_counters.bump(
                        "commit.label.%s" % str(_verified or "UNKNOWN").lower())
                except Exception as _commit_exc:
                    # GROUND TRUTH T5/T10: a swallowed commit write must stay
                    # visible as a number and a warning.
                    _write_counters.bump("commit.write_failed")
                    logger.warning(
                        "[DER] record_commit FAILED (session=%s step=%s label=%s): %s",
                        _session, _commit_step, _verified, _commit_exc,
                    )

            if not _durability_lane("memory_events").submit("der_commit", _commit_job):
                _write_counters.bump("commit.write_failed")
        except Exception as _commit_exc:
            _write_counters.bump("commit.write_failed")
            logger.warning(
                "[DER] record_commit FAILED (session=%s step=%s label=%s): %s",
                _session, getattr(item, "step_id", "?"), _verified, _commit_exc,
            )

        # â”€â”€ REQ-1 AC2/AC3/AC4: per-step edge-score consequence of verified_label.
        # VERIFIED hit-scores (+0.05), UNVERIFIED partial-credits (+0.02, capped â€”
        # AC3) and never crystallizes, FAILED miss-scores (-0.08) and feeds the
        # AVOID header (AC4). Never raises. INLINE on purpose: the next step of
        # this turn decides on what it writes (explorer tool choice reads the
        # tool_choice edges, the AVOID header and the recovery graft read the
        # miss episode), so a lane would hand them a stale view. Node steps
        # score here since S54; a slow run is logged so a cost shows up.
        # tc-decide-v7: the decided tool_choice rows are stamped in
        # _der_post_step, after the post-finalize artifact graft decides whether
        # this step was retried. A stamp here would run before the graft and
        # call a grafted step "completed".

        try:
            _score_t0 = time.monotonic()
            self._der_score_step_outcome(item, _verified, _session, step_result)
            _score_s = time.monotonic() - _score_t0
            if _score_s > 0.25:
                logger.warning(
                    "[DER] slow step scoring %.2fs (step=%s label=%s)",
                    _score_s, getattr(item, "step_id", "?"), _verified,
                )
        except Exception as _score_exc:
            _write_counters.bump("step_outcome.scoring_failed")
            logger.warning(
                "[DER] per-step edge scoring FAILED (step=%s): %s",
                getattr(item, "step_id", "?"), _score_exc,
            )

        if _children and not getattr(item, "is_subloop", False):
            # Fold-back (parallel nodes, 2026-10-04): the step's verification
            # FAILED and it split - it waits for its children (the race)
            # instead of completing, so its dependents wait for the resolution.
            queue.hold_split_parent(item.step_id, [c.step_id for c in _children], [])
        else:
            queue.mark_complete(item.step_id)

        # â”€â”€ T6/T8/T10 (specs/long-horizon-der-execution REQ-5/REQ-9) â”€â”€â”€â”€â”€â”€
        # D8: persistence gates terminal state. Close the execution-attempt in
        # the ledger and persist BEFORE emitting the terminal task:learning
        # event. A persistence failure is exposed honestly (warning) and the
        # event still fires â€” but the durable record is flagged, never silently
        # claimed.
        try:
            from backend.agent.der_execution_ledger import ExecutionLedger

            _ledger = getattr(self, "_der_ledger", None)
            if _ledger is None:
                _ledger = ExecutionLedger(
                    conversation_id=self.conversation_id or self.session_id or "",
                    storage_path=_der_ledger_storage_path(),  # GROUND TRUTH T9 (REQ-14 AC1)
                )
                self._der_ledger = _ledger
            _att = _ledger.open_attempt(
                task_id=self.conversation_id or self.session_id or "unknown",
                step_id=item.step_id,
                parent_step_id=getattr(item, "parent_step_id", None),
                action_key=(item.description or item.tool or "")[:80],
                tool=_step_tool(item),
            )
            _ledger.close_attempt(
                _att,
                outcome=_verified if _verified in ("VERIFIED", "UNVERIFIED", "FAILED") else "permanent",
                verified_label=_verified,
                error_type=getattr(item, "error_type", None),
            )
            if not _ledger.persist():
                logger.warning(
                    "[DER] attempt persistence FAILED for step %s â€” durable completion not claimed",
                    item.step_id,
                )
        except Exception as _att_exc:  # noqa: BLE001 â€” ledger must never block the step
            logger.debug("[DER] attempt-ledger write failed: %s", _att_exc)

        # â”€â”€ REQ-8: honest learning signal (task:learning) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Emited (never injected into a prompt) so the frontend can show the real
        # card state + Pacman OrbCanvas particles on the border. Three signals:
        #   avoided    â€” FAILED step (no children, not a subloop) -> AVOID
        #   retried    â€” verify_failed -> split into Sub-Loops
        #   crystallizedâ€” VERIFIED step -> skill captured
        # Off the critical path; a bus failure must never block the step result.
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            if _verified == "VERIFIED":
                _signal = "crystallized"
            elif _children:
                _signal = "retried"
            else:
                _signal = "avoided"
            get_event_bus().emit(
                IRISStreamEvent.TASK_LEARNING,
                {
                    "session_id": _session,
                    "step_id": item.step_id,
                    "step_number": item.step_number,
                    "signal": _signal,
                    "verified_label": _verified,
                    "description": item.description or "",
                    "is_subloop": bool(getattr(item, "is_subloop", False)),
                },
            )
        except Exception as _learn_exc:
            logger.debug("[DER] task:learning emit failed: %s", _learn_exc)

        # â”€â”€ Phase 3 (Gap 3): propagate this step's output into dependent
        # pending steps so later steps consume real results, not static
        # params. Non-blocking â€” never fails the step. â”€â”€
        try:
            queue.resolve_dependent_params(item, step_result)
        except Exception as _dep_exc:
            logger.warning(
                "[DER] resolve_dependent_params failed: %s", _dep_exc
            )

        # â”€â”€ Caducean physics -> ordered side lane (_der_submit_physics) â”€â”€
        # The node record is stamped HERE, inline: synthesis and the
        # continuation consult read it. The physics update (EML, integrator,
        # trajectory row, homeostasis, refit, Immortus chain, physics-event
        # narration) is queued right after and lands off the answer path; the
        # next shape decision folds back on it (_der_physics_settle).
        _mediator, _mediator_source = "none", "none"
        _phys = None
        try:
            # REQ-23 (T37): the causal triple â€” resolve the MEDIATOR once and
            # bind it to a VALUE (the write runs later; `item` must not be
            # read from another thread after the loop moves on). AC1: written
            # at the same finalize point as the outcome; AC5: "none" is the
            # explicit value for mediator-less (decision/synthesis) nodes,
            # never empty â€” so they do not rank as failed actions.
            _mediator, _mediator_source = self._der_mediator_for(item)
            # REQ-3 AC2 (T37 completion): stamp the node's memory record at
            # finalize â€” outcome, continuous fraction, mediator, and the
            # landing coordinate â€” so the record is complete for the causal
            # vocabulary (Treatment -> Mediator -> Outcome) and for the
            # REQ-26 posterior reader. Off the critical path; never fails the
            # step.
            try:
                _rec = getattr(item, "node_record", None) or getattr(
                    item, "footprint", None
                )
                if _rec is None:
                    # Every node carries its record (REQ-3 T8), and this is
                    # where outcome, goal coverage and mediator land. Steps
                    # added after planning (continuation, recovery, steering
                    # and revise replans, recovery grafts) were built without
                    # one, so their results never counted: a "cover the open
                    # fact" step searched the fact, it stayed open, was pushed
                    # again and blocked (eval r09 conv-836, 2026-10-05).
                    from backend.agent.der_loop import NodeRecord

                    _rec = NodeRecord(
                        step_id=str(getattr(item, "step_id", "") or ""),
                        parent_step_id="",
                        objective_anchor=str(getattr(item, "objective_anchor", "") or ""),
                        expected_output=str(getattr(item, "expected_output", "") or ""),
                        remaining=str(getattr(item, "description", "") or ""),
                    )
                    item.node_record = _rec
                if _rec is not None:
                    _rec.outcome = _verified
                    # REQ-18 (T19): stamp the two domain axes at the same
                    # finalize point as the outcome â€” topic re-resolved from
                    # the FULL step result text (richer signal than the seed
                    # description; registry-backed, general + logged on miss),
                    # execution from the active winding. AC4: these ride the
                    # node record AND the chain row.
                    _rec.topic_domain = self._der_topic_domain(
                        f"{item.description or ''} {step_result or ''}"
                    ) or "general"
                    _rec.execution_domain = (
                        self._der_execution_domain(from_voice) or "der"
                    )
                    # T36-FIX (content_summary): the L6014 construction comment
                    # promised "the finalize site re-stamps with the full step
                    # result text" â€” but content_summary was NEVER re-stamped, so
                    # _der_node_record_evidence fed the synthesis LLM only the
                    # step DESCRIPTION (plan sentence), not the actual tool output.
                    # Live T36 smoke: crawl stored 17 chunks + rendered the prism
                    # card, yet synthesis said "search tool did not return any
                    # actual results" (synthesis prompt was ~111 tokens). Re-stamp
                    # here with the real step result so the synthesis evidence is
                    # the actual crawl content, not the plan text. Bounded to 300
                    # chars to keep the record bounded (same as the seed).
                    _rec.content_summary = (step_result or "")[:300]
                    # REQ-4: continuous verified fraction, recomputed at the
                    # finalize point (the verifier's decisive fraction is not
                    # otherwise surfaced here). Fallback: the label's canonical
                    # continuous value so the record is never NaN/0.0 for a
                    # VERIFIED step.
                    try:
                        _vf = self._verified_fraction(
                            item.expected_output, str(step_result or "")
                        )
                    except Exception:
                        _vf = {"VERIFIED": 1.0, "UNVERIFIED": 0.5, "FAILED": 0.0}.get(
                            _verified, 0.0
                        )
                    _rec.verified_fraction = _vf
                    # â”€â”€ Goal contract T5 (specs/goal-contract-coverage,
                    # REQ-2/REQ-3) â”€â”€ mark coverage from the settled node's
                    # outcome + result (VERIFIED + term match, set union),
                    # stamp C onto the task node's verified_fraction, log
                    # C/g/covered/required. Advisory: never break finalize.
                    try:
                        _gc_state = getattr(self, "_goal_contract_state", None)
                        if _gc_state is not None:
                            from backend.agent import goal_contract as _gc_mod2

                            _gc_state["outcomes"].append(
                                _gc_coverage_label(_verified, item, step_result)
                            )
                            _gc_state["results"].append(str(step_result or ""))
                            _gc_cov = _gc_mod2.mark_coverage(
                                _gc_state["contract"],
                                list(_gc_state["outcomes"]),
                                list(_gc_state["results"]),
                            )
                            _gc_prev = float(_gc_state.get("C", 0.0))
                            _gc_state["prev_c"] = _gc_prev
                            _gc_state["C"] = float(_gc_cov.C)
                            _gc_state["g"] = float(_gc_cov.g)
                            _gc_state["covered"] = list(_gc_cov.covered)
                            try:
                                _gc_counters = _gc_state.get("counters") or {}
                                _gc_counters["facts_covered"] = len(_gc_cov.covered)
                                _gc_state["counters"] = _gc_counters
                            except Exception:
                                pass
                            # REQ-3 AC3.4: track consecutive settled nodes with
                            # unmoved C so the stall signal (rho/idling) can
                            # fire downstream. Never raises, never blocks.
                            try:
                                if abs(float(_gc_cov.C) - _gc_prev) < 1e-9:
                                    _gc_state["unmoved"] = int(
                                        _gc_state.get("unmoved", 0)
                                    ) + 1
                                else:
                                    _gc_state["unmoved"] = 0
                                # rho = dC/(g*ds): ds = measured tokens spent
                                # this cycle (4 chars ~= 1 token on the step
                                # result). Advisory â€” computed best-effort.
                                _gc_ds = max(
                                    1.0, len(str(step_result or "")) / 4.0
                                )
                                _gc_state["rho"] = _gc_mod2.progress_ratio(
                                    _gc_prev, float(_gc_cov.C),
                                    float(_gc_cov.g), _gc_ds,
                                )
                            except Exception:
                                _gc_state["unmoved"] = 0
                            _gc_task_rec = _gc_state.get("task_record")
                            if _gc_task_rec is not None:
                                _gc_task_rec.verified_fraction = float(_gc_cov.C)
                                _gc_task_rec.covered_facts = list(_gc_cov.covered)
                            # REQ-4 AC4.2: agent ceiling discovery â€” a VERIFIED
                            # step whose result carries deliverables BEYOND the
                            # required floor proposes them as ceiling facts
                            # (surplus extraction via the same deterministic
                            # extractor; floor-deduped, capped, never
                            # blocking). Bounded to 2 per step so one rich
                            # result cannot fill the ceiling alone. Advisory.
                            try:
                                # Session 326 (live bug): a step can be VERIFIED
                                # while its result is an ERROR envelope. Probe 3
                                # logged
                                #   agent ceiling +2 ({"success": true,
                                #   "stdout": "wc : The term 'wc' is not
                                #   recognized..."})
                                # â€” shell error text became "discovered facts".
                                # Only discover from a result that carries
                                # actual output.
                                if (
                                    str(_verified or "").upper() == "VERIFIED"
                                    and str(step_result or "").strip()
                                    and not self._gc_result_is_error(step_result)
                                ):
                                    _gc_req_norms = {
                                        _gc_mod2._norm(_f)
                                        for _f in _gc_state["contract"].required
                                    }
                                    _gc_surplus = [
                                        _f for _f in _gc_mod2.extract_required(
                                            str(step_result or "")
                                        )
                                        if _gc_mod2._norm(_f)
                                        not in _gc_req_norms
                                    ][:2]
                                    if _gc_surplus:
                                        _gc_new = _gc_mod2.add_ceiling(
                                            _gc_state["contract"], _gc_surplus
                                        )
                                        if _gc_new is not _gc_state["contract"]:
                                            _gc_state["contract"] = _gc_new
                                            _gc_state["task_record"].ceiling_facts = (
                                                list(_gc_new.ceiling)
                                            )
                                            _gc_state[
                                                "task_record"
                                            ].contract_version = int(
                                                _gc_new.version
                                            )
                                            _gc_c2 = _gc_state.get("counters") or {}
                                            _gc_c2["amendments_agent"] = int(
                                                _gc_c2.get("amendments_agent", 0)
                                            ) + 1
                                            _gc_state["counters"] = _gc_c2
                                            logger.info(
                                                "[goal-contract] agent ceiling "
                                                "+%d (%s)",
                                                len(_gc_surplus),
                                                str(_gc_surplus[0])[:120],
                                            )
                            except Exception:
                                pass
                            logger.info(
                                "[goal-contract] node settled: C=%.3f g=%.3f "
                                "covered=%d required=%d blocked=%s",
                                float(_gc_cov.C), float(_gc_cov.g),
                                len(_gc_cov.covered), int(_gc_cov.required_n),
                                [b for b in _gc_cov.blocked] or [],
                            )
                    except Exception as _gc_cov_exc:
                        logger.debug(
                            "[goal-contract] coverage mark skipped: %s",
                            _gc_cov_exc,
                        )
                    # â”€â”€ Goal contract T9 (REQ-5 AC5.1): a FAILED settle with
                    # a terminal typed reason blocks the facts it was working
                    # on. Advisory â€” non-terminal failures retry, never block.
                    try:
                        if str(_verified or "").upper() == "FAILED":
                            _gc_reason = str(
                                getattr(item, "error_type", "") or ""
                            )
                            if _gc_reason:
                                self._goal_contract_block_facts(
                                    item, _gc_reason, str(step_result or ""),
                                )
                    except Exception:
                        pass
                    _rec.mediator = _mediator
                    _rec.mediator_source = _mediator_source
                    _rec.edge_ids = _rec.edge_ids or []
                    # â”€â”€ REQ-5 AC2/AC4 (T17): record the COUPLING DECISION at
                    # commit. The branches surfaced to this step (all of them,
                    # capped â€” AC1) plus the one it chose are stamped on the
                    # node record, and the edge to the chosen branch is
                    # written/strengthened with the decision as provenance.
                    # Off the critical path; never raises.
                    try:
                        _cands = getattr(item, "_coupled_candidates", None) or []
                        if _cands:
                            _chosen = self._der_choose_coupling_branch(item, _cands)
                            self._der_record_coupling_decision(
                                item, _cands, chosen_node_id=_chosen, record=_rec
                            )
                    except Exception as _cc_exc:
                        logger.debug(
                            "[DER] coupling-decision record failed: %s", _cc_exc
                        )
                    # â”€â”€ REQ-19 (T20): persist the DER structural links into
                    # the SHARED link store at the same finalize point â€” the
                    # node's memory record AND its edges land together (DAG =
                    # memory = DAG). part_of (sub-loop containment, child ->
                    # parent), depends_on (plan dependency), relevant_to
                    # (branches actually surfaced to a decision â€” provenance,
                    # not affinity), failed_like (same failure class, so AVOID
                    # recall is a graph walk). Off the critical path; the
                    # writer itself never raises.
                    # D1: on lane("memory_events") - inline, pin_store.link
                    # waited on "database is locked" in the answer path.
                    try:
                        if self._der_links is not None:
                            from backend.utils.durability_queue import lane as _durability_lane

                            _durability_lane("memory_events").submit(
                                "der_node_links", self._der_links.write_node_links,
                                item,
                                _rec,
                                step_success=step_success,
                                step_result=str(step_result or ""),
                                execution_domain=_rec.execution_domain,
                                session_id=_session or "",
                            )
                    except Exception as _dl_exc:
                        logger.debug(
                            "[DER] structural link write failed: %s", _dl_exc
                        )
            except Exception as _rec_exc:
                logger.debug(
                    "[DER] node_record finalize stamp failed: %s", _rec_exc
                )
            # â”€â”€ REQ-4 AC4 (T16b): FOLD-BACK â€” a sub-loop child folds back as
            # a compressed observation that CHANGES the parent's state: the
            # parent's node_record gains the child's verified outcome (REQ-3
            # AC1: the parent's next decision reads node records that now
            # include what the children resolved). Bounded (DER_FOLD_BACK_MAX);
            # off the critical path; never raises.
            if getattr(item, "is_subloop", False):
                try:
                    _parent_step_id = getattr(
                        getattr(item, "node_record", None), "parent_step_id", ""
                    ) or ""
                    if _parent_step_id:
                        for _qi in getattr(queue, "items", None) or []:
                            if getattr(_qi, "step_id", "") == _parent_step_id:
                                _prec = getattr(_qi, "node_record", None)
                                if _prec is not None:
                                    _fbs = list(
                                        getattr(_prec, "folded_back", None) or []
                                    )
                                    _fbs.append(
                                        f"[{item.step_id}] {_verified}: "
                                        f"{item.description[:160]}"
                                    )
                                    _prec.folded_back = _fbs[-DER_FOLD_BACK_MAX:]
                                break
                except Exception as _fb_exc:  # noqa: BLE001
                    logger.debug("[DER] fold-back write failed: %s", _fb_exc)

        except Exception as _cad_exc:
            loud_error(_cad_exc, "der_node_record_finalize")
        try:
            _phys = self._der_submit_physics(
                item,
                node_record=getattr(item, "node_record", None)
                or getattr(item, "footprint", None),
                step_success=step_success,
                verified=_verified,
                session=_session,
                from_voice=from_voice,
                n_children=len(_children),
                mediator=_mediator,
                mediator_source=_mediator_source,
            )
        except Exception as _lane_exc:
            loud_error(_lane_exc, "der_physics_submit")
        # â”€â”€ specs/tool-result-envelope T6 (REQ-1 AC1.2): build the
        # envelope ONCE at the finalize site. Extracted into its own
        # method so an upstream caducean failure can never skip
        # envelope construction (AC1.4: the envelope ALWAYS exists â€”
        # full or minimal â€” never a silent legacy item).
        try:
            self._der_build_step_envelope(
                item=item,
                step_result=step_result,
                step_success=step_success,
                outcome=_verified,
                completed_items=completed_items,
                _session=_session,
                _turn_id=_turn_id,
                coords_from=None,
                coords_to=None,
            )
            if _phys is not None:
                with _phys.lock:
                    _der_fold_envelope(item, _phys)
        except Exception as _env_call_exc:
            logger.warning(
                "[envelope] finalize call failed for step %s: %s",
                getattr(item, "step_id", "?"), _env_call_exc,
            )

        # â”€â”€ WORKING MEMORY: accumulate findings for later steps â”€â”€
        # T7 (specs/tool-result-envelope REQ-2 AC2.1): append the envelope
        # LINE (status + summary + wrapper labels + raw_ref doc id) for EVERY
        # settled step INCLUDING failures â€” the old site appended a raw
        # _smart_excerpt for successes only, silently skipping failures,
        # which guaranteed the next step could not see the flat tire it just
        # hit. Raw payloads no longer enter working memory by construction;
        # _run_step_direct's 6000-cap stays as defense-in-depth. Pre-envelope
        # items (legacy edge) degrade to the old bounded excerpt.
        try:
            _env = getattr(item, "envelope", None)
            if self._memory_interface:
                if _env is not None:
                    _wm_note = (
                        f"[Step {item.step_number}: {item.description[:80]}] "
                        f"{_env.line()}"
                    )
                elif step_result:
                    _wm_note = (
                        f"[Step {item.step_number}: {item.description[:80]}]"
                        f" {self._smart_excerpt(step_result, _step_evidence_cap(item))}"
                    )
                else:
                    _wm_note = ""
                if _wm_note:
                    self._memory_interface.append_to_session(
                        _session, _wm_note, zone="working_history"
                    )
                # Session 245 (live memory footer): surface the memory WRITE
                # on the card's footer while execution happens â€” previously
                # memory:event only fired once at recall time (before the
                # card existed), so the footer sat on "Active Execution" for
                # whole runs. Same registry kind ("episodic"), outcome_type
                # distinguishes store from recall.
                try:
                    from backend.agent.event_bus import get_event_bus, IRISStreamEvent

                    get_event_bus().emit(
                        IRISStreamEvent.MEMORY_EVENT,
                        data={
                            "kind": "episodic",
                            "task_summary": f"[Step {item.step_number}] {item.description[:80]}",
                            "outcome_type": "store",
                            "duration_ms": 0,
                        },
                        session_id=_session,
                        conversation_id=self.conversation_id,
                    )
                except Exception:
                    pass  # never block the DER loop on an emit failure
        except Exception as _wm2_exc:
            loud_error(_wm2_exc, "append_working_history")

        completed_items.append(item)

        # Session-318 T16 (REQ-9 AC9.5/AC9.6): VLM in-site recovery trigger.
        # Dead fetch + unvisited same-site candidates + budget remaining â†’
        # a recovery QueueItem joins via add_item (the card-visible path).
        # Dependents order after it; independents ahead proceed first â€” the
        # lane never blocks the loop (no new locks, no waits). One recovery
        # per dead host per turn; chains forbidden in the helper.
        try:
            _rec_item = self._der_maybe_open_recovery(
                item, step_result, completed_items, queue,
            )
            if _rec_item is not None:
                queue.add_item(_rec_item)
                try:
                    from backend.agent.write_counters import bump as _bump_ropen
                    _bump_ropen("envelope.recovery_opens")
                except Exception:
                    pass
                try:
                    from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                    get_event_bus().emit(
                        IRISStreamEvent.TASK_PROGRESS,
                        data={
                            "add_step": True,
                            "step_id": _rec_item.step_id,
                            "step_number": _rec_item.step_number,
                            "description": _rec_item.description[:200],
                            "tool_name": "crawler_query",
                            **self._card_envelope(_turn_id),
                        },
                    )
                except Exception:
                    pass  # never block the DER loop on an emit failure
        except Exception as _rec_open_exc:
            logger.debug("[DER] recovery open failed: %s", _rec_open_exc)

        # â”€â”€ Phase 3: escalation + explorer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # After each step, check if mode escalation is warranted.
        # If queue is complete but more work is needed in AGENTIC/FULL
        # mode, re-plan with the LLM.
        try:
            _result_summary = (step_outputs[-1] if step_outputs else "")[:200]
            queue.check_escalation(
                review_verdict=verdict,
                tool_result_summary=_result_summary,
                token_budget_remaining=_token_budget - _tokens_used,
                turn_id=_turn_id,
            )

            # If queue is complete but mode is AGENTIC or FULL,
            # ask the LLM if more tools are needed.
            # Phase 5: rec-int termination â€” during COMPRESS (rec==1) the field
            # is condensing, so do NOT expand the plan with new explorer steps.
            # (next_ready already defers non-critical steps during COMPRESS; this
            # stops adding NEW ones, integrating the recommendation into loop
            # termination.)
            # Session 366: make the continuation gate VISIBLE. It was one compound
            # condition, so a skipped consult left no trace at all - the same
            # silent-skip class that hid seven consumers for a session. Logging the
            # values lets "depth_route/done did not score" be told apart from "the
            # consult never ran".
            _cont_complete = queue.is_complete()
            _cont_mode_ok = queue.mode in (
                ExecutionMode.AGENTIC, ExecutionMode.FULL,
            )
            _cont_run = _cont_mode_ok and _cont_complete
            _cover_push = None
            logger.info(
                "[DER] continuation gate: mode=%s complete=%s -> %s",
                getattr(queue.mode, "value", queue.mode),
                _cont_complete, "RUN" if _cont_run else "SKIP",
            )
            # `rec == 1` (caducean COMPRESS) forbids growing the plan, so under
            # COMPRESS the consult can change nothing: a "not done" answer was
            # discarded and a "done" answer ends a queue that is already
            # complete. Owner 2026-10-01: skip its Brain call (13 of 18 consults
            # in one coding run were discarded; they ran only to give the paused
            # Oracle `done`/`depth_route` rows - Session 366's reason). Fold-back:
            # rec decides whether the consult runs, so it is read first.
            if _cont_run:
                _der_physics_settle(self, _session)
                try:
                    from backend.gateway.iris_ffi import ffi_caducean_recommend

                    _rec_now = ffi_caducean_recommend(_session)
                except Exception:
                    _rec_now = 2
                if _rec_now == 1:
                    _cont_run = False
                    logger.info(
                        "[DER] continuation consult skipped during COMPRESS "
                        "(rec=1) - the plan cannot expand"
                    )
                    # COMPRESS condenses the work done; it cannot end a task
                    # whose required fact nobody worked on. Eval r09
                    # (2026-10-04, conv-733): one search of three facts, then
                    # rec=1 skipped the consult and the reply missed two. The
                    # push for an open fact is fixed text - no consult needed.
                    _cover_push = AgentKernel._goal_contract_cover_step(self)
                    if _cover_push is not None:
                        _cont_run = True
            # The objective is MET: every required fact of the goal contract is
            # covered and none is blocked. The consult can only add steps that
            # chase the agent's own action lines as "ceiling facts" - live
            # 2026-10-02 run A5: C=1.000 at 23:56:37, then a consult + 2 added
            # steps + a bonus pass over "Opened Wikipedia homepage"-style facts,
            # 46 s before the same answer. No contract / open facts -> unchanged.
            if _cont_run and AgentKernel._goal_contract_met(self):
                _cont_run = False
                logger.info(
                    "[DER] continuation consult skipped - the goal contract is met "
                    "(all required facts covered)"
                )
            if _cont_run:
                _next_tool = _cover_push or self._der_plan_next_step(
                    plan.original_task,
                    completed_items,
                    queue.mode,
                    _turn_id,
                    step_outputs=step_outputs,
                )
                if _next_tool:
                    # GOAL ONLY: the continuation step carries no tool/params.
                    # _der_run_step_execution resolves it via the single resolver
                    # (explorer.propose) â€” F6 / System Invariant. We never take a
                    # tool from the Explorer's continuation dict.
                    # Session 312 (live conv-99): QueueItem was referenced here
                    # without an import â€” the one at the DER-loop function is a
                    # LOCAL binding, invisible here. Explorer escalation died
                    # with NameError at 18:05:09, exactly when result-aware
                    # steering was needed.
                    from backend.agent.der_loop import QueueItem
                    _next_item = QueueItem(
                        step_id=f"explorer_{len(completed_items) + 1}",
                        step_number=len(completed_items) + 1,
                        description=_next_tool.get("description", ""),
                        tool=None,
                        params={},
                        parallel_safe=False,
                        objective_anchor=plan.original_task,
                    )
                    queue.add_item(_next_item)
                    logger.info(
                        "[DER] Explorer added step %d: %s",
                        _next_item.step_number,
                        _next_item.description,
                    )
                    # Surface the newly-planned step to the frontend so the
                    # inline plan card shows the agent's live search/action
                    # steps as they are discovered â€” not just the upfront
                    # planner plan.  Frontend appends it to the to-do list.
                    # No session_id -> broadcast to all (single-user IRIS).
                    try:
                        from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                        get_event_bus().emit(
                            IRISStreamEvent.TASK_PROGRESS,
                            data={
                                "add_step": True,
                                "step_id": _next_item.step_id,  # pin_517dfcbda150: unique id so split/sub-loop children each append
                                "step_number": _next_item.step_number,
                                "description": _next_item.description[:200],
                                "tool_name": _next_item.tool,
                                # REQ-3 AC6 (T2): card_id stays stable across
                                # every event of a card's lifetime.
                                **self._card_envelope(_turn_id),
                            },
                        )
                        # T4a (REQ-4 AC5): persist the step addition so a
                        # card interrupted mid-run restores with the
                        # explorer-discovered step included.
                        _add_step_envelope = self._card_envelope(_turn_id)
                        self._persist_card_snapshot(
                            card_id=_add_step_envelope.get("card_id"),
                            conversation_id=self.conversation_id,
                            card_relation="continues",
                            # save_card upserts the WHOLE row â€” plan_title/mode
                            # must be re-sent every write or a step-transition
                            # snapshot would null out what task:start set.
                            plan_title=self._effective_plan_title(plan),
                            mode=queue.mode.value if getattr(queue, "mode", None) else None,
                            steps=self._queue_steps_snapshot(queue),
                            total_steps=len(queue.items),
                            terminal_state="running",
                        )
                    except Exception:
                        pass  # never block the DER loop on an emit failure

            # The FULL-mode progress check (_der_check_full_progress) was
            # REMOVED 2026-10-01 (owner): one Brain call after every step from
            # step 3 on, and the caller ignored its answer (16 calls in one
            # coding run, 1 "drift", logged only).
        except Exception as _explorer_exc:
            logger.warning(
                "[DER] Explorer escalation failed: %s", _explorer_exc
            )
        # Session-318 T19 (AC5.6 defect fix): grade at completion on EVERY
        # terminal path â€” the continuation-done branch alone never runs on
        # queue-exhaustion ends (conv-102: zero grade lines). Deduped by turn.
        # Non-vacuous only: an EMPTY queue is trivially "complete" and must
        # never stamp a premature PASS mid-run (caught by BT-4).
        try:
            if queue.is_complete() and len(getattr(queue, "items", []) or []) > 0:
                self._der_report_run_grade(
                    completed_items, _turn_id, "finalize-complete"
                )
        except Exception:
            pass

        # â”€â”€ EventBus: emit der:step â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            get_event_bus().emit(
                IRISStreamEvent.DER_STEP,
                data={
                    "task_id": _turn_id or item.step_id,
                    "step_number": item.step_number,
                    "step_description": item.description[:200],
                    "tool": item.tool,
                    "success": step_success,
                    "total_steps": len(queue.items),
                    "completed": len(completed_items),
                    "mode": queue.mode.value,
                },
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
            )
        except Exception:
            pass

        # Surface step completion to the frontend plan card so the to-do
        # list checks the step off as it finishes.  Reuses the bridged
        # TASK_PROGRESS channel (no new event type needed).
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            get_event_bus().emit(
                IRISStreamEvent.TASK_PROGRESS,
                data={
                    "step_done": True,
                    # pin_517dfcbda150: carry the unique step id so the frontend
                    # can check off BOTH plan steps (ids like r1/step_1) and
                    # DER-discovered steps (der-N / explorer_N) â€” previously it
                    # only matched der-N, so plan steps never visually completed.
                    "step_id": item.step_id,
                    "step_number": item.step_number,
                    "description": item.description[:200],
                    "success": step_success,
                    # REQ-3 AC6 (T2): card_id stays stable across every
                    # event of a card's lifetime.
                    **self._card_envelope(_turn_id),
                },
            )
            # T4a (REQ-4 AC5): persist the step transition so a card
            # interrupted mid-run restores with current step statuses â€”
            # the whole point of AC5, since a crash never reaches task:done.
            _step_done_envelope = self._card_envelope(_turn_id)
            self._persist_card_snapshot(
                card_id=_step_done_envelope.get("card_id"),
                conversation_id=self.conversation_id,
                card_relation="continues",
                plan_title=self._effective_plan_title(plan),
                mode=queue.mode.value if getattr(queue, "mode", None) else None,
                steps=self._queue_steps_snapshot(queue),
                total_steps=len(queue.items),
                terminal_state="running",
            )
        except Exception:
            pass

        # â”€â”€ TRAILING DIRECTOR gap-fill REMOVED (2026-08-06) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # The gap-fill ran SEQUENTIALLY after the user's task: it was invoked
        # synchronously in _der_finalize_step and its gap items were queued
        # into the SAME turn, re-executing completed steps' work after the plan
        # finished (live turn 95cbe698-342: 5 planned steps then gap-s2-*
        # extended the turn; turn fc2a1a48-ddf looped unbounded on gap-on-gap).
        # It never ran in parallel with the task, so it only added latency and
        # unsolicited steps. Decision: remove the gap-fill entirely.
        # SESSION 364: the module itself is now DELETED
        # (backend/agent/trailing_director.py, with its dedicated tests) - it had
        # been unreachable since this decision and the attribute is gone from
        # __init__. Its two jobs are covered elsewhere or were already retired:
        # gap analysis lives in _goal_contract_open_facts() (the goal contract's
        # required-but-uncovered facts, which drives the run grade and the
        # finalize/partial-answer text), and the REQ-5 AC1 shallow-verified check
        # was dropped with it because it only fed gap analysis.

        # NOTE: the verify_failed -> split-into-sub-loops step (Phase 2 D2.1)
        # used to live here. It computed `_children`, which the REQ-8
        # task:learning emit and the REQ-7 physics-narration hook above both
        # read â€” but those reads ran *before* this block, every time, so
        # `_children` was always unbound at read time (UnboundLocalError,
        # silently swallowed). Moved up to right after `_verified` is known,
        # before its first reader. See the bugfix note there.

        return _tokens_used


    # â”€â”€ Phase 3: explorer methods â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _gc_result_is_error(self, result: object) -> bool:
        """True when a settled step's result is an ERROR envelope, not output.

        Session 326 (live bug): ceiling discovery extracted "facts" from shell
        error text because a step can be VERIFIED while its result is a failed
        command. Accepts a dict envelope (``success: False`` / an ``error`` key /
        non-zero ``returncode``) or a JSON string of one. Never raises; an
        unparseable string is treated as real output (discovery is advisory, so
        a false negative is harmless while a false positive pollutes the
        ceiling with error text).
        """
        try:
            _r = result
            if isinstance(_r, str):
                _s = _r.strip()
                if _s[:1] in ("{", "["):
                    try:
                        import json as _json_err

                        _r = _json_err.loads(_s)
                    except Exception:
                        return False
                else:
                    return False
            if isinstance(_r, dict):
                if _r.get("success") is False:
                    return True
                if str(_r.get("error") or "").strip():
                    return True
                _rc = _r.get("returncode")
                if isinstance(_rc, int) and _rc != 0:
                    return True
                # A stdout that is only a shell "not recognized"/usage error is
                # still an error even when the wrapper reported success.
                _out = str(_r.get("stdout") or "").lower()
                if _out and any(
                    _m in _out
                    for _m in (
                        "is not recognized",
                        "command not found",
                        "no such file or directory",
                        "cannot find path",
                    )
                ):
                    return True
            return False
        except Exception:
            return False

    def _goal_contract_bound_cover_push(self, open_facts: List[str]) -> List[str]:
        """Bound the "cover the open required fact" push per fact.

        Each call counts one push for the first open fact. A fact pushed
        GOAL_COVER_PUSH_MAX times without being covered is BLOCKED (reason
        no_progress) and the next open fact is tried. Returns the facts still
        worth a push. Measured 2026-10-01 (eval c06): the push had no bound -
        36 pushes on a fact no step could cover, reply 366 s vs 64 s. (The
        streak gate's coverage-stall brake runs only when the user steers.)
        """
        try:
            from backend.agent.der_constants import GOAL_COVER_PUSH_MAX

            _st = getattr(self, "_goal_contract_state", None)
            if _st is None:
                return open_facts
            _pushes = _st.setdefault("cover_pushes", {})
            _left = list(open_facts)
            while _left:
                _k = str(_left[0]).strip().lower()
                if int(_pushes.get(_k, 0)) < GOAL_COVER_PUSH_MAX:
                    _pushes[_k] = int(_pushes.get(_k, 0)) + 1
                    return _left
                _blocked = _st.get("blocked") or []
                _blocked.append({
                    "fact": str(_left[0]),
                    "reason": "no_progress",
                    "evidence": f"{GOAL_COVER_PUSH_MAX} pushes, still not covered",
                })
                _st["blocked"] = _blocked
                _counters = _st.get("counters") or {}
                _counters["facts_blocked"] = len(_blocked)
                _st["counters"] = _counters
                logger.info(
                    "[goal-contract] fact BLOCKED (no_progress after %d pushes) "
                    "conv=%s: %r",
                    GOAL_COVER_PUSH_MAX, getattr(self, "conversation_id", ""),
                    str(_left[0])[:160],
                )
                _left = _left[1:]
            return []
        except Exception as _bp_exc:  # noqa: BLE001 - a bound never breaks the loop
            logger.warning("[goal-contract] cover-push bound failed: %r", _bp_exc)
            return open_facts

    def _goal_contract_cover_step(self) -> Optional[Dict]:
        """The goal of the step that covers the first open required fact, or
        None when no fact is open (or every open fact used its pushes).
        Called as a class function: a stand-in kernel without a contract
        dict gets None."""
        try:
            if not isinstance(getattr(self, "_goal_contract_state", None), dict):
                return None
            _open = AgentKernel._goal_contract_open_facts(self)
            if _open:
                _open = AgentKernel._goal_contract_bound_cover_push(self, _open)
            if not _open:
                return None
            logger.info(
                "[goal-contract] gap open (%d facts) â€” requesting "
                "work instead of finalizing: %r",
                len(_open), str(_open[0])[:160],
            )
            from backend.agent import goal_contract as _gc_cover

            return {"description": _gc_cover.cover_goal(
                _open[0], self._goal_contract_state.get("results") or ()
            )}
        except Exception as _cs_exc:  # noqa: BLE001 - doubt means no push
            logger.warning("[goal-contract] cover step failed: %r", _cs_exc)
            return None

    def _goal_contract_met(self) -> bool:
        """True when a goal contract exists, it has required facts, all are
        covered and none is blocked. Advisory; False on any doubt."""
        try:
            _st = getattr(self, "_goal_contract_state", None)
            _contract = _st.get("contract") if isinstance(_st, dict) else None
            if _contract is None or not list(_contract.required or []):
                return False
            if _st.get("blocked"):
                return False
            return not self._goal_contract_open_facts()
        except Exception:  # noqa: BLE001 â€” doubt means "not met": the consult runs
            return False

    def _goal_contract_open_facts(self) -> List[str]:
        """Goal contract T6 (REQ-3 AC3.2/AC3.6): required facts neither covered
        nor blocked. Advisory helper â€” empty when no contract exists."""
        try:
            _st = getattr(self, "_goal_contract_state", None)
            if _st is None:
                return []
            _contract = _st.get("contract")
            if _contract is None:
                return []
            _covered = {str(_c).strip().lower() for _c in _st.get("covered", [])}
            _blocked = set()
            try:
                from backend.agent import goal_contract as _gc_mod3

                for _bf in _st.get("blocked", []):
                    if isinstance(_bf, dict):
                        _blocked.add(str(_bf.get("fact", "")).strip().lower())
                    else:
                        _blocked.add(str(_bf).strip().lower())
                _open = [
                    str(_f) for _f in _contract.required
                    if str(_f).strip().lower() not in _covered
                    and str(_f).strip().lower() not in _blocked
                ]
                return _open
            except Exception:
                return [
                    str(_f) for _f in _contract.required
                    if str(_f).strip().lower() not in _covered
                ]
        except Exception:
            return []

    # â”€â”€ Goal contract Wave 3 (T7/T8/T9/T10) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Advisory helpers: every path degrades to legacy behavior when no
    # contract exists. Never raise, never block the turn.

    def _goal_contract_block_facts(
        self,
        failed_item: object = None,
        reason: str = "",
        evidence: str = "",
    ) -> List[str]:
        """Mark uncovered facts a failed step was working on as blocked (T9).

        REQ-5 AC5.1: only fires on a terminal typed Reason (via
        goal_contract.is_blocked); non-terminal failures are retried, not
        blocked. Blocked facts stay in the denominator (AC5.2, CT-GC7).
        Returns the newly blocked fact texts.
        """
        try:
            _st = getattr(self, "_goal_contract_state", None)
            if _st is None:
                return []
            from backend.agent import goal_contract as _gc_mod4

            _reason = str(reason or getattr(failed_item, "error_type", "") or "")
            if not _gc_mod4.is_blocked(_reason):
                return []
            _open = self._goal_contract_open_facts()
            if not _open:
                return []
            _step_text = " ".join([
                str(getattr(failed_item, "description", "") or ""),
                str(getattr(failed_item, "expected_output", "") or ""),
                str(evidence or ""),
            ])
            _hits = list(_gc_mod4.step_fact_hits(_open, _step_text))
            if not _hits:
                # The failed step maps to no open fact â€” name the gap against
                # the first open fact so the block is never silent.
                _hits = [str(_open[0])]
            _blocked = _st.get("blocked") or []
            _have = set()
            for _b in _blocked:
                if isinstance(_b, dict):
                    _have.add(str(_b.get("fact", "")).strip().lower())
                else:
                    _have.add(str(_b).strip().lower())
            _new: List[str] = []
            import time as _time_mod

            for _h in _hits:
                if str(_h).strip().lower() in _have:
                    continue
                _blocked.append({
                    "fact": str(_h),
                    "reason": _reason,
                    "evidence": str(evidence or "")[:200],
                })
                _new.append(str(_h))
                _have.add(str(_h).strip().lower())
            _st["blocked"] = _blocked
            try:
                _counters = _st.get("counters") or {}
                _counters["facts_blocked"] = len(_blocked)
                _st["counters"] = _counters
            except Exception:
                pass
            _task_rec = _st.get("task_record")
            if _task_rec is not None:
                try:
                    _task_rec.blocked_facts = list(_blocked)
                except Exception:
                    pass
            for _h in _new:
                logger.info(
                    "[goal-contract] fact blocked (%s): %r",
                    _reason, _h[:160],
                )
            return _new
        except Exception as _blk_exc:
            logger.debug("[goal-contract] block skipped: %s", _blk_exc)
            return []

    def _goal_contract_blocked_texts(self) -> List[str]:
        """Blocked fact texts for grade + naming (T9/T10)."""
        try:
            _st = getattr(self, "_goal_contract_state", None)
            if _st is None:
                return []
            _out: List[str] = []
            for _b in _st.get("blocked", []) or []:
                if isinstance(_b, dict):
                    _out.append(str(_b.get("fact", "")))
                else:
                    _out.append(str(_b))
            return [str(_f) for _f in _out if str(_f).strip()]
        except Exception:
            return []

    def _goal_contract_name_blocked(self, answer: str) -> str:
        """T9 AC5.3/AC5.4: the final answer names every blocked fact.

        When blocked facts exist and the answer does not already name all
        of them, the deterministic blocked-fact summary is the floor â€” the
        naming block is appended so every blocked fact is explicit. Returns
        the answer unchanged when nothing is blocked or all are named.
        Advisory: never raises.
        """
        try:
            _blocked = self._goal_contract_blocked_texts()
            if not _blocked or not (answer or "").strip():
                return answer
            from backend.agent import goal_contract as _gc_mod6

            _unnamed = [
                _f for _f in _blocked
                if not _gc_mod6.step_fact_hits((_f,), answer or "")
            ]
            if not _unnamed:
                return answer
            _lines = "\n".join(f"- {_f}" for _f in _blocked)
            _suffix = (
                "\n\nParts of your request I could not cover "
                "(blocked â€” not skipped):\n" + _lines
            )
            logger.info(
                "[goal-contract] named %d blocked fact(s) in final answer "
                "(%d were unnamed)", len(_blocked), len(_unnamed),
            )
            return str(answer or "") + _suffix
        except Exception:
            return answer

    def _goal_contract_apply_steering(self, text: str) -> bool:
        """Route user steering through amend (T7, REQ-4 AC4.1/AC4.6/AC4.7).

        Amends the task node's required set in place â€” add, remove, or
        repromote â€” without creating a second task. Writes the forward
        amendment node (derives_from, T8) and logs who/when/why (AC7.3).
        Returns True when the contract changed.
        """
        try:
            _st = getattr(self, "_goal_contract_state", None)
            if _st is None or not (text or "").strip():
                return False
            from backend.agent import goal_contract as _gc_mod5

            _parsed = _gc_mod5.parse_steering_amendment(
                text,
                list(_st["contract"].required),
                self._goal_contract_blocked_texts(),
            )
            if not any(_parsed.values()):
                return False
            import time as _time_mod2

            _old = _st["contract"]
            _new = _old
            # Repromote: drop the blocked entry so the fact is open again.
            _repromoted: List[str] = []
            for _rp in _parsed.get("repromote", ()):
                _keys = {_b["fact"].strip().lower() for _b in _st.get("blocked", [])
                         if isinstance(_b, dict)}
                _kept = [
                    _b for _b in _st.get("blocked", [])
                    if not (isinstance(_b, dict)
                            and _b.get("fact", "").strip().lower()
                            == str(_rp).strip().lower())
                ]
                if len(_kept) != len(_st.get("blocked", [])):
                    _st["blocked"] = _kept
                    _repromoted.append(str(_rp))
            if _parsed.get("add") or _parsed.get("remove"):
                _new = _gc_mod5.amend(
                    _old, add=_parsed.get("add", ()),
                    remove=_parsed.get("remove", ()),
                    source="user", reason=str(text)[:200],
                )
            if _new is _old and not _repromoted:
                return False
            _from_v = int(_old.version)
            _st["contract"] = _new
            _st["task_record"].required_facts = list(_new.required)
            _st["task_record"].contract_version = int(_new.version)
            # Forward amendment node (T8): who/when/why + version pair.
            _entry = {
                "who": "user",
                "when": _time_mod2.time(),
                "why": str(text)[:200],
                "add": list(_parsed.get("add", ())),
                "remove": list(_parsed.get("remove", ())),
                "repromote": list(_repromoted),
                "version_from": _from_v,
                "version_to": int(_new.version),
            }
            _st.setdefault("amendments", []).append(_entry)
            try:
                _counters2 = _st.get("counters") or {}
                _counters2["amendments_user"] = int(
                    _counters2.get("amendments_user", 0)) + 1
                _st["counters"] = _counters2
            except Exception:
                pass
            try:
                _writer = getattr(self, "_der_links", None)
                if _writer is not None:
                    _writer.link_derives_from(
                        f"contract-v{int(_new.version)}",
                        f"contract-v{_from_v}",
                    )
            except Exception:
                pass
            logger.info(
                "[goal-contract] amendment by user: +%d -%d repromote=%d "
                "v%d->v%d (%s)",
                len(_parsed.get("add", ())), len(_parsed.get("remove", ())),
                len(_repromoted), _from_v, int(_new.version),
                str(text)[:120],
            )
            return True
        except Exception as _am_exc:
            logger.debug("[goal-contract] steering amend skipped: %s", _am_exc)
            return False

    def _goal_contract_bonus_pass(self) -> Optional[Dict[str, str]]:
        """REQ-3 AC3.5: one bounded bonus pass over ceiling facts at C=1.0.

        Returns a goal-only continuation dict when the turn reached full
        floor coverage with uncovered ceiling facts and no bonus pass has
        run yet this turn; None otherwise. Advisory, never raises. The
        counter (REQ-7 AC7.2) is incremented here so every increment has
        exactly one writer.
        """
        try:
            _st = getattr(self, "_goal_contract_state", None)
            if _st is None:
                return None
            _counters = _st.get("counters") or {}
            if abs(float(_st.get("C", 0.0)) - 1.0) >= 1e-9:
                return None
            if int(_counters.get("bonus_passes", 0)) != 0:
                return None
            _covered_now = {
                str(_c).strip().lower() for _c in _st.get("covered", [])
            }
            _open = [
                str(_f) for _f in (_st["contract"].ceiling or ())
                if str(_f).strip().lower() not in _covered_now
            ]
            if not _open:
                return None
            _counters["bonus_passes"] = 1
            _st["counters"] = _counters
            logger.info(
                "[goal-contract] bonus pass over %d ceiling fact(s): %r",
                len(_open), str(_open[0])[:160],
            )
            return {"description": (
                "Bonus pass over an extra discovery: "
                f"{str(_open[0])[:300]}"
            )}
        except Exception:
            return None

    def _der_plan_next_step(
        self,
        task_objective: str,
        completed_items: List,
        mode: "ExecutionMode",
        turn_id: Optional[str] = None,
        step_outputs: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """
        After all planned steps are done, ask the LLM if more work is
        needed to satisfy the original objective.

        Returns a dict with 'description' (a GOAL) if more work is needed,
        or None if done. It MUST NOT return a 'tool'/'params' â€” tool
        selection is the single resolver's job (explorer.propose), fired
        when the continuation step executes (F6 / System Invariant). This
        is the key method for AGENTIC mode â€” it enables the multi-step tool
        loop without a hardcoded limit, while keeping one tool authority.
        """
        try:
            if not completed_items:
                return None

            from backend.agent.der_constants import ExecutionMode

            # Build a summary of what was done â€” T8 (specs/tool-result-envelope
            # REQ-2 AC2.2 / REQ-4 AC4.2): BOTH halves render envelope views
            # only. The old done_summary half appended the FULL raw i.result
            # for the last 10 steps (the conv-99 leak); it is now capped to
            # the envelope line exactly like the outputs block. Legacy edge
            # (no envelope): bounded excerpt, never raw.
            done_summary = "\n".join(
                f"  Step {i.step_number}: {i.description}"
                + (
                    f"\n    {i.envelope.line()}"
                    if getattr(i, "envelope", None) is not None
                    else (
                        # Legacy edge (pre-envelope item): bounded excerpt via
                        # the class static â€” fake/test kernels may not carry
                        # the instance method.
                        f"\n    OUTPUT: {AgentKernel._smart_excerpt(i.result, 400)}"
                        if i.result
                        else ""
                    )
                )
                for i in completed_items[-10:]
            )

            # Phase 3 (Gap 4): surface what each completed step actually
            # returned â€” now as ENVELOPE lines (status + wrapper + summary +
            # doc pointer), not bounded raw excerpts. Bounded by construction.
            _env_lines = [
                f"  [{i.step_number}] {i.envelope.line()}"
                for i in completed_items[-10:]
                if getattr(i, "envelope", None) is not None
            ]
            outputs_block = (
                "\n".join(_env_lines)
                if _env_lines
                else (
                    "\n".join(
                        f"  [{idx + 1}] {out[:600]}"
                        for idx, out in enumerate(step_outputs)
                    )
                    if step_outputs
                    else "  (none captured)"
                )
            )

            # REQ-8 AC8.2: visited ledger â€” pointers only, omit when empty.
            try:
                _visited_next = self._der_visited_block()
            except Exception:
                _visited_next = ""
            _visited_tail = f"{_visited_next}\n\n" if _visited_next else ""
            # Goal contract T6 (REQ-3 AC3.2/AC3.6): the deterministic gap
            # check rides with the replan hook. Open (uncovered, unblocked)
            # required facts go into the prompt so the planner sees them, and
            # an LLM "done" with open facts still requests work instead of
            # finalizing. Advisory â€” absent contract = legacy behavior.
            _gc_open: List[str] = []
            try:
                _gc_open = self._goal_contract_open_facts()
            except Exception:
                _gc_open = []
            _gc_open_block = ""
            if _gc_open:
                _gc_open_block = (
                    "OPEN REQUIRED FACTS (uncovered, unblocked â€” the turn "
                    "must not end while any remains and work is admissible):\n"
                    + "\n".join(f"  - {_f[:200]}" for _f in _gc_open[:8])
                    + "\n\n"
                )
            prompt = (
                "You are the Explorer. Your job is to decide if more work is needed.\n\n"
                f"OBJECTIVE: {task_objective}\n\n"
                f"{_gc_open_block}"
                f"STEPS COMPLETED ({len(completed_items)} total):\n{done_summary}\n\n"
                f"ACTUAL STEP OUTPUTS (what each completed step returned):\n"
                f"{outputs_block}\n\n"
                f"{_visited_tail}"
                f"Current mode: {mode.value if isinstance(mode, (str, ExecutionMode)) else 'agentic'}\n\n"
                "Is the objective fully met? If yes, respond with {\"done\": true}.\n"
                "If no, describe the SINGLE next goal to make progress (do NOT name a\n"
                'tool). Respond with:\n'
                '{"done": false, "description": "what goal to pursue next"}\n'
                "Be specific about the outcome the next step should achieve.\n\n"
                "Respond with JSON only."
            )

            response = self.infer(
                prompt, role="reasoning", max_tokens=400, temperature=0.1
            )
            raw = response.raw_text or ""

            # Parse JSON from response
            import json as _json

            m = re.search(r"\{[\s\S]+\}", raw)
            if not m:
                # FALLBACK EXTRACTION (2026-09-27). This used to end the turn
                # here, silently, and that one line had two faults:
                #  1. `return None` is the SAME value the caller gets for "no
                #     next step wanted", so a prose reply silently ENDED the task
                #     with no way to tell the two apart.
                #  2. It skips the `done` shadow consult below entirely â€” no row,
                #     no log line, a consumer that looks unwired.
                # Recover the done-bit from the common non-JSON shapes first. A
                # recovered bit keeps the row PAIRABLE (an unpaired row carries
                # brain_bool=None and is not scorable), which is worth more than
                # merely recording a row.
                _bit_m = re.search(
                    r'"done"\s*:\s*(true|false)', raw, re.IGNORECASE
                ) or re.search(
                    r"^\s*(true|false|yes|no)\s*$", raw,
                    re.IGNORECASE | re.MULTILINE,
                )
                if not _bit_m:
                    logger.warning(
                        "[DER] _der_plan_next_step: planner reply had no JSON and "
                        "no recoverable done-bit â€” returning None (which is "
                        "indistinguishable from 'no next step') and SKIPPING the "
                        "`done` shadow consult. raw[:120]=%r",
                        raw[:120],
                    )
                    return None
                data = {"done": _bit_m.group(1).lower() in ("true", "yes")}
            else:
                data = _json.loads(m.group())
            # REQ-14 AC14.1 (T18): shadow-score the `done` consumer and emit
            # the row. The Brain's bit still decides â€” the goal-contract
            # override below is PRESERVED (AC14.1) â€” and the engine only ever
            # supplies the bool, never the next-goal text (AC14.2).
            try:
                from backend.agent import monitor_shadow as _ms
                from backend.agent.decision_engine import decides, oracle_acts

                _done_dec = decides("done") is not None
                # 3-TUPLE, not 2 (2026-09-27). monitor_bool returns
                # (value, text, shadow_row). Unpacking two names raised
                #   ValueError: too many values to unpack (expected 2, got 3)
                # BEFORE emit_row below, so the `done` row was never written -
                # silently, because this block used to end in a bare `pass`.
                # That one character is why the consumer read "0 rows" all
                # session and looked unwired. Caught the moment the bare `pass`
                # became a logged warning.
                _done_value, _done_text, _done_row = _ms.monitor_bool(
                    "done", _monitor_statement(task_objective, completed_items),
                    # v3 (2026-11-06): the instruction moved from "Is the
                    # objective complete?" to one that names what complete means
                    # ("every required fact covered... nothing required is still
                    # missing"). MEASURED on the 63 distinct parity rows: the same
                    # 61.9% agreement with the Brain's done-bit at AUROC 0.7019
                    # against 0.6549 - a strict improvement, no trade-off. A
                    # question change is a new calibrated identity, so the stamp
                    # moves and the v2 cohort is never blended in.
                    # v4 (2026-11-10): the declared question reaches the
                    # model for the first time (monitor registrar fix); the
                    # v3 rows were asked the generic AUTO_INSTRUCTION.
                    criteria_version="done/v4",
                    brain_bool_fn=lambda: data.get("done") is True,
                    brain_text_fn=lambda: str(data.get("description", "") or ""),
                    engine=_ms.AUTO_ENGINE,
                    # shadow score off the reply path (4.3 s at turn end,
                    # eval c04 2026-10-01); the row is emitted from the lane.
                    # Stage B: deferral applies only while `done` does not
                    # decide (monitor_bool ignores defer once enforced) - a
                    # deciding consumer must be waited for.
                    defer=True,
                    enforced=_done_dec,
                    acts=lambda c: oracle_acts("done", c),
                )
                _ms.emit_row(_done_row)
                if _done_dec:
                    # The value is the final decision (the Oracle's when it was
                    # confident, else the Brain's own bit): make it the one the
                    # loop reads below. The Brain's next-goal text stays.
                    data["done"] = bool(_done_value)
            except Exception as _mon_err:  # noqa: BLE001 â€” advisory observer
                # VISIBLE, but still ADVISORY (2026-09-27). This was a bare
                # `pass`, so a failing monitor consult lost its calibration row
                # in total silence â€” the exact class of silence that made seven
                # consumers look unwired for a whole session. A skipped consumer
                # must leave a trace. Warning, not debug: losing a row is a real
                # calibration event, and the observed failure mode was NO row
                # with NO log line at all.
                logger.warning(
                    "[monitor] done shadow consult failed (row NOT recorded): %r",
                    _mon_err,
                )
            if data.get("done") is True:
                # Goal contract T6 (REQ-3 AC3.6): the turn SHALL NOT end while
                # a required fact is open and unblocked â€” request work on the
                # first open fact instead of honoring the LLM's done.
                _gc_push = AgentKernel._goal_contract_cover_step(self)
                if _gc_push is not None:
                    return _gc_push
                # REQ-3 AC3.5: C reached 1.0 â€” permit ONE bounded bonus pass
                # over ceiling facts, then terminate (helper owns the
                # counter so every increment has exactly one writer).
                try:
                    _gc_bonus = self._goal_contract_bonus_pass()
                except Exception:
                    _gc_bonus = None
                if _gc_bonus is not None:
                    return _gc_bonus
                # AC5.6: done+GRADE via the shared helper (deduped by turn â€”
                # the finalize-complete site may have reported first, T19).
                try:
                    self._der_report_run_grade(
                        completed_items, turn_id, "continuation-done"
                    )
                except Exception:
                    pass
                return None

            _desc = data.get("description")
            if not _desc or not str(_desc).strip():
                # Not done, but the Brain named no next step, so the loop STOPS.
                return None

            # GOAL ONLY â€” no tool/params. The resolver picks the tool on exec.
            return {"description": str(_desc).strip()}

        except Exception as exc:
            logger.warning(
                "[DER] _der_plan_next_step failed: %s", exc
            )
            return None

    def _generate_response(
        self,
        user_message: str,
        plan: Dict[str, Any],
        execution_results: List[Any],
        context: List[Dict[str, Any]],
    ) -> str:
        """
        Generate final response based on plan and execution results.

        Args:
            user_message: Original user message
            plan: Generated plan
            execution_results: Results from execute_plan()
            context: Conversation context

        Returns:
            Final response text
        """
        # Check if any steps failed
        has_errors = any(
            isinstance(r, dict) and ("error" in r or not r.get("success", True))
            for r in execution_results
        )

        # Build response based on results
        if has_errors:
            error_messages = [
                r.get("error", "Unknown error")
                for r in execution_results
                if isinstance(r, dict) and "error" in r
            ]
            return f"I encountered some issues: {'; '.join(error_messages)}"

        # Extract successful results
        success_results = [
            r
            for r in execution_results
            if isinstance(r, dict) and r.get("success", False)
        ]

        if not success_results:
            return "I've processed your request."

        # Format response based on results
        if len(success_results) == 1:
            result = success_results[0]
            if "response" in result:
                return result["response"]
            elif "result" in result:
                return result["result"]

        # Multiple results - summarize
        summary_parts = []
        for r in success_results:
            if "result" in r:
                summary_parts.append(
                    f"- {r.get('action', 'Action')}: {r['result'][:100]}"
                )
            elif "response" in r:
                summary_parts.append(f"- {r['response'][:100]}")

        if summary_parts:
            return "I've completed your request:\n\n" + "\n".join(summary_parts)

        return "I've processed your request."

    def _synthesize_response(
        self, task: TaskContext, execution_results: List[Any]
    ) -> str:
        """
        Synthesize response using the brain model with tool results.

        This addresses Bug 2: The brain now sees the actual tool output
        before generating the final response.

        Args:
            task: TaskContext containing user message and plan
            execution_results: Results from execute_plan()

        Returns:
            Synthesized response from the brain model
        """
        # Short-circuit: if the plan already contains a raw free-form response
        # (model didn't output JSON), return it directly without a second model call.
        if task.plan and task.plan.get("_raw_response"):
            logger.info("[AgentKernel] Using raw plan response (no synthesis needed)")
            return task.plan["_raw_response"]

        # Get results summary for the brain
        results_summary = task.get_results_summary()

        # Build synthesis prompt for the brain
        synthesis_prompt = f"""User request: {task.user_message}

Tool execution results:
{results_summary}

Based on the tool results above, provide a natural response to the user's request.
If any tools failed, address those issues in your response.
Cover every part of the user's request. If the results lack some asked part, say which part is missing in one line â€” never skip it in silence.
If a CROSS-CHECK section is present, say which facts are confirmed since the earlier date and which changed.
PRIOR RESEARCH lines are results of earlier searches: a fact found only there is NOT missing - give it with its date.

{_READABLE_FORMAT_RULES}
"""

        try:
            # Get reasoning model for synthesis â€” only use local model if it's
            # actually loaded.  Do NOT call get_reasoning_model() as a fallback here:
            # that can return a broken/unloaded stub which echoes garbage like
            # "respond_to_user" back to the user verbatim.
            reasoning_model = None
            if self._model_router and self._selected_reasoning_model:
                reasoning_model = self._model_router.models.get(
                    self._selected_reasoning_model
                )

            if reasoning_model:
                # Call the loaded local/LFM model for synthesis. In-process
                # local models never report a usage block (no HTTP response to
                # parse), so this is an ESTIMATE-only accrual (D1 item 4/5) â€”
                # there is no real number available to prefer here.
                _raw_reply = reasoning_model.generate(synthesis_prompt)
                response = self._strip_thinking(_raw_reply)
                self._accrue_tokens(
                    _raw_reply, None, source="_synthesize_response:local"
                )
                logger.info(
                    "[AgentKernel] Brain synthesized response with tool results context"
                )
                return response

            # Primary path: route synthesis through the unified InferenceRouter so
            # API providers (Cerebras, OpenAI, â€¦) are used for the brain answer,
            # not just local/Ollama models. Legacy LM Studio / Ollama branches
            # below remain as fallbacks for local-model configurations.
            #
            # REQ-8 AC3 (T26): when the ROUTER holds the primary provider (its
            # health check reports ok), a router failure degrades DIRECTLY to the
            # compressed-summary fallback â€” we do NOT replay the giant synthesis
            # prompt through the LM Studio / Ollama chain (the 429-stall
            # behaviour REQ-8 fixes). LM Studio / Ollama are only tried when the
            # router has NO bound provider (local-only configurations), where
            # they ARE the primary path.
            _router_primary = False
            try:
                if self._router is not None:
                    _router_primary = bool(
                        self._router.health_check_provider("reasoning").get("ok")
                    )
            except Exception:
                _router_primary = False
            try:
                # AC11.6 (session-319): the user-facing answer was the ONLY
                # unbounded wait left in the turn â€” no timeout here, and the
                # transport retried 3x60s beneath it, so one slow provider
                # response could stall the turn for ~3 minutes with nothing
                # watching. This bounds it. On expiry the exception path below
                # degrades to the deterministic compressed summary, which is
                # the honest outcome. Safety net BEHIND streaming (AC13.1),
                # not the primary speed mechanism.
                try:
                    from backend.agent.der_constants import DEADLINE_SYNTHESIS_S
                    _syn_deadline_s = float(DEADLINE_SYNTHESIS_S)
                except Exception:
                    _syn_deadline_s = 120.0
                _syn_text, _syn_think, _syn_tools = self._router.generate(
                    "reasoning",
                    [{"role": "user", "content": synthesis_prompt}],
                    max_tokens=self.response_max_tokens(),
                    temperature=0.6,
                    timeout_s=_syn_deadline_s,
                )
                self._accrue_tokens(
                    _syn_text, getattr(self._router, "last_usage", None),
                    source="_synthesize_response:router",
                )
                # Session-342 (live 2026-09-19): Ollama intermittently answers
                # a synthesis prompt with an EMPTY completion (HTTP 200, no
                # text) while the provider is healthy â€” observed on a working
                # run where the crawl had extracted the answer and the turn
                # degraded to "I've completed the task" anyway. A single retry
                # on the SAME prompt recovers it; without that the user sees a
                # task-status receipt instead of the answer the run found.
                # Bounded: exactly ONE retry, inside the existing deadline.
                if not _syn_text and _router_primary:
                    logger.warning(
                        "[AgentKernel] router synthesis returned empty â€” retrying "
                        "once before degrading (transient empty completion)"
                    )
                    _syn_text, _syn_think, _syn_tools = self._router.generate(
                        "reasoning",
                        [{"role": "user", "content": synthesis_prompt}],
                        max_tokens=self.response_max_tokens(),
                        temperature=0.6,
                        timeout_s=_syn_deadline_s,
                    )
                    self._accrue_tokens(
                        _syn_text, getattr(self._router, "last_usage", None),
                        source="_synthesize_response:router:retry_empty",
                    )
                if _syn_text:
                    logger.info(
                        "[AgentKernel] Brain synthesized response via InferenceRouter"
                    )
                    return self._strip_thinking(_syn_text)
                if _router_primary:
                    # Empty response from the primary provider counts as failure
                    # (the health check reports ok even when the endpoint returns
                    # nothing â€” reachability is only proven at execution time).
                    logger.warning(
                        "[AgentKernel] router (primary) returned empty synthesis â€” "
                        "degrading to compressed-summary fallback (REQ-8 AC3)"
                    )
                    return ""
            except Exception as _syn_err:
                logger.warning(
                    f"[AgentKernel] router synthesis failed: {_syn_err}"
                )
                # Session-342 (live 2026-09-19): the transport RAISES on a
                # transient empty completion ("Empty response from Ollama"),
                # never returning a falsy string â€” so the success-path retry
                # above never fired and the turn degraded to "I've completed
                # the task" while the answer sat extracted on the card. Retry
                # once on THIS shape only; any other failure degrades exactly
                # as before.
                if _router_primary and "empty response" in str(_syn_err).lower():
                    logger.warning(
                        "[AgentKernel] synthesis failed on a transient empty "
                        "completion â€” retrying once (session-342 evidence: the "
                        "same endpoint answered 688 tokens 16s earlier)"
                    )
                    try:
                        _syn_retry, _syn_retry_think, _syn_retry_tools = (
                            self._router.generate(
                                "reasoning",
                                [{"role": "user", "content": synthesis_prompt}],
                                max_tokens=self.response_max_tokens(),
                                temperature=0.6,
                                timeout_s=_syn_deadline_s,
                            )
                        )
                        self._accrue_tokens(
                            _syn_retry,
                            getattr(self._router, "last_usage", None),
                            source="_synthesize_response:router:retry_empty",
                        )
                        if _syn_retry:
                            logger.info(
                                "[AgentKernel] Brain synthesized response via "
                                "InferenceRouter (retry after empty completion)"
                            )
                            return self._strip_thinking(_syn_retry)
                    except Exception as _retry_err:
                        logger.warning(
                            f"[AgentKernel] empty-response retry failed: {_retry_err}"
                        )
                if _router_primary:
                    # REQ-8 AC3 (T26): primary provider failed â€” degrade to the
                    # deterministic compressed summary, no giant-prompt replay.
                    logger.warning(
                        "[AgentKernel] router is the primary provider and failed â€” "
                        "degrading to compressed-summary fallback (REQ-8 AC3)"
                    )
                    return ""

            # Try LM Studio synthesis
            _sel_synth = self._selected_reasoning_model or ""
            if not reasoning_model and self._is_openai_compat():
                try:
                    _lms_synth = self._get_lmstudio_client()
                    _lms_synth_resp = _lms_synth.chat.completions.create(
                        model=_sel_synth or "local-model",
                        messages=[{"role": "user", "content": synthesis_prompt}],
                        max_tokens=-1,
                        temperature=0.7,
                        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                    )
                    _synth_text = _lms_synth_resp.choices[0].message.content
                    if _synth_text:
                        logger.info("[AgentKernel] LM Studio synthesized response")
                        return self._strip_thinking(_synth_text)
                except Exception as _lms_synth_err:
                    logger.warning(
                        f"[AgentKernel] LM Studio synthesis failed: {_lms_synth_err}"
                    )

            # Try Ollama if the selected model is an Ollama model (colon-format ID)
            if not reasoning_model and ":" in _sel_synth:
                try:
                    import requests as _req

                    _r = _req.post(
                        f"{self._ollama_endpoint}/api/chat",
                        json={
                            "model": _sel_synth,
                            "messages": [{"role": "user", "content": synthesis_prompt}],
                            "stream": False,
                        },
                        timeout=60,
                    )
                    if _r.status_code == 200:
                        _synth_text = _r.json().get("message", {}).get("content", "")
                        if _synth_text:
                            logger.info("[AgentKernel] Ollama synthesized response")
                            return self._strip_thinking(_synth_text)
                except Exception as _ollama_synth_err:
                    logger.warning(
                        f"[AgentKernel] Ollama synthesis failed: {_ollama_synth_err}"
                    )

            # No model available for synthesis. Return "" instead of a generic
            # template so the REQ-12 success path falls through to the DER-shaped
            # deterministic summary (_der_deterministic_success_summary) that
            # mirrors _der_deterministic_failure_summary â€” never a silent raw
            # concatenation of step outputs (REQ-12 AC4).
            logger.warning(
                "[AgentKernel] No model for synthesis â€” returning empty "
                "(caller falls back to deterministic summary)"
            )
            return ""

        except Exception as e:
            logger.error(f"[AgentKernel] Error in brain synthesis: {e}")
            return ""

    def get_status(self) -> Dict[str, Any]:
        """
        Get agent status information.

        Returns:
            Status dictionary with:
            - ready: bool - if agent is ready to process requests
            - models_loaded: int - number of loaded models
            - total_models: int - total number of models
            - tool_bridge_available: bool - if tool bridge is available
            - model_status: dict - individual model status
            - single_model_mode: bool - if in fallback mode
            - error: str - initialization error if any
            - vps_gateway: dict - VPS Gateway status (enabled, available endpoints, health)
        """
        status = {
            "ready": False,
            "models_loaded": 0,
            "total_models": 0,
            "tool_bridge_available": False,
            "model_status": {},
            "single_model_mode": self._single_model_mode,
            "error": self._initialization_error,
        }

        # Check model router status
        if self._model_router:
            all_status = self._model_router.get_all_models_status()
            status["model_status"] = all_status
            status["total_models"] = len(all_status)
            status["models_loaded"] = len(self._model_router.get_loaded_models())

            # Agent is ready if at least one model is available
            reasoning_model = self._model_router.get_reasoning_model()
            execution_model = self._model_router.get_execution_model()
            status["ready"] = reasoning_model is not None or execution_model is not None

        # Check tool bridge status
        if self._tool_bridge:
            try:
                bridge_status = self._tool_bridge.get_status()
                status["tool_bridge_available"] = bridge_status.get("available", False)
            except Exception as e:
                logger.warning(f"[AgentKernel] Failed to get tool bridge status: {e}")

        # Add VPS Gateway status
        if self._vps_gateway:
            try:
                vps_status = self._vps_gateway.get_status()
                status["vps_gateway"] = vps_status
                logger.debug(f"[AgentKernel] VPS Gateway status: {vps_status}")
            except Exception as e:
                logger.warning(f"[AgentKernel] Failed to get VPS Gateway status: {e}")
                status["vps_gateway"] = {"enabled": False, "error": str(e)}
        else:
            status["vps_gateway"] = {"enabled": False, "available_endpoints": 0}

        return status

    # NOTE (session 247): a second, arg-less `clear_conversation` used to be
    # defined HERE and silently SHADOWED the real one near the top of this
    # class (line ~590). Python class bodies keep the LAST def, so every
    # `clear_conversation(conversation_id)` call from iris_gateway raised
    # "takes 1 positional argument but 2 were given" â€” logged as
    # "[Chat] Failed to clear previous conversation ..." on every new-thread
    # switch, meaning the previous thread's kernel context was never cleared
    # and could leak into the new thread. The duplicate is removed; the real
    # definition handles both call shapes (conversation_id optional, defaulting
    # to the kernel's current thread).

    def get_conversation_context(
        self, max_messages: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get conversation context.

        Args:
            max_messages: Optional limit on number of messages

        Returns:
            List of message dictionaries
        """
        if self._conversation_memory:
            return self._conversation_memory.get_context(max_messages=max_messages)
        return []

    def update_personality(self, config: Dict[str, Any]) -> None:
        """
        Update personality configuration.

        Args:
            config: Dictionary containing identity fields
        """
        if self._personality:
            self._personality.load_from_config(config)
            logger.info("[AgentKernel] Personality configuration updated")

    # Maps legacy/local model names to their canonical VPS/API identifiers.
    # This allows saved settings that used local model path names to resolve
    # correctly against VPS available-model IDs without requiring a migration.
    _MODEL_ALIASES: Dict[str, str] = {
        # Legacy local model directory name â†’ canonical ID (executor only; brain removed)
        "LFM2.5-1.2B-Instruct": "lfm2.5-1.2b-instruct",
        "executor": "lfm2.5-1.2b-instruct",
        # NOTE: LFM2-8B-A1B / "brain" / "lfm2-8b" aliases are intentionally absent.
        # That model is not in use â€” removing the aliases prevents accidental routing.
    }





    def set_internet_access(self, enabled: bool) -> None:
        """
        Enable or disable agent internet access.

        Delegates to the app-wide global flag (set_global_internet_access) so that
        internet access is a single switch for all conversations, not per-kernel.
        The UI web-mode toggle flips this via iris_gateway.set_web_mode.

        Args:
            enabled: True to enable internet access, False to disable
        """
        set_global_internet_access(enabled)

    def get_internet_access(self) -> bool:
        """
        Get current internet access setting (app-wide global).

        Returns:
            True if internet access is enabled, False otherwise
        """
        return get_global_internet_access()

    def set_swarm_enabled(self, enabled: bool) -> None:
        """
        Enable or disable multi-agent swarm compound collaboration.
        Initialises SwarmCoordinator and ContextControlHandler lazily on first enable.
        """
        self._swarm_enabled = enabled
        if (
            enabled
            and self._memory_interface is not None
            and self._swarm_coordinator is None
        ):
            try:
                from backend.agent.swarm import SwarmCoordinator, ContextControlHandler
                from backend.agent.mcm import MCM

                _mcm = MCM(self._memory_interface, self.session_id)
                _protocol = self._mcm_orch._protocol if self._mcm_orch else None
                self._swarm_coordinator = SwarmCoordinator(
                    memory_interface=self._memory_interface,
                    session_id=self.session_id,
                    agent_id=self.session_id,
                    protocol=_protocol,
                )
                self._context_control_handler = ContextControlHandler(
                    memory_interface=self._memory_interface,
                    mcm_instance=_mcm,
                    session_id=self.session_id,
                )
                logger.info(
                    "[AgentKernel] SwarmCoordinator + ContextControlHandler initialized"
                )
            except Exception as _swarm_err:
                logger.warning("[AgentKernel] Swarm init failed: %s", _swarm_err)
        logger.info("[AgentKernel] Swarm %s", "enabled" if enabled else "disabled")

    def get_swarm_enabled(self) -> bool:
        """Return current swarm enabled state."""
        return self._swarm_enabled

    def _handle_control_codes(self, response_text: str, messages: list) -> list:
        """
        Scan response for MCM: control codes (MCM:999/998/997/996) and execute.
        Called after every agent response when swarm is enabled.
        Never raises. Returns messages (potentially modified by MCM:999 prune).
        """
        if not self._swarm_enabled or self._context_control_handler is None:
            return messages
        try:
            self._context_control_handler.scan_and_execute(
                response_text,
                messages,
                self._current_task if hasattr(self, "_current_task") else "",
            )
        except Exception:
            pass
        return messages


# Singleton instance management
_agent_kernel_instances: Dict[str, AgentKernel] = {}

# â”€â”€ Global internet-access gate (app-wide) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Web mode is a single app-level switch, not per-conversation.  Kernels are
# created per conversation (_agent_kernel_instances), but internet access must
# apply to every kernel at once when the user toggles web mode in the UI.
# set_web_mode in iris_gateway flips this; tool_bridge gates web tools on it.
_internet_access_enabled: bool = False


def set_global_internet_access(enabled: bool) -> None:
    """Flip the app-wide internet-access gate (UI web-mode toggle)."""
    global _internet_access_enabled
    _internet_access_enabled = bool(enabled)
    logger.info(
        f"[AgentKernel] Global internet access {'enabled' if enabled else 'disabled'}"
    )


def get_global_internet_access() -> bool:
    """Return the app-wide internet-access gate state."""
    return _internet_access_enabled


# â”€â”€ Global desktop-control gate (app-wide) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Desktop control = launching the user's real browser/apps, opening files with
# their default application, locking the screen, GUI/screen automation, etc.
# Everything that reaches OUTSIDE the app sandbox.  It is OFF by default and
# only enabled when the user explicitly grants permission via the
# desktop_control dashboard card (confirm_card â†’ set_desktop_control_enabled).
# tool_bridge gates every desktop-control tool on this flag so the agent can
# NEVER reach the desktop unless the user opted in.
_desktop_control_enabled: bool = False


def set_desktop_control_enabled(enabled: bool) -> None:
    """Flip the app-wide desktop-control gate (UI desktop_control card)."""
    global _desktop_control_enabled
    _desktop_control_enabled = bool(enabled)
    logger.info(
        f"[AgentKernel] Desktop control {'enabled' if enabled else 'disabled'}"
    )


def get_desktop_control_enabled() -> bool:
    """Return the app-wide desktop-control gate state."""
    return _desktop_control_enabled


# Last-known-good swarm configuration snapshot.
# When a new session's kernel is created after swarm mode has already been
# configured, it reads from this snapshot instead of relying on peer
# inheritance (which fails if all peers were also created post-swarm).
_swarm_config_snapshot: Optional[dict] = None

# REMOVED 2026-08-16: `_model_config_snapshot`. It was a module-global copy of
# the persisted model config, stashed at startup so lazily-created kernels could
# hydrate from it. It is gone because the thing it hydrated is gone: kernels now
# read the process-wide role-binding table, which already holds the live choice.
#
# It was also the third of the five competing sources of truth for "which model
# is active", and the one that made the others hard to reason about â€” it was
# written by set_model_selection under one key spelling ("tool_execution_model")
# and read under another ("tool_model"), and its reader had been raising
# TypeError on every call since the day set_model_selection's signature changed.
# Startup seeding now happens once, in InferenceRouter._apply_config.


def get_agent_kernel(
    conversation_id: str = "default",
    session_id: Optional[str] = None,
) -> AgentKernel:
    """
    Get or create an AgentKernel instance for a conversation.
    Auto-wires the memory interface (Pillar 4) when a new kernel is created.

    Re-keyed from session_id to conversation_id for multi-thread context.
    session_id is preserved for WS routing and Mycelium ingestion.

    Args:
        conversation_id: Primary key â€” one kernel per conversation thread.
        session_id: Transport label for WS routing and Mycelium.
                    If None, falls back to conversation_id.

    Returns:
        AgentKernel instance for the conversation
    """
    global _agent_kernel_instances

    _sid = session_id or conversation_id

    if conversation_id not in _agent_kernel_instances:
        # DIAGNOSTIC: kernels are cached BY conversation_id, so a conversation
        # id that drifts mid-turn silently constructs a SECOND kernel and
        # orphans the first one's in-turn state (tokens, node records, DER
        # bookkeeping). That was observed live: a fresh kernel for conv-1 was
        # initialised AFTER turn 1 had already completed, while the turn itself
        # ran under session_iris. Log every construction with BOTH ids and the
        # existing keys so a mid-turn rebuild is visible instead of inferred.
        # Note some keys are pseudo-conversations by design (crawl_planner,
        # data_extractor, default) â€” those are expected; a real thread id
        # appearing twice, or appearing late, is not.
        logger.info(
            "[AgentKernel] CONSTRUCTING kernel conv=%r session=%r "
            "(existing keys: %s)",
            conversation_id,
            _sid,
            sorted(_agent_kernel_instances.keys()),
        )
        kernel = AgentKernel(
            session_id=_sid,
            conversation_id=conversation_id,
        )

        # Auto-wire Pillar 4 (Memory) â€” connects episodic/semantic memory to every session
        try:
            from backend.memory import get_memory_interface

            memory = get_memory_interface()
            if memory is not None:
                kernel.set_memory_interface(memory)
                logger.info(
                    f"[AgentKernel] Memory interface wired for conv={conversation_id}"
                )
        except Exception as e:
            logger.warning(
                f"[AgentKernel] Memory interface not available for conv={conversation_id}: {e}"
            )

        # Inherit inference BEHAVIOUR settings from any already-configured peer.
        #
        # Context: the user configures things once (in session_iris / the main UI
        # session).  Secondary sessions â€” such as session_iris_integration which is
        # created when the wake-word fires â€” are spun up lazily.  Without this,
        # a wake-word-triggered response ran with default behaviour settings.
        #
        # WHICH MODEL SERVES WHICH ROLE IS NOT COPIED HERE (2026-08-16). It used
        # to be: this block called ``set_model_selection(model_provider=peer.
        # _model_provider, ...)`` without ``preserve_bindings``, which fell
        # through to ``bind_role`` and REBOUND the process-wide role table from
        # the peer's LEGACY fields. Those fields are not updated by the gateway's
        # role-binding path, so they held the startup provider â€” and every new
        # conversation therefore reverted the user's live pick (the recurring
        # "picked cohere, sent a message, back to cerebras" bug).
        #
        # There is nothing to copy: the role table and the provider registry are
        # process-wide singletons (REQ-5), so this kernel's router already sees
        # the user's live choice the moment it is constructed. Model/provider
        # state is READ from the router (see the ``_model_provider`` /
        # ``_selected_*_model`` properties), never stored per kernel.
        #
        # Credentials likewise live on the ProviderInstance in the shared
        # registry; ``_api_key`` / ``_api_base_url`` are copied only as a
        # compatibility convenience for the remaining direct readers.
        for peer_key, peer_kernel in _agent_kernel_instances.items():
            if peer_kernel is kernel:
                continue
            if peer_kernel._model_provider in (None, "uninitialized"):
                continue
            kernel._lmstudio_endpoint = peer_kernel._lmstudio_endpoint
            if peer_kernel._api_key:
                kernel._api_key = peer_kernel._api_key
                kernel._api_key_provider = peer_kernel._api_key_provider
            if peer_kernel._api_base_url:
                kernel._api_base_url = peer_kernel._api_base_url
            kernel._thinking_style = peer_kernel._thinking_style
            kernel._response_length = peer_kernel._response_length
            kernel._reasoning_effort = peer_kernel._reasoning_effort
            kernel._tool_mode = peer_kernel._tool_mode
            logger.info(
                f"[AgentKernel] Conv '{conversation_id}' inherited inference "
                f"behaviour from '{peer_key}' "
                f"(active model comes from the shared router: "
                f"provider={kernel._model_provider!r}, "
                f"model={kernel._selected_reasoning_model!r})"
            )
            break

        if kernel._model_provider == "uninitialized":
            # If no role is bound yet and a global swarm snapshot exists,
            # auto-hydrate this kernel so it doesn't stay "uninitialized".
            if _swarm_config_snapshot is not None:
                # SLICE 5: wire the router (not the legacy compat client) so
                # DER/Pacman inference paths actually use the swarm endpoint.
                try:
                    from backend.agent.inference.provider import (
                        ProviderInstance,
                        ProviderKind,
                    )

                    _ep = _swarm_config_snapshot.get("endpoint") or ""
                    _r_model = _swarm_config_snapshot.get("reasoning_model")
                    _t_model = _swarm_config_snapshot.get("tool_model")
                    _inst = ProviderInstance(
                        id="swarm_director",
                        label="Swarm (auto-hydrated)",
                        kind=ProviderKind.LOCAL_OPENAI,
                        model=_r_model or "local-model",
                        api_base_url=_ep,
                    )
                    _router = getattr(kernel, "_router", None)
                    if _router is not None:
                        _router.add_provider(_inst)
                        _router.bind_role("reasoning", "swarm_director")
                        _router.bind_role(
                            "tool_execution", "swarm_director", model_override=_t_model
                        )
                except Exception as _sw_err:
                    logger.warning(
                        f"[AgentKernel] Swarm auto-hydrate router wire failed: {_sw_err}"
                    )
                kernel._swarm_enabled = True
                logger.info(
                    f"[AgentKernel] Conv '{conversation_id}' auto-hydrated from "
                    f"swarm snapshot (provider='iris_local', "
                    f"endpoint={_swarm_config_snapshot.get('endpoint')!r})"
                )

            # NOTE (2026-08-16): a "persisted model config snapshot" hydrate
            # used to live here, replaying `_model_config_snapshot` through
            # set_model_selection. It was removed for two reasons. First, it
            # had never run: it passed `provider=`, `thinking_style=`,
            # `response_length=` and `tool_mode=`, none of which are parameters
            # of set_model_selection, so every call raised TypeError straight
            # into the handler below it and logged "model snapshot hydrate
            # failed". Second, even working it would have been wrong â€” it
            # replayed a STORED copy of the user's choice over the live
            # process-wide role table, which is the same class of bug as the
            # peer-inheritance rebind above. Startup seeding belongs in
            # InferenceRouter._apply_config, which now binds only unbound roles.

        _agent_kernel_instances[conversation_id] = kernel

    return _agent_kernel_instances[conversation_id]


# â”€â”€ Session â†’ active conversation registry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Wave 5 (session-conversation-switching spec): eliminates the phantom
# "default" kernel.  Callers that only knew a session_id (e.g. a wake-word
# voice path, a reconnect, a REST chat request) were calling
# get_agent_kernel(session_id=...) which fell back to conversation_id="default",
# creating a kernel the active thread never used.  The gateway owns the
# authoritative sessionâ†’active-conversation binding (_active_conversation_id);
# it mirrors that binding here (module-level, no circular import) so any
# caller can resolve the *real* active kernel for a session via
# get_active_kernel(session_id) instead of spawning a "default" ghost.
_session_active_conversation: dict = {}


def set_active_conversation(
    session_id: str, conversation_id: Optional[str]
) -> None:
    """Mirror the gateway's sessionâ†’active-conversation binding into this
    module-level registry.  Called by the gateway whenever it (re)points a
    session at a conversation (new_conversation / switch_conversation /
    sync_state / voice_command_start / connect).

    ``conversation_id=None`` UNBINDS the session â€” the state "the user left a
    thread and has not started the next one yet".  Leaving a stale binding in
    place is what let a wake word or a reconnect resolve back into the thread
    the user had just walked away from, so the absence of a thread has to be
    representable, not approximated by the session id."""
    global _session_active_conversation
    if not session_id:
        return
    if conversation_id:
        _session_active_conversation[session_id] = conversation_id
    else:
        _session_active_conversation.pop(session_id, None)


def get_active_kernel(session_id: str) -> "AgentKernel":
    """Resolve the kernel for a session's *currently active* conversation.

    Falls back to conversation_id="default" only when no active conversation
    has been registered for the session (e.g. a brand-new session before the
    first new_conversation / sync_state).  This is the correct replacement for
    the old get_agent_kernel(session_id=...) pattern that silently created a
    phantom "default" kernel disconnected from the active thread.
    """
    conv_id = _session_active_conversation.get(session_id) or "default"
    return get_agent_kernel(conversation_id=conv_id, session_id=session_id)


def peek_active_kernel(session_id: str) -> "Optional[AgentKernel]":
    """Non-constructing variant of ``get_active_kernel``: return the kernel
    for a session's currently active conversation IF one already exists,
    else ``None``.

    Never constructs a kernel.  ``get_agent_kernel`` builds a full
    ``AgentKernel`` when absent (measured 71.81s cold on 2026-08-12), which
    made read-only paths (``/api/inference/state``, ``request_state``) time
    out on page loads racing backend startup.  Callers that only read router
    state (inference snapshot, status broadcast) MUST use this instead so a
    read can never pay kernel-construction cost.  ``build_inference_snapshot``
    already accepts ``None`` and returns the full key set with empty
    providers, so a missing kernel degrades gracefully, never errors.
    """
    conv_id = _session_active_conversation.get(session_id) or "default"
    return _agent_kernel_instances.get(conv_id)


def cleanup_agent_kernel(
    conversation_id: str,
    session_id: Optional[str] = None,
) -> None:
    """
    Remove the AgentKernel instance for a conversation and release its resources.

    Call this when a conversation expires or is deleted.
    Keyed by conversation_id (re-keyed from session_id).

    Args:
        conversation_id: Conversation whose kernel should be cleaned up
        session_id: Optional session label for logging
    """
    global _agent_kernel_instances
    kernel = _agent_kernel_instances.pop(conversation_id, None)
    _log_id = session_id or conversation_id
    if kernel is not None:
        try:
            # Save any pending context to the store
            try:
                kernel.save_context_to_store()
            except Exception:
                pass
            # Shut down VPS Gateway if it was active
            if kernel._vps_gateway is not None:
                import asyncio

                try:
                    # Prefer the already-running loop (cleanup called from async context).
                    # Fall back to a fresh asyncio.run() if called from a sync context.
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(kernel.shutdown_vps_gateway())
                    except RuntimeError:
                        asyncio.run(kernel.shutdown_vps_gateway())
                except Exception:
                    pass
        except Exception as e:
            logger.warning(
                f"[AgentKernel] Error during cleanup for conv {_log_id}: {e}"
            )
        logger.info(f"[AgentKernel] Kernel cleaned up for conv {_log_id}")




# <kernel-split:propagate> generated by scripts/kernel_split_check.py move; do not edit by hand
# RES-7: an assignment to one of these module attributes (mock.patch, monkeypatch.setattr,
# plain `agent_kernel.X = v`) is forwarded to every kernel module that binds the name.
# A `global X; X = v` store inside this file does NOT pass through __setattr__.
import sys as _sys
import types as _types
_PROPAGATE = {
    'backend.agent.kernel.base': ('AgentKernel', '_emit_event', 'debit_work_units', ),
    'backend.agent.kernel.context': ('TurnMetrics', ),
    'backend.agent.kernel.models': ('_agent_kernel_instances', ),
    'backend.agent.kernel.surface': ('AgentKernel', '_emit_event', ),
}


class _KernelModule(_types.ModuleType):
    def __setattr__(self, name, value):
        _types.ModuleType.__setattr__(self, name, value)
        for _mod_name, _names in _PROPAGATE.items():
            if name in _names:
                _target = _sys.modules.get(_mod_name)
                if _target is not None:
                    setattr(_target, name, value)


_sys.modules[__name__].__class__ = _KernelModule
for _mod_name, _names in _PROPAGATE.items():
    for _name in _names:
        setattr(_sys.modules[_mod_name], _name, globals()[_name])
# </kernel-split:propagate>
