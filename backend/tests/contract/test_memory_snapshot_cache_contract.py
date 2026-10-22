"""Memory snapshot cache + warm-up - the contract (2026-10-21).

Measured: the first GET /api/memory/snapshot after a backend start took > 300 s (cold hard disk, indexes building, TTS
loading), the next call 1.0 s. The fix has two parts, both pinned here against the temp store of the snapshot contract:
  * the API layer keeps the default snapshot SNAPSHOT_TTL_S, single-flight (concurrent callers share ONE computation, a
    failure is shared and not cached), bounded to SNAPSHOT_CACHE_MAX parameter sets;
  * start_snapshot_warmup() (called by main.py once app.state.ready is set) fills that cache from a daemon thread, defers
    to a running turn, never raises, and is off with IRIS_MEMORY_SNAPSHOT_WARMUP=0.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import pytest

from backend.tests.contract.test_memory_api_contract import env  # noqa: F401  (the fixture snap_env builds on)
from backend.tests.contract.test_memory_snapshot_contract import SNAP, snap_env  # noqa: F401

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture()
def cache(snap_env, monkeypatch):
    """A clean cache, and a counter around the real sq.snapshot (the real computation, only counted and optionally slowed)."""
    api, sq = snap_env.api, snap_env.sq
    api._snap_cache.clear()
    api._snap_flight.clear()
    real = sq.snapshot
    state = {"calls": 0, "delay": 0.0, "fail": None}

    def counted(*a, **kw):
        state["calls"] += 1
        if state["delay"]:
            time.sleep(state["delay"])
        if state["fail"]:
            raise state["fail"]
        return real(*a, **kw)

    monkeypatch.setattr(sq, "snapshot", counted)
    yield type("C", (), {"env": snap_env, "api": api, "state": state})
    api._snap_cache.clear()
    api._snap_flight.clear()


def test_concurrent_requests_share_one_computation(cache):
    cache.state["delay"] = 0.5   # long enough that every caller arrives while the first one computes
    out: list = []
    threads = [threading.Thread(target=lambda: out.append(cache.api.snapshot_cached())) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert cache.state["calls"] == 1, "a concurrent request started a second computation"
    assert len(out) == 4 and all(o is out[0] for o in out)


def test_a_failure_is_shared_by_the_waiters_and_not_cached(cache):
    cache.state["delay"] = 0.3
    cache.state["fail"] = RuntimeError("store hiccup")
    errs: list = []

    def call():
        try:
            cache.api.snapshot_cached()
        except RuntimeError as exc:
            errs.append(exc)

    threads = [threading.Thread(target=call) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert cache.state["calls"] == 1 and len(errs) == 3
    cache.state["fail"], cache.state["delay"] = None, 0.0
    assert cache.api.snapshot_cached()["meta"]["counts"]["events"] == 7   # the failure left nothing behind
    assert cache.state["calls"] == 2


def test_a_result_is_served_within_the_ttl_and_recomputed_after_it(cache, monkeypatch):
    first = cache.api.snapshot_cached()
    assert cache.api.snapshot_cached() is first and cache.state["calls"] == 1
    monkeypatch.setattr(cache.api, "SNAPSHOT_TTL_S", 0.0)   # every kept result is now older than the TTL
    second = cache.api.snapshot_cached()
    assert cache.state["calls"] == 2 and second is not first
    assert second["meta"]["generated"] >= first["meta"]["generated"]   # meta.generated carries the age to the surface


def test_the_endpoint_serves_the_cache(cache):
    a = cache.env.client.get(SNAP).json()
    b = cache.env.client.get(SNAP).json()
    assert cache.state["calls"] == 1 and a["meta"]["generated"] == b["meta"]["generated"]


def test_the_cache_is_bounded_and_keys_use_clamped_parameters(cache):
    cache.api.snapshot_cached(threads=999)
    cache.api.snapshot_cached(threads=cache.env.sq.SNAPSHOT_THREADS_MAX)
    assert cache.state["calls"] == 1, "a clamped value must reuse the entry of the limit"
    for i in range(1, cache.api.SNAPSHOT_CACHE_MAX + 3):
        cache.api.snapshot_cached(events=i)
    assert len(cache.api._snap_cache) <= cache.api.SNAPSHOT_CACHE_MAX


def test_a_changed_store_is_a_new_entry(cache):
    import sqlite3

    cache.api.snapshot_cached()
    con = sqlite3.connect(cache.env.mem)
    con.execute("CREATE INDEX idx_cache_probe ON memory_events(ts, label)")
    con.commit()
    con.close()
    cache.api.snapshot_cached()
    assert cache.state["calls"] == 2


def test_the_warmup_fills_the_cache_so_the_first_request_computes_nothing(cache):
    cache.api._snapshot_warmup(0.0)
    assert cache.state["calls"] == 1
    r = cache.env.client.get(SNAP)
    assert r.status_code == 200 and cache.state["calls"] == 1


def test_a_failing_warmup_is_logged_not_raised(cache, caplog):
    cache.state["fail"] = RuntimeError("disk gone")
    with caplog.at_level(logging.WARNING, logger=cache.api.logger.name):
        cache.api._snapshot_warmup(0.0)   # must return normally
    assert any("warm-up failed" in r.getMessage() and "disk gone" in r.getMessage() for r in caplog.records)
    assert not cache.api._snap_cache and not cache.api._snap_flight


def test_the_warmup_waits_for_a_running_turn(cache, monkeypatch):
    running = iter([True, True, False])
    sleeps: list[float] = []
    monkeypatch.setattr(cache.api, "_turn_running", lambda: next(running))
    monkeypatch.setattr(cache.api.time, "sleep", lambda s: sleeps.append(s))
    cache.api._snapshot_warmup(7.0)
    assert sleeps == [7.0, 2.0, 2.0] and cache.state["calls"] == 1   # delay, then two polls while the turn ran


def test_the_env_flag_turns_the_warmup_off(cache, monkeypatch):
    started: list = []
    monkeypatch.setattr(cache.api, "_snapshot_warmup", lambda delay: started.append(delay))
    monkeypatch.setenv("IRIS_MEMORY_SNAPSHOT_WARMUP", "0")
    assert cache.api.start_snapshot_warmup(0.0) is None and started == []
    monkeypatch.delenv("IRIS_MEMORY_SNAPSHOT_WARMUP")
    t = cache.api.start_snapshot_warmup(0.0)
    assert t is not None and t.daemon
    t.join(10)
    assert started == [0.0]


def test_main_starts_the_warmup_after_the_app_is_ready():
    src = (REPO / "backend" / "main.py").read_text(encoding="utf-8")
    ready, hook = src.index("app.state.ready = True"), src.index("start_snapshot_warmup()")
    assert hook > ready, "the warm-up must start only after startup completed (it must never delay /health)"
