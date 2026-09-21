"""Expectation registry (session-319) — FAULTLINE's three layers for EXPECTATION.

WHY THIS FILE EXISTS
--------------------
The envelope's per-family bars used to be `if family == ...` branches inside
`derive_match`, so every new tool meant editing envelope logic, and a tool nobody
had classified fell through to a default that silently judged it. That is the
"re-engineer it every time" problem.

The fix follows the shape the project already validates for FAILURE
(docs/architecture/FAULTLINE.md, backend/agent/tool_errors.py):

  Layer 1 — DIMENSIONS  : a CLOSED, invariant outcome triple.
  Layer 2 — REGISTRY    : which bar judges a tool, as DATA.
  Layer 3 — UNCLASSIFIED: unregistered tools are COUNTED, never silently judged.

The closedness of Layer 1 is not a style choice: specs/wormhole-aperture requires
a closed categorical address it may hash but never re-derive (aperture REQ-32
AC2), and it already keys retrieval on FAULTLINE's `(retryable × blame ×
info_state)`. This suite pins that contract so a future change cannot quietly
widen the lattice out from under the aperture.
"""

from __future__ import annotations

import pytest

from backend.agent import tool_envelope as te


@pytest.fixture(autouse=True)
def _clean_registry():
    """Non-seeded labels and unknown counts must not leak between tests."""
    te.reset_expectation_registry_for_testing()
    yield
    te.reset_expectation_registry_for_testing()


# ── Layer 1: dimensions are CLOSED ──────────────────────────────────────────


def test_dimension_value_sets_are_closed_and_small():
    """The aperture hashes this lattice — widening it is a breaking change."""
    assert te.ALIGNMENT_VALUES == {"matched", "mismatched", "unclear"}
    assert te.IDENTITY_VALUES == {"new", "repeat", "unknown"}
    assert te.YIELD_VALUES == {"full", "partial", "empty"}
    # 3x3x3 = 27 addresses, the same order of magnitude as FAULTLINE's lattice.
    assert len(te.ALIGNMENT_VALUES) * len(te.IDENTITY_VALUES) * len(te.YIELD_VALUES) == 27


def test_address_is_stable_ordered_and_hashable():
    """REQ-32 AC2: a closed categorical ADDRESS, never a vector."""
    d = te.ExpectationDimensions(
        alignment="matched", identity="new", yield_state="full"
    )
    assert d.as_key() == "matched|new|full"
    # Same inputs -> same address, always (it is a primary-key shape).
    assert d.as_key() == te.ExpectationDimensions(
        alignment="matched", identity="new", yield_state="full"
    ).as_key()
    assert set(d.as_dict()) == {"alignment", "identity", "yield_state"}


def test_default_dimensions_are_the_unknown_corner():
    assert te.UNKNOWN_DIMENSIONS.as_key() == "unclear|unknown|empty"


# ── Layer 2: registry is DATA ───────────────────────────────────────────────


def test_seeded_labels_cover_the_existing_families():
    for label in ("gather", "read", "synthesis", "action", "direct"):
        assert label in te.EXPECTATION_LABELS


def test_register_refuses_an_unknown_bar():
    """A typo must not create a new judgement — refuse, never coerce."""
    assert te.register_expectation_label("typo_tool", "no_such_bar") is False
    assert "typo_tool" not in te.EXPECTATION_LABELS


def test_register_refuses_duplicates():
    """Same rule as FAULTLINE: the first spec to name a label owns it."""
    assert te.register_expectation_label("dup_tool", "read", "first") is True
    assert te.register_expectation_label("dup_tool", "gather", "second") is False
    assert te.EXPECTATION_LABELS["dup_tool"].bar == "read"


def test_new_tool_maps_onto_an_existing_bar_without_touching_envelope_code():
    """THE property this work exists for: adding a tool is a DATA edit.

    `scrape_pages` is not in any tool list and matches no heuristic, so before
    this change it would have fallen to the generic default. Registering it
    against the gather bar makes it judged exactly like a crawl — with no edit
    to derive_match.
    """
    assert te.register_expectation_label(
        "scrape_pages", "gather", "A new scraper — judged like a gather."
    ) is True
    _text = "alpha beta sources: https://x.example"
    assert te.judge_alignment("scrape_pages", _text, "alpha beta", "") == "matched"


# ── Layer 3: unclassified is VISIBLE ────────────────────────────────────────


def test_unregistered_label_is_counted_and_never_silently_matched():
    """The whole point of Layer 3: an unknown tool is visible, not invisible."""
    assert te.unknown_expectation_counts() == {}
    verdict = te.judge_alignment(
        "totally_new_tool", "plenty of content here", "expected thing", ""
    )
    assert verdict == "unclear"          # never matched/mismatched by default
    assert te.unknown_expectation_counts() == {"totally_new_tool": 1}

    te.judge_alignment("totally_new_tool", "more content", "x", "")
    assert te.unknown_expectation_counts() == {"totally_new_tool": 2}


def test_promotion_moves_a_label_from_layer3_to_layer2():
    """Vocabulary grows from EVIDENCE, mirroring promote_unknown()."""
    te.judge_alignment("emergent_tool", "text", "x", "")
    assert "emergent_tool" in te.unknown_expectation_counts()

    assert te.promote_unknown_expectation("emergent_tool", "read", "promoted") is True
    assert "emergent_tool" not in te.unknown_expectation_counts()
    assert te.EXPECTATION_LABELS["emergent_tool"].bar == "read"


def test_reset_keeps_seeds_and_drops_the_rest():
    te.register_expectation_label("temp_tool", "read")
    te.judge_alignment("temp_tool_2", "text", "x", "")
    te.reset_expectation_registry_for_testing()
    assert "temp_tool" not in te.EXPECTATION_LABELS
    assert te.unknown_expectation_counts() == {}
    assert "gather" in te.EXPECTATION_LABELS


# ── Behaviour preservation: the refactor must not change any verdict ────────


@pytest.mark.parametrize(
    "family,result,expected,want",
    [
        # gather: no term overlap -> mismatched
        ("gather", "completely unrelated prose", "alpha beta", "mismatched"),
        # gather: all terms + sources -> matched
        ("gather", "alpha beta sources", "alpha beta", "matched"),
        # read: doc id resolved -> matched
        ("read", "short", "anything", "matched"),
        # action: no success marker -> unclear
        ("action", "attempted the thing", "write it", "unclear"),
        # direct: no expectation terms -> unclear
        ("direct", "some text", "", "unclear"),
    ],
)
def test_seeded_bars_preserve_prior_verdicts(family, result, expected, want):
    """The registry is a refactor, not a behaviour change."""
    assert te.derive_match(family, result, expected, "doc" if family == "read" else "") == want


def test_read_bar_matches_on_substantial_text_without_a_doc_id():
    assert te.derive_match("read", "x" * 120, "anything", "") == "matched"


def test_read_bar_is_mismatched_on_nothing_at_all():
    assert te.derive_match("read", "", "anything", "") == "mismatched"


def test_derive_match_never_raises_on_a_broken_bar(monkeypatch):
    """A broken bar degrades to `unclear`; it must never break the DER loop."""
    def _boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setitem(te.BARS, "read", _boom)
    assert te.derive_match("read", "text", "expected", "doc") == "unclear"
