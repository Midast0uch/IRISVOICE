"""Session 247: search-loop bounds — the three anti-churn layers.

Live evidence (conv-41, session 247): a websearch task ran 18 dispatch rounds
over 30+ minutes because (a) FAULTLINE was write-only — walled domains were
classified but never skipped, (b) nothing assessed goal-level sufficiency of
accumulated findings before grafting more gather rounds, and (c) no wall-clock
bounded the turn. These tests pin the read side, the gate, and the cutoff.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.agent import tool_errors


# ── Layer 1: the wall ledger (FAULTLINE read-side) ──────────────────────────

@pytest.fixture(autouse=True)
def _clean_ledger():
    tool_errors.reset_wall_ledger_for_testing()
    yield
    tool_errors.reset_wall_ledger_for_testing()


def test_record_then_walled():
    """A recorded wall is visible to is_walled immediately."""
    tool_errors.record_wall("spacedaily.com")
    assert tool_errors.is_walled("spacedaily.com") is True


def test_unknown_domain_not_walled():
    assert tool_errors.is_walled("never-seen.example") is False


def test_domain_normalised():
    """Case/whitespace variants of a domain hit the same ledger entry."""
    tool_errors.record_wall("SpaceDaily.com")
    assert tool_errors.is_walled("  spacedaily.com") is True


def test_empty_domain_never_walled():
    tool_errors.record_wall("")
    assert tool_errors.is_walled("") is False
    assert tool_errors.is_walled(None) is False  # type: ignore[arg-type]


def test_ttl_expiry(monkeypatch):
    """An expired wall record reads as not-walled AND is evicted."""
    tool_errors.record_wall("old-wall.example")
    # Simulate the record aging past the TTL.
    now = __import__("time").monotonic()
    with tool_errors._wall_lock:
        tool_errors._wall_ledger["old-wall.example"] = (
            now - tool_errors._WALL_LEDGER_TTL_S - 1
        )
    assert tool_errors.is_walled("old-wall.example") is False
    with tool_errors._wall_lock:
        assert "old-wall.example" not in tool_errors._wall_ledger  # evicted


# ── Layer 2: the goal-sufficiency gate ──────────────────────────────────────


class _Item:
    def __init__(self, result: str):
        self.result = result


class _Raw:
    def __init__(self, text: str):
        self.raw_text = text


class _GateKernel:
    """Minimal stand-in exposing exactly what _der_findings_sufficient uses."""

    _DER_GATHER_TOOLS = {"crawler_query", "web_search", "search"}
    _smart_excerpt = staticmethod(__import__(
        "backend.agent.agent_kernel", fromlist=["AgentKernel"]
    ).AgentKernel._smart_excerpt)
    _der_findings_sufficient = __import__(
        "backend.agent.agent_kernel", fromlist=["AgentKernel"]
    ).AgentKernel._der_findings_sufficient

    def __init__(self, reply: str = "", raise_exc: bool = False):
        self._reply = reply
        self._raise = raise_exc

    def infer(self, prompt, role=None, max_tokens=0, temperature=0.0):
        if self._raise:
            raise RuntimeError("provider down")
        return _Raw(self._reply)


def test_gate_parses_sufficient_true():
    k = _GateKernel(reply='{"sufficient": true, "missing": ""}')
    suff, missing = k._der_findings_sufficient(
        "summarize space news", [_Item("SpaceX launched X"), _Item("NASA announced Y")]
    )
    assert suff is True
    assert missing == ""


def test_gate_parses_sufficient_false_with_missing():
    k = _GateKernel(reply='{"sufficient": false, "missing": "launch dates"}')
    suff, missing = k._der_findings_sufficient(
        "summarize space news", [_Item("partial content")]
    )
    assert suff is False
    assert missing == "launch dates"


def test_gate_no_items_is_insufficient():
    k = _GateKernel(reply='{"sufficient": true}')
    suff, _ = k._der_findings_sufficient("obj", [])
    assert suff is False


def test_gate_unparseable_reply_falls_open():
    """Garbage reply -> (False, ''): advisory gate never changes semantics."""
    k = _GateKernel(reply="I think so, yes")
    suff, missing = k._der_findings_sufficient("obj", [_Item("content")])
    assert suff is False
    assert missing == ""


def test_gate_inference_failure_falls_open():
    k = _GateKernel(raise_exc=True)
    suff, _ = k._der_findings_sufficient("obj", [_Item("content")])
    assert suff is False


def test_gate_items_without_results_are_insufficient():
    k = _GateKernel(reply='{"sufficient": true}')
    suff, _ = k._der_findings_sufficient("obj", [_Item(""), _Item(None)])  # type: ignore[list-item]
    assert suff is False


# ── Layer 3b: zero-yield cutoff ─────────────────────────────────────────────


class _YieldOrch:
    """Expose the cutoff helpers without constructing the full orchestrator."""

    _record_yield = __import__(
        "backend.crawler.orchestrator", fromlist=["CrawlOrchestrator"]
    ).CrawlOrchestrator._record_yield
    _zero_yield_tripped = __import__(
        "backend.crawler.orchestrator", fromlist=["CrawlOrchestrator"]
    ).CrawlOrchestrator._zero_yield_tripped

    def __init__(self, limit=2, window=600.0):
        self._zero_yield_limit = limit
        self._zero_yield_window_s = window
        self._recent_yields = {}


def test_zero_yield_trips_after_two_empty_jobs():
    o = _YieldOrch()
    o._record_yield("s1", 0)
    assert o._zero_yield_tripped("s1") is False  # one empty job: not yet
    o._record_yield("s1", 0)
    assert o._zero_yield_tripped("s1") is True


def test_zero_yield_reset_by_a_productive_job():
    o = _YieldOrch()
    o._record_yield("s1", 0)
    o._record_yield("s1", 0)
    o._record_yield("s1", 3)  # a real rescue resets the streak
    assert o._zero_yield_tripped("s1") is False


def test_zero_yield_sessions_isolated():
    o = _YieldOrch()
    o._record_yield("s1", 0)
    o._record_yield("s1", 0)
    assert o._zero_yield_tripped("s2") is False


def test_zero_yield_window_ages_out():
    import time as _t

    o = _YieldOrch(window=600.0)
    o._record_yield("s1", 0)
    o._record_yield("s1", 0)
    # Age every record past the window.
    for i, (ts, u) in enumerate(list(o._recent_yields["s1"])):
        o._recent_yields["s1"][i] = (ts - 601.0, u)
    assert o._zero_yield_tripped("s1") is False
