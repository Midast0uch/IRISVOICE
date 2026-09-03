"""Access control for the in-app browser surface endpoints.

specs/in-app-browser-surface REQ-3 (closing the unauthenticated-endpoint gap
found in review, pin_160522ab3740).

THE PROBLEM THIS SOLVES. `/api/browser/proxy` and `/api/browser/capture/...`
had no auth, and the backend binds 0.0.0.0 (start-backend.py). Anyone on the
LAN or the tailnet could drive the proxy or READ EVERY PAGE the agent had
crawled. Two independent gates now apply, and a request must pass BOTH:

  1. ADDRESS  — loopback or tailnet only. A LAN peer is refused outright.
  2. TOKEN    — derived from the Post-Quantum (Dilithium) identity key, i.e.
                the same wallet credential that unlocks the memory DB.

WHY BOTH. The address gate alone trusts the network; anything that lands on
the tailnet inherits full access. The token alone would be replayable from any
network. Neither is sufficient, and they fail independently.

KEY SEPARATION IS DELIBERATE. This token is HKDF'd from the Dilithium key with
its OWN info string — it is NOT the memory key and cannot be used to open the
memory DB, nor can capturing it reveal that key. Reusing one derived secret for
two purposes is how a read-only leak becomes a database compromise.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import os
import secrets
from typing import Optional

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

COOKIE_NAME = "iris_browser_surface"
HEADER_NAME = "X-IRIS-Browser-Token"

# Tailscale's address space: CGNAT v4 (100.64.0.0/10) and its IPv6 ULA prefix.
_TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
_TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")

_token_cache: Optional[str] = None


def _derive_token() -> str:
    """Derive the surface token from the Dilithium identity key.

    Falls back to a per-PROCESS random token when no wallet key is present
    (development). The fallback is random, never a fixed default — a shipped
    constant would be worse than no token at all, because it would look like
    authentication while authenticating nothing.
    """
    global _token_cache
    if _token_cache is not None:
        return _token_cache

    override = os.environ.get("IRIS_BROWSER_SURFACE_TOKEN")
    if override:
        _token_cache = override
        return _token_cache

    try:
        from backend.core.biometric import load_dilithium_private_key

        priv = load_dilithium_private_key()
        if priv:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.hkdf import HKDF

            # DISTINCT info string — see "KEY SEPARATION" in the module docstring.
            derived = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=None,
                info=b"iris-voice-browser-surface-token-v1",
            ).derive(priv)
            _token_cache = derived.hex()
            logger.info("[browser-auth] surface token derived from identity key")
            return _token_cache
    except Exception as exc:  # noqa: BLE001 - never block startup on this
        logger.warning("[browser-auth] identity-key derivation unavailable: %s", exc)

    _token_cache = secrets.token_urlsafe(32)
    logger.warning(
        "[browser-auth] no identity key present — using an ephemeral per-process "
        "token; the browser surface is unavailable to other processes"
    )
    return _token_cache


def client_address_allowed(request: Request) -> bool:
    """Loopback or tailnet only.

    Deliberately reads the SOCKET peer (request.client.host), never
    X-Forwarded-For: that header is attacker-controlled and trusting it would
    let any LAN peer claim a tailnet address.
    """
    host = getattr(getattr(request, "client", None), "host", None)
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return True
    return ip in _TAILNET_V4 or ip in _TAILNET_V6


def token_from(request: Request) -> Optional[str]:
    """An iframe cannot set request headers, so the cookie is the real path.

    The header is accepted too, for callers that are not a frame (tests, tools).
    """
    return request.cookies.get(COOKIE_NAME) or request.headers.get(HEADER_NAME)


def token_valid(presented: Optional[str]) -> bool:
    if not presented:
        return False
    # Constant-time: a plain == leaks the shared prefix length by timing.
    return hmac.compare_digest(presented, _derive_token())


async def require_browser_surface_access(request: Request) -> None:
    """FastAPI dependency enforcing BOTH gates. Refuses without detail."""
    if not client_address_allowed(request):
        peer = getattr(getattr(request, "client", None), "host", "?")
        logger.warning("[browser-auth] refused: address %s not loopback/tailnet", peer)
        # 404, not 403: a wrong-network caller learns nothing about what exists.
        raise HTTPException(status_code=404, detail="not found")
    if not token_valid(token_from(request)):
        logger.warning("[browser-auth] refused: missing or invalid surface token")
        raise HTTPException(status_code=404, detail="not found")


def issue_token() -> str:
    """The token to hand a local caller. Address-gated at the call site."""
    return _derive_token()


def reset_token_cache_for_tests() -> None:
    global _token_cache
    _token_cache = None
