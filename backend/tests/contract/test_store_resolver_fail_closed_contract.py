"""The store resolver never hands out the default store for a config that exists.

Found 2026-11-09 (memory writer audit): resolve_memory_store_path caught any
load_config failure and returned data/memory.db, and open_encrypted_memory
CREATES a store there. One bad read of an existing memory_config.json (an
unknown field - the key_source incident of 2026-10-31 - or a half-written
file) gave the app an empty memory without an error. Pins:
  * a config that fails validation still yields ITS db_path (raw JSON read);
  * an unreadable config yields the last path that resolved, never the default;
  * with neither, the resolver raises instead of picking a store;
  * a MISSING config still means defaults (a fresh install).
"""
from __future__ import annotations

import json

import pytest

from backend.memory import config as mc


@pytest.fixture(autouse=True)
def _no_last_good(monkeypatch):
    monkeypatch.setattr(mc, "_LAST_GOOD_STORE_PATH", None)


def test_an_invalid_field_still_resolves_the_configured_store(tmp_path):
    store = tmp_path / "store" / "memory.db"
    cfg = tmp_path / "memory_config.json"
    cfg.write_text(json.dumps({"db_path": str(store), "not_a_field": 1}), encoding="utf-8")
    assert mc.resolve_memory_store_path(str(cfg)) == store


def test_an_unreadable_config_uses_the_last_good_path(tmp_path):
    good = tmp_path / "good.json"
    store = tmp_path / "store" / "memory.db"
    good.write_text(json.dumps({"db_path": str(store)}), encoding="utf-8")
    assert mc.resolve_memory_store_path(str(good)) == store
    bad = tmp_path / "bad.json"
    bad.write_text('{"db_path": "D:/IRIS/sto', encoding="utf-8")  # half-written
    assert mc.resolve_memory_store_path(str(bad)) == store


def test_with_no_good_path_it_raises_instead_of_the_default(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError):
        mc.resolve_memory_store_path(str(bad))


def test_a_missing_config_still_means_defaults(tmp_path):
    p = mc.resolve_memory_store_path(str(tmp_path / "absent.json"))
    assert p == mc.REPO_ROOT / "data" / "memory.db"
