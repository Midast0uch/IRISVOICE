#!/usr/bin/env python3
"""Record + replay a vision trajectory (REQ-17 AC3; T22).

T13's standing harness can only "reuse recorded trajectories" once a corpus
exists — and the audit found the vision path had ZERO recorded events. This
recorder closes that gap: it runs a fixture (or replays a live run journal) and
writes a REDACTED, schema-v1 trajectory into `tests/vision_traces/`, which the
harness then replays on every invocation.

Schema mirrors `scripts/validate_websearch_trajectory.py`'s redacted shape:
a versioned envelope + a list of redacted event records. It NEVER commits a
real page's PII or a session cookie: URLs are host-only, text/bytes are
dropped, and only the contract-relevant fields are kept.

Usage:
    python scripts/record_vision_trajectory.py --name fixture_basic
    python scripts/record_vision_trajectory.py --from-journal run.jsonl --name live_1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TRACE_DIR = Path(__file__).resolve().parents[1] / "tests" / "vision_traces"
SCHEMA_VERSION = 1

#: Fields dropped on record (PII / secrets / non-contract payloads).
_REDACT_KEYS = frozenset({"text", "bytes", "html", "value", "url", "reason"})


def _redact_event(event: str, payload: dict) -> dict:
    """Redact one event to its contract-relevant, PII-free shape."""
    out = {"event": event}
    for k, v in payload.items():
        if k in _REDACT_KEYS:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        # Nested structures are not recorded (they can carry page content).
    return out


def record_from_events(name: str, events: list) -> Path:
    """Write a schema-v1 redacted trace and return its path."""
    _TRACE_DIR.mkdir(parents=True, exist_ok=True)
    trace = {
        "schema": SCHEMA_VERSION,
        "kind": "vision_trajectory",
        "name": name,
        "events": events,
    }
    path = _TRACE_DIR / f"{name}.json"
    path.write_text(json.dumps(trace, indent=2), encoding="utf-8")
    return path


def record_from_journal(journal_path: str, name: str) -> Path:
    """Redact a run journal (JSONL) into a trace."""
    events: list = []
    with open(journal_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if obj.get("kind") != "event":
                continue
            ev = obj.get("event", "")
            payload = obj.get("payload", {}) or {}
            events.append(_redact_event(ev, payload))
    return record_from_events(name, events)


def record_fixture(name: str) -> Path:
    """Run the hermetic fixture steps and record the emitted trajectory."""
    import io
    import contextlib

    sys.argv = ["record", "--json"]
    import scripts.validate_vision_browser_e2e as h
    from backend.vision.run_journal import RunJournal
    import tempfile

    jpath = str(Path(tempfile.gettempdir()) / f"iris_vision_trace_{name}.jsonl")
    journal = RunJournal(jpath, "record-run")
    journal.open()
    server, port = h.start_fixture_server()
    try:
        h._run_fixture_steps(port, journal)
        h._run_takeover_steps(journal)
    finally:
        server.shutdown()
        journal.close()
    return record_from_journal(jpath, name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a vision trajectory (T22)")
    parser.add_argument("--name", required=True, help="trace name (file stem)")
    parser.add_argument("--from-journal", default="", help="redact a run journal")
    args = parser.parse_args()

    if args.from_journal:
        path = record_from_journal(args.from_journal, args.name)
    else:
        path = record_fixture(args.name)
    print(f"recorded {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
