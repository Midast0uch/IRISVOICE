"""
Tests for the Dilithium -> memory-DB key migration helper.

Verifies that migrate_memory_db_key re-encrypts an existing pseudo-protected
DB in place (so the old key no longer opens it), is a no-op when no Dilithium
key is configured, is idempotent when already Dilithium-protected, and fails
safe when sqlcipher3 is unavailable.
"""

import os
import tempfile
from unittest.mock import patch

from backend.core import biometric
from backend.memory.db import open_encrypted_memory

_FAKE_PRIV = b"fake_dilithium_priv_32_bytes_long!!"  # 32 bytes


def _pseudo_key():
    return biometric.initialize_memory_encryption(force_pseudo=True)


def test_migrate_rekeys_db_and_old_key_fails():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "memory.db")
        old_key = _pseudo_key()

        # Create DB encrypted with the dev pseudo key.
        c = open_encrypted_memory(db_path, old_key)
        c.execute("CREATE TABLE t(id INTEGER)")
        c.commit()
        c.close()

        expected_new = biometric.derive_memory_key_from_dilithium(_FAKE_PRIV)
        with patch.object(
            biometric, "load_dilithium_private_key", return_value=_FAKE_PRIV
        ):
            status = biometric.migrate_memory_db_key(db_path=db_path)

        assert status == "migrated"

        # New (Dilithium-derived) key opens it.
        c2 = open_encrypted_memory(db_path, expected_new)
        c2.execute("SELECT * FROM t")
        c2.close()

        # Old pseudo key must NO LONGER open it.
        try:
            c3 = open_encrypted_memory(db_path, old_key)
            c3.close()
            raise AssertionError("old pseudo key should NOT open the re-keyed DB")
        except Exception:
            pass


def test_migrate_no_dilithium_returns_no_dilithium():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "memory.db")
        with patch.object(
            biometric, "load_dilithium_private_key", return_value=None
        ):
            status = biometric.migrate_memory_db_key(db_path=db_path)
        assert status == "no-dilithium"


def test_migrate_already_dilithium_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "memory.db")
        new_key = biometric.derive_memory_key_from_dilithium(_FAKE_PRIV)

        # Create DB already encrypted with the Dilithium-derived key.
        c = open_encrypted_memory(db_path, new_key)
        c.execute("CREATE TABLE t(id INTEGER)")
        c.commit()
        c.close()

        with patch.object(
            biometric, "load_dilithium_private_key", return_value=_FAKE_PRIV
        ):
            status = biometric.migrate_memory_db_key(db_path=db_path)
        assert status == "already-dilithium"


def test_migrate_sqlcipher_unavailable_fails_safe():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "memory.db")
        # DB must exist (pseudo-protected) so the Dilithium probe open fails
        # and we reach the sqlcipher3-availability guard.
        old_key = _pseudo_key()
        c = open_encrypted_memory(db_path, old_key)
        c.execute("CREATE TABLE t(id INTEGER)")
        c.commit()
        c.close()
        with patch.object(
            biometric, "load_dilithium_private_key", return_value=_FAKE_PRIV
        ):
            with patch(
                "backend.memory.db.is_sqlcipher_available", return_value=False
            ):
                status = biometric.migrate_memory_db_key(db_path=db_path)
        assert status == "failed:sqlcipher3-unavailable"
