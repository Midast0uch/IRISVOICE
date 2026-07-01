# Audio Pipeline Regression — Root Cause Analysis & Fix Plan

> Date: 2026-07-01
> Status: Root causes identified. Plan ready for implementation.
> Method: Systematic debugging (Phase 1: Root Cause Investigation complete)

---

## Issues Reported

1. **TTS distorted/static** — "sounds like static, barely make out what it's saying"
2. **TTS not playing at all** — queue times out, no audio reaches device
3. **VAD slow to register end of speech** — takes too long to detect silence
4. **Cadence animation different** — whisper animation is good, parakeet is bad
5. **Backend start command doesn't exit** — terminal hangs after starting backend
6. **Parakeet GPU fails** — empty error, falls back to whisper
7. **Noticeable wait between STT and TTS** — agent says "speaking" but no audio

---

## Root Cause Analysis

### Issue 1: TTS Distorted/Static

**Root cause:** My `np.tanh()` change in `pipeline.py` (commit `15b90fcb`).

The original code was:
```python
audio_float = np.clip(audio_float * 2.5, -0.99, 0.99)
```

I changed it to:
```python
audio_float = audio_float * 2.5
audio_float = np.tanh(audio_float / 0.7) * 0.7
```

`tanh()` is a non-linear function that distorts the waveform shape. For audio:
- Input 0.37 peak → 0.37 * 2.5 = 0.925 → 0.925/0.7 = 1.32 → tanh(1.32) = 0.87 → * 0.7 = 0.61
- Input 0.1 peak → 0.1 * 2.5 = 0.25 → 0.25/0.7 = 0.36 → tanh(0.36) = 0.34 → * 0.7 = 0.24

The non-linear tanh adds harmonic distortion (changes the waveform shape), which sounds like static/buzzing. The original `np.clip` only clips peaks above 0.99, leaving the rest of the waveform intact.

**Fix:** REVERT tanh back to original `np.clip(audio_float * 2.5, -0.99, 0.99)`.

---

### Issue 2: TTS Not Playing (Queue Timeout)

**Root cause:** The TTS producer puts chunks into `audio_queue`, but the consumer (`play_stream`) is called with a different iterable. The queue times out because the consumer never reads from it.

From logs:
```
18:32:32 [TTS][producer] synthesized 16 audio chunks for 'Of course!'
18:32:37 [TTS][producer] synthesized 89 chunks (170880 samples)
18:32:37 [Voice] TTS audio queue timed out after 30s - skipping TTS
```

The producer finishes at 18:32:37, but the queue times out at the SAME time. This means the consumer never started consuming.

**Investigation needed:** Check how `audio_queue` is connected to `play_stream()`. The consumer might be waiting for the first chunk with a 300s timeout, but the first chunk was already produced. Or the consumer thread might not be started at all.

**Fix:** Trace the producer→consumer flow in `_speak_response()` and ensure `play_stream()` is actually called with the queue items.

---

### Issue 3: VAD Slow to Register End of Speech

**Root cause:** `VAD_SILENCE_SEC = 0.8` requires 800ms of continuous silence before detecting end of speech. With 512-sample frames at 16kHz (32ms per frame), that's 25 frames of silence.

From logs:
```
18:10:20 [VoiceCommand] VAD: 25/25 silence frames → end of speech
```

VAD detection itself is fast (800ms is by design). The "slow" perception is from:
1. STT startup time (whisper model load: 4-5s)
2. Parakeet failing and falling back to whisper (adds delay)
3. LLM response time (varies by provider)

**Fix:** Reduce `VAD_SILENCE_SEC` from 0.8 to 0.5 (500ms, ~16 frames). This makes the system feel more responsive without cutting off speech prematurely.

---

### Issue 4: Cadence Animation Different (Whisper vs Parakeet)

**Root cause:** The cadence detector runs during the VAD phase, BEFORE STT. The STT engine (whisper vs parakeet) should NOT affect the cadence animation. But the user sees a difference.

My investigation found:
1. The cadence detector uses **spectral flux** — comparing consecutive FFT frames
2. The smoothing factor was 0.85 (very smooth, 213ms time constant)
3. I changed it to 0.7 (faster, 106ms) and added a noise floor

The user says the WHISPER animation is good. The whisper animation was with the ORIGINAL cadence detector (smoothing 0.85, no noise floor). My changes made it different.

**Fix:** REVERT cadence detector to original settings (smoothing 0.85, history 10, no noise floor). The whisper animation IS the original animation. My changes broke it.

---

### Issue 5: Backend Start Command Doesn't Exit

**Root cause:** `Start-Process` with `-RedirectStandardOutput` keeps the PowerShell pipeline open. The command appears to hang because PowerShell is waiting for the redirected stream to close.

**Fix:** Use `Start-Process` with `-WindowStyle Hidden` and WITHOUT `-RedirectStandardOutput`. The backend already logs to `backend/logs/irisvoice.log`, so console output redirection is unnecessary.

Alternative: Use `Start-Job` with `Start-Process` to fully background the process.

---

### Issue 6: Parakeet GPU Fails (Empty Error)

**Root cause:** The Parakeet TDT model uses `generate()` for inference, not direct `forward()`. The original code called `self._model(input_values=...)` (forward pass) and then `self._processor.batch_decode(outputs)`. TDT models need `generate()` to handle the token decoding properly.

I changed this to use `generate()` + `tokenizer.decode()`, but the test mock needs updating. The actual GPU inference might still fail due to:
1. CUDA OOM (parakeet uses ~1.2GB VRAM, other models might be using VRAM too)
2. Tensor shape mismatch (input might need different preprocessing)
3. Model compatibility (the installed parakeet version might need different API)

**Fix:** The `generate()` change is correct for TDT models. Need to verify it works on the actual GPU. If it still fails, check CUDA memory and model compatibility.

---

### Issue 7: Noticeable Wait Between STT and TTS

**Root cause:** Multiple delays in the pipeline:
1. VAD detects end of speech (800ms)
2. STT processes audio (4-5s for whisper, ~1s for parakeet)
3. LLM generates response (varies by provider, 1-10s)
4. TTS loads model (first call: 1-5s, subsequent: cached)
5. TTS synthesizes audio (1.5x real-time)
6. TTS queue consumer starts (might not be starting at all — see Issue 2)

The total delay from "user stops speaking" to "TTS starts playing" can be 10-20s. The "agent is speaking" state is broadcast BEFORE TTS actually starts playing, creating the perception of a long wait.

**Fix:** 
1. Fix Parakeet (Issue 6) — reduces STT from 4-5s to ~1s
2. Fix TTS queue (Issue 2) — ensures audio actually plays
3. Broadcast "speaking" state only when TTS audio actually starts, not when TTS is queued

---

## Fix Plan (Ordered)

### Fix 1: REVERT TTS tanh to original clip
**File:** `backend/audio/pipeline.py`
**Change:** Replace `np.tanh(audio_float / 0.7) * 0.7` with `np.clip(audio_float * 2.5, -0.99, 0.99)`
**Risk:** None — reverting to known-working code
**Test:** TTS audio should be clear, not static

### Fix 2: REVERT cadence detector to original settings
**File:** `backend/audio/cadence_detector.py`
**Change:** Revert smoothing to 0.85, history to 10, remove noise floor
**Risk:** None — reverting to known-working code
**Test:** Cadence animation should match whisper behavior

### Fix 3: Fix TTS queue consumer flow
**File:** `backend/iris_gateway.py`
**Change:** Trace and fix the producer→consumer flow so `play_stream()` actually receives the audio chunks
**Risk:** Medium — need to understand the existing flow before changing
**Test:** TTS audio should play within 2s of agent responding

### Fix 4: Reduce VAD silence threshold
**File:** `backend/audio/voice_command.py`
**Change:** `VAD_SILENCE_SEC = 0.8` → `VAD_SILENCE_SEC = 0.5`
**Risk:** Low — 500ms is still enough to detect end of speech
**Test:** VAD should detect end of speech faster

### Fix 5: Fix backend start command
**File:** None (PowerShell command change)
**Change:** Use `Start-Process -WindowStyle Hidden` without `-RedirectStandardOutput`
**Risk:** None
**Test:** Command should exit immediately after starting backend

### Fix 6: Verify Parakeet GPU fix
**File:** `backend/audio/voice_command.py` (already changed)
**Change:** Already using `generate()` + `tokenizer.decode()`
**Risk:** Medium — need to verify on actual GPU
**Test:** Parakeet should transcribe without falling back to whisper

### Fix 7: Broadcast "speaking" state when TTS audio starts
**File:** `backend/iris_gateway.py`
**Change:** Move `listening_state: speaking` broadcast to after TTS audio starts playing, not before
**Risk:** Low — cosmetic timing change
**Test:** "Speaking" state should appear when audio actually starts

---

## Implementation Order

1. Fix 1 (TTS tanh revert) — immediate, no investigation needed
2. Fix 2 (cadence revert) — immediate, no investigation needed
3. Fix 5 (backend start) — immediate, no investigation needed
4. Fix 4 (VAD threshold) — immediate, small change
5. Fix 3 (TTS queue) — needs investigation of producer/consumer flow
6. Fix 6 (Parakeet verify) — needs backend running with GPU
7. Fix 7 (speaking state timing) — needs TTS working first

---

## What NOT to Change

- Do NOT change the 2.5x gain — it was working before
- Do NOT add tanh or other non-linear processing — it distorts audio
- Do NOT change the cadence detector algorithm — the original was working
- Do NOT change the VAD energy threshold (0.006) — it was working
- Do NOT change the frame size (512) — it was working
- Do NOT change the sample rate (16kHz) — it was working

---

## Verification Plan

After all fixes:
1. Start backend (command exits immediately)
2. Trigger voice command (double-click orb)
3. Speak a sentence
4. VAD detects end of speech within 500ms
5. Parakeet transcribes (no whisper fallback)
6. LLM responds
7. TTS plays clear audio (no static)
8. Cadence animation matches whisper behavior
9. "Speaking" state appears when audio starts