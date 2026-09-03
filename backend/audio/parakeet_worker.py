"""
Parakeet ASR worker — runs in a SUBPROCESS so GIL-bound model loading and
inference never starve the main asyncio event loop.

Protocol (stdin/stdout JSONL, one JSON object per line):
  → {"action": "transcribe", "audio": "<base64 float32 PCM>", "sample_rate": 16000}
  ← {"text": "transcribed text", "error": null}
  ← {"text": "", "error": "error message"}

  → {"action": "ping"}
  ← {"status": "ready"}   or   {"status": "loading"}

  → {"action": "shutdown"}
  ← (process exits cleanly)

The worker sends {"status": "ready"} on stdout as soon as the model is loaded.
Until then, it responds to ping with {"status": "loading"} and to transcribe
with {"text": "", "error": "model not ready"}.

All diagnostic logging goes to stderr so it never contaminates the JSONL
protocol on stdout.
"""

# ── Offline Hub (REQ-1) ────────────────────────────────────────────────────
# The model is expected to be cached locally (the primary load path uses
# local_files_only=True). Setting HF_HUB_OFFLINE=1 makes the fallback path
# offline too, so a transient network blip can never trigger a surprise
# multi-GB download mid-load.
import os as _os

_os.environ.setdefault("HF_HUB_OFFLINE", "1")

import base64
import json
import logging
import os
import sys
import threading
import time
import traceback
from pathlib import Path

import numpy as np

# ── Logging to stderr ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[parakeet-worker] %(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("parakeet_worker")


# ── Paths ──────────────────────────────────────────────────────────────────
# Repo root = parents[3] of this file (backend/audio/parakeet_worker.py).
_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
# Pre-converted fp16 cache (see scripts/convert_parakeet_fp16.py). Loading the
# fp16 safetensors directly (~1.2 GB) is far faster than reading the 2.39 GB
# fp32 checkpoint and converting at load time.
_FP16_CACHE = _PROJECT_DIR / "data" / "models" / "parakeet-fp16"


# ── Model singleton ───────────────────────────────────────────────────────
_model = None
_processor = None
_load_error = None

# REQ-1 AC1.6: idle-exit timeout. If no transcription request arrives for this
# long, the worker shuts itself down cleanly so the parent can reclaim GPU VRAM
# and host RAM until the next voice activation. The parent treats an idle exit
# as a clean stop (not a crash) and respawns lazily on the next utterance.
_IDLE_TIMEOUT_S: float = 1200.0
_last_activity: float = 0.0


def _load_model() -> None:
    """Load ParakeetForTDT + AutoProcessor. Called once at startup.

    Loads weights DIRECTLY onto GPU via accelerate's device_map so no CPU-side
    weight copy is retained. ``low_cpu_mem_usage`` is deliberately NOT set: it
    routes through accelerate's slow mmap dispatch (measured ~13 min for this
    0.6B model). Since Parakeet loads lazily (not at boot), the transient CPU
    memory during load does not affect idle memory, so the fast direct-GPU path
    is the right tradeoff.
    """
    global _model, _processor, _load_error
    try:
        logger.info("Loading Parakeet TDT model (GPU fp16)...")
        import torch
        import gc as _gc
        from transformers import AutoProcessor, ParakeetForTDT

        model_name = "nvidia/parakeet-tdt-0.6b-v3"
        load_kwargs = {
            "torch_dtype": torch.float16,
        }

        # ── Pre-converted fp16 cache (fast path) ─────────────────────────
        # If scripts/convert_parakeet_fp16.py has run, load the fp16 safetensors
        # directly (~1.2 GB, no fp32->fp16 conversion) — far faster than reading
        # the 2.39 GB fp32 checkpoint.
        if (_FP16_CACHE / "model.safetensors").exists():
            logger.info("Loading pre-converted fp16 cache: %s", _FP16_CACHE)
            processor = AutoProcessor.from_pretrained(
                str(_FP16_CACHE), local_files_only=True
            )
            try:
                model = ParakeetForTDT.from_pretrained(
                    str(_FP16_CACHE), local_files_only=True,
                    device_map="cuda:0", **load_kwargs,
                )
            except (TypeError, ValueError):
                model = ParakeetForTDT.from_pretrained(
                    str(_FP16_CACHE), local_files_only=True, **load_kwargs
                )
                model.to("cuda")
        else:
            # ── HF cache fallback (original path) ────────────────────────
            try:
                processor = AutoProcessor.from_pretrained(
                    model_name, local_files_only=True
                )
                # Load directly onto GPU via device_map so weights never sit on CPU.
                # accelerate is always installed alongside transformers.
                try:
                    load_kwargs["device_map"] = "cuda:0"
                    model = ParakeetForTDT.from_pretrained(
                        model_name, local_files_only=True, **load_kwargs
                    )
                except (TypeError, ValueError):
                    # device_map not supported by this model class — fall back to
                    # CPU load + .to("cuda") + aggressive cache purge.
                    logger.warning(
                        "device_map not supported, falling back to CPU load + purge"
                    )
                    model = ParakeetForTDT.from_pretrained(
                        model_name, local_files_only=True, **load_kwargs
                    )
                    model.to("cuda")
            except (OSError, ValueError):
                logger.warning(
                    "Local cache miss — fetching %s from HuggingFace Hub", model_name
                )
                processor = AutoProcessor.from_pretrained(model_name)
                try:
                    model = ParakeetForTDT.from_pretrained(
                        model_name, device_map="cuda:0", **load_kwargs
                    )
                except (TypeError, ValueError):
                    model = ParakeetForTDT.from_pretrained(
                        model_name, **load_kwargs
                    )
                    model.to("cuda")

        model.eval()

        # ── Aggressive cache purge ──────────────────────────────────────
        # Even with device_map, the HuggingFace loading machinery retains
        # intermediate tensors in the process's private memory.  Force a
        # full GC cycle and CUDA cache compaction to release them.
        _gc.collect()
        torch.cuda.empty_cache()
        _gc.collect()

        # REQ-1: compact the working set after load. Even with device_map, the
        # HF loading machinery retains intermediate tensors in private memory;
        # EmptyWorkingSet forces the OS to reclaim the freed pages.
        try:
            from backend.utils.memory_trim import trim_working_set

            trim_working_set()
        except Exception as _trim_exc:  # noqa: BLE001 — trim must never fail load
            logger.debug("Working set trim skipped: %s", _trim_exc)

        _model = model
        _processor = processor
        logger.info("Parakeet model loaded successfully (GPU fp16)")
    except Exception as exc:
        _load_error = exc
        logger.error(
            "Failed to load Parakeet model: %s\n%s",
            exc,
            traceback.format_exc(),
        )


def _transcribe(audio_np: np.ndarray, sample_rate: int) -> str:
    """Run inference on the loaded model. Must be called after _load_model."""
    global _model, _processor
    if _model is None or _processor is None:
        raise RuntimeError("Model not loaded")

    import torch

    pcm_int16 = (audio_np * 32767.0).clip(-32768, 32767).astype(np.int16)

    inputs = _processor(
        audio=pcm_int16,
        sampling_rate=sample_rate,
        return_tensors="pt",
    )

    _dtype = next(_model.parameters()).dtype
    input_features = inputs.input_features.to(dtype=_dtype, device="cuda")
    attention_mask = (
        inputs.attention_mask.to(dtype=_dtype, device="cuda")
        if hasattr(inputs, "attention_mask")
        else None
    )

    with torch.no_grad():
        output = _model.generate(
            input_features=input_features,
            attention_mask=attention_mask,
            max_new_tokens=256,
        )
        generated_ids = (
            output.sequences if hasattr(output, "sequences") else output
        )

    if hasattr(_processor, "tokenizer"):
        text = _processor.tokenizer.decode(
            generated_ids[0], skip_special_tokens=True
        ).strip()
    else:
        text = _processor.batch_decode(generated_ids)[0].strip()

    return text


# ── Main loop ─────────────────────────────────────────────────────────────

def main() -> None:
    """Read JSONL commands from stdin, write JSONL responses to stdout."""
    logger.info("Parakeet worker starting — loading model...")

    # Send loading status immediately so the parent knows we're alive
    print(json.dumps({"status": "loading"}), flush=True)

    _load_model()

    if _load_error is not None:
        # Model failed to load — report and exit. The parent will restart us
        # or fall back to faster-whisper permanently.
        print(
            json.dumps({"status": "error", "error": str(_load_error)}),
            flush=True,
        )
        logger.error("Worker exiting due to load failure")
        sys.exit(1)

    print(json.dumps({"status": "ready"}), flush=True)
    logger.info("Parakeet worker ready — listening for transcription requests")

    # ── Idle-exit watchdog (REQ-1 AC1.6) ─────────────────────────────────
    # The command loop below blocks on sys.stdin.readline(), so it cannot
    # self-timeout. A daemon watchdog tracks the last request time and, after
    # _IDLE_TIMEOUT_S of inactivity, emits a clean shutdown notice and exits so
    # the parent can reclaim GPU VRAM + host RAM until the next activation.
    global _last_activity
    _last_activity = time.monotonic()

    def _idle_watchdog() -> None:
        while True:
            time.sleep(5.0)
            if time.monotonic() - _last_activity >= _IDLE_TIMEOUT_S:
                logger.info(
                    "Idle for %.0fs — shutting down cleanly (REQ-1 AC1.6)",
                    _IDLE_TIMEOUT_S,
                )
                print(
                    json.dumps({"status": "shutting_down", "reason": "idle"}),
                    flush=True,
                )
                _os._exit(0)

    threading.Thread(target=_idle_watchdog, daemon=True, name="parakeet-idle").start()

    # ── Command loop ──────────────────────────────────────────────────────
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON on stdin: %s", exc)
            print(json.dumps({"text": "", "error": f"invalid json: {exc}"}), flush=True)
            continue

        action = request.get("action", "")
        _last_activity = time.monotonic()

        if action == "ping":
            print(json.dumps({"status": "ready"}), flush=True)

        elif action == "transcribe":
            try:
                audio_b64 = request.get("audio", "")
                if not audio_b64:
                    print(
                        json.dumps({"text": "", "error": "missing audio field"}),
                        flush=True,
                    )
                    continue

                audio_bytes = base64.b64decode(audio_b64)
                audio_np = np.frombuffer(audio_bytes, dtype=np.float32)
                sample_rate = request.get("sample_rate", 16000)

                text = _transcribe(audio_np, sample_rate)
                print(json.dumps({"text": text, "error": None}), flush=True)
                if text:
                    logger.info("Transcribed: '%s'", text[:80])
                else:
                    logger.info("Transcription returned empty text")

            except Exception as exc:
                logger.error("Transcription error: %s", exc)
                print(
                    json.dumps({"text": "", "error": str(exc)}),
                    flush=True,
                )

        elif action == "shutdown":
            logger.info("Worker shutting down")
            print(json.dumps({"status": "shutting_down"}), flush=True)
            break

        else:
            logger.warning("Unknown action: %s", action)
            print(
                json.dumps({"text": "", "error": f"unknown action: {action}"}),
                flush=True,
            )

    logger.info("Worker exited")


if __name__ == "__main__":
    main()