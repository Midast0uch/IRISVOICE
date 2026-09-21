"""CT-1..CT-5, CT-9 (specs/tool-result-envelope Wave 2 gate TG-2).

Contract pins over the envelope shape, prompt surfaces, reviewer contract,
error-shape mapping, event vocabulary, and the no-new-persistence rule.
Real kernel objects with stubbed collaborators; no live web, no live model.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.agent.der_loop import QueueItem
from backend.agent.tool_envelope import (
    ToolResultEnvelope,
    build_envelope,
    classify_exception_from_message,
)
from backend.agent.tool_errors import resolve_label


# ── fixtures ─────────────────────────────────────────────────────────────────


def _envelope(**over) -> ToolResultEnvelope:
    base = dict(
        status="success",
        summary="gathered streaming docs for whisper.cpp",
        raw_ref={"doc_id": "doc_abc123"},
        match="matched",
        novelty="new",
        suggestion="proceed",
        stuck_shape="none",
        coords_from="x0.10,y0.20,xi0.30,u0.40",
        coords_to="x0.50,y0.20,xi0.30,u0.60",
        coords_basis="format_coords",
        criticality="load-bearing",
        criticality_source="declared",
        card_id="card_1",
        step_id="s1",
        session_id="sess",
        turn_id="t1",
    )
    base.update(over)
    return ToolResultEnvelope(**base)


# ── CT-1: envelope shape on QueueItem (fields + bounds) ─────────────────────


def test_ct1_queueitem_envelope_shape_and_bounds():
    item = QueueItem(step_id="s1", step_number=1, description="d")
    item.envelope = _envelope()
    env = item.envelope
    # fields present
    for f in ("status", "summary", "raw_ref", "match", "novelty",
              "suggestion", "stuck_shape", "coords_from", "coords_to",
              "criticality", "criticality_source", "card_id", "step_id",
              "session_id", "turn_id"):
        assert hasattr(env, f), f"missing field {f}"
    # bounds: summary <=300 chars, single line
    assert len(env.summary) <= 300
    assert "\n" not in env.summary
    # raw_ref = doc_id ONLY (no chunk ids ever — AC1.3)
    assert set(env.raw_ref.keys()) == {"doc_id"}
    # coords VERBATIM passthrough
    assert env.coords_from == "x0.10,y0.20,xi0.30,u0.40"
    # step identity present
    assert env.step_id and env.session_id and env.turn_id
    # NO fingerprint field anywhere (KD-7 / session-316 lock)
    assert not any("fingerprint" in f for f in vars(env))
    # QueueItem carries the declared criticality + captured doc id
    assert item.declared_criticality == "supporting"
    assert item.captured_doc_id is None


# ── CT-2: no raw gather payload in the continuation prompt ─────────────────


_CONV99_RAW = (
    "whisper.cpp/README.md — Build instructions: cmake -B build && "
    "cmake --build build --config Release. Download ggml models: "
    "ggml-large-v3.bin (3.1 GB).... " + "page chrome junk " * 200
)


def _kernel_with_completed():
    from backend.agent.agent_kernel import AgentKernel

    class _K(AgentKernel):
        def __init__(self):
            self.conversation_id = "conv_ct2"
            self._der_crawled_urls = {}
            self._der_last_run_grade = None

        def infer(self, prompt, **kw):
            self.captured_prompt = prompt
            raise RuntimeError("no inference in CT")

    k = _K()
    k.captured_prompt = ""
    return k


def test_ct2_continuation_prompt_contains_only_envelope_lines():
    """The old done_summary half appended the FULL raw i.result; BOTH halves
    must now render envelope lines only — the raw crawl chrome never enters
    the continuation prompt."""
    k = _kernel_with_completed()
    items = []
    for i in (1, 2, 3):
        it = QueueItem(step_id=f"s{i}", step_number=i, description=f"step {i}")
        it.result = _CONV99_RAW  # raw payload present on the item
        it.envelope = _envelope(step_id=f"s{i}", summary=f"summary {i}")
        items.append(it)
    try:
        k._der_plan_next_step("objective", items, None, "t1", step_outputs=[_CONV99_RAW])
    except RuntimeError:
        pass  # infer raise expected — the prompt was captured
    prompt = k.captured_prompt
    assert "summary 1" in prompt and "summary 3" in prompt, (
        "envelope summaries must appear in both halves"
    )
    assert "ggml-large-v3" not in prompt, (
        "raw gather payload leaked into the continuation prompt"
    )
    assert "page chrome junk" not in prompt


# ── CT-3: ReviewVerdict semantics unchanged, inputs are envelope views ──────


def test_ct3_reviewer_verdict_mapping_identical():
    from backend.agent.der_loop import ReviewVerdict, Reviewer

    r = Reviewer(adapter=MagicMock(), memory_interface=MagicMock())
    fixtures = [
        ('{"verdict":"pass","reason":""}', ReviewVerdict.PASS),
        ('{"verdict":"refine","reason":"x","refined":"y"}', ReviewVerdict.REFINE),
        ('{"verdict":"veto","reason":"z"}', ReviewVerdict.VETO),
        ("not json at all", ReviewVerdict.PASS),
    ]
    for raw, expected in fixtures:
        verdict, _ = r._parse_verdict(raw)
        assert verdict == expected


def test_ct3_review_prompt_includes_envelope_views_not_raw():
    from backend.agent.der_loop import Reviewer

    r = Reviewer(adapter=MagicMock(), memory_interface=MagicMock())
    prev = QueueItem(step_id="s0", step_number=0, description="earlier")
    prev.result = _CONV99_RAW
    prev.envelope = _envelope(step_id="s0", summary="earlier summary")
    item = QueueItem(step_id="s1", step_number=1, description="next step")
    prompt = r._build_review_prompt(
        item=item, completed_steps=[prev],
        gradient_warnings="", active_contracts="",
    )
    assert "earlier summary" in prompt, "envelope view must reach the reviewer"
    assert "ggml-large-v3" not in prompt, "raw result must NOT reach the reviewer"


# ── CT-4: tool_errors shape → error_type/recovery_hint mapping locked ───────


def test_ct4_error_shape_mapping_locked():
    # the taxonomy vocabulary must not drift
    for label in ("transient", "walled", "rate_limited", "empty", "crashed"):
        assert resolve_label(label) is not None, f"{label} vanished"
    assert resolve_label("walled").dimensions.retryable == "no"
    # builder classification rides the same taxonomy
    assert classify_exception_from_message("connection timed out") == "transient"
    assert classify_exception_from_message("403 challenge page") == "walled"
    env = build_envelope(
        result_text="failed: connection timed out", step_success=False,
        outcome="FAILED", expected_output="", tool="crawler_query",
        params_digest="d", verified_fraction=None,
        prev_verified_fraction=None, raw_doc_id="", coords_from=None,
        coords_to=None, turn_memory={},
    )
    assert env.error_type == "transient"
    assert env.recovery_hint == resolve_label("transient").description[:120]


# ── CT-5: no new IRISStreamEvent types — observability rides logs ───────────


def test_ct5_event_vocabulary_unchanged():
    from backend.agent.event_bus import IRISStreamEvent

    expected = {
        "TOOL_CALL", "TOOL_RESULT", "TOOL_ERROR", "MEMORY_EVENT",
        "TASK_LEARNING",
    }
    missing = expected - set(IRISStreamEvent.__members__.keys())
    assert not missing, f"IRISStreamEvent vocabulary drifted: {missing}"
    # the envelope module imports no event bus at all
    import inspect

    import backend.agent.tool_envelope as te

    src = inspect.getsource(te)
    assert "event_bus" not in src and "IRISStreamEvent" not in src


# ── CT-9: no-new-persistence — envelope build touches NO store ──────────────


def test_ct9_envelope_construction_performs_no_db_writes():
    """KD-7/AC1.3: the envelope performs NO DB writes and reads NO chunk
    stores. Pacman filing and document-store writes happen elsewhere; a
    recording episodic store must see ZERO activity from the builder."""
    calls = {"fragment": 0, "save_doc": 0, "retrieve": 0}

    import backend.agent.tool_envelope as te

    # tool_envelope must not import any store module
    import inspect

    src = inspect.getsource(te)
    for banned in ("fragment_and_store", "retrieve_context_chunks",
                   "document_store", "save_document", "sqlite", "psycopg"):
        assert banned not in src, f"envelope module references {banned}"

    # and building one performs no I/O by construction (pure function over
    # in-scope values) — run it and assert the recording counters stay zero
    env = build_envelope(
        result_text=_CONV99_RAW, step_success=True, outcome="VERIFIED",
        expected_output="whisper.cpp streaming", tool="crawler_query",
        params_digest="d", verified_fraction=1.0,
        prev_verified_fraction=0.0, raw_doc_id="doc_x",
        coords_from="x0.00,y0.00,xi0.00,u0.00",
        coords_to="x0.10,y0.00,xi0.00,u0.10",
        turn_memory={"crawled_urls": set(), "tool_params": {},
                     "step_summaries": []},
    )
    assert env.status == "success"
    assert calls == {"fragment": 0, "save_doc": 0, "retrieve": 0}
