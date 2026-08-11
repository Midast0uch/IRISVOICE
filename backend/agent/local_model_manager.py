"""
LocalModelManager — GGUF model lifecycle manager for IRISVOICE v.3.

Two load paths coexist, selected by the IRIS_INPROCESS_LLAMA env var
(default ``"1"`` — in-process):

* **In-process (preferred)** — ``from llama_cpp import Llama`` runs in the
  backend process. An ``InProcessOpenAIAdapter`` duck-types the openai
  Python client's ``.chat.completions.create(**kwargs)`` surface so the
  agent kernel continues to call the same API it used against the
  subprocess server. This is the path that actually works at the
  measured 50.8 tok/s (RTX 3070, Qwen3.5-9B-Q3_K_S).

* **Legacy subprocess** — spawns ``python -m llama_cpp.server`` on port
  8082 and points the kernel at it via OpenAI HTTP. Kept alive behind
  ``IRIS_INPROCESS_LLAMA=0`` as a rollback lever while the in-process
  path is verified end-to-end; scheduled for deletion after V1–V3 pass.

Neither path auto-loads at startup — both only activate when the user
picks a model from the ModelsScreen.
"""

import asyncio
import atexit
import gc
import inspect
import io
import json
import logging
import os
import signal
import struct
import subprocess
import sys
import threading
import time
from multiprocessing import cpu_count
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Dict, Iterator, List, Optional
from dataclasses import dataclass

import httpx

# ── Hardware detection (import-guarded, matches audio/model_manager.py pattern) ──
try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# NOTE: torch is NOT imported at module level — it costs ~360 MB.
# Imported lazily inside get_hardware_info() on first use.
TORCH_AVAILABLE = (
    False  # legacy flag — kept for backward compat, never set True at import
)

# ── HuggingFace Hub (import-guarded) ──
HF_HUB_AVAILABLE = False
try:
    from huggingface_hub import hf_hub_download

    HF_HUB_AVAILABLE = True
except ImportError:
    pass

logger = logging.getLogger(__name__)

IRISVOICE_ROOT = Path(__file__).parent.parent.parent

# ── Quantization bits-per-weight table (for VRAM estimation) ──
QUANT_BPW: Dict[str, float] = {
    "Q2_K": 2.56,
    "Q3_K_S": 3.0,
    "Q3_K_M": 3.35,
    "Q3_K_L": 3.6,
    "Q4_0": 4.5,
    "Q4_K_S": 4.37,
    "Q4_K_M": 4.85,
    "Q4_K": 4.85,
    "Q5_0": 5.5,
    "Q5_K_S": 5.54,
    "Q5_K_M": 5.69,
    "Q5_K": 5.69,
    "Q6_K": 6.56,
    "Q8_0": 8.5,
    "F16": 16.0,
    "F32": 32.0,
    "BF16": 16.0,
}

# ── Hardware profile definitions ──
PROFILES: Dict[str, Dict[str, Any]] = {
    # CPU-only fallback — zero VRAM, minimal RAM footprint
    "eco": {
        "n_gpu_layers": 0,
        "n_ctx": 2048,
        "flash_attn": False,
        "cache_type_k": "f16",
        "cache_type_v": "f16",
        "n_batch": 512,
        "offload_kv_cache": False,
        "unified_kv_cache": False,
        "keep_model_in_memory": False,
        "use_mmap": True,
    },
    # VERIFIED: 45+ tok/s on RTX 3070 8GB with Qwen3.5-9B-Q3_K_S and Q4_K_M.
    # n_batch=2048 maximises prompt processing (prefill) speed.
    # q8_0 KV compression keeps VRAM overhead low at 32k context.
    # This is the IRIS standard for iris_local inference.
    "balanced": {
        "n_gpu_layers": -1,  # all layers on GPU — mandatory for 25+ tok/s
        "n_ctx": 32768,  # 32k context window
        "flash_attn": True,  # required: saves VRAM + faster attention
        "cache_type_k": "q8_0",  # compressed KV key cache
        "cache_type_v": "q8_0",  # compressed KV value cache
        "n_batch": 2048,  # max physical batch — fast prompt processing
        "offload_kv_cache": True,
        "unified_kv_cache": True,
        "keep_model_in_memory": True,
        "use_mmap": True,
    },
    # MTP-optimized profile for models with draft-mtp speculative decoding.
    # Uses compiled llama-server subprocess (required for self-MTP).
    "balanced_mtp": {
        "n_gpu_layers": -1,
        "n_ctx": 32768,
        "flash_attn": True,
        "cache_type_k": "q8_0",
        "cache_type_v": "q8_0",
        "n_batch": 2048,
        "offload_kv_cache": True,
        "unified_kv_cache": True,
        "keep_model_in_memory": True,
        "use_mmap": True,
        "mtp_n_max": 3,  # --spec-draft-n-max (1-6)
        "mtp_p_min": 0.75,  # --spec-draft-p-min (optional)
        "force_subprocess": True,  # MTP requires compiled llama-server
    },
    # High-throughput: same as balanced but context reduced for minimum first-token latency.
    # Use for fast iterative coding / tool-calling tasks.
    "performance": {
        "n_gpu_layers": -1,
        "n_ctx": 16384,
        "flash_attn": True,
        "cache_type_k": "q8_0",
        "cache_type_v": "q8_0",
        "n_batch": 2048,
        "offload_kv_cache": True,
        "unified_kv_cache": True,
        "keep_model_in_memory": True,
        "use_mmap": True,
    },
    # Voice latency: 8k context, smaller KV footprint = faster first-token for voice.
    "voice_first": {
        "n_gpu_layers": -1,
        "n_ctx": 8192,
        "flash_attn": True,
        "cache_type_k": "q8_0",
        "cache_type_v": "q8_0",
        "n_batch": 2048,
        "offload_kv_cache": True,
        "unified_kv_cache": True,
        "keep_model_in_memory": True,
        "use_mmap": True,
    },
    # Long-context: 100k window with Q4 KV compression to fit 8 GB VRAM.
    # Verified on RTX 3070 8GB with Qwen3.5-9B-Q3_K_S (4.32 GB weights +
    # ~1.8 GB Q4 KV at 100k tokens = 6.1 GB total).
    # Use for document analysis, large codebase queries.
    "research": {
        "n_gpu_layers": -1,
        "n_ctx": 102400,  # ~100k context
        "flash_attn": True,  # mandatory at this context length
        "cache_type_k": "q4_0",  # Q4 KV cache — halves VRAM vs q8_0 at long ctx
        "cache_type_v": "q4_0",
        "n_batch": 2048,
        "offload_kv_cache": True,
        "unified_kv_cache": True,
        "keep_model_in_memory": True,
        "use_mmap": True,
    },
    # RotorQuant research profile — requires the scrya-com/rotorquant fork
    # (johndpope/llama-cpp-turboquant, feature/planarquant-kv-cache branch).
    # PlanarQuant / IsoQuant compress KV cache 5–10× vs q8_0, so a 131k ctx
    # window fits where q4_0 at 100k currently does. If the fork is not
    # installed, the profile selector falls back to `performance` with a
    # warning (see _rotorquant_available detection in __init__).
    "research_rotorquant": {
        "n_gpu_layers": -1,
        "n_ctx": 131072,  # 128k — unlocked by planar3 compression
        "flash_attn": True,
        "cache_type_k": "planar3",  # RotorQuant key: 5–10× KV compression
        "cache_type_v": "planar3",
        "n_batch": 2048,
        "offload_kv_cache": True,
        "unified_kv_cache": True,
        "keep_model_in_memory": True,
        "use_mmap": True,
        "requires_fork": "llama-cpp-turboquant",
    },
}

# ── Phase 3: Device policy constants ──────────────────────────────────────
# TARGET_TPS — minimum acceptable tokens/sec for chat models. If measured
# throughput falls below this, the ConfigDeriver shrinks n_ctx (and then
# n_batch) to stay within VRAM. Env-overridable for tuning.
TARGET_TPS = float(os.environ.get("IRIS_TARGET_TPS", "25"))
# MIN_CTX — floor for context window shrinking. Never go below 4096.
MIN_CTX = 4096
# MAX_CTX — ceiling for context window expansion (default 32k, the
# largest common GGUF training context).
MAX_CTX = 32768
# SCAN_MAX_DEPTH — max directory depth for model scanning. Bounds the
# symlink-following walk so a circular symlink cannot loop forever (REQ-6).
SCAN_MAX_DEPTH = 8
# TPS_DEADBAND — fraction of TARGET_TPS within which no correction is written.
# A measurement between TARGET_TPS * (1 - TPS_DEADBAND) and TARGET_TPS * (1 + TPS_DEADBAND)
# is "close enough"; we neither shrink nor grow the cached context. This prevents
# thrashing the cache on noise around the target (REQ-4 AC5).
TPS_DEADBAND = 0.15

# ── DevicePolicy: the single source of truth for device/ladder/VRAM/target ──
# resolve_device_policy() is the ONLY function that decides:
#   - which device (gpu/cpu) a model loads on
#   - the degradation ladder (which knobs to turn when VRAM is tight)
#   - whether the model counts against the GPU VRAM budget
#   - the throughput target (None for non-chat purposes)
# All callers MUST go through this function — no if-guards elsewhere.

@dataclass(frozen=True)
class DevicePolicy:
    """Immutable decision about how a model should be loaded and run.

    Attributes:
        device: "gpu" or "cpu"
        ladder: Ordered tuple of degradation steps. For GPU chat models:
                ("ctx", "batch") — shrink context first, then batch.
                For CPU models: () — no degradation ladder.
        counts_against_vram: Whether this model's VRAM usage counts
                             toward the GPU budget. CPU models: False.
        throughput_target: Minimum acceptable tok/s. None for CPU
                          (embedding/rerank) — no throughput requirement.
    """
    device: str
    ladder: tuple[str, ...]
    counts_against_vram: bool
    throughput_target: Optional[float]


@dataclass
class CachedConfig:
    """A persisted, known-good config for a specific model + hardware combo.

    REQ-5: corrections from record_tps land here, not on the running model.
    """
    fingerprint: str          # path + size + mtime  (REQ-5 AC2)
    hw_fingerprint: str       # gpu name + total VRAM (REQ-5 AC4)
    config: Dict[str, Any]    # {n_ctx, n_gpu_layers, n_batch, ...}
    measured_tps: Optional[float] = None
    updated_at: float = 0.0


class ConfigCache:
    """Per-model config cache backed by .mcm/local_model_configs.json.

    Keyed by model path. Each entry stores a CachedConfig. On a hardware
    change (hw_fingerprint mismatch) the entry is invalidated and re-derived.
    A corrupt file is discarded and derivation falls back to fresh (REQ-5 AC5).
    """

    def __init__(self, cache_path: Optional[Path] = None) -> None:
        self.cache_path = cache_path or (IRISVOICE_ROOT / ".mcm" / "local_model_configs.json")
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if self.cache_path.exists():
                with open(self.cache_path, "r", encoding="utf-8") as fh:
                    self._data = json.load(fh)
                if not isinstance(self._data, dict):
                    raise ValueError("cache root not a dict")
        except Exception as exc:  # corrupt / unreadable → discard, derive fresh
            logger.warning(
                f"[ConfigCache] cache unreadable ({exc}); starting fresh"
            )
            self._data = {}

    @staticmethod
    def _hw_fingerprint(hw: Dict[str, Any]) -> str:
        gpu = hw.get("gpu_name") or "no-gpu"
        vram = hw.get("vram_total_gb") or 0.0
        return f"{gpu}:{vram:.1f}GB"

    @staticmethod
    def _model_fingerprint(model_path: str, model_meta: Dict[str, Any]) -> str:
        try:
            p = Path(model_path)
            st = p.stat()
            return f"{model_path}:{st.st_size}:{int(st.st_mtime)}"
        except Exception:
            # Fall back to metadata-only fingerprint if file unstat-able
            return f"{model_path}:{model_meta.get('params_b')}:{model_meta.get('quant')}"

    def get(self, model_path: str, model_meta: Dict[str, Any],
            hw: Dict[str, Any]) -> Optional[CachedConfig]:
        """Return a valid cached config, or None if missing/invalid/stale."""
        self._ensure_loaded()
        key = self._model_fingerprint(model_path, model_meta)
        entry = self._data.get(key)
        if entry is None:
            return None
        if entry.get("hw_fingerprint") != self._hw_fingerprint(hw):
            # Hardware changed since caching → invalidate (REQ-5 AC4)
            logger.info(
                f"[ConfigCache] hw fingerprint mismatch for {model_path}; re-deriving"
            )
            return None
        return CachedConfig(
            fingerprint=entry.get("fingerprint", key),
            hw_fingerprint=entry.get("hw_fingerprint", ""),
            config=entry.get("config", {}),
            measured_tps=entry.get("measured_tps"),
            updated_at=entry.get("updated_at", 0.0),
        )

    def put(self, model_path: str, model_meta: Dict[str, Any], hw: Dict[str, Any],
            config: Dict[str, Any], measured_tps: Optional[float] = None) -> None:
        """Persist a config for the model + current hardware."""
        self._ensure_loaded()
        key = self._model_fingerprint(model_path, model_meta)
        self._data[key] = {
            "fingerprint": key,
            "hw_fingerprint": self._hw_fingerprint(hw),
            "config": config,
            "measured_tps": measured_tps,
            "updated_at": time.time(),
        }
        self._save()

    # ── Machine-scoped hardware calibration (NOT per-model) ──
    # A single real throughput measurement anywhere on the machine yields an
    # effective memory bandwidth; every model derives its own base_tps from that
    # one number divided by its own parsed size/quant. Keyed by hw_fingerprint so
    # a GPU swap invalidates it automatically (see CADUCEAN_ARCHITECTURE.md §10
    # rule 1 — the "compute-and-discard" defect, 5th instance). Kept in a SEPARATE
    # file from the per-model config cache so it never pollutes model entries and
    # existing per-model cache assertions are unaffected.
    _MACHINE_BW_PREFIX = "_machine_bw:"

    def _machine_path(self) -> Path:
        base = self.cache_path or (IRISVOICE_ROOT / ".mcm" / "local_model_configs.json")
        return base.with_name("local_model_machine_bandwidth.json")

    def _ensure_loaded_machine(self) -> None:
        if getattr(self, "_machine_loaded", False):
            return
        self._machine_loaded = True
        self._machine_data: Dict[str, Any] = {}
        try:
            p = self._machine_path()
            if p.exists():
                with open(p, "r", encoding="utf-8") as fh:
                    self._machine_data = json.load(fh)
                if not isinstance(self._machine_data, dict):
                    raise ValueError("machine cache root not a dict")
        except Exception as exc:
            logger.warning(
                f"[ConfigCache] machine cache unreadable ({exc}); starting fresh"
            )
            self._machine_data = {}

    def _save_machine(self) -> None:
        try:
            p = self._machine_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(self._machine_data, fh, indent=2)
        except Exception as exc:
            logger.warning(f"[ConfigCache] failed to save machine cache: {exc}")

    def put_machine_bandwidth(self, hw: Dict[str, Any], effective_bandwidth: float) -> None:
        """Persist the machine-level effective bandwidth (GB/s) for the current HW."""
        self._ensure_loaded_machine()
        key = self._MACHINE_BW_PREFIX + self._hw_fingerprint(hw)
        self._machine_data[key] = {
            "hw_fingerprint": self._hw_fingerprint(hw),
            "effective_bandwidth": effective_bandwidth,
            "updated_at": time.time(),
        }
        self._save_machine()

    def get_machine_bandwidth(self, hw: Dict[str, Any]) -> Optional[float]:
        """Return the cached machine bandwidth (GB/s), or None if uncalibrated/stale."""
        self._ensure_loaded_machine()
        key = self._MACHINE_BW_PREFIX + self._hw_fingerprint(hw)
        entry = self._machine_data.get(key)
        if entry is None:
            return None
        if entry.get("hw_fingerprint") != self._hw_fingerprint(hw):
            return None
        bw = entry.get("effective_bandwidth")
        return float(bw) if bw is not None else None

    def _save(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
            tmp.replace(self.cache_path)
        except Exception as exc:
            logger.warning(f"[ConfigCache] failed to persist cache: {exc}")


def resolve_device_policy(
    purpose: str,
    user_override: Optional[str] = None,
) -> DevicePolicy:
    """Resolve the device policy for a given model purpose.

    This is the SINGLE source of truth for device/ladder/VRAM/target.
    D-1: One function, not four if-guards scattered across the codebase.

    Purpose → device mapping (D-2):
        chat       → GPU, ladder ("ctx","batch"), counts VRAM, target=TARGET_TPS
        embedding  → CPU, ladder (), no VRAM, no target
        rerank     → CPU, ladder (), no VRAM, no target
        tool       → GPU, ladder ("ctx","batch"), counts VRAM, target=TARGET_TPS

    user_override: If "gpu" or "cpu", flips BOTH device and
                   counts_against_vram together (D-2).
                   If None, uses the purpose-based default.

    Args:
        purpose: One of "chat", "embedding", "rerank", "tool".
        user_override: Explicit device override ("gpu" or "cpu"), or None.

    Returns:
        DevicePolicy with device, ladder, counts_against_vram, throughput_target.

    Raises:
        ValueError: If purpose is not recognized.
    """
    # Validate purpose
    valid_purposes = {"chat", "embedding", "rerank", "tool"}
    if purpose not in valid_purposes:
        raise ValueError(
            f"Unknown purpose '{purpose}'. "
            f"Valid purposes: {sorted(valid_purposes)}"
        )

    # Determine base device from purpose
    # chat and tool → GPU; embedding and rerank → CPU
    if purpose in ("chat", "tool"):
        base_device = "gpu"
        ladder = ("ctx", "batch")
        counts_vram = True
        target = TARGET_TPS
    else:  # embedding, rerank
        base_device = "cpu"
        ladder = ()
        counts_vram = False
        target = None

    # Apply user override: flips device AND counts_against_vram together
    if user_override is not None:
        override = user_override.lower()
        if override not in ("gpu", "cpu"):
            raise ValueError(
                f"Invalid user_override '{user_override}'. "
                f"Must be 'gpu' or 'cpu'."
            )
        device = override
        # When user overrides to GPU, model counts against VRAM.
        # When user overrides to CPU, model does NOT count against VRAM.
        counts_vram = (override == "gpu")
    else:
        device = base_device

    return DevicePolicy(
        device=device,
        ladder=ladder,
        counts_against_vram=counts_vram,
        throughput_target=target,
    )


_SPLIT_SUFFIX_PART = "-of-"

# ── GGML type string → llama_cpp integer constant ─────────────────────────
# Kept module-scope so _load_inprocess and _build_server_cmd share one source
# of truth. Values mirror llama_cpp.GGML_TYPE_* (verified against
# llama-cpp-python ≥ 0.3). Strings that have no llama_cpp.Llama constructor
# mapping (e.g. "planar3" / "iso3" from the RotorQuant fork) are intentionally
# excluded — they are passed through verbatim when _rotorquant_available.
_GGML_TYPE_INT: Dict[str, int] = {
    "f32": 0,
    "f16": 1,
    "bf16": 30,
    "q4_0": 2,
    "q4_1": 3,
    "q5_0": 6,
    "q5_1": 7,
    "q8_0": 8,
    "q8_1": 9,
    "q2_k": 10,
    "q3_k": 11,
    "q3_k_s": 11,
    "q3_k_m": 11,
    "q4_k": 12,
    "q4_k_s": 12,
    "q4_k_m": 12,
    "q5_k": 13,
    "q5_k_s": 13,
    "q5_k_m": 13,
    "q6_k": 14,
    "q8_k": 15,
}

# RotorQuant-only KV cache types (not understood by stock llama-cpp-python).
# When present in a profile and the fork IS installed, they are forwarded to
# Llama(cache_type_k=..., cache_type_v=...) as strings.
_ROTORQUANT_KV_TYPES = frozenset({"planar3", "iso3", "planarquant", "isoquant"})


class LocalModelManager:
    """
    Manages GGUF model loading via llama-cpp-python server mode subprocess.
    Port 8082, OpenAI-compatible API.

    Loading contract:
      - NEVER auto-loads at startup
      - Only spawns subprocess when user calls load_model()
      - Registers atexit + SIGTERM cleanup to kill subprocess on backend exit
    """

    PORT = int(os.environ.get("IRIS_LOCAL_MODEL_PORT", "8082"))
    ENDPOINT = f"http://127.0.0.1:{PORT}/v1"

    # ── Model scan directory resolution ─────────────────────────────────────
    # Priority: IRIS_MODELS_DIR env var → LM Studio default → IRIS fallback
    # NOTE: This is the class-level default. Use set_models_directory() at
    # runtime to override from config (takes priority over env var).
    _env_dir = os.environ.get("IRIS_MODELS_DIR")
    _lmstudio_dir = Path.home() / ".lmstudio" / "models"
    _iris_fallback = IRISVOICE_ROOT / "models" / "gguf"
    if _env_dir:
        MODELS_DIR = Path(_env_dir)
    elif _lmstudio_dir.exists():
        MODELS_DIR = _lmstudio_dir
    else:
        MODELS_DIR = _iris_fallback

    SETTINGS_FILE = _iris_fallback / ".iris_model_settings.json"

    # ── Runtime models directory override ──────────────────────────────────

    @property
    def effective_models_dir(self) -> Path:
        """Return the effective models directory, checking instance override first."""
        if self._models_dir_override:
            return self._models_dir_override
        return self.MODELS_DIR

    def set_models_directory(self, path_str: str) -> None:
        """Override the models scan directory at runtime (from config via APPLY)."""
        if path_str and Path(path_str).exists():
            self._models_dir_override = Path(path_str)
        else:
            self._models_dir_override = None

    def __init__(self) -> None:
        # Always ensure the IRIS fallback dir exists for downloads
        (IRISVOICE_ROOT / "models" / "gguf").mkdir(parents=True, exist_ok=True)
        # Instance-level override for models directory (from config). When set,
        # this takes priority over the class-level MODELS_DIR / env var.
        self._models_dir_override: Optional[Path] = None
        # ── Legacy subprocess state (used when IRIS_INPROCESS_LLAMA=0) ──
        self._process: Optional[subprocess.Popen] = None
        # ── In-process Llama state (used when IRIS_INPROCESS_LLAMA=1) ───
        # Held lazily; constructed on the executor in _load_inprocess.
        self._llm: Any = None  # Optional[llama_cpp.Llama]
        # Serializes concurrent inference calls into the single Llama instance.
        # llama-cpp is thread-hostile — one call at a time through this lock.
        self._inference_lock = threading.Lock()
        self._current_model_path: Optional[str] = None
        self._current_profile: str = "balanced"
        self._current_params: Dict[str, Any] = {}
        self._current_model_meta: Dict[str, Any] = {}
        self._current_purpose: str = "chat"
        self._lock = threading.Lock()
        # [10.6] Async lock — prevents concurrent load_model() calls racing
        self._load_lock: Optional[asyncio.Lock] = None
        # Metadata cache: key = "path::mtime" -> parsed GGUF metadata dict
        # Persists across calls — only re-parsed when file changes (mtime check)
        self._metadata_cache: Dict[str, Dict[str, Any]] = {}
        # Hardware info cache — invalidated on model load/unload (VRAM changes)
        self._hw_cache: Optional[Dict[str, Any]] = None
        self._hw_cache_time: float = 0.0
        # [10.7] Watchdog task — detects subprocess crash after load
        self._watchdog_task: Optional[asyncio.Task] = None
        # [10.10] TPS rolling window — last 3 measurements for gradient warning
        self._tps_window: list = []
        self._tps_slow_warned: bool = False
        # [Phase 3 / REQ-5] Per-model config cache — corrections from record_tps
        # land here, never on the running model (REQ-4 AC4).
        self._config_cache = ConfigCache()
        # MTP speculative-decoding metrics
        self._mtp_acceptance_window: list = []  # rolling acceptance rates
        self._mtp_draft_tokens_total: int = 0
        self._mtp_accepted_total: int = 0
        # ── RotorQuant fork detection ───────────────────────────────────
        # The scrya-com/rotorquant fork adds `cache_type_k` / `cache_type_v`
        # string kwargs to Llama.__init__ that accept "planar3" / "iso3" etc.
        # Stock llama-cpp-python uses `type_k` / `type_v` ints instead.
        self._rotorquant_available: bool = False
        try:
            from llama_cpp import Llama as _Llama_probe

            _sig = inspect.signature(_Llama_probe.__init__)
            self._rotorquant_available = "cache_type_k" in _sig.parameters
        except Exception:
            # llama_cpp not importable yet — that's fine, just means no
            # in-process path available. detection retries on load_model.
            pass
        logger.info(
            f"[LocalModelManager] RotorQuant (planar3/iso3) available: "
            f"{self._rotorquant_available}"
        )
        # Progress heartbeat task — synthesises load_progress events during
        # in-process load since Llama() gives no native progress.
        self._progress_task: Optional[asyncio.Task] = None
        self._register_cleanup()

    def _get_load_lock(self) -> asyncio.Lock:
        """Lazy-create asyncio.Lock (must be created in async context)."""
        if self._load_lock is None:
            self._load_lock = asyncio.Lock()
        return self._load_lock

    # ─────────────────────────────────────────────────────────────────────────
    # In-process inference (preferred path — IRIS_INPROCESS_LLAMA=1)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _inprocess_enabled() -> bool:
        """Feature flag — default on. Set IRIS_INPROCESS_LLAMA=0 to restore
        the subprocess path while the in-process implementation is verified."""
        return os.environ.get("IRIS_INPROCESS_LLAMA", "1") != "0"

    def _build_llama_ctor_kwargs(
        self, model_path: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Map a PROFILES dict into ``Llama(**kwargs)`` form.

        Handles the fork split:
          * Stock llama-cpp-python → ``type_k`` / ``type_v`` = GGML int
          * RotorQuant fork       → ``cache_type_k`` / ``cache_type_v`` = string
        """
        ctor: Dict[str, Any] = {
            "model_path": str(model_path),
            "n_gpu_layers": int(params.get("n_gpu_layers", -1)),
            "n_ctx": int(params.get("n_ctx", 8192)),
            "n_batch": int(params.get("n_batch", 2048)),
            "n_threads": int(params.get("n_threads", cpu_count())),
            "flash_attn": bool(params.get("flash_attn", True)),
            "use_mmap": bool(params.get("use_mmap", True)),
            "use_mlock": bool(params.get("keep_model_in_memory", False)),
            "offload_kqv": bool(params.get("offload_kv_cache", True)),
            "verbose": False,
        }

        k_name = (params.get("cache_type_k") or "").lower()
        v_name = (params.get("cache_type_v") or "").lower()

        if k_name in _ROTORQUANT_KV_TYPES or v_name in _ROTORQUANT_KV_TYPES:
            # Profile requested a RotorQuant KV type — only honoured if fork
            # is installed; otherwise leave KV cache at library default (f16).
            if self._rotorquant_available:
                if k_name:
                    ctor["cache_type_k"] = k_name
                if v_name:
                    ctor["cache_type_v"] = v_name
            else:
                logger.warning(
                    f"[LocalModelManager] Profile requested RotorQuant KV "
                    f"'{k_name}/{v_name}' but llama-cpp-turboquant fork not "
                    f"installed. Falling back to default f16 KV cache. "
                    f"See docs/rotorquant_build.md."
                )
        else:
            # Stock llama-cpp-python path — map string → GGML_TYPE integer.
            if k_name and k_name in _GGML_TYPE_INT:
                ctor["type_k"] = _GGML_TYPE_INT[k_name]
            if v_name and v_name in _GGML_TYPE_INT:
                ctor["type_v"] = _GGML_TYPE_INT[v_name]

        seed = params.get("seed")
        if seed is not None and int(seed) != -1:
            ctor["seed"] = int(seed)

        return ctor

    async def _start_progress_heartbeat(self, progress_cb) -> None:
        """Synthesise load_progress events every 500 ms until cancelled.

        Llama() gives no native progress signal from Python — this keeps the
        frontend's "model loading…" UI alive instead of staring at a frozen
        bar for the 15–30 s of GPU upload.
        """
        if progress_cb is None:
            return

        async def _pump() -> None:
            phases = [
                (5, "init", "Initialising llama-cpp runtime"),
                (20, "loading", "Reading GGUF from disk"),
                (50, "loading", "Uploading weights to GPU"),
                (80, "context", "Allocating KV cache"),
                (95, "context", "Warming up"),
            ]
            idx = 0
            try:
                while idx < len(phases):
                    pct, phase, msg = phases[idx]
                    try:
                        await progress_cb({"phase": phase, "pct": pct, "msg": msg})
                    except Exception:
                        pass
                    idx += 1
                    await asyncio.sleep(2.0)
                # After scripted phases, idle at 95% until caller cancels.
                while True:
                    await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                return

        self._progress_task = asyncio.ensure_future(_pump())

    def _stop_progress_heartbeat(self) -> None:
        if self._progress_task is not None and not self._progress_task.done():
            self._progress_task.cancel()
        self._progress_task = None

    async def _load_inprocess(
        self,
        model_path: str,
        params: Dict[str, Any],
        progress_cb=None,
    ) -> bool:
        """Construct a `llama_cpp.Llama` on a thread executor (no subprocess).

        Returns True when the instance is ready for inference. Emits
        synthetic progress events via progress_cb (Llama itself gives none).
        """
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            logger.error(f"[LocalModelManager] llama-cpp-python not importable: {exc}")
            if progress_cb:
                try:
                    await progress_cb(
                        {
                            "phase": "error",
                            "pct": 0,
                            "msg": "llama-cpp-python not installed in backend env",
                        }
                    )
                except Exception:
                    pass
            return False

        # Re-detect in case the env changed since __init__ (e.g. fork was just
        # installed). Cheap — one inspect.signature call.
        try:
            self._rotorquant_available = (
                "cache_type_k" in inspect.signature(Llama.__init__).parameters
            )
        except Exception:
            pass

        ctor = self._build_llama_ctor_kwargs(model_path, params)
        logger.info(
            f"[LocalModelManager] Loading in-process: "
            f"model={Path(model_path).name} n_ctx={ctor.get('n_ctx')} "
            f"n_gpu_layers={ctor.get('n_gpu_layers')} "
            f"flash_attn={ctor.get('flash_attn')} "
            f"rotorquant={self._rotorquant_available}"
        )

        await self._start_progress_heartbeat(progress_cb)
        loop = asyncio.get_running_loop()
        try:
            llm = await loop.run_in_executor(None, lambda: Llama(**ctor))
        except Exception as exc:
            logger.exception(
                f"[LocalModelManager] In-process Llama construction failed: {exc}"
            )
            if progress_cb:
                try:
                    await progress_cb(
                        {
                            "phase": "error",
                            "pct": 0,
                            "msg": f"Load failed: {exc}",
                        }
                    )
                except Exception:
                    pass
            self._stop_progress_heartbeat()
            return False
        finally:
            self._stop_progress_heartbeat()

        self._llm = llm
        self._current_model_path = model_path
        self._current_params = params
        logger.info(
            f"[LocalModelManager] In-process Llama ready "
            f"(model={Path(model_path).name}, ctx={ctor.get('n_ctx')})"
        )
        if progress_cb:
            try:
                await progress_cb({"phase": "ready", "pct": 100, "msg": "Model ready"})
            except Exception:
                pass
        return True

    def create_chat_completion(self, **kwargs) -> Dict[str, Any]:
        """Synchronous wrapper around `Llama.create_chat_completion`.

        Kept sync to match the caller shape in agent_kernel (OpenAI Python
        client is sync). Serialised by `_inference_lock` — only one inference
        runs through the single Llama instance at a time.

        `stream=True` routes through `create_chat_completion_stream`.

        Returns an OpenAI-format dict — the caller (`InProcessOpenAIAdapter`)
        wraps it in attribute-access objects to match the Pydantic surface
        the kernel expects from the real openai client.
        """
        if self._llm is None:
            raise RuntimeError("LocalModelManager: no in-process model loaded")
        if kwargs.get("stream"):
            # Collapse to the streaming generator; caller decides what to do.
            return self.create_chat_completion_stream(**kwargs)  # type: ignore[return-value]
        with self._inference_lock:
            return self._llm.create_chat_completion(
                **_sanitise_completion_kwargs(kwargs)
            )

    def create_chat_completion_stream(self, **kwargs) -> Iterator[Dict[str, Any]]:
        """Token-by-token generator. Holds `_inference_lock` for the whole run.

        Yields OpenAI-format chunk dicts straight from llama-cpp-python.
        Caller is responsible for wrapping chunks in attribute-access objects
        if it speaks the openai Pydantic surface.
        """
        if self._llm is None:
            raise RuntimeError("LocalModelManager: no in-process model loaded")
        kwargs = _sanitise_completion_kwargs(kwargs)
        kwargs["stream"] = True
        with self._inference_lock:
            for chunk in self._llm.create_chat_completion(**kwargs):
                yield chunk

    def get_inprocess_client(self) -> Optional["InProcessOpenAIAdapter"]:
        """Return an OpenAI-client shim bound to this manager, or None if no
        in-process model is loaded.

        Agent kernel's `_get_lmstudio_client()` calls this when the provider
        is ``iris_local`` and the feature flag is on. The adapter mimics
        ``openai.OpenAI().chat.completions.create(**kwargs)`` closely enough
        for the kernel's existing call sites — both the non-streaming
        ``resp.choices[0].message.content`` access and the streaming
        ``for chunk in resp: chunk.choices[0].delta.content`` iteration.
        """
        if self._llm is None:
            return None
        return InProcessOpenAIAdapter(self)

    # ─────────────────────────────────────────────────────────────────────────
    # Hardware info
    # ─────────────────────────────────────────────────────────────────────────

    def _invalidate_hw_cache(self) -> None:
        """Call after model load/unload — VRAM state changes, cache stale."""
        self._hw_cache = None
        self._hw_cache_time = 0.0

    def get_hardware_info(self, force_refresh: bool = False) -> Dict[str, Any]:
        import time as _time

        # Cache for 60 seconds — VRAM doesn't change unless a model loads/unloads
        # (which calls _invalidate_hw_cache). This avoids re-initializing CUDA on
        # every models-list request.
        if (
            not force_refresh
            and self._hw_cache is not None
            and (_time.monotonic() - self._hw_cache_time) < 60.0
        ):
            return self._hw_cache

        info: Dict[str, Any] = {
            "cuda_available": False,
            "gpu_name": "No GPU",
            "vram_total_gb": 0.0,
            "vram_free_gb": 0.0,
            "ram_total_gb": 0.0,
        }
        if PSUTIL_AVAILABLE:
            vm = psutil.virtual_memory()
            info["ram_total_gb"] = round(vm.total / (1024**3), 1)

        # Lazy torch import — avoids 360 MB cost at startup.
        try:
            import torch as _torch

            _has_cuda = _torch.cuda.is_available()
        except ImportError:
            _torch = None
            _has_cuda = False

        if _has_cuda:
            try:
                props = _torch.cuda.get_device_properties(0)
                total = props.total_memory / (1024**3)
                allocated = _torch.cuda.memory_allocated(0) / (1024**3)
                reserved = _torch.cuda.memory_reserved(0) / (1024**3)
                used = max(allocated, reserved)
                info.update(
                    {
                        "cuda_available": True,
                        "gpu_name": props.name,
                        "vram_total_gb": round(total, 1),
                        "vram_free_gb": round(max(0.0, total - used), 1),
                    }
                )
            except Exception as e:
                logger.warning(f"[LocalModelManager] VRAM query failed: {e}")
        # NOTE: No llama_cpp fallback here. Importing llama_cpp at this point
        # triggers CUDA driver initialization, which spikes memory at startup.
        # GPU detection via llama_cpp only happens when the user explicitly loads
        # a model (load_model → _build_server_cmd). Until then, cuda_available
        # stays False and the UI shows the "No GPU" placeholder — this is correct
        # because no inference is running yet.

        info["models_dir"] = str(self.effective_models_dir)
        self._hw_cache = info
        self._hw_cache_time = _time.monotonic()
        return info

    # ─────────────────────────────────────────────────────────────────────────
    # Model scanning
    # ─────────────────────────────────────────────────────────────────────────

    def _iter_gguf_paths(self) -> List[Path]:
        """Depth-bounded walk that follows symlinks, deduped by resolved path.

        REQ-6: discovers models reachable ONLY through a symlink, exactly once.
        Circular symlinks are skipped (resolved paths are tracked). Depth is
        bounded by SCAN_MAX_DEPTH so a symlink loop cannot hang the scan.
        """
        root = self.effective_models_dir
        results: List[Path] = []
        seen: set = set()  # resolved paths already handled (files + dirs)
        from collections import deque

        queue: "deque[tuple[Path, int]]" = deque([(root, 0)])
        try:
            seen.add(root.resolve())
        except OSError:
            pass
        while queue:
            d, depth = queue.popleft()
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_symlink():
                        target = Path(entry.path).resolve()
                        if target in seen:
                            continue
                        seen.add(target)
                        if entry.is_dir():
                            # Symlinked directory — follow it (depth-bounded).
                            if depth + 1 <= SCAN_MAX_DEPTH:
                                queue.append((Path(entry.path), depth + 1))
                        elif entry.name.endswith(".gguf"):
                            results.append(Path(entry.path))
                        # Symlinked non-gguf file → skip.
                        continue
                    # Regular (non-symlink) entry.
                    if entry.is_dir(follow_symlinks=False):
                        if depth + 1 <= SCAN_MAX_DEPTH:
                            queue.append((Path(entry.path), depth + 1))
                    elif entry.name.endswith(".gguf"):
                        rp = Path(entry.path).resolve()
                        if rp not in seen:
                            seen.add(rp)
                            results.append(Path(entry.path))
                except OSError:
                    continue
        return sorted(results)

    def scan_models(self) -> List[Dict[str, Any]]:
        """
        Walk MODELS_DIR for *.gguf files.
        Groups split-shard files (model-00001-of-NNNNN.gguf) under one entry.
        Returns list of model dicts with metadata.

        REQ-6: traversal follows symlinks (depth-bounded, circular-safe) so a
        model reachable only through a symlink is discovered exactly once.
        """
        settings = self.load_model_settings()
        seen_bases: Dict[str, Dict[str, Any]] = {}  # base_name -> entry

        for gguf_path in self._iter_gguf_paths():
            filename = gguf_path.name
            stem = gguf_path.stem  # without .gguf

            # Stat the file once — used for both size and cache key
            try:
                st = gguf_path.stat()
            except OSError:
                continue

            # Detect split shards (e.g., model-00001-of-00003)
            is_shard = False
            shard_idx = 0
            base_stem = stem
            if _SPLIT_SUFFIX_PART in stem:
                parts = stem.rsplit(_SPLIT_SUFFIX_PART, 1)
                if len(parts) == 2 and parts[0][-6:].lstrip("-").isdigit():
                    base_stem = parts[0][:-7]  # strip "-NNNNN"
                    shard_str = parts[0][-5:]
                    is_shard = True
                    try:
                        shard_idx = int(shard_str)
                    except ValueError:
                        pass

            if base_stem in seen_bases:
                # Already have this model; only keep the first shard as load path
                if is_shard and shard_idx == 1:
                    seen_bases[base_stem]["path"] = str(gguf_path)
                seen_bases[base_stem]["shard_count"] = (
                    seen_bases[base_stem].get("shard_count", 1) + 1
                )
                continue

            # Metadata cache: key = "path::mtime" — avoids re-parsing unchanged files.
            # First call is slow (reads GGUF headers). Subsequent calls are instant.
            cache_key = f"{gguf_path}::{st.st_mtime}"
            if cache_key in self._metadata_cache:
                meta = self._metadata_cache[cache_key]
            else:
                try:
                    meta = self.parse_gguf_metadata(gguf_path)
                except Exception as e:
                    logger.debug(
                        f"[LocalModelManager] Could not parse GGUF header for {filename}: {e}"
                    )
                    meta = {}
                self._metadata_cache[cache_key] = meta

            size_gb = round(st.st_size / (1024**3), 2)
            quant = meta.get("quantization") or self._quant_from_filename(stem)
            vram_est = self.estimate_vram_gb(meta) if meta.get("params_b") else 0.0

            model_settings = settings.get(filename, {})

            entry = {
                "path": str(gguf_path),
                "filename": filename,
                "display_name": base_stem.replace("-", " ").replace("_", " "),
                "size_gb": size_gb,
                "architecture": meta.get("architecture", "unknown"),
                "params_b": meta.get("params_b", 0),
                "native_ctx": meta.get("context_length", 0),
                "quantization": quant,
                "vram_estimate_gb": round(vram_est, 1),
                "loaded": (
                    self._current_model_path is not None
                    and Path(self._current_model_path).resolve() == gguf_path.resolve()
                ),
                "pinned": model_settings.get("pinned", False),
                "last_profile": model_settings.get("last_profile", "balanced"),
                "last_ctx": model_settings.get("last_ctx", 32768),
                "last_gpu_layers": model_settings.get("last_gpu_layers", -1),
                "shard_count": 1,
                "is_mtp_capable": meta.get("is_mtp", False)
                or "mtp" in filename.lower()
                or "mtp" in base_stem.lower(),
            }
            seen_bases[base_stem] = entry

        models = list(seen_bases.values())
        # Pinned models float to top
        models.sort(key=lambda m: (not m["pinned"], m["display_name"].lower()))
        return models

    def parse_gguf_metadata(self, path: Path) -> Dict[str, Any]:
        """
        Read GGUF binary header to extract architecture, parameter count,
        context length, and quantization type.

        Optimised for WSL / network mounts: reads the entire header block
        into memory once, then parses from a buffer.  Avoids hundreds of
        tiny 1-8 byte reads across the 9P boundary which hang on
        Windows-mounted drives.
        """
        meta: Dict[str, Any] = {}
        GGUF_MAGIC = b"GGUF"

        # Read just the fixed header first (24 bytes) to validate
        with open(path, "rb") as f:
            header = f.read(24)
        if len(header) < 24 or header[:4] != GGUF_MAGIC:
            return meta

        version = struct.unpack("<I", header[4:8])[0]
        if version not in (1, 2, 3):
            return meta

        _tensor_count = struct.unpack("<Q", header[8:16])[0]
        kv_count = struct.unpack("<Q", header[16:24])[0]

        # Now read a reasonably-sized chunk that should contain all metadata.
        # Most GGUF files have < 32 KB of metadata, but MoE models (e.g.
        # LFM2.5-8B-A1B with 32 experts) can have ~900 KB. We cap at 2 MB.
        META_READ_SIZE = 2_097_152
        with open(path, "rb") as f:
            f.read(24)  # skip header we already parsed
            buf = f.read(META_READ_SIZE)

        pos = 0
        buf_len = len(buf)

        def _read(n: int) -> bytes:
            nonlocal pos
            end = pos + n
            if end > buf_len:
                raise EOFError()
            data = buf[pos:end]
            pos = end
            return data

        def read_str() -> str:
            length = struct.unpack("<Q", _read(8))[0]
            return _read(length).decode("utf-8", errors="replace")

        # GGUF value type readers. This file uses a non-standard type enum
        # (type 4 = UINT32, type 8 = STRING) that differs from the GGUF spec
        # (type 4 = STRING, type 8 = ARRAY). We support BOTH encodings by
        # treating type 4 and type 8 as STRING, and type 0 as UINT32.
        # The non-standard mapping is what LM Studio / HF cache GGUF files use.
        _GGUF_TYPE_READERS = {
            0: lambda: struct.unpack("<I", _read(4))[0],   # UINT32
            1: lambda: struct.unpack("<i", _read(4))[0],   # INT32
            2: lambda: struct.unpack("<f", _read(4))[0],   # FLOAT32
            3: lambda: struct.unpack("<?", _read(1))[0],   # BOOL
            5: lambda: struct.unpack("<Q", _read(8))[0],   # UINT64
            6: lambda: struct.unpack("<q", _read(8))[0],   # INT64
            7: lambda: struct.unpack("<d", _read(8))[0],   # FLOAT64
            9: lambda: struct.unpack("<H", _read(2))[0],   # UINT16 (standard) — may be ARRAY (non-standard)
            11: lambda: read_str(),                        # STRING_DEPRECATED
        }

        def _try_string() -> Any:
            """Try to read a STRING value (8-byte length + data).
            Returns None if the length looks unreasonable."""
            nonlocal pos
            peek = buf[pos:pos+8]
            if len(peek) < 8:
                return None
            slen = struct.unpack("<Q", peek)[0]
            if slen > 0 and slen < 65536 and pos + 8 + slen <= buf_len:
                pos += 8
                return _read(slen).decode("utf-8", errors="replace")
            return None

        class _StopParsing(Exception):
            """Raised when a value's length cannot be determined (cursor unrecoverable)."""

        def _read_str_strict() -> str:
            slen = struct.unpack("<Q", _read(8))[0]
            if slen <= 0 or slen >= 65536 or pos + slen > buf_len:
                raise _StopParsing()
            return _read(slen).decode("utf-8", errors="replace")

        def _read_array_strict() -> list:
            elem_type = struct.unpack("<I", _read(4))[0]
            count = struct.unpack("<Q", _read(8))[0]
            if elem_type not in _GGUF_TYPE_READERS or count >= 1024:
                raise _StopParsing()
            return [read_value(elem_type, "auto") for _ in range(count)]

        def _skip_string() -> bool:
            slen = struct.unpack("<Q", _read(8))[0]
            if slen <= 0 or slen >= 65536 or pos + slen > buf_len:
                return False
            _read(slen)
            return True

        def _skip_array() -> bool:
            elem_type = struct.unpack("<I", _read(4))[0]
            count = struct.unpack("<Q", _read(8))[0]
            if elem_type not in _GGUF_TYPE_READERS or count >= 1024:
                return False
            for _ in range(count):
                if not _skip_value(elem_type, "auto"):
                    return False
            return True

        def _skip_value(vtype: int, mode: str = "auto") -> bool:
            """Advance pos past a value of `vtype`. Return False if the type's
            length cannot be determined (cursor unrecoverable)."""
            if vtype in (0, 1, 2, 3):
                _read({0: 4, 1: 4, 2: 4, 3: 1}[vtype]); return True
            if vtype in (5, 6, 7):
                _read(8); return True
            if vtype == 10:
                return False  # COMPLEX — unsized
            if vtype == 11:  # STRING_DEPRECATED
                slen = struct.unpack("<Q", _read(8))[0]
                _read(slen); return True
            if vtype == 4:  # STRING or UINT32
                if mode == "non_standard":
                    _read(4); return True
                peek = buf[pos:pos + 8]
                if len(peek) >= 8:
                    slen = struct.unpack("<Q", peek)[0]
                    if 0 < slen < 65536 and pos + 8 + slen <= buf_len:
                        _read(8 + slen); return True
                if mode == "standard":
                    return False
                _read(4); return True  # auto UINT32 fallback
            if vtype == 8:  # STRING or ARRAY
                if mode == "non_standard":
                    return _skip_string()
                peek = buf[pos:pos + 8]
                if len(peek) >= 8:
                    slen = struct.unpack("<Q", peek)[0]
                    if 0 < slen < 65536 and pos + 8 + slen <= buf_len:
                        _read(8 + slen); return True
                if mode == "standard":
                    return _skip_array()
                return _skip_array()  # auto: try array
            if vtype == 9:  # ARRAY or UINT16
                if mode == "standard":
                    _read(2); return True
                peek = buf[pos:pos + 12]
                if len(peek) >= 12:
                    elem_type = struct.unpack("<I", peek[:4])[0]
                    count = struct.unpack("<Q", peek[4:12])[0]
                    if elem_type in _GGUF_TYPE_READERS and count < 1024:
                        _read(12)
                        for _ in range(count):
                            if not _skip_value(elem_type, mode):
                                return False
                        return True
                if mode == "non_standard":
                    return False
                _read(2); return True  # auto UINT16 fallback
            return False

        def read_value(vtype: int, mode: str = "auto") -> Any:
            nonlocal pos
            if mode == "standard":
                if vtype == 4:
                    return _read_str_strict()
                if vtype == 8:
                    return _read_array_strict()
                if vtype == 9:
                    return struct.unpack("<H", _read(2))[0]
            elif mode == "non_standard":
                if vtype == 4:
                    return struct.unpack("<I", _read(4))[0]
                if vtype == 8:
                    return _read_str_strict()
                if vtype == 9:
                    return _read_array_strict()
            # auto (default) — tries STRING first, falls back (current behavior)
            if vtype == 4:
                result = _try_string()
                if result is not None:
                    return result
                return struct.unpack("<I", _read(4))[0]
            if vtype == 8:
                result = _try_string()
                if result is not None:
                    return result
                elem_type = struct.unpack("<I", _read(4))[0]
                count = struct.unpack("<Q", _read(8))[0]
                if elem_type in _GGUF_TYPE_READERS and count < 1024:
                    return [read_value(elem_type, mode) for _ in range(count)]
                raise _StopParsing()
            if vtype == 9:
                peek = buf[pos:pos + 12]
                if len(peek) >= 12:
                    elem_type = struct.unpack("<I", peek[:4])[0]
                    count = struct.unpack("<Q", peek[4:12])[0]
                    if elem_type in _GGUF_TYPE_READERS and count < 1024:
                        pos += 12
                        return [read_value(elem_type, mode) for _ in range(count)]
                return struct.unpack("<H", _read(2))[0]
            if vtype == 10:  # COMPLEX — not needed for metadata
                raise _StopParsing()
            reader = _GGUF_TYPE_READERS.get(vtype)
            if reader is None:
                raise _StopParsing()
            return reader()

        def _is_sane_architecture(arch: Any) -> bool:
            if not isinstance(arch, str) or not arch:
                return False
            return all(32 <= ord(c) < 127 for c in arch)

        def _parse_once(mode: str) -> Dict[str, Any]:
            """Parse the KV section once under enum `mode`.

            GAP 2 fix: a single unparseable key no longer discards every key
            after it. On a per-key failure we skip the value and continue with
            the NEXT key; we stop (marked ``_partial``) only when the cursor is
            genuinely unrecoverable.
            """
            nonlocal pos
            pos = 0
            result: Dict[str, Any] = {}
            skipped: list = []
            for _ in range(min(kv_count, 256)):
                try:
                    key = read_str()
                    vtype = struct.unpack("<I", _read(4))[0]
                    val = read_value(vtype, mode)
                except _StopParsing:
                    result["_partial"] = True
                    break
                except Exception:
                    # Recoverable error (e.g. truncated buffer): skip the value
                    # and continue instead of discarding all remaining keys.
                    try:
                        if not _skip_value(vtype, mode):
                            result["_partial"] = True
                            break
                    except Exception:
                        result["_partial"] = True
                        break
                    skipped.append(key)
                    continue
                if key == "general.architecture" and isinstance(val, str):
                    result["architecture"] = val
                elif key == "general.parameter_count" and isinstance(val, int):
                    result["params_b"] = round(val / 1e9, 1)
                elif key == "general.name" and isinstance(val, str):
                    result["model_name"] = val
                    if "mtp" in val.lower():
                        result["is_mtp"] = True
                elif key == "general.size_label" and isinstance(val, str):
                    # e.g. "1.2B", "450M", "8B" — fallback when parameter_count is absent
                    try:
                        val_stripped = val.strip().upper()
                        if "X" in val_stripped:
                            # MoE format: "32x959M" → 32 experts × 959M = 30.7B total params
                            parts = val_stripped.split("X")
                            if len(parts) == 2:
                                n_experts = int(parts[0])
                                per_expert = parts[1]
                                if per_expert.endswith("M"):
                                    per_b = float(per_expert[:-1]) / 1000
                                elif per_expert.endswith("B"):
                                    per_b = float(per_expert[:-1])
                                else:
                                    per_b = float(per_expert)
                                result["params_b"] = round(n_experts * per_b, 1)
                                result["is_moe"] = True
                        elif val_stripped.endswith("B"):
                            result["params_b"] = float(val_stripped[:-1])
                        elif val_stripped.endswith("M"):
                            result["params_b"] = round(float(val_stripped[:-1]) / 1000, 1)
                    except (ValueError, IndexError):
                        pass
                elif key.endswith(".context_length") and isinstance(val, int):
                    result["context_length"] = val
                elif key.endswith(".block_count") and isinstance(val, int):
                    result["block_count"] = val
            if skipped or result.get("_partial"):
                logger.info(
                    f"[LocalModelManager] parse_gguf_metadata: parsed "
                    f"{len([k for k in result if not k.startswith('_')])} fields, "
                    f"skipped {len(skipped)} key(s)={skipped}, "
                    f"partial={result.get('_partial', False)}"
                )
            return result

        # GAP 3: detect, do not assume. Auto-parse first; if the architecture is
        # not sane ASCII, retry with explicit standard / non-standard enums and
        # keep whichever yields a sane architecture. Log the selected enum.
        meta = _parse_once("auto")
        arch = meta.get("architecture")
        if not _is_sane_architecture(arch):
            chosen = None
            for mode in ("standard", "non_standard"):
                cand = _parse_once(mode)
                if _is_sane_architecture(cand.get("architecture")):
                    meta = cand
                    chosen = mode
                    break
            if chosen is not None:
                logger.info(
                    f"[LocalModelManager] parse_gguf_metadata: auto enum produced "
                    f"non-sane architecture ({arch!r}); selected enum={chosen}"
                )
            else:
                logger.warning(
                    f"[LocalModelManager] parse_gguf_metadata: architecture not "
                    f"sane under any enum ({arch!r}); using auto result"
                )

        # Tensor-based MTP detection: peek at first few tensor names for mtp. prefix
        if not meta.get("is_mtp"):
            try:
                # Read tensor name count and a small slice of tensor names
                tensor_count = struct.unpack("<Q", buf[pos : pos + 8])[0]
                pos += 8
                for _ in range(min(tensor_count, 20)):
                    name_len = struct.unpack("<I", buf[pos : pos + 4])[0]
                    pos += 4
                    name = buf[pos : pos + name_len].decode("utf-8", errors="replace")
                    pos += name_len
                    if name.startswith("mtp.") or ".mtp." in name:
                        meta["is_mtp"] = True
                        break
                    # Skip type (4) + offset (8) + dimensions
                    pos += 4 + 8
                    ndim = struct.unpack("<I", buf[pos - 4 : pos])[0] if pos >= 4 else 0
                    pos += ndim * 8
            except Exception:
                pass

        return meta

    def _quant_from_filename(self, stem: str) -> str:
        """Fallback: extract quantization type from filename."""
        stem_upper = stem.upper()
        for quant in sorted(QUANT_BPW.keys(), key=len, reverse=True):
            if quant in stem_upper:
                return quant
        return "unknown"

    # ─────────────────────────────────────────────────────────────────────────
    # VRAM estimation
    # ─────────────────────────────────────────────────────────────────────────

    def estimate_vram_gb(
        self, model_meta: Dict[str, Any], n_ctx: Optional[int] = None
    ) -> float:
        """
        Estimate VRAM requirement: weights + KV cache.

        D-3: VRAM estimate must include KV cache (context-dependent,
        not weights-only). The KV cache grows linearly with n_ctx and
        is computed from the model's architecture metadata.

        Formula:
            weights = params_B × bits_per_weight / 8 × 1.1 overhead
            kv_cache = 2 × n_layers × n_ctx × hidden_size × 2 bytes (fp16)
            total = weights + kv_cache

        Args:
            model_meta: Parsed GGUF metadata dict.
            n_ctx: Target context length. If None, uses model_meta's
                   native context_length or MIN_CTX as fallback.

        Returns:
            Estimated VRAM in GB (weights + KV cache).
        """
        params_b = model_meta.get("params_b", 0)
        quant = model_meta.get("quantization", "Q4_K_M")
        bpw = QUANT_BPW.get(quant.upper(), 4.85)

        if not params_b:
            return 0.0

        # ── Weights (context-independent) ──
        weights_gb = params_b * bpw / 8.0 * 1.1

        # ── KV cache (context-dependent, D-3) ──
        # Use provided n_ctx, or fall back to metadata, or MIN_CTX
        if n_ctx is None:
            n_ctx = model_meta.get("context_length") or model_meta.get("n_ctx") or MIN_CTX

        block_count = model_meta.get("block_count", 0)
        embed_dim = model_meta.get("embed_dim", 0)

        if block_count and embed_dim and n_ctx:
            # Standard transformer KV cache:
            #   2 (K+V) × n_layers × n_ctx × hidden_size × 2 bytes (fp16)
            kv_cache_gb = 2 * block_count * n_ctx * embed_dim * 2 / (1024 ** 3)
        else:
            # Fallback: estimate KV cache from params and n_ctx.
            # Approximate: KV cache ≈ params × n_ctx × 2 bytes / 1e9
            # (assumes ~1 byte of KV cache per parameter per token)
            kv_cache_gb = params_b * n_ctx * 2 / (1024 ** 3)

        return weights_gb + kv_cache_gb

    # ─────────────────────────────────────────────────────────────────────────
    # Profile resolution
    # ─────────────────────────────────────────────────────────────────────────

    def get_profile_params(
        self, profile: str, custom: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        base = dict(PROFILES.get(profile, PROFILES["balanced"]))
        if custom:
            base.update(custom)
        return base

    def recommend_profile(self, model_meta: Dict[str, Any]) -> str:
        """
        Auto-select profile based on model size + available hardware.
        Returns profile name string.
        """
        hw = self.get_hardware_info()
        vram = hw.get("vram_free_gb", 0.0)
        cuda = hw.get("cuda_available", False)
        vram_needed = self.estimate_vram_gb(model_meta)

        # GPU-ONLY policy: never recommend the CPU 'eco' profile. If CUDA is
        # missing or VRAM is tight, still prefer a GPU profile (balanced) and
        # let the pre-flight check reject the load if VRAM is truly insufficient
        # — rather than silently falling back to CPU.
        if vram_needed > 0 and vram_needed > vram * 0.9:
            # Tight VRAM: try performance (more aggressive offload) but stay on GPU.
            return "performance"
        # Always prefer balanced (32k ctx / 1536 batch) — it's the 24GB RAM sweet spot.
        # performance is only for explicit user override.
        return "balanced"

    # ─────────────────────────────────────────────────────────────────────────
    # ConfigDeriver: compute optimal n_ctx, n_gpu_layers, n_batch
    # ─────────────────────────────────────────────────────────────────────────

    def derive_config(
        self,
        model_meta: Dict[str, Any],
        target_tps: float = TARGET_TPS,
        base_tps: Optional[float] = None,
        vram_budget_gb: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Derive the optimal inference config for a model.

        T2.2: ConfigDeriver — the single function that, given model_meta +
        hardware + target_tps, returns the largest n_ctx such that:
          a) estimated VRAM (weights + KV cache) fits in gpu_free_vram
          b) expected tps >= target_tps

        Binary-searches n_ctx from [MIN_CTX, MAX_CTX] and returns the config.

        D-2: n_gpu_layers is ALWAYS -1 for chat (full GPU offload, never CPU).
        D-3: VRAM estimate includes KV cache (context-dependent).

        Args:
            model_meta: Parsed GGUF metadata dict.
            target_tps: Minimum acceptable tokens/sec (default: TARGET_TPS).
            base_tps: Estimated base throughput at MIN_CTX. If None (default),
                      derive_config seeds it from a machine-level memory-bandwidth
                      calibration cached against the hw_fingerprint (P3.4 fix),
                      falling back to 50.0 only when uncalibrated. Used for the
                      throughput model: tps = base_tps * sqrt(MIN_CTX/n_ctx).
            vram_budget_gb: GPU VRAM budget in GB. If None, uses hardware info.

        Returns:
            Dict with keys: n_ctx, n_gpu_layers, n_batch, vram_est_gb, expected_tps
        """
        hw = self.get_hardware_info()
        if vram_budget_gb is None:
            vram_budget_gb = hw.get("vram_free_gb", 0.0)

        # P3.4 fix (CADUCEAN_ARCHITECTURE.md §10 rule 1 — compute-and-discard): if the
        # caller did not supply a base_tps, seed it from a machine-level memory-bandwidth
        # calibration cached against the hw_fingerprint. This makes a single real
        # measurement anywhere on the machine correct for EVERY model's first load,
        # instead of each model having to be run slowly three times to learn its own
        # lesson. Falls back to the flat 50.0 only when no calibration exists yet.
        calibrated = False
        if base_tps is None:
            base_tps = 50.0
            try:
                cache = getattr(self, "_config_cache", None)
                if cache is not None:
                    bw = cache.get_machine_bandwidth(hw)
                    if bw is not None:
                        _params_b = model_meta.get("params_b", 0) or 0
                        _quant = model_meta.get("quantization", "") or ""
                        _bpw = QUANT_BPW.get(_quant.upper(), 4.85)
                        if _params_b and _bpw:
                            seeded = bw / (_params_b * _bpw / 8.0)
                            if seeded > 0:
                                base_tps = seeded
                                calibrated = True
            except Exception:
                pass
        logger.info(
            f"[LocalModelManager] derive_config base_tps={base_tps:.1f} "
            f"(source={'machine_bandwidth' if calibrated else 'uncalibrated_default'})"
        )

        native_ctx = model_meta.get("context_length") or model_meta.get("n_ctx") or MAX_CTX
        max_ctx = min(native_ctx, MAX_CTX)

        # Throughput model: tps decreases as n_ctx increases.
        # tps = base_tps * sqrt(MIN_CTX / n_ctx)
        # This captures the fact that larger context → more attention computation → lower tps.
        def expected_tps(n_ctx: int) -> float:
            if n_ctx <= 0:
                return 0.0
            return base_tps * (MIN_CTX / n_ctx) ** 0.5

        # Binary search for the largest n_ctx that satisfies both constraints.
        lo, hi = MIN_CTX, max_ctx
        best_n_ctx = MIN_CTX

        while lo <= hi:
            mid = (lo + hi) // 2
            vram_est = self.estimate_vram_gb(model_meta, n_ctx=mid)
            tps_est = expected_tps(mid)

            if vram_est <= vram_budget_gb and tps_est >= target_tps:
                best_n_ctx = mid
                lo = mid + 1
            else:
                hi = mid - 1

        # Compute n_batch: scale with n_ctx, capped at 2048.
        # Larger context → larger batch for efficiency, but capped to avoid OOM.
        n_batch = min(max(best_n_ctx, 512), 2048)

        # D-2: n_gpu_layers ALWAYS -1 for chat (full GPU offload, never CPU offload).
        n_gpu_layers = -1

        return {
            "n_ctx": best_n_ctx,
            "n_gpu_layers": n_gpu_layers,
            "n_batch": n_batch,
            "vram_est_gb": self.estimate_vram_gb(model_meta, n_ctx=best_n_ctx),
            "expected_tps": expected_tps(best_n_ctx),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Subprocess lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_load_progress(line: str) -> Optional[Dict[str, Any]]:
        """
        Parse a line of llama.cpp / llama-cpp-python server stdout into a
        progress event dict, or return None if the line carries no progress info.

        Progress events: {"phase": str, "pct": int, "msg": str}
        Phases: init → loading → context → ready
        """
        import re

        # CUDA device detection: first sign of life
        if "ggml_cuda_init" in line or ("CUDA device" in line and "VRAM" in line):
            return {"phase": "init", "pct": 5, "msg": "CUDA device detected"}

        # Model header load begins
        if ("llama_model_load" in line or "llm_load_print_meta" in line) and (
            "loading" in line.lower()
            or "metadata" in line.lower()
            or "arch" in line.lower()
        ):
            return {"phase": "init", "pct": 10, "msg": "Reading model metadata"}
        # PrismML server: "llama_model_loader: loaded meta data with ..."
        if "llama_model_loader" in line and "meta data" in line:
            return {"phase": "init", "pct": 10, "msg": "Reading model metadata"}

        # Tensor loading / GPU layer offloading
        # "llm_load_tensors: offloading 32 repeating layers to GPU"
        # "llm_load_tensors: offloaded 32/33 layers to GPU"
        m = re.search(r"offloaded?\s+(\d+)(?:/(\d+))?\s+(?:repeating\s+)?layers", line)
        if m:
            n = int(m.group(1))
            total = int(m.group(2)) if m.group(2) else n
            pct = max(15, min(75, int(n / max(total, 1) * 65) + 10))
            return {
                "phase": "loading",
                "pct": pct,
                "msg": f"Offloading layers {n}/{total} to GPU",
            }

        # Tensor loading generic: "llm_load_tensors: ggml ctx size"
        if "llm_load_tensors" in line and "ggml" in line:
            return {"phase": "loading", "pct": 20, "msg": "Loading tensors"}
        # PrismML server: "llama_model_loader: - tensor N: name type" for each tensor.
        # N goes from 0 to ~850 for a 27B model. Use N to compute a rough
        # percentage between 15% and 75% (~1% per 14 tensors).
        m = re.search(r"llama_model_loader: - tensor\s+(\d+):", line)
        if m:
            n = int(m.group(1))
            pct = min(75, 15 + n // 14)
            return {"phase": "loading", "pct": pct, "msg": "Loading tensors"}

        # Context / KV cache allocation
        if "llama_new_context_with_model" in line or (
            "kv cache" in line.lower() and "size" in line.lower()
        ):
            return {"phase": "context", "pct": 85, "msg": "Building KV cache"}
        # PrismML: "llama_new_context_with_model: n_ctx = N"
        if "llama_new_context_with_model" in line and "n_ctx" in line:
            return {"phase": "context", "pct": 85, "msg": "Building KV cache"}

        # Prompt cache / batch alloc
        if "llama_kv_cache_init" in line or "ggml_backend_alloc" in line:
            return {"phase": "context", "pct": 90, "msg": "Allocating compute buffers"}

        # Server listening (about to be ready)
        if re.search(
            r"(listening|HTTP server|server started|server is running)", line, re.I
        ):
            return {"phase": "ready", "pct": 98, "msg": "Server online"}

        # MTP speculative decoding metrics
        # llama-server prints: spec_decode_draft_tokens=N, spec_decode_draft_accepted=M
        m = re.search(r"spec_decode_draft_tokens[=:]\s*(\d+)", line)
        if m:
            return {
                "phase": "metrics",
                "type": "mtp_draft_tokens",
                "value": int(m.group(1)),
            }
        m = re.search(r"spec_decode_draft_accepted[=:]\s*(\d+)", line)
        if m:
            return {
                "phase": "metrics",
                "type": "mtp_accepted",
                "value": int(m.group(1)),
            }
        m = re.search(r"spec_decode_n_past[=:]\s*(\d+)", line)
        if m:
            return {"phase": "metrics", "type": "mtp_n_past", "value": int(m.group(1))}

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # [10.5] Pre-load resource validation
    # ─────────────────────────────────────────────────────────────────────────

    def _preflight_resource_check(
        self, model_path: str, params: Dict[str, Any], model_meta: Dict[str, Any] = None,
        purpose: str = "chat",
    ) -> Optional[str]:
        """
        Estimate VRAM/RAM requirements before spawning the subprocess.
        Properly accounts for partial GPU offloading (n_gpu_layers > 0).

        T3.3: Branches on resolve_device_policy(purpose). CPU purposes
        (embedding, rerank) skip the GPU check entirely.

        Returns an error string if resources are insufficient, None if OK.
        Fails open (returns None) if hardware info is unavailable —
        we never block a load due to a failed check.
        """
        try:
            # T3.3: Branch on device policy FIRST. CPU purposes skip GPU check
            # entirely — they don't count against VRAM, so no need to stat the file.
            policy = resolve_device_policy(purpose)
            if policy.device == "cpu":
                logger.debug(
                    f"[LocalModelManager] CPU purpose '{purpose}' — skipping GPU pre-flight"
                )
                return None

            path = Path(model_path)
            if not path.exists():
                return f"Model file not found: {model_path}"

            file_gb = path.stat().st_size / (1024**3)

            hw = self.get_hardware_info()
            n_gpu = params.get("n_gpu_layers", -1)
            n_ctx = params.get("n_ctx", 8192)

            # Get total layer count from metadata or estimate from params
            total_layers = 0
            if model_meta:
                total_layers = model_meta.get("block_count", 0)
            if not total_layers and model_meta:
                params_b = model_meta.get("params_b", 0)
                if params_b:
                    # Heuristic: Qwen ~2.2 layers per B, Llama ~4 layers per B
                    total_layers = max(24, int(params_b * 2.5))

            # Estimate KV cache RAM. For dense transformers this is roughly
            # 2 bytes * n_ctx * n_layers / 2 (K+V) ~ (ctx/1000) * 0.1 GB.
            # Hybrid-attention models (Qwen/Bonsai with 64 blocks) grow a
            # full-attention cache on only ~25% of layers, making the cache
            # ~4x smaller.
            kv_cache_gb = (n_ctx / 1000.0) * 0.1
            if total_layers >= 48:
                # Likely hybrid attention (e.g. Qwen3.6-27B: 64 blocks,
                # 16 full-attention). Scale cache down 4x.
                kv_cache_gb *= 0.25

            # Scale weight VRAM by fraction of layers offloaded to GPU
            if n_gpu != 0 and hw.get("cuda_available"):
                if n_gpu == -1:
                    # All layers on GPU
                    weight_vram = file_gb * 1.05
                elif total_layers and n_gpu > 0:
                    # Partial offload: only offloaded layers go to GPU
                    offload_frac = min(n_gpu / total_layers, 1.0)
                    weight_vram = file_gb * 1.05 * offload_frac
                else:
                    # Fallback: assume all on GPU when we don't know layer count
                    weight_vram = file_gb * 1.05

                vram_needed = weight_vram + kv_cache_gb
                vram_free = hw.get("vram_free_gb", 0.0)
                if vram_free > 0 and vram_needed > vram_free * 0.92:
                    return (
                        f"Insufficient VRAM: model needs ~{vram_needed:.1f} GB, "
                        f"{vram_free:.1f} GB free. Try a smaller quantization, "
                        f"reduce n_ctx, or reduce n_gpu_layers."
                    )
            else:
                # CPU load (n_gpu_layers == 0): NOT PERMITTED. Local models must
                # run on the GPU. Reject loudly instead of falling back to CPU.
                return (
                    "GPU offload required: local models must load onto the GPU "
                    "(n_gpu_layers must not be 0). No CPU fallback is allowed. "
                    "Ensure a CUDA build of llama-server is available and VRAM "
                    "is sufficient, or use a smaller model."
                )
        except Exception as e:
            logger.debug(f"[LocalModelManager] Pre-flight check skipped: {e}")
        return None  # fail open — never block load due to check error

    # ─────────────────────────────────────────────────────────────────────────
    # [10.7] Subprocess death watchdog
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_watchdog(self, crash_cb=None) -> None:
        """
        Poll is_loaded() every 5 seconds after a successful model load.
        If the subprocess exits unexpectedly (OOM, segfault, etc.), call crash_cb
        so the gateway can broadcast a crashed event to the frontend.
        """
        try:
            while True:
                await asyncio.sleep(5)
                if not self.is_loaded():
                    # Process died — reset state
                    with self._lock:
                        self._current_model_path = None
                        self._current_profile = "balanced"
                        self._current_params = {}
                    self._invalidate_hw_cache()
                    logger.warning(
                        "[LocalModelManager] Model server exited unexpectedly"
                    )
                    if crash_cb:
                        try:
                            await crash_cb()
                        except Exception as e:
                            logger.debug(f"[LocalModelManager] crash_cb failed: {e}")
                    break
        except asyncio.CancelledError:
            pass  # normal — watchdog cancelled by unload_model()

    def _stop_watchdog(self) -> None:
        """Cancel the watchdog task if running."""
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            self._watchdog_task = None

    # ─────────────────────────────────────────────────────────────────────────
    # [10.9] Settings comparison — decide if reload is required
    # ─────────────────────────────────────────────────────────────────────────

    def would_require_reload(
        self, new_profile: str, custom_params: Dict[str, Any]
    ) -> bool:
        """
        Return True if applying new_profile + custom_params requires a subprocess
        restart (n_ctx or n_gpu_layers differ from current loaded params).
        Return False if only hot-applicable params changed (e.g. n_batch only).
        """
        new_params = self.get_profile_params(new_profile, custom_params)
        reload_keys = {"n_ctx", "n_gpu_layers"}
        for k in reload_keys:
            if new_params.get(k) != self._current_params.get(k):
                return True
        return False

    # ─────────────────────────────────────────────────────────────────────────
    # [10.10] TPS recording + gradient warning
    # ─────────────────────────────────────────────────────────────────────────

    def record_tps(
        self, tps: float, gpu_active: bool = True, purpose: Optional[str] = None
    ) -> None:
        """
        Record a TPS measurement and feed corrections to ConfigCache.

        T4.1: threshold is TARGET_TPS (not the old hardcoded 8 tok/s).
        T4.4: embedding/rerank purposes are NOT measured against TARGET_TPS —
              they return early, recording no correction and emitting no warning.
        T4.2: sustained sub-target throughput writes a reduced-context config to
              ConfigCache for the NEXT load.
        T4.3: nothing here reconfigures the running model — corrections only
              affect the next load (REQ-4 AC4).

        Args:
            tps: measured tokens/sec for the last generation.
            gpu_active: whether the model is running on GPU (kept for signature
                        compat; the real device decision comes from `purpose`).
            purpose: the model's purpose ("chat", "embedding", "rerank", "tool").
                     Defaults to the currently-loaded model's purpose.
        """
        # Resolve purpose: explicit arg wins, else the loaded model's purpose.
        if purpose is None:
            purpose = getattr(self, "_current_purpose", "chat") or "chat"
        # T4.4: CPU purposes (embedding, rerank) have no throughput target and
        # must never be measured against TARGET_TPS (REQ-4 AC6).
        try:
            policy = resolve_device_policy(purpose)
        except ValueError:
            policy = resolve_device_policy("chat")
        if policy.throughput_target is None:
            return

        threshold = policy.throughput_target  # TARGET_TPS for chat/tool
        self._tps_window.append(tps)
        if len(self._tps_window) > 3:
            self._tps_window.pop(0)

        if len(self._tps_window) < 3:
            return

        avg = sum(self._tps_window) / len(self._tps_window)

        # Within deadband → close enough, record nothing (REQ-4 AC5).
        if threshold * (1 - TPS_DEADBAND) <= avg <= threshold * (1 + TPS_DEADBAND):
            self._tps_slow_warned = False
            return

        # T4.2: write a correction to ConfigCache for the NEXT load.
        self._write_tps_correction(avg, threshold, policy)

    def _write_tps_correction(
        self, avg_tps: float, target: float, policy: "DevicePolicy"
    ) -> None:
        """Persist a corrected config to ConfigCache based on measured throughput.

        Calibrates the throughput model's base_tps from the actual measurement,
        then re-derives at the ORIGINAL target. This naturally yields:
          - measured < target  → smaller n_ctx (shrink, recover throughput)
          - measured > target  → larger n_ctx (grow, use the headroom)
        Never touches the running model (T4.3).
        """
        if not self._current_model_path or not self._current_model_meta:
            return
        if policy.device == "cpu":
            return  # CPU models are never corrected

        current_n_ctx = self._current_params.get("n_ctx", MIN_CTX)
        if current_n_ctx <= 0:
            return

        # Calibrate base_tps from the measurement:
        #   expected_tps(n) = base_tps * sqrt(MIN_CTX / n)
        #   => base_tps = avg_tps / sqrt(MIN_CTX / current_n_ctx)
        try:
            calibrated_base = avg_tps / ((MIN_CTX / current_n_ctx) ** 0.5)
        except ZeroDivisionError:
            calibrated_base = 50.0

        hw = self.get_hardware_info()

        # P3.4 fix (CADUCEAN_ARCHITECTURE.md §10 rule 1 — compute-and-discard, 5th
        # instance): calibrated_base is model-specific and was previously used once
        # then discarded. Convert it to a MACHINE-LEVEL constant by dividing out this
        # model's own weight footprint, then cache it against the hw_fingerprint so
        # EVERY future model's first load derives its own correct base_tps — not just
        # this model's next load. Reuses the existing closed loop; only the SCOPE
        # changes. A computed signal must change behavior, or it is not implemented.
        try:
            _params_b = self._current_model_meta.get("params_b", 0) or 0
            _quant = self._current_model_meta.get("quantization", "") or ""
            _bpw = QUANT_BPW.get(_quant.upper(), 4.85)
            if _params_b and _bpw:
                effective_bandwidth = calibrated_base * (_params_b * _bpw / 8.0)
                self._config_cache.put_machine_bandwidth(hw, effective_bandwidth)
                logger.info(
                    f"[LocalModelManager] machine bandwidth calibrated: "
                    f"{effective_bandwidth:.1f} GB/s (from {avg_tps:.1f} tok/s, "
                    f"{_params_b}B {_quant})"
                )
        except Exception as exc:
            logger.warning(
                f"[LocalModelManager] failed to cache machine bandwidth: {exc}"
            )

        direction = "shrink" if avg_tps < target else "grow"

        try:
            derived = self.derive_config(
                self._current_model_meta,
                target_tps=target,
                base_tps=calibrated_base,
                vram_budget_gb=hw.get("vram_free_gb", 0.0),
            )
            corrected = dict(self._current_params)
            corrected["n_ctx"] = derived["n_ctx"]
            corrected["n_batch"] = derived["n_batch"]
            corrected["n_gpu_layers"] = -1
            self._config_cache.put(
                self._current_model_path,
                self._current_model_meta,
                hw,
                corrected,
                measured_tps=avg_tps,
            )
            logger.info(
                f"[LocalModelManager] TPS correction ({direction}): "
                f"measured {avg_tps:.1f} tok/s (target {target:.0f}) → "
                f"next-load n_ctx={corrected['n_ctx']}"
            )
        except Exception as exc:
            logger.warning(
                f"[LocalModelManager] failed to write TPS correction: {exc}"
            )

    # ──────────────────────────────────────────────────────────────────
    async def load_model(
        self,
        model_path: str,
        profile: str = "balanced",
        custom_params: Dict[str, Any] = None,
        purpose: str = "chat",
        progress_cb=None,  # async callable(event: dict) — optional progress hook
        crash_cb=None,  # async callable() — called if subprocess dies after load
    ) -> bool:
        """
        Stop existing subprocess (if any), spawn new llama-cpp-python server.
        Streams incremental load progress via progress_cb if provided.
        Returns True when /health responds 200.

        T3.3: Branches on resolve_device_policy(purpose). CPU purposes
        (embedding, rerank) skip GPU pre-flight and load on CPU.

        T3.1: GPU-only degradation ladder — if VRAM is tight, shrink n_ctx
        first (step 1), then n_batch (step 2). Never CPU offload.

        [10.6] Held under _load_lock — concurrent calls return False immediately.
        [10.5] Pre-flight resource check before spawning subprocess.
        [10.7] Starts watchdog task after successful load.
        """
        # ── Kill any orphaned llama-server processes before starting ──
        kill_orphan_servers()

        # [10.6] Concurrent load guard
        lock = self._get_load_lock()
        if lock.locked():
            logger.warning(
                "[LocalModelManager] Load already in progress — rejecting concurrent request"
            )
            if progress_cb:
                try:
                    await progress_cb(
                        {
                            "phase": "error",
                            "pct": 0,
                            "msg": "Load already in progress — wait for current load to complete",
                        }
                    )
                except Exception:
                    pass
            return False

        async with lock:
            self._stop_watchdog()  # cancel any existing watchdog
            await self.unload_model()
            self._invalidate_hw_cache()  # VRAM state will change during load

            # Resolve requested profile; may fall back if the fork isn't
            # installed and the profile demands it.
            profile = self._resolve_profile_for_environment(profile)
            params = self.get_profile_params(profile, custom_params or {})

            # Parse metadata early so preflight check can use layer count for
            # accurate partial-offload VRAM estimation.
            model_meta = self.parse_gguf_metadata(Path(model_path))
            # Track meta for ConfigCache corrections (REQ-5). Only used by
            # record_tps after a successful load; harmless if load fails.
            self._current_model_meta = model_meta
            self._current_purpose = purpose

            # REQ-5: consult ConfigCache for a known-good starting config. A
            # previous run's TPS correction (record_tps) lands here and is used
            # as the starting point for THIS load — never the running one.
            config_source = "profile"
            try:
                cached = self._config_cache.get(
                    model_path, model_meta, self.get_hardware_info()
                )
                if cached is not None:
                    params["n_ctx"] = cached.config.get("n_ctx", params["n_ctx"])
                    params["n_batch"] = cached.config.get("n_batch", params["n_batch"])
                    config_source = "cache"
                    logger.info(
                        f"[LocalModelManager] using cached config "
                        f"(n_ctx={params['n_ctx']}, measured_tps="
                        f"{cached.measured_tps}) as known-good start"
                    )
                elif not custom_params and profile == "balanced":
                    # REQ-1: no known-good cache and no user override → DERIVE the
                    # optimal config from model + hardware. This is the primary
                    # path; PROFILES remain available only as explicit overrides.
                    try:
                        hw = self.get_hardware_info()
                        derived = self.derive_config(
                            model_meta,
                            vram_budget_gb=hw.get("vram_free_gb", 0.0),
                        )
                        params["n_ctx"] = derived["n_ctx"]
                        params["n_batch"] = derived["n_batch"]
                        params["n_gpu_layers"] = derived["n_gpu_layers"]
                        config_source = "derived"
                        logger.info(
                            f"[LocalModelManager] derived config (source=derived): "
                            f"n_ctx={params['n_ctx']}, n_batch={params['n_batch']}, "
                            f"est_vram={derived['vram_est_gb']:.1f}GB, "
                            f"exp_tps={derived['expected_tps']:.1f}"
                        )
                    except Exception as exc:
                        logger.warning(
                            f"[LocalModelManager] derivation failed, using profile: {exc}"
                        )
            except Exception as exc:
                logger.debug(f"[LocalModelManager] cache consult skipped: {exc}")

            # T6.1: log the resolved load config with its source for observability.
            logger.info(
                f"[LocalModelManager] load config source={config_source} "
                f"purpose={purpose} n_ctx={params.get('n_ctx')} "
                f"n_gpu_layers={params.get('n_gpu_layers')} "
                f"n_batch={params.get('n_batch')}"
            )

            # [10.5] Pre-flight resource check — fail fast before spawning
            preflight_error = self._preflight_resource_check(
                model_path, params, model_meta, purpose=purpose
            )

            # T3.1: Degradation ladder — if pre-flight fails, try shrinking n_ctx
            # then n_batch. Never CPU offload.
            if preflight_error:
                policy = resolve_device_policy(purpose)
                if policy.device == "gpu" and policy.ladder:
                    degraded_params = self._degrade_config(
                        params, model_meta, purpose=purpose
                    )
                    if degraded_params is not None:
                        # Retry pre-flight with degraded config
                        retry_error = self._preflight_resource_check(
                            model_path, degraded_params, model_meta, purpose=purpose
                        )
                        if retry_error is None:
                            logger.info(
                                f"[LocalModelManager] Degradation succeeded: "
                                f"n_ctx={degraded_params.get('n_ctx')} "
                                f"n_batch={degraded_params.get('n_batch')}"
                            )
                            params = degraded_params
                            preflight_error = None
                        else:
                            logger.warning(
                                f"[LocalModelManager] Degradation failed: {retry_error}"
                            )
                            preflight_error = retry_error
            if preflight_error:
                logger.error(
                    f"[LocalModelManager] Pre-flight failed: {preflight_error}"
                )
                if progress_cb:
                    try:
                        await progress_cb(
                            {"phase": "error", "pct": 0, "msg": preflight_error}
                        )
                    except Exception:
                        pass
                return False

            # Detect MTP-capable models; they require compiled llama-server
            is_mtp = (
                model_meta.get("is_mtp", False)
                or "mtp" in Path(model_path).name.lower()
            )
            force_server = params.get("force_subprocess", False) or is_mtp

            if is_mtp and self._inprocess_enabled():
                logger.info(
                    f"[LocalModelManager] MTP model detected ({Path(model_path).name}); "
                    f"routing to compiled llama-server subprocess for speculative decoding."
                )

            # RotorQuant / ternary GGUFs (e.g. Bonsai 27B dspark) require the
            # llama-cpp-turboquant fork server — the in-process binding (stock
            # llama_cpp_python) cannot load them. Force the server path.
            is_rotorquant = self._detect_quantization(model_path) == "rotorquant"
            if is_rotorquant:
                force_server = True
                logger.info(
                    f"[LocalModelManager] RotorQuant model detected "
                    f"({Path(model_path).name}); routing to fork server."
                )
                # Override cache types for RotorQuant's planar3 KV cache.
                params["cache_type_k"] = "planar3"
                params["cache_type_v"] = "f16"

            # Bonsai-family low-bit models (Q1_0 / Q2_0 binary/ternary) use
            # non-standard quantization formats that the stock llama_cpp_python
            # binding cannot load. Detect them by architecture or naming and
            # route directly to the server (PrismML fork), bypassing in-process.
            _is_bonsai = False
            if not force_server:
                _name = Path(model_path).name.lower()
                if any(tag in _name for tag in ("q1_0", "q2_0", "bonsai")):
                    _is_bonsai = True
                elif model_meta.get("general.file_type", 0) in (1, 2, 3):
                    # GGUF file types 1-3 correspond to Q1_0 / Q2_0 etc.
                    _is_bonsai = True
            if _is_bonsai:
                force_server = True
                logger.info(
                    f"[LocalModelManager] Bonsai low-bit model detected "
                    f"({Path(model_path).name}); routing to PrismML server."
                )

            # ── In-process path (preferred, but NOT for MTP / RotorQuant ─)
            inproc_ok = False
            if self._inprocess_enabled() and not force_server:
                self._current_profile = profile
                ok = await self._load_inprocess(
                    model_path, params, progress_cb=progress_cb
                )
                if ok:
                    filename = Path(model_path).name
                    self.save_model_settings(
                        filename,
                        {
                            "last_profile": profile,
                            "last_ctx": params.get("n_ctx", 8192),
                            "last_gpu_layers": params.get("n_gpu_layers", -1),
                        },
                    )
                    self._invalidate_hw_cache()
                    return True
                # In-process failed — fall back to server subprocess (the
                # stock python binding may not support this model format, e.g.
                # Bonsai Q1_0 binary tensors or RotorQuant ternary tensors).
                logger.warning(
                    f"[LocalModelManager] In-process load failed for "
                    f"{Path(model_path).name}; falling back to server."
                )

            # ── Subprocess path (MTP, RotorQuant, or in-process fallback) ───
            cmd = self._build_server_cmd(model_path, params, is_mtp=is_mtp)
            logger.info(f"[LocalModelManager] Starting llama-server: {' '.join(cmd)}")

            loop = asyncio.get_running_loop()

            with self._lock:
                try:
                    self._process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,  # line-buffered so we get progress lines as they arrive
                        # Set CWD to the server binary's parent so the Windows
                        # DLL loader finds CUDA runtime DLLs shipped alongside
                        # the server (e.g. PrismML's cublas64_12.dll, etc.).
                        cwd=str(Path(cmd[0]).parent),
                    )
                    self._current_model_path = model_path
                    self._current_profile = profile
                    self._current_params = (
                        params  # [10.9] track for hot-apply comparison
                    )
                except FileNotFoundError:
                    logger.error(
                        "[LocalModelManager] llama-cpp-python not installed or python not found"
                    )
                    return False

            # ── Background thread reads stdout and pushes parsed events to queue ──
            progress_queue: asyncio.Queue = asyncio.Queue()

            def _read_stdout() -> None:
                try:
                    proc = self._process
                    if proc is None or proc.stdout is None:
                        return
                    for raw_line in proc.stdout:
                        line = raw_line.rstrip()
                        if not line:
                            continue
                        logger.debug(f"[llama-server] {line}")
                        event = self._parse_load_progress(line)
                        if event:
                            # Accumulate MTP metrics in background thread
                            if event.get("phase") == "metrics":
                                mtype = event.get("type")
                                val = event.get("value", 0)
                                if mtype == "mtp_draft_tokens":
                                    self._mtp_draft_tokens_total += val
                                elif mtype == "mtp_accepted":
                                    self._mtp_accepted_total += val
                                    # Compute rolling acceptance rate
                                    total = self._mtp_draft_tokens_total
                                    if total > 0:
                                        rate = self._mtp_accepted_total / total
                                        self._mtp_acceptance_window.append(rate)
                                        if len(self._mtp_acceptance_window) > 20:
                                            self._mtp_acceptance_window.pop(0)
                                        logger.info(
                                            f"[LocalModelManager] MTP acceptance: "
                                            f"{self._mtp_accepted_total}/{total} = {rate:.1%} "
                                            f"(rolling {sum(self._mtp_acceptance_window) / len(self._mtp_acceptance_window):.1%})"
                                        )
                            else:
                                loop.call_soon_threadsafe(
                                    progress_queue.put_nowait, event
                                )
                except Exception as exc:
                    logger.debug(f"[LocalModelManager] stdout reader exited: {exc}")
                finally:
                    loop.call_soon_threadsafe(
                        progress_queue.put_nowait, None
                    )  # sentinel

            reader = threading.Thread(
                target=_read_stdout, daemon=True, name="llm-stdout-reader"
            )
            reader.start()

            # ── Async wait loop — drain progress queue + poll for server ready ──
            # Poll with exponential backoff: starts at 1 s, doubles each miss up to 8 s.
            # This prevents 2 HTTP requests/sec thrashing the event loop during a 3-min load.
            deadline = (
                loop.time() + 180.0
            )  # 3 min max (large models on slow HW need time)
            ready = False
            last_pct = 0
            poll_interval = 1.0  # seconds; grows with backoff

            async with httpx.AsyncClient(timeout=2.0) as client:
                while loop.time() < deadline:
                    if not self.is_loaded():
                        break  # process died

                    # Drain any queued progress events before polling health
                    while True:
                        try:
                            event = progress_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        if event is None:
                            break  # stdout EOF
                        if progress_cb and event.get("pct", 0) > last_pct:
                            last_pct = event["pct"]
                            try:
                                await progress_cb(event)
                            except Exception:
                                pass

                    # Poll health endpoint
                    for path in ("/health", "/v1/models"):
                        try:
                            r = await client.get(f"http://127.0.0.1:{self.PORT}{path}")
                            if r.status_code == 200:
                                ready = True
                                break
                        except Exception:
                            pass

                    if ready:
                        break
                    await asyncio.sleep(poll_interval)
                    # Exponential backoff: 1 s → 2 s → 4 s → 8 s (cap) per missed poll
                    poll_interval = min(poll_interval * 2, 8.0)

            if ready:
                filename = Path(model_path).name
                self.save_model_settings(
                    filename,
                    {
                        "last_profile": profile,
                        "last_ctx": params.get("n_ctx", 8192),
                        "last_gpu_layers": params.get("n_gpu_layers", -1),
                    },
                )
                self._invalidate_hw_cache()  # refresh VRAM after model occupies GPU
                # [10.7] Start watchdog — detects subprocess death after load
                self._watchdog_task = asyncio.ensure_future(
                    self._run_watchdog(crash_cb=crash_cb)
                )
                logger.info(f"[LocalModelManager] Model ready at {self.ENDPOINT}")
            else:
                logger.error(
                    "[LocalModelManager] Timed out waiting for server to start"
                )
                await self.unload_model()
            return ready

    def _degrade_config(
        self,
        params: Dict[str, Any],
        model_meta: Dict[str, Any],
        purpose: str = "chat",
    ) -> Optional[Dict[str, Any]]:
        """
        T3.1: Degradation ladder for GPU-only models.

        When VRAM is tight, shrink n_ctx first (step 1 of ladder),
        then n_batch (step 2). Never CPU offload — n_gpu_layers stays -1.

        Uses derive_config() to binary-search the largest n_ctx that fits
        in the GPU VRAM budget. If even MIN_CTX doesn't fit, returns a
        last-resort config with MIN_CTX and n_batch=256.

        Args:
            params: Original inference params (n_ctx, n_gpu_layers, n_batch).
            model_meta: Parsed GGUF metadata.
            purpose: Model purpose ("chat", "tool", "embedding", "rerank").

        Returns:
            Degraded params dict, or None if degradation is not applicable
            (e.g. CPU purpose or no VRAM budget).
        """
        policy = resolve_device_policy(purpose)
        if policy.device != "gpu" or not policy.ladder:
            return None

        hw = self.get_hardware_info()
        vram_budget = hw.get("vram_free_gb", 0.0) * 0.92  # 8% safety margin

        if vram_budget <= 0:
            return None

        # Use derive_config to find the largest n_ctx that fits in VRAM
        config = self.derive_config(
            model_meta,
            target_tps=policy.throughput_target or TARGET_TPS,
            base_tps=None,
            vram_budget_gb=vram_budget,
        )

        # Build degraded params — D-2: n_gpu_layers ALWAYS -1
        degraded = dict(params)
        degraded["n_ctx"] = config["n_ctx"]
        degraded["n_gpu_layers"] = -1
        degraded["n_batch"] = config["n_batch"]

        # T6.1: log the degradation step with its reason (VRAM tight → ctx→batch).
        logger.info(
            f"[LocalModelManager] degradation (reason=VRAM tight, GPU-only ladder): "
            f"n_ctx {params.get('n_ctx')} -> {degraded['n_ctx']}, "
            f"n_batch {params.get('n_batch')} -> {degraded['n_batch']}, "
            f"n_gpu_layers stays -1"
        )

        return degraded

    def _resolve_profile_for_environment(self, profile: str) -> str:
        """If the requested profile demands a fork we don't have, fall back
        to a safe default and log a warning. No-op for profiles that don't
        declare ``requires_fork``.

        Note: the RotorQuant fork is delivered as a standalone llama-server
        binary (llama.cpp-turboquant/build/bin/llama-server), NOT as the
        in-process llama_cpp Python binding. So availability is checked via
        the fork server binary, not ``_rotorquant_available`` (which probes
        the Python binding).
        """
        cfg = PROFILES.get(profile)
        if not cfg:
            return profile
        needed = cfg.get("requires_fork")
        if not needed:
            return profile
        if needed == "llama-cpp-turboquant":
            fork_bin = (
                IRISVOICE_ROOT / "llama.cpp-turboquant" / "build" / "bin" / "llama-server.exe"
                if sys.platform == "win32"
                else IRISVOICE_ROOT / "llama.cpp-turboquant" / "build" / "bin" / "llama-server"
            )
            if not fork_bin.is_file():
                logger.warning(
                    f"[LocalModelManager] Profile '{profile}' requires the "
                    f"llama-cpp-turboquant fork (RotorQuant); server binary not "
                    f"found at {fork_bin}. Falling back to 'performance'. "
                    f"See docs/rotorquant_build.md."
                )
                return "performance"
        return profile

    async def unload_model(self) -> bool:
        # Kill any orphaned llama-server processes to free VRAM
        kill_orphan_servers()

        # [10.7] Cancel watchdog before stopping subprocess
        self._stop_watchdog()
        self._stop_progress_heartbeat()

        # ── In-process path: drop the Llama instance and let GC free VRAM ──
        if self._llm is not None:
            with self._inference_lock:
                self._llm = None
            gc.collect()
            with self._lock:
                self._current_model_path = None
                self._current_params = {}
            self._invalidate_hw_cache()
            logger.info("[LocalModelManager] In-process model unloaded")
            return True

        # ── Legacy subprocess path ─────────────────────────────────────────
        with self._lock:
            if self._process is None:
                return True
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()
            except Exception as e:
                logger.warning(f"[LocalModelManager] Error stopping subprocess: {e}")
            finally:
                self._process = None
                self._current_model_path = None
                self._current_params = {}  # [10.9] reset param tracking
        self._invalidate_hw_cache()
        logger.info("[LocalModelManager] Model unloaded")
        return True

    async def health_check(self) -> bool:
        # In-process: simply check the Llama instance exists. Subprocess:
        # probe HTTP endpoints as before.
        if self._llm is not None:
            return True
        for path in ("/health", "/v1/models"):
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    r = await client.get(f"http://127.0.0.1:{self.PORT}{path}")
                    if r.status_code == 200:
                        return True
            except Exception:
                pass
        return False

    def is_loaded(self) -> bool:
        # In-process wins: if a Llama instance is held we're loaded.
        if self._llm is not None:
            return True
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def get_status(self) -> Dict[str, Any]:
        loaded = self.is_loaded()
        inprocess = self._llm is not None
        return {
            "loaded": loaded,
            "model_path": self._current_model_path if loaded else None,
            "profile": self._current_profile if loaded else None,
            # REQ-3 AC1 / CT-L7: expose the REAL configured context of the
            # loaded model — the authoritative source for context-window
            # resolution (overrides any table entry).
            "n_ctx": self._current_params.get("n_ctx") if loaded else None,
            "purpose": self._current_purpose if loaded else None,
            # Endpoint is only meaningful when we're running the subprocess
            # HTTP server; in-process has no URL.
            "endpoint": None if inprocess else (self.ENDPOINT if loaded else None),
            "pid": None
            if inprocess
            else (self._process.pid if loaded and self._process else None),
            "inprocess": inprocess,
            "rotorquant": self._rotorquant_available,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Subprocess command builder
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _find_llama_server_binary() -> Optional[str]:
        """
        Locate ik_llama.cpp's llama-server binary.
        Priority: IK_LLAMA_SERVER env var → PATH → common install locations.
        Returns full path string, or None if not found.
        """
        import shutil

        # 1. Explicit override
        env_path = os.environ.get("IK_LLAMA_SERVER")
        if env_path and Path(env_path).is_file():
            return env_path
        # 1b. Tauri-bundled binary (the widget ships llama-server via
        # externalBin). Resolved next to the running backend executable so
        # the vision model / legacy subprocess path work out-of-the-box.
        try:
            from backend.binaries import find_binary as _find_bundled

            bundled = _find_bundled("llama-server", env_var="IRIS_LLAMA_SERVER")
            if bundled and Path(bundled).is_file():
                return bundled
        except Exception:
            pass
        # 2. PATH lookup
        found = shutil.which("llama-server")
        if found:
            return found
        # 3. Common install locations — platform-aware
        if sys.platform == "win32":
            candidates = [
                # PrismML fork — supports Bonsai Q1_0 (1-bit) and Q2_0
                # (ternary) on CUDA. Preferred for all Bonsai-family models.
                IRISVOICE_ROOT
                / "llama.cpp-prismml"
                / "bin"
                / "llama-server.exe",
                # RotorQuant / ternary-quantized models (e.g. DSpark drafter)
                # require the llama-cpp-turboquant fork.
                IRISVOICE_ROOT
                / "llama.cpp-turboquant"
                / "build"
                / "bin"
                / "llama-server.exe",
                Path.home() / "ik_llama.cpp" / "build" / "bin" / "llama-server.exe",
                Path.home() / "llama.cpp" / "build" / "bin" / "llama-server.exe",
                IRISVOICE_ROOT
                / "llama.cpp"
                / "build"
                / "bin"
                / "Release"
                / "llama-server.exe",
                IRISVOICE_ROOT / "llama.cpp" / "build" / "bin" / "llama-server.exe",
                Path("C:/tools/llama-server.exe"),
                Path("C:/llama/llama-server.exe"),
            ]
        else:
            # Linux / macOS
            candidates = [
                IRISVOICE_ROOT
                / "llama.cpp-turboquant"
                / "build"
                / "bin"
                / "llama-server",
                Path.home() / "ik_llama.cpp" / "build" / "bin" / "llama-server",
                Path.home() / "llama.cpp" / "build" / "bin" / "llama-server",
                IRISVOICE_ROOT / "llama.cpp" / "build" / "bin" / "llama-server",
                Path("/usr/local/bin/llama-server"),
                Path("/usr/bin/llama-server"),
                Path("/opt/llama/bin/llama-server"),
            ]
        for c in candidates:
            if c.is_file():
                return str(c)
        return None

    def _detect_quantization(self, model_path: str) -> str:
        """
        Inspect a GGUF's metadata to determine its quantization family.
        Returns one of: 'rotorquant' (RotorQuant/ternary planar KV cache),
        'standard' (normal k-quants / f16 / etc.), or 'unknown'.
        """
        try:
            meta = self.parse_gguf_metadata(Path(model_path))
            qv = str(meta.get("general.quantization_version", "")).lower()
            # Some GGUFs store architecture under 'architecture' rather than
            # 'general.architecture' — check both.
            arch = str(meta.get("general.architecture") or meta.get("architecture") or "").lower()
            # RotorQuant GGUFs use the 'dspark' architecture (ternary/RotorQuant)
            # or advertise quantization_version 3 / planar KV-cache types.
            if "rotor" in qv or "ternary" in qv or qv in ("3", "planar3"):
                return "rotorquant"
            if arch in ("dspark", "dspark_v1", "dspark_gguf"):
                return "rotorquant"
            # Fallback: scan tensor type strings for planar/rotor markers.
            for k, v in meta.items():
                vs = str(v).lower()
                if "planar" in vs or "rotor" in vs or "turbo" in vs:
                    return "rotorquant"
        except Exception:
            pass
        return "standard"

    def _select_server_binary(self, model_path: str) -> Optional[str]:
        """
        Model-aware server selector ("sensor"): pick the correct llama-server
        build for the model being loaded. RotorQuant/ternary GGUFs require the
        llama-cpp-turboquant fork; everything else uses the stock server.
        Returns the binary path, or None if no server binary is available.
        """
        quant = self._detect_quantization(model_path)
        if quant == "rotorquant":
            # Prefer the in-tree fork build for RotorQuant models.
            fork = (
                IRISVOICE_ROOT / "llama.cpp-turboquant" / "build" / "bin" / "llama-server.exe"
                if sys.platform == "win32"
                else IRISVOICE_ROOT / "llama.cpp-turboquant" / "build" / "bin" / "llama-server"
            )
            if fork.is_file():
                return str(fork)
            # No fork available -> caller must fail loud (no CPU fallback).
            return None
        return self._find_llama_server_binary()

    @staticmethod
    def _find_llama_python() -> str:
        """
        Find the best Python interpreter for running llama_cpp.server.
        Prefers one with CUDA support; falls back to sys.executable.

        Logic:
          1. Check sys.executable (current interpreter) for CUDA support
          2. Check IRIS_LLAMA_PYTHON env var override
          3. Try py -3.12 (Python 3.12 has pre-built CUDA wheels)
          4. Fall back to sys.executable regardless
        """

        def _has_cuda(python_exe: str) -> bool:
            try:
                result = subprocess.run(
                    [
                        python_exe,
                        "-c",
                        "import llama_cpp; exit(0 if llama_cpp.llama_supports_gpu_offload() else 1)",
                    ],
                    capture_output=True,
                    timeout=10,
                )
                return result.returncode == 0
            except Exception:
                return False

        def _has_llama(python_exe: str) -> bool:
            try:
                result = subprocess.run(
                    [python_exe, "-c", "import llama_cpp"],
                    capture_output=True,
                    timeout=10,
                )
                return result.returncode == 0
            except Exception:
                return False

        # Env override
        env_py = os.environ.get("IRIS_LLAMA_PYTHON")
        if env_py and Path(env_py).is_file():
            return env_py

        # Check current interpreter first (fast path)
        if _has_cuda(sys.executable):
            return sys.executable

        # Try to find a Python 3.12 with CUDA/llama support
        import shutil

        if sys.platform == "win32":
            # Windows: use py launcher
            py_candidates: List[str] = []
            py_launcher = shutil.which("py")
            if py_launcher:
                try:
                    result = subprocess.run(
                        [
                            py_launcher,
                            "-3.12",
                            "-c",
                            "import sys; print(sys.executable)",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        py_candidates.append(result.stdout.strip())
                except Exception:
                    pass
        else:
            # Linux/macOS: check versioned executables in PATH
            py_candidates = []
            for name in ("python3.12", "python3.11", "python3"):
                found_py = shutil.which(name)
                if found_py and found_py != sys.executable:
                    py_candidates.append(found_py)

        for py312 in py_candidates:
            if _has_cuda(py312):
                logger.info(f"[LocalModelManager] Using Python with CUDA: {py312}")
                return py312
            elif _has_llama(py312):
                logger.info(f"[LocalModelManager] Using Python (no CUDA): {py312}")
                return py312

        # Fall back to current interpreter even without CUDA
        return sys.executable

    def _build_server_cmd(
        self, model_path: str, params: Dict[str, Any], is_mtp: bool = False
    ) -> List[str]:
        """
        Build the inference server command.
        Prefers ik_llama.cpp's llama-server binary when available.
        Falls back to python -m llama_cpp.server (llama-cpp-python).

        ik_llama.cpp flags use hyphens and different names:
          --ctx-size instead of --n_ctx
          --batch-size instead of --n_batch
          --n-gpu-layers instead of --n_gpu_layers
          --threads instead of --n_threads
        """
        # Model-aware server selection: RotorQuant/ternary GGUFs require the
        # llama-cpp-turboquant fork; everything else uses the stock server.
        llama_server = self._select_server_binary(str(model_path))
        if llama_server is None:
            # No server binary can serve this model (e.g. RotorQuant model but
            # the fork build is missing). Fail loud — never fall back to CPU.
            raise RuntimeError(
                "No compatible llama-server binary available for this model. "
                "RotorQuant/ternary models require the llama-cpp-turboquant "
                "fork build (llama.cpp-turboquant/build/bin/llama-server)."
            )

        if llama_server:
            # ── ik_llama.cpp / compiled llama-server ───────────────────────
            logger.info(
                f"[LocalModelManager] Using compiled llama-server: {llama_server}"
            )
            cmd = [
                llama_server,
                "--model",
                str(model_path),
                "--port",
                str(self.PORT),
                "--host",
                "127.0.0.1",
                "--threads",
                str(cpu_count()),
            ]
            # GPU-ONLY: local models must run on the GPU. Never allow a CPU
            # offload (n_gpu_layers == 0). Default to full offload (-1) if the
            # profile omitted it, and reject any explicit 0.
            n_gpu = params.get("n_gpu_layers")
            if n_gpu is None or n_gpu == 0:
                if n_gpu == 0:
                    logger.warning(
                        "[LocalModelManager] Rejecting CPU offload (n_gpu_layers=0) "
                        "for local model; forcing full GPU offload."
                    )
                n_gpu = -1
            cmd += ["--n-gpu-layers", str(n_gpu)]
            if params.get("n_ctx"):
                cmd += ["--ctx-size", str(params["n_ctx"])]
            if params.get("n_batch"):
                cmd += ["--batch-size", str(params["n_batch"])]
            if params.get("flash_attn"):
                cmd += ["--flash-attn", "on"]
            if params.get("cache_type_k"):
                cmd += ["--cache-type-k", params["cache_type_k"]]
            if params.get("cache_type_v"):
                cmd += ["--cache-type-v", params["cache_type_v"]]
            if params.get("use_mmap", True):
                cmd += ["--mmap"]
            if params.get("keep_model_in_memory"):
                cmd += ["--mlock"]
            if params.get("offload_kv_cache"):
                cmd += ["--kv-offload"]
            else:
                cmd += ["--no-kv-offload"]
            seed = params.get("seed")
            if seed is not None and seed != -1:
                cmd += ["--seed", str(int(seed))]

            # ── MTP speculative decoding flags ─────────────────────────────
            if is_mtp:
                cmd += ["--spec-type", "draft-mtp"]
                mtp_n_max = params.get("mtp_n_max", 3)
                cmd += ["--spec-draft-n-max", str(mtp_n_max)]
                mtp_p_min = params.get("mtp_p_min")
                if mtp_p_min is not None:
                    cmd += ["--spec-draft-p-min", str(mtp_p_min)]
                logger.info(
                    f"[LocalModelManager] MTP enabled: --spec-type draft-mtp "
                    f"--spec-draft-n-max {mtp_n_max}"
                )
        else:
            # ── llama-cpp-python fallback ──────────────────────────────────
            # Flag reference (llama_cpp.server v0.3+):
            #   --type_k / --type_v expect GGML_TYPE integer (F16=1, Q4_0=2, Q8_0=8, Q4_K=12)
            #   --offload_kqv  bool  (default: True)
            #   --flash_attn   bool
            _GGML_TYPE = {
                "f32": 0,
                "f16": 1,
                "bf16": 30,
                "q4_0": 2,
                "q4_1": 3,
                "q5_0": 6,
                "q5_1": 7,
                "q8_0": 8,
                "q8_1": 9,
                "q2_k": 10,
                "q3_k": 11,
                "q3_k_s": 11,
                "q3_k_m": 11,
                "q4_k": 12,
                "q4_k_s": 12,
                "q4_k_m": 12,
                "q5_k": 13,
                "q5_k_s": 13,
                "q5_k_m": 13,
                "q6_k": 14,
                "q8_k": 15,
            }
            python_exe = self._find_llama_python()
            logger.info(
                f"[LocalModelManager] llama-server not found; using {python_exe} -m llama_cpp.server"
            )
            cmd = [
                python_exe,
                "-m",
                "llama_cpp.server",
                "--model",
                str(model_path),
                "--port",
                str(self.PORT),
                "--host",
                "127.0.0.1",
                "--n_threads",
                str(cpu_count()),
            ]
            n_gpu = params.get("n_gpu_layers")
            if n_gpu is not None:
                cmd += ["--n_gpu_layers", str(n_gpu)]
            if params.get("n_ctx"):
                cmd += ["--n_ctx", str(params["n_ctx"])]
            if params.get("n_batch"):
                cmd += ["--n_batch", str(params["n_batch"])]
            if params.get("flash_attn"):
                cmd += ["--flash_attn", "true"]
            if params.get("cache_type_k"):
                type_int = _GGML_TYPE.get(params["cache_type_k"].lower(), 1)
                cmd += ["--type_k", str(type_int)]
            if params.get("cache_type_v"):
                type_int = _GGML_TYPE.get(params["cache_type_v"].lower(), 1)
                cmd += ["--type_v", str(type_int)]
            if params.get("use_mmap"):
                cmd += ["--use_mmap", "true"]
            if params.get("keep_model_in_memory"):
                cmd += ["--use_mlock", "true"]
            if params.get("offload_kv_cache"):
                cmd += ["--offload_kqv", "true"]
            seed = params.get("seed")
            if seed is not None and seed != -1:
                cmd += ["--seed", str(int(seed))]

        return cmd

    async def _wait_for_ready(self, timeout: float = 90.0) -> bool:
        # Probe both /health (ik_llama.cpp) and /v1/models (llama-cpp-python)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        async with httpx.AsyncClient(timeout=2.0) as client:
            while loop.time() < deadline:
                if not self.is_loaded():
                    return False
                for path in ("/health", "/v1/models"):
                    try:
                        r = await client.get(f"http://127.0.0.1:{self.PORT}{path}")
                        if r.status_code == 200:
                            return True
                    except Exception:
                        pass
                await asyncio.sleep(0.75)
        return False

    # ─────────────────────────────────────────────────────────────────────────
    # HuggingFace download
    # ─────────────────────────────────────────────────────────────────────────

    async def download_model(
        self, repo_id: str, filename: str, dest_dir: Optional[Path] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Download a GGUF file from HuggingFace Hub.
        Yields progress dicts: {status, progress_pct, bytes_downloaded, total_bytes, error?}
        """
        if not HF_HUB_AVAILABLE:
            yield {
                "status": "error",
                "error": "huggingface_hub not installed",
                "progress_pct": 0,
            }
            return

        dest = (dest_dir or self.MODELS_DIR) / filename
        if dest.exists():
            yield {"status": "complete", "progress_pct": 100, "path": str(dest)}
            return

        yield {"status": "starting", "progress_pct": 0, "filename": filename}

        loop = asyncio.get_running_loop()
        try:
            path = await loop.run_in_executor(
                None,
                lambda: hf_hub_download(
                    repo_id=repo_id,
                    filename=filename,
                    local_dir=str(dest_dir or self.MODELS_DIR),
                ),
            )
            yield {
                "status": "complete",
                "progress_pct": 100,
                "filename": filename,
                "path": path,
            }
        except Exception as e:
            yield {
                "status": "error",
                "error": str(e),
                "progress_pct": 0,
                "filename": filename,
            }

    # ─────────────────────────────────────────────────────────────────────────
    # Per-model settings persistence
    # ─────────────────────────────────────────────────────────────────────────

    def load_model_settings(self) -> Dict[str, Any]:
        if not self.SETTINGS_FILE.exists():
            return {}
        try:
            return json.loads(self.SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_model_settings(self, filename: str, settings: Dict[str, Any]) -> None:
        all_settings = self.load_model_settings()
        existing = all_settings.get(filename, {})
        existing.update(settings)
        all_settings[filename] = existing
        try:
            self.SETTINGS_FILE.write_text(
                json.dumps(all_settings, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"[LocalModelManager] Could not save model settings: {e}")

    def toggle_pin(self, filename: str) -> bool:
        """Toggle pin state for a model. Returns new pin state."""
        settings = self.load_model_settings()
        current = settings.get(filename, {})
        new_pin = not current.get("pinned", False)
        self.save_model_settings(filename, {"pinned": new_pin})
        return new_pin

    # ─────────────────────────────────────────────────────────────────────────
    # Cleanup
    # ─────────────────────────────────────────────────────────────────────────

    def _register_cleanup(self) -> None:
        atexit.register(self._sync_cleanup)
        try:
            signal.signal(signal.SIGTERM, lambda *_: self._sync_cleanup())
        except (OSError, ValueError):
            pass  # SIGTERM not available on Windows console

    def _sync_cleanup(self) -> None:
        # In-process instance — best-effort drop. Python's GC will free the
        # CUDA context when the interpreter exits even if we skip this.
        if self._llm is not None:
            try:
                self._llm = None
                gc.collect()
                logger.info("[LocalModelManager] In-process model released on shutdown")
            except Exception:
                pass
        with self._lock:
            if self._process is not None:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=3)
                except Exception:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
                self._process = None
                logger.info("[LocalModelManager] Subprocess killed on shutdown")


# ─────────────────────────────────────────────────────────────────────────
# Helpers + OpenAI-client adapter for the in-process path
# ─────────────────────────────────────────────────────────────────────────

# openai-client kwargs that aren't meaningful to Llama.create_chat_completion,
# or that map differently. We strip these before handing kwargs to llama-cpp.
_OPENAI_ONLY_KWARGS = frozenset(
    {
        # "model" is required by openai; Llama already knows which weights are loaded.
        "model",
        # "extra_body" carries provider-specific hints like chat_template_kwargs.
        # Stock llama-cpp-python does not consume it; silently drop.
        "extra_body",
        # Timeouts are HTTP concerns.
        "timeout",
        # Not yet supported by our path.
        "user",
        "response_format",
        "logit_bias",
        "seed",  # Llama accepts via ctor, not per-call
    }
)


def _sanitise_completion_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Drop kwargs meaningful only to the OpenAI HTTP client; translate where
    straightforward. Returns a new dict — does not mutate input."""
    out: Dict[str, Any] = {}
    for k, v in kwargs.items():
        if k in _OPENAI_ONLY_KWARGS:
            continue
        # max_tokens=-1 is OpenAI shorthand for "no cap"; llama-cpp wants None.
        if k == "max_tokens" and v == -1:
            continue
        out[k] = v
    return out


def _wrap_chat_response(data: Dict[str, Any]) -> Any:
    """Convert a `Llama.create_chat_completion` dict into an attribute-access
    object tree so caller code can do `resp.choices[0].message.content` —
    matching the shape the kernel expects from the real openai Pydantic
    response.

    Tool calls are handled: each tool_call dict gets wrapped such that
    ``tc.id``, ``tc.function.name``, ``tc.function.arguments`` are all
    attribute-accessible, and ``tc.index`` is set so the kernel's
    accumulation loop (which works off stream-style indices) is happy.
    """

    def _wrap(obj: Any) -> Any:
        if isinstance(obj, dict):
            return SimpleNamespace(**{k: _wrap(v) for k, v in obj.items()})
        if isinstance(obj, list):
            return [_wrap(i) for i in obj]
        return obj

    wrapped = _wrap(data)

    # llama-cpp returns usage as a dict with prompt_tokens / completion_tokens
    # — the wrapping above turns it into a SimpleNamespace already. Nothing
    # extra to do on the non-streaming path.
    return wrapped


def _wrap_chat_chunk(chunk: Dict[str, Any]) -> Any:
    """Convert a streaming chunk dict into the object shape the kernel
    iterates over: ``chunk.choices[0].delta.content``,
    ``chunk.choices[0].delta.tool_calls[i].{index,id,function.name,function.arguments}``,
    ``chunk.choices[0].finish_reason``.
    """
    # llama-cpp chunk shape matches OpenAI closely; the generic wrapper works.
    wrapped = _wrap_chat_response(chunk)
    # Defensive: some llama-cpp builds emit choices[].delta without a
    # `content` attribute on empty deltas — ensure it's at least present.
    try:
        for ch in wrapped.choices:
            if not hasattr(ch, "delta"):
                ch.delta = SimpleNamespace(content=None, tool_calls=None)
            else:
                if not hasattr(ch.delta, "content"):
                    ch.delta.content = None
                if not hasattr(ch.delta, "tool_calls"):
                    ch.delta.tool_calls = None
    except Exception:
        pass
    return wrapped

    # Orphan process guard
    # ──────────────────────────────────────────────────────────────────


def kill_orphan_servers() -> None:
    """Kill any stray llama-server processes from previous sessions.

    Module-level function callable from LocalModelManager and
    SwarmInferenceManager. Uses taskkill (Windows) / pkill (Linux/Mac)
    to kill ALL llama-server processes by name, not just tracked ones.

    Prevents orphaned subprocesses from accumulating when:
    - A model load is interrupted (process spawned but never tracked)
    - Multiple APPLY clicks create overlapping subprocesses
    - The backend restarts but leaves child processes running
    """
    import subprocess as _sp
    import platform as _pf

    system = _pf.system().lower()
    try:
        if system == "windows":
            _sp.run(
                ["taskkill", "/F", "/IM", "llama-server.exe"],
                capture_output=True,
                timeout=10,
            )
            _sp.run(
                [
                    "taskkill",
                    "/F",
                    "/FI",
                    "WINDOWTITLE eq *llama_cpp.server*",
                    "/IM",
                    "python.exe",
                ],
                capture_output=True,
                timeout=10,
            )
        else:
            _sp.run(
                ["pkill", "-f", "llama-server"],
                capture_output=True,
                timeout=10,
            )
            _sp.run(
                ["pkill", "-f", "llama_cpp.server"],
                capture_output=True,
                timeout=10,
            )
    except Exception:
        pass  # best-effort; if kill fails there's nothing to do


class InProcessOpenAIAdapter:
    """Duck-types ``openai.OpenAI`` narrowly enough for the agent kernel's
    three call sites:

      client.chat.completions.create(**kwargs)          → non-streaming dict → wrapped obj
      client.chat.completions.create(..., stream=True)  → iterator of wrapped chunks

    All access patterns that the kernel uses on the returned object
    (``resp.choices[0].message.content``, ``resp.choices[0].message.tool_calls``,
    ``chunk.choices[0].delta.content``, ``chunk.choices[0].delta.tool_calls``,
    ``chunk.choices[0].finish_reason``, ``resp.usage.prompt_tokens``, etc.)
    go through ``_wrap_chat_response`` / ``_wrap_chat_chunk``.

    NOT a general-purpose OpenAI replacement — specifically targets the
    ``iris_local`` provider path in ``AgentKernel``. Other providers still
    use the real openai HTTP client.
    """

    def __init__(self, mgr: "LocalModelManager") -> None:
        self._mgr = mgr
        # openai-python style surface: client.chat.completions.create(...)
        self.chat = self
        self.completions = self

    def create(self, **kwargs) -> Any:
        if kwargs.get("stream"):
            return _WrappedStream(self._mgr.create_chat_completion_stream(**kwargs))
        raw = self._mgr.create_chat_completion(**kwargs)
        return _wrap_chat_response(raw)


class _WrappedStream:
    """Iterator over wrapped streaming chunks.

    Kept as a class so the kernel can ``for chunk in resp: ...`` — matching
    how the real openai client's stream object behaves.
    """

    def __init__(self, inner: Iterator[Dict[str, Any]]) -> None:
        self._inner = inner

    def __iter__(self) -> "_WrappedStream":
        return self

    def __next__(self) -> Any:
        raw = next(self._inner)
        return _wrap_chat_chunk(raw)


# ── Singleton ──────────────────────────────────────────────────────────────
_local_model_manager: Optional[LocalModelManager] = None
_manager_lock = threading.Lock()


def get_local_model_manager() -> LocalModelManager:
    global _local_model_manager
    if _local_model_manager is None:
        with _manager_lock:
            if _local_model_manager is None:
                _local_model_manager = LocalModelManager()
    return _local_model_manager
