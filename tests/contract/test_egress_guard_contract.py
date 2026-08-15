"""T4a — Adversarial egress-guard tests (REQ-5 AC1-AC5).

One test per refusal class, plus a redirect chain terminating at loopback and
an IPv6-mapped private address. Each test is PROVEN FAILABLE: the assertion is
``pytest.raises(EgressRefused)`` with the specific rule — if the corresponding
rule in ``_classify`` / the scheme allowlist is removed, the guard stops
raising and the test goes RED. A guard whose test cannot fail is
indistinguishable from no guard (design.md "Egress guard").

These are the feature's primary security evidence. They never hit live web:
address-class cases use literal IPs (no resolution), and the redirect-chain
case uses a MockTransport whose guard checks still run against the real
resolver.
"""

import asyncio

import httpx
import pytest

from backend.proxy.egress_guard import (
    EgressRefused,
    acheck_hop,
    acheck_url,
    check_url,
)
from backend.proxy.fetch_client import fetch_with_guard


# ── REQ-5 AC3: scheme allowlist ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "data:text/html,<h1>hi</h1>",
        "gopher://example.com/1",
        "javascript:alert(1)",
        "ws://example.com/socket",
    ],
)
def test_scheme_refused(url):
    """AC3: only http/https are allowed; every other scheme is refused."""
    with pytest.raises(EgressRefused) as ei:
        check_url(url)
    assert ei.value.rule == "scheme"


# ── REQ-5 AC1: address-class rejection ──────────────────────────────────────


def test_loopback_refused():
    with pytest.raises(EgressRefused) as ei:
        check_url("http://127.0.0.1:8000/admin")
    assert ei.value.rule == "loopback"


def test_loopback_v6_refused():
    with pytest.raises(EgressRefused) as ei:
        check_url("http://[::1]:8000/admin")
    assert ei.value.rule == "loopback"


def test_private_v4_refused():
    for ip in ("10.0.0.1", "172.16.0.1", "192.168.1.1"):
        with pytest.raises(EgressRefused) as ei:
            check_url(f"http://{ip}/x")
        assert ei.value.rule == "private"


def test_link_local_refused():
    # 169.254.169.254 is the cloud metadata endpoint — the classic SSRF target.
    with pytest.raises(EgressRefused) as ei:
        check_url("http://169.254.169.254/latest/meta-data/")
    assert ei.value.rule == "link_local"


def test_unique_local_v6_refused():
    with pytest.raises(EgressRefused) as ei:
        check_url("http://[fd00::1]/x")
    assert ei.value.rule == "private"  # fc00::/7 is private in ipaddress


def test_multicast_refused():
    with pytest.raises(EgressRefused) as ei:
        check_url("http://224.0.0.1/x")
    assert ei.value.rule == "multicast"


def test_ipv6_mapped_private_refused():
    """::ffff:10.0.0.1 is an IPv6-mapped IPv4 private address — must be caught."""
    with pytest.raises(EgressRefused) as ei:
        check_url("http://[::ffff:10.0.0.1]/x")
    assert ei.value.rule == "private"


def test_ipv6_mapped_loopback_refused():
    with pytest.raises(EgressRefused) as ei:
        check_url("http://[::ffff:127.0.0.1]/x")
    assert ei.value.rule == "loopback"


def test_public_address_allowed():
    # A genuinely public address passes the guard.
    checked = check_url("http://93.184.216.34/")
    assert checked.address == "93.184.216.34"


# ── REQ-5 AC2: per-hop re-check (redirect chain terminating at loopback) ──────


def test_redirect_chain_terminating_at_loopback_refused():
    """A public-looking first hop that redirects to 127.0.0.1 is refused.

    The MockTransport simulates an upstream server that 302s to a loopback
    target. The guard checks run against the REAL resolver: the initial URL
    resolves public (93.184.216.34), passes hop 1, then the redirect Location
    http://127.0.0.1:9/ is re-checked and refused at hop 2. If the per-hop
    re-check (REQ-5 AC2) were removed, the client would follow to loopback and
    return 200 — this test would go red.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        # The fetch binds to the checked address (93.184.216.34) with the real
        # Host header; simulate an upstream that redirects to loopback.
        return httpx.Response(
            302,
            headers={"Location": "http://127.0.0.1:9999/private"},
        )

    transport = httpx.MockTransport(handler)
    result = asyncio.run(
        fetch_with_guard(
            "http://93.184.216.34/start",
            transport=transport,
            max_redirects=5,
        )
    )
    assert result.ok is False
    assert "refused" in (result.error or "").lower()
    assert result.hops >= 1


def test_redirect_chain_depth_bounded():
    """A chain longer than max_redirects is aborted (REQ-5 AC4)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://93.184.216.34/next"})

    transport = httpx.MockTransport(handler)
    result = asyncio.run(
        fetch_with_guard(
            "http://93.184.216.34/start",
            transport=transport,
            max_redirects=2,
        )
    )
    assert result.ok is False
    assert "redirect depth" in (result.error or "").lower()


def test_response_size_bounded():
    """A response larger than max_bytes is refused (REQ-5 AC4)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 100_000)

    transport = httpx.MockTransport(handler)
    result = asyncio.run(
        fetch_with_guard(
            "http://93.184.216.34/big",
            transport=transport,
            max_bytes=10_000,
        )
    )
    assert result.ok is False
    assert "too large" in (result.error or "").lower()


# ── Async variants (used by the proxy endpoint) ───────────────────────────────


def test_acheck_url_refuses_loopback():
    async def _run():
        with pytest.raises(EgressRefused) as ei:
            await acheck_url("http://127.0.0.1:8000/x")
        return ei.value.rule

    assert asyncio.run(_run()) == "loopback"


def test_acheck_hop_refuses_private():
    async def _run():
        with pytest.raises(EgressRefused) as ei:
            await acheck_hop("http://10.0.0.1/x")
        return ei.value.rule

    assert asyncio.run(_run()) == "private"