"""
NBL — Neutral Bayesian Logic coordinate state builder.

build_nbl()       — query Mycelium DB → compact ≤40-token string
parse_nbl()       — parse NBL string back to structured dict
as_system_message() — plain system-message wrapper (fallback)
build_mito_tag()  — <MCM_MITO> XML tag per JsonManagement.md spec

The <MCM_MITO> tag is the primary injection format.
Agents treat it as internal biology, not an external tool call.
Target: ≤300 tokens per tag, base template cacheable.
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Any

logger = logging.getLogger(__name__)

_DEFAULT_NBL = "MYCELIUM: context:[0.10,0.00,0.00]@gate1 | confidence:0.10"


def build_nbl(
    conn,
    session_id: str,
    thread_id: Optional[str] = None,
    temporal_coord=None,
) -> str:
    """
    Query the Mycelium DB and build a ≤40-token NBL string.

    Format:
      MYCELIUM: context:[gate_prog,landmark_density,session_depth]@gate<N>
               | toolpath:[t1,t2,t3] | confidence:<float>
    Optional continuation lines:
      TOPOLOGY: <space_label>
      CHAIN: result_counts
      GRADIENT: warning_summary

    Falls back to _DEFAULT_NBL on any DB error.
    """
    if conn is None:
        return _DEFAULT_NBL

    try:
        # ── Gate progress ────────────────────────────────────────────────
        gate_row = conn.execute(
            "SELECT MAX(activation_count) FROM mycelium_nodes WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        activation_max = int(gate_row[0] or 0) if gate_row else 0
        gate_n = max(1, min(5, activation_max // 4 + 1))
        gate_prog = round(min(1.0, activation_max / max(1, gate_n * 4)), 2)

        # ── Landmark density ─────────────────────────────────────────────
        lm_row = conn.execute(
            "SELECT COUNT(*) FROM mycelium_landmarks WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        landmark_count = int(lm_row[0] or 0) if lm_row else 0
        landmark_density = round(min(1.0, landmark_count / 10.0), 2)

        # ── Session depth ────────────────────────────────────────────────
        depth_row = conn.execute(
            "SELECT COUNT(*) FROM mycelium_traversals WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        traversal_count = int(depth_row[0] or 0) if depth_row else 0
        session_depth = round(min(1.0, traversal_count / 20.0), 2)

        # ── Confidence ───────────────────────────────────────────────────
        conf_row = conn.execute(
            "SELECT AVG(confidence) FROM mycelium_nodes WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        confidence = round(float(conf_row[0] or 0.10), 2) if conf_row else 0.10

        # ── Tool path (last 3 tool names from traversals) ────────────────
        tool_rows = conn.execute(
            "SELECT tool_name FROM mycelium_traversals "
            "WHERE session_id = ? ORDER BY created_at DESC LIMIT 3",
            (session_id,),
        ).fetchall()
        tools = [r[0] for r in tool_rows if r[0]] if tool_rows else []
        toolpath = ",".join(tools[:3]) if tools else ""

        # ── Build string ─────────────────────────────────────────────────
        coord = f"[{gate_prog:.2f},{landmark_density:.2f},{session_depth:.2f}]"
        nbl = f"MYCELIUM: context:{coord}@gate{gate_n}"
        if toolpath:
            nbl += f" | toolpath:[{toolpath}]"
        nbl += f" | confidence:{confidence:.2f}"

        # Optional CHAIN line when thread_id is set
        if thread_id:
            try:
                chain_row = conn.execute(
                    "SELECT COUNT(*), SUM(CASE WHEN result='landmark' THEN 1 ELSE 0 END) "
                    "FROM memory_chain WHERE thread_id = ?",
                    (thread_id,),
                ).fetchone()
                if chain_row and chain_row[0]:
                    nbl += f"\nCHAIN: entries:{chain_row[0]} landmarks:{chain_row[1] or 0}"
            except Exception:
                pass

        return nbl

    except Exception as exc:
        logger.debug("[NBL] build failed: %s", exc)
        return _DEFAULT_NBL


def parse_nbl(nbl_str: str) -> dict:
    """
    Parse an NBL string back into a structured dict.
    Returns {} on any failure.
    """
    if not nbl_str or not nbl_str.startswith("MYCELIUM:"):
        return {}

    result: dict[str, Any] = {}
    try:
        # Extract context coordinates
        coord_m = re.search(r"context:\[([0-9.,]+)\]@gate(\d+)", nbl_str)
        if coord_m:
            coords = [float(x) for x in coord_m.group(1).split(",")]
            result["coordinates"] = coords
            result["gate"] = int(coord_m.group(2))

        # Extract confidence
        conf_m = re.search(r"confidence:([\d.]+)", nbl_str)
        if conf_m:
            result["confidence"] = float(conf_m.group(1))

        # Extract toolpath
        tool_m = re.search(r"toolpath:\[([^\]]*)\]", nbl_str)
        if tool_m:
            result["toolpath"] = [t.strip() for t in tool_m.group(1).split(",") if t.strip()]

        # Extract chain info
        chain_m = re.search(r"CHAIN: entries:(\d+) landmarks:(\d+)", nbl_str)
        if chain_m:
            result["chain"] = {
                "entries": int(chain_m.group(1)),
                "landmarks": int(chain_m.group(2)),
            }
    except Exception:
        pass

    return result


def as_system_message(nbl_str: str) -> dict:
    """Wrap NBL string as a plain system message (fallback when MITO not available)."""
    return {"role": "system", "content": f"## Context State\n{nbl_str}"}


def build_mito_tag(
    nbl_str: str,
    task_id: str = "",
    workflow: str = "pre_call",
    collab_mode: str = "normal",
    pin_count: int = 0,
    compress_pct: float = 0.70,
) -> str:
    """
    Build a compact <MCM_MITO> XML tag per JsonManagement.md.

    Target: ≤300 tokens. Base template is cacheable — only dynamic
    parts (task_id, nbl_str, pin_count) change per turn.

    Agents treat this tag as internal biology, not an external tool.
    Insert at messages[1] (right after system prompt).
    """
    version = "0.2"
    compress_pct_int = int(compress_pct * 100)

    # Extract first NBL line only (keep it compact)
    nbl_line = nbl_str.split("\n")[0] if nbl_str else _DEFAULT_NBL

    tag = (
        f"<MCM_MITO>\n"
        f"v{version} | Task:{task_id[:40] or 'active'} | WF:{workflow} | Collab:{collab_mode}\n"
        f"NBL: {nbl_line}\n"
        f"Pins: {pin_count} active | Compress at {compress_pct_int}% budget\n"
        f"Rule: Trust NBL for spatial reasoning | Compress naturally at limit\n"
        f"</MCM_MITO>"
    )
    return tag
