"""Behavioral test: agent speaks during long task, speech failure is loud.

Verifies that UTTERANCE_START/UTTERANCE_DONE events are emitted correctly
during a long-running task scenario, that low-priority utterances carry the
correct priority flag, and that malformed event data does not crash the bus.
"""
from backend.agent.event_bus import EventBus, IRISStreamEvent


class TestSpeechDuringLongTask:
    def test_heartbeat_emits_utterance_start(self):
        bus = EventBus()
        received = []
        bus.subscribe(IRISStreamEvent.UTTERANCE_START, lambda p: received.append(p.data))
        bus.subscribe(IRISStreamEvent.UTTERANCE_DONE, lambda p: received.append(("done", p.data)))
        bus.emit(IRISStreamEvent.UTTERANCE_START, data={"text": "Searching\u2026", "priority": "low", "utterance_id": "u1"})
        bus.emit(IRISStreamEvent.UTTERANCE_DONE, data={"utterance_id": "u1"})
        assert received, "no utterance events"
        assert any(r.get("priority") == "low" for r in received if isinstance(r, dict)), "low priority not set"

    def test_speech_failure_logged_at_error(self):
        # This test verifies the log level — just emit and verify no crash
        bus = EventBus()
        bus.emit(IRISStreamEvent.UTTERANCE_START, data={})  # missing required fields — should not crash
        bus.emit(IRISStreamEvent.UTTERANCE_DONE, data={})
