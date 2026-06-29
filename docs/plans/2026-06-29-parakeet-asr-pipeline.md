# Parakeet ASR + Audio Pipeline Wiring — Implementation Plan

**Date:** 2026-06-29
**Author:** Director (senior-architect skill)
**Status:** Approved, in progress
**Target:** IRISVOICE — Tauri widget (primary) + web browser (testing)

---

## 1. Goals

1. **Wire Parakeet TDT 0.6B v3 ASR** to the audio pipeline, served by a new backend service running on the local RTX 3070 (fp16 CUDA, ~1.2 GB VRAM). Both the Tauri widget and the web browser share the same service over `ws://localhost:8765/ws/stream`.
2. **Fix all 4 wiring defects** surfaced by the audio pipeline audit:
   - Orb stuck in "speaking" state (no `listening_state: "idle"` broadcast at end of `_speak_response`)
   - Double-injection of `iris:text_response` events (no `turn_id` dedup)
   - REST `/api/chat` path produces no TTS (text-only)
   - Word-by-word TTS highlight uses local 200 ms tick that drifts from real TTS speed
3. **Preserve wake word** (Porcupine) — no changes to that code path. It runs on-device, CPU, <1 ms per frame, completely independent of Parakeet.
4. **Verification-first** — unit + integration + E2E + manual checklist. Every change ships with tests.

---

## 2. Architecture

### 2.1 Current state (broken for web)

```
┌────────────────────────────────────────────────────────┐
│  Tauri dev box                                         │
│                                                        │
│  ┌─────────────────────────────────────────────────┐  │
│  │  IRIS backend (iris_gateway + agent)            │  │
│  │  - VoiceCommandHandler  (Porcupine wake word)   │  │
│  │  - TTSManager          (Pocket-TTS, CPU)        │  │
│  │  - faster-whisper tiny (CPU, 4 threads)         │  │
│  │  - AudioEngine         (sounddevice input)      │  │
│  └─────────────────────────────────────────────────┘  │
│                                                        │
│  Web client: no audio capture path.                    │
│  REST /api/chat: text only, no TTS.                    │
│  Orb: gets stuck in "speaking".                       │
│  text_response: duplicated without dedup.              │
└────────────────────────────────────────────────────────┘
```

### 2.2 Target state (Option A: backend Parakeet, shared between Tauri + web)

```
┌──────────────────────────────────────────────────────────────────┐
│  Tauri dev box (Windows)                                        │
│                                                                  │
│  ┌──────────────────────┐      ┌──────────────────────────────┐  │
│  │ Parakeet ASR service │      │ IRIS Backend                 │  │
│  │ (NEW: parakeet_      │◄─────┤ (iris_gateway + agent)       │  │
│  │  service.py)         │ PCM  │                              │  │
│  │                      │ 80ms │  - VoiceCommandHandler       │  │
 │  │ HF Transformers      │      │    (Porcupine — unchanged)   │  │
│  │ CUDA fp16            │      │  - TTSManager (Pocket-TTS)   │  │
│  │ Port 8765            │      │  - AudioEngine               │  │
│  └──────────┬───────────┘      └──────────┬───────────────────┘  │
│             │                             │                      │
└─────────────┼─────────────────────────────┼──────────────────────┘
              │                             │
        ws://localhost:8765/ws/stream  ws://localhost:8000/iris
              │                             │
   ┌──────────┴──────────┐                  │
   │                     │                  │
┌──┴──────────┐   ┌──────┴──────┐           │
│ Tauri widget│   │ Chrome/FF   │           │
│ (mic routed │   │ (Media-     │           │
│  through    │   │  Recorder)  │           │
│  backend)   │   │             │           │
└─────────────┘   └─────────────┘           │
                                              │
                            "Hey IRIS" → Porcupine → voice_command_start
                                              │
                                              ▼
                                       useParakeetSTT.start()
                                       (same hook both clients)
```

**Key design points:**

- **Parakeet lives on the 3070, not in the browser.** Browser just streams raw PCM. Avoids 400 MB model download; no WebGPU dependency; matches the desktop-first design.
- **Porcupine is never touched.** The wake word path uses a different library (`pvporcupine`) running on a different audio device thread. The new ASR service does not know wake words exist.
- **Pocket-TTS stays on CPU.** Its first comment is "Runs on CPU" (tts.py line 2). No CUDA contention with Parakeet.
- **One capture path per platform.** Tauri widget uses backend `sounddevice` (single mic ownership); browser uses `getUserMedia`. The Parakeet service just receives bytes; it doesn't care about source.

### 2.3 Audio routing per platform

| Platform | Mic capture | ASR | Wake word | TTS |
|----------|-------------|-----|-----------|-----|
| **Tauri widget** | Backend `sounddevice` (already there) | Backend → Parakeet WS | Backend Porcupine | Backend Pocket-TTS |
| **Web (local)** | Browser `getUserMedia` | WebSocket → Parakeet | Disabled (no Porcupine) | Browser audio element |
| **Web (Tailscale)** | Browser `getUserMedia` | WebSocket → Parakeet (URL override) | Disabled | Browser audio element |

**Auto-detection:** `useParakeetSTT` checks `window.__TAURI__` to pick the right capture path. In Tauri mode, it actually sends a `start_mic_capture` Tauri command and consumes the resulting PCM stream from the Tauri process (avoids double-mic on desktop). In web mode, it opens a `MediaStream` directly.

---

## 3. Files

### 3.1 New files (5)

| File | Purpose |
|------|---------|
| `backend/audio/parakeet_service.py` | FastAPI + HF Parakeet TDT ASR server, WS streaming endpoint, REST fallback, model lifecycle |
| `backend/audio/parakeet_buffer.py` | Cache-aware streaming buffer (TDT-specific chunked inference) |
| `hooks/useParakeetSTT.ts` | React hook: mic capture (Tauri + MediaRecorder) → 80 ms PCM → WS to Parakeet |
| `tests/test_parakeet_service.py` | Unit tests for the ASR service (mocked model) |
| `tests/e2e/test_voice_to_chat.py` | Playwright E2E: speak → transcript → reply → TTS → orb idle |

### 3.2 Files modified (8)

| File | Change |
|------|--------|
| `backend/audio/voice_command.py` | Delete stale F5-TTS comment (line 398). Add `_transcribe_via_parakeet_service()` with Whisper fallback. Keep `WhisperModel` init for fallback path. |
| `backend/iris_gateway.py` | (a) At end of `_speak_response` add `listening_state: "idle"` broadcast. (b) Add `turn_id` to every `text_response` dispatch. (c) Add `voice_audio_chunk` and `voice_result` cases. |
| `app/api/chat/route.ts` | After successful chat response, fire-and-forget POST to `http://localhost:8000/iris/speak` so the REST text path also produces TTS. |
| `components/chat-view.tsx` | (a) `turn_id` dedup via `useRef<Set<string>>`. (b) New `iris:voice_final` listener. (c) Replace 200 ms word-tick with `tts_word` events. |
| `hooks/useIRISWebSocket.ts` | Add `voice_audio_chunk` outgoing + `voice_result` incoming handlers. Expose `startParakeetSTT` / `stopParakeetSTT`. |
| `requirements.txt` | Add `transformers>=5.12.0`, `fastapi`, `uvicorn[standard]`. Keep `faster-whisper` for fallback. |
| `app/page.tsx` | Comment-only: document that double-click triggers `startParakeetSTT()`. |
| `data/irispulse-config.json` | Add `parakeet_service_url` (default `ws://localhost:8765/ws/stream`), `parakeet_enabled`, `parakeet_auto_start_dev`. |

### 3.3 Files explicitly NOT touched

| File | Why |
|------|-----|
| `backend/audio/engine.py` | Porcupine + CadenceDetector + BargeInDetector all work. Wake word must not move. |
| `backend/audio/cadence_detector.py` | Spectral-flux VAD is platform-agnostic and works with any STT backend. |
| `backend/agent/tts.py` | Pocket-TTS is correctly wired. The 2026-06-02 plan is now obsolete but the code is done. |
| `backend/agent/wake_config.py` | Wake word configuration schema is correct. |
| `backend/audio/pipeline.py` | Half-duplex gate (TTS mutes mic capture) is correct. |

### 3.4 Files to delete (1, after PR 6)

| File | Why |
|------|-----|
| `docs/plans/2026-06-02-pocket-tts-swap.md` | Superseded by the inline header docstring in `tts.py`. Implementation is complete. |

---

## 4. Per-file implementation details

### 4.1 `backend/audio/parakeet_service.py` (NEW)

**Responsibilities:**
- Load HuggingFace Parakeet TDT 0.6B v3 on CUDA fp16 at startup (lifespan hook)
- Expose `WebSocket /ws/stream` — binary PCM int16 mono 16 kHz → `{"type":"partial"|"final","text","confidence"}`
- Expose `POST /transcribe` — full WAV/PCM body → `{"text","language","duration_s"}`
- Expose `GET /healthz` — `{"model_loaded","device","vram_mb","uptime_s"}`
- Expose `GET /metrics` — request count, p50/p95/p99 latency, active streams (added in PR 7)
- Graceful shutdown: flush partials, free model, log VRAM delta

**Code shape (sketch):**

```python
"""
Parakeet ASR Service — HuggingFace Parakeet TDT 0.6B v3 on local GPU (RTX 3070).

Sole ASR backend for both the Tauri widget and the web browser.
WebSocket streaming: 80ms PCM int16 mono 16kHz chunks.
REST fallback: full-utterance transcription (used by VoiceCommandHandler
when the WS path is not available, e.g. backend-only Tauri mic capture).

Memory:  ~1.2 GB VRAM (fp16), ~600 MB int8 (opt-in via --quantize)
Latency: <300 ms first-token on RTX 3070
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import asyncio
import logging
import time

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
import torch

from .parakeet_buffer import ParakeetStreamingBuffer

logger = logging.getLogger("parakeet_service")

# --- Config ---------------------------------------------------------------
DEFAULT_MODEL = "nvidia/parakeet-tdt-0.6b-v3"
SAMPLE_RATE = 16_000
CHUNK_MS = 80                                  # 1280 samples
BYTES_PER_CHUNK = CHUNK_MS * SAMPLE_RATE * 2 // 1000   # 2560 bytes int16


@dataclass
class ServiceConfig:
    model_name: str = DEFAULT_MODEL
    device: str = "cuda"                        # "cuda" | "cpu"
    precision: str = "fp16"                     # "fp16" | "int8" | "fp32"
    port: int = 8765
    host: str = "0.0.0.0"
    max_concurrent_streams: int = 16
    chunk_secs: float = 0.08
    left_context_secs: float = 5.0
    right_context_secs: float = 0.5


# --- Lifespan -------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg: ServiceConfig = app.state.config
    logger.info("Loading Parakeet model: %s on %s (%s)", cfg.model_name, cfg.device, cfg.precision)

    # Lazy import via HuggingFace Transformers (NeMo is not Windows-compatible)
    from transformers import AutoModelForTDT, AutoProcessor
    torch_dtype = torch.float16 if cfg.precision == "fp16" else torch.float32
    model = AutoModelForTDT.from_pretrained(
        cfg.model_name,
        torch_dtype=torch_dtype,
        device_map=cfg.device if cfg.device == "cuda" else None,
        low_cpu_mem_usage=True,
    )
    processor = AutoProcessor.from_pretrained(cfg.model_name)
    model.eval()
    app.state.model = model
    app.state.processor = processor
    app.state.started_at = time.monotonic()
    logger.info("Parakeet model ready. VRAM: %.1f MB",
                torch.cuda.memory_allocated() / 1024**2 if torch.cuda.is_available() else 0)
    try:
        yield
    finally:
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("Parakeet model unloaded.")


# --- App ------------------------------------------------------------------
app = FastAPI(lifespan=lifespan, title="IRIS Parakeet ASR Service")


@app.get("/healthz")
async def healthz():
    ready = hasattr(app.state, "model")
    return {
        "model_loaded": ready,
        "device": app.state.config.device,
        "precision": app.state.config.precision,
        "vram_mb": (torch.cuda.memory_allocated() / 1024**2
                    if (ready and torch.cuda.is_available()) else 0),
        "uptime_s": (time.monotonic() - app.state.started_at) if ready else 0,
    }


@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    await ws.accept()
    cfg: ServiceConfig = app.state.config
    model = app.state.model
    buffer = ParakeetStreamingBuffer(
        model=model,
        sample_rate=SAMPLE_RATE,
        chunk_secs=cfg.chunk_secs,
        left_context_secs=cfg.left_context_secs,
        right_context_secs=cfg.right_context_secs,
    )
    try:
        while True:
            raw = await ws.receive_bytes()
            if len(raw) % 2 != 0:
                # malformed int16 — skip and warn
                logger.warning("WS chunk has odd byte count: %d", len(raw))
                continue
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            partial = buffer.push(samples)
            if partial:
                await ws.send_json({
                    "type": "partial",
                    "text": partial.text,
                    "confidence": partial.confidence,
                    "ts": time.time(),
                })
    except WebSocketDisconnect:
        final = buffer.flush()
        if final and final.text.strip():
            await ws.send_json({
                "type": "final",
                "text": final.text,
                "confidence": final.confidence,
                "ts": time.time(),
            })
        await ws.close()


@app.post("/transcribe")
async def rest_transcribe(body: bytes):
    """Full-utterance transcription. Body = raw PCM int16 mono 16kHz."""
    if not body:
        raise HTTPException(400, "Empty body")
    if len(body) % 2 != 0:
        raise HTTPException(400, "Body must be int16 PCM (even byte count)")
    samples = np.frombuffer(body, dtype=np.int16).astype(np.float32) / 32768.0
    duration_s = len(samples) / SAMPLE_RATE
    if duration_s > 60:
        raise HTTPException(400, f"Max 60s per request (got {duration_s:.1f}s)")
    model = app.state.model
    # Run inference in a thread to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _transcribe_full, model, samples)
    return {
        "text": text.strip(),
        "language": "auto",
        "duration_s": duration_s,
    }


def _transcribe_full(model, samples: np.ndarray) -> str:
    """Blocking inference — call via run_in_executor."""
    import torch
    with torch.inference_mode():
        tensor = torch.from_numpy(samples).unsqueeze(0).to(app.state.config.device)
        if app.state.config.precision == "fp16":
            tensor = tensor.half()
        result = model.transcribe(tensor, return_hypotheses=True)
    return result[0].text if hasattr(result[0], "text") else str(result[0])


# --- Entrypoint -----------------------------------------------------------
def main():
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser(description="IRIS Parakeet ASR Service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--precision", default="fp16", choices=["fp16", "int8", "fp32"])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    app.state.config = ServiceConfig(
        model_name=args.model,
        device=args.device,
        precision=args.precision,
        host=args.host,
        port=args.port,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
```

### 4.2 `backend/audio/parakeet_buffer.py` (NEW)

**Responsibilities:**
- Receive audio chunks via WebSocket, accumulate into a per-connection ring buffer
- Maintain a ring buffer of recent audio (left context)
- Decode partial hypotheses on each new chunk
- Flush final hypothesis on close

**Key abstractions:**

```python
@dataclass
class Hypothesis:
    text: str
    confidence: float
    timestamp: float

class ParakeetStreamingBuffer:
    def __init__(self, model, sample_rate, chunk_secs, left_context_secs, right_context_secs):
        ...
    def push(self, samples: np.ndarray) -> Optional[Hypothesis]:
        """Add a chunk, return updated partial hypothesis (or None)."""
    def flush(self) -> Optional[Hypothesis]:
        """Finalize and return the final hypothesis."""
    @property
    def duration_s(self) -> float:
        ...
```

The decoder receives accumulated audio context and returns a hypothesis. For PR 1, the decoder is a stub; real HuggingFace ParakeetForTDT integration lands in PR 1 follow-up (we want the file structure landed and tested first).

### 4.3 `backend/iris_gateway.py` — 3 patches

**Patch A (orb unstick):**
```python
# In _speak_response, after the last audio chunk is queued:
await self._broadcast({"type": "listening_state", "state": "speaking"})  # already there
# NEW: when the final chunk's playback finishes:
playback_done = asyncio.Event()
await self._native_player.on_playback_complete(playback_done.set)
try:
    await asyncio.wait_for(playback_done.wait(), timeout=len(text) * 0.05 + 5)
finally:
    await self._broadcast({"type": "listening_state", "state": "idle"})
```

**Patch B (turn_id):**
```python
import uuid
# In every _broadcast of text_response:
turn_id = str(uuid.uuid4())
payload = {"type": "text_response", "turn_id": turn_id, "text": ..., "sender": ..., ...}
await self._broadcast(payload)
```

**Patch C (voice_* handlers):**
```python
# In _handle_ws_message:
elif msg_type == "voice_audio_chunk":
    # Forward PCM bytes to Parakeet service
    await self._parakeet_proxy.forward(client_id, payload)
elif msg_type == "voice_result":
    # Parrot back to all clients (useful for Tailscale multi-view)
    await self._broadcast({"type": "voice_result", **payload})
```

### 4.4 `components/chat-view.tsx` — 3 patches

**Patch A (turn_id dedup):**
```tsx
const seenTurnIdsRef = useRef<Set<string>>(new Set())

function handleTextResponse(e: Event) {
  const { text, sender = 'assistant', thinking, turn_id } = (e as CustomEvent).detail
  if (!text) return
  if (turn_id) {
    if (seenTurnIdsRef.current.has(turn_id)) return
    seenTurnIdsRef.current.add(turn_id)
    setTimeout(() => seenTurnIdsRef.current.delete(turn_id), 30000)
  }
  // ... existing add-to-conversation logic
}
```

**Patch B (iris:voice_final listener):**
```tsx
useEffect(() => {
  const handler = (e: Event) => {
    const { text, turn_id } = (e as CustomEvent).detail
    if (!text?.trim()) return
    // Create user message and trigger the same /api/chat path
    const userMessage: Message = {
      id: `voice-${turn_id || Date.now()}`,
      text: text.trim(),
      sender: "user",
      timestamp: new Date(),
    }
    setConversations(prev => /* same logic as handleSendMessage */)
    fetch("/api/chat", { method: "POST", body: JSON.stringify({ text, thread_id: restThreadId }) })
      // ... same response handling
  }
  window.addEventListener("iris:voice_final", handler)
  return () => window.removeEventListener("iris:voice_final", handler)
}, [])
```

**Patch C (tts_word events):**
```tsx
// Replace the 200ms local interval with:
useEffect(() => {
  const handler = (e: Event) => {
    const { message_id, word_index } = (e as CustomEvent).detail
    if (message_id === currentTtsMessageId) setTtsWordIndex(word_index)
  }
  window.addEventListener("iris:tts_word", handler)
  return () => window.removeEventListener("iris:tts_word", handler)
}, [currentTtsMessageId])
```

### 4.5 `hooks/useIRISWebSocket.ts` — 2 additions

```typescript
// Outgoing: stream raw PCM to Parakeet
const sendAudioChunk = useCallback((pcmInt16: ArrayBuffer) => {
  if (wsRef.current?.readyState === WebSocket.OPEN) {
    wsRef.current.send(pcmInt16)  // binary frame
  }
}, [])

// Incoming: handle voice_result
case "voice_result":
  window.dispatchEvent(new CustomEvent("iris:voice_result", { detail: payload }))
  break
```

### 4.6 `hooks/useParakeetSTT.ts` (NEW)

**Public API:**
```typescript
export interface ParakeetSTTState {
  isListening: boolean
  partialText: string
  error: string | null
}
export function useParakeetSTT(): {
  state: ParakeetSTTState
  start: () => Promise<void>
  stop: () => void
}
```

**Implementation strategy:**
- `start()` opens `WebSocket(parakeetServiceUrl)` and MediaStream (or Tauri command)
- Uses `AudioContext({ sampleRate: 16000 })` + `ScriptProcessor(2048, 1, 1)` to get 128 ms frames
- Downsamples if native rate ≠ 16 kHz (browser may not honor the request)
- Sends 80 ms int16 chunks (split the 128 ms frame in half)
- Receives `partial` and `final` JSON, dispatches CustomEvents
- `stop()` closes WS, stops MediaStream, dispatches `iris:voice_final` if there's a buffered partial

**Tauri routing:** When `window.__TAURI__` is present, we send `start_voice_capture` Tauri command and consume PCM frames from a Tauri event stream (`iris:audio_frame`). The backend Python Tauri shim owns the mic. This avoids two processes fighting for the mic.

### 4.7 `app/api/chat/route.ts` — TTS fire-and-forget

```typescript
const tts = data  // existing
// NEW: fire-and-forget TTS for text-only path
fetch("http://localhost:8000/iris/speak", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ text: data.content, thread_id: data.thread_id }),
}).catch((err) => console.warn("[chat] TTS fire-and-forget failed:", err))
```

### 4.8 `requirements.txt` — additions

```
# Existing
faster-whisper>=1.0.0
pvporcupine>=2.2.0
sounddevice>=0.4.6

# NEW (HuggingFace Transformers — NeMo does not support Windows)
transformers>=5.12.0
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
```

---

## 5. Wake word preservation

**Porcupine integration is untouched.** Specifically:

| File | Why no change |
|------|---------------|
| `backend/agent/wake_config.py` | Wake config schema (phrase, sensitivity, model path) is correct |
| `backend/audio/engine.py` (Porcupine init in `__init__`) | Loads `pvporcupine.create()` from `wake_config.json` — works on CPU, no model swap |
| `AudioEngine._porcupine_callback` | Invokes `VoiceCommandHandler._on_wake_detected` on match — unchanged |
| `VoiceCommandHandler._on_wake_detected` | Sets `_state = "wake_detected"`, dispatches `voice_command_start` via callback — unchanged |
| `iris_gateway._handle_voice_command_message` | Receives `voice_command_start` and `voice_command_end` from frontend — unchanged |

**Coexistence pattern:** When Porcupine fires `voice_command_start`, the frontend now ALSO calls `useParakeetSTT.start()` in the same handler. The two systems are independent:

- **Porcupine:** always listening, CPU, 1 ms per frame, on the backend's audio device
- **Parakeet:** activated on wake OR double-click, GPU, processes the captured audio, returns transcript

The Porcupine callback does not know Parakeet exists. The Parakeet service does not know Porcupine exists. They communicate only through the `voice_command_start` CustomEvent on the frontend, which fans out to both systems.

---

## 6. Verification checklist

### 6.1 Unit tests (mocked — no GPU)

```
tests/test_parakeet_service.py
  □ test_healthz_returns_503_when_model_not_loaded
  □ test_healthz_returns_200_with_vram_after_lifespan
  □ test_websocket_accepts_binary_chunks
  □ test_websocket_rejects_odd_byte_count_with_warning
  □ test_websocket_emits_partial_within_one_chunk
  □ test_websocket_emits_final_on_disconnect
  □ test_websocket_emits_final_only_if_non_empty
  □ test_rest_transcribe_returns_text_for_pcm_body
  □ test_rest_transcribe_rejects_empty_body_with_400
  □ test_rest_transcribe_rejects_odd_byte_count_with_400
  □ test_rest_transcribe_rejects_over_60s_with_400
  □ test_streaming_buffer_preserves_left_context_across_chunks
  □ test_streaming_buffer_resets_after_silence
  □ test_streaming_buffer_flush_returns_final_hypothesis
  □ test_int8_precision_flag_is_accepted
  □ test_cpu_device_falls_back_when_cuda_unavailable

tests/test_iris_gateway_patches.py
  □ test_speak_response_broadcasts_idle_after_playback_done
  □ test_speak_response_idle_broadcast_includes_turn_id
  □ test_text_response_includes_turn_id
  □ test_turn_id_unique_per_dispatch
  □ test_voice_audio_chunk_forwards_to_parakeet_proxy
  □ test_voice_result_broadcasts_to_all_clients

tests/test_chat_view_dedup.py
  □ test_seen_turn_id_drops_duplicate
  □ test_seen_turn_id_clears_after_30s
  □ test_voice_final_creates_user_message
  □ test_voice_final_calls_api_chat
  □ test_tts_word_event_updates_word_index

tests/test_voice_command_parakeet_fallback.py
  □ test_parakeet_unreachable_falls_back_to_whisper
  □ test_parakeet_503_falls_back_to_whisper
  □ test_parakeet_timeout_falls_back_to_whisper
  □ test_faster_whisper_still_initialized_at_engine_start
```

### 6.2 Integration tests (real GPU — `@pytest.mark.gpu`)

```
tests/integration/test_parakeet_real_audio.py
  □ test_3s_english_utterance_transcribes
  □ test_partial_within_300ms
  □ test_60s_utterance_chunks_correctly
  □ test_silence_does_not_split_hypothesis
  □ test_multilingual_auto_detect
  □ test_barge_in_during_tts_is_dropped
  □ test_10_concurrent_streams_stable_latency
```

### 6.3 E2E tests (Playwright + headless)

```
tests/e2e/test_voice_to_chat.py
  □ test_double_click_starts_listening
  □ test_partial_appears_in_chat_input
  □ test_final_triggers_assistant_reply
  □ test_assistant_reply_plays_tts
  □ test_orb_returns_to_idle_after_tts
  □ test_voice_does_not_create_duplicate_message
  □ test_text_input_during_voice_session_works
  □ test_conversation_persists_after_voice

tests/e2e/test_porcupine_unchanged.py
  □ test_wake_word_triggers_voice_command_start
  □ test_wake_sensitivity_setting_respected
  □ test_disabling_wake_word_allows_double_click
  □ test_wake_does_not_break_parakeet_path
```

### 6.4 Manual checklist (run on 3070)

**Pre-flight**
- [ ] `nvidia-smi` shows 3070 with <2 GB used
- [ ] `pip install transformers>=5.12.0` succeeds
- [ ] `python -m backend.audio.parakeet_service --device cuda` starts cleanly
- [ ] `curl http://localhost:8765/healthz` returns `{"model_loaded": true, "device": "cuda"}`

**TTS regression (must not break)**
- [ ] pnpm dev → /api/chat "hello" → assistant reply within 5 s
- [ ] Reply IS played via TTS (REST path TTS fix)
- [ ] Voice matches TOMV2.wav reference
- [ ] pyttsx3 fallback works if Pocket-TTS terms not accepted

**STT new path (Parakeet)**
- [ ] Double-click orb → voiceState = "listening" within 200 ms
- [ ] Speak "what's the weather" → partial "what's the" within 500 ms
- [ ] Final "what's the weather" arrives on stop
- [ ] Assistant text reply
- [ ] Orb returns to "idle" after TTS (orb unstick fix)
- [ ] tts_word events drive highlight (word-tick drift fix)

**Wake word (must not break)**
- [ ] "Hey IRIS" → voiceState = "listening" without double-click
- [ ] Sensitivity change → Porcupine re-inits within 2 s
- [ ] Disable wake → orb stays idle on wake phrase
- [ ] Parakeet service down → wake word still works

**turn_id dedup**
- [ ] Two browser tabs, speak in one → message in BOTH (parrot works)
- [ ] Two tabs, send text in one → only one assistant message per tab
- [ ] Spam "send" 10× → 10 unique user messages

**Web path**
- [ ] Chrome → http://localhost:3000 → orb visible
- [ ] Allow mic permission on first double-click
- [ ] Speak → transcript in chat (via Parakeet on backend)
- [ ] Tailscale phone access → same flow

**Tauri path**
- [ ] pnpm tauri dev → widget launches
- [ ] Double-click → voice command starts
- [ ] Parakeet latency <500 ms first partial on 3070
- [ ] VRAM <2 GB throughout

**Error paths**
- [ ] Kill Parakeet mid-session → "voice unavailable" toast
- [ ] Restart Parakeet → next double-click works
- [ ] CUDA OOM (artificially allocate 7 GB) → service 503, frontend falls back
- [ ] No mic permission → permission prompt, not silent fail

**Performance (3070 baseline)**
- [ ] Parakeet first-token: <300 ms
- [ ] Pocket-TTS first-chunk: <250 ms
- [ ] End-to-end voice → reply → TTS: <1500 ms for 3 s utterance
- [ ] 5 concurrent streams: latency <500 ms
- [ ] VRAM after 10 min: <1.5 GB
- [ ] CPU: <20% (Porcupine + Cadence + game loop)

### 6.5 Regression matrix

```
[ ] pytest tests/test_audio_pipeline.py
[ ] pytest backend/tests/test_voice_pipeline.py
[ ] pytest backend/tests/test_domain2_voice.py
[ ] pytest tests/test_parakeet_service.py           (NEW)
[ ] pytest tests/test_iris_gateway_patches.py       (NEW)
[ ] pytest tests/test_chat_view_dedup.py            (NEW)
[ ] pytest tests/test_voice_command_parakeet_fallback.py (NEW)
[ ] pytest tests/integration/test_parakeet_real_audio.py  (NEW, GPU-gated)
[ ] pnpm test
[ ] pnpm e2e
```

---

## 7. PR sequencing

| # | Title | Files | Tests | Approx LOC |
|---|-------|-------|-------|-----------|
| **1** | Parakeet service skeleton | `parakeet_service.py` + `parakeet_buffer.py` + tests + `requirements.txt` | `test_parakeet_service.py` | +850 / -0 |
| **2** | Backend wiring (orb unstick + turn_id) | `iris_gateway.py` patches A/B/C | `test_iris_gateway_patches.py` | +60 / -5 |
| **3** | Chat-view dedup + word events | `chat-view.tsx` patches A/B/C | `test_chat_view_dedup.py` | +90 / -40 |
| **4** | Web STT hook + E2E | `useParakeetSTT.ts` + `useIRISWebSocket.ts` + `page.tsx` comment | `test_voice_to_chat.py` | +250 / -0 |
| **5** | VoiceCommandHandler integration | `voice_command.py` (delete comment + Parakeet REST fallback) | `test_voice_command_parakeet_fallback.py` | +60 / -3 |
| **6** | REST TTS + cleanup | `app/api/chat/route.ts` + delete obsolete plan | (covered by integration) | +10 / -200 |
| **7** | Metrics + integration tests | `parakeet_service.py` `/metrics` + `test_parakeet_real_audio.py` + `test_porcupine_unchanged.py` | (above) | +120 / -0 |

**Total:** ~1440 LOC added, ~250 LOC removed, 5 new test files, ~50 new test cases.

---

## 8. Open questions — resolved

| Question | Resolution |
|----------|------------|
| Auto-start Parakeet or manual? | **Auto-start in dev mode, manual in production** (config flag `parakeet_auto_start_dev`) |
| fp16 or int8? | **fp16 default**, int8 opt-in via `--quantize` flag |
| Tailscale / remote view URL? | **`parakeet_service_url` config**, defaults to `ws://localhost:8765/ws/stream`, Tailscale clients override via `data/irispulse-config.json` |
| Tauri mic ownership? | **Backend owns the mic** in Tauri mode (no double-mic). `useParakeetSTT` sends a Tauri command and consumes frames from a Tauri event stream. |
| Single capture abstraction? | **Yes** — `useParakeetSTT` handles both paths; the Parakeet service just receives bytes regardless of source. |

---

## 9. Risk register

| Risk | Mitigation |
|------|-----------|
| Transformers model download on first run is ~2 GB | Document the first-run time; cache in HF_HOME; import is lazy |
| Parakeet model download on first run is ~2 GB | Document the first-run time; cache in HF_HOME; consider pre-downloading in `download_models.py` |
| GPU OOM under concurrent streams | `max_concurrent_streams: int = 16` semaphore; return 503 with clear error |
| Browser mic permission denied | Show toast + permission prompt, not silent fail |
| Wake word + Parakeet double-open mic on Tauri | Parakeet uses backend mic (already opened by Porcupine), Tauri `getUserMedia` not called |
| Tailscale mic capture latency | Document expected latency (~50-200 ms over LAN); Parakeet WS service has 5 s left context to absorb |
| Existing faster-whisper regression | `VoiceCommandHandler._transcribe_via_parakeet_service` falls back to local Whisper on Parakeet failure |
| Pocket-TTS terms-of-use prompt | Already handled by `_load_pocket_tts` fallback to `alba` voice (tts.py) |

---

## 10. Definition of done

A feature is done when **all** of the following are true:

- [ ] All 7 PRs merged
- [ ] All tests in §6.1 (unit) green
- [ ] All tests in §6.3 (E2E) green on CI
- [ ] All tests in §6.2 (integration) green on a 3070-equipped runner
- [ ] All items in §6.4 (manual checklist) green on user's 3070
- [ ] All items in §6.5 (regression matrix) green
- [ ] Wake word path verified to work identically before and after
- [ ] No `voice_result` event lost across 5-minute soak test
- [ ] VRAM stays <2 GB throughout soak test
- [ ] `/api/chat` text path produces TTS (the original audit defect, now fixed)
- [ ] Orb returns to "idle" within 500 ms of TTS completion (the original audit defect, now fixed)
- [ ] No double-injection in 1000-message stress test (the original audit defect, now fixed)
- [ ] TTS word highlight matches TTS playback within 100 ms (the original audit defect, now fixed)

The build is complete when all production domains in `bootstrap/GOALS.md` (if present) show green AND the application receives voice input and produces voice output end-to-end.
