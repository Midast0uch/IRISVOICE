"""BT-7 (vision-goal-directed-search T27, REQ-14): semantic temporal
snapshot diffing — store two revisions of a URL-derived document and the
system must compute natural LANGUAGE deltas (price moved from 1999 to 1799,
−10%), never a raw JSON diff, and never a delta against a missing prior.

Covered paths:
  - AC14.2: semantic delta statements (numeric percent + condition wording).
  - AC14.4: revision increments by exactly 1 per store.
  - First-ever snapshot: revision 1, NO delta (never fabricated).
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from backend.agent.document_store import DocumentDataStore


@pytest.fixture()
def store(tmp_path):
    conn = sqlite3.connect(":memory:")
    s = DocumentDataStore(conn)
    yield s
    conn.close()


DOC_ID = "url_snapshot:abc123def4567890"


def test_first_snapshot_creates_revision_1_with_no_delta(store):
    store.store_json_atomic(DOC_ID, "application/json",
                            json.dumps({"price": 1999, "availability": "In Stock"}))
    record, rev, delta = store.get_with_delta(DOC_ID)
    assert rev == 1
    # No prior → no delta to compute (AC14.2 boundary: never fabricate).
    assert delta is None
    assert record["json"]["price"] == 1999


def test_second_snapshot_computes_semantic_price_drop(store):
    store.store_json_atomic(DOC_ID, "application/json",
                            json.dumps({"price": 1999, "availability": "In Stock"}))
    store.store_json_atomic(DOC_ID, "application/json",
                            json.dumps({"price": 1799, "availability": "Pre-order"}))
    record, rev, delta = store.get_with_delta(DOC_ID)

    assert rev == 2, f"revision did not advance by exactly 1 (got {rev})"
    assert record["json"]["availability"] == "Pre-order"
    assert delta is not None, "no temporal delta recorded on a real change"
    assert set(delta["delta_statements"]) & {
        s for s in delta["delta_statements"] if "price" in s
    }, f"price change missing from {delta['delta_statements']}"
    price_stmt = next(s for s in delta["delta_statements"] if "price" in s)
    assert "1999" in price_stmt and "1799" in price_stmt
    assert "-10" in price_stmt or "10.0%" in price_stmt, (
        f"a moved number needs the signed percent overlay: {price_stmt}"
    )
    assert any("availability" in s and "In Stock" in s and "Pre-order" in s
               for s in delta["delta_statements"])
    assert delta["prior_revision"] == 1 and delta["current_revision"] == 2
    assert "price" in delta["changed_fields"]


def test_unchanged_snapshot_produces_no_delta(store):
    """A re-crawl of an identical page must not manufacture changes."""
    payload = json.dumps({"price": 1999, "availability": "In Stock"})
    store.store_json_atomic(DOC_ID, "application/json", payload)
    store.store_json_atomic(DOC_ID, "application/json", payload)
    _, rev, delta = store.get_with_delta(DOC_ID)
    assert rev == 2
    # Zero-change revision: the delta exists structurally but contains no
    # statements — the UI renders no pills.
    assert delta is None or delta["delta_statements"] == []
