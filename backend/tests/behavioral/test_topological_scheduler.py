"""
Tests for Phase 1.3 — topological scheduler + failed_ids handling.

Run: python -m pytest backend/tests/test_topological_scheduler.py -v
"""

from unittest.mock import patch


def _make_queue():
    from backend.agent.der_loop import QueueItem, DirectorQueue

    return QueueItem, DirectorQueue


def test_topological_order_respected():
    QueueItem, DirectorQueue = _make_queue()
    q = DirectorQueue(objective="build")
    q.items = [
        QueueItem(step_id="a", step_number=1, description="first"),
        QueueItem(step_id="b", step_number=2, description="second", depends_on=["a"]),
        QueueItem(step_id="c", step_number=3, description="third", depends_on=["b"]),
    ]
    assert q.next_ready().step_id == "a"
    q.mark_complete("a")
    assert q.next_ready().step_id == "b"
    q.mark_complete("b")
    assert q.next_ready().step_id == "c"


def test_failed_ids_skipped_in_next_ready():
    QueueItem, DirectorQueue = _make_queue()
    q = DirectorQueue(objective="build")
    q.items = [
        QueueItem(step_id="a", step_number=1, description="first"),
        QueueItem(step_id="b", step_number=2, description="second", depends_on=["a"]),
    ]
    q.mark_failed("a")
    # b depends on a (failed) → not ready; nothing ready
    assert q.next_ready() is None


def test_abort_descendants_marks_dependents_failed():
    QueueItem, DirectorQueue = _make_queue()
    q = DirectorQueue(objective="build")
    q.items = [
        QueueItem(step_id="a", step_number=1, description="root"),
        QueueItem(step_id="b", step_number=2, description="mid", depends_on=["a"]),
        QueueItem(step_id="c", step_number=3, description="leaf", depends_on=["b"]),
        QueueItem(step_id="d", step_number=4, description="independent"),
    ]
    # Caller marks the original step failed first (mirrors _der_handle_step_failure)
    q.mark_failed("a")
    aborted = q.abort_descendants("a")
    assert set(aborted) == {"b", "c"}
    assert "a" in q.failed_ids
    assert "b" in q.failed_ids
    assert "c" in q.failed_ids
    assert "d" not in q.failed_ids
    # d is still ready (independent)
    assert q.next_ready().step_id == "d"


def test_is_complete_treats_failed_as_terminal():
    QueueItem, DirectorQueue = _make_queue()
    q = DirectorQueue(objective="build")
    q.items = [
        QueueItem(step_id="a", step_number=1, description="first"),
        QueueItem(step_id="b", step_number=2, description="second", depends_on=["a"]),
    ]
    q.mark_complete("a")
    q.mark_failed("b")
    # b is failed → terminal → queue complete
    assert q.is_complete() is True


def test_is_complete_false_when_active_pending():
    QueueItem, DirectorQueue = _make_queue()
    q = DirectorQueue(objective="build")
    q.items = [
        QueueItem(step_id="a", step_number=1, description="first"),
        QueueItem(step_id="b", step_number=2, description="second", depends_on=["a"]),
    ]
    q.mark_complete("a")
    # b not done, not failed → not complete
    assert q.is_complete() is False
