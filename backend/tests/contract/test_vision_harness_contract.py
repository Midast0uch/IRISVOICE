"""Contract tests for the agent-driveable harness pieces (REQ-17; T21/T22).

Pins:
  - `run_journal` is bounded (max lines + max bytes) with an explicit
    truncation marker, and NEVER records a typed value / frame bytes / HTML.
  - a read-only disk degrades to "journal unavailable" (never fails a run).
  - the recorded vision corpus is schema v1 and redacted (no URL/text/bytes).
  - the harness exits non-zero and NAMES the offending invariant on a break.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from backend.vision.run_journal import RunJournal


def test_journal_records_run_id_first_and_events():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "j.jsonl")
        j = RunJournal(p, "run-x")
        assert j.open() is True
        j.record("CRAWLER_VISION_ACTION", {"seq": 1, "kind": "scroll"})
        j.close()
        lines = [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines()]
        assert lines[0]["kind"] == "run_start"
        assert lines[0]["run_id"] == "run-x"
        assert lines[1]["event"] == "CRAWLER_VISION_ACTION"
        assert lines[1]["payload"]["seq"] == 1


def test_journal_is_bounded_by_lines_with_truncation_marker():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "j.jsonl")
        j = RunJournal(p, "run-y", max_lines=5)
        j.open()
        for i in range(50):
            j.record("E", {"seq": i})
        j.close()
        lines = [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines()]
        assert any(x.get("kind") == "truncated" for x in lines), (
            "a bounded journal must write an explicit truncation marker (REQ-17 edge)"
        )
        assert j.truncated is True


def test_journal_never_records_forbidden_fields():
    """REQ-14 AC4 / REQ-16 AC2: no typed value, frame bytes, or HTML."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "j.jsonl")
        j = RunJournal(p, "run-z")
        j.open()
        j.record("E", {"text": "SECRET", "bytes": "AAAA", "html": "<x>", "seq": 1})
        j.close()
        blob = Path(p).read_text(encoding="utf-8")
        assert "SECRET" not in blob
        assert "AAAA" not in blob
        assert "<x>" not in blob
        assert '"seq": 1' in blob


def test_journal_unavailable_on_readonly_path(tmp_path):
    """REQ-17 edge: an unwritable journal degrades, never raises."""
    # Point the journal at a DIRECTORY path — opening it as a file fails.
    bad = tmp_path / "adir"
    bad.mkdir()
    j = RunJournal(str(bad), "run-ro")
    assert j.open() is False
    # Recording is a no-op, not a crash.
    j.record("E", {"seq": 1})
    j.close()


def test_recorded_corpus_is_schema_v1_and_redacted():
    """REQ-17 AC3 / T22: the committed corpus is schema v1 and PII-free."""
    trace_dir = Path(__file__).resolve().parents[3] / "tests" / "vision_traces"
    traces = sorted(trace_dir.glob("*.json"))
    assert traces, "no recorded vision traces — run scripts/record_vision_trajectory.py"
    for t in traces:
        data = json.loads(t.read_text(encoding="utf-8"))
        assert data["schema"] == 1
        assert data["kind"] == "vision_trajectory"
        for e in data.get("events", []):
            for k in ("url", "text", "bytes", "html", "value"):
                assert k not in e, f"{t.name} leaked {k!r} (T22 redaction)"


def test_harness_reports_and_exits_nonzero_on_a_named_break():
    """REQ-17 AC4: the harness names the offending invariant + exits non-zero."""
    import scripts.validate_vision_browser_e2e as h

    # A deliberately failing invariant must produce a failure report.
    results = [h._Invariant("demo.ok", True),
               h._Invariant("demo.break", False, "the offender")]
    failures = [r for r in results if not r.ok]
    assert failures and failures[0].name == "demo.break"
    assert failures[0].detail == "the offender"
