"""
TTS Manager — F5-TTS (zero-shot voice cloning) for IRIS.

Primary engine : F5-TTS (F5TTS_v1_Base)
  - ~800 MB model, CPU-compatible (RTF ~0.15 on modern CPU — fast)
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
import os
import re
import sys
import tempfile
import threading
import wave
from pathlib import Path
from typing import Optional, Dict, Any, List, Generator

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

F5TTS_NATIVE_RATE:  int = 24_000  # F5-TTS native output sample rate
PIPER_NATIVE_RATE:  int = 22_050  # Piper ryan-high native rate
OUTPUT_SAMPLE_RATE: int = F5TTS_NATIVE_RATE  # pipeline rate
PYTTSX_NATIVE_RATE: int = 22_050
SAMPLE_RATE:        int = OUTPUT_SAMPLE_RATE  # legacy alias

# Paths (relative to this file: backend/agent/tts.py)
_THIS_DIR    = Path(__file__).parent          # backend/agent/
_BACKEND_DIR = _THIS_DIR.parent               # backend/
_PROJECT_DIR = _BACKEND_DIR.parent            # IRISVOICE/

REFERENCE_AUDIO = _PROJECT_DIR / "data" / "TOMV2.wav"

# Piper TTS — fast CPU engine (RTF ~0.04x). Used as fallback.
PIPER_MODEL_DIR  = _BACKEND_DIR / "voice" / "piper_models"
PIPER_MODEL_ONNX = PIPER_MODEL_DIR / "en_US-ryan-high.onnx"

AVAILABLE_VOICES: List[str] = ["Cloned Voice", "Built-in"]

# F5-TTS model identifier — F5TTS_v1_Base (~800 MB, downloads on first use)
F5TTS_MODEL = "F5TTS_v1_Base"


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
        logger.warning(f"[TTSManager] scipy resample failed ({exc}); using numpy interp fallback")
        n_out = int(len(audio) * OUTPUT_SAMPLE_RATE / orig_sr)
        return np.interp(
            np.linspace(0, len(audio) - 1, n_out),
            np.arange(len(audio)),
            audio
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
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks: List[str] = []
    for sentence in raw:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            chunks.append(sentence)
        else:
            # Long sentence — split further at commas
            parts = re.split(r',\s+', sentence)
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

    Engine selection (user-controlled via Settings):
      "Cloned Voice"  → F5-TTS zero-shot voice cloning from TOMV2.wav
                        CPU-based, RTF ~0.15, ~800 MB model
      "Built-in"      → Piper en_US-ryan-high (CPU, RTF ~0.04x, ~65 MB)
      Final fallback  → pyttsx3 SAPI5 (always available on Windows)

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
            "tts_enabled":   True,
            # Default to Built-in (Piper, ~65 MB CPU model) so the backend
            # starts without any heavy model load. Switch to "Cloned Voice"
            # (F5-TTS, ~800 MB CPU, RTF ~0.15) in Settings for voice cloning.
            "tts_voice":     "Built-in",
            "speaking_rate": 1.0,
        }

        # Engine instances (lazy-loaded)
        self._f5tts       = None    # F5TTS instance
        self._piper       = None    # PiperVoice instance
        self._lock        = threading.Lock()   # guards init only, NOT inference

        TTSManager._initialized = True

        threading.Thread(target=self._log_preflight, daemon=True, name="tts-preflight").start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    AVAILABLE_VOICES = AVAILABLE_VOICES

    def _log_preflight(self) -> None:
        """Log TTS preflight status at startup."""
        if self.config.get("tts_voice") == "Cloned Voice":
            issues = []
            if not REFERENCE_AUDIO.exists():
                issues.append(
                    f"Voice cloning reference audio not found at {REFERENCE_AUDIO}. "
                    "Place TOMV2.wav at IRISVOICE/data/TOMV2.wav to enable cloning."
                )
            if issues:
                logger.warning(
                    "[TTSManager] F5-TTS preflight issues:\n"
                    + "\n".join(f"  - {i}" for i in issues)
                )
            else:
                logger.info(
                    f"[TTSManager] F5-TTS preflight OK — "
                    f"reference audio at {REFERENCE_AUDIO}"
                )
        else:
            if PIPER_MODEL_ONNX.exists():
                logger.info(f"[TTSManager] CPU mode — Piper engine at {PIPER_MODEL_ONNX}")
            else:
                logger.warning(
                    f"[TTSManager] Piper model not found at {PIPER_MODEL_ONNX} — "
                    "will fall back to pyttsx3"
                )

    def update_config(self, **kwargs) -> None:
        """Update TTS configuration."""
        voice_changed = "tts_voice" in kwargs and kwargs["tts_voice"] != self.config.get("tts_voice")
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
        use_f5 = self.config.get("tts_voice") == "Cloned Voice"
        if use_f5:
            engine_name = "F5-TTS F5TTS_v1_Base (zero-shot voice cloning, CPU)"
            engine_ready = self._f5tts is not None
        else:
            engine_name = "Piper en_US-ryan-high (CPU)"
            engine_ready = self._piper is not None

        return {
            "available_voices":       AVAILABLE_VOICES,
            "current_voice":          self.config.get("tts_voice", "Built-in"),
            "config":                 self.get_config(),
            "model":                  engine_name,
            "model_ready":            engine_ready,
            "reference_audio":        str(REFERENCE_AUDIO),
            "reference_audio_exists": REFERENCE_AUDIO.exists(),
            "sample_rate":            OUTPUT_SAMPLE_RATE,
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
        """Resolve which engine to use on first call (no-op after that)."""
        if self._engine_selected:
            return
        self._engine_selected = True
        voice = self.config.get("tts_voice", "Built-in")
        logger.info(
            f"[TTSManager] Engine selected: "
            f"{'F5-TTS (CPU voice cloning)' if voice == 'Cloned Voice' else 'Piper/pyttsx3 (CPU)'}"
        )

    def synthesize_stream(self, text: str) -> Generator[np.ndarray, None, None]:
        """Stream synthesis — yields float32 arrays at OUTPUT_SAMPLE_RATE Hz.

        Text is normalised before synthesis (strips markdown / expands symbols).
        F5-TTS path: text split into sentence chunks; each chunk synthesized
        in sequence and yielded immediately — approximates streaming.
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

        if self.config.get("tts_voice") == "Cloned Voice":
            # --- F5-TTS path: CPU zero-shot cloning --------------------------
            with self._lock:
                loaded = self._load_f5tts()
                f5tts = self._f5tts

            if loaded and f5tts is not None:
                try:
                    for chunk in self._stream_f5tts(f5tts, normalized):
                        yield chunk
                    return
                except Exception as exc:
                    logger.warning(
                        f"[TTSManager] F5-TTS stream failed, falling back to Piper: {exc}",
                        exc_info=True,
                    )

        # --- Piper path: fast CPU engine ------------------------------------
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
    # F5-TTS engine (CPU primary — zero-shot voice cloning)
    # ------------------------------------------------------------------

    def _load_f5tts(self) -> bool:
        """Load F5-TTS model.  Must be called under self._lock.

        Downloads F5TTS_v1_Base (~800 MB) from HuggingFace on first run.
        CPU-only — does not consume any VRAM.
        """
        if self._f5tts is not None:
            return True
        try:
            from f5_tts.api import F5TTS
            logger.info(f"[TTSManager] Loading F5-TTS ({F5TTS_MODEL})...")
            self._f5tts = F5TTS(model=F5TTS_MODEL)
            logger.info("[TTSManager] F5-TTS loaded (CPU mode)")
            return True
        except ImportError:
            logger.error(
                "[TTSManager] f5-tts not installed. "
                "Run: pip install f5-tts"
            )
            self._f5tts = None
            return False
        except Exception as exc:
            logger.error(f"[TTSManager] Failed to load F5-TTS: {exc}", exc_info=True)
            self._f5tts = None
            return False

    def _stream_f5tts(
        self, f5tts, text: str
    ) -> Generator[np.ndarray, None, None]:
        """Synthesize *text* with F5-TTS using TOMV2.wav as reference voice.

        Text is split into sentence chunks and each is synthesized in sequence.
        Yields float32 audio at OUTPUT_SAMPLE_RATE Hz per chunk.

        ref_text is left empty — F5-TTS auto-transcribes the reference audio.
        """
        if not REFERENCE_AUDIO.exists():
            logger.warning(
                f"[TTSManager] Reference audio missing: {REFERENCE_AUDIO}. "
                "Falling back to Piper."
            )
            return

        ref_file = str(REFERENCE_AUDIO)
        speed = float(self.config.get("speaking_rate", 1.0))
        chunks = _split_into_chunks(text)

        for i, chunk_text in enumerate(chunks):
            if not chunk_text.strip():
                continue
            try:
                wav, sr, _ = f5tts.infer(
                    ref_file=ref_file,
                    ref_text="",        # auto-transcribed from TOMV2.wav
                    gen_text=chunk_text,
                    speed=speed,
                )
                # wav may be a torch.Tensor or numpy array
                try:
                    audio = wav.cpu().numpy().flatten().astype(np.float32)
                except AttributeError:
                    audio = np.asarray(wav, dtype=np.float32).flatten()

                if len(audio) == 0:
                    continue

                audio = _resample(audio, sr)
                logger.debug(
                    f"[TTSManager] F5-TTS chunk {i+1}/{len(chunks)}: "
                    f"{len(audio)} samples @ {sr} Hz"
                )
                yield audio
            except Exception as exc:
                logger.warning(
                    f"[TTSManager] F5-TTS chunk {i+1} failed: {exc}. Skipping."
                )
                continue

    # ------------------------------------------------------------------
    # Piper engine (CPU fallback)
    # ------------------------------------------------------------------

    def _load_piper(self) -> bool:
        """Load Piper voice model.  Must be called under self._lock."""
        if self._piper is not None:
            return True
        if not PIPER_MODEL_ONNX.exists():
            logger.warning(f"[TTSManager] Piper model not found at {PIPER_MODEL_ONNX}")
            return False
        try:
            from piper import PiperVoice
            logger.info(f"[TTSManager] Loading Piper from {PIPER_MODEL_ONNX}...")
            self._piper = PiperVoice.load(str(PIPER_MODEL_ONNX))
            logger.info("[TTSManager] Piper loaded (en_US-ryan-high)")
            return True
        except Exception as exc:
            logger.error(f"[TTSManager] Failed to load Piper: {exc}", exc_info=True)
            self._piper = None
            return False

    @staticmethod
    def _stream_piper(piper, text: str) -> Generator[np.ndarray, None, None]:
        """Run Piper inference and yield float32 chunks at OUTPUT_SAMPLE_RATE.

        piper.synthesize() yields AudioChunk objects per sentence.
        Each chunk has audio_int16_array (numpy int16) and sample_rate.
        RTF ~0.04x on CPU; first chunk typically in <100 ms.
        """
        for chunk in piper.synthesize(text):
            arr = chunk.audio_int16_array  # numpy int16
            piper_rate = chunk.sample_rate
            audio = arr.astype(np.float32) / 32768.0
            audio = _resample(audio, piper_rate)
            if len(audio) > 0:
                yield audio

    # ------------------------------------------------------------------
    # pyttsx3 fallback (SAPI5)
    # ------------------------------------------------------------------

    def _synthesize_pyttsx(self, text: str) -> Optional[np.ndarray]:
        """Synthesize with pyttsx3 SAPI5.

        Returns float32 array at OUTPUT_SAMPLE_RATE Hz.
        """
        try:
            import pyttsx3
        except ImportError:
            logger.error("[TTSManager] pyttsx3 not installed")
            return None

        tmp_path = None
        try:
            engine = pyttsx3.init()

            voices = engine.getProperty("voices")
            if voices:
                for v in voices:
                    if any(n in v.name.lower() for n in ("english", "david", "zira")):
                        engine.setProperty("voice", v.id)
                        break

            rate_multiplier = float(self.config.get("speaking_rate", 1.0))
            engine.setProperty("rate", int(150 * rate_multiplier))
            engine.setProperty("volume", 1.0)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name

            engine.save_to_file(text, tmp_path)
            engine.runAndWait()
            engine.stop()

            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                logger.warning("[TTSManager] pyttsx3 produced empty WAV")
                return None

            with wave.open(tmp_path, "rb") as wf:
                n_frames   = wf.getnframes()
                samp_width = wf.getsampwidth()
                n_channels = wf.getnchannels()
                file_rate  = wf.getframerate()
                raw        = wf.readframes(n_frames)

            if samp_width == 2:
                audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            elif samp_width == 4:
                audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                logger.warning(f"[TTSManager] pyttsx3 unsupported sample width: {samp_width}")
                return None

            if n_channels > 1:
                audio = audio.reshape(-1, n_channels).mean(axis=1)

            return _resample(audio, file_rate)

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
