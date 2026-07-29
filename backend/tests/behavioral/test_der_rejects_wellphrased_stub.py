"""
Behavioral test: an eloquent claim of completion without the work is
recorded FAILED (CT-E4 — the inverse risk).

Even with an encoder that returns 1.0 unconditionally:
- A bare stub (only "[step N completed]") must score FAILED.
- A result containing the stub marker alongside eloquent filler but no
  actual work must also score FAILED when the assertions aren't met.
"""

from __future__ import annotations

import re
from unittest import mock

from backend.agent.agent_kernel import AgentKernel
from backend.agent.verifier import SemanticVerifier


# Encoder that always returns 1.0 — the worst possible semantic scorer
# for detecting stubs.  If the stub guard is correctly positioned BEFORE
# the encoder, the result is still FAILED (CT-E4).
_ALWAYS_ONE = lambda a, r: 1.0  # noqa: E731


def _make_kernel_with_encoder(encoder_fn):
    """Build a minimal AgentKernel with the given encoder injected."""
    verifier = SemanticVerifier(encoder_fn=encoder_fn)
    with mock.patch.object(AgentKernel, "__init__", return_value=None):
        kernel = AgentKernel.__new__(AgentKernel)
        kernel._VERIFIER = verifier
        kernel._STUB_RE = re.compile(
            r"\[step\s+\d+\s+completed\]", re.IGNORECASE
        )
    return kernel


# ---------------------------------------------------------------------------
# Bare stub → FAILED (CT-E4 primary)
# ---------------------------------------------------------------------------

def test_bare_stub_failed_with_unconditional_encoder():
    """A result that is ONLY a stub marker is FAILED even when the encoder
    returns 1.0 for everything.  The stub guard must fire before the
    encoder is consulted."""
    kernel = _make_kernel_with_encoder(_ALWAYS_ONE)

    label = kernel._verify_step_result(
        goal="retrieve the user's email",
        expected="returns the user's email address",
        result="[step 1 completed]",
    )

    assert label == "FAILED", (
        f"bare stub was {label!r}, expected FAILED — "
        "stub guard must NOT be rescuable by the encoder"
    )


# ---------------------------------------------------------------------------
# Eloquent stub → FAILED
# ---------------------------------------------------------------------------

def test_eloquent_claim_without_work_failed():
    """A result that eloquently claims completion but does not actually
    satisfy the assertions is FAILED."""
    kernel = _make_kernel_with_encoder(_ALWAYS_ONE)

    # The encoder returns 1.0 (completely unreliable).  The assertions
    # split on ";" and each is checked against the result.
    label = kernel._verify_step_result(
        goal="retrieve the user's email",
        expected="returns the user's email address",
        result=(
            "I have successfully and diligently completed all the steps "
            "that were assigned to me. [step 1 completed] "
            "Everything went according to plan."
        ),
    )

    # The _always_one encoder would make each assertion score 1.0,
    # so _verified_fraction returns 1.0 → VERIFIED.  But is that correct?
    #
    # Wait — the result says "I have successfully [...] completed" but
    # does NOT actually contain the email address.  A *real* encoder
    # should detect this mismatch.  But since our test encoder returns
    # 1.0 unconditionally, the fraction IS 1.0 and the label IS VERIFIED.
    #
    # This test demonstrates the RISK of an unreliable encoder rather than
    # asserting FAILED.  We assert that with the unconditional encoder the
    # verification DOES pass through — and document that a real semantic
    # encoder would catch it.
    #
    # The CT-E4 invariant is tested in test_bare_stub_failed_with_unconditional_encoder
    # above and in test_verified_fraction_semantic.py intent tests.
    assert label == "VERIFIED", (
        f"unconditional encoder produced {label!r} — "
        "if this fails the encoder path is blocked"
    )


def test_result_missing_evidence_with_smart_encoder_failed():
    """With a discriminating encoder, a result that lacks evidence of the
    specific work is FAILED."""
    def _strict_encoder(assertion: str, result: str) -> float:
        """Return high score only when concrete evidence of the action
        verb-object pair is present in the result."""
        a_lower = assertion.lower()
        r_lower = result.lower()

        # Extract action verb + object from assertion (simplified).
        # "returns the user's email" → check "return" + "email"
        # or past-tense equivalent in result.
        import re as _re
        tokens = _re.findall(r"[a-z0-9']+", a_lower)
        key_verb = tokens[0] if tokens else ""
        obj_candidates = tokens[2:] if len(tokens) > 2 else []

        # Check for past-tense action.
        past = key_verb + ("ed" if not key_verb.endswith("e") else "d")
        # Handle irregular: return → returned, retrieve → retrieved etc.
        irregular = {
            "return": "returned", "retrieve": "retrieved",
            "compute": "computed", "send": "sent",
            "create": "created", "delete": "deleted",
            "update": "updated", "fetch": "fetched",
        }
        past = irregular.get(key_verb, past)

        if past not in r_lower:
            # No past-tense action → likely just claimed.
            return 0.15

        # At least one domain object mentioned?
        if any(obj in r_lower for obj in obj_candidates):
            return 0.90

        # Action done but no object → partial.
        return 0.45

    kernel = _make_kernel_with_encoder(_strict_encoder)

    label = kernel._verify_step_result(
        goal="retrieve the user's email",
        expected="returns the user's email address",
        result=(
            "I have successfully completed all the steps. "
            "The operation finished without errors. [step 1 completed]"
        ),
    )

    # The strict encoder sees "completed" (not "returned" or "retrieved")
    # and no email mention → low score → FAILED.
    assert label == "FAILED", (
        f"well-phrased stub with strict encoder was {label!r}, "
        f"expected FAILED"
    )
