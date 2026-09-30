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

LANES (2026-09-29)
------------------
One lane is one writer: a FIFO drained by one thread. Work that must not wait
behind other work gets its OWN lane, so the lanes run side by side and never
queue behind each other — the phase-model idea (docs/CADUCEAN_CONCURRENCY_MODEL.md)
of letting many operations run at once at distinct positions, instead of one
line everyone waits in. Measured reason: (1) above, thread-per-row, reached
~90 threads all writing through one shared connection; each "database is
locked" fell back to the native writer and blocked there, and every other DB
write in the process waited in the same crowd. The module-level functions are
the default lane; ``lane(name)`` returns a named one.

GUARANTEES (per lane)
---------------------
* Order    — one worker thread, FIFO queue: writes land in submission order.
* Bounded  — a fixed maxsize. If durability falls behind the agent, work is
             DROPPED and COUNTED, never accumulated without limit.
* Silent to the caller — submit() never raises and never blocks. A durability
             write must not be able to fail a task that already succeeded.
* Loud in the log — drops and failures are logged with a context identifier,
             because a silently discarded audit trail is the exact defect class
             this codebase keeps rediscovering. A lane given a ``watch``
             callback also reports a job that never returns.

Deliberately daemon threads: a worker wedged in a native FFI call cannot be
joined, and a non-daemon worker would hang interpreter shutdown forever.
"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Deep enough to absorb a burst from a long multi-step task, shallow enough
# that a stalled FFI layer cannot grow memory without bound.
_MAX_PENDING = 512


class _JobHandle:
    """Thread-like view of one queued job (join / is_alive), for a watcher."""

    __slots__ = ("_done",)

    def __init__(self) -> None:
        self._done = threading.Event()

    def join(self, timeout: Optional[float] = None) -> None:
        self._done.wait(timeout)

    def is_alive(self) -> bool:
        return not self._done.is_set()


class _Lane:
    """One ordered writer: a bounded FIFO drained by one daemon thread."""

    def __init__(
        self,
        name: str,
        watch: Optional[Callable[[Any, str], None]] = None,
    ) -> None:
        self.name = name
        self._q: "queue.Queue[tuple[str, Callable[..., Any], tuple, dict]]" = queue.Queue(
            maxsize=_MAX_PENDING
        )
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()
        self._dropped = 0
        # One watcher thread per lane (never one per job): it is handed each
        # job as it starts and calls watch(handle, label), which may block
        # up to its own bound. Jobs run one at a time, so one watcher suffices.
        self._watch = watch
        self._watch_q: "queue.Queue[tuple[_JobHandle, str]]" = queue.Queue()

    def _drain(self) -> None:
        """Single consumer. Runs forever; never lets one bad write kill the loop."""
        while True:
            label, fn, args, kwargs = self._q.get()
            handle = _JobHandle()
            if self._watch is not None:
                self._watch_q.put((handle, label))
            try:
                fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                # Swallowed on purpose: durability is best-effort and must never
                # propagate into the agent. Logged so it is still diagnosable.
                logger.warning(
                    "[durability] write failed lane=%s label=%s: %s", self.name, label, exc
                )
            finally:
                handle._done.set()
                self._q.task_done()

    def _watch_loop(self) -> None:
        while True:
            handle, label = self._watch_q.get()
            try:
                self._watch(handle, label)
            except Exception:  # noqa: BLE001 — an observer never breaks the lane
                pass

    def _ensure_worker(self) -> None:
        """Start the drain (and watch) thread on first use, never at import."""
        if self._worker is not None and self._worker.is_alive():
            return
        with self._worker_lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._drain, daemon=True, name=f"iris-{self.name}"
            )
            self._worker.start()
            if self._watch is not None:
                threading.Thread(
                    target=self._watch_loop, daemon=True, name=f"iris-{self.name}-watch"
                ).start()

    def submit(self, label: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> bool:
        """Queue a write. Returns False if it was dropped. Never raises or blocks.

        Bind VALUES, not mutable objects that the caller keeps editing: the write
        executes later, so a list or dict handed in here may have moved on by then.
        """
        try:
            self._ensure_worker()
            self._q.put_nowait((label, fn, args, kwargs))
            return True
        except queue.Full:
            self._dropped += 1
            # Log the first drop and then every 50th, so a sustained backlog is
            # visible without flooding the log with one line per lost write.
            if self._dropped == 1 or self._dropped % 50 == 0:
                logger.warning(
                    "[durability] lane=%s queue full (%d pending) — dropped %d "
                    "write(s), most recent label=%s",
                    self.name, _MAX_PENDING, self._dropped, label,
                )
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[durability] submit failed lane=%s label=%s: %s", self.name, label, exc
            )
            return False

    def in_worker(self) -> bool:
        """True on this lane's drain thread. A job that waits on work queued
        behind it here would wait on itself, so fold-back barriers skip here."""
        return self._worker is not None and threading.current_thread() is self._worker

    def pending(self) -> int:
        """Approximate queue depth — for diagnostics/tests."""
        return self._q.qsize()

    def dropped(self) -> int:
        """Total writes discarded because the queue was full."""
        return self._dropped

    def flush(self, timeout: float = 5.0) -> bool:
        """Block until the queue drains. TESTS AND SHUTDOWN ONLY.

        Never call this on a request path — it reintroduces exactly the blocking
        this module exists to remove.
        """
        done = threading.Event()
        if not self.submit("flush-sentinel", done.set):
            return False
        return done.wait(timeout)


_default = _Lane("durability")
_lanes: Dict[str, _Lane] = {}
_lanes_lock = threading.Lock()


def lane(name: str, watch: Optional[Callable[[Any, str], None]] = None) -> _Lane:
    """The named lane, created on first use (``watch`` applies at creation)."""
    with _lanes_lock:
        existing = _lanes.get(name)
        if existing is None:
            existing = _Lane(name, watch=watch)
            _lanes[name] = existing
        return existing


# ── The default lane (module API kept for existing callers) ─────────────────

def submit(label: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> bool:
    """Queue a durability write on the default lane. Returns False if dropped."""
    return _default.submit(label, fn, *args, **kwargs)


def in_worker() -> bool:
    """True on the default lane's drain thread."""
    return _default.in_worker()


def pending() -> int:
    """Approximate default-lane queue depth — for diagnostics/tests."""
    return _default.pending()


def dropped() -> int:
    """Total default-lane writes discarded because the queue was full."""
    return _default.dropped()


def flush(timeout: float = 5.0) -> bool:
    """Block until the default lane drains. TESTS AND SHUTDOWN ONLY."""
    return _default.flush(timeout)
