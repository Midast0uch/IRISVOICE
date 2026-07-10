"""Shared SSL context for outbound API calls.

On Windows, Python's ssl.create_default_context() uses Schannel, which
performs certificate *revocation* checking (OCSP/CRL). In some corporate /
offline environments that revocation check fails with
CRYPT_E_NO_REVOCATION_CHECK and either hangs or rejects the TLS handshake
outright — even for perfectly valid certs (e.g. api.cerebras.ai). This makes
every LLM / crawler call to a remote provider hang with no response.

The fix: keep full certificate + hostname verification (CA trust is intact)
but disable the revocation step, which is an availability check, not an
authenticity check. This restores connectivity without weakening trust.
"""
from __future__ import annotations

import ssl
from typing import Optional


def build_ssl_context() -> ssl.SSLContext:
    """Return an SSLContext with CA verification but no revocation check."""
    ctx = ssl.create_default_context()
    # Drop revocation checking (the part that hangs/fails on Windows Schannel).
    # VERIFY_DEFAULT already requires a valid CA-signed cert + hostname match;
    # we only remove the CRL/OCSP step.
    try:
        ctx.verify_flags = ssl.VERIFY_DEFAULT & ~getattr(ssl, "VERIFY_CRL_CHECK_CHAIN", 0)
    except Exception:
        # Some OpenSSL builds expose VERIFY_CRL_CHECK_LEAF instead.
        try:
            ctx.verify_flags = ssl.VERIFY_DEFAULT & ~getattr(ssl, "VERIFY_CRL_CHECK_LEAF", 0)
        except Exception:
            pass
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


# Module-level singleton — reused by all httpx clients so we don't rebuild
# the context (and re-load the CA bundle) on every request.
_SSL_CONTEXT: Optional[ssl.SSLContext] = None


def get_ssl_context() -> ssl.SSLContext:
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        _SSL_CONTEXT = build_ssl_context()
    return _SSL_CONTEXT
