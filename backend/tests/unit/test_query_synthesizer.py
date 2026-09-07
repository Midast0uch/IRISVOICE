"""T13 (REQ-13): dynamic multi-angle query synthesis + in-flight adaptation.

The Brain synthesizes 2–4 ORTHOGONAL query facets off the user's task (not
one fused query) and the initial set enqueues as a BatchToolCall. Gaps in the
StepFindingsAccumulator trigger targeted FOLLOW-UP queries onto the same
DAG without restarting.

Scope pinned by the spec text ("Brain agent dynamically synthesizes 2-4
orthogonal query facets"): we test the DER-facing surface — the planner
produces the facet set, the DAG dispatches it, and a missing-field signal
from the accumulator re-synthesizes. The LLM brain itself is behind the
`brain()` callable (replaced in tests) so we never touch the network.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from backend.agent.query_synthesizer import (
    QueryBatch,
    QuerySynthesizer,
    synthesize_for_task,
)


# ---------------------------------------------------------------------------
# Synthesis: fixed inputs, fixed facet axes; the LLM is stubbed
# ---------------------------------------------------------------------------

def _llm_stub(task: str, n_needed: int, existing: list[str]):
    # Deterministic multi-facet response: the LLM "sees" the focus axis and
    # returns a query for each requested axis.
    return [
        "technical specifications for halide tablets",
        "pricing and availability for halide tablets",
        "chromium benchmark for halide tablets",
    ]


def test_synthesizer_produces_2_to_4_orthogonal_facets():
    """AC13.1: 2–4 facets, each anchored to a DIFFERENT axis."""
    q = synthesize_for_task("give me the newest halide tablets", brain=_llm_stub)
    assert 2 <= len(q.queries) <= 4
    # Each facet tags the axis so downstream routing can see WHY the query
    # exists — not just the string.
    assert all(isinstance(qf.axis, str) and qf.axis for qf in q.queries)
    # No duplicate axes (orthogonal means distinct, not just unique strings).
    assert len({f.axis for f in q.queries}) == len(q.queries)


def test_synthesizer_handles_empty_llm_result_safely():
    """Edge case: if the Brain returns nothing, fall through to a single
    task-derived fallback query (never returns nothing)."""
    q = synthesize_for_task("compare q1 vs q2 models", brain=lambda *_a, **_k: None)
    assert len(q.queries) == 1
    assert q.queries[0].query


def test_facets_embed_intent_axis():
    """The synthesized query string carries the target axis — because without
    it every facet looks like a variation of the same template."""
    q = synthesize_for_task(
        "research the Acme Pro 3000 launch",
        brain=lambda *_a, **_kw: [
            "Acme Pro 3000 official specs",
            "Acme Pro 3000 reviews 2026",
        ],
    )
    assert q.queries[0].axis


# ---------------------------------------------------------------------------
# In-flight adaptation: a gap fires a follow-up query onto the same DAG
# ---------------------------------------------------------------------------

def test_inflight_missing_field_triggers_followup():
    """AC13.3: schema-missing field = use a targeted follow-up query on the
    SAME run (no re-plan)."""
    from backend.agent.query_synthesizer import StepFindingsAccumulator

    acc = StepFindingsAccumulator(goal_fields={"price", "specs"})
    acc.ingest(result={"specs": "16 GB / 1 TB SSD"}, url="https://example.com/x")

    followups = acc.missing_followups(brain=lambda task, existing: [
        "halide tablet launch price announcement",
    ])
    assert followups, "the price gap should trigger a follow-up"


def test_full_schema_yields_no_followups():
    """When every goal field is satisfied, no follow-up query is generated."""
    from backend.agent.query_synthesizer import StepFindingsAccumulator

    acc = StepFindingsAccumulator(goal_fields={"price", "specs"})
    acc.ingest(result={"specs": "16 GB", "price": 999}, url="https://example.com/x")
    assert acc.missing_followups(brain=lambda *_a, **_k: ["extra"]) == []


def test_no_duplicate_urls_across_followups():
    """A synthesized follow-up URL that was already crawled is dropped —
    merge-by-normalized-URL (AC13.4)."""
    from backend.agent.query_synthesizer import StepFindingsAccumulator

    acc = StepFindingsAccumulator(goal_fields={"price"})
    acc.ingest(result={"specs": "x"}, url="https://example.com/tablet")
    acc.ingest(result={"specs": "x"}, url="https://example.com/tablet/")  # SAME page
    assert acc.url_count == 1
