# IRIS Voice — Full Audio Pipeline Architecture

> **DEFINITIVE REFERENCE** — Last updated 2026-07-13 (agent narration unification + stop-listening voice command).
> This document is the single source of truth for the audio pipeline. If the
> code and this document ever disagree, treat this as a bug and update both.
> All values below are verified against `backend/audio/voice_command.py` and
> `backend/iris_gateway.py` at commit `3997c3ca`.

---

## Table of Contents

1. [Overview](#overview)
2. [Component Inventory](#component-inventory)
3. [Complete Flow — Wake Word to TTS Playback](#complete-flow--wake-word-to-tts-playback)
4. [Thread Architecture](#thread-architecture)
5. [WebSocket Events (Backend → Frontend)](#websocket-events-backend--frontend)
6. [VAD State Machine](#vad-state-machine)
7. [TTS Streaming Pipeline](#tts-streaming-pipeline)
8. [Word Highlighting Sync](#word-highlighting-sync)
9. [Barge-In Architecture](#barge-in-architecture)
10. [Half-Duplex Gate (Echo Avoidance)](#half-duplex-gate-echo-avoidance)
11. [Voice State Machine](#voice-state-machine)
12. [Memory Budget](#memory-budget)
13. [Error Recovery](#error-recovery)
14. [Test Coverage](#test-coverage)
15. [Known Issues & Recent Fixes](#known-issues--recent-fixes)
16. [Agent-Initiated Narration](#agent-initiated-narration-speaktool--conversationkernel)
17. [Stop Listening Voice Command](#stop-listening-voice-command)

---

## Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          IRIS VOICE — AUDIO PIPELINE                           │
│                                                                                 │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐ │
│  │  WAKE    │───▶│   VAD    │───▶│   STT    │───▶│   LLM    │───▶│   TTS    │ │
│  │  WORD    │    │          │    │          │    │          │    │          │ │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘ │
│       │               │               │               │               │        │
│   Porcupine       Energy-based    Parakeet GPU   Provider-agnostic  Pocket-TTS │
│   (native C++)    + silence       (in-process)   (agent card picks  (streaming) │
│                   detection       or Whisper      the provider)                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

The pipeline runs five sequential phases plus a cross-cutting half-duplex gate
and a barge-in interrupt path. Each phase runs in its own thread or async
task. State transitions are coordinated via `threading.Event` objects and
WebSocket broadcasts.

---

## Component Inventory

| Component | File | Role | Threading |
|-----------|------|------|-----------|
| **AudioEngine** | `backend/audio/engine.py` | Manages mic input stream, frame listeners, half-duplex gate (`_tts_active`) | Single-threaded callback |
| **AudioPipeline** | `backend/audio/pipeline.py` | PortAudio I/O streams, native C++ player, device enumeration | Callback + main |
| **VoiceCommandHandler** | `backend/audio/voice_command.py` | VAD, recording, STT orchestration, cadence detection, activation beep | Multi-threaded (VAD + STT + beep) |
| **ParakeetTranscriber** | `backend/audio/voice_command.py` | In-process GPU ASR (lazy-loaded, ~1.2GB VRAM) | Async |
| **CadenceDetector** | `backend/audio/cadence_detector.py` | Spectral flux → 0-1 cadence envelope | Inline |
| **iris_gateway** | `backend/iris_gateway.py` | TTS orchestration, WS events, word timing, state management, stop-listening sleep state (`_sleeping_sessions`) | Multi-threaded (producer + consumer + word monitor + cadence) |
| **WS Manager** | `backend/ws_manager.py` | WebSocket broadcast/send with session tracking | Async |
| **useIRISWebSocket** | `hooks/useIRISWebSocket.ts` | WS event dispatch → React state | React effect |
| **XurOrb** | `components/iris/XurOrb.tsx` | Orb component, voice state rendering | React |
| **OrbCanvas** | `components/iris/orb/OrbCanvas.tsx` | Canvas-based 3D orb, breath animations | Canvas RAF |
| **chat-view** | `components/chat-view.tsx` | Word highlighting, response rendering | React effect |
| **SpeakTool** | `backend/agent/tools/speak_tool.py` | Agent-initiated TTS speech (fire-and-forget, rate-limited, bounded) | EventBus emit |
| **ConversationKernel (narration)** | `backend/agent/conversation_kernel.py` | Single narration path for agent speech; broadcasts audio_envelope / listening_state | Worker thread |

---

## Complete Flow — Wake Word to TTS Playback

### Phase 1: Wake Word Detection
```
┌──────────────────────────────────────────────────────────┐
│  Porcupine (native C++ via picovoice)                    │
│                                                          │
│  - Runs continuously on AudioEngine input stream         │
│  - Listens for "Hey Iris" (custom .ppn wake word)        │
│  - On detection → voice_handler.start_recording()        │
│  - AudioEngine half-duplex gate: _tts_active = True      │
│    drops incoming frames during TTS (echo avoidance)     │
└──────────────────────┬───────────────────────────────────┘
                       │ wake word detected
                       ▼
```

**Configuration** (in `backend/audio/engine.py`):
```python
"activation_sound": "liquid-bubble-3000.wav",  # activation chime
```

### Phase 2: Voice Activity Detection (VAD)
```
┌──────────────────────────────────────────────────────────┐
│  VoiceCommandHandler._capture_frame()                    │
│  (registered as AudioEngine frame listener)              │
│                                                          │
│  - Accumulates float32 PCM frames into _raw_frames[]    │
│  - Energy-based VAD loop (auto_stop=True):               │
│    ├─ VAD_ENERGY_THRESHOLD = 0.006 RMS                   │
│    ├─ VAD_MIN_SPEECH_SEC = 0.15s (ignore blips)          │
│    ├─ VAD_SILENCE_SEC = 1.2s → end of utterance          │
│    └─ VAD_MAX_DURATION_SEC = 30s (hard cap)              │
│  - VAD_POLL_INTERVAL_SEC = 0.015s (CPU-efficient wait)   │
│  - Broadcasts audio_envelope WS events during recording  │
│    { rms, cadence, phase: "listening" }                  │
│  - CadenceDetector.process() → spectral flux envelope    │
│    (tracks speech rhythm for orb breathing)              │
└──────────────────────┬───────────────────────────────────┘
                       │ VAD detects end-of-speech
                       ▼
```

**VAD State Machine** (see [VAD State Machine](#vad-state-machine) for details):
- `PRE_SPEECH` → wait for RMS ≥ threshold
- `IN_SPEECH` → wait for sustained silence
- `DONE` → return True/False

**Barge-in VAD flush**: When recording is triggered by barge-in, the first
~400ms of captured frames are dropped via `flush_ms=400`. This lets residual
TTS echo from the interrupted playback decay before VAD speech detection begins.

### Phase 3: Speech-to-Text (STT)
```
┌──────────────────────────────────────────────────────────┐
│  VoiceCommandHandler._run_transcription()                │
│                                                          │
│  1. _vad_wait_for_speech_then_silence() returns bool    │
│     ├─ False → skip Parakeet (prevents hallucination)    │
│     └─ True → proceed to transcription                   │
│                                                          │
│  2. Try ParakeetTranscriber (GPU, in-process)            │
│     ├─ Lazy-loads nvidia/parakeet-tdt-0.6b-v3 on        │
│     │  first call (~1.2GB VRAM, fp16 on RTX 3070)       │
│     ├─ Preloaded at startup via asyncio.create_task()    │
│     │  in FastAPI lifespan to avoid first-call latency   │
│     ├─ float32 PCM → int16 → processor → GPU inference   │
│     ├─ batch_decode() → text                             │
│     └─ Returns "" on failure → falls back                │
│                                                          │
│  3. Fallback: faster-whisper (tiny/int8, ~40MB CPU)      │
│     ├─ WhisperModel('tiny', compute_type='int8')         │
│     ├─ transcribe(wav_buffer, beam_size=1)               │
│     └─ ~40MB RAM, no VRAM conflict                       │
│                                                          │
│  → _on_command_result callback with client_id            │
└──────────────────────┬───────────────────────────────────┘
                       │ transcribed text
                       ▼
```

### Phase 4: LLM Processing (Provider-Agnostic)
```
┌──────────────────────────────────────────────────────────┐
│  iris_gateway._on_command_result()                       │
│                                                          │
│  1. Send user bubble via text_response (turn_id)         │
│  2. Broadcast listening_state = "processing_conversation"│
│  3. Start STTPROC loop sound (data/STTPROC.wav)          │
│     ├─ 3x gain (file is -27.4 dBFS, target -17.9 dBFS)  │
│     ├─ Resample to 24kHz                                 │
│     ├─ Loops until TTS playback starts                   │
│     └─ Stops on _sttproc_stop event                      │
│  4. AgentKernel._model_provider determines the backend: │
│     ├─ "lmstudio"        → LM Studio local API          │
│     ├─ "iris_local"      → In-process llama-cpp-python   │
│     ├─ "local"           → LFM HuggingFace model         │
│     ├─ "api"             → Remote API (OpenAI key)       │
│     ├─ "openai_compatible" → Any OpenAI-compat server    │
│     ├─ "cohere"/"deepseek"/"anthropic"/"groq"           │
│     │                    → Named remote APIs via LiteLLM  │
│     └─ "local" + ":"     → Ollama native API             │
│                                                          │
│  5. Streaming response → sentence queue                  │
│  6. chat_chunk WS events → frontend for progressive text │
│  7. text_response WS event → final assembled response    │
│  8. listening_state WS: "processing" → "speaking"         │
└──────────────────────┬───────────────────────────────────┘
                       │ sentence from LLM
                       ▼
```

### Phase 5: Text-to-Speech (TTS) — Streaming
```
┌──────────────────────────────────────────────────────────┐
│  iris_gateway._speak_response()                          │
│                                                          │
│  1. Generate _turn_id (uuid4) — shared across:          │
│     ├─ tts_started event (sent immediately)             │
│     └─ text_response (assistant) event (sent later)     │
│     This prevents the frontend from missing the first N  │
│     tts_word events due to re-entrancy race.             │
│                                                          │
│  2. Broadcast tts_started { turn_id, total_words }       │
│     └─ Frontend sets currentTtsMessageId from turn_id   │
│        so the word highlight listener is registered      │
│        BEFORE tts_word events arrive.                    │
│     Also used by play-button TTS path (isolated state): │
│        XurOrb.playbackSpeaking listens to tts_started    │
│        and drives the same breathing animation without   │
│        touching voiceState.                              │
│                                                          │
│  3. Producer thread: _producer()                         │
│     ┌─────────────────────────────────────────────────┐ │
│     │  Pocket-TTS streaming synthesis                 │ │
│     │  - Synthesizes sentence → float32 PCM chunks    │ │
│     │  - Pushes chunks to native player OR audio_queue│ │
│     │  - Broadcasts audio_envelope {rms, phase:"speaking"}│
│     │  - Tracks total samples for cadence timing      │ │
│     │  - _playback_event.set() on FIRST chunk pushed  │ │
│     └─────────────────────────────────────────────────┘ │
│                                                          │
│  4. Consumer path (native OR fallback):                  │
│     ┌─────────────────────────────────────────────────┐ │
│     │  Native C++ ring-buffer player (sub-5ms latency)│ │
│     │  OR sounddevice (PortAudio) fallback            │ │
│     │  - playback_started_event passed to play_stream()│ │
│     └─────────────────────────────────────────────────┘ │
│                                                          │
│  5. Word-highlight thread: _monitor_words()              │
│     ┌─────────────────────────────────────────────────┐ │
│     │  Dynamic while-True loop (re-checks _all_words) │ │
│     │  - Character-proportional timing at 15.8 chars/s│ │
│     │  - Fires tts_word WS events                     │ │
│     │  - is_final=True only after stream close         │ │
│     │  - Barge-in: catch up remaining words at 30ms   │ │
│     └─────────────────────────────────────────────────┘ │
│                                                          │
│  6. Cadence thread: _broadcast_native_cadence()          │
│     ┌─────────────────────────────────────────────────┐ │
│     │  - Uses RMS from producer as cadence envelope   │ │
│     │  - Sends audio_envelope {rms, cadence, "speaking"}│
│     │  - ~10 Hz broadcast rate                        │ │
│     └─────────────────────────────────────────────────┘ │
│                                                          │
│  7. Post-stream interrupt monitor (1s window):            │
│     - Polls engine.is_speech_interrupted() for 1s       │
│     - If interrupted, broadcasts idle envelope           │
│                                                          │
│  8. finally block:                                       │
│     - Set _sttproc_stop (always, unconditional)         │
│     - Stop word monitor thread (signal + join 3s)       │
│     - On SUCCESS: conversation mode → auto-relisten      │
│                   single-shot → send idle                │
│     - On ERROR: send idle (unsticks orb from "speaking") │
└──────────────────────┬───────────────────────────────────┘
                       │ audio played
                       ▼
```

### Phase 6: Frontend Rendering
```
┌──────────────────────────────────────────────────────────┐
│  useIRISWebSocket.ts                                     │
│                                                          │
│  WS events received:                                     │
│  ├─ listening_state → setVoiceState()                    │
│  │   "idle" | "listening" | "speaking" | "processing"   │
│  ├─ audio_envelope → { rms, cadence, phase }             │
│  │   ├─ phase="listening" → setAudioLevel(rms)           │
│  │   │                          setCadenceLevel(cadence) │
│  │   ├─ phase="speaking" → setTtsAudioLevel(rms)         │
│  │   │                          setCadenceLevel(rms)     │
│  │   └─ phase="idle" → zeros all levels                  │
│  ├─ tts_started → setCurrentTtsMessageId(turn_id)        │
│  │   setTtsTotalWords(total_words)                       │
│  ├─ tts_word → dispatch iris:tts_word CustomEvent        │
│  │   { word_index, total_words, is_final }               │
│  ├─ chat_chunk → dispatch iris:chat_chunk CustomEvent    │
│  └─ chat_message → setLastTextResponse()                 │
│                                                          │
│  XurOrb.tsx                                              │
│  ├─ voiceState prop → orb animation state                │
│  ├─ audioPhase prop → "listening" | "speaking" | "idle"  │
│  ├─ audioLevel (listening RMS) → orb scale/pulse         │
│  ├─ ttsAudioLevel (speaking RMS) → orb glow              │
│  ├─ cadenceLevel → breathing rhythm (spectral flux       │
│  │   during listening, RMS during speaking)              │
│  └─ handleDoubleClick → startVoiceCommand()              │
│                                                          │
│  chat-view.tsx                                           │
│  ├─ Listens for iris:tts_word → updates ttsWordIndex     │
│  │   (highlights current word in response text)          │
│  ├─ useEffect deps: [ttsTotalWords, message?.words]      │
│  │   (re-runs when ttsTotalWords arrives from tts_started)│
│  └─ fallbackActive = false initially, enabled after 1s   │
│      timeout fires without backend events                │
│                                                          │
│  OrbCanvas.tsx                                           │
│  ├─ Canvas-based 3D orb rendering                        │
│  ├─ breathMode/breathLevel props → animation driver     │
│  └─ Smooth interpolation between states                  │
└──────────────────────────────────────────────────────────┘
```

---

## Agent-Initiated Narration (SpeakTool → ConversationKernel)

Agent-initiated speech — web-search progress ("Searching the web for…"),
fillers ("One moment"), `ask_user` reminders, and any background narration —
is the SAME output stream as a normal LLM response. There is ONE frontend
narration contract; both TTS drivers feed it.

### The single narration contract

The frontend "speaking / thinking" indicator (orb + chatview) is driven ONLY
by two WS messages:

  * `audio_envelope`  — `{ rms, cadence, phase: "speaking" | "idle" }`
  * `listening_state` — `{ state: "speaking" | "idle" | ... }`

Both the normal response path (`iris_gateway._speak_response`) and the
agent-initiated path (`ConversationKernel._speak_utterance`) broadcast these.
This is the unification: "utterance" and "narration" are one concept — the
act of the agent speaking.

### SpeakTool (fire-and-forget emitter)

`backend/agent/tools/speak_tool.py`:

  * `speak(text, priority, interrupt)` emits `UTTERANCE_START` on the EventBus
    and returns immediately (never blocks the DER loop).
  * Text bounded to `MAX_TEXT_CHARS = 500`; pending speaks rate-limited
    (`MAX_PENDING = 3` within a 10s window) so a runaway agent can't flood TTS.
  * `UTTERANCE_START` / `UTTERANCE_DONE` are a BACKEND-INTERNAL contract
    (consumed by `SpeakBroadcaster` for external channels — Telegram, MCP).
    The frontend does NOT listen to them; it listens to `audio_envelope` /
    `listening_state` (above).

### ConversationKernel._speak_utterance (the single narration path)

`backend/agent/conversation_kernel.py`:

  1. `_on_utterance_start` (subscribed to `UTTERANCE_START`) spawns a daemon
     worker thread → `_speak_utterance(text, interrupt)`.
  2. Resolves session_id (`session_id_getter` → `voice_handler._active_session_id`
     → `"default"`).
  3. Broadcasts `listening_state: speaking` + `audio_envelope` (phase speaking).
  4. Serializes playback via the shared `_NARRATION_PLAYBACK_LOCK` (below) and
     calls `pipeline.play_stream(tts.synthesize_stream(text))`.
  5. Broadcasts `audio_envelope` (phase idle) + `listening_state: idle`.

Because steps 3 and 5 use the SAME messages as `_speak_response`, the orb /
chatview "speaking" indicator now fires for agent speech exactly as it does
for a normal response — web search, fillers, and any background task the user
is waiting on.

### Serialization (no cut-off)

`_NARRATION_PLAYBACK_LOCK` (module-level in `conversation_kernel.py`, exposed
via `narration_playback_lock()`) serializes ALL TTS playback:

  * `ConversationKernel._speak_utterance` holds it for the full playback.
  * `iris_gateway._speak_response` waits on it (non-holding) at the start of
    its producer thread, so a response can't cut an in-flight agent utterance
    off mid-word (the web-search "Searching…" cut-off bug).

This fixes the TTS utterance cut-off that occurred when the DER loop advanced
and the next step's audio overlapped the still-playing utterance.

---

## Stop Listening Voice Command

The user can release the microphone hands-free by saying a stop-listening
phrase. This is detected from the **transcribed speech text** — it does NOT
require a separate wake word or a second Porcupine model. The wake word
("Hey Iris") only *opens* the session; a stop-listening phrase *closes* it.

### Trigger phrases

`iris_gateway._STOP_LISTENING_PHRASES` (matched after filler stripping via
`_normalize_for_sleep`):

- "stop listening" / "stop listening now"
- "go to sleep" / "sleep now" / "sleep mode"
- "that's all" / "thats all"
- "stop now"
- "pause listening"

Fillers stripped before matching (`_STOP_LISTENING_FILLERS`): "hey iris",
"okay", "please", "iris", "um", "uh", "yo". So "hey iris stop listening" and
"okay stop listening now" both match.

### State

`iris_gateway._sleeping_sessions: set` — session IDs that have been put to
sleep. Initialized in `__init__` alongside the other session-state sets.

### Entering sleep — `_enter_sleep_mode(session_id)`

Async coroutine invoked (via `run_coroutine_threadsafe`) from
`_on_voice_result` when a stop phrase is detected:

1. `self._sleeping_sessions.add(session_id)`
2. `self._conversation_sessions.discard(session_id)` — drops conversation
   mode so the next wake word starts a fresh turn
3. `voice_handler.cancel_recording()` — releases VAD / recording / ASR
4. Broadcasts `listening_state: "idle"` — orb returns to idle

**Porcupine stays armed.** Only the heavy VAD/STT/TTS path is released; the
native C++ wake-word listener keeps running at low power, so a later
"Hey Iris" re-opens the session.

### Interception point — `_on_voice_result`

After the loop-availability check and BEFORE the empty-transcript branch,
the transcript is tested with `_matches_stop_listening()`. On a match the
gateway calls `_enter_sleep_mode(...)` and **returns immediately** — the
LLM is never queried and TTS never fires. Normal commands fall through to
the normal pipeline unchanged.

### Auto-relisten suppression — `_should_auto_relisten`

Extracted helper used by the `_speak_response` finally block. Returns
`True` only when:

- the session is in conversation mode, AND
- `session_id not in self._sleeping_sessions`

So a response that finished just before the user said "stop listening" will
NOT auto-relisten and re-open the mic — the session stays asleep until the
next wake word.

### Wake-word re-entry — `_handle_voice`

On a new wake-word detection, `self._sleeping_sessions.discard(session_id)`
clears the sleep flag so the session behaves normally again. (Barge-in does
NOT clear sleep — sleep and an active recording cannot coexist; the user
must wake the assistant to resume.)

### Voice State Machine addition

A `SLEEP` state is added to the voice state machine (see
[Voice State Machine](#voice-state-machine) for the full diagram):

```
SLEEP → (wake word) → RECORDING   (re-opens the session)
SPEAKING / IDLE → (stop-listening phrase) → SLEEP   (mic released, wake word armed)
```

---

## Thread Architecture

```
iris_gateway._speak_response()
│
├── Producer Thread (_producer)
│   ├── Pocket-TTS synthesis (sentence queue → PCM chunks)
│   ├── Push to native player OR audio_queue
│   ├── Broadcast audio_envelope WS events (~10 Hz)
│   └── _playback_event.set() on first chunk
│
├── Consumer (main thread via pipeline)
│   ├── Native C++ ring-buffer player (sub-5ms)
│   │   └── OR sounddevice fallback (PortAudio)
│   └── playback_started_event parameter
│
├── Word-highlight Thread (_monitor_words)
│   ├── Dynamic while-True loop (re-checks _all_words)
│   ├── Character-proportional sleep at 15.8 chars/sec
│   ├── Wait for _total_written_for_words > 0 (first chunk)
│   ├── _word_monitor_stop event for kill
│   └── Barge-in: catch up remaining at 30ms intervals
│
├── Cadence Thread (_broadcast_native_cadence)
│   ├── Uses RMS from producer
│   └── Broadcasts audio_envelope {phase:"speaking"} at 10 Hz
│
├── Post-stream Interrupt Monitor (main thread)
│   ├── Polls engine.is_speech_interrupted() for 1s
│   └── If interrupted, broadcasts idle envelope
│
└── VoiceCommandHandler (recording phase)
    ├── _capture_frame() — AudioEngine frame listener
    ├── VAD loop thread — energy-based silence detection
    ├── ParakeetTranscriber.transcribe() — GPU inference
    │   └── OR _whisper.transcribe() — CPU fallback
    └── CadenceDetector.process() — spectral flux
```

**Thread safety guarantees:**
- `_word_monitor_stop` is instance-level — each new `_speak_response` sets
  the old event to kill the old monitor, then creates a fresh Event.
- Old monitor thread joined with 500ms timeout.
- WS broadcasts use `run_coroutine_threadsafe()` from threads to the
  main asyncio loop.
- `self._main_loop` is captured at iris_gateway init for thread-safe calls.

---

## WebSocket Events (Backend → Frontend)

| Event | Payload | When | Purpose |
|-------|---------|------|---------|
| `listening_state` | `{ state: "idle" \| "listening" \| "speaking" \| "processing" \| "processing_conversation" }` | State transitions | Orb animation mode |
| `audio_envelope` | `{ rms, cadence, phase }` | During recording + playback (~10 Hz) | Orb breathing/speaking |
| `audio_level` | `{ level }` | During recording (legacy) | Old IrisOrb compatibility |
| `tts_started` | `{ turn_id, total_words }` (flat, not nested) | Before TTS playback starts | Frontend sets currentTtsMessageId early |
| `tts_word` | `{ word_index, total_words, is_final }` | During TTS playback | Word highlighting in chat |
| `chat_chunk` | `{ chunk }` | LLM streaming | Progressive text rendering |
| `text_response` | `{ text, sender, turn_id }` | LLM complete (user + assistant) | Final response display |
| `chat_message` | `{ content, turn_id, thinking }` | LLM complete | Final response display (legacy) |

---

## VAD State Machine

The VAD runs in `VoiceCommandHandler._vad_wait_for_speech_then_silence()`.
It is a two-state machine with a return value indicating whether speech
was actually detected.

### Parameters (from `backend/audio/voice_command.py`)

```python
VAD_ENERGY_THRESHOLD: float = 0.006  # RMS level that counts as speech
VAD_MIN_SPEECH_SEC: float = 0.15     # ignore blips shorter than this
VAD_SILENCE_SEC: float = 1.2         # silence after speech → end of utterance
VAD_MAX_DURATION_SEC: float = 30.0   # hard cap on recording length
VAD_POLL_INTERVAL_SEC: float = 0.015 # how often VAD loop checks for new frames
```

### State Transitions

```
PRE_SPEECH
  │ rms >= VAD_ENERGY_THRESHOLD
  │ AND speech_count >= speech_needed (5 frames at 0.15s)
  ▼
IN_SPEECH
  │ rms < VAD_ENERGY_THRESHOLD
  │ AND silence_count >= silence_needed (37 frames at 1.2s)
  ▼
DONE → return True (speech detected and ended naturally)
```

### Return Values

- **True**: Speech was detected and ended naturally. Proceed to transcription.
- **False**: Only silence was captured (timeout or max duration). **Skip
  transcription** to avoid Parakeet hallucinating text from silence.

### Barge-in VAD Flush

When recording is triggered by barge-in (`flush_ms=400`), the first ~400ms
of captured frames are dropped. This lets residual TTS echo from the
interrupted playback decay before VAD speech detection begins. The flush
is applied at frame level in `_capture_frame()`.

---

## TTS Streaming Pipeline

The TTS pipeline is a producer-consumer pattern with a separate word-highlight
thread. All three threads coordinate via `threading.Event` objects.

### Producer (_producer)

The producer thread runs Pocket-TTS synthesis. It:
1. Pops sentences from `sentence_queue`
2. Synthesizes each sentence → float32 PCM chunks
3. Pushes chunks to the native player OR `audio_queue` (fallback path)
4. Broadcasts `audio_envelope` events at ~10 Hz with RMS/cadence
5. Sets `_playback_event` on the first chunk pushed to the device

### Consumer (native path)

The native C++ ring-buffer player receives chunks from the producer.
- `playback_started_event` is set on first chunk
- `engine.pipeline._native_player.wait_done()` blocks until playback completes
- The consumer thread joins the word-highlight thread after playback

### Consumer (fallback path)

Uses `sounddevice.OutputStream` for PortAudio-based playback:
- Creates an async stream callback that writes chunks from `audio_queue`
- Sets `_playback_event` on first chunk written
- Closes the stream on barge-in (discards buffered audio) or stops/closes on
  normal completion

### Word-Highlight Thread (_monitor_words)

**Contract** (enforced by `TestTTSWordEventIntegration` in
`backend/tests/test_voice_pipeline.py`):
1. **All expected indices appear** (monotonically non-decreasing)
2. **No premature is_final** (`is_final=True` only after stream close)
3. **Barge-in**: remaining words catch up at 30ms intervals;
   `is_final` on the last catch-up word
4. **Dynamic word count**: re-reads `len(_all_words)` each iteration to
   catch words added by the producer from later sentences

**Timing algorithm** (character-proportional, 15.8 chars/sec):
```python
_char_prop = len(_all_words[_i]) / _total_chars_now
_est_tts_dur = _total_chars_now / 15.8
_word_dur = max(0.03, _est_tts_dur * _char_prop)
```

**Why character-proportional and not `_sd_stream.time`?**
`_sd_stream.time` is unreliable on Windows WASAPI/MME. Character-proportional
sleep is deterministic, matches the native path (proven working), and has
no OS-specific audio API dependency.

**Why 15.8 chars/sec?**
This rate closely matches the actual Pocket-TTS synthesis speed. Tuned through
multiple iterations: 12.5 (too slow, highlights lagged) → 14.5 (closer) →
15.8 (verified perfectly in sync with TTS playback during live testing).
The `tts_started` event includes `total_words` so the frontend can derive
character-proportional timing independently.

---

## Word Highlighting Sync

Word highlighting is a three-component system: backend word events, frontend
state, and frontend rendering.

### Backend: Word Events

The word monitor thread broadcasts `tts_word` events:
```json
{
  "type": "tts_word",
  "payload": {
    "word_index": 0,
    "total_words": 5,
    "is_final": false
  }
}
```

The `tts_started` event is sent **before** the first `tts_word`:
```json
{
  "type": "tts_started",
  "turn_id": "uuid4-here",
  "total_words": 5
}
```

### Re-entrancy Race Fix

**Problem**: If `tts_started` arrives before `text_response` (assistant),
the frontend's `currentTtsMessageId` is null when the first `tts_word` events
arrive, causing the useEffect to return early and miss the first N words.

**Fix**: Both `tts_started` and `text_response` (assistant) use the **same**
`_turn_id` (generated at the start of `_speak_response`). The frontend
sets `currentTtsMessageId` from `tts_started.turn_id` immediately, so the
word highlight listener is registered before the first `tts_word` event.

### Multi-Sentence Coverage Fix

**Problem**: The original word monitor used `for _i in range(0, _wn)` which
captured the word count once at start. Words from later sentences added by
the producer were never broadcast.

**Fix**: Dynamic `while True` loop that re-reads `len(_all_words)` each
iteration. When `_i >= _current_wn`, the monitor waits for the producer to
add more words (50ms poll) or for the stream to close.

### Fallback Timing Fix

**Problem**: The frontend had `fallbackActive = true` from the start. The
200ms interval incremented `wordIndex` before the first backend event
arrived, causing the highlight to move faster than the audio.

**Fix**: `fallbackActive = false` initially. The 1-second timeout fires only
if no backend events arrive, then enables the fallback as a safety net.

### Frontend: Rendering

`chat-view.tsx` listens for `iris:tts_word` CustomEvents:
```typescript
useEffect(() => {
  const handler = (e: CustomEvent) => {
    const { word_index, total_words, is_final } = e.detail;
    setTtsWordIndex(word_index);
    setTtsTotalWords(total_words);
    setFallbackActive(false);  // Backend event received
  };
  window.addEventListener('iris:tts_word', handler);
  return () => window.removeEventListener('iris:tts_word', handler);
}, [ttsTotalWords, message?.words?.length]);
```

The effect re-runs when `ttsTotalWords` changes (from `tts_started` event).

---

## Barge-In Architecture

Barge-in is the ability for the user to interrupt TTS playback by speaking.
It involves coordinated state changes across audio, STT, and TTS layers.

### Barge-In Flow

```
User speaks during TTS playback
  │
  ▼
VAD detects speech (energy threshold)
  │
  ▼
iris_gateway.is_speech_interrupted() returns True
  │
  ▼
_speak_response() sets `interrupted` event
  │
  ├─ Consumer path: closes _sd_stream (discards buffered audio)
  │   OR sets _sttproc_stop (native path)
  │
  ├─ Word monitor: catch up remaining words at 30ms intervals
  │   (is_final on last catch-up word)
  │
  └─ Cadence thread: stops broadcasting speaking envelopes
  │
  ▼
start_recording(play_beep=False, flush_ms=400)
  ├─ flush_ms=400 drops first ~400ms of frames (TTS echo decay)
  └─ play_beep=False skips activation chime
  │
  ▼
VAD loop runs with cleaned audio → STT → LLM → TTS
```

### Barge-In VAD Flush

When recording is triggered by barge-in, the first ~400ms of captured
frames are dropped via `flush_ms=400`. This lets residual TTS echo from
the interrupted playback decay before VAD speech detection begins. Without
this flush, the VAD would immediately detect the echo as speech, causing
a phantom "yeah" response.

### STTPROC Stop (Always)

The STTPROC processing loop is stopped **unconditionally** in the
`_speak_response` finally block. Previously it was only stopped on the
first audio chunk push, which left the loop running forever if barge-in
happened before the first chunk.

---

## Half-Duplex Gate (Echo Avoidance)

The half-duplex gate prevents the microphone from capturing TTS playback
audio (which would cause echo and false VAD triggers).

### Mechanism

```python
# In AudioPipeline._input_callback:
if self._tts_active:
    return  # drop frame, don't forward to listeners
```

### Transitions

- **TTS starts**: `engine.set_tts_active(True)` → mic frames dropped
- **TTS ends**: `engine.set_tts_active(False)` → mic frames forwarded
- **Activation beep**: Wrapped in `set_tts_active(True/False)` so the
  half-duplex gate drops frames captured while the sound is audible

### Why Not Full-Duplex?

Full-duplex (simultaneous playback + recording with echo cancellation) is
complex and error-prone. Half-duplex is simpler, more reliable, and
sufficient for voice assistant use cases where the user is not expected
to speak during TTS playback (except for barge-in, which has its own
mechanism).

---

## Voice State Machine

```
IDLE → (wake word / double-click) → RECORDING → PROCESSING → SPEAKING → IDLE
  ↑                                                                          │
  └──────────────────── conversation mode: auto-relisten ────────────────────┘
  ▲                                                                          │
  └── stop-listening phrase → SLEEP (mic released, wake word armed) ──────────┘

SLEEP → (wake word) → RECORDING   (re-opens the session)

Error path: any state → ERROR → IDLE (2s delay)
```

### State Transitions

| From | To | Trigger |
|------|-----|---------|
| IDLE | RECORDING | Wake word detected or orb double-click |
| RECORDING | PROCESSING | VAD detects end-of-speech |
| PROCESSING | SPEAKING | LLM response ready, TTS starts |
| SPEAKING | IDLE | TTS playback complete (single-shot mode) |
| SPEAKING | RECORDING | Conversation mode auto-relisten |
| SPEAKING / IDLE | SLEEP | Stop-listening phrase detected in transcript |
| SLEEP | RECORDING | Wake word ("Hey Iris") detected |
| any | ERROR | Exception in pipeline |
| ERROR | IDLE | 2s delay, unsticks orb |

### Orb Click Behavior

`handleOrbClick` in `XurOrb.tsx`:
- If `isSpeaking` → calls `cancelVoiceCommand()` to stop TTS
- If idle → calls `startVoiceCommand()` to begin recording

---

## Memory Budget

LLM memory depends on the user's selected provider (see Phase 4). These are
the fixed audio-pipeline costs:

| Component | VRAM | RAM | When |
|-----------|------|-----|------|
| Parakeet (fp16) | ~1.2 GB | ~200 MB | Lazy-loaded on first STT, preloaded at startup |
| faster-whisper (int8) | 0 | ~40 MB | Fallback if parakeet fails |
| Porcupine | 0 | ~5 MB | Always (wake word) |
| Torch + transformers | 0 | ~200 MB | Loaded with parakeet |
| Native C++ player | 0 | ~1 MB | During TTS playback |
| Pocket-TTS | 0 | ~50 MB | During TTS synthesis |
| **Total (audio pipeline, parakeet)** | **~1.2 GB** | **~450 MB** | — |
| **Total (audio pipeline, whisper)** | **0** | **~95 MB** | — |

**Watchdog thresholds** (in `backend/core/memory_watchdog.py`):
- Warning: 5000 MB
- Critical: 7000 MB

LLM provider memory (separate, user-selected):
| Provider | VRAM | RAM |
|----------|------|-----|
| LM Studio (local model) | varies by model | varies by model |
| iris_local (llama-cpp) | varies by GGUF | varies by GGUF |
| Ollama | varies by model | varies by model |
| Remote API (OpenAI, Anthropic, etc.) | 0 | ~10 MB (HTTP client) |

---

## Error Recovery

| Failure | Recovery |
|---------|----------|
| Parakeet GPU OOM | Falls back to faster-whisper (CPU) |
| Parakeet load error | Falls back to faster-whisper, logs error once |
| Parakeet hallucination from silence | `_vad_wait_for_speech_then_silence()` returns False → skip transcription |
| TTS synthesis error | `_succeeded=False` → sends idle state (unsticks orb) |
| Native player fails | Falls back to sounddevice (PortAudio) |
| WebSocket disconnect | Frontend reconnects, state resets to idle |
| LM Studio unreachable | Shows fallback model list (expected when not using LM Studio) |
| PortAudio init slow | Lazy-loaded on first audio use, not at startup |
| STTPROC infinite loop | Fixed: always stopped in `_speak_response` finally block |
| Word monitor thread leak | Fixed: `_word_monitor_stop` is instance-level, old thread killed + joined |
| Barge-in echo | Fixed: `flush_ms=400` drops first ~400ms of frames |
| Output device "Default" string | Fixed: resolve "Default" → None for sounddevice compatibility |
| Timer(2.0) orphan | Fixed: stored as `_idle_timer`, cancelled on next recording start |
| Activation beep during barge-in | Fixed: `play_beep=False` skips beep during re-recordings |
| .env PICOVOICE_ACCESS_KEY missing | Fixed: synced real key from `.env.local` into `.env` |
| Parakeet hallucination after barge-in | Fixed: RMS guard (`< 1e-4`) skips Parakeet on near-silence |

---

## Test Coverage

### Test Files

- `backend/tests/test_voice_pipeline.py` — 88 unit/integration tests + 3 new regression tests (91 total)
- `backend/tests/test_latency_metrics.py` — 8 latency metric tests
- `backend/tests/test_chunk_callback_nonstreaming.py` — 6 chunk callback / DER path tests
- `backend/tests/test_barge_in.py` — 40+ tests
- `backend/tests/test_conversation_kernel.py` — 12 tests
- `backend/tests/test_voice_pipeline.py::TestStopListening` — 21 tests (phrase match incl. fillers/negatives, pipeline interception skips LLM/TTS, auto-relisten suppression, sleep entry, wake-word re-entry)
- `backend/tests/test_narration_broadcast.py` — 4 tests (narration speaking→idle order, serialization via `_NARRATION_PLAYBACK_LOCK`, no-broadcast unwired, gateway wires broadcaster)

### TestWordMonitorCharacterProportional (6 unit tests)

Verifies the character-proportional algorithm contracts:
- Word events fire in order
- Total events match word count
- Barge-in catch-up fires is_final
- Multi-sentence word coverage

### TestTTSWordEventIntegration (7 integration tests)

**Contract** (enforced by these tests):
1. All expected indices appear (monotonically non-decreasing)
2. No premature is_final (is_final=True only after stream close)
3. Barge-in: remaining words catch up at 30ms intervals
4. Multi-sentence: words from later sentences are broadcast

**Test cases**:
- `test_tts_word_events_for_single_sentence`
- `test_barge_in_catchup_integration`
- `test_tts_started_events_include_turn_id`
- `test_multi_sentence_dynamic_word_count`
- `test_text_response_includes_turn_id_matching_tts_started`
- `test_text_response_turn_id_source_code_contract`
- `test_tts_play_sends_tts_started_not_listening_state`

**Critical**: `_make_mock_gateway` uses `AsyncMock` for `broadcast_to_session`
and `send_to_client`. `MagicMock` lacks `__await__` in Python 3.14, so
`run_coroutine_threadsafe()` would raise `TypeError` silently.

### Contract Warning

The `_monitor_words` function has a contract comment:
```python
# CONTRACT: TestTTSWordEventIntegration enforces:
#   1. All expected indices appear (monotonically non-decreasing)
#   2. No premature is_final (is_final=True only after stream close)
#   3. Barge-in: remaining words catch up at 30ms intervals
# DO NOT change this function without updating the tests.
```

---

## Known Issues & Recent Fixes

### Session 156 (2026-07-13) — Agent Narration Unification

**RESOLVED**:
- Agent-initiated speech (SpeakTool / fillers / ask_user) now drives the SAME
  frontend "speaking" indicator as normal LLM responses. Previously
  `ConversationKernel._speak_utterance` called `pipeline.play_stream()`
  directly and emitted no `audio_envelope` / `listening_state`, so web-search
  progress, fillers, and background narration showed no UI. Now it broadcasts
  `audio_envelope` (phase speaking→idle) + `listening_state` (speaking→idle) —
  the single narration contract.
- TTS utterance cut-off fixed via `_NARRATION_PLAYBACK_LOCK` shared between
  `ConversationKernel._speak_utterance` and `iris_gateway._speak_response`.
  The response waits for any in-flight agent utterance before playing, so it
  can't cut narration off mid-word.
- Design decision: "utterance" == "narration" (one concept). `UTTERANCE_START`
  / `UTTERANCE_DONE` remain a backend-internal contract for `SpeakBroadcaster`
  (external channels); the frontend consumes only `audio_envelope` /
  `listening_state`.

### Session 157 (2026-07-13) — Stop Listening Voice Command

**RESOLVED**:
- Hands-free "stop listening" voice command, detected from the **transcribed
  speech text** (no separate wake word / Porcupine model). Phrases: "stop
  listening", "go to sleep", "that's all", "pause listening", etc. (fillers
  like "hey iris" / "okay" stripped first via `_normalize_for_sleep`).
- `iris_gateway._sleeping_sessions: set` tracks asleep sessions.
  `_enter_sleep_mode()` adds the session, drops conversation mode, calls
  `voice_handler.cancel_recording()`, and broadcasts `listening_state: idle`.
  Porcupine stays armed — a later "Hey Iris" re-opens the session.
- Interception in `_on_voice_result`: a stop phrase returns early (skips
  LLM/TTS). Normal commands are unaffected.
- Auto-relisten suppressed via extracted `_should_auto_relisten()` helper
  (adds `session_id not in self._sleeping_sessions`), so a response that
  finished just before "stop listening" won't re-open the mic.
- Wake-word re-entry in `_handle_voice` clears the sleep flag
  (`_sleeping_sessions.discard`). Barge-in does NOT clear sleep (sleep and an
  active recording cannot coexist).
- 25 new tests pass: `TestStopListening` (21) + `test_narration_broadcast.py`
  (4). Pre-existing failures in `test_domain2_voice.py` (DER_TOKEN_BUDGETS
  KeyError) and `test_barge_in.py::test_idle_timer_is_daemon` are unrelated to
  this change.

### Session 155 (2026-07-05) — Pipeline Solidified (commit 3997c3ca)

**RESOLVED**:
- Word highlighting regression — `turn_id` not propagated through
  `iris:text_response` CustomEvent. Backend sends `turn_id` at top level of
  WS message but handler only destructured from nested `payload`. Fixed:
  extract `message.turn_id` and pass through CustomEvent detail.
- Play-button TTS orb breathing — orb did not animate when user clicks play
  button on assistant response. Fixed: `tts_play` backend sends `tts_started`
  (with `turn_id` + `total_words`) instead of `listening_state: speaking`.
  Frontend XurOrb added `playbackSpeaking` state listening to
  `iris:tts_started`/`iris:tts_word(is_final)` for isolated breathing.
- Character-proportional timing tuned to **15.8 chars/sec** (was 12.5, then
  14.5). Verified perfectly in sync with TTS playback during live testing.
- 3 new targeted regression tests added (91/91 passing):
  - `test_text_response_includes_turn_id_matching_tts_started`
  - `test_text_response_turn_id_source_code_contract`
  - `test_tts_play_sends_tts_started_not_listening_state`

### Session 154 (2026-07-05) — Major Checkpoint (commit fa9313c7)

**RESOLVED**:
- Re-entrancy race (tts_started missing turn_id) — frontend now registers
  word highlighting listener immediately
- Multi-sentence word coverage — dynamic while True loop re-checks
  `len(_all_words)` instead of fixed-range for
- Fallback timing race — `fallbackActive` starts false, enabled only after
  1s timeout without backend events
- AsyncMock for WS manager in tests — `MagicMock` lacks `__await__` in
  Python 3.14, `run_coroutine_threadsafe` silently failed
- `_turn_id` in `text_response` — assistant responses now use same `_turn_id`
  as `tts_started` (was generating separate UUID)
- 140 tests passing (130 legacy + 6 unit + 4 integration)

**REMAINING TWEAKS** (all resolved in session 155):
- VAD sensitivity tuning (`VAD_SILENCE_SEC` increased from 0.75s to 1.2s)
- Word highlighting sync (`chars_per_sec` tuned from 10 → 12.5 → 14.5 → 15.8)

### Session 153 (2026-07-04) — Barge-In + STTPROC Fix (commit 42f9c9cf)

**RESOLVED**:
- STTPROC infinite loop — always stopped in `_speak_response` finally block
- Concurrent word monitor threads killed — `_word_monitor_stop` is
  instance-level
- Barge-in VAD echo flush — `flush_ms=400` drops first ~400ms of frames
- Word highlighting: character-proportional timing (replaced unreliable
  `_sd_stream.time`)
- `is_final` skipped on barge-in — main thread's `is_final` broadcast is
  skipped when `interrupted.is_set()`

### Session 152 (2026-07-03) — Output Device + Word Highlight Fix (commit 4b5d676f)

**RESOLVED**:
- Output device "Default" string fix — `"Default"` → `None` in three places
  (engine.py, voice_command.py, iris_gateway.py). STTPROC and beep now work.
- Word monitor `is_final` fix — `is_final: True` sent from main thread
  after stream closes.

### Session 151 (2026-07-02) — Parakeet Hallucination Fix (commit 2cc1b307)

**RESOLVED**:
- VAD/Parakeet hallucination fix — `_vad_wait_for_speech_then_silence()`
  returns `bool`, `_run_transcription()` skips Parakeet when `False`, RMS
  guard (`< 1e-4`). Prevents phantom "yeah" responses.

### Session 150 (2026-07-01) — Comprehensive Architecture

- Created this document as the definitive reference for the audio pipeline.
- All values verified against `backend/audio/voice_command.py` and
  `backend/iris_gateway.py`.

---

**END OF DOCUMENT** — If you find a discrepancy between this document and
the code, either fix the code to match the doc, or update the doc to match
the code. Never let them diverge silently.
