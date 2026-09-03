"""Shared retry / timeout / breaker utilities for DER and skill execution.

Phase 1.1 (B1 + RC3) of the DER+PACMAN execution-hardening plan.

Two twins are provided:

* ``retry_with_backoff`` — async, uses ``asyncio.sleep``. Use it inside a
  running event loop (concurrent gather, skill execution).
* ``retry_with_backoff_sync`` — sync, uses ``time.sleep``. Use it in the DER
  loop, which runs inside ``run_in_executor`` (a thread-pool thread) and whose
  step executor (``_der_run_step_execution``) itself calls ``asyncio.run()``
  internally. Wrapping that in another ``asyncio.run`` would nest event loops
  and raise ``RuntimeError``, so the sync twin keeps the thread model intact.

Both classify failures:
* TRANSIENT_ERRORS are retried with exponential backoff + jitter.
* PERMANENT_ERRORS fail fast (no retry).
* Any other Exception is treated as permanent and re-raised immediately.
"""

import asyncio
import logging
import random
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")

# Transient error types — safe to retry
TRANSIENT_ERRORS = (asyncio.TimeoutError, ConnectionError, OSError, TimeoutError)

# Permanent error types — fail fast to graft
PERMANENT_ERRORS = (ValueError, PermissionError, FileNotFoundError, KeyError)

# Do-not-retry errors — the DER layer must surface these immediately instead of
# re-wrapping them in retry_with_backoff(_sync). RateLimitedError is the prime
# member: retrying a rate-limited step at the DER layer just hammers the
# provider harder (REQ-4 AC1). The transport already performed its own bounded
# 429 retries; a RateLimitedError means those are exhausted, so the step should
# fail fast and be reported honestly.
try:  # imported lazily to avoid an import cycle with the inference layer
    from backend.agent.inference.errors import RateLimitedError

    NO_RETRY_ERRORS = (RateLimitedError,)
except Exception:  # pragma: no cover — defensive; errors module is local
    NO_RETRY_ERRORS = ()


async def retry_with_backoff(
    fn: Callable[[], "T"],
    *,
    max_retries: int = 3,
    base: float = 1.0,
    cap: float = 8.0,
    jitter: bool = True,
    label: str = "unknown",
) -> "T":
    """Execute ``fn`` with exponential backoff on transient errors.

    Defaults match existing codebase convention:
    - base=1.0 matches agent_kernel.py:2230 sleep(1.0 * 2**attempt)
    - cap=8.0 gives delays of 1s -> 2s -> 4s -> 8s
    - max_retries=3 matches mcp/server_manager.py max_restart_attempts

    Permanent errors (ValueError, PermissionError, etc.) are raised immediately.
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except NO_RETRY_ERRORS:
            raise  # do-not-retry — surface immediately (REQ-4 AC1)
        except PERMANENT_ERRORS:
            raise  # fail fast — no retry
        except TRANSIENT_ERRORS as e:
            last_error = e
            if attempt == max_retries:
                break
            delay = min(cap, base * (2 ** attempt))
            if jitter:
                delay *= 1 + random.random() * 0.3
            logger.warning(
                "[resilience] %s: transient error (attempt %d/%d), "
                "retrying in %.1fs: %s",
                label, attempt + 1, max_retries, delay, e,
            )
            await asyncio.sleep(delay)
        except Exception as e:
            # Unknown error — treat as permanent
            raise
    raise last_error


def retry_with_backoff_sync(
    fn: Callable[[], "T"],
    *,
    max_retries: int = 3,
    base: float = 1.0,
    cap: float = 8.0,
    jitter: bool = True,
    label: str = "unknown",
) -> "T":
    """Sync twin of :func:`retry_with_backoff` for thread-pool contexts.

    Uses ``time.sleep`` instead of ``asyncio.sleep`` so it composes with
    callables that themselves call ``asyncio.run()`` internally (no nested
    event loops). Same transient/permanent classification as the async twin.
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except NO_RETRY_ERRORS:
            raise  # do-not-retry — surface immediately (REQ-4 AC1)
        except PERMANENT_ERRORS:
            raise  # fail fast — no retry
        except TRANSIENT_ERRORS as e:
            last_error = e
            if attempt == max_retries:
                break
            delay = min(cap, base * (2 ** attempt))
            if jitter:
                delay *= 1 + random.random() * 0.3
            logger.warning(
                "[resilience] %s: transient error (attempt %d/%d), "
                "retrying in %.1fs: %s",
                label, attempt + 1, max_retries, delay, e,
            )
            time.sleep(delay)
        except Exception as e:
            # Unknown error — treat as permanent
            raise
    raise last_error
