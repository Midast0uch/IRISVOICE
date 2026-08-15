"""
LFM2.5-VL Vision Provider
HTTP client wrapping llama-server on the configured vision port (default 18181).
Provides synchronous screen analysis, UI element detection, OCR, and action suggestion.

Auto-start: If llama-server is not running on the vision port, the provider attempts to
spawn it using the LFM2.5-VL-3B GGUF model found in the models dir.
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


def _find_vision_model() -> Optional[Tuple[str, str]]:
    """
    Find the LFM2.5-VL-3B GGUF model + mmproj files (upgraded from the 450M).

    2026-08-12: the vision model was upgraded from LFM2.5-VL-450M to the newer
    LFM2.5-VL-3B (same repo family: LiquidAI/LFM2.5-VL-3B-GGUF). The 3B
    directory is searched FIRST so the upgrade takes effect automatically when
    present; the 450M remains as a fallback for setups that never downloaded
    the 3B. Searches the same directory LocalModelManager uses for brain
    models (IRIS_MODELS_DIR env var → ~/.lmstudio/models → project root
    models/gguf). Returns (model_path, mmproj_path) or None if not found.
    """
    # Resolve project root from this file's location: backend/tools/ -> project root
    project_root = Path(__file__).resolve().parents[2]

    # Import LocalModelManager to reuse its MODELS_DIR resolution
    try:
        from backend.agent.local_model_manager import LocalModelManager
        lm_models_dir = LocalModelManager.MODELS_DIR
    except Exception:
        lm_models_dir = None

    search_dirs = [
        # Upgraded vision model (2026-08-12): LFM2.5-VL-3B, same repo family
        # as the 450M it replaces. Prefer it when present.
        lm_models_dir / "LFM2.5-VL-3B" if lm_models_dir else None,
        lm_models_dir / "LiquidAI" / "LFM2.5-VL-3B-GGUF" if lm_models_dir else None,
        # Legacy 450M — fallback only (kept for setups without the 3B).
        lm_models_dir / "LFM2.5-VL-450M" if lm_models_dir else None,
        lm_models_dir / "LiquidAI" / "LFM2.5-VL-450M-GGUF" if lm_models_dir else None,
        # Fallback paths
        project_root / "models" / "LFM2.5-VL-3B",
        project_root / "models" / "LFM2.5-VL-450M",
        Path.home() / "models" / "LFM2.5-VL-3B",
        Path.home() / "models" / "LFM2.5-VL-450M",
        Path.home() / ".iris" / "models" / "LFM2.5-VL-3B",
        Path.home() / ".iris" / "models" / "LFM2.5-VL-450M",
    ]

    for d in search_dirs:
        if d is None or not d.exists():
            continue
        ggufs = list(d.glob("*.gguf"))
        mmproj = list(d.glob("mmproj*.gguf"))
        if ggufs and mmproj:
            return str(ggufs[0]), str(mmproj[0])

    # Last resort: recursive scan of the shared models dir for any dir
    # containing both a .gguf and mmproj*.gguf (catches arbitrary nesting).
    # Prefer 3B over 450M when both are nested.
    if lm_models_dir and lm_models_dir.exists():
        found: list[Tuple[str, str]] = []
        for d in lm_models_dir.rglob("*/"):
            ggufs = list(d.glob("*.gguf"))
            mmproj = list(d.glob("mmproj*.gguf"))
            if ggufs and mmproj:
                # Verify it's actually the vision model by checking the stem
                if any("LFM2.5-VL" in g.name for g in ggufs):
                    found.append((str(ggufs[0]), str(mmproj[0])))
        if found:
            found.sort(key=lambda pair: "3B" in pair[0], reverse=True)
            return found[0]

    return None


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

    The vision model runs on the GPU when VRAM allows (2026-08-12: upgraded
    to LFM2.5-VL-3B, previously the 450M ran un-offloaded). The spawn command
    used to pass NO -ngl flag, so llama.cpp defaulted to 0 GPU layers = pure
    CPU — confirmed live: VRAM flat at 4839 MiB before/after the 3B loaded.

    This is deliberate about headroom: the brain/tool models are normally
    cloud API providers (Cerebras etc.), but a USER may load a local model
    for brain or tool execution at any time. Vision must therefore never
    grab so much VRAM that a subsequent local-model load OOMs. We:

      1. Read CURRENT free VRAM via LocalModelManager.get_hardware_info()
         (torch-based, cached 60s — the same source the local-model loader
         budgets against, so both agree on what is "free").
      2. Estimate the vision model's weight footprint (weights + mmproj +
         KV cache) using the SAME estimator the local-model path uses.
      3. Offload ALL layers only if the model fits with a reserved margin
         (see _VISION_VRAM_RESERVE_GB); otherwise offload none (CPU) rather
         than gamble a partial offload that could OOM the machine.

    Returning 0 = CPU (safe fallback). Returning a large number = full
    GPU offload. llama.cpp accepts -ngl N with N > layer count meaning "all".
    """
    if not model_path or not mmproj_path:
        return 0
    try:
        # Free VRAM MUST come from nvidia-smi (sees every process), not torch:
        # torch.cuda.memory_allocated only counts torch's own tensors, so it
        # reports ~8GB "free" on a card where the desktop + any llama-cpp-
        # loaded local model already hold ~5GB (verified 2026-08-12: torch said
        # vram_free 8.0 while nvidia-smi showed 4.8GB used). Budgeting against
        # the torch figure let vision think a 2.6GB model has the whole card.
        import shutil as _shutil
        import subprocess as _sp

        free_gb = 0.0
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
                    free_gb = _free_mib / 1024.0
            except Exception:
                free_gb = 0.0
        if free_gb <= 0:
            # Fallback: torch figure (may over-report; still better than CPU
            # when nvidia-smi is unavailable).
            from backend.agent.local_model_manager import get_local_model_manager

            hw = get_local_model_manager().get_hardware_info()
            if not hw.get("cuda_available"):
                return 0  # no GPU — CPU
            free_gb = float(hw.get("vram_free_gb", 0.0))
        if free_gb <= 0:
            return 0

        # Weight footprint: model + mmproj + KV cache (n_ctx 4096 as spawned).
        # Q4_K_M ~1.6GB + F16 mmproj ~0.8GB + KV ~0.2GB ≈ 2.6GB for the 3B.
        import os as _os

        model_gb = (_os.path.getsize(model_path) or 0) / (1024 ** 3)
        mmproj_gb = (_os.path.getsize(mmproj_path) or 0) / (1024 ** 3)
        _kv_overhead_gb = 0.3  # 4096 ctx KV + CUDA compute buffers (estimate)
        needed_gb = model_gb + mmproj_gb + _kv_overhead_gb

        if needed_gb <= free_gb - _VISION_VRAM_RESERVE_GB:
            logger.info(
                "[LFMVLProvider] GPU offload: vision needs %.2fGB, %.2fGB free "
                "(reserving %.2fGB for a local brain/tool model) -> full offload",
                needed_gb, free_gb, _VISION_VRAM_RESERVE_GB,
            )
            return 999  # "all layers" — llama.cpp clamps to the model's count
        logger.warning(
            "[LFMVLProvider] GPU offload SKIPPED: vision needs %.2fGB, %.2fGB "
            "free (%.2fGB reserved) -> running on CPU to avoid OOM",
            needed_gb, free_gb, _VISION_VRAM_RESERVE_GB,
        )
        return 0
    except Exception as _exc:  # noqa: BLE001 — VRAM probe must never block vision
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

    model_files = _find_vision_model()
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
    # before/after the 3B loaded). 999 = "all layers".
    ngl = _compute_vision_gpu_layers(model_path, mmproj_path)
    cmd = [
        binary,
        "-m", model_path,
        "--mmproj", mmproj_path,
        "--port", str(requested_port),
        "--host", "127.0.0.1",
        "-c", "4096",
        "-np", "1",
        "-n", "512",
        "-ngl", str(ngl),
        "--no-warmup",  # Prevents crash with upstream llama.cpp on WSL
    ]

    # If using the upstream binary, it needs its shared libraries in LD_LIBRARY_PATH
    env = os.environ.copy()
    binary_path = Path(binary)
    if "llama.cpp-upstream" in str(binary_path):
        env["LD_LIBRARY_PATH"] = str(binary_path.parent) + ":" + env.get("LD_LIBRARY_PATH", "")

    logger.info(f"[LFMVLProvider] Spawning vision server: {' '.join(cmd)}")
    try:
        # Capture llama-server stderr to a file so future load failures are
        # diagnosable (previously DEVNULL hid failures entirely — the 2026-08-12
        # -fit hang produced zero evidence in the backend log).
        log_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
        )
        os.makedirs(log_dir, exist_ok=True)
        vision_stderr = open(
            os.path.join(log_dir, f"vision-llama-server-{time.strftime('%Y%m%d-%H%M%S')}.log"),
            "wb",
        )

        # Windows CUDA parent quirk (verified live 2026-08-12): a llama-server
        # child spawned DIRECTLY from a parent that has loaded torch/transformers
        # with CUDA (the backend's LFM encoder does this on first use) hangs
        # forever inside llama.cpp's `-fit` device probe — "fitting params to
        # device memory" — and never serves /v1/models (503 for 6+ min at ~640MB
        # RSS). Spawning through a tiny launcher python (imports only
        # subprocess/sys, so NO torch/CUDA state) gives llama-server a clean
        # parent: load completes in ~25-40s. Direct spawn = hang, launcher spawn
        # = READY (reproduced back-to-back on LFM2.5-VL-3B Q4_K_M, -ngl 999).
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
    # 2026-08-12: the model was upgraded from LFM2.5-VL-450M (~450M params,
    # loads in seconds) to LFM2.5-VL-3B (Q4_K_M ~2GB + F16 mmproj, loads in
    # well over 30s). The old fixed 30s window reported "not ready" for a
    # server that was still loading, so the first vision call failed and
    # the UI showed vision as down. Scale the window by model size: ~90s
    # for the 3B, ~30s for the 450M.
    ready_url = base_url or f"http://localhost:{requested_port}/v1"
    _big_model = "3B" in model_path
    _ready_attempts = 180 if _big_model else 60  # 0.5s each → 90s / 30s
    for _ in range(_ready_attempts):
        time.sleep(0.5)
        try:
            r = httpx.get(f"{ready_url}/models", timeout=1.0)
            if r.status_code == 200:
                logger.info("[LFMVLProvider] Vision server ready.")
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
    logger.warning(
        "[LFMVLProvider] Vision server did not become ready within %.0fs.",
        _ready_attempts * 0.5,
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
    vision_stderr.close()
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
                # 2026-08-12: upgraded from lfm2.5-vl (450M) to the newer
                # LFM2.5-VL-3B — same model family, same repo source
                # (LiquidAI/LFM2.5-VL-3B-GGUF). The string is informational for
                # llama-server (which serves whatever -m it was launched with);
                # kept in sync with _find_vision_model's 3B preference.
                "model": "lfm2.5-vl-3b",
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
