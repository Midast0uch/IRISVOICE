"""Wave 3 (REQ-2): the decision identity is ``model_id|readout_mode|criteria_hash``.

THE CONTRACT (specs/oracle-native-decision-surface, TG-3)
  * AC2.1 ``decision_identity`` composes the three parts; the retired letter
    readout is nameable as ``legacy_letters`` so historical rows address a
    real identity instead of silently matching the native one (T3.1).
  * AC2.2 ``EngineConfig.threshold_for`` resolves None on an UNKNOWN identity:
    a readout change and a criteria edit must each kill the threshold (T3.2,
    T3.4). Fail-closed is the default, not a fallback.
  * AC2.3 ``consumer_bar.superseded_flips`` compares ``readout_mode`` and the
    per-consumer ``criteria_hash``: a flip measured under the letter readout
    or under edited criteria is reported superseded, and never silently
    stands (T3.3). The record is NEVER mutated - stale rows stay.
  * AC13.3 the candidate cap is INSIDE the criteria hash: tuning the cap
    re-identifies every choice consumer exactly as editing its criteria does.
  * AC13.8 (stated, not fixed): a ``sampled`` consumer is never reported as
    superseded, because the function returns early on ``bar.flipped``.
"""
from __future__ import annotations

import copy

import pytest

from backend.agent import consumer_bar as cb
from backend.agent import decision_engine as de


# ---------------------------------------------------------------------------
# T3.1 / AC2.1: the identity is composed, and the legacy readout is nameable
# ---------------------------------------------------------------------------


def test_identity_composes_model_readout_and_criteria():
    h = de.criteria_hash("mode")
    assert de.decision_identity("d1-x", de.CURRENT_READOUT_MODE, "mode") == (
        f"d1-x|{de.CURRENT_READOUT_MODE}|{h}"
    )


def test_the_retired_letter_readout_is_a_nameable_identity():
    """T3.1: historical rows address a real identity, not a silent match."""
    legacy = de.decision_identity(
        "d1-x", de.LEGACY_READOUT_MODE, "mode")
    native = de.decision_identity(
        "d1-x", de.CURRENT_READOUT_MODE, "mode")
    assert de.LEGACY_READOUT_MODE == "legacy_letters"
    assert legacy != native
    assert legacy.split("|")[1] == "legacy_letters"


def test_backend_identity_without_a_consumer_carries_no_criteria_hash():
    """The BACKEND identity is `model|readout`; the criteria hash belongs to
    the decision point, per consumer (handoff: report writes that one)."""
    assert de.decision_identity("d1-x", de.CURRENT_READOUT_MODE) == (
        f"d1-x|{de.CURRENT_READOUT_MODE}"
    )


# ---------------------------------------------------------------------------
# AC2.4 + AC13.3: the criteria hash tracks the declarations and the cap
# ---------------------------------------------------------------------------


def test_criteria_edit_reidentifies_the_consumer(monkeypatch):
    """T3.4 drive: edit one consumer's criteria text and it is a NEW
    identity (oracle.md §19.3.6)."""
    before = de.criteria_hash("mode")
    decl = de.CONSUMER_DECLARATIONS["mode"]
    edited = dict(decl.criteria)
    edited["spec"] = "Write or update a specification (edited)"
    monkeypatch.setitem(
        de.CONSUMER_DECLARATIONS, "mode",
        de.ConsumerDeclaration(decl.decision_type, edited))
    assert de.criteria_hash("mode") != before


def test_the_candidate_cap_is_inside_the_hash():
    """AC13.3: tuning the cap re-identifies the consumer, exactly as an edit
    does - nobody may 'harmlessly' tune the cap and keep a stale flip."""
    assert de.criteria_hash("mode", 6) != de.criteria_hash("mode", 8)


def test_criteria_hash_is_stable_and_typed():
    """Same input, same digest; and the decision TYPE is part of the digest,
    so `native_choice` vs `native_noul` can never collide through the hash."""
    a = de.criteria_hash("mode")
    b = de.criteria_hash("mode")
    assert a == b and len(a) == 12
    decl = de.CONSUMER_DECLARATIONS["mode"]
    assert de.criteria_hash("mode") != de.criteria_hash("done")
    assert decl.decision_type == "choice"


# ---------------------------------------------------------------------------
# T3.2 / AC2.2: threshold_for resolves None on an unknown identity
# ---------------------------------------------------------------------------


def _cfg(backend_id, thresholds, cap=6):
    return de.EngineConfig(
        backend_id=backend_id, backend_thresholds=thresholds,
        candidate_cap=cap, calibrated_cap=cap)


def test_a_threshold_resolves_only_under_its_own_decision_identity():
    key = de.decision_identity(
        "d1-x", de.CURRENT_READOUT_MODE, "mode")
    assert _cfg("d1-x", {key: 0.73}).threshold_for("mode") == pytest.approx(0.73)
    # The same number recorded for ANOTHER consumer's identity is not theirs.
    assert _cfg("d1-x", {key: 0.73}).threshold_for("done") is None
    # And a bare model id is NO LONGER a key (the pre-Wave-3 shape).
    assert _cfg("d1-x", {"d1-x": 0.73}).threshold_for("mode") is None


def test_a_readout_change_kills_the_threshold():
    """AC2.2: the letter-era entry must not resolve under the native readout."""
    legacy_key = de.decision_identity("d1-x", de.LEGACY_READOUT_MODE, "mode")
    cfg = _cfg("d1-x", {legacy_key: 0.73})
    assert cfg.threshold_for("mode") is None, (
        "a threshold measured under the retired letter readout resolved "
        "against the native identity")


def test_a_criteria_edit_kills_the_threshold(monkeypatch):
    """TG-3: an edit to the criteria empties the map for that consumer."""
    key = de.decision_identity("d1-x", de.CURRENT_READOUT_MODE, "mode")
    cfg = _cfg("d1-x", {key: 0.73})
    assert cfg.threshold_for("mode") == pytest.approx(0.73)
    decl = de.CONSUMER_DECLARATIONS["mode"]
    edited = dict(decl.criteria)
    edited["research"] = "Gather information before acting (edited)"
    monkeypatch.setitem(
        de.CONSUMER_DECLARATIONS, "mode",
        de.ConsumerDeclaration(decl.decision_type, edited))
    assert cfg.threshold_for("mode") is None, (
        "a criteria edit left the old threshold resolving")


def test_a_cap_change_kills_the_threshold():
    """AC13.3 at the gate: the same entry stops resolving at a new width."""
    key = de.decision_identity("d1-x", de.CURRENT_READOUT_MODE, "mode", 6)
    cfg = _cfg("d1-x", {key: 0.73}, cap=8)
    assert cfg.threshold_for("mode") is None


# ---------------------------------------------------------------------------
# T3.3 / AC2.3: superseded_flips reads the readout and the criteria
# ---------------------------------------------------------------------------


def _bar(cid, **config):
    return cb.ConsumerBar(
        consumer_id=cid, rows=200, precision=0.95, ece=0.01,
        status="enforced", config=config)


_DEPLOYED = {
    "candidate_cap": 6,
    "backend_id": "d1-3b-ad-q4_k_m",
    "variant": "",
    "readout_mode": de.CURRENT_READOUT_MODE,
}


def test_a_flip_measured_under_the_letter_readout_is_superseded():
    record = {"mode": _bar(
        "mode", candidate_cap=6, backend_id="d1-3b-ad-q4_k_m",
        variant="", readout_mode=de.LEGACY_READOUT_MODE)}
    assert cb.superseded_flips(record, dict(_DEPLOYED)) == ["mode"]


def test_a_flip_measured_under_edited_criteria_is_superseded():
    record = {"mode": _bar(
        "mode", candidate_cap=6, backend_id="d1-3b-ad-q4_k_m",
        variant="", readout_mode=de.CURRENT_READOUT_MODE,
        criteria_hash="stalehash123")}
    out = cb.superseded_flips(
        record, dict(_DEPLOYED),
        criteria_hash_of=lambda cid: de.criteria_hash(cid, 6))
    assert out == ["mode"], "a criteria edit left the old flip standing"


def test_a_flip_measured_at_another_cap_is_superseded():
    record = {"mode": _bar("mode", candidate_cap=8)}
    assert cb.superseded_flips(record, {"candidate_cap": 6}) == ["mode"]


def test_an_unchanged_configuration_keeps_its_flip_and_its_rows():
    """The flip stands ONLY when every compared scalar matches, and the
    record is never mutated to get there."""
    h = de.criteria_hash("mode", 6)
    record = {"mode": _bar(
        "mode", candidate_cap=6, backend_id="d1-3b-ad-q4_k_m",
        variant="", readout_mode=de.CURRENT_READOUT_MODE,
        criteria_hash=h)}
    snapshot = copy.deepcopy({c: b.config for c, b in record.items()})
    out = cb.superseded_flips(
        record, dict(_DEPLOYED),
        criteria_hash_of=lambda cid: de.criteria_hash(cid, 6))
    assert out == []
    assert {c: b.config for c, b in record.items()} == snapshot, (
        "superseded_flips mutated the record - stale rows must stay (AC2.3)")


def test_a_sampled_consumer_is_never_reported_superseded_yet():
    """AC13.8 (stated, not fixed): only `status == "enforced"` is inspected;
    a `sampled` consumer's superseded configuration is a real gap once the
    sampled rung (Wave 5) is live."""
    record = {"mode": cb.ConsumerBar(
        consumer_id="mode", rows=200, precision=0.95, ece=0.01,
        status="sampled",
        config={"candidate_cap": 8, "readout_mode": de.LEGACY_READOUT_MODE})}
    assert cb.superseded_flips(record, dict(_DEPLOYED)) == []
