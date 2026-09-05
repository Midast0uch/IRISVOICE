"""Parakeet sherpa-onnx worker — runs in a SUBPROCESS.

Why a subprocess (2026-09-03): the backend process preloads PyPI
``onnxruntime`` for the wake-word backbone, and Windows resolves the
sherpa-bundled CUDA provider against the already-loaded (incompatible)
build — provider load fails. A dedicated worker owns exactly one ORT, so
no present or future package upgrade can re-break GPU STT. The worker
never imports torch: cuDNN is located via ``importlib`` path probing
(parent also prepends it to PATH at spawn).

Protocol (stdin/stdout JSONL, one JSON object per line):
  → {"action": "transcribe", "audio": "<base64 float32 PCM>", "sample_rate": 16000}
  ← {"text": "...", "timestamps": [...], "error": null}
  ← {"text": "", "timestamps": [], "error": "message"}
  → {"action": "ping"}
  ← {"status": "ready"}   or   {"status": "loading"}
  → {"action": "shutdown"}
  ← (process exits cleanly)

``{"status": "ready"}`` is emitted once the recognizer is built; a warm-up
decode runs right after so the first live utterance never pays kernel
init. Idle-exit after ``_IDLE_TIMEOUT_S`` with no requests emits
``{"status": "shutting_down"}`` so the parent reclaims VRAM/RAM and
rebuilds lazily (REQ-1 AC1.6).

All diagnostics go to stderr; stdout carries protocol only.
"""

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

logging.basicConfig(
    level=logging.INFO,
    format="[parakeet-sherpa-worker] %(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("parakeet_sherpa_worker")

_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_DIR))

_IDLE_TIMEOUT_S: float = 1200.0
_last_activity: float = time.monotonic()

_recognizer = None
_recognizer_provider = ""


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _note_activity() -> None:
    global _last_activity
    _last_activity = time.monotonic()


def _idle_watchdog() -> None:
    """Exit cleanly after 20 min with no requests (daemon thread)."""
    while True:
        time.sleep(30)
        try:
            if time.monotonic() - _last_activity > _IDLE_TIMEOUT_S:
                logger.info("idle timeout — shutting down (VRAM reclaim)")
                _send({"status": "shutting_down"})
                sys.stdout.flush()
                os._exit(0)
        except Exception:
            return


def _load() -> None:
    """Build the recognizer via the shared factory (lazy inside worker)."""
    global _recognizer, _recognizer_provider
    from backend.audio import parakeet_sherpa as _ps

    logger.info("building recognizer (provider=%s)...", _ps.PROVIDER)
    _recognizer, _recognizer_provider = _ps.build_recognizer()
    _note_activity()
    logger.info("recognizer built (provider=%s)", _recognizer_provider)
    _send({"status": "ready"})


def _warm_up() -> None:
    """One silent decode so live utterances never pay kernel init."""
    try:
        silence = np.zeros(16000, dtype=np.float32)
        stream = _recognizer.create_stream()
        stream.accept_waveform(16000, silence)
        _recognizer.decode_stream(stream)
        logger.info("warm-up decode complete")
    except Exception as exc:
        logger.warning("warm-up decode failed (non-fatal): %s", exc)


def _do_transcribe(payload: dict) -> dict:
    _note_activity()
    if _recognizer is None:
        return {"text": "", "timestamps": [], "error": "model not ready"}
    try:
        raw = base64.b64decode(payload.get("audio", ""))
        audio = np.frombuffer(raw, dtype=np.float32).astype(np.float32, copy=True)
        sample_rate = int(payload.get("sample_rate", 16000) or 16000)
        stream = _recognizer.create_stream()
        stream.accept_waveform(sample_rate, audio)
        _recognizer.decode_stream(stream)
        result = stream.result
        try:
            stamps = [float(t) for t in (result.timestamps or [])]
        except Exception:
            stamps = []
        text = str(result.text).strip()
        logger.info("transcribed %ds audio -> %r", len(audio) // sample_rate, text[:80])
        return {"text": text, "timestamps": stamps, "error": None}
    except Exception as exc:
        logger.error("transcription failed: %s", exc)
        return {"text": "", "timestamps": [], "error": str(exc)[:300]}


def main() -> int:
    try:
        _load()
    except Exception as exc:
        logger.error("model load failed: %s", exc)
        traceback.print_exc()
        _send({"status": "error", "error": str(exc)[:300]})
        return 1
    _warm_up()

    threading.Thread(target=_idle_watchdog, daemon=True, name="sherpa-idle").start()
    logger.info("listening for transcription requests")
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            action = msg.get("action", "")
            if action == "transcribe":
                _send(_do_transcribe(msg))
            elif action == "ping":
                _send({"status": "ready" if _recognizer is not None else "loading"})
            elif action == "shutdown":
                break
            else:
                _send({"text": "", "timestamps": [], "error": f"unknown action {action!r}"})
    except KeyboardInterrupt:
        # Ctrl+C reaches the whole process group: the parent is shutting
        # down too. Exit quietly instead of dumping a traceback — there is
        # no in-flight state worth preserving (stateless worker).
        logger.info("worker interrupted (parent shutting down)")
    logger.info("worker exiting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
