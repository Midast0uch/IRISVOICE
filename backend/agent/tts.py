"""
TTS Manager — Pocket-TTS (voice cloning) for IRIS.
Sole engine : Pocket-TTS (~100M int8 quantized, ~100 MB RAM)
  - Zero-shot voice cloning from reference audio (TOMV2.wav)
  - True streaming inference (generate_audio_stream — yields chunk-by-chunk)
  - Text normalizer wired in: strips markdown, expands symbols, removes
    code blocks so TTS never reads out "$", "%", "->", "**bold**" etc.
  - 24 kHz native output

Setup           : pip install pocket-tts
                  Place TOMV2.wav at IRISVOICE/data/TOMV2.wav

Lock discipline
  self._lock guards model initialisation only.  It is released before
  inference so synthesis never blocks the consumer's audio-queue timeout.
  The lock is NOT reentrant — do not acquire it inside _stream_pocket.
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

TTS_NATIVE_RATE: int = 24_000  # Pocket-TTS native output sample rate
OUTPUT_SAMPLE_RATE: int = TTS_NATIVE_RATE  # pipeline rate
SAMPLE_RATE: int = OUTPUT_SAMPLE_RATE  # legacy alias

# Paths (relative to this file: backend/agent/tts.py)
_THIS_DIR = Path(__file__).parent  # backend/agent/
_BACKEND_DIR = _THIS_DIR.parent  # backend/
_PROJECT_DIR = _BACKEND_DIR.parent  # IRISVOICE/

REFERENCE_AUDIO = _PROJECT_DIR / "data" / "TOMV2.wav"

AVAILABLE_VOICES: List[str] = [
    "Cloned Voice",
    "alba",
    "marius",
    "javert",
    "jean",
    "fantine",
    "cosette",
    "eponine",
    "azelma",
]


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
    """Split *text* into sentence-level chunks suitable for Pocket-TTS synthesis.

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

    Engine: Pocket-TTS (sole engine)
      - Zero-shot voice cloning from TOMV2.wav
      - CPU-based, int8 quantized, ~100 MB RAM (lazy load)
      - True streaming inference (yields chunk-by-chunk)
      - 24 kHz native output

    Text is normalised before synthesis (markdown stripped, symbols
    expanded to spoken words).

    IMPORTANT — first-time setup:
      pip install pocket-tts
      Place TOMV2.wav at IRISVOICE/data/TOMV2.wav to enable voice cloning.
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
            "tts_enabled": True,
            "tts_voice": "Cloned Voice",  # Pocket-TTS voice cloning
            "speaking_rate": 1.0,
        }

        # Engine instance (lazy-loaded)
        self._pocket_tts_model = None  # Pocket-TTS model instance
        self._voice_state = None  # cached voice embedding from TOMV2.wav
        self._filler_cache: Dict[str, tuple] = {}  # phrase → (audio_array, sample_rate)
        self._lock = threading.Lock()  # guards init only, NOT inference

        TTSManager._initialized = True

        threading.Thread(
            target=self._log_preflight, daemon=True, name="tts-preflight"
        ).start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _log_preflight(self) -> None:
        """Log TTS preflight status at startup."""
        if not REFERENCE_AUDIO.exists():
            logger.warning(
                f"[TTSManager] Reference audio not found at {REFERENCE_AUDIO}. "
                "Place TOMV2.wav at IRISVOICE/data/TOMV2.wav to enable voice cloning."
            )
        else:
            logger.info(
                f"[TTSManager] Pocket-TTS — reference audio OK at {REFERENCE_AUDIO}"
            )

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
            "current_voice": self.config.get("tts_voice", "Cloned Voice"),
            "config": self.get_config(),
            "model": "Pocket-TTS (~100M, zero-shot voice cloning, int8)",
            "model_ready": self._pocket_tts_model is not None,
            "model_path_exists": True,  # installed via pip
            "reference_audio": str(REFERENCE_AUDIO),
            "reference_audio_exists": REFERENCE_AUDIO.exists(),
            "sample_rate": OUTPUT_SAMPLE_RATE,
        }

    def is_loaded(self) -> bool:
        """Return True if Pocket-TTS model and voice state are loaded."""
        return self._pocket_tts_model is not None

    def synthesize(self, text: Optional[str]) -> Optional[np.ndarray]:
        """Synthesize speech from text.

        Returns float32 array at OUTPUT_SAMPLE_RATE Hz, or None on failure.

        On first call, dumps raw output to a timestamped .wav file in
        data/tts_dumps/ for diagnostic comparison (good vs degraded paths).
        """
        if not self.config.get("tts_enabled", True):
            return None
        if not text or not text.strip():
            return None
        chunks = list(self.synthesize_stream(text))
        if chunks:
            audio = np.concatenate(chunks)
            self._dump_raw_audio(audio, "tts_synthesize")
            return audio
        return None

    def _dump_raw_audio(self, audio: np.ndarray, label: str) -> None:
        """Dump raw float32 audio to a .wav file for diagnostic comparison.

        Only dumps on the first call per process.  File is written to
        data/tts_dumps/ with a timestamped name.
        """
        if getattr(self, "_did_dump_audio", False):
            return
        self._did_dump_audio = True
        try:
            import time as _t
            from pathlib import Path as _P

            dump_dir = _P(__file__).parent.parent / "data" / "tts_dumps"
            dump_dir.mkdir(parents=True, exist_ok=True)
            ts = _t.strftime("%Y%m%d_%H%M%S", _t.localtime())
            path = dump_dir / f"{label}_{ts}.wav"
            import scipy.io.wavfile as _wav

            # Ensure float32, clip to [-1, 1], convert to int16 for WAV
            audio_f32 = np.clip(audio.astype(np.float32), -1.0, 1.0)
            audio_i16 = (audio_f32 * 32767.0).astype(np.int16)
            _wav.write(str(path), OUTPUT_SAMPLE_RATE, audio_i16)
            logger.info(
                f"[TTSManager] Raw audio dump: {path} "
                f"({len(audio_i16)} samples, {OUTPUT_SAMPLE_RATE} Hz, int16)"
            )
        except Exception as _dump_err:
            logger.debug(f"[TTSManager] Audio dump skipped: {_dump_err}")

    # Silence durations for natural pacing (in seconds)
    _INTER_SENTENCE_SILENCE: float = 0.50  # 500ms pause between sentences
    _TRAILING_SILENCE: float = 0.60  # 600ms silence after last word

    def synthesize_stream(self, text: str) -> Generator[np.ndarray, None, None]:
        """Stream synthesis — yields float32 arrays at OUTPUT_SAMPLE_RATE Hz.

        Text is normalised before synthesis (strips markdown / expands symbols).
        Pocket-TTS: streaming yields chunks during generation (true streaming).

        Natural pacing: text is split into sentences. Each sentence is
        synthesized separately, with a short silence gap inserted between
        sentences. A trailing silence is appended after the final sentence
        so TTS doesn't end abruptly.

        Lock discipline: self._lock held only during model load, not inference.
        """
        import logging as _logging

        _root_log = _logging.getLogger()
        _root_log.info(
            f"[TTSManager] synthesize_stream ENTRY: {len(text)} chars, "
            f"text={text[:80]!r}"
        )
        if not self.config.get("tts_enabled", True):
            _root_log.warning("[TTSManager] TTS disabled in config, returning empty")
            return
        if not text.strip():
            _root_log.warning("[TTSManager] Empty text, returning empty")
            return

        # Normalise text before synthesis
        normalized = self._normalize(text)
        if not normalized:
            _root_log.warning("[TTSManager] Normalized text is empty, returning empty")
            return

        # --- Pocket-TTS: sole engine (zero-shot voice cloning) ----------------
        with self._lock:
            loaded = self._load_pocket_tts()
            pocket = self._pocket_tts_model
            voice = self._voice_state

        _root_log.info(
            f"[TTSManager] model state: loaded={loaded}, "
            f"pocket={'OK' if pocket else 'None'}, voice={'OK' if voice else 'None'}"
        )

        if loaded and pocket is not None and voice is not None:
            # ── Split into sentences for natural pacing ──────────────────
            # Each sentence is synthesized separately, with a short silence
            # gap inserted between them so the speech doesn't sound rushed.
            sentences = _split_into_chunks(normalized, max_chars=200)
            _root_log.info(
                f"[TTSManager] split into {len(sentences)} sentence(s) for pacing"
            )

            silence_gap = int(self._INTER_SENTENCE_SILENCE * OUTPUT_SAMPLE_RATE)
            trailing = int(self._TRAILING_SILENCE * OUTPUT_SAMPLE_RATE)
            _chunk_count = 0
            _total_samples = 0

            try:
                for idx, sentence in enumerate(sentences):
                    for chunk in self._stream_pocket(pocket, voice, sentence):
                        _chunk_count += 1
                        _total_samples += len(chunk) if chunk is not None else 0
                        yield chunk

                    # Insert silence between sentences (not after the last one)
                    if idx < len(sentences) - 1 and silence_gap > 0:
                        yield np.zeros(silence_gap, dtype=np.float32)

                # Trailing silence so TTS doesn't end abruptly
                if trailing > 0:
                    yield np.zeros(trailing, dtype=np.float32)

                _root_log.info(
                    f"[TTSManager] produced {_chunk_count} chunks, "
                    f"{_total_samples} samples total "
                    f"({len(sentences)} sentences, "
                    f"{silence_gap/OUTPUT_SAMPLE_RATE*1000:.0f}ms gaps, "
                    f"{trailing/OUTPUT_SAMPLE_RATE*1000:.0f}ms trailing)"
                )
                return
            except Exception as exc:
                _root_log.error(
                    f"[TTSManager] Pocket-TTS stream failed: {exc}",
                    exc_info=True,
                )
        else:
            _root_log.error(
                f"[TTSManager] Pocket-TTS unavailable — synthesis produced "
                f"ZERO audio. loaded={loaded}, model={'OK' if pocket else 'None'}, "
                f"voice={'OK' if voice else 'None'}, "
                f"text_preview={text[:80]!r}. "
                f"Check previous error logs for the reason."
            )

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
    PREDEFINED_VOICES = [
        "alba",
        "marius",
        "javert",
        "jean",
        "fantine",
        "cosette",
        "eponine",
        "azelma",
    ]

    def _load_pocket_tts(self) -> bool:
        """Load Pocket-TTS model + voice/voice-state (once, cached)."""
        if self._pocket_tts_model is not None:
            return True
        try:
            # Pocket-TTS v2.x applies beartype runtime type-checking to every
            # function at import time, which adds ~40s to the first import.
            # No-op it here — we don't need runtime type validation in production.
            import beartype.claw as _bt
            _bt.beartype_this_package = lambda **_: None
        except ImportError:
            pass

        try:
            from pocket_tts import TTSModel

            t0 = time.monotonic()
            # Pocket-TTS v2.1.0 API: load_model accepts `language` (not `variant`).
            # Available languages: english, english_2026-01, english_2026-04, french_24l, etc.
            # Override via POCKET_TTS_LANGUAGE env var (default: "english").
            # The eos_threshold=-1.0 forces clean EOS termination (default -4.0 hits
            # max length with broken voice state, producing garbled tail).
            model_lang = os.environ.get("POCKET_TTS_LANGUAGE", "english")
            self._pocket_tts_model = TTSModel.load_model(
                language=model_lang,
                eos_threshold=-1.0,
            )
            dt = time.monotonic() - t0
            logger.info(f"[TTSManager] Pocket-TTS model loaded in {dt:.1f}s")
            self._load_voice_state()
            # Pre-synthesize filler phrases (async-friendly, runs once)
            threading.Thread(
                target=self._pre_synthesize_fillers,
                daemon=True,
                name="tts-fillers",
            ).start()
            return True
        except ImportError:
            logger.error(
                "[TTSManager] pocket-tts not installed. Run: pip install pocket-tts"
            )
            self._pocket_tts_model = None
            return False
        except Exception as exc:
            logger.error(
                f"[TTSManager] Failed to load Pocket-TTS: {exc}",
                exc_info=True,
            )
            self._pocket_tts_model = None
            return False

    def _load_voice_state(self) -> bool:
        """Load the appropriate voice state: cloned from TOMV2.wav or catalog embedding."""
        if self._voice_state is not None:
            return True

        voice_name = self.config.get("tts_voice", "Cloned Voice")

        # --- Catalog voice path ---
        if voice_name in self.PREDEFINED_VOICES:
            return self._load_catalog_voice(voice_name)

        # --- Voice cloning path (Cloned Voice / default) ---
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
                logger.error(
                    f"[TTSManager] Failed to clone voice '{voice_name}' from "
                    f"{ref_path}: {exc}",
                    exc_info=True,
                )

        logger.warning(
            "[TTSManager] Voice cloning failed — falling back to catalog voice 'alba'. "
            "Accept terms at https://huggingface.co/kyutai/pocket-tts "
            "to enable voice cloning."
        )
        # Fallback to first catalog voice
        return self._load_catalog_voice(self.PREDEFINED_VOICES[0])

    # ------------------------------------------------------------------
    # Filler phrase pre-synthesis
    # ------------------------------------------------------------------

    FILLER_PHRASES = [
        "One moment.",
        "Let me check that for you.",
        "Hmm, let me think.",
        "Give me a second.",
        "Looking into it.",
    ]

    def _pre_synthesize_fillers(self) -> None:
        """Pre-synthesize short filler phrases to .wav cache + in-memory arrays.

        Called once after voice state is loaded.  These are played alongside
        STTPROC during the LLM thinking gap so the user hears speech instead
        of silence.
        """
        if self._pocket_tts_model is None or self._voice_state is None:
            return

        fillers_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data", "fillers",
        )
        os.makedirs(fillers_dir, exist_ok=True)

        for phrase in self.FILLER_PHRASES:
            # Check if already cached
            safe_name = phrase.lower().replace(" ", "_").replace(".", "").replace(",", "")
            wav_path = os.path.join(fillers_dir, f"{safe_name}.wav")
            if os.path.isfile(wav_path):
                # Load from cache
                try:
                    import soundfile as _sf_f
                    data, sr = _sf_f.read(wav_path, dtype="float32")
                    if data.ndim > 1:
                        data = data.mean(axis=1)
                    self._filler_cache[phrase] = (data, sr)
                    continue
                except Exception:
                    pass  # Re-synthesize if cache is corrupt

            # Synthesize
            try:
                import soundfile as _sf_f
                audio_chunks = []
                for chunk in self._pocket_tts_model.generate_audio_stream(
                    self._voice_state,
                    phrase,
                ):
                    if chunk is not None and len(chunk) > 0:
                        audio_chunks.append(chunk)
                if audio_chunks:
                    import numpy as _np_f
                    audio = _np_f.concatenate(audio_chunks)
                    _sf_f.write(wav_path, audio, 24000)
                    self._filler_cache[phrase] = (audio, 24000)
                    logger.info(f"[TTSManager] Pre-synthesized filler: {phrase!r}")
            except Exception as exc:
                logger.warning(f"[TTSManager] Filler synthesis failed for {phrase!r}: {exc}")

    def get_filler_audio(self) -> Optional[tuple]:
        """Return a random pre-synthesized filler phrase audio + sample rate."""
        if not self._filler_cache:
            return None
        import random as _rand
        phrase = _rand.choice(list(self._filler_cache.keys()))
        return self._filler_cache[phrase]

    def _load_catalog_voice(self, voice_name: str) -> bool:
        """Download a Pocket-TTS catalog voice embedding and convert to state dict."""
        try:
            from huggingface_hub import hf_hub_download
            from safetensors.torch import load_file
            import torch

            t0 = time.monotonic()
            emb_path = hf_hub_download(
                repo_id="kyutai/pocket-tts",
                filename=f"languages/english/embeddings/{voice_name}.safetensors",
            )
            flat = load_file(emb_path)

            # Convert flat key format (e.g. "transformer.layers.0.self_attn/cache")
            # to nested dict format expected by generate_audio_stream
            state = {}
            for flat_key, tensor in flat.items():
                module_path, attr = flat_key.split("/")
                if module_path not in state:
                    state[module_path] = {}
                state[module_path][attr] = tensor

            self._voice_state = state
            dt = time.monotonic() - t0
            logger.info(
                f"[TTSManager] Catalog voice '{voice_name}' loaded in {dt:.1f}s "
                f"({len(flat)} tensors)"
            )
            return True
        except Exception as exc:
            logger.error(
                f"[TTSManager] Failed to load catalog voice '{voice_name}': {exc}",
                exc_info=True,
            )
            self._voice_state = None
            return False

    def _stream_pocket(
        self,
        model,
        voice_state,
        text: str,
    ) -> Generator[np.ndarray, None, None]:
        """Stream audio chunks from Pocket-TTS (true streaming inference)."""
        if model is None or voice_state is None:
            logger.error(
                f"[TTSManager] _stream_pocket called with model=None "
                f"(model={'OK' if model else 'None'}, "
                f"voice={'OK' if voice_state else 'None'})"
            )
            return
        self._dump_call_count = getattr(self, "_dump_call_count", 0) + 1
        _should_dump = self._dump_call_count <= 1
        _dump_chunks = []
        _yielded = 0
        _total_samples = 0
        _t_start = time.monotonic()
        try:
            for chunk_tensor in model.generate_audio_stream(
                voice_state,
                text,
                frames_after_eos=0,  # stop at EOS — no trailing frames (reduces static artifacts)
            ):
                audio = chunk_tensor.cpu().numpy().astype(np.float32)
                if len(audio) == 0:
                    continue
                # Clamp NaN/Inf values — these produce harsh digital noise when
                # converted to int16 during playback. NaN/Inf indicates GPU memory
                # corruption or torch state pollution from shared-process ASR.
                n_nan = int(np.isnan(audio).sum())
                n_inf = int(np.isinf(audio).sum())
                if n_nan > 0 or n_inf > 0:
                    logger.warning(
                        f"[TTSManager] NaN/Inf detected in raw TTS output: "
                        f"{n_nan} NaN, {n_inf} Inf — clamping to zero. "
                        f"This may indicate GPU memory corruption from shared-process ASR."
                    )
                    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
                # Accumulate for first-call diagnostic dump
                if _should_dump:
                    _dump_chunks.append(audio.copy())
                # Skip near-silent lead-in chunks (Pocket-TTS warm-up artifacts).
                # First ~3 chunks (240 ms) are ~60 dB below actual speech RMS.
                if np.max(np.abs(audio)) < 0.01:
                    continue
                _yielded += 1
                _total_samples += len(audio)
                yield audio
        except Exception as exc:
            logger.error(
                f"[TTSManager] Pocket-TTS stream failed: {exc}",
                exc_info=True,
            )
        finally:
            _t_elapsed = time.monotonic() - _t_start
            if _yielded == 0:
                logger.error(
                    f"[TTSManager] _stream_pocket yielded ZERO audio chunks in "
                    f"{_t_elapsed:.2f}s — TTS produced silence. "
                    f"text={text[:60]!r}, model={'OK' if model else 'None'}"
                )
            else:
                logger.info(
                    f"[TTSManager] stream end: {_yielded} chunks, "
                    f"{_total_samples} samples "
                    f"({_total_samples/OUTPUT_SAMPLE_RATE:.1f}s audio) "
                    f"in {_t_elapsed:.2f}s"
                )
                # Structured playback log: when audio REALLY flowed, with the
                # spoken text + wall-clock timestamp. Pairs with the SpeakTool
                # SPEAK-intent log so live-test screenshots can be correlated
                # to which thread/text played and exactly when.
                logger.info(
                    "[TTSManager] PLAYBACK ts=%.3f dur=%.2fs text=%r",
                    time.time(),
                    _t_elapsed,
                    (text or "")[:80],
                )
            # Diagnostic dump: save first TTS call's raw output to .wav
            if _should_dump and _dump_chunks:
                try:
                    import scipy.io.wavfile as _wav
                    import time as _t
                    from pathlib import Path as _P

                    dump_dir = _P(__file__).parent.parent / "data" / "tts_dumps"
                    dump_dir.mkdir(parents=True, exist_ok=True)
                    ts = _t.strftime("%Y%m%d_%H%M%S", _t.localtime())
                    path = dump_dir / f"tts_stream_{ts}.wav"
                    full = np.concatenate(_dump_chunks)
                    # Clip and convert to int16 for WAV
                    full_i16 = (np.clip(full, -1.0, 1.0) * 32767.0).astype(np.int16)
                    _wav.write(str(path), OUTPUT_SAMPLE_RATE, full_i16)
                    logger.info(
                        f"[TTSManager] Diagnotic dump: {path} "
                        f"({len(full_i16)} samples, {OUTPUT_SAMPLE_RATE} Hz, "
                        f"max={float(np.max(np.abs(full))):.4f})"
                    )
                except Exception as _de:
                    logger.debug(f"[TTSManager] Diagnotic dump skipped: {_de}")


def get_tts_manager() -> TTSManager:
    """Return the process-wide TTSManager singleton."""
    return TTSManager()
