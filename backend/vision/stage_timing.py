"""Run-scoped per-stage timing + tuning signals for the vision path (REQ-8, REQ-10).

The audit found NO per-stage breakdown anywhere in the vision loop: only a
single end-to-end ``duration_ms`` on ``FetchOutcome`` and a coarse
"browser acquired in Nms (cold pool)" line. Tuning without that breakdown is
guesswork, so this module is the ONE place a stage duration or a tuning
counter is emitted.

Design (specs/vision-browser-e2e-reliability/design.md, Data Models):
  - ``StageTiming(run_id, stage, duration_ms)`` -- one measured stage.

Contract (REQ-8 AC3, REQ-10 AC3): instrumentation is OFF the critical path.
``record_stage`` never raises, never blocks, and never awaits -- a logging
failure (or a missing run id) must never cost a page. REQ-8 AC4 / REQ-10:
the emitted lines are structured (``key=value``) so
``scripts/measure_vision_latency.py`` can parse them into a per-stage report.

REQ-8 edge: a missing run id falls back to the job id (callers pass the job
id as ``run_id`` -- they are the same identifier on this path). REQ-8 AC2 /
REQ-10: counters that reveal waste (model calls per page, redundant
screenshots, frames published vs skipped) ride the same line via ``counters``.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# REQ-8 edge / REQ-10: bounded emission so a pathological loop cannot flood
# the log. Overridable; 0 disables the cap (dev debugging).
_MAX_STAGE_EVENTS = int(os.environ.get("IRIS_VISION_TIMING_MAX_EVENTS", "2000"))
_emitted = 0


@dataclass
class StageTiming:
    """One measured stage of a vision run (REQ-8 AC1).

    ``run_id`` scopes the timing to one run; ``stage`` names the measured
    segment (``acquire``, ``open``, ``screenshot``, ``inference``, ``action``,
    ``publish``, ``session``); ``duration_ms`` is the wall time of the stage.
    """

    run_id: str
    stage: str
    duration_ms: int
    counters: Dict[str, Any] = field(default_factory=dict)


def record_stage(
    run_id: str,
    stage: str,
    duration_ms: int,
    **counters: Any,
) -> None:
    """Emit one stage timing line. Never raises (REQ-8 AC3 / REQ-10 AC3).

    Best-effort by construction: a missing/odd run id degrades to ``"-"``
    (REQ-8 edge), and any logging failure is swallowed -- instrumentation
    must never fail a session.
    """
    global _emitted
    try:
        if _MAX_STAGE_EVENTS and _emitted >= _MAX_STAGE_EVENTS:
            return
        _emitted += 1
        _rid = str(run_id) if run_id else "-"
        _extra = " ".join(f"{k}={v}" for k, v in counters.items()) if counters else ""
        logger.info(
            "[vision-timing] run_id=%s stage=%s duration_ms=%d %s",
            _rid, stage, int(duration_ms), _extra,
        )
    except Exception:  # noqa: BLE001 -- instrumentation is off the critical path
        pass


class StageTimer:
    """Context manager measuring one stage and recording it on exit.

    Usage::

        with StageTimer(run_id, "open"):
            await session.open()

    Never raises from ``__exit__`` -- a timing failure is invisible to the
    caller. Also usable as a plain stopwatch via ``elapsed_ms()`` when the
    caller wants to attach counters only known after the stage (REQ-8 AC2).
    """

    __slots__ = ("_run_id", "_stage", "_t0", "_counters", "_recorded")

    def __init__(self, run_id: str, stage: str, **counters: Any) -> None:
        self._run_id = run_id
        self._stage = stage
        self._counters = dict(counters)
        self._t0 = time.monotonic()
        self._recorded = False

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    def add(self, **counters: Any) -> None:
        self._counters.update(counters)

    def record(self) -> int:
        """Emit the timing once (idempotent). Returns the elapsed ms."""
        ms = self.elapsed_ms()
        if not self._recorded:
            self._recorded = True
            record_stage(self._run_id, self._stage, ms, **self._counters)
        return ms

    def __enter__(self) -> "StageTimer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.record()
        except Exception:  # noqa: BLE001 -- never surface a timing failure
            pass


__all__ = ["StageTiming", "StageTimer", "record_stage"]
