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
STALL_SECONDS = 30.0                # no output AND no CPU this long = waiting, not working
WATCH_TICK_SECONDS = 2.0            # how often a running agent command is looked at
MAX_BACKGROUND_PER_SESSION = 4      # running handles kept per session (oldest stopped)
TAIL_LINES = 40                     # output lines returned with a status

# Environment for agent commands: nothing may stop to ask a person. A tool that
# opens an editor, a pager, a password prompt or a credential window would wait
# forever; Python buffers piped output, so a working script would look silent.
_NON_INTERACTIVE_ENV = {
    "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "GIT_EDITOR": "true",
    "EDITOR": "true", "VISUAL": "true", "GIT_PAGER": "cat", "PAGER": "cat",
    "CI": "1", "PIP_NO_INPUT": "1", "npm_config_yes": "true",
    "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
}

OutputCallback = Callable[[str], Awaitable[None]]

# Marker the shell prints after each submitted batch so we know the command
# finished and can capture $LASTEXITCODE. Chosen to be unlikely in real output.
_MARKER_PREFIX = "__IRIS_EOF_"


def _ps_quote(path: str) -> str:
    """Single-quote a path for PowerShell (double embedded quotes)."""
    return "'" + path.replace("'", "''") + "'"


_AGENT_SHELL: Optional[tuple] = None  # (name, argv prefix), resolved once


def agent_shell() -> tuple:
    """(name, argv prefix) of the shell that runs ONE agent command.

    Windows: Git Bash when installed - the models write bash (heredocs, &&) -
    else PowerShell. Never System32\\bash.exe: that is the WSL launcher and runs
    the command inside Linux. POSIX: bash, else sh.
    """
    global _AGENT_SHELL
    if _AGENT_SHELL is None:
        if os.name == "nt":
            bash = None
            git = shutil.which("git")
            # git is ...\Git\cmd\git.exe or ...\Git\mingw64\bin\git.exe
            root = os.path.dirname(git) if git else ""
            for _ in range(3 if git else 0):
                root = os.path.dirname(root)
                for rel in (("bin", "bash.exe"), ("usr", "bin", "bash.exe")):
                    cand = os.path.join(root, *rel)
                    if os.path.isfile(cand):
                        bash = cand
                        break
                if bash:
                    break
            _AGENT_SHELL = (
                ("bash", [bash, "--noprofile", "--norc", "-c"]) if bash
                else ("powershell", ["powershell", "-NoProfile", "-NonInteractive", "-Command"])
            )
        else:
            sh = shutil.which("bash") or "/bin/sh"
            _AGENT_SHELL = ("bash" if sh.endswith("bash") else "sh", [sh, "-c"])
        logger.info("[SubprocessManager] agent commands run in %s (%s)",
                    _AGENT_SHELL[0], _AGENT_SHELL[1][0])
    return _AGENT_SHELL


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
        self.lines_total = 0                 # lines seen (read cursor for a handle)
        self.last_output_at = time.monotonic()

    def set_output_callback(self, cb: Optional[OutputCallback]) -> None:
        """Set the streaming sink for this shell's output lines."""
        self._on_output = cb

    # ── lifecycle ───────────────────────────────────────────────────────

    async def start(self, argv: Optional[list] = None, env: Optional[dict] = None) -> None:
        """Spawn the platform shell reading commands from stdin.

        With *argv*: spawn that ONE command instead, with an empty, closed
        stdin (an agent command - see SubprocessManager.run_isolated).
        """
        one_shot = argv is not None
        if not one_shot:
            if os.name == "nt":
                argv = ["powershell", "-NoExit", "-Command", "-"]
            else:
                shell = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"
                argv = [shell]
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=self.spawn_workdir or None,
                env=env,
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

        if one_shot and self.proc.stdin is not None:
            # An empty pipe, closed: a reader sees end-of-file. Not DEVNULL - on
            # Windows NUL counts as a console, and `python -` opened its REPL.
            self.proc.stdin.close()
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
            self.lines_total += 1
            now = time.monotonic()
            self.last_output_at = now
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


def _tree_cpu_seconds(pid: int) -> Optional[float]:
    """User+system CPU seconds of *pid* and its children; None if unreadable."""
    try:
        import psutil

        p = psutil.Process(pid)
        total = sum(p.cpu_times()[:2])
        for c in p.children(recursive=True):
            try:
                total += sum(c.cpu_times()[:2])
            except psutil.Error:
                continue
        return total
    except Exception:  # noqa: BLE001 - no reading = no CPU evidence, output still counts
        return None


def _tail(proc: "ShellSession") -> str:
    return "\n".join(list(proc.buffer)[-TAIL_LINES:]).strip()


def _emit(proc: "ShellSession", status: str, **extra) -> None:
    cb = getattr(proc, "on_event", None)
    if cb is None:
        return
    try:
        cb({"id": proc.handle, "command": proc.command[:300], "status": status,
            "elapsed_s": round(time.monotonic() - proc.started_at, 1), **extra})
    except Exception as exc:  # noqa: BLE001 - display never breaks a command
        logger.debug("[SubprocessManager] command event failed: %s", exc)


def _finish(proc: "ShellSession", error: Optional[str] = None, status: Optional[str] = None) -> dict:
    """Final result of an agent command (and its last display event), once."""
    if getattr(proc, "final_status", None) is None:
        if status is None:
            status = ("failed" if proc._flood_reason else "stopped" if proc._aborted
                      else "done" if (proc._exit_code or 0) == 0 else "failed")
        proc.final_status = status
        _emit(proc, status, exit_code=proc._exit_code)
    tail = _tail(proc)
    if error or proc._flood_reason or proc._aborted:
        res = {"success": False, "error": error or proc._flood_reason or "aborted by user", "stdout": tail}
        if proc._flood_reason:
            res["flood"] = True
        if status == "timed_out" or proc.final_status == "timed_out":
            res["timed_out"] = True
        if proc._aborted and not error and not proc._flood_reason:
            res["aborted"] = True
        return res
    return {"success": True, "exit_code": proc._exit_code}


class SubprocessManager:
    """Registry of session shells + the global concurrency cap (T2).

    Each session maps to at most one shell. The semaphore counts CONCURRENT
    COMMAND EXECUTIONS across all sessions — agent commands included once T0c
    routes them here (REQ-5 AC6: one budget, not two).
    """

    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT) -> None:
        self._shells: dict[str, ShellSession] = {}
        self._one_shots: dict[str, set] = {}  # session -> running agent commands
        self._jobs: dict[str, dict] = {}      # session -> {handle: backgrounded command}
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

    # ── agent commands: one process each, no shared stdin ───────────────

    async def run_isolated(
        self,
        session_id: str,
        command,
        workdir: Optional[str] = None,
        timeout: Optional[float] = None,
        on_output: Optional[OutputCallback] = None,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Run ONE agent command in its own process, stdin closed.

        The session shell reads its commands from a stdin pipe that a native
        child inherits: `python - <<'PY'` swallowed the next lines, including
        the completion marker, and waited for the 300 s limit (eval c02,
        2026-10-02). Here nothing can read the command stream. A str runs in
        agent_shell(); a list/tuple is an argv, run with no shell. Same global
        cap, output bounds, timeout and tree kill as execute(); abort() kills it.

        Stall watch (owner 2026-10-02): every WATCH_TICK_SECONDS the command's
        output and its process tree's CPU are read. No output AND no CPU for
        STALL_SECONDS means it waits on something (network, a lock, a prompt)
        or is a server - the call returns at once with running=True, a handle
        and the output so far, and the command keeps running (command_status
        reads or stops it). A busy command (CPU in use) is never cut short.
        Every failed end carries the last TAIL_LINES of output. on_event gets
        one dict per status change (running / waiting / done / failed /
        timed_out / stopped) for the workspace display.
        """
        current = asyncio.get_running_loop()
        home = self._home_loop
        if home is not None and home.is_running() and current is not home:
            fut = asyncio.run_coroutine_threadsafe(
                self._run_isolated_impl(session_id, command, workdir, timeout, on_output, on_event),
                home,
            )
            return await asyncio.wrap_future(fut)
        return await self._run_isolated_impl(session_id, command, workdir, timeout, on_output, on_event)

    async def _run_isolated_impl(self, session_id, command, workdir, timeout, on_output,
                                 on_event=None) -> dict:
        argv = list(command) if isinstance(command, (list, tuple)) else agent_shell()[1] + [command]
        proc = ShellSession(session_id, workdir or os.getcwd())
        proc._on_output = on_output
        proc.handle = f"cmd-{uuid.uuid4().hex[:6]}"
        proc.command = command if isinstance(command, str) else " ".join(map(str, command))
        proc.started_at = time.monotonic()
        proc.deadline = proc.started_at + timeout if timeout else None
        proc.on_event = on_event
        # Backgrounding needs a loop that outlives this call: the shells' home
        # loop. An ephemeral loop (no home loop yet) waits to the end instead.
        can_background = self._home_loop is not None and asyncio.get_running_loop() is self._home_loop
        await self._sem.acquire()
        held = True
        self._one_shots.setdefault(session_id, set()).add(proc)
        try:
            try:
                await proc.start(argv=argv, env={**os.environ, **_NON_INTERACTIVE_ENV})
            except OSError as exc:
                return {"success": False, "error": f"could not start command: {exc}"}
            _emit(proc, "running")
            cpu_prev, cpu_active_at = None, proc.started_at
            while True:
                try:
                    await asyncio.wait_for(proc._done.wait(), timeout=WATCH_TICK_SECONDS)
                    return _finish(proc)
                except asyncio.TimeoutError:
                    pass
                now = time.monotonic()
                if proc.deadline is not None and now >= proc.deadline:
                    await proc.kill()
                    return _finish(proc, error=f"command exceeded {timeout:.0f}s — terminated",
                                   status="timed_out")
                cpu = _tree_cpu_seconds(proc.proc.pid)
                if cpu is not None and (cpu_prev is None or cpu - cpu_prev >= 0.05):
                    cpu_active_at = now
                cpu_prev = cpu if cpu is not None else cpu_prev
                quiet = now - max(proc.last_output_at, cpu_active_at)
                if quiet >= STALL_SECONDS and can_background:
                    # Waiting on something (network, a lock, a prompt) or a
                    # server: hand control back to the agent, keep it running.
                    self._one_shots[session_id].discard(proc)
                    self._sem.release()
                    held = False
                    self._keep_in_background(session_id, proc)
                    _emit(proc, "waiting", idle_s=round(quiet))
                    return {
                        "success": True, "running": True, "handle": proc.handle,
                        "elapsed_s": round(now - proc.started_at), "idle_s": round(quiet),
                        "stdout": _tail(proc),
                        "note": (f"still running after {now - proc.started_at:.0f}s with no output "
                                 f"and no CPU for {quiet:.0f}s - it is waiting on something, or it "
                                 f"is a server. Handle {proc.handle}: read_command_output to look "
                                 f"again, stop_command to stop it."),
                    }
        finally:
            if held:
                self._one_shots.get(session_id, set()).discard(proc)
                self._sem.release()

    def _keep_in_background(self, session_id: str, proc: "ShellSession") -> None:
        jobs = self._jobs.setdefault(session_id, {})
        jobs[proc.handle] = proc
        while len(jobs) > MAX_BACKGROUND_PER_SESSION:   # bounded: stop the oldest
            oldest = next(iter(jobs))
            asyncio.ensure_future(jobs.pop(oldest).kill())
        asyncio.ensure_future(self._reap(session_id, proc))

    async def _reap(self, session_id: str, proc: "ShellSession") -> None:
        """A background command ends by itself or at its own deadline."""
        try:
            remaining = None if proc.deadline is None else max(0.0, proc.deadline - time.monotonic())
            await asyncio.wait_for(proc._done.wait(), timeout=remaining)
            _finish(proc)
        except asyncio.TimeoutError:
            await proc.kill()
            _finish(proc, error="time limit reached in the background — terminated", status="timed_out")
        except Exception as exc:  # noqa: BLE001 - a reaper never raises into the loop
            logger.debug("[SubprocessManager][%s] reap %s failed: %s", session_id, proc.handle, exc)

    async def command_status(self, session_id: str, handle: str, stop: bool = False) -> dict:
        """Status + new output of a background agent command; *stop* kills it first."""
        current = asyncio.get_running_loop()
        home = self._home_loop
        if home is not None and home.is_running() and current is not home:
            fut = asyncio.run_coroutine_threadsafe(self._command_status(session_id, handle, stop), home)
            return await asyncio.wrap_future(fut)
        return await self._command_status(session_id, handle, stop)

    async def _command_status(self, session_id: str, handle: str, stop: bool) -> dict:
        proc = self._jobs.get(session_id, {}).get(handle)
        if proc is None:
            return {"success": False,
                    "error": f"no running command {handle!r} (it ended and was read, or the handle is wrong)"}
        if stop and not proc._done.is_set():
            await proc.kill()
            _finish(proc, error="stopped by the agent", status="stopped")
        now = time.monotonic()
        new = proc.lines_total - getattr(proc, "read_cursor", 0)
        proc.read_cursor = proc.lines_total
        lines = list(proc.buffer)[-new:] if new > 0 else []
        done = proc._done.is_set()
        if done:
            self._jobs.get(session_id, {}).pop(handle, None)
        out = {
            "success": True, "handle": handle, "running": not done,
            "status": getattr(proc, "final_status", None) or ("running" if not done else "done"),
            "elapsed_s": round(now - proc.started_at),
            "idle_s": round(now - proc.last_output_at),
            "stdout": "\n".join(lines[-TAIL_LINES:]).strip() or "(no new output)",
        }
        if done and proc._exit_code is not None:
            out["returncode"] = proc._exit_code
        return out

    # ── abort / status (existing semantics preserved) ───────────────────

    async def abort(self, session_id: str) -> None:
        """Kill the session's shell tree and its agent commands. Next input respawns (reported)."""
        for one in list(self._one_shots.get(session_id, ())) + list(self._jobs.pop(session_id, {}).values()):
            await one.kill()
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
