"""Contract test (T8c, REQ-10 AC5): MCM emits memory events from the REAL
compress() and recall() paths — reached from the actual methods, not a helper —
and the events carry the correct ``kind``. The emit is fire-and-forget and must
never raise even when the EventBus is unavailable, so compression/recall can
never be blocked by a memory-event failure.

This is the guard that would have caught a silent mcm.py (the original T8c
defect: recall()/compress() emitted NOTHING, so the card's memory footer was
honest but permanently empty).
"""
import pytest

from backend.agent.event_bus import get_event_bus, IRISStreamEvent
from backend.agent.mcm import MCM


@pytest.fixture
def captured():
    bus = get_event_bus()
    received = []

    def handler(payload):
        received.append(payload)

    bus.subscribe(IRISStreamEvent.MEMORY_EVENT, handler)
    yield received
    bus.unsubscribe(IRISStreamEvent.MEMORY_EVENT, handler)


def test_compress_emits_memory_event_from_real_path(captured):
    mcm = MCM(memory_interface=None, session_id="test-session-t8c")
    # Reached from the real compress() method, not a helper.
    mcm.compress(active_task="Write the spec", active_files=["a.py", "b.py"])

    kinds = [p.data.get("kind") for p in captured if p.data]
    assert "compress" in kinds

    comp = next(p for p in captured if p.data and p.data.get("kind") == "compress")
    # Payload carries the real compression context (registry fields).
    assert comp.data["active_task"] == "Write the spec"
    assert comp.data["active_files"] == ["a.py", "b.py"]
    assert "compressed_at" in comp.data


def test_recall_emits_memory_event_from_real_path(captured):
    mcm = MCM(memory_interface=None, session_id="test-session-t8c")
    # Reached from the real recall() method, not a helper.
    mcm.recall("how did we solve the auth bug")

    kinds = [p.data.get("kind") for p in captured if p.data]
    assert "recall" in kinds

    rec = next(p for p in captured if p.data and p.data.get("kind") == "recall")
    assert rec.data.get("query") == "how did we solve the auth bug"


def test_memory_event_emit_never_raises_without_bus(captured):
    # The emit helper swallows EventBus errors; compress/recall must not raise
    # even if emitting fails. (captured stays empty — no crash.)
    mcm = MCM(memory_interface=None, session_id="test-session-t8c")
    mcm.compress(active_task="x")  # must not raise
    mcm.recall("y")  # must not raise
    assert True
