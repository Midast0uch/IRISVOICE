"""
Unit tests for SemanticVerifier with an injectable fake encoder.

Asserts (REQ-4):
- A paraphrase scores > 0.0 (fails with substring — that's the point).
- A bare stub ("[step 1 completed]") scores exactly 0.0.
- A result that restates the assertion without doing the work does NOT
  score satisfied (assertion not met).
"""

from __future__ import annotations

from backend.agent.verifier import SemanticVerifier


def _make_fake_encoder():
    """Return a callable encoder that returns scores based on heuristics:

    - High similarity (0.90) when the result actually contains evidence of
      the requested action (past/present tense, concrete detail).
    - Low similarity (0.25) when the result only promises or describes
      intent to do the work ("I will …", "I plan to …").
    - No similarity (0.05) when the result is generic completion text.
    """
    _INTENT_MARKERS = {
        "will", "going to", "plan to", "intend to", "aim to",
        "my task is", "i should", "i need to", "i'm supposed to",
    }

    def _score(assertion: str, result: str) -> float:
        r_lower = result.lower()

        # Intent markers → low similarity (promise ≠ action).
        if any(m in r_lower for m in _INTENT_MARKERS):
            return 0.25

        # Generic completion claims → very low similarity.
        _GENERIC = {
            "completed successfully", "finished without errors",
            "all steps done", "task complete", "operation finished",
        }
        if any(g in r_lower for g in _GENERIC):
            return 0.05

        # Concrete evidence that work was done → high similarity.
        a_words = set(assertion.lower().split())
        r_words = set(r_lower.split())
        overlap = len(a_words & r_words)
        if overlap >= 2:
            return 0.90

        # Otherwise moderate.
        return 0.50

    return _score


# ---------------------------------------------------------------------------
# Paraphrase scores above zero (REQ-4 AC1)
# ---------------------------------------------------------------------------

def test_paraphrase_scores_above_zero():
    """A genuine paraphrase of the expected output scores > 0.0.

    Today's substring containment scores this 0.0 because no exact
    substring match exists.  Semantic scoring must fix this gap.
    """
    encoder = _make_fake_encoder()
    verifier = SemanticVerifier(encoder_fn=encoder)

    frac, scorer = verifier.verified_fraction(
        expected="returns the user's email address",
        result="the address was retrieved from the database",
    )

    assert frac > 0.0, (
        f"paraphrase scored {frac}; expected > 0.0 — "
        "substring containment fails here, semantic scoring must not"
    )
    assert scorer == "semantic"


def test_paraphrase_completely_different_words():
    """A true paraphrase using entirely different vocabulary scores > 0.0."""
    encoder = _make_fake_encoder()
    verifier = SemanticVerifier(encoder_fn=encoder)

    frac, scorer = verifier.verified_fraction(
        expected="compute the total price including taxes",
        result="the final cost with tax added was calculated",
    )

    assert frac > 0.0, (
        f"paraphrase scored {frac}; expected > 0.0"
    )
    assert scorer == "semantic"


# ---------------------------------------------------------------------------
# Bare stub scores exactly 0.0 (CT-E4)
# ---------------------------------------------------------------------------

def test_bare_stub_scores_zero():
    """A result that is only a stub marker scores exactly 0.0."""
    # Use an encoder that returns 1.0 unconditionally — the stub guard
    # must still produce 0.0 (CT-E4).
    encoder = lambda a, r: 1.0  # noqa: E731
    verifier = SemanticVerifier(encoder_fn=encoder)

    frac, scorer = verifier.verified_fraction(
        expected="returns the user's email address",
        result="[step 1 completed]",
    )

    assert frac == 0.0, (
        f"bare stub scored {frac}; expected 0.0 — "
        "stub guard must not be rescuable by the encoder"
    )


def test_bare_stub_with_variant_format():
    """Variant stub formats are also scored 0.0."""
    encoder = lambda a, r: 1.0  # noqa: E731
    verifier = SemanticVerifier(encoder_fn=encoder)

    frac, scorer = verifier.verified_fraction(
        expected="update the user profile",
        result="[Step 42 Completed]",
    )

    assert frac == 0.0


def test_stub_with_extra_whitespace_is_still_bare():
    """A stub marker surrounded by whitespace only is still a bare stub."""
    encoder = lambda a, r: 1.0  # noqa: E731
    verifier = SemanticVerifier(encoder_fn=encoder)

    frac, scorer = verifier.verified_fraction(
        expected="update the user profile",
        result="  [step 1 completed]  ",
    )

    assert frac == 0.0


# ---------------------------------------------------------------------------
# Restatement without doing the work (CT-E4 — inverse risk)
# ---------------------------------------------------------------------------

def test_intent_restatement_not_satisfied():
    """A result that only states intent / restates the goal does NOT score
    as satisfied (assertion not actually met)."""
    encoder = _make_fake_encoder()
    verifier = SemanticVerifier(encoder_fn=encoder)

    frac, scorer = verifier.verified_fraction(
        expected="returns the user's email address",
        result="I will return the user's email address",
    )

    # The encoder returns 0.25 for promises/intent → well below 0.8.
    assert frac < 0.8, (
        f"intent-only result scored {frac}; expected < 0.8 — "
        "intent ≠ action"
    )


def test_generic_completion_not_satisfied():
    """A vague 'completed successfully' with no specific evidence scores
    low."""
    encoder = _make_fake_encoder()
    verifier = SemanticVerifier(encoder_fn=encoder)

    frac, scorer = verifier.verified_fraction(
        expected="returns the user's email address",
        result="The task completed successfully without any errors",
    )

    assert frac < 0.8, (
        f"generic completion scored {frac}; expected < 0.8"
    )
