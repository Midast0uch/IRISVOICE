"""
TTS Manager — Pocket-TTS (voice cloning) for IRIS.

Sole engine : Pocket-TTS (~100M int8 quantized, ~100 MB RAM)
  - Zero-shot voice cloning from reference audio (TOMV2.wav)
  - True streaming inference (generate_audio_stream — yields chunk-by-chunk)
  - Text normalizer wired in: strips markdown, expands symbols, removes
    code blocks so TTS never reads out "$", "%", "->", "**bold**" etc.
  - 24 kHz native output

Since the audio-pipeline overhaul (session 278), Pocket-TTS runs in a
SUBPROCESS (`backend/audio/tts_worker.py`) so GIL-bound model loading and
streaming synthesis never starve the main asyncio event loop. `TTSManager` is
now a PROXY: it spawns the worker, sends JSONL commands over stdin/stdout, and
yields numpy arrays from the base64 audio chunks the worker streams back.

The public API is unchanged — every caller (`_speak_response`, `tts_play`,
`conversation_kernel.py`, `chat.py`) works identically.

Setup           : pip install pocket-tts
                  Place TOMV2.wav at IRISVOICE/data/TOMV2.wav
"""

import base64
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TTS_NATIVE_RATE: int = 24_000  # Pocket-TTS native output sample rate
OUTPUT_SAMPLE_RATE: int = TTS_NATIVE_RATE  # pipeline rate
SAMPLE_RATE: int = OUTPUT_SAMPLE_RATE  # legacy alias

# Sentinel pushed onto the line queue when the worker's stdout closes.
# Distinct from ``None`` (read timeout) so callers can tell "the worker is
# slow" apart from "the worker is gone" and restart at most once.
_WORKER_EOF = object()

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
    import re

    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: List[str] = []
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


# ---------------------------------------------------------------------------
# TTSManager — subprocess proxy
# ---------------------------------------------------------------------------


class TTSManager:
    """
    Singleton TTS manager — a PROXY to the Pocket-TTS subprocess worker.

    Engine: Pocket-TTS (sole engine), running in `backend/audio/tts_worker.py`.
      - Zero-shot voice cloning from TOMV2.wav
      - CPU-based, int8 quantized, ~100 MB RAM (lazy load in subprocess)
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

        # Subprocess worker state.
        self._proc: Optional[subprocess.Popen] = None
        self._ready: bool = False
        self._load_error: Optional[str] = None
        self._proc_lock = threading.Lock()  # guards spawn/restart
        self._synthesis_lock = threading.Lock()  # serializes synthesis requests
        self._filler_cache: Dict[str, tuple] = {}  # phrase → (audio_array, sample_rate)

        # Worker stdout lines. One persistent reader thread feeds this queue
        # (see ``_read_stdout``); ``_read_line`` drains it with a timeout.
        # Replaced on every respawn so lines from a dead worker can never be
        # mistaken for the new one's.
        self._lines: "queue.Queue" = queue.Queue()

        TTSManager._initialized = True

        threading.Thread(
            target=self._log_preflight, daemon=True, name="tts-preflight"
        ).start()

    # ------------------------------------------------------------------
    # Subprocess lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def _read_stdout(stream, lines: "queue.Queue") -> None:
        """Pump worker stdout into *lines*, then push the EOF sentinel.

        One long-lived thread per worker. The previous design started a fresh
        thread per ``_read_line`` call and abandoned it on timeout; those
        threads stayed blocked on ``readline()`` forever and, because
        ``TextIOWrapper`` is not thread-safe, a stale reader could consume the
        line the *current* caller was waiting for — making a healthy worker
        look dead.
        """
        try:
            for line in stream:
                lines.put(line)
        except Exception:  # noqa: BLE001 — pipe torn down on restart
            pass
        finally:
            lines.put(_WORKER_EOF)

    @staticmethod
    def _drain_stderr(stream) -> None:
        """Forward worker stderr into the parent log.

        This MUST run. Leaving stderr as an unread ``subprocess.PIPE`` deadlocks
        the worker: Windows anonymous pipes buffer only ~4 KB, Pocket-TTS logs
        ~35 lines per synthesized sentence (~16 KB over a long response), so
        the buffer fills and the worker blocks forever inside its own logging.
        Observed 2026-09-03 (pid 25120): an 853-char synthesis produced no
        audio for 30 s, the parent's read timed out, and it killed a worker
        that was merely blocked on a full stderr pipe. Draining also restores
        worker diagnostics, which were otherwise discarded unread.
        """
        try:
            for line in stream:
                line = line.rstrip()
                if line:
                    logger.info("[tts-worker] %s", line)
        except Exception:  # noqa: BLE001 — pipe torn down on restart
            pass

    def _spawn_worker(self) -> None:
        """Spawn the TTS subprocess worker and wait for it to become ready."""
        with self._proc_lock:
            if self._proc is not None and self._proc.poll() is None:
                return  # already running

            logger.info("[TTSManager] Spawning Pocket-TTS subprocess worker...")
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-u", "-m", "backend.audio.tts_worker"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=str(_PROJECT_DIR),
                    env={
                        **os.environ,
                        "PYTHONPATH": str(_PROJECT_DIR)
                        + os.pathsep
                        + os.environ.get("PYTHONPATH", ""),
                    },
                )
            except Exception as exc:
                self._load_error = str(exc)
                logger.error(f"[TTSManager] Failed to spawn worker: {exc}")
                self._proc = None
                return

            self._proc = proc
            self._lines = queue.Queue()
            threading.Thread(
                target=self._read_stdout,
                args=(proc.stdout, self._lines),
                daemon=True,
                name="tts-stdout",
            ).start()
            threading.Thread(
                target=self._drain_stderr,
                args=(proc.stderr,),
                daemon=True,
                name="tts-stderr",
            ).start()

            self._wait_ready(timeout=120)

    def _wait_ready(self, timeout: float = 120.0) -> None:
        """Poll the worker until it reports ready or the timeout elapses.

        Waits in short slices so the deadline is honoured: a single
        ``Queue.get(timeout)`` could otherwise overrun it by however long the
        worker stays silent (observed 2026-09-03: a respawn took 178 s under a
        nominal 120 s limit while holding ``_proc_lock`` against every other
        TTS caller).
        """
        if self._proc is None:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self._read_line(timeout=min(5.0, deadline - time.monotonic()))
            if status is _WORKER_EOF:
                self._ready = False
                self._load_error = "worker exited during startup"
                logger.error("[TTSManager] Worker exited during startup")
                return
            if status is None:
                continue  # still loading, no line yet
            if status.get("status") == "ready":
                self._ready = True
                self._load_error = None
                logger.info("[TTSManager] Worker ready")
                return
            if status.get("status") == "error":
                self._ready = False
                self._load_error = status.get("error")
                logger.error(f"[TTSManager] Worker load error: {self._load_error}")
                return
        if not self._ready:
            self._load_error = "worker startup timeout"
            logger.error("[TTSManager] Worker startup timed out")

    def _ensure_worker(self) -> bool:
        """Ensure the worker subprocess is running and ready."""
        if self._proc is not None and self._proc.poll() is None and self._ready:
            return True
        self._spawn_worker()
        return self._ready

    def _send(self, payload: dict) -> None:
        """Send a JSONL command to the worker."""
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("TTS worker not running")
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def _read_line(self, timeout: float = 30.0):
        """Read one JSONL response line from the worker with a timeout.

        Returns the decoded message, ``None`` on timeout, or ``_WORKER_EOF``
        when the worker's stdout closed.

        Restarting is deliberately NOT this method's job. It used to restart
        the worker itself and return ``None``, whereupon the caller
        (``synthesize_stream``) restarted a *second* time — killing the worker
        that had just been spawned and paying the ~35 s model load twice
        (observed 2026-09-03: "restarting" logged twice, 7 s apart).
        """
        if self._proc is None:
            return _WORKER_EOF
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            return None
        if line is _WORKER_EOF:
            return _WORKER_EOF
        try:
            return json.loads(line.strip())
        except json.JSONDecodeError:
            return None

    def _restart_worker(self) -> None:
        """Kill and respawn the worker after a crash."""
        logger.warning("[TTSManager] Restarting TTS worker after crash")
        with self._proc_lock:
            old = self._proc
            self._proc = None
            self._ready = False
        # Close the dead worker's pipes before killing it. Skipping this leaks
        # a pipe handle per restart and keeps the old reader thread alive.
        if old is not None:
            for stream in (old.stdin, old.stdout, old.stderr):
                try:
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass
            try:
                old.kill()
            except Exception:  # noqa: BLE001 — already exited
                pass
        self._spawn_worker()

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
            "model_ready": self.is_loaded(),
            "model_path_exists": True,  # installed via pip
            "reference_audio": str(REFERENCE_AUDIO),
            "reference_audio_exists": REFERENCE_AUDIO.exists(),
            "sample_rate": OUTPUT_SAMPLE_RATE,
        }

    def is_loaded(self) -> bool:
        """Return True if the TTS worker is ready."""
        return self._ready

    def _load_pocket_tts(self) -> bool:
        """Ensure the worker subprocess is spawned and ready (proxy)."""
        return self._ensure_worker()

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
            audio = np.concatenate(chunks)
            self._dump_raw_audio(audio, "tts_synthesize")
            return audio
        return None

    def _dump_raw_audio(self, audio: np.ndarray, label: str) -> None:
        """Dump raw float32 audio to a .wav file for diagnostic comparison."""
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

    # Overall budget for one synthesize_stream() call. Measured throughput is
    # ~0.025 s/char (964 chars -> 23.8 s), so this is ~4x headroom — generous
    # enough never to cut a healthy synthesis short, tight enough that a wedged
    # worker cannot hold ``_synthesis_lock`` indefinitely. That lock is
    # process-wide: on 2026-09-03 a single wedged synthesis held it for ~4 min
    # and every other TTS caller on every thread blocked behind it.
    _SYNTHESIS_BASE_TIMEOUT: float = 30.0
    _SYNTHESIS_PER_CHAR_TIMEOUT: float = 0.10

    def _synthesis_deadline(self, text: str) -> float:
        """Monotonic deadline for one call to synthesize_stream(*text*)."""
        return time.monotonic() + (
            self._SYNTHESIS_BASE_TIMEOUT + len(text) * self._SYNTHESIS_PER_CHAR_TIMEOUT
        )

    def synthesize_stream(self, text: str) -> Generator[np.ndarray, None, None]:
        """Stream synthesis — yields float32 arrays at OUTPUT_SAMPLE_RATE Hz.

        Routes through the TTS subprocess worker. The generator signature is
        unchanged from the in-process version, so every caller works identically.
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

        # Ensure the worker is running.
        if not self._ensure_worker():
            _root_log.error(
                f"[TTSManager] Worker not ready — synthesis produced ZERO audio. "
                f"load_error={self._load_error}"
            )
            return

        # Serialize synthesis requests (one at a time, same as single-model).
        with self._synthesis_lock:
            deadline = self._synthesis_deadline(text)
            req_id = int(time.time() * 1000) % 100000
            try:
                self._send({"action": "synthesize", "text": text, "id": req_id})
            except Exception as exc:
                _root_log.error(f"[TTSManager] Failed to send synthesize: {exc}")
                self._restart_worker()
                return

            # Read chunks until done/error.
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _root_log.error(
                        "[TTSManager] Synthesis exceeded its %.0fs budget for %d "
                        "chars — worker is wedged, restarting",
                        self._SYNTHESIS_BASE_TIMEOUT
                        + len(text) * self._SYNTHESIS_PER_CHAR_TIMEOUT,
                        len(text),
                    )
                    self._restart_worker()
                    return
                msg = self._read_line(timeout=min(30.0, remaining))
                if msg is None:
                    _root_log.error(
                        "[TTSManager] Worker produced nothing for 30s "
                        "mid-synthesis — restarting"
                    )
                    self._restart_worker()
                    return
                if msg is _WORKER_EOF:
                    _root_log.error(
                        "[TTSManager] Worker died mid-synthesis — restarting"
                    )
                    self._restart_worker()
                    return
                mtype = msg.get("type")
                if mtype == "chunk":
                    try:
                        data = base64.b64decode(msg.get("data", ""))
                        audio = np.frombuffer(data, dtype=np.float32)
                        if len(audio) > 0:
                            yield audio
                    except Exception as exc:
                        _root_log.warning(
                            f"[TTSManager] Chunk decode failed: {exc}"
                        )
                elif mtype == "done":
                    _root_log.info(
                        f"[TTSManager] Synthesis done: {msg.get('total_samples')} "
                        f"samples in {msg.get('duration_s')}s"
                    )
                    return
                elif mtype == "error":
                    _root_log.error(
                        f"[TTSManager] Worker synthesis error: {msg.get('error')}"
                    )
                    return

    # ------------------------------------------------------------------
    # Filler phrases
    # ------------------------------------------------------------------

    FILLER_PHRASES = [
        "One moment.",
        "Let me check that for you.",
        "Hmm, let me think.",
        "Give me a second.",
        "Looking into it.",
    ]

    def _pre_synthesize_fillers(self) -> None:
        """Pre-synthesize filler phrases to .wav cache (via worker)."""
        if not self._ensure_worker():
            return
        try:
            self._send({"action": "pre_synthesize_fillers"})
            # Read the fillers_ready response.
            while True:
                msg = self._read_line()
                if msg is None or msg is _WORKER_EOF:
                    return
                if msg.get("status") == "fillers_ready":
                    logger.info(
                        f"[TTSManager] Fillers ready: {msg.get('count')}"
                    )
                    return
        except Exception as exc:
            logger.warning(f"[TTSManager] Filler pre-synthesis failed: {exc}")

    def get_filler_audio(self) -> Optional[tuple]:
        """Return a random pre-synthesized filler phrase audio + sample rate."""
        if not self._filler_cache:
            # Load from the .wav cache written by the worker.
            fillers_dir = _PROJECT_DIR / "data" / "fillers"
            if fillers_dir.exists():
                import random as _rand

                wavs = list(fillers_dir.glob("*.wav"))
                if wavs:
                    try:
                        import soundfile as _sf

                        wav = _rand.choice(wavs)
                        data, sr = _sf.read(str(wav), dtype="float32")
                        if data.ndim > 1:
                            data = data.mean(axis=1)
                        self._filler_cache[wav.stem] = (data, sr)
                    except Exception:
                        pass
        if not self._filler_cache:
            return None
        import random as _rand

        phrase = _rand.choice(list(self._filler_cache.keys()))
        return self._filler_cache[phrase]

    # ------------------------------------------------------------------
    # Text normalization (kept in main process — cheap string ops)
    # ------------------------------------------------------------------

    @staticmethod
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


def get_tts_manager() -> TTSManager:
    """Return the process-wide TTSManager singleton."""
    return TTSManager()