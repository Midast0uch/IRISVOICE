# Audio Pipeline Handoff — 2026-06-29

## Status Overview

| Component | Status | Last Fix |
|-----------|--------|----------|
| Wake word detection | ✅ Working | Async double-suppression fixed |
| Activation sound | ✅ Working (no static) | Native C++ player disabled, uses `sd.play()` |
| Microphone capture | ✅ Working | Half-duplex gate removed |
| VAD (auto-stop) | ✅ Working | `auto_stop=True` for all triggers |
| Parakeet ASR (GPU) | ✅ Working | HuggingFace transformers, port 8765 |
| STT → ChatView | ✅ Working | Single-click orb now ENDS (was cancel) |
| LLM response | ✅ Working | Text + highlighted words |
| **TTS audio playback** | ❌ **BROKEN** | **See below** |
| TTS → Orb cadence | ❌ **BROKEN** | Depends on TTS working |
| Auto-relisten after TTS | ❌ **BROKEN** | Depends on TTS working |
| Test Output button | ✅ Wired | 440Hz tone on selected device |
| Test Input button | ✅ Wired | Mic level check |
| Cerebras Gemma 4 31B | ✅ Added | Frontend + backend |

## System Architecture

### Services (all running on same Windows machine)

```
┌─────────────┐  port 8090  ┌──────────────┐  port 8765  ┌──────────────┐
│  Frontend   │◄───────────►│  FastAPI App  │◄───────────►│  Parakeet    │
│  Next.js    │  WS + REST  │  (main.py)   │  REST/WS    │  TDT GPU ASR │
│  :3000      │              │  iris_gateway │              │  :8765       │
└─────────────┘              └──────┬───────┘              └──────────────┘
                                     │
                           ┌─────────▼─────────┐
                           │  Audio Pipeline   │
                           │  (pipeline.py)    │
                           │                   │
                           │  sd.play()        │
                           │  (native disabled)│
                           └───────────────────┘
```

### Audio Pipeline Components

| File | Role |
|------|------|
| `backend/audio/engine.py` | AudioEngine — manages input/output devices, Porcupine wake word, VAD gate |
| `backend/audio/pipeline.py` | AudioPipeline — `play_audio()`, `play_stream()`, `start_listening()` |
| `backend/audio/voice_command.py` | VoiceCommand — recording, VAD, STT orchestration |
| `backend/audio/parakeet_service.py` | Standalone FastAPI ASR service (HuggingFace) |
| `backend/iris_gateway.py` | Message router — TTS playback, conversation mode |
| `backend/agent/tts.py` | TTSManager — Pocket-TTS wrapper, lazy model load |
| `backend/api/chat.py` | Fire-and-forget TTS (`_fire_tts_background`) |

## Audio Pipeline Flow (Expected)

### Full conversational cycle (what SHOULD happen):

```
Step 1: WAKE WORD
  User says "hey iris"
  PorcupineDetector → engine callbacks → _on_wake_word_sync
  → _on_wake_word_async → iris_gateway._handle_voice()
  → voice_command_start → recording starts
  → _play_activation_beep() (liquid-bubble-3000.wav via sd.play)
  → broadcast "listening_state: listening" to frontend
  → XurOrb: flash overlay (600ms), scale 1.15, haze effect

Step 2: SPEECH CAPTURE (WORKS)
  Mic frames → _capture_frame() → _raw_frames[]
  VAD monitors RMS > 0.004 threshold
  Frontend audioLevel indicator shows in chat textarea

Step 3: VAD AUTO-STOP (WORKS)
  User stops speaking → 1 second silence detected
  → _stop_event.set() → _run_transcription finishes
  → audio concatenated → Parakeet HTTP POST to :8765/transcribe
  → text response → _on_voice_result callback

Step 4: STT → CHATVIEW (WORKS)
  _process_voice_transcription() → sends transcript to LLM
  → chunk_callback sends text chunks via WS
  → frontend shows transcript + highlights words (200ms tick)

Step 5: TTS (BROKEN — see below)
  _wrap_tts_streaming() thread starts
  → reads sentences from queue
  → self._speak_response(q, sid) ← THIS FAILS SILENTLY
  → should generate audio via tts.synthesize_stream()
  → play via sd.play(blocking=True) on selected output device

Step 6: AUTO-RELISTEN (BROKEN — depends on Step 5)
  After TTS completes → broadcast "idle" → restart listening
```

## TTS Bug — Root Cause Investigation

### Current symptom

- Model responds with text ✅
- Words highlight in chatview (200ms frontend timer) ✅
- Dashboard shows "processing" state ❌
- NO audio plays ❌
- Orb cadence doesn't pulse ❌
- Voice state stays in "processing", never transitions ❌

### What we've verified works in isolation

```
Python direct Pocket-TTS test:
  ✓ pocket_tts installed (v2.1.0)
  ✓ Model variant 'english' loads in ~1s (230MB cached)
  ✓ Catalog voice 'alba' downloads (5.9MB)
  ✓ TTSManager._load_pocket_tts() returns True
  ✓ TTSManager._voice_state is not None (voice loaded)
```

### What the backend logs show

From `backend/logs/irisvoice.log`:
```
01:57:39 [TTS] Starting Pocket-TTS pre-load...
01:57:41 [TTS] Pocket-TTS pre-loaded in 0.7s   ← success
```

The pre-load succeeds! But subsequent TTS calls produce NO log entries at all. No `[TTS] _wrap_tts_streaming started` from the logging I added.

### Suspected root causes (unresolved)

1. **`_wrap_tts_streaming` thread never starts** — The thread is at line 2074-2078 in `iris_gateway.py`. Check if `_process_voice_transcription()` is actually called. It's inside `_on_voice_result()` at line 2535.

2. **`_speak_response()` silently crashes** — The function is called from `_wrap_tts_streaming` (line 2056). It's a synchronous function (not async) that uses `asyncio.run_coroutine_threadsafe()` internally. It accesses `self._main_loop` (must be set) and `self._ws_manager` for broadcasting.

3. **Producer thread blocks** — Inside `_speak_response()`, the `_producer` function runs in a thread (line 2477-2480) and reads from the sentence queue. If `input_source.get()` blocks because no sentences are queued, it never produces audio chunks.

4. **Consumer thread times out** — The consumer loop (line 2492+) waits for chunks with a 300s timeout. If the producer never pushes chunks, the consumer blocks for 300s then skips TTS.

5. **Audio queue push fails** — `asyncio.run_coroutine_threadsafe(audio_queue.put(audio_chunk), loop)` at line 2261. If `loop` is the wrong event loop (or not running), this fails silently.

### Logging added for diagnosis (committed)

In `_wrap_tts_streaming` at iris_gateway.py:2053-2062:
```
[TTS] _wrap_tts_streaming started — calling _speak_response
[TTS] _speak_response completed
[TTS] streaming fatal: {traceback}
```

Search for `[TTS]` in `backend/logs/irisvoice.log` after testing to see where it fails.

## All Fixes Applied This Session

### Commits on `feat/xurorb-spiral-dissolve-winner`

```
e7b7df60 fix(tts): Pocket-TTS variant 'b6369a24' → 'english'
            (variant doesn't exist in Pocket-TTS v2)
            
4be11a83 feat(providers): add Gemma 4 31B to Cerebras backend model list

b14b817e fix(tts): move pre-load after _main_loop assignment
            (was crashing with NameError)

b68206fc feat(ui): add Gemma 4 31B to Cerebras frontend PROVIDER_MODELS

30969e0c fix(tts): add exception logging to TTS streaming path

Also: voice_command.py, engine.py, XurOrb.tsx, iris_gateway.py
      (single-click→end, auto_stop=True, native disabled, etc.)
```

### Full change list

| File | Change |
|------|--------|
| `backend/main.py` | Fixed `_on_wake_word_async` — removed `self` reference, added `import time`, moved TTS pre-load after `_main_loop` |
| `backend/iris_gateway.py` | Added `voice_command_cancel` to router, `auto_stop=True` default, TTS timeout 300s, loopback device filter, test_audio handler, exception logging |
| `backend/audio/engine.py` | Skip loopback devices in auto-select, `activation_sound` config default to wav file |
| `backend/audio/pipeline.py` | **Disabled native C++ player** (caused 30-40s blocking + static) |
| `backend/audio/voice_command.py` | Removed half-duplex gate from activation sound, bypass native player with `sd.play()`, RMS logging |
| `backend/agent/tts.py` | Pocket-TTS variant `b6369a24` → `english` |
| `backend/api/chat.py` | TTS error logs DEBUG→WARNING |
| `backend/customize/notifications.py` | Rewrote `play_notification_sound()` to actually play WAV via sounddevice |
| `components/iris/XurOrb.tsx` | Single-click → `endVoiceCommand()` (was cancel), removed dead wake word bridge code |
| `components/iris/IrisOrb.tsx` | Removed `onCallbacksReady`/`wakeFlash` props |
| `components/iris/types.ts` | Removed dead callback props |
| `components/dark-glass-dashboard.tsx` | Wired test_output/input buttons, added Gemma 4 31B to Cerebras PROVIDER_MODELS |
| `app/page.tsx`, `orb-preview/page.tsx` | Removed `wakeFlash={false}` prop |

## Remaining Issues for Next Agent

### 1. TTS audio not playing (CRITICAL)

The TTS is the last broken piece. `_speak_response()` is called but produces no audio. Steps to debug:

1. **Refresh browser page (F5)** — ensures fresh WebSocket connection
2. **Say "hey iris"** → speak → wait for LLM response
3. **Check logs immediately**: `Select-String -Path irisvoice.log -Pattern "\[TTS\]"`
4. If `[TTS] _wrap_tts_streaming started` appears but no `[TTS] _speak_response completed`, the function is stuck inside `_speak_response()`
5. If nothing appears, the thread never started — check `_process_voice_transcription()` at iris_gateway.py:1897

**Code path to trace:**
- `iris_gateway.py:1897` — `_process_voice_transcription()`
- `iris_gateway.py:1982` — `chunk_callback()` (puts sentences in queue)
- `iris_gateway.py:2053` — `_wrap_tts_streaming()` (consumes queue)
- `iris_gateway.py:2074` — thread start
- `iris_gateway.py:2148` — `_speak_response()` (TTS generation + playback)
- `iris_gateway.py:2310-2480` — Queue input path (reads sentences, generates chunks)
- `iris_gateway.py:2492-2560` — Consumer loop (accumulates chunks, calls play_stream)
- `backend/audio/pipeline.py:226` — `play_stream()` (concatenates + sd.play)

### 2. `_speak_response` function structure

```
_speak_response(input_source: str | queue.Queue, session_id):
  │
  ├─ if isinstance(input_source, str):  ─── for play button
  │     for chunk in tts.synthesize_stream(input_source):
  │         _push_or_queue(chunk)           push to audio_queue
  │
  └─ else:                                ─── for auto-TTS
        while True:
            sentence = input_source.get()    blocks on sentence queue
            if sentence is None: break
            accumulate words → call synthesize_stream(segment)
            for chunk in output:
                _push_or_queue(chunk)
  
  Then: consumer loop reads audio_queue → accumulate → play_stream()
```

### 3. Key test

The closest function to raw TTS playback is the **play button** in chatview. It sends `tts_play` WS message. The handler calls `_speak_response(text, session_id)` directly. If the play button also produces no audio, the bug is in `_speak_response()` or lower.

### 4. Simple test script (run from project root)

```python
from agent.tts import TTSManager
tts = TTSManager()
tts._load_pocket_tts()  # returns True
chunks = list(tts.synthesize_stream("test"))
import sounddevice as sd
sd.play(np.concatenate(chunks), 24000, blocking=True)
```

### 5. `_main_loop` must be set

In `iris_gateway.py:2765`, `self._main_loop = loop` is set before the agent runs. If this is None when `_speak_response` runs, the `asyncio.run_coroutine_threadsafe` calls inside will fail silently. Check with:

```python
Select-String "set_main_loop|_main_loop =" iris_gateway.py
```

## Services to Restart

```powershell
# Kill all
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object CommandLine -Match "backend|parakeet" | Stop-Process

# Start Parakeet (GPU ASR)
venv\Scripts\python.exe -m backend.audio.parakeet_service --port 8765 --device cuda

# Start backend
venv\Scripts\python.exe start-backend.py

# Frontend (if not running)
npm run dev
```

## Configuration

- **Pocket-TTS config**: backend/agent/tts.py — edit `POCKET_TTS_VARIANT` env var or default at line 333
- **Output device**: Settings → Audio → Output (dropdown), resolves via `_resolve_device_index()`
- **Input device**: Settings → Audio → Input, currently auto-selected to Microphone (V8)
- **Test buttons**: Settings → Audio → Output/Input section, play icon sends `test_audio` WS message
