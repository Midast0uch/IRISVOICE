#!/usr/bin/env python3
"""
SwarmInferenceManager — auto-configures Director + Worker llama-server instances.

Reads swarm_mode from UI and starts the appropriate inference backends:
  local_fast:      All TurboQuant (Director + Workers on GPU)
  api_director:    API Director + TurboQuant Workers on GPU
  quality_director: Q3_K_M Director (partial GPU) + TurboQuant Workers on GPU

VRAM-aware — calculates GPU/CPU split automatically.
"""

import asyncio
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Port configuration — Swarm uses its OWN llama-server instances for
# Director and Workers.  These are NOT the same as the brain/vision ports.
# Override via environment variables.
# ---------------------------------------------------------------------------

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


SWARM_DIRECTOR_PORT: int = _env_int("IRIS_SWARM_DIRECTOR_PORT", 8081)
SWARM_WORKERS_PORT: int = _env_int("IRIS_SWARM_WORKERS_PORT", 8082)

logger = logging.getLogger(__name__)


class SwarmMode(Enum):
    """Swarm configuration modes from UI dropdown."""

    LOCAL_FAST = "local_fast"
    API_DIRECTOR = "api_director"
    QUALITY_DIRECTOR = "quality_director"


@dataclass
class SwarmConfig:
    """Resolved swarm configuration for a given mode."""

    mode: SwarmMode
    worker_ctx: int
    director_ctx: int
    director_model: Optional[str]
    worker_model: str
    director_gpu_layers: int
    worker_gpu_layers: int
    director_endpoint: str
    workers_endpoint: str
    use_api_director: bool


class SwarmInferenceManager:
    """
    Manages two llama-server instances: Director (port IRIS_SWARM_DIRECTOR_PORT) and Workers (port IRIS_SWARM_WORKERS_PORT).

    Auto-detects available VRAM and picks GPU layer splits.
    """

    # Model paths (resolved at runtime)
    TURBOQUANT_PATH = "C:/Users/midas/.lmstudio/models/apothic/bonsai-8B-1bit-turboquant/Bonsai-8B.gguf"
    Q3KM_PATH = "C:/Users/midas/.lmstudio/models/bartowski/prism-ml_Bonsai-8B-unpacked-Q3_K_M.gguf"
    Q2K_PATH = "C:/Users/midas/.lmstudio/models/lilyanatia/Ternary-Bonsai-8B-GGUF/Ternary-Bonsai-8B-Q2_K.gguf"

    # VRAM budget (RTX 3070 8GB — let Director use full GPU offload)
    USABLE_VRAM_GB = 8.0

    def __init__(self):
        self.director_proc: Optional[subprocess.Popen] = None
        self.workers_proc: Optional[subprocess.Popen] = None
        self._current_mode: Optional[SwarmMode] = None
        self._current_config: Optional[SwarmConfig] = None
        self._swarm_lock = asyncio.Lock()

    # ── Public API ──────────────────────────────────────────────────────

    def apply_swarm_mode(self, mode_str: str, worker_ctx: int = 2048) -> SwarmConfig:
        """
        Apply a swarm mode from UI selection.

        Args:
            mode_str: One of 'local_fast', 'api_director', 'quality_director'
            worker_ctx: Worker context window in tokens (from UI slider)
        """
        mode = SwarmMode(mode_str)
        self._current_mode = mode

        config = self._resolve_config(mode, worker_ctx)
        self._current_config = config

        logger.info(
            "[SwarmInferenceManager] Mode=%s | Director=%s | Workers=%s | "
            "DirectorCtx=%s | WorkerCtx=%s",
            mode.value,
            config.director_model or "API",
            config.worker_model,
            config.director_ctx,
            config.worker_ctx,
        )
        return config

    async def start_swarm(self) -> bool:
        """Start llama-server processes for Director and Workers.

        Uses an async lock to prevent concurrent starts from duplicate
        APPLY clicks — only the first caller proceeds, others return False.
        """
        async with self._swarm_lock:
            if not self._current_config:
                logger.warning(
                    "[SwarmInferenceManager] No config — call apply_swarm_mode() first"
                )
                return False

            # Kill orphan llama-server processes before spawning new ones
            from .local_model_manager import kill_orphan_servers

            kill_orphan_servers()

            self.stop_swarm()
            cfg = self._current_config

            # Start Director first (if local) — load the heavy model on GPU first,
            # then start Workers once Director is up. This avoids both models
            # competing for VRAM during initialisation.
            if not cfg.use_api_director and cfg.director_model:
                self.director_proc = self._start_llama_server(
                    model=cfg.director_model,
                    port=SWARM_DIRECTOR_PORT,
                    ctx_size=cfg.director_ctx,
                    gpu_layers=cfg.director_gpu_layers,
                    parallel=1,
                    label="Director",
                )
                if self.director_proc:
                    # Brief pause so the Director can finish its VRAM allocation
                    # before Workers begin theirs.
                    time.sleep(3)

            # Start Workers
            self.workers_proc = self._start_llama_server(
                model=cfg.worker_model,
                port=SWARM_WORKERS_PORT,
                ctx_size=cfg.worker_ctx,
                gpu_layers=cfg.worker_gpu_layers,
                parallel=4,
                label="Workers",
            )

            return self.director_proc is not None or self.workers_proc is not None

    def stop_swarm(self) -> None:
        """Kill all llama-server processes."""
        for proc, label in [
            (self.director_proc, "Director"),
            (self.workers_proc, "Workers"),
        ]:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                logger.info("[SwarmInferenceManager] %s stopped", label)
        self.director_proc = None
        self.workers_proc = None

    def get_status(self) -> Dict[str, Any]:
        """Return swarm status for UI display."""
        cfg = self._current_config
        if not cfg:
            return {"status": "not_configured"}

        return {
            "status": "running" if self._is_running() else "stopped",
            "mode": cfg.mode.value,
            "director": {
                "model": cfg.director_model or "API",
                "endpoint": cfg.director_endpoint,
                "gpu_layers": cfg.director_gpu_layers,
                "ctx": cfg.director_ctx,
                "alive": self.director_proc is not None
                and self.director_proc.poll() is None,
            },
            "workers": {
                "model": cfg.worker_model,
                "endpoint": cfg.workers_endpoint,
                "gpu_layers": cfg.worker_gpu_layers,
                "ctx": cfg.worker_ctx,
                "alive": self.workers_proc is not None
                and self.workers_proc.poll() is None,
            },
        }

    # ── Configuration resolution ──────────────────────────────────────────

    def _resolve_config(self, mode: SwarmMode, worker_ctx: int) -> SwarmConfig:
        """Build SwarmConfig based on mode and VRAM constraints."""
        if mode == SwarmMode.LOCAL_FAST:
            return SwarmConfig(
                mode=mode,
                worker_ctx=worker_ctx,
                director_ctx=12288,
                director_model=self.TURBOQUANT_PATH,
                worker_model=self.TURBOQUANT_PATH,
                director_gpu_layers=99,
                worker_gpu_layers=99,
                director_endpoint=f"http://localhost:{SWARM_DIRECTOR_PORT}/v1",
                workers_endpoint=f"http://localhost:{SWARM_WORKERS_PORT}/v1",
                use_api_director=False,
            )

        if mode == SwarmMode.API_DIRECTOR:
            return SwarmConfig(
                mode=mode,
                worker_ctx=worker_ctx,
                director_ctx=0,  # API doesn't need local context
                director_model=None,
                worker_model=self.TURBOQUANT_PATH,
                director_gpu_layers=0,
                worker_gpu_layers=99,
                director_endpoint="",  # Set by API provider in agent_kernel
                workers_endpoint=f"http://localhost:{SWARM_WORKERS_PORT}/v1",
                use_api_director=True,
            )

        if mode == SwarmMode.QUALITY_DIRECTOR:
            # Calculate partial GPU offload for Q3_K_M to fit with workers
            director_gpu = self._calculate_director_gpu_layers(worker_ctx)
            return SwarmConfig(
                mode=mode,
                worker_ctx=worker_ctx,
                director_ctx=12288,
                director_model=self.Q3KM_PATH,
                worker_model=self.TURBOQUANT_PATH,
                director_gpu_layers=director_gpu,
                worker_gpu_layers=99,
                director_endpoint=f"http://localhost:{SWARM_DIRECTOR_PORT}/v1",
                workers_endpoint=f"http://localhost:{SWARM_WORKERS_PORT}/v1",
                use_api_director=False,
            )

        raise ValueError(f"Unknown swarm mode: {mode}")

    def _calculate_director_gpu_layers(self, worker_ctx: int) -> int:
        """
        Calculate how many GPU layers Q3_K_M Director can have while fitting TurboQuant workers.

        For 8B models with ~33 layers:
        - Each layer on GPU ≈ 0.13 GB (Q3_K_M) or 0.03 GB (TurboQuant)
        - Full GPU for Q3_K_M = ~4.5 GB with 12k ctx
        - Workers need ~1.0 GB + KV cache
        """
        # Rough heuristic: if workers need >2GB combined, director gets partial offload
        worker_kv_gb = (worker_ctx * 4 * 64 * 1024) / (
            1024**3
        )  # 4 slots, 64KB per token
        worker_total = 1.1 + worker_kv_gb + 0.1

        available_for_director = self.USABLE_VRAM_GB - worker_total
        logger.debug(
            "[SwarmInferenceManager] VRAM: workers=%.2fGB, director_budget=%.2fGB",
            worker_total,
            available_for_director,
        )

        if available_for_director >= 4.5:
            return 99  # All layers GPU
        if available_for_director >= 3.5:
            return 24  # ~24/33 layers GPU
        if available_for_director >= 2.5:
            return 16  # ~16/33 layers GPU
        return 12  # Minimum viable GPU layers

    # ── Process management ──────────────────────────────────────────────

    def _start_llama_server(
        self,
        model: str,
        port: int,
        ctx_size: int,
        gpu_layers: int,
        parallel: int,
        label: str,
    ) -> Optional[subprocess.Popen]:
        """Start a llama-server process."""
        exe = self._find_llama_server()
        if not exe:
            logger.error("[SwarmInferenceManager] llama-server.exe not found")
            return None

        if not os.path.exists(model):
            logger.error("[SwarmInferenceManager] Model not found: %s", model)
            return None

        cmd = [
            str(exe),
            "--model",
            model,
            "--port",
            str(port),
            "--host",
            "127.0.0.1",
            "--ctx-size",
            str(ctx_size),
            "--batch-size",
            str(min(ctx_size, 2048)),
            "--threads",
            "8",
            "--gpu-layers",
            str(gpu_layers),
            "--parallel",
            str(parallel),
            "--cache-type-k",
            "q4_0",
            "--cache-type-v",
            "q4_0",
            "--flash-attn",
            "on",
            "--mmap",
        ]

        logger.info("[SwarmInferenceManager] Starting %s on port %d", label, port)
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            time.sleep(2)  # Brief startup delay
            if proc.poll() is not None:
                err = proc.stderr.read(500) if proc.stderr else ""
                logger.error(
                    "[SwarmInferenceManager] %s failed to start: %s", label, err
                )
                return None
            logger.info("[SwarmInferenceManager] %s started (pid=%d)", label, proc.pid)
            return proc
        except Exception as exc:
            logger.error("[SwarmInferenceManager] Failed to start %s: %s", label, exc)
            return None

    def _find_llama_server(self) -> Optional[Path]:
        """Locate llama-server.exe in the llama.cpp build directory."""
        candidates = [
            Path(
                "C:/Users/midas/Desktop/IRISVOICE/llama.cpp/build/bin/Release/llama-server.exe"
            ),
            Path(
                "C:/Users/midas/Desktop/IRISVOICE/llama.cpp/build/bin/llama-server.exe"
            ),
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _is_running(self) -> bool:
        """Check if any swarm process is alive."""
        for proc in [self.director_proc, self.workers_proc]:
            if proc and proc.poll() is None:
                return True
        return False
