"""Inference-layer error types.

Kept separate from ``transport.py`` so that ``resilience.py`` can import the
classification without pulling in the transport layer (which would create the
cycle ``resilience`` ← ``agent_kernel`` → ``inference.router`` →
``inference.transport``).

The single most important type here is :class:`RateLimitedError`: it is raised
when every rate-limit retry attempt is exhausted, and it MUST NOT be caught and
replaced with a placeholder string by the transport. The DER loop reports it
honestly (see ``specs/der-loop-integrity-display`` REQ-1 and
``specs/caducean-phase-scheduler`` REQ-3).
"""

from typing import Optional


class RateLimitedError(RuntimeError):
    """Raised when a provider refuses a request with HTTP 429 and all
    configured retry attempts are exhausted.

    Carries enough context for the DER loop to report the real cause to the
    user instead of fabricating an acknowledgement (the historical bug returned
    the literal string ``"(I see.)"`` after exhausted retries).

    Attributes:
        provider_id: The provider instance id that refused the request.
        attempts: How many HTTP attempts were made before giving up.
        retry_after: The server-supplied ``Retry-After`` delay in seconds, if
            any was observed. ``None`` when the provider sent no such header.
    """

    def __init__(
        self,
        provider_id: str,
        attempts: int,
        retry_after: Optional[float] = None,
    ) -> None:
        self.provider_id = provider_id
        self.attempts = attempts
        self.retry_after = retry_after
        _hint = (
            f"retry after {retry_after:.1f}s" if retry_after is not None
            else "no Retry-After supplied"
        )
        super().__init__(
            f"RateLimitedError: provider={provider_id} attempts={attempts} ({_hint})"
        )
