# IRIS Voice — Full Audio Pipeline Architecture

> **DEFINITIVE REFERENCE** — Last updated 2026-09-07 (session-306: AC28.2 TTS worker leak fixed via MKL fast-MM off + Known-Issues entry; TTS worker lifecycle REQ-28: lazy boot, connect pre-warm, idle unload/respawn, voice-state cache, post-synthesis compact).
> This document is the single source of truth for the audio pipeline. If the
> code and this document ever disagree, treat this as a bug and update both.
> All values below are verified against `backend/audio/voice_command.py`,
> `backend/iris_gateway.py`, `backend/agent/tts.py` and
> `backend/audio/tts_worker.py` (pre-REQ-28 sections last verified at commit
> `106a271e`; TTS lifecycle sections verified live 2026-09-07, Session 302).

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
│  Violawake       Energy-based    Parakeet GPU   Provider-agnostic  Pocket-TTS │
│  (custom ONNX    + silence       (sherpa-onnx   (agent card picks  (subprocess)│
│  head + OWW      detection       subprocess     the provider)                  │
│  backbone)                                                          │          │
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
| **ViolawakeWakeWordDetector** | `backend/voice/violawake_detector.py` | Custom ONNX wake head + OpenWakeWord backbone, 320-sample frames, CPU-first | Audio callback |
| **TTSManager (proxy)** | `backend/agent/tts.py` | Proxy to the Pocket-TTS subprocess worker; lazy at boot, pre-warms on WS connect, unloads worker after `IRIS_TTS_IDLE_TIMEOUT_S` quiet (default 600s), respawns on demand (singleflight); sends JSONL, yields audio | Proxy (main) + reaper daemon |
| **TTS Worker (subprocess)** | `backend/audio/tts_worker.py` | Pocket-TTS model + hash-guarded voice-state disk cache (`data/tts_voice_cache/`, 10.7s encode → ~0s load) + streaming synthesis + post-synthesis heap compact (gc → `_heapmin` → trim) in a SEPARATE PROCESS. Spawn env sets `MKL_DISABLE_FAST_MM=1` (operator override respected) — without it Intel MKL retains ~18MB per synthesis forever (see Known Issues, session-306) | Subprocess |
| **VoiceCommandHandler** | `backend/audio/voice_command.py` | VAD, recording, STT orchestration, cadence detection, activation beep | Multi-threaded (VAD + STT + beep) |
| **ParakeetTranscriber** | `backend/audio/voice_command.py` | sherpa-onnx Parakeet TDT 0.6B v3 int8 in a worker SUBPROCESS (`parakeet_sherpa_worker.py`, JSONL): lazy first-speech spawn (~2 s) + build (~4–13 s cold), CUDA default (`IRIS_PARAKEET_PROVIDER`), word timestamps | Spawner thread + reader thread (bounded round-trip) |
| **parakeet_sherpa** | `backend/audio/parakeet_sherpa.py` | Model-dir resolution, cuDNN DLL path (via torch bundle), recognizer factory with CPU fallback | Import-time only |
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
│  Violawake (custom ONNX head + OpenWakeWord backbone)    │
│                                                          │
│  - ARMED at backend startup (main.py lifespan calls      │
│    audio_engine.initialize_detector()) — NOT mid-session │
│  - Runs continuously on AudioEngine input stream AFTER   │
│    arming (see AUDIO DIAG "Wake word: READY")            │
│  - Listens for "Hey Iris" (custom ONNX model at          │
│    data/hey iris_237_1788045452.onnx)                    │
│  - On detection → main.py _on_wake_word_sync →           │
│    _on_wake_word_async fires voice_command_start to the  │
│    WS session for client "iris" (see Session Routing)    │
│  - AudioEngine half-duplex gate: _tts_active = True      │
│    drops incoming frames during TTS (echo avoidance)     │
└──────────────────────┬───────────────────────────────────┘
                        │ wake word detected
                        ▼
```

**Arming lifecycle (IMPORTANT — common "wake word not working" cause):**
- Violawake is initialized **once at backend startup**, inside the FastAPI
  lifespan, *before* `audio_engine.start()`:
  ```python
  # backend/main.py (lifespan)
  if audio_engine.initialize_detector():   # arms Violawake
      logger.info("[AUDIO DIAG] ... wake word detection active")
  audio_engine.start()                       # starts the 31 Hz audio callback
  ```
- Until that init completes, the 31 Hz audio callback logs
  `wake_detector_initialized=False. Wake word detection never started.` and drops
  frames. **The backend is READY in ~22 s (measured 2026-09-03; STT, TTS and
  Parakeet are all lazy — nothing heavy preloads at boot);
  saying "Hey Iris" during that window is silently dropped.** Wait for the
  `AUDIO DIAG ... Wake word: READY` line before testing the wake word.
- `engine.start()` does NOT arm Violawake on its own — only `initialize_detector()`
  does. Do not rely on `start_recording` / orb-click to arm it; it is armed at
  startup regardless of UI interaction.

**Configuration** (in `backend/audio/engine.py`):
```python
"activation_sound": "liquid-bubble-3000.wav",  # activation chime
```

#### Wake Word → Session Routing

When Violawake detects "Hey Iris", the audio thread fires the registered callback
(`engine.set_wake_word_callback`, wired in `main.py:372`). The routing is:

```
Violawake detects "Hey Iris"
  → engine._on_wake_word_detected(word)        [audio thread]
  → main.py _on_wake_word_sync(word)           [debounce + cooldown]
  → asyncio.run_coroutine_threadsafe(
        _on_wake_word_async(word), _main_event_loop)
  → _on_wake_word_async:
       session_id = ws_manager.get_session_id_for_client("iris")   # Priority 1
       if None: active_sessions = ws_manager.get_active_session_ids()  # Priority 2
       if None: session_id = "voice_headless"                       # Priority 3
     → gateway.handle_voice_message("voice_command_start", session_id, ...)
  → iris_gateway._handle_voice → voice_handler.start_recording()
```

- **Requires an active frontend WebSocket session for client `"iris"`**
  (the frontend connects to `ws://host:8090/ws/iris` in `useIRISWebSocket.ts`).
  If no browser is connected, the headless fallback (`voice_headless`) is used.
- **Cooldown**: `_WAKE_WORD_COOLDOWN_SEC` (in `main.py`) debounces repeated
  detections so one utterance doesn't open multiple recordings.
- The wake callback and the orb double-click / VOICE-label click all converge on
  the SAME `voice_command_start` → `_handle_voice` path (see Voice State Machine).


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
│  2. Try ParakeetTranscriber (sherpa worker GPU)          │
│     ├─ LAZY-LOADED ON FIRST WAKE WORD (start_recording)  │
│     │  — GPU engine gets a head start during the         │
│     │  utterance (~17-22s build overlaps VAD recording). │
│     │  No-op when already loaded (no thread churn).      │
│     ├─ If still loading, _transcribe_via_parakeet WAITS  │
│     │  (bounded 25s via wait_ready()) instead of bailing │
│     │  to whisper — Parakeet is the PRIMARY engine.      │
│     ├─ int8 transducer (encoder 622 MB), GPU-resident    │
│     ├─ JSONL base64 PCM → text + timestamps (90 s bound) │
│     ├─ Worker owns sole ORT: no clash w/ wake-word DLL   │
│     ├─ 20-min worker idle-exit reclaims VRAM (respawn)   │
│     └─ Returns "" on failure → falls back                │
│                                                          │
│  3. Fallback: faster-whisper (tiny/int8, ~40MB CPU)      │
│     ├─ WhisperModel('tiny', compute_type='int8')         │
│     ├─ _get_whisper uses a _whisper_loading FLAG (not a  │
│     │  lock held across the ~126s cold import) — the     │
│     │  +90s background warm-up never blocks a live turn. │
│     │  A concurrent caller waits up to 5s then returns   │
│     │  None (skips whisper) instead of hanging.          │
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

**Worker lifecycle (REQ-28, verified live 2026-09-07):** the worker does NOT
start with the backend. `TTSManager` boots with no subprocess
(`IRIS_TTS_EARLY_SPAWN=1` restores the old boot-time spawn); the first
frontend WS connect fires `prewarm()` (once per process, non-blocking), and
any synthesis path spawns on demand via `_ensure_worker` (300 s startup
budget). After `IRIS_TTS_IDLE_TIMEOUT_S` seconds with no terminal synthesis
event (default 600 s), the reaper daemon sends graceful `shutdown`, waits
10 s, kills if needed, and detaches — the next request respawns transparently
(singleflight via the existing locks; crash recovery unchanged). Measured
live: boot→no worker; connect→worker in ~7 s; first speech 54,720 samples in
1.22 s; idle 97 s → process gone; next request → ready in 6 s, 52,800 samples.
Floor effect: idle total 3350.7 → 1302.8 MB (−2047.9 MB returned, harness
measured). Voice-state cache: TOMV2 encode (10.7 s) runs once ever, then
`voice_state_<sha>.pt` (3.5 MB) loads in ~0 s. Post-synthesis compact runs
after every request (success or failure) and can never fail the synthesis.
Worker spawn env sets `MKL_DISABLE_FAST_MM=1` (session-306, AC28.2): without
it the worker grows ~25MB per synthesis, linear with no plateau (Intel MKL
fast-MM retains per-call scratch; invisible to all TTS logging, which only
reports speed/events). With it: ~7MB/synth residual CRT fragmentation, same
RTF (~1.9x), same audio. Pinned by `test_worker_spawn_disables_mkl_fast_mm`
(+ override test) — see Known Issues for the full story and the re-check
procedure.

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
│     │  Pocket-TTS streaming synthesis (SUBPROCESS)    │ │
│     │  - TTSManager proxy sends text to tts_worker.py │ │
│     │  - Worker (separate process) synthesizes →      │ │
│     │    streams base64 audio chunks back             │ │
│     │  - Proxy yields float32 PCM chunks              │ │
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
require a separate wake word or a second Violawake model. The wake word
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

**Violawake stays armed.** Only the heavy VAD/STT/TTS path is released; the
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
│   ├── Pocket-TTS synthesis via SUBPROCESS (tts_worker.py)
│   │   - TTSManager proxy sends text, reads base64 audio chunks
│   │   - Worker runs in a SEPARATE PROCESS (no GIL contention)
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
│     ├── ParakeetTranscriber → sherpa worker subprocess (JSONL)
│     │   └── OR _whisper.transcribe() — CPU fallback
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
It is a four-state machine with adaptive noise-floor calibration (retuned
live over 0.5 → 0.6 → **0.8**; see history below).

### Parameters (from `backend/audio/voice_command.py`)

```python
VAD_ENERGY_THRESHOLD: float = 0.006  # fallback floor when no frames yet
VAD_MIN_SPEECH_SEC: float = 0.3      # ignore blips shorter than this
VAD_SILENCE_SEC: float = 0.8         # base end-of-speech silence (live 2026-09-04: 0.5 cut mid-sentence pauses, 0.8 covers breaths)
VAD_SILENCE_SEC_MAX: float = 1.2     # hard cap on adaptive silence (long utterances)
VAD_MAX_DURATION_SEC: float = 30.0   # hard cap on recording length
VAD_POLL_INTERVAL_SEC: float = 0.015 # how often VAD loop checks for new frames
```

### Tuning history (why 0.8, not 1.2)

Session 155 set 1.2 for natural pauses; a later session moved 0.5 → 0.6;
commit `230ce06f` (live 2026-09-04) moved 0.5 → **0.8** because 0.5 cut
mid-sentence pauses, with 0.8 covering breaths. 1.2 survives as the adaptive
cap, not the base. Tests pin 0.8 / 0.3 / 1.2-max (`TestVADSilenceThreshold`).

### State Transitions

```
CALIBRATE
  │ first ~0.5s of frames sampled as ambient (median, RMS >= 0.1 excluded
  │ so beep echo can't poison it); constant drone from frame 0 becomes the
  │ floor and NEVER triggers speech (anti-false-trigger by design)
  ▼
PRE_SPEECH
  │ rms >= 3.0x floor (hysteresis; floor-adaptive, 0.006 fallback)
  │ sustained for VAD_MIN_SPEECH_SEC (0.3s)
  ▼
IN_SPEECH
  │ rms < 1.5x floor sustained for VAD_SILENCE_SEC (0.8s)
  │ (long utterances > 5s speech stretch the allowance up to 1.2s cap)
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
| IDLE | RECORDING | Wake word detected, orb double-click, or VOICE label click |
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

### Three Voice-Activation Triggers (must be visually identical)

All three paths converge on the SAME state machine and the SAME orb rendering,
so the listening animation (glow halo + cadence breathing) is identical
regardless of how listening started:

| Trigger | UI action | Code path |
|---------|-----------|-----------|
| Wake word | "Hey Iris" (Violawake, **armed at backend startup**) | Violawake callback → `main.py` `_on_wake_word_async` → `voice_command_start` |
| Double-click | double-click orb (any state) | `handleDoubleClick` → `startVoiceCommand` |
| VOICE label | click "↑↑ Voice" label (idle only) | `handleLabelClick('voice')` → `startVoiceCommand` |

> **Arming note:** the wake word is the ONLY trigger that does not require a prior
> UI interaction — Violawake is armed in the FastAPI lifespan (`main.py`) at backend
> startup, independent of the orb. The other two triggers *start a recording
> session*; the wake word *opens* the session by firing the same `voice_command_start`
> the others send. All three converge on `iris_gateway._handle_voice`.

- `startVoiceCommand` (in `useIRISWebSocket.ts`) optimistically sets
  `voiceState="listening"`, dispatches `iris:voice_state_change`, and sends
  `voice_command_start` over the WS. The backend handler
  `iris_gateway._handle_voice` (line 1863) treats `voice_command_start` from
  double-click OR wake word identically — it broadcasts `listening_state:
  listening` and streams `audio_envelope` phase `"listening"` (cadence envelope
  drives the orb breathing). `useCadenceDetection` + `OrbCanvas` glow refs are
  shared, so the data/cadence path is already consistent.
- **Orb prominence fix (2026-07-15):** `XurOrb.tsx` previously forced
  `orbRetreatScale = 0.85` / `orbOpacity = 0.85` whenever a wing was open —
  *including during listening* — so a click/double-click with a wing open
  breathed at reduced prominence versus the wake word (which runs from idle at
  full prominence). Now `orbRetreatScale` / `orbOpacity` only diminish when the
  orb is **idle** behind an open wing (`isWingsOpen && !isVoiceActive`); during
  any voice-active state the orb is full prominence in EVERY orb state
  (idle / chatview open / dashboard wing open), matching the wake word.
- The VOICE label stays **hidden** when wings are open (`labelsVisible =
  !isWingsOpen && !menuOpen`) — intended UX. Double-click still reaches the orb
  because the orb is at `zIndex: 100` while wings sit at `zIndex: 5–20` and
  never overlap the orb.
- Glow color is theme/brand-color driven (`getThemeConfig().glow.color`, default
  'aether' = cyan `hsl(190,100%,50%)`) and is identical for all three triggers.

---

## Memory Budget

LLM memory depends on the user's selected provider (see Phase 4). These are
the fixed audio-pipeline costs:

| Component | VRAM | RAM | When |
|-----------|------|-----|------|
| Parakeet sherpa int8 (GPU worker) | ~0.7–1 GB | ~50 MB (native lib) | Lazy-spawned on first speech; 20-min worker idle-exit reclaims VRAM |
| faster-whisper (int8) | 0 | ~40 MB | Fallback if parakeet fails |
| Violawake (ONNX + OWW) | 0 | ~50 MB | Always (wake word) |
| sherpa-onnx runtime | 0 | (included above) | No torch at STT runtime; cuDNN via torch bundle |
| Native C++ player | 0 | ~1 MB | During TTS playback |
| Pocket-TTS worker (subprocess) | 0 | **~2.05–2.3 GB commit** (~1.1 GB resident fresh, decaying toward ~0.3 GB over idle hours; 438 MB weights on disk) — live only; **0 at rest** (idle-unload, REQ-28). Spawn env MUST carry `MKL_DISABLE_FAST_MM=1` (else +25MB/synth leak, session-306) | On first speech after boot/connect; unloaded after quiet timeout |
| **Total (audio pipeline, parakeet, TTS live)** | **~1 GB** | **~2.5 GB commit** | measured 2026-09-07: backend 1.30 + worker 2.05 GB |
| **Total (audio pipeline, parakeet, TTS idle)** | **~1 GB** | **~1.3 GB commit** | measured 2026-09-07 post-unload (was 3.35–3.59 GB before REQ-28) |
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
| TTS subprocess crash | TTSManager proxy restarts the worker; next synthesis retries |
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
| .env PICOVOICE_ACCESS_KEY missing (Porcupine era) | Legacy row: Violawake needs no key and runs fully offline; kept for history |
| Parakeet hallucination after barge-in | Fixed: RMS guard (`< 1e-4`) skips Parakeet on near-silence |
| Parakeet still loading on first utterance | Fixed (2026-09-03): lazy-load on first wake word; `_transcribe_via_parakeet` waits (bounded 25s) for the GPU engine instead of bailing to whisper |
| faster-whisper cold import (~126s) blocks a live turn | Fixed (2026-09-03): `_get_whisper` uses a `_whisper_loading` flag, not a lock held across the import — the +90s warm-up never blocks a live transcription thread (waits up to 5s then skips whisper) |
| TTS worker dies mid-synthesis on long text | **ROOT CAUSE FOUND + GUARDED (2026-09-07; was OPEN since 2026-09-03)**: the documented deaths match the stderr-pipe backpressure incident signature exactly (same date, ~853-char synthesis, 30 s of silence, manager kills a *healthy* worker) — fixed since `3b09f929` added the stderr drain thread. Reproductions now SURVIVE: 2500 chars → 61.7 s, 3.0M samples, alive; 7500 chars → 196.5 s, 9.2M samples, alive. Residual measured risk (not fragility): one synthesis retains ~0.15–0.19 MB/char in native arenas (+1082 MB for 7500 chars), so ~10k+ char single requests could OOM — mitigated by the `_MAX_SINGLE_SYNTH_CHARS=2000` sequential-split guard in `synthesize_stream` (identical audio, compact runs between pieces; pinned by `test_tts_lifecycle.py` split tests). Remaining sub-item (untouched): reset `_tts_active` even when the producer is stuck — still open. The 30 s chunk-gap timeout is intentionally NOT shortened (healthy chunks stream continuously; only true silence trips it). |

---

## Test Coverage

### Test Files

- `backend/tests/test_voice_pipeline.py` — 88 unit/integration tests + 3 new regression tests (91 total)
- `backend/tests/test_latency_metrics.py` — 8 latency metric tests
- `backend/tests/test_chunk_callback_nonstreaming.py` — 6 chunk callback / DER path tests
- `backend/tests/test_barge_in.py` — 40+ tests
- `backend/tests/test_conversation_kernel.py` — 12 tests
- `backend/tests/test_voice_pipeline.py::TestStopListening` — 21 tests (phrase match incl. fillers/negatives, pipeline interception skips LLM/TTS, auto-relisten suppression, sleep entry, wake-word re-entry)
- `backend/tests/contract/test_narration_broadcast.py` — 4 tests (narration speaking→idle order, serialization via the lane scheduler's single worker (REQ-7 AC7.1; the narration lock is removed), no-broadcast unwired, gateway wires broadcaster). Session-309 deduplicated the stale root twin into this file.
- `backend/tests/unit/test_tts_lifecycle.py` — 16 tests (REQ-28: lazy boot, once-per-process prewarm, unload decision matrix, graceful reap + active sparing, respawn after reap, voice-state cache hit, post-synthesis compact hook, 2000-char split guard, worker spawn sets `MKL_DISABLE_FAST_MM=1` + respects operator override)
- `backend/tests/contract/test_tts_subprocess_contract.py` — worker JSONL protocol (ping/synthesize/shutdown), float32 chunks at 24 kHz, crash recovery (spawns a REAL worker)
- `backend/tests/unit/test_tts_pocket_load.py` — model-load contract; 1 test stale at HEAD (`test_tts_manager_uses_language_not_variant` pins the pre-split in-process loader — reported, not modified)

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

### Parakeet silently ran on CPU for ~9 days — bad cuDNN path + silent fallback (fixed 2026-09-12)

**SYMPTOM**: the sherpa worker spawned a ~750 MB–1.3 GB `python.exe`
(`backend.audio.parakeet_sherpa_worker`) on the first wake word and built the
recognizer **on CPU**, while this document (line 70) and
`HANDOFF_AUDIO_PIPELINE.md:261` both state Parakeet is GPU. The operator's
"my Parakeet was always on my GPU" was correct for the **old transformers
worker** (`parakeet_worker.py`, hardcoded `device_map="cuda:0"`) and had been
false since the 2026-09-03 sherpa swap.

**ROOT CAUSE (two defects, one silent)**:
1. `backend/audio/parakeet_sherpa.py:_torch_lib_dir()` returned
   `<site-packages>/lib` instead of `<site-packages>/torch/lib`. torch bundles
   cuDNN 9 (`cudnn64_9.dll`) in `torch/lib`, so the directory it put on the
   DLL search path held no cuDNN. ORT then failed
   `Error loading ... cudnn64_9.dll ... missing` and `build_recognizer()`
   caught it and retried `cpu`.
2. `PROVIDER` defaulted to `"cpu"` and `IRIS_PARAKEET_PROVIDER` was set
   **nowhere** (verified: unset at Machine, User, and Process level), so the
   GPU path was never even requested.
3. The fallback logged only `provider 'cuda' failed (...) — trying next`,
   which reads as a routine retry. Nothing distinguished "GPU built" from
   "silently downgraded to CPU".

**EVIDENCE**: every `recognizer built (provider=...)` line in the log history
from 2026-09-04 through 2026-09-12 10:15 reads **`provider=cpu`** (13 builds).
The first `provider=cuda` build is 2026-09-12 10:34, after the fix.

**FIX**:
- `_torch_lib_dir()` now joins `os.path.dirname(_spec.origin)` + `lib`
  (i.e. `<torch>/lib`) — the directory that actually contains the cuDNN DLLs.
- `.env` now sets `IRIS_PARAKEET_PROVIDER=cuda`, matching the documented
  operator decision.
- `build_recognizer()` logs a loud `FALLBACK: requested provider=... but built
  provider=...` warning whenever the built provider differs from the requested
  one, so a downgrade can never be quiet again.

**VERIFIED LIVE (2026-09-12)**: a real `voice_command_start` built
`recognizer built (provider=cuda)` in ~53 s, and `nvidia-smi` listed the
worker PID in its compute-apps set with GPU memory rising 1301 → 1667 MiB.
Honest limit: per-process VRAM attribution reads `[Insufficient Permissions]`
on this box, so the GPU evidence is the explicit build line + the PID in the
compute-apps list, not a clean per-process number.

**PINNED**: `backend/tests/contract/test_parakeet_provider_contract.py`
(CT-PP1..CT-PP4) — proven-failable: reverting the fix fails 2 of the 5
assertions (the path shape and the loud fallback).

**LESSON**: a fallback that keeps the feature working is not automatically a
safe fallback — if it can silently move work off the hardware the user chose,
it must be loud, and the chosen provider must be pinned by a test.

### Wake Word "not working after restart" — startup-window timing (documented 2026-07-17)

**SYMPTOM**: After a backend (re)start, saying "Hey Iris" does nothing — the orb
doesn't react and no recording starts.

**ROOT CAUSE (timing, not a code regression)**: Violawake is armed in the FastAPI
lifespan via `audio_engine.initialize_detector()` (`main.py`), which runs *before*
`audio_engine.start()`. But Violawake arms inside the FastAPI lifespan: if
"Hey Iris" is spoken before `initialize_detector()` returns, it is silently
dropped. The backend itself is READY in ~22 s (measured 2026-09-03), so this
window is now seconds, not minutes. Until `initialize_detector()` returns,
logs `wake_detector_initialized=False. Wake word detection never started.` and drops
frames. If "Hey Iris" is spoken during that load window, it is silently dropped. The
`AUDIO DIAG ... Wake word: READY` line marks the point Violawake is live.

**VERIFIED**: The current backend startup log shows
`[AUDIO DIAG] ... Wake word: READY | Pipeline: RUNNING | wake word detection active`
— so the wake word IS armed and functional once the backend has finished loading.

**RESOLUTION / guidance**:
- Wait for the `AUDIO DIAG ... Wake word: READY` line (or ~30 s after backend start)
  before testing the wake word.
- The wake word does NOT require any orb click or UI interaction to arm — it is armed
  at startup. (The earlier belief that it needed an orb double-click was incorrect;
  that only *starts a recording session*, which the wake word also does via its own
  callback.)
- Requires an active frontend WS session for client `"iris"` (the frontend connects
  to `ws://host:8090/ws/iris`); without a connected browser the headless fallback
  (`voice_headless`) is used.
- See [Phase 1: Wake Word Detection → Arming lifecycle](#phase-1-wake-word-detection)
  and [Wake Word → Session Routing](#wake-word--session-routing) for the full path.

### Session 158 (2026-07-15) — Orb Listening Animation Consistency (double-click + VOICE label == wake word)

**RESOLVED**:
- Requirement: the orb's listening animation (glow halo + cadence breathing)
  must be IDENTICAL for the three voice-activation triggers — "Hey Iris" wake
  word, double-click orb, and VOICE label click — in EVERY orb state (idle,
  chatview open, dashboard wing open). The wake word is the proven-consistent
  reference standard.
- Root cause of the inconsistency: `XurOrb.tsx` forced `orbRetreatScale = 0.85`
  and `orbOpacity = 0.85` whenever `isWingsOpen` — *including during
  listening/speaking* — so a click/double-click with a wing open breathed at
  reduced prominence versus the wake word (which runs from idle at full
  prominence). The data layer was already shared (backend
  `iris_gateway._handle_voice` line 1863 treats `voice_command_start` from
  double-click OR wake word identically; `useCadenceDetection` + `OrbCanvas`
  glow refs shared), so only the visual prominence diverged.
- Fix: `orbRetreatScale` / `orbOpacity` now only diminish when the orb is
  **idle** behind an open wing (`isWingsOpen && !isVoiceActive`). During any
  voice-active state the orb is full prominence regardless of wing state, so
  all three triggers render the same listening animation. VOICE label stays
  hidden when wings open (intended UX); double-click still reaches the orb at
  `zIndex: 100` (wings at `zIndex: 5–20`, never overlap).
- Verification (live, 2026-07-15):
  - **Backend reaction**: a WebSocket client sent `voice_command_start` to
    `ws://localhost:8090/ws/<client_id>` and received `listening_state:
    listening` immediately, then `audio_envelope` phase `"listening"` with a
    rising cadence envelope (0.0 → 0.75) — the exact signal that drives orb
    breathing. This is the shared handler for both click/double-click triggers.
  - **Orb visual**: drove the UI in a browser — double-click orb ×2 and VOICE
    label click ×2. Screenshots confirm idle = calm dot (no halo); all four
    listening shots show the identical large glowing/breathing halo,
    consistent regardless of trigger. Glow color is theme-driven (cyan/teal for
    the default 'aether' theme, RGB ≈ 21,63,77), identical across triggers.
  - Each trigger was verified twice, satisfying the "verify each trigger twice"
    protocol (orb change + backend reaction).

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
  speech text** (no separate wake word / Violawake model). Phrases: "stop
  listening", "go to sleep", "that's all", "pause listening", etc. (fillers
  like "hey iris" / "okay" stripped first via `_normalize_for_sleep`).
- `iris_gateway._sleeping_sessions: set` tracks asleep sessions.
  `_enter_sleep_mode()` adds the session, drops conversation mode, calls
  `voice_handler.cancel_recording()`, and broadcasts `listening_state: idle`.
  Violawake stays armed — a later "Hey Iris" re-opens the session.
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

### Session 286 (2026-09-03) — Parakeet STT engine swap (transformers → sherpa-onnx, GPU)

**RESOLVED** (the 8-minute cold STT):
- The transformers subprocess worker took ~500 s cold (torch import chain +
  723-tensor Python dispatch on HDD) before Parakeet transcribed anything; the
  faster-whisper fallback was itself import-bound (`import ctranslate2` = 126 s
  cold). Prior "17 s warm" figures are warm-page-cache-only.
- `ParakeetTranscriber` (`backend/audio/voice_command.py`) reimplemented on the
  sherpa-onnx native runtime (int8 v3 transducer, `IRIS_PARAKEET_PROVIDER`
  default `cuda` with CPU fallback) inside the same class shell: same lazy
  first-speech build, same `_loading`/`_loaded`/`_load_error` flags, same
  `parakeet*` latency strings, same 20-min idle VRAM release, decode bounded by
  `TRANSCRIBE_TIMEOUT_SEC`. New factory module `backend/audio/parakeet_sherpa.py`;
  `sherpa-onnx` pinned in `requirements.txt`. Word timestamps on
  `last_timestamps` (reserved for long-form video transcription).
- Measured (Hey Iris wav, RTX 3070): import 1–2.6 s, ready 12–22 s cold,
  "Hey Iris" 0.3 s warm CUDA / 0.16 s CPU, idle backend 0.39 GB (nothing STT
  loads at boot). 32 tests pass; 5 failures byte-identical to pre-change
  baseline (stale transformers seam + gateway drift — reported, not reconciled);
  the swap healed 3 stale `_load_model_worker` tests.
- Rejected with evidence: official v3 GGUF via llama-server (llama.cpp has no
  Parakeet support — needs parakeet.cpp/transcribe.cpp/sherpa instead),
  community fp16 export under CUDA EP (transcribes garbage; correct on CPU),
  TensorRT (no transducer support), a new sidecar server (transcriber already
  provides the isolation; a port only adds ops surface).
- Dormant on purpose: `parakeet_worker.py` stays on disk because
  `test_memory_optimization_contract.py` pins its source (deleting it needs a
  spec change first); `parakeet_service.py` (:8765) untouched (separate service).
  Deleted data only: transformers fp16 cache, rejected fp16 export, install
  tarball (~2.9 GB reclaimed). Model lives at
  `data/models/parakeet-sherpa/...v3-int8/`.
- TTS double-click warm-up (`iris_gateway.py` `voice_command_start` mirrors the
  wake-word warm-up) verified live in the backend log same session.

### Session 286b (2026-09-03) — Worker subprocess isolation + cold-start honesty

**RESOLVED** (two live-session failures the clean-room pilots missed):
- The in-process sherpa engine failed in production: the backend preloads PyPI
  `onnxruntime` for the wake-word backbone, and Windows binds the sherpa CUDA
  provider against the already-loaded incompatible build (plus the env carries
  BOTH `onnxruntime` 1.25 and `onnxruntime-gpu` 1.27 overwriting each other).
  Pilots never saw it — they ran in processes without the preloaded ORT.
- The engine now runs in a dedicated worker SUBPROCESS
  (`backend/audio/parakeet_sherpa_worker.py`, JSONL stdin/stdout, torch never
  imported — cuDNN located by path probe, parent prepends it to PATH at spawn).
  The worker owns the only ORT in its process, so no package upgrade can
  re-break GPU STT. Same public surface (`_ensure_loaded`, flags, `parakeet*`
  latency strings, 20-min idle-exit) — pipeline and mocked tests unchanged.
- Cold first-speech watchdog ERROR: `import ctranslate2` costs ~126 s on HDD
  *on the transcription thread* → 60 s watchdog → orb ERROR. faster-whisper
  now warms in background 90 s after boot (`main.py` lifespan); first
  transcription is instant thereafter. The old "~1–2 s" comment corrected.
- Backend file logging unified: EVERY launcher (manager, direct,
  Tauri sidecar) now writes `.iris-logs/backend-<ts>-pid<PID>.log` in-process
  (`backend/core/logging_config.py`); pid-stamped so concurrent instances
  never interleave. `IRIS_LOG_DIR` still overrides the directory.

**Lesson recorded**: component benchmarks are not system verification — the
process environment (preloaded modules, cold disk, real audio) IS part of the
system under test. Pilots must run backend-like from now on.

### Session 302 (2026-09-07) — TTS lifecycle rework + leak verdict (REQ-28)

> AMENDED session-306: the "flat, retained arenas not a leak" verdict below
> was overturned by deeper probing (4 syntheses are not enough to see a
> +25MB/synth slope through ±30MB noise — 30 syntheses showed it linear, no
> plateau). See "Session 306 — TTS worker memory leak (Intel MKL fast-MM)"
> for the corrected root cause, fix, and guards. The lifecycle mechanics in
> this section (lazy/prewarm/unload/cache/compact) stand as written.

**RESOLVED** (the 2.3 GB idle worker):
- Leak probe (own worker, 3 syntheses + 60 s idle): 2307.5 → 2275.5 / 2304.2 /
  2277.5 → 2277.4 MB — flat within ±30 MB noise. Verdict: **retained arenas,
  not a leak** (no per-use growth; freed native memory stays committed).
- Lifecycle now: lazy at boot (`IRIS_TTS_EARLY_SPAWN=1` restores old spawn),
  pre-warm on WS connect (`main.py` endpoint, non-blocking, once per process),
  idle unload after `IRIS_TTS_IDLE_TIMEOUT_S` (default 600 s, graceful
  `shutdown` → 10 s wait → kill), transparent respawn on next synthesis.
  All five transitions proven live against the real backend (see Phase 5).
- Voice-state disk cache (`data/tts_voice_cache/voice_state_<sha>.pt`, 3.5 MB):
  10.7 s TOMV2 encode → ~0 s load; respawn ready in 6 s (was ~19 s+).
- Post-synthesis compact in the worker after every request: `gc.collect()` →
  ucrt `_heapmin` decommit → working-set trim. Best-effort, can never fail
  a completed synthesis.
- Doc honesty: `tts.py` claimed "~100 MB RAM" (weights-only figure) for a
  2.3 GB process — corrected to measured commit/resident figures.
- `test_tts_pocket_load` repointed at the worker's `_load_model` (same
  language-not-variant requirement, correct address — was pinning the
  pre-split in-process proxy).

### Session 306 (2026-09-07) — TTS worker memory leak, fixed (Intel MKL fast-MM)

**SYMPTOM**: TTS worker private bytes grew ~25MB per synthesis, linear over
30 syntheses (+745MB), no plateau — two independent workers reproduced it.
The old Session-302 probe (4 syntheses) read it as flat noise.

**WHY NO LOG CAUGHT IT (blind spot, read this first)**: every line the TTS
stack logs describes *speed and events* — synthesis time, real-time factor,
chunks, ready/reap transitions. All of those looked perfect (RTF stayed
~1.9x). Nothing anywhere in the pipeline logs *native memory*, and Python's
garbage collector cannot see the hoard (below). A leak that costs speed
would have paged us; a leak that costs only bytes is silent. Any future
native-memory suspicion must be answered with private-bytes measurement
(`scripts/measure_memory.py` pattern), never with log inspection.

**ROOT CAUSE**: Intel MKL (the math library torch uses for CPU number
crunching) runs its own private memory manager that keeps per-call scratch
"in case it's needed again" — and never gives it back. Each sentence filed
~18MB into that private cabinet. Python-side forensics proved the negative:
threads flat at 1, Python object count flat, shared voice state flat at 3MB,
`copy_state=False` corrupts audio (the per-call deepcopy is load-bearing —
never touch it), torch profiler names only already-freed transients,
single-threaded run changes nothing, KV-cache sizing is proportional to text.
The ~19MB of per-call torch temporaries is freed correctly; MKL kept its cut.

**FIX** (`backend/agent/tts.py`, worker spawn env — 12 lines, zero behavior
change): `MKL_DISABLE_FAST_MM=1` (operator override respected; ignored on
non-MKL builds). MKL then allocates through plain malloc so freed blocks are
reused. Measured through the real spawn path: slope 25 → 7MB/synth, warm
first-audio still 0.2s, same voice, same RTF. Pinned by
`test_worker_spawn_disables_mkl_fast_mm` (+ override test) in
`test_tts_lifecycle.py` — deleting the flag fails the suite.

**RESIDUAL (known, bounded, not silently dropped)**: ~7MB/synth linear
through 40 syntheses — CRT-heap fragmentation from torch transient churn,
no code retainer, no plateau. No fix exists that doesn't trade something
away (periodic respawn costs latency churn, fewer threads costs speed, a
custom allocator is platform-fragile). Bounded in practice by the existing
600 s idle-unload. AC28.2's literal ≤50MB/10 gate stays red (+75/10);
revisit only with a library-side allocator fix or an accepted recycle design.

**RE-CHECK PROCEDURE (if memory suspicion returns)**: 1) sample worker
private bytes across ≥10 real syntheses (first-synth arena setup excluded
from slope math); 2) compare threads / gc-object count / shared-state bytes
across the run — if all flat, suspect native allocator, not code; 3) test
`MKL_DISABLE_FAST_MM` and thread-count variants in-process before touching
any call path; 4) never "fix" by buffering streaming calls (regresses
first-audio latency) or by weakening the gate.

### Session 302b (2026-09-07) — test-harness reconciliation (no production change)

**RESOLVED** — pre-existing reds triaged, harness repaired, assertions intact:
- VAD drift: `VAD_SILENCE_SEC` 0.8 (live-tuned `230ce06f`) vs tests/doc
  pinning 0.6/1.2, plus the loop's CALIBRATE mechanics the old stimulus
  never fed. Tests re-pinned to 0.8/0.3/1.2-max with cited evidence; frames
  tests now lead with quiet calibration; new drone test pins the
  calibration floor (constant noise never triggers). Doc §VAD rewritten.
- Mock drift: `test_voice_pipeline` gateway mock + `test_latency_metrics`
  gateways gained the `_voice_handler` / `_active_conversation_id` attrs
  the real `__init__` sets; parakeet mock fixed to the failed branch
  (`_loading=False` + `_load_error`, the path the test names — a bare
  MagicMock is truthy for `_loading` and took the wrong branch).
- Global pollution: both `test_speak_tool.py` files save/restore
  `agent_kernel._agent_kernel_instances` around each test — this alone
  healed the switch_conversation + voice_command contract failures (their
  logic was fine; phantom `_FakeKernel`s were the cause).
- `test_tts_pocket_load` repointed at the worker's `_load_model` (same
  language-not-variant requirement, correct address).
- Audio sweep after fixes: **250 passed, 0 failed** (integration
  voice file excluded — needs a physical mic; hangs headless regardless
  of code).
- Long-text repro (2500 chars, own worker): 61.7 s → 3,019,200 samples,
  worker alive — the "dies on long text" OPEN row did NOT reproduce;
  commit +477 MB retained on the long job (short-job deltas remain flat).
  Row left OPEN pending a second reproduction, not closed on one datapoint.

---

**END OF DOCUMENT** — If you find a discrepancy between this document and
the code, either fix the code to match the doc, or update the doc to match
the code. Never let them diverge silently.
