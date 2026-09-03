# IRIS Voice — Timing, Sync & Pipeline Overlap Plan

> **Status**: Phase 1 ready for implementation
> **Date**: 2026-07-03
> **Author**: OpenWork session 147
> **Scope**: Fix 4 immediate issues + close STT→TTS latency gap + design ConversationKernel/TaskKernel separation

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Current Pipeline Architecture](#2-current-pipeline-architecture)
3. [Phase 1: Immediate Fixes](#3-phase-1-immediate-fixes)
4. [Phase 2: ConversationKernel/TaskKernel Separation](#4-phase-2-conversationkerneltaskkernel-separation)
5. [C++ Performance Assessment](#5-c-performance-assessment)
6. [Implementation Order](#6-implementation-order)
7. [Verification Checklist](#7-verification-checklist)
8. [Appendix: Exact Line References](#8-appendix-exact-line-references)

---

## 1. Problem Statement

The conversational STT/TTS pipeline works — the user can talk back and forth with the agent. However, six issues degrade the real-time experience:

1. **Barge-in doesn't fire** — speaking during TTS doesn't interrupt
2. **VAD cuts off too early** — natural pauses trigger STT processing
3. **STTPROC.wav is inaudible** — no processing sound between STT and TTS
4. **Orb cadence animation lags** — breathing visuals stutter during speech
5. **TTS delay after text** — 5-8 seconds between text appearing in chat and TTS audio playing
6. **Barge-in pipeline safety** — must not break the audio pipeline if it fires mid-generation

---

## 2. Current Pipeline Architecture

### STT → LLM → TTS Flow

```
User speaks
  → Mic capture (PortAudio, 16kHz, 512-frame chunks)
  → VAD loop (voice_command.py, line 200+)
    → Energy threshold check → silence detection (0.5s) → end of speech
  → STT transcription (Parakeet TDT on GPU, or Whisper fallback)
  → LLM generation (streamed via chunk_callback, iris_gateway.py line 2148)
    → chunk_callback:
      1. Sends text to frontend via chat_chunk WebSocket message (line 2150)
      2. Accumulates text in sentence_buf (line 2165)
      3. Waits for sentence boundary ([.!?]\s+) → pushes to sentence_queue (line 2170)
  → TTS thread (_wrap_tts_streaming, line 2236)
    → _speak_response creates producer thread (line 2731)
    → Producer consumes sentence_queue (line 2566)
    → Splits sentence into word chunks (first chunk = 1 word, line 2388)
    → Calls tts.synthesize_stream(chunk) (line 2632)
      → _stream_pocket → model.generate_audio_stream(voice_state, text)
      → Skips first ~3 chunks (silent lead-in, < 0.01 amplitude, tts.py line 589)
      → Yields audible chunks
    → "speaking" state broadcast AFTER first audio chunk (line 2653-2678)
    → Audio pushed to native player (line 2610) or audio_queue (line 2618)
  → Audio plays through speakers
```

### Key Files

| File | Role |
|------|------|
| `backend/iris_gateway.py` | Orchestrates STT→LLM→TTS flow, barge-in callback, STTPROC, sentence queue |
| `backend/audio/voice_command.py` | VAD loop, STT transcription, watchdog timer |
| `backend/audio/engine.py` | Audio engine singleton, barge-in energy detection, half-duplex gate |
| `backend/audio/pipeline.py` | PortAudio I/O, RMS computation, echo cancellation gate |
| `backend/audio/cadence_detector.py` | Spectral flux cadence detection (FFT, ~31Hz) |
| `backend/agent/tts.py` | Pocket-TTS model loading, synthesize_stream, _stream_pocket |
| `backend/agent/conversation_kernel.py` | Thin Caducean wrapper (TTS chunk sizing, barge-in nudge) |
| `backend/agent/streaming.py` | chunk_batcher for WebSocket chat_chunk messages |
| `hooks/useClientMicCadence.ts` | Client-side mic cadence (rAF, 60fps) |
| `hooks/useCadenceDetection.ts` | Priority chain: backend cadence → backend RMS → client mic |
| `components/iris/orb/OrbCanvas.tsx` | Canvas particle rendering (168 particles, rAF loop) |
| `components/iris/XurOrb.tsx` | Orb component, label scramble, animation modes |
| `backend/tests/test_barge_in.py` | Barge-in unit tests (17 tests) |
| `backend/tests/test_voice_command_parakeet.py` | Parakeet transcription tests (6 tests) |

---

## 3. Phase 1: Immediate Fixes

### Step 0: Pocket-TTS Streaming Verification

**Before designing the latency fix**, run a timing test to determine if `generate_audio_stream()` is truly streaming (yields chunks during generation) or batch-generates then chunks.

**Action**: Create and run `backend/tests/test_tts_streaming_timing.py`:

```python
"""Timing test — determines if Pocket-TTS streams or batch-generates.

Usage: python -m backend.tests.test_tts_streaming_timing
"""
import time, os, sys
os.environ.setdefault("IRIS_ENV", "development")

def main():
    from pocket_tts import TTSModel
    model = TTSModel.load_model(language="english", eos_threshold=-1.0)
    voice_state = model.get_state_for_audio_prompt("data/TOMV2.wav")

    text = "Hello, this is a test sentence to measure the timing characteristics of the streaming audio generation."
    t0 = time.monotonic()
    first_chunk_time = None
    chunk_count = 0
    for chunk in model.generate_audio_stream(voice_state, text, frames_after_eos=0):
        chunk_count += 1
        if first_chunk_time is None:
            first_chunk_time = time.monotonic() - t0
    total_time = time.monotonic() - t0

    print(f"First chunk: {first_chunk_time:.2f}s")
    print(f"Total: {total_time:.2f}s")
    print(f"Chunks: {chunk_count}")
    if first_chunk_time and total_time:
        ratio = first_chunk_time / total_time
        if ratio < 0.3:
            print("VERDICT: STREAMING — first chunk arrives early, rest streams")
        else:
            print("VERDICT: BATCH — first chunk arrives near end of generation")

if __name__ == "__main__":
    main()
```

**Run**: `python -m backend.tests.test_tts_streaming_timing`

**Decision branch**:
- **If STREAMING** (first chunk < 30% of total): Latency fix focuses on shorter first sentences + pre-warm. Chunks arrive during generation, so the user hears audio quickly.
- **If BATCH** (first chunk ≈ total): Latency fix must also split text into smaller chunks (20-30 chars) to reduce per-batch generation time. Each batch generates in ~1s instead of ~5s.

---

### Issue 1: Barge-In Doesn't Fire

#### Root Cause

Three compounding issues:
1. **Threshold too high (0.06)**: Normal speech through a desktop mic while TTS is playing often produces RMS of 0.03–0.05.
2. **Total detection window too long (1.6s)**: Arm delay (0.8s) + 25 frames (0.8s) = 1.6 seconds.
3. **No barge-in log messages appear at all**, suggesting the RMS never reaches 0.06.

#### Fix — `backend/audio/engine.py`

**Change 1: Constants (line ~330)**

Find these lines (around line 330):
```python
    BARGE_IN_ENERGY_THRESHOLD: float = 0.06     # RMS level to trigger barge-in
    BARGE_IN_CONSECUTIVE_FRAMES: int = 25       # ~800 ms sustained speech
    BARGE_IN_ARM_DELAY: float = 0.8             # seconds after TTS starts before barge-in is armed
```

Replace with:
```python
    BARGE_IN_ENERGY_THRESHOLD: float = 0.04     # RMS level to trigger barge-in
    BARGE_IN_CONSECUTIVE_FRAMES: int = 15       # ~500 ms sustained speech
    BARGE_IN_ARM_DELAY: float = 0.3             # seconds after TTS starts before barge-in is armed
```

**Change 2: Debug logging in `_on_barge_in_energy` (line ~355)**

Find the method (around line 355):
```python
    def _on_barge_in_energy(self, rms: float) -> None:
        """..."""
        # Suppress barge-in during the arm delay window
        import time as _time
        if _time.monotonic() - self._barge_in_arm_time < self.BARGE_IN_ARM_DELAY:
            return

        if rms >= self.BARGE_IN_ENERGY_THRESHOLD:
```

Replace the arm delay check with debug logging:
```python
    def _on_barge_in_energy(self, rms: float) -> None:
        """..."""
        import time as _time
        elapsed = _time.monotonic() - self._barge_in_arm_time
        armed = elapsed >= self.BARGE_IN_ARM_DELAY
        if not armed:
            return

        if self._logger:
            self._logger.debug(
                "[barge_in] rms=%.4f frames=%d/%d armed=%s",
                rms, self._barge_in_frame_count,
                self.BARGE_IN_CONSECUTIVE_FRAMES, armed,
            )

        if rms >= self.BARGE_IN_ENERGY_THRESHOLD:
```

**Change 3: Test updates — `backend/tests/test_barge_in.py`**

Find the fixture (around line 30):
```python
        eng.BARGE_IN_ENERGY_THRESHOLD = 0.06
        eng.BARGE_IN_CONSECUTIVE_FRAMES = 25
        eng.BARGE_IN_ARM_DELAY = 0.8
```

Replace with:
```python
        eng.BARGE_IN_ENERGY_THRESHOLD = 0.04
        eng.BARGE_IN_CONSECUTIVE_FRAMES = 15
        eng.BARGE_IN_ARM_DELAY = 0.3
```

**IMPORTANT**: There are MULTIPLE places in test_barge_in.py where these constants appear (fixture, TestMultipleBargeIns, TestPipelineEnergyCallback, test_gate_reopens_on_barge_in, test_engine_registers_callback_on_start). Use `replaceAll` or find every occurrence. Search for `0.06`, `25`, `0.8` in the test file and replace with `0.04`, `15`, `0.3` respectively.

**Test values that DON'T need changing**: The test uses `0.08` for "above threshold" (still above 0.04 ✓) and `0.03` for "below threshold" (still below 0.04 ✓).

**Verify**: Run `python -m pytest backend/tests/test_barge_in.py::TestBargeInDetection backend/tests/test_barge_in.py::TestConstants backend/tests/test_barge_in.py::TestMultipleBargeIns -v`

---

### Issue 2: VAD Too Sensitive

#### Root Cause

`VAD_SILENCE_SEC = 0.5` at `voice_command.py:183` — 500ms of silence triggers end-of-speech.

#### Fix — `backend/audio/voice_command.py`

Find line 183:
```python
    VAD_SILENCE_SEC: float = 0.5
```

Replace with:
```python
    VAD_SILENCE_SEC: float = 0.8
```

**No test changes needed** — VAD silence is not directly tested in unit tests (it's an integration parameter).

---

### Issue 3: STTPROC Inaudible + Filler Phrases

#### Root Cause — STTPROC

The STTPROC.wav file is -27.4 dBFS (extremely quiet). The playback code does `sd.play(data, sr, device=dev, blocking=True)` with no gain.

#### Fix Part A — STTPROC Amplification

**File**: `backend/iris_gateway.py`

Find the `_loop_sttproc` function (around line 2085-2137). Inside the loop, find the `sd.play` call (around line 2125):

```python
                    sd.play(
                        data,
                        sr,
                        device=_sttproc_dev,
                        blocking=True,
                    )
```

Replace with:
```python
                    # Apply 3x gain (+9.5 dB) — WAV file is -27.4 dBFS, needs to be ~-18 dBFS
                    import numpy as _np
                    _play_data = _np.clip(data * 3.0, -1.0, 1.0).astype(_np.float32)
                    sd.play(
                        _play_data,
                        sr,
                        device=_sttproc_dev,
                        blocking=True,
                    )
```

**Note**: `data` is already a numpy array from `soundfile.read()`. The `np.clip` prevents digital clipping.

#### Fix Part B — Filler Phrase Pre-synthesis

**File**: `backend/agent/tts.py`

Find the `_load_pocket_tts` method (around line 421). After the model loads successfully (after the `self._pocket_tts_model = TTSModel.load_model(...)` line, around line 440), add filler pre-synthesis:

```python
            self._pocket_tts_model = TTSModel.load_model(
                language=model_lang,
                eos_threshold=-1.0,
            )
            # ── Pre-synthesize filler phrases for zero-latency playback ──
            self._filler_cache = {}
            self._pre_synthesize_fillers()
```

Then add a new method after `_load_pocket_tts`:

```python
    def _pre_synthesize_fillers(self) -> None:
        """Pre-synthesize conversational filler phrases as cached WAV arrays."""
        import numpy as np
        import hashlib
        import os

        FILLER_PHRASES = [
            "Mm, let me think about that.",
            "Got it, one second.",
            "Right, let me check.",
            "Okay, thinking...",
        ]

        # Load voice state from reference audio
        ref_path = os.path.join(os.path.dirname(__file__), "..", "data", "TOMV2.wav")
        if not os.path.exists(ref_path):
            self._logger.warning("[TTS] No reference voice for fillers — using default")
            voice_state = None
        else:
            voice_state = self._pocket_tts_model.get_state_for_audio_prompt(ref_path)

        cache_dir = os.path.join(os.path.dirname(__file__), "..", "data", "fillers")
        os.makedirs(cache_dir, exist_ok=True)

        for phrase in FILLER_PHRASES:
            cache_key = hashlib.md5(phrase.encode()).hexdigest()
            cache_path = os.path.join(cache_dir, f"{cache_key}.npy")

            if os.path.exists(cache_path):
                # Load from cache
                audio = np.load(cache_path)
                self._filler_cache[phrase] = (audio, self._pocket_tts_model.sample_rate)
                self._logger.info(f"[TTS] Filler loaded from cache: {phrase!r}")
            else:
                # Synthesize and cache
                chunks = []
                for chunk in self._pocket_tts_model.generate_audio_stream(
                    voice_state, phrase, frames_after_eos=0
                ):
                    audio = chunk.cpu().numpy().astype(np.float32)
                    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
                    if np.max(np.abs(audio)) < 0.01:
                        continue
                    chunks.append(audio)
                if chunks:
                    full_audio = np.concatenate(chunks)
                    np.save(cache_path, full_audio)
                    self._filler_cache[phrase] = (full_audio, self._pocket_tts_model.sample_rate)
                    self._logger.info(f"[TTS] Filler synthesized: {phrase!r} ({len(full_audio)} samples)")

    def get_filler_phrase(self) -> tuple | None:
        """Return a random (audio_array, sample_rate) filler phrase, or None."""
        import random
        if not self._filler_cache:
            return None
        phrase = random.choice(list(self._filler_cache.keys()))
        return self._filler_cache[phrase]
```

**Also**: Add `self._filler_cache = {}` to the `__init__` method of the TTS class. Find the `__init__` and add:
```python
        self._filler_cache: dict = {}
```

#### Fix Part C — Filler Playback Alongside STTPROC

**File**: `backend/iris_gateway.py`

Find the STTPROC start section (around line 2137, where `_sttproc_thread.start()` is called). After the STTPROC thread starts, add filler playback:

```python
                    _sttproc_thread.start()
                    self._logger.info("[STTPROC] Loop started")

                    # ── Play filler phrase alongside STTPROC ──
                    # Pre-synthesized, zero-latency. Plays once while STTPROC loops.
                    try:
                        from backend.agent.tts import TTSEngine
                        _tts_eng = TTSEngine.get_instance()
                        _filler = _tts_eng.get_filler_phrase()
                        if _filler is not None:
                            _filler_audio, _filler_sr = _filler
                            import threading as _th
                            def _play_filler():
                                try:
                                    import sounddevice as _sd
                                    _sd.play(_filler_audio, _filler_sr, device=_sttproc_dev, blocking=True)
                                except Exception:
                                    pass
                            _filler_thread = _th.Thread(target=_play_filler, daemon=True, name="filler-playback")
                            _filler_thread.start()
                            self._logger.info("[STTPROC] Filler phrase started alongside STTPROC")
                    except Exception as _filler_err:
                        self._logger.warning(f"[STTPROC] Filler playback failed: {_filler_err}")
```

**IMPORTANT**: The filler plays on a separate thread using `sounddevice.play()` with `blocking=True`. This plays simultaneously with the STTPROC loop because `sounddevice` can open multiple output streams on the same device (PortAudio supports this).

**Note**: `_sttproc_dev` is already defined earlier in the STTPROC setup code. If it's None (first call), the filler will use the default device, which should match.

#### Fix Part D — Stop STTPROC on First TTS Audio (Not Before)

**File**: `backend/iris_gateway.py`

Find line 2726 (inside `_speak_response`, before the producer thread starts):
```python
            if _sttproc_stop is not None:
                _sttproc_stop.set()
```

**Remove this line** (or comment it out). Instead, pass `_sttproc_stop` to the producer thread and stop it when the first audio chunk is pushed.

Find the producer thread definition (around line 2731) and add `_sttproc_stop` as a parameter:

```python
            def _producer(
                input_source,
                audio_queue,
                interrupted,
                engine,
                tts,
                session_id,
                _sttproc_stop=None,  # ← ADD THIS PARAMETER
            ):
```

Then inside the producer, after the first audio chunk is pushed to the player (around line 2653, where `is_first_chunk` is handled), add:

```python
                            if is_first_chunk:
                                is_first_chunk = False
                                _target = NORMAL_CHUNK_THRESHOLD
                                # Stop STTPROC + filler now that TTS audio is playing
                                if _sttproc_stop is not None and not _sttproc_stop.is_set():
                                    _sttproc_stop.set()
                                # Broadcast "speaking" on first audio chunk
```

**Also**: Update the `_producer` call site (around line 2731) to pass `_sttproc_stop`:

Find:
```python
            _prod_thread = threading.Thread(
                target=_producer,
                args=(input_source, audio_queue, interrupted, engine, tts, session_id),
                daemon=True,
                name="tts-producer",
            )
```

Replace with:
```python
            _prod_thread = threading.Thread(
                target=_producer,
                args=(input_source, audio_queue, interrupted, engine, tts, session_id, _sttproc_stop),
                daemon=True,
                name="tts-producer",
            )
```

---

### Issue 4: Orb Cadence Animation Lag

#### Root Cause

`useClientMicCadence.ts:150` calls `setCadence(val)` inside `requestAnimationFrame` — 60 React state updates per second.

#### Fix — 4 Files

**File 1: `hooks/useClientMicCadence.ts`**

Find the rAF callback (around line 140-155). The current code calls `setCadence(val)`:

```typescript
    // Inside the rAF loop:
    setCadence(val)  // ← THIS triggers 60 re-renders/sec
```

**Change**: Replace `setCadence(val)` with a ref update. The hook should return a ref instead of state.

Find the hook's state declaration (around line 10):
```typescript
  const [cadence, setCadence] = useState(0)
```

Replace with:
```typescript
  const cadenceRef = useRef(0)
```

Find the return statement (around line 160):
```typescript
  return cadence
```

Replace with:
```typescript
  return cadenceRef
```

Find the `setCadence(val)` call inside the rAF loop (around line 150):
```typescript
    setCadence(val)
```

Replace with:
```typescript
    cadenceRef.current = val
```

**File 2: `hooks/useCadenceDetection.ts`**

The hook currently calls `useClientMicCadence()` and gets a number. Now it gets a ref.

Find (around line 30):
```typescript
  const clientCadence = useClientMicCadence()
```

This now returns a `React.MutableRefObject<number>` instead of a number. The priority logic needs to read `.current`.

Find the return block (around line 60-75) where the priority chain computes the final values. Replace the client cadence references:

```typescript
  // Before: clientCadence is a number
  const listeningLevel = cadenceLevel || audioLevel || clientCadence

  // After: clientCadence is a ref
  const listeningLevel = cadenceLevel || audioLevel || clientCadence.current
```

**Also**: The hook needs to pass the ref to OrbCanvas. Add a new return value:

Find the return statement (around line 75):
```typescript
  return {
    breathMode,
    breathLevel,
    isBreathing,
  }
```

Replace with:
```typescript
  return {
    breathMode,
    breathLevel,
    isBreathing,
    clientCadenceRef: clientCadence,  // pass ref to OrbCanvas for rAF loop
  }
```

**File 3: `components/iris/orb/OrbCanvas.tsx`**

**Change 1**: Add `clientCadenceRef` to props.

Find the props interface (around line 20):
```typescript
interface OrbCanvasProps {
  glowColor: string
  breathMode?: string
  breathLevel?: number
  isBreathing?: boolean
  animationMode?: AnimationMode | null
  animActive?: boolean
}
```

Add:
```typescript
  clientCadenceRef?: React.MutableRefObject<number>
```

**Change 2**: Store the ref and read it in the rAF loop.

Find the ref declarations (around line 90):
```typescript
  const breathLevelRef = useRef<number>(0)
  const isBreathingRef = useRef<boolean>(false)
  breathLevelRef.current = breathLevel
  isBreathingRef.current = isBreathing
```

After these lines, add:
```typescript
  // Read client mic cadence directly from ref — no React re-render needed
  const clientCadence = clientCadenceRef?.current ?? 0
```

**Change 3**: Use client cadence in the rAF loop's breath calculation.

Find the `draw()` function (around line 300):
```typescript
    function draw() {
      const elapsed = Date.now() - (startTimeRef.current ?? Date.now())
      const pulse = pulseRef.current
      const aPulse = pulseARef.current
      const mode = modeRef.current
      const bl = breathLevelRef.current
      const br = isBreathingRef.current
```

After `const br = isBreathingRef.current`, add:
```typescript
      // If backend isn't sending cadence (bl === 0), use client mic cadence
      const effectiveBl = bl > 0 ? bl : (clientCadenceRef?.current ?? 0)
```

Then replace all subsequent uses of `bl` with `effectiveBl` in the draw function. Specifically:
- Line 339: `if (br && bl > 0)` → `if (br && effectiveBl > 0)`
- Line 340: `const breathPulse = bl` → `const breathPulse = effectiveBl`
- Line 353: `if (br && bl > 0)` → `if (br && effectiveBl > 0)`
- Line 355: `drawBreathHalo(bl, glowColor)` → `drawBreathHalo(effectiveBl, glowColor)`
- Line 357: `drawBreathHaloFaint(bl, glowColor)` → `drawBreathHaloFaint(effectiveBl, glowColor)`
- Line 365: `drawShell(shell, progress, s, scaleMul, bloom, overallAlpha, elapsed, glowColor, br, bl)` → `... br, effectiveBl)`
- Line 369: `drawCenterCore(bl, glowColor, br)` → `drawCenterCore(effectiveBl, glowColor, br)`

**Change 4**: Add `React.memo` with custom comparator.

Find the component export (around line 30):
```typescript
export function OrbCanvas({
  glowColor,
  breathMode,
  breathLevel,
  isBreathing,
  animationMode,
  animActive,
}: OrbCanvasProps) {
```

Wrap with `React.memo`:
```typescript
export const OrbCanvas = React.memo(function OrbCanvas({
  glowColor,
  breathMode,
  breathLevel,
  isBreathing,
  animationMode,
  animActive,
  clientCadenceRef,
}: OrbCanvasProps) {
  // ... existing code ...
}, (prev, next) => {
  // Only re-render if visual props changed.
  // breathLevel/isBreathing are read from refs in rAF loop, not needed for re-render.
  return prev.glowColor === next.glowColor &&
         prev.animationMode === next.animationMode &&
         prev.animActive === next.animActive
})
```

**IMPORTANT**: The `React.memo` comparator must return `true` to SKIP re-render. The function returns `true` when props are equal (skip), `false` when different (re-render).

**File 4: `components/iris/XurOrb.tsx`**

Find where OrbCanvas is rendered (around line 439):
```typescript
            <OrbCanvas
              glowColor={glowColor}
              breathMode={cadence.breathMode}
              breathLevel={cadence.breathLevel}
              isBreathing={cadence.isBreathing}
              animationMode={animationMode}
              animActive={animActive}
            />
```

Add the `clientCadenceRef` prop:
```typescript
            <OrbCanvas
              glowColor={glowColor}
              breathMode={cadence.breathMode}
              breathLevel={cadence.breathLevel}
              isBreathing={cadence.isBreathing}
              animationMode={animationMode}
              animActive={animActive}
              clientCadenceRef={cadence.clientCadenceRef}
            />
```

**Verify**: Run `npx tsc --noEmit` to check TypeScript compilation. Then visually verify the orb breathes smoothly in the browser.

---

### Issue 5: STT→TTS Latency Gap (5-8 seconds)

#### Root Cause

1. **Sentence boundary wait**: `chunk_callback` waits for `[.!?]\s+` before pushing to TTS
2. **TTS generation time**: 4.63s for 152 chars (batch or streaming unknown until Step 0)
3. **No pre-warm**: First `generate_audio_stream` call may have GPU initialization overhead
4. **STTPROC stops before TTS audio is ready**: Dead air gap
5. **"speaking" state broadcast delayed**: Only after first audio chunk

#### Fix A — Shorter First-Sentence Boundary

**File**: `backend/iris_gateway.py`

Find the `chunk_callback` function (around line 2148). Find the sentence boundary detection (around line 2170):

```python
                    m := _re.search(r"([.!?])\s+", text)
```

Replace with:
```python
                    # Flush on sentence boundary, semicolon, comma+space, or after 40 chars
                    m := _re.search(r"([.!?;])\s+|,\s+(?=[A-Z])|(?<=.{40})\s+", text)
```

**Explanation**: 
- `[.!?;]\s+` — sentence boundary or semicolon
- `,\s+(?=[A-Z])` — comma followed by space and capital letter (clause boundary)
- `(?<=.{40})\s+` — after 40 characters, flush on next whitespace (character-count fallback)

This means the first TTS generation starts after ~40 chars instead of waiting for a full 152-char sentence. A 40-char chunk generates in ~1.5s instead of 4.6s.

#### Fix B — TTS Pre-warm

**File**: `backend/agent/tts.py`

Find the `_load_pocket_tts` method (around line 440, after model loads). After the filler pre-synthesis code (added in Issue 3), add:

```python
            # ── Pre-warm GPU kernels with dummy generation ──
            # First call to generate_audio_stream pays CUDA initialization cost.
            # Running a dummy generation during startup eliminates this on first real use.
            try:
                self._logger.info("[TTS] Pre-warming GPU kernels...")
                _warm_text = "System ready."
                _warm_voice = self._pocket_tts_model.get_state_for_audio_prompt(
                    os.path.join(os.path.dirname(__file__), "..", "data", "TOMV2.wav")
                )
                for _ in self._pocket_tts_model.generate_audio_stream(
                    _warm_voice, _warm_text, frames_after_eos=0
                ):
                    pass  # discard audio
                self._logger.info("[TTS] GPU kernels pre-warmed")
            except Exception as _warm_err:
                self._logger.warning(f"[TTS] Pre-warm failed (will pay cold-start on first use): {_warm_err}")
```

#### Fix C — Instrument Every Stage

**File**: `backend/iris_gateway.py`

In the `chunk_callback` function (around line 2148), add timing variables at the top:

```python
                # Timing instrumentation
                _t_first_token = None
                _t_first_sentence = None
```

When the first chunk arrives (around line 2150):
```python
                    if _t_first_token is None:
                        _t_first_token = time.monotonic()
```

When the first sentence is pushed to the queue (around line 2172):
```python
                    if _t_first_sentence is None:
                        _t_first_sentence = time.monotonic()
```

In the producer thread, when TTS synthesis starts (around line 2632):
```python
                            _t_tts_start = time.monotonic()
```

When the first audio chunk is pushed (around line 2653):
```python
                                _t_first_audio = time.monotonic()
```

At the end of the producer thread, log the timing:
```python
                    _t_end = time.monotonic()
                    _root_log.info(
                        "[timing] first_token=%.2fs first_sentence=%.2fs "
                        "tts_start=%.2fs first_audio=%.2fs total=%.2fs "
                        "gap_sentence_tts=%.2fs gap_tts_audio=%.2fs",
                        _t_first_token - _t_start if _t_first_token else -1,
                        _t_first_sentence - _t_start if _t_first_sentence else -1,
                        _t_tts_start - _t_start if _t_tts_start else -1,
                        _t_first_audio - _t_start if _t_first_audio else -1,
                        _t_end - _t_start,
                        (_t_tts_start - _t_first_sentence) if _t_tts_start and _t_first_sentence else -1,
                        (_t_first_audio - _t_tts_start) if _t_first_audio and _t_tts_start else -1,
                    )
```

**Note**: `_t_start` should be set at the beginning of the voice input handler (when STT completes). Add ` _t_start = time.monotonic()` near the top of the handler function.

#### Fix D — STTPROC Overlap (Already covered in Issue 3 Part D)

The STTPROC stop is moved from line 2726 to inside the producer thread (first audio chunk). This eliminates the dead air gap.

#### Fix E — Filler Phrases Bridge the Gap (Already covered in Issue 3 Part C)

The pre-synthesized filler plays immediately on STT completion, covering the entire wait.

#### Fix F — Broadcast "speaking" State Earlier

**File**: `backend/iris_gateway.py`

Currently, the "speaking" state is broadcast inside the producer thread after the first audio chunk (line 2653-2678). This is actually correct — we want the frontend to show "speaking" when audio is actually playing, not when TTS is still generating.

**No change needed** — the filler phrase + STTPROC provide auditory feedback during the generation gap. The "speaking" state correctly fires when audio starts.

---

### Issue 6: Barge-In Pipeline Safety

#### Concern

If barge-in fires mid-TTS-generation, the producer thread is still running and might push stale chunks.

#### Fix — `backend/iris_gateway.py`

Find the producer thread's `synthesize_stream` loop (around line 2603):

```python
                                chunk = " ".join(_pending)
                                for audio_chunk in tts.synthesize_stream(chunk):
                                    if audio_chunk is not None and len(audio_chunk) > 0:
                                        if _native:
                                            gained = np.clip(
                                                audio_chunk * 2.5, -0.99, 0.99
                                            )
                                            try:
                                                engine.pipeline._native_player.push_chunk(
                                                    gained
                                                )
```

Add `interrupted` checks at three points:

**Check 1 — Before each synthesize_stream call** (around line 2602):

```python
                                if interrupted.is_set() or engine.is_speech_interrupted():
                                    _root_log.info("[tts] barge-in interrupted before synthesis")
                                    break
                                chunk = " ".join(_pending)
```

**Check 2 — Inside the audio chunk loop** (after line 2603):

```python
                                for audio_chunk in tts.synthesize_stream(chunk):
                                    if interrupted.is_set() or engine.is_speech_interrupted():
                                        _root_log.info("[tts] barge-in interrupted mid-generation")
                                        break
                                    if audio_chunk is not None and len(audio_chunk) > 0:
```

**Check 3 — After each sentence from the queue** (around line 2566, the `item = input_source.get()` line):

The `input_source.get()` blocks. Add a timeout so it can check for interruption:

```python
                        try:
                            item = input_source.get(timeout=0.1)
                        except Exception:
                            if interrupted.is_set() or engine.is_speech_interrupted():
                                _root_log.info("[tts] barge-in interrupted while waiting for sentence")
                                break
                            continue
```

**Check 4 — Drain audio queue on barge-in**

After the producer thread exits (in the `finally` block or after the thread join), drain the audio queue:

```python
                    # Drain stale audio chunks if barge-in interrupted
                    if interrupted.is_set() and not _native:
                        while not audio_queue.empty():
                            try:
                                audio_queue.get_nowait()
                            except Exception:
                                break
                        _root_log.info("[tts] audio queue drained after barge-in")
```

---

## 4. Phase 2: ConversationKernel/TaskKernel Separation

### Architecture

```
Agent LLM Output
    ├── ConversationKernel (speech channel)
    │   ├── Emits utterance events → TTS subscribes
    │   ├── Caducean-governed turn-taking (EXPAND = speak, COMPRESS = listen)
    │   ├── Filler phrase selection during processing
    │   └── Status phrases during long tasks
    │
    └── TaskKernel (action/reasoning channel)
        ├── Emits tool-call events → UI subscribes
        ├── Planning steps → UI shows in dashboard
        ├── Tool execution → UI shows progress
        └── No audio output (never reaches TTS)
```

### Current State

The `ConversationKernel` already exists (`backend/agent/conversation_kernel.py`) as a thin Caducean wrapper. It needs to be extended to emit utterance events and filter speech from task content. A new `TaskKernel` needs to be created. A lightweight event bus needs to be built.

### Phase 2 Implementation Files

- `backend/agent/event_bus.py` — new event bus (IRISStreamEvent + EventBus class)
- `backend/agent/conversation_kernel.py` — extend with utterance emission
- `backend/agent/task_kernel.py` — new TaskKernel
- `backend/iris_gateway.py` — route LLM output through kernel separation
- `backend/agent/tts.py` — subscribe to utterance events only

### Caducean Integration

The Caducean Engine governs the phase:
- **EXPAND (u → +1)**: ConversationKernel active — agent speaks, reports results
- **COMPRESS (u → -1)**: TaskKernel active — agent works, executes tools
- **Phase transition**: When TaskKernel completes a step, ConversationKernel emits a status phrase

This maps to the existing `on_voice_state` callback in `conversation_kernel.py`:
- `RECORDING → COMPRESS` (user speaking, agent listens)
- `IDLE → EXPAND` (user finished, agent responds)
- `PROCESSING → COMPRESS` (agent thinking/working, TaskKernel active)
- `SUCCESS → EXPAND` (TTS playing, ConversationKernel active)

### Phase 2 is deferred until Phase 1 is verified working.

---

## 5. C++ Performance Assessment

### Where C++ Would NOT Help

| Bottleneck | Cause | C++ helps? |
|-----------|-------|------------|
| TTS generation latency (4.6s) | GPU inference (Pocket-TTS model) | **No** — already on CUDA |
| STT processing | GPU inference (Parakeet model) | **No** — same reason |
| Orb animation lag | 60 React state updates/sec | **No** — frontend/TypeScript issue |
| Barge-in not firing | Threshold too high | **No** — tuning issue |
| TTS delay after text | Sequential pipeline | **No** — architecture issue |

Python's heavy lifting (numpy FFT, PyTorch inference) already runs C/C++ under the hood. The GIL is released during GPU calls.

### Where C++ COULD Help in the Future

1. **Real-time audio DSP** — custom echo cancellation, beamforming, noise reduction
2. **ASIO audio backend** — for sub-10ms audio I/O on Windows
3. **Multi-band spectral analysis** — if cadence detection becomes more complex
4. **Tauri/Rust bridge** — already in Rust, could be optimized for lower-latency audio routing

### Recommendation

Clean up the Python code architecture first (Phase 1 + Phase 2). If sub-50ms audio round-trip latency is needed later, consider a Rust/C++ audio bridge via Tauri.

---

## 6. Implementation Order

### Phase 1 (immediate)

| Step | Task | Files | Depends On |
|------|------|-------|------------|
| 0 | Pocket-TTS streaming test | `backend/tests/test_tts_streaming_timing.py` (new) | Nothing |
| 1 | Barge-in tuning | `backend/audio/engine.py` | Nothing |
| 2 | VAD silence | `backend/audio/voice_command.py` | Nothing |
| 3 | STTPROC amplification | `backend/iris_gateway.py` | Nothing |
| 4 | Filler pre-synthesis | `backend/agent/tts.py` | TTS model loaded (step 3 of startup) |
| 5 | Filler playback alongside STTPROC | `backend/iris_gateway.py` | Step 4 |
| 6 | STTPROC stop on first TTS chunk | `backend/iris_gateway.py` | Step 5 |
| 7 | Orb cadence ref-based | `hooks/useClientMicCadence.ts`, `hooks/useCadenceDetection.ts`, `components/iris/orb/OrbCanvas.tsx`, `components/iris/XurOrb.tsx` | Nothing |
| 8 | TTS latency: shorter first sentence | `backend/iris_gateway.py` | Step 0 result |
| 9 | TTS latency: pre-warm | `backend/agent/tts.py` | Step 4 |
| 10 | TTS latency: instrumentation | `backend/iris_gateway.py` | Nothing |
| 11 | Barge-in pipeline safety | `backend/iris_gateway.py` | Step 1 |
| 12 | Update barge-in tests | `backend/tests/test_barge_in.py` | Step 1 |
| 13 | Run all tests | — | Steps 1-12 |
| 14 | Restart backend + frontend | — | Step 13 |
| 15 | End-to-end verification | — | Step 14 |

### Phase 2 (follow-up)

| Step | Task | Files |
|------|------|-------|
| 1 | Design event bus | `backend/agent/event_bus.py` |
| 2 | Extend ConversationKernel | `backend/agent/conversation_kernel.py` |
| 3 | Create TaskKernel | `backend/agent/task_kernel.py` |
| 4 | Route LLM output through kernels | `backend/iris_gateway.py` |
| 5 | Caducean phase-governed turn-taking | `backend/agent/conversation_kernel.py` |
| 6 | Status phrases during long tasks | `backend/agent/conversation_kernel.py` |

---

## 7. Verification Checklist

### Phase 1

- [ ] Pocket-TTS streaming behavior verified (streaming vs batch)
- [ ] Barge-in fires within 0.8s of speaking over TTS
- [ ] Barge-in debug logging shows RMS levels in logs
- [ ] VAD doesn't trigger on 0.8s natural pauses
- [ ] STTPROC is audible during processing (3x gain)
- [ ] Filler phrase plays immediately on STT completion
- [ ] STTPROC + filler play together, not instead of each other
- [ ] No dead air between STTPROC stop and TTS start
- [ ] Orb breathing is smooth at 60fps, no stutter
- [ ] React re-renders reduced from 70/sec to 10/sec
- [ ] TTS first audio plays within 1-2s of text appearing in chat
- [ ] Barge-in cleanly interrupts producer thread (no stale chunks)
- [ ] Timing instrumentation reveals actual bottleneck
- [ ] All existing tests pass (17/17 barge-in + 6 parakeet)
- [ ] TypeScript compiles (`npx tsc --noEmit`)
- [ ] Frontend builds without errors

### Verification Commands

```bash
# Barge-in + parakeet tests
python -m pytest backend/tests/test_barge_in.py::TestBargeInDetection backend/tests/test_barge_in.py::TestConstants backend/tests/test_barge_in.py::TestMultipleBargeIns backend/tests/test_voice_command_parakeet.py -v

# TypeScript check
npx tsc --noEmit

# Pocket-TTS streaming test
python -m backend.tests.test_tts_streaming_timing

# Restart backend
# (kill existing uvicorn process first)
Start-Process -FilePath "cmd" -ArgumentList "/c", "cd /d C:\dev\IRISVOICE && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8090 > backend\logs\backend_restart.log 2>&1"

# Restart frontend
Start-Process -FilePath "cmd" -ArgumentList "/c", "cd /d C:\dev\IRISVOICE && npx next dev --port 3000 > logs\frontend_restart.log 2>&1"
```

### Phase 2

- [ ] Event bus created and tested
- [ ] ConversationKernel emits utterance events
- [ ] TaskKernel emits tool-call and planning events
- [ ] TTS only receives utterance events (no tool calls)
- [ ] Caducean phase governs when to speak vs when to work
- [ ] Status phrases during long tasks
- [ ] Turn IDs link utterances to task steps

---

## 8. Appendix: Exact Line References

### `backend/audio/engine.py`

| Line | Content |
|------|---------|
| ~75 | `_barge_in_frame_count: int = 0` |
| ~76 | `_on_barge_in_detected: Optional[...] = None` |
| ~77 | `_barge_in_arm_time: float = 0.0` |
| ~330 | `BARGE_IN_ENERGY_THRESHOLD: float = 0.06` |
| ~331 | `BARGE_IN_CONSECUTIVE_FRAMES: int = 25` |
| ~332 | `BARGE_IN_ARM_DELAY: float = 0.8` |
| ~308 | `def set_tts_active(self, active: bool)` |
| ~355 | `def _on_barge_in_energy(self, rms: float)` |

### `backend/audio/voice_command.py`

| Line | Content |
|------|---------|
| 179 | `VAD_ENERGY_THRESHOLD = 0.006` |
| 181 | `VAD_MIN_SPEECH_SEC = 0.15` |
| 183 | `VAD_SILENCE_SEC = 0.5` |
| 185 | `VAD_MAX_DURATION_SEC = 30.0` |

### `backend/iris_gateway.py`

| Line | Content |
|------|---------|
| 1670 | `_engine.set_barge_in_detected_callback(...)` |
| 2085 | `_loop_sttproc` function |
| 2125 | `sd.play(data, sr, device=..., blocking=True)` |
| 2137 | `_sttproc_thread.start()` |
| 2148 | `chunk_callback` function |
| 2150 | chat_chunk WebSocket send |
| 2165 | `sentence_buf` accumulation |
| 2170 | `_re.search(r"([.!?])\s+", text)` |
| 2172 | `sentence_queue.put(...)` |
| 2236 | `self._speak_response(...)` |
| 2388 | `_first_chunk_threshold = 1` |
| 2465 | `def _producer(...)` |
| 2566 | `item = input_source.get()` |
| 2602 | `chunk = " ".join(_pending)` |
| 2603 | `for audio_chunk in tts.synthesize_stream(chunk):` |
| 2610 | `engine.pipeline._native_player.push_chunk(gained)` |
| 2618 | `audio_queue.put(audio_chunk)` |
| 2632 | `for audio_chunk in tts.synthesize_stream(chunk):` (second occurrence) |
| 2653 | `if is_first_chunk:` |
| 2663 | `_speaking_broadcasted = True` |
| 2670 | `"type": "listening_state", "payload": {"state": "speaking"}` |
| 2726 | `if _sttproc_stop is not None: _sttproc_stop.set()` |
| 2728 | `engine.set_tts_active(True)` |
| 2731 | `_prod_thread = threading.Thread(...)` |

### `backend/agent/tts.py`

| Line | Content |
|------|---------|
| 421 | `def _load_pocket_tts(self)` |
| 440 | `self._pocket_tts_model = TTSModel.load_model(...)` |
| 543 | `def _stream_pocket(self, ...)` |
| 589 | `if np.max(np.abs(audio)) < 0.01: continue` (silent lead-in skip) |

### `hooks/useClientMicCadence.ts`

| Line | Content |
|------|---------|
| ~10 | `const [cadence, setCadence] = useState(0)` |
| ~140 | rAF callback starts |
| ~150 | `setCadence(val)` |
| ~160 | `return cadence` |

### `hooks/useCadenceDetection.ts`

| Line | Content |
|------|---------|
| ~30 | `const clientCadence = useClientMicCadence()` |
| ~60-75 | Priority chain + return block |

### `components/iris/orb/OrbCanvas.tsx`

| Line | Content |
|------|---------|
| ~20 | `interface OrbCanvasProps` |
| ~30 | `export function OrbCanvas(...)` |
| ~90 | `breathLevelRef = useRef<number>(0)` |
| ~91 | `isBreathingRef = useRef<boolean>(false)` |
| ~92-93 | `breathLevelRef.current = breathLevel` / `isBreathingRef.current = isBreathing` |
| ~300 | `function draw()` (rAF callback) |
| ~305 | `const bl = breathLevelRef.current` |
| ~306 | `const br = isBreathingRef.current` |
| ~339 | `if (br && bl > 0)` (breath application) |
| ~353 | `if (br && bl > 0)` (breath halo) |
| ~365 | `drawShell(... br, bl)` |
| ~369 | `drawCenterCore(bl, ...)` |
| ~379 | `rafRef.current = requestAnimationFrame(draw)` |
| ~384 | `}, [glowColor])` (useEffect dependency) |
| ~396 | End of component |

### `components/iris/XurOrb.tsx`

| Line | Content |
|------|---------|
| ~75 | `const cadence = useCadenceDetection()` |
| ~439 | `<OrbCanvas glowColor={...} breathMode={...} ... />` |

### `backend/tests/test_barge_in.py`

| Line | Content |
|------|---------|
| ~30 | Fixture: `eng.BARGE_IN_ENERGY_THRESHOLD = 0.06` |
| ~31 | `eng.BARGE_IN_CONSECUTIVE_FRAMES = 25` |
| ~32 | `eng.BARGE_IN_ARM_DELAY = 0.8` |

**Multiple occurrences** of these constants appear in:
- TestBargeInDetection fixture (~line 30)
- TestMultipleBargeIns.test_multiple_barge_in_cycles (~line 200)
- TestPipelineEnergyCallback (~line 250)
- test_gate_reopens_on_barge_in (~line 280)
- test_engine_registers_callback_on_start (~line 310)

---

*For Caducean Engine technical overview: `docs/CADUCEAN_TECHNICAL_OVERVIEW.md`*
*For MCM agent protocol: `AGENTS.md`*
