"""Post-Quantum Identity (Dilithium) -> memory-DB key derivation (HKDF).

Verifies the intended "quantum key unlocks memory" path is wired correctly
and that development (no Dilithium key) still uses the dev pseudo-key so the
existing data/memory.db always opens.
"""
import os
from unittest.mock import patch

from backend.core import biometric


def test_dilithium_derivation_is_deterministic_and_32_bytes():
    priv = b"\x01" * 32
    k1 = biometric.derive_memory_key_from_dilithium(priv)
    k2 = biometric.derive_memory_key_from_dilithium(priv)
    assert isinstance(k1, bytes)
    assert len(k1) == 32
    assert k1 == k2  # deterministic: same key -> same memory key


def test_dilithium_derivation_differs_by_input():
    a = biometric.derive_memory_key_from_dilithium(b"\x01" * 32)
    b = biometric.derive_memory_key_from_dilithium(b"\x02" * 32)
    assert a != b


def test_load_dilithium_key_from_env_hex():
    priv = b"\xab" * 32
    with patch.dict(os.environ, {"IRIS_DILITHIUM_KEY": priv.hex()}):
        assert biometric.load_dilithium_private_key() == priv


def test_load_dilithium_key_from_file():
    import tempfile
    priv = b"\xcd" * 32
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(priv)
        path = f.name
    try:
        with patch.dict(os.environ, {"IRIS_DILITHIUM_KEY_FILE": path}):
            assert biometric.load_dilithium_private_key() == priv
    finally:
        os.remove(path)


def test_load_dilithium_key_absent_in_dev():
    with patch.dict(os.environ, {}, clear=True):
        assert biometric.load_dilithium_private_key() is None


def test_force_pseudo_returns_dev_key_without_dilithium():
    # force_pseudo must skip the Dilithium path and return a 32-byte dev key
    # without requiring any quantum key — keeps data/memory.db openable.
    key = biometric.initialize_memory_encryption(
        db_path="data/memory.db", force_pseudo=True
    )
    assert isinstance(key, bytes)
    assert len(key) == 32


def test_dilithium_key_drives_memory_key_when_present():
    priv = b"\x07" * 48
    expected = biometric.derive_memory_key_from_dilithium(priv)
    with patch.dict(os.environ, {"IRIS_DILITHIUM_KEY": priv.hex()}):
        # No IRIS_MEMORY_KEY / keychain -> Dilithium path is taken
        with patch.object(biometric, "derive_key_from_env", return_value=None), \
             patch.object(biometric.KeyStorage, "retrieve_key", return_value=None):
            got = biometric.initialize_memory_encryption(db_path="data/memory.db")
    assert got == expected
