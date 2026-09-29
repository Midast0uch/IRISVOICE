"""Behavioral test: the memory pre-filter's latency budget (REQ-12 AC12.2, T16).

AC12.2  cache hit ≤ 20ms p50, miss ≤ 100ms p50 — engine start is never blocked
        beyond that budget.

Measured with a REAL loop in a background thread and a stubbed registry, so
the numbers are the seam's own cost, not the registry's.
"""

from __future__ import annotations

import asyncio
import statistics
import threading
import time

from backend.agent import explorer as ex


class _FakeRegistry:
    def __init__(self, delay=0.0):
        self._delay = delay
        self.calls = 0

    async def resolve(self, goal, quick=True):
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        return {"hit": True, "sources": [{"url": f"https://x/{goal}"}]}


def _live_loop():
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    return loop


def _p50(samples):
    return statistics.median(samples) * 1000.0


class TestPrefilterLatencyBudget:
    def test_prefilter_latency_budget(self, monkeypatch):
        """AC12.2: a cache hit is ~0ms and a fast miss stays under 100ms."""
        reg = _FakeRegistry(delay=0.0)
        monkeypatch.setattr(
            "backend.crawler.source_registry.get_source_registry", lambda: reg)
        ex.clear_source_hint_cache()
        loop = _live_loop()

        # ── misses (first sight of each goal) ──
        miss = []
        for i in range(12):
            t0 = time.perf_counter()
            out = ex.source_hint(f"goal {i}", loop=loop, miss_budget_s=0.10)
            miss.append(time.perf_counter() - t0)
            assert out.get("hit") is True, f"goal {i} produced no hint"

        # ── hits (the same goals again) ──
        hit = []
        for i in range(12):
            t0 = time.perf_counter()
            out = ex.source_hint(f"goal {i}", loop=loop, miss_budget_s=0.10)
            hit.append(time.perf_counter() - t0)
            assert out.get("hit") is True

        assert reg.calls == 12, (
            f"expected exactly one lookup per distinct goal, got {reg.calls}"
        )
        assert _p50(hit) <= 20.0, f"cache-hit p50 {_p50(hit):.2f}ms > 20ms"
        assert _p50(miss) <= 100.0, f"miss p50 {_p50(miss):.2f}ms > 100ms"

        loop.call_soon_threadsafe(loop.stop)

    def test_a_slow_registry_never_exceeds_the_budget(self, monkeypatch):
        """AC12.2/AC12.3: even a registry that takes 10x the budget cannot
        block the caller past it."""
        reg = _FakeRegistry(delay=1.0)
        monkeypatch.setattr(
            "backend.crawler.source_registry.get_source_registry", lambda: reg)
        ex.clear_source_hint_cache()
        loop = _live_loop()

        t0 = time.perf_counter()
        out = ex.source_hint("very slow goal", loop=loop, miss_budget_s=0.10)
        elapsed = time.perf_counter() - t0

        assert out == {}
        assert elapsed < 0.35, (
            f"the budget was not honoured: caller blocked {elapsed:.3f}s"
        )

        loop.call_soon_threadsafe(loop.stop)
