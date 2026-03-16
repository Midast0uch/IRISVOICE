"""
TTS Manager — LuxTTS voice synthesis for IRIS.

Primary engine : LuxTTS / ZipVoice (offline, high quality, voice cloning)
  - Requires a reference wav at: IRISVOICE/data/voice_clone_ref.wav (3-5 seconds)
  - Model downloads automatically from HuggingFace (YatharthS/LuxTTS, ~1 GB)
  - Output: 48 kHz → resampled to 16 kHz for playback
  - Uses CUDA if available, falls back to CPU automatically

Fallback        : pyttsx3 Built-in (Windows SAPI5 — zero download, instant)
"""
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LUXTTS_MODEL = "YatharthS/LuxTTS"
LUXTTS_SAMPLE_RATE = 48000

AVAILABLE_VOICES: List[str] = ["Cloned Voice", "Built-in"]

# Path to user's voice clone reference audio (3-5 seconds recommended)
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_CLONE_REF = _DATA_DIR / "voice_clone_ref.wav"


class TTSManager:
    """
    Singleton TTS manager. Lazy-loads LuxTTS on first synthesis so
    startup is never blocked by model downloading/loading.
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
            "speaking_rate": 1.0,   # 0.5 – 2.0
        }

        self._lux: Optional[Any] = None
        self._lux_encode_dict: Optional[Any] = None
        self._lux_lock = threading.Lock()
        self._pyttsx_engine = None

        TTSManager._initialized = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    AVAILABLE_VOICES = AVAILABLE_VOICES

    def update_config(self, **kwargs) -> None:
        """Update TTS configuration (called by iris_gateway on confirm_card)."""
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value
        logger.info(f"[TTSManager] Config updated: {kwargs}")

    def get_config(self) -> Dict[str, Any]:
        return self.config.copy()

    def get_voice_info(self) -> Dict[str, Any]:
        return {
            "available_voices": AVAILABLE_VOICES,
            "current_voice":    self.config["tts_voice"],
            "config":           self.config,
        }

    def synthesize(self, text: str) -> Optional[np.ndarray]:
        """
        Synthesize text → float32 numpy audio array (mono, 16 kHz).
        Returns None if TTS is disabled, text is empty, or synthesis fails.
        """
        if not self.config.get("tts_enabled", True):
            return None
        text = (text or "").strip()
        if not text:
            return None

        voice_label = self.config.get("tts_voice", "Cloned Voice")

        if voice_label == "Built-in":
            return self._synthesize_pyttsx(text)

        return self._synthesize_luxtts(text)

    # ------------------------------------------------------------------
    # LuxTTS engine
    # ------------------------------------------------------------------

    def _get_lux(self) -> Any:
        """Lazy-load and cache the LuxTTS instance (thread-safe)."""
        if self._lux is None:
            with self._lux_lock:
                if self._lux is None:
                    try:
                        from zipvoice.luxvoice import LuxTTS
                        import torch
                        device = "cuda" if torch.cuda.is_available() else "cpu"
                        logger.info(f"[TTSManager] Loading LuxTTS on {device} ...")
                        lux = LuxTTS(LUXTTS_MODEL, device=device)
                        self._lux = lux
                        logger.info(f"[TTSManager] LuxTTS ready ({device})")
                    except Exception as e:
                        logger.error(f"[TTSManager] LuxTTS load failed: {e}")
                        raise
        return self._lux

    def _get_encode_dict(self, lux: Any) -> Optional[Any]:
        """
        Encode the voice reference prompt (result is cached).
        Returns None if the reference file is missing.
        """
        if self._lux_encode_dict is None:
            if not _CLONE_REF.exists():
                return None
            try:
                logger.info(f"[TTSManager] Encoding voice reference: {_CLONE_REF}")
                self._lux_encode_dict = lux.encode_prompt(str(_CLONE_REF))
                logger.info("[TTSManager] Voice reference encoded OK")
            except Exception as e:
                logger.error(f"[TTSManager] encode_prompt failed: {e}")
                return None
        return self._lux_encode_dict

    def _synthesize_luxtts(self, text: str) -> Optional[np.ndarray]:
        """
        Synthesize with LuxTTS voice cloning.
        Falls back to pyttsx3 if the reference file is missing or LuxTTS fails.
        """
        try:
            lux = self._get_lux()
        except Exception:
            logger.warning("[TTSManager] LuxTTS unavailable, falling back to Built-in")
            return self._synthesize_pyttsx(text)

        encode_dict = self._get_encode_dict(lux)
        if encode_dict is None:
            if _CLONE_REF.exists():
                logger.warning(
                    f"[TTSManager] Voice reference encoding failed (torchcodec/FFmpeg unavailable). "
                    "Install FFmpeg full-shared (e.g. 'winget install ffmpeg') and restart IRIS. "
                    "Falling back to Built-in TTS."
                )
            else:
                logger.warning(
                    f"[TTSManager] Voice reference not found at {_CLONE_REF}. "
                    "Place a 3-5s WAV of your target voice there, then restart IRIS. "
                    "Falling back to Built-in TTS."
                )
            return self._synthesize_pyttsx(text)

        try:
            rate = float(self.config.get("speaking_rate", 1.0))
            wav = lux.generate_speech(text, encode_dict, num_steps=4, speed=rate)
            audio: np.ndarray = wav.numpy().squeeze().astype(np.float32)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            audio = self._resample(audio, LUXTTS_SAMPLE_RATE, 16000)
            peak = np.abs(audio).max()
            if peak > 0:
                audio = audio / peak * 0.9
            logger.debug(f"[TTSManager] LuxTTS synthesized {len(audio)} samples ({len(audio)/16000:.2f}s)")
            return audio
        except RuntimeError as e:
            if "Kernel size can't be greater than actual input size" in str(e):
                # Text is too short for LuxTTS vocoder convolution kernel.
                # Fall back to pyttsx3 for very short utterances.
                logger.warning(
                    f"[TTSManager] LuxTTS: text too short for vocoder ({len(text)} chars), "
                    "falling back to Built-in TTS."
                )
                return self._synthesize_pyttsx(text)
            logger.error(f"[TTSManager] LuxTTS synthesis error: {e}", exc_info=True)
            return self._synthesize_pyttsx(text)
        except Exception as e:
            logger.error(f"[TTSManager] LuxTTS synthesis error: {e}", exc_info=True)
            return self._synthesize_pyttsx(text)

    # ------------------------------------------------------------------
    # pyttsx3 fallback (Built-in / Windows SAPI5)
    # ------------------------------------------------------------------

    def _synthesize_pyttsx(self, text: str) -> Optional[np.ndarray]:
        """Synthesize with pyttsx3 SAPI5. Returns float32 array at 16 kHz."""
        try:
            if self._pyttsx_engine is None:
                import pyttsx3
                self._pyttsx_engine = pyttsx3.init()
                self._pyttsx_engine.setProperty("rate", 175)
                self._pyttsx_engine.setProperty("volume", 1.0)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name

            try:
                self._pyttsx_engine.save_to_file(text, tmp_path)
                self._pyttsx_engine.runAndWait()
                audio, sr = self._read_wav(tmp_path)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

            audio = audio.astype(np.float32)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            if sr != 16000:
                audio = self._resample(audio, sr, 16000)
            return audio

        except Exception as e:
            logger.error(f"[TTSManager] pyttsx3 synthesis error: {e}")
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_wav(path: str) -> Tuple[np.ndarray, int]:
        """Read a WAV file using stdlib wave, returning (float32_array, sample_rate)."""
        import wave
        with wave.open(path, "rb") as wf:
            sr = wf.getframerate()
            n_frames = wf.getnframes()
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            raw = wf.readframes(n_frames)

        dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
        dtype = dtype_map.get(sampwidth, np.int16)
        audio = np.frombuffer(raw, dtype=dtype).astype(np.float32)
        audio = audio / float(np.iinfo(dtype).max)

        if n_channels > 1:
            audio = audio.reshape(-1, n_channels).mean(axis=1)

        return audio, sr

    @staticmethod
    def _resample(audio: np.ndarray, from_sr: int, to_sr: int) -> np.ndarray:
        """Resample mono float32 array using torchaudio (with scipy fallback)."""
        try:
            import torch
            import torchaudio.functional as F
            t = torch.from_numpy(audio).unsqueeze(0)
            t = F.resample(t, from_sr, to_sr)
            return t.squeeze(0).numpy()
        except Exception:
            from scipy.signal import resample_poly
            from math import gcd
            g = gcd(from_sr, to_sr)
            return resample_poly(audio, to_sr // g, from_sr // g).astype(np.float32)


def get_tts_manager() -> TTSManager:
    """Return the process-wide TTSManager singleton."""
    return TTSManager()
