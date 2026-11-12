"""CT-1 (specs/clm-memory design, Testing Strategy; CLM-1 AC6): view parity.

While no edit has happened, ``ContextView.render()`` returns the SAME message
list the old builder returns for the same parts: same order, same dict shapes,
same bytes. Unit level (T1.1 part 1): the parts are synthetic but follow the
shapes ``AgentKernel._assemble_direct_context`` builds - a system message, the
``<memory>`` pair, profile messages, the ``<context_memory>`` pair, history,
and the current user turn. Recorded rows hold only block SIZES (Wave 0), not
content, so no recorded text exists to replay.

``_old_builder_list`` is the final assembly of the old builder, copied from
``kernel/context.py`` (``messages = [system]; extend x3; ensure the list ends
on the current user turn``). It is the oracle: this test does not import the
kernel (430 lazy imports).
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List

import pytest

from backend.agent.context_view import (
    CURRENT_USER,
    HISTORY,
    RECALL_CHUNKS,
    RECALL_EPISODIC,
    RECALL_PROFILE,
    SYSTEM_PROMPT,
    ContextView,
    Ref,
)

TEXT = "and what was the second one?"


def _parts(*, episodic: bool, profile: bool, chunks: bool, history: int) -> Dict[str, Any]:
    hist: List[Dict[str, Any]] = []
    for i in range(history):
        hist.append({"role": "user", "content": f"question {i} — café über"})
        hist.append({"role": "assistant", "content": f"answer {i}"})
    return {
        "system": [{"role": "system", "content": "You are IRIS.\n\nRules: be exact."}],
        "episodic": (
            [
                {"role": "user", "content": "<memory>\npast success\n</memory>"},
                {"role": "assistant", "content": "Understood — I have that context."},
            ]
            if episodic
            else []
        ),
        "profile": (
            [{"role": "system", "content": "<mycelium_profile>likes tea</mycelium_profile>"}]
            if profile
            else []
        ),
        "chunks": (
            [
                {"role": "user", "content": "<context_memory>\nfact A\n---\nfact B\n</context_memory>"},
                {"role": "assistant", "content": "Understood — I have those context fragments."},
            ]
            if chunks
            else []
        ),
        "history": hist,
    }


def _old_builder_list(p: Dict[str, Any], text: str) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = list(p["system"])
    messages.extend(p["episodic"])
    messages.extend(p["profile"])
    messages.extend(p["chunks"])
    messages.extend(p["history"])
    if (
        not messages
        or messages[-1].get("content") != text
        or messages[-1].get("role") != "user"
    ):
        messages.append({"role": "user", "content": text})
    return messages


def _view_list(p: Dict[str, Any], text: str, *, order=None) -> List[Dict[str, Any]]:
    """The call-site shape T1.1 will have: admit each part in today's order."""
    view = ContextView()
    admits = [
        (SYSTEM_PROMPT, p["system"], True),
        (RECALL_EPISODIC, p["episodic"], False),
        (RECALL_PROFILE, p["profile"], False),
        (RECALL_CHUNKS, p["chunks"], False),
        (HISTORY, p["history"], False),
    ]
    if order is not None:
        admits = [admits[i] for i in order]
    for kind, msgs, protected in admits:
        view.admit(kind, msgs, protected=protected)
    out = view.render()
    if not out or out[-1].get("content") != text or out[-1].get("role") != "user":
        view.admit(CURRENT_USER, [{"role": "user", "content": text}], protected=True)
    return view.render()


def _bytes(messages: List[Dict[str, Any]]) -> bytes:
    return json.dumps(messages, ensure_ascii=False, sort_keys=False).encode("utf-8")


SCENARIOS = [
    pytest.param(dict(episodic=False, profile=False, chunks=False, history=0), id="first-turn"),
    pytest.param(dict(episodic=True, profile=False, chunks=False, history=2), id="episodic-history"),
    pytest.param(dict(episodic=True, profile=True, chunks=True, history=3), id="all-parts"),
    pytest.param(dict(episodic=False, profile=True, chunks=True, history=0), id="profile-chunks-no-history"),
]


@pytest.mark.parametrize("shape", SCENARIOS)
def test_render_is_byte_equal_to_old_builder_list(shape):
    parts = _parts(**shape)
    assert _bytes(_view_list(parts, TEXT)) == _bytes(_old_builder_list(parts, TEXT))


def test_current_turn_already_last_is_not_appended_twice():
    parts = _parts(episodic=False, profile=False, chunks=False, history=1)
    parts["history"].append({"role": "user", "content": TEXT})
    assert _bytes(_view_list(parts, TEXT)) == _bytes(_old_builder_list(parts, TEXT))
    assert sum(1 for m in _view_list(parts, TEXT) if m["content"] == TEXT) == 1


def test_tool_call_message_keeps_its_shape():
    parts = _parts(episodic=False, profile=False, chunks=False, history=0)
    parts["history"] = [
        {"role": "user", "content": "run it"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function",
                                                              "function": {"name": "t", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
    ]
    assert _bytes(_view_list(parts, TEXT)) == _bytes(_old_builder_list(parts, TEXT))


def test_reordered_block_breaks_parity():
    """The guard is sensitive: swapping two non-empty blocks changes the bytes."""
    parts = _parts(episodic=True, profile=True, chunks=True, history=2)
    expected = _bytes(_old_builder_list(parts, TEXT))
    # system, chunks, profile, episodic, history  (episodic <-> chunks swapped)
    assert _bytes(_view_list(parts, TEXT, order=[0, 3, 2, 1, 4])) != expected
    # history before chunks
    assert _bytes(_view_list(parts, TEXT, order=[0, 1, 2, 4, 3])) != expected


def test_view_never_mutates_the_lists_or_dicts_it_is_given():
    parts = _parts(episodic=True, profile=True, chunks=True, history=2)
    before = copy.deepcopy(parts)
    rendered = _view_list(parts, TEXT)
    assert parts == before
    # editing a rendered message touches neither the view's blocks nor the record
    rendered[1]["content"] = "EDITED"
    parts_after = copy.deepcopy(parts)
    view = ContextView()
    view.admit(HISTORY, parts["history"])
    out = view.render()
    out[0]["content"] = "EDITED"
    assert view.render()[0]["content"] == parts["history"][0]["content"]
    assert parts == parts_after


def test_admit_assigns_stable_ids_refs_and_tokens():
    view = ContextView()
    b1 = view.admit(SYSTEM_PROMPT, [{"role": "system", "content": "x" * 70}], protected=True)
    b2 = view.admit(RECALL_CHUNKS, [], ref=Ref("chunk", "c-1", "t-1"))
    assert (b1.block_id, b2.block_id) == ("b1", "b2")
    assert b1.ref.kind == "ephemeral" and b1.ref.id == ""
    assert b2.ref == Ref("chunk", "c-1", "t-1")
    assert b1.tokens == int((70 + 16) / 3.5) + 1
    assert b2.messages == [] and view.render() == [{"role": "system", "content": "x" * 70}]
    assert [b.block_id for b in view.blocks] == ["b1", "b2"]
