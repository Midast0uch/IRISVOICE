"""Unit tests for scripts/calibrate_decision_threshold.py (REQ-6)."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "scripts" / "calibrate_decision_threshold.py"


def _load_mod():
    spec = importlib.util.spec_from_file_location("calibrate_de", SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_db(path: Path, rows: list[tuple[str, str, dict]]):
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE system_events (event_id TEXT, session_id TEXT,"
        " event_domain TEXT, event_type TEXT, actor TEXT, outcome TEXT,"
        " sanitization_state TEXT, summary TEXT, interaction_payload TEXT,"
        " created_at TEXT DEFAULT '2026-09-20')"
    )
    for outcome, tool, decision in rows:
        payload = {"tool": tool}
        if decision is not None:
            payload["decision"] = decision
        c.execute(
            "INSERT INTO system_events VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("e", "s1", "SYSTEM", "tool_execution", "agent_tool_bridge",
             outcome, None, "", json.dumps(payload), "2026-09-20"),
        )
    c.commit()
    c.close()


def _row(route="engine", conf=0.9, latency=12, escalated=False):
    return {
        "engine": "m350", "consumer_id": "tool_choice", "route": route,
        "chosen": "read_file", "confidence": conf, "escalated": escalated,
        "retried": False, "engine_latency_ms": latency,
        "decision_latency_ms": latency,
    }


class TestCalibrate:
    def test_refuses_under_50(self, tmp_path):
        db = tmp_path / "m.db"
        _make_db(db, [("success", "read_file", _row()) for _ in range(10)])
        mod = _load_mod()
        rows = mod._load_decisions(str(db))
        assert len(rows) == 10
        t, n = mod.recommend_threshold(rows)
        assert t is None and n == 10

    def test_recommends_threshold_and_metrics(self, tmp_path):
        db = tmp_path / "m.db"
        rows = (
            [("success", "read_file", _row(conf=0.9)) for _ in range(50)]
            + [("failure", "read_file", _row(conf=0.55)) for _ in range(6)]
            + [("success", "read_file", _row(route="escalated",
                                             escalated=True, conf=0.4))
               for _ in range(4)]
        )
        _make_db(db, rows)
        mod = _load_mod()
        data = mod._load_decisions(str(db))
        assert len(data) == 60
        lats = [r["latency_ms"] for r in data]
        assert mod._pct(lats, 0.5) == 12
        t, n = mod.recommend_threshold(data)
        assert n == 60
        # failures cluster at conf 0.55; the recommender picks the LOWEST
        # threshold meeting the target so the auto-executed fraction is
        # maximal: t = 0.56 keeps the 50 good rows, excludes the 6 bad ones.
        assert t == 0.56
        buckets = mod._buckets(data)
        assert buckets["0.50-0.60"] == (6, 0.0)
        assert buckets["0.90-0.95"] == (50, 1.0)

    def test_groups_by_model_and_consumer(self, tmp_path):
        db = tmp_path / "m.db"
        a = dict(_row(), consumer_id="presentation", engine="m350")
        b = dict(_row(), engine="m900")
        _make_db(db, [("success", "t", a), ("success", "t", b), ("success", "t", None)])
        mod = _load_mod()
        rows = mod._load_decisions(str(db))
        keys = {(r["consumer_id"], r["engine"]) for r in rows}
        assert ("presentation", "m350") in keys
        assert ("tool_choice", "m900") in keys
        assert len(rows) == 2  # rows without a decision block are skipped

    def test_missing_db_unverified(self, tmp_path):
        mod = _load_mod()
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            import sys as _s
            old = _s.argv
            _s.argv = ["x", "--db", str(tmp_path / "none.db")]
            try:
                rc = mod.main()
            finally:
                _s.argv = old
        assert rc == 4 and "UNVERIFIED" in buf.getvalue()
