# Disk move — execution report

> **OWNER CORRECTION 2026-09-30 (supersedes Step 2 below):** `data/memory.db` stays the PRIMARY
> application store. `data/memory_config.json` `db_path` was set back to `"data/memory.db"`
> (identical to the committed file); both copies were byte-identical with empty WALs at the
> switch, so no data was lost or merged. `D:\IRIS\data\memory.db` is an unused leftover — delete
> THAT one, never `C:\dev\IRISVOICE\data\memory.db`. MCM pin `pin_f1cb33f20a88`.

Executed 2026-09-30 by the agent, per `disk-move-plan.md`.
Scope: Steps 1-4 (the steps the plan delegates). Steps 0 and 5 are owner-only
(they need a reboot) and were **not** run.

All robocopy invocations returned **exit code 1** (0-7 = success, 8+ = failure).
**Zero files failed to copy in any step.**

---

## Result summary

| # | Payload | Destination | Result |
|---|---|---|---|
| 1 | site-packages (7.207 GB, 99,157 files) | `D:\PythonUser\Python314\site-packages` | copied + verified, switch skipped (D1) |
| 2 | memory.db (6.16 GB) | `D:\IRIS\data\memory.db` | done + verified |
| 3 | HF cache | `D:\hf-cache\huggingface` (not the plan's `D:/cache/...`) | done (D2) |
| 4 | LM Studio models (38.620 GB, 30 files) | `D:\lmstudio\models` | done + verified |

---

## Step 1 — site-packages

Copy **complete and verified**: `D:\PythonUser\Python314\site-packages` now holds
99,157 files / 14,859 dirs / 7.207 GB, matching the source exactly (robocopy exit 1, 0 failed).

**The rename + junction switch was NOT performed.** The plan's precondition 2
was not satisfiable: the MCM MCP server (`C:\Python314\python.exe -m mcm.mcp_cad`,
PID 1948, registered in `~/.claude.json` as `mcm-cad`) holds 8 mapped modules
from that folder:

    _pydantic_core.cp314-win_amd64.pyd   _brotli.cp314-win_amd64.pyd
    win32\_win32sysloader.pyd            win32\win32api.pyd
    win32\win32job.pyd                   pywin32_system32\pywintypes314.dll
    rpds\rpds.cp314-win_amd64.pyd        zstandard\backend_c.cp314-win_amd64.pyd

Windows will refuse the folder rename while those are mapped, so the plan's own
fallback was taken ("skip it and leave it to the owner"). The copy is already
made, so finishing is a 2-minute job.

**To finish Step 1** — close every Python process (including the MCM server /
Claude Code), then from a plain terminal:

    robocopy "C:\Users\midas\AppData\Roaming\Python\Python314\site-packages" "D:\PythonUser\Python314\site-packages" /E /COPY:DAT /R:1 /W:1
    ren "C:\Users\midas\AppData\Roaming\Python\Python314\site-packages" site-packages.old
    mklink /J "C:\Users\midas\AppData\Roaming\Python\Python314\site-packages" "D:\PythonUser\Python314\site-packages"
    python -c "import torch, scipy, onnxruntime; print('ok')"

Rollback: `rmdir` the junction (not the target), then
`ren site-packages.old site-packages`.

---

## Step 2 — memory.db  (verified)

- Copied `memory.db` (6,611,886,080 bytes) to `D:\IRIS\data\memory.db`.
  No `memory.db-wal` / `memory.db-shm` existed at the source (WAL already
  checkpointed); an exclusive-open test confirmed nothing held the file.
- `data/memory_config.json`: `"db_path": "data/memory.db"` became
  `"db_path": "D:/IRIS/data/memory.db"` (forward slashes - JSON-legal, and what the file now holds).
  Backup: `data/memory_config.json.bak-20260930-083203`.

**Verification**

| Check | Source | Destination |
|---|---|---|
| size | 6,611,886,080 | 6,611,886,080 |
| head-1 MB SHA-256 | 799440a7f297c586 | 799440a7f297c586 |
| PRAGMA page_count | 1,614,230 | 1,614,230 |
| PRAGMA freelist_count | 56,957 | 56,957 |
| tables / indexes | 55 / 135 | 55 / 135 |
| memory_chain / episodes rows | 3,811 / 385 | 3,811 / 385 |

`idx_memory_chain_created` is present, so no 7.5-minute index rebuild on boot.

The production chain was traced end to end and every link resolves to D::

    backend/main.py:564             memory = await initialise_memory(adapter=adapter)
    backend/memory/__init__.py:86   db_path = str(resolve_memory_store_path(config_path=...))
    backend/memory/config.py:49-50  if not db_path.is_absolute(): ...   # D:/IRIS/... is absolute, used as-is
    backend/memory/__init__.py:122  initialize_memory_encryption(db_path=db_path, ...)
    backend/gateway/iris_ffi.py:1104  self._ffi.init_core_engine(db_path, key_hex)

`resolve_memory_store_path()` returns `D:\IRIS\data\memory.db` (absolute, exists).
The `"data/memory.db"` defaults in `backend/core/biometric.py:369,517` are never
reached in production — line 122 passes the resolved path explicitly. The
forbidden-path guard (`iris_ffi.py:576`) only rejects `.mcm/` and
`backend/data/`, so the new path passes.

Rollback: set `db_path` back to `data/memory.db`.

---

## Step 3 — HF cache  (plan target changed, see D2)

The plan's premise was out of date. The HF cache was **already moved to the SSD
on 2026-08-30**, to `D:\hf-cache\huggingface` (22 GB), wired up by `HF_HOME` in
the repo's `.env` (which records that the Parakeet checkpoint took 32-35 min to
load from the HDD).

`D:\hf-cache\huggingface/hub` is a **superset** of the C: cache — it already has
`kyutai--pocket-tts`, `kyutai--pocket-tts-without-voice-cloning`,
`nvidia--parakeet-tdt-0.6b-v3`, `Systran--faster-whisper-tiny`, plus 15 more
(`LFM2.5-Encoder-350M`, `F5-TTS`, `whisper-large-v3-turbo`, `CosyVoice3`, ...).
The C: cache's only unique entry is an **aborted** download (a 40-byte
`refs/main`, no weights).

Following the plan literally would have created a *second*, smaller cache:
`backend/memory/embedding.py:562` reads `HF_HOME` (not `HF_HUB_CACHE`), so bare
processes would have used the 2.6 GB copy while the backend (where `.env` wins
in-process) used the 22 GB one — duplicate downloads and drift.

**What was done instead:**

- `HF_HOME` set at **user** scope to `D:\hf-cache\huggingface` (it was
  previously unset at every scope, so bare processes fell back to
  `~/.cache/huggingface` on the HDD — that was the real gap).
- The redundant `D:\cache\huggingface` copy was removed.
- The C: source `C:\Users\midas/.cache/huggingface` is untouched.

`.env` and the user variable now agree on the same 22 GB cache.

**Verification** — `D:\hf-cache\huggingface/hub` contains pocket-tts, parakeet,
LFM2.5-Encoder-350M and faster-whisper-tiny.

Rollback: `setx HF_HOME ""` (or delete the variable in System Properties).

Note: a user env var only affects **new** processes — start the backend from a
new terminal.

---

## Step 4 — LM Studio models  (verified)

- Copied 38.620 GB / 30 files / 33 dirs to `D:\lmstudio\models`. 0 failed.
- Renamed `C:\Users\midas\.lmstudio\models` to `models.old`, then created a
  **directory junction** `C:\Users\midas\.lmstudio\models` pointing at
  `D:\lmstudio\models`.
- `C:\Users\midas/.lmstudio/settings.json`: `downloadsFolder` became
  `D:\lmstudio\models`.
- `data/iris_config.json`: **4** paths repointed (the plan named 2):
  - `inference.local_model_path`
  - `inference.providers["local:LFM2.5-2.6B-QAD-Q4_0"].model_path`
  - `field_values.inference_mode.iris_local_model_path` (extra — also pointed at .lmstudio\models)
  - `field_values.vision.vision_model` (extra — also pointed at .lmstudio\models)

  Backup: `data/iris_config.json.bak-20260930-083505`

**Why the junction (D4):** `backend/agent/local_model_manager.py:722-733`
resolves `MODELS_DIR` at **import time** from `IRIS_MODELS_DIR`, then
`Path.home()/".lmstudio"/"models"`, then `IRISVOICE_ROOT/models/gguf`. Moving the
folder without a junction would have silently fallen back to
`C:\dev\IRISVOICE\models\gguf`, which holds **no GGUF files at all** (only
`.iris_model_settings.json`) — local model discovery would have broken.
`set_models_directory()` is only called when the UI *pushes* a settings change
(`iris_gateway.py:1489+`), not at cold start, so config alone would not fix it.

**Verification** — all 3 referenced GGUFs exist on D: with correct sizes
(1,593,894,944 / 1,915,306,144 / 1,674,454,240 bytes); `~/.lmstudio/models`
resolves through the junction to `D:\lmstudio\models`.

Rollback: point `downloadsFolder` and the 4 `iris_config.json` paths back to
`C:\Users\midas\.lmstudio\models/...`, then `rmdir` the junction and
`ren models.old models`.

---

## Deviations from the plan

| # | Deviation | Why |
|---|---|---|
| D1 | Step 1 switch skipped | MCM MCP server (PID 1948) holds 8 mapped modules in site-packages; the rename cannot succeed. Plan's own fallback. Copy is done. |
| D2 | Step 3 destination is `D:\hf-cache\huggingface`, not `D:\cache\huggingface` | That cache already existed (22 GB, moved 2026-08-30 via .env) and is a superset. Pointing HF_HOME at it avoids a second cache and duplicate downloads. |
| D3 | Step 4 repointed 4 config paths, not 2 | `field_values.inference_mode.iris_local_model_path` and `field_values.vision.vision_model` also pointed into .lmstudio\models and would have broken. |
| D4 | Step 4 added a junction at `~/.lmstudio/models` | `MODELS_DIR` is resolved at import time from that path; without the junction, model discovery falls back to an empty dir. |
| D5 | Live backend boot not completed | `start-backend.py` purges `backend/__pycache__` (66 dirs) on every launch, which trips the environment's bulk-delete guard and kills the process. Unrelated to the move. |

---

## Not done — owner steps

- **Step 0** (cold measurement) — needs a reboot.
- **Step 5** (`run_evals.py --group coding --record-standard`) — needs a reboot.
- **The live backend check** for Step 2, blocked by D5. Since Step 0 reboots and
  boots the backend cold anyway, that boot is the natural integration test —
  look for `[MemoryInterface] Caducean C++ engine initialised` and confirm turns
  recall episodes.

## Space reclaimed on C: (after verification)

Delete these once satisfied, in this order:

| Path | Frees |
|---|---|
| `C:\Users\midas\.lmstudio\models.old` | 38.6 GB |
| `C:\dev\IRISVOICE\data/memory.db` | 6.2 GB |
| `C:\Users\midas/.cache/huggingface` (now unused) | 2.6 GB |
| `...\Python314\site-packages.old` (after the Step 1 switch) | 7.2 GB |
| **total** | **~54.6 GB** |

C: currently has about 30 GB free.

## Files changed

| File | Change | Backup |
|---|---|---|
| `C:\dev\IRISVOICE\data/memory_config.json` | db_path to `D:\IRIS\data\memory.db` | `.bak-20260930-083203` |
| `C:\dev\IRISVOICE\data/iris_config.json` | 4 model paths to `D:\lmstudio\models/...` | `.bak-20260930-083505` |
| `C:\Users\midas/.lmstudio/settings.json` | downloadsFolder to `D:\lmstudio\models` | `.bak-20260930-083505` |
| `HF_HOME` (user env var) | unset to `D:\hf-cache\huggingface` | - |
| `C:\Users\midas\.lmstudio\models` | dir became junction to `D:\lmstudio\models` | `models.old` |
