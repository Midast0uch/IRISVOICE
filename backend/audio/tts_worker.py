"""
Pocket-TTS worker — runs in a SUBPROCESS so GIL-bound model loading and
streaming synthesis never starve the main asyncio event loop.

Protocol (stdin/stdout JSONL, one JSON object per line):
  → {"action": "load", "language": "english", "voice": "Cloned Voice"}
  ← {"status": "ready", "duration_s": 12.4}

  → {"action": "synthesize", "text": "Hello world", "id": 1}
  ← {"type": "chunk", "id": 1, "data": "<base64 float32 PCM>", "sample_rate": 24000}
  ← {"type": "done", "id": 1, "total_samples": 48000, "duration_s": 2.0}
  ← {"type": "error", "id": 1, "error": "message"}

  → {"action": "set_voice", "voice": "alba"}
  ← {"status": "voice_loaded", "voice": "alba", "duration_s": 3.1}

  → {"action": "synthesize_and_hold", "text": "Short beat", "id": 7}
  ← {"type": "held", "id": 7, "data": "<base64 f32>", "samples": N,
     "duration_s": s}
  (same audio "synthesize" would stream, one message; the parent holds the
  buffer and frees it on every exit path)

  → {"action": "pre_synthesize_fillers"}
  ← {"status": "fillers_ready", "count": 5}

  → {"action": "ping"}
  ← {"status": "ready"}   or   {"status": "loading"}

  → {"action": "shutdown"}
  ← (process exits cleanly)

The worker sends {"status": "ready"} on stdout as soon as the model + voice
state are loaded. All diagnostic logging goes to stderr so it never
contaminates the JSONL protocol on stdout.
"""

# ── CUDA masking (REQ-5 AC5.1) ─────────────────────────────────────────────
# Pocket-TTS is a strictly CPU-bound model. Probing and initialising CUDA
# contexts (runtime DLLs, contexts, caching allocators) wasted ~1.4 GB of
# private memory in this worker. Mask CUDA BEFORE any import that could
# transitively load torch, so torch.cuda.is_available() is False and no CUDA
# runtime is ever initialised.
import os as _os

_os.environ["CUDA_VISIBLE_DEVICES"] = ""

import base64
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np

# ── Logging to stderr ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[tts-worker] %(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("tts_worker")

# ── Constants (mirror backend/agent/tts.py) ───────────────────────────────
OUTPUT_SAMPLE_RATE: int = 24_000
_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
REFERENCE_AUDIO = _PROJECT_DIR / "data" / "TOMV2.wav"

# ── Model singleton ───────────────────────────────────────────────────────
_model = None
_voice_state = None
_load_error = None
_voice_name = "Cloned Voice"


# ── Voice-state disk cache (REQ-28: kill the ~10s per-boot re-encode) ────
# The TOMV2 reference encode is deterministic for a given (audio bytes,
# language): same bytes in → same state out. Cache the computed state with
# torch.save keyed by sha256(ref_bytes + language); on a hash hit the load
# path skips the encode entirely. Any failure (missing torch, corrupt file,
# unserializable state) falls back to computing fresh — the cache can never
# break a load.
_VOICE_CACHE_DIR = _PROJECT_DIR / "data" / "tts_voice_cache"


def _voice_cache_key(ref_path: Path, language: str) -> str:
    import hashlib

    h = hashlib.sha256()
    h.update(ref_path.read_bytes())
    h.update(b"\0" + language.encode("utf-8"))
    return h.hexdigest()[:16]


def _load_cached_voice_state(key: str):
    try:
        import torch

        path = _VOICE_CACHE_DIR / f"voice_state_{key}.pt"
        if not path.exists():
            return None
        t0 = time.monotonic()
        state = torch.load(str(path), map_location="cpu", weights_only=True)
        logger.info(
            "Voice state loaded from cache in %.1fs", time.monotonic() - t0
        )
        return state
    except Exception as exc:  # noqa: BLE001 — stale/corrupt cache recomputes
        logger.info(
            "Voice cache miss/invalid (%s); recomputing", type(exc).__name__
        )
        try:
            (_VOICE_CACHE_DIR / f"voice_state_{key}.pt").unlink(missing_ok=True)
        except Exception:
            pass
        return None


def _save_cached_voice_state(key: str, state) -> None:
    try:
        import torch

        _VOICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _VOICE_CACHE_DIR / f"voice_state_{key}.pt.tmp"
        torch.save(state, str(tmp))
        os.replace(tmp, _VOICE_CACHE_DIR / f"voice_state_{key}.pt")
        logger.info("Voice state cached for next boot")
    except Exception as exc:  # noqa: BLE001 — cache is best-effort only
        logger.debug("Voice cache save skipped: %s", exc)


def _compact_heap() -> None:
    """Return post-synthesis scratch to the OS (REQ-28 AC28.2/AC28.4).

    The encode spike lives in native (malloc) arenas that the allocator
    retains after free — committed bytes that are never touched again. Order
    matters: collect Python garbage first (releases the malloc blocks it
    held), then ask the CRT to decommit fully-free heap segments
    (``_heapmin`` — the call Windows itself provides for this), then trim
    the working set so resident pages follow. Best-effort throughout: a
    compact failure must never fail a synthesis that already succeeded.
    """
    try:
        import gc

        gc.collect()
    except Exception:
        pass
    try:
        import ctypes

        _heapmin = ctypes.CDLL("ucrtbase.dll")._heapmin
        _heapmin.restype = ctypes.c_int
        _heapmin.argtypes = []
        logger.debug("ucrt _heapmin -> %s", _heapmin())
    except Exception as exc:  # noqa: BLE001 — e.g. non-Windows CRT
        logger.debug("Heap decommit skipped: %s", exc)
    try:
        from backend.utils.memory_trim import trim_working_set

        trim_working_set()
    except Exception:
        pass


def _load_model(language: str = "english") -> None:
    """Load Pocket-TTS model + voice state. Called once at startup."""
    global _model, _voice_state, _load_error
    try:
        # Pocket-TTS v2.x applies beartype runtime type-checking to every
        # function at import time, which adds ~40s to the first import.
        # No-op it here — we don't need runtime type validation in production.
        try:
            import beartype.claw as _bt

            _bt.beartype_this_package = lambda **_: None
        except ImportError:
            pass

        from pocket_tts import TTSModel

        t0 = time.monotonic()
        # eos_threshold=-1.0 forces clean EOS termination (default -4.0 hits
        # max length with broken voice state, producing garbled tail).
        _model = TTSModel.load_model(
            language=language,
            eos_threshold=-1.0,
        )
        dt = time.monotonic() - t0
        logger.info("Pocket-TTS model loaded in %.1fs", dt)

        _load_voice_state()

        # REQ-5 AC5.3: compact the working set after model + voice-state load.
        # The safetensors heap buffers freed during load stay resident in the
        # working set until the OS reclaims them; EmptyWorkingSet forces that
        # reclaim, dropping this worker's private footprint (~2.3 GB -> ~0.9 GB).
        try:
            from backend.utils.memory_trim import trim_working_set

            trim_working_set()
        except Exception as _trim_exc:  # noqa: BLE001 — trim must never fail load
            logger.debug("Working set trim skipped: %s", _trim_exc)
    except Exception as exc:
        _load_error = exc
        logger.error(
            "Failed to load Pocket-TTS: %s\n%s", exc, traceback.format_exc()
        )


def _load_voice_state() -> None:
    """Load the appropriate voice state: cloned from TOMV2.wav or catalog voice."""
    global _voice_state
    if _model is None:
        return

    voice_name = _voice_name

    # Catalog voice path
    if voice_name in _PREDEFINED_VOICES:
        _load_catalog_voice(voice_name)
        return

    # Voice cloning path (Cloned Voice / default)
    ref_path = REFERENCE_AUDIO
    if _model.has_voice_cloning and ref_path.exists():
        try:
            key = _voice_cache_key(
                ref_path, os.environ.get("POCKET_TTS_LANGUAGE", "english")
            )
            cached = _load_cached_voice_state(key)
            if cached is not None:
                _voice_state = cached
                return
            t0 = time.monotonic()
            _voice_state = _model.get_state_for_audio_prompt(str(ref_path))
            dt = time.monotonic() - t0
            logger.info("Voice state from %s in %.1fs", ref_path.name, dt)
            _save_cached_voice_state(key, _voice_state)
            return
        except Exception as exc:
            logger.error(
                "Failed to clone voice '%s' from %s: %s",
                voice_name, ref_path, exc,
            )

    logger.warning(
        "Voice cloning failed — falling back to catalog voice 'alba'. "
        "Accept terms at https://huggingface.co/kyutai/pocket-tts "
        "to enable voice cloning."
    )
    _load_catalog_voice(_PREDEFINED_VOICES[0])


_PREDEFINED_VOICES = [
    "alba",
    "marius",
    "javert",
    "jean",
    "fantine",
    "cosette",
    "eponine",
    "azelma",
]


def _load_catalog_voice(voice_name: str) -> None:
    """Download a Pocket-TTS catalog voice embedding and convert to state dict."""
    global _voice_state
    try:
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file

        t0 = time.monotonic()
        emb_path = hf_hub_download(
            repo_id="kyutai/pocket-tts",
            filename=f"languages/english/embeddings/{voice_name}.safetensors",
        )
        flat = load_file(emb_path)

        # Convert flat key format to nested dict format expected by
        # generate_audio_stream.
        state = {}
        for flat_key, tensor in flat.items():
            module_path, attr = flat_key.split("/")
            if module_path not in state:
                state[module_path] = {}
            state[module_path][attr] = tensor

        _voice_state = state
        dt = time.monotonic() - t0
        logger.info(
            "Catalog voice '%s' loaded in %.1fs (%d tensors)",
            voice_name, dt, len(flat),
        )
    except Exception as exc:
        logger.error(
            "Failed to load catalog voice '%s': %s", voice_name, exc
        )
        _voice_state = None


def _normalize(text: str) -> str:
    """Run text through tts_normalizer before synthesis."""
    try:
        from backend.voice.tts_normalizer import normalize_for_speech

        return normalize_for_speech(text)
    except ImportError:
        import re

        text = re.sub(r"```[\s\S]*?```", "", text)
        text = re.sub(r"`[^`]+`", "", text)
        text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
        return text.strip()


def _split_into_chunks(text: str, max_chars: int = 200):
    """Split text into sentence-level chunks for natural pacing."""
    import re

    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks = []
    for sentence in raw:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            chunks.append(sentence)
        else:
            parts = re.split(r",\s+", sentence)
            buf = ""
            for part in parts:
                if buf and len(buf) + len(part) + 2 > max_chars:
                    chunks.append(buf.strip())
                    buf = part
                else:
                    buf = f"{buf}, {part}" if buf else part
            if buf.strip():
                chunks.append(buf.strip())
    return chunks if chunks else [text.strip()]


class _SynthFailed(Exception):
    """Internal control flow: synthesis cannot run (model not ready / empty).

    Caught by the request handlers, which emit the protocol `error` message —
    never propagates to the command loop.
    """


def _iter_synth_arrays(text: str, req_id: int):
    """Yield float32 audio arrays for text (shared synthesis core, T14).

    Identical audio to what "synthesize" streams (chunks + inter-sentence and
    trailing silence included). Raises _SynthFailed when synthesis cannot run.
    """
    global _model, _voice_state
    if _model is None or _voice_state is None:
        raise _SynthFailed("model not ready")

    normalized = _normalize(text)
    if not normalized:
        raise _SynthFailed("empty text")

    sentences = _split_into_chunks(normalized, max_chars=200)
    silence_gap = int(0.50 * OUTPUT_SAMPLE_RATE)
    trailing = int(0.60 * OUTPUT_SAMPLE_RATE)

    for idx, sentence in enumerate(sentences):
        for chunk_tensor in _model.generate_audio_stream(
            _voice_state,
            sentence,
            frames_after_eos=0,
        ):
            audio = chunk_tensor.cpu().numpy().astype(np.float32)
            if len(audio) == 0:
                continue
            # Clamp NaN/Inf
            if np.isnan(audio).any() or np.isinf(audio).any():
                audio = np.nan_to_num(
                    audio, nan=0.0, posinf=0.0, neginf=0.0
                )
            # Skip near-silent lead-in chunks
            if np.max(np.abs(audio)) < 0.01:
                continue
            yield audio

        # Inter-sentence silence
        if idx < len(sentences) - 1 and silence_gap > 0:
            yield np.zeros(silence_gap, dtype=np.float32)

    # Trailing silence
    if trailing > 0:
        yield np.zeros(trailing, dtype=np.float32)


def _synthesize(text: str, req_id: int) -> None:
    """Synthesize text and stream base64 audio chunks to stdout."""
    total_samples = 0
    t0 = time.monotonic()

    try:
        for audio in _iter_synth_arrays(text, req_id):
            total_samples += len(audio)
            b64 = base64.b64encode(audio.tobytes()).decode("ascii")
            print(
                json.dumps(
                    {
                        "type": "chunk",
                        "id": req_id,
                        "data": b64,
                        "sample_rate": OUTPUT_SAMPLE_RATE,
                    }
                ),
                flush=True,
            )

        duration = time.monotonic() - t0
        print(
            json.dumps(
                {
                    "type": "done",
                    "id": req_id,
                    "total_samples": total_samples,
                    "duration_s": round(duration, 2),
                }
            ),
            flush=True,
        )
        logger.info(
            "Synthesized %d samples (%.1fs audio) in %.2fs",
            total_samples,
            total_samples / OUTPUT_SAMPLE_RATE,
            duration,
        )
    except _SynthFailed as exc:
        print(
            json.dumps({"type": "error", "id": req_id, "error": str(exc)}),
            flush=True,
        )
    except Exception as exc:
        logger.error("Synthesis error: %s", exc)
        print(
            json.dumps({"type": "error", "id": req_id, "error": str(exc)}),
            flush=True,
        )
    # The request is over (success or failure): hand back whatever scratch
    # the encode spike left behind before the next request arrives.
    _compact_heap()


def _synthesize_and_hold(text: str, req_id: int) -> None:
    """Synthesize text and return it in ONE held message (REQ-10 AC10.6, T14).

    Lowest-priority beat audio: the parent only issues this while no lane
    synthesis runs, holds the buffer, and frees it on every exit path. Same
    audio bytes "synthesize" would have streamed.
    """
    t0 = time.monotonic()
    try:
        parts = list(_iter_synth_arrays(text, req_id))
        if not parts:
            print(
                json.dumps(
                    {"type": "error", "id": req_id, "error": "empty audio"}
                ),
                flush=True,
            )
            return
        held = np.concatenate(parts)
        duration = time.monotonic() - t0
        print(
            json.dumps(
                {
                    "type": "held",
                    "id": req_id,
                    "data": base64.b64encode(held.tobytes()).decode("ascii"),
                    "samples": len(held),
                    "duration_s": round(duration, 2),
                }
            ),
            flush=True,
        )
        logger.info(
            "Held %d samples (%.1fs audio) in %.2fs",
            len(held),
            len(held) / OUTPUT_SAMPLE_RATE,
            duration,
        )
    except _SynthFailed as exc:
        print(
            json.dumps({"type": "error", "id": req_id, "error": str(exc)}),
            flush=True,
        )
    except Exception as exc:
        logger.error("Hold synthesis error: %s", exc)
        print(
            json.dumps({"type": "error", "id": req_id, "error": str(exc)}),
            flush=True,
        )
    _compact_heap()


def _pre_synthesize_fillers() -> None:
    """Pre-synthesize filler phrases to .wav cache (best-effort)."""
    global _model, _voice_state
    if _model is None or _voice_state is None:
        print(json.dumps({"status": "fillers_ready", "count": 0}), flush=True)
        return

    fillers_dir = _PROJECT_DIR / "data" / "fillers"
    fillers_dir.mkdir(parents=True, exist_ok=True)

    phrases = [
        "One moment.",
        "Let me check that for you.",
        "Hmm, let me think.",
        "Give me a second.",
        "Looking into it.",
    ]
    count = 0
    for phrase in phrases:
        safe_name = (
            phrase.lower().replace(" ", "_").replace(".", "").replace(",", "")
        )
        wav_path = fillers_dir / f"{safe_name}.wav"
        if wav_path.exists():
            count += 1
            continue
        try:
            import soundfile as _sf

            audio_chunks = []
            for chunk in _model.generate_audio_stream(_voice_state, phrase):
                if chunk is not None and len(chunk) > 0:
                    audio_chunks.append(chunk.cpu().numpy().astype(np.float32))
            if audio_chunks:
                audio = np.concatenate(audio_chunks)
                _sf.write(str(wav_path), audio, OUTPUT_SAMPLE_RATE)
                count += 1
                logger.info("Pre-synthesized filler: %r", phrase)
        except Exception as exc:
            logger.warning("Filler synthesis failed for %r: %s", phrase, exc)

    print(json.dumps({"status": "fillers_ready", "count": count}), flush=True)


# ── Main loop ─────────────────────────────────────────────────────────────

def main() -> None:
    """Read JSONL commands from stdin, write JSONL responses to stdout."""
    # Module state, declared once for the whole function. The set_voice
    # branch below assigns _voice_state; without this declaration that one
    # assignment made the name LOCAL to all of main() (2026-09-30): the warm-up
    # raised UnboundLocalError, and set_voice read its own local None after
    # _load_voice_state() had set the module value, so every voice change
    # reported "voice_error" even when the voice loaded.
    global _voice_name, _voice_state
    # TEMP (execution audit 2026-09-30): the boot load hung >5 min at 0 CPU
    # inside the backend but loads in ~10 s standalone. Same switch as the
    # backend's hook in start-backend.py; remove with it.
    if os.environ.get("IRIS_STACK_DUMP_S"):
        import faulthandler

        _dump_fh = open(_PROJECT_DIR / "logs" / "stackdump_tts.log", "w")
        _dump_fh.write(f"start_epoch {time.time():.3f}\n")
        _dump_fh.flush()
        faulthandler.dump_traceback_later(
            float(os.environ["IRIS_STACK_DUMP_S"]), repeat=True, file=_dump_fh
        )
    logger.info("TTS worker starting — loading model...")

    # Send loading status immediately so the parent knows we're alive
    print(json.dumps({"status": "loading"}), flush=True)

    language = os.environ.get("POCKET_TTS_LANGUAGE", "english")
    _load_model(language)

    if _load_error is not None:
        print(
            json.dumps({"status": "error", "error": str(_load_error)}),
            flush=True,
        )
        logger.error("Worker exiting due to load failure")
        sys.exit(1)

    # Warm-up (2026-09-30): the first generation after a load pays a one-time
    # cost ("Prompting text took 15622 ms" for the first real sentence on
    # 2026-09-29, 171 ms for the next). Pay it here, so "ready" means warm and
    # the first spoken reply is fast. Output discarded; failure is non-fatal.
    try:
        _t_warm = time.monotonic()
        for _ in _model.generate_audio_stream(_voice_state, "Ready."):
            pass
        logger.info("Warm-up generation done in %.1fs", time.monotonic() - _t_warm)
    except Exception as exc:  # noqa: BLE001 — a cold first sentence is slow, not wrong
        logger.warning("Warm-up generation skipped: %s", exc)

    print(json.dumps({"status": "ready"}), flush=True)
    logger.info("TTS worker ready — listening for synthesis requests")

    # ── Command loop ──────────────────────────────────────────────────────
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON on stdin: %s", exc)
            print(
                json.dumps({"type": "error", "id": 0, "error": f"invalid json: {exc}"}),
                flush=True,
            )
            continue

        action = request.get("action", "")

        if action == "ping":
            status = "ready" if _model is not None else "loading"
            print(json.dumps({"status": status}), flush=True)

        elif action == "synthesize":
            text = request.get("text", "")
            req_id = request.get("id", 0)
            _synthesize(text, req_id)

        elif action == "synthesize_and_hold":
            text = request.get("text", "")
            req_id = request.get("id", 0)
            _synthesize_and_hold(text, req_id)

        elif action == "set_voice":
            new_voice = request.get("voice", "Cloned Voice")
            _voice_name = new_voice
            _voice_state = None
            _load_voice_state()
            ok = _voice_state is not None
            print(
                json.dumps(
                    {
                        "status": "voice_loaded" if ok else "voice_error",
                        "voice": new_voice,
                        "duration_s": 0.0,
                    }
                ),
                flush=True,
            )

        elif action == "pre_synthesize_fillers":
            _pre_synthesize_fillers()

        elif action == "shutdown":
            logger.info("Worker shutting down")
            print(json.dumps({"status": "shutting_down"}), flush=True)
            break

        else:
            logger.warning("Unknown action: %s", action)
            print(
                json.dumps(
                    {"type": "error", "id": 0, "error": f"unknown action: {action}"}
                ),
                flush=True,
            )

    logger.info("Worker exited")


if __name__ == "__main__":
    main()