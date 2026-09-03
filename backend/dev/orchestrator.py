"""
Dev Orchestrator — routes dev_cli messages to IRIS's own AgentKernel (REQ-0).

Responsibilities:
  1. Receive dev_cli WS message { query, workdir? }
  2. Dispatch the query to the AgentKernel turn path with the session's
     conversation context (D7 — external CLI registry removed, not demoted).
  3. Stream the turn's output → cli_output WS messages
  4. Emit cli_started, cli_activity, file_activity messages
  5. Emit a text_response summary when the turn completes

The frontend contract is unchanged: cli_activity / cli_started / cli_output
keep the shapes at types/iris.ts:258-272.

Quality-check gates applied:
  - No model loading at import time — agent_kernel fetched lazily per call.
  - The kernel turn runs in an executor (sync call, avoids blocking event loop).
  - Output callbacks are non-blocking; they post to the asyncio loop.
  - File watcher started/stopped per session; not shared between sessions.
  - No unbounded state — active sessions tracked in a plain dict with cleanup.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, Callable, Optional

from .subprocess_manager import get_subprocess_manager
from .file_watcher import FileEvent, get_file_watcher

logger = logging.getLogger(__name__)

# Display name surfaced in cli_* events — IRIS's own agent, not an external CLI.
_AGENT_DISPLAY_NAME = "IRIS Agent"


class DevOrchestrator:
    """Handles one dev_cli message per call; runs it as an IRIS agent turn."""

    def __init__(self) -> None:
        self._subprocess_mgr = get_subprocess_manager()
        self._file_watcher = get_file_watcher()
        # session_id → asyncio loop reference (so callbacks can post events)
        self._session_loops: dict[str, asyncio.AbstractEventLoop] = {}

    # ── Public entry point ──────────────────────────────────────────────────

    async def handle_dev_cli(
        self,
        session_id: str,
        payload: dict[str, Any],
        ws_send: Callable[[dict], Any],  # coroutine that sends a WS message
        conversation_id: Optional[str] = None,
    ) -> None:
        """
        Main handler for dev_cli messages.
        ws_send must be a coroutine: await ws_send({...})
        conversation_id: the caller's active conversation thread, so /run joins
        the user's live context instead of a detached one. Falls back to
        session_id when unknown.
        """
        query: str = payload.get("query", "").strip()
        conv_id = conversation_id or session_id

        if not query:
            await ws_send({"type": "text_response", "text": "No query provided.", "sender": "assistant"})
            return

        # T0c: pin this WS loop as the session shells' home loop so agent
        # tool executions (ephemeral executor loops) hop onto it.
        self._subprocess_mgr.note_home_loop()

        # T3 (REQ-4 AC3): validate an explicit workdir before anything uses
        # it; omitted workdir falls back to the backend default.
        from .terminal_handler import validate_workdir

        workdir = payload.get("workdir") or os.getcwd()
        workdir_error = validate_workdir(workdir)
        if workdir_error:
            await ws_send({
                "type": "text_response",
                "text": workdir_error,
                "sender": "assistant",
            })
            return

        # ── T8a (REQ-10): /review — delete-list contract ────────────────
        if query.startswith("/review"):
            scope = query[len("/review"):].strip().strip('"') or None
            from .slash_commands import build_review_prompt, get_diff

            diff = get_diff(workdir, scope)
            if diff is None:
                await ws_send({"type": "text_response",
                               "text": f"No git repository at {workdir}",
                               "sender": "assistant"})
                return
            if not diff.strip():
                await ws_send({"type": "text_response",
                               "text": "No changes to review.",
                               "sender": "assistant"})
                return
            query = build_review_prompt(diff)

        # ── T8b (REQ-11): /debt — marker scan into task cards ───────────
        elif query.startswith("/debt"):
            from .slash_commands import save_debt_cards, scan_debt_markers

            markers = scan_debt_markers(workdir)
            new_count, dup_count = save_debt_cards(conv_id, markers)
            if not markers:
                text = "Debt ledger clean — no deferred markers found."
            else:
                text = (f"Debt ledger: {len(markers)} marker(s) found — "
                        f"{new_count} new card(s), {dup_count} already tracked.")
                for m in markers[:20]:
                    text += f"\n• {m['file']}:{m['line']} — {m['text']}"
                if len(markers) > 20:
                    text += f"\n… and {len(markers) - 20} more"
            await ws_send({"type": "text_response", "text": text,
                           "sender": "assistant"})
            return

        # REQ-4 AC5: bind the session workdir so the agent's dev tools
        # (run_command, git_*) execute in the active tab's directory.
        try:
            from backend.agent.tool_bridge import get_agent_tool_bridge

            get_agent_tool_bridge().set_session_workdir(session_id, workdir)
        except Exception as exc:
            logger.warning(
                "[DevOrchestrator][%s] could not bind workdir '%s': %s",
                session_id, workdir, exc,
            )

        # Store loop reference for thread callbacks
        loop = asyncio.get_event_loop()
        self._session_loops[session_id] = loop

        # Start file watcher
        def _on_file_event(event: FileEvent) -> None:
            msg = {
                "type": "file_activity",
                "path": event.path,
                "change": event.change,
            }
            asyncio.run_coroutine_threadsafe(ws_send(msg), loop)

        self._file_watcher.start(workdir, _on_file_event)

        # Notify frontend: the agent turn is starting
        await ws_send({
            "type": "cli_activity",
            "tool_name": _AGENT_DISPLAY_NAME,
            "workdir": workdir,
        })

        proc_id = f"iris-agent-{uuid.uuid4().hex[:8]}"
        await ws_send({
            "type": "cli_started",
            "tool_name": _AGENT_DISPLAY_NAME,
            "proc_id": proc_id,
        })

        # Stream the turn: chunk_callback fires on the executor thread, so post
        # complete lines to the loop fire-and-forget. Chunks are not
        # line-aligned — buffer until newline, flush the remainder at the end.
        line_buffer = {"text": ""}

        def _post_line(line: str) -> None:
            msg = {"type": "cli_output", "line": line, "proc_id": proc_id}
            asyncio.run_coroutine_threadsafe(ws_send(msg), loop)

        def _chunk_cb(chunk: str) -> None:
            line_buffer["text"] += chunk
            while "\n" in line_buffer["text"]:
                line, _, rest = line_buffer["text"].partition("\n")
                line_buffer["text"] = rest
                if line:
                    _post_line(line)

        def _run_turn() -> str:
            from backend.agent import get_agent_kernel  # lazy import

            kernel = get_agent_kernel(conv_id, session_id)
            if getattr(kernel, "_tool_bridge", None) is None:
                from backend.agent.tool_bridge import get_agent_tool_bridge

                kernel._tool_bridge = get_agent_tool_bridge()
            return kernel.process_text_message(
                query,
                session_id=session_id,
                conversation_id=conv_id,
                chunk_callback=_chunk_cb,
                turn_id=proc_id,
            )

        try:
            response = await loop.run_in_executor(None, _run_turn)
        except Exception as exc:
            logger.error("[DevOrchestrator][%s] agent turn failed: %s", session_id, exc)
            response = f"Agent turn failed: {exc}"
        finally:
            remainder = line_buffer["text"].strip()
            if remainder:
                _post_line(remainder)
            self._file_watcher.stop()
            self._session_loops.pop(session_id, None)

        # ── T4b (REQ-15): verification gate on turns that wrote files ───
        try:
            from backend.agent.tool_bridge import get_agent_tool_bridge

            written = get_agent_tool_bridge().pop_turn_writes(session_id)
            if written:
                from .verification import run_verification_async

                async def _gate_exec(cmd: str, timeout: int) -> dict:
                    return await self._subprocess_mgr.execute(
                        session_id, cmd, workdir=workdir, timeout=timeout,
                    )

                verdict = await run_verification_async(workdir, written,
                                                       execute_fn=_gate_exec)
                response = (response or "") + "\n\n" + verdict
        except Exception as exc:  # never let the gate break the turn result
            logger.warning("[DevOrchestrator][%s] verification gate skipped: %s",
                           session_id, exc)

        await ws_send({
            "type": "text_response",
            "text": response or "Done.",
            "sender": "assistant",
        })

    async def abort_session(self, session_id: str) -> None:
        """Abort any running subprocess for this session."""
        self._subprocess_mgr.abort(session_id)
        self._file_watcher.stop()
        self._session_loops.pop(session_id, None)


# ── Module-level singleton ──────────────────────────────────────────────────

_orchestrator: Optional[DevOrchestrator] = None


def get_dev_orchestrator() -> DevOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = DevOrchestrator()
    return _orchestrator
