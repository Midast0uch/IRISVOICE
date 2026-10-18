"""Turn verdict reporting - the OUTSIDE label for held shadow rows.

  POST /api/eval/verdict   {"turn_id": str, "passed": bool}

WHY (oracle.md 7.5, depth_met, 2026-10-17): depth_met's honest label is
whether the TURN was actually right - the eval verdict (hidden tests) for
eval turns, a user correction or a re-ask for live turns. That verdict exists
only outside the backend process, so the depth_met shadow row is HELD at its
consult (backend/agent/turn_verdict_label.py) until this endpoint reports
what actually happened. The endpoint is inert without held rows: a verdict
for an unknown turn is a no-op.

The eval harness (evals/run_evals.py) POSTs here after a task's hidden tests.
A future live-turn source (a user correction) POSTs the same shape.

Cheap and never raises: one bounded map lookup, zero I/O beyond the write of
the held rows themselves.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _tvl_stats_rows_pending() -> int:
    """Best-effort pending count for the MISS log line. Never raises."""
    try:
        from backend.agent import turn_verdict_label as _tvl

        return int(_tvl.stats().get("rows_pending", 0))
    except Exception:  # noqa: BLE001
        return -1


@router.post("/api/eval/verdict")
async def report_eval_verdict(request: Request) -> JSONResponse:
    """Stamp this turn's held shadow rows with the reported verdict."""
    try:
        body: dict[str, Any] = await request.json()
    except Exception:  # noqa: BLE001 — a malformed body is a 400, never a 500
        return JSONResponse({"error": "invalid json"}, status_code=400)
    turn_id = str(body.get("turn_id") or "")
    if not turn_id:
        return JSONResponse({"error": "turn_id required"}, status_code=400)
    passed = body.get("passed")
    if not isinstance(passed, bool):
        return JSONResponse({"error": "passed must be a bool"}, status_code=400)
    labelled = 0
    try:
        from backend.agent import turn_verdict_label as _tvl

        labelled = _tvl.report_verdict(turn_id, passed)
    except Exception as e:  # noqa: BLE001 — a report never 500s
        logger.warning("[eval_verdict] report failed: %r", e)
        return JSONResponse({"error": "report failed"}, status_code=200)
    if labelled:
        logger.info(
            "[Oracle] turn verdict: turn=%s passed=%s labelled=%d",
            turn_id, passed, labelled,
        )
    else:
        # A report that labelled nothing is a JOIN MISS (the harness reported
        # a turn whose rows were never held - a different id space, or the
        # rows were emitted before the hold engaged). Visible, not silent.
        logger.info(
            "[Oracle] turn verdict MISS: turn=%s passed=%s held_rows=%d",
            turn_id, passed,
            _tvl_stats_rows_pending(),
        )
    return JSONResponse({"labelled": labelled})
