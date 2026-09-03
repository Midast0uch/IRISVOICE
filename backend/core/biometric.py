"""
Biometric Key Derivation for IRIS Memory Encryption.

Provides secure 32-byte key derivation using:
1. Platform biometric APIs (Windows Hello, macOS Touch ID, Linux fingerprint)
2. Secure passphrase with PBKDF2 fallback
3. Hardware security keys (future)

The derived key is used for AES-256 encryption of the memory database.
"""

import getpass
import hashlib
import logging
import os
import platform
import socket
import uuid as _uuid
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# HKDF (cryptography lib) for deriving the memory key from the Post-Quantum
# (Dilithium) identity private key. Optional import so the module still loads
# if cryptography is somehow absent.
try:
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    _HAVE_CRYPTOGRAPHY = True
except Exception:
    _HAVE_CRYPTOGRAPHY = False

# Salt for key derivation - in production, this should be unique per installation
# and stored in a secure location (keychain, secure enclave, etc.)
DEFAULT_SALT = b"iris_memory_foundation_v1.0"

# PBKDF2 iterations - higher is more secure but slower
PBKDF2_ITERATIONS = 100000


def derive_biometric_key(
    passphrase: Optional[str] = None,
    salt: Optional[bytes] = None,
    use_platform_biometric: bool = True
) -> bytes:
    """
    Derive a 32-byte encryption key for memory database.
    
    Priority:
    1. Platform biometric API (if available and use_platform_biometric=True)
    2. Provided passphrase
    3. Interactive passphrase prompt
    
    Args:
        passphrase: Optional passphrase to use (skips biometric and prompt)
        salt: Optional salt bytes (uses default if not provided)
        use_platform_biometric: Whether to try platform biometric APIs
    
    Returns:
        32-byte key for AES-256 encryption
    
    Raises:
        RuntimeError: If key derivation fails
    """
    if salt is None:
        salt = DEFAULT_SALT
    
    # If passphrase provided, use it directly
    if passphrase is not None:
        logger.info("[Biometric] Using provided passphrase for key derivation")
        return _derive_from_passphrase(passphrase, salt)
    
    # Try platform biometric if enabled
    if use_platform_biometric:
        try:
            key = _try_platform_biometric(salt)
            if key is not None:
                logger.info("[Biometric] Successfully derived key from platform biometric")
                return key
        except Exception as e:
            logger.warning(f"[Biometric] Platform biometric failed: {e}")
    
    # Fall back to interactive passphrase
    logger.info("[Biometric] Falling back to passphrase prompt")
    passphrase = _prompt_passphrase()
    return _derive_from_passphrase(passphrase, salt)


def _derive_from_passphrase(passphrase: str, salt: bytes) -> bytes:
    """
    Derive key from passphrase using PBKDF2.
    
    Args:
        passphrase: User passphrase
        salt: Salt bytes
    
    Returns:
        32-byte key
    """
    key = hashlib.pbkdf2_hmac(
        'sha256',
        passphrase.encode('utf-8'),
        salt,
        PBKDF2_ITERATIONS
    )
    return key


def _prompt_passphrase() -> str:
    """
    Prompt user for passphrase interactively.
    
    Returns:
        User-provided passphrase
    """
    print("\n" + "=" * 50)
    print("IRIS Memory Encryption")
    print("=" * 50)
    print("A passphrase is required to encrypt your memory database.")
    print("This protects your personal data and conversation history.")
    print("=" * 50 + "\n")
    
    while True:
        passphrase = getpass.getpass("Enter passphrase: ")
        
        if len(passphrase) < 8:
            print("[x] Passphrase must be at least 8 characters long.")
            continue
        
        confirm = getpass.getpass("Confirm passphrase: ")
        
        if passphrase != confirm:
            print("[x] Passphrases do not match. Please try again.")
            continue
        
        print("[+] Passphrase accepted.\n")
        return passphrase


def _try_platform_biometric(salt: bytes) -> Optional[bytes]:
    """
    Try to use platform biometric APIs.
    
    Args:
        salt: Salt for key derivation
    
    Returns:
        Derived key or None if not available/failed
    """
    system = platform.system()
    
    if system == "Darwin":  # macOS
        return _try_macos_biometric(salt)
    elif system == "Windows":
        return _try_windows_biometric(salt)
    elif system == "Linux":
        return _try_linux_biometric(salt)
    
    logger.debug(f"[Biometric] Platform '{system}' not supported for biometric auth")
    return None


def _try_macos_biometric(salt: bytes) -> Optional[bytes]:
    """
    Try to use macOS Touch ID / Secure Enclave.
    
    Args:
        salt: Salt for key derivation
    
    Returns:
        Derived key or None
    """
    try:
        # Try to use pyobjc-framework-LocalAuthentication
        # This is a simplified version - production would use proper Touch ID integration
        import subprocess
        
        # Check if Touch ID is available
        result = subprocess.run(
            ["bioutil", "-r"],
            capture_output=True,
            text=True
        )
        
        if "Touch ID" in result.stdout or result.returncode == 0:
            # For now, fall back to passphrase
            # Full implementation would use LocalAuthentication framework
            logger.debug("[Biometric] macOS Touch ID available but using passphrase fallback")
            return None
            
    except Exception as e:
        logger.debug(f"[Biometric] macOS biometric check failed: {e}")
    
    return None


def _try_windows_biometric(salt: bytes) -> Optional[bytes]:
    """
    Try to use Windows Hello.
    
    Args:
        salt: Salt for key derivation
    
    Returns:
        Derived key or None
    """
    try:
        # Try to use pywin32 or Windows Runtime APIs
        # This is a simplified version - production would use Windows Hello APIs
        import subprocess
        
        # Check if Windows Hello is available
        result = subprocess.run(
            ["powershell", "-Command", "Get-WindowsOptionalFeature -Online -FeatureName WindowsHello"],
            capture_output=True,
            text=True
        )
        
        if "Enabled" in result.stdout:
            logger.debug("[Biometric] Windows Hello available but using passphrase fallback")
            return None
            
    except Exception as e:
        logger.debug(f"[Biometric] Windows biometric check failed: {e}")
    
    return None


def _try_linux_biometric(salt: bytes) -> Optional[bytes]:
    """
    Try to use Linux fingerprint/PAM authentication.
    
    Args:
        salt: Salt for key derivation
    
    Returns:
        Derived key or None
    """
    try:
        # Check for fingerprint support via fprintd
        import subprocess
        
        result = subprocess.run(
            ["which", "fprintd-verify"],
            capture_output=True
        )
        
        if result.returncode == 0:
            logger.debug("[Biometric] Linux fingerprint available but using passphrase fallback")
            return None
            
    except Exception as e:
        logger.debug(f"[Biometric] Linux biometric check failed: {e}")
    
    return None


class KeyStorage:
    """
    Secure key storage using platform keychain/keyring.
    
    Provides methods to store and retrieve the encryption key
    securely using platform-native keychain services.
    """
    
    SERVICE_NAME = "IRIS_Memory_Foundation"
    ACCOUNT_NAME = "memory_encryption_key"
    
    @classmethod
    def store_key(cls, key: bytes) -> bool:
        """
        Store key in platform keychain.
        
        Args:
            key: 32-byte encryption key
        
        Returns:
            True if stored successfully
        """
        try:
            import keyring
            keyring.set_password(
                cls.SERVICE_NAME,
                cls.ACCOUNT_NAME,
                key.hex()
            )
            logger.info("[Biometric] Key stored in platform keychain")
            return True
        except ImportError:
            logger.warning("[Biometric] keyring module not installed, key not stored")
            return False
        except Exception as e:
            logger.error(f"[Biometric] Failed to store key: {e}")
            return False
    
    @classmethod
    def retrieve_key(cls) -> Optional[bytes]:
        """
        Retrieve key from platform keychain.
        
        Returns:
            Key bytes or None if not found
        """
        try:
            import keyring
            key_hex = keyring.get_password(cls.SERVICE_NAME, cls.ACCOUNT_NAME)
            if key_hex:
                return bytes.fromhex(key_hex)
            return None
        except ImportError:
            return None
        except Exception as e:
            logger.error(f"[Biometric] Failed to retrieve key: {e}")
            return None
    
    @classmethod
    def delete_key(cls) -> bool:
        """
        Delete key from platform keychain.
        
        Returns:
            True if deleted successfully
        """
        try:
            import keyring
            keyring.delete_password(cls.SERVICE_NAME, cls.ACCOUNT_NAME)
            logger.info("[Biometric] Key deleted from platform keychain")
            return True
        except Exception as e:
            logger.error(f"[Biometric] Failed to delete key: {e}")
            return False


def _derive_machine_key(salt: bytes) -> bytes:
    """
    Derive a non-interactive machine-specific encryption key.

    Uses a combination of hostname + a stable UUID stored in a local
    file so the key survives restarts without requiring user input.
    This is the server-mode fallback — no interactive prompts.

    Args:
        salt: Salt bytes for key derivation

    Returns:
        32-byte key
    """
    import socket
    import uuid as _uuid
    from pathlib import Path as _Path

    machine_id_file = _Path("data/.machine_id")
    try:
        if machine_id_file.exists():
            machine_uuid = machine_id_file.read_text().strip()
        else:
            machine_uuid = str(_uuid.uuid4())
            machine_id_file.parent.mkdir(parents=True, exist_ok=True)
            machine_id_file.write_text(machine_uuid)
    except Exception:
        machine_uuid = str(_uuid.getnode())  # MAC-address-based fallback

    machine_passphrase = f"{socket.gethostname()}:{machine_uuid}"
    logger.info("[Biometric] Using machine-derived encryption key (non-interactive server mode)")
    return _derive_from_passphrase(machine_passphrase, salt)


def initialize_memory_encryption(
    db_path: str = "data/memory.db",
    config_path: str = "data/memory_config.json",
    force_pseudo: bool = False
) -> bytes:
    """
    Initialize memory encryption with automatic key management.

    NON-BLOCKING server-safe priority order:
    0. (Opt-in) Post-Quantum Identity (Dilithium) private key, if provided by
       iris-launcher — derived to the memory key via HKDF. This is the intended
       "quantum key unlocks memory" path. Skipped during development (no key),
       so the existing data/memory.db always opens with the dev pseudo-key.
    1. IRIS_MEMORY_KEY environment variable (development override / pseudo key)
    2. Existing key stored in platform keychain
    3. Machine-derived key (hostname + stable UUID) — no user prompt

    Args:
        db_path: Path to memory database
        config_path: Path to memory configuration
        force_pseudo: When True, skip the Dilithium path and use the dev
            pseudo-key chain. Used as a safety-net fallback if the primary
            key cannot open the existing DB, so the connection is never lost.

    Returns:
        32-byte encryption key
    """
    salt = DEFAULT_SALT

    # 0. (Opt-in) Post-Quantum Identity (Dilithium) -> memory key via HKDF.
    # Only active when iris-launcher has provided a Dilithium private key.
    # During development (no key) this is skipped and the dev pseudo-key
    # below is used, so the existing data/memory.db always opens.
    if not force_pseudo:
        _dil = load_dilithium_private_key()
        if _dil:
            try:
                logger.info(
                    "[Biometric] Deriving memory key from Dilithium private key (HKDF)"
                )
                return derive_memory_key_from_dilithium(_dil)
            except Exception as _e:
                logger.warning(
                    "[Biometric] Dilithium key derivation failed, falling back: %s", _e
                )

    # 1. Check environment variable (dev override / pseudo key)
    env_key = derive_key_from_env()
    if env_key is not None:
        logger.info("[Biometric] Using IRIS_MEMORY_KEY environment variable")
        return env_key

    # 2. Try to retrieve existing key from keychain
    key = KeyStorage.retrieve_key()
    if key is not None:
        logger.info("[Biometric] Using stored encryption key from keychain")
        return key

    # 3. Non-interactive fallback: machine-derived key
    # This keeps the server from blocking on getpass.getpass() at startup.
    # Interactive passphrase setup can be added as a frontend setting later.
    key = _derive_machine_key(salt)

    # Try to store for future use
    if KeyStorage.store_key(key):
        logger.info("[Biometric] Machine-derived key stored in system keychain")
    else:
        logger.info("[Biometric] Keychain unavailable — machine-derived key used in-memory only")

    return key


# For testing/development: allow key from environment
def derive_key_from_env() -> Optional[bytes]:
    """
    Derive key from environment variable (development only).
    
    Set IRIS_MEMORY_KEY environment variable to use.
    
    Returns:
        Key bytes or None if env var not set
    """
    env_key = os.environ.get("IRIS_MEMORY_KEY")
    if env_key:
        logger.warning("[Biometric] Using key from environment variable (development only)")
        return hashlib.sha256(env_key.encode()).digest()
    return None


# ── Post-Quantum Identity (Dilithium) → memory key ───────────────────────────
# Intended "quantum key unlocks memory" path. iris-launcher generates the
# Dilithium3 identity keypair; its private key becomes the sole source of the
# memory-DB encryption key via HKDF. During development (no key provided) this
# is skipped and the dev pseudo-key chain below is used instead.

def derive_memory_key_from_dilithium(dilithium_priv: bytes) -> bytes:
    """
    Derive the 32-byte memory-DB encryption key from the Post-Quantum
    (Dilithium) identity private key via HKDF-SHA256.

    Deterministic: the same private key always yields the same memory key,
    so a user holding their Dilithium key can always reopen their memory DB.

    Args:
        dilithium_priv: Raw Dilithium private-key bytes (from iris-launcher).
    Returns:
        32-byte key for AES-256 (sqlcipher3) memory database.
    """
    if not _HAVE_CRYPTOGRAPHY:
        raise RuntimeError(
            "cryptography library required for Dilithium->memory key derivation"
        )
    _hk = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=DEFAULT_SALT,
        info=b"iris-voice-memory-key-v1",
    )
    return _hk.derive(dilithium_priv)


def load_dilithium_private_key() -> Optional[bytes]:
    """
    Load the Dilithium private key provided by iris-launcher.

    Sources (in order):
      1. IRIS_DILITHIUM_KEY       — hex-encoded private key (env var)
      2. IRIS_DILITHIUM_KEY_FILE  — path to a file with raw key bytes

    Returns the raw key bytes, or None when not provided (development mode).
    """
    _hex = os.environ.get("IRIS_DILITHIUM_KEY")
    if _hex:
        try:
            return bytes.fromhex(_hex.strip())
        except Exception as _e:
            logger.warning("[Biometric] IRIS_DILITHIUM_KEY not valid hex: %s", _e)
            return None
    _file = os.environ.get("IRIS_DILITHIUM_KEY_FILE")
    if _file and os.path.exists(_file):
        try:
            with open(_file, "rb") as _f:
                return _f.read()
        except Exception as _e:
            logger.warning("[Biometric] Could not read Dilithium key file: %s", _e)
    return None


def migrate_memory_db_key(
    db_path: str = "data/memory.db",
    config_path: str = "data/memory_config.json",
) -> str:
    """
    Migrate data/memory.db from the dev pseudo-key to the Dilithium-derived key.

    This is the runbook step executed once iris-launcher has generated the real
    Post-Quantum (Dilithium) identity key and exported it via IRIS_DILITHIUM_KEY
    (hex) or IRIS_DILITHIUM_KEY_FILE. It re-encrypts the existing DB in place using
    SQLCipher's ``PRAGMA rekey`` so the memory is thereafter protected solely by the
    Dilithium-derived key — no data is copied or lost.

    Safe to call at any time; it is idempotent and never corrupts the DB:
      - No Dilithium key configured      -> "no-dilithium"   (nothing done)
      - DB already Dilithium-protected    -> "already-dilithium"
      - DB pseudo-protected, rekeyed OK   -> "migrated"
      - sqlcipher3 absent (plaintext)     -> "failed:sqlcipher3-unavailable"
      - any open/rekey error              -> "failed:<ErrorType>" (DB untouched)

    Returns:
        A short status string (see above) for logging / agent decision-making.
    """
    if not _HAVE_CRYPTOGRAPHY:
        return "failed:cryptography-unavailable"

    _dil = load_dilithium_private_key()
    if not _dil:
        return "no-dilithium"

    _new_key = derive_memory_key_from_dilithium(_dil)

    # Already migrated? Try opening with the Dilithium key first.
    try:
        from backend.memory.db import open_encrypted_memory
        _probe = open_encrypted_memory(db_path, _new_key)
        _probe.close()
        return "already-dilithium"
    except Exception:
        pass

    # Not Dilithium-protected: assume pseudo key. Open with pseudo and rekey.
    try:
        from backend.memory.db import is_sqlcipher_available
        if not is_sqlcipher_available():
            return "failed:sqlcipher3-unavailable"

        _old_key = initialize_memory_encryption(
            db_path=db_path, config_path=config_path, force_pseudo=True
        )
        _conn = open_encrypted_memory(db_path, _old_key)
        try:
            _conn.execute(f"PRAGMA rekey='{_new_key.hex()}'")
            _conn.commit()
        finally:
            _conn.close()
        logger.info("[Biometric] Memory DB re-keyed to Dilithium-derived key")
        return "migrated"
    except Exception as _e:
        logger.error(f"[Biometric] Memory DB re-key failed: {_e}")
        return f"failed:{type(_e).__name__}"
