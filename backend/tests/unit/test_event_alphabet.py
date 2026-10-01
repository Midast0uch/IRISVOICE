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
    assert a != ea.hash_signature("3.00,1.00,1.05,0.35", "der", "general")
    assert ea.hash_signature(None, "der", "general") is None
    assert ea.hash_signature("rest:input:1", "der", "general") is None


def test_only_facts_count_as_outside_evidence():
    """An Oracle or Brain GUESS that a message confirms something is not outside
    evidence; only rule- or user-produced labels are facts."""
    assert ea.counts_as_outside_evidence("user", "user")
    assert ea.counts_as_outside_evidence("test", "rule")
    assert not ea.counts_as_outside_evidence("user", "oracle")
    assert not ea.counts_as_outside_evidence("user", "brain")
    assert not ea.counts_as_outside_evidence("verifier", "rule")
    assert ea.TRUSTED_LABEL_SOURCES < ea.LABEL_SOURCES
