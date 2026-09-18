"""Unit tests for the run-scoped vision stage timing (REQ-8, REQ-10, T4).

Pure-logic + caplog: the timing helper is OFF the critical path by contract
(REQ-8 AC3 / REQ-10 AC3), so the load-bearing properties are (a) it emits a
structured, parseable line, and (b) it NEVER raises — a logging failure or a
missing run id must never cost a page.
"""

import logging

from backend.vision import stage_timing as st
from backend.vision.stage_timing import StageTimer, record_stage


def test_record_stage_emits_a_parseable_line(caplog):
    with caplog.at_level(logging.INFO, logger="backend.vision.stage_timing"):
        record_stage("run-1", "inference", 42, count=3)
    line = " ".join(r.getMessage() for r in caplog.records)
    assert "run_id=run-1" in line
    assert "stage=inference" in line
    assert "duration_ms=42" in line
    assert "count=3" in line


def test_missing_run_id_falls_back_without_raising(caplog):
    """REQ-8 edge: a missing run id degrades to '-', never raises."""
    with caplog.at_level(logging.INFO, logger="backend.vision.stage_timing"):
        record_stage("", "session", 0)
    assert any("run_id=-" in r.getMessage() for r in caplog.records)


def test_stage_timer_context_manager_records_once(caplog):
    with caplog.at_level(logging.INFO, logger="backend.vision.stage_timing"):
        with StageTimer("run-2", "open") as t:
            t.add(kind="goto")
            ms = t.record()  # explicit record
            assert isinstance(ms, int)
        # __exit__ records again — but only once total.
    lines = [r for r in caplog.records if "stage=open" in r.getMessage()]
    assert len(lines) == 1, f"expected one emit, got {len(lines)}"
    assert "kind=goto" in lines[0].getMessage()


def test_record_stage_never_raises_even_if_logging_is_broken(monkeypatch):
    """REQ-8 AC3: instrumentation must never fail a session. Even a logger
    that raises is swallowed."""
    def _boom(*_a, **_k):
        raise RuntimeError("logger exploded")

    monkeypatch.setattr(st.logger, "info", _boom)
    # Must not raise.
    record_stage("run-3", "action", 5, kind="click")


def test_emission_is_bounded(monkeypatch, caplog):
    """REQ-8 edge: high volume is bounded so a pathological loop cannot flood
    the log. Once the cap is hit, further stages are dropped silently."""
    monkeypatch.setattr(st, "_MAX_STAGE_EVENTS", 3)
    monkeypatch.setattr(st, "_emitted", 0)
    with caplog.at_level(logging.INFO, logger="backend.vision.stage_timing"):
        for i in range(10):
            record_stage("run-4", "cadence", i)
    assert len(caplog.records) == 3
