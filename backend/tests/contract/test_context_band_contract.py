"""The pill's band follows CLM (owner 2026-11-23: "it's more like a rubber band that goes up and down").

Before: the one number sent was the turn's LARGEST call, so inside a turn it could only rise; a node's view that grows, is
set aside and starts small again never reached the pill. Each test FAILS on the code before this change.
"""
from __future__ import annotations

from types import SimpleNamespace

from backend.agent import node_executor as ne
from backend.agent.agent_kernel import AgentKernel
from backend.agent.context_gauge import GAUGE
from backend.agent.event_bus import IRISStreamEvent, get_event_bus
from backend.agent.kernel.context import note_context_view
from backend.agent.kernel.der.node import _live_band


def _kernel():
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id, k.session_id, k._current_turn_id = "conv-band", "sess", "t1"
    k.resolve_context_window = lambda: 260_000
    k.resolve_context_window_with_source = lambda role: SimpleNamespace(tokens=8_000)
    k._router = SimpleNamespace(resolve=lambda role: SimpleNamespace(id="band-prov", model="band-model"))
    return k


class _Wire:
    def __enter__(self):
        self.got = []
        self.cap = lambda p: self.got.append(dict(p.data or {}))
        get_event_bus().subscribe(IRISStreamEvent.CONTEXT_USAGE, self.cap)
        return self.got

    def __exit__(self, *a):
        get_event_bus().unsubscribe(IRISStreamEvent.CONTEXT_USAGE, self.cap)


def _r(tokens, **kw):
    return dict({"tokens": tokens, "limit": 0, "aside": 0, "aside_tokens": 0, "role": "tool_execution"}, **kw)


def test_the_band_rises_falls_and_rests():
    k = _kernel()
    k._accrue_tokens("x", {"total_tokens": 23_000})
    k._accrue_tokens("x", {"total_tokens": 900})
    with _Wire() as got:
        on = _live_band(k, "n1", "t1", 0)
        on(_r(1_000))
        on(_r(5_000, limit=4_000))
        on(_r(2_000, limit=4_000, aside=2, aside_tokens=3_000))
        note_context_view(k, "n1", None)
    assert [d["now_tokens"] for d in got] == [1_000, 5_000, 2_000, 900]          # at rest: the last call, not the largest
    assert [d["now_window"] for d in got] == [8_000, 8_000, 8_000, 260_000]      # a node is measured on its own model
    assert got[2]["peak_tokens"] == 5_000 and got[2]["aside"] == 2 and got[2]["limit_tokens"] == 4_000
    assert got[3]["views"] == 0 and got[3]["aside"] == 0 and got[3]["limit_tokens"] == 0 and got[3]["peak_tokens"] == 23_000
    assert {d["used_tokens"] for d in got} == {23_000} and {d["max_tokens"] for d in got} == {260_000}   # old keys unmoved


def test_side_by_side_nodes_show_the_fullest_and_a_lost_one_leaves_with_its_turn():
    k = _kernel()
    with _Wire() as got:
        _live_band(k, "a", "t1", 0)(_r(3_000, aside=1))
        _live_band(k, "b", "t1", 32_000)(_r(4_000, aside=2))      # more tokens, but a larger window: less full
        _live_band(k, "c", "t2", 0)(_r(500))                      # a later turn: a and b never came back
    assert (got[1]["now_tokens"], got[1]["views"], got[1]["aside"]) == (3_000, 2, 3)
    assert (got[2]["now_tokens"], got[2]["views"]) == (500, 1)
    with _Wire() as got:
        note_context_view(k, "a", None)                           # its late end says nothing
    assert got == []


def test_the_numbers_are_the_servers_tokens_not_the_rulers():
    GAUGE.observe("band-prov", "band-model-2", 1_000, 1_500)
    k = _kernel()
    k._router = SimpleNamespace(resolve=lambda role: SimpleNamespace(id="band-prov", model="band-model-2"))
    with _Wire() as got:
        _live_band(k, "n", "t1", 0)(_r(1_000, limit=2_000, aside=1, aside_tokens=400))
    d = got[0]
    assert (d["now_tokens"], d["limit_tokens"], d["aside_tokens"]) == (1_500, 3_000, 600)


def test_a_node_under_pressure_stretches_past_the_limit_then_lets_go(monkeypatch):
    from backend.tests.behavioral import test_clm_offload_node_behavior as bt

    seen = []
    real = ne.NodeContext
    monkeypatch.setattr(ne, "NodeContext", lambda **kw: real(on_gauge=seen.append, **kw))
    bt._run(with_clm=True)
    i = next(i for i, r in enumerate(seen) if r["tokens"] > r["limit"])
    assert seen[i + 1]["tokens"] <= seen[i + 1]["limit"] and seen[i + 1]["aside"] > seen[i]["aside"]
    assert seen[0]["tokens"] < seen[1]["tokens"]                                  # a read stretches it
    assert seen[-1]["aside_tokens"] > 0

    seen.clear()
    bt._run(with_clm=False)                                                       # hooks off: it still moves, and claims nothing
    assert len(seen) == bt.READS + 1 and all(r["limit"] == 0 and r["aside"] == 0 for r in seen)
    assert seen[-1]["tokens"] > seen[0]["tokens"]


def test_a_broken_observer_never_stops_a_node(monkeypatch):
    from backend.tests.behavioral import test_clm_offload_node_behavior as bt

    real = ne.NodeContext

    def boom(_r):
        raise RuntimeError("pill gone")

    monkeypatch.setattr(ne, "NodeContext", lambda **kw: real(on_gauge=boom, **kw))
    assert bt._run(with_clm=True)[3].success


def test_the_node_ends_its_reading_in_its_finally():
    from backend.tests._kernel_source import kernel_function_source

    src = kernel_function_source("_der_run_node")
    i = src.index("note_context_view(self, _band_key, None)")
    assert "_der_release(self, _c)" in src[i - 200:i] and "_node_ctx.on_gauge = _live_band(" in src
