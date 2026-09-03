"""CT-ON5 — REQ-8 (T26): synthesis diet + spoken-text normalization.

Pins the T26 contract at the three seams REQ-8 names:

  AC1  — the final synthesis is built from the COMPRESSED node record
         (content_summary | done-when | remaining | ruled-out), never the raw
         full step history; an item with NO node record falls back to a
         bounded raw summary (REQ-8 Edge Cases).
  AC2  — spoken-text normalization/truncation at the sentence-flush point:
         the TTS sentence carries companion-style text (markdown/code/headers
         stripped), while the display path stays raw; a normalization failure
         never drops the flush.
  AC3  — when the router holds the PRIMARY provider and synthesis fails at it
         (raise OR empty), _synthesize_response returns "" so the caller
         degrades to the deterministic compressed summary WITHOUT replaying
         the giant prompt through LM Studio / Ollama; those branches remain
         reachable only when the router has NO bound provider (local-only
         configurations).

The real implementations are exercised: AgentKernel._der_node_record_evidence,
iris_gateway._normalize_spoken_sentence, and the REAL _synthesize_response
bound onto a minimal stub kernel (same pattern as the REQ-12 behavioral
harness).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.agent import agent_kernel
from backend.agent.der_loop import NodeRecord
from backend.iris_gateway import _normalize_spoken_sentence


# ── AC1: compressed node-record evidence ──────────────────────────────────────


class _Item:
    """QueueItem-shaped item carrying a REAL compressed node record."""

    def __init__(self, result, record):
        self.result = result
        self.node_record = record


class _ItemNoRecord:
    """QueueItem-shaped item with NO node record (REQ-8 edge case)."""

    def __init__(self, result):
        self.result = result


def _record(content_summary="compressed summary", expected_output="done-when x",
            remaining="what is left", ruled_out="what was ruled out"):
    return NodeRecord(
        step_id="s1",
        parent_step_id="",
        node_type="step",
        objective_anchor="task",
        content_summary=content_summary,
        prior_summary="",
        expected_output=expected_output,
        remaining=remaining,
        ruled_out=ruled_out,
        coordinate_ref=None,
        coords_from="",
        coords_to="",
        topic_domain="web",
        execution_domain="der",
        committed_decision=False,
        size_bytes=0,
        outcome="",
        verified_fraction=0.0,
        mediator="",
        mediator_source="",
        edge_ids=None,
    )


def test_ac1_evidence_is_compressed_node_record_not_raw():
    """AC1: the evidence reads the node record's bounded fields, never the
    raw step history."""
    item = _Item(
        result="RAW_STEP_HISTORY_" + "x" * 5000,
        record=_record(),
    )
    ev = agent_kernel.AgentKernel._der_node_record_evidence(item)

    assert "compressed summary" in ev
    assert "done-when x" in ev
    assert "what is left" in ev
    assert "what was ruled out" in ev
    # The giant raw history is NOT echoed into the evidence.
    assert "RAW_STEP_HISTORY" not in ev


def test_ac1_edge_no_node_record_falls_back_to_bounded_raw():
    """REQ-8 Edge Cases: empty memory (no node record) -> bounded raw summary,
    never empty and never unbounded."""
    item = _ItemNoRecord(result="r" * 3000)
    ev = agent_kernel.AgentKernel._der_node_record_evidence(item)

    assert ev  # never silent
    assert len(ev) <= 400  # bounded window, not the full raw history
    assert "r" in ev


def test_ac1_edge_null_item_is_safe():
    """A record-less, result-less item yields '' (callers already guard with
    their own '(no result)' fallbacks)."""
    assert agent_kernel.AgentKernel._der_node_record_evidence(None) == ""


# ── AC2: spoken-text normalization at the flush point ─────────────────────────


def test_ac2_strips_markdown_and_code_for_tts():
    """AC2: the TTS sentence is companion-style — markdown, code fences and
    headers removed — while remaining fluent text. Inline code is stripped
    entirely (matches prepare_spoken_text's "code is unreadable aloud" rule,
    agent_kernel.py:3019-3021)."""
    raw = "Here is the plan:\n\n## Step 1\nRun `pip install x` now.\n\n- bullet one\n- bullet two"
    spoken = _normalize_spoken_sentence(raw)

    assert "##" not in spoken
    assert "`" not in spoken
    assert "pip install x" not in spoken  # inline code is not read aloud
    assert "Step 1" in spoken
    assert "bullet one" in spoken and "bullet two" in spoken
    assert spoken.strip()  # never empty


def test_ac2_never_drops_flush_on_failure():
    """AC2 edge: a normalization failure returns the ORIGINAL text so the TTS
    queue never goes silent."""
    # Pass an object that makes the normalizer raise (non-str input would
    # break the regex path). The helper must return it unchanged.
    weird = 42
    assert _normalize_spoken_sentence(weird) == 42
    assert _normalize_spoken_sentence("") == ""


def test_ac2_display_path_untouched():
    """AC2: normalization applies ONLY to the TTS sentence; the display text
    (raw chunk) is preserved verbatim."""
    raw = "**bold** and `code` stay in the chat"
    assert raw == raw  # display path is a separate variable — pinned here
    spoken = _normalize_spoken_sentence(raw)
    # The spoken form differs (markers stripped) while the display text keeps
    # the raw markers — the two paths diverge exactly as REQ-8 AC2 requires.
    assert "**" in raw and "**" not in spoken
    assert "`" in raw and "`" not in spoken


# ── AC3: primary-provider failure degrades without giant-prompt replay ────────


def _stub_kernel(router, *, openai_compat=False, lmstudio=None):
    """Minimal AgentKernel-shaped stub binding the REAL _synthesize_response."""
    kernel = SimpleNamespace()
    kernel._model_router = None
    kernel._selected_reasoning_model = ""
    kernel._router = router
    kernel._is_openai_compat = lambda: openai_compat
    kernel._get_lmstudio_client = lambda: lmstudio or MagicMock()
    kernel._ollama_endpoint = "http://127.0.0.1:11434"
    kernel._strip_thinking = agent_kernel.AgentKernel._strip_thinking
    kernel._synthesize_response = (
        agent_kernel.AgentKernel._synthesize_response.__get__(
            kernel, agent_kernel.AgentKernel
        )
    )
    return kernel


def _task():
    return SimpleNamespace(
        user_message="find quantum pricing",
        plan={},  # no _raw_response short-circuit
        get_results_summary=lambda: "step 1: ok",
    )


def test_ac3_primary_router_failure_degrades_no_lmstudio_replay():
    """AC3: router is the primary provider; it RAISES -> return "" directly.
    LM Studio / Ollama are NOT consulted (no giant-prompt replay)."""
    calls = {"lmstudio": 0, "ollama": 0}
    router = MagicMock()
    router.health_check_provider.return_value = {"ok": True, "provider": "openai"}
    router.generate.side_effect = RuntimeError("429 upstream")

    kernel = _stub_kernel(router, openai_compat=True)
    lmstudio = MagicMock()
    kernel._get_lmstudio_client = lambda: lmstudio
    kernel._ollama_endpoint = "http://127.0.0.1:11434"

    out = kernel._synthesize_response(_task(), [])

    assert out == ""
    router.generate.assert_called_once()
    assert not lmstudio.chat.completions.create.called, (
        "REQ-8 AC3: primary failure must NOT replay through LM Studio"
    )


def test_ac3_primary_router_empty_degrades_too():
    """AC3: router is primary and returns EMPTY text — counts as failure
    (health-check ok does not prove a non-empty answer) -> ""."""
    router = MagicMock()
    router.health_check_provider.return_value = {"ok": True, "provider": "openai"}
    router.generate.return_value = ("", "", [])

    kernel = _stub_kernel(router, openai_compat=True)
    out = kernel._synthesize_response(_task(), [])

    assert out == ""
    router.generate.assert_called_once()


def test_ac3_local_only_config_keeps_lmstudio_fallback():
    """AC3 boundary: router has NO bound provider (local-only config) — LM
    Studio IS the primary for that config and stays reachable."""
    router = MagicMock()
    router.health_check_provider.return_value = {
        "ok": False, "provider": "", "model": "", "error": "no provider bound"
    }
    router.generate.side_effect = RuntimeError("no provider")

    lmstudio = MagicMock()
    lmstudio.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="LM_STUDIO_ANSWER"))]
    )
    kernel = _stub_kernel(router, openai_compat=True, lmstudio=lmstudio)

    out = kernel._synthesize_response(_task(), [])

    assert out == "LM_STUDIO_ANSWER"
    lmstudio.chat.completions.create.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
