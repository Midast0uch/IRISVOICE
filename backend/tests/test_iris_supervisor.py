"""
Tests for Phase 4.1 — ModelRunnerSupervisor (process isolation + restart).

Uses backend/tests/mock_model_worker.py as a stand-in for the real CUDA
model runner so the restart + protocol logic is verified without a GPU.

Run: python -m pytest backend/tests/test_iris_supervisor.py -v
"""

import os
import sys
import time

import pytest

from backend.iris_supervisor import ModelRunnerSupervisor

_MOCK_WORKER = os.path.join(os.path.dirname(__file__), "mock_model_worker.py")


def _sup(**kw):
    return ModelRunnerSupervisor(
        worker_cmd=[sys.executable, _MOCK_WORKER],
        restart_backoff=0.1,
        poll_interval=0.05,
        **kw,
    )


def test_supervisor_start_reports_running():
    sup = _sup()
    try:
        sup.start()
        h = sup.health()
        assert h["status"] == "running"
        assert isinstance(h["pid"], int)
        assert h["restart_count"] == 0
    finally:
        sup.stop()


def test_worker_protocol_ping_pong():
    sup = _sup()
    try:
        sup.start()
        assert sup.send_json({"type": "ping"}) is True
        resp = sup.read_json_line(timeout=3.0)
        assert resp is not None
        assert resp.get("type") == "pong"
    finally:
        sup.stop()


def test_worker_protocol_health_metric():
    sup = _sup()
    try:
        sup.start()
        sup.send_json({"type": "health"})
        resp = sup.read_json_line(timeout=3.0)
        assert resp is not None
        assert resp.get("type") == "health"
        # memory_metric() returns a dict with an availability flag
        mem = sup.memory_metric()
        assert isinstance(mem, dict)
        assert "available" in mem
    finally:
        sup.stop()


def test_supervisor_restarts_crashed_worker():
    sup = _sup()
    try:
        sup.start()
        assert sup.health()["status"] == "running"
        # Kill the worker outright to simulate a crash.
        sup._proc.kill()
        sup._proc.wait(timeout=5)
        # Manually drive one restart cycle (deterministic, no flaky sleep).
        restarted = sup._restart_if_needed()
        assert restarted is True
        assert sup.health()["restart_count"] == 1
        assert sup.health()["status"] == "running"
        # The new worker still answers the protocol.
        sup.send_json({"type": "ping"})
        resp = sup.read_json_line(timeout=3.0)
        assert resp is not None and resp.get("type") == "pong"
    finally:
        sup.stop()


def test_supervisor_respects_restart_budget():
    sup = _sup(max_restarts=1)
    try:
        sup.start()
        sup._proc.kill()
        sup._proc.wait(timeout=5)
        assert sup._restart_if_needed() is True  # 1st restart
        assert sup._restart_if_needed() is False  # budget exhausted
        assert sup.health()["restart_count"] == 1
    finally:
        sup.stop()
