"""
Contract tests for the T36 web-mode / DER gate fixes (2026-08-09).

Two layered defects found during the T36 live smoke re-run (turn
114d95a3-6f1, 16:57): the user asked "what are the latest NASA Mars rover
discoveries this month?" with web mode ON, the frontend stripped the
"websearch:" prefix, the text heuristic missed it, and the DER-skip gate
treated the turn as chit-chat — DER never ran and the blind fallback
returned "IRIS couldn't generate a response. Please try again."

Defect 1 — the DER-skip gate ignored the internet-access toggle.
  Contract: web mode ON + a factual/informational question must NOT skip
  DER (crawler path must stay available) even when the explicit-search
  heuristic misses; chit-chat still skips DER regardless of web mode.

Defect 2 — the empty-DER fallback was blind.
  Contract: the fallback is AWARE — it surfaces a real upstream error,
  advises the web-mode toggle when the turn clearly wanted a search, or
  gives neutral rephrase guidance. It never returns the old blind
  "couldn't generate" message (which must never reach chat content).

Tests pin the extracted decision boundaries (_should_skip_der and
_empty_der_fallback_message) — the same methods the real
process_text_message path calls — not mocks of the pipeline.

Run: python -m pytest backend/tests/contract/test_t36_web_mode_der_contract.py -v
"""

import pytest

from backend.agent.agent_kernel import AgentKernel

# The exact factual question from the failed live smoke turn (prefix
# stripped by the frontend, so no explicit web-search phrase remains).
NASA_QUESTION = "what are the latest NASA Mars rover discoveries this month?"


def _agent():
    return AgentKernel.__new__(AgentKernel)


class _Step:
    def __init__(self, tool):
        self.tool = tool


def _speak_only_steps(n=2):
    return [_Step("speak") for _ in range(n)]


def _mixed_steps():
    return [_Step("speak"), _Step("crawler_query")]


# ─────────────────────────────────────────────
# DEFECT 1 — DER-skip gate consults web mode
# ─────────────────────────────────────────────

class TestShouldSkipDerGate:
    def test_empty_plan_always_skips(self):
        assert _agent()._should_skip_der([], NASA_QUESTION, web_on=True) is True
        assert _agent()._should_skip_der([], NASA_QUESTION, web_on=False) is True

    def test_explicit_websearch_never_skips(self):
        # Explicit search phrase → DER must run even with web OFF
        # (existing behavior preserved).
        assert (
            _agent()._should_skip_der(
                _speak_only_steps(), "web search for Python", web_on=False
            )
            is False
        )

    def test_non_voice_plan_never_skips(self):
        # A plan with a real tool step (crawler etc.) always goes to DER.
        assert (
            _agent()._should_skip_der(_mixed_steps(), NASA_QUESTION, web_on=True)
            is False
        )
        assert (
            _agent()._should_skip_der(_mixed_steps(), "hello", web_on=False)
            is False
        )

    def test_chit_chat_skips_regardless_of_web_mode(self):
        # T36 fix must NOT force chit-chat through DER when web mode is ON.
        assert (
            _agent()._should_skip_der(_speak_only_steps(), "hello", web_on=False)
            is True
        )
        assert (
            _agent()._should_skip_der(_speak_only_steps(), "hello", web_on=True)
            is True
        )
        assert (
            _agent()._should_skip_der(_speak_only_steps(), "how are you", web_on=True)
            is True
        )

    def test_informational_question_web_off_skips(self):
        # Prefix-stripped factual question + web OFF → heuristic misses,
        # no web path needed → fast path is fine.
        assert (
            _agent()._should_skip_der(_speak_only_steps(), NASA_QUESTION, web_on=False)
            is True
        )

    def test_informational_question_web_on_forces_der(self):
        # THE T36 DEFECT: prefix-stripped factual question + web ON must
        # reach DER so the crawler path stays available. This was the exact
        # live failure (agent returned the blind error instead of searching).
        assert (
            _agent()._should_skip_der(_speak_only_steps(), NASA_QUESTION, web_on=True)
            is False
        )


class TestLooksInformational:
    def test_factual_question_forms_match(self):
        a = _agent()
        assert a._looks_informational(NASA_QUESTION) is True
        assert a._looks_informational("what is the weather like") is True
        assert a._looks_informational("who won last night's game") is True
        assert a._looks_informational("latest news on the election") is True
        assert a._looks_informational("how many people live in Tokyo") is True

    def test_chit_chat_does_not_match(self):
        a = _agent()
        assert a._looks_informational("hello") is False
        assert a._looks_informational("how are you") is False
        assert a._looks_informational("tell me a joke") is False
        assert a._looks_informational("thanks") is False
        assert a._looks_informational("") is False


# ─────────────────────────────────────────────
# DEFECT 2 — aware empty-DER fallback
# ─────────────────────────────────────────────

class TestEmptyDerFallback:
    def test_never_blind_generic(self):
        """The old blind message must never be produced by any branch."""
        a = _agent()
        for text, web_on, err in [
            ("hello", False, ""),
            ("hello", True, ""),
            (NASA_QUESTION, False, ""),
            (NASA_QUESTION, True, ""),
            ("web search for X", True, ""),
            ("anything", True, "boom"),
        ]:
            msg = a._empty_der_fallback_message(text, web_on=web_on, der_err_text=err)
            assert "couldn't generate" not in msg.lower(), (
                f"blind message leaked for text={text!r} web_on={web_on} err={err!r}"
            )

    def test_surfaces_real_upstream_error(self):
        msg = _agent()._empty_der_fallback_message(
            "anything", web_on=True, der_err_text="rate limit exceeded"
        )
        assert "rate limit exceeded" in msg
        assert "try again" in msg

    def test_search_intent_web_off_advises_toggle(self):
        # Web OFF + searchy turn → advise the dashboard toggle (same wording
        # as the Gate-A advisory) instead of a blind error.
        msg = _agent()._empty_der_fallback_message(
            "web search for Mars rover news", web_on=False
        )
        assert "Web search is currently disabled" in msg
        assert "toggle internet access" in msg
        assert "web button" in msg

    def test_search_intent_web_off_informational_advises_toggle(self):
        # Prefix-stripped factual question + web OFF + DER still failed →
        # must advise the toggle, not error blindly.
        msg = _agent()._empty_der_fallback_message(NASA_QUESTION, web_on=False)
        assert "Web search is currently disabled" in msg

    def test_search_intent_web_on_is_honest(self):
        # Web ON + searchy turn but DER came back empty → honest incomplete-
        # search message, not silence and not a toggle advisory.
        msg = _agent()._empty_der_fallback_message(NASA_QUESTION, web_on=True)
        assert "couldn't complete the web search" in msg
        assert "try again" in msg

    def test_plain_failure_gives_rephrase_guidance(self):
        msg = _agent()._empty_der_fallback_message("hello", web_on=True)
        assert "rephrase" in msg
        assert "Web search" not in msg
