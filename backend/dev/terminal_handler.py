"""
Terminal Handler — routes user `>` commands onto the persistent session shell.

Gate 3 T1 (REQ-1): every terminal_input line executes on a per-session
persistent shell owned by subprocess_manager. Output streams back as
`terminal_output { line, proc_id }` (design CONTRACT LOCK). Shell state
(cwd, env) persists across commands; a dead shell is restarted on the next
input with a reported restart (REQ-1 AC3).

Gate 3 T3 (REQ-4 AC3): an explicitly supplied workdir that does not exist
or is not accessible is rejected with an error naming the path; omitted
workdir falls back to the backend default.

It is a pipe, not a terminal: no PTY, no ANSI parsing, no completion.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

from .subprocess_manager import get_subprocess_manager

logger = logging.getLogger(__name__)

# Callable that awaits one WS message dict to the originating client.
WsSend = Callable[[dict], Any]


def validate_workdir(workdir: str) -> Optional[str]:
    """T3 (REQ-4 AC3): return an error message naming the path, or None if OK."""
    if not workdir:
        return None
    try:
        if not os.path.isdir(workdir):
            return f"Workdir does not exist: {workdir}"
        # accessibility probe — isdir can pass on permission-truncated paths
        os.listdir(workdir)
    except OSError as exc:
        return f"Workdir is not accessible: {workdir} ({exc})"
    return None


class TerminalHandler:
    """Handles terminal_input messages for all sessions."""

    def __init__(self) -> None:
        self._mgr = get_subprocess_manager()

    async def handle_input(
        self,
        session_id: str,
        line: str,
        ws_send: WsSend,
        workdir: Optional[str] = None,
    ) -> None:
        """Execute one user command line on the session shell.

        ws_send must be awaitable: await ws_send({...}).
        """
        line = (line or "").strip()
        if not line:
            return  # empty line toggles the panel client-side (existing behavior)

        # Pin this long-lived WS loop as the shells' home loop (T0c: agent
        # tool calls hop here from ephemeral executor loops).
        self._mgr.note_home_loop()

        # T3: validate an explicit workdir before anything spawns.
        workdir_error = validate_workdir(workdir or "")
        if workdir_error:
            await self._emit(ws_send, session_id, workdir_error)
            return

        # REQ-1 AC3: a dead/absent shell respawns here; if we are replacing
        # one that died, say so before running the command.
        replaced_dead = (
            self._mgr.get_shell(session_id) is not None
            and not self._mgr.is_running(session_id)
        )

        async def _out(text: str) -> None:
            await self._emit(ws_send, session_id, text)

        try:
            if replaced_dead:
                await _out("Shell restarted.")

            captured: list[str] = []

            def _on_output(line: str):
                captured.append(line)
                return self._emit(ws_send, session_id, line)

            result = await self._mgr.execute(
                session_id,
                line,
                workdir=workdir,
                on_output=_on_output,
            )

            # T4 (REQ-2): queue the completed command for next-turn injection.
            from .shell_records import get_shell_record_queue, is_denied_target

            if is_denied_target(line):
                get_shell_record_queue().mark_suppressed(session_id, line)
                await _out("[injection suppressed — command targets a secret source]")
            else:
                get_shell_record_queue().record(
                    session_id, line, result.get("exit_code"),
                    "\n".join(captured), workdir or os.getcwd(),
                )
        except OSError as exc:
            # spawn failure: report and retry on next input (REQ-1 rule)
            logger.warning("[TerminalHandler][%s] spawn failed: %s", session_id, exc)
            self._mgr.drop_shell(session_id)
            await _out(f"shell_spawn_failed: could not start shell ({exc}). Try again.")
            return
        except Exception as exc:  # noqa: BLE001 — never crash the WS loop
            logger.exception("[TerminalHandler][%s] input error", session_id)
            await _out(f"Terminal error: {exc}")
            return

        # Stated outcomes beyond plain output (T2 messages surface verbatim).
        if result.get("queued"):
            await _out(str(result.get("message")))
        if result.get("aborted"):
            await _out("^C aborted")
        elif result.get("flood"):
            await _out(str(result.get("error")))
        elif not result.get("success") and result.get("error"):
            await _out(str(result.get("error")))
        elif result.get("success") and isinstance(result.get("exit_code"), int) \
                and result["exit_code"] != 0:
            # REQ-19 AC2 shape at the panel level: the command RAN and failed.
            await _out(f"[exit {result['exit_code']}]")

    async def _emit(self, ws_send: WsSend, session_id: str, text: str) -> None:
        """Emit one terminal_output line (design CONTRACT LOCK shape)."""
        from .subprocess_manager import get_subprocess_manager as _gsm

        shell = _gsm().get_shell(session_id)
        proc_id = shell.proc_id if shell else f"shell-{session_id}"
        try:
            await ws_send({"type": "terminal_output", "line": text, "proc_id": proc_id})
        except Exception as exc:  # dead socket must not kill the pump
            logger.debug("[TerminalHandler][%s] emit failed: %s", session_id, exc)


_handler: Optional[TerminalHandler] = None


def get_terminal_handler() -> TerminalHandler:
    global _handler
    if _handler is None:
        _handler = TerminalHandler()
    return _handler
