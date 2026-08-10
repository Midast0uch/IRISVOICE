"""Tests for the verified skill-capture pipeline (Phase 5.1 / research D1)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.agent.workflow_capture import (
    capture_workflow,
    distinct_tool_names,
    register_verified_skill,
    self_test_skill,
    sequence_similarity,
    should_capture,
)


class FakeSemantic:
    def __init__(self):
        self.store: dict = {}
        self.displays: dict = {}

    def update(self, category, key, value, confidence=0.9, source="test"):
        self.store[(category, key)] = value

    def get_by_category(self, category):
        class _E:
            pass

        out = []
        for (c, k), v in self.store.items():
            if c == category:
                e = _E()
                e.value = v
                e.key = k
                e.confidence = confidence
                out.append(e)
        return out

    def update_user_display(self, key, display_name, source="test"):
        self.displays[key] = display_name


class FakeMemory:
    def __init__(self):
        self.semantic = FakeSemantic()


def _seq(*tools):
    return [{"tool": t, "params": {"x": 1}, "success": True} for t in tools]


def test_distinct_tool_names_dedupes_and_orders():
    assert distinct_tool_names(_seq("a", "b", "a", "c")) == ["a", "b", "c"]


def test_sequence_similarity_jaccard():
    assert sequence_similarity(["a", "b"], ["a", "b"]) == 1.0
    assert sequence_similarity(["a", "b"], ["c", "d"]) == 0.0
    assert abs(sequence_similarity(["a", "b", "c"], ["a", "b"]) - 2 / 3) < 1e-9


def test_should_capture_requires_three_distinct_tools():
    assert should_capture(_seq("a", "b", "c"), existing_skills=[]) is True
    assert should_capture(_seq("a", "b"), existing_skills=[]) is False
    # repeated tool does not reach 3 distinct
    assert should_capture(_seq("a", "a", "a"), existing_skills=[]) is False


def test_should_capture_skips_when_similar_skill_exists():
    existing = [{"tool_sequence": _seq("a", "b", "c")}]
    assert should_capture(_seq("a", "b", "c"), existing_skills=existing) is False
    # disjoint sequence still captures
    assert should_capture(_seq("x", "y", "z"), existing_skills=existing) is True


def test_self_test_rejects_unknown_tool():
    registered = {"a", "b", "c"}
    assert self_test_skill(_seq("a", "b", "c"), lambda n: n in registered) is True
    assert self_test_skill(_seq("a", "b", "z"), lambda n: n in registered) is False


def test_self_test_rejects_bad_params():
    seq = [{"tool": "a", "params": "not-a-dict", "success": True}]
    assert self_test_skill(seq, lambda n: True) is False


def test_capture_workflow_end_to_end_registers():
    mem = FakeMemory()
    key = capture_workflow(
        tool_sequence=_seq("a", "b", "c"),
        memory=mem,
        existing_skills=[],
        is_registered=lambda n: n in {"a", "b", "c"},
    )
    assert key == "skill_a_workflow"
    raw = mem.semantic.store[("named_skills", key)]
    data = json.loads(raw)
    assert data["verified"] is True
    assert data["tool_sequence"] == _seq("a", "b", "c")
    assert "named_skills.skill_a_workflow" in mem.semantic.displays


def test_capture_workflow_skips_when_similar_exists():
    mem = FakeMemory()
    existing = [{"tool_sequence": _seq("a", "b", "c")}]
    key = capture_workflow(
        tool_sequence=_seq("a", "b", "c"),
        memory=mem,
        existing_skills=existing,
        is_registered=lambda n: n in {"a", "b", "c"},
    )
    assert key is None
    assert mem.semantic.store == {}


def test_capture_workflow_skips_when_self_test_fails():
    mem = FakeMemory()
    key = capture_workflow(
        tool_sequence=_seq("a", "b", "c"),
        memory=mem,
        existing_skills=[],
        is_registered=lambda n: n in {"a", "b"},  # 'c' unknown
    )
    assert key is None
    assert mem.semantic.store == {}


def test_register_verified_skill_returns_key():
    mem = FakeMemory()
    stub = {"name": "My Skill", "description": "d", "tool_sequence": _seq("a"), "verified": True}
    assert register_verified_skill(stub, mem) == "skill_my_skill"
