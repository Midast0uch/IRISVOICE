"""
Contract tests for RateLimitedError (REQ-3 AC1, REQ-4 AC1).

Pins the boundary contract:
  * RateLimitedError shape (provider_id, attempts, retry_after) — any consumer
    (DER ledger, agent_kernel) depends on these fields.
  * resilience.NO_RETRY_ERRORS MUST contain RateLimitedError so the DER layer
    does not re-wrap a rate-limited step in retry_with_backoff_sync (which would
    hammer the provider harder).

A contract break here is caught at the interface, BEFORE behavior.
"""
import pytest

from backend.agent.inference.errors import RateLimitedError
from backend.agent.resilience import NO_RETRY_ERRORS, retry_with_backoff_sync


def test_rate_limited_error_shape():
    _e = RateLimitedError(provider_id="openai:gpt-4o", attempts=3, retry_after=2.5)
    assert _e.provider_id == "openai:gpt-4o"
    assert _e.attempts == 3
    assert _e.retry_after == 2.5
    assert "openai:gpt-4o" in str(_e)
    assert "3" in str(_e)


def test_rate_limited_error_optional_retry_after():
    _e = RateLimitedError(provider_id="p", attempts=1)
    assert _e.retry_after is None
    assert "no Retry-After" in str(_e)


def test_no_retry_errors_contains_rate_limited():
    # REQ-4 AC1: RateLimitedError must be in NO_RETRY_ERRORS so the DER layer
    # surfaces it immediately instead of retrying.
    assert RateLimitedError in NO_RETRY_ERRORS


def test_retry_with_backoff_does_not_retry_rate_limited():
    """REQ-4 AC1: retry_with_backoff_sync must NOT retry a RateLimitedError —
    it should re-raise immediately (single authority, no hammering)."""
    _calls = {"n": 0}

    def _fn():
        _calls["n"] += 1
        raise RateLimitedError(provider_id="p", attempts=3)

    with pytest.raises(RateLimitedError):
        retry_with_backoff_sync(_fn, max_retries=2, label="test")
    # Must NOT have retried — exactly one call.
    assert _calls["n"] == 1
