"""
TTS Manager — CosyVoice 2.0 (zero-shot voice cloning) for IRIS.

Primary engine : CosyVoice2-0.5B
  - Zero-shot voice cloning from TOMV2.wav reference (pre-registered as 'tommv2')
  - Streaming: yields audio chunks as soon as they are ready (~150 ms first-chunk)
  - 24 kHz native output — passed directly to sd.play() (no intermediate resampling)
  - CUDA if available, CPU otherwise

Fallback        : pyttsx3 (Windows SAPI5 — zero download, instant)

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

COSYVOICE_NATIVE_RATE: int = 24_000  # CosyVoice2-0.5B native rate
OUTPUT_SAMPLE_RATE:   int = COSYVOICE_NATIVE_RATE  # pass native rate to sd.play() directly
PYTTSX_NATIVE_RATE:   int = 22_050   # pyttsx3 / SAPI5 typical rate
SAMPLE_RATE:          int = OUTPUT_SAMPLE_RATE  # legacy alias

# Paths (relative to this file: backend/agent/tts.py)
_THIS_DIR    = Path(__file__).parent          # backend/agent/
_BACKEND_DIR = _THIS_DIR.parent               # backend/
_PROJECT_DIR = _BACKEND_DIR.parent            # IRISVOICE/

COSYVOICE_DIR   = _BACKEND_DIR / "voice" / "CosyVoice"
MODEL_DIR       = _BACKEND_DIR / "voice" / "pretrained_models" / "CosyVoice2-0.5B"
REFERENCE_AUDIO = _PROJECT_DIR / "data" / "TOMV2.wav"
SPK_ID          = "tommv2"

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

    Primary engine  : CosyVoice2-0.5B — zero-shot voice cloning via TOMV2.wav.
    Fallback engine : pyttsx3 SAPI5.

    Both engines produce float32 audio at OUTPUT_SAMPLE_RATE (24 kHz) ready
    for AudioPipeline.play_audio(sample_rate=24000).  sd.play() handles the
    single-step conversion to the device's native rate.
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

        self.config: Dict[str, Any] = {
            "tts_enabled":   True,
            "tts_voice":     "Cloned Voice",
            "speaking_rate": 1.0,
        }

        self._cosyvoice      = None     # AutoModel instance (lazy-loaded)
        self._spk_registered = False    # Whether TOMV2 speaker is registered
        self._lock           = threading.Lock()   # guards init only, NOT inference
        self._ready_event    = threading.Event()  # set when model+speaker ready

        TTSManager._initialized = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    AVAILABLE_VOICES = AVAILABLE_VOICES

    def _warm_tts_pipeline(self) -> None:
        """Pre-load CosyVoice model and register voice in a background thread.

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
            logger.info("[TTSManager] CosyVoice2 ready event set")

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
        return {
            "available_voices": AVAILABLE_VOICES,
            "current_voice":    self.config.get("tts_voice", "Cloned Voice"),
            "config":           self.get_config(),
            "model":            "CosyVoice2-0.5B (zero-shot voice cloning)",
            "sample_rate":      OUTPUT_SAMPLE_RATE,
            "reference_audio":  str(REFERENCE_AUDIO),
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

        if self.config.get("tts_voice") == "Cloned Voice":
            # --- Step 1: ensure model is loaded (under lock) ----------------
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
                        f"[TTSManager] CosyVoice stream failed, falling back to pyttsx3: {exc}"
                    )

        # --- pyttsx3 fallback -----------------------------------------------
        try:
            result = self._synthesize_pyttsx(text)
            if result is not None:
                yield result
        except Exception as exc:
            logger.error(f"[TTSManager] pyttsx3 stream error: {exc}")

    # ------------------------------------------------------------------
    # CosyVoice engine
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

            logger.info(f"[TTSManager] Loading CosyVoice2-0.5B from {MODEL_DIR}...")
            self._cosyvoice = AutoModel(model_dir=str(MODEL_DIR))
            logger.info(
                f"[TTSManager] CosyVoice2-0.5B loaded "
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
            # Empty prompt_text is acceptable for CosyVoice2.
            result = self._cosyvoice.add_zero_shot_spk("", str(REFERENCE_AUDIO), SPK_ID)
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
            gen = cosyvoice.inference_zero_shot(
                text, "", "", zero_shot_spk_id=SPK_ID, stream=True
            )
        elif REFERENCE_AUDIO.exists():
            gen = cosyvoice.inference_zero_shot(
                text, "", str(REFERENCE_AUDIO), stream=True
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
