"""
TTS Manager — Pocket-TTS (voice cloning) for IRIS.
Primary engine : Pocket-TTS (~100M int8 quantized, ~100 MB RAM)
  - Zero-shot voice cloning from reference audio (TOMV2.wav)
  - True streaming inference (generate_audio_stream — yields chunk-by-chunk)
  - Fallback engines: Piper → pyttsx3
  - Zero-shot voice cloning from TOMV2.wav reference audio
  - Chunked synthesis: text split into sentences, each synthesized
    sequentially and yielded as audio — approximates streaming
  - Text normalizer wired in: strips markdown, expands symbols, removes
    code blocks so TTS never reads out "$", "%", "->", "**bold**" etc.
  - 24 kHz native output

Fallback        : Piper en_US-ryan-high (fast CPU, ~65 MB, no cloning)
Final fallback  : pyttsx3 (Windows SAPI5 — zero download, instant)

Setup           : pip install f5-tts
                  Place TOMV2.wav at IRISVOICE/data/TOMV2.wav

Lock discipline
  self._lock guards model initialisation only.  It is released before
  inference so synthesis never blocks the consumer's audio-queue timeout.
  The lock is NOT reentrant — do not acquire it inside _stream_f5tts.
"""

import logging
import math
import os
import queue
import random
import re
import threading
import time
import tempfile
import traceback
import wave
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

import numpy as np
import psutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

F5TTS_NATIVE_RATE: int = 24_000  # F5-TTS native output sample rate
PIPER_NATIVE_RATE: int = 22_050  # Piper ryan-high native rate
OUTPUT_SAMPLE_RATE: int = F5TTS_NATIVE_RATE  # pipeline rate
PYTTSX_NATIVE_RATE: int = 22_050
SAMPLE_RATE: int = OUTPUT_SAMPLE_RATE  # legacy alias

# Paths (relative to this file: backend/agent/tts.py)
_THIS_DIR = Path(__file__).parent  # backend/agent/
_BACKEND_DIR = _THIS_DIR.parent  # backend/
_PROJECT_DIR = _BACKEND_DIR.parent  # IRISVOICE/

REFERENCE_AUDIO = _PROJECT_DIR / "data" / "TOMV2.wav"

# Piper TTS — fast CPU engine (RTF ~0.04x). Used as fallback.
PIPER_MODEL_DIR = _BACKEND_DIR / "voice" / "piper_models"
PIPER_MODEL_ONNX = PIPER_MODEL_DIR / "en_US-ryan-high.onnx"

AVAILABLE_VOICES: List[str] = ["Cloned Voice", "Built-in"]


# ---------------------------------------------------------------------------
# Helper — resample to pipeline rate
# ---------------------------------------------------------------------------


def _resample(audio: np.ndarray, orig_sr: int) -> np.ndarray:
    """Resample *audio* (float32) from *orig_sr* to OUTPUT_SAMPLE_RATE.

    Uses scipy.signal.resample for quality; falls back to numpy interp.
    No-op when orig_sr == OUTPUT_SAMPLE_RATE.
    """
    if orig_sr == OUTPUT_SAMPLE_RATE:
        return audio.astype(np.float32)
    try:
        from scipy.signal import resample as _sp_resample

        n_out = int(len(audio) * OUTPUT_SAMPLE_RATE / orig_sr)
        return _sp_resample(audio, n_out).astype(np.float32)
    except Exception as exc:
        logger.warning(
            f"[TTSManager] scipy resample failed ({exc}); using numpy interp fallback"
        )
        n_out = int(len(audio) * OUTPUT_SAMPLE_RATE / orig_sr)
        return np.interp(
            np.linspace(0, len(audio) - 1, n_out), np.arange(len(audio)), audio
        ).astype(np.float32)


# ---------------------------------------------------------------------------
# Helper — sentence chunker
# ---------------------------------------------------------------------------


def _split_into_chunks(text: str, max_chars: int = 200) -> List[str]:
    """Split *text* into sentence-level chunks suitable for F5-TTS synthesis.

    Splits on sentence-ending punctuation (. ! ?) followed by whitespace.
    Chunks that are still too long are split further at commas.
    Empty chunks are discarded.
    """
    # Split at sentence boundaries
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: List[str] = []
    for sentence in raw:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            chunks.append(sentence)
        else:
            # Long sentence — split further at commas
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


# ---------------------------------------------------------------------------
# TTSManager
# ---------------------------------------------------------------------------


class TTSManager:
    """
    Singleton TTS manager.

    Engine priority (automatic — not user-selected):
      1. F5-TTS (F5TTS_v1_Base) — PRIMARY
            Zero-shot voice cloning from TOMV2.wav.
            CPU-based, RTF ~0.15, ~800 MB model (lazy load).
            Always tried first unless user forces "Built-in".
      2. Piper en_US-ryan-high — FALLBACK
            Fast CPU engine, RTF ~0.04x, ~65 MB model (auto-downloaded).
            Used when F5-TTS is not installed, fails to load, or stream errors.
      3. pyttsx3 (SAPI5 on Windows) — LAST RESORT
            Zero download, always available on Windows.

    Voice setting "Built-in" skips F5-TTS and goes directly to Piper.
    This is the only way to bypass F5-TTS (e.g. for testing or low-resource mode).

    All engines produce float32 audio at OUTPUT_SAMPLE_RATE (24 kHz).

    Text is normalised before synthesis (markdown stripped, symbols
    expanded to spoken words) via backend/voice/tts_normalizer.py.

    IMPORTANT — first-time setup:
      pip install f5-tts
      Place TOMV2.wav at IRISVOICE/data/TOMV2.wav to enable voice cloning.
      F5TTS_v1_Base weights (~800 MB) are downloaded automatically on first use.
    """

    _instance: Optional["TTSManager"] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if TTSManager._initialized:
            return

        # Engine selection is deferred to first synthesize_stream() call
        # via _select_engine().  Avoids importing heavy deps at startup.
        self._engine_selected = False

        self.config: Dict[str, Any] = {
            "tts_enabled": True,
            # Pocket-TTS is the primary TTS engine (voice cloning).
            # "Cloned Voice" = Pocket-TTS primary (default).
            # "Built-in"     = force Piper (skips Pocket-TTS).
            # In both cases Piper → pyttsx3 are available as automatic fallbacks.
            "tts_voice": "Cloned Voice",  # Pocket-TTS voice cloning
            "speaking_rate": 1.0,
        }

        # Engine instances (lazy-loaded)
        self._pocket_tts_model = None  # Pocket-TTS model instance
        self._voice_state = None  # cached voice embedding from TOMV2.wav
        self._piper = None  # PiperVoice instance
        self._lock = threading.Lock()  # guards init only, NOT inference

        TTSManager._initialized = True

        threading.Thread(
            target=self._log_preflight, daemon=True, name="tts-preflight"
        ).start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    AVAILABLE_VOICES = AVAILABLE_VOICES

    def _log_preflight(self) -> None:
        """Log TTS preflight status at startup.

        F5-TTS is always the primary engine.  Piper is the fallback.
        "Built-in" voice setting forces Piper directly (skips F5-TTS).
        """
        force_builtin = self.config.get("tts_voice") == "Built-in"

        if not force_builtin:
            # F5-TTS primary path
            issues = []
            if not REFERENCE_AUDIO.exists():
                issues.append(
                    f"Reference audio not found at {REFERENCE_AUDIO}. "
                    "Place TOMV2.wav at IRISVOICE/data/TOMV2.wav to enable voice cloning."
                )
            if issues:
                logger.warning(
                    "[TTSManager] F5-TTS primary — preflight issues:\n"
                    + "\n".join(f"  - {i}" for i in issues)
                    + "\n  Will fall back to Piper."
                )
            else:
                logger.info(
                    f"[TTSManager] F5-TTS primary — reference audio OK at {REFERENCE_AUDIO}"
                )
            # Always log Piper status as fallback
            if PIPER_MODEL_ONNX.exists():
                logger.info(f"[TTSManager] Piper fallback ready at {PIPER_MODEL_ONNX}")
            else:
                logger.warning(
                    f"[TTSManager] Piper fallback model not found at {PIPER_MODEL_ONNX} — "
                    "will fall back to pyttsx3 if F5-TTS also fails"
                )
        else:
            # User explicitly selected "Built-in" → Piper only
            logger.info(
                "[TTSManager] Voice set to 'Built-in' — using Piper directly (F5-TTS skipped)"
            )
            if PIPER_MODEL_ONNX.exists():
                logger.info(f"[TTSManager] Piper engine at {PIPER_MODEL_ONNX}")
            else:
                logger.warning(
                    f"[TTSManager] Piper model not found at {PIPER_MODEL_ONNX} — "
                    "will fall back to pyttsx3"
                )

    def update_config(self, **kwargs) -> None:
        """Update TTS configuration."""
        voice_changed = "tts_voice" in kwargs and kwargs[
            "tts_voice"
        ] != self.config.get("tts_voice")
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value
        if voice_changed:
            # Force engine re-selection on next synthesize_stream.
            self._engine_selected = False
        logger.info(f"[TTSManager] Config updated: {kwargs}")

    def get_config(self) -> Dict[str, Any]:
        """Return current TTS configuration."""
        return dict(self.config)

    def get_voice_info(self) -> Dict[str, Any]:
        """Return available voice information."""
        use_cloned = self.config.get("tts_voice") == "Cloned Voice"
        if use_cloned:
            _mode = "GPU" if True else "CPU"  # Pocket-TTS loads on any device
            engine_name = f"Pocket-TTS (~100M, zero-shot voice cloning, int8)"
            engine_ready = self._pocket_tts_model is not None
            model_path_exists = True  # installed via pip
        else:
            engine_name = "Piper en_US-ryan-high (CPU)"
            engine_ready = self._piper is not None
            model_path_exists = PIPER_MODEL_ONNX.exists()

        return {
            "available_voices": AVAILABLE_VOICES,
            "current_voice": self.config.get("tts_voice", "Built-in"),
            "config": self.get_config(),
            "model": engine_name,
            "model_ready": engine_ready,
            "model_path_exists": model_path_exists,
            "reference_audio": str(REFERENCE_AUDIO),
            "reference_audio_exists": REFERENCE_AUDIO.exists(),
            "sample_rate": OUTPUT_SAMPLE_RATE,
        }

    def synthesize(self, text: Optional[str]) -> Optional[np.ndarray]:
        """Synthesize speech from text.

        Returns float32 array at OUTPUT_SAMPLE_RATE Hz, or None on failure.
        """
        if not self.config.get("tts_enabled", True):
            return None
        if not text or not text.strip():
            return None
        chunks = list(self.synthesize_stream(text))
        if chunks:
            return np.concatenate(chunks)
        return None

    def _select_engine(self) -> None:
        """Resolve which engine to use on first call (no-op after that).

        Pocket-TTS is always the primary.  Selecting "Built-in" forces Piper.
        """
        if self._engine_selected:
            return
        self._engine_selected = True
        force_builtin = self.config.get("tts_voice") == "Built-in"
        logger.info(
            f"[TTSManager] Engine priority: "
            f"{'Piper/pyttsx3 (Built-in selected — Pocket-TTS skipped)' if force_builtin else 'Pocket-TTS (primary) → Piper (fallback) → pyttsx3 (last resort)'}"
        )

    def synthesize_stream(self, text: str) -> Generator[np.ndarray, None, None]:
        """Stream synthesis — yields float32 arrays at OUTPUT_SAMPLE_RATE Hz.

        Text is normalised before synthesis (strips markdown / expands symbols).
        Pocket-TTS path: streaming yields chunks during generation (true streaming).
        Piper path:  native per-sentence streaming via piper.synthesize().
        pyttsx3:     one full chunk as last resort.

        Lock discipline: self._lock held only during model load, not inference.
        """
        if not self.config.get("tts_enabled", True):
            return
        if not text.strip():
            return

        # Normalise text before synthesis
        normalized = self._normalize(text)
        if not normalized:
            return

        self._select_engine()

        # --- Pocket-TTS: primary engine (voice cloning) -----------------------
        force_builtin = self.config.get("tts_voice") == "Built-in"
        if not force_builtin:
            with self._lock:
                loaded = self._load_pocket_tts()
                pocket = self._pocket_tts_model
                voice = self._voice_state

            if loaded and pocket is not None and voice is not None:
                try:
                    for chunk in self._stream_pocket(pocket, voice, normalized):
                        yield chunk
                    return
                except Exception as exc:
                    logger.warning(
                        f"[TTSManager] Pocket-TTS stream failed, falling back to Piper: {exc}",
                        exc_info=True,
                    )
            else:
                logger.info(
                    "[TTSManager] Pocket-TTS unavailable — falling back to Piper"
                )

        # --- Piper path: fallback engine ------------------------------------
        with self._lock:
            piper_loaded = self._load_piper()
            piper = self._piper

        if piper_loaded and piper is not None:
            try:
                for chunk in self._stream_piper(piper, normalized):
                    yield chunk
                return
            except Exception as exc:
                logger.warning(
                    f"[TTSManager] Piper stream failed, falling back to pyttsx3: {exc}"
                )

        # --- pyttsx3 last-resort fallback ------------------------------------
        try:
            result = self._synthesize_pyttsx(normalized)
            if result is not None:
                yield result
        except Exception as exc:
            logger.error(f"[TTSManager] pyttsx3 stream error: {exc}")

    # ------------------------------------------------------------------
    # Text normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(text: str) -> str:
        """Run text through tts_normalizer before synthesis.

        Strips markdown, expands symbols ($→dollars, %→percent, etc.),
        removes code blocks so TTS never reads out raw symbols or markup.
        Falls back to stripping obvious markdown if the normalizer import fails.
        """
        try:
            from backend.voice.tts_normalizer import normalize_for_speech

            return normalize_for_speech(text)
        except ImportError:
            # Minimal inline fallback — remove markdown code fences and bold/italic
            text = re.sub(r"```[\s\S]*?```", "", text)
            text = re.sub(r"`[^`]+`", "", text)
            text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
            return text.strip()

    # ------------------------------------------------------------------
    # Pocket-TTS engine (primary — zero-shot voice cloning)
    # ------------------------------------------------------------------

    # Manual transcript of data/TOMV2.wav (5.6 s, used for voice cloning).
    # Note: voice cloning requires accepting terms at
    # https://huggingface.co/kyutai/pocket-tts — until then we fall back
    # to the built-in "alba" catalog voice.
    REFERENCE_TRANSCRIPT: str = (
        "There's been a lot of talk about race lately. "
        "I don't see color. Racism isn't real anymore."
    )
    POCKET_CATALOG_VOICE: str = "alba"

    def _load_pocket_tts(self) -> bool:
        """Load Pocket-TTS model + voice/voice-state (once, cached)."""
        if self._pocket_tts_model is not None:
            return True
        try:
            from pocket_tts import TTSModel

            t0 = time.monotonic()
            self._pocket_tts_model = TTSModel.load_model(
                variant=os.environ.get("POCKET_TTS_VARIANT", "b6369a24"),
            )
            dt = time.monotonic() - t0
            logger.info(f"[TTSManager] Pocket-TTS model loaded in {dt:.1f}s")
            self._load_voice_state()
            return True
        except ImportError:
            logger.error(
                "[TTSManager] pocket-tts not installed. Run: pip install pocket-tts"
            )
            self._pocket_tts_model = None
            return False
        except Exception as exc:
            logger.warning(f"[TTSManager] Failed to load Pocket-TTS: {exc}")
            self._pocket_tts_model = None
            return False

    def _load_voice_state(self) -> bool:
        """Extract voice embedding from TOMV2.wav (gated) or use catalog voice."""
        if self._voice_state is not None:
            return True

        # If the model supports voice cloning, try TOMV2.wav
        ref_path = REFERENCE_AUDIO
        if self._pocket_tts_model.has_voice_cloning and ref_path.exists():
            try:
                t0 = time.monotonic()
                self._voice_state = self._pocket_tts_model.get_state_for_audio_prompt(
                    str(ref_path)
                )
                dt = time.monotonic() - t0
                logger.info(
                    f"[TTSManager] Voice state from {ref_path.name} in {dt:.1f}s"
                )
                return True
            except Exception as exc:
                logger.warning(
                    f"[TTSManager] Failed to clone voice from {ref_path.name}: {exc}"
                )
                logger.info(
                    "[TTSManager] Accept terms at https://huggingface.co/kyutai/pocket-tts "
                    "for voice cloning. Using default catalog voice."
                )

        # Fallback: use a catalog voice
        catalog = self.POCKET_CATALOG_VOICE
        try:
            _, _sr = self._pocket_tts_model.generate_audio(catalog, "")  # warm up
            self._voice_state = catalog  # store the voice name
            logger.info(f"[TTSManager] Using catalog voice '{catalog}'")
            return True
        except Exception as exc:
            logger.warning(f"[TTSManager] Catalog voice '{catalog}' failed: {exc}")
            self._voice_state = None
            return False
        except Exception as exc:
            logger.warning(f"[TTSManager] Failed to load Pocket-TTS: {exc}")
            self._pocket_tts_model = None
            return False

    def _load_voice_state(self) -> bool:
        """Extract voice embedding from TOMV2.wav and cache it."""
        if self._voice_state is not None:
            return True
        ref_path = REFERENCE_AUDIO
        if not ref_path.exists():
            logger.warning(f"[TTSManager] Reference audio missing: {ref_path}")
            self._voice_state = None
            return False
        try:
            t0 = time.monotonic()
            self._voice_state = self._pocket_tts_model.get_state_for_audio_prompt(
                str(ref_path)
            )
            dt = time.monotonic() - t0
            logger.info(f"[TTSManager] Voice state from {ref_path.name} in {dt:.1f}s")
            return True
        except Exception as exc:
            logger.warning(f"[TTSManager] Failed to get voice state: {exc}")
            self._voice_state = None
            return False

    def _stream_pocket(
        self,
        model,
        voice_state,
        text: str,
    ) -> Generator[np.ndarray, None, None]:
        """Stream audio chunks from Pocket-TTS (true streaming inference).

        voice_state is either a voice embedding dict (voice cloning) or a
        catalog voice name (string like 'alba').  The streaming API handles
        either.
        """
        if model is None or voice_state is None:
            return
        speed = float(self.config.get("speaking_rate", 1.0))
        try:
            for chunk_tensor in model.generate_audio_stream(
                voice_state,
                text,
                speed=speed,
                chunk_size=100,  # characters per streaming chunk
            ):
                audio = chunk_tensor.cpu().numpy().astype(np.float32)
                if len(audio) == 0:
                    continue
                yield audio
        except Exception as exc:
            logger.warning(f"[TTSManager] Pocket-TTS stream failed: {exc}")

        except Exception as exc:
            logger.error(f"[TTSManager] pyttsx3 error: {exc}", exc_info=True)
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


def get_tts_manager() -> TTSManager:
    """Return the process-wide TTSManager singleton."""
    return TTSManager()
