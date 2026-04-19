"""
Tests for der_loop.py — ReviewVerdict, QueueItem, DirectorQueue, Reviewer
Source: specs/agent_loop_tasks..md Task 1.3 (inline verify) + Task 7.2 (unit tests)
Gate 1 Step 1.1 acceptance criteria.

Run: python -m pytest backend/tests/test_der_loop.py -v
"""

from unittest.mock import MagicMock
import pytest


# ── Import sanity ──────────────────────────────────────────────────────────

def test_imports():
    from backend.agent.der_loop import ReviewVerdict, QueueItem, DirectorQueue, Reviewer
    assert ReviewVerdict.PASS
    assert ReviewVerdict.REFINE
    assert ReviewVerdict.VETO


# ── DirectorQueue — basics ────────────────────────────────────────────────

def test_queue_basic_order():
    from backend.agent.der_loop import QueueItem, DirectorQueue
    q = DirectorQueue(objective="build a game")
    q.items = [
        QueueItem(step_id="s1", step_number=1, description="scaffold"),
        QueueItem(step_id="s2", step_number=2, description="implement",
                  depends_on=["s1"]),
    ]
    assert q.next_ready().step_id == "s1"
    q.mark_complete("s1")
    assert q.next_ready().step_id == "s2"
    q.mark_complete("s2")
    assert q.is_complete()


def test_queue_dependency_blocks_until_done():
    from backend.agent.der_loop import QueueItem, DirectorQueue
    q = DirectorQueue(objective="test")
    q.items = [
        QueueItem(step_id="a", step_number=1, description="first"),
        QueueItem(step_id="b", step_number=2, description="second",
                  depends_on=["a"]),
    ]
    # b is not ready until a is completed
    assert q.next_ready().step_id == "a"
    # mark a complete — b should now be ready
    q.mark_complete("a")
    assert q.next_ready().step_id == "b"


def test_queue_veto_and_complete():
    from backend.agent.der_loop import QueueItem, DirectorQueue
    q = DirectorQueue(objective="test")
    q.items = [
        QueueItem(step_id="s1", step_number=1, description="a"),
        QueueItem(step_id="s2", step_number=2, description="b",
                  depends_on=["s1"]),
    ]
    assert q.next_ready().step_id == "s1"
    q.mark_vetoed("s1")
    # s2 depends on s1 which is vetoed not completed — no ready item
    assert q.next_ready() is None
    # queue not complete because s2 never completed
    assert not q.is_complete()


def test_queue_is_complete_ignores_vetoed():
    from backend.agent.der_loop import QueueItem, DirectorQueue
    q = DirectorQueue(objective="test")
    q.items = [
        QueueItem(step_id="s1", step_number=1, description="a"),
        QueueItem(step_id="s2", step_number=2, description="b"),
    ]
    q.mark_vetoed("s1")
    q.mark_complete("s2")
    # s1 is vetoed (excluded from active), s2 is complete → queue done
    assert q.is_complete()


def test_queue_cycle_limit():
    from backend.agent.der_loop import DirectorQueue
    q = DirectorQueue(objective="test", max_cycles=3)
    assert not q.hit_cycle_limit()
    q.cycle_count = 3
    assert q.hit_cycle_limit()


def test_queue_add_item():
    from backend.agent.der_loop import QueueItem, DirectorQueue
    q = DirectorQueue(objective="test")
    item = QueueItem(step_id="new", step_number=1, description="added")
    q.add_item(item)
    assert len(q.items) == 1
    assert q.next_ready().step_id == "new"


# ── Reviewer — fallback guarantees ────────────────────────────────────────

def test_reviewer_pass_on_immature_graph():
    """Immature graph → skip review entirely → PASS."""
    from backend.agent.der_loop import Reviewer, QueueItem, ReviewVerdict
    reviewer = Reviewer(adapter=MagicMock(), memory_interface=MagicMock())
    verdict, output = reviewer.review(
        item=QueueItem(step_id="s1", step_number=1,
                       description="test", objective_anchor="goal"),
        completed_steps=[],
        context_package=MagicMock(),
        is_mature=False,
    )
    assert verdict == ReviewVerdict.PASS
    assert output is None


def test_reviewer_pass_on_broken_adapter():
    """Adapter exception → always PASS, never raise."""
    from backend.agent.der_loop import Reviewer, QueueItem, ReviewVerdict
    adapter = MagicMock()
    adapter.infer.side_effect = Exception("model down")
    reviewer = Reviewer(adapter=adapter, memory_interface=MagicMock())

    pkg = MagicMock()
    pkg.gradient_warnings = ""
    pkg.active_contracts = ""

    verdict, output = reviewer.review(
        item=QueueItem(step_id="s1", step_number=1,
                       description="test", objective_anchor="test"),
        completed_steps=[],
        context_package=pkg,
        is_mature=True,
    )
    assert verdict == ReviewVerdict.PASS
    assert output is None


def test_reviewer_pass_on_exception_with_warnings():
    """Adapter throws even when warnings present → PASS."""
    from backend.agent.der_loop import Reviewer, QueueItem, ReviewVerdict
    adapter = MagicMock()
    adapter.infer.side_effect = Exception("down")
    reviewer = Reviewer(adapter=adapter, memory_interface=MagicMock())

    pkg = MagicMock()
    pkg.gradient_warnings = "warning: avoid X"
    pkg.active_contracts = "contract: always do Y"

    verdict, output = reviewer.review(
        item=QueueItem(step_id="s1", step_number=1,
                       description="test", objective_anchor="goal"),
        completed_steps=[],
        context_package=pkg,
        is_mature=True,
    )
    assert verdict == ReviewVerdict.PASS


def test_reviewer_pass_when_context_has_no_gradient_attr():
    """context_package without gradient_warnings attr → PASS."""
    from backend.agent.der_loop import Reviewer, QueueItem, ReviewVerdict
    reviewer = Reviewer(adapter=MagicMock(), memory_interface=MagicMock())
    # plain object — no gradient_warnings attribute
    ctx = object()
    verdict, output = reviewer.review(
        item=QueueItem(step_id="s1", step_number=1,
                       description="test", objective_anchor="goal"),
        completed_steps=[],
        context_package=ctx,
        is_mature=True,
    )
    assert verdict == ReviewVerdict.PASS


# ── Reviewer — parse_verdict ──────────────────────────────────────────────

def test_reviewer_parse_pass():
    from backend.agent.der_loop import Reviewer, ReviewVerdict
    r = Reviewer(adapter=MagicMock(), memory_interface=MagicMock())
    verdict, output = r._parse_verdict('{"verdict":"pass","reason":"","refined":""}')
    assert verdict == ReviewVerdict.PASS
    assert output is None


def test_reviewer_parse_veto():
    from backend.agent.der_loop import Reviewer, ReviewVerdict
    r = Reviewer(adapter=MagicMock(), memory_interface=MagicMock())
    verdict, reason = r._parse_verdict(
        '{"verdict":"veto","reason":"conflicts with contract","refined":""}'
    )
    assert verdict == ReviewVerdict.VETO
    assert reason == "conflicts with contract"


def test_reviewer_parse_refine():
    from backend.agent.der_loop import Reviewer, ReviewVerdict
    r = Reviewer(adapter=MagicMock(), memory_interface=MagicMock())
    verdict, refined = r._parse_verdict(
        '{"verdict":"refine","reason":"add error handling",'
        '"refined":"Write file with try/except around open()"}'
    )
    assert verdict == ReviewVerdict.REFINE
    assert "try/except" in refined


def test_reviewer_parse_garbage_falls_back_to_pass():
    from backend.agent.der_loop import Reviewer, ReviewVerdict
    r = Reviewer(adapter=MagicMock(), memory_interface=MagicMock())
    verdict, output = r._parse_verdict("I cannot determine the verdict here")
    assert verdict == ReviewVerdict.PASS
    assert output is None


def test_reviewer_parse_bad_json_falls_back_to_pass():
    from backend.agent.der_loop import Reviewer, ReviewVerdict
    r = Reviewer(adapter=MagicMock(), memory_interface=MagicMock())
    verdict, output = r._parse_verdict("{broken json }")
    assert verdict == ReviewVerdict.PASS


# ── ReviewVerdict enum ────────────────────────────────────────────────────

def test_verdict_values():
    from backend.agent.der_loop import ReviewVerdict
    assert ReviewVerdict.PASS.value == "pass"
    assert ReviewVerdict.REFINE.value == "refine"
    assert ReviewVerdict.VETO.value == "veto"


# ── QueueItem defaults ────────────────────────────────────────────────────

def test_queue_item_defaults():
    from backend.agent.der_loop import QueueItem
    item = QueueItem(step_id="x", step_number=1, description="do it")
    assert item.tool is None
    assert item.params == {}
    assert item.depends_on == []
    assert item.critical is True
    assert item.objective_anchor == ""
    assert item.veto_count == 0
    assert item.refined_description is None
