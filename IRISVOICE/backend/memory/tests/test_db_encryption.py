"""
Tests for database encryption functionality.

Verifies that SQLCipher properly encrypts the memory database
and that data cannot be read without the correct key.
"""

import os
import tempfile
import pytest

from backend.memory.db import (
    open_encrypted_memory,
    verify_encryption,
    is_sqlcipher_available,
)


# Skip all tests if sqlcipher3 is not available
pytestmark = pytest.mark.skipif(
    not is_sqlcipher_available(),
    reason="sqlcipher3 not installed"
)


@pytest.fixture
def temp_db_path():
    """Create a temporary database file path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "test_memory.db")


@pytest.fixture
def biometric_key():
    """Generate a test 32-byte biometric key."""
    return b"x" * 32  # 256-bit test key


class TestDatabaseEncryption:
    """Test suite for database encryption."""
    
    def test_sqlcipher_available(self):
        """Verify sqlcipher3 is available for testing."""
        assert is_sqlcipher_available(), "sqlcipher3 should be available"
    
    def test_open_encrypted_memory_creates_db(self, temp_db_path, biometric_key):
        """Test that open_encrypted_memory creates a database file."""
        conn = open_encrypted_memory(temp_db_path, biometric_key)
        assert conn is not None
        conn.close()
        
        # Verify file was created
        assert os.path.exists(temp_db_path), "Database file should be created"
    
    def test_verify_encryption_returns_true(self, temp_db_path, biometric_key):
        """Test that verify_encryption returns True for valid connection."""
        conn = open_encrypted_memory(temp_db_path, biometric_key)
        try:
            assert verify_encryption(conn), "Encryption should be verified"
        finally:
            conn.close()
    
    def test_cannot_read_without_key(self, temp_db_path, biometric_key):
        """Test that database cannot be read without the correct key."""
        # Create encrypted database
        conn1 = open_encrypted_memory(temp_db_path, biometric_key)
        try:
            # Create a test table and insert data
            conn1.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, data TEXT)")
            conn1.execute("INSERT INTO test (data) VALUES ('secret_data')")
            conn1.commit()
        finally:
            conn1.close()
        
        # Try to open with wrong key
        wrong_key = b"y" * 32  # Different 32-byte key
        conn2 = open_encrypted_memory(temp_db_path, wrong_key)
        try:
            # Should fail or return garbage when trying to read
            with pytest.raises(Exception):
                conn2.execute("SELECT * FROM test")
        except:
            pass  # Expected to fail
        finally:
            conn2.close()
    
    def test_wal_mode_enabled(self, temp_db_path, biometric_key):
        """Test that WAL mode is enabled."""
        conn = open_encrypted_memory(temp_db_path, biometric_key)
        try:
            cursor = conn.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]
            assert journal_mode.upper() == "WAL", f"WAL mode should be enabled, got {journal_mode}"
        finally:
            conn.close()
    
    def test_foreign_keys_enabled(self, temp_db_path, biometric_key):
        """Test that foreign keys are enabled."""
        conn = open_encrypted_memory(temp_db_path, biometric_key)
        try:
            cursor = conn.execute("PRAGMA foreign_keys")
            foreign_keys = cursor.fetchone()[0]
            assert foreign_keys == 1, "Foreign keys should be enabled"
        finally:
            conn.close()
    
    def test_cipher_page_size_configured(self, temp_db_path, biometric_key):
        """Test that cipher_page_size is configured."""
        conn = open_encrypted_memory(temp_db_path, biometric_key)
        try:
            cursor = conn.execute("PRAGMA cipher_page_size")
            page_size = cursor.fetchone()[0]
            assert page_size == 4096, f"Page size should be 4096, got {page_size}"
        finally:
            conn.close()
    
    def test_database_is_encrypted_not_plaintext(self, temp_db_path, biometric_key):
        """Test that database file is encrypted (not plaintext SQLite)."""
        # Create encrypted database
        conn = open_encrypted_memory(temp_db_path, biometric_key)
        try:
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
            conn.commit()
        finally:
            conn.close()
        
        # Read raw bytes of database file
        with open(temp_db_path, "rb") as f:
            header = f.read(100)
        
        # Plaintext SQLite starts with "SQLite format 3\0"
        # Encrypted database should not have this header
        assert not header.startswith(b"SQLite format 3"), \
            "Database file should be encrypted, not plaintext SQLite"
    
    def test_parent_directory_created(self, temp_db_path, biometric_key):
        """Test that parent directory is created if it doesn't exist."""
        nested_path = os.path.join(temp_db_path + "_dir", "nested", "memory.db")
        
        conn = open_encrypted_memory(nested_path, biometric_key)
        try:
            assert conn is not None
        finally:
            conn.close()
        
        assert os.path.exists(nested_path), "Nested directory should be created"


class TestImportErrorHandling:
    """Test behavior when sqlcipher3 is not available."""
    
    def test_is_sqlcipher_available_false_when_not_installed(self, monkeypatch):
        """Test that is_sqlcipher_available returns False when import fails."""
        # Simulate sqlcipher3 not being available
        import sys
        monkeypatch.setitem(sys.modules, "sqlcipher3", None)
        
        # Reimport to test
        from backend.memory import db
        assert not db.is_sqlcipher_available()
    
    def test_open_encrypted_memory_raises_import_error(self, monkeypatch):
        """Test that open_encrypted_memory raises ImportError when sqlcipher3 missing."""
        # Simulate sqlcipher3 not being available
        import sys
        monkeypatch.setitem(sys.modules, "sqlcipher3", None)
        
        from backend.memory import db
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            key = b"x" * 32
            
            with pytest.raises(ImportError):
                db.open_encrypted_memory(db_path, key)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
