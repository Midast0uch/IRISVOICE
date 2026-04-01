"""
TTS Manager — CosyVoice 3.0 (zero-shot voice cloning) for IRIS.

Primary engine : CosyVoice3-0.5B
  - Same 0.5B parameter count as CosyVoice2; better content consistency,
    speaker similarity, and prosody naturalness
  - Zero-shot voice cloning from TOMV2.wav reference (pre-registered as 'tommv2')
  - Streaming: yields audio chunks as soon as they are ready (~150 ms first-chunk)
  - 24 kHz native output — passed directly to sd.play() (no intermediate resampling)
  - CPU inference supported — no CUDA required

Fallback        : pyttsx3 (Windows SAPI5 — zero download, instant)

Setup           : run scripts/download_models.py to download CosyVoice3-0.5B
                  and get instructions for placing TOMV2.wav

Lock discipline
  self._lock guards model initialisation only.  It is released before
  inference so synthesis never blocks the consumer's audio-queue timeout.
  The lock is NOT reentrant — do not acquire it inside _stream_cosyvoice.

PIPELINE SAMPLE RATE: OUTPUT_SAMPLE_RATE == COSYVOICE_NATIVE_RATE (24 kHz).
_resample() is a no-op for CosyVoice chunks.  sd.play() handles the
single-step conversion from 24 kHz to the device's native rate.
pyttsx3 audio is still resampled from its file rate to 24 kHz so both
engines return audio at the same OUTPUT_SAMPLE_RATE.
"""
import logging
import os
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

COSYVOICE_NATIVE_RATE: int = 24_000  # CosyVoice3-0.5B native rate
PIPER_NATIVE_RATE:    int = 22_050   # Piper ryan-high native rate
OUTPUT_SAMPLE_RATE:   int = COSYVOICE_NATIVE_RATE  # pipeline rate (both engines resample to this)
PYTTSX_NATIVE_RATE:   int = 22_050   # pyttsx3 / SAPI5 typical rate
SAMPLE_RATE:          int = OUTPUT_SAMPLE_RATE  # legacy alias

# Paths (relative to this file: backend/agent/tts.py)
_THIS_DIR    = Path(__file__).parent          # backend/agent/
_BACKEND_DIR = _THIS_DIR.parent               # backend/
_PROJECT_DIR = _BACKEND_DIR.parent            # IRISVOICE/

COSYVOICE_DIR   = _BACKEND_DIR / "voice" / "CosyVoice"
MODEL_DIR       = _BACKEND_DIR / "voice" / "pretrained_models" / "CosyVoice3-0.5B"
REFERENCE_AUDIO = _PROJECT_DIR / "data" / "TOMV2.wav"
SPK_ID          = "tommv2"

# Piper TTS — fast CPU engine (RTF ~0.04x vs CosyVoice3 CPU RTF ~50x).
# Used as primary when CUDA is not available.
PIPER_MODEL_DIR  = _BACKEND_DIR / "voice" / "piper_models"
PIPER_MODEL_ONNX = PIPER_MODEL_DIR / "en_US-ryan-high.onnx"

# CosyVoice3 requires <|endofprompt|> in prompt_text (CosyVoice2 accepted empty string).
# This prefix is prepended to any prompt transcript so the tokenizer sees the special token.
COSYVOICE3_PROMPT_PREFIX = "You are a helpful assistant.<|endofprompt|>"

def _cuda_available() -> bool:
    # NOTE: do NOT call this at module level — importing torch costs ~360 MB.
    # Evaluated lazily on first TTS use (see TTSManager._select_engine).
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False

# Engine selection deferred to first use — avoids 360 MB torch import at startup.
# USE_COSYVOICE is now a property of TTSManager, not a module constant.
USE_COSYVOICE: bool = False  # overridden at first TTSManager init

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
        logger.warning(f"[TTSManager] scipy resample failed ({exc}); using numpy interp fallback")
        n_out = int(len(audio) * OUTPUT_SAMPLE_RATE / orig_sr)
        return np.interp(
            np.linspace(0, len(audio) - 1, n_out),
            np.arange(len(audio)),
            audio
        ).astype(np.float32)


# ---------------------------------------------------------------------------
# TTSManager
# ---------------------------------------------------------------------------

class TTSManager:
    """
    Singleton TTS manager.

    Engine selection (automatic, based on hardware):
      GPU present  → CosyVoice3-0.5B (zero-shot voice cloning, RTF ~1-3x)
      CPU only     → Piper en_US-ryan-high (fast, RTF ~0.04x)
      Final fallback → pyttsx3 SAPI5 (always available on Windows)

    All engines produce float32 audio at OUTPUT_SAMPLE_RATE (24 kHz).

    IMPORTANT — first-time setup:
      Run scripts/download_models.py to download CosyVoice3-0.5B weights (GPU path).
      Piper model (backend/voice/piper_models/) is downloaded automatically.
      Place TOMV2.wav at IRISVOICE/data/TOMV2.wav to enable CosyVoice3 cloning.
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

        # Resolve GPU availability here (first TTSManager use), not at module
        # import time.  This defers the 360 MB torch import until TTS is needed.
        global USE_COSYVOICE
        USE_COSYVOICE = _cuda_available()

        self.config: Dict[str, Any] = {
            "tts_enabled":   True,
            "tts_voice":     "Cloned Voice",
            "speaking_rate": 1.0,
        }

        self._cosyvoice      = None     # AutoModel instance (lazy-loaded, GPU only)
        self._piper          = None     # PiperVoice instance (lazy-loaded, CPU path)
        self._spk_registered = False    # Whether TOMV2 speaker is registered
        self._lock           = threading.Lock()   # guards init only, NOT inference
        self._ready_event    = threading.Event()  # set when model+speaker ready

        TTSManager._initialized = True

        # Run preflight once at init so any missing pieces are surfaced immediately
        # in the startup logs rather than silently at first TTS call.
        threading.Thread(target=self._log_preflight, daemon=True, name="tts-preflight").start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    AVAILABLE_VOICES = AVAILABLE_VOICES

    def _log_preflight(self) -> None:
        """Log TTS preflight status at startup — surfaces missing pieces clearly."""
        if USE_COSYVOICE:
            issues = []
            if not COSYVOICE_DIR.exists():
                issues.append(
                    f"CosyVoice source not found at {COSYVOICE_DIR}. "
                    "Run: python scripts/download_models.py"
                )
            if not MODEL_DIR.exists():
                issues.append(
                    f"CosyVoice3-0.5B weights not found at {MODEL_DIR}. "
                    "Run: python scripts/download_models.py"
                )
            if not REFERENCE_AUDIO.exists():
                issues.append(
                    f"Voice cloning reference audio not found at {REFERENCE_AUDIO}. "
                    "Place TOMV2.wav at IRISVOICE/data/TOMV2.wav to enable cloning."
                )
            if issues:
                logger.warning(
                    "[TTSManager] CosyVoice3 preflight issues:\n"
                    + "\n".join(f"  - {i}" for i in issues)
                )
            else:
                logger.info(
                    f"[TTSManager] Preflight OK — CosyVoice3-0.5B GPU path, "
                    f"reference audio at {REFERENCE_AUDIO}"
                )
        else:
            if PIPER_MODEL_ONNX.exists():
                logger.info(
                    f"[TTSManager] CPU mode — Piper engine at {PIPER_MODEL_ONNX}"
                )
            else:
                logger.warning(
                    f"[TTSManager] Piper model not found at {PIPER_MODEL_ONNX} — "
                    "will fall back to pyttsx3"
                )

    def _warm_tts_pipeline(self) -> None:
        """Pre-load CosyVoice3 model and register voice in a background thread.

        Called by iris_gateway._prewarm_tts() at startup.  Sets _ready_event
        when complete so synthesize_stream can block-wait efficiently instead
        of polling.
        """
        if self._cosyvoice is not None:
            if not self._ready_event.is_set():
                self._ready_event.set()
            return

        def _do():
            with self._lock:
                self._load_cosyvoice()
            self._ready_event.set()
            logger.info("[TTSManager] CosyVoice3 ready event set")

        threading.Thread(target=_do, daemon=True, name="tts-cosyvoice-warmup").start()

    def update_config(self, **kwargs) -> None:
        """Update TTS configuration."""
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value
        logger.info(f"[TTSManager] Config updated: {kwargs}")

    def get_config(self) -> Dict[str, Any]:
        """Return current TTS configuration."""
        return dict(self.config)

    def get_voice_info(self) -> Dict[str, Any]:
        """Return available voice information."""
        if USE_COSYVOICE:
            engine_name = "CosyVoice3-0.5B (zero-shot voice cloning, GPU)"
            engine_ready = self._cosyvoice is not None
        else:
            engine_name = "Piper en_US-ryan-high (CPU)"
            engine_ready = self._piper is not None

        return {
            "available_voices":  AVAILABLE_VOICES,
            "current_voice":     self.config.get("tts_voice", "Cloned Voice"),
            "config":            self.get_config(),
            "model":             engine_name,
            "model_ready":       engine_ready,
            "model_path_exists": MODEL_DIR.exists() if USE_COSYVOICE else PIPER_MODEL_ONNX.exists(),
            "reference_audio":   str(REFERENCE_AUDIO),
            "reference_audio_exists": REFERENCE_AUDIO.exists(),
            "sample_rate":       OUTPUT_SAMPLE_RATE,
            "use_cosyvoice":     USE_COSYVOICE,
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

    def synthesize_stream(self, text: str) -> Generator[np.ndarray, None, None]:
        """Stream synthesis — yields float32 arrays at OUTPUT_SAMPLE_RATE Hz.

        Lock discipline: acquires self._lock only long enough to ensure the
        model is loaded, then releases it before calling inference.  This
        prevents the audio-queue consumer from timing out during model load.

        CosyVoice streams audio chunks as soon as generated (~150 ms first
        chunk after model is warm).  pyttsx3 fallback yields one full chunk.
        """
        if not self.config.get("tts_enabled", True):
            return
        if not text.strip():
            return

        if USE_COSYVOICE and self.config.get("tts_voice") == "Cloned Voice":
            # --- GPU path: CosyVoice3 zero-shot cloning ----------------------
            with self._lock:
                loaded = self._load_cosyvoice()
                cosyvoice      = self._cosyvoice
                spk_registered = self._spk_registered

            if loaded and cosyvoice is not None:
                try:
                    for chunk in self._stream_cosyvoice(cosyvoice, spk_registered, text):
                        yield chunk
                    return
                except Exception as exc:
                    logger.warning(
                        f"[TTSManager] CosyVoice stream failed, falling back to Piper: {exc}"
                    )

        if not USE_COSYVOICE or self.config.get("tts_voice") != "Cloned Voice":
            # --- CPU path: Piper (fast, ~50 ms) ------------------------------
            with self._lock:
                piper_loaded = self._load_piper()
                piper = self._piper

            if piper_loaded and piper is not None:
                try:
                    for chunk in self._stream_piper(piper, text):
                        yield chunk
                    return
                except Exception as exc:
                    logger.warning(
                        f"[TTSManager] Piper stream failed, falling back to pyttsx3: {exc}"
                    )

        # --- pyttsx3 last-resort fallback -----------------------------------
        try:
            result = self._synthesize_pyttsx(text)
            if result is not None:
                yield result
        except Exception as exc:
            logger.error(f"[TTSManager] pyttsx3 stream error: {exc}")

    # ------------------------------------------------------------------
    # Piper engine (CPU primary)
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
    def _stream_piper(
        piper,
        text: str,
    ) -> Generator[np.ndarray, None, None]:
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
    # CosyVoice engine (GPU only)
    # ------------------------------------------------------------------

    def _ensure_cosyvoice_paths(self) -> None:
        """Add CosyVoice source directories to sys.path if not already there."""
        cv_dir     = str(COSYVOICE_DIR)
        matcha_dir = str(COSYVOICE_DIR / "third_party" / "Matcha-TTS")
        for p in (cv_dir, matcha_dir):
            if p not in sys.path:
                sys.path.insert(0, p)

    def _load_cosyvoice(self) -> bool:
        """Load CosyVoice2-0.5B and register the cloned voice prompt.

        Must be called under self._lock.  Returns True on success.
        """
        if self._cosyvoice is not None:
            return True

        if not MODEL_DIR.exists():
            logger.warning(
                f"[TTSManager] CosyVoice model not found at {MODEL_DIR} — "
                "falling back to pyttsx3"
            )
            return False

        try:
            self._ensure_cosyvoice_paths()
            from cosyvoice.cli.cosyvoice import AutoModel

            logger.info(f"[TTSManager] Loading CosyVoice3-0.5B from {MODEL_DIR}...")
            self._cosyvoice = AutoModel(model_dir=str(MODEL_DIR))
            logger.info(
                f"[TTSManager] CosyVoice3-0.5B loaded "
                f"(sample_rate={getattr(self._cosyvoice, 'sample_rate', COSYVOICE_NATIVE_RATE)})"
            )

            self._register_speaker()
            return True

        except Exception as exc:
            logger.error(f"[TTSManager] Failed to load CosyVoice: {exc}", exc_info=True)
            self._cosyvoice = None
            return False

    def _register_speaker(self) -> None:
        """Register TOMV2.wav as the 'tommv2' zero-shot speaker.

        CosyVoice2 stores a speaker embedding so subsequent calls skip WAV
        re-encoding.  Must be called under self._lock (via _load_cosyvoice).
        """
        if self._spk_registered or self._cosyvoice is None:
            return
        if not REFERENCE_AUDIO.exists():
            logger.warning(
                f"[TTSManager] Reference audio not found: {REFERENCE_AUDIO} — "
                "voice cloning disabled; will use pyttsx3 fallback"
            )
            return

        try:
            # add_zero_shot_spk(prompt_text, prompt_speech_path, spk_id)
            # CosyVoice3 requires <|endofprompt|> in prompt_text (CosyVoice2 accepted "").
            result = self._cosyvoice.add_zero_shot_spk(
                COSYVOICE3_PROMPT_PREFIX, str(REFERENCE_AUDIO), SPK_ID
            )
            if result is not False:
                self._spk_registered = True
                logger.info(f"[TTSManager] Registered speaker '{SPK_ID}' from {REFERENCE_AUDIO.name}")
            else:
                logger.warning("[TTSManager] add_zero_shot_spk returned False — direct WAV path will be used")
        except Exception as exc:
            logger.warning(f"[TTSManager] Speaker registration failed ({exc}); direct WAV path will be used")

    @staticmethod
    def _stream_cosyvoice(
        cosyvoice,
        spk_registered: bool,
        text: str,
    ) -> Generator[np.ndarray, None, None]:
        """Run CosyVoice2 zero-shot inference and yield resampled float32 chunks.

        Called WITHOUT self._lock — inference is thread-safe once the model
        is loaded.  Each yielded chunk is ready to play immediately.
        """
        native_rate = getattr(cosyvoice, "sample_rate", COSYVOICE_NATIVE_RATE)

        if spk_registered:
            # Registered speaker path: prompt_text/wav can be empty because the
            # speaker embedding (including the <|endofprompt|> token) was stored
            # by add_zero_shot_spk using COSYVOICE3_PROMPT_PREFIX.
            gen = cosyvoice.inference_zero_shot(
                text, "", "", zero_shot_spk_id=SPK_ID, stream=True
            )
        elif REFERENCE_AUDIO.exists():
            # Direct wav path: CosyVoice3 requires <|endofprompt|> in prompt_text.
            gen = cosyvoice.inference_zero_shot(
                text, COSYVOICE3_PROMPT_PREFIX, str(REFERENCE_AUDIO), stream=True
            )
        else:
            logger.warning("[TTSManager] No speaker and no reference audio — skipping CosyVoice")
            return

        for chunk in gen:
            wav = chunk.get("tts_speech")
            if wav is None:
                continue
            audio = wav.numpy().flatten().astype(np.float32)
            if len(audio) == 0:
                continue
            audio = _resample(audio, native_rate)
            logger.debug(
                f"[TTSManager] CosyVoice chunk: {len(audio)} samples @ {native_rate} Hz"
            )
            yield audio

    # ------------------------------------------------------------------
    # pyttsx3 fallback (SAPI5 — writes to temp WAV, then reads back)
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
