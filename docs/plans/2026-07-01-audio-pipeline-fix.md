# Audio Pipeline Fix Plan — 2026-07-01

## Problem Statement

The voice conversation loop has broken behaviors that prevent end-to-end interactive experience:

1. **TTS plays twice** — Every agent response audio plays back 2x
2. **Parakeet silently fails** — HTTP boundary to separate service eats errors, falls back to whisper without user knowing
3. **Voice state stuck at "processing"** — TTS sometimes never plays (voice stuck)
4. **Word highlighting out of sync** — Frontend highlights words before audio plays
5. **Cadence animations inconsistent** — Breathing works for whisper but not parakeet
6. **Stale HTTP references** — Codebase still references port 8765 / parakeet_service_url after embedding

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

### Bug 4: Word Highlighting Out of Sync
**Files:** `backend/iris_gateway.py:2977-2984`, `backend/audio/pipeline.py:240-286`

The word timing thread (`_broadcast_words`) starts at line 2977 with a **hardcoded 0.15s sleep** before dispatching the first word event. Meanwhile, `play_stream()` at line 2984 opens the audio device and starts `sd.play(blocking=True)` — but the audio device has its own buffer latency (50-200ms).

Timeline:
```
t=0.00s  Word thread starts → sleeps 0.15s
t=0.00s  play_stream() called → opens device → concatenates chunks
t=0.15s  Word thread wakes → fires word[0] event
t=0.20s+ sd.play() actually produces audio from speakers
```

Result: First word highlights 50-200ms BEFORE audio is audible. This compounds — by the time audio catches up, the highlight is multiple words ahead.

The root cause: no synchronization between "audio device started playing" and "word thread started dispatching". The 0.15s is a guess that doesn't account for device latency.

Additionally, the `play_stream()` path has **two execution paths** (native C++ and sd.play fallback), and the word thread starts differently in each:
- **Native path** (line 2784): Word thread starts AFTER `_native_player.wait_done()` — meaning audio already finished before words begin
- **Fallback path** (line 2977): Word thread starts BEFORE `play_stream()` — words fire before audio starts

### Bug 5: Cadence Missing for Parakeet
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

### Phase 2: Embed Parakeet In-Process + Full HTTP Cleanup (45 min)
**Risk: MEDIUM — architectural change, but isolated to audio layer**

**What:** Move parakeet model loading and inference from the separate `parakeet_service.py` FastAPI server into `voice_command.py` directly, eliminating the HTTP boundary. Clean up ALL HTTP/8765 references.

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

1. `backend/audio/voice_command.py`:
   - Add `ParakeetTranscriber` class:
     - Lazy-loads model on first call (ParakeetForTDT + AutoProcessor from transformers)
     - Transcribes audio numpy array directly (no HTTP)
     - Returns transcription text or raises exception (NO silent `""` return)
     - Logs which STT backend was used: `[STT] parakeet GPU` or `[STT] whisper fallback`
   - Replace `_transcribe_via_parakeet_service()` with `_transcribe_via_parakeet_inprocess()`
   - Remove `parakeet_service_url` parameter from `VoiceCommandHandler.__init__`

2. `backend/main.py`:
   - Remove `parakeet_service_url` config pass-through
   - Remove `PARAKEET_SERVICE_URL` env var references

3. `backend/audio/parakeet_service.py`:
   - Keep as-is for standalone debugging, but add comment: `# STANDALONE DEBUGGING ONLY — primary path is in-process via voice_command.py`

4. `backend/audio/parakeet_buffer.py`:
   - Keep as-is (streaming buffer may still be useful for future streaming STT)

5. `backend/config.py` or equivalent:
   - Remove `parakeet_service_url` from config

6. **HTTP cleanup sweep** — search and remove ALL references to:
   - `localhost:8765` in Python/TS files
   - `parakeet_service_url` in config/init files
   - `PARAKEET_SERVICE_URL` env var references
   - Any frontend code that references the parakeet service port

**Verification:**
- Start backend (NO parakeet service needed on port 8765)
- Trigger voice command
- Log should show `[STT] parakeet GPU — transcription took 0.3s`
- If parakeet fails, log should show `[STT] parakeet FAILED: <error> — falling back to whisper`
- No more silent fallback
- `netstat` should NOT show port 8765 listening

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

### Phase 4: Fix Word Highlighting Sync (30 min)
**Risk: MEDIUM — threading synchronization change**

**What:** Synchronize word highlight timing with actual audio playback start, replacing the hardcoded 0.15s sleep.

**Root cause recap:**
- Word thread uses `time.sleep(0.15)` as a guess for audio device startup
- `sd.play(blocking=True)` has variable latency (50-200ms depending on device/buffer)
- Native path: word thread starts AFTER playback finishes (too late)
- Fallback path: word thread starts BEFORE playback starts (too early)

**Solution:** Add a `threading.Event` to `play_stream()` that signals when audio actually starts playing. Word thread waits on this event instead of sleeping.

**Files changed:**

1. `backend/audio/pipeline.py` — Add `_playback_started` event:
   ```python
   def play_stream(self, audio_chunks, sample_rate=None, playback_started_event=None):
       """..."""
       sr = sample_rate if sample_rate is not None else self.sample_rate
       if self._native_available and self._native_player is not None:
           try:
               if not self._native_player.open(self.output_device or -1, sr):
                   raise RuntimeError("Native player failed to open")
               for i, audio_data in enumerate(audio_chunks):
                   audio_float = np.clip(audio_data.astype(np.float32) * 2.5, -0.99, 0.99)
                   self._native_player.push_chunk(audio_float)
                   if i == 0 and playback_started_event:
                       playback_started_event.set()  # Signal: audio started
               self._native_player.wait_done()
               self._native_player.close()
               return
           except Exception as _native_err:
               logger.warning(f"[AudioPipeline] Native stream failed ({_native_err}), falling back")

       # Fallback: sd.play path
       all_audio = np.concatenate(list(audio_chunks))
       audio_float = np.clip(all_audio.astype(np.float32) * 2.5, -0.99, 0.99)
       
       # Signal immediately before blocking play — sd.play starts the stream
       # synchronously; actual device latency is handled by the audio driver
       if playback_started_event:
           playback_started_event.set()
       
       out_dev = self.output_device
       _sd().play(audio_float, samplerate=sr, device=out_dev, blocking=True)
   ```

2. `backend/iris_gateway.py` — Pass event to word thread:
   ```python
   # In _speak_response, non-native path:
   _playback_event = threading.Event()
   
   def _broadcast_words():
       _playback_event.wait()  # Wait for audio to actually start
       _time2.sleep(0.05)  # Tiny buffer for device latency
       # ... rest of word dispatch logic ...
   
   _word_thread = threading.Thread(target=_broadcast_words, daemon=True)
   _word_thread.start()
   
   engine.pipeline.play_stream(
       _buffered_chunks, sample_rate=_TTS_SAMPLE_RATE,
       playback_started_event=_playback_event
   )
   ```

3. Same pattern for native path — set event after first `push_chunk()`.

**Verification:**
- Trigger voice command
- First word highlight should appear WITHIN 50ms of first audible sound
- Word progression should match speech rate (not ahead or behind)
- No visual "jumping" where highlight skips ahead then waits

---

### Phase 5: Verify End-to-End (15 min)
**What:** Full manual test of the conversation loop.

**Test script:**
1. Start backend (`python start-backend.py`) — NO parakeet service needed
2. Start frontend (`npm run dev`)
3. Open browser to localhost:3000
4. Test via wake word: Say wake phrase → speak a question → hear response ONCE
5. Test via double-click: Double-click orb → speak a question → hear response ONCE
6. Verify: Cadence breathing animates during LLM thinking
7. Verify: Orb transitions through states (idle → listening → processing → speaking → idle)
8. Verify: Word highlighting appears DURING TTS playback, synced with audio
9. Verify: Voice returns to idle after response completes
10. Check logs: `[STT] parakeet GPU` appears for transcriptions
11. Check `netstat`: port 8765 NOT listening
12. Check frontend: no console errors about missing events

---

## Execution Order

1. **Phase 1** first (TTS double-play) — smallest change, highest impact, zero risk
2. **Phase 4** next (word highlighting sync) — depends on Phase 1 being done (single play_stream call)
3. **Phase 2** next (embed parakeet + HTTP cleanup) — architectural change, needs careful testing
4. **Phase 3** next (voice state stuck) — error handling, independent of Phase 2/4
5. **Phase 5** last (verification) — manual end-to-end test

---

## Completion Status

### All Original Bugs Fixed ✅

| Bug | Status | Fix |
|-----|--------|-----|
| 1. TTS plays twice | ✅ Fixed | Removed duplicate `play_stream()` call |
| 2. Parakeet silently fails | ✅ Fixed | Embedded in-process, HTTP boundary removed |
| 3. Voice state stuck | ✅ Fixed | Error handling + watchdog in `_speak_response` |
| 4. Word highlighting out of sync | ✅ Fixed | Character-proportional timing at **15.8 chars/sec**, `tts_started`/`tts_word` events with `turn_id` |
| 5. Cadence animations inconsistent | ✅ Fixed | Shared cadence path for all STT backends |
| 6. Stale HTTP references | ✅ Fixed | HTTP/8765 references cleaned up |

### Additional Fixes Applied (Session 150-155)

These were discovered and fixed during live testing beyond the original plan:

#### Word Highlighting Regression: `turn_id` not propagated through `iris:text_response`

**Problem**: Backend sends `text_response` with `turn_id` at the top level of the WS message, but `useIRISWebSocket.ts` only destructured from the nested `payload` object. The `iris:text_response` CustomEvent was dispatched **without `turn_id`**, so `chat-view.tsx` created messages with `id = Date.now()` — which never matched `currentTtsMessageId` set by `tts_started`. Word highlighting rendered against a mismatched ID → nothing highlighted.

**Fix** (`hooks/useIRISWebSocket.ts`): Extract `turn_id` from the top-level WS message (`message.turn_id`) and pass it through the `iris:text_response` CustomEvent detail.

**Verification**: `test_text_response_includes_turn_id_matching_tts_started` — asserts both events share the same `turn_id`. `test_text_response_turn_id_source_code_contract` — source code pattern check.

#### Play-Button TTS Orb Breathing Animation

**Problem**: When a user clicks the play button on an assistant response, the orb did not animate (no breathing, no scale). The `tts_play` backend path sent `listening_state: speaking` which polluted `voiceState`, and the orb relied solely on `voiceState` for animation.

**Fix**:
- **Backend** (`backend/iris_gateway.py`): Changed `tts_play` handler to send `tts_started` (with `turn_id` and `total_words`) instead of `listening_state: speaking`. This keeps the play-button TTS completely isolated from `voiceState` — no risk of triggering listening/processing effects or restarting VAD.
- **Frontend** (`components/iris/XurOrb.tsx`): Added `playbackSpeaking` state that listens to `iris:tts_started` / `iris:tts_word(is_final)` CustomEvents. Drives the same 1.2× scale and breathing animation as voice pipeline TTS. Completely isolated: never touches `voiceState`.

**Verification**: `test_tts_play_sends_tts_started_not_listening_state` — asserts `tts_started` has `turn_id` and `total_words`, and `listening_state:speaking` is NOT sent.

#### Character-Proportional Timing Tuned to 15.8 chars/sec

Word highlight timing was tuned through multiple iterations:
- Started at 12.5 chars/sec → too slow (highlights lagged behind audio)
- Bumped to 14.5 → closer but still slightly behind
- Final value: **15.8 chars/sec** — verified perfectly in sync with TTS playback during live testing

**File**: `backend/iris_gateway.py` line 3327

#### Other Fixes Retained

- `tts_started` carries `turn_id` + `total_words` in detail (re-entrancy race fix)
- `fallbackActive = false` initially (prevents 200ms fallback racing against first backend `tts_word`)
- Dynamic word count (`while True` loop) picks up words from later sentences
- `_root_log` NameError fixed (line 2291 — changed to `self._logger`)
- VAD_SILENCE_SEC increased to 1.2s for natural speech pauses
- DER path `chunk_callback` fix for TTS playback on non-streaming responses
- AsyncMock for WS manager in tests (Python 3.14 compatibility)
- 12 diagnostic logging lines (`[DER-TTS-FIX]`, `[STT_LATENCY]`, `[TTS_LATENCY]`, `[FLOW_LATENCY]`)

### Test Results

**91/91 tests passing** (backend):
- 88 legacy voice pipeline tests
- `test_text_response_includes_turn_id_matching_tts_started`
- `test_text_response_turn_id_source_code_contract`
- `test_tts_play_sends_tts_started_not_listening_state`

**8/8 latency metric tests** passing
**6/6 chunk callback tests** passing

## Commit Strategy

Each phase gets its own commit:
1. `fix: remove duplicate TTS play_stream call` 
2. `fix: sync word highlighting with audio playback via threading.Event`
3. `refactor: embed parakeet transcriber in-process, remove HTTP boundary`
4. `fix: ensure voice state returns to idle on error`
5. `docs: audio pipeline fix plan and verification results`
6. `fix: turn_id propagation in text_response + orb breathing for play TTS` ← latest
