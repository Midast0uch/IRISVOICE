"""Contract: the tool_approval/v6 PRE-CALL GUARD (oracle.md 7.5, 2026-10-18).

The consumer's live decision: when enforced and confidently answered "no -
this call will fail as written", the call does NOT run; the model gets a
rejection message and re-issues. Refuse-only and bounded: after
_MAX_GUARD_CORRECTIONS rejections the guard stands down for the node, and any
fault means "run the call".

Pins:
  - None (run the call) unless enforced AND above threshold AND answered "no";
  - never raises, whatever it is handed;
  - the node seam exists and is bounded (structural, read from source).
"""
from __future__ import annotations

import inspect

import pytest

from backend.agent import node_executor
from backend.agent import tool_approval_shadow as ta


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    yield


def _enforced(monkeypatch, threshold=0.75, acts=None):
    import backend.agent.decision_engine as de

    monkeypatch.setattr(de, "decides", lambda cid: threshold if cid == "tool_approval" else None)
    if acts is None:
        # the real shape: the calibrated confidence must clear the threshold
        monkeypatch.setattr(de, "oracle_acts", lambda cid, conf: conf >= threshold)
    else:
        monkeypatch.setattr(de, "oracle_acts", lambda cid, conf: acts)


class _Noul:
    def __init__(self, p: float):
        self.probability = p
        self.engine_latency_ms = 5

    def true(self, _cut=0.5):
        return self.probability >= 0.5


# ── the verdict ─────────────────────────────────────────────────────────────

def test_not_enforced_means_run_the_call(monkeypatch):
    import backend.agent.decision_engine as de

    monkeypatch.setattr(de, "decides", lambda cid: None)
    assert ta.pre_call_guard(goal="g", proposed_tool="read_file") is None


def test_a_confident_no_rejects(monkeypatch):
    _enforced(monkeypatch)
    monkeypatch.setattr(ta, "score_tool_approval", lambda frame, engine=None: _Noul(0.05))
    assert ta.pre_call_guard(goal="g", proposed_tool="edit_file") is False


def test_a_yes_runs_the_call(monkeypatch):
    _enforced(monkeypatch)
    monkeypatch.setattr(ta, "score_tool_approval", lambda frame, engine=None: _Noul(0.95))
    assert ta.pre_call_guard(goal="g", proposed_tool="read_file") is None


def test_below_the_threshold_runs_the_call(monkeypatch):
    """A "no" the calibration does not trust (conf 0.60 < the 0.90 bound) must
    NOT reject: the guard acts only above its calibrated threshold."""
    _enforced(monkeypatch)
    # P(true)=0.40 -> chosen "no", confidence in the chosen answer 0.60.
    monkeypatch.setattr(ta, "score_tool_approval", lambda frame, engine=None: _Noul(0.40))
    assert ta.pre_call_guard(goal="g", proposed_tool="edit_file") is None



def test_a_scoring_failure_runs_the_call(monkeypatch):
    _enforced(monkeypatch)

    def _boom(frame, engine=None):
        raise RuntimeError("engine down")

    monkeypatch.setattr(ta, "score_tool_approval", _boom)
    assert ta.pre_call_guard(goal="g", proposed_tool="edit_file") is None


def test_no_engine_runs_the_call(monkeypatch):
    _enforced(monkeypatch)
    monkeypatch.setattr(ta, "_default_engine", lambda: None)
    assert ta.pre_call_guard(goal="g", proposed_tool="read_file") is None


@pytest.mark.parametrize("bad", [None, "", {}])
def test_never_raises_on_bad_input(monkeypatch, bad):
    _enforced(monkeypatch)
    ta.pre_call_guard(goal=bad, proposed_tool=bad, args=bad, offered_tools=bad)


def test_the_frame_never_carries_the_calls_own_result():
    frame = ta._build_frame(goal="g", last_result="prior", proposed_tool="t",
                           args={"a": 1}, offered_tools=["t"])
    assert "result" not in frame and "outcome" not in frame


# ── the node seam (structural) ──────────────────────────────────────────────

def test_the_guard_is_wired_into_run_node_and_bounded():
    src = inspect.getsource(node_executor.run_node)
    assert "pre_call_guard" in src
    assert "_guard_budget" in src
    assert "_MAX_GUARD_CORRECTIONS" in src
    assert node_executor._MAX_GUARD_CORRECTIONS >= 1
    # refuse-only: the rejection path CONTINUES the loop (the call never
    # executes on a rejection); the budget decrement stands the guard down.
    assert "_guard_budget -= 1" in src
