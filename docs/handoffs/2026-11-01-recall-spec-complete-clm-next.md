# Handoff -- 2026-11-01 -- memory-recall-reach COMPLETE; next is specs/clm-memory

Read this with `AGENTS.md`, `.mcm/GOALS.md` and
`docs/audits/2026-09-29/PROGRESS.md`. This file covers only what the last
session changed and what the next agent must not re-litigate.

## 1. Where things stand

`specs/memory-recall-reach` is **72/72 tasks**, TG-10 ticked on live evidence.

Post-reboot gate (2026-11-01, backend fresh, encrypted store):

| check | result |
|---|---|
| `evals/run_evals.py --group memory` | **3/3 PASS** (reply_s 37 / 56 / 19; ask 4.1 / 3.9 / 5.4 s) |
| `evals/probe_conflict.py` immediately after | **BT-W10-2 PASS** |
| `STANDARDS` | no regression |
| `database is locked` warnings | 0 |
| contract suite (chunk FTS, recall filters, turn-start, routing) | 78 passed |

Evidence: `evals/results/` (two 20261031 files and the 2026-11-01 run),
`specs/memory-recall-reach/tasks.md` (TG-10 note).

## 2. What the last session changed (do not redo)

### Memory store, encryption, native engine

- Live store: `D:\IRIS\store\memory.db` (`data/memory_config.json` `db_path`).
  SQLCipher-encrypted 2026-10-31 with the owner's 12-word passphrase:
  `key = sha256(" ".join(phrase.split()).lower())`, kept in Windows Credential
  Manager as `IRIS_Memory_Foundation / memory_encryption_key`.
- `backend/memory/db.py` opens it with the RAW key form
  (`PRAGMA key="x'<hex>'"`). A passphrase-form key cannot open it.
- An encrypted connection is a `sqlcipher3.Connection` SUBCLASS carrying
  `store_path` (a C connection has no `__dict__`), with the same per-thread read
  routing as `AppStoreConnection`. Without it `app_write` bypassed the native
  writer and every memory event failed with `database is locked`.
- `iris_core.dll` was rebuilt against `e_sqlcipher.dll` (SQLCipher 4 + FTS5),
  vendored in `src-tauri/src/iris_core/third_party/sqlcipher/`; the old DLL is
  `backend/native/iris_core.dll.bak-20261031`. Windows needs
  `os.add_dll_directory` (done in `iris_ffi.py`) because it does not search a
  module's own directory for imports.
- All memory copies are encrypted: the pre-SSD store, the 6.6 GB archive
  (`D:\IRIS\data\_archive\memory-2026-09-30.enc.db`), the pre-int8 backup and a
  rollback copy. No plaintext memory DB remains on D: or the repo `data/`.

### Release-mode key source (built, OFF)

- `key_source` in `data/memory_config.json`: `"keychain"` (current) or
  `"launcher"` (fail closed; `IRIS_MEMORY_PASSPHRASE`). Dashboard fallback:
  `GET /api/memory/key-status`, `POST /api/memory/unlock`, UI card
  `components/dashboard/MemoryKeyUnlockCard.tsx`.
- Contract: `backend/tests/contract/test_memory_key_source_contract.py` (10).
- To flip: `KeyStorage.delete_key()`, set `key_source="launcher"`, have
  iris-launcher pass the env var on spawn (its `main.rs` does not yet).

### Recall latency (the replies were 6.3-9.4 s, now 3.9-5.4 s)

- `chunk_fts.search` applied session/type/zone filters INSIDE the FTS join: 1.66 s
  filtered vs 0.009 s unfiltered. It now takes a wider unfiltered match and
  filters those rowids in one lookup: 0.013-0.14 s. Trade-off: a filtered search
  considers the top 400 global matches, not every match.
- The exact-word leg runs even when the reach index is cold, and the one-slot
  keyword guarantee is applied AFTER `memory_rank.LIVE` (which re-sorts).
- Bounded `app_flush(2.0)` before `turn_start_prior_memory` and before
  `_assemble_direct_context`, so the previous turn's queued rows are visible.

### BT-W10-2 (newest fact wins) -- the cause was harness hygiene

- A crashed probe never cleaned up; its fact answered every later run. The probe
  now pre-cleans eval memory/chats and the whole `fern-alpha-`/`fern-bravo-`
  prefix, and its conversation titles carry the run id.
- The T42 user row carries `thread_id = conversation id`, `session_id = NULL`,
  so `_retire_eval_memory` could not find an eval's last fact.
  `_retire_eval_chats` now deletes `memory_chain` rows for eval conversation ids.
- `_dedupe_fact_lines` only knew `_same_fact_text` shapes. It now also accepts
  >= 0.8 token overlap and keeps the newest; the cross-session chunk leg carries
  timestamps (`retrieve_context_chunks(with_meta=True)`) so the older statement
  is dropped.

### File recall (REQ-9 W3/W4)

- Image OCR via RapidOCR on the existing onnxruntime; audio/video via ffmpeg ->
  16 kHz mono -> faster-whisper. Both lazy and fail as `ExtractionError`.
- `pypdf`, `python-docx`, `openpyxl`, `rapidocr-onnxruntime` installed into
  `.venv` (the venv lacked the first three).

### Memory level backfill (REQ-11)

- `backend/memory/levels.py` `_write` used a bare `conn.execute` with NO commit
  when the native writer did not own the file, so the whole backfill vanished on
  exit. Fixed: always `app_write`.
- Rebuilt and PERSISTED: `thread_context` 3,168 rows / 61,019 chunks covered,
  L1 405 KB vs 7.81 MB = 19.3x; `episodes` 232/232 with vectors.

### Recall defects from the earlier list (D1-D7)

- `forget` stales every chain node type and keeps LIKE metacharacters safe; a
  memory-deletion claim with no successful `forget` event is rewritten at the
  reply exit; the tool menu is parity with the registry; thread delete reports
  `chain_purged` / `chain_rows_removed`.

## 3. Memory system state (measured 2026-11-01)

| table | rows |
|---|---|
| `memory_chain` | 13,382 |
| `context_chunks` | 61,018 |
| `thread_context` | 3,168 |
| `episodes` | 232 (232 with `vec_i8`) |
| `mycelium_landmarks` | 4,136 |
| `mycelium_pins` | 5 |
| `file_nodes` | 5,247 |

Journal mode WAL, 128 MB cache on encrypted connections.

## 4. Known open issues (not fixed)

1. **A cold-run TTS wedge killed the backend once.** Log:
   `[TTSManager] Synthesis exceeded its 32s budget for 17 chars -- worker is
   wedged, restarting`, then the process exited and the eval's `m02` got
   `ConnectionResetError`. The gate was re-run and passed, but this is a real
   crash path.
2. **Boot-time snapshot warm-up warning** (`TypeError: tuple indices must be
   integers`). It happens once at boot; the first request computes instead and
   the snapshot works (2,001 events). Not explained.
3. `retrieve_context_chunks` candidate fetch is ~0.9 s under load (17 ms in a
   quiet process).
4. Chat stores are still plaintext: `data/conversations.db`,
   `data/databases/conversation_contexts.db`. They are opened with plain
   `sqlite3`; encrypting them needs the same treatment as the memory store.
5. `key_source="launcher"` is implemented but OFF, and the launcher does not yet
   pass `IRIS_MEMORY_PASSPHRASE`.

## 5. Next: specs/clm-memory

Read all three files of `specs/clm-memory/` plus
`docs/Design/CLM_MYCELIUM_DESIGN_BRIEF.md`. The CLM inherits from this spec:

- three addressable levels (`thread_context` L1, `episodes` L2, chunks L3), one
  codec (`vector_quant`), incidence to the phase plane, an immutable record
  layer, and an L2 vector already in `episodes`;
- two planes (REQ-10), the codec (REQ-4), the Kyudo decay law (REQ-5) and "no new
  dependency without the owner" are settled - do not re-litigate them.

Start the CLM work only after the store is quiet and the gate is green:

```
.\.venv\Scripts\python.exe start-backend.py        # detached
# wait for http://127.0.0.1:8090/health -> 200
.\.venv\Scripts\python.exe evals\load_tool_model.py
.\.venv\Scripts\python.exe evals\run_evals.py --group memory
.\.venv\Scripts\python.exe evals\probe_conflict.py
.\.venv\Scripts\python.exe -m backend.memory.levels --episodes   # if the derived tables read 0
```

## 6. Repo state

Nothing is committed. The diff includes the memory/agent files named above,
`specs/memory-recall-reach/tasks.md`, `specs/memory-recall-reach/requirements.md`,
`evals/run_evals.py`, `evals/probe_conflict.py`, the vendored SQLCipher files,
`backend/native/iris_core.dll`, and the new contract tests
(`test_memory_key_source_contract.py`, `test_memory_encryption_roundtrip_contract.py`,
`test_memory_deletion_claim_contract.py`, `test_tool_menu_parity_contract.py`,
`test_thread_delete_chain_purge_contract.py`).

Stage only code files; `backend/data/*` changes are pre-existing and unrelated.
