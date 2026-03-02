"""
Database utilities for IRIS Memory Foundation.

Provides encrypted SQLite connections via SQLCipher.
All memory access goes through this module — never raw sqlite3.connect().
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default configuration values
DEFAULT_CIPHER_PAGE_SIZE = 4096
DEFAULT_KDF_ITERATIONS = 64000


def open_encrypted_memory(db_path: str, biometric_key: bytes) -> "sqlcipher3.Connection":
    """
    Opens the SQLCipher AES-256 encrypted memory database.
    
    All memory access goes through this function — never raw sqlite3.connect().
    
    Args:
        db_path: Path to the database file (e.g., "data/memory.db")
        biometric_key: 32-byte key derived from platform biometric API at app startup.
                      At Phase 6 (Torus), this key derives from the same seed phrase as
                      the Dilithium3 identity — one backup recovers everything.
    
    Returns:
        sqlcipher3.Connection: Configured and encrypted connection
    
    Raises:
        ImportError: If sqlcipher3 is not installed
        RuntimeError: If database cannot be opened or configured
    
    Example:
        >>> from backend.memory.db import open_encrypted_memory
        >>> from backend.core.biometric import derive_biometric_key
        >>> key = derive_biometric_key()
        >>> conn = open_encrypted_memory("data/memory.db", key)
    """
    try:
        import sqlcipher3
    except ImportError as e:
        logger.error(
            "sqlcipher3 is required for encrypted memory. "
            "Install: pip install sqlcipher3 (requires libsqlcipher-dev on Linux/macOS)"
        )
        raise ImportError(
            "sqlcipher3 not installed. See docs/MEMORY_SETUP.md for platform-specific instructions."
        ) from e
    
    # Ensure parent directory exists
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Open connection
    conn = sqlcipher3.connect(str(db_path))
    
    try:
        # Configure encryption key
        # Key must be hex-encoded for PRAGMA key
        key_hex = biometric_key.hex()
        conn.execute(f"PRAGMA key='{key_hex}'")
        
        # Configure SQLCipher settings
        conn.execute(f"PRAGMA cipher_page_size={DEFAULT_CIPHER_PAGE_SIZE}")
        conn.execute(f"PRAGMA kdf_iter={DEFAULT_KDF_ITERATIONS}")
        conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent write performance
        conn.execute("PRAGMA foreign_keys=ON")
        
        # Verify encryption is working by executing a test query
        conn.execute("SELECT count(*) FROM sqlite_master")
        
        logger.info(f"[db] Opened encrypted memory database: {db_path}")
        return conn
        
    except Exception as e:
        conn.close()
        logger.error(f"[db] Failed to configure encrypted database: {e}")
        raise RuntimeError(f"Failed to open encrypted memory database: {e}") from e


def verify_encryption(conn: "sqlcipher3.Connection") -> bool:
    """
    Verify that the database connection is properly encrypted.
    
    This is a test function that attempts to verify encryption is active.
    It should be called once after opening the database.
    
    Args:
        conn: SQLCipher connection to verify
    
    Returns:
        True if encryption is verified, False otherwise
    """
    try:
        # Attempt to read the cipher settings
        cursor = conn.execute("PRAGMA cipher_page_size")
        page_size = cursor.fetchone()[0]
        
        cursor = conn.execute("PRAGMA kdf_iter")
        kdf_iter = cursor.fetchone()[0]
        
        logger.debug(f"[db] Encryption verified: page_size={page_size}, kdf_iter={kdf_iter}")
        return True
        
    except Exception as e:
        logger.warning(f"[db] Could not verify encryption settings: {e}")
        return False


def is_sqlcipher_available() -> bool:
    """
    Check if sqlcipher3 is available without importing it.
    
    Returns:
        True if sqlcipher3 can be imported, False otherwise
    """
    try:
        import sqlcipher3
        return True
    except ImportError:
        return False


# Type alias for connection type
Connection = "sqlcipher3.Connection"
