# Audio Pipeline Fix Plan — 2026-07-01

## Problem Statement

The voice conversation loop has three broken behaviors that prevent end-to-end interactive experience:

1. **TTS plays twice** — Every agent response audio plays back 2x
2. **Parakeet silently fails** — HTTP boundary to separate service eats errors, falls back to whisper without user knowing
3. **Voice state stuck at "processing"** — TTS sometimes never plays (voice stuck)
4. **Cadence animations inconsistent** — Breathing works for whisper but not parakeet

## Root Causes Found

### Bug 1: TTS Double-Play
**File:** `backend/iris_gateway.py:2931` and `:2984`

`play_stream()` is called **twice** on the same `_buffered_chunks` in the non-native TTS path:
- Line 2931: First `play_stream()` — blocks until audio finishes
- Lines 2935-2982: Cadence thread + word timing thread start
- Line 2984: Second `play_stream()` — plays the exact same audio again

`play_stream()` uses `sd.play(data, rate, blocking=True)`. Both calls are blocking, so audio plays sequentially twice.

### Bug 2: Parakeet Silent Failure
**File:** `backend/audio/voice_command.py:444-498`

`_transcribe_via_parakeet_service()` catches ALL exceptions and returns `""`, which triggers whisper fallback silently. The HTTP boundary means:
- Network errors → silent fallback
- Parakeet OOM → silent fallback  
- Timeouts → silent fallback
- User never knows they're using whisper instead of parakeet

### Bug 3: Voice State Stuck
**File:** `backend/iris_gateway.py:2225-2240`

`_on_voice_result()` dispatches `_wrap_tts_streaming()` in a background thread. If the LLM call within that thread fails (API error, timeout), the voice state never transitions back to idle — stuck at "processing".

### Bug 4: Cadence Missing for Parakeet
When parakeet IS used (HTTP path), the backend's VoiceCommandHandler still runs VAD and sends `audio_envelope` events. But since parakeet silently fails 100% of the time (0 requests seen), the user only ever experiences whisper's cadence path.

---

## Fix Plan

### Phase 1: Fix TTS Double-Play (15 min)
**Risk: LOW — single line removal**

**What:** Remove the duplicate `play_stream()` call at line 2931 in `iris_gateway.py`.

**Why it's safe:** The second call at line 2984 is the correct one — it runs AFTER the cadence and word timing threads are started, so those threads get to run concurrently with audio playback. The first call at 2931 blocks and plays everything before threads even start.

**Files changed:**
- `backend/iris_gateway.py` — Remove line 2931 `engine.pipeline.play_stream(_buffered_chunks, sample_rate=_TTS_SAMPLE_RATE)`

**Verification:**
- Start backend + frontend
- Trigger voice command via wake word or double-click
- Agent response should play audio exactly ONCE
- Word highlighting should still work
- Cadence breathing should still animate during TTS

---

### Phase 2: Embed Parakeet In-Process (45 min)
**Risk: MEDIUM — architectural change, but isolated to audio layer**

**What:** Move parakeet model loading and inference from the separate `parakeet_service.py` FastAPI server into `voice_command.py` directly, eliminating the HTTP boundary.

**Why:**
- Single-user desktop assistant — no need for separate service scaling
- Eliminates silent HTTP failure mode
- Removes one process to manage (no more port 8765)
- Model loads once on first use, stays in memory
- RTX 3070 has 8GB VRAM — plenty for parakeet (1.2GB) + other tasks

**Architecture change:**

```
BEFORE:
  VoiceCommandHandler → HTTP POST to localhost:8765 → ParakeetService (separate process)
                                              ↓ (on failure)
                                         faster-whisper fallback

AFTER:
  VoiceCommandHandler → ParakeetTranscriber (in-process, lazy-loaded)
                                         ↓ (on failure with explicit error log)
                                    faster-whisper fallback
```

**Files changed:**
- `backend/audio/voice_command.py` — Replace `_transcribe_via_parakeet_service()` with `_transcribe_via_parakeet_inprocess()`. Add `ParakeetTranscriber` class that:
  - Lazy-loads model on first call (ParakeetForTDT + AutoProcessor from transformers)
  - Transcribes audio numpy array directly (no HTTP)
  - Returns transcription text or raises exception (NO silent `""` return)
  - Logs which STT backend was used: `[STT] parakeet GPU` or `[STT] whisper fallback`

- `backend/audio/voice_command.py` — Remove `parakeet_service_url` parameter from `VoiceCommandHandler.__init__`

- `backend/main.py` — Remove `parakeet_service_url` config pass-through

- `backend/audio/parakeet_service.py` — Keep as-is (can still be run standalone if needed for debugging), but no longer the primary path

- `backend/audio/parakeet_buffer.py` — Keep as-is (streaming buffer may still be useful)

**Verification:**
- Start backend (NO parakeet service needed on port 8765)
- Trigger voice command
- Log should show `[STT] parakeet GPU — transcription took 0.3s`
- If parakeet fails, log should show `[STT] parakeet FAILED: <error> — falling back to whisper`
- No more silent fallback

---

### Phase 3: Fix Voice State Stuck (20 min)
**Risk: LOW — error handling improvement**

**What:** Add proper error handling in `_wrap_tts_streaming()` so voice state always returns to idle, even if LLM or TTS fails.

**Files changed:**
- `backend/iris_gateway.py` — Wrap the LLM → TTS chain in try/finally:
  ```python
  async def _wrap_tts_streaming(self, text, turn_id):
      try:
          # ... LLM call + TTS synthesis + playback ...
      except Exception as e:
          logger.error(f"[TTS] Pipeline failed: {e}")
          # Send error to frontend
          await self._broadcast({"type": "voice_result", "state": "error", "error": str(e)})
      finally:
          # ALWAYS return voice to idle
          await self._broadcast({"type": "voice_result", "state": "idle"})
  ```

**Verification:**
- Disconnect network mid-conversation → voice should return to idle
- Use invalid API key → voice should return to idle with error message
- Normal conversation should still work as before

---

### Phase 4: Verify End-to-End (15 min)
**What:** Full manual test of the conversation loop.

**Test script:**
1. Start backend (`python start-backend.py`)
2. Start frontend (`npm run dev`)
3. Open browser to localhost:3000
4. Test via wake word: Say wake phrase → speak a question → hear response ONCE
5. Test via double-click: Double-click orb → speak a question → hear response ONCE
6. Verify: Cadence breathing animates during LLM thinking
7. Verify: Orb transitions through states (idle → listening → processing → speaking → idle)
8. Verify: Word highlighting appears during TTS playback
9. Verify: Voice returns to idle after response completes
10. Check logs: `[STT] parakeet GPU` appears for transcriptions

---

## Execution Order

1. **Phase 1** first (TTS double-play) — smallest change, highest impact, zero risk
2. **Phase 2** next (embed parakeet) — architectural change, needs careful testing
3. **Phase 3** next (voice state stuck) — error handling, independent of Phase 2
4. **Phase 4** last (verification) — manual end-to-end test

## Commit Strategy

Each phase gets its own commit:
1. `fix: remove duplicate TTS play_stream call` 
2. `refactor: embed parakeet transcriber in-process`
3. `fix: ensure voice state returns to idle on error`
4. `docs: audio pipeline fix plan and verification results`
