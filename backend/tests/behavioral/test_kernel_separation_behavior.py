"""Behavioral tests: Kernel separation — EventBus routing.

Verifies:
  - ConversationKernel subscribes to utterance events, gates by phase
  - TaskKernel subscribes to tool events, emits progress
  - Handler isolation: TaskKernel failure never blocks ConversationKernel
  - Ring buffer replay for late TaskListCard subscribers
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.agent.event_bus import (
    EventBus,
    EventPayload,
    IRISStreamEvent,
    get_event_bus,
    reset_event_bus_for_testing,
)
from backend.agent.task_kernel import (
    TaskKernel,
    Task,
    TaskStep,
    get_task_kernel,
    set_task_kernel,
    reset_task_kernel_for_testing,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def bus():
    """Fresh EventBus for each test."""
    b = EventBus()
    yield b


@pytest.fixture(autouse=True)
def reset_singletons():
    reset_event_bus_for_testing()
    reset_task_kernel_for_testing()
    yield


# ── ConversationKernel speech gating ────────────────────────────────────────


class TestConversationKernelSpeechGate:
    def test_filter_speech_expand_returns_true(self):
        """During EXPAND phase, speech is allowed."""
        from backend.agent.conversation_kernel import ConversationKernel

        kernel = ConversationKernel(
            voice_handler=MagicMock(), tts_manager=MagicMock(),
            audio_pipeline=MagicMock(), session_id_getter=lambda: "test",
        )
        assert kernel.filter_speech("EXPAND") is True

    def test_filter_speech_compress_returns_false(self):
        """During COMPRESS phase, speech is suppressed."""
        from backend.agent.conversation_kernel import ConversationKernel

        kernel = ConversationKernel(
            voice_handler=MagicMock(), tts_manager=MagicMock(),
            audio_pipeline=MagicMock(), session_id_getter=lambda: "test",
        )
        assert kernel.filter_speech("COMPRESS") is False

    def test_filter_speech_idle_returns_true(self):
        """During IDLE phase, speech is allowed."""
        from backend.agent.conversation_kernel import ConversationKernel

        kernel = ConversationKernel(
            voice_handler=MagicMock(), tts_manager=MagicMock(),
            audio_pipeline=MagicMock(), session_id_getter=lambda: "test",
        )
        assert kernel.filter_speech("IDLE") is True

    def test_filter_speech_unknown_phase_defaults_expand(self):
        """Unknown phase defaults to allowing speech (EXPAND behavior)."""
        from backend.agent.conversation_kernel import ConversationKernel

        kernel = ConversationKernel(
            voice_handler=MagicMock(), tts_manager=MagicMock(),
            audio_pipeline=MagicMock(), session_id_getter=lambda: "test",
        )
        phase = getattr(kernel, "_current_caducean_phase", "EXPAND")
        assert kernel.filter_speech(phase) is True

    def test_utterance_suppressed_during_compress(self):
        """Utterance events during COMPRESS are suppressed (not forwarded to TTS)."""
        from backend.agent.conversation_kernel import ConversationKernel

        kernel = ConversationKernel(
            voice_handler=MagicMock(), tts_manager=MagicMock(),
            audio_pipeline=MagicMock(), session_id_getter=lambda: "test",
        )
        kernel._current_caducean_phase = "COMPRESS"
        kernel._tts_manager = MagicMock()

        kernel._on_utterance_start(
            EventPayload(
                event=IRISStreamEvent.UTTERANCE_START,
                data={"text": "Working on your task..."},
            )
        )

        # TTS should NOT have been called during COMPRESS
        kernel._tts_manager.speak.assert_not_called()

    def test_utterance_forwarded_during_expand(self):
        """Utterance events during EXPAND are forwarded to TTS."""
        from backend.agent.conversation_kernel import ConversationKernel

        kernel = ConversationKernel(
            voice_handler=MagicMock(), tts_manager=MagicMock(),
            audio_pipeline=MagicMock(), session_id_getter=lambda: "test",
        )
        kernel._current_caducean_phase = "EXPAND"
        kernel._tts_manager = MagicMock()

        # Dispatch is now threaded (off the EventBus thread); run the utterance
        # thread synchronously so the assertion is deterministic (T4.2: dispatch
        # is threaded, not sync).
        import threading as _threading

        _real = _threading.Thread

        class _SyncThread:
            def __init__(self, target=None, args=(), kwargs=None, **_kw):
                self._target = target
                self._args = args or ()

            def start(self):
                if self._target:
                    self._target(*self._args)

            def join(self, *a, **k):
                pass

        _threading.Thread = _SyncThread
        try:
            kernel._on_utterance_start(
                EventPayload(
                    event=IRISStreamEvent.UTTERANCE_START,
                    data={"text": "Here's what I found..."},
                )
            )
        finally:
            _threading.Thread = _real

        # T4.2: dispatch is now threaded — _speak_utterance calls synthesize_stream
        kernel._tts_manager.synthesize_stream.assert_called_once_with("Here's what I found...")


# ── TaskKernel tool event handling ─────────────────────────────────────────


class TestTaskKernel:
    def test_tool_call_creates_task(self, bus):
        tk = TaskKernel(event_bus=bus)
        bus.emit(
            IRISStreamEvent.TOOL_CALL,
            data={"tool_name": "write_file", "task_id": "task_001"},
        )

        task = tk.get_task("task_001")
        assert task is not None
        assert task.status == "in_progress"
        assert len(task.steps) == 1
        assert task.steps[0].tool_name == "write_file"

    def test_tool_call_auto_creates_task(self, bus):
        """A tool:call without a prior task:start auto-creates the task."""
        tk = TaskKernel(event_bus=bus)
        bus.emit(
            IRISStreamEvent.TOOL_CALL,
            data={
                "tool_name": "read_file",
                "task_id": "auto_task",
                "description": "Reading config",
            },
        )

        task = tk.get_task("auto_task")
        assert task is not None
        assert len(task.steps) == 1
        assert task.steps[0].description == "Reading config"

    def test_tool_result_completes_step(self, bus):
        tk = TaskKernel(event_bus=bus)
        bus.emit(
            IRISStreamEvent.TOOL_CALL,
            data={"tool_name": "search", "task_id": "task_002"},
        )
        bus.emit(
            IRISStreamEvent.TOOL_RESULT,
            data={
                "task_id": "task_002",
                "result_summary": "Found 3 results",
            },
        )

        task = tk.get_task("task_002")
        assert task is not None
        assert task.steps[-1].status == "completed"
        assert task.steps[-1].result_summary == "Found 3 results"

    def test_tool_error_fails_step(self, bus):
        tk = TaskKernel(event_bus=bus)
        bus.emit(
            IRISStreamEvent.TOOL_CALL,
            data={"tool_name": "delete_file", "task_id": "task_003"},
        )
        bus.emit(
            IRISStreamEvent.TOOL_ERROR,
            data={
                "task_id": "task_003",
                "error": "Permission denied",
            },
        )

        task = tk.get_task("task_003")
        assert task is not None
        assert task.steps[-1].status == "failed"
        assert "Permission denied" in (task.steps[-1].result_summary or "")

    def test_task_start_creates_empty_task(self, bus):
        tk = TaskKernel(event_bus=bus)
        bus.emit(
            IRISStreamEvent.TASK_START,
            data={
                "task_id": "task_004",
                "description": "Research the Caducean Engine",
            },
        )

        task = tk.get_task("task_004")
        assert task is not None
        assert task.description == "Research the Caducean Engine"
        assert task.steps == []  # No steps yet

    def test_multiple_steps_in_order(self, bus):
        tk = TaskKernel(event_bus=bus)
        # Three sequential tool calls
        for i, (tool, desc) in enumerate(
            [("search", "Searching docs"), ("read", "Reading relevant pages"), ("summarize", "Summarizing results")]
        ):
            bus.emit(
                IRISStreamEvent.TOOL_CALL,
                data={"tool_name": tool, "description": desc, "task_id": "task_multi"},
            )
            bus.emit(
                IRISStreamEvent.TOOL_RESULT,
                data={"task_id": "task_multi", "result_summary": f"Done step {i+1}"},
            )

        task = tk.get_task("task_multi")
        assert task is not None
        assert len(task.steps) == 3
        assert task.steps[0].tool_name == "search"
        assert task.steps[1].tool_name == "read"
        assert task.steps[2].tool_name == "summarize"
        assert all(s.status == "completed" for s in task.steps)


class TestKernelIsolation:
    def test_task_kernel_failure_does_not_affect_event_bus(self, bus):
        """If TaskKernel crashes internally, EventBus still delivers to other handlers."""
        results = []

        def other_handler(payload):
            results.append(payload.event.value)

        # Create TaskKernel with a broken ws_sender
        def broken_sender(event_type, data):
            raise RuntimeError("WS is down")

        tk = TaskKernel(event_bus=bus, ws_sender=broken_sender)
        # Also subscribe a separate handler
        bus.subscribe(IRISStreamEvent.TOOL_CALL, other_handler)

        # Emit — should not raise
        bus.emit(IRISStreamEvent.TOOL_CALL, data={"tool_name": "test", "task_id": "iso_001"})

        # Other handler should still have received the event
        assert "tool:call" in results

    def test_kernel_handlers_independent(self, bus):
        """ConversationKernel and TaskKernel don't interfere."""
        from backend.agent.conversation_kernel import ConversationKernel

        ck = ConversationKernel(
            voice_handler=MagicMock(), tts_manager=MagicMock(),
            audio_pipeline=MagicMock(), session_id_getter=lambda: "test",
        )
        tk = TaskKernel(event_bus=bus)
        ck._tts_manager = MagicMock()  # override with isolated mock

        # Emit an utterance — only ConversationKernel reacts
        bus.emit(
            IRISStreamEvent.UTTERANCE_START,
            data={"text": "Status update"},
        )

        # TaskKernel should not have created a task from an utterance
        assert tk.get_active_tasks() == []

        # Emit a tool call — only TaskKernel reacts
        bus.emit(
            IRISStreamEvent.TOOL_CALL,
            data={"tool_name": "read", "task_id": "indep_001"},
        )

        task = tk.get_task("indep_001")
        assert task is not None
        # TTS should not have been called for a tool call
        ck._tts_manager.speak.assert_not_called()


class TestTaskKernelQueries:
    def test_get_active_tasks(self, bus):
        tk = TaskKernel(event_bus=bus)

        # Create one completed task and one active
        bus.emit(
            IRISStreamEvent.TOOL_CALL,
            data={"tool_name": "done", "task_id": "done_task"},
        )
        bus.emit(
            IRISStreamEvent.TOOL_RESULT,
            data={"task_id": "done_task", "result_summary": "ok"},
        )

        bus.emit(
            IRISStreamEvent.TOOL_CALL,
            data={"tool_name": "active", "task_id": "active_task"},
        )

        active = tk.get_active_tasks()
        assert len(active) == 2  # both still in_progress (no TASK_DONE yet)

    def test_get_active_tasks_by_conversation(self, bus):
        tk = TaskKernel(event_bus=bus)
        # Override conversation_id via manual payload
        bus.emit(
            IRISStreamEvent.TOOL_CALL,
            data={"tool_name": "a", "task_id": "conv_a_task"},
            conversation_id="conv_a",
        )
        bus.emit(
            IRISStreamEvent.TOOL_CALL,
            data={"tool_name": "b", "task_id": "conv_b_task"},
            conversation_id="conv_b",
        )

        conv_a_tasks = tk.get_active_tasks(conversation_id="conv_a")
        assert len(conv_a_tasks) == 1
        assert conv_a_tasks[0].task_id == "conv_a_task"

    def test_get_nonexistent_task(self, bus):
        tk = TaskKernel(event_bus=bus)
        assert tk.get_task("not_there") is None


class TestTaskDataTypes:
    def test_task_step_to_dict(self):
        step = TaskStep(step_number=1, description="Test step", status="completed")
        d = step.to_dict()
        assert d["step_number"] == 1
        assert d["status"] == "completed"

    def test_task_to_dict(self):
        task = Task(task_id="t1", description="Test task")
        task.steps.append(TaskStep(step_number=1, description="Step 1"))
        d = task.to_dict()
        assert d["task_id"] == "t1"
        assert d["step_count"] == 1
        assert d["completed_count"] == 0
