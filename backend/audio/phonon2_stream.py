"""Phonon-2 live streaming STT client (CPU) — replaces the Parakeet seam.

Spec: specs/phonon2-d1-model-swap (REQ-1, Wave 1). Owner decision 2026-10-08:
Phonon-2 runs in its LIVE STREAMING mode (WS /v1/audio/stream; interim
hypotheses ~0.35 s, ~2/s updates, final at ~0.7 s silence or a 30 s cap) —
streaming is what replaces Parakeet inside the audio pipeline.

ARCHITECTURE (mirrors the ParakeetTranscriber seam it replaces, voice_command.py):
  * The ENGINE is a separate process: `fermion serve phonon-2` (the
    fermion-research package's own OpenAI-compatible server, installed in
    the project .venv). torch never loads in the backend process.
  * This module manages that process (lazy first-use spawn, health poll,
    sticky failure, idle exit after 20 min) and provides a per-utterance
    streaming client: begin_utterance() -> feed_frame() xN -> finish().
  * The VAD in voice_command remains the TURN authority: frames are fed to
    the stream while they are captured; at end-of-speech the stream is
    closed and its accumulated finals become the transcript. The captured
    _raw_frames buffer stays the whisper-fallback safety net (AC1.2).

Wire protocol (verified live, Wave 0 VERIFY.md V2):
  client -> server : one JSON text frame {"sample_rate":16000,"format":"pcm_s16le"},
                     then binary frames of raw mono s16le PCM,
                     then {"type":"end"} (or a clean close).
  server -> client : {"type":"partial","text":...}
                     {"type":"final","text":...,"segment":N}
                     {"type":"done","text":<full transcript>}
                     {"type":"error","message":...} followed by a close.

Everything here is fail-soft: a fault means "" / False and the caller
(voice_command) falls back to faster-whisper. Nothing in this module may
raise out of a public method — feed_frame() runs on the sounddevice
callback thread (see _capture_frame).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable, Dict, Optional

import numpy as np

logger = logging.getLogger("phonon2_stream")

# Repo root = parents[2] of this file (backend/audio/phonon2_stream.py),
# same convention as parakeet_sherpa.py:42.
_PROJECT_DIR = Path(__file__).resolve().parents[2]

# Retirement record (C2, specs/phonon2-d1-model-swap REQ-11): Parakeet was the
# STT engine until 2026-10-08. The greppable flag lives in voice_command.py;
# this module is its replacement and shares the same seam.
DEFAULT_PORT = int(os.environ.get("IRIS_PHONON2_PORT", "8766"))
# Cold-boot budget: the first run in a new environment COMPILES the runtime
# (measured 39 s idle, >150 s under backend-boot CPU contention — live
# 2026-10-08, when a 150 s budget killed a healthy-but-slow boot). The wait
# runs on a background thread, so a generous budget costs nothing.
_BOOT_TIMEOUT_S = float(os.environ.get("IRIS_PHONON2_BOOT_TIMEOUT", "300"))
_IDLE_EXIT_S = float(os.environ.get("IRIS_PHONON2_IDLE_EXIT_S", "1200"))  # 20 min
_FINISH_TIMEOUT_S = float(os.environ.get("IRIS_PHONON2_FINISH_TIMEOUT", "12"))


def _fermion_exe() -> Optional[Path]:
    """The fermion CLI shipped in the project .venv, or None."""
    exe = _PROJECT_DIR / ".venv" / "Scripts" / "fermion.exe"
    return exe if exe.exists() else None


class _ServerManager:
    """One `fermion serve phonon-2` process for the whole app.

    Thread-safe. Sticky failure: after 2 consecutive spawn/health failures
    the manager refuses further attempts this process (mirrors
    ParakeetTranscriber's sticky build failure) so a broken install cannot
    stall the audio path — whisper keeps serving.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._starting = False
        self._failed = 0
        self._disabled = False
        self._last_activity = time.monotonic()
        self._idle_thread: Optional[threading.Thread] = None

    # -- health ------------------------------------------------------------
    def _healthy(self) -> bool:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{DEFAULT_PORT}/health", timeout=2
            ) as r:
                return json.loads(r.read()).get("status") == "ok"
        except Exception:
            return False

    def server_ready(self) -> bool:
        """Fast non-blocking check: a healthy server is up right now."""
        with self._lock:
            if self._disabled:
                return False
        if self._proc is not None and self._proc.poll() is None:
            self.touch()
            return True
        return self._healthy()

    def spawn_in_background(self) -> None:
        """Kick ensure() on a daemon thread (cold-start path)."""
        if self._starting:
            return
        threading.Thread(
            target=self.ensure, daemon=True, name="iris-phonon2-spawn"
        ).start()

    def _port_in_use_by_stranger(self) -> bool:
        """Someone already serves our port. Reuse only if it is healthy AND
        speaks the phonon endpoints; otherwise refuse (never fight a port)."""
        return self._healthy()

    # -- lifecycle ----------------------------------------------------------
    def ensure(self) -> bool:
        """True when a healthy server is up (spawning and waiting if needed).

        BLOCKS up to _BOOT_TIMEOUT_S on the first spawn (model download +
        runtime compile, measured 64 s cold — Wave 0 VERIFY.md). Callers run
        this on a background thread (warm-up) or accept the miss (first
        utterance falls back to whisper, exactly like Parakeet's cold start).
        """
        with self._lock:
            if self._disabled:
                return False
            if self._proc is not None and self._proc.poll() is None:
                self._last_activity = time.monotonic()
                return True
            if self._starting:
                return False
            if self._port_in_use_by_stranger():
                # A previous boot's server is still alive — adopt it.
                self._last_activity = time.monotonic()
                return True
            exe = _fermion_exe()
            if exe is None:
                logger.warning(
                    "[Phonon2] fermion.exe not found in .venv — STT falls "
                    "back to faster-whisper (install: pip install "
                    "fermion-research)"
                )
                self._mark_failure()
                return False
            self._starting = True

        # Spawn OUTSIDE the lock (Popen + health poll can take minutes).
        try:
            logs = _PROJECT_DIR / "logs"
            logs.mkdir(exist_ok=True)
            log_f = open(logs / "phonon2.log", "ab")
            try:
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                proc = subprocess.Popen(
                    [str(exe), "serve", "phonon-2",
                     "--host", "127.0.0.1", "--port", str(DEFAULT_PORT)],
                    cwd=str(_PROJECT_DIR),
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
            except Exception as exc:
                log_f.close()
                raise
            with self._lock:
                self._proc = proc
                self._last_activity = time.monotonic()
                self._start_idle_watchdog_locked()
            deadline = time.monotonic() + _BOOT_TIMEOUT_S
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    logger.error(
                        "[Phonon2] server exited rc=%s during boot — see "
                        "logs/phonon2.log", proc.returncode
                    )
                    with self._lock:
                        self._proc = None
                        self._starting = False
                        self._mark_failure_locked()
                    return False
                if self._healthy():
                    logger.info(
                        "[Phonon2] server ready on :%s (boot %.1fs)",
                        DEFAULT_PORT, _BOOT_TIMEOUT_S - (deadline - time.monotonic()),
                    )
                    with self._lock:
                        self._starting = False
                        self._failed = 0
                    return True
                time.sleep(1.0)
            logger.error("[Phonon2] server not healthy after %.0fs", _BOOT_TIMEOUT_S)
            # DO NOT terminate: a slow boot (cold compile under load) is
            # PROGRESS, not failure — killing it wastes the work and the
            # next retry starts from zero. Leave the process alive; the next
            # ensure() adopts it the moment it turns healthy
            # (_port_in_use_by_stranger). Only a real crash (poll() above)
            # counts as a failure.
            with self._lock:
                self._starting = False
            return False
        except Exception as exc:
            logger.warning("[Phonon2] server spawn failed: %s", exc)
            with self._lock:
                self._starting = False
                self._mark_failure_locked()
            return False

    def _mark_failure(self) -> None:
        with self._lock:
            self._mark_failure_locked()

    def _mark_failure_locked(self) -> None:
        self._failed += 1
        if self._failed >= 2:
            self._disabled = True
            logger.error(
                "[Phonon2] %d consecutive server failures — STT stays on "
                "faster-whisper for this process (sticky)", self._failed
            )

    def _start_idle_watchdog_locked(self) -> None:
        if self._idle_thread is not None and self._idle_thread.is_alive():
            return

        def _watch():
            while True:
                time.sleep(60.0)
                with self._lock:
                    if self._proc is None:
                        return
                    idle = time.monotonic() - self._last_activity
                    if idle > _IDLE_EXIT_S:
                        proc = self._proc
                        self._proc = None
                        logger.info(
                            "[Phonon2] server idle %.0fs — stopping (restarts "
                            "on next utterance)", idle
                        )
                        try:
                            proc.terminate()
                            proc.wait(timeout=5)
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass
                        return

        t = threading.Thread(target=_watch, daemon=True, name="iris-phonon2-idle")
        t.start()
        self._idle_thread = t

    def touch(self) -> None:
        """Record activity so the idle watchdog does not stop the server."""
        with self._lock:
            self._last_activity = time.monotonic()

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


_manager: Optional[_ServerManager] = None
_manager_lock = threading.Lock()


def get_server_manager() -> _ServerManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = _ServerManager()
        return _manager


def ensure_server() -> bool:
    """Module-level convenience for non-pipeline consumers (media_tools)."""
    return get_server_manager().ensure()


class Phonon2StreamClient:
    """Per-utterance streaming client. One live utterance at a time.

    Usage (voice_command):
        ok = client.begin_utterance(on_partial)   # non-blocking best-effort
        client.feed_frame(frame)                  # every captured frame
        text = client.finish()                    # at VAD end-of-speech
        # text == "" on ANY failure -> caller falls back to whisper.
    """

    def __init__(self) -> None:
        self._conn = None
        self._reader: Optional[threading.Thread] = None
        self._active = False
        self._done = threading.Event()
        self._error: Optional[str] = None
        self._finals: list[str] = []
        self._on_partial: Optional[Callable[[str], None]] = None
        self._first_partial_monotonic: Optional[float] = None
        self._begin_monotonic: Optional[float] = None
        self._finish_monotonic: Optional[float] = None
        self._feed_count = 0
        self._last_error: Optional[str] = None

    # -- state ---------------------------------------------------------------
    @property
    def active(self) -> bool:
        return self._active

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def last_timing(self) -> Dict[str, float]:
        """Timing of the last finished utterance (monotonic seconds)."""
        return {
            "first_partial_s": (
                self._first_partial_monotonic - self._begin_monotonic
                if self._first_partial_monotonic and self._begin_monotonic else None
            ),
            "final_s": (
                self._finish_monotonic - self._begin_monotonic
                if self._finish_monotonic and self._begin_monotonic else None
            ),
        }

    # -- utterance lifecycle ---------------------------------------------------
    def begin_utterance(self, on_partial: Optional[Callable[[str], None]] = None) -> bool:
        """Open the stream for a new utterance. False = unavailable; the
        caller transcribes via the whisper fallback. Never raises.

        NEVER blocks on a cold server: a fast health probe decides, and a
        miss kicks a background spawn (the boot warm-up or a previous
        utterance started it). The first utterance after a cold boot falls
        back to whisper — the same cold-start contract Parakeet had
        (voice_command.py:160, REQ-1 AC1.2/AC1.5)."""
        if self._active:
            self.abort()
        self._reset_utterance()
        try:
            mgr = get_server_manager()
            if not mgr.server_ready():
                mgr.spawn_in_background()
                self._last_error = "server cold (spawning)"
                return False
            from websockets.sync.client import connect

            self._conn = connect(
                f"ws://127.0.0.1:{DEFAULT_PORT}/v1/audio/stream",
                open_timeout=5, close_timeout=5,
            )
            self._conn.send(json.dumps(
                {"sample_rate": 16000, "format": "pcm_s16le"}))
            self._on_partial = on_partial
            self._begin_monotonic = time.monotonic()
            self._active = True
            self._reader = threading.Thread(
                target=self._read_loop, daemon=True, name="iris-phonon2-reader")
            self._reader.start()
            get_server_manager().touch()
            return True
        except Exception as exc:
            self._last_error = f"begin failed: {exc}"
            logger.warning("[Phonon2] stream open failed: %s", exc)
            self._close_quietly()
            return False

    def feed_frame(self, audio_np: np.ndarray) -> None:
        """Forward one float32 mono frame to the stream. Never raises;
        a dropped frame is best-effort (AC1.2: interim is provisional)."""
        if not self._active or self._conn is None:
            return
        try:
            pcm = (np.clip(audio_np, -1.0, 1.0) * 32767.0).astype("<i2")
            self._conn.send(pcm.tobytes())
            self._feed_count += 1
            if self._feed_count % 100 == 0:
                get_server_manager().touch()
        except Exception as exc:
            # Stream died mid-utterance: mark dead, keep the buffer fallback.
            self._last_error = f"feed failed: {exc}"
            logger.warning("[Phonon2] stream dropped mid-utterance: %s", exc)
            self._active = False
            self._close_quietly()

    def finish(self, timeout: float = _FINISH_TIMEOUT_S) -> str:
        """Close the utterance and return its final transcript.

        Returns "" on any failure/timeout — the caller (voice_command)
        then transcribes the captured buffer with faster-whisper (AC1.2).
        Never raises.
        """
        if not self._active:
            # Never opened (server cold) or died mid-stream: nothing to read.
            self._close_quietly()
            return ""
        try:
            self._conn.send(json.dumps({"type": "end"}))
        except Exception as exc:
            self._last_error = f"end failed: {exc}"
            self._close_quietly()
            return ""
        if not self._done.wait(timeout):
            self._last_error = "finish timeout"
            self._close_quietly()
            return ""
        self._finish_monotonic = time.monotonic()
        text = " ".join(t.strip() for t in self._finals if t.strip())
        self._close_quietly()
        get_server_manager().touch()
        return text

    def abort(self) -> None:
        """Hard close without waiting (barge-in / cancel path)."""
        self._close_quietly()

    # -- internals ---------------------------------------------------------------
    def _reset_utterance(self) -> None:
        self._done = threading.Event()
        self._finals = []
        self._error = None
        self._first_partial_monotonic = None
        self._begin_monotonic = None
        self._finish_monotonic = None
        self._feed_count = 0

    def _read_loop(self) -> None:
        """Reader thread: parses server events until done/error/close."""
        try:
            for msg in self._conn:
                try:
                    ev = json.loads(msg)
                except Exception:
                    continue
                kind = ev.get("type")
                if kind == "partial":
                    if self._first_partial_monotonic is None:
                        self._first_partial_monotonic = time.monotonic()
                    cb = self._on_partial
                    if cb is not None:
                        try:
                            cb(str(ev.get("text", "")))
                        except Exception:
                            pass
                elif kind == "final":
                    self._finals.append(str(ev.get("text", "")))
                elif kind == "done":
                    # done.text is the authoritative full transcript
                    # (concatenation of all finals) — replace, never append,
                    # or the text doubles.
                    self._finals = [str(ev.get("text", ""))]
                    self._done.set()
                    return
                elif kind == "error":
                    self._error = str(ev.get("message", ""))
                    logger.warning("[Phonon2] server error: %s", self._error)
                    self._done.set()
                    return
        except Exception as exc:
            if self._active:
                self._last_error = f"stream closed: {exc}"
                logger.warning("[Phonon2] stream closed unexpectedly: %s", exc)
        finally:
            self._done.set()

    def _close_quietly(self) -> None:
        self._active = False
        conn = self._conn
        self._conn = None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
