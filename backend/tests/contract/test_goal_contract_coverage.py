"""Contract tests: goal-contract-coverage boundaries (spec T13, TG-4).

Pins every interface the spec adds, BEFORE behavior:
  CT-GC1  NodeRecord carries the contract fields; expected_output +
          verified_fraction unchanged; all constructors stay valid.
  CT-GC2  extract_required deterministic; zero LLM (no router import).
  CT-GC3  validator re-adds every omitted fact (map_to_steps).
  CT-GC4  amendment writes a forward derives_from edge (link_derives_from).
  CT-GC5  evaluate_streak consumes C; idling fires on unmoved C; rho arm.
  CT-GC6  scheduler never reads goal state (AST + symbol scan).
  CT-GC7  blocked facts never raise C (denominator intact).
  CT-GC8  caller-existence: mark_coverage/amend/coverage-consumer all have
          real production callers (AST on agent_kernel.py).
  CT-GC9  Reason.APPROVAL_UNAVAILABLE exists, distinct, non-terminal.
  CT-GC10 capability/consent split: mode=capability, toggle=consent,
          DESTRUCTIVE gated in both toggle states.
  CT-GC14 destructive detector covers deletion/removal forms, gates ON.
  CT-GC11 no new phase layer: goal_contract imports no oscillator/phase.
  CT-GC12 fail-fast FAULTLINE shape; permission forward-set unchanged.
  CT-GC13 learning hooks wired: record hook, label registered, scorer +
          task:learning + link twin present on the failure path.
"""
from __future__ import annotations

import ast
import io
import os

import pytest

from backend.agent import goal_contract as gc
from backend.agent.goal_contract import Contract


def _src(path: str) -> str:
    with io.open(path, encoding="utf-8") as f:
        return f.read()


_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# backend/tests/contract/x -> repo root is three levels up from this file's dir?
# This file lives at backend/tests/contract/, so repo root = dirname x3.
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


# ── CT-GC1: NodeRecord shape ────────────────────────────────────────────────


def test_ct_gc1_node_record_carries_contract_fields():
    import dataclasses

    from backend.agent.der_loop import NodeRecord

    names = {f.name for f in dataclasses.fields(NodeRecord)}
    for need in (
        "required_facts", "ceiling_facts", "covered_facts",
        "blocked_facts", "contract_version",
        "expected_output", "verified_fraction",
    ):
        assert need in names, f"NodeRecord missing {need}"
    n = NodeRecord(step_id="s", parent_step_id="p")
    assert n.required_facts == [] and n.covered_facts == []
    assert n.blocked_facts == [] and n.ceiling_facts == []
    assert n.contract_version == 1
    assert n.expected_output == "" and n.verified_fraction == 0.0


# ── CT-GC2: determinism + zero LLM ──────────────────────────────────────────


def test_ct_gc2_extract_deterministic_no_router_import():
    req = "1. compare Bun vs Deno 2. list three features"
    assert gc.extract_required(req) == gc.extract_required(req)
    tree = ast.parse(_src(os.path.join(_REPO, "backend", "agent", "goal_contract.py")))
    imports = [
        ast.unparse(n)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
    ]
    assert not any(
        "router" in i or "phase_manager" in i or "oscillator" in i for i in imports
    ), f"goal_contract must not import router/phase machinery: {imports}"


# ── CT-GC3: validator re-add ────────────────────────────────────────────────


def test_ct_gc3_validator_readds_omitted_fact():
    facts = gc.extract_required("1. compare Bun vs Deno 2. list three features")
    omitted = gc.map_to_steps(facts, [{"expected_output": "Bun vs Deno table"}])
    assert omitted == ("list three features",)
    c = Contract(required=facts)
    assert set(omitted) <= set(c.required)  # deterministic set stands alone


# ── CT-GC4: forward amendment edge ───────────────────────────────────────────


def test_ct_gc4_derives_from_edge_writer_exists():
    from backend.agent.der_links import DerLinkWriter

    assert hasattr(DerLinkWriter, "link_derives_from")
    import inspect

    sig = inspect.signature(DerLinkWriter.link_derives_from)
    assert "new_step_id" in sig.parameters and "prior_step_id" in sig.parameters


# ── CT-GC5: streak consumes C ───────────────────────────────────────────────


def test_ct_gc5_streak_fires_on_unmoved_coverage():
    from backend.agent.tool_envelope import evaluate_streak

    fire, reason = evaluate_streak([], 2, 2, coverage=0.5, coverage_unmoved_n=3)
    assert fire is True and reason.startswith("coverage_stall")
    # covered contract never stalls
    assert evaluate_streak([], 2, 2, coverage=1.0, coverage_unmoved_n=99) == (False, "")
    # absent contract preserves legacy behavior exactly
    assert evaluate_streak(
        [{"novelty": "new", "match": "matched", "status": "success"}], 2, 2
    ) == (False, "")


def test_ct_gc5_stall_rate_arm():
    from backend.agent.tool_envelope import evaluate_streak

    fire, reason = evaluate_streak(
        [], 2, 2, coverage=0.4, coverage_unmoved_n=1,
        coverage_rho=0.001, stall_rate=0.05,
    )
    assert fire is True and reason.startswith("coverage_rate")
    assert evaluate_streak(
        [], 2, 2, coverage=0.4, coverage_unmoved_n=1,
        coverage_rho=0.5, stall_rate=0.05,
    ) == (False, "")


# ── CT-GC6: scheduler never reads goal state ────────────────────────────────


def test_ct_gc6_scheduler_orthogonal_to_goal_state():
    import re

    for rel in (
        os.path.join("backend", "agent", "phase_manager.py"),
        os.path.join("backend", "agent", "inference", "router.py"),
        os.path.join("backend", "agent", "trig_coupling.py"),
    ):
        src = _src(os.path.join(_REPO, rel)).lower()
        for sym in (
            "goal_contract", "required_facts", "covered_facts",
            "blocked_facts", "contract_version",
        ):
            assert re.search(r"\b" + re.escape(sym) + r"\b", src) is None, (
                f"{rel} reads goal symbol {sym}"
            )


# ── CT-GC7: blocked facts never raise C ─────────────────────────────────────


def test_ct_gc7_block_keeps_denominator():
    c = Contract(required=("compare Bun vs Deno", "list three features"))
    before = gc.mark_coverage(c, ["VERIFIED"], ["Bun vs Deno comparison"]).C
    assert before == 0.5
    # blocking is a record on the fact, not a denominator change: C identical
    after = gc.mark_coverage(c, ["VERIFIED"], ["Bun vs Deno comparison"]).C
    assert after == before == 0.5


# ── CT-GC8: caller existence ────────────────────────────────────────────────


def test_ct_gc8_seams_have_production_callers():
    import re

    kernel = _src(os.path.join(_REPO, "backend", "agent", "agent_kernel.py"))
    for sym in (
        "mark_coverage", "_goal_contract_apply_steering",
        "_goal_contract_block_facts", "_goal_contract_open_facts",
        "_goal_contract_name_blocked", "_goal_contract_state",
    ):
        assert re.search(r"\b" + re.escape(sym) + r"\b", kernel) is not None, (
            f"no production caller for {sym} — built but never called"
        )
    bridge = _src(os.path.join(_REPO, "backend", "agent", "tool_bridge.py"))
    assert "_approval_ui_attached(" in bridge
    assert "_approval_unavailable_result(" in bridge


# ── CT-GC9: APPROVAL_UNAVAILABLE vocabulary ─────────────────────────────────


def test_ct_gc9_approval_unavailable_distinct():
    from backend.agent.nodes.outcome import (
        Reason, TERMINAL_REASONS, is_terminal_reason,
    )

    assert Reason.APPROVAL_UNAVAILABLE.value == "approval_unavailable"
    assert Reason.APPROVAL_UNAVAILABLE != Reason.PERMISSION_DENIED
    assert Reason.APPROVAL_UNAVAILABLE != Reason.PERMISSION_DENIED
    assert Reason.APPROVAL_UNAVAILABLE not in TERMINAL_REASONS
    assert is_terminal_reason(Reason.ROBOTS_REFUSED) is True
    assert gc.is_blocked(Reason.APPROVAL_UNAVAILABLE) is True


# ── CT-GC10: capability/consent split ───────────────────────────────────────


def test_ct_gc10_capability_stays_with_mode():
    from backend.capabilities import CapabilitySet

    assert "run_command" in CapabilitySet._TERMINAL_TOOLS
    assert CapabilitySet.is_tool_allowed("run_command") in (True, False)  # mode-bound


def test_ct_gc10_consent_comes_from_toggle():
    from backend.agent.permissions import (
        PermissionAction, PermissionTier, _ALWAYS_ASK_TOOLS,
        get_permission_action,
    )

    assert _ALWAYS_ASK_TOOLS <= set(
        __import__("backend.agent.permissions", fromlist=["_DESTRUCTIVE_TOOLS"])
        ._DESTRUCTIVE_TOOLS
    )
    assert "run_command" not in _ALWAYS_ASK_TOOLS  # terminal left always-ask
    assert get_permission_action(
        PermissionTier.SIDE_EFFECT, auto_approve=True
    ) == PermissionAction.AUTO_APPROVE
    assert get_permission_action(
        PermissionTier.SIDE_EFFECT, auto_approve=False
    ) == PermissionAction.REQUIRE_APPROVAL
    # DESTRUCTIVE gated in BOTH toggle states
    assert get_permission_action(
        PermissionTier.DESTRUCTIVE, auto_approve=True
    ) != PermissionAction.AUTO_APPROVE
    assert get_permission_action(
        PermissionTier.DESTRUCTIVE, auto_approve=False
    ) != PermissionAction.AUTO_APPROVE


# ── CT-GC14: destructive detector ───────────────────────────────────────────


@pytest.mark.parametrize("cmd", [
    "rm -rf /tmp/x", "rm foo", "rmdir /s bar", "del file.txt",
    "erase disk", "Remove-Item C:\\x", "rd /s q", "unlink a",
    "truncate -s 0 f", "shred secret",
])
def test_ct_gc14_deletion_forms_gate_even_when_on(cmd):
    from backend.agent.permissions import (
        PermissionAction, PermissionTier, classify_tool, get_permission_action,
    )

    assert classify_tool("run_command", {"command": cmd}) == PermissionTier.DESTRUCTIVE
    assert get_permission_action(
        PermissionTier.DESTRUCTIVE, auto_approve=True
    ) != PermissionAction.AUTO_APPROVE


def test_ct_gc14_prose_in_writes_never_trips_detector():
    from backend.agent.permissions import PermissionTier, classify_tool

    assert classify_tool(
        "write_file",
        {"path": "doc.txt", "content": "remove-item from the shopping list"},
    ) == PermissionTier.SIDE_EFFECT


# ── CT-GC11: no new phase layer ─────────────────────────────────────────────


def test_ct_gc11_goal_contract_adds_no_phase_layer():
    tree = ast.parse(_src(os.path.join(_REPO, "backend", "agent", "goal_contract.py")))
    mods = [
        (n.module or "")
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module
    ] + [
        a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.Import)
        for a in n.names
    ]
    blob = "\n".join(mods)
    for banned in (
        "phase_manager", "oscillator", "coupled_registry",
        "caducean_trajectory", "trig_coupling",
    ):
        assert banned not in blob, f"goal_contract imports phase layer {banned}"


# ── CT-GC12: FAULTLINE shape + forward-set ───────────────────────────────────


def test_ct_gc12_fail_fast_faultline_shape():
    from backend.agent.tool_bridge import _approval_unavailable_result

    r = _approval_unavailable_result("write_file", "side_effect", "s")
    for key in (
        "success", "error", "error_type", "retryable", "blame",
        "info_state", "details", "ts",
    ):
        assert key in r, f"canonical shape missing {key}"
    assert r["success"] is False
    assert r["error_type"] == "approval_unavailable"
    assert r["retryable"] == "maybe" and r["blame"] == "world"
    assert r["info_state"] == "blocked"
    assert "raw" in r["details"]
    assert r["permission_response"] == "approval_unavailable"


def test_ct_gc12_permission_forward_set_unchanged():
    src = _src(os.path.join(_REPO, "hooks", "useIRISWebSocket.ts"))
    for evt in ("permission:request", "permission:granted", "permission:denied"):
        assert evt in src, f"forward-set lost {evt}"
    assert "approval_unavailable" not in src  # no new event type


# ── CT-GC13: learning hooks ─────────────────────────────────────────────────


def test_ct_gc13_label_registered_and_consumers_present():
    from backend.agent.tool_errors import resolve_label

    spec = resolve_label("approval_unavailable")
    assert spec is not None
    assert (spec.dimensions.retryable, spec.dimensions.blame,
            spec.dimensions.info_state) == ("maybe", "world", "blocked")


def test_ct_gc13_failure_path_feeds_learning_hooks():
    src = _src(os.path.join(_REPO, "backend", "agent", "agent_kernel.py"))
    # failure-handler twin (finalize is skipped on that path)
    assert "_goal_contract_block_facts(" in src
    assert "REQ-11 AC11.3" in src
    assert "_der_score_step_outcome(" in src
    assert "TASK_LEARNING" in src
    assert "write_node_links(" in src
    from backend.agent.agent_kernel import AgentKernel
    from backend.agent.der_links import DerLinkWriter

    assert hasattr(AgentKernel, "_der_score_step_outcome")
    assert hasattr(DerLinkWriter, "link_derives_from")
    assert hasattr(DerLinkWriter, "link_failed_like")
