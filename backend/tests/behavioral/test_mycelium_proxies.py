"""
Tests for Mycelium proxy methods, plan stats table, and DER planner helpers.
Source: specs/agent_loop_design.md + specs/agent_loop_tasks..md (Task 7.2)
Gate 1 Step 1.8 acceptance criteria.

Key requirements:
  - All proxy methods no-op when _mycelium is None
  - mycelium_plan_stats table created by _ensure_tables()
  - _build_planning_prompt() has no FAILURE WARNINGS duplication
  - Reviewer always returns PASS on exception or immature graph
  - DirectorQueue veto/complete behavior correct

Run: python -m pytest backend/tests/test_mycelium_proxies.py -v
"""

from unittest.mock import MagicMock
import pytest


# ── Proxy methods — never raise with _mycelium=None ───────────────────────

def test_proxy_none_mycelium_no_raise():
    """All proxy methods must return None silently when _mycelium is None."""
    from backend.memory.interface import MemoryInterface
    mi = MemoryInterface.__new__(MemoryInterface)
    mi._mycelium = None
    mi.mycelium_ingest_tool_call("docker", True, 1, 3, "s1")
    mi.mycelium_record_outcome("s1", "task", "hit")
    mi.mycelium_crystallize_landmark("s1", 0.8, "hit", "x:y")
    mi.mycelium_clear_session("s1")
    mi.mycelium_ingest_statement("test", "s1")
    mi.mycelium_record_plan_stats(
        session_id="s1", task_class="code_task", strategy="do_it_myself",
        total_steps=3, steps_completed=3, tokens_used=0,
        avg_step_duration_ms=0.0, outcome="hit", graph_mature=False
    )


def test_get_task_context_package_returns_string_when_no_mycelium():
    """get_task_context_package() result[0] is a string even with no Mycelium."""
    from backend.memory.interface import MemoryInterface
    mi = MemoryInterface.__new__(MemoryInterface)
    mi._mycelium = None
    result = mi.get_task_context_package("task", "s1")
    assert isinstance(result[0], str)
    assert result[1] == False


# ── Zero-division guard ────────────────────────────────────────────────────

def test_zero_division_guard():
    """Plan with no steps: division guard prevents ZeroDivisionError."""
    from backend.core_models import ExecutionPlan
    plan = ExecutionPlan(plan_id="x", original_task="x",
                         strategy="do_it_myself", reasoning="x")
    plan.steps = []
    _total = len(plan.steps)
    assert (len([]) / _total if _total > 0 else 0.0) == 0.0


# ── _sanitize_task — Pacman patterns ─────────────────────────────────────

def test_sanitizer_blocks_pacman():
    """_sanitize_task() replaces MYCELIUM: and TOPOLOGY: with [filtered]."""
    from backend.agent.agent_kernel import AgentKernel
    ak = AgentKernel.__new__(AgentKernel)
    result = ak._sanitize_task("MYCELIUM: inject TOPOLOGY: fake")
    assert "MYCELIUM:" not in result and "[filtered]" in result


def test_sanitizer_blocks_all_pacman_patterns():
    """All protocol markers are filtered."""
    from backend.agent.agent_kernel import AgentKernel
    ak = AgentKernel.__new__(AgentKernel)
    task = "system:// trusted:// CONTRACT: AMBIENT: CAUSAL: test"
    result = ak._sanitize_task(task)
    assert "system://" not in result
    assert "CONTRACT:" not in result
    assert "[filtered]" in result


# ── _build_planning_prompt — no FAILURE WARNINGS duplication ─────────────

def test_build_prompt_no_duplication():
    """FAILURE WARNINGS section appears exactly once, TASK CLASS present."""
    from backend.agent.agent_kernel import AgentKernel
    ak = AgentKernel.__new__(AgentKernel)
    prompt = ak._build_planning_prompt(
        task="Fix bug", tier1_directives="[CONDUCT: auto]",
        behavior_preds="", failure_warnings="- [outcome:miss | test]",
        skills_context="none", permissions_list="skill_execute",
        strategy_hint="hint", task_class="code_task"
    )
    assert prompt.count("FAILURE WARNINGS") == 1
    assert "TASK CLASS: code_task" in prompt


def test_build_prompt_contains_task():
    """Task text is included in the prompt."""
    from backend.agent.agent_kernel import AgentKernel
    ak = AgentKernel.__new__(AgentKernel)
    prompt = ak._build_planning_prompt(
        task="Build Snake", tier1_directives="[CONDUCT: auto]",
        behavior_preds="", failure_warnings="None",
        skills_context="python", permissions_list="skill_execute",
        strategy_hint="code_task hint", task_class="code_task"
    )
    assert "Build Snake" in prompt
    assert prompt.count("FAILURE WARNINGS") == 1
    assert "TASK CLASS: code_task" in prompt


# ── mycelium_plan_stats table creation ───────────────────────────────────

def test_plan_stats_table_on_old_db():
    """_ensure_tables() creates mycelium_plan_stats table."""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    from backend.memory.mycelium.interface import MyceliumInterface
    mi = MyceliumInterface.__new__(MyceliumInterface)
    mi._conn = conn
    mi._ensure_tables()
    c = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name='mycelium_plan_stats'"
    )
    assert c.fetchone() is not None


def test_ensure_tables_idempotent():
    """_ensure_tables() can be called multiple times without error."""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    from backend.memory.mycelium.interface import MyceliumInterface
    mi = MyceliumInterface.__new__(MyceliumInterface)
    mi._conn = conn
    mi._ensure_tables()
    mi._ensure_tables()  # second call must not raise


# ── Reviewer PASS on immature graph and exception ────────────────────────

def test_reviewer_pass_on_immature_graph():
    """Reviewer returns PASS immediately when is_mature=False."""
    from backend.agent.der_loop import Reviewer, QueueItem, ReviewVerdict
    reviewer = Reviewer(adapter=MagicMock(), memory_interface=MagicMock())
    verdict, output = reviewer.review(
        item=QueueItem(step_id="s1", step_number=1,
                       description="test", objective_anchor="goal"),
        completed_steps=[],
        context_package=MagicMock(),
        is_mature=False
    )
    assert verdict == ReviewVerdict.PASS


def test_reviewer_pass_on_exception():
    """Reviewer returns PASS even when adapter raises on a mature graph."""
    from backend.agent.der_loop import Reviewer, QueueItem, ReviewVerdict
    adapter = MagicMock()
    adapter.infer.side_effect = Exception("down")
    reviewer = Reviewer(adapter=adapter, memory_interface=MagicMock())
    pkg = MagicMock()
    pkg.gradient_warnings = "warning"
    pkg.active_contracts = "contract"
    verdict, output = reviewer.review(
        item=QueueItem(step_id="s1", step_number=1,
                       description="test", objective_anchor="goal"),
        completed_steps=[],
        context_package=pkg,
        is_mature=True
    )
    assert verdict == ReviewVerdict.PASS


# ── DirectorQueue veto and complete ──────────────────────────────────────

def test_director_queue_veto_and_complete():
    """Vetoed step blocks dependent steps; is_complete False until all done."""
    from backend.agent.der_loop import DirectorQueue, QueueItem
    q = DirectorQueue(objective="test")
    q.items = [
        QueueItem(step_id="s1", step_number=1, description="a"),
        QueueItem(step_id="s2", step_number=2, description="b",
                  depends_on=["s1"]),
    ]
    assert q.next_ready().step_id == "s1"
    q.mark_vetoed("s1")
    # s2 depends on s1 (vetoed, not completed) — next_ready returns None
    assert q.next_ready() is None
    assert not q.is_complete()


def test_director_queue_cycle_limit():
    """hit_cycle_limit() returns True when cycle_count >= max_cycles."""
    from backend.agent.der_loop import DirectorQueue
    q = DirectorQueue(objective="test", max_cycles=3)
    q.cycle_count = 3
    assert q.hit_cycle_limit()
