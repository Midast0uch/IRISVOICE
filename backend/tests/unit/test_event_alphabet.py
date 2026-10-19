"""The event alphabet is CLOSED (docs/Design/EVENT_TAXONOMY.md, owner-approved
2026-09-30). Node chains hash sentences written in it (specs/wormhole-aperture
REQ-46 AC7): widening a lattice silently corrupts every stored chain. These
tests pin the sizes; changing one is a BREAKING decision for the owner, never a
fix to make a test pass."""
from __future__ import annotations

import pytest

from backend.memory import event_alphabet as ea


def test_the_new_lattices_are_closed_and_pinned():
    assert ea.FAMILIES == frozenset({"intent", "control", "problem", "knowledge", "feedback",
                                     "delivery", "memory", "safety", "environment"})
    assert ea.VALENCES == frozenset({"advances", "sets_back", "neutral"})
    assert ea.ACTORS == frozenset({"user", "agent", "tool", "world", "subagent"})
    assert ea.EVIDENCE == frozenset({"none", "claim", "verifier", "test", "completion", "user",
                                     "recurrence", "corroboration"})
    assert ea.OUTSIDE_EVIDENCE == frozenset({"test", "completion", "user", "recurrence",
                                             "corroboration"})
    assert ea.OUTSIDE_EVIDENCE < ea.EVIDENCE


def test_the_reused_lattices_are_not_re_modelled():
    from backend.agent.tool_envelope import ExpectationDimensions
    from backend.agent.tool_errors import FailureDimensions

    assert set(ExpectationDimensions().as_dict()) == {"alignment", "identity", "yield_state"}
    assert set(FailureDimensions().as_dict()) == {"retryable", "blame", "info_state"}
    assert not hasattr(ea, "CAUSE") and not hasattr(ea, "OUTCOME")


def test_every_seed_label_sits_inside_the_alphabet_and_every_family_has_words():
    labels = ea.registered_labels()
    assert {s.family for s in labels.values()} == ea.FAMILIES
    for spec in labels.values():
        assert spec.valence in ea.VALENCES and spec.actor in ea.ACTORS
    # The coding words stay words of the problem family.
    for word in ("BUG", "FIX", "VERIFIED_FIX", "OBSTACLE", "RESOLUTION", "VERIFIED_RESOLUTION"):
        assert labels[word].family == "problem"


def test_the_registry_grows_words_never_letters():
    with pytest.raises(ValueError):
        ea.register_event_label("X_NEW", "finance", "neutral", "agent", "a family outside")
    with pytest.raises(ValueError):
        ea.register_event_label("X_NEW", "problem", "great", "agent", "a valence outside")
    with pytest.raises(ValueError):
        ea.register_event_label("BUG", "problem", "sets_back", "tool", "duplicate")


def test_unknown_labels_are_counted_then_promotable():
    name = "TEST_ONLY_UNSEEN_LABEL"
    assert ea.resolve_event_label(name) is None
    assert ea.unknown_event_counts()[name] >= 1
    spec = ea.promote_unknown_event(name, "knowledge", "neutral", "world", "test promotion")
    assert ea.resolve_event_label(name) is spec
    assert name not in ea.unknown_event_counts()


def test_hash_signature_is_deterministic_and_never_a_stand_in():
    a = ea.hash_signature("2.00,1.00,1.05,0.35", "der", "general")
    assert a == ea.hash_signature("2.00,1.00,1.10,0.40", "der", "general")  # same bins
    assert a != ea.hash_signature("2.00,1.00,1.05,0.35", "voice", "general")
    # A different STATE gets a different address. Scheme 2 (owner, 2026-10-18): x and y
    # enter as the charge Q and the work volume, not raw counts, so the different state
    # here is the opposite balance (expansion-led vs compression-led), not "one more step".
    assert a != ea.hash_signature("1.00,2.00,1.05,0.35", "der", "general")
    assert ea.hash_signature(None, "der", "general") is None
    assert ea.hash_signature("rest:input:1", "der", "general") is None


def test_the_address_is_a_state_not_a_step_counter():
    """Scheme 1 hashed raw step counts: every step of every session minted a new
    address, so an exact-match recall (Wormhole Tier-1a) could only hit 'step n of
    some session'. The address space must stay bounded however long sessions run."""
    seen = {ea.hash_signature(f"{x}.00,{y}.00,1.05,0.35", "der", "general")
            for x in range(0, 200, 3) for y in range(0, 200, 3)}
    assert len(seen) <= 5 * 6   # charge bins x volume bins


def test_a_poisoned_coordinate_is_written_unhashed_never_raised():
    """Wormhole REQ-1 edge case: NaN / inf -> no address, logged. Scheme 1 raised
    inside emit, whose broad except then dropped the WHOLE event."""
    for bad in ("nan,1.00,1.05,0.35", "1.00,1.00,inf,0.35", "1.00,1.00,1.05,nan"):
        assert ea.hash_signature(bad, "der", "general") is None
        assert ea.hex_bin_id(bad, "der", "general") is None


def test_refining_a_sector_never_moves_an_address():
    s = "4.00,3.00,2.10,-0.30"
    assert ea.hash_signature(s, "der", "systems/memory/recall") == ea.hash_signature(s, "der", "systems")
    assert ea.hex_bin_id(s, "der", "systems/memory") == ea.hex_bin_id(s, "der", "systems")
    assert ea.hash_signature(s, "der", "systems") != ea.hash_signature(s, "der", "web")


def test_the_hex_bin_is_minted_from_the_same_state():
    s = "4.00,3.00,2.10,-0.30"
    h = ea.hex_bin_id(s, "der", "general")
    assert h and h == ea.hex_bin_id(s, "der", "general")          # deterministic
    assert h != ea.hex_bin_id("4.00,3.00,5.10,0.80", "der", "general")  # another cell
    assert ea.hex_bin_id(None, "der", "general") is None


def test_only_facts_count_as_outside_evidence():
    """An Oracle or Brain GUESS that a message confirms something is not outside
    evidence; only rule- or user-produced labels are facts."""
    assert ea.counts_as_outside_evidence("user", "user")
    assert ea.counts_as_outside_evidence("test", "rule")
    assert not ea.counts_as_outside_evidence("user", "oracle")
    assert not ea.counts_as_outside_evidence("user", "brain")
    assert not ea.counts_as_outside_evidence("verifier", "rule")
    assert ea.TRUSTED_LABEL_SOURCES < ea.LABEL_SOURCES
