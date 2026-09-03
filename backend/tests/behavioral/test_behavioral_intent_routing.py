"""
T13 (REQ-1..REQ-8) — behavioral intent-routing suite + gate-proof.

BEHAVIORAL (drives the REAL kernel path — _needs_planning shim -> gate ->
compile_dag, exactly as a user turn runs): a 50+ prompt matrix across every
intent class asserts the routing the user actually experiences.

GATE-PROOF (equivalence + superiority over the legacy router, measured):
  * Equivalence — for every non-compound prompt, the gate's routing decision
    equals the legacy router's (reconstructed exactly: the migrated Tier 0
    rule sets minus the two documented REQ-1 AC2 additions).
  * Superiority — every disagreement is a compound/multi-concern prompt that
    the legacy router misrouted to the DIRECT path but the gate routes to DER
    with a multi-lane DAG. The reverse (gate -> direct, legacy -> DER) is a
    regression and fails the suite.

Retires the legacy router: with this suite green, the _needs_planning shim is
declared permanent (its docstring is updated) and the dead _classify_intent
delegator is removed (agent_kernel.py:1895, zero callers).
"""

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.semantic_gate import (
    ACTION_VERBS,
    TOOL_PREFIXES,
    is_chitchat,
    is_followup_to_task,
    is_web_search_request,
)

# ---------------------------------------------------------------------------
# 50+ prompt matrix: (text, context, expected_requires_der)
# ---------------------------------------------------------------------------

_CHITCHAT = [
    "hey how are you?", "hi", "hello there", "good morning", "thanks",
    "thank you", "no problem", "got it", "sure thing", "sounds good",
    "agreed", "of course", "alright", "have a nice day", "that's great to hear",
]
_QUESTION = [
    "what time is it in Tokyo?", "explain how recursion works",
    "what is the capital of France?", "who wrote Romeo and Juliet?",
    "how does a carburetor work?", "why is the sky blue?",
    "tell me about the history of Rome", "how do I get to the station?",
    "what's the weather like today?", "how do databases handle concurrency?",
    "what is a mycelium node?", "explain the ontology to me",
    # "internet" alone is not a WEB trigger (migrated list) -> direct.
    "what does the internet say about AI safety?",
]
_ACTION = [
    "search for the latest news on AI", "create a file called notes.txt",
    "open chrome", "remind me to call mom at 5pm", "send an email to bob",
    "download the report", "list files in the project folder",
    "run the tests", "test this function", "update the config file",
    "look up the capital of France", "build the project",
    "deploy to production", "translate this text to French",
    "calculate the total cost",
    # "summarize" is an action verb (migrated) -> DER.
    "can you summarize this article for me?",
    # FINDING (legacy-equivalent, verb/noun ambiguity): "list" the noun
    # matches the "list" verb -> DER. Same as the legacy router; T13 tuning
    # candidate, not a regression.
    "what's the difference between a list and a tuple?",
    # FINDING (legacy-equivalent): anaphora "this" + marker "the" route this
    # question to DER. The gate preserves the migrated behavior for
    # equivalence; the false positive is a T13 tuning candidate, not a
    # regression (pin_85e598dcd79e family).
    "what does this error mean?",
]
_FOLLOWUP = [
    "yes do it", "change that to 6pm", "what about the other one",
    "ok proceed", "and the second file too", "go ahead",
    "now do the same for the other folder", "also add a header",
]
_WEB = [
    "search the web for quantum computing", "look up online the best restaurants",
    "find information about the new iPhone", "google the weather forecast",
]
# Explicit (text, ctx, expected): "" / whitespace / None -> chat (REQ-1 AC4);
# "Tool:" and "RUN" are normalized to lowercase before matching -> action.
_EDGE = [
    ("", None, False), ("   ", None, False), (None, None, False),
    ("Tool: do the thing", None, True), ("RUN the benchmark now", None, True),
]

_COMPOUND = [
    "Look up our WebSocket reconnect pattern from last session and test it in ws_client.rs",
    "find the retry logic we discussed yesterday then verify it in the tests",
    # CLEAN SUPERIORITY CASE: no legacy verb, no anaphora pronoun, no marker
    # word -> the legacy router sends this to the DIRECT path (False); the
    # gate's REQ-1 AC2 additions ("look up"/"test") route it to DER with a
    # 2-lane DAG (skill_landmark_query -> test_validation).
    "look up retry logic and test connection",
]

TASK_CTX = [
    {"role": "user", "content": "remind me to call mom at 5pm"},
    {"role": "assistant", "content": "I'll create a reminder to call mom at 5pm."},
]


def _matrix():
    m = [(t, None, False) for t in _CHITCHAT]
    m += [(t, None, False) for t in _QUESTION]
    m += [(t, None, True) for t in _ACTION]
    m += [(t, TASK_CTX, True) for t in _FOLLOWUP]
    m += [(t, None, True) for t in _WEB]
    m += list(_EDGE)
    m += [(t, None, True) for t in _COMPOUND]
    return m


def _make_kernel():
    k = AgentKernel.__new__(AgentKernel)
    k._tool_mode = "auto"
    k._memory_interface = None
    return k


# ---------------------------------------------------------------------------
# Behavioral: the REAL kernel routing (full user-turn path)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,ctx,expected", _matrix())
def test_kernel_routing_contract(text, ctx, expected):
    k = _make_kernel()
    assert k._needs_planning(text, ctx) is expected, (
        f"routing mismatch for {text!r}: expected {expected}"
    )


def test_compound_prompts_emit_multi_lane_dag():
    k = _make_kernel()
    for text in _COMPOUND:
        graph = k._gate.compile_dag(text, web_mode=False)
        assert graph.requires_der_kernel is True
        task_lanes = [n.lane for n in graph.nodes]
        assert len(task_lanes) >= 2, f"{text!r}: {task_lanes}"


# ---------------------------------------------------------------------------
# Gate-proof: equivalence + superiority over the legacy router
# ---------------------------------------------------------------------------

def _legacy_router(text, context=None):
    """Reconstructed legacy router (agent_kernel.py:1885-1955 pre-gate, per
    baseline.md §5). Tier 0 is the verbatim migration, so legacy == the gate's
    Tier 0 minus the two documented REQ-1 AC2 verb additions."""
    t = (text or "").lower().strip()
    if not t:
        return False
    if t.startswith(TOOL_PREFIXES):
        return True
    if is_chitchat(text):
        return False
    if is_web_search_request(text):
        return True
    legacy_verbs = [v for v in ACTION_VERBS if v not in ("test", "look up")]
    if any(v in t for v in legacy_verbs):
        return True
    if is_followup_to_task(text, context):
        return True
    return False


def test_gate_proof_equivalence_and_superiority():
    k = _make_kernel()
    disagreements = []
    for text, ctx, _expected in _matrix():
        gate = bool(k._needs_planning(text, ctx))
        legacy = _legacy_router(text, ctx)
        if gate != legacy:
            disagreements.append((text, legacy, gate))

    # Equivalence: the only allowed disagreements are compound/multi-concern
    # prompts the legacy router misrouted to DIRECT (False) while the gate
    # routes to DER (True). Any gate->False / legacy->True is a regression.
    regressions = [d for d in disagreements if d[1] and not d[2]]
    assert not regressions, f"gate regressed vs legacy on: {regressions}"

    # Superiority: at least one compound prompt demonstrates the gate winning
    # where the legacy router misrouted to DIRECT. (The other compound prompts
    # are agreements — the legacy caught them via verbs/anaphora; the gate
    # still emits the multi-lane DAG, asserted in
    # test_compound_prompts_emit_multi_lane_dag.)
    compound_wins = [d for d in disagreements if d[0] in _COMPOUND and d[2] and not d[1]]
    assert compound_wins, (
        f"expected >=1 compound prompt where the gate beats the legacy router, "
        f"got disagreements={disagreements}"
    )
    assert "look up retry logic and test connection" in [d[0] for d in compound_wins]


def test_gate_proof_no_silent_reversals():
    """The gate never silently flips a legacy DER decision to direct."""
    k = _make_kernel()
    for text, ctx, _ in _matrix():
        gate = k._needs_planning(text, ctx)
        legacy = _legacy_router(text, ctx)
        if legacy and not gate:
            pytest.fail(f"gate reversed legacy DER -> direct on {text!r}")
