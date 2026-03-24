"""
Resolution Encoder + Coordinate Interpreter stubs
File: IRISVOICE/backend/memory/mycelium/interpreter.py

ResolutionEncoder   — Tier 3 failure + resolution headers
CoordinateInterpreter — stub for later phase
BehavioralPredictor — stub for later phase

Source: specs/agent_loop_design.md
Gate 1 Step 1.9
"""

import json
from typing import Dict, Optional


class ResolutionEncoder:
    """
    Encodes failure+resolution pairs as compact Tier 3 header strings.
    These appear in ContextPackage.tier3_failures.
    Never raises — falls back to minimal string on any error.
    """

    def encode_with_resolution(self, failure: Dict, conn=None) -> str:
        """
        Encode a failure dict as a compact header string.

        Empty dict → valid fallback string (no raise).
        Full dict  → [space:X | outcome:miss | tool:Y | condition:Z | delta:D]
        With resolution → appends '| resolution:R -> hit'
        """
        try:
            space_id   = failure.get("space_id", "unknown")
            tool       = failure.get("tool_name", "unknown")
            condition  = failure.get("condition", "unknown")
            delta      = failure.get("score_delta", -0.05)
            resolution = failure.get("resolution", None)

            if resolution is None and conn is not None:
                resolution = self._find_resolution(failure, conn)

            if resolution:
                return (
                    f"[space:{space_id} | outcome:miss | tool:{tool} | "
                    f"condition:{condition} | delta:{delta:.2f} | "
                    f"resolution:{resolution} -> hit]"
                )
            return (
                f"[space:{space_id} | outcome:miss | tool:{tool} | "
                f"condition:{condition} | delta:{delta:.2f}]"
            )
        except Exception:
            summary = failure.get("task_summary", "unknown failure")
            reason  = failure.get("failure_reason", "")
            return f"[outcome:miss | {summary[:80]} | {reason[:40]}]"

    def _find_resolution(self, failure: Dict, conn) -> Optional[str]:
        """Look up a successful resolution from episode history."""
        try:
            session_id = failure.get("session_id")
            if not session_id:
                return None
            cursor = conn.execute(
                """SELECT tool_sequence FROM episodes
                   WHERE session_id != ? AND outcome_type = 'success'
                   AND task_summary LIKE ? ORDER BY created_at DESC LIMIT 1""",
                (session_id, f"%{failure.get('tool_name', '')}%")
            )
            row = cursor.fetchone()
            if not row:
                return None
            seq = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            if seq and isinstance(seq, list) and len(seq) > 0:
                first = seq[0]
                name = first.get("tool", "") if isinstance(first, dict) else str(first)
                return name[:40] if name else None
            return None
        except Exception:
            return None


class CoordinateInterpreter:
    """Stub — coordinate interpretation pipeline, implemented in later phase."""
    pass


class BehavioralPredictor:
    """Stub — behavioral prediction layer, implemented in later phase."""
    pass
