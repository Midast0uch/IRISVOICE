"""
Unit tests for encoder fallback in SemanticVerifier.

When the encoder is unavailable / raises an error / times out, the
verifier must fall back to substring containment and log ``scorer="fallback"``
(REQ-4 AC4).
"""

from __future__ import annotations

import logging

from backend.agent.verifier import SemanticVerifier


# ---------------------------------------------------------------------------
# Encoder unavailable (None)
# ---------------------------------------------------------------------------

def test_encoder_none_falls_back_to_substring(caplog):
    """When no encoder is provided (None), substring fallback is used."""
    verifier = SemanticVerifier(encoder_fn=None)

    # _load_default_encoder() will try and fail (no weights present).
    # The internal _encoder_fn will be None → substring fallback.
    with caplog.at_level(logging.INFO):
        frac, scorer = verifier.verified_fraction(
            expected="email notification was sent",
            result="the email notification was sent successfully",
        )

    assert frac == 1.0, (
        f"substring match should score 1.0, got {frac}"
    )
    assert isinstance(frac, float)
    assert 0.0 <= frac <= 1.0


def test_encoder_none_non_match(caplog):
    """With no encoder, a non-matching assertion scores 0.0."""
    verifier = SemanticVerifier(encoder_fn=None)

    frac, scorer = verifier.verified_fraction(
        expected="email notification was sent",
        result="the database was updated",
    )

    assert frac == 0.0


# ---------------------------------------------------------------------------
# Encoder raises exception
# ---------------------------------------------------------------------------

def test_encoder_raises_on_call(caplog):
    """If the encoder raises during scoring, fall back to substring and log."""
    def _broken_encoder(assertion: str, result: str) -> float:
        raise RuntimeError("encoder model crashed")

    verifier = SemanticVerifier(encoder_fn=_broken_encoder)

    with caplog.at_level(logging.WARNING):
        frac, scorer = verifier.verified_fraction(
            expected="email notification was sent",
            result="the email notification was sent",
        )

    assert frac == 1.0, "substring fallback should produce correct score"
    assert scorer == "fallback", "broken encoder must produce fallback tag"


def test_encoder_raises_on_call_logs_warning(caplog):
    """A warning is logged when the encoder errors out."""
    def _broken_encoder(assertion: str, result: str) -> float:
        raise RuntimeError("OOM in encoder")

    verifier = SemanticVerifier(encoder_fn=_broken_encoder)

    with caplog.at_level(logging.WARNING):
        verifier.verified_fraction(
            expected="send the email notification",
            result="the email notification was sent",
        )

    assert "encoder error" in caplog.text.lower()


# ---------------------------------------------------------------------------
# Encoder returns out-of-range value
# ---------------------------------------------------------------------------

def test_encoder_out_of_range_clamped(caplog):
    """Return values outside [0, 1] are clamped."""
    def _wild_encoder(assertion: str, result: str) -> float:
        return 42.0

    verifier = SemanticVerifier(encoder_fn=_wild_encoder)

    frac, scorer = verifier.verified_fraction(
        expected="send the email notification",
        result="the email notification was sent",
    )

    assert frac == 1.0, "out-of-range clamped to 1.0"
    assert scorer == "semantic"
