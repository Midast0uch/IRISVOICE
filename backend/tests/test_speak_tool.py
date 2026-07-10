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
