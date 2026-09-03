"""
T11 (REQ-1, REQ-4, REQ-8) — unit tests for the semantic logic gate.

Covers: 16 lanes / 5 domains, Tier 0 deterministic edge cases, tool-mode
policies, compound-task DAG shape, and compile_dag robustness.

Tier 1 (the neural centroid projector) was REMOVED — the gate routes on
rules (Tier 0) + coordinates (Tier 2 ontology) + the continuation lens, not
vector search. No embedding service or centroid artifact is exercised here.
"""

import pytest

from backend.agent import semantic_gate as sg
from backend.agent.semantic_gate import (
    CapabilityLane,
    IntentDomain,
    SemanticLogicGate,
    Tier0Intent,
    tier0_classify,
)


# ---------------------------------------------------------------------------
# lane inventory (REQ-1)
# ---------------------------------------------------------------------------

class TestLaneInventory:
    def test_16_lanes(self):
        assert len(CapabilityLane) == 16

    def test_5_domains(self):
        assert len(IntentDomain) == 5

    def test_followup_threshold_initial_value(self):
        # Pinned initial value (Decisions Locked); change only vs T13 numbers.
        assert sg.FOLLOWUP_SIM_THRESHOLD == 0.65


# ---------------------------------------------------------------------------
# Tier 0 edge cases (REQ-1 AC4)
# ---------------------------------------------------------------------------

class TestTier0EdgeCases:
    @pytest.mark.parametrize("text", ["", None, "   ", "\t\n"])
    def test_empty_is_chat(self, text):
        v = tier0_classify(text)
        assert v.intent == Tier0Intent.CHAT
        assert v.is_chitchat

    @pytest.mark.parametrize("text", [
        "tool: search for cats",
        "run: deploy the app",
        "execute: run tests",
        "plan: migrate the db",
    ])
    def test_tool_prefix_is_action(self, text):
        assert tier0_classify(text).intent == Tier0Intent.ACTION

    @pytest.mark.parametrize("text", [
        "got it", "sure thing", "sounds good", "agreed", "of course", "alright",
    ])
    def test_chitchat_acks(self, text):
        # Exact pinned ack set from test_universal_planning.py:91 (W0.2).
        v = tier0_classify(text)
        assert v.intent == Tier0Intent.CHAT and v.is_chitchat

    @pytest.mark.parametrize("text", [
        "search the web for the latest news",
        "look up online the weather",
        "find information about tauri v2",
    ])
    def test_web_search(self, text):
        v = tier0_classify(text)
        assert v.intent == Tier0Intent.WEB and v.is_web_search

    @pytest.mark.parametrize("text", [
        "create a file called notes.txt",
        "open chrome",
        "send an email to bob",
        "remind me to call mom at 5pm",
    ])
    def test_action_verbs(self, text):
        assert tier0_classify(text).intent == Tier0Intent.ACTION

    @pytest.mark.parametrize("text", [
        "what time is it in Tokyo?",
        "explain how recursion works",
        "what is the capital of France?",
    ])
    def test_standalone_questions(self, text):
        assert tier0_classify(text).intent == Tier0Intent.QUESTION

    def test_followup_with_context(self):
        ctx = [
            {"role": "user", "content": "remind me to call mom at 5pm"},
            {"role": "assistant", "content": "I'll create a reminder to call mom at 5pm."},
        ]
        assert tier0_classify("yes do it", ctx).intent == Tier0Intent.FOLLOWUP


# ---------------------------------------------------------------------------
# tool-mode policies (REQ-8 AC3)
# ---------------------------------------------------------------------------

class TestToolModePolicies:
    def test_disabled_never_plans(self):
        g = SemanticLogicGate(tool_mode="disabled")
        for text in ["search for cats", "tool: search for cats", "create a file"]:
            assert g.compile_dag(text).requires_der_kernel is False

    def test_ask_first_only_tool_prefix(self):
        g = SemanticLogicGate(tool_mode="ask_first")
        assert g.compile_dag("search for cats").requires_der_kernel is False
        assert g.compile_dag("create a file").requires_der_kernel is False
        assert g.compile_dag("tool: search for cats").requires_der_kernel is True

    def test_auto_plans_actions(self):
        g = SemanticLogicGate(tool_mode="auto")
        assert g.compile_dag("create a file called notes.txt").requires_der_kernel is True
        assert g.compile_dag("hey how are you?").requires_der_kernel is False

    def test_invalid_mode_falls_back_to_auto(self):
        g = SemanticLogicGate(tool_mode="banana")
        assert g.tool_mode == "auto"


# ---------------------------------------------------------------------------
# compound-task DAG (REQ-1 AC2)
# ---------------------------------------------------------------------------

class TestCompoundTaskDag:
    def test_ac2_multi_lane_dag_shape(self):
        g = SemanticLogicGate(tool_mode="auto")
        dag = g.compile_dag(
            "Look up our WebSocket reconnect pattern from last session and test it in ws_client.rs",
            web_mode=False,
        )
        lanes = {n.lane for n in dag.nodes}
        assert dag.requires_der_kernel is True
        assert CapabilityLane.SKILL_LANDMARK_QUERY in lanes
        assert CapabilityLane.CODE_INSPECTION in lanes
        assert CapabilityLane.TEST_VALIDATION in lanes
        rels = {e["relationship"] for e in dag.edges}
        assert "derives_from" in rels and "depends_on" in rels

    def test_single_clause_not_compound(self):
        assert sg._compound_task_lanes("create a file called notes.txt") == []


# ---------------------------------------------------------------------------
# default lane assignment (Tier 1 removed — deterministic defaults)
# ---------------------------------------------------------------------------

class TestDefaultLanes:
    def test_action_defaults_to_code_inspection(self):
        g = SemanticLogicGate(tool_mode="auto")
        dag = g.compile_dag("create a file called notes.txt")
        task_nodes = [n for n in dag.nodes if n.domain == IntentDomain.TASK_EXECUTION_DAG]
        assert task_nodes
        assert task_nodes[0].lane == CapabilityLane.CODE_INSPECTION
        assert dag.requires_der_kernel is True

    def test_question_defaults_to_explanation(self):
        g = SemanticLogicGate(tool_mode="auto")
        dag = g.compile_dag("what time is it in Tokyo?")
        assert dag.requires_der_kernel is False
        assert dag.nodes[0].lane == CapabilityLane.EXPLANATION_SYNTHESIS
        assert dag.nodes[0].domain == IntentDomain.CONVERSATIONAL_SURFACE


# ---------------------------------------------------------------------------
# compile_dag robustness
# ---------------------------------------------------------------------------

class TestCompileRobustness:
    @pytest.mark.parametrize("text", [
        None, "", "   ", "a" * 5000, "héllo wörld — ünïcode ✓",
        "tool:" * 100, "\x00\x01\x02",
    ])
    def test_never_raises(self, text):
        g = SemanticLogicGate(tool_mode="auto")
        dag = g.compile_dag(text)
        assert isinstance(dag, sg.DAGPlanGraph)
        assert dag.latency_ms >= 0.0

    def test_chitchat_pure_conversation(self):
        g = SemanticLogicGate(tool_mode="auto")
        dag = g.compile_dag("hey how are you?")
        assert dag.is_pure_conversation is True
        assert dag.requires_der_kernel is False
        assert dag.nodes[0].lane == CapabilityLane.CHITCHAT_BANTER

    def test_planning_hook_contributor(self):
        g = SemanticLogicGate(tool_mode="auto")
        seen = {"called": False}

        def contributor(graph, text, context):
            seen["called"] = True
            return graph

        g.register_policy("test_contributor", contributor)
        g.compile_dag("create a file")
        assert seen["called"] is True
