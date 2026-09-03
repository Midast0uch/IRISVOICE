"""
Contract test: REQ-11 graded fallback scorer (T19).

Pins the measured-data choice for the encoder-absent fallback:
F1 token-overlap, chosen against the labeled 11-case probe at
backend/tests/data/verification_probe.json (REQ-11 Open Question —
"chosen from measured data, not guessed").

Asserts:
- AC1: the fallback is GRADED — a paraphrase scores strictly between the
  genuine-failure score and 1.0, never binary 0/1.
- AC1 (probe separation): on the labeled probe, paraphrase scores exceed
  genuine_failure scores, and vocab_overlap_no_satisfaction (assertion
  words echoed but the action failed) stays BELOW the 0.8 VERIFIED band —
  the binary substring scorer returned 1.0 for those, a false positive.
- AC2: the 0.8 / 0.3 bands and VERIFIED/UNVERIFIED/FAILED labels remain
  unchanged (CONTRACT LOCK CT-E3/CT-E5).
- AC3: scorer_tag stays observable ("fallback" vs "semantic").
- AC4: the bare-stub guard scores 0.0 unconditionally, before the scorer.
- AC5: when both encoder and fallback produce scores, the encoder's score
  is returned with tag "semantic" — never averaged with the fallback.
- AC6: the verifier's surface returns only (score, scorer_tag) — no
  trust/channel field is added or read (trust stays out of the verifier).

Run: python -m pytest backend/tests/contract/test_graded_fallback_scorer.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.agent.verifier import SemanticVerifier

_PROBE = Path(__file__).resolve().parents[1] / "data" / "verification_probe.json"


def _fallback() -> SemanticVerifier:
    """A verifier with NO encoder — always the graded F1 fallback."""
    return SemanticVerifier(encoder_fn=None)


def _fallback_score(expected: str, result: str) -> float:
    frac, tag = _fallback().verified_fraction(expected, result)
    assert tag == "fallback", f"encoder-less verifier must tag fallback, got {tag!r}"
    return frac


# ---------------------------------------------------------------------------
# AC1: graded, not binary
# ---------------------------------------------------------------------------

def test_fallback_is_graded_not_binary():
    """A partial overlap scores strictly between 0 and 1, and a paraphrase
    scores above a genuine failure and below the perfect-match ceiling."""
    frac = _fallback_score(
        "email notification was sent",
        "the email notification was sent successfully",
    )
    assert 0.0 < frac < 1.0, (
        f"graded fallback must return an intermediate score, got {frac}"
    )


def test_paraphrase_scores_above_genuine_failure():
    """A mostly-correct paraphrase is NOT scored identically to a completely
    wrong answer (REQ-11 user story)."""
    paraphrase = _fallback_score(
        "compute the total price including taxes",
        "the final cost with tax added was calculated",
    )
    failure = _fallback_score(
        "compute the total price including taxes",
        "the database connection timed out and the operation was aborted",
    )
    assert paraphrase > failure, (
        f"paraphrase {paraphrase} must outscore genuine failure {failure}"
    )


# ---------------------------------------------------------------------------
# AC1 (probe): measured separation on the labeled 11-case sample
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label", ["paraphrase", "genuine_failure",
                                   "bare_stub", "well_phrased_stub",
                                   "vocab_overlap_no_satisfaction"])
def test_probe_is_present(label):
    """The labeled probe the algorithm was chosen from must exist and
    contain every label it documents."""
    cases = json.loads(_PROBE.read_text(encoding="utf-8"))
    assert any(c["label"] == label for c in cases), f"probe missing label {label!r}"


def test_probe_vocab_overlap_stays_below_verified_band():
    """The binary substring scorer returned 1.0 (VERIFIED) for results that
    merely echo the assertion's words while the action actually failed.
    The graded fallback must keep those BELOW 0.8 (REQ-11 AC1, AC7)."""
    cases = json.loads(_PROBE.read_text(encoding="utf-8"))
    for c in cases:
        if c["label"] != "vocab_overlap_no_satisfaction":
            continue
        frac = _fallback_score(c["expected"], c["result"])
        assert frac < 0.8, (
            f"vocab_overlap_no_satisfaction scored {frac} >= 0.8 (would "
            f"VERIFY) for {c['expected']!r} vs {c['result']!r} — the "
            "graded fallback must not reproduce the binary false positive"
        )


def test_probe_separation_paraphrase_vs_failure():
    """On the labeled probe, every paraphrase outscores every genuine
    failure (the class separation the measurement justified F1 with)."""
    cases = json.loads(_PROBE.read_text(encoding="utf-8"))
    paraphrases = [_fallback_score(c["expected"], c["result"])
                   for c in cases if c["label"] == "paraphrase"]
    failures = [_fallback_score(c["expected"], c["result"])
                for c in cases if c["label"] == "genuine_failure"]
    assert paraphrases and failures
    assert min(paraphrases) > max(failures), (
        f"paraphrase min {min(paraphrases):.3f} must exceed "
        f"failure max {max(failures):.3f} (probe separation)"
    )


# ---------------------------------------------------------------------------
# AC2: band thresholds and labels are CONTRACT LOCK (CT-E3/CT-E5)
# ---------------------------------------------------------------------------

def test_band_thresholds_unchanged():
    """The 0.8 / 0.3 boundaries and labels are CONTRACT LOCK (CT-E3/CT-E5)
    and are pinned in test_der_band_contract.py (via a mocked
    _verified_fraction). Here we assert the graded scorer's own extremes
    that feed those bands: perfect token match → 1.0, no overlap → 0.0,
    and a partial match stays strictly inside (0, 1)."""
    perfect = _fallback_score("returns the total", "the total returns")
    none = _fallback_score("returns the total", "nothing relevant happened")
    partial = _fallback_score("returns the total", "the total was partly computed")
    assert perfect == 1.0
    assert none == 0.0
    assert 0.0 < partial < 1.0


# ---------------------------------------------------------------------------
# AC3: scorer_tag observable
# ---------------------------------------------------------------------------

def test_scorer_tag_fallback_observable():
    frac, tag = _fallback().verified_fraction(
        "send the email", "the email was sent"
    )
    assert tag == "fallback"
    assert 0.0 <= frac <= 1.0


def test_scorer_tag_semantic_when_encoder_present():
    encoder = lambda a, r: 0.9  # noqa: E731
    verifier = SemanticVerifier(encoder_fn=encoder)
    frac, tag = verifier.verified_fraction("send the email", "the email was sent")
    assert tag == "semantic"
    assert frac == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# AC4: stub guard unconditional (CT-E4)
# ---------------------------------------------------------------------------

def test_bare_stub_scores_zero_unconditionally():
    """A bare stub is 0.0 even with a perfect encoder — the guard fires
    before the scorer is consulted."""
    encoder = lambda a, r: 1.0  # noqa: E731
    verifier = SemanticVerifier(encoder_fn=encoder)
    frac, _ = verifier.verified_fraction("send the email", "[step 1 completed]")
    assert frac == 0.0


# ---------------------------------------------------------------------------
# AC5: encoder preferred, never averaged
# ---------------------------------------------------------------------------

def test_encoder_preferred_over_fallback_when_disagreeing():
    """When the encoder and fallback disagree, the encoder's score is
    returned untouched — never blended with the fallback."""
    encoder = lambda a, r: 0.15  # noqa: E731  (deliberately lower than F1)
    verifier = SemanticVerifier(encoder_fn=encoder)
    frac, tag = verifier.verified_fraction(
        "email notification was sent",
        "the email notification was sent successfully",
    )
    assert tag == "semantic"
    assert frac == pytest.approx(0.15), (
        "encoder's score must be returned as-is, not averaged with the "
        "fallback's ~0.8 (REQ-11 AC5)"
    )


# ---------------------------------------------------------------------------
# AC6: no trust/channel field on the verifier surface
# ---------------------------------------------------------------------------

def test_verifier_surface_returns_only_score_and_tag():
    """The verifier returns exactly (score, scorer_tag) — REQ-11 AC6 / REQ-22:
    no trust, channel, or zone field may be added to or read from this
    surface. Trust assignment lives in kyudo.py, never here."""
    import inspect

    src = inspect.getsource(SemanticVerifier)
    for forbidden in ("HyphaChannel", "CellWall", "trust", "channel", "zone"):
        # "trust" appears in docstrings as prose; the guard here is that no
        # FIELD/attribute access like .trust / trust= exists in code.
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            assert f".{forbidden}" not in line, (
                f"verifier must not touch {forbidden!r} — found: {stripped}"
            )
            if forbidden in ("trust", "channel", "zone"):
                assert not line.lstrip().startswith(f"{forbidden} ="), (
                    f"verifier must not assign {forbidden!r} — found: {stripped}"
                )
