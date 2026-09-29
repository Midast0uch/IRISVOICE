"""Unit tests: off-thread memory lookup (REQ-12 AC12.1/AC12.3, T16).

AC12.1  the DER thread must never call `asyncio.run` — resolution goes via
        `run_coroutine_threadsafe` (or a bounded TTL cache).
AC12.3  a lookup that exceeds its budget returns an empty hint immediately and
        the late result is attached to the NEXT step.
"""

from __future__ import annotations

import asyncio
import ast
import threading
import time
from pathlib import Path

from backend.agent import explorer as ex

_REPO = Path(__file__).resolve().parents[3]


class _FakeRegistry:
    def __init__(self, payload=None, delay=0.0):
        self._payload = payload or {"hit": True, "sources": [{"url": "https://x/y"}]}
        self._delay = delay
        self.calls = 0

    async def resolve(self, goal, quick=True):
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        return dict(self._payload)


def _live_loop():
    """A real running loop in a background thread (stands in for the gateway)."""
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    return loop


def _src(rel: str) -> str:
    return (_REPO / rel).read_text(encoding="utf-8", errors="replace")


def _func_source(src: str, name: str) -> str:
    """Source text of one top-level function, found by AST."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{name} not found")


def _calls_in(src: str, name: str) -> bool:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == name:
                return True
            if isinstance(fn, ast.Name) and fn.id == name:
                return True
    return False


class TestNoAsyncioRunOnDerThread:
    def test_no_asyncio_run_on_der_thread(self, monkeypatch):
        """AC12.1: the memory gate does not start an event loop on the DER
        thread, and the lookup goes through run_coroutine_threadsafe."""
        # (a) source pin, AST-based: a comment mentioning `asyncio.run` must not
        # satisfy or break this — only a real CALL node counts.
        kernel_src = _src("backend/agent/agent_kernel.py")
        gate = _func_source(kernel_src, "_mem_lookup")
        assert not _calls_in(gate, "run"), (
            "`asyncio.run(...)` is back on the DER thread's memory gate"
        )
        assert "source_hint" in gate, (
            "the memory gate no longer goes through the off-thread helper"
        )

        ex_src = _src("backend/agent/explorer.py")
        tree = ast.parse(ex_src)
        runs = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "run"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "_asyncio"
        ]
        assert len(runs) == 1, (
            "expected exactly ONE guarded `_asyncio.run` (the allow_sync "
            f"escape hatch), found {len(runs)}"
        )
        assert _calls_in(ex_src, "run_coroutine_threadsafe"), (
            "source_hint does not use run_coroutine_threadsafe"
        )

        # (b) behaviour: with no loop and allow_sync=False, NOTHING runs.
        reg = _FakeRegistry()
        monkeypatch.setattr(
            "backend.crawler.source_registry.get_source_registry", lambda: reg)
        ex.clear_source_hint_cache()

        assert ex.source_hint("no loop here") == {}
        assert reg.calls == 0, "the coroutine ran on the caller's thread"


class TestOverBudgetLateAttach:
    def test_over_budget_late_attach(self, monkeypatch):
        """AC12.3: over budget → empty hint now, result attached next step."""
        reg = _FakeRegistry(delay=0.30)
        monkeypatch.setattr(
            "backend.crawler.source_registry.get_source_registry", lambda: reg)
        ex.clear_source_hint_cache()
        loop = _live_loop()

        t0 = time.perf_counter()
        first = ex.source_hint("slow goal", loop=loop, miss_budget_s=0.05)
        elapsed = time.perf_counter() - t0

        assert first == {}, "an over-budget lookup must return an empty hint"
        assert elapsed < 0.25, (
            f"the caller blocked for {elapsed:.3f}s — the budget did not hold"
        )
        assert reg.calls == 1, "the lookup was not submitted at all"

        # The lookup keeps running; the NEXT step picks the late result up.
        time.sleep(0.45)
        second = ex.source_hint("slow goal", loop=loop, miss_budget_s=0.05)
        assert second.get("hit") is True
        assert second["sources"][0]["url"] == "https://x/y"
        assert reg.calls == 1, "the late attach re-ran the lookup"

        loop.call_soon_threadsafe(loop.stop)


class TestCacheBoundsTheWork:
    def test_second_call_is_a_cache_hit(self, monkeypatch):
        """A cached goal never re-submits (the TTL cache is the fast half of
        AC12.1)."""
        reg = _FakeRegistry()
        monkeypatch.setattr(
            "backend.crawler.source_registry.get_source_registry", lambda: reg)
        ex.clear_source_hint_cache()
        loop = _live_loop()

        first = ex.source_hint("cached goal", loop=loop)
        assert first.get("hit") is True
        assert reg.calls == 1

        second = ex.source_hint("cached goal", loop=loop)
        assert second == first
        assert reg.calls == 1, "the cache did not absorb the repeat"

        loop.call_soon_threadsafe(loop.stop)
