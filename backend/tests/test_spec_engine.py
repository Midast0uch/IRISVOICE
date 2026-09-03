"""
Tests for spec_engine.py — SpecOutput, SpecEngine
Source: specs/director_mode_system.md (Req 31) + agent_loop_tasks.md verify block
Gate 1 Step 1.4 acceptance criteria.

Key requirements:
  - simple task → single_doc populated, design_doc None
  - complex task → all three docs populated
  - produce() never raises with broken adapter

Run: python -m pytest backend/tests/test_spec_engine.py -v
"""

from unittest.mock import MagicMock
import pytest


# ── Import sanity ──────────────────────────────────────────────────────────

def test_imports():
    from backend.agent.spec_engine import SpecOutput, SpecEngine
    assert SpecOutput
    assert SpecEngine


# ── SpecOutput dataclass ──────────────────────────────────────────────────

def test_spec_output_defaults():
    from backend.agent.spec_engine import SpecOutput
    out = SpecOutput(title="My Feature", is_complex=False)
    assert out.single_doc is None
    assert out.design_doc is None
    assert out.requirements_doc is None
    assert out.tasks_doc is None


def test_spec_output_simple_fields():
    from backend.agent.spec_engine import SpecOutput
    out = SpecOutput(title="Login", is_complex=False, single_doc="## Feature: Login\n...")
    assert out.single_doc is not None
    assert out.design_doc is None


def test_spec_output_complex_fields():
    from backend.agent.spec_engine import SpecOutput
    out = SpecOutput(
        title="Auth System", is_complex=True,
        design_doc="design", requirements_doc="reqs", tasks_doc="tasks"
    )
    assert out.design_doc == "design"
    assert out.requirements_doc == "reqs"
    assert out.tasks_doc == "tasks"
    assert out.single_doc is None


# ── produce() — simple task ───────────────────────────────────────────────

def test_simple_task_single_doc_populated():
    """Simple task → single_doc populated, design_doc None."""
    from backend.agent.spec_engine import SpecEngine
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text="# Feature: Login\n## What it does\nAllows users to log in.")
    engine = SpecEngine(adapter=adapter, memory_interface=MagicMock())
    result = engine.produce(
        task="add a simple login form",
        is_complex=False,
        context_package=None,
        is_mature=False,
        session_id="s1",
    )
    assert result.single_doc is not None
    assert result.design_doc is None
    assert result.requirements_doc is None
    assert result.tasks_doc is None
    assert result.is_complex is False


# ── produce() — complex task ─────────────────────────────────────────────

def test_complex_task_all_three_docs_populated():
    """Complex task → design_doc, requirements_doc, tasks_doc all populated."""
    from backend.agent.spec_engine import SpecEngine
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text="generated content")
    engine = SpecEngine(adapter=adapter, memory_interface=MagicMock())
    result = engine.produce(
        task="design the full authentication system architecture",
        is_complex=True,
        context_package=None,
        is_mature=False,
        session_id="s1",
    )
    assert result.design_doc is not None
    assert result.requirements_doc is not None
    assert result.tasks_doc is not None
    assert result.single_doc is None
    assert result.is_complex is True


def test_complex_task_calls_adapter_three_times():
    """Three doc producers → three adapter.infer() calls."""
    from backend.agent.spec_engine import SpecEngine
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text="doc content")
    engine = SpecEngine(adapter=adapter, memory_interface=MagicMock())
    engine.produce(
        task="build a complete auth system from scratch",
        is_complex=True,
        context_package=None,
        is_mature=False,
        session_id="s1",
    )
    assert adapter.infer.call_count == 3


# ── produce() — never raises ──────────────────────────────────────────────

def test_produce_never_raises_with_broken_adapter():
    """Broken adapter → SpecOutput with None fields, no exception."""
    from backend.agent.spec_engine import SpecEngine, SpecOutput
    adapter = MagicMock()
    adapter.infer.side_effect = Exception("model down")
    engine = SpecEngine(adapter=adapter, memory_interface=MagicMock())
    result = engine.produce(
        task="build something", is_complex=False,
        context_package=None, is_mature=False, session_id="s1",
    )
    assert isinstance(result, SpecOutput)


def test_produce_never_raises_complex_with_broken_adapter():
    from backend.agent.spec_engine import SpecEngine, SpecOutput
    adapter = MagicMock()
    adapter.infer.side_effect = RuntimeError("gpu oom")
    engine = SpecEngine(adapter=adapter, memory_interface=MagicMock())
    result = engine.produce(
        task="design full system", is_complex=True,
        context_package=None, is_mature=False, session_id="s1",
    )
    assert isinstance(result, SpecOutput)


def test_produce_never_raises_with_broken_context_package():
    """Broken context_package → no raise, still returns SpecOutput."""
    from backend.agent.spec_engine import SpecEngine, SpecOutput

    class BrokenCtx:
        @property
        def topology_primitive(self):
            raise RuntimeError("db down")
        def get_system_zone_content(self):
            raise RuntimeError("gone")

    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text="ok")
    engine = SpecEngine(adapter=adapter, memory_interface=MagicMock())
    result = engine.produce(
        task="add login", is_complex=False,
        context_package=BrokenCtx(), is_mature=True, session_id="s1",
    )
    assert isinstance(result, SpecOutput)


# ── Topology depth calibration ────────────────────────────────────────────

def test_topology_core_uses_lean_depth():
    """core topology → lean depth instruction passed to adapter."""
    from backend.agent.spec_engine import SpecEngine
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text="lean doc")

    ctx = MagicMock()
    ctx.topology_primitive = "core"
    ctx.get_system_zone_content.return_value = ""

    engine = SpecEngine(adapter=adapter, memory_interface=MagicMock())
    engine.produce(
        task="add feature", is_complex=False,
        context_package=ctx, is_mature=True, session_id="s1",
    )
    call_args = adapter.infer.call_args[0][0]
    assert "lean" in call_args.lower() or "expert" in call_args.lower()


def test_topology_acquisition_uses_detailed_depth():
    """acquisition topology → detailed depth instruction."""
    from backend.agent.spec_engine import SpecEngine
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text="detailed doc")

    ctx = MagicMock()
    ctx.topology_primitive = "acquisition"
    ctx.get_system_zone_content.return_value = ""

    engine = SpecEngine(adapter=adapter, memory_interface=MagicMock())
    engine.produce(
        task="add feature", is_complex=False,
        context_package=ctx, is_mature=True, session_id="s1",
    )
    call_args = adapter.infer.call_args[0][0]
    assert "reasoning" in call_args.lower() or "detailed" in call_args.lower()


# ── _extract_title ────────────────────────────────────────────────────────

def test_extract_title_from_task():
    from backend.agent.spec_engine import SpecEngine
    engine = SpecEngine(adapter=MagicMock(), memory_interface=MagicMock())
    title = engine._extract_title("build a user authentication system with oauth")
    # Should be at most 6 words, title-cased
    words = title.split()
    assert len(words) <= 6
    assert title[0].isupper()


def test_extract_title_empty_task():
    from backend.agent.spec_engine import SpecEngine
    engine = SpecEngine(adapter=MagicMock(), memory_interface=MagicMock())
    title = engine._extract_title("")
    assert title == "Feature Spec"


# ── SpecOutput title from task on failure ─────────────────────────────────

def test_failure_result_has_task_as_title():
    """On produce() failure, title is truncated task string."""
    from backend.agent.spec_engine import SpecEngine
    adapter = MagicMock()
    adapter.infer.side_effect = Exception("boom")
    engine = SpecEngine(adapter=adapter, memory_interface=MagicMock())
    result = engine.produce(
        task="x" * 200, is_complex=False,
        context_package=None, is_mature=False, session_id="s1",
    )
    assert len(result.title) <= 60
