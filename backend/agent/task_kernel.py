#!/usr/bin/env python3
"""
TaskKernel — subscribes to tool-call events and sends structured
events to the frontend for rendering (TaskListCard progress, etc).

Architecture:
  AgentKernel (DER loop) --emit--> EventBus --dispatch--> TaskKernel
                                                             |
                                                     emits WS messages
                                                             v
                                                      Frontend UI

TaskKernel never speaks via TTS — that is ConversationKernel's job.
It emits structured data events for the frontend to render.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

from backend.agent.event_bus import (
    EventBus,
    EventPayload,
    IRISStreamEvent,
    get_event_bus,
)

logger = logging.getLogger(__name__)


# ── Data types ─────────────────────────────────────────────────────────────


@dataclass
class TaskStep:
    """A single step in an agent task."""

    step_number: int
    description: str
    status: str = "pending"  # pending | in_progress | completed | failed
    tool_name: Optional[str] = None
    result_summary: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Task:
    """An agent task with multiple steps."""

    task_id: str
    description: str
    conversation_id: str = "default"
    steps: List[TaskStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    status: str = "in_progress"  # in_progress | completed | failed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "conversation_id": self.conversation_id,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "status": self.status,
            "step_count": len(self.steps),
            "completed_count": sum(1 for s in self.steps if s.status == "completed"),
        }


# ── TaskKernel ─────────────────────────────────────────────────────────────


class TaskKernel:
    """Subscribes to tool-call events, tracks progress, emits to frontend.

    Responsibilities:
      - Listen for tool:call, tool:result, tool:error events
      - Track task progress as structured Task objects
      - Emit task:start, task:progress, task:milestone, task:done events
      - Never speaks via TTS
      - Handler isolation: failures never crash the DER loop
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        ws_sender: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        """
        Args:
            event_bus: EventBus to subscribe to (uses singleton if None).
            ws_sender: Callable to send structured messages to the frontend.
                       Signature: ws_sender(type, payload). If None, emits
                       events on EventBus instead (for testing).
        """
        self._event_bus = event_bus or get_event_bus()
        self._ws_sender = ws_sender
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.Lock()

        # Subscribe to events
        self._event_bus.subscribe(IRISStreamEvent.TOOL_CALL, self._on_tool_call)
        self._event_bus.subscribe(IRISStreamEvent.TOOL_RESULT, self._on_tool_result)
        self._event_bus.subscribe(IRISStreamEvent.TOOL_ERROR, self._on_tool_error)
        self._event_bus.subscribe(IRISStreamEvent.TASK_START, self._on_task_start)

    def _on_tool_call(self, payload: EventPayload) -> None:
        """Handle a tool:call event."""
        data = payload.data or {}
        task_id = data.get("task_id") or payload.turn_id or "unknown"
        tool_name = data.get("tool_name", "unknown")
        step_desc = data.get("description", tool_name)

        with self._lock:
            if task_id not in self._tasks:
                self._tasks[task_id] = Task(
                    task_id=task_id,
                    description=data.get("task_description", tool_name),
                    conversation_id=payload.conversation_id,
                )
            task = self._tasks[task_id]
            step = TaskStep(
                step_number=len(task.steps) + 1,
                description=step_desc,
                status="in_progress",
                tool_name=tool_name,
            )
            task.steps.append(step)

        # Emit progress
        self._emit_frontend(
            "task:progress",
            {
                "task_id": task_id,
                "step": step.to_dict(),
                "task": task.to_dict(),
            },
            payload,
        )

    def _on_tool_result(self, payload: EventPayload) -> None:
        """Handle a tool:result event."""
        data = payload.data or {}
        task_id = data.get("task_id") or payload.turn_id or "unknown"
        result_summary = data.get("result_summary", str(data.get("result", ""))[:200])

        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.steps:
                step = task.steps[-1]
                step.status = "completed"
                step.result_summary = result_summary
                step.completed_at = time.time()

        if task:
            self._emit_frontend(
                "task:milestone",
                {
                    "task_id": task_id,
                    "step": step.to_dict() if task.steps else None,
                    "task": task.to_dict(),
                },
                payload,
            )

    def _on_tool_error(self, payload: EventPayload) -> None:
        """Handle a tool:error event."""
        data = payload.data or {}
        task_id = data.get("task_id") or payload.turn_id or "unknown"
        error_msg = str(data.get("error", "unknown error"))[:200]

        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.steps:
                step = task.steps[-1]
                step.status = "failed"
                step.result_summary = f"Error: {error_msg}"
                step.completed_at = time.time()

        if task:
            self._emit_frontend(
                "task:milestone",
                {
                    "task_id": task_id,
                    "error": error_msg,
                    "task": task.to_dict(),
                },
                payload,
            )

    def _on_task_start(self, payload: EventPayload) -> None:
        """Handle a task:start event — sent when DER begins planning."""
        data = payload.data or {}
        task_id = data.get("task_id") or payload.turn_id or "unknown"

        with self._lock:
            self._tasks[task_id] = Task(
                task_id=task_id,
                description=data.get("description", "Agent task"),
                conversation_id=payload.conversation_id,
            )

        # REQ-3 AC5: forward planned steps so the frontend renders the real
        # plan, not a re-constructed empty one. Steps come from the planner
        # (agent_kernel.py:5484-5492) and must survive _on_task_start.
        steps = data.get("steps", [])
        total_steps = len(steps) or data.get("total_steps", 0)
        plan_title = data.get("plan_title")
        self._emit_frontend(
            "task:start",
            {
                "task_id": task_id,
                "description": data.get("description", "Agent task"),
                "plan_title": plan_title,
                "steps": steps,
                "total_steps": total_steps,
                "task": self._tasks[task_id].to_dict() if task_id in self._tasks else {},
            },
            payload,
        )

    # ── Helper: emit to frontend ────────────────────────────────────────

    def _emit_frontend(
        self,
        event_type: str,
        payload_data: Dict[str, Any],
        original_payload: Optional[EventPayload] = None,
    ) -> None:
        """Send a structured message to the frontend.

        Uses ws_sender if configured (production), otherwise re-emits
        on EventBus (for testing).
        """
        if self._ws_sender:
            try:
                self._ws_sender(event_type, payload_data)
            except Exception as exc:
                logger.warning(
                    "[TaskKernel] ws_sender failed for %s: %s", event_type, exc
                )
        elif original_payload:
            # Re-emit as event for test subscribers or fallback
            try:
                event = IRISStreamEvent(event_type)
                self._event_bus.emit(
                    event,
                    data=payload_data,
                    turn_id=original_payload.turn_id,
                    conversation_id=original_payload.conversation_id,
                    session_id=original_payload.session_id,
                )
            except ValueError:
                pass  # event_type not in IRISStreamEvent enum — skip

    # ── Queries ─────────────────────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID.  Returns None if not found."""
        with self._lock:
            return self._tasks.get(task_id)

    def get_active_tasks(self, conversation_id: Optional[str] = None) -> List[Task]:
        """Get all active (in_progress) tasks, optionally filtered by conversation."""
        with self._lock:
            tasks = [t for t in self._tasks.values() if t.status == "in_progress"]
            if conversation_id:
                tasks = [t for t in tasks if t.conversation_id == conversation_id]
            return tasks

    def shutdown(self) -> None:
        """Unsubscribe all handlers.  Called on app shutdown."""
        self._event_bus.unsubscribe(IRISStreamEvent.TOOL_CALL, self._on_tool_call)
        self._event_bus.unsubscribe(IRISStreamEvent.TOOL_RESULT, self._on_tool_result)
        self._event_bus.unsubscribe(IRISStreamEvent.TOOL_ERROR, self._on_tool_error)
        self._event_bus.unsubscribe(IRISStreamEvent.TASK_START, self._on_task_start)


# Lazy import for threading
import threading


# ── Singleton ──────────────────────────────────────────────────────────────

_task_kernel_instance: Optional[TaskKernel] = None
_task_kernel_lock = threading.Lock()


def get_task_kernel() -> Optional[TaskKernel]:
    """Return the active TaskKernel, or None if not yet set."""
    return _task_kernel_instance


def set_task_kernel(kernel: Optional[TaskKernel]) -> None:
    """Set or clear the active TaskKernel (called by iris_gateway)."""
    global _task_kernel_instance
    with _task_kernel_lock:
        _task_kernel_instance = kernel


def reset_task_kernel_for_testing() -> None:
    """Reset singleton — for test isolation only."""
    global _task_kernel_instance
    _task_kernel_instance = None
