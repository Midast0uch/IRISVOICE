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


def kill_orphan_tts_workers() -> None:
    """Kill any stray Pocket-TTS worker processes left by a previous crash.

    Session-331: the TTS worker is a ~2 GB-commit python subprocess spawned as
    a child of the backend. Its idle-unload reaper lives in the PARENT, so if
    the backend dies mid-synthesis the worker is orphaned and never reaped — it
    just sits there holding multi-GB until reboot. This mirrors
    ``local_model_manager.kill_orphan_servers`` (called at the same startup
    point) so a crashed run can never leave a zombie behind.

    Matches on the module name ``backend.audio.tts_worker`` in the command line,
    NOT the bare word "python" — killing every python process would take out the
    backend itself and every MCP server. Windows uses WMIC/taskkill via
    psutil (already a dependency); non-Windows uses pkill -f. Best-effort:
    never raises, never blocks boot.
    """
    import platform as _pf

    _marker = "backend.audio.tts_worker"
    _self = os.getpid()
    try:
        if _pf.system().lower() == "windows":
            import psutil

            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    if proc.pid == _self:
                        continue
                    cmd = " ".join(proc.info.get("cmdline") or [])
                    if _marker in cmd and "python" in (proc.info.get("name") or "").lower():
                        logger.warning(
                            "[TTSManager] Killing orphaned TTS worker pid=%s",
                            proc.pid,
                        )
                        proc.kill()
                except Exception:  # noqa: BLE001 — a vanished process is fine
                    pass
        else:
            subprocess.run(
                ["pkill", "-f", _marker], capture_output=True, timeout=10
            )
    except Exception as exc:  # noqa: BLE001 — cleanup must never block boot
        logger.debug("[TTSManager] orphan TTS worker cleanup skipped: %s", exc)

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
      - CPU-based, int8 quantized. Measured worker commit ~2.3 GB
        (torch CPU runtime + weights + retained encode arenas; resident
        decays toward ~0.3 GB over idle hours) — see REQ-28. The old
        "~100 MB" figure described the quantized weights alone, not the
        process, and is kept here only as a warning against repeating it.
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
    # One reaper per process: test doubles reset the singleton (fresh
    # _proc/_ready per test), but a second 30 s-sleep daemon per reset is
    # pure thread litter — the loop only ever reaps the CURRENT singleton's
    # worker via direct calls in tests, so one thread is enough forever.
    _reaper_started: bool = False

    # Total time a worker may spend starting up, measured from spawn.
    #
    # NOT a per-waiter slice. A Pocket-TTS cold start measured 238 s on this
    # box (2026-09-05 pid 8180, all CPU): ~151 s importing torch/pocket_tts
    # while the Parakeet worker loaded alongside it, 17.3 s model load,
    # 51.0 s audio-prompt encode, 68.5 s voice state. The old fixed 120 s
    # wait expired mid-load, and every later caller only re-polled for 30 s
    # at a time — so the manager declared "worker startup timeout" while the
    # worker was still healthy and every synthesis returned ZERO audio until
    # a request happened to arrive after the load finished (26 min later).
    _WORKER_STARTUP_TIMEOUT: float = 300.0

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
        # Pre-synthesis hold store (REQ-10 AC10.6/AC10.7, T14): key → audio.
        self._held: Dict[str, "np.ndarray"] = {}
        self._held_turn_counts: Dict[str, int] = {}
        self._dead_hold_keys: set = set()  # free raced ahead of completion
        # Narration toggle (REQ-10 AC10.14, T15): when False, presynthesis
        # refuses and completions discard (in-flight aborted); free_all_held
        # sweeps stored buffers. Guarded by _synthesis_lock discipline.
        self._holds_accepted: bool = True

        # Worker stdout lines. One persistent reader thread feeds this queue
        # (see ``_read_stdout``); ``_read_line`` drains it with a timeout.
        # Replaced on every respawn so lines from a dead worker can never be
        # mistaken for the new one's.
        self._lines: "queue.Queue" = queue.Queue()

        # monotonic() timestamp of the current worker's spawn. The startup
        # budget is measured from HERE, not per waiter — see
        # ``_remaining_startup_budget``.
        self._spawn_started_at: Optional[float] = None

        # REQ-28 lifecycle: lazy at boot, pre-warm on connect, unload when
        # quiet. ``_last_activity`` is stamped when the worker becomes ready
        # and on every terminal synthesis event; the reaper unloads the
        # worker once it has been quiet longer than ``_idle_timeout_s``.
        # ``_connect_prewarm_done`` keeps the connect hook once-per-process
        # (on-demand spawn in the synthesize path covers everything after).
        self._last_activity: Optional[float] = None
        self._connect_prewarm_done: bool = False
        # SESSION 366 - REVERTED (owner: system memory climbed to ~9 GB and a
        # python process had to be end-tasked). Setting the idle unload to 0
        # (keep the worker resident forever) EXPOSED unbounded growth: the worker
        # does not return to its idle baseline after a synthesis, so with no
        # unload that growth ACCUMULATED across utterances instead of being
        # reclaimed. The unload was MASKING a growth problem - turning it off was
        # the wrong fix. Restored to 600 s.
        # The owner's actual goal is: fast synthesis AND memory released when
        # idle, with no spike. That needs the per-synthesis GROWTH fixed, not the
        # unload removed - tracked as a separate defect below.
        #
        # 2026-09-30 (owner: "TTS should be ready with the backend"): idle unload
        # is OFF by default again. What made that unsafe in Session 366 is now
        # bounded separately: the growth-budget recycle below (500 MB over the
        # post-load baseline) unloads a worker that grows, and the reaper then
        # reloads it at once (_load_until_ready), so memory stays capped AND the
        # worker stays warm. With the unload on, every quiet 10 min cost a full
        # cold load on the next speech: 2-5 min on this machine's hard disk
        # (c11 2026-09-29: the load landed in a turn and starved its pytest).
        # IRIS_TTS_IDLE_TIMEOUT_S > 0 restores the idle unload.
        try:
            self._idle_timeout_s: float = float(
                os.environ.get("IRIS_TTS_IDLE_TIMEOUT_S", "0") or 0
            )
        except ValueError:
            self._idle_timeout_s = 0.0
        self._last_unload_reason: Optional[str] = None

        # SESSION 366: the worker's COMMITTED memory grows per synthesis and
        # never returns to its post-load baseline (measured: 1304MB -> 2001MB
        # across ONE synthesis, then it stayed). `_compact_heap()` in the worker
        # already runs gc.collect() + ucrt `_heapmin` + a working-set trim, so the
        # retention is NOT the CRT heap - it is the ML runtime's own arena (the
        # worker's own note names MKL's allocator). Chasing that allocator is
        # fragile, so the growth is BOUNDED deterministically instead: when the
        # worker has grown past this budget over its own baseline, it is unloaded
        # (the existing graceful shutdown path) and the next request respawns it.
        # That keeps synthesis fast while it is warm AND caps the footprint.
        # 0 disables the check. Growth is measured from the baseline captured
        # when the worker first becomes ready, so a large-but-constant footprint
        # does not trigger a recycle loop.
        try:
            self._max_growth_mb: float = float(
                os.environ.get("IRIS_TTS_MAX_GROWTH_MB", "500") or 500
            )
        except ValueError:
            self._max_growth_mb = 500.0
        self._baseline_commit_mb: float = 0.0

        TTSManager._initialized = True

        threading.Thread(
            target=self._log_preflight, daemon=True, name="tts-preflight"
        ).start()
        if not TTSManager._reaper_started:
            TTSManager._reaper_started = True
            threading.Thread(
                target=self._reaper_loop, daemon=True, name="tts-idle-reaper"
            ).start()
        # Lazy at boot (REQ-28): no worker is spawned here, so a fresh
        # backend idles without the ~2.3 GB commit. Warmth comes from two
        # cheaper points: pre-warm on frontend connect (``prewarm()``,
        # called from the WS endpoint — the user is present but not yet
        # speaking) and on-demand spawn inside ``synthesize_stream``.
        # Either path still pays one cold load (~20 s measured); a 300 s
        # startup budget covers pathological contention (2026-09-05: 238 s
        # with Parakeet loading alongside). Set IRIS_TTS_EARLY_SPAWN=1 to
        # restore the old boot-time spawn.
        #
        # Skipped under pytest (test suites construct TTSManager() for unit
        # checks — singleton/config — and must not each boot a real model
        # subprocess), matching the IRIS_* env convention used elsewhere.
        _early_spawn = (
            self.config.get("tts_enabled", True)
            and "pytest" not in sys.modules
            and "PYTEST_CURRENT_TEST" not in os.environ
            and os.environ.get("IRIS_TTS_EARLY_SPAWN", "0") == "1"
        )
        if _early_spawn:
            threading.Thread(
                target=self._spawn_worker, daemon=True, name="tts-early-spawn"
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
                if self._ready:
                    return  # already running and ready
                # Alive but never became ready (startup timed out on another
                # thread while holding no lock — the waiter gave up but the
                # worker may still be loading). Wait out the REST of this
                # worker's startup budget instead of abandoning it.
                #
                # It used to wait a fresh 30 s slice here. The cold start is
                # ~238 s, so slice after slice expired, each one logging
                # "Worker startup timed out" and leaving _ready False, and
                # every later synthesize failed with ZERO audio forever
                # (2026-09-05: TTS silent for 26 min because the only thing
                # that ever re-polled was the next request, ~26 min later).
                remaining = self._remaining_startup_budget()
                if remaining <= 0:
                    return  # budget genuinely exhausted — nothing more to wait for
                logger.info(
                    f"[TTSManager] Worker alive but not ready — waiting "
                    f"{remaining:.0f}s more for late ready"
                )
                self._wait_ready(timeout=remaining)
                return

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
                        # REQ-28 AC28.2 (T41-fix): MKL's fast memory manager
                        # retains ~10-25MB of per-synthesis scratch forever
                        # (measured linear over 30, no plateau; threads, python
                        # objects and shared voice state all flat). Disabling
                        # routes MKL through plain malloc so freed blocks are
                        # reused — growth flat over repeats at the same RTF
                        # (~1.9x). Operator override respected.
                        "MKL_DISABLE_FAST_MM": os.environ.get(
                            "MKL_DISABLE_FAST_MM", "1"
                        ),
                    },
                )
            except Exception as exc:
                self._load_error = str(exc)
                logger.error(f"[TTSManager] Failed to spawn worker: {exc}")
                self._proc = None
                return

            self._proc = proc
            self._spawn_started_at = time.monotonic()
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

            self._wait_ready(timeout=self._WORKER_STARTUP_TIMEOUT)

    def _remaining_startup_budget(self) -> float:
        """Seconds left in the CURRENT worker's startup budget, never negative.

        Measured from spawn, not from whichever caller happens to be waiting:
        N callers polling a still-loading worker must together see the SAME
        budget as one caller, otherwise each caller's private timeout silently
        shortens the worker's remaining chance to finish loading (that is what
        the old per-caller 30 s slices did).
        """
        if self._spawn_started_at is None:
            return 0.0
        elapsed = time.monotonic() - self._spawn_started_at
        return max(0.0, self._WORKER_STARTUP_TIMEOUT - elapsed)

    def _wait_ready(self, timeout: float = 120.0, report_timeout: bool = True) -> None:
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
            # The worker sends ONE "ready" line, and several callers may wait
            # on it at once (the spawner under _proc_lock, adopters without
            # it). Whoever reads it sets _ready; every other waiter must stop
            # on that flag, not on a line it will never see. Before this, the
            # others waited their full budget (up to 300 s) — the spawner
            # holding _proc_lock the whole time, silencing every TTS caller
            # (test_concurrent_first_speak_spawns_exactly_one_worker hung).
            # Short slices bound how late a waiter notices.
            if self._ready:
                return
            status = self._read_line(timeout=min(0.5, deadline - time.monotonic()))
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
                self._note_activity()
                # SESSION 366: capture the memory baseline HERE, the moment the
                # worker is READY with its model loaded. Capturing it on the first
                # REAPER read was too late: the reaper's first sweep after a spawn
                # can land after the worker has already grown, so the baseline
                # absorbed the growth and the budget could never see it (measured:
                # worker at 2083MB, baseline ~2000MB, growth ~0, no recycle ever
                # fired). Read the child lock-free here - `_wait_ready` already
                # runs inside `_spawn_worker`'s `_proc_lock`, and that lock is not
                # reentrant, so `_worker_commit_mb()` must NOT be called from here.
                try:
                    import psutil

                    _p = self._proc
                    self._baseline_commit_mb = (
                        psutil.Process(_p.pid).memory_info().private
                        / (1024.0 * 1024.0)
                        if _p is not None else 0.0
                    )
                except Exception:  # noqa: BLE001 - a baseline is best-effort
                    self._baseline_commit_mb = 0.0
                logger.info("[TTSManager] Worker ready")
                return
            if status.get("status") == "error":
                self._ready = False
                self._load_error = status.get("error")
                logger.error(f"[TTSManager] Worker load error: {self._load_error}")
                return
        if not self._ready and report_timeout:
            self._load_error = "worker startup timeout"
            logger.error("[TTSManager] Worker startup timed out")

    def _ensure_worker(self) -> bool:
        """Ensure the worker subprocess is running and ready."""
        if self._proc is not None and self._proc.poll() is None and self._ready:
            return True
        # session-319 fix: a worker that finished loading AFTER its startup
        # deadline must be ADOPTED, never abandoned.
        #
        # `_ready` is set in exactly one place — inside `_wait_ready`, when it
        # reads a "ready" line. So when the startup deadline fires first, the
        # worker's late "ready" line simply sits unread in `self._lines`. The
        # old code then called `_spawn_worker()` here, which REPLACED
        # `self._lines` and DISCARDED that line, spawning a fresh ~238 s cold
        # worker — which timed out in turn, and so on. Every narration in the
        # turn then came back silent (measured: worker ready 10:14:59, startup
        # deadline fired 10:13:58, ZERO audio across 12 narrations).
        #
        # Give the EXISTING worker the chance to report readiness before paying
        # for another cold spawn. The wait is short and bounded: the ready line,
        # when it exists, is already queued, so this returns immediately.
        if self._proc is not None and self._proc.poll() is None:
            self._wait_ready(timeout=self._remaining_startup_budget() or 5.0)
            if self._ready:
                logger.info(
                    "[TTSManager] Worker adopted (ready after startup deadline)"
                )
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

    def _note_activity(self) -> None:
        """Stamp the last-use clock (REQ-28: the idle reaper's input)."""
        self._last_activity = time.monotonic()

    def prewarm(self) -> None:
        """Start worker load without blocking the caller (connect hook).

        Once per process; on-demand spawn in the synthesize path covers
        everything after. Never raises — warmth is an optimization, and an
        exception here must never break a client connect.
        """
        try:
            if self._connect_prewarm_done:
                return
            self._connect_prewarm_done = True
            threading.Thread(
                target=self._load_until_ready,
                daemon=True,
                name="tts-boot-load",
            ).start()
        except Exception:  # noqa: BLE001 — prewarm never breaks the caller
            pass

    def _load_until_ready(self) -> None:
        """Load the worker and keep waiting until it reports ready (background).

        The startup deadline bounds a CALLER that waits for speech; this runs on
        its own thread, so it outlasts the deadline and adopts a late "ready"
        (a cold load on this machine's hard disk took 5 min 6 s, past the 300 s
        deadline, 2026-09-29). Ends when ready or when the worker is gone.
        """
        try:
            self._load_pocket_tts()
            while (
                not self._ready
                and self._proc is not None
                and self._proc.poll() is None
            ):
                # Past the deadline the worker is slow, not failed: keep reading
                # for its "ready" line without re-reporting a timeout error.
                self._wait_ready(timeout=30.0, report_timeout=False)
                if not self._ready:
                    logger.info(
                        "[TTSManager] boot load still loading (%.0fs since spawn)",
                        time.monotonic() - (self._spawn_started_at or time.monotonic()),
                    )
            logger.info(
                "[TTSManager] boot load finished: ready=%s error=%s",
                self._ready, self._load_error,
            )
        except Exception as exc:  # noqa: BLE001 — a background load never raises
            logger.warning("[TTSManager] boot load failed: %s", exc)

    def readiness(self) -> Dict[str, Any]:
        """State for the /health and /ready probes.

        loading: a worker is starting and has not reported ready — the backend
        is not ready either (owner 2026-09-30: no turn may start during the
        load). error: no worker and a load error — reported, never waited on.
        """
        if not self.config.get("tts_enabled", True):
            return {"status": "disabled"}
        if self._ready and self._proc is not None and self._proc.poll() is None:
            return {"status": "ready"}
        if self._proc is not None and self._proc.poll() is None:
            return {"status": "loading"}
        if self._load_error:
            return {"status": "error", "error": str(self._load_error)}
        if self._connect_prewarm_done:
            return {"status": "loading"}  # the boot thread has not spawned yet
        return {"status": "not_started"}

    def _worker_commit_mb(self) -> float:
        """The live worker's COMMITTED memory in MB, or 0.0 when unknown.

        WorkingSet is deliberately NOT used: Windows pages an idle worker out,
        so the same process reports ~10 MB WS while holding ~2 GB commit
        (measured session 366) - a WS-based budget would never fire.
        """
        try:
            import psutil

            with self._proc_lock:
                proc = self._proc
                if proc is None or proc.poll() is not None:
                    return 0.0
                pid = proc.pid
            return psutil.Process(pid).memory_info().private / (1024.0 * 1024.0)
        except Exception:  # noqa: BLE001 - a budget read never breaks a turn
            return 0.0

    def _grown_too_big(self) -> bool:
        """Session 366: has the worker's commit grown past its growth budget?

        The baseline is captured on the first read, so a large-but-stable
        footprint (the loaded model) never triggers a recycle - only GROWTH does.
        """
        if self._max_growth_mb <= 0:
            return False
        mb = self._worker_commit_mb()
        if mb <= 0.0:
            return False
        if self._baseline_commit_mb <= 0.0:
            self._baseline_commit_mb = mb
            return False
        return (mb - self._baseline_commit_mb) >= self._max_growth_mb

    def _should_unload(self, now: float) -> bool:
        """Pure decision: is the live worker quiet past its timeout?"""
        if self._idle_timeout_s <= 0:
            return False  # escape hatch: no idle unload
        if not self._ready or self._proc is None or self._proc.poll() is not None:
            return False  # nothing live to unload (startup/crash paths own it)
        if self._last_activity is None:
            return False
        return (now - self._last_activity) >= self._idle_timeout_s

    def _reap_if_idle(self) -> bool:
        """Gracefully shut down a quiet-past-timeout worker. Returns True
        when a worker was unloaded. Best-effort: never raises, never reaps a
        worker with a synthesis in flight (non-blocking lock check)."""
        now = time.monotonic()
        _idle = self._should_unload(now)
        _fat = self._grown_too_big()
        # Read the commit ONCE, BEFORE taking `_proc_lock` below: `_worker_commit_mb`
        # takes the same lock, and threading.Lock is NOT reentrant, so calling it
        # inside the `with` block would DEADLOCK the reaper thread.
        _commit_mb = self._worker_commit_mb() if _fat else 0.0
        if not _idle and not _fat:
            return False
        if not self._synthesis_lock.acquire(blocking=False):
            return False  # mid-synthesis — skip this cycle
        try:
            with self._proc_lock:
                proc = self._proc
                if proc is None or proc.poll() is not None or not self._ready:
                    return False
                _why = (
                    "idle %.0fs > %.0fs" % (
                        now - (self._last_activity or now), self._idle_timeout_s
                    )
                    if _idle else
                    "commit %.0fMB, baseline %.0fMB, growth budget %.0fMB" % (
                        _commit_mb, self._baseline_commit_mb,
                        self._max_growth_mb,
                    )
                )
                logger.info("[TTSManager] unloading TTS worker (%s)", _why)
                try:
                    self._send({"action": "shutdown"})
                except Exception:  # noqa: BLE001 — pipes may already be gone
                    pass
                try:
                    proc.wait(timeout=10)
                except Exception:  # noqa: BLE001 — graceful failed; force it
                    try:
                        proc.kill()
                    except Exception:
                        pass
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    try:
                        stream.close()
                    except Exception:  # noqa: BLE001
                        pass
                self._proc = None
                self._ready = False
                self._baseline_commit_mb = 0.0  # new worker -> new baseline
                self._last_unload_reason = "idle" if _idle else "growth"
                return True
        finally:
            self._synthesis_lock.release()

    def _reaper_loop(self) -> None:
        """Daemon: sweep for a quiet worker every 30 s (REQ-28)."""
        while True:
            time.sleep(30)
            try:
                if self._reap_if_idle() and self._last_unload_reason == "growth":
                    # A growth recycle caps memory; reload at once so the next
                    # speech never pays a cold load (owner 2026-09-30).
                    threading.Thread(
                        target=self._load_until_ready, daemon=True,
                        name="tts-recycle-load",
                    ).start()
            except Exception as exc:  # noqa: BLE001 — reaper never dies loudly
                logger.debug("[TTSManager] Idle sweep skipped: %s", exc)

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

    # Overall budget for one synthesize_stream() call.
    #
    # SESSION 366, CORRECTED: a first attempt raised this 30 -> 60 to tolerate a
    # slow COLD prompt, and that was WRONG. The very next run showed the real
    # shape: `No chunk for 30s but worker is alive` then `Synthesis exceeded its
    # 63s budget for 26 chars - worker is wedged, restarting` with NO "Prompting
    # text" line at all - a GENUINE hang, not a cold model. After the restart the
    # worker was healthy: "Prompting text took 192 ms", "Synthesis done: 39360
    # samples in 0.82s". So a longer budget only makes a REAL wedge more
    # expensive (63 s instead of 31 s) and does not fix it. 30 s is restored.
    #
    # The COLD-start problem is handled where it belongs: the idle UNLOAD is now
    # OFF by default (see _idle_timeout_s), so the model loads once and stays -
    # the cold prompt no longer recurs. The WEDGE itself is a separate, still-
    # open bug (the worker hangs with no output) and 30 s bounds it.
    _SYNTHESIS_BASE_TIMEOUT: float = 30.0
    _SYNTHESIS_PER_CHAR_TIMEOUT: float = 0.10

    # Long-text guard (measured 2026-09-07): one synthesis retains
    # ~0.15–0.19 MB per char in native arenas (+477 MB for 2500 chars,
    # +1082 MB for 7500). Past ~10k chars a single request can plausibly
    # exhaust commit and get OOM-killed — presenting as "died on long
    # text" (the 2026-09-03 deaths were the stderr-pipe incident, fixed
    # since, but the scaling risk is real and measured). Requests longer
    # than this are split at sentence boundaries into sequential worker
    # requests: identical audio, bounded growth per request, compact runs
    # between them.
    _MAX_SINGLE_SYNTH_CHARS: int = 2000

    def _synthesis_deadline(self, text: str) -> float:
        """Monotonic deadline for one call to synthesize_stream(*text*)."""
        return time.monotonic() + (
            self._SYNTHESIS_BASE_TIMEOUT + len(text) * self._SYNTHESIS_PER_CHAR_TIMEOUT
        )

    @staticmethod
    def _split_synthesis_text(text: str, max_chars: int = 2000) -> list:
        """Split a long request at sentence boundaries into bounded pieces.

        Hard-splits pathological no-punctuation runs so no piece can exceed
        the cap (see _MAX_SINGLE_SYNTH_CHARS). Pure string ops, never raises
        on strange input — worst case returns [text].
        """
        import re

        try:
            sentences = [
                s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s
            ]
            slices: list = []
            for s in sentences:
                while len(s) > max_chars:
                    slices.append(s[:max_chars])
                    s = s[max_chars:]
                if s:
                    slices.append(s)
            pieces: list = []
            buf = ""
            for s in slices:
                if len(buf) + len(s) + 1 <= max_chars:
                    buf = (buf + " " + s).strip()
                else:
                    if buf:
                        pieces.append(buf)
                    buf = s
            if buf:
                pieces.append(buf)
            return pieces or [text]
        except Exception:  # noqa: BLE001 — splitting never breaks synthesis
            return [text]

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
            req_base = int(time.time() * 1000) % 100000
            # Sequential bounded pieces (long-text guard): identical audio,
            # one worker request each, so per-request arena growth stays
            # capped and the post-synthesis compact runs between pieces.
            pieces = self._split_synthesis_text(
                text, max_chars=self._MAX_SINGLE_SYNTH_CHARS
            )
            for piece_idx, piece in enumerate(pieces):
                req_id = req_base + piece_idx
                try:
                    self._send({"action": "synthesize", "text": piece, "id": req_id})
                except Exception as exc:
                    _root_log.error(f"[TTSManager] Failed to send synthesize: {exc}")
                    self._note_activity()
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
                        self._note_activity()
                        self._restart_worker()
                        return
                    msg = self._read_line(timeout=min(30.0, remaining))
                    if msg is None:
                        # A read timeout is NOT proof the worker is wedged. A
                        # cold model or a long prompt can delay the FIRST chunk
                        # past 30s while the worker is healthy and generating
                        # (measured 2026-09-13: the worker logged "Prompting
                        # text took 15636 ms" then generation steps, yet the
                        # parent killed it at 30s and paid a fresh 438MB model
                        # load — the restart loop that spiked CPU/RAM). Only
                        # restart when the process is actually gone; otherwise
                        # keep waiting inside the synthesis budget.
                        if self._proc is not None and self._proc.poll() is None:
                            _root_log.warning(
                                "[TTSManager] No chunk for 30s but worker is "
                                "alive — continuing to wait (%.0fs budget left)",
                                remaining,
                            )
                            continue
                        _root_log.error(
                            "[TTSManager] Worker produced nothing for 30s "
                            "mid-synthesis — restarting"
                        )
                        self._note_activity()
                        self._restart_worker()
                        return
                    if msg is _WORKER_EOF:
                        _root_log.error(
                            "[TTSManager] Worker died mid-synthesis — restarting"
                        )
                        self._note_activity()
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
                        self._note_activity()
                        break  # next piece (long-text guard), if any
                    elif mtype == "error":
                        _root_log.error(
                            f"[TTSManager] Worker synthesis error: {msg.get('error')}"
                        )
                        self._note_activity()
                        return
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
    # Pre-synthesis hold (REQ-10 AC10.6/AC10.7, T14)
    # ------------------------------------------------------------------
    # Hybrid pre-synthesis: planned beats 2..N are synthesized at authoring
    # time (latency hides in segment waits) and held here; playback consumes
    # via take_held(), every other exit frees via free_held()/free_turn_held().
    # Lowest-priority invariant: hold jobs NEVER queue ahead of lane
    # synthesis — presynthesize_hold takes _synthesis_lock non-blocking and
    # requires a ready worker, so a hold either runs in a true idle window
    # or refuses (fallback to on-admission synthesis). Residual bound: one
    # already-running sentence-capped hold job ahead of a reply, worst case.

    MAX_HOLD_CHARS = 300  # sentence-capped buffers only; longer refused
    MAX_HELD_PER_TURN = 6  # per-task held-buffer cap
    DEAD_HOLD_KEYS_MAX = 256  # race-set cap (free arriving before completion)

    def _hold_key(self, turn_id: str) -> str:
        n = self._held_turn_counts.get(turn_id, 0)
        self._held_turn_counts[turn_id] = n + 1
        return f"hold:{turn_id}:{n}"

    def presynthesize_hold(self, turn_id: str, text: str) -> Optional[str]:
        """Synthesize a beat now, hold the buffer. Returns key or None.

        Returns None (caller falls back to on-admission synthesis) when: the
        text is empty/over the sentence cap, the per-turn cap is reached, the
        worker is not ready (never spawns here), the synthesis lock is busy
        (lane work first, always), or the worker errors. Never raises.
        """
        import logging as _logging

        _root_log = _logging.getLogger()
        try:
            cleaned = (text or "").strip()
            if not cleaned:
                return None
            if len(cleaned) > self.MAX_HOLD_CHARS:
                _root_log.info(
                    "[TTSManager] hold refused (over sentence cap): %d chars",
                    len(cleaned),
                )
                return None
            if self._held_turn_counts.get(turn_id or "unknown", 0) >= self.MAX_HELD_PER_TURN:
                _root_log.info("[TTSManager] hold refused (per-turn cap)")
                return None
            if not (
                self._proc is not None
                and self._proc.poll() is None
                and self._ready
            ):
                return None  # never spawn for background work
            if not self._holds_accepted:
                return None  # narration toggled off (AC10.14)
            if not self._synthesis_lock.acquire(blocking=False):
                return None  # lane synthesis first, always
            try:
                req_id = int(time.time() * 1000) % 100000
                self._send(
                    {"action": "synthesize_and_hold", "text": cleaned, "id": req_id}
                )
                deadline = self._synthesis_deadline(cleaned)
                key: Optional[str] = None
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        _root_log.warning("[TTSManager] hold timed out, dropping")
                        return None
                    msg = self._read_line(timeout=min(30.0, remaining))
                    if msg is None or msg is _WORKER_EOF:
                        return None
                    if msg.get("type") == "held" and msg.get("id") == req_id:
                        data = base64.b64decode(msg.get("data", ""))
                        audio = np.frombuffer(data, dtype=np.float32)
                        key = self._store_hold(turn_id or "unknown", cleaned, audio)
                        return key
                    if msg.get("type") == "error":
                        _root_log.info(
                            "[TTSManager] hold failed: %s", msg.get("error")
                        )
                        return None
                    # No other message type is legal here; ignore and continue.
            finally:
                self._synthesis_lock.release()
        except Exception as exc:  # noqa: BLE001 — presynth never breaks turns
            _root_log.debug("[TTSManager] hold skipped: %s", exc)
            return None

    def _store_hold(self, turn_id: str, text: str, audio: "np.ndarray") -> str:
        """Store a completed hold buffer; discards races with free (waste)."""
        import logging as _logging

        key = self._hold_key(turn_id)
        if key in self._dead_hold_keys or not self._holds_accepted:
            # Free (or toggle-off) arrived while synthesis ran: discard +
            # count waste (AC10.7). Toggle-off also clears the dead set below.
            self._dead_hold_keys.discard(key)
            _logging.getLogger().info(
                "[TTSManager] hold waste (freed mid-synthesis): %s", key
            )
            return key
        self._held[key] = audio
        _logging.getLogger().info(
            "[TTSManager] hold stored: %s (%d samples)", key, len(audio)
        )
        return key

    def take_held(self, key: Optional[str]) -> Optional["np.ndarray"]:
        """Consume a held buffer for playback (played-from-hold, AC10.6)."""
        import logging as _logging

        if not key:
            return None
        audio = self._held.pop(key, None)
        if audio is None:
            return None
        _logging.getLogger().info("[TTSManager] hold hit: %s", key)
        return audio

    def free_held(self, key: Optional[str]) -> bool:
        """Free a held buffer on a non-play exit. True = waste counted."""
        if not key:
            return False
        if key in self._held:
            self._held.pop(key, None)
            import logging as _logging

            _logging.getLogger().info("[TTSManager] hold waste (freed): %s", key)
            return True
        self._dead_hold_keys.add(key)
        while len(self._dead_hold_keys) > self.DEAD_HOLD_KEYS_MAX:
            self._dead_hold_keys.pop()
        return False

    def set_holds_accepted(self, accepted: bool) -> None:
        """Toggle-off/on for pre-synthesis (REQ-10 AC10.14, T15).

        Off refuses new holds and discards in-flight completions; callers
        sweep stored buffers via free_all_held(). Session scope matches the
        narration toggle (single-user desktop: process-wide).
        """
        self._holds_accepted = bool(accepted)

    def free_all_held(self) -> int:
        """Free every held buffer (narration toggle-off, T15)."""
        import logging as _logging

        n = len(self._held)
        self._held.clear()
        self._held_turn_counts.clear()
        self._dead_hold_keys.clear()
        if n:
            _logging.getLogger().info(
                "[TTSManager] hold waste (toggle off): %d buffers", n
            )
        return n

    def free_turn_held(self, turn_id: str) -> int:
        """Free every held buffer for a turn (barge/turn-end/toggle/session)."""
        if not turn_id:
            return 0
        prefix = f"hold:{turn_id}:"
        doomed = [k for k in self._held if k.startswith(prefix)]
        for key in doomed:
            self._held.pop(key, None)
        for key in [k for k in self._dead_hold_keys if k.startswith(prefix)]:
            self._dead_hold_keys.discard(key)
        self._held_turn_counts.pop(turn_id, None)
        if doomed:
            import logging as _logging

            _logging.getLogger().info(
                "[TTSManager] hold waste (turn end): %d buffers", len(doomed)
            )
        return len(doomed)

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