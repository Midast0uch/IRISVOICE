"""Contract: concurrent config saves never fail or leave temp files.

2026-10-02: the dashboard fired ~36 /api/config/save at once on load, and the
WS confirm_card path saves from a worker thread. save_config wrote one shared
".json.tmp" and renamed it with no lock; on Windows two renames onto the same
target fail with "Access is denied". 8 threads x 20 saves: 52 failed writes,
leftover temp files. Writers now take turns, each with its own temp file.
"""
from __future__ import annotations

import json
import logging
import threading

import backend.iris_config as ic


def test_parallel_saves_all_land_and_leave_no_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(ic, "_IRIS_CONFIG_PATH", tmp_path / "iris_config.json")
    failed = []

    class _Catch(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.WARNING and "Failed to save config" in record.getMessage():
                failed.append(record.getMessage())

    handler = _Catch()
    ic.logger.addHandler(handler)
    try:
        cfg = ic.load_config()
        threads = [threading.Thread(target=lambda: [ic.save_config(cfg) for _ in range(20)]) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        ic.logger.removeHandler(handler)

    assert failed == []
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []
    json.loads((tmp_path / "iris_config.json").read_text(encoding="utf-8"))
