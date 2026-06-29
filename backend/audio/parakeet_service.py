"""
Parakeet ASR Service — NVIDIA NeMo TDT 0.6B v3 on local RTX 3070.

This is the **sole ASR backend** for both the Tauri widget and the web
browser.  Audio capture happens on the client side (Tauri command or
browser MediaRecorder), PCM is streamed here as 80 ms int16 mono 16 kHz
chunks, and the response carries partial and final hypotheses as JSON.

Two transports:

    WebSocket /ws/stream    Binary PCM chunks → JSON partial/final events
    POST    /transcribe     Full-utterance raw PCM body → JSON result

Plus diagnostics:

    GET     /healthz        liveness + model readiness + VRAM
    GET     /metrics        request counts + p50/p95/p99 latency (PR 7)

The NeMo import is **lazy** so the test suite can import this module
without the (heavy) NeMo dependency installed.  Calling `main()` or
hitting any endpoint that needs the model will surface a clear error.

Memory budget (RTX 3070, 8 GB):

    fp32 model       ~2.4 GB   (not recommended)
    fp16 model       ~1.2 GB   (default)
    int8 model       ~0.6 GB   (--quantize, opt-in)

Latency target (RTX 3070):

    First partial    <300 ms after end of utterance
    End-to-end       <500 ms for 3 s utterance
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from collections import deque
from math import floor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import torch
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect

# Lazy import — only the WS endpoint and the /transcribe route actually
# need the model.  This keeps unit tests fast.
try:
    from nemo.collections.asr.models import ASRModel  # noqa: F401  (lazy)
    _NEMO_AVAILABLE = True
except ImportError:
    _NEMO_AVAILABLE = False

from .parakeet_buffer import Hypothesis, ParakeetStreamingBuffer

logger = logging.getLogger("parakeet_service")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "nvidia/parakeet-tdt-0.6b-v3"
SAMPLE_RATE = 16_000                       # Hz — fixed
BYTES_PER_SAMPLE = 2                       # int16
CHUNK_MS_DEFAULT = 80                      # 1280 samples per chunk
MAX_TRANSCRIBE_SECONDS = 60.0
MAX_CONCURRENT_STREAMS = 16

import threading

# Server is "ready" when the model is loaded into app.state
_READY = False
_MODEL = None
# Threading lock protects the model singleton across the WS / REST paths.
# Model load runs in the thread executor, so asyncio.Lock won't work here.
_MODEL_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ServiceConfig:
    model_name: str = DEFAULT_MODEL
    device: str = "cuda"                       # "cuda" | "cpu"
    precision: str = "fp16"                    # "fp16" | "int8" | "fp32"
    port: int = 8765
    host: str = "0.0.0.0"
    max_concurrent_streams: int = MAX_CONCURRENT_STREAMS
    chunk_secs: float = 0.08
    left_context_secs: float = 5.0
    right_context_secs: float = 0.5
    started_at: float = field(default_factory=time.monotonic)

    def as_dict(self) -> dict:
        return {
            "model_name": self.model_name,
            "device": self.device,
            "precision": self.precision,
            "chunk_secs": self.chunk_secs,
            "left_context_secs": self.left_context_secs,
            "right_context_secs": self.right_context_secs,
        }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

LATENCY_HISTORY = 10_000


@dataclass
class ServiceMetrics:
    """Service-level metrics with rolling latency distribution for percentiles.

    Tracks request counts, WebSocket connections, errors, and a rolling
    window of decode latencies (max LATENCY_HISTORY entries) so that
    /metrics can report p50 / p95 / p99 without unbounded memory growth.
    """

    started_at: float = field(default_factory=time.monotonic)
    requests_total: int = 0
    ws_connections_total: int = 0
    ws_connections_active: int = 0
    rest_transcribe_total: int = 0
    errors_total: int = 0
    last_latency_ms: float = 0.0
    _latencies: deque[float] = field(default_factory=lambda: deque(maxlen=LATENCY_HISTORY))

    def record_latency(self, ms: float) -> None:
        """Record a decode latency (ms) into the rolling window."""
        self._latencies.append(ms)
        self.last_latency_ms = ms

    def _percentile(self, p: float) -> float:
        """Return the p-th percentile from the rolling latency window."""
        if not self._latencies:
            return 0.0
        sorted_vals = sorted(self._latencies)
        idx = max(0, min(len(sorted_vals) - 1, floor(len(sorted_vals) * p / 100.0)))
        return round(sorted_vals[idx], 1)

    def as_dict(self) -> dict:
        return {
            "uptime_s": time.monotonic() - self.started_at,
            "requests_total": self.requests_total,
            "ws_connections_total": self.ws_connections_total,
            "ws_connections_active": self.ws_connections_active,
            "rest_transcribe_total": self.rest_transcribe_total,
            "errors_total": self.errors_total,
            "last_latency_ms": self.last_latency_ms,
            "latency_p50_ms": self._percentile(50),
            "latency_p95_ms": self._percentile(95),
            "latency_p99_ms": self._percentile(99),
        }

    def as_prometheus_text(self) -> str:
        """Return metrics in Prometheus exposition format (default for /metrics).

        The text-format endpoint is meant for Prometheus scraping.  The JSON
        equivalent is available via ``GET /metrics?format=json``.
        """
        d = self.as_dict()
        lines = [
            "# HELP parakeet_uptime_seconds Service uptime in seconds",
            "# TYPE parakeet_uptime_seconds gauge",
            f"parakeet_uptime_seconds {d['uptime_s']}",
            "",
            "# HELP parakeet_requests_total Total HTTP requests processed",
            "# TYPE parakeet_requests_total counter",
            f"parakeet_requests_total {d['requests_total']}",
            "",
            "# HELP parakeet_ws_connections_total Total WebSocket connections",
            "# TYPE parakeet_ws_connections_total counter",
            f"parakeet_ws_connections_total {d['ws_connections_total']}",
            "",
            "# HELP parakeet_ws_connections_active Currently active streams",
            "# TYPE parakeet_ws_connections_active gauge",
            f"parakeet_ws_connections_active {d['ws_connections_active']}",
            "",
            "# HELP parakeet_rest_transcribe_total REST /transcribe calls",
            "# TYPE parakeet_rest_transcribe_total counter",
            f"parakeet_rest_transcribe_total {d['rest_transcribe_total']}",
            "",
            "# HELP parakeet_errors_total Total errors encountered",
            "# TYPE parakeet_errors_total counter",
            f"parakeet_errors_total {d['errors_total']}",
            "",
            "# HELP parakeet_decode_latency_milliseconds Decode latency distribution",
            "# TYPE parakeet_decode_latency_milliseconds gauge",
            f'parakeet_decode_latency_p50_ms {d["latency_p50_ms"]}',
            f'parakeet_decode_latency_p95_ms {d["latency_p95_ms"]}',
            f'parakeet_decode_latency_p99_ms {d["latency_p99_ms"]}',
        ]
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Model lifecycle
# ---------------------------------------------------------------------------

def _load_model(cfg: ServiceConfig) -> "ASRModel":  # type: ignore[name-defined]
    """
    Synchronous model loader.  Called once at startup.  Raises a clear
    error if NeMo isn't installed.
    """
    if not _NEMO_AVAILABLE:
        raise RuntimeError(
            "nemo_toolkit[asr] is not installed.  Run:\n"
            "  pip install 'nemo_toolkit[asr]>=2.4.0'\n"
            "Then start the service again."
        )
    if cfg.device == "cuda" and not torch.cuda.is_available():
        logger.warning(
            "Requested device=cuda but torch.cuda.is_available() is False. "
            "Falling back to CPU."
        )
        cfg.device = "cpu"

    logger.info("Loading model %s on %s (%s)", cfg.model_name, cfg.device, cfg.precision)
    t0 = time.monotonic()
    model = ASRModel.from_pretrained(cfg.model_name)  # type: ignore[name-defined]
    model = model.to(cfg.device)
    if cfg.precision == "fp16":
        model = model.half()
    elif cfg.precision == "int8":
        # PR 7 will add real int8 quantize() call.  For now we fall back
        # to fp32 rather than silently shipping a "quantized" model that
        # is actually full precision.
        logger.warning("int8 precision not implemented in PR 1; using fp32")
        cfg.precision = "fp32"
    model.eval()
    elapsed = time.monotonic() - t0
    logger.info("Model loaded in %.1f s", elapsed)
    return model


# ---------------------------------------------------------------------------
# Decoder functions
# ---------------------------------------------------------------------------

def make_ne_mo_decoder(model, device: str) -> "callable":
    """
    Returns a decoder function compatible with ParakeetStreamingBuffer.

    The decoder is invoked on every push() with a context ndarray and an
    is_final flag.  It must return a Hypothesis or None.

    Throttling: full-context decode only runs every 10 pushes (~800 ms at
    80 ms chunks).  Intermediate pushes return None (no partial result).
    On final (flush), the decode always runs.  This reduces the GPU decode
    load by ∼10× compared to decoding every 80 ms push.
    """
    import itertools
    _counter = itertools.count()

    def _decode(context: np.ndarray, is_final: bool) -> Optional[Hypothesis]:
        # Throttle: skip all but every 10th push for non-final decodes
        if not is_final and next(_counter) % 10 != 0:
            return None

        # Skip empty / silent input
        if context.size < SAMPLE_RATE // 4:  # < 250 ms
            return None
        # RMS check — avoid transcribing pure silence
        rms = float(np.sqrt(np.mean(context ** 2)))
        if rms < 1e-4:
            return None
        try:
            with torch.inference_mode():
                tensor = torch.from_numpy(context).unsqueeze(0).to(device)
                if next(model.parameters()).dtype == torch.float16:
                    tensor = tensor.half()
                result = model.transcribe(tensor, return_hypotheses=True)
            hyp = result[0]
            text = hyp.text if hasattr(hyp, "text") else str(hyp)
            # TDT hypotheses carry a confidence score; fall back to 1.0 if missing
            conf = float(getattr(hyp, "score", 1.0) or 1.0)
            return Hypothesis(text=text.strip(), confidence=conf)
        except Exception as e:
            logger.exception("Decode failed: %s", e)
            return None
    return _decode


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load model on startup, free VRAM on shutdown."""
    cfg: ServiceConfig = app.state.config
    metrics: ServiceMetrics = app.state.metrics
    semaphore: asyncio.Semaphore = app.state.stream_semaphore

    # Run model load in a thread to avoid blocking startup
    loop = asyncio.get_event_loop()
    try:
        model = await loop.run_in_executor(None, _load_model, cfg)
    except Exception as e:
        logger.error("Model load failed: %s", e)
        # Don't crash — healthz will report model_loaded=false and
        # the service can still respond to /healthz.
        app.state.model = None
        yield
        return

    app.state.model = model
    app.state.decoder = make_ne_mo_decoder(model, cfg.device)
    if torch.cuda.is_available():
        vram = torch.cuda.memory_allocated() / 1024 ** 2
        logger.info("VRAM in use after load: %.1f MB", vram)

    try:
        yield
    finally:
        logger.info("Unloading model...")
        app.state.model = None
        app.state.decoder = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("Service shut down cleanly after %.1f s",
                    time.monotonic() - metrics.started_at)


def create_app(config: Optional[ServiceConfig] = None) -> FastAPI:
    """Factory so tests can spin up an app with a mocked config."""
    cfg = config or ServiceConfig()
    app = FastAPI(
        title="IRIS Parakeet ASR Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.config = cfg
    app.state.metrics = ServiceMetrics()
    app.state.model = None
    app.state.decoder = None
    app.state.stream_semaphore = asyncio.Semaphore(cfg.max_concurrent_streams)

    # ----- Routes ---------------------------------------------------- #

    @app.get("/healthz")
    async def healthz():
        cfg: ServiceConfig = app.state.config
        metrics: ServiceMetrics = app.state.metrics
        ready = app.state.model is not None
        vram_mb = 0.0
        if ready and torch.cuda.is_available() and cfg.device == "cuda":
            vram_mb = torch.cuda.memory_allocated() / 1024 ** 2
        body = {
            "status": "ok" if ready else "loading",
            "model_loaded": ready,
            "device": cfg.device,
            "precision": cfg.precision,
            "model_name": cfg.model_name,
            "vram_mb": vram_mb,
            "uptime_s": time.monotonic() - metrics.started_at,
        }
        return body if ready else _JSON_503(body)

    @app.get("/metrics")
    async def metrics(format: str = "prometheus"):
        """Service metrics in Prometheus text format (default) or JSON.

        Usage:
          GET /metrics               — Prometheus text (default)
          GET /metrics?format=json   — JSON object
          GET /metrics?format=prometheus  — explicit text
        """
        m = app.state.metrics
        if format == "json":
            return m.as_dict()
        # Prometheus text format
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=m.as_prometheus_text())

    @app.websocket("/ws/stream")
    async def ws_stream(ws: WebSocket):
        await ws.accept()
        cfg: ServiceConfig = app.state.config
        metrics: ServiceMetrics = app.state.metrics

        if app.state.model is None:
            await ws.send_json({"type": "error", "error": "model_not_loaded"})
            await ws.close(code=1011)
            return

        semaphore: asyncio.Semaphore = app.state.stream_semaphore
        await semaphore.acquire()
        metrics.ws_connections_total += 1
        metrics.ws_connections_active += 1
        try:
            buffer = ParakeetStreamingBuffer(
                decoder=app.state.decoder,
                sample_rate=SAMPLE_RATE,
                chunk_secs=cfg.chunk_secs,
                left_context_secs=cfg.left_context_secs,
                right_context_secs=cfg.right_context_secs,
            )
            await ws.send_json({"type": "ready", "sample_rate": SAMPLE_RATE})

            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break

                if "bytes" in msg:
                    raw = msg["bytes"]
                    if len(raw) % BYTES_PER_SAMPLE != 0:
                        logger.warning("WS chunk has odd byte count: %d — dropping", len(raw))
                        metrics.errors_total += 1
                        continue

                    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                    t0 = time.monotonic()
                    partial = buffer.push(samples)
                    metrics.record_latency((time.monotonic() - t0) * 1000.0)

                    if partial is not None and partial.text:
                        await ws.send_json({
                            "type": "partial",
                            "text": partial.text,
                            "confidence": partial.confidence,
                            "ts": partial.timestamp,
                        })
                elif "text" in msg:
                    try:
                        text_data = json.loads(msg["text"])
                        if text_data.get("type") == "stop":
                            logger.debug("WS stream received graceful stop signal")
                            break
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.exception("WS stream error: %s", e)
            metrics.errors_total += 1
            try:
                await ws.send_json({"type": "error", "error": str(e)})
                await ws.close(code=1011)
            except Exception:
                pass
        finally:
            # Flush on disconnect
            try:
                final = buffer.flush() if 'buffer' in locals() else None
                if final is not None and final.text.strip():
                    await ws.send_json({
                        "type": "final",
                        "text": final.text,
                        "confidence": final.confidence,
                        "ts": final.timestamp,
                    })
            except Exception:
                pass
            try:
                await ws.close()
            except Exception:
                pass
            metrics.ws_connections_active -= 1
            semaphore.release()

    @app.post("/transcribe")
    async def rest_transcribe(body: bytes = Body(default=b"", media_type="application/octet-stream")):
        cfg: ServiceConfig = app.state.config
        metrics: ServiceMetrics = app.state.metrics
        metrics.requests_total += 1

        if app.state.model is None:
            raise HTTPException(503, "model not loaded")
        if not body:
            raise HTTPException(400, "empty body")
        if len(body) % BYTES_PER_SAMPLE != 0:
            raise HTTPException(400, "body must be int16 PCM (even byte count)")

        samples = np.frombuffer(body, dtype=np.int16).astype(np.float32) / 32768.0
        duration_s = samples.size / SAMPLE_RATE
        if duration_s > MAX_TRANSCRIBE_SECONDS:
            raise HTTPException(
                400,
                f"max {MAX_TRANSCRIBE_SECONDS:.0f}s per request, got {duration_s:.1f}s"
            )

        t0 = time.monotonic()
        loop = asyncio.get_event_loop()
        hyp = await loop.run_in_executor(None, app.state.decoder, samples, True)
        metrics.record_latency((time.monotonic() - t0) * 1000.0)
        if hyp is None:
            metrics.rest_transcribe_total += 1
            return {"text": "", "language": "auto", "duration_s": duration_s, "confidence": 0.0}

        metrics.rest_transcribe_total += 1
        return {
            "text": hyp.text.strip(),
            "language": "auto",
            "duration_s": duration_s,
            "confidence": hyp.confidence,
        }

    return app


def _JSON_503(body: dict) -> "Response":  # type: ignore[name-defined]
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content=body)


# Module-level app for `uvicorn parakeet_service:app` — uses default config
app = create_app()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="IRIS Parakeet ASR Service (NVIDIA NeMo TDT on local GPU)"
    )
    parser.add_argument("--host", default=os.environ.get("PARAKEET_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PARAKEET_PORT", "8765")))
    parser.add_argument("--device", default=os.environ.get("PARAKEET_DEVICE", "cuda"),
                        choices=["cuda", "cpu"])
    parser.add_argument("--precision", default=os.environ.get("PARAKEET_PRECISION", "fp16"),
                        choices=["fp16", "int8", "fp32"])
    parser.add_argument("--model", default=os.environ.get("PARAKEET_MODEL", DEFAULT_MODEL))
    parser.add_argument("--max-streams", type=int, default=MAX_CONCURRENT_STREAMS)
    parser.add_argument("--chunk-secs", type=float, default=CHUNK_MS_DEFAULT / 1000.0)
    parser.add_argument("--left-context-secs", type=float, default=5.0)
    parser.add_argument("--log-level", default=os.environ.get("PARAKEET_LOG", "info"))
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    )

    cfg = ServiceConfig(
        model_name=args.model,
        device=args.device,
        precision=args.precision,
        port=args.port,
        host=args.host,
        max_concurrent_streams=args.max_streams,
        chunk_secs=args.chunk_secs,
        left_context_secs=args.left_context_secs,
    )
    application = create_app(cfg)
    import uvicorn
    logger.info("Starting IRIS Parakeet ASR Service on %s:%d (model=%s, device=%s, precision=%s)",
                cfg.host, cfg.port, cfg.model_name, cfg.device, cfg.precision)
    uvicorn.run(application, host=cfg.host, port=cfg.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
