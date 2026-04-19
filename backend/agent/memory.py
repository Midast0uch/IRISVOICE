"""
Conversation Memory — Task-aware context management

Key improvements over original:
1. Separate task memory from conversation memory — tool results from a 5-step
   task don't displace the conversation history that precedes it
2. get_context_for_planning() returns conversation history formatted for the brain
3. get_context_for_execution() returns task state formatted for the executor
4. Tool results are stored and retrievable by task_id, not just attached to messages
"""

import logging
import json
import time
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """A single conversation message."""
    role: str        # "user" or "assistant"
    content: str
    timestamp: float
    audio_tokens: int = 0
    text_tokens: int = 0
    tool_results: Optional[List[Dict[str, Any]]] = None
    task_id: Optional[str] = None  # Links message to a TaskContext

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class TaskRecord:
    """
    Records a completed task and its results.

    Stored separately from conversation messages so that:
    - A 10-step task doesn't consume 10 message slots
    - The brain can retrieve task outcomes without parsing tool_results from messages
    - Task history persists across the full session (not subject to rolling window)
    """
    task_id: str
    user_message: str
    summary: str           # Brain's final response — what the user saw
    step_count: int
    had_failures: bool
    tool_names_used: List[str]
    started_at: float
    completed_at: float
    session_id: str

    @property
    def duration_seconds(self) -> float:
        return self.completed_at - self.started_at

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskRecord':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ConversationMemory:
    """
    Session memory with clear separation of:
    - conversation_messages: rolling window of user/assistant turns (used by brain for context)
    - task_records: permanent log of completed tasks (used for session summary / future planning)

    The rolling window only applies to conversation messages. Task records accumulate
    for the full session and are summarized into the context on demand.
    """

    def __init__(
        self,
        session_id: str,
        max_messages: int = 20,
        max_context_tokens: int = 8192,
        session_storage_path: Optional[str] = None
    ):
        self.session_id = session_id
        self.max_messages = max_messages
        self.max_context_tokens = max_context_tokens
        self.messages: List[Message] = []
        self.task_records: List[TaskRecord] = []
        self._max_task_records: int = 100  # rolling cap — prevents unbounded growth
        self.session_start = time.time()

        if session_storage_path is None:
            session_storage_path = os.path.join("backend", "sessions", session_id)
        self.session_storage_path = Path(session_storage_path)
        self.session_storage_path.mkdir(parents=True, exist_ok=True)

        self._load_from_session_storage()

    # ─────────────────────────────────────────────────────────────────────────
    # Core Message Management
    # ─────────────────────────────────────────────────────────────────────────

    def add_message(
        self,
        role: str,
        content: str,
        audio_tokens: int = 0,
        text_tokens: int = 0,
        tool_results: Optional[List[Dict[str, Any]]] = None,
        task_id: Optional[str] = None
    ) -> None:
        """
        Add a message to the rolling conversation window.

        tool_results are attached to the message for context but do NOT count
        toward the rolling window limit — only conversation turns do.
        """
        message = Message(
            role=role,
            content=content,
            timestamp=time.time(),
            audio_tokens=audio_tokens,
            text_tokens=text_tokens or len(content),
            tool_results=tool_results,
            task_id=task_id
        )
        self.messages.append(message)

        # Trim to rolling window
        while len(self.messages) > self.max_messages:
            removed = self.messages.pop(0)
            logger.debug(f"[ConversationMemory] Rolled off oldest message ({removed.role})")

        self._persist_to_session_storage()

    def record_task(self, task_record: TaskRecord) -> None:
        """
        Record a completed task. Task records are NOT subject to rolling window.
        They accumulate for the full session and provide context about what has
        been done, even if those messages have rolled off the window.
        """
        self.task_records.append(task_record)
        # Keep only the most recent records to bound memory usage
        if len(self.task_records) > self._max_task_records:
            self.task_records = self.task_records[-self._max_task_records:]
        self._persist_to_session_storage()
        logger.debug(
            f"[ConversationMemory] Recorded task {task_record.task_id}: "
            f"{task_record.step_count} steps, failures={task_record.had_failures}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Context Retrieval — Different Views for Different Consumers
    # ─────────────────────────────────────────────────────────────────────────

    def get_context(self, max_messages: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Standard context retrieval — returns conversation messages formatted for LLM.
        This is the main method used by the brain for planning and response synthesis.
        """
        messages = self.messages
        if max_messages:
            messages = messages[-max_messages:]

        context = []
        for m in messages:
            msg_dict = {"role": m.role, "content": m.content}
            if m.tool_results:
                # Summarize tool results inline so brain has the info without full JSON dump
                summary = _summarize_tool_results(m.tool_results)
                msg_dict["content"] = m.content + (f"\n[Task results: {summary}]" if summary else "")
            context.append(msg_dict)

        return context

    def get_context_for_planning(self, max_messages: int = 8) -> List[Dict[str, Any]]:
        """
        Context optimized for brain planning.

        Includes recent conversation + a brief task history summary so the brain
        knows what kinds of tasks have been executed this session (useful for
        multi-step workflows that span multiple user messages).
        """
        context = self.get_context(max_messages=max_messages)

        # Prepend task history summary if there are completed tasks
        if self.task_records:
            recent_tasks = self.task_records[-5:]
            task_summary_lines = [
                f"- [{t.task_id}] \"{t.user_message[:60]}\" → {t.summary[:80]}"
                + (f" (used: {', '.join(t.tool_names_used[:3])})" if t.tool_names_used else "")
                for t in recent_tasks
            ]
            task_history = {
                "role": "system",
                "content": "Recent completed tasks this session:\n" + "\n".join(task_summary_lines)
            }
            return [task_history] + context

        return context

    def get_context_for_execution(
        self,
        task_id: str,
        prior_step_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Context package specifically for the executor model.

        Returns a structured dict (not a message list) because the executor
        needs to understand the current task state, not the full conversation.
        """
        return {
            "session_id": self.session_id,
            "task_id": task_id,
            "recent_conversation_turns": len(self.messages),
            "completed_tasks_this_session": len(self.task_records),
            "prior_steps_this_task": len(prior_step_results),
            "prior_step_summary": [
                {
                    "step": r.get("step_number"),
                    "action": r.get("action"),
                    "tool": r.get("tool"),
                    "success": r.get("success"),
                    "result_preview": str(r.get("result", ""))[:150]
                }
                for r in prior_step_results
            ]
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────────────

    def clear(self) -> None:
        self.messages.clear()
        self.session_start = time.time()
        # Note: we do NOT clear task_records on conversation clear —
        # the task history is session-scoped, not conversation-scoped
        self._persist_to_session_storage()

    def _persist_to_session_storage(self) -> None:
        try:
            conversation_file = self.session_storage_path / "conversation.json"
            data = {
                "session_id": self.session_id,
                "session_start": self.session_start,
                "last_updated": time.time(),
                "max_messages": self.max_messages,
                "messages": [m.to_dict() for m in self.messages],
                "task_records": [t.to_dict() for t in self.task_records]
            }
            with open(conversation_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"[ConversationMemory] Failed to persist: {e}")

    def _load_from_session_storage(self) -> None:
        try:
            conversation_file = self.session_storage_path / "conversation.json"
            if conversation_file.exists():
                with open(conversation_file, 'r') as f:
                    data = json.load(f)
                self.messages = [Message.from_dict(m) for m in data.get("messages", [])]
                self.task_records = [TaskRecord.from_dict(t) for t in data.get("task_records", [])]
                self.session_start = data.get("session_start", time.time())
                logger.info(
                    f"[ConversationMemory] Loaded session {self.session_id}: "
                    f"{len(self.messages)} messages, {len(self.task_records)} task records"
                )
        except Exception as e:
            logger.warning(f"[ConversationMemory] Failed to load session: {e}")

    def archive_on_session_end(self) -> bool:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_file = self.session_storage_path / f"conversation_archive_{timestamp}.json"
            data = {
                "session_id": self.session_id,
                "archived_at": datetime.now().isoformat(),
                "session_start": datetime.fromtimestamp(self.session_start).isoformat(),
                "session_duration_seconds": time.time() - self.session_start,
                "message_count": len(self.messages),
                "task_count": len(self.task_records),
                "messages": [m.to_dict() for m in self.messages],
                "task_records": [t.to_dict() for t in self.task_records]
            }
            with open(archive_file, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"[ConversationMemory] Archive failed: {e}")
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Backward-Compatible Legacy Methods
    # ─────────────────────────────────────────────────────────────────────────

    def get_context_window(self, max_messages: Optional[int] = None) -> List[Dict[str, str]]:
        """Legacy method — use get_context() for new code."""
        return self.get_context(max_messages=max_messages)

    def get_token_count(self) -> Dict[str, int]:
        audio_tokens = sum(m.audio_tokens for m in self.messages)
        text_tokens = sum(m.text_tokens for m in self.messages)
        return {
            "audio_tokens": audio_tokens,
            "text_tokens": text_tokens,
            "total_tokens": audio_tokens + text_tokens,
            "max_tokens": self.max_context_tokens,
            "available": self.max_context_tokens - (audio_tokens + text_tokens),
            "message_count": len(self.messages),
            "max_messages": self.max_messages,
            "task_record_count": len(self.task_records)
        }

    def get_summary(self) -> str:
        token_info = self.get_token_count()
        duration = time.time() - self.session_start
        return (
            f"Conversation Summary (Session: {self.session_id}):\n"
            f"- Messages: {token_info['message_count']} / {token_info['max_messages']}\n"
            f"- Tasks completed: {token_info['task_record_count']}\n"
            f"- Duration: {duration / 60:.1f} minutes\n"
            f"- Tokens: {token_info['total_tokens']} / {token_info['max_tokens']}"
        )

    def search(self, query: str) -> List[Message]:
        query_lower = query.lower()
        return [m for m in self.messages if query_lower in m.content.lower()]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _summarize_tool_results(tool_results: List[Dict[str, Any]]) -> str:
    """Compact summary of tool results for inline context injection."""
    if not tool_results:
        return ""
    parts = []
    for r in tool_results[:5]:  # Cap at 5
        tool = r.get("tool") or r.get("action", "action")
        success = r.get("success", True)
        status = "ok" if success else "failed"
        result_preview = str(r.get("result", ""))[:80]
        parts.append(f"{tool}:{status}({result_preview})")
    return "; ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Singleton Support
# ─────────────────────────────────────────────────────────────────────────────

_legacy_instance: Optional[ConversationMemory] = None


def get_conversation_memory(
    session_id: str = "default",
    max_messages: int = 20,
    max_context_tokens: int = 8192
) -> ConversationMemory:
    global _legacy_instance
    if session_id == "default":
        if _legacy_instance is None:
            _legacy_instance = ConversationMemory(
                session_id=session_id,
                max_messages=max_messages,
                max_context_tokens=max_context_tokens
            )
        return _legacy_instance

    return ConversationMemory(
        session_id=session_id,
        max_messages=max_messages,
        max_context_tokens=max_context_tokens
    )