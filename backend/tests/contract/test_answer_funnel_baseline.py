"""BASELINE — Wave 0, specs/task-card-v2-liquid-ink.

Originally pinned behavior as of 2026-08-19, including the funnel-bypass
defect: the gateway's `question_response` branch called
`tool.receive_answer(...)` DIRECTLY instead of `resolve_answer(...)`, so a
card click never resumed a parked source the way a voice answer did.

INVERTED BY T3 (2026-08-19). T3 changed `iris_gateway.py`'s
`question_response` branch to call `resolve_answer(...)` — the SAME single
funnel `resolve_via_voice` already used — so a card click now resumes a
parked source exactly like voice does. This file is updated (the one
sanctioned edit for T3) to assert the FIXED behavior instead of the
defect. `test_direct_receive_answer_does_not_resume_parked_source` is kept
because it still describes true, current behavior: `receive_answer` in
isolation (bypassing the funnel on purpose) never touches the
ParkedSourceRegistry — that is exactly why the gateway must call
`resolve_answer`, not `receive_answer`, and this test now documents the
contrast rather than the live defect.

Targets:
  - backend/agent/tools/ask_user_tool.py — `resolve_answer` is the documented
    single funnel (receive_answer + ParkedSourceRegistry.resume); voice
    reaches it via `resolve_via_voice`, and (as of T3) so does the gateway's
    card-click path.
  - backend/iris_gateway.py (~line 5391) — the `question_response` branch
    now calls `tool.resolve_answer(...)`, not `receive_answer(...)`
    directly, so a card click resumes a parked source (T3 / REQ-6).

Inverted by: T3 (landed)
"""

from __future__ import annotations

import ast
import os
import re

import pytest

from backend.agent.tools import ask_user_tool as _aut


# ── Isolation ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset the AskUserTool + ParkedSourceRegistry singletons per test so
    pending questions / parked sources never leak across tests."""
    _aut.reset_ask_user_tool_for_testing()
    _aut.reset_parked_source_registry_for_testing()
    yield
    _aut.reset_ask_user_tool_for_testing()
    _aut.reset_parked_source_registry_for_testing()


# ── 1. Voice resumes a parked source ────────────────────────────────────

def test_voice_answer_resumes_parked_source():
    """resolve_via_voice -> resolve_answer -> registry.resume(): the SINGLE
    funnel that both voice and card clicks share (as of T3). Voice uses it
    directly here."""
    tool = _aut.get_ask_user_tool()
    registry = _aut.get_parked_source_registry()

    question = tool.ask_non_blocking(
        text="Which result should I use?",
        options=["yes", "no"],
        turn_id="session-voice",
        run_id="run-voice",
        parked_url="https://example.com/blocked-page",
        wall_kind="captcha",
    )

    # Parked as a side effect of ask_non_blocking(parked_url=...).
    parked = registry.get(question.question_id)
    assert parked is not None
    assert parked.status == "parked"

    result = tool.resolve_via_voice("yes", "session-voice")

    assert result == {"handled": True, "resolved": "yes"}
    # The parked source was popped and marked resumed by the funnel.
    assert registry.get(question.question_id) is None


# ── 2. Direct receive_answer (bypassing the funnel) does NOT resume ────

def test_direct_receive_answer_does_not_resume_parked_source():
    """A caller that answers via `receive_answer` directly — bypassing
    `resolve_answer` on purpose — never touches the ParkedSourceRegistry.
    This is exactly why the gateway must route through `resolve_answer`
    (T3): calling `receive_answer` directly is still the wrong thing to do,
    even though (post-T3) nothing in production does it anymore."""
    tool = _aut.get_ask_user_tool()
    registry = _aut.get_parked_source_registry()

    question = tool.ask_non_blocking(
        text="Which result should I use?",
        options=["yes", "no"],
        turn_id="session-click",
        run_id="run-click",
        parked_url="https://example.com/other-blocked-page",
        wall_kind="login",
    )
    parked = registry.get(question.question_id)
    assert parked is not None

    answered = tool.receive_answer(question.question_id, "yes")

    assert answered is not None
    assert answered.status == "answered"
    # receive_answer alone never calls registry.resume() — that is the
    # funnel's job. Still parked here confirms resolve_answer is doing
    # real work, not just delegating.
    still_parked = registry.get(question.question_id)
    assert still_parked is not None
    assert still_parked.status == "parked"


# ── 2b. A card click (i.e. resolve_answer, what the gateway now calls)
#        DOES resume a parked source — the fix T3 makes ────────────────

def test_card_click_now_resumes_parked_source():
    """Simulates the gateway's `question_response` branch post-T3: it calls
    `tool.resolve_answer(question_id, answer)` (see
    test_gateway_question_response_uses_funnel below for proof the gateway
    source does exactly that). Resolving through the funnel resumes the
    parked source — the defect this baseline used to pin is fixed."""
    tool = _aut.get_ask_user_tool()
    registry = _aut.get_parked_source_registry()

    question = tool.ask_non_blocking(
        text="Which result should I use?",
        options=["yes", "no"],
        turn_id="session-click",
        run_id="run-click-2",
        parked_url="https://example.com/click-blocked-page",
        wall_kind="login",
    )
    parked = registry.get(question.question_id)
    assert parked is not None
    assert parked.status == "parked"

    # This is the call the gateway's question_response branch makes.
    answered = tool.resolve_answer(question.question_id, "yes")

    assert answered is not None
    assert answered.status == "answered"
    assert answered.answer == "yes"
    # FIXED: the source was resumed (popped from the registry) by the
    # funnel, exactly like the voice path in test 1 above.
    assert registry.get(question.question_id) is None


# ── 3. The gateway uses the funnel ──────────────────────────────────────
#
# Preferred: drive the gateway's `question_response` branch (with
# ask_user_tool patched) and assert resolve_answer was called and
# receive_answer does not appear directly in the branch. `IRISGateway.__init__`
# is not independently constructible in a unit test — it stands up wake-word
# audio discovery (`WakeWordDiscovery().scan_directory()`), a vision provider
# that dials a local llama-server, a WSEventBridge thread, and session GC
# machinery, none of which is mockable without effectively rebuilding the
# gateway. Falling back to the AST assertion the spec names as the fallback:
# parse iris_gateway.py, locate the `elif msg_type == "question_response":`
# branch inside handle_message, and assert the attribute call is
# `resolve_answer` and `receive_answer` does not appear in it directly.

# backend/agent/tools/ask_user_tool.py -> backend/iris_gateway.py
_GATEWAY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(_aut.__file__)))),
    "iris_gateway.py",
)


def _find_question_response_branch(tree: ast.AST) -> ast.If:
    """Find the `if/elif msg_type == "question_response":` node.

    The gateway represents `elif` as the `orelse` of the previous `If`, so
    walk every `If` node (at any depth) rather than assuming a flat list.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "msg_type"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "question_response"
        ):
            return node
    raise AssertionError(
        "Could not locate `elif msg_type == \"question_response\":` in "
        f"{_GATEWAY_PATH} — has the branch been renamed/restructured?"
    )


def _attribute_call_names(node: ast.AST) -> set[str]:
    """All `<obj>.<name>(...)` call attribute names anywhere under node."""
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            names.add(sub.func.attr)
    return names


def test_gateway_question_response_uses_funnel():
    with open(_GATEWAY_PATH, "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=_GATEWAY_PATH)

    branch = _find_question_response_branch(tree)
    called = _attribute_call_names(branch)

    # FIXED (T3): the gateway routes through the single funnel...
    assert "resolve_answer" in called
    # ...and no longer calls receive_answer directly in this branch
    # (resolve_answer calls it internally, inside ask_user_tool.py — that
    # nested call is not part of THIS branch's source text).
    assert "receive_answer" not in called


def test_gateway_question_response_line_reference_still_matches():
    """Secondary guard: pin the exact funnel call text at the location the
    spec names (iris_gateway.py ~5391-5399), so a future refactor that
    moves the call without renaming it still trips this baseline."""
    with open(_GATEWAY_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    branch_start = None
    for i, line in enumerate(lines):
        if re.search(r'elif msg_type == "question_response":', line):
            branch_start = i
            break
    assert branch_start is not None, "question_response branch not found"

    window = "".join(lines[branch_start:branch_start + 25])
    assert "tool.resolve_answer(question_id, answer)" in window
    assert "tool.receive_answer(question_id, answer)" not in window


# ── 4. First-wins: a second answer to the same question is a no-op ─────

def test_receive_answer_first_wins():
    """`receive_answer` pops from `_pending`, so the second caller to answer
    the same question_id gets None — first answer wins, matches
    resolve_answer's documented CT-4 first-wins contract (REQ-14 AC5)."""
    tool = _aut.get_ask_user_tool()

    question = tool.ask(text="Pick one", options=["x", "y"], turn_id="t-first-wins")

    first = tool.receive_answer(question.question_id, "x")
    assert first is not None
    assert first.answer == "x"
    assert first.status == "answered"

    second = tool.receive_answer(question.question_id, "y")
    assert second is None


def test_resolve_answer_first_wins():
    """Same first-wins guarantee through the actual funnel (what the
    gateway now calls), not just the lower-level receive_answer."""
    tool = _aut.get_ask_user_tool()

    question = tool.ask(text="Pick one", options=["x", "y"], turn_id="t-first-wins-2")

    first = tool.resolve_answer(question.question_id, "x")
    assert first is not None
    assert first.answer == "x"

    second = tool.resolve_answer(question.question_id, "y")
    assert second is None
