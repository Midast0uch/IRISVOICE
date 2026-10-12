"""tool_approval — the binary outcome-referenced approval consumer (2026-10-10).

WHY THIS EXISTS. The ``tool_choice`` consumer's parity label is noisy: a
confident, valid-but-different pick scores "wrong" against the Brain's pick, so
its AUROC is punished for the LABEL's unfairness, not the model's. This consumer
asks the FAIR question instead:

    "Is this tool the right next tool for this goal, given this result?"

answered yes/no (d1's best shape — the live noul probe spread P(yes) 0.01-0.99),
and labelled by the call's OUTCOME: ``brain_bool = (the call succeeded)``. The
reference is GROUND TRUTH, so the row is scoreable the moment it lands and the
label noise is gone. Build spec: pin_1fb3ce63bb3b.

SHADOW ONLY. Nothing here changes what runs. The consult is POST-HOC: it runs at
tool-result time with the PRE-CALL frame bound as values. The call's own result
NEVER enters the frame — that would leak the answer the row is measuring.

The row shape follows monitor_shadow/surface_shadow exactly: a Noul row carries
``chosen`` as a BOOL (the report's ``decision_label`` compares
``bool(chosen) == bool(brain_bool)``; a string "no" would read as True), the
confidence in the CHOSEN answer, and the raw ``probability`` beside it.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("tool_approval_shadow")

TOOL_APPROVAL_CONSUMER = "tool_approval"

# The question the model scores against (the Decision Index `instructions`
# field). Registered on the consumer spec so the backend renders it.
TOOL_APPROVAL_INSTRUCTION = (
    "Is this tool the right next tool for this goal, given this result?"
)

_TRUE_LABEL = "yes"
_FALSE_LABEL = "no"

# The frame change stamp. Any change to what the model reads = a new stamp, so
# rows measured under different frames never blend (the cohort rule).
# v2 (2026-10-10, owner-directed iteration): the frame adds the call's
# ARGUMENTS and the offered tool list. v1 read AUROC 0.4953 at n=104 — for a
# tool like run_command the arguments are the strongest approval signal, and
# the model could not see what else was on the menu. v1 rows are RETIRED
# (criteria_version scopes them; never blend them back).
# v3 (2026-10-11): `calls_this_step` (the step's own calls so far) and
# last_result = THIS step's last call. The node path passed the previous
# STEP's result, computed once per node, so every call of a step carried the
# same evidence (the tool_choice defect, measured 50.9% parity there).
CRITERIA_VERSION = "tool_approval/v3"

# Sentinel: adopt the module-level engine singleton. `engine=None` means NO
# ENGINE (fail-safe) — never "resolve the singleton", or a shadow scorer would
# silently load the model the first time it is called.
AUTO_ENGINE = object()

# Process-wide row sink. The consult sites have no bridge of their own, so this
# is how their rows reach a ledger (the kernel installs it) — and how a test
# observes them. None = log only, never silently dropped.
_ROW_SINK: Optional[Callable[[dict], None]] = None


def set_row_sink(sink: Optional[Callable[[dict], None]]) -> None:
    """Install (or clear) the process-wide row sink. Test seam / ledger wiring."""
    global _ROW_SINK
    _ROW_SINK = sink


def emit_row(row: Optional[dict]) -> None:
    """Hand a shadow row to the installed sink, else log it. Never raises."""
    if not row:
        return
    sink = _ROW_SINK
    if callable(sink):
        try:
            sink(row)
            return
        except Exception as e:  # noqa: BLE001 — an observer never blocks
            logger.debug("[tool_approval] row sink failed: %r", e)
    logger.info(
        "[tool_approval] shadow row chosen=%s conf=%s brain=%s",
        row.get("chosen"), row.get("confidence"), row.get("brain_bool"),
    )


def register_tool_approval_consumer() -> bool:
    """Register the consumer's criteria (declared noul). Idempotent.

    REQ-4: the DECLARED type and criteria come from the declaration table
    (``register_declared``); ``needs_upgrade`` also replaces a pre-REQ-4 spec.
    """
    try:
        from backend.agent.decision_engine import (
            get_consumer_spec,
            needs_upgrade,
            register_declared,
        )
        if not needs_upgrade(get_consumer_spec(TOOL_APPROVAL_CONSUMER)):
            return False
        register_declared(
            TOOL_APPROVAL_CONSUMER, TOOL_APPROVAL_INSTRUCTION,
            (_TRUE_LABEL, _FALSE_LABEL),
        )
        return True
    except Exception as e:  # noqa: BLE001 — criteria are best-effort
        logger.debug("[tool_approval] consumer spec unavailable: %s", e)
        return False


def _default_engine():
    """The process-wide decision engine, or None. Never raises."""
    try:
        from backend.agent.decision_engine import get_decision_engine

        return get_decision_engine()
    except Exception:  # noqa: BLE001 — a missing engine is simply no verdict
        return None


def _scope_now() -> Dict[str, str]:
    """REQ-6 AC6.3a: the row's scope (turn/step/node ids), bound AS VALUES at
    submit time — the shadow lane's own thread context would say nothing."""
    try:
        from backend.agent.decision_engine import scope_now

        return scope_now()
    except Exception:  # noqa: BLE001 - scope is best-effort, never fatal
        return {}


def score_tool_approval(
    frame: Dict[str, Any],
    *,
    engine: Any = None,
) -> Optional[Any]:
    """The consumer's Noul for the approval question, or None. Never raises.

    ``frame`` carries the PRE-CALL evidence: goal, last_result, proposed_tool,
    tool_description. The call's own result is deliberately absent.
    """
    try:
        register_tool_approval_consumer()
        eng = _default_engine() if engine is AUTO_ENGINE else engine
        if eng is None:
            return None
        scorer = getattr(eng, "noul", None)
        if not callable(scorer):
            return None
        return scorer(
            TOOL_APPROVAL_CONSUMER,
            TOOL_APPROVAL_INSTRUCTION,
            frame,
            true_label=_TRUE_LABEL, false_label=_FALSE_LABEL,
        )
    except Exception as e:  # noqa: BLE001 — a shadow never raises
        logger.debug("[tool_approval] shadow failed: %r", e)
        return None


def shadow_row(
    noul: Optional[Any],
    brain_bool: Optional[bool],
    scope: Optional[Dict[str, str]] = None,
) -> Optional[dict]:
    """The row for one approval judgment, or None.

    No Noul → no row: a missing engine must never fabricate a shadow row.
    ``brain_bool`` is the call's OUTCOME (success), so the row is a shadow PAIR
    with GROUND TRUTH as the reference.
    """
    if noul is None:
        return None
    p = float(noul.probability)
    row = {
        "consumer_id": TOOL_APPROVAL_CONSUMER,
        "job": "approve",
        # BOOL, not "yes"/"no": the report's decision_label compares
        # bool(chosen) == bool(brain_bool) for a noul row (a string "no" would
        # read as True). Same shape as monitor_shadow/surface_shadow.
        "chosen": bool(noul.true(0.5)),
        # Confidence in the CHOSEN answer, raw P(true) beside it (see
        # monitor_shadow.shadow_row: P(true) read as confidence inverts a "no").
        "confidence": round(max(p, 1.0 - p), 4),
        "probability": round(p, 4),
        "engine_latency_ms": noul.engine_latency_ms,
        "brain_bool": brain_bool,
        "shadow": True,
        "criteria_version": CRITERIA_VERSION,
    }
    if scope:
        row.update(scope)
    return row


def _fmt_args(args: Optional[dict]) -> Optional[str]:
    """The call's arguments, rendered compactly for the state text: the
    identifying values only, each bounded (never a file body whole). Never
    raises."""
    try:
        if not isinstance(args, dict) or not args:
            return None
        parts = []
        for k, v in args.items():
            parts.append(f"{k}={str(v)[:80]}")
            if len(parts) >= 6:
                break
        return "; ".join(parts)[:400] or None
    except Exception:  # noqa: BLE001 — evidence is best-effort
        return None


def _fmt_tools(tools: Optional[list]) -> Optional[str]:
    """The offered tool NAMES (what else was on the menu), compact. Never
    raises."""
    try:
        names = [str(t) for t in (tools or []) if t]
        return "; ".join(names[:12])[:150] or None
    except Exception:  # noqa: BLE001 — evidence is best-effort
        return None


def record_tool_approval(
    *,
    goal: str,
    last_result: Optional[str],
    proposed_tool: str,
    tool_description: str = "",
    args: Optional[dict] = None,
    offered_tools: Optional[list] = None,
    outcome_success: bool,
    engine: Any = AUTO_ENGINE,
    session_id: str = "",
    conversation_id: str = "",
    calls_this_step: Optional[str] = None,
) -> None:
    """Submit the post-hoc approval consult on the ``oracle_shadow`` lane.

    Called at TOOL-RESULT time: the pre-call values are bound now (the goal, the
    previous result, the proposed tool, its description, the call's ARGUMENTS
    and the offered tool list) and the OUTCOME is the label. The score runs off
    the reply path; the row goes to the sink. Never raises.
    """
    if not proposed_tool:
        return
    _scope = _scope_now()
    _frame = {
        "goal": (goal or "")[:200],
        # v3: the step's own calls so far (empty on its first call).
        "calls_this_step": (calls_this_step or "")[-300:] or None,
        # v3: 400 -> 300 (and description 200 -> 150, offered 200 -> 150) so
        # the added history fits the 384-id budget with `args` intact.
        "last_result": (last_result or "")[:300] or None,
        "proposed_tool": str(proposed_tool),
        "tool_description": (tool_description or "")[:150] or None,
        # v2: the arguments the Brain is about to execute — the strongest
        # approval signal for tools like run_command — and the names of the
        # tools the Brain was OFFERED (what else was on the menu).
        "args": _fmt_args(args),
        "offered_tools": _fmt_tools(offered_tools),
    }
    _brain = bool(outcome_success)

    def _job() -> None:
        noul = score_tool_approval(_frame, engine=engine)
        emit_row(shadow_row(noul, brain_bool=_brain, scope=_scope))

    try:
        from backend.utils.durability_queue import lane

        if not lane("oracle_shadow").submit(
            f"tool_approval:{proposed_tool}", _job
        ):
            logger.warning("[tool_approval] shadow row dropped (lane full)")
    except Exception as e:  # noqa: BLE001 — a shadow never raises
        logger.warning("[tool_approval] shadow submit failed: %r", e)
