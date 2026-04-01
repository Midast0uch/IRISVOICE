"""
Audio Model Manager — VRAM-aware device selection for audio models.

Manages device selection for LFM audio model loading.  Before enabling GPU,
checks that at least 8 GB of free VRAM is available to prevent OOM crashes
when LM Studio or Ollama is already occupying GPU memory.

VRAM threshold: >= 8.0 GB free required for GPU mode.
Fallback: device = "cpu" when VRAM is insufficient or unavailable.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# VRAM threshold: 8 GB free required before enabling GPU for audio models.
# Rationale: LM Studio + Ollama can hold 4-7 GB for a loaded LLM.
# Using < 8.0 GB free threshold caused OOM (old threshold was 3 GB — too low).
_VRAM_FREE_THRESHOLD_GB: float = 8.0


def get_audio_device(force_cpu: bool = False) -> str:
    """
    Return the device string to use for audio model loading.

    Checks free VRAM.  If >= 8.0 GB is available AND force_cpu is False,
    returns "cuda".  Otherwise returns "cpu".

    Args:
        force_cpu: If True, always return "cpu" regardless of VRAM.

    Returns:
        "cuda" or "cpu"
    """
    if force_cpu:
        return "cpu"

    try:
        import torch
        if not torch.cuda.is_available():
            return "cpu"

        free_vram_bytes, _ = torch.cuda.mem_get_info()
        free_vram_gb = free_vram_bytes / (1024 ** 3)

        if free_vram_gb >= _VRAM_FREE_THRESHOLD_GB:
            logger.info(
                f"[AudioModelManager] VRAM check: {free_vram_gb:.1f} GB free "
                f"(threshold >= {_VRAM_FREE_THRESHOLD_GB} GB) — using CUDA"
            )
            return "cuda"
        else:
            logger.warning(
                f"[AudioModelManager] VRAM check: only {free_vram_gb:.1f} GB free "
                f"(need >= {_VRAM_FREE_THRESHOLD_GB} GB) — falling back to CPU"
            )
            device = "cpu"
            return device

    except Exception as exc:
        logger.warning(f"[AudioModelManager] VRAM check failed: {exc} — using CPU")
        device = "cpu"
        return device


def check_vram_available(required_gb: float = _VRAM_FREE_THRESHOLD_GB) -> bool:
    """Return True if at least required_gb of free VRAM is available."""
    try:
        import torch
        if not torch.cuda.is_available():
            return False
        free_bytes, _ = torch.cuda.mem_get_info()
        free_gb = free_bytes / (1024 ** 3)
        return free_gb >= required_gb
    except Exception:
        return False
