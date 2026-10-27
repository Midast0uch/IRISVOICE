"""Contract: logs/iris.log has a size budget (growth has a budget).

Measured 2026-10-27: logs/iris.log had grown to 5.8 GB. backend/monitor/logs.py held it
with TWO handles (a logging.FileHandler nothing logged to, plus the raw handle log()
writes) and never rotated it; on Windows a rename fails while another handle holds the
file. These pin: one handle, rollover at LOG_ROTATE_BYTES into at most LOG_BACKUPS
backups, and an oversized legacy file set aside (kept), never deleted by a rollover.
The writer is driven for real (a temp log dir); only the budget is made small.
"""
from __future__ import annotations

import logging
from collections import deque

import pytest

import backend.monitor.logs as logs_mod

BUDGET = 4000   # bytes per file in the test; production is LOG_ROTATE_BYTES
BACKUPS = 3


def _manager(tmp_path, monkeypatch):
    monkeypatch.setattr(logs_mod, "LOG_ROTATE_BYTES", BUDGET, raising=False)
    monkeypatch.setattr(logs_mod, "LOG_BACKUPS", BACKUPS, raising=False)
    m = object.__new__(logs_mod.LogManager)   # the real class, without the singleton's fixed repo path
    m._logs = deque(maxlen=100)
    m._log_dir = tmp_path
    m._setup_file_logging()
    return m


def _close(m):
    f = getattr(m, "_log_file", None)
    if f:
        f.close()


def test_iris_log_rolls_over_and_stays_within_its_budget(tmp_path, monkeypatch):
    m = _manager(tmp_path, monkeypatch)
    try:
        for i in range(2000):   # ~170 KB of lines: ~40 budgets' worth
            m.log("INFO", "agent", f"line {i:05d} " + "x" * 60)
    finally:
        _close(m)
    files = sorted(p.name for p in tmp_path.iterdir())
    assert "iris.log" in files
    backups = [f for f in files if f.startswith("iris.log.")]
    assert 1 <= len(backups) <= BACKUPS, files
    line_max = 120
    for f in tmp_path.iterdir():
        assert f.stat().st_size <= BUDGET + line_max, (f.name, f.stat().st_size)
    total = sum(f.stat().st_size for f in tmp_path.iterdir())
    assert total <= (BACKUPS + 1) * (BUDGET + line_max), total
    newest = (tmp_path / "iris.log").read_text(encoding="utf-8").strip().splitlines()[-1]
    assert "line 01999" in newest, "the current file holds the newest line"


def test_iris_log_has_one_handle(tmp_path, monkeypatch):
    m = _manager(tmp_path, monkeypatch)
    try:
        target = str(tmp_path / "iris.log")
        for name in ("IRIS", ""):
            for h in logging.getLogger(name or None).handlers:
                assert getattr(h, "baseFilename", None) != target, "a second handle blocks the rename on Windows"
    finally:
        _close(m)


def test_an_oversized_legacy_log_is_set_aside_not_rotated_away(tmp_path, monkeypatch):
    legacy = tmp_path / "iris.log"
    legacy.write_bytes(b"old\n" * ((BACKUPS + 1) * BUDGET // 4 + 10))
    size = legacy.stat().st_size
    m = _manager(tmp_path, monkeypatch)
    try:
        for i in range(400):
            m.log("INFO", "agent", f"new {i} " + "y" * 60)
    finally:
        _close(m)
    aside = [p for p in tmp_path.iterdir() if p.name.startswith("iris-legacy-")]
    assert len(aside) == 1 and aside[0].stat().st_size == size, "the old file is kept whole"
