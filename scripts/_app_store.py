"""The application memory store path, for tooling scripts.

Uses the backend's own resolver (backend/memory/config.py
``resolve_memory_store_path``: ``data/memory_config.json`` ``db_path``,
anchored to the repo root), loaded by FILE so a script does not import the
``backend.memory`` package (stores, embedding models). config.py imports only
the standard library.

Why (2026-09-30): the store moved to D: (docs/audits/2026-09-29/
disk-move-plan.md) and ``db_path`` is now absolute. Scripts that hardcoded
``data/memory.db`` kept reading the stale C: copy, and once that copy is
deleted, ``sqlite3.connect`` would silently create an EMPTY store there.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_CONFIG = Path(__file__).resolve().parents[1] / "backend" / "memory" / "config.py"


def app_store_path() -> str:
    """Absolute path of the configured application memory store."""
    spec = importlib.util.spec_from_file_location("_iris_memory_config", _CONFIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return str(mod.resolve_memory_store_path())
