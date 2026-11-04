"""Contract: a store written by `encrypt_plaintext_store` opens with the app's opener.

Measured 2026-10-31 (D6): the exporter wrote a RAW-key file
(`ATTACH ... KEY "x'<hex>'"`), while `open_encrypted_memory` read the same hex as
a PASSPHRASE (`PRAGMA key='<hex>'`, PBKDF2 over the text). The live 640 MB store
was therefore encrypted into a format its own opener rejected:

    sqlcipher3.dbapi2.DatabaseError: file is not a database
    (hmac check failed for pgno=1)

The exporter's own probe passed because it used the raw form, so this contract
pins the two sides together. Without it the store is encrypted but unopenable.
"""
from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("sqlcipher3")

from backend.core.biometric import encrypt_plaintext_store  # noqa: E402
from backend.memory.db import is_plaintext_store, open_encrypted_memory  # noqa: E402

KEY = bytes(range(32))


def _plain_store(path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t (v) VALUES ('kept')")
        conn.commit()
    finally:
        conn.close()


def test_encrypted_store_opens_with_the_app_opener(tmp_path):
    db = tmp_path / "memory.db"
    _plain_store(db)

    assert encrypt_plaintext_store(str(db), KEY) == "encrypted"
    assert is_plaintext_store(str(db)) is False

    conn = open_encrypted_memory(str(db), KEY)
    try:
        assert conn.execute("select v from t").fetchone()[0] == "kept"
    finally:
        conn.close()


def test_the_wrong_key_still_fails(tmp_path):
    db = tmp_path / "memory.db"
    _plain_store(db)
    assert encrypt_plaintext_store(str(db), KEY) == "encrypted"

    with pytest.raises(RuntimeError):
        open_encrypted_memory(str(db), b"\x00" * 32)
