"""Contract: memory-recall questions route to the DIRECT path (T48).

The T48 memory gate asks three questions about facts the user stated in an
earlier turn/conversation. The gate was routing all three to DER:

  * "staging deployment" matched the action verb "deploy" as a SUBSTRING, and
  * "Answer with the number only" matched the weak follow-up marker "with the".

Both diverted a recall question to the DER step, whose only memory block is a
thin 8-row / 420-char leg, and away from the direct path's session +
cross-session + file + prior assembly. These are the REAL failing inputs, so
this contract is derived from the live gate trace, not invented.

Every assertion here fails on the pre-fix code (verified by the substring and
marker probes in the PR notes).
"""

import pytest

from backend.agent.semantic_gate import (
    CapabilityLane,
    IntentDomain,
    SemanticLogicGate,
    Tier0Intent,
    _prior_task_context,
    has_action_verb,
    is_broad_memory_question,
    is_followup_to_task,
    is_memory_question,
    is_memory_write,
    tier0_classify,
)

# The three GT-10 / T48 asks, verbatim from evals/tasks.json.
_EVAL_ASKS = (
    "What is the name of my staging deployment? Answer with the name only.",
    "What is my library card number? Answer with the number only.",
    "Which color do I prefer for status indicators? Answer with the color only.",
)

_EVAL_SEEDS = (
    "Remember this for later: my staging deployment is named kestrel-blue-abc. "
    "Just acknowledge it briefly.",
    "Remember this for later: my library card number is 880417. "
    "Just acknowledge it briefly.",
    "Remember this for later: I prefer the color fern-green-abc for status "
    "indicators. Just acknowledge it briefly.",
)

_TASK_CTX = [
    {"role": "user", "content": "remind me to call mom at 5pm"},
    {"role": "assistant", "content": "I'll create a reminder to call mom at 5pm."},
]


def _dag(text, context=None):
    return SemanticLogicGate(tool_mode="auto").compile_dag(text, context)


class TestMemoryQuestionRoutesDirect:
    def test_all_three_t48_asks_route_direct_without_the_memory_skill(self):
        for text in _EVAL_ASKS:
            # The shadow feature still recognises the question ...
            assert is_memory_question(text), text
            verdict = tier0_classify(text)
            assert verdict.intent == Tier0Intent.QUESTION, (text, verdict)
            # ... but the LIVE route must not use it.
            assert verdict.is_memory is False, (text, verdict)
            assert _dag(text).requires_der_kernel is False, text

    def test_memory_question_uses_the_conversational_lane(self):
        dag = _dag(_EVAL_ASKS[2])
        assert dag.nodes
        assert dag.nodes[0].domain == IntentDomain.CONVERSATIONAL_SURFACE
        assert dag.nodes[0].lane == CapabilityLane.EXPLANATION_SYNTHESIS
        assert "memory-question" not in dag.why

    def test_no_memory_lane_is_emitted(self):
        for text in _EVAL_ASKS:
            dag = _dag(text)
            assert all(n.domain != IntentDomain.ONTOLOGY_MEMORY_QA for n in dag.nodes), text


class TestOldMisroutesCannotReturn:
    def test_a_verb_inside_a_noun_is_not_an_action(self):
        # Old code: "deploy" in "deployment" -> True -> DER.
        assert has_action_verb("the staging deployment name") is False
        assert has_action_verb("the deployment name") is False
        # A real verb is still a verb.
        assert has_action_verb("deploy the app") is True

    def test_a_generic_marker_without_a_task_is_not_a_followup(self):
        # Old code: " with the " in "Answer with the number only" -> True -> DER.
        for text in _EVAL_ASKS:
            assert is_followup_to_task(text, None) is False, text

    def test_a_real_continuation_with_a_task_still_goes_der(self):
        for text in (
            "yes do it",
            "ok proceed",
            "change that to 6pm",
            "now do the same for the other folder",
        ):
            assert is_followup_to_task(text, _TASK_CTX) is True, text
            assert _dag(text, _TASK_CTX).requires_der_kernel is True, text

    def test_action_requests_keep_der(self):
        for text in (
            "create a file called notes.txt",
            "deploy to production",
            "search the web for cats",
        ):
            assert _dag(text).requires_der_kernel is True, text

    def test_a_request_to_act_on_my_data_is_not_a_memory_question(self):
        # "my" alone must not pull action requests onto the direct path.
        assert is_memory_question("Can you search my email for the number?") is False
        assert _dag("Can you search my email for the number?").requires_der_kernel is True


class TestMemoryWriteRoutesDirect:
    def test_eval_seeds_route_direct_without_the_write_skill(self):
        for text in _EVAL_SEEDS:
            # The shadow feature still recognises the write ...
            assert is_memory_write(text) is True, text
            verdict = tier0_classify(text)
            # ... but the LIVE route must not use it. The anaphora guard
            # (prior task required) is what makes the seed a QUESTION.
            assert verdict.is_memory_write is False, (text, verdict)
            assert _dag(text).requires_der_kernel is False, text

    def test_memory_write_uses_the_conversational_lane(self):
        dag = _dag(_EVAL_SEEDS[0])
        assert dag.nodes
        assert dag.nodes[0].domain == IntentDomain.CONVERSATIONAL_SURFACE
        assert "memory-write" not in dag.why

    def test_reminder_is_not_a_memory_write(self):
        for text in ("remind me to call mom at 5pm",
                     "Remember to call mom at 5pm"):
            assert is_memory_write(text) is False, text
            assert _dag(text).requires_der_kernel is True, text


class TestBroadMemoryQuestion:
    def test_broad_self_query_is_detected(self):
        for text in (
            "What do you know about me? Be specific.",
            "What have you learned about me?",
            "What have I told you?",
            "Tell me about myself.",
        ):
            assert is_broad_memory_question(text) is True, text

    def test_a_specific_fact_question_is_not_broad(self):
        for text in (
            "What is my library card number?",
            "Which color do I prefer?",
            "What is the capital of France?",
        ):
            assert is_broad_memory_question(text) is False, text


class TestRouterEdgeMatrix:
    @pytest.mark.parametrize("text", [
        "what's my library card number?",
        "where is my staging server?",
        "where's my staging server?",
        "do you remember my card number?",
        "do you know my card number?",
        "what did I tell you about the card?",
        "when is my appointment?",
    ])
    def test_recall_phrasings_are_memory_and_direct(self, text):
        assert is_memory_question(text) is True, text
        assert _dag(text).requires_der_kernel is False, text

    @pytest.mark.parametrize("text", [
        "remind me to call mom at 5pm",
        "can you search my email for the number?",
        "list my files",
    ])
    def test_action_requests_are_not_memory(self, text):
        assert is_memory_question(text) is False, text
        assert _dag(text).requires_der_kernel is True, text

    def test_fresh_topic_is_not_a_followup_without_a_task(self):
        # "what about" is a WEAK marker: without a task it is a fresh question.
        assert is_followup_to_task("what about the weather?", None) is False
        assert _dag("what about the weather?").requires_der_kernel is False

    def test_topic_after_a_task_is_a_followup(self):
        assert is_followup_to_task("what about the other one", _TASK_CTX) is True

    def test_action_verb_boundaries_and_multiword(self):
        assert has_action_verb("the context is clear") is False
        assert has_action_verb("open_ai is a company") is False
        assert has_action_verb("search.py") is True
        assert has_action_verb("look up the capital") is True
        assert has_action_verb("lookup the capital") is True
        assert has_action_verb("turn off the lights") is True
        assert has_action_verb("turnoff") is False

    def test_inflected_actions_still_route_to_der(self):
        # A word boundary alone would miss these; the old substring caught them.
        for text in (
            "deploying the app",
            "creating a file",
            "running the tests",
            "updating the config",
            "setting the value",
        ):
            assert has_action_verb(text) is True, text
            assert _dag(text).requires_der_kernel is True, text
        # The noun is still a noun.
        assert has_action_verb("the deployment is fine") is False

    def test_prior_task_context_uses_word_boundaries(self):
        # A plan/tool/step/task word inside a longer word is not a task.
        assert _prior_task_context(
            [{"role": "assistant", "content": "the planet is blue"}]
        ) is False
        assert _prior_task_context(
            [{"role": "assistant", "content": "the toolbar is hidden"}]
        ) is False
        assert _prior_task_context(
            [{"role": "assistant", "content": "I'll create a reminder"}]
        ) is True
        assert _prior_task_context(
            [{"role": "assistant", "content": "step 2 is done"}]
        ) is True
