# Spec: Dilithium Key → Memory DB Wallet (Secure Key Custody)

> Status: Design (Phase 1 implementable, Phase 2 specified)
> Notation: EARS (Easy Approach to Requirements Syntax)
> Related: `dilithium-memory-migration` skill, `backend/core/biometric.py`

## Summary

IRIS Voice ties its long-term memory database (`data/memory.db`, SQLCipher AES-256)
to the user's Post-Quantum (Dilithium3) identity private key generated in
`iris-launcher`, deriving a 32-byte memory key via HKDF-SHA256. Today the key is
only loadable from an env var (`IRIS_DILITHIUM_KEY`) or plaintext file
(`IRIS_DILITHIUM_KEY_FILE`), and `sqlcipher3` is not installed, so the DB is
effectively unencrypted and the raw key is exposed at rest.

This spec introduces a **wallet-style custody model**:

- **Phase 1 (now):** store the key in the **OS keychain** (cross-platform:
  Windows Credential Manager, macOS Keychain, Linux Secret Service), never in
  env/plaintext. Unlock via OS login, a user password, or a TOTP
  (Google Authenticator) factor; cache in the keychain after first unlock so the
  user is not prompted every time. No passphrase is ever persisted by the app.
- **Phase 2 (later):** move to an **isolated key service / IPC wallet** where the
  raw key never enters the backend process. The `KeyProvider` abstraction makes
  both interchangeable.

A **recovery path** (portable encrypted backup blob + restore) is defined so
losing the keychain entry does not mean losing memory access.

## Goals

- Store the Dilithium private key in the OS keychain; never in env/plaintext.
- Work identically on **Windows, macOS, and Linux** (headless-safe fallback).
- Support unlock via **OS keychain, user password, or TOTP (Google Authenticator)**,
  with "unlock once → cached" behavior.
- Persist **no passphrase/TOTP secret** anywhere (agent process or external actors
  must not be able to grab one).
- Provide a **recovery path** (encrypted, portable backup + restore).
- Define a `KeyProvider` abstraction that is IPC-wallet-ready.
- Preserve dev/CI ergonomics via an explicit opt-in env provider.

## Non-Goals

- Phase 2 IPC key service is **specified but not implemented** now.
- TPM / Windows Hello / Secure-Enclave *non-extractable* key generation is Phase 2+.
- No change to HKDF derivation or the SQLCipher schema.
- The recovery passphrase is **user-held**, not managed by the app.

---

## Requirements (EARS)

### Capability: Key Provider Selection

- **R1 (Ubiquitous):** THE SYSTEM shall resolve the Dilithium private key through a
  pluggable `KeyProvider` abstraction.
- **R2 (Event-driven):** WHEN the backend initializes memory encryption, THE SYSTEM
  shall select a `KeyProvider` per the resolved configuration order.
- **R3 (State-driven):** IF `IRIS_KEY_PROVIDER` is `os_keychain`, THEN THE SYSTEM
  shall use the OS keychain provider as primary.
- **R4 (State-driven):** IF `IRIS_DILITHIUM_KEY` or `IRIS_DILITHIUM_KEY_FILE` is set,
  THEN THE SYSTEM shall use the environment provider (dev/CI opt-in) and log a
  warning that a plaintext key source is active.
- **R5 (State-driven):** IF no provider yields a key, THEN THE SYSTEM shall fall back
  to the dev pseudo-key chain (env → keychain → machine-derived) so the DB connection
  is never lost.

### Capability: OS Keychain Storage (Phase 1, cross-platform)

- **R6 (Ubiquitous):** THE SYSTEM shall store/retrieve the Dilithium private key via
  the platform keychain appropriate to the OS:
  - Windows → Credential Manager (`win32cred` / DPAPI)
  - macOS → Keychain Services (`keyring` / Security framework)
  - Linux → Secret Service (GNOME Keyring / KeePassXC via `keyring`)
- **R6.1 (State-driven):** IF the OS is Linux and no Secret Service daemon is
  available, THEN THE SYSTEM shall fall back to an **encrypted key file**
  (Argon2id-derived key, versioned prefix) with the same write-probe-read-delete
  verification, and shall **NOT** fall back to the kernel session keyring.
- **R6.2 (State-driven):** IF a keychain write succeeds but read-back verification
  fails (locked keychain, enterprise policy block, unsigned-binary ACL rejection),
  THEN THE SYSTEM shall report keychain custody unavailable and fall back to the
  pseudo-key chain — never silently accept a failed write.
- **R7 (Ubiquitous):** THE SYSTEM shall never write the Dilithium private key to an
  env var, `.env`, or plaintext file.
- **R8 (Event-driven):** WHEN the key is stored, THE SYSTEM shall perform a
  **write-probe-read-delete** verification (write probe → read back → assert equality
  → delete probe) before reporting success.
- **R9 (State-driven):** IF the keychain write succeeds but read-back verification
  fails, THEN THE SYSTEM shall report custody unavailable and fall back (never silent
  accept).
- **R10 (Ubiquitous):** THE SYSTEM shall scope the keychain entry to the OS user
  account under service `iris-voice` with a versioned key name
  (`dilithium-private-key:v1`).
- **R11 (Ubiquitous):** THE SYSTEM shall store the key as a hex string under the
  versioned name to allow future format migration.

### Capability: Unlock (password / TOTP / keychain cache)

- **R12 (Ubiquitous):** THE SYSTEM shall support unlocking the stored Dilithium key
  via one of: OS keychain (no input), a user password, or a TOTP factor
  (Google Authenticator / RFC 6238).
- **R13 (Event-driven):** WHEN the user unlocks via password or TOTP, THE SYSTEM
  shall derive the decryption key from the factor, decrypt the key blob, and cache
  the decrypted key in the OS keychain.
- **R14 (State-driven):** IF the key is already cached in the OS keychain, THEN THE
  SYSTEM shall unlock without prompting for password or TOTP ("unlock once").
- **R15 (Ubiquitous):** THE SYSTEM shall never persist the unlock password or TOTP
  secret; both are discarded (zeroized) immediately after deriving the decryption key.
- **R16 (State-driven):** IF an incorrect password or TOTP is supplied, THEN THE
  SYSTEM shall fail the unlock and shall not cache or expose the key.
- **R17 (Ubiquitous):** THE SYSTEM shall treat the cached key in the OS keychain as
  the "unlocked" state; the password/TOTP is only required on first unlock or after
  the keychain entry is cleared.

### Capability: No Passphrase At Rest

- **R18 (Ubiquitous):** THE SYSTEM shall not persist any user passphrase, password,
  TOTP secret, or derived secret used to protect the key (env, file, keychain, or
  registry).
- **R19 (State-driven):** IF keychain access requires OS authentication, THEN THE
  SYSTEM shall rely on the OS credential (not a stored passphrase) to decrypt the key
  at runtime.

### Capability: Memory Key Derivation

- **R20 (Ubiquitous):** THE SYSTEM shall derive the 32-byte memory key from the
  Dilithium private key via HKDF-SHA256 (`DEFAULT_SALT`, info
  `b"iris-voice-memory-key-v1"`).
- **R21 (Event-driven):** WHEN the memory key is derived, THE SYSTEM shall pin it in
  memory where the OS allows (e.g., `VirtualLock`) and zeroize it after use to reduce
  swap exposure.

### Capability: Migration

- **R22 (Event-driven):** WHEN `migrate_memory_db_key()` runs with a Dilithium key
  available, THE SYSTEM shall re-encrypt `data/memory.db` in place via SQLCipher
  `PRAGMA rekey` and return `"migrated"`.
- **R23 (State-driven):** IF the DB is already Dilithium-protected, THEN THE SYSTEM
  shall return `"already-dilithium"` and make no changes.
- **R24 (State-driven):** IF `sqlcipher3` is unavailable, THEN THE SYSTEM shall return
  `"failed:sqlcipher3-unavailable"` and leave the DB untouched.
- **R25 (Ubiquitous):** THE SYSTEM shall make `migrate_memory_db_key()` idempotent and
  fail-safe (any error → `"failed:<ErrorType>"`, never corrupt the DB).

### Capability: Recovery

- **R26 (Event-driven):** WHEN the user requests a backup, THE SYSTEM shall export the
  Dilithium private key as an encrypted, versioned backup blob protected by a
  user-chosen recovery passphrase.
- **R27 (Ubiquitous):** THE SYSTEM shall never store the recovery passphrase; it is
  user-held.
- **R28 (Event-driven):** WHEN the user imports a backup blob and supplies the
  recovery passphrase, THE SYSTEM shall decrypt it and re-establish keychain custody.
- **R29 (Ubiquitous):** THE SYSTEM shall make the backup blob **portable across OSes**
  (self-contained encrypted file), enabling recovery on any supported platform.
- **R30 (State-driven):** IF the keychain entry is lost (OS reinstall, new device,
  cleared keychain), THEN THE SYSTEM shall support restore from the encrypted backup
  blob as the recovery path.
- **R31 (Event-driven):** WHEN a backup is written, THE SYSTEM shall apply the same
  write-probe-read-delete verification to the backup file.

### Capability: IPC Wallet Readiness (Phase 2, specified now)

- **R32 (Ubiquitous):** THE SYSTEM shall define an `IPCKeyProvider` (same `KeyProvider`
  contract) that requests the derived memory key from a local key service over a
  localhost transport, receiving only the 32-byte memory key.
- **R33 (State-driven):** IF `IRIS_KEY_PROVIDER` is `ipc`, THEN THE SYSTEM shall obtain
  the memory key from the key service and shall never receive the raw Dilithium
  private key into the backend process.
- **R34 (Ubiquitous):** THE SYSTEM shall keep Phase 1 (keychain) and Phase 2 (IPC)
  providers interchangeable behind the same abstraction with **no changes** to
  `initialize_memory_encryption` or `migrate_memory_db_key`.

### Non-Functional

- **R35 (Performance):** THE SYSTEM shall complete keychain load + derivation within the
  backend startup budget (no blocking prompts).
- **R36 (Security):** THE SYSTEM shall surface the active key mode
  (`dilithium-keychain` / `dilithium-env` / `dilithium-ipc` / `pseudo`) in logs/status
  so callers never silently downgrade.

---

## Acceptance Criteria

- **AC1:** `OSKeychainProvider.store_key` + `retrieve_key` round-trips identical bytes
  on Windows, macOS, and Linux (Secret Service); the write-probe-read-delete cycle
  succeeds on each.
- **AC2:** On Linux without a Secret Service daemon, the encrypted-file fallback
  succeeds and the kernel session keyring is **not** used.
- **AC3:** `load_dilithium_private_key()` returns the keychain key when env is unset and
  the key is present; returns `None` when keychain empty and env unset.
- **AC4:** A simulated read-back failure makes `store_key` return `False` and the system
  falls back to pseudo-key (no silent accept).
- **AC5:** Unlock via password decrypts and caches the key in the keychain; a second
  load requires no password (R14). An incorrect password fails and caches nothing
  (R16).
- **AC6:** Unlock via TOTP (Google Authenticator) decrypts and caches; an incorrect
  TOTP code fails and caches nothing.
- **AC7:** The unlock password and TOTP secret are absent from process memory after
  unlock (zeroized) and never written to disk/env (R15, R18).
- **AC8:** `initialize_memory_encryption()` with a keychain-stored Dilithium key returns
  the HKDF key; that key reopens the DB; the pseudo-key raises on the migrated DB.
- **AC9:** After setup, no `.env`/plaintext file contains the Dilithium key hex (repo
  `grep` returns nothing).
- **AC10:** `migrate_memory_db_key()` returns `"migrated"` then `"already-dilithium"`;
  returns `"failed:sqlcipher3-unavailable"` when `sqlcipher3` absent.
- **AC11:** Backup export produces a portable encrypted blob; import with the correct
  recovery passphrase restores keychain custody; import with a wrong passphrase fails.
- **AC12:** `IRIS_KEY_PROVIDER=ipc` routes through `IPCKeyProvider` with **no**
  modification to `initialize_memory_encryption`.

---

## Technical Design

### 4.1 KeyProvider abstraction

```python
class KeyProvider(Protocol):
    name: str
    def load_private_key(self) -> Optional[bytes]: ...
    def store_private_key(self, key: bytes) -> bool: ...   # setup only
    def unlock(self, factor: Optional[dict]) -> bool: ...   # password / totp / None
```

Implementations: `EnvDilithiumProvider` (dev/CI), `OSKeychainProvider` (Phase 1),
`IPCKeyProvider` (Phase 2 stub).

### 4.2 OSKeychainProvider (cross-platform)

- **Windows:** `win32cred` (Credential Manager), `CRED_TYPE_GENERIC`, target
  `iris-voice:dilithium-private-key:v1`, `CRED_PERSIST_LOCAL_MACHINE`.
- **macOS:** `keyring` → Keychain Services (login keychain).
- **Linux:** `keyring` → Secret Service (GNOME Keyring / KeePassXC). If no daemon,
  fall back to an **encrypted key file**: Argon2id(passphrase=None → machine-bound
  random key wrapped by OS keychain, or a user passphrase) with versioned prefix
  `dilithium-private-key:v1:`; never kernel keyutils.
- `store_private_key`: write hex → **write-probe-read-delete** → return bool.
- `load_private_key`: read → hex → bytes; any failure → `None`.
- No passphrase; OS login (or unlock factor) decrypts at runtime.

### 4.3 Unlock flow

The key blob at rest is encrypted. Decryption requires a factor:

1. **OS keychain** — key already decrypted in keychain → no input (R14).
2. **Password** — user inputs password once → `scrypt`/`Argon2id` derives the
   decryption key → decrypt → cache decrypted key in OS keychain (R13). Password is
   zeroized after derive (R15).
3. **TOTP (Google Authenticator)** — user inputs current RFC 6238 code → code-derived
   key decrypts the blob → cache in keychain (R13). TOTP secret stays on the user's
   phone, never in the app (R15, R18).

After first unlock the key is cached in the OS keychain, so subsequent launches need
no password/TOTP (R17). The password/TOTP are **user-held, never persisted**.

### 4.4 Recovery flow

- **Backup:** `export_backup(passphrase)` → encrypt the Dilithium private key (with a
  random salt + versioned header) to a self-contained file the user stores safely.
  Passphrase is user-held, never stored (R27). Write-probe-read-delete on the file
  (R31).
- **Restore:** `import_backup(blob, passphrase)` → decrypt → re-establish keychain
  custody (R28). Portable across OSes (R29). This is the recovery path when the
  keychain entry is lost (R30). `iris-launcher` identity backup remains the primary
  user-facing backup UX; the encrypted blob is the portable artifact.

### 4.5 Refactor `load_dilithium_private_key`

Resolve provider by config; default order: env (if set, dev opt-in, logs warning) →
`os_keychain` → `None`. `derive_memory_key_from_dilithium` unchanged.
`initialize_memory_encryption` calls the resolved provider instead of reading env
directly.

### 4.6 Migration (API unchanged)

`migrate_memory_db_key` is already idempotent/fail-safe; it uses the provider-resolved
key. Requires `sqlcipher3` installed + backend stopped during `rekey`.

### 4.7 IPCKeyProvider (Phase 2 stub)

Interface only now: connects to `\\.\pipe\iris-key` (Windows) / Unix socket; sends
`derive_memory_key`; receives 32-byte key. Raw Dilithium key stays in the key-service
process (recommended to live as an `iris-launcher` key mode).

---

## Security / Threat Model

- **Blast radius:** Dilithium private key (tier-1, keychain) is distinct from the
  derived memory key (ephemeral). Compromising the memory key does not expose the
  Dilithium key.
- **No passphrase at rest:** satisfies the constraint — the agent process cannot read a
  password/TOTP that does not exist. Only the *decrypted key* is cached in the OS
  keychain after unlock.
- **Unlock factors:** password and TOTP are user-held secrets used transiently and
  zeroized; they are never written to disk, env, or keychain.
- **Phase 1 residual risk:** the backend (same OS user) *can* call `CredRead` and
  materialize the raw key in RAM. **Phase 2 IPC removes it** (raw key never enters the
  backend).
- **External forces:** the Credential Manager / Keychain entry is OS-encrypted and
  scoped to the user account; other users/processes cannot read it.
- **Recovery:** losing the keychain entry is recoverable via the encrypted backup blob;
  losing both the keychain entry *and* the backup passphrase = losing memory access (by
  design — user holds the passphrase).

---

## Risks / Open Questions

1. **Persistence scope (Windows):** `CRED_PERSIST_LOCAL_MACHINE` (survives
   non-interactive, single-user desktop) vs `CRED_PERSIST_ENTERPRISE` — recommend
   `LOCAL_MACHINE`.
2. **Linux headless:** servers without a Secret Service daemon need the encrypted-file
   fallback; the fallback should prefer a machine-bound key wrapped by the OS keychain
   over a user passphrase when possible.
3. **Key service host (Phase 2):** should live inside `iris-launcher` (already the
   identity app) or a standalone daemon — recommend `iris-launcher` key mode.
4. **TOTP enrollment:** Google Authenticator requires a one-time secret provisioning
   (QR / otpauth URI) during setup; the secret lives on the phone, never in the app.
5. **sqlcipher3 prerequisite:** must be installed (Phase 1 blocker) before migration
   can re-encrypt; may need the system SQLCipher lib on Windows.
6. **Recovery UX:** must clearly tell the user that the backup passphrase is the only
   recovery and is not stored by IRIS.
