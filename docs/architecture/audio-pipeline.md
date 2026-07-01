# IRIS Voice — Full Audio Pipeline Architecture

> Last updated: 2026-07-01 — after embedding parakeet, fixing TTS double-play, word highlight sync, and voice state stuck fixes.

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
│   Porcupine       Energy-based    Parakeet GPU     LM Studio     Pocket-TTS   │
│   (native)        + silence       (in-process)     (remote)      (streaming)  │
│                   detection       or Whisper                                               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

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
│    ├─ VAD_SILENCE_SEC = 0.8s → end of utterance          │
│    └─ VAD_MAX_DURATION_SEC = 30s (hard cap)              │
│  - Broadcasts audio_envelope WS events during recording  │
│    { rms, cadence, phase: "listening" }                  │
│  - CadenceDetector.process() → spectral flux envelope    │
│    (tracks speech rhythm for orb breathing)              │
└──────────────────────┬───────────────────────────────────┘
                       │ VAD detects end-of-speech
                       ▼
```

### Phase 3: Speech-to-Text (STT)
```
┌──────────────────────────────────────────────────────────┐
│  VoiceCommandHandler._run_transcription()                │
│                                                          │
│  1. Try ParakeetTranscriber (GPU, in-process)            │
│     ├─ Lazy-loads nvidia/parakeet-tdt-0.6b-v3 on        │
│     │  first call (~1.2GB VRAM, fp16 on RTX 3070)       │
│     ├─ float32 PCM → int16 → processor → GPU inference   │
│     ├─ batch_decode() → text                             │
│     └─ Returns "" on failure → falls back                │
│                                                          │
│  2. Fallback: faster-whisper (tiny/int8, ~40MB CPU)      │
│     ├─ WhisperModel('tiny', compute_type='int8')         │
│     ├─ transcribe(wav_buffer, beam_size=1)               │
│     └─ ~40MB RAM, no VRAM conflict                       │
│                                                          │
│  → _on_command_result callback                           │
└──────────────────────┬───────────────────────────────────┘
                       │ transcribed text
                       ▼
```

### Phase 4: LLM Processing
```
┌──────────────────────────────────────────────────────────┐
│  iris_gateway._on_voice_result()                         │
│                                                          │
│  - Sends transcribed text to LLM API                     │
│  - Receives streaming response → sentence queue          │
│  - Each sentence pushed to TTS queue                     │
│  - chat_chunk WS events → frontend for progressive text  │
│  - chat_message WS event → final assembled response      │
│  - listening_state WS: "processing" → "speaking"         │
└──────────────────────┬───────────────────────────────────┘
                       │ sentence from LLM
                       ▼
```

### Phase 5: Text-to-Speech (TTS) — Streaming
```
┌──────────────────────────────────────────────────────────┐
│  iris_gateway._speak_response()                          │
│                                                          │
│  Producer thread: _producer()                            │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Pocket-TTS streaming synthesis                    │  │
│  │  - Synthesizes sentence → float32 PCM chunks       │  │
│  │  - Pushes chunks to native player OR audio_queue   │  │
│  │  - Broadcasts audio_envelope {rms, phase:"speaking"}│  │
│  │  - Tracks total samples for cadence timing         │  │
│  │  - _playback_event.set() on FIRST chunk pushed     │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  Consumer (main path):                                   │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Native C++ ring-buffer player (sub-5ms latency)   │  │
│  │  OR sounddevice (PortAudio) fallback               │  │
│  │  - Normalizes amplitude to 0.85 peak               │  │
│  │  - playback_started_event passed to play_stream()  │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  Word-highlight thread: _broadcast_words()               │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Waits on _playback_event (NOT hardcoded sleep)    │  │
│  │  + 3ms buffer for device latency                   │  │
│  │  - Fires tts_word WS events at character-          │  │
│  │    proportional timing                             │  │
│  │  - { word_index, total_words, is_final }           │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  Cadence thread (TTS breathing):                         │
│  ┌────────────────────────────────────────────────────┐  │
│  │  - Uses RMS from producer as cadence envelope      │  │
│  │  - Sends audio_envelope {rms, cadence, "speaking"} │  │
│  │  - ~10 Hz broadcast rate                           │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  finally block:                                          │
│  - On SUCCESS: conversation mode → auto-relisten        │
│                single-shot → send idle                   │
│  - On ERROR: send idle (unsticks orb from "speaking")   │
└──────────────────────────────────────────────────────────┘
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
│  └─ Listens for iris:text_response → renders response    │
│                                                          │
│  OrbCanvas.tsx                                           │
│  ├─ Canvas-based 3D orb rendering                        │
│  ├─ breathMode/breathLevel props → animation driver      │
│  └─ Smooth interpolation between states                  │
└──────────────────────────────────────────────────────────┘
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
├── Word-highlight Thread (_broadcast_words)
│   ├── _playback_event.wait(timeout=2.0)
│   ├── +3ms buffer for device latency
│   └── Send tts_word WS events at char-proportional timing
│
├── Cadence Thread (TTS breathing)
│   ├── Uses RMS from producer
│   └── Broadcasts audio_envelope {phase:"speaking"}
│
└── VoiceCommandHandler (recording phase)
    ├── _capture_frame() — AudioEngine frame listener
    ├── VAD loop thread — energy-based silence detection
    ├── ParakeetTranscriber.transcribe() — GPU inference
    │   └── OR _whisper.transcribe() — CPU fallback
    └── CadenceDetector.process() — spectral flux
```

---

## WebSocket Events (Backend → Frontend)

| Event | Payload | When | Purpose |
|-------|---------|------|---------|
| `listening_state` | `{ state: "idle" \| "listening" \| "speaking" \| "processing" }` | State transitions | Orb animation mode |
| `audio_envelope` | `{ rms, cadence, phase }` | During recording + playback (~10 Hz) | Orb breathing/speaking |
| `audio_level` | `{ level }` | During recording (legacy) | Old IrisOrb compatibility |
| `tts_word` | `{ word_index, total_words, is_final }` | During TTS playback | Word highlighting in chat |
| `chat_chunk` | `{ chunk }` | LLM streaming | Progressive text rendering |
| `chat_message` | `{ content, turn_id, thinking }` | LLM complete | Final response display |

---

## Component Responsibilities

| Component | File | Role |
|-----------|------|------|
| **AudioEngine** | `audio/engine.py` | Manages mic input stream, frame listeners, half-duplex gate |
| **AudioPipeline** | `audio/pipeline.py` | Audio I/O streams, native C++ player, device enumeration |
| **VoiceCommandHandler** | `audio/voice_command.py` | VAD, recording, STT orchestration, cadence detection |
| **ParakeetTranscriber** | `audio/voice_command.py` | In-process GPU ASR (lazy-loaded, ~1.2GB VRAM) |
| **CadenceDetector** | `audio/cadence_detector.py` | Spectral flux → 0-1 cadence envelope |
| **iris_gateway** | `iris_gateway.py` | TTS orchestration, WS events, word timing, state management |
| **useIRISWebSocket** | `hooks/useIRISWebSocket.ts` | WS event dispatch → React state |
| **XurOrb** | `components/iris/XurOrb.tsx` | Orb component, voice state rendering |
| **OrbCanvas** | `components/iris/orb/OrbCanvas.tsx` | Canvas-based 3D orb, breath animations |
| **chat-view** | `components/chat-view.tsx` | Word highlighting, response rendering |

---

## Key Sync Mechanisms

### 1. Word Highlight ↔ TTS Playback
```
_playback_event (threading.Event)
  ├─ Set by: _producer() on first push_chunk() to native player
  │           OR play_stream() before sd.play()
  └─ Waited by: _broadcast_words() thread
                 → fires tts_word events starting from device start time
```

### 2. Echo Avoidance (Half-Duplex)
```
engine.set_tts_active(True/False)
  ├─ True: input callback drops all frames (mic muted during playback)
  └─ False: input callback resumes forwarding to STT + frame listeners
```

### 3. Voice State Machine
```
IDLE → (wake word / double-click) → RECORDING → PROCESSING → SPEAKING → IDLE
  ↑                                                                          │
  └──────────────────── conversation mode: auto-relisten ────────────────────┘

Error path: any state → _wrap_tts_streaming error → send idle (unsticks orb)
```

---

## Memory Budget

| Component | VRAM | RAM | When |
|-----------|------|-----|------|
| Parakeet (fp16) | ~1.2 GB | ~200 MB | Lazy-loaded on first STT |
| faster-whisper (int8) | 0 | ~40 MB | Fallback if parakeet fails |
| Porcupine | 0 | ~5 MB | Always (wake word) |
| Torch + transformers | 0 | ~200 MB | Loaded with parakeet |
| Native C++ player | 0 | ~1 MB | During TTS playback |
| **Total (parakeet active)** | **~1.2 GB** | **~450 MB** | — |
| **Total (whisper fallback)** | **0** | **~95 MB** | — |

---

## Error Recovery

| Failure | Recovery |
|---------|----------|
| Parakeet GPU OOM | Falls back to faster-whisper (CPU) |
| Parakeet load error | Falls back to faster-whisper, logs error once |
| TTS synthesis error | `_succeeded=False` → sends idle state (unsticks orb) |
| Native player fails | Falls back to sounddevice (PortAudio) |
| WebSocket disconnect | Frontend reconnects, state resets to idle |
| LM Studio unreachable | Shows fallback model list (expected when not using LM Studio) |
| PortAudio init slow | Lazy-loaded on first audio use, not at startup |
