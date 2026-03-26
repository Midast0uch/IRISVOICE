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
    "balanced": {
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
    "performance": {
        "n_gpu_layers": -1,
        "n_ctx": 8192,
        "flash_attn": True,
        "cache_type_k": "f16",
        "cache_type_v": "f16",
        "n_batch": 4096,
        "offload_kv_cache": True,
        "unified_kv_cache": True,
        "keep_model_in_memory": True,
        "use_mmap": True,
    },
    "voice_first": {
        "n_gpu_layers": -1,
        "n_ctx": 4096,
        "flash_attn": True,
        "cache_type_k": "f16",
        "cache_type_v": "f16",
        "n_batch": 1024,
        "offload_kv_cache": True,
        "unified_kv_cache": True,
        "keep_model_in_memory": True,
        "use_mmap": True,
    },
    "research": {
        "n_gpu_layers": -1,
        "n_ctx": 32768,
        "flash_attn": True,
        "cache_type_k": "q8_0",
        "cache_type_v": "q8_0",
        "n_batch": 1024,
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
        self._register_cleanup()

    # ─────────────────────────────────────────────────────────────────────────
    # Hardware info
    # ─────────────────────────────────────────────────────────────────────────

    def get_hardware_info(self) -> Dict[str, Any]:
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
        info["models_dir"] = str(self.MODELS_DIR)
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

            # Parse metadata from GGUF header
            try:
                meta = self.parse_gguf_metadata(gguf_path)
            except Exception as e:
                logger.debug(f"[LocalModelManager] Could not parse GGUF header for {filename}: {e}")
                meta = {}

            size_gb = round(gguf_path.stat().st_size / (1024 ** 3), 2)
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
                "last_ctx": model_settings.get("last_ctx", 8192),
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
        if vram >= 8.0:
            return "performance"
        return "balanced"

    # ─────────────────────────────────────────────────────────────────────────
    # Subprocess lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    async def load_model(
        self,
        model_path: str,
        profile: str = "balanced",
        custom_params: Dict[str, Any] = None,
    ) -> bool:
        """
        Stop existing subprocess (if any), spawn new llama-cpp-python server.
        Returns True when /health responds 200.
        """
        await self.unload_model()

        params = self.get_profile_params(profile, custom_params)
        cmd = self._build_server_cmd(model_path, params)
        logger.info(f"[LocalModelManager] Starting llama-cpp-python server: {' '.join(cmd)}")

        with self._lock:
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                self._current_model_path = model_path
                self._current_profile = profile
            except FileNotFoundError:
                logger.error("[LocalModelManager] llama-cpp-python not installed or python not found")
                return False

        ready = await self._wait_for_ready(timeout=45.0)
        if ready:
            filename = Path(model_path).name
            self.save_model_settings(filename, {
                "last_profile": profile,
                "last_ctx": params.get("n_ctx", 8192),
                "last_gpu_layers": params.get("n_gpu_layers", -1),
            })
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
        logger.info("[LocalModelManager] Model unloaded")
        return True

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self.ENDPOINT}/health")
                return r.status_code == 200
        except Exception:
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

    def _build_server_cmd(self, model_path: str, params: Dict[str, Any]) -> List[str]:
        cmd = [
            sys.executable, "-m", "llama_cpp.server",
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
            cmd += ["--cache_type_k", params["cache_type_k"]]
        if params.get("cache_type_v"):
            cmd += ["--cache_type_v", params["cache_type_v"]]
        if params.get("use_mmap"):
            cmd += ["--use_mmap", "true"]
        if params.get("keep_model_in_memory"):
            cmd += ["--use_mlock", "true"]
        # KV cache offload to GPU (--offload_kqv flag)
        if params.get("offload_kv_cache"):
            cmd += ["--offload_kqv"]
        # Seed (-1 means random; only pass explicit seeds)
        seed = params.get("seed")
        if seed is not None and seed != -1:
            cmd += ["--seed", str(int(seed))]
        return cmd

    async def _wait_for_ready(self, timeout: float = 45.0) -> bool:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        async with httpx.AsyncClient(timeout=2.0) as client:
            while loop.time() < deadline:
                if not self.is_loaded():
                    return False
                try:
                    r = await client.get(f"{self.ENDPOINT}/health")
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
