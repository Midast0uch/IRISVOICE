# Audio Pipeline Handoff — June 30, 2026

## What's Working

1. **TTS Natural Pacing** — Sentences are split via `_split_into_chunks` and synthesized separately with 500ms silence gaps between them + 600ms trailing silence. User confirmed this sounds natural.

2. **VAD Speech Detection** — Threshold raised from 0.004 → 0.006, silence detection lowered from 1.0s → 0.8s. Info-level logging now visible in `irisvoice.log` for speech start, silence progress, and end-of-speech events.

3. **Word Highlighting** — Backend sends `tts_word` events during `_handle_tts_play` playback with 100ms startup delay to account for audio device buffering. Frontend (`chat-view.tsx:558`) listens and highlights.

4. **Orb Breath Modes** — `useCadenceDetection.ts` returns `breathMode: "C"` for listening, `"D"` for speaking, `"A"` for idle. `OrbCanvas.tsx` has `drawBreathHalo` for Mode C (dramatic expanding halo for STT) and reduced-bloom Mode D (subtle pulse for TTS).

5. **Chatview TTS Cadence Broadcast** — `_handle_tts_play` now has a cadence broadcast thread that sends `audio_envelope` with sinusoidal cadence during playback + cleanup `audio_envelope` with phase:"idle" at end.

---

## Bugs Found (Root Causes + Fixes)

### BUG 1: Conversation Loop Killer — `_wrap_tts_streaming` overrides auto-relisten

**Severity:** Critical
**File:** `backend/iris_gateway.py` — `_wrap_tts_streaming` (line ~2087)
**Impact:** Conversation mode closes after every TTS response. User cannot have back-and-forth voice conversation.

**Root Cause:**
The flow is:
```
_process_voice_transcription
  → _wrap_tts_streaming(queue, session_id, client_id, loop)
    → _speak_response(queue, session_id)
      → finally: if in_conversation → sends listening_state:"listening" + starts recording
    → finally: ALWAYS sends listening_state:"idle"  ← OVERRIDES!
```

`_speak_response` correctly auto-relistens in conversation mode (line 2648-2673), but `_wrap_tts_streaming`'s `finally` block (line ~2087) sends `listening_state: "idle"` UNCONDITIONALLY, overriding the auto-relisten.

The frontend receives `listening_state: idle` → sets `voiceState = "idle"` → resets `audioLevel(0)` (line 586-588 of `useIRISWebSocket.ts`) → orb goes to idle → voice command state closes.

**Fix:** Remove or condition the `_wrap_tts_streaming` finally block. `_speak_response` already handles all state transitions (listening/idle) in its own finally block. The `_wrap_tts_streaming` finally block is redundant and harmful. Either:
- Remove the `listening_state` broadcast from `_wrap_tts_streaming` entirely
- Or only send `idle` if `_speak_response` threw an exception (error fallback)

---

### BUG 2: `_handle_tts_play` doesn't restart recording in conversation mode

**Severity:** High
**File:** `backend/iris_gateway.py` — `_handle_tts_play` finally block (line ~2880)
**Impact:** When user clicks play button in chatview during an active conversation, TTS plays but the orb goes idle instead of returning to listening mode.

**Root Cause:**
`_handle_tts_play` correctly sends `listening_state: "listening"` when in conversation mode (line ~2890), but it does NOT call `self._voice_handler.start_recording()` to restart VAD capture. The orb shows "listening" state but no audio is being captured. When `_speak_response` is called through this path, it works correctly because it does both — but `_handle_tts_play` is a separate code path that only sends the state message without restarting recording.

**Fix:** In `_handle_tts_play` finally block, after sending `listening_state: "listening"`, also call:
```python
self._voice_handler.set_active_session(session_id)
self._voice_handler.start_recording(
    auto_stop=True,
    pre_speech_timeout_sec=self._relisten_pre_speech_timeout,
)
```

---

### BUG 3: Audio pipeline state corruption during continuous conversation

**Severity:** High
**Files:** `backend/audio/engine.py`, `backend/audio/voice_command.py`, `backend/iris_gateway.py`
**Impact:** After 2-3 conversation turns, the audio pipeline breaks — VAD stops detecting speech, or TTS playback fails, or both.

**Root Cause (multiple issues):**

**3a. TTS active flag not cleared on exception:**
In `engine.py`, `set_tts_active(True/False)` controls whether `_process_audio_frame` triggers Porcupine wake word detection. If TTS playback throws an exception before reaching `set_tts_active(False)`, the engine stays in TTS mode and won't respond to wake word or voice commands.

**3b. `_speech_interrupted` flag can get stuck:**
`engine._speech_interrupted` is set by `interrupt_speech()` (called from `voice_command_start`). It's cleared by `_speak_response` at the start. But if `_speak_response` crashes or is never called (e.g., transcription fails), the flag stays set and all subsequent `_speak_response` calls see `was_interrupted=True` and skip auto-relisten.

**3c. Voice handler recording state conflicts:**
`voice_command.py`'s `start_recording` can be called while a previous recording is still active. The old recording thread may still be running and writing to the same `frame_queue`. This causes garbled audio data or stale frames being transcribed.

**3d. Audio device contention:**
TTS playback (via `sounddevice` or native player) and VAD recording (via `sounddevice` input stream) can conflict on the same audio device. The `play_stream` function opens the output device exclusively, potentially blocking the input stream.

**Fixes:**
- Add try/finally around TTS playback in `_handle_voice` to always clear `set_tts_active(False)` and `_speech_interrupted`
- Add `stop_recording()` call before `start_recording()` to ensure clean state
- Consider using separate audio devices for input/output (already configured but may not be enforced)

---

### BUG 4: Orb animations not reactive during STT (listening)

**Severity:** Medium
**Files:** `backend/audio/voice_command.py`, frontend `useIRISWebSocket.ts`
**Impact:** During STT recording, the orb doesn't show Mode C (breath halo) animation.

**Root Cause:**
The VAD loop in `voice_command.py` broadcasts `audio_envelope` during recording (line ~730-786), but this only happens inside the `_capture_frame` method's diagnostic logging path (every 30 frames). The `audio_envelope` broadcast uses `_on_audio_envelope_callback` which was set up in `_handle_voice` via `self._voice_handler.set_audio_envelope_callback(...)`.

However, if `_handle_voice` is called through the `voice_command_start` path, the callback is properly set. The issue is more likely that:
1. The `audio_envelope` messages aren't reaching the frontend during recording because the callback isn't being called frequently enough
2. OR the frontend's `useCadenceDetection` requires `voiceState === "listening"` AND `audioLevel > threshold` to return Mode C — if `audioLevel` is too low (silence between words), it falls back to Mode A

**Fix:** Ensure the `audio_envelope` broadcast in the VAD loop is sent on EVERY frame (or at least every 3-5 frames), not just during diagnostic logging. Also verify `useCadenceDetection` has a low enough threshold for the cadence level to trigger Mode C.

---

### BUG 5: `_speak_response` audio_envelope broadcast missing in conversation mode

**Severity:** Medium
**File:** `backend/iris_gateway.py` — `_speak_response`
**Impact:** During conversation-mode TTS playback, the orb doesn't animate reactively because no `audio_envelope` messages are being broadcast.

**Root Cause:**
`_speak_response` uses a **producer/consumer thread pattern** (lines 2340-2450). The TTS synthesis happens in a producer thread, the playback in a consumer thread. Neither thread sends `audio_envelope` messages.

Compare with `_handle_tts_play`, which now has a cadence broadcast thread (added in the last commit). `_speak_response` has NO equivalent — it relies on `listening_state: speaking` to trigger Mode D on the frontend, but `useCadenceDetection` also needs `ttsAudioLevel > 0` (from `audio_envelope` with phase:"speaking") to produce non-zero `breathLevel`. Without `audio_envelope`, `breathLevel` stays at 0 and the breathing effect is invisible.

**Fix:** Add a cadence broadcast thread in `_speak_response` similar to what was added in `_handle_tts_play`:
```python
# In _speak_response, after setting listening_state:"speaking":
if session_id and total_duration_s > 0.3:
    def _broadcast_cadence():
        # ... same pattern as _handle_tts_play's cadence thread
    cadence_thread = threading.Thread(target=_broadcast_cadence, daemon=True)
    cadence_thread.start()
```

---

## Architecture Summary

### State Flow (Backend → Frontend)

```
Backend Event                    Frontend Handler                    Orb Effect
─────────────────────────────────────────────────────────────────────────────
listening_state: "listening"  →  setVoiceState("listening")       →  breathMode "C"
listening_state: "speaking"   →  setVoiceState("speaking")        →  breathMode "D"  
listening_state: "idle"       →  setVoiceState("idle")            →  breathMode "A"
listening_state: "processing" →  setVoiceState("processing")      →  breathMode "D"
audio_envelope (phase:"speaking") → setTtsAudioLevel(rms)         →  breathLevel (y-axis)
audio_envelope (phase:"listening") → setAudioLevel(rms)           →  cadenceLevel (y-axis)
tts_word                        →  CustomEvent iris:tts_word       →  word highlighting
```

### Key Constraint
`useCadenceDetection` (line 42-65) requires BOTH:
- `voiceState` matching the expected state ("listening" or "speaking")
- Audio level > 0.01 threshold

If either is zero, it returns Mode A (idle). This means sending `listening_state` alone is not enough — you MUST also send `audio_envelope` messages to get visible breathing animation.

### Conversation Mode Lifecycle

```
1. User double-clicks orb → voice_command_start
   → _handle_voice() → _conversation_sessions.add(session_id)
   → voice_handler.start_recording(auto_stop=True)
   → listening_state:"listening" broadcast

2. User speaks → VAD detects silence → _on_voice_result callback
   → transcription via Parakeet/faster-whisper
   → listening_state:"processing" broadcast

3. LLM streams response → sentences into queue
   → _process_voice_transcription → _wrap_tts_streaming → _speak_response
   → listening_state:"speaking" broadcast
   → TTS synthesis + playback

4. TTS finishes → _speak_response finally:
   IF in_conversation → listening_state:"listening" + restart recording ← CORRECT
   ELSE → listening_state:"idle"
   
   THEN _wrap_tts_streaming finally:
   ALWAYS → listening_state:"idle" ← BUG 1: OVERRIDES!
```

---

## Files to Touch

| File | Changes Needed |
|------|---------------|
| `backend/iris_gateway.py` | Fix `_wrap_tts_streaming` finally block (Bug 1). Add cadence broadcast to `_speak_response` (Bug 5). Fix `_handle_tts_play` restart recording (Bug 2). |
| `backend/audio/engine.py` | Add try/finally to clear `set_tts_active` and `_speech_interrupted` (Bug 3a/3b). |
| `backend/audio/voice_command.py` | Ensure `audio_envelope` broadcasts on every VAD frame (Bug 4). Add `stop_recording()` before `start_recording()` (Bug 3c). |
| `hooks/useCadenceDetection.ts` | May need to lower audio level threshold for Mode C activation (Bug 4). |
| `hooks/useIRISWebSocket.ts` | Line 586-588: `setAudioLevel(0)` on non-listening state may be too aggressive — check if it resets cadence during conversation transitions. |

---

## Testing Checklist

- [ ] Start backend + frontend + Parakeet
- [ ] Double-click orb → speak → TTS plays → orb returns to listening (Bug 1 fix)
- [ ] Double-click orb → speak → TTS plays → speak again → TTS plays → repeat 5x without breakage (Bug 3 fix)
- [ ] Click play button in chatview → orb animates reactively during TTS (Bug 5 fix)
- [ ] Click play button in chatview during voice conversation → orb returns to listening after TTS (Bug 2 fix)
- [ ] During STT recording → orb shows Mode C breath halo (Bug 4 fix)
- [ ] Check `irisvoice.log` for: `VAD: speech started`, `VAD: silence N/25`, `VAD: end-of-speech detected`
- [ ] Check that conversation works for 5+ turns without audio pipeline breakdown

---

## Config Reference

| Setting | Value | Location |
|---------|-------|----------|
| `VAD_ENERGY_THRESHOLD` | 0.006 | `voice_command.py` line ~70 |
| `VAD_SILENCE_SEC` | 0.8 | `voice_command.py` line ~73 |
| `VAD_MIN_SPEECH_SEC` | 0.15 | `voice_command.py` line ~72 |
| `_INTER_SENTENCE_SILENCE` | 0.50s | `tts.py` class constant |
| `_TRAILING_SILENCE` | 0.60s | `tts.py` class constant |
| `_PLAYBACK_STARTUP_DELAY_S` | 0.10s | `iris_gateway.py` line ~2755 |
| `OUTPUT_SAMPLE_RATE` | 24000 | `tts.py` |
| Parakeet port | 8765 | Separate process |
| Backend port | 8090 | `start_all.py` |
| Frontend port | 3000 | Next.js dev server |
