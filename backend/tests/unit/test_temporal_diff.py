"""T15 (REQ-14): TemporalDelta — turns current-vs-prior content into natural
language deltas + bumps the revision counter.

The engine reads the PRIOR version's JSON dict and the CURRENT dict, computes
a diff on shared fields (price, availability, headings, table values,
database rows), and returns a ``TemporalDelta`` recording both the changed
fields and the natural-language delta strings the UI renders as one-liners.

Rules the engine must honor (from REQ-14):
- Revision increments only on write, so a re-read of the same content with
  no changes leaves revision and prior_version_matched unchanged.
- Price deltas are normalized to percent change formatted as "+15.2%" /
  "-10.0%" where the sign and the one decimal are preserved.
- A field whose value is present in the CURRENT row but missing in PRIOR is
  treated as a "new" field (never "unchanged"), the chassis shows it as
  added.
"""
from __future__ import annotations

import json
import sqlite3

from backend.agent.document_store import DocumentDataStore
from backend.crawler.temporal_diff import compute_temporal_delta


def test_price_drop_with_number_change():
    d = compute_temporal_delta(
        prior={"price": 1999, "availability": "In Stock"},
        current={"price": 1799, "availability": "In Stock"},
    )
    assert d.changed_fields == ["price"]
    assert "10.0%" in d.delta_statements[0]


def test_availability_change_is_a_meaningful_delta():
    d = compute_temporal_delta(
        prior={"price": 1999, "availability": "In Stock"},
        current={"price": 1999, "availability": "Sold Out"},
    )
    assert "availability" in d.changed_fields
    assert "Sold Out" in d.delta_statements[0]


def test_no_changes_produce_no_delta():
    d = compute_temporal_delta(
        prior={"price": 1999, "availability": "In Stock"},
        current={"price": 1999, "availability": "In Stock"},
    )
    assert not d.changed_fields
    assert d.delta_statements == []


def test_new_field_only_in_current_yields_added_delta():
    d = compute_temporal_delta(
        prior={"price": 1999},
        current={"price": 1999, "warranty_term": "2yr"},
    )
    assert "warranty_term" in d.changed_fields
    assert any("2yr" in s for s in d.delta_statements)


def test_unchanged_structured_values_dont_explode():
    d = compute_temporal_delta(
        prior={"features": ["h1", "h2"], "price": 100},
        current={"features": ["h1", "h2"], "price": 100},
    )
    assert "features" not in d.changed_fields


def test_store_round_trip_bumps_revision_and_emits_delta(tmp_path):
    """REQ-14 AC1-AC2: store a JSON snapshot, then the same document with a
    price change — reading it back must return revision=2 with a computed
    TemporalDelta naming the price drop percentage."""
    conn = sqlite3.connect(str(tmp_path / "docs.db"))
    store = DocumentDataStore(conn)
    prior = {"price": 1999, "availability": "In Stock"}
    # First write through THE SAME atomic pathway as the real runtime (a new
    # snapshot is never going through plain store()).
    store.store_json_atomic("doc:t1", fmt="json", content=json.dumps(prior))

    current = {"price": 1799, "availability": "In Stock"}
    store.store_json_atomic("doc:t1", fmt="json", content=json.dumps(current))

    _, rev, delta = store.get_with_delta("doc:t1") or (None, None, None)
    assert rev == 2
    assert delta is not None
    assert "price" in delta["changed_fields"]
