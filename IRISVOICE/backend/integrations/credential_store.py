"""
Credential Store - Secure credential storage with AES-256-GCM encryption

Phase 1: OS Keychain-based key derivation
Phase 2: Torus Dilithium identity layer (future upgrade)
"""
import os
import json
import asyncio
import logging
from pathlib import Path
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend
import keyring

from .models import CredentialPayload

logger = logging.getLogger(__name__)


class CredentialStoreError(Exception):
    """Base exception for credential store errors"""
    pass


class CredentialDecryptionError(CredentialStoreError):
    """
    Credential decryption failed - credential is corrupted or key has changed.
    The corrupted credential has been wiped. Re-authentication is required.
    """
    pass


class CredentialStore:
    """
    Secure credential storage with AES-256-GCM encryption.
    Interface is stable across Phase 1 (OS Keychain) and Phase 2 (Torus Identity).

    Credentials are stored encrypted at:
        ~/.iris/credentials/{integration_id}.enc

    Encryption keys are derived from OS keychain in Phase 1.
    """

    SERVICE_NAME = "iris"
    KEY_ACCOUNT_PREFIX = "credential-key-"
    CREDENTIALS_DIR = ".iris/credentials"

    def __init__(self, credentials_dir: Optional[Path] = None):
        """
        Initialize the credential store.

        Args:
            credentials_dir: Directory to store encrypted credentials.
                           Defaults to ~/.iris/credentials
        """
        if credentials_dir:
            self._credentials_dir = Path(credentials_dir)
        else:
            self._credentials_dir = Path.home() / self.CREDENTIALS_DIR

        # Ensure credentials directory exists
        self._credentials_dir.mkdir(parents=True, exist_ok=True)

    def _get_key_account(self, integration_id: str) -> str:
        """Get the keychain account name for an integration"""
        return f"{self.KEY_ACCOUNT_PREFIX}{integration_id}"

    def _get_credential_path(self, integration_id: str) -> Path:
        """Get the file path for an integration's encrypted credential"""
        return self._credentials_dir / f"{integration_id}.enc"

    async def _get_encryption_key(self, integration_id: str) -> bytes:
        """
        Get or derive the encryption key for an integration.

        Phase 1 Implementation (OS Keychain):
        - Try to load existing key from OS keychain
        - If not exists, generate random 256-bit key and store it

        Future Phase 2 (Torus Identity):
        - Replace this method to derive key from Dilithium private key using HKDF
        - Interface remains unchanged

        Args:
            integration_id: Unique identifier for the integration

        Returns:
            32-byte encryption key
        """
        account = self._get_key_account(integration_id)

        # Try to load existing key
        key_hex = keyring.get_password(self.SERVICE_NAME, account)

        if key_hex:
            logger.debug(f"[CredentialStore] Loaded existing key for {integration_id}")
            return bytes.fromhex(key_hex)

        # Generate new key
        logger.info(f"[CredentialStore] Generating new encryption key for {integration_id}")
        key = AESGCM.generate_key(bit_length=256)
        key_hex = key.hex()

        # Store in keychain
        try:
            keyring.set_password(self.SERVICE_NAME, account, key_hex)
            logger.info(f"[CredentialStore] Key stored in OS keychain for {integration_id}")
        except Exception as e:
            logger.error(f"[CredentialStore] Failed to store key in keychain: {e}")
            raise CredentialStoreError(f"Failed to store encryption key: {e}")

        return key

    def _encrypt_data(self, plaintext: bytes, key: bytes) -> dict:
        """
        Encrypt data using AES-256-GCM.

        Args:
            plaintext: Data to encrypt
            key: 32-byte encryption key

        Returns:
            Dictionary with iv, tag, data, and version
        """
        # Generate random 12-byte IV (nonce)
        iv = os.urandom(12)

        # Create AESGCM instance and encrypt
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(iv, plaintext, None)

        # AES-GCM appends 16-byte authentication tag to ciphertext
        # Split it for storage compatibility with existing format
        actual_ciphertext = ciphertext[:-16]
        tag = ciphertext[-16:]

        return {
            "iv": iv.hex(),
            "tag": tag.hex(),
            "data": actual_ciphertext.hex(),
            "version": 1  # For future migration support
        }

    def _decrypt_data(self, encrypted: dict, key: bytes) -> bytes:
        """
        Decrypt data using AES-256-GCM.

        Args:
            encrypted: Dictionary with iv, tag, data
            key: 32-byte encryption key

        Returns:
            Decrypted plaintext

        Raises:
            CredentialStoreError: If decryption fails (wrong key, tampered data)
        """
        try:
            iv = bytes.fromhex(encrypted["iv"])
            tag = bytes.fromhex(encrypted["tag"])
            ciphertext = bytes.fromhex(encrypted["data"])

            # Reconstruct ciphertext with tag for AESGCM
            full_ciphertext = ciphertext + tag

            # Decrypt
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(iv, full_ciphertext, None)

            return plaintext

        except Exception as e:
            logger.error(f"[CredentialStore] Decryption failed: {e}")
            raise CredentialStoreError(f"Failed to decrypt credential: {e}")

    async def save(self, integration_id: str, credential: CredentialPayload) -> None:
        """
        Encrypt and store a credential.

        Args:
            integration_id: Unique identifier for the integration
            credential: Credential payload to store

        Raises:
            CredentialStoreError: If encryption or storage fails
        """
        try:
            # Get encryption key
            key = await self._get_encryption_key(integration_id)

            # Serialize credential to JSON
            plaintext = json.dumps(credential.to_dict()).encode('utf-8')

            # Encrypt
            encrypted = self._encrypt_data(plaintext, key)

            # Write to file
            credential_path = self._get_credential_path(integration_id)
            with open(credential_path, 'w') as f:
                json.dump(encrypted, f)

            logger.info(f"[CredentialStore] Credential saved for {integration_id}")

        except CredentialStoreError:
            raise
        except Exception as e:
            logger.error(f"[CredentialStore] Failed to save credential: {e}")
            raise CredentialStoreError(f"Failed to save credential: {e}")

    async def load(self, integration_id: str) -> CredentialPayload:
        """
        Retrieve and decrypt a credential.

        Args:
            integration_id: Unique identifier for the integration

        Returns:
            Decrypted credential payload

        Raises:
            CredentialStoreError: If credential doesn't exist
            CredentialDecryptionError: If decryption fails (credential wiped, re-auth needed)
        """
        credential_path = self._get_credential_path(integration_id)

        if not credential_path.exists():
            raise CredentialStoreError(f"No credential found for {integration_id}")

        try:
            # Read encrypted data
            with open(credential_path, 'r') as f:
                encrypted = json.load(f)

            # Get encryption key
            key = await self._get_encryption_key(integration_id)

            # Decrypt
            plaintext = self._decrypt_data(encrypted, key)

            # Parse JSON
            data = json.loads(plaintext.decode('utf-8'))
            credential = CredentialPayload.from_dict(data)

            logger.debug(f"[CredentialStore] Credential loaded for {integration_id}")
            return credential

        except CredentialStoreError:
            # Re-raise credential store errors as-is
            raise
        except Exception as e:
            # Decryption failed - credential is corrupted or key changed
            logger.error(
                f"[CredentialStore] Decryption failed for {integration_id}: {e}. "
                "Wiping corrupted credential - re-authentication required."
            )

            # Wipe the corrupted credential (don't revoke - token may be invalid anyway)
            try:
                credential_path.unlink()
                logger.info(f"[CredentialStore] Corrupted credential file deleted for {integration_id}")
            except Exception as delete_error:
                logger.warning(f"[CredentialStore] Failed to delete corrupted credential: {delete_error}")

            # Raise decryption error to trigger re-authentication flow
            raise CredentialDecryptionError(
                f"Credential decryption failed for {integration_id}. "
                "The corrupted credential has been removed. Please re-authenticate."
            )

    async def wipe(self, integration_id: str, revoke_token: bool = True) -> None:
        """
        Delete a stored credential and optionally revoke OAuth token.

        Args:
            integration_id: Unique identifier for the integration
            revoke_token: Whether to revoke OAuth token if applicable

        Raises:
            CredentialStoreError: If deletion fails
        """
        try:
            # Load credential to check if token revocation is needed
            if revoke_token:
                try:
                    credential = await self.load(integration_id)
                    if credential.revocable and credential.revoke_url:
                        # TODO: Implement token revocation
                        logger.info(f"[CredentialStore] Revoking token for {integration_id}")
                except CredentialStoreError:
                    # Credential doesn't exist, skip revocation
                    pass

            # Delete credential file
            credential_path = self._get_credential_path(integration_id)
            if credential_path.exists():
                credential_path.unlink()
                logger.info(f"[CredentialStore] Credential file deleted for {integration_id}")

            # Delete key from keychain
            account = self._get_key_account(integration_id)
            try:
                keyring.delete_password(self.SERVICE_NAME, account)
                logger.info(f"[CredentialStore] Key deleted from keychain for {integration_id}")
            except Exception:
                # Key might not exist, that's okay
                pass

        except Exception as e:
            logger.error(f"[CredentialStore] Failed to wipe credential: {e}")
            raise CredentialStoreError(f"Failed to wipe credential: {e}")

    async def exists(self, integration_id: str) -> bool:
        """
        Check if a credential exists.

        Args:
            integration_id: Unique identifier for the integration

        Returns:
            True if credential exists, False otherwise
        """
        credential_path = self._get_credential_path(integration_id)
        return credential_path.exists()


# Global instance for convenience
_credential_store: Optional[CredentialStore] = None


def get_credential_store() -> CredentialStore:
    """Get the global credential store instance"""
    global _credential_store
    if _credential_store is None:
        _credential_store = CredentialStore()
    return _credential_store
