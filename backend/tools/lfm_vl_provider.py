"""
LFM2.5-VL Vision Provider
HTTP client wrapping llama-server on the configured vision port (default 18181).
Provides synchronous screen analysis, UI element detection, OCR, and action suggestion.

Auto-start: If llama-server is not running on the vision port, the provider attempts to
spawn it using the widest vision-capable GGUF model that fits current free VRAM,
discovered from the scanned models directory (REQ-10) — never a hardcoded model id.
"""
import base64
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Port — IRIS-owned vision port, env-var overridable.  Must match what the
# iris_gateway's _handle_set_vision_enabled uses.
# ---------------------------------------------------------------------------
from backend.iris_config import load_config as _load_vl_config

_VISION_PORT: int = _load_vl_config().ports.vision_port

# VRAM (GB) the vision server must leave free for a LATER local-model load.
# The brain/tool roles are usually cloud APIs, but a user may load a local
# GGUF at any time — vision must never consume the whole card (2026-08-12:
# vision was upgraded to LFM2.5-VL-3B; on an 8GB RTX 3070 with ~4.8GB used
# by the desktop, the 3B (~2.6GB with mmproj+KV) fits while reserving this
# margin; the local-model loader budgets the SAME free-VRAM figure).
_VISION_VRAM_RESERVE_GB = 1.0

# REQ-6 (T4): explicit ctx/batch size passed to the vision llama-server so
# nothing is left for `--fit` (llama.cpp b9591's auto-fit device-memory
# probe, on by default) to guess at. Mirrors
# local_model_manager._build_server_cmd's "leave nothing meaningful unset"
# rationale (commit e9d2fc89) — that probe was measured stalling 12-36
# minutes on MoE models. The vision server spawn is a separate code path
# that never got the fix until now.
_VISION_CTX_SIZE = 4096
_VISION_BATCH_SIZE = 2048

# PID of the llama-server subprocess IRIS spawned (None = we didn't start one).
# Tracked so disable() can stop only servers we own — a user-run llama-server on
# the same port is left alone.
_VISION_SERVER_PID: Optional[int] = None

# Reusable probe buffer for _probe_av_latency. Module-level and small:
# that function reads ONE chunk per file (a full read was measured harmful —
# see its docstring), so this never grows the backend's footprint. The spawn
# path is single-flighted, so there is exactly one user at a time.
_AV_PROBE_BUF = bytearray(8 << 20)  # 8 MiB
# Reading 8 MiB off an SSD is milliseconds. Anything past this means something
# sat in the middle of the open — in practice, on-access AV scanning.
_AV_WARM_SLOW_S: float = float(os.environ.get("IRIS_VISION_AV_WARN_S", "3"))


# ── Idle lifecycle ────────────────────────────────────────────────────────────
# Vision loads on FIRST USE and then STAYS WARM for the life of the process.
#
# It used to auto-stop after 120s idle on the premise that a small model is
# cheap to restart. Measured 2026-08-24, that premise is false on this class of
# machine: the identical spawn took 3.87s / 3.95s / 4.90s / 11.04s / >100s
# within one 20-minute window, depending on what else held memory. So the
# 120s auto-stop did not save a cheap restart — it guaranteed that every use
# re-paid a load of unpredictable duration, and it routinely tore the server
# down in the gap between a websearch prewarm and the vision call that
# followed. That is the mechanism behind "vision is randomly unavailable".
#
# Set IRIS_VISION_IDLE_TIMEOUT=<seconds> to re-enable auto-stop (e.g. to hand
# the ~2GB back to a local brain model or LM Studio on a small card).
#
# NOTE: expressed as a very large finite timeout rather than a disabled flag
# on purpose — should_idle_stop() keeps its exact "idle past the timeout"
# semantics, so the lease/idle contracts stay meaningful and their tests keep
# testing the real predicate. A finite value (not inf) avoids inf-inf NaN in
# any caller doing timeout arithmetic.
_STAY_WARM_S: float = 315_360_000.0  # 10 years == "not while this process lives"
_IDLE_TIMEOUT: float = float(
    os.environ.get("IRIS_VISION_IDLE_TIMEOUT", _STAY_WARM_S)
)

_last_vision_use: float = 0.0
_idle_timer: Optional[threading.Timer] = None
_idle_lock = threading.Lock()
_vision_idle_callback = None  # set by iris_gateway to broadcast idle-stop status


def set_vision_idle_callback(cb) -> None:
    """Register a callback invoked when the idle watchdog stops the server."""
    global _vision_idle_callback
    _vision_idle_callback = cb


def _idle_timer_interval() -> float:
    """How long the next idle-watchdog tick should wait.

    NOT simply ``_IDLE_TIMEOUT``: threading.Timer ultimately calls
    ``waiter.acquire(True, interval)``, which raises ``OverflowError: timeout
    value is too large`` well below the stay-warm sentinel — the timer thread
    then dies with an unhandled exception on every vision use. So the wait is
    capped and the watchdog simply re-arms; ``_idle_stop`` re-checks
    ``should_idle_stop()`` on every tick, so a capped tick can only ever
    decline to stop early, never stop early.
    """
    _cap = min(threading.TIMEOUT_MAX, 3600.0)  # re-arm at most hourly
    return max(0.0, min(_IDLE_TIMEOUT, _cap))


def _touch_vision_use() -> None:
    """Record a vision use and (re)schedule the idle auto-stop timer.

    Only schedules a timer when IRIS owns the server (_VISION_SERVER_PID set),
    so a user-run llama-server is never idled out.
    """
    global _last_vision_use, _idle_timer
    with _idle_lock:
        _last_vision_use = time.monotonic()
        if _idle_timer is not None:
            _idle_timer.cancel()
        if _VISION_SERVER_PID is not None:
            _idle_timer = threading.Timer(_idle_timer_interval(), _idle_stop)
            _idle_timer.daemon = True
            _idle_timer.start()


def should_idle_stop() -> bool:
    """Pure predicate: is the owned server idle past the timeout?"""
    if _VISION_SERVER_PID is None:
        return False
    if has_active_lease():
        return False  # REQ-9: never idle-stop a server under an active lease
    return (time.monotonic() - _last_vision_use) >= _IDLE_TIMEOUT


# --- Vision lease (T9, REQ-7/REQ-9) ------------------------------------------
# A counted lease with a hard expiry. While any lease is active the idle
# watchdog defers the stop, so a fetch.vision session (multi-action loop,
# possibly > 120 s wall time) cannot be killed mid-task. Leases are pure
# bookkeeping here — no server calls — and expire lazily.

_VISION_LEASES: dict[str, float] = {}  # lease_id -> monotonic deadline
_LEASE_LOCK = threading.Lock()


class VisionLease:
    """Context-managed vision lease with hard expiry.

    Usable as ``with acquire_vision_lease(max_ms=...) as lease:`` so the
    lease is ALWAYS released on exception. ``active`` is checked lazily
    against the deadline, so an abandoned lease self-expires.
    """

    __slots__ = ("_lease_id", "_deadline", "_active")

    def __init__(self, lease_id: str, deadline: float):
        self._lease_id = lease_id
        self._deadline = deadline
        self._active = True

    @property
    def lease_id(self) -> str:
        return self._lease_id

    @property
    def deadline(self) -> float:
        return self._deadline

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self._deadline

    @property
    def active(self) -> bool:
        if not self._active:
            return False
        if self.expired:
            self.release()
            return False
        return True

    def release(self) -> None:
        if not self._active:
            return
        self._active = False
        with _LEASE_LOCK:
            _VISION_LEASES.pop(self._lease_id, None)

    def __enter__(self) -> "VisionLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()  # releases on exception (REQ-9 AC3) and on normal exit


def acquire_vision_lease(max_ms: float = 60_000.0) -> Optional[VisionLease]:
    """Acquire a vision lease that hard-expires after ``max_ms``.

    Returns None when the owned vision server is not running (nothing to
    protect) — callers treat None as "no lease needed, proceed".
    """
    _prune_expired_leases()
    if _VISION_SERVER_PID is None:
        return None
    deadline = time.monotonic() + max(1.0, max_ms) / 1000.0
    lease_id = uuid.uuid4().hex
    with _LEASE_LOCK:
        _VISION_LEASES[lease_id] = deadline
    return VisionLease(lease_id, deadline)


def has_active_lease() -> bool:
    """True while at least one unexpired lease is held (REQ-9 AC2)."""
    _prune_expired_leases()
    with _LEASE_LOCK:
        return bool(_VISION_LEASES)


def _prune_expired_leases() -> None:
    now = time.monotonic()
    with _LEASE_LOCK:
        expired = [lid for lid, dl in _VISION_LEASES.items() if now >= dl]
        for lid in expired:
            _VISION_LEASES.pop(lid, None)


# ── Single-flight spawn (specs/vision-browser-stage REQ-1) ───────────────────
# Concurrent callers of _ensure_vision_server_running (boot prewarm, lazy
# first call, explicit start(), the tool_bridge vision path, N concurrent
# escalations) used to EACH run a full spawn attempt during the ~25-90s ready
# window; losers failed port-bind and their cleanup could kill the winner's
# healthy server. Now: ONE in-flight attempt; waiters block on its Event.
#
# OPT GATE (tasks.md): the health fast path stays OUTSIDE the lock so a warm
# server never contends; waiters block on an Event (zero polling); the attempt
# object is allocated once per SPAWN, never per call.
class _SpawnAttempt:
    """One coalesced spawn attempt. The leader runs the spawn; waiters share
    the outcome via `done`. `done` is ALWAYS set — success, failure, or
    exception — so a waiter can never hang."""

    __slots__ = ("done", "result")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.result = False


_spawn_lock = threading.Lock()
_spawn_attempt: Optional[_SpawnAttempt] = None


# ── Vision lifecycle broadcast (REQ-5) ──────────────────────────────────────
# cold -> spawning -> warm | error. Emitted off every inference path via a
# registered callback (same pattern as set_vision_idle_callback). Duplicate
# transitions inside the debounce window are dropped so a flapping state
# cannot spam the WS channel.
_lifecycle_callback = None
_lifecycle_lock = threading.Lock()
_last_lifecycle: tuple = ("", 0.0)  # (state, monotonic)
_LIFECYCLE_DEBOUNCE_S = 1.0


def set_vision_lifecycle_callback(cb) -> None:
    """Register the callback invoked on vision lifecycle transitions."""
    global _lifecycle_callback
    _lifecycle_callback = cb


def _notify_lifecycle(state: str, reason: str = "", trigger: str = "") -> None:
    """Best-effort lifecycle emit — never raises, never blocks inference."""
    global _last_lifecycle
    now = time.monotonic()
    with _lifecycle_lock:
        last_state, last_t = _last_lifecycle
        if state == last_state and (now - last_t) < _LIFECYCLE_DEBOUNCE_S:
            return
        _last_lifecycle = (state, now)
    cb = _lifecycle_callback
    if cb is None:
        return
    try:
        cb(state=state, reason=reason, trigger=trigger)
    except Exception as exc:  # noqa: BLE001 — broadcast must never fail a call
        logger.debug("[LFMVLProvider] lifecycle notify failed: %s", exc)


# ── Search-scoped warmth (REQ-4) ─────────────────────────────────────────────
# Boot prewarm evaporates to the idle-stop; request_warm re-warms at
# crawler_started (sequenced AFTER pool readiness by the gateway caller) so
# escalation finds a warm endpoint. Idempotent: at most one warm in flight;
# the actual spawn delegates to _ensure_vision_server_running and therefore
# inherits single-flight (REQ-4 AC3).
_warm_guard = threading.Lock()
_warm_in_flight = False
_current_trigger = "lazy-call"  # attribution for lifecycle emits


def request_warm(trigger: str) -> bool:
    """Warm the owned vision server, attributed to `trigger`
    ('boot' | 'search-scoped' | 'lazy-call'). Returns True when reachable.

    Bounded to one in-flight warm (REQ-4 AC5); a warm arriving while another
    is running is dropped (the in-flight one covers it)."""
    global _warm_in_flight, _current_trigger
    with _warm_guard:
        if _warm_in_flight:
            logger.info(
                "[LFMVLProvider] warm already in flight — dropping trigger=%s",
                trigger,
            )
            return False
        _warm_in_flight = True
        _current_trigger = trigger or "lazy-call"
    try:
        ok = _ensure_vision_server_running()
        if ok:
            _touch_vision_use()
        return ok
    finally:
        with _warm_guard:
            _warm_in_flight = False


def _stop_owned_vision_server() -> None:
    """Kill the llama-server subprocess IRIS spawned (tracked PID only)."""
    global _VISION_SERVER_PID
    if _VISION_SERVER_PID is None:
        return
    _kill_process_tree(_VISION_SERVER_PID)
    logger.info(f"[LFMVLProvider] Stopped vision server PID {_VISION_SERVER_PID}")
    _VISION_SERVER_PID = None


def _kill_process_tree(pid: Optional[int]) -> None:
    """Kill a process AND its children (REQ-2 ownership-safe cleanup).

    Only ever called with a PID this module spawned and still holds a Popen
    handle for — never with a port-scanned stranger. Windows: `taskkill /T`
    walks the child tree. POSIX: the spawn used start_new_session, so the
    child is its own process group -> killpg; fall back to a direct kill.
    Never raises."""
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True, timeout=15,
            )
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGTERM)
    except Exception as e:
        logger.warning(f"[LFMVLProvider] Failed to stop vision server tree {pid}: {e}")


def _kill_pid(pid: Optional[int]) -> None:
    """Best-effort kill of a pid (platform-aware), never raising."""
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=15)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def _probe_av_latency(*paths: str, server_binary: str = "") -> float:
    """Time a single small read of each model file before spawning
    llama-server, purely as a DIAGNOSTIC. Returns seconds spent. Never raises.

    WHY (measured live 2026-08-24 — the root cause of "vision is randomly
    unavailable"): Windows Defender real-time protection scans a GGUF on first
    open. llama-server blocks inside the AV filter driver for the whole scan
    with NO cpu, NO io progress and NO log output, so it is indistinguishable
    from a hung process. Captured trace for the 854MB F16 mmproj:
    llama-server's read_bytes sat at 11MB for 73 SECONDS while MsMpEng.exe
    burned CPU linearly, then jumped to 826MB and the server was ready at
    75.66s. Any readiness heuristic that reads silence as death kills that
    load and reports vision unavailable.

    This function CANNOT fix that, and does not pretend to. Pre-reading the
    files in full was tried and measured harmful: 29.7s to pull 2.5GB through
    the scanner, after which llama-server was STILL blocked 481s, because
    Defender's verdict cache is scoped to the accessing process. So the files
    are merely PROBED, and the only product is a log line that names AV
    instead of leaving a mysterious llama.cpp hang.

    THE ACTUAL FIX is an AV exclusion, which the slow-path warning spells out.
    """
    _t0 = time.monotonic()
    _server_binary = server_binary
    _model_dir = ""
    for _p in paths:
        if _p:
            _model_dir = str(Path(_p).parent)
            break
    for _p in paths:
        if not _p:
            continue
        try:
            # PROBE ONLY — deliberately NOT a full read.
            #
            # A full sequential read was tried first and MEASURED HARMFUL: it
            # cost 29.7s to pull 2.5GB through the scanner, and llama-server
            # was STILL blocked for 481s afterwards. Defender's verdict cache
            # is scoped per accessing process, so warming the file from python
            # buys llama-server nothing — it just pays the scan twice and
            # evicts page cache on the way.
            #
            # One chunk is enough for the only thing this function can
            # honestly deliver: a TIMING SIGNAL that names AV as the culprit
            # in the log, cheaply, before the spawn.
            with open(_p, "rb", buffering=0) as _fh:
                _fh.readinto(_AV_PROBE_BUF)
        except Exception as _exc:  # noqa: BLE001 — probing must never block a spawn
            logger.debug("[LFMVLProvider] av-probe skipped for %s (%s)", _p, _exc)
    _elapsed = time.monotonic() - _t0
    if _elapsed >= _AV_WARM_SLOW_S:
        logger.warning(
            "[LFMVLProvider] av_scan_suspected probe_sec=%.1f model_dir=%s — a "
            "small read of the vision model files took far longer than disk. "
            "This is on-access antivirus scanning, and it blocks llama-server "
            "inside the filter driver with no cpu/io/log output for the whole "
            "scan (measured: 73s on the mmproj). Fix, in an ADMINISTRATOR "
            "PowerShell: Add-MpPreference -ExclusionPath '%s' ; "
            "Add-MpPreference -ExclusionProcess '%s'  (the PROCESS exclusion "
            "is the one that matters — Defender's verdict cache is per "
            "accessing process, so pre-reading the files elsewhere does not "
            "help llama-server).",
            _elapsed,
            _model_dir,
            _model_dir,
            _server_binary or "<path to llama-server.exe>",
        )
    else:
        logger.info("[LFMVLProvider] av_probe_ok sec=%.1f", _elapsed)
    return _elapsed


def _proc_cpu_seconds(pid: Optional[int]) -> Optional[float]:
    """Total CPU seconds burned by ``pid``, or None if it cannot be read.

    This is the readiness loop's LIVENESS signal and the fix for the bug that
    made vision "randomly unavailable" (2026-08-24). llama.cpp emits NOTHING
    between "load_model: loading model '<gguf>'" and "loaded multimodal
    model" — measured, every stalled log truncates at exactly one of those
    two points. So the old no-progress test ("has the stderr log grown?")
    could not tell a healthy slow load from a dead process, and killed
    healthy loads at 120s.

    A loading llama-server pegs a core; a genuinely wedged one does not. CPU
    time is therefore the honest discriminator. Never raises — an unreadable
    value returns None and the caller treats it as "no information", never as
    "dead".
    """
    if not pid:
        return None
    try:
        import psutil  # already a backend dependency

        t = psutil.Process(pid).cpu_times()
        return float(t.user + t.system)
    except Exception:
        return None


def _read_log_tail(log_path: str, max_lines: int = 20) -> str:
    """Best-effort read of the last ``max_lines`` of a log file, never raising.

    Used on the failed-start edge case (REQ-6): when the vision server exits
    during start, its own stderr is far more useful than a generic timeout
    message. Returns an explanatory string instead of raising if the file is
    missing, empty, or unreadable (e.g. still locked on Windows).
    """
    try:
        with open(log_path, "rb") as f:
            raw = f.read()
        if not raw:
            return "(stderr log is empty)"
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        return "\n".join(lines[-max_lines:])
    except Exception as exc:  # noqa: BLE001 — diagnostics must never block
        return f"(failed to read stderr log {log_path}: {exc})"


def _idle_stop() -> None:
    """Idle watchdog callback: stop the owned server if it is still idle."""
    global _idle_timer
    with _idle_lock:
        _idle_timer = None
    if not should_idle_stop():
        # Not idle yet (or REQ-9: an active lease defers the stop). RE-ARM
        # rather than returning dead. The old code relied on the next
        # _touch_vision_use to reschedule, which is exactly backwards: a
        # server that is never touched again is the one that should idle out,
        # and it was the only one whose watchdog stayed dead. Re-arming also
        # makes the capped interval in _idle_timer_interval correct — a tick
        # that fires early just re-arms until the real deadline passes.
        with _idle_lock:
            if _VISION_SERVER_PID is not None and _idle_timer is None:
                _idle_timer = threading.Timer(_idle_timer_interval(), _idle_stop)
                _idle_timer.daemon = True
                _idle_timer.start()
        return
    _stop_owned_vision_server()
    _notify_lifecycle("cold", reason="idle timeout")  # REQ-5: truth to the UI
    cb = _vision_idle_callback
    if cb is not None:
        try:
            cb()
        except Exception:
            pass


_lfm_vl_provider_singleton = None


def get_lfm_vl_provider():
    """Module-level singleton used by both the gateway and VisionMCPServer."""
    global _lfm_vl_provider_singleton
    if _lfm_vl_provider_singleton is None:
        _lfm_vl_provider_singleton = LFMVLProvider()
    return _lfm_vl_provider_singleton


@dataclass
class LFMVLConfig:
    """Configuration for LFM2.5-VL vision provider."""
    base_url: str = f"http://127.0.0.1:{_VISION_PORT}/v1"
    temperature: float = 0.1
    min_p: float = 0.15
    repetition_penalty: float = 1.05
    image_max_tokens: int = 128  # 64 for speed, 256 for detail
    timeout: float = 30.0


class VisionModelUnavailable(RuntimeError):
    """Raised when no vision-language model can be found on disk, or none of
    the discovered candidates fit current free VRAM (REQ-3 AC4).

    Carries the facts AC4's error message and AC6's VISION_UNAVAILABLE chat
    system message both need, computed exactly once (``_fail_vision_
    unavailable`` populates both from this object) so the log, the raise and
    the event can never disagree.
    """

    def __init__(
        self,
        message: str,
        *,
        free_gb: float = 0.0,
        smallest_requirement_gb: float = 0.0,
        ladder: Optional[list] = None,
    ) -> None:
        super().__init__(message)
        self.free_gb = free_gb
        self.smallest_requirement_gb = smallest_requirement_gb
        self.ladder = ladder or []


def _fail_vision_unavailable(
    message: str,
    *,
    free_gb: float,
    smallest_requirement_gb: float,
    ladder: list,
) -> None:
    """Log, escalate (REQ-3 AC6) and raise (REQ-3 AC4) — the single exit for
    every "no usable VL model" path, so AC4's error and AC6's chat system
    message always carry the same facts.

    Emitting VISION_UNAVAILABLE is best-effort: the EventBus is optional
    infrastructure (mirrors the existing BUDGET_EXHAUSTED/VALIDATION_FAILED
    emit sites in agent_kernel.py) — a broken bus must never suppress the
    raise, which is the part that actually stops a doomed spawn.
    """
    logger.error("[LFMVLProvider] %s", message)
    try:
        from backend.agent.event_bus import get_event_bus, IRISStreamEvent

        get_event_bus().emit(
            IRISStreamEvent.VISION_UNAVAILABLE,
            data={
                "message": message,
                "free_vram_gb": round(free_gb, 2),
                "smallest_requirement_gb": round(smallest_requirement_gb, 2),
                "ladder": ladder,
            },
        )
    except Exception as exc:  # noqa: BLE001 — EventBus is optional, never blocks the raise
        logger.warning("[LFMVLProvider] failed to emit VISION_UNAVAILABLE: %s", exc)
    raise VisionModelUnavailable(
        message,
        free_gb=free_gb,
        smallest_requirement_gb=smallest_requirement_gb,
        ladder=ladder,
    )


def _read_free_vram_gb() -> Tuple[float, bool, bool]:
    """Read TRUE free VRAM — the ONE source both candidate selection
    (``_find_vision_model``) and the GPU-vs-CPU decision
    (``_compute_vision_gpu_layers``) read from, so they never disagree about
    what "free" means.

    nvidia-smi first (sees every process on the card — the driver, not
    torch, is the authority on free VRAM; torch.cuda.memory_allocated only
    counts torch's own tensors and reported ~8GB "free" on a card where the
    desktop + a loaded local model already held ~5GB, verified 2026-08-12).
    Falls back to LocalModelManager.get_hardware_info() only when nvidia-smi
    is unavailable.

    Returns ``(free_gb, readable, cuda_available)``:
      - ``readable=False`` — neither source produced a trustworthy figure
        (REQ-3 edge case: "Free VRAM unreadable -> use the most conservative
        candidate").
      - ``cuda_available=False`` — no GPU was detected at all. This is NOT a
        "does not fit" failure (there is no VRAM budget to fail against); it
        is handled as its own case by callers.
    """
    import shutil as _shutil
    import subprocess as _sp

    _nvsmi = _shutil.which("nvidia-smi")
    if _nvsmi:
        try:
            _out = _sp.run(
                [_nvsmi, "--query-gpu=memory.free,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            if _out.returncode == 0 and _out.stdout.strip():
                _free_mib, _total_mib = (float(x) for x in _out.stdout.split(",")[:2])
                return _free_mib / 1024.0, True, True
        except Exception:
            pass  # fall through to the hardware-info fallback below

    try:
        from backend.agent.local_model_manager import get_local_model_manager

        hw = get_local_model_manager().get_hardware_info()
    except Exception:
        return 0.0, False, False

    cuda_available = bool(hw.get("cuda_available"))
    if not cuda_available:
        return 0.0, True, False  # readable: we KNOW there is no GPU
    free_gb = hw.get("vram_free_gb")
    if free_gb is None:
        return 0.0, False, True
    return float(free_gb), True, True


def _estimate_vision_footprint_gb(model_path: str, mmproj_path: str) -> float:
    """THE single VRAM estimator for vision — used by both candidate
    selection (``_find_vision_model``, REQ-3 AC1/AC2) and the GPU-vs-CPU
    offload decision (``_compute_vision_gpu_layers``).

    Before this change the two functions carried INDEPENDENT estimators:
    this one (via ``_find_vision_model``, which did no VRAM math at all) and
    ``_compute_vision_gpu_layers``'s inline ``model_gb + mmproj_gb + 0.3``
    with a hardcoded KV constant — they could disagree about what "fits"
    means. Reconciled: both now call this, which delegates weights+KV math
    to ``LocalModelManager.estimate_vram_gb`` — the GQA- and KV-quant-aware
    estimator every local-model load already budgets against (e9d2fc89).

    Real GGUF header metadata (block_count, n_head_kv, head_dim) is parsed
    when the file is a well-formed GGUF, giving an accurate, architecture-
    aware KV term. ``parse_gguf_metadata`` never raises and degrades to
    ``{}`` for an unreadable/foreign file, in which case
    ``estimate_vram_gb``'s own per-parameter KV fallback applies — there is
    no vision-specific hardcoded constant left in this module at all.
    """
    model_gb = (os.path.getsize(model_path) or 0) / (1024 ** 3)
    mmproj_gb = (os.path.getsize(mmproj_path) or 0) / (1024 ** 3)

    from backend.agent.local_model_manager import get_local_model_manager

    lm = get_local_model_manager()
    try:
        model_meta = lm.parse_gguf_metadata(Path(model_path))
    except Exception:
        model_meta = {}

    return lm.estimate_vram_gb(
        model_meta,
        n_ctx=_VISION_CTX_SIZE,
        file_size_gb=model_gb,
        # REQ-3 AC2: the projector is a SEPARATE GGUF, absent from the base
        # model's file size — added to the weights term, not assumed included.
        mmproj_size_gb=mmproj_gb,
        kv_bytes=1,  # q8_0 cache — matches the GPU profiles this project uses
    )


def _configured_vision_ladder() -> list:
    """Read the user's chosen vision fallback ladder (REQ-10 AC2/AC3).

    ``cfg.inference.vision_fallback_ladder`` is a list of model ``path``
    strings — the SAME identity ``scan_models()`` and the model browser
    already use to address a model — in USER-CHOSEN PRIORITY ORDER.
    Empty/absent means "auto" (AC5). A malformed value (wrong type, garbage
    entries) degrades to auto rather than raising: a broken config must
    never crash vision (never-crash contract; mirrors every other config
    read in this module).
    """
    try:
        cfg = _load_vl_config()
        ladder = getattr(cfg.inference, "vision_fallback_ladder", None) or []
        if not isinstance(ladder, list):
            logger.warning(
                "[LFMVLProvider] cfg.inference.vision_fallback_ladder is not "
                "a list (got %s) -> falling back to auto-selection",
                type(ladder).__name__,
            )
            return []
        return [str(entry) for entry in ladder if entry]
    except Exception as exc:  # noqa: BLE001 — a broken config must never crash vision
        logger.warning(
            "[LFMVLProvider] failed to read vision_fallback_ladder from "
            "config (%s) -> falling back to auto-selection", exc,
        )
        return []


def _discover_vision_candidates() -> list:
    """Discover vision-capable candidates from the SCANNED models directory
    (REQ-10 AC1/AC7) — no hardcoded GGUF model id or directory name anywhere
    in this path.

    Source: ``LocalModelManager.scan_models()`` already attaches
    ``has_vision`` / ``mmproj_path`` / ``mmproj_size_gb`` to every
    projector-paired base model (REQ-5, T1) — every ``has_vision: true``
    entry it returns IS the candidate list. This replaces the earlier
    hardcoded, model-family-named directory walk (see git history) with the
    SAME discovery the model browser already relies on — one mechanism, not
    two.

    Ordering (REQ-3 AC1's size-FIT arithmetic in ``_find_vision_model``
    applies identically either way — this function only decides the WALK
    ORDER candidates are offered in):
      - Configured (``cfg.inference.vision_fallback_ladder`` non-empty,
        REQ-10 AC2/AC3/AC4): candidates are ordered exactly as the user
        chose. A configured entry that is no longer vision-capable (deleted
        from disk, or its projector deleted) is SKIPPED and LOGGED (AC6),
        never a hard failure — the walk continues to the next entry.
      - Auto (nothing configured, REQ-10 AC5): candidates are ranked
        widest-first by measured footprint — unchanged default behavior.

    Bounded and cheap: ``scan_models()`` is the SAME call the model browser
    already makes per rescan (its own GGUF-metadata cache keeps repeat scans
    fast), and this only runs on a cold vision-server start — the per-
    request hot path short-circuits via an httpx health check in
    ``_ensure_vision_server_running`` before this is ever reached.
    """
    try:
        from backend.agent.local_model_manager import get_local_model_manager

        scanned = get_local_model_manager().scan_models()
    except Exception as exc:  # noqa: BLE001 — a broken scan must never crash vision
        logger.warning(
            "[LFMVLProvider] scan_models() failed during vision candidate "
            "discovery (%s) -> no vision candidates", exc,
        )
        return []

    vision_models = {
        m["path"]: m
        for m in scanned
        if m.get("has_vision") and m.get("mmproj_path")
    }

    configured = _configured_vision_ladder()
    if configured:
        entries = []
        for model_id in configured:
            entry = vision_models.get(model_id)
            if entry is None:
                # REQ-10 AC6 / edge case: missing from disk OR its projector
                # was deleted since it was chosen — either way scan_models()
                # no longer reports it has_vision, so it is not in the dict
                # above. Skip and log; the ladder walk continues.
                logger.info(
                    "[LFMVLProvider] configured vision candidate SKIPPED "
                    "(missing from disk or no longer has a matching "
                    "projector): %s",
                    model_id,
                )
                continue
            entries.append(entry)
        auto = False
    else:
        entries = list(vision_models.values())
        auto = True

    candidates = []
    for entry in entries:
        try:
            needed_gb = _estimate_vision_footprint_gb(entry["path"], entry["mmproj_path"])
        except Exception as exc:  # noqa: BLE001 — one bad candidate must not drop the rest
            logger.warning(
                "[LFMVLProvider] vision candidate SKIPPED (footprint "
                "estimate failed: %s): %s", exc, entry.get("path"),
            )
            continue
        candidates.append({
            "model_path": entry["path"],
            "mmproj_path": entry["mmproj_path"],
            "needed_gb": needed_gb,
        })

    if auto:
        # AC5: nothing configured -> widest-first, the prior default.
        candidates.sort(key=lambda c: c["needed_gb"], reverse=True)
    # else: AC2/AC4 — preserve the user's chosen priority order verbatim;
    # _find_vision_model walks it top-to-bottom and takes the first whose
    # weights + projector + KV fit (REQ-3's arithmetic, unchanged) — a
    # candidate ordered first that cannot fit any plausible free VRAM is
    # rejected there and logged, not treated as a hard failure (edge case).
    return candidates


def _find_vision_model(vram_state=None) -> Optional[Tuple[str, str]]:
    """
    Size-select the VL fallback model from a widest-first ladder walked
    against REAL free VRAM (REQ-3 AC1), taking the first candidate whose
    weights + projector + KV fit — never an unconditional size preference.

    ``vram_state`` (REQ-13 AC1, T4): an optional pre-read
    ``(free_gb, readable, cuda_available)`` tuple so ONE nvidia-smi probe
    serves both candidate selection AND the GPU-layer decision within a
    single spawn. When None the read happens here (back-compat for existing
    callers/tests).

    Returns ``(model_path, mmproj_path)``.

    FAIL LOUDLY (REQ-3 AC4/AC6, user-resolved 2026-08-18: "fail loudly and
    alert the user through a system message") — raises
    ``VisionModelUnavailable`` when either no VL model exists on disk at all,
    or none of the discovered candidates fit current free VRAM. The raise
    always follows a VISION_UNAVAILABLE chat system message emit and a log
    line naming the same facts (``_fail_vision_unavailable``). Callers must
    catch ``VisionModelUnavailable`` — this is a clean, reported failure,
    never an exception left to escape into the agent loop.
    """
    candidates = _discover_vision_candidates()

    if not candidates:
        msg = (
            "No vision-capable model found. IRIS looks for a base GGUF with "
            "a matching mmproj*.gguf projector inside the configured models "
            "directory (scanned the same way the model browser does) — "
            "REQ-10: any such pair works, none is hardcoded. Download one "
            "(e.g. python scripts/models/download_vision_model.py) or point "
            "the models directory at one you already have."
        )
        _fail_vision_unavailable(
            msg, free_gb=0.0, smallest_requirement_gb=0.0, ladder=[],
        )

    if vram_state is None:
        vram_state = _read_free_vram_gb()
    free_gb, vram_readable, _cuda_available = vram_state

    if not vram_readable:
        # REQ-3 edge case: free VRAM unreadable -> most conservative
        # candidate (narrowest estimated footprint), no fit arithmetic —
        # there is no trustworthy free-VRAM figure to compare against.
        chosen = candidates[-1]
        logger.warning(
            "[LFMVLProvider] free VRAM unreadable -> choosing most "
            "conservative vision candidate: %s (needs ~%.2fGB)",
            chosen["model_path"], chosen["needed_gb"],
        )
        return chosen["model_path"], chosen["mmproj_path"]

    rejected: list = []
    for c in candidates:
        headroom = free_gb - _VISION_VRAM_RESERVE_GB
        if c["needed_gb"] <= headroom:
            logger.info(
                "[LFMVLProvider] vision candidate ladder (widest-first): %s",
                [cand["model_path"] for cand in candidates],
            )
            if rejected:
                logger.info(
                    "[LFMVLProvider] vision candidates rejected before selection: %s",
                    rejected,
                )
            logger.info(
                "[LFMVLProvider] vision model SELECTED: %s needs %.2fGB, "
                "%.2fGB free (reserving %.2fGB for a later local-model load)",
                c["model_path"], c["needed_gb"], free_gb, _VISION_VRAM_RESERVE_GB,
            )
            return c["model_path"], c["mmproj_path"]
        reason = (
            f"needs {c['needed_gb']:.2f}GB, only {headroom:.2f}GB available "
            f"after the {_VISION_VRAM_RESERVE_GB:.2f}GB reserve"
        )
        logger.info(
            "[LFMVLProvider] vision candidate REJECTED: %s (%s)",
            c["model_path"], reason,
        )
        rejected.append({
            "model_path": c["model_path"],
            "needed_gb": round(c["needed_gb"], 2),
            "reason": reason,
        })

    smallest = min(c["needed_gb"] for c in candidates)
    msg = (
        f"No vision-language model fits current free VRAM: {free_gb:.2f}GB "
        f"free (reserving {_VISION_VRAM_RESERVE_GB:.2f}GB for a later "
        f"local-model load), smallest candidate needs {smallest:.2f}GB."
    )
    _fail_vision_unavailable(
        msg, free_gb=free_gb, smallest_requirement_gb=smallest, ladder=rejected,
    )
    return None  # unreachable — _fail_vision_unavailable always raises; keeps mypy happy


def _find_llama_server_binary() -> Optional[str]:
    """
    Find llama-server binary for the vision model.

    Priority: upstream ggml-org/llama.cpp (supports LFM2/LFM2-VL)
             → LocalModelManager discovery (ik_llama.cpp, PATH, etc.)
             → basic PATH search

    We prefer upstream llama.cpp for vision because ik_llama.cpp
    (Kimi-K2 fork) does not support the LFM2 model architecture.
    Brain models on port 8082 continue to use whatever binary
    LocalModelManager resolves (ik_llama.cpp for Kimi-K2).
    """
    # 1. Prefer upstream llama.cpp which supports LFM2/LFM2-VL
    upstream = Path.home() / "llama.cpp-upstream" / "llama-server"
    if upstream.exists():
        return str(upstream)

    # 2. Reuse LocalModelManager discovery
    try:
        from backend.agent.local_model_manager import LocalModelManager
        return LocalModelManager._find_llama_server_binary()
    except Exception:
        pass

    # 3. Fallback: basic PATH search
    import shutil
    found = shutil.which("llama-server")
    if found:
        return found
    return None


def _compute_vision_gpu_layers(model_path: str, mmproj_path: str, vram_state=None) -> int:
    """Decide how many GPU layers the vision llama-server should offload.

    ``vram_state`` (REQ-13 AC1, T4): optional pre-read
    ``(free_gb, readable, cuda_available)`` shared with ``_find_vision_model``
    so one nvidia-smi probe serves the whole spawn decision — and so selection
    and this decision can never disagree about what "free" means (the TOCTOU
    two-read race is structurally gone).

    The vision model runs on the GPU when VRAM allows (2026-08-12: this used
    to default to CPU-only — the spawn command passed NO -ngl flag, so
    llama.cpp defaulted to 0 GPU layers, confirmed live by flat VRAM
    before/after a vision model load).

    This is deliberate about headroom: the brain/tool models are normally
    cloud API providers (Cerebras etc.), but a USER may load a local model
    for brain or tool execution at any time. Vision must therefore never
    grab so much VRAM that a subsequent local-model load OOMs. We:

      1. Read CURRENT free VRAM via ``_read_free_vram_gb`` — the SAME
         reader ``_find_vision_model`` uses, so selection and this decision
         never disagree about what "free" means.
      2. Estimate the model's footprint (weights + mmproj + KV cache) via
         ``_estimate_vision_footprint_gb`` — the SAME estimator
         ``_find_vision_model`` uses (REQ-3: one estimator, not two; the old
         inline ``model_gb + mmproj_gb + 0.3`` with a hardcoded KV constant
         is gone).
      3. Offload ALL layers if the model fits with the reserved margin (see
         _VISION_VRAM_RESERVE_GB).

    REQ-3 AC4/AC6 (user-resolved 2026-08-18: "fail loudly and alert the user
    through a system message"): when CUDA IS available but the given model
    does NOT fit, this now raises ``VisionModelUnavailable`` — the CPU
    degrade this function used to perform for that case is REMOVED.
    ``_find_vision_model`` already screens candidates against free VRAM
    before returning one, so this path fires only if free VRAM changed
    between selection and spawn (a concurrent load) or a caller supplies an
    unscreened pair directly.

    A machine with NO GPU at all is a DIFFERENT case — there is no VRAM
    budget to fail against, so CPU (0) remains the correct, unchanged
    outcome; only the VRAM-insufficient case became a hard failure.

    Returning 0 = CPU. Returning a large number = full GPU offload.
    llama.cpp accepts -ngl N with N > layer count meaning "all".
    """
    if not model_path or not mmproj_path:
        return 0
    try:
        if vram_state is None:
            vram_state = _read_free_vram_gb()
        free_gb, vram_readable, cuda_available = vram_state

        if not cuda_available:
            logger.info(
                "[LFMVLProvider] No CUDA device detected -> vision runs on "
                "CPU (ngl=0); no VRAM budget applies"
            )
            return 0
        if not vram_readable:
            logger.warning(
                "[LFMVLProvider] free VRAM unreadable -> vision runs on CPU "
                "(ngl=0) rather than offload against an unknown budget"
            )
            return 0

        needed_gb = _estimate_vision_footprint_gb(model_path, mmproj_path)

        if needed_gb <= free_gb - _VISION_VRAM_RESERVE_GB:
            logger.info(
                "[LFMVLProvider] GPU offload: vision needs %.2fGB, %.2fGB free "
                "(reserving %.2fGB for a local brain/tool model) -> full offload",
                needed_gb, free_gb, _VISION_VRAM_RESERVE_GB,
            )
            return 999  # "all layers" — llama.cpp clamps to the model's count

        reason = (
            f"needs {needed_gb:.2f}GB, only "
            f"{free_gb - _VISION_VRAM_RESERVE_GB:.2f}GB available after the "
            f"{_VISION_VRAM_RESERVE_GB:.2f}GB reserve"
        )
        msg = (
            f"Vision model does not fit free VRAM: {free_gb:.2f}GB free "
            f"(reserving {_VISION_VRAM_RESERVE_GB:.2f}GB), model needs "
            f"{needed_gb:.2f}GB."
        )
        _fail_vision_unavailable(
            msg,
            free_gb=free_gb,
            smallest_requirement_gb=needed_gb,
            ladder=[{"model_path": model_path, "needed_gb": round(needed_gb, 2), "reason": reason}],
        )
        return 0  # unreachable — _fail_vision_unavailable always raises
    except VisionModelUnavailable:
        raise
    except Exception as _exc:  # noqa: BLE001 — VRAM probe must never crash vision
        logger.warning("[LFMVLProvider] GPU layer probe failed (%s) -> CPU fallback", _exc)
        return 0


def _ensure_vision_server_running(base_url: str = "") -> bool:
    """Ensure the vision llama-server is reachable, spawning it if needed.

    SINGLE-FLIGHT (specs/vision-browser-stage REQ-1): concurrent callers from
    ANY entry point (boot prewarm, lazy _call, start(), tool_bridge, N
    escalations) coalesce onto ONE in-flight attempt — waiters block on its
    Event and share the outcome; exactly one llama-server is ever spawned.

    Structure:
      1. Health fast path OUTSIDE the lock (REQ-1 AC5) — a warm server never
         contends.
      2. Under `_spawn_lock`: join the in-flight attempt or become its leader.
      3. Leader runs ONE spawn attempt; `attempt.done` is ALWAYS set in a
         finally, so a waiter can never hang.

    Returns True when the server is reachable after this call.
    """
    requested_port = _VISION_PORT

    # ── 1. fast path, no lock ──
    # base_url ALREADY ENDS IN /v1 (LFMVLConfig.base_url), so the endpoint is
    # "/models" — NOT "/v1/models". Appending /v1 again produced .../v1/v1/models,
    # which 404s forever (live proof 2026-08-10). Keep hitting /models.
    try:
        import httpx
        check_url = base_url or f"http://127.0.0.1:{requested_port}/v1"
        r = httpx.get(f"{check_url}/models", timeout=2.0)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    # ── 2. coalesce under the lock ──
    global _spawn_attempt
    with _spawn_lock:
        current = _spawn_attempt
        if current is not None and not current.done.is_set():
            attempt = current
            leader = False
        else:
            attempt = _SpawnAttempt()
            _spawn_attempt = attempt
            leader = True

    if not leader:
        logger.info(
            "[LFMVLProvider] awaiting in-flight vision server spawn "
            "(coalesced waiter)"
        )
        attempt.done.wait()
        return attempt.result

    # ── 3. leader runs the one attempt ──
    logger.info(
        f"[LFMVLProvider] Vision server not running on port {requested_port}. "
        "Attempting auto-start..."
    )
    try:
        attempt.result = bool(_spawn_vision_server_now(base_url))
        return attempt.result
    finally:
        # ALWAYS release waiters — success, failure, or exception.
        attempt.done.set()
        with _spawn_lock:
            if _spawn_attempt is attempt:
                _spawn_attempt = None


def _spawn_vision_server_now(base_url: str = "") -> bool:
    """Leader path: run ONE spawn attempt. Single-flight is the CALLER's job
    (_ensure_vision_server_running); calling this directly bypasses the lock.

    Ownership rule (REQ-2): this function kills ONLY processes it spawned
    itself — the Popen handle it owns pins the real PID (no netstat adoption,
    no port-scan kill). On Windows an open process handle prevents PID reuse;
    on POSIX the kill happens within the same-second reap window, and the
    /proc exe check below guards even that.
    """
    requested_port = _VISION_PORT

    # PREFLIGHT (2026-08-24): reap a server we previously spawned that is no
    # longer answering. The caller only reaches this function after the health
    # probe failed, so if _VISION_SERVER_PID is still set the process it names
    # is either dead (kill is a no-op) or wedged mid-load holding ~2GB of RAM
    # and its share of VRAM. Leaving it resident makes the NEXT spawn slower
    # and more likely to stall, which leaves another one behind — the
    # degrade-with-every-retry spiral behind "it only works after a reboot".
    # Ownership is unchanged: this only ever kills a pid THIS module spawned.
    global _VISION_SERVER_PID
    _stale_pid = _VISION_SERVER_PID
    if _stale_pid:
        logger.info(
            "[LFMVLProvider] reaping unresponsive owned vision server pid=%s "
            "before respawn", _stale_pid,
        )
        _kill_process_tree(_stale_pid)
        _VISION_SERVER_PID = None

    # Not running — try to auto-start

    # REQ-13 AC1 (T4): ONE free-VRAM probe serves the whole spawn decision —
    # candidate selection and the GPU-layer computation share this tuple, so
    # they can never disagree about what "free" means.
    _vram_state = _read_free_vram_gb()

    # REQ-3 AC4/AC6: _find_vision_model FAILS LOUDLY (raises + emits
    # VISION_UNAVAILABLE) when no VL model exists or none fits free VRAM,
    # rather than returning None. Caught here so the failure is a clean,
    # reported "vision unavailable" rather than an exception escaping into
    # the agent loop — the caller of start()/_call() only ever sees False.
    try:
        model_files = _find_vision_model(vram_state=_vram_state)
    except VisionModelUnavailable as exc:
        logger.warning(f"[LFMVLProvider] vision unavailable: {exc}")
        return False
    if not model_files:
        logger.warning("[LFMVLProvider] Vision model not found. Run: python scripts/models/download_vision_model.py")
        return False

    binary = _find_llama_server_binary()
    if not binary:
        logger.warning("[LFMVLProvider] llama-server binary not found in PATH. Install llama.cpp or set PATH.")
        return False

    model_path, mmproj_path = model_files
    # GPU offload: compute -ngl from CURRENT free VRAM, reserving headroom so
    # a user's later local brain/tool model load cannot OOM. Without -ngl,
    # llama.cpp runs the vision model on CPU (confirmed 2026-08-12: VRAM flat
    # before/after a vision model load). 999 = "all layers". Same FAIL
    # LOUDLY contract as _find_vision_model above (REQ-3 AC4/AC6).
    try:
        ngl = _compute_vision_gpu_layers(model_path, mmproj_path, vram_state=_vram_state)
    except VisionModelUnavailable as exc:
        logger.warning(f"[LFMVLProvider] vision unavailable: {exc}")
        return False
    cmd = [
        binary,
        "-m", model_path,
        "--mmproj", mmproj_path,
        "--port", str(requested_port),
        "--host", "127.0.0.1",
        "-np", "1",
        "-n", "512",
        "--n-gpu-layers", str(ngl),
        # REQ-6 (T4): --fit off + explicit ctx/batch sizing, mirroring
        # local_model_manager._build_server_cmd (e9d2fc89). b9591 defaults to
        # `--fit on`, which probes device memory to size anything left
        # unset — measured stalling 12-36 minutes on MoE models. This spawn
        # path never got that fix until now; it is the likely root cause of
        # the reported "vision server slow on first request".
        "--fit", "off",
        "--ctx-size", str(_VISION_CTX_SIZE),
        "--batch-size", str(_VISION_BATCH_SIZE),
        "--no-warmup",  # Prevents crash with upstream llama.cpp on WSL
    ]

    # If using the upstream binary, it needs its shared libraries in LD_LIBRARY_PATH
    env = os.environ.copy()
    binary_path = Path(binary)
    if "llama.cpp-upstream" in str(binary_path):
        # os.pathsep, not ":": this code also runs on Windows where the
        # separator is ";" (REQ-3 — the POSIX literal was a latent bug).
        env["LD_LIBRARY_PATH"] = (
            str(binary_path.parent) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        )

    # 2026-08-23 THEORY, FALSIFIED 2026-08-24 — env sanitizing is GONE.
    #
    # The previous theory was that the backend's imported-at-module-time env
    # (porcupine DLL dir on PATH, CUDA/torch vars) poisoned the child, so the
    # child's env was stripped of CUDA_/TORCH_/GGML_/LLAMA_/PERF_ and the
    # pvporcupine PATH segment was surgically removed. Measured refutation:
    #   - the identical stall reproduces from a parent that NEVER imports
    #     torch/CUDA, with a fully inherited env (877-byte truncated log,
    #     byte-identical to the backend's);
    #   - it also reproduces from a plain shell with a plain Popen, no env
    #     mutation at all.
    # Env is NOT the variable. Stripping it only risked breaking a child that
    # legitimately needs one of those vars, so the child now inherits the
    # parent env verbatim (plus LD_LIBRARY_PATH above, which IS load-bearing
    # for the upstream build).

    # Diagnostic only — see _probe_av_latency. A first-open Defender scan of
    # the mmproj was measured blocking llama-server for 73s with no cpu, no io
    # and no log output: indistinguishable from a hang, and the direct cause
    # of vision being reported unavailable. This cheap probe cannot prevent
    # that (the verdict cache is per-process), but it puts a log line naming
    # AV in front of the spawn instead of leaving a silent mystery.
    _probe_av_latency(model_path, mmproj_path, server_binary=binary)

    # RETRY IS OFF BY DEFAULT — deliberately. This is the second-order lesson
    # from the 2026-08-24 investigation.
    #
    # Retrying LOOKS right for a "wedged" spawn and is actively HARMFUL here:
    # the wedge is Windows Defender scanning the 854MB mmproj on open, so
    # killing the child and respawning throws away a scan that was most of the
    # way done and starts a fresh one. Measured: 3 attempts x a 60s window ->
    # all three "wedged", call failed after 296s. A single PATIENT attempt on
    # the same machine minutes later completed at 75.66s.
    #
    # Kept as a knob (IRIS_VISION_SPAWN_ATTEMPTS=N) because a genuinely
    # crash-looping binary is a different failure, but the default must be 1:
    # patience beats churn when the blocker is a filesystem filter driver.
    _MAX_SPAWN_ATTEMPTS = max(1, int(os.environ.get("IRIS_VISION_SPAWN_ATTEMPTS", "1")))
    for _attempt in range(1, _MAX_SPAWN_ATTEMPTS + 1):
        if _attempt > 1:
            logger.warning(
                "[LFMVLProvider] vision spawn attempt %d/%d (previous attempt "
                "wedged with no CPU progress)", _attempt, _MAX_SPAWN_ATTEMPTS,
            )
        logger.info(f"[LFMVLProvider] Spawning vision server: {' '.join(cmd)}")
        _spawn_start = time.monotonic()  # REQ-6 AC3: time-to-ready measurement
        _notify_lifecycle("spawning", trigger=_current_trigger)  # REQ-5
        try:
            # Capture llama-server stderr to a file so future load failures are
            # diagnosable (previously DEVNULL hid failures entirely — the 2026-08-12
            # -fit hang produced zero evidence in the backend log).
            log_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
            )
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(
                log_dir, f"vision-llama-server-{time.strftime('%Y%m%d-%H%M%S')}.log"
            )
            vision_stderr = open(log_path, "wb")

            # SPAWN MECHANISM — REWRITTEN 2026-08-24 after the "parent process
            # context" theory was falsified by measurement.
            #
            # The 2026-08-23 matrix concluded the decisive variable was the
            # PARENT'S CUDA/TORCH STATE and shipped a python launcher wrapper to
            # give llama-server a "clean parent". Re-measured 2026-08-24:
            #   - the stall reproduces from a console-less parent that never
            #     imports torch (GetConsoleWindow()==0, CREATE_NO_WINDOW);
            #   - it reproduces from a plain shell with a plain Popen;
            #   - the embedding-sidecar spawn shape stalls too;
            #   - `-ngl 0` (pure CPU, zero GPU allocation) stalls too;
            #   - the SAME argv measured 3.87s / 3.95s / 4.90s / 11.04s / >100s
            #     within one 20-minute window.
            # It is a variable-duration load, not a spawn-context hang. The
            # wrapper bought nothing and cost plenty: its stdout was a PIPE that
            # nothing drained until after readiness, so a chatty child could wedge
            # on a full pipe buffer, and it inserted a second process between us
            # and the server for no reason.
            #
            # This is now the shape both spawn paths that demonstrably work in
            # this repo already use:
            #   - stdout=DEVNULL, stderr=<log file>  (diagnosable, no pipe to fill)
            #   - stdin=DEVNULL                      (never block on a console read)
            #   - cwd=<binary dir>                   (Windows DLL loader resolves
            #     the CUDA runtime DLLs shipped beside llama-server — this is
            #     deliberate in local_model_manager._build_server_cmd and was the
            #     one thing the vision path genuinely lacked)
            #   - inherited env, own process group   (embedding_sidecar's shape)
            # Ownership is unchanged and simpler: proc.pid IS the server pid, so
            # there is no launcher-stdout adoption protocol and still no netstat.
            _spawn_argv = cmd
            _popen_kwargs = {}
            if os.name == "nt":
                _popen_kwargs["creationflags"] = getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                )
            else:
                _popen_kwargs["start_new_session"] = True
            proc = subprocess.Popen(
                _spawn_argv,
                stdout=subprocess.DEVNULL,
                stderr=vision_stderr,
                stdin=subprocess.DEVNULL,
                cwd=str(Path(binary).parent),
                env=env,
                **_popen_kwargs,
            )
        except Exception as e:
            logger.warning(f"[LFMVLProvider] Failed to spawn vision server: {e}")
            return False

        # (_VISION_SERVER_PID is already declared global at the top of this
        # function, for the preflight reap.)
        # proc.pid IS the llama-server pid (the launcher wrapper is gone), so
        # ownership is pinned directly by the Popen handle — no netstat, no
        # adoption protocol, no possibility of killing a stranger on the port.
        _VISION_SERVER_PID = proc.pid
        # Wait for the server to become ready. The probe hits the SAME url the
        # health check uses — `base_url` may be empty (the parameter defaults
        # to "") in which case f"{base_url}/..." is not even a valid URL, so
        # every iteration raised and the loop always fell through to the
        # timeout warning.
        #
        # 2026-08-12: a fixed 30s window reported "not ready" for a server that
        # was still loading a larger model, so the first vision call failed and
        # the UI showed vision as down. Scale the window by the model's MEASURED
        # footprint (REQ-10 AC7 — no hardcoded model-name substring to key off
        # of; any vision model the user picked can be small or large) rather
        # than a name heuristic: ~90s above a ~1.5GB footprint, ~30s at/under it.
        ready_url = base_url or f"http://127.0.0.1:{requested_port}/v1"
        try:
            _footprint_gb = _estimate_vision_footprint_gb(model_path, mmproj_path)
        except Exception:
            _footprint_gb = 0.0
        # Readiness wait: PROGRESS-AWARE (live finding 2026-08-23 x2: BOTH the
        # old 90s two-tier cap AND a footprint-scaled 88s window expired while a
        # model was mid-load — cold disk reads dominate, not size; the 3B showed
        # "37% | ETA 2:44" at the old cutoff). The signal that a spawn deserves
        # more time is its stderr LOG GROWING. So:
        #   - no-progress window: ~2min without a growing log = hung -> give up
        #   - hard ceiling: 10min absolute (a genuinely stuck spawn cannot hold
        #     a caller longer than that)
        #   - process exit cuts the wait immediately (checked every poll)
        # 120s -> 300s (2026-08-24), and this number is now EVIDENCE-BACKED.
        #
        # ROOT CAUSE of "vision randomly unavailable", measured live: Windows
        # Defender real-time scanning. llama-server opens the 854MB F16 mmproj,
        # the AV filter driver intercepts the open and scans the whole file,
        # and llama-server blocks in the kernel with NO cpu, NO io, NO log
        # output. One captured trace: read_bytes flat at 11MB for 73 seconds
        # while MsMpEng.exe burned CPU linearly (0.2s -> 5.92s), then
        # read_bytes jumped to 826MB and the server was ready at 75.66s.
        #
        # So EVERY in-process progress signal — log growth, cpu time, io
        # counters — is legitimately flat while the load is healthy and
        # progressing. There is no signal that distinguishes "AV is scanning"
        # from "dead" without reaching outside the process. The only honest
        # policy is PATIENCE: a live process gets the benefit of the doubt up
        # to the hard deadline. Killing early is what turned a slow load into
        # a reported failure.
        #
        # The real fix is an AV exclusion for the models directory (see the
        # preflight warning emitted by _probe_av_latency). This window
        # is the safety net for machines that do not have one.
        _NO_PROGRESS_WINDOW_S = float(os.environ.get("IRIS_VISION_READY_WINDOW_S", "300"))
        _HARD_DEADLINE_S = float(os.environ.get("IRIS_VISION_READY_MAX_S", "600"))
        _hard_deadline = time.monotonic() + _HARD_DEADLINE_S
        _last_progress = time.monotonic()
        try:
            _last_log_size = os.path.getsize(log_path)
        except OSError:
            _last_log_size = 0
        # THIRD progress signal (2026-08-24 fix): the child's CPU time. See
        # _proc_cpu_seconds — llama.cpp is SILENT for the whole model+mmproj load,
        # so "log stopped growing" and "server is dead" were indistinguishable and
        # healthy loads were being killed at the 120s window. Sampled on a slow
        # cadence (CPU-time reads are a syscall per poll, and the window they feed
        # is 120s wide — 0.5s resolution buys nothing).
        _CPU_SAMPLE_EVERY_S = 5.0
        _last_cpu_sample_at = time.monotonic()
        _last_cpu_seconds = _proc_cpu_seconds(proc.pid)
        _exited_early = False
        while time.monotonic() < _hard_deadline:
            time.sleep(0.5)
            # Progress check 1 / edge case (REQ-6): the server process itself has
            # exited — stop polling immediately instead of waiting out the full
            # window for a process that is not coming back. This is checked FIRST
            # every iteration so a crash is always reported as a crash (with its
            # stderr tail) rather than as a timeout.
            if proc.poll() is not None:
                _exited_early = True
                break
            try:
                r = httpx.get(f"{ready_url}/models", timeout=1.0)
                # ANY HTTP response — including llama.cpp's 503 "still loading" —
                # proves the server's HTTP layer is ALIVE. That is the true
                # progress signal: llama.cpp binds its port BEFORE loading the
                # model, and its stderr progress bar uses \r overwrites that
                # barely grow the file (the naive size check killed healthy
                # loads mid-bar). Silence now means: no bind AND no stderr.
                _last_progress = time.monotonic()
                if r.status_code == 200:
                    _elapsed = time.monotonic() - _spawn_start
                    logger.info(
                        "[LFMVLProvider] vision_server_ready port=%s ttr_sec=%.2f "
                        "ctx=%s ngl=%s batch=%s",
                        requested_port, _elapsed, _VISION_CTX_SIZE, ngl, _VISION_BATCH_SIZE,
                    )
                    # No pid adoption step: the launcher wrapper is gone, so
                    # proc.pid IS the llama-server pid and _VISION_SERVER_PID was
                    # already set to it above.
                    vision_stderr.close()
                    _notify_lifecycle("warm", trigger=_current_trigger)  # REQ-5
                    return True
            except Exception:
                pass
            # Progress check 2: llama.cpp writes load progress to stderr. A
            # growing log means the loader is WORKING — keep waiting.
            try:
                _size = os.path.getsize(log_path)
                if _size > _last_log_size:
                    _last_log_size = _size
                    _last_progress = time.monotonic()
            except OSError:
                pass
            # Progress check 3 (2026-08-24): CPU time advancing means the loader
            # is WORKING even though it is writing nothing. This is the signal
            # that covers the silent model/mmproj load — the exact span where
            # every measured stall log truncates, and where the old two-signal
            # loop used to kill healthy work.
            _now = time.monotonic()
            if _now - _last_cpu_sample_at >= _CPU_SAMPLE_EVERY_S:
                _last_cpu_sample_at = _now
                _cpu = _proc_cpu_seconds(proc.pid)
                if _cpu is not None:
                    if _last_cpu_seconds is None or _cpu > _last_cpu_seconds:
                        _last_progress = _now
                    _last_cpu_seconds = _cpu
            if time.monotonic() - _last_progress > _NO_PROGRESS_WINDOW_S:
                break

        _elapsed = time.monotonic() - _spawn_start
        vision_stderr.close()
        if _exited_early:
            # Edge case (REQ-6): surface the server's own last stderr lines
            # instead of a generic timeout — the process exited, it did not
            # merely take too long, and the log usually names the real cause
            # (bad flag, missing file, OOM).
            _exit_code = proc.poll()
            logger.warning(
                "[LFMVLProvider] vision_server_exited_during_start port=%s "
                "exit_code=%s ttr_sec=%.2f last_stderr=\n%s",
                requested_port, _exit_code, _elapsed, _read_log_tail(log_path),
            )
        else:
            logger.warning(
                "[LFMVLProvider] vision_server_not_ready port=%s "
                "no_progress_for_sec=%.0f ttr_sec=%.2f (hard deadline %.0fs)",
                requested_port,
                time.monotonic() - _last_progress,
                _elapsed,
                _HARD_DEADLINE_S,
            )
        # Failed: clean up ONLY what this attempt spawned (REQ-2). The Popen
        # handle pins the PID — there is no port scan and no possibility of
        # killing another attempt's healthy server. Tree kill so the wrapper
        # fallback's child dies with it.
        _kill_process_tree(proc.pid)
        _VISION_SERVER_PID = None
        # NO lifecycle "error" here: a retry that is about to succeed must not
        # flash "vision failed" at the UI first. The single terminal
        # _notify_lifecycle("error") after the loop is the only one the
        # frontend sees, and it fires only once every attempt is spent.
        #
        # Wedged (not a clean exit): kill and try again if attempts remain.
        # The kill above already released this attempt's memory, so the next
        # attempt starts from the same clean state a manual respawn would.
        if _exited_early:
            break  # real error — do not burn attempts on it
    _notify_lifecycle(
        "error",
        reason="exited during start" if _exited_early else "not ready before timeout",
        trigger=_current_trigger,
    )
    return False


def screenshot_to_bytes(region: Optional[Tuple[int, int, int, int]] = None) -> bytes:
    """
    Capture screen and return as PNG bytes.
    Uses mss for cross-platform support. Latency: <5ms.

    Args:
        region: Optional (left, top, width, height) bounding box.

    Returns:
        PNG bytes of the screenshot.
    """
    import mss
    import mss.tools

    with mss.mss() as sct:
        if region:
            left, top, width, height = region
            monitor = {"left": left, "top": top, "width": width, "height": height}
        else:
            monitor = sct.monitors[1]  # Primary monitor

        sct_img = sct.grab(monitor)
        return mss.tools.to_png(sct_img.rgb, sct_img.size)


def _img_to_base64(img_bytes: bytes) -> str:
    """Convert PNG bytes to base64 string."""
    return base64.b64encode(img_bytes).decode("utf-8")


class LFMVLProvider:
    """
    Synchronous HTTP client for LFM2.5-VL vision model via llama-server.

    Design principles:
    - No state held between calls
    - Every call is independent (screenshot, query, response)
    - All methods return strings/dicts — never raise on failure
    - Uses httpx for sync HTTP requests

    Sampling (Liquid AI official recommendations):
    - temperature: 0.1   (deterministic outputs)
    - min_p: 0.15        (nucleus sampling threshold)
    - repetition_penalty: 1.05 (prevent repetition)
    """

    def __init__(self, config: Optional[LFMVLConfig] = None):
        self.config = config or LFMVLConfig()

    def _call(self, img_bytes: bytes, prompt: str, max_tokens: Optional[int] = None) -> str:
        """
        Send image + prompt to llama-server /v1/chat/completions.
        Auto-starts the vision server if not already running.
        Returns model response text, or error string on any failure.
        """
        # REQ-13 AC2 (T4): while a vision LEASE is active, skip the per-call
        # health probe — the lease is the liveness contract and the probe was
        # pure serial latency (up to its 2s timeout) before every inference.
        # If the server died mid-lease anyway, the POST below fails with a
        # connect error and we force ONE single-flight respawn + retry, so
        # nothing silently degrades (REQ-13 AC4).
        if not has_active_lease():
            _ensure_vision_server_running(self.config.base_url)
        # Record use so the idle watchdog resets its auto-stop timer
        _touch_vision_use()

        try:
            import httpx

            img_b64 = _img_to_base64(img_bytes)
            tokens = max_tokens or self.config.image_max_tokens

            payload = {
                # REQ-10 AC7: this string is purely informational for the
                # OpenAI-compat request shape — llama-server serves whatever
                # -m it was launched with regardless of what is sent here,
                # so it deliberately names no specific model id.
                "model": "vision-model",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{img_b64}"}
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ],
                "temperature": self.config.temperature,
                "min_p": self.config.min_p,
                "repetition_penalty": self.config.repetition_penalty,
                "max_tokens": tokens,
            }

            try:
                response = httpx.post(
                    f"{self.config.base_url}/chat/completions",
                    json=payload,
                    timeout=self.config.timeout
                )
                response.raise_for_status()
            except Exception as exc:
                # Connect-class failure under an active lease = the server died
                # mid-lease. Force the ensure (bypassing the lease skip — it
                # coalesces through the single-flight lock) and retry ONCE.
                if has_active_lease() and "connect" in str(exc).lower():
                    logger.warning(
                        "[LFMVLProvider] vision server unreachable under active "
                        "lease — forcing respawn: %s", exc,
                    )
                    _ensure_vision_server_running(self.config.base_url)
                    response = httpx.post(
                        f"{self.config.base_url}/chat/completions",
                        json=payload,
                        timeout=self.config.timeout
                    )
                    response.raise_for_status()
                else:
                    raise
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()

        except Exception as e:
            logger.warning(f"[LFMVLProvider] Call failed: {e}")
            return f"Vision unavailable: {e}"

    def health_check(self) -> bool:
        """
        Check if llama-server is reachable and has a vision model loaded.
        Returns True if server responds, False otherwise.
        """
        try:
            import httpx
            response = httpx.get(
                f"{self.config.base_url}/models",
                timeout=5.0
            )
            return response.status_code == 200
        except Exception:
            return False

    def start(self) -> bool:
        """
        Ensure the LFM2.5-VL llama-server subprocess is running on the vision port.

        This is the explicit 'enable vision' entry point.  The previous design only
        started the server lazily inside _call() on the first vision query, which
        meant toggling 'vision enabled' in the UI did nothing — the health check
        came back False, the gateway reported 'not_started', and GUI automation
        that gate-checked availability bailed out before any vision call could
        trigger the lazy auto-start.  Now the enable handler calls start()
        directly so the server is up before anything tries to use it.

        Returns True if the server is reachable after this call (already running
        or successfully spawned); False if the model/binary is missing or the
        server failed to come up in 30 s.
        """
        ok = _ensure_vision_server_running(self.config.base_url)
        if ok:
            _touch_vision_use()
        return ok

    def disable(self) -> None:
        """
        Stop the LFM2.5-VL llama-server subprocess if IRIS spawned it.

        Only terminates a server we started ourselves (tracked by PID).  If the
        user is running their own llama-server on the vision port, we leave it
        alone — health checks will still succeed, but IRIS will not kill it.
        Safe to call when nothing is running (no-op).  Also cancels any pending
        idle auto-stop timer.
        """
        global _idle_timer
        with _idle_lock:
            if _idle_timer is not None:
                _idle_timer.cancel()
                _idle_timer = None
        _stop_owned_vision_server()

    def analyze_screen(self, img_bytes: bytes, question: str = "") -> str:
        """
        Analyze screen content and answer a question about it.

        Args:
            img_bytes: PNG screenshot bytes
            question: Optional specific question about the screen

        Returns:
            Text description of screen content.
        """
        prompt = question if question else "Describe what is visible on this screen in detail."
        return self._call(img_bytes, prompt, max_tokens=256)

    def find_ui_element(self, img_bytes: bytes, description: str) -> dict:
        """
        Locate a UI element on screen by description.

        Args:
            img_bytes: PNG screenshot bytes
            description: Natural language description of the element

        Returns:
            {"found": bool, "location_hint": str}
        """
        prompt = (
            f'Find the UI element described as: "{description}". '
            "Describe where it is located on screen (top-left, center, bottom-right, etc.) "
            "and whether it is visible. Keep response brief."
        )
        response = self._call(img_bytes, prompt, max_tokens=64)

        if response.startswith("Vision unavailable"):
            return {"found": False, "location_hint": response}

        found = not any(
            word in response.lower()
            for word in ["not found", "not visible", "cannot find", "don't see", "no such"]
        )
        return {"found": found, "location_hint": response}

    def read_text(self, img_bytes: bytes, region: Optional[Tuple] = None) -> str:
        """
        Extract text from screen or a specific region.

        Args:
            img_bytes: PNG screenshot bytes
            region: Optional region description hint

        Returns:
            Extracted text string.
        """
        hint = f" Focus on: {region}." if region else ""
        prompt = f"Extract all readable text from this screenshot.{hint} Return only the text content, no commentary."
        return self._call(img_bytes, prompt, max_tokens=256)

    def suggest_action(self, img_bytes: bytes, goal: str) -> dict:
        """
        Suggest the next UI action to achieve a goal.

        Args:
            img_bytes: PNG screenshot bytes
            goal: What the user wants to accomplish

        Returns:
            {"action": str, "target": str, "reasoning": str}
        """
        prompt = (
            f'Goal: "{goal}". '
            "Looking at the current screen, what is the single best next action? "
            "Reply with: ACTION: [click/type/scroll/wait], TARGET: [what to interact with], REASON: [brief reason]."
        )
        response = self._call(img_bytes, prompt, max_tokens=128)

        if response.startswith("Vision unavailable"):
            return {"action": "error", "target": "", "reasoning": response}

        # Parse structured response
        result = {"action": "unknown", "target": "", "reasoning": response}
        for line in response.splitlines():
            line_lower = line.lower()
            if line_lower.startswith("action:"):
                result["action"] = line.split(":", 1)[1].strip().lower()
            elif line_lower.startswith("target:"):
                result["target"] = line.split(":", 1)[1].strip()
            elif line_lower.startswith("reason:"):
                result["reasoning"] = line.split(":", 1)[1].strip()

        return result

    def describe_live_frame(self, img_bytes: bytes) -> str:
        """
        Fast single-sentence description for streaming/monitoring.
        Uses minimum tokens for speed.

        Args:
            img_bytes: PNG screenshot bytes

        Returns:
            Single sentence describing the screen.
        """
        prompt = "In one sentence, what is happening on this screen right now?"
        return self._call(img_bytes, prompt, max_tokens=64)

