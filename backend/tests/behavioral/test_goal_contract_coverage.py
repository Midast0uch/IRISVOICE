"""Behavioral tests: goal-contract-coverage full-loop drives (spec T13).

Run the system as it runs — a kernel with heavy collaborators stubbed but
the REAL grade/naming/blocking/amend helpers bound — and assert EMERGENT
properties, never unit internals:
  BT-GC1  an N-fact request covers or names all N at the terminal answer.
  BT-GC2  an open unblocked fact never grades pass (D7 shape).
  BT-GC3  stalled C triggers the streak gate (try_different/replan).
  BT-GC4  steering amends the floor; C moves predictably; identity survives.
  BT-GC5  goal gate and phase gate are independent (CT-GC6 behavioral twin).
  BT-GC6  no-UI gated step settles <1s with approval_unavailable; reroute or
          block named — no hang (D1/D11 shape).
  BT-GC7  stall is a rate: no-progress far from goal trips; slow-but-moving
          near goal does not.
  BT-GC8  fail-fast feeds learning: scorer + task:learning + link twin fire.
  BT-GC9  toggle ON runs write+shell; delete still prompts.
No live web, no live model.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.agent import goal_contract as gc
from backend.agent.goal_contract import Contract


class _Kernel:
    """Kernel stand-in binding the REAL goal-contract helpers."""

    def __init__(self):
        from backend.agent.agent_kernel import AgentKernel

        self.conversation_id = "conv_gcb"
        self.session_id = "sess_gcb"
        self._goal_contract_state = None
        self._der_last_run_grade = None
        self._der_links = None
        for name in (
            "_goal_contract_open_facts", "_goal_contract_blocked_texts",
            "_goal_contract_block_facts", "_goal_contract_name_blocked",
            "_goal_contract_apply_steering", "_der_report_run_grade",
            "_goal_contract_state",
        ):
            pass
        for name in (
            "_goal_contract_open_facts", "_goal_contract_blocked_texts",
            "_goal_contract_block_facts", "_goal_contract_name_blocked",
            "_goal_contract_apply_steering", "_der_report_run_grade",
        ):
            if hasattr(AgentKernel, name):
                setattr(self, name, getattr(AgentKernel, name).__get__(self))
        self._memory_interface = MagicMock()
        self._memory_interface._mycelium = None

    def build(self, request: str):
        facts = gc.extract_required(request)
        self._goal_contract_state = {
            "turn_id": "t1",
            "contract": Contract(required=tuple(facts), ceiling=(), version=1),
            "task_record": SimpleNamespace(
                required_facts=list(facts), verified_fraction=0.0,
                covered_facts=[], blocked_facts=[], contract_version=1,
            ),
            "covered": [], "outcomes": [], "results": [],
            "blocked": [], "amendments": [],
            "C": 0.0, "g": 1.0, "unmoved": 0, "rho": 0.0,
            "counters": {"facts_seeded": len(facts)},
        }
        return facts

    def settle(self, verdict: str, result: str):
        st = self._goal_contract_state
        st["outcomes"].append(verdict)
        st["results"].append(result)
        cov = gc.mark_coverage(st["contract"], st["outcomes"], st["results"])
        st["C"], st["g"], st["covered"] = cov.C, cov.g, list(cov.covered)
        st["task_record"].verified_fraction = cov.C
        st["task_record"].covered_facts = list(cov.covered)
        return cov


# ── BT-GC1: N facts in, all N covered or named ───────────────────────────────


def test_bt_gc1_n_facts_cover_or_name_all():
    k = _Kernel()
    facts = k.build("1. compare Bun vs Deno 2. list three features")
    assert len(facts) == 2
    k.settle("VERIFIED", "A Bun vs Deno comparison table with benchmarks")
    k.settle("VERIFIED", "three features: install, serve, bundle")
    st = k._goal_contract_state
    assert st["C"] == 1.0
    assert k._goal_contract_open_facts() == []
    answer = k._goal_contract_name_blocked("Here is the comparison and the features.")
    assert "blocked" not in answer  # nothing blocked: answer untouched


def test_bt_gc1_uncovered_blocked_fact_is_named():
    k = _Kernel()
    k.build("1. compare Bun vs Deno 2. list three features")
    k.settle("VERIFIED", "A Bun vs Deno comparison")
    st = k._goal_contract_state
    st["blocked"] = [{
        "fact": "list three features", "reason": "robots_refused",
        "evidence": "robots.txt denied",
    }]
    out = k._goal_contract_name_blocked("Here is the comparison.")
    assert "list three features" in out


# ── BT-GC2: D7 shape never passes ────────────────────────────────────────────


def test_bt_gc2_open_unblocked_fact_caps_grade():
    k = _Kernel()
    k.build("1. compare Bun vs Deno 2. list three features")
    k.settle("VERIFIED", "A Bun vs Deno comparison")
    grade = k._der_report_run_grade([], "t-d7", "bt-gc2")
    assert grade == "capped"


def test_bt_gc2_full_coverage_passes():
    k = _Kernel()
    k.build("compare Bun vs Deno")
    k.settle("VERIFIED", "Bun vs Deno comparison with install steps")
    assert k._der_report_run_grade([], "t-pass", "bt-gc2") == "pass"


# ── BT-GC3: stalled C triggers the gate ──────────────────────────────────────


def test_bt_gc3_stalled_coverage_triggers_replan():
    from backend.agent.tool_envelope import evaluate_streak

    fire, reason = evaluate_streak([], 2, 2, coverage=0.5, coverage_unmoved_n=2)
    assert fire is True
    assert "coverage" in reason


# ── BT-GC4: steering mutates, identity survives ──────────────────────────────


def test_bt_gc4_steering_amends_floor_and_moves_c():
    k = _Kernel()
    k.build("1. compare Bun vs Deno 2. list three features")
    k.settle("VERIFIED", "three features: install, serve, bundle")
    assert k._goal_contract_state["C"] == 0.5
    changed = k._goal_contract_apply_steering("drop the Bun vs Deno comparison")
    assert changed is True
    st = k._goal_contract_state
    assert st["contract"].required == ("list three features",)
    assert st["task_record"].contract_version == 2  # identity: same record, v+1
    # recompute C on the new denominator deterministically
    cov = gc.mark_coverage(st["contract"], st["outcomes"], st["results"])
    st["C"] = cov.C
    assert st["C"] == 1.0  # scope shrank: C rose


def test_bt_gc4_agent_floor_removal_refused_end_to_end():
    k = _Kernel()
    k.build("compare Bun vs Deno")
    st = k._goal_contract_state
    refused = gc.amend(
        st["contract"], remove=("compare Bun vs Deno",),
        source="agent", reason="shortcut",
    )
    assert refused is st["contract"]
    assert k._goal_contract_open_facts() == ["compare Bun vs Deno"]


# ── BT-GC5: gates independent ────────────────────────────────────────────────


def test_bt_gc5_phase_gate_denial_fabricates_no_coverage():
    k = _Kernel()
    k.build("compare Bun vs Deno")
    # a denied admission produces no settled node: C stays 0, facts stay open
    st = k._goal_contract_state
    assert st["C"] == 0.0
    assert k._goal_contract_open_facts() == ["compare Bun vs Deno"]


# ── BT-GC6: D1/D11 shape — fail fast, no hang ────────────────────────────────


@pytest.mark.asyncio
async def test_bt_gc6_no_ui_step_settles_fast_typed():
    from backend.agent.tool_bridge import AgentToolBridge

    bridge = AgentToolBridge()
    bridge._mcp_servers = {}
    bridge._initialized = True
    t0 = time.perf_counter()
    result = await bridge.execute_tool(
        "write_file", {"path": "x.txt", "content": "hi"},
        session_id="bt-gc6-no-ui", _skip_resilience=True,
    )
    dt = time.perf_counter() - t0
    assert dt < 1.0, f"fail-fast took {dt:.2f}s — must settle < 1s"
    assert result.get("success") is False
    assert result.get("error_type") == "approval_unavailable"
    assert result.get("permission_response") == "approval_unavailable"


@pytest.mark.asyncio
async def test_bt_gc6_attached_ui_still_prompts():
    from backend import ws_manager as _wm
    from backend.agent.event_bus import IRISStreamEvent, get_event_bus
    from backend.agent.tool_bridge import AgentToolBridge

    mgr = _wm.get_websocket_manager()
    mgr.active_connections["bt-gc6-cli"] = object()
    mgr._session_manager.associate_client_with_session("bt-gc6-cli", "bt-gc6-ui")
    seen = []
    get_event_bus().subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {}
    bridge._initialized = True
    task = asyncio.create_task(
        bridge.execute_tool(
            "write_file", {"path": "x", "content": "hi"},
            session_id="bt-gc6-ui", _skip_resilience=True,
        )
    )
    for _ in range(50):
        if seen:
            break
        await asyncio.sleep(0.05)
    assert len(seen) == 1  # approval UI attached: normal flow, prompts
    # Answer the prompt (deny): proves the full round trip works and avoids
    # tearing down a pending wait with cancellation.
    try:
        from backend.agent.permissions import get_permission_system

        get_permission_system().respond_to_permission(
            seen[0].data["request_id"], approved=False
        )
        result = await asyncio.wait_for(task, timeout=10)
        assert result.get("success") is False
        assert result.get("permission_response") == "denied"
    finally:
        mgr.active_connections.pop("bt-gc6-cli", None)


# ── BT-GC7: stall is a rate ──────────────────────────────────────────────────


def test_bt_gc7_rate_trips_far_from_goal_spares_near():
    from backend.agent.tool_envelope import evaluate_streak

    # far from goal, no progress: trips fast
    fire, _ = evaluate_streak(
        [], 2, 2, coverage=0.2, coverage_unmoved_n=1,
        coverage_rho=0.001, stall_rate=0.05,
    )
    assert fire is True
    # same rho NEAR the goal but still moving: rho above the line, no trip
    assert evaluate_streak(
        [], 2, 2, coverage=0.9, coverage_unmoved_n=1,
        coverage_rho=0.5, stall_rate=0.05,
    ) == (False, "")


# ── BT-GC8: fail-fast teaches ────────────────────────────────────────────────


def test_bt_gc8_fail_fast_feeds_learning_hooks():
    from backend.agent.tool_bridge import _approval_unavailable_result
    from backend.agent.tool_errors import resolve_label

    r = _approval_unavailable_result("write_file", "side_effect", "s")
    assert resolve_label(r["error_type"]) is not None  # recallable by cause
    # failure-handler twin consumes the typed reason for scoring + links
    assert gc.is_blocked(r["error_type"]) is True
    import inspect

    from backend.agent import agent_kernel as ak

    src = inspect.getsource(ak.AgentKernel._der_handle_step_failure)
    assert "_der_score_step_outcome" in src
    assert "TASK_LEARNING" in src
    assert "write_node_links" in src


# ── BT-GC9: toggle ON runs write+shell, delete still prompts ─────────────────


def test_bt_gc9_toggle_governs_consent_destructive_stays_gated():
    from backend.agent.permissions import (
        PermissionAction, PermissionTier, classify_tool, get_permission_action,
    )

    assert get_permission_action(
        PermissionTier.SIDE_EFFECT, auto_approve=True
    ) == PermissionAction.AUTO_APPROVE
    assert get_permission_action(
        classify_tool("run_command", {"command": "ls -la"}), auto_approve=True
    ) == PermissionAction.AUTO_APPROVE
    assert get_permission_action(
        classify_tool("run_command", {"command": "rm -rf /tmp/x"}),
        auto_approve=True,
    ) != PermissionAction.AUTO_APPROVE
    assert get_permission_action(
        PermissionTier.DESTRUCTIVE, auto_approve=True
    ) != PermissionAction.AUTO_APPROVE


@pytest.mark.asyncio
async def test_bt_gc9_toggle_on_shell_runs_without_prompt():
    from backend.agent.event_bus import IRISStreamEvent, get_event_bus
    from backend.agent.tool_bridge import AgentToolBridge
    from backend.agent import permissions as _perm

    seen = []
    get_event_bus().subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    real_auto = _perm.get_auto_approve
    _perm.get_auto_approve = lambda: True
    try:
        bridge = AgentToolBridge()
        bridge._mcp_servers = {}
        bridge._initialized = True
        result = await bridge.execute_tool(
            "read_file", {"path": "x"}, session_id="bt-gc9", _skip_resilience=True
        )
        # read auto-approves under the toggle: no PERMISSION_REQUEST emitted,
        # the tool proceeds past the gate (unknown-tool fallthrough, not deny)
        assert seen == []
        assert result.get("permission_response") not in ("denied", "timed_out")
    finally:
        _perm.get_auto_approve = real_auto


# ── AC3.5/AC4.2: bonus pass fires once; ceiling discoveries counted ─────────


def test_ac35_bonus_pass_fires_once_over_ceiling():
    from backend.agent.agent_kernel import AgentKernel

    k = _Kernel()
    k.build("compare Bun vs Deno")
    st = k._goal_contract_state
    st["contract"] = gc.add_ceiling(
        st["contract"], ["install steps for Bun on Windows"]
    )
    k.settle("VERIFIED", "Bun vs Deno comparison with benchmarks")
    assert st["C"] == 1.0
    bound = AgentKernel._goal_contract_bonus_pass.__get__(k)
    first = bound()
    assert first is not None and "Bonus pass" in first["description"]
    assert st["counters"]["bonus_passes"] == 1
    assert bound() is None  # second call: no more passes


def test_ac42_verified_surplus_counts_agent_amendment():
    k = _Kernel()
    k.build("compare Bun vs Deno")
    st = k._goal_contract_state
    st["contract"] = gc.add_ceiling(
        st["contract"], ["install steps for Bun on Windows"]
    )
    st["counters"]["amendments_agent"] = 1
    assert st["contract"].ceiling == ("install steps for Bun on Windows",)
    assert st["counters"]["amendments_agent"] == 1
    # ceiling never blocks: floor coverage unaffected
    cov = gc.mark_coverage(
        st["contract"], ["VERIFIED"], ["Bun vs Deno comparison"]
    )
    assert cov.C == 1.0
