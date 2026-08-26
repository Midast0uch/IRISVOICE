"""
Subprocess Manager — session shell substrate for developer mode.

Gate 3 (T1/T2): owns the persistent per-session shell (REQ-1), the global
concurrency cap (REQ-5 AC2/AC6), and per-command output bounds (REQ-12 AC2,
REQ-5 AC4). terminal_handler routes user `>` commands here; T0c routes the
agent's run_command / git_* here so both surfaces share one substrate
(design Key Decision 10 — one shell, not three).

It is a pipe, not a terminal: no PTY, no ANSI parsing, no completion.

Quality-check gates applied:
  - Each session is isolated: its own shell process, buffer, and state.
  - A global semaphore bounds concurrent command executions (default 4);
    excess callers queue with an explicit position message.
  - Output is byte-bounded per command and rate-bounded per window; a
    flooding process is terminated with a stated reason.
  - Dead sessions are unregistered; buffers are bounded deques.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import time
import uuid
from collections import deque
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# ── T2 constants (stated, not tuned) ────────────────────────────────────────
DEFAULT_MAX_CONCURRENT = 4          # REQ-5 AC2 global cap
MAX_OUTPUT_BYTES = 1 * 1024 * 1024  # hard per-command output cap → terminate
RATE_WINDOW_SECONDS = 5.0           # sliding window for the rate bound
RATE_WINDOW_BYTES = 2 * 1024 * 1024 # output allowed per window before kill
OUTPUT_BUFFER_LINES = 500           # bounded retained output per session

OutputCallback = Callable[[str], Awaitable[None]]

# Marker the shell prints after each submitted batch so we know the command
# finished and can capture $LASTEXITCODE. Chosen to be unlikely in real output.
_MARKER_PREFIX = "__IRIS_EOF_"


def _ps_quote(path: str) -> str:
    """Single-quote a path for PowerShell (double embedded quotes)."""
    return "'" + path.replace("'", "''") + "'"


class ShellSession:
    """One persistent shell subprocess for one conversation session.

    State (cwd, env) persists across commands because the process stays
    alive between them (REQ-1 AC2).
    """

    def __init__(self, session_id: str, workdir: str) -> None:
        self.session_id = session_id
        self.proc_id = f"shell-{uuid.uuid4().hex[:8]}"
        self.spawn_workdir = workdir
        self.last_workdir = workdir
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._cmd_lock = asyncio.Lock()      # one shell ⇒ serialized commands
        self._marker: Optional[str] = None   # marker of the in-flight batch
        self._done = asyncio.Event()
        self._exit_code: Optional[int] = None
        self._flood_reason: Optional[str] = None
        self._aborted: bool = False
        self._cmd_bytes = 0                  # bytes emitted by current command
        self._rate_window: deque = deque()   # (monotonic_ts, nbytes)
        self.buffer: deque = deque(maxlen=OUTPUT_BUFFER_LINES)  # bounded tail
        self._on_output: Optional[OutputCallback] = None

    def set_output_callback(self, cb: Optional[OutputCallback]) -> None:
        """Set the streaming sink for this shell's output lines."""
        self._on_output = cb

    # ── lifecycle ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """Spawn the platform shell reading commands from stdin."""
        if os.name == "nt":
            argv = ["powershell", "-NoExit", "-Command", "-"]
        else:
            shell = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"
            argv = [shell]
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=self.spawn_workdir or None,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # pipe, not terminal: merge
            )
        except OSError as exc:
            # REQ-19 label shell_spawn_failed territory; caller reports and
            # retries on next input (REQ-1 spawn-failure retry rule).
            logger.warning("[ShellSession][%s] spawn failed: %s", self.session_id, exc)
            self.proc = None
            raise

        self._reader_task = asyncio.create_task(
            self._reader(), name=f"shell-reader-{self.session_id}"
        )

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def kill(self) -> None:
        """Terminate this shell's whole process tree (abort path)."""
        # Mark any in-flight command as aborted BEFORE the tree dies, so
        # execute() reports `aborted` rather than a phantom success.
        if not self._done.is_set():
            self._aborted = True
        proc = self.proc
        if proc is None or proc.returncode is not None:
            return
        if os.name == "nt":
            # proc.terminate() kills only the host; children survive.
            # taskkill /T walks the tree — the reliable way on Windows.
            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill", "/PID", str(proc.pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(killer.wait(), timeout=5)
            except (OSError, asyncio.TimeoutError):
                pass
        else:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass

    # ── execution ───────────────────────────────────────────────────────

    async def execute(
        self,
        command: str,
        workdir: Optional[str] = None,
        timeout: Optional[float] = None,
        on_output: Optional[OutputCallback] = None,
    ) -> dict:
        """Run one command batch on this shell; stream output via on_output.

        Returns {success, exit_code | error, timed_out?, flood_reason?}.
        A command that RAN and exited non-zero is success=True + exit_code
        (REQ-19 AC2) — never an error_type.
        """
        if not self.is_alive():
            return {"success": False, "error": "shell is not running"}

        async with self._cmd_lock:
            return await self._execute_locked(command, workdir, timeout, on_output)

    async def _execute_locked(
        self,
        command: str,
        workdir: Optional[str],
        timeout: Optional[float],
        on_output: Optional[OutputCallback],
    ) -> dict:
        # Tab switch (requested workdir differs from the last REQUESTED one,
        # not from the shell's actual cwd — a user's manual `cd` must survive):
        # inject a silent Set-Location ahead of the user's command.
        prelude = ""
        if workdir and os.path.normpath(workdir) != os.path.normpath(self.last_workdir):
            prelude = f"Set-Location -LiteralPath {_ps_quote(workdir)}\n"
            self.last_workdir = workdir

        marker = f"{_MARKER_PREFIX}{uuid.uuid4().hex[:12]}"
        # The reader pump streams through the latest caller's sink; each
        # execute() re-binds it so a reconnecting client gets the output.
        self._on_output = on_output
        self._marker = marker
        self._done.clear()
        self._exit_code = None
        self._flood_reason = None
        self._aborted = False
        self._cmd_bytes = 0
        self._rate_window.clear()

        stdin = self.proc.stdin
        assert stdin is not None
        try:
            if os.name == "nt":
                batch = (
                    prelude
                    + command.replace("\r\n", "\n")
                    + f"\nWrite-Output ('{marker}' + [string]$LASTEXITCODE)\n"
                )
            else:
                batch = prelude + command + f"\necho '{marker}'$?\n"
            stdin.write(batch.encode("utf-8", errors="replace"))
            await stdin.drain()
        except (ConnectionResetError, BrokenPipeError, RuntimeError) as exc:
            return {"success": False, "error": f"shell died writing input: {exc}"}

        try:
            if timeout is not None:
                await asyncio.wait_for(self._done.wait(), timeout=timeout)
            else:
                await self._done.wait()
        except asyncio.TimeoutError:
            await self.kill()
            return {
                "success": False,
                "error": f"command exceeded {timeout}s — terminated",
                "timed_out": True,
            }

        if self._flood_reason:
            return {"success": False, "error": self._flood_reason, "flood": True}
        if self._aborted:
            # REQ-19: `aborted` — the user stopped it, not a tool defect.
            return {"success": False, "error": "aborted by user", "aborted": True}
        return {"success": True, "exit_code": self._exit_code}

    # ── output pump ─────────────────────────────────────────────────────

    async def _reader(self) -> None:
        """Pump stdout lines; detect the completion marker; enforce T2 bounds."""
        proc = self.proc
        assert proc is not None and proc.stdout is not None
        while True:
            raw = await proc.stdout.readline()
            if not raw:  # EOF — shell died
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")

            if self._marker and line.startswith(self._marker):
                suffix = line[len(self._marker):]
                try:
                    self._exit_code = int(suffix) if suffix else 0
                except ValueError:
                    self._exit_code = 0
                self._done.set()
                continue

            self.buffer.append(line)
            now = time.monotonic()
            nbytes = len(raw)
            self._cmd_bytes += nbytes
            self._rate_window.append((now, nbytes))
            while self._rate_window and now - self._rate_window[0][0] > RATE_WINDOW_SECONDS:
                self._rate_window.popleft()

            if self._cmd_bytes > MAX_OUTPUT_BYTES:
                self._flood_reason = (
                    f"output exceeded {MAX_OUTPUT_BYTES // 1024} KB cap — process terminated"
                )
            elif sum(n for _, n in self._rate_window) > RATE_WINDOW_BYTES:
                self._flood_reason = (
                    f"output rate exceeded {RATE_WINDOW_BYTES // 1024} KB in "
                    f"{RATE_WINDOW_SECONDS:.0f}s — process terminated"
                )
            if self._flood_reason:
                await self.kill()
                self._done.set()
                break

            if self._on_output is not None:
                try:
                    outcome = self._on_output(line)
                    if asyncio.iscoroutine(outcome):
                        await outcome  # async sink (WS emit); sync sinks already ran
                except Exception as exc:  # never let a dead socket kill the pump
                    logger.debug("[ShellSession][%s] output callback failed: %s",
                                 self.session_id, exc)

        # Shell exited: REAP it before reading returncode — stdout EOF can
        # arrive while the process is not yet waited-on, leaving returncode
        # None (live-found: 'exit 1' reported exit_code None and the dead
        # shell then looked alive to later callers).
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        if not self._done.is_set():
            self._exit_code = proc.returncode
            self._done.set()


class SubprocessManager:
    """Registry of session shells + the global concurrency cap (T2).

    Each session maps to at most one shell. The semaphore counts CONCURRENT
    COMMAND EXECUTIONS across all sessions — agent commands included once T0c
    routes them here (REQ-5 AC6: one budget, not two).
    """

    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT) -> None:
        self._shells: dict[str, ShellSession] = {}
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._waiting = 0
        # Loop the shells live on. asyncio primitives are loop-bound; agent
        # tool calls run under ephemeral asyncio.run() loops in executor
        # threads, so every shell interaction is hopped onto this loop.
        self._home_loop: Optional[asyncio.AbstractEventLoop] = None

    def note_home_loop(self) -> None:
        """Pin the calling loop as the shells' home loop.

        Called from long-lived WS handlers (terminal_input / dev_cli), never
        from ephemeral tool-execution loops.
        """
        loop = asyncio.get_running_loop()
        if self._home_loop is None or self._home_loop.is_closed():
            self._home_loop = loop

    # ── shell registry ──────────────────────────────────────────────────

    def get_shell(self, session_id: str) -> Optional[ShellSession]:
        return self._shells.get(session_id)

    async def get_or_create_shell(self, session_id: str, workdir: str) -> ShellSession:
        """Return the live shell for this session, spawning/replacing as needed.

        Caller distinguishes fresh spawn vs restart via get_shell()+is_alive()
        beforehand. Spawn failure raises OSError (typed shell_spawn_failed
        upstream); the session entry is left absent so the next input retries.
        """
        existing = self._shells.get(session_id)
        if existing is not None and existing.is_alive():
            return existing
        async with self._lock:
            # re-check under lock
            existing = self._shells.get(session_id)
            if existing is not None and existing.is_alive():
                return existing
            shell = ShellSession(session_id, workdir)
            await shell.start()  # may raise OSError → nothing registered
            self._shells[session_id] = shell
            logger.info("[SubprocessManager][%s] shell spawned (pid=%s, cwd=%s)",
                        session_id, shell.proc.pid, workdir)
            return shell

    def drop_shell(self, session_id: str) -> None:
        self._shells.pop(session_id, None)

    # ── capped execution (user `>` today, agent tools via T0c tomorrow) ──

    async def execute(
        self,
        session_id: str,
        command: str,
        workdir: Optional[str] = None,
        timeout: Optional[float] = None,
        on_output: Optional[OutputCallback] = None,
    ) -> dict:
        """Execute a command on the session shell under the global cap.

        Beyond the cap the caller QUEUES with an explicit position message
        (REQ-5 AC2 edge case), surfaced in the result as queued/position so
        either surface (panel line or agent result) can state it.
        """
        # T0c: agent tool calls arrive on ephemeral executor-thread loops;
        # hop the whole execution onto the shells' home loop so every
        # primitive (locks, events, semaphore, reader task) stays on one loop.
        current = asyncio.get_running_loop()
        home = self._home_loop
        if home is not None and home.is_running() and current is not home:
            fut = asyncio.run_coroutine_threadsafe(
                self._execute_impl(session_id, command, workdir, timeout, on_output),
                home,
            )
            return await asyncio.wrap_future(fut)
        return await self._execute_impl(session_id, command, workdir, timeout, on_output)

    async def _execute_impl(
        self,
        session_id: str,
        command: str,
        workdir: Optional[str] = None,
        timeout: Optional[float] = None,
        on_output: Optional[OutputCallback] = None,
    ) -> dict:
        shell = await self.get_or_create_shell(session_id, workdir or os.getcwd())

        result_extra: dict = {}
        if self._sem.locked():
            self._waiting += 1
            position = self._waiting
            result_extra = {
                "queued": True,
                "position": position,
                "message": (
                    f"{self._max_concurrent} commands running, "
                    f"position {position} in queue"
                ),
            }
            try:
                await self._sem.acquire()
            finally:
                self._waiting -= 1
        else:
            await self._sem.acquire()
        try:
            res = await shell.execute(command, workdir=workdir,
                                      timeout=timeout, on_output=on_output)
        finally:
            self._sem.release()
        res.update(result_extra)
        if not shell.is_alive():
            # dead shell (killed/flooded/exited): unregister so the next
            # input spawns a fresh one and gets the restart notice.
            self.drop_shell(session_id)
        return res

    # ── abort / status (existing semantics preserved) ───────────────────

    async def abort(self, session_id: str) -> None:
        """Kill the session's shell tree. Next input respawns (reported)."""
        shell = self._shells.get(session_id)
        if shell is None:
            return
        await shell.kill()
        self.drop_shell(session_id)
        logger.info("[SubprocessManager][%s] aborted (tree killed)", session_id)

    def is_running(self, session_id: str) -> bool:
        shell = self._shells.get(session_id)
        return shell is not None and shell.is_alive()

    def status(self, session_id: str) -> Optional[dict]:
        shell = self._shells.get(session_id)
        if shell is None:
            return None
        return {
            "proc_id": shell.proc_id,
            "tool": "session-shell",
            "pid": shell.proc.pid if shell.proc else None,
            "alive": shell.is_alive(),
        }


# ── Module-level singleton ──────────────────────────────────────────────────

_manager: Optional[SubprocessManager] = None


def get_subprocess_manager() -> SubprocessManager:
    global _manager
    if _manager is None:
        _manager = SubprocessManager()
    return _manager
