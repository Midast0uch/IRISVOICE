"""Contract tests for the speak broadcaster (Issue C.2 external delivery).

Verifies the core forwarding logic: channel registry, subscription to
UTTERANCE_START, empty-text handling, multi-channel delivery, and that a
failing channel never breaks the others (fire-and-forget, exception-safe).
"""
import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from backend.agent.event_bus import EventBus, IRISStreamEvent
from backend.agent.tools.speak_broadcaster import SpeakBroadcaster


def _bus_and_broadcaster():
    bus = EventBus()
    bc = SpeakBroadcaster(event_bus=bus)
    return bus, bc


def test_register_and_forward_external():
    bus, bc = _bus_and_broadcaster()
    received = []
    bc.register_channel("mock", lambda t: received.append(t))
    bc.forward_external("hello")
    assert received == ["hello"]


def test_subscription_forwards_utterance():
    bus, bc = _bus_and_broadcaster()
    received = []
    bc.register_channel("mock", lambda t: received.append(t))
    bc.subscribe()
    bus.emit(IRISStreamEvent.UTTERANCE_START, data={"text": "spoken"})
    assert received == ["spoken"]


def test_empty_text_not_forwarded():
    bus, bc = _bus_and_broadcaster()
    received = []
    bc.register_channel("mock", lambda t: received.append(t))
    bc.forward_external("")
    bc.forward_external(None)
    assert received == []


def test_multiple_channels_all_receive():
    bus, bc = _bus_and_broadcaster()
    a, b = [], []
    bc.register_channel("a", lambda t: a.append(t))
    bc.register_channel("b", lambda t: b.append(t))
    bc.forward_external("x")
    assert a == ["x"] and b == ["x"]


def test_channel_failure_isolated():
    bus, bc = _bus_and_broadcaster()
    good, bad = [], []

    def _bad(t):
        raise RuntimeError("boom")

    bc.register_channel("good", lambda t: good.append(t))
    bc.register_channel("bad", _bad)
    bc.forward_external("y")  # must not raise
    assert good == ["y"]
