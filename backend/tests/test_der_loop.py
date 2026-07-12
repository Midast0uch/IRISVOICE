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
    assert item.parallel_safe is False
    assert item.objective_anchor == ""
    assert item.veto_count == 0
    assert item.refined_description is None


# ── Phase 4: all_ready_items (concurrent batch) ────────────────────────────


def test_all_ready_items_returns_all_unblocked():
    """all_ready_items returns every dependency-satisfied, non-done item."""
    from backend.agent.der_loop import QueueItem, DirectorQueue
    q = DirectorQueue(objective="parallel")
    q.items = [
        QueueItem(step_id="s1", step_number=1, description="a", parallel_safe=True),
        QueueItem(step_id="s2", step_number=2, description="b", parallel_safe=True),
        QueueItem(step_id="s3", step_number=3, description="c",
                  depends_on=["s1"], parallel_safe=True),
    ]
    ready = q.all_ready_items()
    ids = {i.step_id for i in ready}
    assert ids == {"s1", "s2"}  # s3 blocked on s1
    q.mark_complete("s1")
    ready2 = q.all_ready_items()
    assert {i.step_id for i in ready2} == {"s2", "s3"}


def test_all_ready_items_empty_when_blocked():
    """No item is ready if the only item has an unmet dependency."""
    from backend.agent.der_loop import QueueItem, DirectorQueue
    q = DirectorQueue(objective="x")
    q.items = [
        QueueItem(step_id="s2", step_number=2, description="b", depends_on=["s1"]),
    ]
    assert q.all_ready_items() == []


def test_all_ready_items_skips_vetoed():
    from backend.agent.der_loop import QueueItem, DirectorQueue
    q = DirectorQueue(objective="x")
    q.items = [
        QueueItem(step_id="s1", step_number=1, description="a"),
        QueueItem(step_id="s2", step_number=2, description="b"),
    ]
    q.mark_vetoed("s2")
    assert {i.step_id for i in q.all_ready_items()} == {"s1"}


# ── Phase 3 (Gap 3): resolve_dependent_params ──────────────────────────────


def test_resolve_explicit_depends_on():
    """Completed step output is injected into a step that depends_on it."""
    from backend.agent.der_loop import QueueItem, DirectorQueue
    q = DirectorQueue(objective="research")
    s1 = QueueItem(step_id="s1", step_number=1, description="search")
    s2 = QueueItem(step_id="s2", step_number=2, description="read top result",
                   depends_on=["s1"], params={"path": "PLACEHOLDER"})
    q.items = [s1, s2]
    q.mark_complete("s1")

    injected = q.resolve_dependent_params(s1, "TITLE: Best Article\nURL: http://x")
    assert injected == ["s2"]
    assert s2.params["_dependency_results"]["s1"] == "TITLE: Best Article\nURL: http://x"
    # original param untouched
    assert s2.params["path"] == "PLACEHOLDER"


def test_resolve_implicit_sequential():
    """Linear plan: step N+1 receives step N's output without explicit depends_on."""
    from backend.agent.der_loop import QueueItem, DirectorQueue
    q = DirectorQueue(objective="summarize")
    s1 = QueueItem(step_id="s1", step_number=1, description="search")
    s2 = QueueItem(step_id="s2", step_number=2, description="summarize")
    s3 = QueueItem(step_id="s3", step_number=3, description="format")
    q.items = [s1, s2, s3]
    q.mark_complete("s1")

    injected = q.resolve_dependent_params(s1, "search results text")
    # only the immediate next step (s2) gets it, not s3
    assert injected == ["s2"]
    assert s2.params["_dependency_results"]["s1"] == "search results text"
    assert "_dependency_results" not in s3.params


def test_resolve_placeholder_substitution():
    """{{step_id}} / {{step_number}} placeholders in params get replaced."""
    from backend.agent.der_loop import QueueItem, DirectorQueue
    q = DirectorQueue(objective="research")
    s1 = QueueItem(step_id="src1", step_number=1, description="search")
    s2 = QueueItem(step_id="s2", step_number=2, description="read",
                   depends_on=["src1"],
                   params={"query": "read {{src1}} and step {{1}}"})
    q.items = [s1, s2]
    q.mark_complete("src1")

    q.resolve_dependent_params(s1, "FOUND_URL")
    assert s2.params["query"] == "read FOUND_URL and step FOUND_URL"


def test_resolve_skips_completed_and_vetoed():
    """Injection never targets already-completed or vetoed items."""
    from backend.agent.der_loop import QueueItem, DirectorQueue
    q = DirectorQueue(objective="x")
    s1 = QueueItem(step_id="s1", step_number=1, description="a")
    s2 = QueueItem(step_id="s2", step_number=2, description="b")
    s3 = QueueItem(step_id="s3", step_number=3, description="c")
    q.items = [s1, s2, s3]
    q.mark_complete("s1")
    q.mark_vetoed("s3")

    injected = q.resolve_dependent_params(s1, "out")
    # s2 is sequential (step 2) → injected; s3 is vetoed → skipped
    assert injected == ["s2"]
    assert "s3" not in injected


def test_resolve_noop_on_empty_result():
    """Empty/None result is a no-op (no mutation)."""
    from backend.agent.der_loop import QueueItem, DirectorQueue
    q = DirectorQueue(objective="x")
    s1 = QueueItem(step_id="s1", step_number=1, description="a")
    s2 = QueueItem(step_id="s2", step_number=2, description="b")
    q.items = [s1, s2]
    q.mark_complete("s1")

    assert q.resolve_dependent_params(s1, "") == []
    assert q.resolve_dependent_params(s1, None) == []
    assert "_dependency_results" not in s2.params


def test_resolve_truncates_long_result():
    """Very long results are truncated to bound param size."""
    from backend.agent.der_loop import QueueItem, DirectorQueue
    q = DirectorQueue(objective="x")
    s1 = QueueItem(step_id="s1", step_number=1, description="a")
    s2 = QueueItem(step_id="s2", step_number=2, description="b")
    q.items = [s1, s2]
    q.mark_complete("s1")

    big = "X" * 10000
    q.resolve_dependent_params(s1, big, max_result_len=50)
    assert s2.params["_dependency_results"]["s1"] == "X" * 50


# ── Phase 3 (Gap 4): Explorer prompt includes actual step outputs ──────────


def test_plan_next_step_includes_step_outputs():
    """_der_plan_next_step surfaces step_outputs in the Explorer prompt."""
    from unittest.mock import MagicMock
    from backend.agent.agent_kernel import AgentKernel
    from backend.agent.der_loop import QueueItem

    captured = {}

    class FakeKernel:
        adapter = MagicMock()

        def infer(self, prompt, **kwargs):
            captured["prompt"] = prompt
            return MagicMock(raw_text='{"done": true}')

    fake = FakeKernel()
    AgentKernel._der_plan_next_step(
        fake,
        "find the capital of France",
        [QueueItem(step_id="s1", step_number=1, description="search web")],
        mode=MagicMock(value="agentic"),
        turn_id="t1",
        step_outputs=["Paris is the capital of France per DuckDuckGo"],
    )
    assert "Paris is the capital of France" in captured["prompt"]
    assert "ACTUAL STEP OUTPUTS" in captured["prompt"]


def test_plan_next_step_includes_completed_result():
    """Per-step result is included in the done summary when present."""
    from unittest.mock import MagicMock
    from backend.agent.agent_kernel import AgentKernel
    from backend.agent.der_loop import QueueItem

    captured = {}

    class FakeKernel:
        adapter = MagicMock()

        def infer(self, prompt, **kwargs):
            captured["prompt"] = prompt
            return MagicMock(raw_text='{"done": true}')

    fake = FakeKernel()
    item = QueueItem(step_id="s1", step_number=1, description="search web")
    item.result = "RAW_SEARCH_OUTPUT_MARKER"
    AgentKernel._der_plan_next_step(
        fake,
        "objective",
        [item],
        mode=MagicMock(value="agentic"),
        turn_id="t2",
    )
    assert "RAW_SEARCH_OUTPUT_MARKER" in captured["prompt"]
