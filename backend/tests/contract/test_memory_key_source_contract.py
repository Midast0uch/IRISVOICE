"""Contract: key_source="launcher" fails closed and reads the phrase only.

Owner decision 2026-10-31: at release the launcher supplies the memory
passphrase at startup, and NO key is cached on the machine. During development
`key_source` stays "keychain" in data/memory_config.json, so the current
behavior is unchanged.

What the launcher mode must guarantee:

  * no phrase -> RuntimeError, and the store stays closed (no keychain read,
    no pseudo-key fallback, even when force_pseudo=True);
  * a phrase -> the SAME key the 2026-10-31 store was encrypted with:
    lowercase, whitespace collapsed, SHA-256 of the UTF-8 bytes;
  * an unknown/missing setting -> "keychain", so a broken config never silently
    switches to a source that does not exist.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from backend.core import biometric

PHRASE = "quantum shield orbit lattice cipher nexus vector prism forge pulse drift anchor"
EXPECTED = hashlib.sha256(PHRASE.encode("utf-8")).digest()


def _config(tmp_path, value) -> str:
    path = tmp_path / "memory_config.json"
    if value is None:
        path.write_text("{}", encoding="utf-8")
    else:
        path.write_text(json.dumps({"key_source": value}), encoding="utf-8")
    return str(path)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(biometric.MEMORY_PASSPHRASE_ENV, raising=False)
    monkeypatch.delenv("IRIS_MEMORY_KEY", raising=False)
    biometric.clear_session_memory_key()
    yield
    biometric.clear_session_memory_key()


def test_launcher_without_a_phrase_fails_closed(tmp_path):
    with pytest.raises(RuntimeError, match="passphrase required"):
        biometric.initialize_memory_encryption(
            db_path="unused.db", config_path=_config(tmp_path, "launcher")
        )


def test_force_pseudo_does_not_bypass_the_launcher_phrase(tmp_path):
    # A "safety net" that decrypts anyway would defeat the mode.
    with pytest.raises(RuntimeError, match="passphrase required"):
        biometric.initialize_memory_encryption(
            db_path="unused.db",
            config_path=_config(tmp_path, "launcher"),
            force_pseudo=True,
        )


def test_launcher_derives_the_store_key_from_the_phrase(tmp_path, monkeypatch):
    monkeypatch.setenv(biometric.MEMORY_PASSPHRASE_ENV, PHRASE)
    key = biometric.initialize_memory_encryption(
        db_path="unused.db", config_path=_config(tmp_path, "launcher")
    )
    assert key == EXPECTED
    assert len(key) == 32


def test_case_and_extra_spaces_do_not_change_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv(
        biometric.MEMORY_PASSPHRASE_ENV,
        "  QUANTUM   shield  orbit lattice cipher nexus vector prism "
        "forge pulse drift anchor  ",
    )
    key = biometric.initialize_memory_encryption(
        db_path="unused.db", config_path=_config(tmp_path, "launcher")
    )
    assert key == EXPECTED


def test_keychain_is_the_default_and_needs_no_phrase(tmp_path, monkeypatch):
    sentinel = b"\x11" * 32
    monkeypatch.setattr(biometric.KeyStorage, "retrieve_key", classmethod(lambda cls: sentinel))
    key = biometric.initialize_memory_encryption(
        db_path="unused.db", config_path=_config(tmp_path, None)
    )
    assert key == sentinel


def test_unknown_key_source_falls_back_to_keychain(tmp_path, monkeypatch):
    sentinel = b"\x22" * 32
    monkeypatch.setattr(biometric.KeyStorage, "retrieve_key", classmethod(lambda cls: sentinel))
    key = biometric.initialize_memory_encryption(
        db_path="unused.db", config_path=_config(tmp_path, "something-else")
    )
    assert key == sentinel

# ── the dashboard unlock path (session key, never persisted) ────────────────

def test_session_key_unlocks_without_the_env(tmp_path):
    biometric.set_session_memory_key(b"\x33" * 32)
    key = biometric.initialize_memory_encryption(
        db_path="unused.db", config_path=_config(tmp_path, "launcher")
    )
    assert key == b"\x33" * 32


def test_clearing_the_session_key_locks_again(tmp_path):
    biometric.set_session_memory_key(b"\x44" * 32)
    biometric.clear_session_memory_key()
    with pytest.raises(RuntimeError, match="passphrase required"):
        biometric.initialize_memory_encryption(
            db_path="unused.db", config_path=_config(tmp_path, "launcher")
        )


def test_memory_is_locked_reflects_the_session_key(tmp_path):
    cfg = _config(tmp_path, "launcher")
    assert biometric.memory_is_locked(cfg) is True
    biometric.set_session_memory_key(b"\x55" * 32)
    assert biometric.memory_is_locked(cfg) is False


def test_keychain_mode_is_never_locked(tmp_path):
    assert biometric.memory_is_locked(_config(tmp_path, "keychain")) is False
