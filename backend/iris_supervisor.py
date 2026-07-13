"""
iris_supervisor.py — Process-isolation supervisor for the model runner.

Phase 4.1 of the Universal DER-PACMAN & Process Isolation plan.

The supervisor owns a model-runner *worker* subprocess (the thing that
actually loads the LLM / CUDA model).  It:

  * spawns the worker as a child process
  * monitors it and restarts it on crash (bounded retries + backoff)
  * exposes a line-based JSON control protocol over the worker's stdio
    (ping/pong, health) so the rest of the system can probe it without
    touching the model directly
  * reports a memory metric (worker RSS) for the /health endpoint

The worker protocol is intentionally tiny and transport-agnostic so it can
be exercised with a mock worker (see backend/tests/mock_model_worker.py)
without a real CUDA model — live model wiring is deferred per the plan.

Usage:
    sup = ModelRunnerSupervisor(
        worker_cmd=[sys.executable, "backend/worker/model_runner.py"],
        max_restarts=5, restart_backoff=2.0,
    )
    sup.start()
    sup.send_json({"type": "ping"})
    pong = sup.read_json_line(timeout=2.0)
    print(sup.health())
    sup.stop()
"""

from __future__ import annotations

import collections
import json
import logging
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ModelRunnerSupervisor:
    """Watchdog + control plane for a model-runner worker subprocess."""

    def __init__(
        self,
        worker_cmd: List[str],
        max_restarts: int = 5,
        restart_backoff: float = 2.0,
        poll_interval: float = 0.5,
        memory_metric_fn: Optional[Callable[[int], Dict[str, Any]]] = None,
    ) -> None:
        if not worker_cmd:
            raise ValueError("worker_cmd must be a non-empty command list")
        self.worker_cmd = list(worker_cmd)
        self.max_restarts = max_restarts
        self.restart_backoff = restart_backoff
        self.poll_interval = poll_interval
        self._memory_metric_fn = memory_metric_fn

        self._proc: Optional[subprocess.Popen] = None
        self._restarts = 0
        self._started_at: Optional[float] = None
        self._stopped = False

        self._lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._reader_thread: Optional[threading.Thread] = None

        # Received JSON messages from the worker (newest at the right).
        self._recv: "collections.deque" = collections.deque()
        self._recv_lock = threading.Lock()

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Spawn the worker and start the monitor loop (idempotent)."""
        with self._lock:
            if self._stopped:
                return
            if self._proc is not None and self._proc.poll() is None:
                return  # already running
            self._spawn()
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop, daemon=True, name="iris-supervisor"
            )
            self._monitor_thread.start()

    def stop(self) -> None:
        """Terminate the worker and stop monitoring."""
        with self._lock:
            self._stopped = True
            self._terminate_proc()

    def _spawn(self) -> None:
        self._proc = subprocess.Popen(
            self.worker_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._started_at = time.time()
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="iris-worker-reader"
        )
        self._reader_thread.start()

    def _terminate_proc(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self._proc = None

    # ── Monitoring ───────────────────────────────────────────────────────

    def _is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _monitor_loop(self) -> None:
        while not self._stopped:
            time.sleep(self.poll_interval)
            self._restart_if_needed()

    def _restart_if_needed(self) -> bool:
        """Restart the worker if it died and we have retries left.

        Returns True if a restart was performed.  Safe to call manually from
        tests (deterministic) or from the monitor loop (periodic).
        """
        with self._lock:
            if self._stopped:
                return False
            if self._is_alive():
                return False
            if self._restarts >= self.max_restarts:
                logger.warning(
                    "[Supervisor] worker exhausted restart budget "
                    "(%d/%d) — giving up",
                    self._restarts, self.max_restarts,
                )
                return False
            if self.restart_backoff > 0:
                time.sleep(self.restart_backoff)
            logger.info(
                "[Supervisor] restarting worker (attempt %d/%d)",
                self._restarts + 1, self.max_restarts,
            )
            self._spawn()
            self._restarts += 1
            return True

    # ── Worker protocol (line-based JSON over stdio) ─────────────────────

    def _reader_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                with self._recv_lock:
                    self._recv.append(msg)
        except Exception:
            pass

    def send_json(self, obj: Dict[str, Any]) -> bool:
        """Send a JSON control message to the worker. Returns False if down."""
        proc = self._proc
        if proc is None or proc.stdin is None:
            return False
        try:
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()
            return True
        except Exception as exc:
            logger.warning("[Supervisor] send_json failed: %s", exc)
            return False

    def read_json_line(self, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
        """Pop the next received worker message, waiting up to `timeout` s."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._recv_lock:
                if self._recv:
                    return self._recv.popleft()
            time.sleep(0.02)
        return None

    # ── Metrics / health ─────────────────────────────────────────────────

    def memory_metric(self) -> Dict[str, Any]:
        """Return a memory metric dict for the worker process.

        Uses a caller-supplied function if provided, else falls back to
        psutil (RSS in bytes).  Always returns a dict with an `available`
        flag so /health never crashes if psutil is missing.
        """
        proc = self._proc
        if proc is None or proc.pid is None:
            return {"available": False, "rss_bytes": None}
        if self._memory_metric_fn is not None:
            try:
                return self._memory_metric_fn(proc.pid)
            except Exception as exc:
                logger.debug("[Supervisor] memory_metric_fn failed: %s", exc)
        try:
            import psutil

            rss = psutil.Process(proc.pid).memory_info().rss
            return {"available": True, "rss_bytes": rss}
        except Exception:
            return {"available": False, "rss_bytes": None}

    def health(self) -> Dict[str, Any]:
        """Snapshot of supervisor + worker state for /health."""
        alive = self._is_alive()
        return {
            "status": (
                "running"
                if alive
                else ("stopped" if self._stopped else "crashed")
            ),
            "pid": self._proc.pid if self._proc is not None else None,
            "uptime_s": (
                round(time.time() - self._started_at, 2)
                if self._started_at is not None
                else 0.0
            ),
            "restart_count": self._restarts,
            "max_restarts": self.max_restarts,
            "memory": self.memory_metric() if alive else None,
        }
