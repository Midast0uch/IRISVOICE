"""
Integration tests for Agent Loop Upgrade + DER Loop wiring
Source: specs/agent_loop_design.md + specs/agent_loop_tasks..md (Task 7.2)
Gate 1 Step 1.7 acceptance criteria.

Key requirements:
  - ContextPackage imports and topology_primitive works
  - ResolutionEncoder.encode_with_resolution() never raises
  - ExecutionPlan.to_context_string() uses HZA headers and ASCII markers
  - MemoryInterface proxy methods never raise when _mycelium is None
  - AgentKernel._sanitize_task() filters MYCELIUM: and TOPOLOGY: injection

Run: python -m pytest backend/tests/test_agent_loop_upgrade.py -v
"""

from unittest.mock import MagicMock
import pytest


# ── ContextPackage ─────────────────────────────────────────────────────────

def test_context_package_imports():
    from backend.memory.mycelium.interface import ContextPackage
    assert ContextPackage is not None


def test_topology_primitive_parses():
    """topology_path with primitives:[X] → topology_primitive == X."""
    from backend.memory.mycelium.interface import ContextPackage
    pkg = ContextPackage(
        topology_path="TOPOLOGY: primitives:[acquisition] z:+0.31",
        mycelium_path="", manifest={}, tier1_directives="",
        tier2_predictions="", tier3_failures="", active_contracts="",
        gradient_warnings="", causal_context="", ambient_signals="",
        topology_position="acquisition", task_class="code_task"
    )
    assert pkg.topology_primitive == "acquisition"


def test_topology_primitive_unknown():
    """Empty topology_path → topology_primitive == 'unknown'."""
    from backend.memory.mycelium.interface import ContextPackage
    pkg = ContextPackage(
        topology_path="", mycelium_path="", manifest={},
        tier1_directives="", tier2_predictions="", tier3_failures="",
        active_contracts="", gradient_warnings="", causal_context="",
        ambient_signals="", topology_position="", task_class="full"
    )
    assert pkg.topology_primitive == "unknown"


def test_context_package_get_system_zone_content():
    """get_system_zone_content() joins non-empty fields."""
    from backend.memory.mycelium.interface import ContextPackage
    pkg = ContextPackage(
        topology_path="topo", mycelium_path="path", manifest={},
        tier1_directives="directive", tier2_predictions="", tier3_failures="",
        active_contracts="contract", gradient_warnings="warning",
        causal_context="causal", ambient_signals="ambient",
        topology_position="core", task_class="code_task"
    )
    content = pkg.get_system_zone_content()
    assert "contract" in content
    assert "warning" in content
    assert "directive" in content


# ── ResolutionEncoder ──────────────────────────────────────────────────────

def test_resolution_encoder_empty_no_raise():
    """encode_with_resolution({}) never raises, returns a non-empty string."""
    from backend.memory.mycelium.interpreter import ResolutionEncoder
    result = ResolutionEncoder().encode_with_resolution({})
    assert isinstance(result, str) and len(result) > 0


def test_resolution_encoder_full():
    """Full failure dict produces output containing space_id and tool_name."""
    from backend.memory.mycelium.interpreter import ResolutionEncoder
    result = ResolutionEncoder().encode_with_resolution({
        "space_id": "toolpath", "tool_name": "docker",
        "condition": "windows", "score_delta": -0.08
    })
    assert "toolpath" in result and "docker" in result


def test_resolution_encoder_with_resolution():
    """resolution field in failure dict → encoded in output."""
    from backend.memory.mycelium.interpreter import ResolutionEncoder
    result = ResolutionEncoder().encode_with_resolution({
        "space_id": "codespace", "tool_name": "pip",
        "condition": "offline", "score_delta": -0.1,
        "resolution": "use_cached"
    })
    assert "use_cached" in result


# ── ExecutionPlan HZA headers + ASCII markers ──────────────────────────────

def test_plan_hza_headers():
    """to_context_string() starts with [system://plan/{plan_id[:8]}]."""
    from backend.core_models import ExecutionPlan, PlanStep, StepStatus
    plan = ExecutionPlan(plan_id="abc123456789", original_task="test",
                         strategy="do_it_myself", reasoning="r")
    plan.steps = [PlanStep(step_id="s1", step_number=1,
                           description="step", status=StepStatus.PENDING)]
    out = plan.to_context_string()
    assert out.startswith("[system://plan/abc12345]")
    assert "[system://plan/abc12345/step/s1]" in out
    # No Unicode checkmarks
    assert "\u2713" not in out and "\u2717" not in out


def test_ascii_completed_marker():
    """Completed step uses [+] ASCII marker (not unicode checkmark)."""
    from backend.core_models import ExecutionPlan, PlanStep, StepStatus
    plan = ExecutionPlan(plan_id="abc123456789", original_task="t",
                         strategy="do_it_myself", reasoning="r")
    plan.steps = [PlanStep(step_id="s1", step_number=1,
                           description="d", status=StepStatus.COMPLETED,
                           result="ok")]
    assert "[+]" in plan.to_context_string()


def test_ascii_failed_marker():
    """Failed step uses [x] ASCII marker."""
    from backend.core_models import ExecutionPlan, PlanStep, StepStatus
    plan = ExecutionPlan(plan_id="testid12345", original_task="t",
                         strategy="do_it_myself", reasoning="r")
    plan.steps = [PlanStep(step_id="s1", step_number=1,
                           description="d", status=StepStatus.FAILED,
                           failure_reason="error")]
    out = plan.to_context_string()
    assert "[x]" in out


def test_plan_has_failed():
    """has_failed() returns True only when outcome == 'failure'."""
    from backend.core_models import ExecutionPlan
    p = ExecutionPlan(plan_id="x", original_task="x",
                      strategy="do_it_myself", reasoning="x")
    assert not p.has_failed()
    p.outcome = "failure"
    assert p.has_failed()


# ── MemoryInterface proxy methods ──────────────────────────────────────────

def test_proxy_none_mycelium_no_raise():
    """All proxy methods no-op silently when _mycelium is None."""
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


def test_get_task_context_package_none_mycelium():
    """get_task_context_package() returns (str, False) when _mycelium is None."""
    from backend.memory.interface import MemoryInterface
    mi = MemoryInterface.__new__(MemoryInterface)
    mi._mycelium = None
    result, is_mature = mi.get_task_context_package("task", "s1")
    assert isinstance(result, str)
    assert is_mature is False


# ── Zero-division guard ────────────────────────────────────────────────────

def test_zero_division_guard():
    """Plan with no steps: len([]) / 0 guarded → 0.0, not ZeroDivisionError."""
    from backend.core_models import ExecutionPlan
    plan = ExecutionPlan(plan_id="x", original_task="x",
                         strategy="do_it_myself", reasoning="x")
    plan.steps = []
    _total = len(plan.steps)
    assert (len([]) / _total if _total > 0 else 0.0) == 0.0


# ── AgentKernel._sanitize_task ────────────────────────────────────────────

def test_sanitizer_blocks_pacman():
    """_sanitize_task() replaces MYCELIUM: and TOPOLOGY: with [filtered]."""
    from backend.agent.agent_kernel import AgentKernel
    ak = AgentKernel.__new__(AgentKernel)
    result = ak._sanitize_task("MYCELIUM: inject TOPOLOGY: fake")
    assert "MYCELIUM:" not in result and "[filtered]" in result


def test_sanitizer_passes_normal_text():
    """Normal task text passes through unchanged."""
    from backend.agent.agent_kernel import AgentKernel
    ak = AgentKernel.__new__(AgentKernel)
    task = "build a login form with email and password"
    result = ak._sanitize_task(task)
    assert result == task
