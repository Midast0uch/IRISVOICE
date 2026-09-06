"""Behavioral tests for the websearch memory baseline harness (BT-11, REQ-23 T36).

Drives ``backend/scripts/benchmark_websearch_memory.py`` as a subprocess with
fakes — never live web:

* ``--urls=`` exercises the real ``dispatch_urls`` drive path with zero fetches
  (no network), asserting table + JSON output shape.
* A negative ``IRIS_WEBSEARCH_PEAK_DELTA_MB`` forces the bound-breach path
  deterministically (any peak delta >= 0 breaches), asserting exit 1 + FAIL.
* ``_resident_crawl_workers`` is exercised with monkeypatched fake processes
  (a ``crawl_worker --serve`` cmdline is detected; anything else is not) —
  no real worker is spawned.

The numeric bound itself is NOT asserted here (it stays a live-measurement
artifact per AC23.3/T36); these tests assert harness BEHAVIOR.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HARNESS_PATH = _REPO_ROOT / "backend" / "scripts" / "benchmark_websearch_memory.py"

pytestmark = pytest.mark.timeout(110)


def _run_harness(*argv, env_extra=None):
    env = dict(os.environ)
    env.pop("IRIS_WEBSEARCH_PEAK_DELTA_MB", None)
    env.pop("IRIS_WEBSEARCH_RETURN_DELTA_MB", None)
    env.pop("DRIVER_WEBSEARCH_PEAK_DELTA_MB", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(_HARNESS_PATH), *argv],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=100,
        env=env,
    )


def _load_harness():
    spec = importlib.util.spec_from_file_location("iris_websearch_harness_bt11", _HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_harness_help_exits_zero():
    proc = _run_harness("--help")
    assert proc.returncode == 0
    assert "--assert-websearch" in proc.stdout


def test_harness_sample_only_prints_table():
    proc = _run_harness("--sample-only")
    assert proc.returncode == 0
    assert "Private MB" in proc.stdout


def test_harness_empty_drive_reports_iterations_blob():
    """BT-11: zero-fetch drive exits 0 and emits the machine-readable blob."""
    proc = _run_harness("--urls=", "--settle-s", "0", "--json", "--job-id", "bt11-probe")
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "STANDARD RUN: 0 URLs" in proc.stdout
    assert "driver (self)" in proc.stdout  # attribution row, never invisible
    blob_line = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    assert blob_line, "expected a JSON blob line with --json"
    blob = json.loads(blob_line[-1])
    for key in ("iterations", "iris_peak_delta_mb", "iris_return_delta_mb",
                "driver_peak_delta_mb", "driver_return_delta_mb",
                "resident_workers_before", "resident_workers_after",
                "bounds_mb"):
        assert key in blob, f"blob missing {key}"


def test_harness_breach_path_fails_with_table():
    """BT-11: a breached bound fails (exit 1) with the per-process table (AC23.5)."""
    proc = _run_harness("--urls=", "--settle-s", "0", "--assert-websearch",
                        "--job-id", "bt11-breach",
                        env_extra={"IRIS_WEBSEARCH_PEAK_DELTA_MB": "-1"})
    assert proc.returncode == 1, proc.stdout[-2000:]
    assert "ASSERT -> FAIL" in proc.stdout
    assert "Private MB" in proc.stdout  # dominant contributor is visible


def test_resident_worker_detection_with_fakes(monkeypatch):
    """BT-11: --serve workers are detected; anything else is ignored (AC23.4)."""
    mod = _load_harness()

    class _FakeProc:
        def __init__(self, pid, cmdline):
            self.pid = pid
            self._cmdline = cmdline

        def cmdline(self):
            return self._cmdline

    fake_iter = [
        _FakeProc(111, ["python", "-m", "backend.crawler.crawl_worker", "--serve", "900"]),
        _FakeProc(222, ["python", "start-backend.py"]),
        _FakeProc(333, ["python", "-m", "backend.crawler.crawl_worker", "params.json"]),
    ]

    class _FakePsutil:
        @staticmethod
        def process_iter(attrs=None):
            return list(fake_iter)

    monkeypatch.setitem(sys.modules, "psutil", _FakePsutil)
    assert mod._resident_crawl_workers() == [111]
