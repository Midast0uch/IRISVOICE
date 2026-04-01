"""
LocalModelManager — GGUF model lifecycle manager for IRISVOICE v.3.

Runs llama-cpp-python in server mode as a subprocess on port 8082,
exposing an OpenAI-compatible API. GGUF brain models are NEVER
auto-loaded at startup — they only spawn when the user explicitly
selects a model from the ModelsScreen frontend.

Follows the same subprocess pattern as the vision model (port 8081)
defined in agent_config.yaml.
"""
import asyncio
import atexit
import io
import json
import logging
import os
import signal
import struct
import subprocess
import sys
import threading
from multiprocessing import cpu_count
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

# ── Hardware detection (import-guarded, matches audio/model_manager.py pattern) ──
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

TORCH_AVAILABLE = False
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    pass

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
    "Q2_K": 2.56,  "Q3_K_S": 3.0,  "Q3_K_M": 3.35, "Q3_K_L": 3.6,
    "Q4_0": 4.5,   "Q4_K_S": 4.37, "Q4_K_M": 4.85, "Q4_K": 4.85,
    "Q5_0": 5.5,   "Q5_K_S": 5.54, "Q5_K_M": 5.69, "Q5_K": 5.69,
    "Q6_K": 6.56,  "Q8_0": 8.5,    "F16": 16.0,     "F32": 32.0,
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
        "n_gpu_layers": -1,          # all layers on GPU — mandatory for 25+ tok/s
        "n_ctx": 32768,              # 32k context window
        "flash_attn": True,          # required: saves VRAM + faster attention
        "cache_type_k": "q8_0",     # compressed KV key cache
        "cache_type_v": "q8_0",     # compressed KV value cache
        "n_batch": 2048,             # max physical batch — fast prompt processing
        "offload_kv_cache": True,
        "unified_kv_cache": True,
        "keep_model_in_memory": True,
        "use_mmap": True,
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
        "n_ctx": 102400,             # ~100k context
        "flash_attn": True,          # mandatory at this context length
        "cache_type_k": "q4_0",     # Q4 KV cache — halves VRAM vs q8_0 at long ctx
        "cache_type_v": "q4_0",
        "n_batch": 2048,
        "offload_kv_cache": True,
        "unified_kv_cache": True,
        "keep_model_in_memory": True,
        "use_mmap": True,
    },
}

# Split GGUF filename pattern: model-00001-of-00003.gguf
_SPLIT_SUFFIX_PART = "-of-"


class LocalModelManager:
    """
    Manages GGUF model loading via llama-cpp-python server mode subprocess.
    Port 8082, OpenAI-compatible API.

    Loading contract:
      - NEVER auto-loads at startup
      - Only spawns subprocess when user calls load_model()
      - Registers atexit + SIGTERM cleanup to kill subprocess on backend exit
    """

    PORT = 8082
    ENDPOINT = f"http://127.0.0.1:{PORT}/v1"

    # ── Model scan directory resolution ─────────────────────────────────────
    # Priority: IRIS_MODELS_DIR env var → LM Studio default → IRIS fallback
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

    def __init__(self) -> None:
        # Always ensure the IRIS fallback dir exists for downloads
        (IRISVOICE_ROOT / "models" / "gguf").mkdir(parents=True, exist_ok=True)
        self._process: Optional[subprocess.Popen] = None
        self._current_model_path: Optional[str] = None
        self._current_profile: str = "balanced"
        self._lock = threading.Lock()
        # Metadata cache: key = "path::mtime" -> parsed GGUF metadata dict
        # Persists across calls — only re-parsed when file changes (mtime check)
        self._metadata_cache: Dict[str, Dict[str, Any]] = {}
        # Hardware info cache — invalidated on model load/unload (VRAM changes)
        self._hw_cache: Optional[Dict[str, Any]] = None
        self._hw_cache_time: float = 0.0
        self._register_cleanup()

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
            info["ram_total_gb"] = round(vm.total / (1024 ** 3), 1)

        if TORCH_AVAILABLE and torch.cuda.is_available():
            try:
                props = torch.cuda.get_device_properties(0)
                total = props.total_memory / (1024 ** 3)
                allocated = torch.cuda.memory_allocated(0) / (1024 ** 3)
                reserved = torch.cuda.memory_reserved(0) / (1024 ** 3)
                used = max(allocated, reserved)
                info.update({
                    "cuda_available": True,
                    "gpu_name": props.name,
                    "vram_total_gb": round(total, 1),
                    "vram_free_gb": round(max(0.0, total - used), 1),
                })
            except Exception as e:
                logger.warning(f"[LocalModelManager] VRAM query failed: {e}")
        # NOTE: No llama_cpp fallback here. Importing llama_cpp at this point
        # triggers CUDA driver initialization, which spikes memory at startup.
        # GPU detection via llama_cpp only happens when the user explicitly loads
        # a model (load_model → _build_server_cmd). Until then, cuda_available
        # stays False and the UI shows the "No GPU" placeholder — this is correct
        # because no inference is running yet.

        info["models_dir"] = str(self.MODELS_DIR)
        self._hw_cache = info
        self._hw_cache_time = _time.monotonic()
        return info

    # ─────────────────────────────────────────────────────────────────────────
    # Model scanning
    # ─────────────────────────────────────────────────────────────────────────

    def scan_models(self) -> List[Dict[str, Any]]:
        """
        Walk MODELS_DIR for *.gguf files.
        Groups split-shard files (model-00001-of-NNNNN.gguf) under one entry.
        Returns list of model dicts with metadata.
        """
        settings = self.load_model_settings()
        seen_bases: Dict[str, Dict[str, Any]] = {}  # base_name -> entry

        for gguf_path in sorted(self.MODELS_DIR.rglob("*.gguf")):
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
                seen_bases[base_stem]["shard_count"] = seen_bases[base_stem].get("shard_count", 1) + 1
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
                    logger.debug(f"[LocalModelManager] Could not parse GGUF header for {filename}: {e}")
                    meta = {}
                self._metadata_cache[cache_key] = meta

            size_gb = round(st.st_size / (1024 ** 3), 2)
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
                "loaded": self._current_model_path == str(gguf_path),
                "pinned": model_settings.get("pinned", False),
                "last_profile": model_settings.get("last_profile", "balanced"),
                "last_ctx": model_settings.get("last_ctx", 32768),
                "last_gpu_layers": model_settings.get("last_gpu_layers", -1),
                "shard_count": 1,
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

        GGUF format:
          magic (4 bytes) + version (uint32) + tensor_count (uint64) +
          metadata_kv_count (uint64) + kv pairs
        """
        meta: Dict[str, Any] = {}
        GGUF_MAGIC = b"GGUF"
        STRING_TYPE = 8
        UINT32_TYPE = 4
        UINT64_TYPE = 7

        def read_str(f: io.RawIOBase) -> str:
            length = struct.unpack("<Q", f.read(8))[0]
            return f.read(length).decode("utf-8", errors="replace")

        def read_value(f: io.RawIOBase, vtype: int) -> Any:
            if vtype == 4:    return struct.unpack("<I", f.read(4))[0]   # uint32
            elif vtype == 5:  return struct.unpack("<i", f.read(4))[0]   # int32
            elif vtype == 6:  return struct.unpack("<f", f.read(4))[0]   # float32
            elif vtype == 7:  return struct.unpack("<Q", f.read(8))[0]   # uint64
            elif vtype == 8:  return read_str(f)                          # string
            elif vtype == 10: return struct.unpack("<q", f.read(8))[0]   # int64
            elif vtype == 11: return struct.unpack("<d", f.read(8))[0]   # float64
            elif vtype == 1:  return struct.unpack("<?", f.read(1))[0]   # bool
            elif vtype == 2:  return struct.unpack("<B", f.read(1))[0]   # uint8
            elif vtype == 3:  return struct.unpack("<H", f.read(2))[0]   # uint16
            elif vtype == 9:
                # array: elem_type (uint32) + count (uint64) + elements
                elem_type = struct.unpack("<I", f.read(4))[0]
                count = struct.unpack("<Q", f.read(8))[0]
                return [read_value(f, elem_type) for _ in range(min(count, 16))]
            else:
                raise ValueError(f"Unknown GGUF value type: {vtype}")

        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != GGUF_MAGIC:
                return meta
            version = struct.unpack("<I", f.read(4))[0]
            if version not in (1, 2, 3):
                return meta
            _tensor_count = struct.unpack("<Q", f.read(8))[0]
            kv_count = struct.unpack("<Q", f.read(8))[0]

            arch = "unknown"
            for _ in range(min(kv_count, 256)):
                try:
                    key = read_str(f)
                    vtype = struct.unpack("<I", f.read(4))[0]
                    val = read_value(f, vtype)
                except Exception:
                    break

                if key == "general.architecture" and isinstance(val, str):
                    arch = val
                    meta["architecture"] = val
                elif key == "general.parameter_count" and isinstance(val, int):
                    meta["params_b"] = round(val / 1e9, 1)
                elif key == "general.quantization_version":
                    pass  # not the quant name, skip
                elif key.endswith(".context_length") and isinstance(val, int):
                    meta["context_length"] = val
                elif key == "general.name" and isinstance(val, str):
                    meta["model_name"] = val

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

    def estimate_vram_gb(self, model_meta: Dict[str, Any]) -> float:
        """
        Estimate VRAM requirement: params_B × bits_per_weight / 8 × 1.1 overhead.
        Falls back to 0.0 if params or quant unknown.
        """
        params_b = model_meta.get("params_b", 0)
        quant = model_meta.get("quantization", "Q4_K_M")
        bpw = QUANT_BPW.get(quant.upper(), 4.85)
        if not params_b:
            return 0.0
        return params_b * bpw / 8.0 * 1.1

    # ─────────────────────────────────────────────────────────────────────────
    # Profile resolution
    # ─────────────────────────────────────────────────────────────────────────

    def get_profile_params(self, profile: str, custom: Dict[str, Any] = None) -> Dict[str, Any]:
        if profile == "custom" and custom:
            base = dict(PROFILES["balanced"])
            base.update(custom)
            return base
        return dict(PROFILES.get(profile, PROFILES["balanced"]))

    def recommend_profile(self, model_meta: Dict[str, Any]) -> str:
        """
        Auto-select profile based on model size + available hardware.
        Returns profile name string.
        """
        hw = self.get_hardware_info()
        vram = hw.get("vram_free_gb", 0.0)
        cuda = hw.get("cuda_available", False)
        vram_needed = self.estimate_vram_gb(model_meta)

        if not cuda or vram < 4.0:
            return "eco"
        if vram_needed > 0 and vram_needed > vram * 0.9:
            return "eco"
        # Always prefer balanced (32k ctx / 1536 batch) — it's the 24GB RAM sweet spot.
        # performance is only for explicit user override.
        return "balanced"

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
            "loading" in line.lower() or "metadata" in line.lower() or "arch" in line.lower()
        ):
            return {"phase": "init", "pct": 10, "msg": "Reading model metadata"}

        # Tensor loading / GPU layer offloading
        # "llm_load_tensors: offloading 32 repeating layers to GPU"
        # "llm_load_tensors: offloaded 32/33 layers to GPU"
        m = re.search(r"offloaded?\s+(\d+)(?:/(\d+))?\s+(?:repeating\s+)?layers", line)
        if m:
            n = int(m.group(1))
            total = int(m.group(2)) if m.group(2) else n
            pct = max(15, min(75, int(n / max(total, 1) * 65) + 10))
            return {"phase": "loading", "pct": pct, "msg": f"Offloading layers {n}/{total} to GPU"}

        # Tensor loading generic: "llm_load_tensors: ggml ctx size"
        if "llm_load_tensors" in line and "ggml" in line:
            return {"phase": "loading", "pct": 20, "msg": "Loading tensors"}

        # Context / KV cache allocation
        if "llama_new_context_with_model" in line or (
            "kv cache" in line.lower() and "size" in line.lower()
        ):
            return {"phase": "context", "pct": 85, "msg": "Building KV cache"}

        # Prompt cache / batch alloc
        if "llama_kv_cache_init" in line or "ggml_backend_alloc" in line:
            return {"phase": "context", "pct": 90, "msg": "Allocating compute buffers"}

        # Server listening (about to be ready)
        if re.search(r"(listening|HTTP server|server started|server is running)", line, re.I):
            return {"phase": "ready", "pct": 98, "msg": "Server online"}

        return None

    async def load_model(
        self,
        model_path: str,
        profile: str = "balanced",
        custom_params: Dict[str, Any] = None,
        progress_cb=None,  # async callable(event: dict) — optional progress hook
    ) -> bool:
        """
        Stop existing subprocess (if any), spawn new llama-cpp-python server.
        Streams incremental load progress via progress_cb if provided.
        Returns True when /health responds 200.
        """
        await self.unload_model()
        self._invalidate_hw_cache()  # VRAM state will change during load

        params = self.get_profile_params(profile, custom_params)
        cmd = self._build_server_cmd(model_path, params)
        logger.info(f"[LocalModelManager] Starting llama-cpp-python server: {' '.join(cmd)}")

        loop = asyncio.get_event_loop()

        with self._lock:
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,  # line-buffered so we get progress lines as they arrive
                )
                self._current_model_path = model_path
                self._current_profile = profile
            except FileNotFoundError:
                logger.error("[LocalModelManager] llama-cpp-python not installed or python not found")
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
                        loop.call_soon_threadsafe(progress_queue.put_nowait, event)
            except Exception as exc:
                logger.debug(f"[LocalModelManager] stdout reader exited: {exc}")
            finally:
                loop.call_soon_threadsafe(progress_queue.put_nowait, None)  # sentinel

        reader = threading.Thread(target=_read_stdout, daemon=True, name="llm-stdout-reader")
        reader.start()

        # ── Async wait loop — drain progress queue + poll for server ready ──
        deadline = loop.time() + 180.0  # 3 min max (large models on slow HW need time)
        ready = False
        last_pct = 0

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
                await asyncio.sleep(0.5)

        if ready:
            filename = Path(model_path).name
            self.save_model_settings(filename, {
                "last_profile": profile,
                "last_ctx": params.get("n_ctx", 8192),
                "last_gpu_layers": params.get("n_gpu_layers", -1),
            })
            self._invalidate_hw_cache()  # refresh VRAM after model occupies GPU
            logger.info(f"[LocalModelManager] Model ready at {self.ENDPOINT}")
        else:
            logger.error("[LocalModelManager] Timed out waiting for server to start")
            await self.unload_model()
        return ready

    async def unload_model(self) -> bool:
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
        self._invalidate_hw_cache()
        logger.info("[LocalModelManager] Model unloaded")
        return True

    async def health_check(self) -> bool:
        # llama-cpp-python server does not expose /health — use /v1/models instead.
        # ik_llama.cpp's llama-server exposes /health at the root (no /v1 prefix).
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
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def get_status(self) -> Dict[str, Any]:
        loaded = self.is_loaded()
        return {
            "loaded": loaded,
            "model_path": self._current_model_path if loaded else None,
            "profile": self._current_profile if loaded else None,
            "endpoint": self.ENDPOINT if loaded else None,
            "pid": self._process.pid if loaded and self._process else None,
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
        # 2. PATH lookup
        found = shutil.which("llama-server")
        if found:
            return found
        # 3. Common Windows install locations for ik_llama.cpp
        candidates = [
            Path.home() / "ik_llama.cpp" / "build" / "bin" / "llama-server.exe",
            Path.home() / "llama.cpp" / "build" / "bin" / "llama-server.exe",
            Path("C:/tools/llama-server.exe"),
            Path("C:/llama/llama-server.exe"),
        ]
        for c in candidates:
            if c.is_file():
                return str(c)
        return None

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
                    [python_exe, "-c",
                     "import llama_cpp; exit(0 if llama_cpp.llama_supports_gpu_offload() else 1)"],
                    capture_output=True, timeout=10,
                )
                return result.returncode == 0
            except Exception:
                return False

        def _has_llama(python_exe: str) -> bool:
            try:
                result = subprocess.run(
                    [python_exe, "-c", "import llama_cpp"],
                    capture_output=True, timeout=10,
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

        # Try Python 3.12 via py launcher (Windows) — CUDA wheels exist for 3.12
        import shutil
        py_launcher = shutil.which("py")
        if py_launcher:
            try:
                result = subprocess.run(
                    [py_launcher, "-3.12", "-c", "import sys; print(sys.executable)"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    py312 = result.stdout.strip()
                    if _has_cuda(py312):
                        logger.info(f"[LocalModelManager] Using Python 3.12 with CUDA: {py312}")
                        return py312
                    elif _has_llama(py312):
                        logger.info(f"[LocalModelManager] Using Python 3.12 (no CUDA): {py312}")
                        return py312
            except Exception:
                pass

        # Fall back to current interpreter even without CUDA
        return sys.executable

    def _build_server_cmd(self, model_path: str, params: Dict[str, Any]) -> List[str]:
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
        llama_server = self._find_llama_server_binary()

        if llama_server:
            # ── ik_llama.cpp / compiled llama-server ───────────────────────
            logger.info(f"[LocalModelManager] Using ik_llama.cpp binary: {llama_server}")
            cmd = [
                llama_server,
                "--model", str(model_path),
                "--port", str(self.PORT),
                "--host", "127.0.0.1",
                "--threads", str(cpu_count()),
            ]
            n_gpu = params.get("n_gpu_layers")
            if n_gpu is not None:
                cmd += ["--n-gpu-layers", str(n_gpu)]
            if params.get("n_ctx"):
                cmd += ["--ctx-size", str(params["n_ctx"])]
            if params.get("n_batch"):
                cmd += ["--batch-size", str(params["n_batch"])]
            if params.get("flash_attn"):
                cmd += ["--flash-attn"]
            if params.get("cache_type_k"):
                cmd += ["--cache-type-k", params["cache_type_k"]]
            if params.get("cache_type_v"):
                cmd += ["--cache-type-v", params["cache_type_v"]]
            if params.get("use_mmap", True):
                cmd += ["--mmap"]
            if params.get("keep_model_in_memory"):
                cmd += ["--mlock"]
            if params.get("offload_kv_cache"):
                cmd += ["--offload-kqv"]
            seed = params.get("seed")
            if seed is not None and seed != -1:
                cmd += ["--seed", str(int(seed))]
        else:
            # ── llama-cpp-python fallback ──────────────────────────────────
            # Flag reference (llama_cpp.server v0.3+):
            #   --type_k / --type_v expect GGML_TYPE integer (F16=1, Q4_0=2, Q8_0=8, Q4_K=12)
            #   --offload_kqv  bool  (default: True)
            #   --flash_attn   bool
            _GGML_TYPE = {
                "f32": 0, "f16": 1, "bf16": 30,
                "q4_0": 2, "q4_1": 3, "q5_0": 6, "q5_1": 7,
                "q8_0": 8, "q8_1": 9,
                "q2_k": 10, "q3_k": 11, "q3_k_s": 11, "q3_k_m": 11,
                "q4_k": 12, "q4_k_s": 12, "q4_k_m": 12,
                "q5_k": 13, "q5_k_s": 13, "q5_k_m": 13,
                "q6_k": 14, "q8_k": 15,
            }
            python_exe = self._find_llama_python()
            logger.info(f"[LocalModelManager] llama-server not found; using {python_exe} -m llama_cpp.server")
            cmd = [
                python_exe, "-m", "llama_cpp.server",
                "--model", str(model_path),
                "--port", str(self.PORT),
                "--host", "127.0.0.1",
                "--n_threads", str(cpu_count()),
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
        loop = asyncio.get_event_loop()
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
            yield {"status": "error", "error": "huggingface_hub not installed", "progress_pct": 0}
            return

        dest = (dest_dir or self.MODELS_DIR) / filename
        if dest.exists():
            yield {"status": "complete", "progress_pct": 100, "path": str(dest)}
            return

        yield {"status": "starting", "progress_pct": 0, "filename": filename}

        loop = asyncio.get_event_loop()
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
            yield {"status": "error", "error": str(e), "progress_pct": 0, "filename": filename}

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
