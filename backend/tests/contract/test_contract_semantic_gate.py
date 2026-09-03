"""
T12 (REQ-1, REQ-2, REQ-5) — contract test CT-GATE-1.

Pins the gate's boundary contracts so a cross-layer break is caught at the
interface BEFORE behavior (AGENTS.md contract-testing layer):

1. ``DAGPlanGraph`` schema — node/edge/graph field shapes (REQ-1 AC1).
2. zero-``TASK_START`` on chitchat — pure conversation carries no task nodes.
3. Composite DAG prompts emit task nodes with typed dependencies (REQ-1 AC2).
4. ``_tool_mode`` (auto|ask_first|disabled) is honored (REQ-8 AC3).
5. Gate fields appear on the ``[LAYERS]`` line, additive-only (REQ-5 AC1).
6. Widen-scope logging fires with the stable key prefix (REQ-5 AC2).
7. REQ-7 write-back is OFF the hot path — compile_dag never writes to the
   chain (the kernel does, separately).
"""

import logging

import pytest

from backend.agent import semantic_gate as sg
from backend.agent.semantic_gate import (
    CapabilityLane,
    DAGPlanGraph,
    EdgeRelationship,
    IntentDomain,
    SemanticLogicGate,
)
from backend.utils.observability import TurnMetrics

ACTION_PROMPT = "create a file called notes.txt"
CHITCHAT_PROMPT = "hey how are you?"
COMPOUND_PROMPT = (
    "Look up our WebSocket reconnect pattern from last session "
    "and test it in ws_client.rs"
)


@pytest.fixture
def gate():
    return SemanticLogicGate(tool_mode="auto")


# ---------------------------------------------------------------------------
# 1. DAGPlanGraph schema (REQ-1 AC1)
# ---------------------------------------------------------------------------

class TestDagPlanGraphSchema:
    def test_graph_field_types(self, gate):
        for text in (ACTION_PROMPT, CHITCHAT_PROMPT, COMPOUND_PROMPT, None, ""):
            dag = gate.compile_dag(text)
            assert isinstance(dag, DAGPlanGraph)
            assert isinstance(dag.nodes, list)
            assert isinstance(dag.edges, list)
            assert isinstance(dag.is_pure_conversation, bool)
            assert isinstance(dag.requires_der_kernel, bool)
            assert isinstance(dag.latency_ms, float) and dag.latency_ms >= 0.0
            assert isinstance(dag.why, str)

    def test_node_field_types(self, gate):
        dag = gate.compile_dag(COMPOUND_PROMPT)
        assert dag.nodes, "compound prompt must produce nodes"
        for n in dag.nodes:
            assert isinstance(n.node_id, str) and n.node_id
            assert isinstance(n.domain, IntentDomain)
            assert isinstance(n.lane, CapabilityLane)
            assert isinstance(n.description, str)
            assert n.topic_domain is None or isinstance(n.topic_domain, str)
            assert n.execution_domain is None or n.execution_domain in (
                "voice", "der", "research",
            )
            assert isinstance(n.confidence, float)

    def test_edge_field_types(self, gate):
        dag = gate.compile_dag(COMPOUND_PROMPT)
        valid_rels = {e.value for e in EdgeRelationship}
        for e in dag.edges:
            assert set(e.keys()) == {"source", "target", "relationship"}
            assert isinstance(e["source"], str)
            assert isinstance(e["target"], str)
            assert e["relationship"] in valid_rels

    def test_node_ids_unique(self, gate):
        dag = gate.compile_dag(COMPOUND_PROMPT)
        ids = [n.node_id for n in dag.nodes]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# 2. zero-TASK_START on chitchat (REQ-1 AC4)
# ---------------------------------------------------------------------------

class TestChitchatZeroTaskStart:
    def test_pure_conversation_no_task_nodes(self, gate):
        dag = gate.compile_dag(CHITCHAT_PROMPT)
        assert dag.is_pure_conversation is True
        assert dag.requires_der_kernel is False
        assert all(
            n.domain != IntentDomain.TASK_EXECUTION_DAG for n in dag.nodes
        ), "chitchat must emit zero TASK_EXECUTION_DAG nodes (no TASK_START)"
        assert all(n.domain != IntentDomain.RESEARCH_SWARM_DAG for n in dag.nodes)
        assert dag.edges == []

    @pytest.mark.parametrize("text", ["", None, "   ", "got it", "thanks"])
    def test_social_utterances_never_task(self, gate, text):
        dag = gate.compile_dag(text)
        assert dag.requires_der_kernel is False


# ---------------------------------------------------------------------------
# 3. composite DAG emits task nodes + typed dependencies (REQ-1 AC2)
# ---------------------------------------------------------------------------

class TestCompositeDagContract:
    def test_task_nodes_with_typed_edges(self, gate):
        dag = gate.compile_dag(COMPOUND_PROMPT, web_mode=False)
        assert dag.requires_der_kernel is True
        task_nodes = [n for n in dag.nodes if n.domain == IntentDomain.TASK_EXECUTION_DAG]
        assert task_nodes, "composite prompt must emit TASK_EXECUTION_DAG nodes"
        rels = {e["relationship"] for e in dag.edges}
        assert "derives_from" in rels
        assert "depends_on" in rels

    def test_single_action_emits_task_node(self, gate):
        dag = gate.compile_dag(ACTION_PROMPT)
        assert dag.requires_der_kernel is True
        assert any(n.domain == IntentDomain.TASK_EXECUTION_DAG for n in dag.nodes)


# ---------------------------------------------------------------------------
# 4. _tool_mode honored (REQ-8 AC3)
# ---------------------------------------------------------------------------

class TestToolModeContract:
    def test_disabled_never_der(self):
        g = SemanticLogicGate(tool_mode="disabled")
        assert g.compile_dag(ACTION_PROMPT).requires_der_kernel is False
        assert g.compile_dag("tool: search").requires_der_kernel is False

    def test_ask_first_only_prefix(self):
        g = SemanticLogicGate(tool_mode="ask_first")
        assert g.compile_dag(ACTION_PROMPT).requires_der_kernel is False
        assert g.compile_dag("tool: search").requires_der_kernel is True

    def test_auto_action_der(self):
        g = SemanticLogicGate(tool_mode="auto")
        assert g.compile_dag(ACTION_PROMPT).requires_der_kernel is True
        assert g.compile_dag(CHITCHAT_PROMPT).requires_der_kernel is False


# ---------------------------------------------------------------------------
# 5. [LAYERS] gate fields, additive-only (REQ-5 AC1)
# ---------------------------------------------------------------------------

class TestLayersGateFields:
    def test_gate_fields_on_layers_line(self):
        m = TurnMetrics(turn_id="ct1")
        m.record_gate(
            domain="task_execution_dag",
            lanes="lane:code_inspection,lane:test_validation",
            latency_ms=9.4,
            widen_scope="exact",
        )
        line = m.to_log_line()
        assert "gate_domain=task_execution_dag" in line
        assert "gate_lanes=lane:code_inspection,lane:test_validation" in line
        assert "gate_latency_ms=9.4" in line
        assert "gate_widen_scope=exact" in line

    def test_existing_fields_survive(self):
        # Additive-only: the pre-gate fields must still be present.
        m = TurnMetrics(turn_id="ct2", engine="native", path="der", der_steps=3)
        line = m.to_log_line()
        for f in ("engine=native", "path=der", "der_steps=3", "der_calls=0",
                  "budget_source=", "chain_drops=", "429s=", "narration=",
                  "pacman_store=", "pacman_recall=", "xi=", "traj_rows=",
                  "map_events=", "step_tokens=", "gov_past=", "gov_live=",
                  "gov_both=", "gov_ratio=", "ttft_ms=", "e2e_ms="):
            assert f in line, f"existing [LAYERS] field dropped: {f}"

    def test_record_gate_never_raises(self):
        m = TurnMetrics(turn_id="ct3")
        m.record_gate()  # empty call — defaults
        assert m.gate_latency_ms is None
        m.to_log_line()  # renders with '-'


# ---------------------------------------------------------------------------
# 6. widen-scope logging (REQ-5 AC2)
# ---------------------------------------------------------------------------

class TestWidenScopeLogging:
    def test_record_widening_telemetry_key_prefix(self, caplog):
        from backend.agent.ontology_recall import RecallFilters, record_widening_telemetry

        with caplog.at_level(logging.INFO, logger="backend.agent.ontology_recall"):
            record_widening_telemetry(
                "exact", RecallFilters(topic_domain="general", execution_domain="der")
            )
        assert any(
            "[ontology_recall] scope=exact requested=" in r.message
            for r in caplog.records
        ), "widen telemetry must log the stable key prefix"


# ---------------------------------------------------------------------------
# 7. REQ-7 write-back is OFF the hot path
# ---------------------------------------------------------------------------

class TestWriteBackOffHotPath:
    def test_compile_dag_never_writes_chain(self, monkeypatch, gate):
        def _boom(*a, **k):
            raise AssertionError("compile_dag must not write to the chain")

        monkeypatch.setattr(sg, "caducean_write_routing", _boom)
        # Classification is pure: a write attempt would raise.
        dag = gate.compile_dag(ACTION_PROMPT, web_mode=False)
        assert dag.requires_der_kernel is True
        assert isinstance(dag, DAGPlanGraph)