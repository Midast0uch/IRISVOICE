"""OS working-set memory trimming helpers (Windows).

Used by the TTS and Parakeet subprocess workers and the Uvicorn main process
to reclaim private memory after heavy model loads. On non-Windows platforms
these are no-ops — the OS reclaims pages under memory pressure anyway.

The heavy ML workers (Pocket-TTS, Parakeet) deserialize safetensors into heap
buffers that are freed during load but whose pages stay resident in the
process's working set. ``EmptyWorkingSet`` forces the OS to reclaim those
pages, dropping the process's private footprint without touching live state.

Session-331 DEFECT FIX: ``EmptyWorkingSet`` was being called with the
``GetCurrentProcess()`` PSEUDO-handle (-1). That handle does NOT carry
``PROCESS_SET_QUOTA``, so the call silently FAILED (returns 0) and reclaimed
nothing — every trim this module claims to perform was a no-op. Measured
decisively (scripts/measure_trim_truth.py): a 617 MB resident process stayed at
647 MB after the old call, then dropped to 1.7 MB when given a REAL handle.
The fix opens a real handle with ``PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION``
and closes it. This is what actually lets the TTS worker shed the ~1.4 GB of
freed safetensors pages after load (and its post-synthesis scratch), instead of
holding ~2 GB commit / ~1 GB resident forever.
"""

from __future__ import annotations

import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

# Windows process-access rights needed by EmptyWorkingSet.
_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_SET_QUOTA = 0x0100


def trim_working_set() -> None:
    """Trim the current process's working set via ``EmptyWorkingSet``.

    Windows-only. On other platforms this is a no-op. Never raises — memory
    trimming is best-effort and must never break the caller (a model worker
    must not fail to serve because a trim call errored).

    Session-331: opens a REAL process handle (the pseudo-handle silently fails
    ``EmptyWorkingSet``). Falls back to the pseudo-handle only if opening a real
    handle fails, so a locked-down sandbox degrades to the old behaviour rather
    than raising.
    """
    if sys.platform != "win32":
        return
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    # Declare arg/return types so 64-bit handles are not truncated to int.
    psapi.EmptyWorkingSet.restype = ctypes.c_int
    psapi.EmptyWorkingSet.argtypes = [ctypes.c_void_p]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    handle = None
    try:
        handle = kernel32.OpenProcess(
            _PROCESS_SET_QUOTA | _PROCESS_QUERY_INFORMATION,
            False,
            kernel32.GetCurrentProcessId(),
        )
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.debug("OpenProcess for trim failed: %s", exc)
        handle = None

    try:
        if handle:
            rc = psapi.EmptyWorkingSet(handle)
            if rc:
                logger.debug("Working set trimmed (real handle)")
            else:
                logger.debug("Working set trim returned 0 (real handle)")
        else:
            # Fallback: pseudo-handle (may no-op on hardened systems, but never raises).
            rc = psapi.EmptyWorkingSet(kernel32.GetCurrentProcess())
            logger.debug("Working set trim (pseudo-handle) -> %s", rc)
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.debug("Working set trim failed: %s", exc)
    finally:
        if handle:
            try:
                kernel32.CloseHandle(handle)
            except Exception:  # noqa: BLE001
                pass
