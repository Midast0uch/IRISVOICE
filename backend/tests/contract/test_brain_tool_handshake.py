"""Contract: Brain<->Tool handshake engages ONLY when the models differ.

Users pair a large Brain with a smaller execution model. The small model can
usually tell WHICH tool to reach for but not always WHAT to pass it — observed
live 2026-08-16: it chose `ask_user_question` and dispatched with no question
text, a permanent failure that aborted the step composing the user's answer.

So when the two roles are on different models, a tool call missing required
arguments asks the Brain for exactly those values and retries once. When both
roles are the SAME model there is nobody to coordinate with, so the path must be
byte-for-byte what it was — no extra call, no extra latency.
"""

from __future__ import annotations

import json

import pytest

from backend.agent.tool_decision import ToolDecisionBox, Decision, DecisionKind
from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter


class _Router(InferenceRouter):
    """Router that records which role each generate() targeted."""

    def __init__(self, reasoning, tool):
        reg = ProviderRegistry()
        for pid, model in {reasoning, tool}:
            reg.add(ProviderInstance(id=pid, label=pid, kind=ProviderKind.API,
                                     model=model))
        object.__setattr__(self, "_registry", reg)
        object.__setattr__(self, "_roles", RoleBindingTable(reg))
        object.__setattr__(self, "_default_role", "reasoning")
        object.__setattr__(self, "_transports", {})
        object.__setattr__(self, "_inprocess_mgr", None)
        self._roles.bind("reasoning", reasoning[0], model_override=reasoning[1])
        self._roles.bind("tool_execution", tool[0], model_override=tool[1])
        self.calls = []
        self.brain_reply = json.dumps({"args": {"text": "What is your name?"}})

    def generate(self, role, messages, **kw):
        self.calls.append(role)
        return self.brain_reply, "", []


def _box(router):
    from backend.agent.tool_registry import (
        register_builtin_tools, get_registry_tools, validate_tool_call,
    )
    register_builtin_tools()
    return ToolDecisionBox(
        router=router, tool_bridge=None,
        get_available_tools=get_registry_tools,
        validate_tool_call=validate_tool_call,
    )


SPLIT = (("cerebras", "big-model"), ("cohere", "small-model"))
SAME = (("cerebras", "one-model"), ("cerebras", "one-model"))


class TestBrainToolHandshake:
    def test_same_model_means_no_handshake_and_no_extra_call(self):
        r = _Router(*SAME)
        box = _box(r)
        assert box._bindings_differ() is False
        assert box._selection_role() == "reasoning"

        d = Decision(kind=DecisionKind.TOOL, tool="ask_user_question", params={})
        out = box._complete_params_via_brain(d, "ask the user their name")
        assert out is d, "same model must return the decision untouched"
        assert r.calls == [], "same model must not make an extra call"

    def test_split_models_select_tools_on_the_tool_binding(self):
        r = _Router(*SPLIT)
        box = _box(r)
        assert box._bindings_differ() is True
        assert box._selection_role() == "tool_execution", (
            "picking a tool and shaping its args is the Tool model's job"
        )

    def test_split_models_ask_the_brain_for_missing_required_args(self):
        r = _Router(*SPLIT)
        box = _box(r)
        d = Decision(kind=DecisionKind.TOOL, tool="ask_user_question", params={})
        out = box._complete_params_via_brain(d, "ask the user their name")

        assert r.calls == ["reasoning"], "the clarification must go to the Brain"
        assert out.kind == DecisionKind.TOOL
        assert out.params.get("text") == "What is your name?", (
            "the Brain's answer was not merged into the call"
        )

    def test_a_call_the_brain_cannot_complete_becomes_reasoning(self):
        """Never dispatch a call that is certain to fail permanently."""
        r = _Router(*SPLIT)
        r.brain_reply = "no json here"
        box = _box(r)
        d = Decision(kind=DecisionKind.TOOL, tool="ask_user_question", params={})
        out = box._complete_params_via_brain(d, "ask something")
        assert out.kind == DecisionKind.REASON
        assert out.source == "handshake"

    def test_complete_calls_are_left_alone(self):
        """Nothing missing -> no clarification, even on split models."""
        r = _Router(*SPLIT)
        box = _box(r)
        d = Decision(kind=DecisionKind.TOOL, tool="ask_user_question",
                     params={"text": "already here"})
        out = box._complete_params_via_brain(d, "goal")
        assert out is d
        assert r.calls == []

    def test_optional_params_do_not_trigger_the_handshake(self):
        """Only genuinely required args count as missing."""
        r = _Router(*SPLIT)
        box = _box(r)
        missing = box._missing_required("ask_user_question", {"text": "hi"})
        assert missing == [], f"optional params wrongly required: {missing}"

    def test_reason_and_fail_decisions_pass_through(self):
        r = _Router(*SPLIT)
        box = _box(r)
        for kind in (DecisionKind.REASON, DecisionKind.FAIL):
            d = Decision(kind=kind)
            assert box._complete_params_via_brain(d, "g") is d
        assert r.calls == []
