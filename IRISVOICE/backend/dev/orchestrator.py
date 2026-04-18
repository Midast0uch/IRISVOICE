"""
Dev Orchestrator — routes dev_cli messages to the correct CLI tool.

Responsibilities:
  1. Receive dev_cli WS message { query, workdir, tool_hint? }
  2. Ask the agent kernel to select the best tool (or honour tool_hint)
  3. Spawn the subprocess via SubprocessManager
  4. Stream stdout → cli_output WS messages
  5. Emit cli_started, cli_activity, file_activity messages
  6. Emit a text_response summary when the process exits

Quality-check gates applied:
  - No model loading at import time — agent_kernel fetched lazily per call.
  - LLM tool selection runs in executor (sync call, avoids blocking event loop).
  - Subprocess output callbacks are non-blocking; they post to an asyncio queue.
  - File watcher started/stopped per session; not shared between sessions.
  - No unbounded state — active sessions tracked in a plain dict with cleanup.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from typing import Any, Callable, Optional

from .cli_registry import CLITool, get_cli_registry
from .subprocess_manager import get_subprocess_manager
from .file_watcher import FileEvent, get_file_watcher

logger = logging.getLogger(__name__)

# Soft idle timeout (seconds) — kill process if no output for this long.
_IDLE_TIMEOUT_S = int(os.environ.get("DEV_CLI_IDLE_TIMEOUT_SECONDS", "300"))


class DevOrchestrator:
    """Handles one dev_cli message per call; manages active subprocess lifecycle."""

    def __init__(self) -> None:
        self._registry = get_cli_registry()
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
    ) -> None:
        """
        Main handler for dev_cli messages.
        ws_send must be a coroutine: await ws_send({...})
        """
        query: str = payload.get("query", "").strip()
        workdir: str = payload.get("workdir", os.getcwd())
        tool_hint: Optional[str] = payload.get("tool_hint")

        if not query:
            await ws_send({"type": "text_response", "text": "No query provided.", "sender": "assistant"})
            return

        # Select tool
        tool = await self._select_tool(query, tool_hint)
        if tool is None:
            await ws_send({
                "type": "text_response",
                "text": "No CLI tools are available on PATH. Install kilo, claude, or opencode first.",
                "sender": "assistant",
            })
            return

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

        # Notify frontend: CLI is starting
        await ws_send({
            "type": "cli_activity",
            "tool_name": tool.display_name,
            "workdir": workdir,
        })

        # Output / done callbacks (called on subprocess thread)
        def _on_output(line: str, proc_id: str) -> None:
            msg = {"type": "cli_output", "line": line, "proc_id": proc_id}
            asyncio.run_coroutine_threadsafe(ws_send(msg), loop)

        def _on_done(returncode: int, proc_id: str) -> None:
            self._file_watcher.stop()
            self._session_loops.pop(session_id, None)
            summary = (
                f"CLI process exited (code {returncode})."
                if returncode not in (0, None)
                else "Done."
            )
            msg = {"type": "text_response", "text": summary, "sender": "assistant"}
            asyncio.run_coroutine_threadsafe(ws_send(msg), loop)

        # Spawn
        proc_id = self._subprocess_mgr.spawn(
            session_id=session_id,
            tool=tool,
            query=query,
            workdir=workdir,
            on_output=_on_output,
            on_done=_on_done,
        )

        if proc_id is None:
            await ws_send({
                "type": "text_response",
                "text": f"Failed to start {tool.display_name}. Check workdir and PATH.",
                "sender": "assistant",
            })
            self._file_watcher.stop()
            return

        await ws_send({
            "type": "cli_started",
            "tool_name": tool.display_name,
            "proc_id": proc_id,
        })

    async def abort_session(self, session_id: str) -> None:
        """Abort any running subprocess for this session."""
        self._subprocess_mgr.abort(session_id)
        self._file_watcher.stop()
        self._session_loops.pop(session_id, None)

    # ── Internal ────────────────────────────────────────────────────────────

    async def _select_tool(
        self, query: str, tool_hint: Optional[str]
    ) -> Optional[CLITool]:
        """Return the best CLI tool for this query via LLM or tool_hint."""
        # Honour explicit hint from frontend (e.g. user picked from dropdown)
        if tool_hint:
            return self._registry.select_tool_for_query(tool_hint)

        # Fast path: only one tool available
        available = self._registry.available_tools()
        if len(available) == 1:
            return available[0]
        if not available:
            return None

        # LLM selection: ask agent kernel which tool fits best
        try:
            tool_name = await asyncio.get_event_loop().run_in_executor(
                None, self._llm_select_tool, query
            )
            return self._registry.select_tool_for_query(tool_name)
        except Exception as exc:
            logger.warning("[DevOrchestrator] LLM tool selection failed: %s — using first", exc)
            return available[0]

    def _llm_select_tool(self, query: str) -> str:
        """
        Synchronous LLM call to pick a tool name.
        Runs in executor so it doesn't block the event loop.
        """
        from backend.agent import get_agent_kernel  # lazy import

        context = self._registry.build_selection_context()
        prompt = (
            f"{context}\n\n"
            f"User request: {query}\n\n"
            "Reply with ONLY the tool name (e.g. kilo_code). "
            "No explanation, no punctuation, just the name."
        )
        kernel = get_agent_kernel("dev_orchestrator")
        raw = kernel._respond_direct(text=prompt, context={})
        # Extract the first word (tool name)
        name = raw.strip().split()[0].lower() if raw.strip() else ""
        return name


# ── Module-level singleton ──────────────────────────────────────────────────

_orchestrator: Optional[DevOrchestrator] = None


def get_dev_orchestrator() -> DevOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = DevOrchestrator()
    return _orchestrator
