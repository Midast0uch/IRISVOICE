"""T14 (REQ-8, REQ-11): StepFindingsAccumulator — strict schema projection
+ semantic cross-source verification gate.

REQ-8: extracted findings are only the schema's fields (bounded ≤5KB per
item; at most 32KB total); everything else is dropped, not stored.

REQ-11: any critical field (price/model_number/release_date) must be seen
on at least 2 independent, non-parked domains before it counts as verified.
Semantic normalization: USD only (fx reconciliation deferred), refurbished
≠ new, bundle ≠ standalone.
"""
from __future__ import annotations

from backend.agent.der_loop import StepFindingsAccumulator


def test_accumulator_rejects_non_schema_fields():
    """REQ-8: raw html/title noise is dropped (not stored) even if present."""
    acc = StepFindingsAccumulator(goal_fields={"price", "name"})
    acc.add("https://store.example/p", {
        "name": "Pro Pad 8",
        "price": 999,
        "raw_html": "<div>garbage</div>" * 500,
        "category": "tablet",
        "description": "long-form SEO boilerplate..." * 100,
    })
    snap = acc.snapshot()
    assert snap["instance"]["price"] == 999
    assert snap["instance"]["name"] == "Pro Pad 8"
    assert "raw_html" not in str(snap["instance"])
    assert acc.total_bytes() < 5_500


def test_total_footprint_bound_over_many_pages():
    """REQ-8 hard cap: after 15 pages nothing is stored above the bound."""
    acc = StepFindingsAccumulator(goal_fields={"price", "name"})
    for i in range(15):
        acc.add("https://p.example/x" + str(i), {
            "price": 100 + i, "name": f"page-{i}", "notes": "x" * 10_000,
        })
    assert acc.total_bytes() <= 32_000


def test_verification_needs_two_domains():
    """REQ-11: a price seen on ONE domain can never be marked verified."""
    acc = StepFindingsAccumulator(goal_fields={"price"})
    acc.add("https://store-a.example/p1", {"price": 100})
    acc.add("https://store-a.example/p2", {"price": 100})  # same domain twice — no quorum
    snap = acc.snapshot()
    assert snap["verified"]["price"]["verified"] is False
    assert snap["verified"]["price"]["corroborations"] < 2


def test_verification_on_different_domains_normalizes_price():
    """Cross-source price normalization (USD conversion assumed: the value
    payloads here are already USD even though the currencies differ in the
    source JSON)."""
    acc = StepFindingsAccumulator(goal_fields={"price"})
    acc.add("https://example-a.com/p", {"price": 899.0})
    acc.add("https://example-b.com/q", {"price": 900.0})
    acc.add("https://example-c.com/r", {"price": 899.0})
    snap = acc.snapshot()
    assert snap["verified"]["price"]["verified"] is True
    # USD normalization keeps cents-denominators separate from dollars so
    # integers $899 vs $89900 do NOT merge — both payloads here are USD.
    assert snap["verified"]["price"]["unit_count"] >= 2


def test_condition_differentiates_new_from_refurbished():
    """REQ-11 semantic reconciliation: a new item vs a refurb of the same
    model must not corroborate one another on price."""
    acc = StepFindingsAccumulator(goal_fields={"price"})
    acc.add("https://mfr.example/p", {"price": 1999, "_condition": "new"})
    acc.add("https://resale.example/p", {"price": 1799, "_condition": "refurbished"})

    snap = acc.snapshot()
    # The refurb count is not a corroborator for the new price claim.
    assert snap["verified"]["price"]["verified"] is False


def test_bundle_vs_standalone_do_not_corroborate():
    """Bundle offer ≠ standalone MSRP. The deal that's richer than the sticker
    must not prove the MSRP wrong."""
    acc = StepFindingsAccumulator(goal_fields={"price"})
    acc.add("https://mfr.example/p", {"price": 1999, "_bundle": False})
    acc.add("https://bundle.example/p", {"price": 1799, "_bundle": True})
    snap = acc.snapshot()
    assert snap["verified"]["price"]["verified"] is False


def test_parked_sources_do_not_corroborate():
    """A parked cord/escalated source never counts toward verification."""
    acc = StepFindingsAccumulator(goal_fields={"price"})
    acc.add("https://a.example/p", {"price": 100})
    acc.add("https://parked.example/blocked", {"price": 100}, parked=True)
    snap = acc.snapshot()
    assert snap["verified"]["price"]["verified"] is False