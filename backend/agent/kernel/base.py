# Moved from backend/agent/agent_kernel.py by scripts/kernel_split_check.py move.
# Bodies are byte-identical to the originals (guard: kernel_split_check.py manifest --check).
from __future__ import annotations

import threading
import os
from typing import Any, Dict, Optional, List, Callable, Tuple, Sequence
import logging


def _der_ledger_storage_path() -> str:
    """GROUND TRUTH T9 (REQ-14 AC1): where the DER execution ledger lives.

    Env-overridable, mirroring the existing IRIS_DER_* convention. Kept a
    function rather than a constant so tests can point it elsewhere without
    touching module state.
    """
    return os.environ.get("IRIS_DER_LEDGER_DIR", os.path.join("data", "der_ledger"))

logger = logging.getLogger("backend.agent.agent_kernel")  # RES-3: log name unchanged

# Per-session update counter for homeostatic relaxation cadence (REQ-1 AC2).
# Keyed by session_id, incremented each time _der_finalize_step processes a
# non-exception step. Reset is implicit â€” a new session starts at 0.
_update_counters: Dict[str, int] = {}

_update_counters_lock = threading.Lock()

# Session-319: guards the per-host-per-turn recovery budget
# (`_der_recovery_opened`). Parallel_safe steps run concurrently (Phase 4,
# agent_kernel.py "run multiple parallel_safe steps concurrently"), so the
# check-and-claim of that budget MUST be atomic. Without this lock two steps
# that hit the same dead host at the same moment can both read "not yet
# opened" and each enqueue a recovery â€” two crews for one broken door, though
# the rule allows one. Module-level so it is shared by every kernel instance.
_der_recovery_lock = threading.Lock()

# â”€â”€ Physics side lane helpers (see AgentKernel._der_submit_physics). Module
# level on purpose: a kernel stand-in that binds only some methods must still
# run the read a barrier guards, so the barrier cannot live on the class.
def _turn_in_flight(fn):
    """Mark the whole turn busy on the process IdleTracker (every entry: voice,
    chat, the developer orchestrator). Background work that waits for idle
    (whisper warm-up, distillation) then waits for the turn to END - not only
    for input to stop: a fixed-delay warm-up fired inside eval c01 and its HDD
    import held the first pytest for 220 s (2026-10-01)."""
    import functools

    @functools.wraps(fn)
    def _wrapper(*args, **kwargs):
        try:
            from backend.core.idle_tracker import get_idle_tracker

            busy = get_idle_tracker().busy()
        except Exception:  # noqa: BLE001 - a tracker fault never blocks a turn
            return fn(*args, **kwargs)
        with busy:
            return fn(*args, **kwargs)

    return _wrapper

_STEP_ID_KEYS = ("path", "file_path", "command", "pattern", "query", "url")

# â”€â”€ Parallel nodes (owner 2026-10-04) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# A node CLAIMS a resource only one node may drive at a time when it first
# uses it, and holds it until the node ends: one browser page per
# conversation, one desktop screen. Everything else (search, files, reasoning)
# runs side by side. This is the lane rule (one writer per resource), not the
# phase model - two drivers on one page break the page.
_NODE_CLAIMS = {
    "browser": frozenset({"browser_open", "browser_observe", "browser_act", "browser_explore"}),
    "screen": frozenset({"take_screenshot", "vision_analyze_screen", "gui_click", "gui_type",
                         "gui_press_key", "launch_app", "open_file", "open_url"}),
}

_SCREEN_CLAIM = threading.Lock()  # one desktop, every conversation

_CLAIM_LOCKS: Dict[tuple, "threading.Lock"] = {}  # (conversation, claim) -> lock

_CLAIM_LOCKS_GUARD = threading.Lock()

_DER_NODE_QUOTA: Dict[str, Optional[str]] = {"quota": None}

_DER_PARALLEL = os.environ.get("IRIS_DER_PARALLEL", "1").strip().lower() not in ("0", "false", "off", "no")

def _step_calls(item) -> list:
    """What a settled step ACTUALLY did - the one source for every reader that
    used ``item.tool`` as "what this step did". A node step (since 2026-09-29)
    has no tool/params; its calls are ``node_call_log`` (set by _der_run_node).
    A direct step is its one tool. Returns [{tool, target, ok, args}] ([] for
    a step that made no call). Module level on purpose (stand-in kernels)."""
    log = getattr(item, "node_call_log", None)
    if isinstance(log, list):
        return log
    tool = getattr(item, "tool", None)
    if not tool:
        return []
    params = getattr(item, "params", None)
    args = {k: params[k] for k in _STEP_ID_KEYS if isinstance(params, dict) and params.get(k)}
    return [{"tool": str(tool), "target": str(next(iter(args.values()), ""))[:80],
             "ok": True, "args": args}]

def _step_evidence_cap(item) -> int:
    """How much of a settled step's result later steps, the window and the
    synthesis see. A node step has no item.tool, so the by-tool rule gave it the
    400-char default: its ~275-char summary filled it and the "Tool results"
    with the facts were cut (live 2026-10-04: the page held "5,895 m" and
    "1889"; the reply said they were missing). A node's result is its own
    summary + what it read, so it gets the read/gather window - and one
    NODE_BLOCK_HEAD per call beyond that, so a node that searched three facts
    keeps all three heads (eval r09 conv-810: the middle search was cut out).
    Module level on purpose (stand-in kernels)."""
    _log = getattr(item, "node_call_log", None)
    if isinstance(_log, list):
        from backend.agent.node_executor import NODE_BLOCK_HEAD

        # + the summary and the per-call headers / cut markers
        return max(8000, NODE_BLOCK_HEAD * len(_log)) + 1500
    return AgentKernel._der_evidence_cap(getattr(item, "tool", None))

def _step_decisive_call(item) -> Optional[dict]:
    """The call that decided the step: the last failed one, else the last."""
    calls = _step_calls(item)
    if not calls:
        return None
    failed = [c for c in calls if not c.get("ok", True)]
    return (failed or calls)[-1]

def _step_tool(item):
    """One tool name for readers that keep a single field (ledger, triage,
    card): the decisive call's tool; ``item.tool`` when no call ran yet."""
    call = _step_decisive_call(item)
    return call.get("tool") if call else getattr(item, "tool", None)

# Sentinel for "no turn has filled the window yet" (a turn id may itself be None).
_FILL_NO_TURN = object()

def _memory_events_submit(owner, fn_name: str, **kwargs) -> None:
    """Typed execution events (spec research-memory-chain-browser D9 / Wave E)
    on lane("memory_events"): never on the answer path, never raises. The
    coordinate is read inside the job (the step's physics may land first).
    The body lives in backend/agent/event_emit.py (shared with the rule emitters
    of the event taxonomy, which also run outside the kernel)."""
    from backend.agent.event_emit import submit

    submit(owner, fn_name, **kwargs)

def _emit_event(owner, label: str, **kw) -> None:
    """A rule-labelled taxonomy event (CONTROL / DELIVERY ...) on the same lane.
    Module level on purpose: stand-in kernels bind only some methods."""
    from backend.agent.event_emit import emit

    emit(owner, label, **kw)

def _der_recall_delivered(owner, item, source: str, refs, session_id: str) -> None:
    """Memory entered THIS step's context (taxonomy v1, memory family). Mints the
    recall_trace_id, carries it on the step to its outcome (record_step then types
    RECALL_HELPED or RECALL_MISLED for it), and types RECALL_DELIVERED on the
    memory_events lane. Only recalls delivered to a step are ever credited to it.
    Module level on purpose (stand-in kernels bind only some methods). Never raises."""
    try:
        from backend.memory.memory_events import new_recall_trace_id

        trace = new_recall_trace_id()
        traces = getattr(item, "recall_trace_ids", None)
        if traces is None:
            traces = item.recall_trace_ids = []
        traces.append(trace)
        _memory_events_submit(
            owner, "record_recall_delivered", thread_id=session_id,
            task_id=f"{session_id}:{getattr(owner, '_der_turn_id', None) or ''}",
            step_id=str(getattr(item, "step_id", "") or ""), source=source,
            recall_trace_id=trace, refs=list(refs or [])[:5],
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[memory_events] recall delivery not typed: %s", exc)

def _der_fold_envelope(item, fold) -> None:
    """Write the landed physics onto the step's envelope (caller holds
    fold.lock). Idempotent: whichever of the lane and the envelope build
    finishes second applies it."""
    env = getattr(item, "envelope", None)
    if env is None:
        return
    if fold.coords_to is not None:
        env.coords_from = str(fold.coords_from or "")
        env.coords_to = str(fold.coords_to or "")
        env.coords_basis = "format_coords"
    if fold.rec == 3:
        # AC3.4: a TOPO_VIOLATION forces suggestion=stop (physics first).
        env.suggestion = "stop"

# â”€â”€ DER Loop constants (spec: agent_loop_requirements.md Gap 11) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Canonical values live in der_constants.py â€” re-exported here for spec
# compliance so module-level code that imports from agent_kernel finds them.
try:
    from backend.agent.der_constants import (
        DER_MAX_CYCLES,
        DER_MAX_VETO_PER_ITEM,
        DER_MAX_GRAFTS,
        DER_MAX_UNVERIFIED_REPROPOSE,
        DER_FOLD_BACK_MAX,
        DER_EMERGENCY_STOP,
        DER_TOKEN_BUDGETS,
        AVG_STEP_COST,
        debit_work_units,
        derive_work_units_0,
        resolve_der_token_budget,
        ResolvedWindow,
        ExecutionMode,
    )
except Exception:
    DER_MAX_CYCLES = 40
    DER_MAX_VETO_PER_ITEM = 2
    DER_MAX_GRAFTS = 3
    DER_FOLD_BACK_MAX = 3
    DER_MAX_UNVERIFIED_REPROPOSE = 1
    DER_EMERGENCY_STOP = 200
    DER_TOKEN_BUDGETS: Dict[str, int] = {
        "implement": 40000,
        "debug": 30000,
        "research": 20000,
        "full": 50000,
        "quick_edit": 8000,
    }
    AVG_STEP_COST = 1500

    def derive_work_units_0(context_window: int) -> int:
        return max(1, int(context_window / AVG_STEP_COST))

    def resolve_der_token_budget(context_window: int, task_class=None) -> int:
        # Mirrors der_constants.resolve_der_token_budget: mode value is a
        # CEILING, the window is the hard cap, the floor is applied last and is
        # itself clamped by the window so it can never overcommit.
        # SESSION 366: cap is the REAL window (DER_WINDOW_UTILISATION is 1.0 in
        # der_constants; this fallback mirrors it so the import-guard path and the
        # real path cannot disagree).
        _cap = max(int(context_window), 1)
        _ceiling = DER_TOKEN_BUDGETS.get(task_class, DER_TOKEN_BUDGETS.get("full", 50000))
        return max(min(_ceiling, _cap), min(4000, _cap))

    def is_shallow_verified(depth_layer: int, result_tokens: int, task_class) -> bool:
        # Mirrors der_constants.is_shallow_verified (REQ-5) for the import-guard
        # fallback path. Excluded classes never flag (AC3).
        if task_class and str(task_class).lower() in (
            "question", "greeting", "simple_command",
        ):
            return False
        return depth_layer <= 1 and result_tokens < 400
