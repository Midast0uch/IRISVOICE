---
name: dilithium-memory-migration
description: >
  Runbook for migrating the IRIS Voice memory database (data/memory.db) from the
  development pseudo-key to the Post-Quantum (Dilithium) identity key, and for
  understanding the Dilithium -> memory-key wiring. Trigger when iris-launcher
  has generated a real Dilithium key and we want the memory DB protected by it,
  or when debugging memory-unlock / "quantum key" behavior.
---

# Dilithium -> Memory Key Migration

## What this is
The memory DB (`data/memory.db`, sqlcipher3 AES-256) is unlocked by a 32-byte key.
During development that key is a **pseudo-key** derived from `IRIS_MEMORY_KEY`
(env) / OS keychain / machine identity (see `backend/core/biometric.py`).

The intended "quantum key unlocks memory" path: the **Dilithium3 Post-Quantum
identity private key** generated in `iris-launcher` (`FirstRunPage.tsx`,
`IdentityPage.tsx`) becomes the sole source of the memory key via **HKDF-SHA256**
(`derive_memory_key_from_dilithium`).

## Wiring (already in place)
- `backend/core/biometric.py`
  - `derive_memory_key_from_dilithium(dilithium_priv)` -> 32-byte key (HKDF-SHA256, `DEFAULT_SALT`, info `b"iris-voice-memory-key-v1"`).
  - `load_dilithium_private_key()` -> reads `IRIS_DILITHIUM_KEY` (hex env) or `IRIS_DILITHIUM_KEY_FILE` (raw bytes). Returns `None` when absent (dev mode).
  - `initialize_memory_encryption(db_path, config_path, force_pseudo=False)`:
    - If `force_pseudo` is False AND a Dilithium key is present -> derive + return the Dilithium key (opt-in, primary path).
    - Else falls through to env -> keychain -> machine-derived pseudo-key.
  - `migrate_memory_db_key(db_path, config_path)` -> re-encrypts the existing DB in place via SQLCipher `PRAGMA rekey`. Idempotent, fails safe. Returns one of:
    - `"migrated"` — re-keyed from pseudo to Dilithium.
    - `"already-dilithium"` — DB already Dilithium-protected.
    - `"no-dilithium"` — no Dilithium key configured; nothing done.
    - `"failed:<ErrorType>"` — open/rekey error; DB left untouched.
    - `"failed:sqlcipher3-unavailable"` — no sqlcipher3; nothing to re-key.
- `backend/memory/__init__.py` `get_memory_interface()`:
  - Derives the key (Dilithium path attempted). If the primary key cannot OPEN the
    existing DB, it falls back to `force_pseudo=True` so the connection is never lost.

## Migration runbook (when the REAL Dilithium key lands)
1. **Export the key from iris-launcher.** After the user creates their identity in
   `FirstRunPage`/`IdentityPage`, export the Dilithium private key to one of:
   - env `IRIS_DILITHIUM_KEY=<hex>` (dev / CI), or
   - file `IRIS_DILITHIUM_KEY_FILE=<path>` (raw bytes).
2. **Stop the backend** (so `data/memory.db` is not open).
3. **Run the one-time migration** (Python, venv):
   ```python
   from backend.core import biometric
   print(biometric.migrate_memory_db_key(db_path="data/memory.db"))
   # expect: "migrated"
   ```
4. **Verify**:
   ```python
   from backend.core import biometric
   from backend.memory.db import open_encrypted_memory
   key = biometric.derive_memory_key_from_dilithium(biometric.load_dilithium_private_key())
   open_encrypted_memory("data/memory.db", key).close()          # must succeed
   open_encrypted_memory("data/memory.db", biometric.initialize_memory_encryption(force_pseudo=True)).close()
   # must RAISE RuntimeError ("file is not a database") -> old pseudo key no longer works
   ```
5. **Restart the backend.** `initialize_memory_encryption` now derives the key from
   Dilithium automatically; the pseudo-key is only a fallback if the Dilithium key
   is absent or fails.

## Safety / rollback
- `migrate_memory_db_key` is idempotent and never corrupts the DB: on any failure it
  returns `"failed:..."` and leaves the DB pseudo-encrypted.
- Before migrating in production, back up `data/memory.db` (+ `-wal`/`-shm`).
- If migration fails, the DB stays pseudo-protected; fix the cause and re-run, or
  restore the backup.
- Dev pseudo-key remains the safety net so `data/memory.db` is always openable during
  development (no lost connection).

## Gotchas
- sqlcipher3 must be installed (`pip show sqlcipher3`); without it the DB is plaintext
  and `PRAGMA rekey` is a no-op (`"failed:sqlcipher3-unavailable"`).
- `PRAGMA rekey` re-encrypts in place — do NOT run it while the backend holds the DB open.
- The Dilithium key is the ONLY thing that can reopen a migrated DB. Losing it = losing
  memory access (by design). Store it via iris-launcher's identity backup.

## Tests
- `backend/memory/tests/test_dilithium_memory_key.py` — key derivation, load paths, fallback.
- `backend/memory/tests/test_dilithium_rekey.py` — migration helper (rekey + old key fails,
  no-dilithium no-op, already-dilithium idempotent, sqlcipher3-unavailable fails safe).
