"""Contract: a PLAINTEXT store is converted, and never reported as protected.

Measured 2026-10-30 on a plaintext temp store:

  * ``migrate_memory_db_key`` returned **"already-dilithium"** with a key set.
    The probe opened the file with sqlite3 whatever the key was, because
    ``open_encrypted_memory`` picks the reader from the file header — so the
    probe "succeeded" and the function claimed quantum protection the file did
    not have.
  * ``PRAGMA rekey`` on a plaintext file is a SILENT no-op on a plain sqlite3
    connection (SQLite ignores unknown pragmas) and raises on a sqlcipher3 one.

Both would tell an operator the memory is encrypted while it sits in the clear.
The conversion is ``sqlcipher_export`` into a keyed target.
"""
import os
import sqlite3

from backend.core import biometric
from backend.memory.db import is_plaintext_store

KEY_HEX = "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899"


def _plain_store(path: str) -> str:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (x TEXT)")
    con.execute("INSERT INTO t VALUES ('secret-value')")
    con.execute("CREATE INDEX ix_t ON t(x)")
    con.commit()
    con.close()
    return path


def test_is_plaintext_store_reads_the_header(tmp_path):
    plain = _plain_store(str(tmp_path / "plain.db"))
    assert is_plaintext_store(plain) is True
    assert is_plaintext_store(str(tmp_path / "missing.db")) is False


def test_encrypt_plaintext_store_round_trip(tmp_path):
    import sqlcipher3

    path = _plain_store(str(tmp_path / "plain.db"))
    key = bytes.fromhex(KEY_HEX)

    assert biometric.encrypt_plaintext_store(path, key) == "encrypted"
    assert is_plaintext_store(path) is False, "the file is still plaintext"

    conn = sqlcipher3.connect(path)
    conn.execute(f"PRAGMA key = \"x'{KEY_HEX}'\"")
    assert conn.execute("SELECT x FROM t").fetchall() == [("secret-value",)]
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='ix_t'"
    ).fetchall() == [("ix_t",)]
    conn.close()

    backups = [p for p in os.listdir(tmp_path) if ".pre-encrypt-" in p]
    assert backups, "the original was not kept"


def test_encrypt_plaintext_store_is_idempotent(tmp_path):
    path = _plain_store(str(tmp_path / "plain.db"))
    key = bytes.fromhex(KEY_HEX)
    assert biometric.encrypt_plaintext_store(path, key) == "encrypted"
    assert biometric.encrypt_plaintext_store(path, key) == "already-encrypted"


def test_migrate_never_claims_protection_on_a_plaintext_store(tmp_path, monkeypatch):
    path = _plain_store(str(tmp_path / "plain.db"))
    monkeypatch.setenv("IRIS_DILITHIUM_KEY", KEY_HEX)

    status = biometric.migrate_memory_db_key(db_path=path)

    assert status != "already-dilithium", "a plaintext store is not protected"
    assert status == "encrypted-plaintext", status
    assert is_plaintext_store(path) is False


def test_migrate_without_a_key_leaves_the_store_alone(tmp_path, monkeypatch):
    path = _plain_store(str(tmp_path / "plain.db"))
    monkeypatch.delenv("IRIS_DILITHIUM_KEY", raising=False)
    monkeypatch.delenv("IRIS_DILITHIUM_KEY_FILE", raising=False)

    assert biometric.migrate_memory_db_key(db_path=path) == "no-dilithium"
    assert is_plaintext_store(path) is True
