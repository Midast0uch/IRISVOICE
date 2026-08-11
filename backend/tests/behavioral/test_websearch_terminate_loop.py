"""Behavioral: websearch gather-loop termination (specs/long-horizon-der-execution).

Drives the REAL ToolDecisionBox + REAL kernel gather-sanction closure
(REQ-3 AC3/AC4) through a gather -> synthesize task. Emergent property per
the NEW spec: redirection is driven by plan/evidence state, NOT oscillator
convergence (D1: physics never authorizes/forbids; AC4: evidence state).

  - First web-intent step resolves to crawler_query (content must be gathered
    once — a first crawl is ALWAYS sanctioned).
  - Once >=1 crawl is committed (_der_crawl_attempts non-empty), a SYNTHESIS
    goal (non-web intent) is steered toward READING the gathered documents
    (get_rendered_documents) instead of re-gathering — the loop's gather waste
    is cut at the source.
  - A FRESH distinct web query beyond the per-task budget
    (len(attempted) >= _MAX_CRAWLS_PER_TASK) is vetoed -> REASON (tool=None,
    rationale budget_exhausted). Same-key repeats are cache-served and skip
    the budget (REQ-3 AC3).
"""

import json
import uuid
from types import SimpleNamespace

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_execution_ledger import make_action_key
from backend.agent.tool_decision import DecisionKind


def _make_box(router):
    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = SimpleNamespace(_mycelium=SimpleNamespace())
    k.session_id = f"sess_{uuid.uuid4().hex[:8]}"
    k.conversation_id = "conv_behavioral"
    k._der_crawl_attempts = {}
    k._der_task_class = "full"
    k._der_completed_tools = []
    k._router = router
    k._tool_bridge = SimpleNamespace()
    k._tool_box = None
    k.infer = lambda *a, **kw: "reason"  # type: ignore[method-assign]
    box = k._get_tool_box()
    return k, box


def _router_proposing(proposal_json):
    # Production router.generate returns (text, thinking, tool_calls).
    return SimpleNamespace(generate=lambda *a, **kw: (proposal_json, "", None))


def _propose_crawl():
    return json.dumps(
        {"kind": "tool", "tool": "crawler_query", "params": {"query": "x"}}
    )


def _propose_reason():
    return json.dumps({"kind": "reasoning", "rationale": "synthesize"})


class TestWebsearchTerminateLoopBehavior:
    """The full resolution cycle through the real box + real closure."""

    def test_evidence_committed_synthesis_accepts_read_tool(self, monkeypatch):
        monkeypatch.setattr(
            "backend.agent.tool_registry.capability_allowed", lambda _spec: True
        )
        # After >=1 crawl committed, AC4 steers synthesis toward READING:
        # the memory hint surfaces get_rendered_documents and the box accepts
        # the model's read choice (the gather re-proposal is NOT force-denied
        # while budget remains — AC2/AC4: advisory steering, not physics veto).
        k, box = _make_box(
            _router_proposing(
                json.dumps(
                    {"kind": "tool", "tool": "get_rendered_documents",
                     "params": {"step_id": "s1"}}
                )
            )
        )
        k._der_crawl_attempts[k.conversation_id] = {
            make_action_key("search the web for recent Python 3.13 features"),
        }
        d = box.resolve(
            {"description": "summarize the findings from the search"},
            {},
            session_id=k.session_id,
            conversation_id=k.conversation_id,
        )
        assert d.kind == DecisionKind.TOOL
        assert d.tool == "get_rendered_documents"

    def test_synthesis_gather_reproposal_allowed_while_budget_remains(self, monkeypatch):
        """AC2/AC4: after a crawl committed, a synthesis step that the model
        STILL routes to a gather is not force-denied by convergence/steering
        alone — the advisory read steer must not become a physics-style veto.
        The budget bound (fresh query beyond _MAX_CRAWLS_PER_TASK) is the
        hard stop, asserted in test_fresh_query_beyond_budget_is_vetoed."""
        monkeypatch.setattr(
            "backend.agent.tool_registry.capability_allowed", lambda _spec: True
        )
        k, box = _make_box(_router_proposing(_propose_crawl()))
        k._der_crawl_attempts[k.conversation_id] = {
            make_action_key("search the web for recent Python 3.13 features"),
        }
        d = box.resolve(
            {"description": "summarize the findings from the search"},
            {},
            session_id=k.session_id,
            conversation_id=k.conversation_id,
        )
        # Advisory steering only: with 1/3 budget used, the model's gather
        # re-proposal still resolves (REQ-3 AC2 — not denied by state alone).
        assert d.kind == DecisionKind.TOOL
        assert d.tool == "crawler_query"

    def test_fresh_query_beyond_budget_is_vetoed(self, monkeypatch):
        monkeypatch.setattr(
            "backend.agent.tool_registry.capability_allowed", lambda _spec: True
        )
        k, box = _make_box(_router_proposing(_propose_crawl()))

        # Budget saturated: 3 distinct queries already committed to this task.
        k._der_crawl_attempts[k.conversation_id] = {
            make_action_key(g)
            for g in ("search topic a", "search topic b", "search topic c")
        }

        # A FRESH distinct web query beyond the per-task budget is vetoed
        # (REQ-3 AC3: explicit resource bound -> REASON, no tool).
        d = box.resolve(
            {"description": "search the web for more details on the findings"},
            {},
            session_id=k.session_id,
            conversation_id=k.conversation_id,
        )
        assert d.kind == DecisionKind.REASON
        assert d.tool is None
        assert d.rationale == "budget_exhausted"

    def test_pre_gather_synthesis_step_is_not_blocked(self, monkeypatch):
        # Before any gather has run, a synthesis step is not vetoed — the
        # model's REASON choice flows through untouched.
        monkeypatch.setattr(
            "backend.agent.tool_registry.capability_allowed", lambda _spec: True
        )
        k, box = _make_box(_router_proposing(_propose_reason()))
        d = box.resolve(
            {"description": "summarize the findings from the search"},
            {},
            session_id=k.session_id,
            conversation_id=k.conversation_id,
        )
        assert d.kind == DecisionKind.REASON
