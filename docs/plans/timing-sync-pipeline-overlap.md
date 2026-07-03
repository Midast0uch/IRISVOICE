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
   - [Issue 1: Barge-In Doesn't Fire](#issue-1-barge-in-doesnt-fire)
   - [Issue 2: VAD Too Sensitive](#issue-2-vad-too-sensitive)
   - [Issue 3: STTPROC Inaudible + Filler Phrases](#issue-3-sttproc-inaudible--filler-phrases)
   - [Issue 4: Orb Cadence Animation Lag](#issue-4-orb-cadence-animation-lag)
   - [Issue 5: STT→TTS Latency Gap](#issue-5-stttts-latency-gap-5-8-seconds)
   - [Issue 6: Barge-In Pipeline Safety](#issue-6-barge-in-pipeline-safety)
4. [Phase 2: ConversationKernel/TaskKernel Separation](#4-phase-2-conversationkerneltaskkernel-separation)
5. [C++ Performance Assessment](#5-c-performance-assessment)
6. [Implementation Order](#6-implementation-order)
7. [Verification Checklist](#7-verification-checklist)

---

## 1. Problem Statement

The conversational STT/TTS pipeline works — the user can talk back and forth with the agent. However, six issues degrade the real-time experience:

1. **Barge-in doesn't fire** — speaking during TTS doesn't interrupt
2. **VAD cuts off too early** — natural pauses trigger STT processing
3. **STTPROC.wav is inaudible** — no processing sound between STT and TTS
4. **Orb cadence animation lags** — breathing visuals stutter during speech
5. **TTS delay after text** — 5-8 seconds between text appearing in chat and TTS audio playing
6. **Barge-in pipeline safety** — must not break the audio pipeline if it fires mid-generation

The root causes are: miscalibrated tuning values, a too-quiet WAV file, 60fps React state updates flooding the render cycle, sequential pipeline stages that should overlap, and a missing speech/task content separation.

---

## 2. Current Pipeline Architecture

### STT → LLM → TTS Flow

```
User speaks
  → Mic capture (PortAudio, 16kHz, 512-frame chunks)
  → VAD loop (voice_command.py)
    → Energy threshold check → silence detection (0.5s) → end of speech
  → STT transcription (Parakeet TDT on GPU, or Whisper fallback)
  → LLM generation (streamed via chunk_callback)
    → chunk_callback:
      1. Sends text to frontend via chat_chunk WebSocket message (text appears in chat)
      2. Accumulates text in sentence_buf
      3. Waits for sentence boundary ([.!?]\s+) → pushes to sentence_queue
  → TTS thread (_wrap_tts_streaming → _speak_response)
    → Producer thread consumes sentence_queue
    → Splits sentence into word chunks (first chunk = 1 word)
    → Calls tts.synthesize_stream(chunk)
      → _stream_pocket → model.generate_audio_stream(voice_state, text)
      → Skips first ~3 chunks (silent lead-in, < 0.01 amplitude)
      → Yields audible chunks
    → "speaking" state broadcast AFTER first audio chunk
    → Audio pushed to native player or audio_queue
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

### Backend Log Evidence

TTS generation timing (from `backend_final.log`):
```
14:24:00 [TTSManager] synthesize_stream ENTRY: 152 chars
14:24:05 [TTSManager] stream end: 83 chunks in 4.63s
```

- 152 chars → 4.63s generation → 6.6s audio (1.42x real-time)
- 26 chars → 1.19s generation → 1.4s audio
- 196 chars → 6.72s generation → 7.8s audio

STTPROC timing:
```
[STTPROC] Loop started
... 2.3s later ...
[STTPROC] Loop ended (1 iterations)
```

STTPROC WAV file analysis:
```
Sample rate: 44100 Hz, stereo
Duration: 2.09s
Max amplitude: 0.3506
RMS: 0.0428
DBFS: -27.4 dB  (extremely quiet — normal speech is -15 to -20 dBFS)
```

---

## 3. Phase 1: Immediate Fixes

### Step 0: Pocket-TTS Streaming Verification

**Before designing the latency fix**, run a timing test to determine if `generate_audio_stream()` is truly streaming (yields chunks during generation) or batch-generates then chunks.

```python
# Test script (read-only, no file changes)
from pocket_tts import TTSModel
import time

model = TTSModel.load_model(language="english", eos_threshold=-1.0)
voice_state = model.get_state_for_audio_prompt("data/TOMV2.wav")

text = "Hello, this is a test sentence to measure timing."
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
# If first_chunk << total → streaming. If first_chunk ≈ total → batch.
```

**Decision branch**:
- **If streaming** (first chunk < 1s): Latency fix focuses on shorter first sentences + pre-warm. Chunks arrive during generation, so the user hears audio quickly.
- **If batch** (first chunk ≈ total): Latency fix must also split text into smaller chunks (20-30 chars) to reduce per-batch generation time. Each batch generates in ~1s instead of ~5s.

---

### Issue 1: Barge-In Doesn't Fire

#### Root Cause

Three compounding issues:

1. **Threshold too high (0.06)**: Normal speech through a desktop mic while TTS is playing often produces RMS of 0.03–0.05. The 0.06 threshold filters out legitimate speech.
2. **Total detection window too long (1.6s)**: Arm delay (0.8s) + 25 frames (0.8s) = 1.6 seconds. A user interrupting IRIS typically speaks for less than 1 second before expecting a response.
3. **No barge-in log messages appear at all**, suggesting the RMS never reaches 0.06 through the user's mic, or the arm delay window is swallowing everything.

#### Evidence

- Barge-in callback IS wired (`iris_gateway.py:1670` registers `_on_barge_in_detected`)
- Pipeline IS computing RMS during TTS (`pipeline.py:217-220` calls `_on_barge_in_energy`)
- The arm delay check (`time.monotonic() - _barge_in_arm_time < 0.8`) suppresses all energy callbacks for the first 800ms
- Zero barge-in messages in backend logs during user testing

#### Fix

| Parameter | Old | New | Reasoning |
|-----------|-----|-----|-----------|
| `BARGE_IN_ENERGY_THRESHOLD` | 0.06 | **0.04** | Catches normal speech (0.04-0.5 RMS) while filtering ambient noise (0.005-0.02). 0.04 is the midpoint between the old too-low 0.02 and the too-high 0.06. |
| `BARGE_IN_CONSECUTIVE_FRAMES` | 25 | **15** | ~500ms at 31Hz. Filters coughs/noises but allows natural interruption. A user saying "wait" or "stop" takes ~500ms. |
| `BARGE_IN_ARM_DELAY` | 0.8s | **0.3s** | 300ms skips the TTS onset burst (first audio chunk). Doesn't block legitimate barge-in for 97% of TTS duration. |

**Total detection time after fix**: 0.3s + 0.5s = **0.8 seconds**.

A normal interruption phrase ("wait", "stop", "actually...") takes about 0.5-1.0s to speak. With the new settings, barge-in fires at 0.8s — right in the middle of a typical interruption.

#### Debug Logging

Add `logger.debug` inside `_on_barge_in_energy` to print RMS, frame count, and arm delay status on every call:

```python
logger.debug("[barge_in] rms=%.4f frames=%d/%d armed=%s",
             rms, self._barge_in_frame_count,
             self.BARGE_IN_CONSECUTIVE_FRAMES,
             time.monotonic() - self._barge_in_arm_time >= self.BARGE_IN_ARM_DELAY)
```

This will appear in logs as:
```
[barge_in] rms=0.041 frames=3/15 armed=True
```

#### Files Changed

- `backend/audio/engine.py` — constants + debug logging

---

### Issue 2: VAD Too Sensitive

#### Root Cause

`VAD_SILENCE_SEC = 0.5` at `voice_command.py:183` — 500ms of silence triggers end-of-speech. Natural conversational pauses between clauses last 0.4-0.8 seconds. The VAD interprets these as end-of-utterance and starts processing.

#### Evidence

User reports: "when I stop speaking it begins to process my STT" — natural conversational pauses trigger STT processing.

#### Fix

| Parameter | Old | New | Reasoning |
|-----------|-----|-----|-----------|
| `VAD_SILENCE_SEC` | 0.5 | **0.8** | 800ms allows natural sentence-level pauses. Standard conversational VAD systems use 0.5-1.0s; 0.8 is the sweet spot for conversational mode. Still short enough that the user doesn't experience "dead air" delay after finishing their thought. |

#### Files Changed

- `backend/audio/voice_command.py` line 183

---

### Issue 3: STTPROC Inaudible + Filler Phrases

#### Root Cause — STTPROC

The STTPROC.wav file is **extremely quiet**: -27.4 dBFS. For reference:
- Normal speech: -15 to -20 dBFS
- TTS output: typically -10 to -15 dBFS
- Music: -10 to -6 dBFS

The STTPROC sound is 12-17 dB quieter than the TTS that follows it. At normal speaker volume (calibrated for TTS), the STTPROC is virtually inaudible.

The playback code does `sd.play(data, sr, device=dev, blocking=True)` with no gain applied.

#### Fix Part A — STTPROC Amplification

Apply a 3x gain factor to the audio data before playback:

```python
# Before sd.play:
play_data = data * 3.0
play_data = np.clip(play_data, -1.0, 1.0)  # prevent clipping
sd.play(play_data, sr, device=dev, blocking=True)
```

**3x gain = +9.5 dB**, bringing the STTPROC from -27.4 dBFS to ~-17.9 dBFS — within the range of normal speech. The `np.clip` prevents digital clipping from the gain boost.

#### Fix Part B — Filler Phrases (play alongside STTPROC)

Pre-synthesize a bank of conversational filler phrases as cached .wav files:

| Phrase | When to play |
|--------|-------------|
| "Mm, let me think about that." | General acknowledgment |
| "Got it, one second." | Quick acknowledgment |
| "Right, let me check." | Task-oriented |
| "Okay, thinking..." | Longer processing |

#### Pre-synthesis

During backend startup, after the TTS model loads, generate each phrase once and cache as `data/fillers/<phrase_hash>.wav`. Zero-latency playback during conversation.

```python
# During startup, after model load:
FILLER_PHRASES = [
    "Mm, let me think about that.",
    "Got it, one second.",
    "Right, let me check.",
    "Okay, thinking...",
]
for phrase in FILLER_PHRASES:
    cache_path = f"data/fillers/{hashlib.md5(phrase.encode()).hexdigest()}.wav"
    if not os.path.exists(cache_path):
        chunks = []
        for chunk in model.generate_audio_stream(voice_state, phrase, frames_after_eos=0):
            chunks.append(chunk.cpu().numpy().astype(np.float32))
        # Save as WAV...
```

#### Playback Flow

1. STT completes → LLM starts generating
2. **Immediately**: Play a filler phrase (from cache, zero latency) AND start STTPROC loop
3. Filler plays once (~1-2s), STTPROC loops underneath
4. When first TTS audio chunk arrives → stop STTPROC, stop any remaining filler
5. TTS plays normally

**STTPROC and filler play together** — the STTPROC provides ambient processing sound while the filler gives a conversational acknowledgment. The user hears both simultaneously.

#### Selection Logic

Random selection from phrase bank, avoiding repeating the same phrase twice in a row. Could be Caducean-governed in Phase 2 (expansion phase = longer filler, compression phase = shorter filler).

#### Files Changed

- `backend/iris_gateway.py` — STTPROC section (gain factor), filler playback, STTPROC stop timing
- `backend/agent/tts.py` — pre-synthesis during startup

---

### Issue 4: Orb Cadence Animation Lag

#### Root Cause

`useClientMicCadence.ts:150` calls `setCadence(val)` inside `requestAnimationFrame` — **60 React state updates per second**. This causes:

1. XurOrb to re-render 60 times/sec
2. Framer-motion to recalculate spring animations 60 times/sec
3. OrbCanvas to re-render 60 times/sec (even though it only needs ref updates)
4. Combined with 10Hz backend cadence = **70 re-renders/sec total**

The React reconciliation overhead (diffing, prop comparison, context propagation) consumes main-thread time that should be available for the canvas rAF loop, causing visual stutter.

#### Key Insight

**The React re-renders are pure overhead.** OrbCanvas's rAF loop already reads from refs (`breathLevelRef.current`), which are updated on every render (lines 95-96). The canvas rendering is independent of React's render cycle. If we update the refs WITHOUT triggering a re-render, the canvas still gets fresh values at 60fps.

#### Current Architecture

```
useClientMicCadence (60fps rAF)
  → setCadence(val) — STATE UPDATE (triggers re-render)
  → XurOrb re-renders (60 times/sec)
  → OrbCanvas re-renders (60 times/sec)
  → breathLevelRef.current = breathLevel  (line 95)
  → rAF loop reads breathLevelRef at 60fps (line 96)
```

#### Fix — Ref-Based Cadence (zero unnecessary re-renders)

**Step 1**: `useClientMicCadence` updates a ref instead of state:

```typescript
// Before (60 re-renders/sec):
setCadence(val)

// After (0 re-renders):
cadenceRef.current = val
```

**Step 2**: Pass `cadenceRef` to OrbCanvas. The rAF loop reads it at 60fps:

```typescript
// Inside OrbCanvas rAF loop:
const clientCadence = cadenceRef?.current ?? 0
const effectiveBreath = isBreathing ? Math.max(breathLevel, clientCadence) : breathLevel
```

**Step 3**: Backend cadence (10Hz) still triggers normal state updates → re-renders → ref updated. These 10 re-renders/sec are not a bottleneck.

**Step 4**: Priority logic in rAF loop:
- If backend sent cadence in last 200ms → use backend value (from prop/ref)
- Else → use client mic ref value

**Step 5**: `React.memo` on OrbCanvas with custom comparator:

```typescript
// Only re-render if visual props changed, not breath data
// (breath data is read from refs in rAF loop)
export const OrbCanvas = React.memo(function OrbCanvas(props) {
  // ...
}, (prev, next) => {
  return prev.glowColor === next.glowColor &&
         prev.animationMode === next.animationMode &&
         prev.animActive === next.animActive
})
```

#### Result

| Metric | Before | After |
|--------|--------|-------|
| Canvas FPS | 60 (stuttering) | 60 (smooth) |
| React re-renders/sec | 70 | 10 |
| Visual responsiveness | Laggy | **Identical or better** |
| Breath data freshness | 60fps (via state) | 60fps (via ref) |

**The orb will be MORE responsive** because:
- Canvas rAF loop runs at the same 60fps, reading fresh values every frame
- Main thread has 60 fewer re-renders/sec to process → more CPU for canvas drawing
- No visual difference — the breathing animation is a slow, continuous motion that doesn't benefit from 60fps data updates vs. 60fps canvas rendering reading a ref

#### Files Changed

- `hooks/useClientMicCadence.ts` — ref-based cadence updates instead of state
- `hooks/useCadenceDetection.ts` — pass ref to OrbCanvas
- `components/iris/orb/OrbCanvas.tsx` — read cadence ref in rAF loop, add React.memo
- `components/iris/XurOrb.tsx` — pass cadence ref prop to OrbCanvas

---

### Issue 5: STT→TTS Latency Gap (5-8 seconds)

#### Root Cause

The TTS pipeline has multiple sequential delays:

1. **Sentence boundary wait**: `chunk_callback` accumulates text in `sentence_buf` and only pushes to `sentence_queue` when a sentence boundary is found (`[.!?]\s+`). If the first sentence is 152 chars, text appears progressively in chat but TTS waits for the full sentence.

2. **TTS generation time**: 4.63s for 152 chars (from log). If Pocket-TTS is batch-mode (generates full audio before yielding chunks), the first audio chunk doesn't arrive until full generation completes.

3. **No pre-warm**: First `generate_audio_stream` call may have GPU initialization overhead (CUDA kernel compilation, memory allocation).

4. **STTPROC stops before TTS audio is ready**: `_sttproc_stop.set()` is called at line 2726, BEFORE the producer thread starts. This creates a dead air gap between STTPROC stopping and the first TTS audio chunk playing.

5. **"speaking" state broadcast delayed**: The "speaking" state is only broadcast AFTER the first audio chunk is received (line 2653), not when TTS starts generating. The frontend doesn't know TTS is starting until audio is already playing.

#### Backend Log Evidence

```
14:24:00 [TTSManager] synthesize_stream ENTRY: 152 chars
14:24:05 [TTSManager] stream end: 83 chunks in 4.63s
```

The 4.63s gap between ENTRY and stream end is the TTS generation time. If batch-mode, the first audio chunk arrives at ~4.63s. If streaming, it arrives much earlier.

#### Fix — Multi-pronged Latency Reduction

**A. Shorter first-sentence boundary**

Currently waits for `[.!?]\s+`. Add comma and semicolon as secondary boundaries, plus a character-count flush:

```python
# Current: only [.!?] followed by whitespace
m := _re.search(r"([.!?])\s+", text)

# New: also flush on comma+space, semicolon, or after 40 chars
m := _re.search(r"([.!?;])\s+|,\s+|(?<=.{40})\s+", text)
```

This means the first TTS generation starts after ~40 chars instead of waiting for a full sentence. A 40-char chunk generates in ~1.5s instead of 4.6s.

**B. TTS pre-warm**

During backend startup, after the TTS model loads, run a dummy generation:

```python
# During startup, after model load:
dummy_text = "System ready."
for _ in model.generate_audio_stream(voice_state, dummy_text, frames_after_eos=0):
    pass  # discard audio, just warm up GPU kernels
```

This ensures the first real generation doesn't pay GPU initialization cost (CUDA kernel compilation, memory allocation, weight transfer).

**C. Instrument every stage**

Add timestamp logging at each pipeline stage to identify the actual bottleneck:

```python
logger.info("[timing] stt_end=%.3f first_llm_token=%.3f first_sentence=%.3f "
            "tts_start=%.3f first_audio_byte=%.3f playback_start=%.3f "
            "gap_stt_tts=%.3f gap_tts_play=%.3f",
            stt_end, first_token, first_sentence,
            tts_start, first_audio, playback_start,
            tts_start - stt_end, playback_start - tts_start)
```

This reveals whether the bottleneck is:
- LLM time-to-first-token (LLM latency)
- Sentence boundary wait (chunk_callback accumulation)
- TTS cold-start (GPU initialization)
- TTS generation time (model inference)
- GPU context switch overhead (Parakeet → Pocket-TTS on same GPU)

**D. Overlap STTPROC stop with TTS first chunk**

Currently STTPROC stops at line 2726 (before producer starts). Change to: STTPROC stops when the first TTS audio chunk is pushed to the player, not before.

```python
# Before: stop STTPROC immediately (dead air gap)
if _sttproc_stop is not None:
    _sttproc_stop.set()

# After: pass _sttproc_stop to producer, stop on first audio chunk
# Inside producer loop, after first chunk pushed to player:
if _sttproc_stop is not None and not _sttproc_stop.is_set():
    _sttproc_stop.set()
```

This eliminates the dead air gap between STTPROC stopping and TTS audio starting. The user hears continuous sound: STTPREC → TTS (seamless transition).

**E. Filler phrases bridge the gap** (from Issue 3)

The pre-synthesized filler phrase plays immediately when STT completes, covering the entire wait until TTS audio arrives. The user hears:
1. Filler phrase (~1-2s) + STTPROC loop underneath
2. TTS audio starts → STTPROC stops, filler already finished

**F. Broadcast "speaking" state earlier**

Currently broadcast after first audio chunk. Change to broadcast when TTS generation starts (before first chunk arrives):

```python
# Before: broadcast after first audio chunk
if not _speaking_broadcasted:
    _speaking_broadcasted = True
    # broadcast "speaking" state

# After: broadcast when producer starts generating
# (move outside the audio chunk loop)
```

This lets the frontend update the orb to "speaking" state before audio actually plays, improving perceived responsiveness.

#### Files Changed

- `backend/iris_gateway.py` — chunk_callback (shorter boundary), _speak_response (STTPROC overlap, speaking state timing), startup (pre-warm)
- `backend/agent/tts.py` — pre-warm dummy generation

---

### Issue 6: Barge-In Pipeline Safety

#### Concern

If barge-in fires mid-TTS-generation, the producer thread is still running. It might push audio chunks to the queue after the player has stopped. This could cause:
- Audio queue overflow (chunks pile up)
- Player restart issues (stale chunks in queue)
- Thread leaks (producer thread keeps running)

#### Fix

The producer thread checks `interrupted.is_set()` at three points:

```python
# Inside producer thread:
for audio_chunk in tts.synthesize_stream(chunk):
    if interrupted.is_set():
        logger.info("[tts] barge-in interrupted producer mid-generation")
        break
    # ... push chunk to player
```

1. Before each `synthesize_stream()` call
2. Before each audio chunk push to player/queue
3. After each sentence from the queue

#### Barge-In Clean Shutdown Sequence

On barge-in:
1. `_barge_in_stop` event set → cadence threads die
2. Producer checks `interrupted` → exits cleanly (no stale chunks)
3. Audio queue drained (if using fallback path)
4. `engine.set_tts_active(False)` → half-duplex gate reopens
5. `interrupted.clear()` → ready for next turn
6. New recording starts → STT processes → new response

This ensures barge-in doesn't break the audio pipeline. The producer thread exits cleanly, no stale audio plays, and the system is ready for the next conversation turn.

#### Files Changed

- `backend/iris_gateway.py` — producer thread interrupted checks

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

The `ConversationKernel` already exists (`backend/agent/conversation_kernel.py`) as a thin Caducean wrapper:
- Observes voice state changes (RECORDING → COMPRESS, IDLE → EXPAND)
- Provides `get_tts_chunk_size()` — scales TTS chunk size by Caducean force_magnitude
- Provides `should_halt_on_violation()` — calls `audio_pipeline.interrupt()` on TOPO_VIOLATION
- Detects barge-in (user speaks while agent speaks → nudge Caducean params)

But it does NOT:
- Separate speech from task/planning content
- Emit distinct event types (ConversationKernel vs TaskKernel)
- Route only conversational text to TTS (filtering out tool calls/planning)
- Provide status phrases during long tasks
- Pre-synthesize filler phrases

### Event Bus (new, lightweight)

A simple in-process event bus:

```python
@dataclass
class IRISStreamEvent:
    event_type: str        # "utterance", "tool_call", "status", "reasoning"
    source: str            # "conversation_kernel" or "task_kernel"
    payload: dict          # text, tool_name, progress, etc.
    turn_id: str           # links utterance to the task step it narrates
    timestamp: float

class EventBus:
    def subscribe(self, event_type: str, handler: Callable): ...
    def emit(self, event: IRISStreamEvent): ...
```

TTS subscribes to `event_type="utterance"` only. The frontend subscribes to all types (for UI display).

### ConversationKernel Extension

Extended to:
1. **Emit utterance events** — when the LLM produces conversational text (not tool calls), emit an `utterance` event with the text + turn_id
2. **Caducean-governed turn-taking** — EXPAND phase → agent speaks (longer turns); COMPRESS phase → agent listens (shorter turns, more filler phrases)
3. **Filler phrase selection** — choose filler based on Caducean phase and task context
4. **Status phrases** — during long TaskKernel operations, emit periodic status utterances ("still checking that...", "almost done")

### TaskKernel (new)

1. **Emits tool-call events** — when the LLM requests a tool call, emit a `tool_call` event
2. **Emits planning events** — reasoning steps, intermediate results
3. **Never reaches TTS** — TTS only subscribes to `utterance` events
4. **Caducean-governed** — COMPRESS phase = execute tasks; EXPAND phase = report results

### Caducean Integration

The Caducean Engine governs the phase:
- **EXPAND (u → +1)**: ConversationKernel active — agent speaks, reports results, fills silence
- **COMPRESS (u → -1)**: TaskKernel active — agent works, executes tools, plans
- **Phase transition**: When TaskKernel completes a step, ConversationKernel emits a status phrase. When the full task completes, ConversationKernel emits the full response.

This maps to the existing `on_voice_state` callback:
- `RECORDING → COMPRESS` (user speaking, agent listens)
- `IDLE → EXPAND` (user finished, agent responds)
- `PROCESSING → COMPRESS` (agent thinking/working, TaskKernel active)
- `SUCCESS → EXPAND` (TTS playing, ConversationKernel active)

### Alignment via Turn IDs

Each utterance event is tagged with the turn_id / plan-step_id it corresponds to. A status phrase like "checking that now" is tied to the TaskKernel step it's narrating, even though it's generated and spoken independently and faster than the actual work finishes.

The agent has states (listening → thinking → executing → responding), and each state has an associated speech behavior (silence, short filler, full response). The ConversationKernel knows which state it's in and speaks accordingly, regardless of how long TaskKernel takes underneath it.

### Phase 2 Implementation Files

- `backend/agent/event_bus.py` — new event bus
- `backend/agent/conversation_kernel.py` — extend with utterance emission
- `backend/agent/task_kernel.py` — new TaskKernel
- `backend/iris_gateway.py` — route LLM output through kernel separation
- `backend/agent/tts.py` — subscribe to utterance events only

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

1. **Real-time audio DSP** — custom echo cancellation, beamforming, noise reduction (if numpy isn't fast enough)
2. **ASIO audio backend** — for sub-10ms audio I/O on Windows (currently using PortAudio/sounddevice)
3. **Multi-band spectral analysis** — if cadence detection becomes more complex
4. **Tauri/Rust bridge** — already in Rust, could be optimized for lower-latency audio routing

### Recommendation

Clean up the Python code architecture first (Phase 1 + Phase 2). If sub-50ms audio round-trip latency is needed later, consider a Rust/C++ audio bridge via Tauri. But for the current issues, the fixes are **architectural**, not language-level.

---

## 6. Implementation Order

### Phase 1 (immediate)

| Step | Task | Files |
|------|------|-------|
| 0 | Pocket-TTS streaming test | (read-only script) |
| 1 | Barge-in tuning | `backend/audio/engine.py` |
| 2 | VAD silence | `backend/audio/voice_command.py` |
| 3 | STTPROC amplification | `backend/iris_gateway.py` |
| 4 | Filler phrase pre-synthesis | `backend/agent/tts.py`, `backend/iris_gateway.py` |
| 5 | Orb cadence ref-based | `hooks/useClientMicCadence.ts`, `hooks/useCadenceDetection.ts`, `components/iris/orb/OrbCanvas.tsx`, `components/iris/XurOrb.tsx` |
| 6 | TTS latency gap | `backend/iris_gateway.py`, `backend/agent/tts.py` |
| 7 | Barge-in pipeline safety | `backend/iris_gateway.py` |
| 8 | Run all tests | barge-in tests, parakeet tests, new filler tests |
| 9 | Restart backend + frontend | verify end-to-end |

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
- [ ] Orb breathing is smooth at 60fps, no stutter
- [ ] React re-renders reduced from 70/sec to 10/sec
- [ ] TTS first audio plays within 1-2s of text appearing in chat
- [ ] No dead air between STTPROC stop and TTS start
- [ ] Barge-in cleanly interrupts producer thread (no stale chunks)
- [ ] Timing instrumentation reveals actual bottleneck
- [ ] All existing tests pass (17/17 barge-in + parakeet)
- [ ] "speaking" state broadcast before first audio chunk (improved perceived responsiveness)

### Phase 2

- [ ] Event bus created and tested
- [ ] ConversationKernel emits utterance events
- [ ] TaskKernel emits tool-call and planning events
- [ ] TTS only receives utterance events (no tool calls)
- [ ] Caducean phase governs when to speak vs when to work
- [ ] Status phrases during long tasks
- [ ] Turn IDs link utterances to task steps

---

*For Caducean Engine technical overview: `docs/CADUCEAN_TECHNICAL_OVERVIEW.md`*
*For MCM agent protocol: `AGENTS.md`*
