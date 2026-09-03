"""Phase 1.1 — retry_with_backoff resilience module (B1 + RC3).

Tests the async twin directly (the sync twin shares the same classification
logic). Transient errors are retried with backoff; permanent errors fail fast.
"""
import asyncio

import pytest

from backend.agent.resilience import retry_with_backoff


@pytest.mark.asyncio
async def test_transient_error_retried():
    """B1: transient errors MUST be retried with backoff."""
    call_count = 0

    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("transient")
        return "success"

    result = await retry_with_backoff(flaky, max_retries=3, base=0.01, cap=0.1)
    assert result == "success"
    assert call_count == 3


@pytest.mark.asyncio
async def test_permanent_error_not_retried():
    """B1: permanent errors MUST fail immediately."""
    call_count = 0

    async def bad_params():
        nonlocal call_count
        call_count += 1
        raise ValueError("bad params")

    with pytest.raises(ValueError):
        await retry_with_backoff(bad_params, max_retries=3, base=0.01)
    assert call_count == 1  # no retry


@pytest.mark.asyncio
async def test_max_retries_exhausted():
    """B1: after max retries, the last error MUST be raised."""
    async def always_fail():
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        await retry_with_backoff(always_fail, max_retries=2, base=0.01, cap=0.1)
