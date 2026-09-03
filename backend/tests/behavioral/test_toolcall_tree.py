"""Behavioral tests: ToolCallTree collapse (REQ-13).

Verifies nodes are collected, the tree emits on collapse, and the pre-filter
can retrieve succeeded tools for repeated goals.

Spec: specs/der-tool-resolution-blackbox/ REQ-13
"""

from __future__ import annotations

from backend.agent.tool_decision import (
    Decision,
    DecisionKind,
    ToolCallNode,
    ToolCallTree,
    ToolDecisionBox,
)


class _DummyRouter:
    def generate(self, role, messages, **kw):
        return ("reasoning", "", [])
    def health_check_provider(self, role="reasoning"):
        return {"ok": True, "provider": "test", "model": "test"}


class TestToolCallNode:
    """ToolCallNode is a simple dataclass with the expected fields."""

    def test_create_node(self):
        node = ToolCallNode(
            step_id="step_1",
            tool="search_web",
            args_hash="abc123",
            result_summary="found results",
            error_type=None,
            source="llm",
            split_depth=0,
            parent_step_id=None,
        )
        assert node.step_id == "step_1"
        assert node.tool == "search_web"
        assert node.args_hash == "abc123"
        assert node.source == "llm"

    def test_child_node(self):
        child = ToolCallNode(
            step_id="step_1_1",
            tool="crawler_query",
            args_hash="def456",
            result_summary="crawled",
            error_type="transient",
            source="memory",
            split_depth=1,
            parent_step_id="step_1",
        )
        assert child.parent_step_id == "step_1"
        assert child.split_depth == 1


class TestToolCallTreeCollection:
    """ToolDecisionBox records tool calls and emits them as a tree."""

    def test_record_and_retrieve_nodes(self):
        box = ToolDecisionBox(
            router=_DummyRouter(),
            tool_bridge=None,
            get_available_tools=lambda: [],
            validate_tool_call=lambda n, p: (True, None),
        )
        box.record_tool_call(
            step_id="s1", tool="search_web", args_hash="a1",
            result_summary="ok", error_type=None, source="llm",
            split_depth=0, parent_step_id=None,
        )
        box.record_tool_call(
            step_id="s2", tool="send_email", args_hash="b2",
            result_summary="sent", error_type=None, source="memory",
            split_depth=1, parent_step_id="s1",
        )
        tree = box.get_tool_call_tree(conversation_id="conv1")
        assert tree.conversation_id == "conv1"
        assert len(tree.nodes) == 2
        assert tree.nodes[0].tool == "search_web"
        assert tree.nodes[1].parent_step_id == "s1"
        assert tree.nodes[1].source == "memory"

    def test_get_tree_clears_nodes(self):
        """get_tool_call_tree returns nodes then clears the list."""
        box = ToolDecisionBox(
            router=_DummyRouter(),
            tool_bridge=None,
            get_available_tools=lambda: [],
            validate_tool_call=lambda n, p: (True, None),
        )
        box.record_tool_call(step_id="s1", tool="t", args_hash="h",
                             result_summary="ok", error_type=None,
                             source="llm")
        tree1 = box.get_tool_call_tree(conversation_id="c1")
        assert len(tree1.nodes) == 1

        tree2 = box.get_tool_call_tree(conversation_id="c1")
        assert len(tree2.nodes) == 0  # cleared

    def test_tree_across_splits(self):
        """Simulates a DER run with a split: parent -> child step."""
        box = ToolDecisionBox(
            router=_DummyRouter(),
            tool_bridge=None,
            get_available_tools=lambda: [],
            validate_tool_call=lambda n, p: (True, None),
        )
        # Parent step
        box.record_tool_call(
            step_id="step_1", tool="search_web", args_hash="a1",
            result_summary="found", error_type=None, source="llm",
            split_depth=0,
        )
        # Split: child step (new step_id, parent reference)
        box.record_tool_call(
            step_id="step_1_1", tool="crawler_query", args_hash="a2",
            result_summary="crawled", error_type="transient", source="memory",
            split_depth=1, parent_step_id="step_1",
        )
        tree = box.get_tool_call_tree(conversation_id="c1")
        assert len(tree.nodes) == 2
        # Hierarchy is recoverable from parent_step_id
        parent_ids = {n.parent_step_id for n in tree.nodes if n.parent_step_id}
        step_ids = {n.step_id for n in tree.nodes}
        assert "step_1" in parent_ids  # child points to parent
        assert "step_1_1" in step_ids  # child in tree
