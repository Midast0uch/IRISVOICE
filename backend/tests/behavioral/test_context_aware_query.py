"""
Tests for Phase 2.2 — context-aware query refinement.

Run: python -m pytest backend/tests/test_context_aware_query.py -v
"""

from unittest.mock import patch, MagicMock

from backend.agent.agent_kernel import AgentKernel


def _make_kernel():
    from backend.agent.agent_kernel import AgentKernel

    with patch.object(AgentKernel, "__init__", lambda self, *a, **kw: None):
        k = AgentKernel.__new__(AgentKernel)
    return k


class _InferResult:
    def __init__(self, raw_text):
        self.raw_text = raw_text


def test_query_has_reference_detects_pronouns():
    for q in [
        "what is the pricing of the plan",
        "search for it",
        "the same file we opened earlier",
        "what we found before",
        "the cost of that service",
        "summarize the above",
    ]:
        assert AgentKernel._der_query_has_reference(q) is True, f"'{q}' has a reference"


def test_query_has_reference_false_for_clean_query():
    for q in [
        "search for the latest news on AI",
        "find restaurants near me",
        "open chrome",
        "what is the capital of France",
    ]:
        assert AgentKernel._der_query_has_reference(q) is False, f"'{q}' is clean"


def test_refine_query_resolves_against_history():
    k = _make_kernel()
    k._conversation_memory = MagicMock()
    k._conversation_memory.get_context.return_value = [
        {"role": "user", "content": "find the Acme pricing page"},
        {"role": "assistant", "content": "opened https://acme.example/pricing"},
    ]
    k.infer = MagicMock(
        return_value=_InferResult("the pricing of the Acme plan at acme.example/pricing")
    )
    out = k._der_refine_query("what is the pricing of the plan", "sess")
    assert "Acme" in out
    assert out.lower() != "what is the pricing of the plan"


def test_refine_query_no_history_returns_original():
    k = _make_kernel()
    k._conversation_memory = MagicMock()
    k._conversation_memory.get_context.return_value = []
    k.infer = MagicMock()  # should not be called
    out = k._der_refine_query("search for cats", "sess")
    assert out == "search for cats"
    k.infer.assert_not_called()


def test_refine_query_failure_returns_original():
    k = _make_kernel()
    k._conversation_memory = MagicMock()
    k._conversation_memory.get_context.return_value = [{"role": "user", "content": "x"}]
    k.infer = MagicMock(side_effect=RuntimeError("model down"))
    out = k._der_refine_query("the pricing of the plan", "sess")
    assert out == "the pricing of the plan"
