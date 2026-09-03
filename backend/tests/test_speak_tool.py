"""Contract tests for the speak tool (Issue C.2).

The speak tool lets the agent proactively speak via TTS.  Contracts:
  * emits UTTERANCE_START + UTTERANCE_DONE on the EventBus
  * fire-and-forget — returns immediately, never blocks
  * text longer than 500 chars is truncated
  * priority/interrupt flags are passed through in the event payload
  * bounded rate limit (max 3 pending) — 4th rapid speak is rate_limited
  * empty/non-string text returns an error status (never raises)
"""
import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from backend.agent.event_bus import EventBus, IRISStreamEvent
from backend.agent.tools.speak_tool import SpeakTool, MAX_TEXT_CHARS, MAX_PENDING


def _capture(bus, event):
    captured = []
    bus.subscribe(event, lambda p: captured.append(p))
    return captured


def test_emits_utterance_event():
    bus = EventBus()
    start = _capture(bus, IRISStreamEvent.UTTERANCE_START)
    done = _capture(bus, IRISStreamEvent.UTTERANCE_DONE)
    tool = SpeakTool(event_bus=bus)
    result = tool.speak("Hello world")
    assert result["status"] == "ok"
    assert len(start) == 1 and len(done) == 1
    assert start[0].data["text"] == "Hello world"


def test_fire_and_forget_returns_immediately():
    import time

    bus = EventBus()
    tool = SpeakTool(event_bus=bus)
    t0 = time.time()
    result = tool.speak("Hi")
    assert time.time() - t0 < 1.0
    assert result["status"] == "ok"


def test_truncates_long_text():
    bus = EventBus()
    start = _capture(bus, IRISStreamEvent.UTTERANCE_START)
    tool = SpeakTool(event_bus=bus)
    tool.speak("x" * 2000)
    assert len(start[0].data["text"]) <= MAX_TEXT_CHARS


def test_interrupt_flag_passed():
    bus = EventBus()
    start = _capture(bus, IRISStreamEvent.UTTERANCE_START)
    tool = SpeakTool(event_bus=bus)
    tool.speak("Urgent", priority="high", interrupt=True)
    assert start[0].data["interrupt"] is True
    assert start[0].data["priority"] == "high"


def test_rate_limit_at_max_pending():
    bus = EventBus()
    tool = SpeakTool(event_bus=bus)
    results = [tool.speak(f"msg {i}") for i in range(MAX_PENDING + 2)]
    assert results[0]["status"] == "ok"
    assert results[MAX_PENDING]["status"] == "rate_limited"


def test_empty_text_errors():
    bus = EventBus()
    tool = SpeakTool(event_bus=bus)
    assert tool.speak("")["status"] == "error"
    assert tool.speak(None)["status"] == "error"


def test_correlation_fields_in_payload():
    """REQ-12 live-testing support: speak() carries conversation_id +
    turn_id in the emitted event so TTS playback can be correlated to a
    conversation thread during manual testing."""
    bus = EventBus()
    start = _capture(bus, IRISStreamEvent.UTTERANCE_START)
    tool = SpeakTool(event_bus=bus)
    result = tool.speak(
        "Now opening the file", conversation_id="conv_42", turn_id="turn_7"
    )
    assert result["status"] == "ok"
    assert start[0].data["conversation_id"] == "conv_42"
    assert start[0].data["turn_id"] == "turn_7"


def test_resolves_active_kernel_without_creating_one():
    """When conv/turn omitted, speak() resolves the EXISTING kernel
    instance for correlation — it must NOT create a new heavy kernel
    (memory wiring) as a side effect of a log call."""
    import backend.agent.agent_kernel as ak

    # Seed one fake existing instance (no real __init__).
    class _FakeKernel:
        conversation_id = "conv_existing"
        _current_turn_id = "turn_existing"

    ak._agent_kernel_instances["conv_existing"] = _FakeKernel()
    bus = EventBus()
    start = _capture(bus, IRISStreamEvent.UTTERANCE_START)
    tool = SpeakTool(event_bus=bus)
    result = tool.speak("Resolved thread")
    assert result["status"] == "ok"
    assert start[0].data["conversation_id"] == "conv_existing"
    assert start[0].data["turn_id"] == "turn_existing"
    # No extra kernel created beyond the one we seeded.
    assert len(ak._agent_kernel_instances) == 1
    del ak._agent_kernel_instances["conv_existing"]
