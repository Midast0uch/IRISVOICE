"""Unit tests: tool_envelope pure functions (specs/tool-result-envelope T4/T9).

Zero I/O, zero encodes, zero LLM — the gate's O(n) arithmetic is pinned here.
Covers: wrapper labels per tool family (AC3.1/KD-9), the 5-shape stuck
taxonomy (AC3.2), hierarchy-C suggestions (AC3.3/KD-8), criticality confirm
option C incl. divergence (AC1.6/KD-9), minimal degrade (AC1.4), streak
evaluation incl. the TOPO_VIOLATION override (AC5.1–AC5.5), run grade
(AC5.6), and the envelope line bounds (AC1.1).
"""
from __future__ import annotations

import pytest

from backend.agent.tool_envelope import (
    ToolResultEnvelope,
    build_envelope,
    classify_stuck_shape,
    confirm_criticality,
    derive_match,
    derive_novelty,
    derive_suggestion,
    evaluate_run_grade,
    evaluate_streak,
    mark_consumed,
    minimal_envelope,
    params_digest,
    tool_family,
)


# ── tool family classification (KD-9) ────────────────────────────────────────


def test_tool_family_classification():
    assert tool_family("crawler_query") == "gather"
    assert tool_family("web_search") == "gather"
    assert tool_family("read_file") == "read"
    assert tool_family("write_file") == "action"
    assert tool_family(None) == "direct"
    assert tool_family("unknown_tool") == "direct"


# ── per-family match bars (AC3.1) ────────────────────────────────────────────


def test_gather_match_asked_terms_and_sources():
    result = (
        "whisper.cpp supports streaming via its stream example.\n"
        "--- Source: https://github.com/ggml-org/whisper.cpp\n"
    )
    assert derive_match(
        "gather", result, "whisper.cpp streaming support", "doc1"
    ) == "matched"


def test_gather_match_mismatched_when_terms_absent():
    result = (
        "Parakeet is NVIDIA's model.\n"
        "--- Source: https://nvidia.com/parakeet\n"
    )
    assert derive_match(
        "gather", result, "whisper.cpp streaming support", "doc1"
    ) == "mismatched"


def test_read_match_ref_resolved():
    assert derive_match("read", "Here is the document content " * 10, "", "doc1") == "matched"
    assert derive_match("read", "", "", "") == "mismatched"


def test_synthesis_match_covers_prior_summaries():
    priors = ["whisper.cpp streams via stdin pipe", "Parakeet streams on GPU"]
    covered = "From the research: whisper.cpp streams via stdin pipe, and Parakeet streams on GPU."
    assert derive_match("synthesis", covered, "", "", priors) == "matched"
    assert derive_match("synthesis", "Nothing relevant at all.", "", "", priors) == "mismatched"


def test_action_match_side_effect_confirmed():
    assert derive_match("action", "File created successfully.", "", "") == "matched"
    assert derive_match("action", "Unrelated text with no markers here.", "", "") == "unclear"


# ── novelty vs turn memory (AC3.1) ──────────────────────────────────────────


def test_novelty_repeat_by_params_digest():
    mem = {"tool_params": {params_digest("crawler_query", {"query": "x"}): "s1"}}
    assert derive_novelty(
        "some result", "crawler_query",
        params_digest("crawler_query", {"query": "x"}), mem,
    ).startswith("repeat_of_")
    assert derive_novelty(
        "some result", "crawler_query",
        params_digest("crawler_query", {"query": "different"}), mem,
    ) == "new"


def test_novelty_empty_and_url_subset():
    assert derive_novelty("", "crawler_query", "d", {}) == "empty"
    mem = {
        "crawled_urls": {"https://a.com", "https://b.com"},
        "last_gather_step_id": "s2",
    }
    assert derive_novelty(
        "see https://a.com and https://b.com", "crawler_query", "d", mem,
    ) == "repeat_of_s2"


# ── stuck taxonomy, all 5 shapes (AC3.2) ────────────────────────────────────


def test_stuck_shape_flat_tire():
    assert classify_stuck_shape("error", "unclear", "new", "err text", "", None, None) == "flat_tire"
    assert classify_stuck_shape("success", "unclear", "new", "x", "", None, None, capture_skipped=True) == "flat_tire"


def test_stuck_shape_dry_well():
    assert classify_stuck_shape("success", "unclear", "empty", "", "", None, None) == "dry_well"


def test_stuck_shape_circling():
    assert classify_stuck_shape("success", "matched", "repeat_of_s1", "text", "", None, None) == "circling"


def test_stuck_shape_wrong_package():
    assert classify_stuck_shape("success", "mismatched", "new", "real output", "", None, None) == "wrong_package"


def test_stuck_shape_idling():
    assert classify_stuck_shape(
        "success", "matched", "new", "good output", "", 0.5, 0.5,
    ) == "idling"
    # fraction moved → not idling
    assert classify_stuck_shape(
        "success", "matched", "new", "good output", "", 0.5, 0.9,
    ) == "none"


def test_hierarchy_c_suggestions():
    # HARD: walled → stop; circling → never retry_same
    assert derive_suggestion("flat_tire", "error", "walled") == "stop"
    s = derive_suggestion("circling", "success", "")
    assert s == "try_different"
    # STRONG suggestions
    assert derive_suggestion("dry_well", "success", "") == "try_different"
    assert derive_suggestion("wrong_package", "success", "") == "try_different"
    assert derive_suggestion("flat_tire", "error", "transient") == "retry_same"
    assert derive_suggestion("idling", "success", "") == "try_different"
    assert derive_suggestion("none", "success", "") == "proceed"


# ── criticality option C (AC1.6) ─────────────────────────────────────────────


def test_confirm_criticality_declared_vs_consumed():
    # declared supporting + consumed → confirmed load-bearing (divergence)
    assert confirm_criticality("supporting", consumed=True) == ("load-bearing", "confirmed")
    # declared load-bearing stays declared
    assert confirm_criticality("load-bearing", consumed=False) == ("load-bearing", "declared")
    # supporting, unconsumed → stays declared
    assert confirm_criticality("supporting", consumed=False) == ("supporting", "declared")
    # invalid declared falls back to supporting
    assert confirm_criticality("bogus", False) == ("supporting", "declared")


def test_mark_consumed_retroactive():
    env = ToolResultEnvelope(status="success", summary="s", criticality="supporting", criticality_source="declared")
    before, after = mark_consumed(env)
    assert before == ("supporting", "declared")
    assert after == ("load-bearing", "confirmed")
    assert env.criticality == "load-bearing"


# ── envelope construction (AC1.1–AC1.5) ─────────────────────────────────────


def test_build_envelope_success_shape_and_bounds():
    env = build_envelope(
        result_text="word " * 200,  # >300 chars
        step_success=True,
        outcome="VERIFIED",
        expected_output="streaming support",
        tool="crawler_query",
        params_digest="d1",
        verified_fraction=1.0,
        prev_verified_fraction=0.0,
        raw_doc_id="doc_abc",
        coords_from="x0.00,y0.00,xi0.00,u0.00",
        coords_to="x1.00,y0.00,xi0.00,u0.00",
        turn_memory={"crawled_urls": set(), "tool_params": {}, "step_summaries": []},
        declared_criticality="load-bearing",
        step_id="s1", session_id="sess", turn_id="t1",
    )
    assert env.status == "success"
    assert len(env.summary) <= 300
    assert "\n" not in env.summary
    assert env.raw_ref == {"doc_id": "doc_abc"}
    assert env.criticality == "load-bearing"
    assert env.criticality_source == "declared"
    assert env.coords_basis == "format_coords"
    assert env.coords_from.startswith("x0.00")
    # NO fingerprint / vector field anywhere (KD-7)
    assert not any("fingerprint" in f or "vector" in f for f in vars(env))


def test_build_envelope_no_coords_signal_never_fabricates_zero():
    env = build_envelope(
        result_text="ok", step_success=True, outcome="VERIFIED",
        expected_output="", tool=None, params_digest="d",
        verified_fraction=1.0, prev_verified_fraction=None,
        raw_doc_id="", coords_from=None, coords_to=None,
        turn_memory={},
    )
    assert env.coords_from == "" and env.coords_to == ""
    assert env.coords_basis == "none"


def test_build_envelope_error_shape_from_tool_errors():
    env = build_envelope(
        result_text="[STEP ERROR: connection timeout]",
        step_success=False, outcome="FAILED",
        expected_output="", tool="crawler_query", params_digest="d",
        verified_fraction=None, prev_verified_fraction=None,
        raw_doc_id="", coords_from=None, coords_to=None,
        turn_memory={},
    )
    assert env.status == "error"
    assert env.error_type  # classified, not empty
    assert env.recovery_hint


def test_minimal_envelope_degrade():
    env = minimal_envelope(
        outcome="VERIFIED", content_summary="some summary", raw_doc_id="d1",
        step_id="s9",
    )
    assert env.status == "success"
    assert env.summary == "some summary"
    assert env.match == "unclear"
    assert env.novelty == "new"
    assert env.suggestion == "proceed"
    assert env.raw_ref == {"doc_id": "d1"}


def test_envelope_line_bounded_and_contains_wrapper():
    env = ToolResultEnvelope(
        status="success", summary="asked Parakeet got whisper.cpp",
        match="mismatched", novelty="repeat_of_s1",
        suggestion="try_different", stuck_shape="circling",
        raw_ref={"doc_id": "abcdef123456"},
    )
    line = env.line()
    assert "success" in line and "mismatched" in line
    assert "repeat_of_s1" in line and "try_different" in line
    assert "abcdef123456"[:12] in line
    assert len(line) <= 500


# ── streak gate (AC5.1–AC5.5) ────────────────────────────────────────────────


def _w(step_id, novelty="new", match="matched", status="success", shape="none"):
    return {
        "step_id": step_id, "status": status, "match": match,
        "novelty": novelty, "suggestion": "proceed", "stuck_shape": shape,
    }


def test_streak_fires_on_repeat_streak():
    wrappers = [_w("s1"), _w("s2", novelty="repeat_of_s1"), _w("s3", novelty="repeat_of_s1")]
    fire, reason = evaluate_streak(wrappers, stuck_n=2, idle_n=2)
    assert fire and reason.startswith("stuck_streak")


def test_streak_fires_on_mismatch_streak():
    wrappers = [_w("s1", match="mismatched"), _w("s2", match="mismatched")]
    fire, reason = evaluate_streak(wrappers, stuck_n=2, idle_n=2)
    assert fire and reason.startswith("stuck_streak")


def test_streak_fires_on_empty_streak():
    wrappers = [_w("s1", novelty="empty", shape="dry_well"), _w("s2", novelty="empty", shape="dry_well")]
    fire, _ = evaluate_streak(wrappers, stuck_n=2, idle_n=2)
    assert fire


def test_streak_fires_on_idling_run():
    wrappers = [_w("s1", shape="idling"), _w("s2", shape="idling")]
    fire, reason = evaluate_streak(wrappers, stuck_n=2, idle_n=2)
    assert fire and reason.startswith("idle_streak")


def test_streak_blocked_on_nominal_run():
    wrappers = [_w("s1"), _w("s2"), _w("s3")]
    fire, reason = evaluate_streak(wrappers, stuck_n=2, idle_n=2)
    assert not fire and reason == ""


def test_streak_blocked_when_nonconsecutive():
    wrappers = [_w("s1", novelty="empty"), _w("s2"), _w("s3", match="mismatched")]
    fire, _ = evaluate_streak(wrappers, stuck_n=2, idle_n=2)
    assert not fire, "non-consecutive stuck wrappers must not fire"


def test_topo_violation_forces_fire_regardless():
    wrappers = [_w("s1"), _w("s2")]
    fire, reason = evaluate_streak(wrappers, stuck_n=2, idle_n=2, topo_violation=True)
    assert fire and reason == "topo_violation"


def test_streak_insufficient_evidence_never_fires_on_step_one():
    fire, _ = evaluate_streak([_w("s1", novelty="empty")], stuck_n=2, idle_n=2)
    assert not fire


# ── run grade (AC5.6) ────────────────────────────────────────────────────────


def test_run_grade_capped_by_load_bearing_mismatch():
    env = ToolResultEnvelope(status="success", summary="s", match="mismatched", criticality="load-bearing")
    grade, reasons = evaluate_run_grade([env])
    assert grade == "capped" and reasons


def test_run_grade_supporting_miss_never_sinks():
    env = ToolResultEnvelope(status="success", summary="s", match="mismatched", criticality="supporting")
    grade, _ = evaluate_run_grade([env])
    assert grade == "pass"


def test_run_grade_veto_can_be_disabled():
    env = ToolResultEnvelope(status="success", summary="s", match="mismatched", criticality="load-bearing")
    grade, _ = evaluate_run_grade([env], load_bearing_veto=False)
    assert grade == "pass"


# ── params digest stability ──────────────────────────────────────────────────


def test_params_digest_stable_and_order_insensitive():
    a = params_digest("t", {"url": "x", "q": 1})
    b = params_digest("t", {"q": 1, "url": "x"})
    assert a == b
    assert params_digest("t", None) != params_digest("other", None)
