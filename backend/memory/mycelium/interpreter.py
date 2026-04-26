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
from typing import Dict, List, Optional


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
    """
    Resolves conflicts when two coordinate nodes make opposing claims
    about the same axis. Stores resolution basis in mycelium_conflicts table.

    Resolution strategy (priority order):
    1. Prefer the node with higher confidence
    2. If equal confidence, prefer the more recently accessed node
    3. If same recency, prefer the node on the pheromone-strongest edge
       (highest hit_count on any edge touching that node)

    Never raises — falls back to 0.5 (neutral) on any error.
    """

    def resolve(
        self,
        space_id: str,
        axis: str,
        node_a: str,
        node_b: str,
        conn=None,
    ) -> float:
        """
        Returns the resolved coordinate value for the given axis conflict.

        Args:
            space_id:  Mycelium space identifier
            axis:      The axis (dimension name) in conflict
            node_a:    First node_id
            node_b:    Second node_id
            conn:      SQLite connection (optional — returns 0.5 if None)

        Returns:
            float — resolved coordinate value
        """
        try:
            if conn is None:
                return 0.5

            cursor = conn.execute(
                "SELECT node_id, confidence, last_accessed, coordinates "
                "FROM mycelium_nodes WHERE node_id IN (?, ?)",
                (node_a, node_b),
            )
            rows = {row[0]: row for row in cursor.fetchall()}

            if not rows:
                return 0.5

            def _node_coord(node_id: str) -> float:
                try:
                    row = rows.get(node_id)
                    if row is None:
                        return 0.5
                    coords = row[3]
                    if isinstance(coords, (bytes, bytearray)):
                        coords = json.loads(coords.decode("utf-8"))
                    elif isinstance(coords, str):
                        coords = json.loads(coords)
                    if isinstance(coords, dict):
                        return float(coords.get(axis, 0.5))
                    if isinstance(coords, list) and coords:
                        return float(coords[0])
                    return 0.5
                except Exception:
                    return 0.5

            val_a = _node_coord(node_a)
            val_b = _node_coord(node_b)

            conf_a = float((rows.get(node_a) or (None, 0.5))[1] or 0.5)
            conf_b = float((rows.get(node_b) or (None, 0.5))[1] or 0.5)
            resolution_basis = "confidence"

            if abs(conf_a - conf_b) > 0.05:
                resolved = val_a if conf_a >= conf_b else val_b
            else:
                acc_a = float((rows.get(node_a) or (None, 0.5, 0.0))[2] or 0.0)
                acc_b = float((rows.get(node_b) or (None, 0.5, 0.0))[2] or 0.0)
                resolution_basis = "recency"

                if abs(acc_a - acc_b) > 1.0:
                    resolved = val_a if acc_a >= acc_b else val_b
                else:
                    cursor2 = conn.execute(
                        "SELECT from_node_id, SUM(hit_count) as total_hits "
                        "FROM mycelium_edges WHERE from_node_id IN (?, ?) "
                        "GROUP BY from_node_id ORDER BY total_hits DESC LIMIT 1",
                        (node_a, node_b),
                    )
                    best = cursor2.fetchone()
                    resolution_basis = "pheromone"
                    if best and best[0] == node_a:
                        resolved = val_a
                    elif best and best[0] == node_b:
                        resolved = val_b
                    else:
                        resolved = (val_a + val_b) / 2.0
                        resolution_basis = "average"

            try:
                import uuid as _uuid
                import time as _time
                conn.execute(
                    "INSERT OR IGNORE INTO mycelium_conflicts "
                    "(conflict_id, space_id, axis, value_a, source_a, "
                    " value_b, source_b, resolved_value, resolution_basis, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(_uuid.uuid4()), space_id, axis,
                        val_a, node_a, val_b, node_b,
                        resolved, resolution_basis, _time.time(),
                    ),
                )
            except Exception:
                pass

            return resolved

        except Exception:
            return 0.5


class BehavioralPredictor:
    """
    Given current coordinate position + task class, predicts the 3 most
    likely next tool/action names based on pheromone edge weights.

    Feeds into ContextPackage.tier2_predictions.

    Prediction is based on pheromone graph edges: outgoing edges from current
    nodes ranked by (hit_count / traversal_count) * target_node_confidence.
    Tools already used in the current session are excluded.

    Never raises — returns [] on any error.
    """

    def predict(
        self,
        session_id: str,
        current_node_ids: List[str],
        task_class: str,
        completed_tools: List[str],
        conn=None,
    ) -> List[str]:
        """
        Returns top-3 predicted next tool/action names.

        Args:
            session_id:       Current session (unused in query, reserved)
            current_node_ids: Active node IDs in this session
            task_class:       Task class label (reserved for future weighting)
            completed_tools:  Tools already used this session (excluded)
            conn:             SQLite connection (returns [] if None)

        Returns:
            List of up to 3 predicted tool names (empty if no data)
        """
        try:
            if conn is None or not current_node_ids:
                return []

            placeholders = ",".join("?" for _ in current_node_ids)
            cursor = conn.execute(
                f"SELECT e.to_node_id, e.hit_count, e.traversal_count, "
                f"       n.label, n.confidence "
                f"FROM mycelium_edges e "
                f"JOIN mycelium_nodes n ON n.node_id = e.to_node_id "
                f"WHERE e.from_node_id IN ({placeholders}) "
                f"  AND e.hit_count > 0 "
                f"ORDER BY (CAST(e.hit_count AS REAL) / MAX(e.traversal_count, 1)) "
                f"         * n.confidence DESC "
                f"LIMIT 10",
                current_node_ids,
            )

            completed_set = set(completed_tools or [])
            candidates: List[str] = []
            seen: set = set()

            for row in cursor.fetchall():
                label = row[3] or ""
                if not label:
                    continue
                name = label.split(":")[-1].strip()
                if name and name not in completed_set and name not in seen:
                    candidates.append(name)
                    seen.add(name)
                if len(candidates) >= 3:
                    break

            return candidates[:3]

        except Exception:
            return []
