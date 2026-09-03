"""Contract test CT-I5: A successful speak() emits UTTERANCE_START with priority and interrupt.

Pins the 01e6625b fix where _speak_inner did not receive priority/interrupt, raising
NameError before UTTERANCE_START was ever emitted — a 100% failure that presented as
intermittence because tool_bridge swallowed the exception with a WARNING.
"""

from __future__ import annotations

from backend.agent.event_bus import EventBus, IRISStreamEvent
from backend.agent.tools.speak_tool import SpeakTool


class TestSpeakEmits:
    def test_speak_emits_utterance_start_carrying_priority_and_interrupt(self):
        bus = EventBus()
        tool = SpeakTool(event_bus=bus)

        received: list = []

        def on_utterance(payload):
            received.append(payload.data)

        bus.subscribe(IRISStreamEvent.UTTERANCE_START, on_utterance)

        result = tool.speak(
            text="Hello, I am working on your request.",
            priority="low",
            interrupt=False,
            conversation_id="test-conv",
            turn_id="test-turn",
        )

        assert result["status"] == "ok", f"speak failed: {result}"
        assert len(received) >= 1, "UTTERANCE_START was never emitted"

        data = received[0]
        assert data["text"] == "Hello, I am working on your request."
        assert data["priority"] == "low"
        assert data["interrupt"] is False

    def test_speak_high_priority_with_interrupt(self):
        bus = EventBus()
        tool = SpeakTool(event_bus=bus)

        received: list = []

        def on_utterance(payload):
            received.append(payload.data)

        bus.subscribe(IRISStreamEvent.UTTERANCE_START, on_utterance)

        result = tool.speak(
            text="Urgent update!",
            priority="high",
            interrupt=True,
            conversation_id="test-conv",
            turn_id="test-turn",
        )

        assert result["status"] == "ok"
        assert len(received) >= 1

        data = received[0]
        assert data["priority"] == "high"
        assert data["interrupt"] is True

    def test_speak_also_emits_utterance_done(self):
        bus = EventBus()
        tool = SpeakTool(event_bus=bus)

        starts: list = []
        dones: list = []

        bus.subscribe(IRISStreamEvent.UTTERANCE_START, lambda p: starts.append(p.data))
        bus.subscribe(IRISStreamEvent.UTTERANCE_DONE, lambda p: dones.append(p.data))

        tool.speak(
            text="Test utterance.",
            priority="normal",
            interrupt=False,
            conversation_id="test-conv",
            turn_id="test-turn",
        )

        assert len(starts) >= 1
        assert len(dones) >= 1
        assert starts[0]["utterance_id"] == dones[0]["utterance_id"]
