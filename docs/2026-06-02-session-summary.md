# Session Summary — Jun 2 2026

**Duration:** ~10 hours (wake word fix → Pocket-TTS swap → animation debug)

## What Changed

### Engine Swap: F5-TTS → Pocket-TTS
Replaced F5-TTS (135M params, torchcodec+FFmpeg, ~540MB RAM, no streaming) with pocket-tts (~100M params, Mimi codec, ~100MB RAM, true streaming via `generate_audio_stream`). Fork: `danneauxs/Pocket-TTS-Spokenword`.

### Voices Added
- "Cloned Voice" — zero-shot voice cloning from `data/TOMV2.wav` (gated HF model, needs accepted terms at kyutai/pocket-tts)
- 8 catalog voices: alba, marius, javert, jean, fantine, cosette, eponine, azelma

### Config Persistence
- Added `TTSConfig` dataclass to `IRISConfig` with `tts_voice`, `tts_enabled`, `speaking_rate`
- Voice selection now saves to `data/iris_config.json` on APPLY and survives restarts

### Audio Pipeline
- Added `play_stream()` — opens native player once, pushes all chunks, waits+closes at end
- Removed per-chunk peak normalization (was amplifying silent lead-in chunks into loud static)
- Added 2.5× fixed gain for Pocket-TTS's quiet output (peak ~0.37, RMS ~0.032)

### Wake Word
- Fixed race condition: cooldown check moved from async coroutine to synchronous callback
- Event loop stored at module level — `asyncio.get_running_loop()` fails in audio callback thread

### Bug Fixes
- Dedup guard: `return False` → `return True` (WS handler was sending `idle` and cancelling recordings)
- Removed duplicate TTS thread (queue-based + spoken-text threads were both calling `_speak_response`)
- Removed conversational loop (auto-relisten fought state machine)
- Removed PreSpeech.wav loading sound
- Removed first TTS thread (line 1832) to prevent doubled audio

## What's Still Not Working

| Issue | Root Cause | Status |
|-------|-----------|--------|
| Wake word doesn't trigger recording | `asyncio.get_running_loop()` in audio thread | FIXED (c54bfe05) — untested |
| Animation: wake word vs double-click differ | Both route through `_handle_voice` → same `listening_state: listening`. The `iris:wake_word_detected` CustomEvent is dead code — never dispatched | Not investigated |
| Audio quality "like old speaker" | Pocket-TTS Mimi codec at 24kHz, 12.5Hz frame rate, 32-dim quantizer | Inherent to engine |
| VAD doesn't detect speech start/end | Energy threshold 0.004, silence timeout 1.0s | May need tuning |

## Backend History (today's commits)
```
c54bfe05 fix: store event loop at module level for _on_wake_word_sync
c250f88c fix: race condition in wake word cooldown
0789370a fix: VAD_SILENCE_SEC 2.0->1.0
4392ea0e fix: lower VAD energy threshold 0.008->0.004
a1a75444 cleanup: @dataclass TTSConfig + dedup guard returns True
7cc0c39b fix: wake word cooldown + remove local load_config import
80b8cfe6 fix: dedup guard returns True + remove duplicate TTS thread
9523181a fix: remove per-chunk normalization, skip silent lead-in, remove conv loop
8fc6d77b feat: catalog voices + conversational loop + animation sync
ddda3727 persist: add TTSConfig to IRISConfig
```

## Running State (at session end)
- Backend: PID 56488, port 8000
- Frontend: PID 64108, port 3000
- Config: chutes provider added to `.opencode/opencode.json`
