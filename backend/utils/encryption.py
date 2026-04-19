"""
Encryption utilities for sensitive data like API keys.
Uses Fernet symmetric encryption from the cryptography library.
"""
import os
import base64
from pathlib import Path
from typing import Optional, Tuple
from cryptography.fernet import Fernet


class EncryptionManager:
    """Manages encryption and decryption of sensitive data"""
    
    def __init__(self, key_file: Optional[str] = None):
        """
        Initialize encryption manager.
        
        Args:
            key_file: Path to file containing encryption key. If None, uses default location.
        """
        if key_file is None:
            # Use default location in backend/settings
            key_file = Path(__file__).parent.parent / "settings" / ".encryption_key"
        
        self._key_file = Path(key_file)
        self._fernet = self._load_or_create_key()
    
    def _load_or_create_key(self) -> Fernet:
        """Load existing encryption key or create a new one"""
        if self._key_file.exists():
            # Load existing key
            with open(self._key_file, 'rb') as f:
                key = f.read()
        else:
            # Create new key
            key = Fernet.generate_key()
            
            # Ensure directory exists
            self._key_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Save key with restricted permissions
            with open(self._key_file, 'wb') as f:
                f.write(key)
            
            # Set file permissions to read/write for owner only (Unix-like systems)
            try:
                os.chmod(self._key_file, 0o600)
            except Exception as e:
                print(f"Warning: Could not set file permissions: {e}")
        
        return Fernet(key)
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string.
        
        Args:
            plaintext: The string to encrypt
            
        Returns:
            Base64-encoded encrypted string
        """
        if not plaintext:
            return ""
        
        encrypted_bytes = self._fernet.encrypt(plaintext.encode('utf-8'))
        return base64.b64encode(encrypted_bytes).decode('utf-8')
    
    def decrypt(self, encrypted: str) -> str:
        """
        Decrypt an encrypted string.
        
        Args:
            encrypted: Base64-encoded encrypted string
            
        Returns:
            Decrypted plaintext string
        """
        if not encrypted:
            return ""
        
        try:
            encrypted_bytes = base64.b64decode(encrypted.encode('utf-8'))
            decrypted_bytes = self._fernet.decrypt(encrypted_bytes)
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            print(f"Error decrypting data: {e}")
            return ""
    
    def mask_api_key(self, api_key: str) -> str:
        """
        Mask an API key, showing only the last 4 characters.
        
        Args:
            api_key: The API key to mask
            
        Returns:
            Masked API key (e.g., "sk-****...****1234")
        """
        if not api_key:
            return ""
        
        if len(api_key) <= 4:
            return "*" * len(api_key)
        
        # Show prefix (e.g., "sk-") and last 4 characters
        prefix = ""
        if api_key.startswith("sk-"):
            prefix = "sk-"
            remaining = api_key[3:]
        else:
            remaining = api_key
        
        if len(remaining) <= 4:
            return prefix + "*" * len(remaining)
        
        last_4 = remaining[-4:]
        masked_middle = "****...****"
        
        return f"{prefix}{masked_middle}{last_4}"


# Global instance
_encryption_manager: Optional[EncryptionManager] = None


def get_encryption_manager() -> EncryptionManager:
    """Get the global encryption manager instance"""
    global _encryption_manager
    if _encryption_manager is None:
        _encryption_manager = EncryptionManager()
    return _encryption_manager


def encrypt_api_key(api_key: str) -> str:
    """Convenience function to encrypt an API key"""
    return get_encryption_manager().encrypt(api_key)


def decrypt_api_key(encrypted_key: str) -> str:
    """Convenience function to decrypt an API key"""
    return get_encryption_manager().decrypt(encrypted_key)


def mask_api_key(api_key: str) -> str:
    """Convenience function to mask an API key"""
    return get_encryption_manager().mask_api_key(api_key)
