"""Behavioral test: bounded waits on every engine entry point (REQ-26, BT-DEI-17).

AC26.1  every entry point acquires its lock with a bounded timeout.
AC26.4  an overrun returns the degraded result — the legacy path decides.
"""

from __future__ import annotations

import threading

import pytest

from backend.agent.decision_engine import (
    DecisionEngine,
    EngineConfig,
)
from backend.tests.unit.test_decision_engine import FakeOnnxBackend


def _held_engine(timeout_s: float):
    e = DecisionEngine(
        config=EngineConfig(acquire_timeout_s=timeout_s),
        backend_factory=lambda **kw: FakeOnnxBackend(**kw),
    )
    e._backend = FakeOnnxBackend()
    e._load_attempted = True
    return e


class TestAllEntryPointsBounded:
    def test_all_entry_points_bounded(self):
        """AC26.1 / BT-DEI-17: BOTH entry points (decide, generate_args)
        acquire with a bounded timeout — neither blocks indefinitely. The
        lifecycle shutdown() may use a bare acquire (it is not an entry
        point on the decision hot path)."""
        import ast
        import inspect

        src = inspect.getsource(DecisionEngine)
        # Both entry points use acquire(timeout=...).
        assert src.count("acquire(timeout=self._cfg.acquire_timeout_s)") >= 2, (
            "every engine entry point must acquire with a bounded timeout"
        )
        # No bare `with self._lock:` inside the decide/generate_args bodies.
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in (
                "decide", "generate_args"
            ):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.With) and isinstance(
                        sub.items[0].context_expr, ast.Name
                    ) and sub.items[0].context_expr.id == "self._lock":
                        raise AssertionError(
                            f"{node.name} uses a bare lock acquire (REQ-26)"
                        )

    def test_decide_overrun_bounded(self):
        """AC26.1: a held lock cannot block decide past its budget."""
        e = _held_engine(0.05)

        def hold():
            with e._lock:
                threading.Event().wait(0.2)

        t = threading.Thread(target=hold)
        t.start()
        try:
            started = threading.Event()
            result = {}

            def call():
                result["ds"] = e.decide("tool_choice", ["a", "b"], {"goal": "g"})
                started.set()

            w = threading.Thread(target=call)
            w.start()
            assert started.wait(2.0), "decide blocked past its budget"
            assert result["ds"] is None
            assert e.counters.lock_timeouts == 1
        finally:
            t.join()
            w.join()

    def test_overrun_returns_none_legacy_path(self):
        """AC26.4 / BT-DEI-17: an overrun returns the degraded result (None /
        ArgsResult(None)) — the caller takes its legacy path, never retries
        in a loop."""
        e = _held_engine(0.05)

        def hold():
            with e._lock:
                threading.Event().wait(0.2)

        t = threading.Thread(target=hold)
        t.start()
        try:
            r = {}
            w1 = threading.Thread(
                target=lambda: r.update(
                    ds=e.decide("tool_choice", ["a"], {"goal": "g"})))
            w2 = threading.Thread(
                target=lambda: r.update(
                    ar=e.generate_args("tool_choice", "x", {}, {"goal": "g"})))
            w1.start()
            w2.start()
            w1.join(2.0)
            w2.join(2.0)
            assert r.get("ds") is None, "decide must degrade on overrun"
            assert r.get("ar") is not None and r["ar"].args is None, (
                "generate_args must degrade on overrun"
            )
        finally:
            t.join()
