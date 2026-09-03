"""Ordered, bounded, off-thread queue for post-step durability writes.

WHY THIS EXISTS
---------------
Three separate audit/durability writes were discovered sitting INLINE on the
DER critical path, each one serialising through FFI into SQLite while the user
waited on an answer that was already computed:

  1. tool_bridge._record_tool_event      — moved off-thread (daemon per call)
  2. agent_kernel._store_document_data   — moved off-thread (daemon per call)
  3. agent_kernel  Immortus chain append — THIS ONE

The comment left on (2) said that if a third appeared, the PATTERN should be
fixed rather than the instance. This is that fix, and (3) forces it for a
reason the first two did not have:

    THE IMMORTUS CHAIN IS ORDER-SENSITIVE.

Each entry carries coords_from -> coords_to and links to the one before it, so
it is a trajectory, not a set of independent rows. Spawning a thread per append
(the shape used for 1 and 2) would let two appends race and land reversed,
silently corrupting the 4D coordinate chain — a worse failure than the latency
it set out to fix, and one that would only surface much later as an incoherent
trajectory. A SINGLE consumer draining a FIFO preserves submission order by
construction.

GUARANTEES
----------
* Order    — one worker thread, FIFO queue: writes land in submission order.
* Bounded  — a fixed maxsize. If durability falls behind the agent, work is
             DROPPED and COUNTED, never accumulated without limit.
* Silent to the caller — submit() never raises and never blocks. A durability
             write must not be able to fail a task that already succeeded.
* Loud in the log — drops and failures are logged with a context identifier,
             because a silently discarded audit trail is the exact defect class
             this codebase keeps rediscovering.

Deliberately a daemon thread: a worker wedged in a native FFI call cannot be
joined, and a non-daemon worker would hang interpreter shutdown forever.
"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Deep enough to absorb a burst from a long multi-step task, shallow enough
# that a stalled FFI layer cannot grow memory without bound.
_MAX_PENDING = 512

_q: "queue.Queue[tuple[str, Callable[..., Any], tuple, dict]]" = queue.Queue(
    maxsize=_MAX_PENDING
)
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
_dropped = 0


def _drain() -> None:
    """Single consumer. Runs forever; never lets one bad write kill the loop."""
    while True:
        label, fn, args, kwargs = _q.get()
        try:
            fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            # Swallowed on purpose: durability is best-effort and must never
            # propagate into the agent. Logged so it is still diagnosable.
            logger.warning("[durability] write failed label=%s: %s", label, exc)
        finally:
            _q.task_done()


def _ensure_worker() -> None:
    """Start the drain thread on first use (never at import time)."""
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(
            target=_drain, daemon=True, name="iris-durability"
        )
        _worker.start()


def submit(label: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> bool:
    """Queue a durability write. Returns False if it was dropped.

    Never raises and never blocks — callers are on a latency-critical path and
    must be able to fire and forget. ``label`` identifies the write in the log.

    Bind VALUES, not mutable objects that the caller keeps editing: the write
    executes later, so a list or dict handed in here may have moved on by then.
    """
    global _dropped
    try:
        _ensure_worker()
        _q.put_nowait((label, fn, args, kwargs))
        return True
    except queue.Full:
        _dropped += 1
        # Log the first drop and then every 50th, so a sustained backlog is
        # visible without flooding the log with one line per lost write.
        if _dropped == 1 or _dropped % 50 == 0:
            logger.warning(
                "[durability] queue full (%d pending) — dropped %d write(s), "
                "most recent label=%s",
                _MAX_PENDING, _dropped, label,
            )
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("[durability] submit failed label=%s: %s", label, exc)
        return False


def pending() -> int:
    """Approximate queue depth — for diagnostics/tests."""
    return _q.qsize()


def dropped() -> int:
    """Total writes discarded because the queue was full."""
    return _dropped


def flush(timeout: float = 5.0) -> bool:
    """Block until the queue drains. TESTS AND SHUTDOWN ONLY.

    Never call this on a request path — it reintroduces exactly the blocking
    this module exists to remove.
    """
    done = threading.Event()

    def _sentinel() -> None:
        done.set()

    if not submit("flush-sentinel", _sentinel):
        return False
    return done.wait(timeout)
