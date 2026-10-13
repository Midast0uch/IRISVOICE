"""The d1 identity's fitted curve must resolve through threshold_for on the RAW scale.

Guard for 2026-10-13. Before this change threshold_for returned None for every d1
identity, so ToolDecisionBox logged "no threshold for the active backend" and
recorded threshold 1.01 on every row. This pins that raw_threshold maps the fitted
calibrated bar back onto the raw confidence, and that threshold_for resolves it for
the active decision identity only (never for a refused consumer or a stale cap).
"""
import pytest

from backend.agent import oracle_calibration
from backend.agent.decision_engine import CURRENT_READOUT_MODE, EngineConfig, decision_identity
from backend.agent.oracle_calibration import calibrated, raw_threshold

BACKEND = "m+letters|letters|abc"
KNOTS = [[0.2, 0.5], [0.6, 0.7], [0.9, 0.95]]


def _write(tmp_path, payload, name="oracle_calibration.json"):
    import json

    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    monkeypatch.setattr(oracle_calibration, "_CACHE", {})


def test_raw_threshold_maps_back_onto_the_calibrated_bar(tmp_path):
    p = _write(tmp_path, {BACKEND: {"tool_choice": {"knots": KNOTS, "threshold": 0.79}}})

    r = raw_threshold(BACKEND, "tool_choice", path=p)

    assert r is not None
    assert calibrated(BACKEND, "tool_choice", r, path=p) >= 0.79
    assert calibrated(BACKEND, "tool_choice", r - 0.01, path=p) < 0.79
    assert 0.6 < r < 0.9


def test_raw_threshold_is_none_without_a_fit(tmp_path):
    no_threshold = _write(
        tmp_path, {BACKEND: {"tool_choice": {"knots": KNOTS, "threshold": None}}}, "a.json")
    assert raw_threshold(BACKEND, "tool_choice", path=no_threshold) is None

    absent = _write(tmp_path, {BACKEND: {"tool_choice": {"knots": KNOTS, "threshold": 0.79}}}, "b.json")
    assert raw_threshold(BACKEND, "call_closing", path=absent) is None

    never = _write(
        tmp_path,
        {BACKEND: {"tool_choice": {"knots": [[0.2, 0.3], [0.9, 0.6]], "threshold": 0.79}}},
        "c.json",
    )
    assert raw_threshold(BACKEND, "tool_choice", path=never) is None


def test_threshold_for_resolves_the_fitted_curve_for_the_active_identity(tmp_path, monkeypatch):
    key = decision_identity("m+letters", CURRENT_READOUT_MODE, "tool_choice", 32)
    p = _write(tmp_path, {key: {"tool_choice": {"knots": KNOTS, "threshold": 0.79}}})
    monkeypatch.setattr(oracle_calibration, "CALIBRATION_PATH", p)

    cfg = EngineConfig(backend_id="m+letters", backend_thresholds={},
                       candidate_cap=32, calibrated_cap=32)

    t = cfg.threshold_for("tool_choice")
    assert t is not None
    assert t == raw_threshold(key, "tool_choice")

    assert cfg.threshold_for("call_closing") is None

    stale = EngineConfig(backend_id="m+letters", backend_thresholds={},
                         candidate_cap=12, calibrated_cap=32)
    assert stale.threshold_for("tool_choice") is None
