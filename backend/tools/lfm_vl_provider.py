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


# ── Idle lifecycle ────────────────────────────────────────────────────────────
# When vision is enabled, the llama-server is spawned eagerly so it is ready
# immediately. To avoid holding memory when vision is not actively used, the
# server auto-stops after IDLE_TIMEOUT seconds of no vision activity, and lazily
# restarts on the next vision call (small model → fast start/stop).
_IDLE_TIMEOUT: float = float(os.environ.get("IRIS_VISION_IDLE_TIMEOUT", "120"))

_last_vision_use: float = 0.0
_idle_timer: Optional[threading.Timer] = None
_idle_lock = threading.Lock()
_vision_idle_callback = None  # set by iris_gateway to broadcast idle-stop status


def set_vision_idle_callback(cb) -> None:
    """Register a callback invoked when the idle watchdog stops the server."""
    global _vision_idle_callback
    _vision_idle_callback = cb


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
            _idle_timer = threading.Timer(_IDLE_TIMEOUT, _idle_stop)
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


def _stop_owned_vision_server() -> None:
    """Kill the llama-server subprocess IRIS spawned (tracked PID only)."""
    global _VISION_SERVER_PID
    if _VISION_SERVER_PID is None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(_VISION_SERVER_PID)],
                capture_output=True,
            )
        else:
            os.kill(_VISION_SERVER_PID, signal.SIGTERM)
        logger.info(f"[LFMVLProvider] Stopped vision server PID {_VISION_SERVER_PID}")
    except Exception as e:
        logger.warning(f"[LFMVLProvider] Failed to stop vision server: {e}")
    finally:
        _VISION_SERVER_PID = None


def _resolve_listener_pid(port: int) -> Optional[int]:
    """Return the PID currently LISTENING on ``port``, or None.

    Used after a spawn to adopt the REAL llama-server PID (the spawn goes
    through a launcher, whose pid is not the server's), and to clean up a
    server that failed to become ready.
    """
    try:
        _out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        for _line in _out.splitlines():
            if f":{port}" in _line and "LISTENING" in _line:
                _parts = _line.split()
                if _parts:
                    return int(_parts[-1])
    except Exception:
        pass
    return None


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
        return  # REQ-9: active lease -> defer; _touch_vision_use reschedules
    _stop_owned_vision_server()
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
    base_url: str = f"http://localhost:{_VISION_PORT}/v1"
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


def _find_vision_model() -> Optional[Tuple[str, str]]:
    """
    Size-select the VL fallback model from a widest-first ladder walked
    against REAL free VRAM (REQ-3 AC1), taking the first candidate whose
    weights + projector + KV fit — never an unconditional size preference.

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

    free_gb, vram_readable, _cuda_available = _read_free_vram_gb()

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


def _compute_vision_gpu_layers(model_path: str, mmproj_path: str) -> int:
    """Decide how many GPU layers the vision llama-server should offload.

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
        free_gb, vram_readable, cuda_available = _read_free_vram_gb()

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
    """
    Check if llama-server is running. If not, try to spawn it.
    Returns True if server is reachable (either already running or successfully started).
    """
    requested_port = _VISION_PORT

    try:
        import httpx
        # base_url ALREADY ENDS IN /v1 (LFMVLConfig.base_url is
        # "http://localhost:<port>/v1"), so the endpoint is "/models" — NOT
        # "/v1/models". Appending /v1 again produced .../v1/v1/models, which
        # 404s forever: the health check therefore reported "not running" for a
        # server that was up, then the readiness loop below made the SAME
        # mistake and timed out after 30s. Live proof 2026-08-10:
        # GET /v1/models -> 200, GET /v1/v1/models -> 404, while the server
        # logged "server is listening on http://127.0.0.1:18181" in under 2s.
        # `_call()` at the bottom of this file always got this right
        # (f"{base_url}/models") — only these two probes were wrong.
        check_url = base_url or f"http://localhost:{requested_port}/v1"
        r = httpx.get(f"{check_url}/models", timeout=2.0)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    # Not running — try to auto-start
    logger.info(f"[LFMVLProvider] Vision server not running on port {requested_port}. Attempting auto-start...")

    # REQ-3 AC4/AC6: _find_vision_model FAILS LOUDLY (raises + emits
    # VISION_UNAVAILABLE) when no VL model exists or none fits free VRAM,
    # rather than returning None. Caught here so the failure is a clean,
    # reported "vision unavailable" rather than an exception escaping into
    # the agent loop — the caller of start()/_call() only ever sees False.
    try:
        model_files = _find_vision_model()
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
        ngl = _compute_vision_gpu_layers(model_path, mmproj_path)
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
        env["LD_LIBRARY_PATH"] = str(binary_path.parent) + ":" + env.get("LD_LIBRARY_PATH", "")

    logger.info(f"[LFMVLProvider] Spawning vision server: {' '.join(cmd)}")
    _spawn_start = time.monotonic()  # REQ-6 AC3: time-to-ready measurement
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

        # Windows CUDA parent quirk (verified live 2026-08-12): a llama-server
        # child spawned DIRECTLY from a parent that has loaded torch/transformers
        # with CUDA (the backend's LFM encoder does this on first use) hangs
        # forever inside llama.cpp's `-fit` device probe — "fitting params to
        # device memory" — and never serves /v1/models (503 for 6+ min at ~640MB
        # RSS). Spawning through a tiny launcher python (imports only
        # subprocess/sys, so NO torch/CUDA state) gives llama-server a clean
        # parent: load completes in ~25-40s. Direct spawn = hang, launcher spawn
        # = READY (reproduced back-to-back with a vision model at -ngl 999).
        _LAUNCHER = "import subprocess,sys; sys.exit(subprocess.run(sys.argv[1:]).returncode)"
        proc = subprocess.Popen(
            [sys.executable, "-c", _LAUNCHER] + cmd,
            stdout=subprocess.DEVNULL,
            stderr=vision_stderr,
            start_new_session=True,  # Detach from parent
            env=env,
        )
    except Exception as e:
        logger.warning(f"[LFMVLProvider] Failed to spawn vision server: {e}")
        return False

    global _VISION_SERVER_PID
    _VISION_SERVER_PID = proc.pid  # launcher pid; refined to the real server pid below
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
    ready_url = base_url or f"http://localhost:{requested_port}/v1"
    try:
        _footprint_gb = _estimate_vision_footprint_gb(model_path, mmproj_path)
    except Exception:
        _footprint_gb = 0.0
    _ready_attempts = 180 if _footprint_gb >= 1.5 else 60  # 0.5s each → 90s / 30s
    _exited_early = False
    for _ in range(_ready_attempts):
        time.sleep(0.5)
        # Edge case (REQ-6): if the launcher process has already exited, the
        # llama-server it wrapped exited too (the launcher runs it
        # synchronously via subprocess.run and only exits after it returns) —
        # stop polling immediately instead of waiting out the full timeout
        # window for a process that is not coming back.
        if proc.poll() is not None:
            _exited_early = True
            break
        try:
            r = httpx.get(f"{ready_url}/models", timeout=1.0)
            if r.status_code == 200:
                _elapsed = time.monotonic() - _spawn_start
                logger.info(
                    "[LFMVLProvider] vision_server_ready port=%s ttr_sec=%.2f "
                    "ctx=%s ngl=%s batch=%s",
                    requested_port, _elapsed, _VISION_CTX_SIZE, ngl, _VISION_BATCH_SIZE,
                )
                # Adopt the REAL llama-server pid (the launcher pid is not the
                # server's), so _stop_owned_vision_server kills the server, not
                # the launcher wrapper.
                _real = _resolve_listener_pid(requested_port)
                if _real is not None:
                    _VISION_SERVER_PID = _real
                vision_stderr.close()
                return True
        except Exception:
            pass

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
            "[LFMVLProvider] vision_server_not_ready port=%s timeout_sec=%.0f "
            "ttr_sec=%.2f",
            requested_port, _ready_attempts * 0.5, _elapsed,
        )
    # Failed: clean up what we spawned. Nothing was listening on the port
    # before we spawned (the health check above only auto-starts when the
    # server is down), so any listener on the port now is OURS — kill it
    # precisely, plus the launcher tree, then clear the tracked pid.
    _stray = _resolve_listener_pid(requested_port)
    if _stray is not None:
        _kill_pid(_stray)
    _kill_pid(proc.pid)
    _VISION_SERVER_PID = None
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
        # Ensure server is running before first call
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

            response = httpx.post(
                f"{self.config.base_url}/chat/completions",
                json=payload,
                timeout=self.config.timeout
            )
            response.raise_for_status()
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
