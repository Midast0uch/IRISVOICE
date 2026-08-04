"""Bounded, logged loading of heavy optional dependencies.

WHY THIS EXISTS
---------------
Two separate multi-minute production stalls in this codebase had the same
shape: a heavy import executed inside a request path, wrapped in a
``try/except ImportError`` that could never fire.

    try:
        from sentence_transformers import CrossEncoder
    except Exception:
        return passages          # unreachable — A HANG IS NOT AN EXCEPTION

On this machine ``import sentence_transformers`` takes ~13 MINUTES (torchcodec
0.13 probes FFmpeg majors 4-7; the host has FFmpeg 8, so the Windows loader
stalls on every probe). The guard above is written for "dependency missing" and
is structurally blind to "dependency slow". Worse, nothing was logged: the
thread sat in an import with no line before it and no line after it, so the
only way to find it was an all-thread stack dump.

RULES THIS ENFORCES
-------------------
1. LOG BEFORE AND AFTER. An import that can block MUST announce itself before
   it starts, so a stall is attributable from the log alone. A missing "done"
   line next to a "loading" line is the diagnosis.
2. BOUND IT. Never let an optional dependency block a request indefinitely.
3. LATCH THE OUTCOME. A slow or failing load is attempted at most once per
   process; retrying on every call turns one stall into many.
4. DEGRADE, DON'T RAISE. Callers get ``None`` and take their existing fallback.

Use this for ANY optional/heavy third-party import on a request path.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = float(os.environ.get("IRIS_HEAVY_IMPORT_TIMEOUT_S", "60"))

# name -> (value | None). Presence of a key means "already attempted".
_results: Dict[str, Optional[Any]] = {}
_lock = threading.Lock()


def load_bounded(
    name: str,
    loader: Callable[[], Any],
    timeout_s: Optional[float] = None,
) -> Optional[Any]:
    """Run ``loader()`` on a daemon thread, bounded by ``timeout_s``.

    Returns the loaded object, or ``None`` if it timed out or raised. The
    outcome is latched per ``name``, so a stall costs the timeout ONCE.

    A daemon thread is used deliberately: a thread wedged in a native import
    cannot be joined or cancelled, and a non-daemon thread (or a bare
    ThreadPoolExecutor, whose atexit hook joins its workers) would then block
    interpreter shutdown forever.
    """
    with _lock:
        if name in _results:
            return _results[name]

    budget = DEFAULT_TIMEOUT_S if timeout_s is None else timeout_s
    box: Dict[str, Any] = {}
    t0 = time.monotonic()

    # RULE 1: announce BEFORE the call that can block.
    logger.info("[heavy_import] loading %r (timeout %.0fs)...", name, budget)

    def _run() -> None:
        try:
            box["value"] = loader()
        except BaseException as exc:  # noqa: BLE001 - report, never propagate
            box["error"] = exc

    th = threading.Thread(target=_run, name=f"heavy-import-{name}", daemon=True)
    th.start()
    th.join(budget)
    elapsed = time.monotonic() - t0

    if th.is_alive():
        logger.warning(
            "[heavy_import] %r did NOT finish within %.0fs — degrading. "
            "The loader thread is still running and will be abandoned. "
            "(Set IRIS_HEAVY_IMPORT_TIMEOUT_S to change the bound.)",
            name, budget,
        )
        value = None
    elif "error" in box:
        logger.warning(
            "[heavy_import] %r failed after %.1fs: %s", name, elapsed, box["error"],
        )
        value = None
    else:
        value = box.get("value")
        # RULE 1: and announce AFTER, with the cost, so slow-but-successful
        # loads are visible before they become someone's mystery stall.
        logger.info("[heavy_import] %r ready in %.1fs", name, elapsed)

    with _lock:
        _results[name] = value
    return value


def reset_for_tests() -> None:
    with _lock:
        _results.clear()
