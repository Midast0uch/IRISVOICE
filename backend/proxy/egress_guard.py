"""Egress guard for the in-app browser fetch proxy (REQ-5, T3/T4).

The proxy is a server-side fetcher whose target is caller-supplied — textbook
SSRF. This module is the guard, and it is PART of the fetch, not a wrapper
around it (design.md "Egress guard").

REQ-5 AC1/AC3/AC4 (T3):
  - scheme allowlist: http/https only; refuse file/ftp/data/gopher/...
  - resolve the host, reject the ADDRESS by class (loopback, private,
    link-local, unique-local, multicast, and IPv6-mapped equivalents)
  - bound response size, total time, and redirect depth; abort cleanly
  - return the CHECKED address so the fetch uses the address that was checked

REQ-5 AC2 (T4):
  - re-check the resolved address after EVERY redirect hop, not only the
    initial URL. The HTTP client must NOT auto-follow redirects; the caller
    drives each hop through ``check_hop`` and only proceeds when it passes.

The subtle failure this defends against is DNS rebinding: a hostname that
resolves public on the check and private on the fetch. Resolving here and
returning the concrete address means the fetch binds to the checked address,
not a re-resolved name.

Every refusal is logged with the target and the specific rule (AC5) and
surfaced to the page as a NON-specific failure (the caller decides the exact
message; this module only classifies).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Scheme allowlist (REQ-5 AC3).
ALLOWED_SCHEMES = frozenset({"http", "https"})

# Bounds (REQ-5 AC4). Overridable for tests.
MAX_RESPONSE_BYTES = int(__import__("os").environ.get("IRIS_PROXY_MAX_BYTES", str(8 * 1024 * 1024)))
MAX_TOTAL_TIME_S = float(__import__("os").environ.get("IRIS_PROXY_MAX_TIME_S", "30"))
MAX_REDIRECT_DEPTH = int(__import__("os").environ.get("IRIS_PROXY_MAX_REDIRECTS", "5"))


class EgressRefused(Exception):
    """A fetch was refused by an egress rule.

    ``rule`` names the specific rule that closed (AC5): one of
    "scheme", "loopback", "private", "link-local", "unique-local",
    "multicast", "unspecified", "reserved", "resolve_failed".
    """

    def __init__(self, rule: str, target: str, detail: str = "") -> None:
        super().__init__(f"egress refused ({rule}): {target} {detail}".strip())
        self.rule = rule
        self.target = target
        self.detail = detail


@dataclass(frozen=True)
class CheckedTarget:
    """A URL whose host has been resolved and validated.

    ``address`` is the concrete IP the fetch MUST use (REQ-5 AC1: the fetch
    uses the address that was checked). ``hostname`` is the original name.
    """

    url: str
    scheme: str
    hostname: str
    port: int
    address: str  # the checked, concrete IP (IPv4 or IPv6 literal)
    family: int  # socket.AF_INET or socket.AF_INET6


def _classify(addr: str) -> Optional[str]:
    """Return the refusal rule for an address, or None if it is public.

    Handles IPv6-mapped IPv4 (``::ffff:127.0.0.1``) by unwrapping to the
    embedded IPv4 before classifying (REQ-5 edge case).
    """
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return "resolve_failed"
    # Unwrap IPv6-mapped IPv4 (::ffff:a.b.c.d) so a private v4 inside a v6
    # literal is caught (REQ-5 edge case).
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link_local"
    if ip.is_private:
        return "private"
    if ip.is_multicast:
        return "multicast"
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_reserved:
        return "reserved"
    return None


def _resolve(host: str) -> list[str]:
    """Resolve a hostname to concrete IP literals (best-effort, all families)."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise EgressRefused("resolve_failed", host, str(exc)) from exc
    addrs: list[str] = []
    for info in infos:
        # info[4] is the sockaddr; for AF_INET it's (ip, port), for AF_INET6
        # it's (ip, port, flowinfo, scopeid).
        sockaddr = info[4]
        ip = sockaddr[0] if sockaddr else ""
        if ip and ip not in addrs:
            addrs.append(ip)
    return addrs


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def check_url(url: str) -> CheckedTarget:
    """Validate a URL's scheme + host and return the checked concrete address.

    Raises ``EgressRefused`` on any refusal. This is the initial-hop check
    (REQ-5 AC1/AC3). For redirect hops use ``check_hop`` (REQ-5 AC2).

    BLOCKING (uses ``socket.getaddrinfo``) — prefer ``acheck_url`` in async
    call paths so DNS resolution never stalls the event loop.
    """
    return _check_with_resolver(url, _resolve)


async def acheck_url(url: str) -> CheckedTarget:
    """Async variant of ``check_url`` for use inside FastAPI/async paths.

    Resolves via the running loop's ``getaddrinfo`` (non-blocking) and applies
    the identical rules. Async/sync boundary discipline: the proxy endpoint
    MUST use this, never ``check_url``.
    """
    loop = asyncio.get_running_loop()
    return await _check_with_resolver_async(url, loop)


def check_hop(url: str) -> CheckedTarget:
    """Validate a redirect-hop URL (REQ-5 AC2).

    Identical rules to ``check_url`` but semantically distinct so the caller
    can log "redirect hop N refused" distinctly. A public URL redirecting to
    127.0.0.1 is refused here, defeating a first-hop-only check.

    BLOCKING — prefer ``acheck_hop`` in async call paths.
    """
    return check_url(url)


async def acheck_hop(url: str) -> CheckedTarget:
    """Async variant of ``check_hop`` (REQ-5 AC2 per-hop re-check)."""
    return await acheck_url(url)


def _check_with_resolver(url: str, resolver) -> CheckedTarget:
    """Shared rule application over a resolved address list (sync resolver)."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise EgressRefused("scheme", url, f"scheme={scheme!r}")
    host = parsed.hostname
    if not host:
        raise EgressRefused("resolve_failed", url, "no hostname")
    port = parsed.port or _default_port(scheme)

    addrs = resolver(host)
    if not addrs:
        raise EgressRefused("resolve_failed", host, "no addresses")
    # Reject if ANY resolved address is non-public (defense in depth: a host
    # that resolves to both public and private is refused outright).
    for addr in addrs:
        rule = _classify(addr)
        if rule is not None:
            raise EgressRefused(rule, host, f"address={addr}")
    # Prefer an IPv4 address for the fetch (simplest, most compatible).
    chosen = next((a for a in addrs if ":" not in a), addrs[0])
    family = socket.AF_INET if ":" not in chosen else socket.AF_INET6
    return CheckedTarget(
        url=url, scheme=scheme, hostname=host, port=port,
        address=chosen, family=family,
    )


async def _resolve_async(host: str, loop) -> list[str]:
    """Async host resolution via the running loop's getaddrinfo."""
    try:
        infos = await loop.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise EgressRefused("resolve_failed", host, str(exc)) from exc
    addrs: list[str] = []
    for info in infos:
        sockaddr = info[4]
        ip = sockaddr[0] if sockaddr else ""
        if ip and ip not in addrs:
            addrs.append(ip)
    return addrs


async def _check_with_resolver_async(url: str, loop) -> CheckedTarget:
    """Async equivalent of ``_check_with_resolver`` (non-blocking resolve)."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise EgressRefused("scheme", url, f"scheme={scheme!r}")
    host = parsed.hostname
    if not host:
        raise EgressRefused("resolve_failed", url, "no hostname")
    port = parsed.port or _default_port(scheme)

    addrs = await _resolve_async(host, loop)
    if not addrs:
        raise EgressRefused("resolve_failed", host, "no addresses")
    for addr in addrs:
        rule = _classify(addr)
        if rule is not None:
            raise EgressRefused(rule, host, f"address={addr}")
    chosen = next((a for a in addrs if ":" not in a), addrs[0])
    family = socket.AF_INET if ":" not in chosen else socket.AF_INET6
    return CheckedTarget(
        url=url, scheme=scheme, hostname=host, port=port,
        address=chosen, family=family,
    )


def is_public_address(addr: str) -> bool:
    """True if ``addr`` is a public (non-refused-class) address."""
    return _classify(addr) is None