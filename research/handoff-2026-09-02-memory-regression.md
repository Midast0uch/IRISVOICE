# Handoff: Memory Regression & Startup Bloat

**Date:** 2026-09-02  
**Author:** Session 284  
**Status:** Memory went from ~2.5 GB to ~8.2 GB total at idle

---

## The Problem

The backend now uses **~8.2 GB private memory** at idle. It was previously **~2.5 GB**. The increase comes from three sources:

| Process | Current | Target | Delta |
|---------|---------|--------|-------|
| Parakeet worker | 4.2 GB | 0 GB (not loaded) | +4.2 GB |
| TTS worker | 2.3 GB | ~1.0 GB | +1.3 GB |
| Backend (uvicorn) | 1.4 GB | ~1.0 GB | +0.4 GB |
| Crawl workers (x2) | 0.7 GB | 0 GB (not pre-warmed) | +0.7 GB |
| MCM server | 63 MB | 63 MB | — |
| **Total** | **~8.2 GB** | **~2.5 GB** | **+5.7 GB** |

---

## Root Causes

### 1. Parakeet worker spawns at startup (biggest offender)

`backend/audio/voice_command.py` line 892: `_parakeet_warm_up()` is called during backend init. This spawns a subprocess that loads `nvidia/parakeet-tdt-0.6b-v3` (0.6B params). Even with `device_map="cuda:0"`, the subprocess retains ~4 GB of CPU private memory from:
- Python interpreter + CUDA runtime overhead
- HuggingFace `from_pretrained` loading cache
- `AutoProcessor` + tokenizer state

**Before the Parakeet subprocess refactor (session ~277):** Parakeet was an in-process model that loaded lazily on first voice command. The subprocess refactor was done to fix GIL contention, but it made the model load eagerly at startup.

### 2. TTS worker loads at startup

`backend/agent/tts.py` calls `_pre_load_worker()` during backend init. Pocket-TTS is a CPU-only model that takes ~2.3 GB. This was always loaded at startup.

### 3. Crawl pool pre-warms 2 workers

`backend/iris_gateway.py` startup spawns 2 crawl workers (`crawl_worker --serve 900.0`). Each takes ~350 MB. This was added for "instant web search" but burns 700 MB at idle.

### 4. Backend imports everything eagerly

`backend/main.py` and `backend/iris_gateway.py` import torch, transformers, sounddevice, etc. at module level. Every import adds memory even if the feature is never used.

---

## What Was Changed This Session

### Files edited (all on disk, need backend restart to take effect):

1. **`components/iris/XurOrb.tsx`** — Removed `isProcessing` from `isAgentWorking`. Orb no longer vanishes during STT/message sending. Only real agent work (task steps, crawls, questions) triggers the swallow.

2. **`backend/audio/voice_command.py`** — Two changes:
   - `TRANSCRIBE_TIMEOUT_SEC` 20.0 → 90.0 (covers CUDA JIT first inference)
   - Warm-up timeout no longer sets `_load_error` — first live utterance retries GPU ASR

3. **`backend/voice/violawake_detector.py`** — `CONSECUTIVE_CHUNKS` 2 → 5 (tighter false-positive guard)

4. **`backend/audio/parakeet_worker.py`** — Added `device_map="cuda:0"` to load directly onto GPU (partial fix, still 4.2 GB)

### NOT changed (needs doing):

- Parakeet should NOT load at startup — lazy load on first voice command
- Crawl pool should NOT pre-warm 2 workers — spawn on first search request
- TTS worker could be lazy-loaded too (but less critical, 2.3 GB is CPU model)

---

## How Memory Was 2.5 GB Before

The user reports the backend ran at ~2.5 GB total previously. The likely configuration was:
- **No Parakeet subprocess** — faster-whisper tiny/int8 (~40 MB) was the primary STT
- **No crawl pool pre-warm** — crawl workers spawned on demand
- **TTS loaded at startup** (same as now, ~2.3 GB)
- **Backend itself** ~200 MB (before all the extra imports accumulated)

The Parakeet subprocess refactor and crawl pool pre-warm were added AFTER that baseline.

---

## Recommended Fixes (in priority order)

### P1: Remove Parakeet startup pre-load

In `backend/audio/voice_command.py`, comment out or guard `_parakeet_warm_up()` call (around line 892). The `_ensure_loaded()` lazy-load path already exists — it just never fires because warm-up already loaded it.

**Saves: ~4.2 GB**

### P2: Remove crawl pool pre-warm

In `backend/iris_gateway.py`, find the crawl pool pre-warm call (around the `[crawl_pool] worker ready` log line) and remove it. Workers should spawn on first `crawler_query` only.

**Saves: ~0.7 GB**

### P3: Lazy-import heavy modules

Move `import torch`, `import sounddevice`, `import soundfile`, `import transformers` into the functions that use them, not module level.

**Saves: ~0.3 GB**

### P4: Consider removing Parakeet entirely

faster-whisper tiny/int8 transcribes in <1s on CPU and uses 40 MB. Parakeet (0.6B) is more accurate but adds 4+ GB. If the user doesn't need high-accuracy ASR, remove the Parakeet path entirely.

**Saves: ~4.2 GB (if not loaded at all)**

---

## Current Backend State

- Backend PID 1612 is running on port 8090
- Parakeet worker PID 11192 is running (4.2 GB)
- TTS worker PID 21032 is running (2.3 GB)
- 2 crawl workers running (358 MB each)
- Frontend dev server on port 3000 (PID 15060)
- MCM server on PID 27072

### Code changes on disk (NOT yet deployed to running backend):
- XurOrb.tsx swallow fix
- voice_command.py timeout + warm-up fix
- violawake_detector.py CONSECUTIVE_CHUNKS=5
- parakeet_worker.py device_map fix

---

## Key Files

| File | Purpose |
|------|---------|
| `backend/audio/voice_command.py` | Parakeet warm-up at line 892, VAD logic, transcription |
| `backend/audio/parakeet_worker.py` | Parakeet subprocess — model loading, inference |
| `backend/audio/tts_worker.py` | Pocket-TTS subprocess — CPU-only |
| `backend/voice/violawake_detector.py` | Wake word detection, threshold, guards |
| `backend/iris_gateway.py` | Crawl pool pre-warm, voice pipeline orchestration |
| `backend/main.py` | Backend startup, module-level imports |
| `components/iris/XurOrb.tsx` | Orb swallow mechanic (isAgentWorking) |
| `backend/api/status_snapshot.py` | git_status — had invalid `kill_on_timeout` kwarg (fixed) |

---

## Pins Created This Session

- pin_f6104c783c87: FIXED+COMMITTED widget freeze — 15 event-loop blockers moved off-loop
- pin_bc15b826b9c6: HANDOFF wake guards verified; VAD, Parakeet, widget fixes applied
- (plus earlier pins from sessions 278-283)

---

## What the User Wants

1. Memory back to ~2.5 GB total at idle
2. Wake word that detects "Hey Iris" but not loud noises
3. STT that works (Parakeet or whisper, doesn't matter which)
4. Orb that stays visible during STT (already fixed)
5. No "voice command failed" errors
6. Widget that doesn't freeze/lag