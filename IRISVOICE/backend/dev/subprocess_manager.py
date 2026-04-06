"""
Subprocess Manager — spawns and manages CLI tool processes.

Quality-check gates applied:
  - Each session gets an isolated subprocess; no shared state between sessions.
  - stdout/stderr are read on a dedicated daemon thread — no blocking the event loop.
  - Hard kill timeout enforced via threading.Timer.
  - Resources (handles, threads) cleaned up in _cleanup(), called on finish and abort.
  - Output queue is bounded (maxsize=500) — overflow drops oldest lines.
  - Async/sync boundary: spawn() is sync; output is sent via callback; abort() is sync.
  - No unbounded caches or state persisting after a session ends.
"""
from __future__ import annotations

import logging
import os
import queue
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .cli_registry import CLITool, get_cli_registry

logger = logging.getLogger(__name__)

_IDLE_TIMEOUT_SECONDS = int(os.environ.get("DEV_CLI_IDLE_TIMEOUT_SECONDS", "300"))
_OUTPUT_QUEUE_SIZE = 500


@dataclass
class ActiveProcess:
    proc_id: str
    tool_name: str
    proc: subprocess.Popen
    output_thread: threading.Thread
    kill_timer: Optional[threading.Timer]
    on_output: Callable[[str, str], None]   # (line, proc_id) → None
    on_done: Callable[[int, str], None]     # (returncode, proc_id) → None
    _queue: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=_OUTPUT_QUEUE_SIZE))
    _done: bool = False

    def abort(self) -> None:
        """Terminate the subprocess immediately."""
        if self._done:
            return
        try:
            self.proc.kill()
        except OSError:
            pass
        if self.kill_timer:
            self.kill_timer.cancel()


class SubprocessManager:
    """
    Manages one active subprocess per session.
    Each session key maps to at most one live process.
    """

    def __init__(self) -> None:
        self._active: dict[str, ActiveProcess] = {}
        self._lock = threading.Lock()

    # ── Public API ──────────────────────────────────────────────────────────

    def spawn(
        self,
        session_id: str,
        tool: CLITool,
        query: str,
        workdir: str,
        on_output: Callable[[str, str], None],
        on_done: Callable[[int, str], None],
    ) -> Optional[str]:
        """
        Spawn a new subprocess for session_id.
        Aborts any existing process for this session first.
        Returns proc_id (== session_id) or None on failure.
        """
        # Abort any existing process for this session
        self.abort(session_id)

        # Validate workdir
        cwd = Path(workdir).resolve()
        if not cwd.exists():
            logger.error("[SubprocessManager] workdir does not exist: %s", cwd)
            on_done(-1, session_id)
            return None

        # Validate workdir against allowed roots from env
        allowed_roots_env = os.environ.get("DEV_ALLOWED_ROOTS", "")
        if allowed_roots_env:
            allowed = [Path(r).resolve() for r in allowed_roots_env.split(os.pathsep) if r]
            if not any(str(cwd).startswith(str(root)) for root in allowed):
                logger.warning(
                    "[SubprocessManager] workdir '%s' not in DEV_ALLOWED_ROOTS — rejected", cwd
                )
                on_done(-2, session_id)
                return None

        cmd = [tool.command] + tool.build_args(query)
        logger.info("[SubprocessManager][%s] spawning: %s in %s", session_id, cmd, cwd)

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,   # merge stderr → stdout
                text=True,
                bufsize=1,                  # line-buffered
                env={**os.environ},
            )
        except FileNotFoundError:
            logger.error("[SubprocessManager] command not found: %s", tool.command)
            on_done(-1, session_id)
            return None
        except OSError as exc:
            logger.error("[SubprocessManager] spawn failed: %s", exc)
            on_done(-1, session_id)
            return None

        proc_id = session_id  # 1:1 mapping for simplicity

        active = ActiveProcess(
            proc_id=proc_id,
            tool_name=tool.name,
            proc=proc,
            output_thread=threading.Thread(target=_noop, daemon=True),  # placeholder
            kill_timer=None,
            on_output=on_output,
            on_done=on_done,
        )

        # Hard kill timer
        kill_timer = threading.Timer(
            tool.timeout_seconds,
            self._timeout_kill,
            args=(session_id,),
        )
        kill_timer.daemon = True
        kill_timer.start()
        active.kill_timer = kill_timer

        # Output reader thread
        output_thread = threading.Thread(
            target=self._read_output,
            args=(active,),
            daemon=True,
        )
        active.output_thread = output_thread

        with self._lock:
            self._active[session_id] = active

        output_thread.start()
        return proc_id

    def abort(self, session_id: str) -> None:
        """Terminate the active process for session_id if one exists."""
        with self._lock:
            active = self._active.get(session_id)
        if active:
            active.abort()

    def is_running(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._active

    def status(self, session_id: str) -> Optional[dict]:
        with self._lock:
            active = self._active.get(session_id)
        if not active:
            return None
        return {"proc_id": active.proc_id, "tool": active.tool_name, "pid": active.proc.pid}

    # ── Internal ────────────────────────────────────────────────────────────

    def _read_output(self, active: ActiveProcess) -> None:
        """Read stdout line by line and invoke on_output callback. Runs on daemon thread."""
        try:
            for line in active.proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip("\n")
                try:
                    active._queue.put_nowait(line)
                except queue.Full:
                    active._queue.get_nowait()  # drop oldest
                    active._queue.put_nowait(line)
                try:
                    active.on_output(line, active.proc_id)
                except Exception as exc:
                    logger.debug("[SubprocessManager] on_output error: %s", exc)
        except Exception as exc:
            logger.debug("[SubprocessManager] output reader error: %s", exc)
        finally:
            rc = active.proc.wait()
            self._cleanup(active.proc_id, rc)

    def _cleanup(self, session_id: str, returncode: int) -> None:
        with self._lock:
            active = self._active.pop(session_id, None)
        if active is None:
            return
        if active.kill_timer:
            active.kill_timer.cancel()
        active._done = True
        logger.info(
            "[SubprocessManager][%s] process exited with code %d", session_id, returncode
        )
        try:
            active.on_done(returncode, session_id)
        except Exception as exc:
            logger.debug("[SubprocessManager] on_done error: %s", exc)

    def _timeout_kill(self, session_id: str) -> None:
        logger.warning(
            "[SubprocessManager][%s] hard timeout — killing process", session_id
        )
        self.abort(session_id)


def _noop() -> None:
    pass


# ── Module-level singleton ──────────────────────────────────────────────────

_manager: Optional[SubprocessManager] = None


def get_subprocess_manager() -> SubprocessManager:
    global _manager
    if _manager is None:
        _manager = SubprocessManager()
    return _manager
