"""Phase 1 (D1.1): Memory-coupled evidence block for the acting prompt.

``assemble_evidence`` builds a ≤300-token, NBL-style context block that is
injected into the Explorer/acting prompt. This is the fix for F1: mid-loop
retrieval now writes into this block instead of the dead ``coordinate_signal``
field.

The block has fixed sections so tests can assert presence deterministically:
    PREDICTED NEXT : BehavioralPredictor top-3
    PROVEN PATH    : top tool_sequences from episodic store for the goal
    AVOID          : high-signal failure tool/condition pairs
    CONTRACTS      : active conduct/style constraints from working memory
    WORKING MEM    : last ≤3 working-memory facts
    (u,xi)         : live Caducean state summary

All accessors reuse the SAME objects the existing recall_decoder / live_context
use (``myc._store._conn``, ``myc._registry.get_active``), so no new DB plumbing
is introduced. The function NEVER raises — on any error it returns a minimal
block so planning/acting always proceeds.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _safe_state_summary(session_id: str) -> str:
    """Return a compact (u,xi) summary from the live Caducean engine."""
    try:
        from backend.gateway.iris_ffi import ffi_caducean_get_state

        st = ffi_caducean_get_state(session_id) or {}
        if not st:
            return "n/a"
        u = st.get("u")
        xi = st.get("xi")
        x = st.get("x")
        y = st.get("y")
        parts = []
        if u is not None:
            parts.append(f"u={u:.2f}")
        if xi is not None:
            parts.append(f"xi={xi:.2f}")
        if x is not None:
            parts.append(f"x={x:.2f}")
        if y is not None:
            parts.append(f"y={y:.2f}")
        return ", ".join(parts) if parts else "n/a"
    except Exception as _e:  # pragma: no cover - defensive
        logger.debug("[evidence] state summary failed: %s", _e)
        return "n/a"


def _predicted_next(
    myc: Any,
    session_id: str,
    task_class: str,
    completed_tools: List[str],
) -> List[str]:
    """Top-3 predicted next tools via BehavioralPredictor (tier2)."""
    try:
        from backend.memory.mycelium.interpreter import BehavioralPredictor

        current_node_ids = list(myc._registry.get_active(session_id))
        predictor = BehavioralPredictor(myc)
        preds = predictor.predict(
            session_id,
            current_node_ids,
            task_class,
            completed_tools,
            conn=getattr(myc._store, "_conn", None),
        )
        return [p for p in (preds or []) if p][:3]
    except Exception as _e:  # pragma: no cover - defensive
        logger.debug("[evidence] predicted_next failed: %s", _e)
        return []


def _proven_path(myc: Any, goal: str, limit: int = 3) -> List[str]:
    """Top tool_sequences from episodic store (proven approaches)."""
    try:
        conn = getattr(myc._store, "_conn", None)
        if conn is None:
            return []
        cur = conn.execute(
            """
            SELECT tool_sequence FROM episodes
            WHERE outcome_type IN ('hit','partial') AND tool_sequence IS NOT NULL
            ORDER BY outcome_score DESC LIMIT ?
            """,
            (limit * 3,),
        )
        seen: List[str] = []
        for (raw,) in cur.fetchall():
            if not raw:
                continue
            try:
                seq = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                seq = []
            if isinstance(seq, list) and seq:
                path = " → ".join(
                    s.get("tool", "?") if isinstance(s, dict) else str(s)
                    for s in seq[:5]
                )
                if path and path not in seen:
                    seen.append(path)
            if len(seen) >= limit:
                break
        return seen
    except Exception as _e:  # pragma: no cover - defensive
        logger.debug("[evidence] proven_path failed: %s", _e)
        return []


def _avoid_list(myc: Any, limit: int = 3) -> List[str]:
    """High-signal failure tool/condition pairs (AVOID section).

    REQ-1 AC4 fix: this previously selected ``result`` and ordered by
    ``score`` — neither column exists on the real ``episodes`` table
    (episodic.py's schema has ``full_content`` and ``outcome_score``), so
    the query raised ``sqlite3.OperationalError`` on every call, silently
    caught below, and this section always rendered "n/a" in production.
    Fixed to the real column names so a FAILED step's per-step episode
    write (AgentKernel._der_score_step_outcome) actually surfaces here.
    """
    try:
        conn = getattr(myc._store, "_conn", None)
        if conn is None:
            return []
        cur = conn.execute(
            """
            SELECT tool_sequence, full_content FROM episodes
            WHERE outcome_type = 'miss' AND tool_sequence IS NOT NULL
            ORDER BY outcome_score DESC LIMIT ?
            """,
            (limit * 2,),
        )
        out: List[str] = []
        for raw, result in cur.fetchall():
            try:
                seq = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                seq = []
            tool = seq[0].get("tool", "?") if isinstance(seq, list) and seq else "?"
            cond = (str(result)[:60] if result else "unknown failure").replace("\n", " ")
            entry = f"{tool}: {cond}"
            if entry not in out:
                out.append(entry)
            if len(out) >= limit:
                break
        return out
    except Exception as _e:  # pragma: no cover - defensive
        logger.debug("[evidence] avoid_list failed: %s", _e)
        return []


def _contracts(memory_interface: Any, session_id: str) -> str:
    """Active conduct/style constraints from working memory."""
    try:
        if memory_interface is None:
            return "None"
        ctx = memory_interface.get_assembled_context(session_id) or ""
        # Pull only the conduct/style lines if present; else summarize.
        lines = [
            ln.strip()
            for ln in ctx.splitlines()
            if ln.strip().lower().startswith(("conduct", "style", "contract"))
        ]
        return "; ".join(lines[:3]) if lines else "None"
    except Exception as _e:  # pragma: no cover - defensive
        logger.debug("[evidence] contracts failed: %s", _e)
        return "None"


def _working_mem(memory_interface: Any, session_id: str, limit: int = 3) -> List[str]:
    """Last ≤3 working-memory facts."""
    try:
        if memory_interface is None:
            return []
        ctx = memory_interface.get_assembled_context(session_id) or ""
        facts = [ln.strip() for ln in ctx.splitlines() if ln.strip()]
        return facts[-limit:]
    except Exception as _e:  # pragma: no cover - defensive
        logger.debug("[evidence] working_mem failed: %s", _e)
        return []


def assemble_evidence(
    goal: str,
    session_id: str,
    myc: Any,
    completed_tools: Optional[List[str]] = None,
    task_class: str = "full",
    memory_interface: Any = None,
) -> str:
    """Assemble the ≤300-token evidence block for the acting prompt.

    Args:
        goal:             Current step goal / description.
        session_id:       Active session id.
        myc:              MyceliumInterface (self._memory_interface._mycelium).
        completed_tools:  Tools already used this session (for prediction context).
        task_class:       Task class ("full" | "research" | "voice_first" | ...).
        memory_interface: AgentKernel memory interface (for contracts/working mem).

    Returns:
        A fenced markdown block. Never raises.
    """
    completed_tools = completed_tools or []
    try:
        predicted = _predicted_next(myc, session_id, task_class, completed_tools)
        proven = _proven_path(myc, goal)
        avoid = _avoid_list(myc)
        contracts = _contracts(memory_interface, session_id)
        wm = _working_mem(memory_interface, session_id)
        state = _safe_state_summary(session_id)

        lines: List[str] = ["```evidence"]
        lines.append("PREDICTED NEXT : " + (", ".join(predicted) if predicted else "n/a"))
        lines.append("PROVEN PATH    : " + (". ".join(proven) if proven else "n/a"))
        lines.append("AVOID          : " + (". ".join(avoid) if avoid else "n/a"))
        lines.append("CONTRACTS      : " + contracts)
        lines.append(
            "WORKING MEM    : " + (" | ".join(wm) if wm else "n/a")
        )
        lines.append(f"(u,xi)         : {state}")
        lines.append("```")
        return "\n".join(lines)
    except Exception as _e:  # pragma: no cover - ultimate defensive
        logger.warning("[evidence] assemble_evidence failed: %s", _e)
        return "```evidence\nPREDICTED NEXT : n/a\nPROVEN PATH    : n/a\nAVOID          : n/a\nCONTRACTS      : None\nWORKING MEM    : n/a\n(u,xi)         : n/a\n```"
