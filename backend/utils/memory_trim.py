"""OS working-set memory trimming helpers (Windows).

Used by the TTS and Parakeet subprocess workers and the Uvicorn main process
to reclaim private memory after heavy model loads. On non-Windows platforms
these are no-ops — the OS reclaims pages under memory pressure anyway.

The heavy ML workers (Pocket-TTS, Parakeet) deserialize safetensors into heap
buffers that are freed during load but whose pages stay resident in the
process's working set. ``EmptyWorkingSet`` forces the OS to reclaim those
pages, dropping the process's private footprint without touching live state.
"""

from __future__ import annotations

import ctypes
import logging
import sys

logger = logging.getLogger(__name__)


def trim_working_set() -> None:
    """Trim the current process's working set via ``EmptyWorkingSet``.

    Windows-only. On other platforms this is a no-op. Never raises — memory
    trimming is best-effort and must never break the caller (a model worker
    must not fail to serve because a trim call errored).
    """
    if sys.platform != "win32":
        return
    try:
        # psapi.EmptyWorkingSet(GetCurrentProcess()) — trims the working set to
        # the minimum, forcing the OS to reclaim pages no longer referenced
        # (e.g. safetensors heap buffers freed after model load).
        _psapi = ctypes.windll.psapi
        _psapi.EmptyWorkingSet(ctypes.windll.kernel32.GetCurrentProcess())
        logger.debug("Working set trimmed")
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.debug("Working set trim failed: %s", exc)