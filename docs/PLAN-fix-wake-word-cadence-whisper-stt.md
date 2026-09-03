# Fix Plan: Wake Word, Cadence Envelope, and Whisper STT Agent Dispatch

Three issues to fix. Each section has root cause, evidence, exact files/lines,
and step-by-step fix instructions.

---

## Issue 1: Wake word ("Hey Iris") not triggering

### Root cause

`pvporcupine` fails to import **inside the uvicorn server process** despite
being installed and importable from the venv directly. The backend logs show:

```
2026-07-02 01:21:47 [ERROR] backend.audio.engine: [AudioEngine] Porcupine init failed: No module named 'pvporcupine'
```

**However**, running `venv\Scripts\python.exe -c "import pvporcupine"` succeeds.
This means pvporcupine's **native DLL dependencies** are not found when uvicorn
runs the app. pvporcupine bundles platform-specific `.dll`/`.so` files that must
be on the system PATH or in the same directory as the package. When uvicorn
starts, it may run with a different working directory or PATH than an interactive
python shell.

**Secondary bug**: `main.py` line 398-399 logs success regardless of failure:

```python
audio_engine.initialize_porcupine()  # reads phrase + sensitivity from WakeConfig
logger.info("    [+] [PORCUPINE] Initialized with wake word config")  # ALWAYS logs, even on failure
```

`initialize_porcupine()` returns `False` on failure, but the return value is
never checked. This masks the failure from the user — the log says "Initialized"
even when Porcupine is completely broken.

### Evidence
- `backend/logs/irisvoice.log` — `No module named 'pvporcupine'` error
- `venv\Scripts\python.exe -c "import pvporcupine"` — succeeds (confirmed)
- `PorcupineWakeWordDetector(custom_model_path=...)` — succeeds when run directly
- pvporcupine has `create` function and `access_key` parameter (v2+ confirmed)
- `.env.local` has a valid `PICOVOICE_ACCESS_KEY` (56 chars, starts with `wIQuZ/h4`)

### Fix steps

**Step 1**: Fix the false-positive success log in `backend/main.py` (~line 398):

```python
# BEFORE:
audio_engine.initialize_porcupine()
logger.info("    [+] [PORCUPINE] Initialized with wake word config")

# AFTER:
if audio_engine.initialize_porcupine():
    logger.info("    [+] [PORCUPINE] Initialized with wake word config")
else:
    logger.error("    [x] [PORCUPINE] Initialization FAILED — wake word detection disabled")
```

**Step 2**: Add a diagnostic pre-flight check that tests `import pvporcupine`
inside the server process BEFORE calling `initialize_porcupine()`, so the error
message is clear about *why* it failed (DLL vs package vs key):

In `backend/audio/engine.py`, inside `initialize_porcupine()`, add a try/except
around the lazy `import pvporcupine` that logs the full exception chain including
`exc_info=True` and specifically checks for DLL load failures:

```python
try:
    import pvporcupine
except ImportError as e:
    logger.error(
        f"[AudioEngine] pvporcupine import failed: {e}\n"
        f"This is usually a missing native DLL. Try:\n"
        f"  1. pip install --force-reinstall pvporcupine\n"
        f"  2. Ensure Visual C++ Redistributable is installed\n"
        f"  3. Check that venv\\Lib\\site-packages\\pvporcupine\\lib\\win\\*.dll exists",
        exc_info=True,
    )
    self._porcupine_initialized = False
    return False
```

**Step 3**: The actual DLL fix — ensure pvporcupine's bundled DLLs are on PATH.
Add to `backend/main.py` lifespan startup, BEFORE any audio imports:

```python
# Ensure pvporcupine native DLLs are loadable
import pvporcupine as _pv_check
import os as _os
_pv_lib_dir = _os.path.join(_os.path.dirname(_pv_check.__file__), "lib")
if _os.path.isdir(_pv_lib_dir):
    _os.environ["PATH"] = _pv_lib_dir + _os.pathsep + _os.environ.get("PATH", "")
```

Alternatively, try `pip install --force-reinstall pvporcupine` in the venv to
ensure the native binaries are properly extracted.

**Step 4**: Verify the fix by restarting the backend and checking logs for:
- No "No module named 'pvporcupine'" error
- `initialize_porcupine()` returns True
- Say "Hey Iris" and confirm `[AudioEngine] Wake word detected` appears in logs

### Files to modify
- `backend/main.py` (~line 398) — check return value, fix false-positive log
- `backend/audio/engine.py` (~line 135, `initialize_porcupine`) — better error logging
- Possibly reinstall pvporcupine in venv

---

## Issue 2: Parakeet path — orb cadence/volume not reactive (whisper fallback IS reactive)

### Root cause

Both Parakeet and whisper use the SAME `_capture_frame()` method (line ~845 in
`voice_command.py`) which broadcasts `audio_envelope` every 3 frames via
`self._on_audio_envelope(level, cadence, "listening")`. So during the RECORDING
phase the orb SHOULD react identically regardless of STT backend.

The difference is **after** recording ends — during the PROCESSING phase:

1. **Whisper path**: Model is pre-warmed (`warm_up()` at line ~225 runs a silent
   inference at startup), so transcription is instant (~80ms). The orb barely
   sits in "processing" state. Envelope broadcasts continue from `_capture_frame`
   for the brief processing window.

2. **Parakeet path**: The 0.6B model loads lazily on first call
   (`ParakeetTranscriber._ensure_loaded()` at line ~48). First load takes
   **10-30+ seconds** (downloading + GPU transfer). During this entire window:
   - `_run_transcription` sets `VoiceState.PROCESSING` (line ~562)
   - `_capture_frame` is still registered as a frame listener, but
     `is_recording=False` (set at line ~548), so `_capture_frame` returns early
     at the `if not self.is_recording: return` guard (line ~863)
   - **No audio_envelope messages are sent during processing**
   - The orb is stuck in "processing" with zero cadence/volume feedback
   - Even after the model loads, `transcribe()` runs on GPU with no envelope
     updates until it returns

3. **The VAD loop** (`_vad_wait_for_speech_then_silence`, line ~718) sends
   `audio_envelope` every 3 frames via `_on_audio_envelope`, but ONLY while
   the VAD loop is running (i.e., during recording, not during processing).

### Fix steps

**Step 1**: Pre-warm Parakeet at startup (same pattern as whisper `warm_up()`).
In `backend/audio/voice_command.py`, `__init__()` (~line 226), add Parakeet
preloading alongside the whisper warm-up:

```python
# Warm up the STT model immediately (background thread)
self.warm_up()

# Pre-load Parakeet GPU model in background so first transcription is instant
self._parakeet_warm_up()
```

Add the method:
```python
def _parakeet_warm_up(self) -> None:
    """Pre-load Parakeet GPU model in background daemon thread."""
    def _do_warm():
        try:
            if self._parakeet._ensure_loaded():
                logger.info("[VoiceCommand] Parakeet GPU pre-loaded — first transcription will be instant")
            else:
                logger.warning(f"[VoiceCommand] Parakeet pre-load failed — will use whisper fallback")
        except Exception as exc:
            logger.warning(f"[VoiceCommand] Parakeet warm-up failed (non-fatal): {exc}")
    threading.Thread(target=_do_warm, daemon=True, name="iris-parakeet-warmup").start()
```

**Step 2**: Send `audio_envelope` with phase="processing" during the
transcription phase. In `_run_transcription()` (line ~560), AFTER setting
`VoiceState.PROCESSING` and BEFORE calling the transcriber, emit periodic
envelope updates so the orb shows a subtle "thinking" pulse:

```python
self._set_state(VoiceState.PROCESSING, "Transcribing...")

# Emit a low-level envelope pulse during processing so the orb
# shows a subtle breathing pattern instead of going completely dead.
if self._on_audio_envelope:
    self._on_audio_envelope(0.15, 0.08, "processing")
```

For a continuous pulse, wrap the transcription call with a timer that emits
envelope updates every ~100ms while the transcriber is running:

```python
import threading
_pulse_stop = threading.Event()
def _pulse():
    while not _pulse_stop.is_set():
        if self._on_audio_envelope:
            self._on_audio_envelope(0.15, 0.08, "processing")
        _pulse_stop.wait(0.1)
threading.Thread(target=_pulse, daemon=True).start()
transcript = self._transcribe_via_parakeet(audio_np)
_pulse_stop.set()
```

**Step 3**: Verify the gateway broadcasts `audio_envelope` with phase
"processing" — check `backend/iris_gateway.py` line ~1634
(`_on_audio_envelope`) to ensure it forwards all phases including "processing"
(not just "listening" and "speaking").

### Files to modify
- `backend/audio/voice_command.py` — add `_parakeet_warm_up()`, add processing envelope pulse
- `backend/iris_gateway.py` (~line 1634) — verify `audio_envelope` with phase="processing" is forwarded to frontend

---

## Issue 3: Whisper fallback with VAD — STT result not dispatched to agent / no TTS playback

### Root cause

Two compounding issues prevent the whisper fallback path from reaching the
agent pipeline:

**3a. Whisper's own VAD filter strips already-VAD-trimmed audio → empty transcript**

In `_run_transcription()` (~line 672), the whisper fallback call uses:
```python
segments, _ = whisper.transcribe(
    audio_np,
    language="en",
    beam_size=1,
    best_of=1,
    condition_on_previous_text=False,
    vad_filter=True,                          # ← PROBLEM
    vad_parameters={"min_silence_duration_ms": 300},
)
```

The energy-based VAD in `_vad_wait_for_speech_then_silence()` has ALREADY
detected end-of-speech and trimmed the audio to just the speech segment.
Whisper's built-in Silero VAD filter (`vad_filter=True`) then re-analyzes this
already-trimmed clip. For short utterances (1-3 seconds), whisper's VAD can:
- Reject the entire clip as "non-speech" → returns 0 segments → `transcript=""`
- Strip leading/trailing speech that our VAD already included → partial/empty text

When `transcript=""`:
- `_on_transcription_complete("")` is called (line ~899)
- The gateway's `_on_voice_result` (line ~1948) checks `if not transcript`
- Empty transcript → logs warning, sends `listening_state: idle`, and returns
- **Agent is never called, no TTS playback occurs**

**3b. The energy VAD's `VAD_ENERGY_THRESHOLD` (0.006) may be too low for clear speech**

If the mic input level is low (quiet room, low gain), speech frames may not
cross the 0.006 RMS threshold, so `speech_started` never becomes True. The VAD
loop hits `pre_speech_timeout` or `max_frames` and returns with
`_raw_frames` populated (all frames captured) but `speech_started=False`.

In this case the code at line ~548 (`self.is_recording = False`) runs, then
line ~555 checks `if not self._raw_frames` — but `_raw_frames` IS populated
(all frames were captured even though no speech was detected). So it proceeds
to transcribe, but the audio is mostly silence/background, which whisper's VAD
filter then strips entirely.

### Fix steps

**Step 1 (CRITICAL)**: Disable whisper's redundant VAD filter. Our energy VAD
already handles end-of-speech detection. In `backend/audio/voice_command.py`,
`_run_transcription()` (~line 672), change:

```python
# BEFORE:
segments, _ = whisper.transcribe(
    audio_np,
    language="en",
    beam_size=1,
    best_of=1,
    condition_on_previous_text=False,
    vad_filter=True,
    vad_parameters={"min_silence_duration_ms": 300},
)

# AFTER:
segments, _ = whisper.transcribe(
    audio_np,
    language="en",
    beam_size=1,
    best_of=1,
    condition_on_previous_text=False,
    vad_filter=False,  # Our energy VAD already trimmed — whisper VAD strips too aggressively
)
```

**Step 2**: Add a retry without VAD when whisper returns empty text. After the
whisper fallback returns empty, try once more with `vad_filter=False` (in case
the primary call had VAD enabled for some reason):

```python
transcript = " ".join(s.text.strip() for s in segments).strip()
if not transcript:
    logger.warning("[STT] whisper returned empty with VAD — retrying without VAD filter")
    segments, _ = whisper.transcribe(
        audio_np,
        language="en",
        beam_size=1,
        best_of=1,
        condition_on_previous_text=False,
        vad_filter=False,
    )
    transcript = " ".join(s.text.strip() for s in segments).strip()
```

**Step 3**: Log when empty transcripts are dispatched so it's debuggable. In
`_on_transcription_complete()` (line ~899), add explicit logging:

```python
if not transcript:
    logger.warning(
        "[VoiceCommand] Empty transcript dispatched to gateway — "
        "agent will NOT be called. Check: (1) mic input level, "
        "(2) VAD_ENERGY_THRESHOLD, (3) whisper vad_filter stripping speech"
    )
```

**Step 4**: Verify the fix:
1. Restart backend
2. Double-click orb (whisper fallback path, auto_stop=False)
3. Speak a short phrase
4. Single-click to stop recording
5. Check logs for `[STT] whisper CPU — 'your text'` (non-empty)
6. Confirm agent response appears and TTS plays

### Files to modify
- `backend/audio/voice_command.py` (~line 672) — disable `vad_filter`, add retry without VAD
- `backend/audio/voice_command.py` (~line 899) — better empty-transcript logging

---

## Verification checklist (for the executing agent)

After all fixes, verify each issue:

1. **Wake word**: Say "Hey Iris" → orb flashes → listening state → speak → VAD stops → transcription → agent response → TTS playback
2. **Cadence with Parakeet**: Double-click orb → speak → orb breathes with voice → Parakeet transcribes → orb shows processing pulse → agent responds → TTS plays → orb breathes with TTS
3. **Whisper fallback STT dispatch**: Force Parakeet to fail (temporarily set `PARAKEET_DISABLED=1` or similar) → double-click orb → speak → stop → whisper transcribes non-empty text → agent responds → TTS plays

## Do NOT skip
- Re-read each file before editing (the line numbers above are approximate)
- Run `venv\Scripts\python.exe -c "compile(open('backend/audio/voice_command.py',encoding='utf-8').read(),'f.py','exec'); print('OK')"` after each edit
- Restart backend after all edits and check `backend/logs/irisvoice.log` for errors
- Kill and restart both backend (port 8090) and frontend (port 3000) servers