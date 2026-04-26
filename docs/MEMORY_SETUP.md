# IRIS Memory Foundation Setup Guide

This guide covers the installation and configuration of the IRIS Memory Foundation, a three-tier memory architecture providing encrypted, persistent storage for the IRIS AI assistant.

## Overview

The Memory Foundation provides:
- **Working Memory**: Zone-based in-process context management
- **Episodic Memory**: Vector-searchable task history with embeddings
- **Semantic Memory**: Distilled user model and preferences

All data is encrypted at rest using AES-256 via SQLCipher.

---

## Prerequisites

### Python Version
- Python 3.9 or higher

### System Dependencies

#### macOS

```bash
# Install SQLCipher via Homebrew
brew install sqlcipher

# Install sentence-transformers dependencies
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

#### Linux (Ubuntu/Debian)

```bash
# Install SQLCipher development libraries
sudo apt-get update
sudo apt-get install -y sqlcipher libsqlcipher-dev

# Install build tools for sentence-transformers
sudo apt-get install -y build-essential python3-dev
```

#### Linux (RHEL/CentOS/Fedora)

```bash
# Install SQLCipher
sudo dnf install sqlcipher sqlcipher-devel
# OR for older versions:
sudo yum install sqlcipher sqlcipher-devel
```

#### Windows

**Option 1: Pre-built binaries (recommended)**
```powershell
# Download SQLCipher pre-built binaries from:
# https://www.zetetic.net/sqlcipher/

# Add to PATH or place in project directory
```

**Option 2: Build from source**
```powershell
# Requires Visual Studio Build Tools
# Follow instructions at: https://github.com/sqlcipher/sqlcipher/blob/master/README.md
```

---

## Installation

### 1. Install Python Dependencies

```bash
# From project root
cd IRISVOICE

# Install memory dependencies
pip install -r requirements.txt
```

The memory system requires:
- `sqlcipher3>=0.5.0` - Encrypted SQLite
- `sqlite-vec>=0.1.0` - Vector search extension
- `sentence-transformers>=2.7.0` - Text embeddings

### 2. Verify SQLCipher Installation

```bash
python -c "from sqlcipher3 import dbapi2; print('SQLCipher OK')"
```

### 3. Download Embedding Model

The embedding model downloads automatically on first use (~80MB), or you can pre-download:

```python
from sentence_transformers import SentenceTransformer

# Pre-download model
model = SentenceTransformer('all-MiniLM-L6-v2')
print("Model downloaded successfully")
```

---

## Configuration

### Basic Configuration

Create `data/memory_config.json`:

```json
{
  "db_path": "data/memory.db",
  "encryption_enabled": true,
  "compression": {
    "threshold": 0.80,
    "keep_ratio": 0.60
  },
  "distillation": {
    "enabled": true,
    "interval_hours": 4,
    "idle_threshold_minutes": 10
  },
  "retention": {
    "enabled": true,
    "episode_retention_days": 90,
    "min_score_to_preserve": 0.8
  },
  "privacy": {
    "audit_logging": true,
    "audit_retention_days": 30
  }
}
```

### Environment Variables

```bash
# Optional: Override database path
export IRIS_MEMORY_DB_PATH=/path/to/memory.db

# Optional: Disable encryption (not recommended)
export IRIS_MEMORY_NO_ENCRYPTION=1
```

---

## First Run

### 1. Initialize Memory System

The memory system initializes automatically on first use:

```python
from backend.memory import MemoryInterface, load_config

# Load configuration
config = load_config("data/memory_config.json")

# Initialize memory interface
memory = MemoryInterface(
    adapter=your_model_adapter,
    db_path=config.db_path,
    biometric_key=derive_key_from_biometric()  # Your key derivation
)

# Database and schema are created automatically
print(f"Memory initialized: {memory.get_memory_stats()}")
```

### 2. Data Migration (If Upgrading)

If you have existing conversation data:

```python
from backend.memory import DataMigration

# Run migration
migration = DataMigration(memory)
result = await migration.run_migration("backend/sessions")
print(f"Migrated {result['episodes_migrated']} episodes")
```

Migration:
- Scans `backend/sessions/*/conversation.json`
- Converts to episodic memory format
- Preserves original files
- Runs once (marker file prevents re-run)

---

## Biometric Key Derivation

The memory system requires a 32-byte encryption key. Example derivation:

```python
import hashlib
import getpass

def derive_key_from_passphrase(passphrase: str = None) -> bytes:
    """Derive 32-byte key from passphrase."""
    if passphrase is None:
        passphrase = getpass.getpass("Enter passphrase: ")
    
    # Use PBKDF2 for secure derivation
    key = hashlib.pbkdf2_hmac(
        'sha256',
        passphrase.encode(),
        salt=b'iris_memory_salt_v1',  # Use unique salt in production
        iterations=100000
    )
    return key

# Derive key
key = derive_key_from_passphrase()
memory = MemoryInterface(adapter, db_path, key)
```

**Production Note**: Use platform-specific biometric APIs (Windows Hello, macOS Touch ID, etc.) rather than passphrases.

---

## Verification

### Test Installation

```bash
# Run memory system tests
pytest backend/memory/tests/ -v
```

### Check Encryption

```python
from backend.memory.db import open_encrypted_memory

# Test database encryption
db = open_encrypted_memory("test.db", key)
db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
db.execute("INSERT INTO test VALUES (1)")
db.commit()
db.close()

# Verify encrypted (should fail without key)
try:
    import sqlite3
    conn = sqlite3.connect("test.db")
    conn.execute("SELECT * FROM test")
    print("WARNING: Database not encrypted!")
except:
    print("OK: Database is encrypted")
```

---

## Troubleshooting

### SQLCipher Not Found

**Error**: `ImportError: No module named 'sqlcipher3'`

**Solution**:
```bash
# macOS
brew install sqlcipher
pip install sqlcipher3

# Linux
sudo apt-get install libsqlcipher-dev
pip install sqlcipher3
```

### Model Download Fails

**Error**: `HTTPError: 403 Forbidden` when downloading embedding model

**Solution**:
```bash
# Set HuggingFace cache directory
export TRANSFORMERS_CACHE=/path/to/cache
export HF_HOME=/path/to/cache

# Or download manually
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

### Database Locked

**Error**: `Database is locked`

**Solution**:
- Check for multiple processes accessing the database
- WAL mode is enabled by default (check disk space)
- Restart the application

### High Memory Usage

**Issue**: Embedding model uses too much RAM

**Solution**:
```python
# Use CPU-only PyTorch
pip install torch --index-url https://download.pytorch.org/whl/cpu

# Or use smaller model (less accurate)
# Edit backend/memory/embedding.py: change model name
```

---

## Performance Tuning

### For Low-Memory Systems

```json
{
  "embedding": {
    "model_name": "paraphrase-MiniLM-L3-v2",
    "embedding_dim": 384
  },
  "compression": {
    "threshold": 0.70
  }
}
```

### For High-Throughput

```json
{
  "compression": {
    "threshold": 0.85
  },
  "distillation": {
    "check_interval_seconds": 600
  }
}
```

---

## Security Best Practices

1. **Never commit encryption keys** - Use environment variables or secure key stores
2. **Regular backups** - Backup `memory.db` and store securely
3. **Audit logging** - Enable `privacy.audit_logging` for compliance
4. **Key rotation** - Plan for periodic key rotation (requires data migration)
5. **Access control** - Limit file permissions on `data/memory.db`

---

## Uninstallation

To completely remove the memory system:

```bash
# Remove database
rm data/memory.db
rm -rf data/audit/

# Remove marker files
rm data/.migration_complete

# Uninstall dependencies
pip uninstall sqlcipher3 sqlite-vec sentence-transformers
```

---

## Getting Help

- **Issues**: Check logs in `logs/memory.log`
- **Documentation**: See `IRIS_Memory_Foundation_Spec.md`
- **Tests**: Run `pytest backend/memory/tests/ -v`

---

## Platform-Specific Notes

### macOS
- May require Xcode Command Line Tools: `xcode-select --install`
- Apple Silicon: Use Rosetta 2 for x86 dependencies if needed

### Linux
- Ensure `libsqlcipher0` is installed system-wide
- Check SELinux/AppArmor if permission errors occur

### Windows
- Use Windows Subsystem for Linux (WSL2) for easier setup
- Or install Visual C++ Redistributable for SQLCipher

---

**Version**: 1.0.0  
**Last Updated**: 2025
