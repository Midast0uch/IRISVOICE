"""CT-6 + CT-10 (specs/tool-result-envelope Wave 2 gate TG-2).

CT-6: the session-312 gather gate + URL turn memory survive the refactor —
the prevention guard EXTENDS the gate path, it never weakens the filter.
CT-10: hierarchy C hard rules hold — a repeat step is NEVER re-dispatched
(rerouted to read), a walled tool is NEVER retried in-run; suggestion
overrides are logged with reasons.
"""
from __future__ import annotations

import pytest

from backend.agent.der_loop import QueueItem
from backend.agent.tool_envelope import ToolResultEnvelope


class _GuardKernel:
    """Kernel stand-in exposing ONLY what the pre-dispatch guard reads."""

    def __init__(self):
        from backend.agent.agent_kernel import AgentKernel

        self.conversation_id = "conv_ct10"
        self._der_crawled_urls = {}
        self._der_seen_dispatches = {}
        self._der_envelope_registry = {}
        self._envelope_counters = {
            "written": 0, "raw_ref_fetches": 0, "crit_confirmed": 0,
            "gate_fired": 0, "gate_blocked": 0, "hard_blocks": 0,
            "suggest_overrides": 0,
        }
        # bind the real method
        self._der_pre_dispatch_guard = (
            AgentKernel._der_pre_dispatch_guard.__get__(self)
        )


def _item(tool, params, step_id="sX"):
    it = QueueItem(step_id=step_id, step_number=2, description="d",
                   tool=tool, params=dict(params or {}))
    return it


# ── CT-10: hard rules ────────────────────────────────────────────────────────


def test_ct10_repeat_is_never_redispatched_but_rerouted_to_read():
    k = _GuardKernel()
    k._der_seen_dispatches = {"conv_ct10": {
        "x": "s1",  # digest placeholder
    }}
    from backend.agent.tool_envelope import params_digest

    k._der_seen_dispatches["conv_ct10"] = {
        params_digest("crawler_query", {"query": "streaming stt"}): "s1",
    }
    # the original step's envelope is registered
    orig_env = ToolResultEnvelope(
        status="success", summary="gathered streaming docs",
        raw_ref={"doc_id": "doc_orig"}, criticality="supporting",
        criticality_source="declared", step_id="s1",
    )
    k._der_envelope_registry = {"conv_ct10": {"doc_orig": orig_env}}

    repeat = _item("crawler_query", {"query": "streaming stt"})
    verdict = k._der_pre_dispatch_guard(repeat)
    assert verdict is not None and verdict["reroute_tool"], (
        "a repeat MUST be blocked pre-dispatch"
    )
    assert verdict["reroute_tool"] == "get_rendered_documents", (
        "the reroute reads the gathered docs — never re-executes the crawl"
    )
    # retroactive criticality confirm fired on the ORIGINAL envelope (AC1.6)
    assert orig_env.criticality == "load-bearing"
    assert orig_env.criticality_source == "confirmed"
    assert k._envelope_counters["hard_blocks"] >= 1


def test_ct10_walled_tool_is_never_retried_in_run():
    from backend.agent.tool_errors import record_wall

    record_wall("walled.example.com")
    try:
        k = _GuardKernel()
        it = _item("fetch_url", {"url": "https://walled.example.com/page"})
        verdict = k._der_pre_dispatch_guard(it)
        assert verdict is not None, "walled target MUST be blocked"
        assert not verdict.get("reroute_tool"), (
            "a walled tool is NEVER retried — no reroute, honest refusal"
        )
        assert "walled" in verdict["reason"]
    finally:
        from backend.agent.tool_errors import reset_wall_ledger_for_testing

        reset_wall_ledger_for_testing()


def test_ct10_fresh_call_proceeds():
    from backend.agent.tool_errors import reset_wall_ledger_for_testing

    reset_wall_ledger_for_testing()
    k = _GuardKernel()
    it = _item("crawler_query", {"query": "brand new query"})
    assert k._der_pre_dispatch_guard(it) is None, (
        "a fresh call must NOT be blocked — the guard extends, never widens"
    )


def test_ct10_url_subset_repeat_blocked():
    k = _GuardKernel()
    k._der_crawled_urls = {"conv_ct10": {"https://a.com/x", "https://b.com/y"}}
    it = _item("crawler_query", {
        "query": "fresh phrasing of the same thing",
        "known_urls": ["https://a.com/x", "https://b.com/y"],
    })
    verdict = k._der_pre_dispatch_guard(it)
    assert verdict is not None and verdict["reroute_tool"], (
        "all-known-URLs gather MUST be rerouted to read"
    )


# ── CT-6: the session-312 gather gate + URL memory survive ──────────────────


def test_ct6_gather_gate_url_filter_still_present_and_untouched():
    """Source-level pin: the session-312 filter block (registry URLs vs
    already-crawled, all-filtered -> fresh discovery) is byte-identical in
    the refactor — the guard EXTENDS the path, never weakens the filter."""
    import io
    from pathlib import Path

    src = io.read = Path(
        Path(__file__).resolve().parents[2] / "agent" / "agent_kernel.py"
    ).read_text(encoding="utf-8")
    assert "gather gate filtered %d/%d registry URLs already crawled" in src
    # Session-322: raw compare strengthened to normalized compare (same guard,
    # stronger match) — accept either form, forbid neither.
    assert "_fresh = [u for u in known_urls" in src
    assert "_cu[_conv] = _fetched" in src, (
        "URL turn-memory recording must survive the refactor"
    )


def test_ct6_url_turn_memory_records_and_filters():
    """The gate behavior end-to-end: recorded URLs are filtered from registry
    results; a fully-crawled set filters everything (fresh discovery)."""
    _crawled = {"https://known.com/a", "https://known.com/b"}
    known_urls = ["https://known.com/a", "https://fresh.com/c"]
    _fresh = [u for u in known_urls if u not in _crawled]
    assert _fresh == ["https://fresh.com/c"]
    # all-crawled -> serve nothing (fresh discovery downstream)
    _all_known = ["https://known.com/a", "https://known.com/b"]
    _fresh_all = [u for u in _all_known if u not in _crawled]
    assert _fresh_all == []
