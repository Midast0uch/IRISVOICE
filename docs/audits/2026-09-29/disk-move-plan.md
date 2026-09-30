# Disk move plan — IRIS hot data from the C: hard disk to the D: NVMe SSD

Owner decision 2026-09-30: "Plan a move to D:". **Nothing in this plan runs
automatically.** The owner runs each step with the backend and frontend
stopped. Every step is reversible (rollback listed per step).

## Why (measured 2026-09-29/30)

| Drive | Hardware | Size | Free |
|---|---|---|---|
| C: | Toshiba DT01ACA100, 7200 rpm **hard disk** (SATA) | 930 GB | **28 GB (97% full)** |
| D: | PNY CS3030, **NVMe SSD** | 931 GB | 755 GB |

A nearly full hard disk is fragmented and pays ~10 ms per cold random read.
Every cold-start number traced in the execution audit is that cost:

| Symptom | Cold | Warm (same files cached) |
|---|---|---|
| TTS worker imports (`torch` + `pocket_tts`) | **110 s** idle, 227 s under load | **5.1 s** |
| `memory_chain` widest recall sort (before its index) | 119 s | — |
| `calculate_eml` counts (before their index) | 16-84 s per DER step | 0.26 s |
| `pytest` start inside a turn | 96-110 s | ~2.5 s |
| one-time `idx_memory_chain_created` build | ~7.5 min | — |

The indexes fixed the two query plans; the disk is what remains.

## What to move (by impact)

| # | Folder | Size | Used by | How |
|---|---|---|---|---|
| 1 | `C:\Users\midas\AppData\Roaming\Python\Python314\site-packages` | 7.2 GB | every Python start (torch, scipy, onnxruntime) | move + directory junction |
| 2 | `C:\dev\IRISVOICE\data\memory.db` (+ `-wal`, `-shm`) | ~6.6 GB | every turn (recall, ledger, physics) | move + `db_path` in `data/memory_config.json` |
| 3 | `C:\Users\midas\.cache\huggingface` | 2.6 GB | Pocket-TTS weights, encoders | move + `HF_HOME` user variable |
| 4 | `C:\Users\midas\.lmstudio\models` | 38.6 GB | the local tool model (LFM2.5-2.6B GGUF) | LM Studio setting + `local_model_path` in `data/iris_config.json` |

Do NOT move the repo itself (`C:\dev\IRISVOICE`): Claude Code's project memory
and the MCM database path (`MCM_DB_PATH`) are keyed to it. Do NOT junction
`.next` (CLAUDE.md: it broke Turbopack).

## Step 0 — measure BEFORE (cold)

Reboot (clears the OS file cache), start nothing else, then run:

```
python -c "import time; t=time.monotonic(); import torch; a=time.monotonic(); from pocket_tts import TTSModel; print('torch', round(a-t,1), 's  pocket_tts', round(time.monotonic()-a,1), 's')"
```

(2026-09-29 baseline: torch 54.4 s, pocket_tts 55.4 s cold; 2.9 s / 2.3 s
warm), then start the backend and note the seconds until `GET /health`
returns 200 (it now waits for TTS).
Record both numbers in PROGRESS.md -> Standards.

## Step 1 — site-packages (largest effect on every start)

```
robocopy "C:\Users\midas\AppData\Roaming\Python\Python314\site-packages" "D:\PythonUser\Python314\site-packages" /E /COPY:DAT /R:1 /W:1
ren "C:\Users\midas\AppData\Roaming\Python\Python314\site-packages" site-packages.old
mklink /J "C:\Users\midas\AppData\Roaming\Python\Python314\site-packages" "D:\PythonUser\Python314\site-packages"
python -c "import torch, scipy, onnxruntime; print('ok')"
```

When this has worked for a few days, delete `site-packages.old`.
Rollback: `rmdir` the junction (not the target), `ren site-packages.old site-packages`.

## Step 2 — memory.db

With the backend stopped (so the WAL is checkpointed on close):

```
mkdir D:\IRIS\data
robocopy C:\dev\IRISVOICE\data D:\IRIS\data memory.db memory.db-wal memory.db-shm /COPY:DAT
```

Edit `C:\dev\IRISVOICE\data\memory_config.json`:
`"db_path": "D:/IRIS/data/memory.db"`. Start the backend; check the log for
`[MemoryInterface] Caducean C++ engine initialised` and that turns recall
episodes. Keep the old file until confirmed, then delete it.
Rollback: set `db_path` back to `data/memory.db`.

## Step 3 — Hugging Face cache

```
robocopy "C:\Users\midas\.cache\huggingface" "D:\cache\huggingface" /E /COPY:DAT
setx HF_HOME "D:\cache\huggingface"
```

Open a NEW terminal (setx does not change the current one) before starting
the backend. Rollback: `setx HF_HOME ""` (or delete the variable in System
Properties), the old folder still exists.

## Step 4 — LM Studio models

In LM Studio: My Models -> models directory -> `D:\lmstudio\models` (let it
move the files, or robocopy them). Then in `data/iris_config.json` update
`inference.local_model_path` and
`inference.providers["local:LFM2.5-2.6B-QAD-Q4_0"].model_path` to the new
path. Rollback: point both back.

## Step 5 — measure AFTER (cold) and record the standard

Reboot, repeat Step 0, then run the full coding group and record it:

```
python evals/run_evals.py --group coding --record-standard
```

Add the before/after numbers to PROGRESS.md -> Standards (new row: cold
start, with this plan as the "how").
