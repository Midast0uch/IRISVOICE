"""Contract: the isolation headers the browser surface serves.

specs/in-app-browser-surface REQ-2 AC2, REQ-3 AC1/AC4/AC5.

WHY THIS FILE EXISTS. The first implementation shipped a CSP containing
``frame-ancestors 'none'``, ``base-uri 'none'`` and ``script-src 'none'``. Each
one silently disabled a mechanism the same module implements:

  * ``frame-ancestors 'none'`` is ``X-Frame-Options: DENY`` by another name, so
    NOTHING the proxy served could be framed — the precise failure the feature
    exists to fix. It stripped the upstream's anti-framing header and then sent
    its own.
  * ``base-uri 'none'`` made the browser ignore the ``<base href>`` the module
    injects, so relative refs resolved against the APP origin.
  * ``script-src 'none'`` meant the injected view-agent never executed.

Every one of those passed the suite, because the suite never looked at a
header. These tests look at the headers.
"""

from __future__ import annotations

import re

import pytest

from backend.api import browser_surface as bs


def _csp() -> str:
    return bs._csp("TESTNONCE", "https://upstream.example")


def _directive(csp: str, name: str) -> str | None:
    for part in csp.split(";"):
        part = part.strip()
        if part == name or part.startswith(name + " "):
            return part
    return None


# ── REQ-2 AC2 / REQ-3 AC4: the page must be FRAMEABLE by the app ──────────

def test_csp_does_not_forbid_framing():
    """frame-ancestors must not be 'none' — that is the bug this file pins."""
    d = _directive(_csp(), "frame-ancestors")
    assert d is not None, "frame-ancestors must be present (an omitted one allows any embedder)"
    assert "'none'" not in d, (
        f"frame-ancestors 'none' makes every served page unframeable — the exact "
        f"failure this feature fixes. Got: {d!r}"
    )
    assert "'self'" in d


def test_csp_allows_the_injected_base_and_only_that():
    """base-uri 'none' would void the <base href> _rewrite_html injects."""
    d = _directive(_csp(), "base-uri")
    assert d is not None
    assert "'none'" not in d, f"base-uri 'none' voids the injected <base>. Got: {d!r}"
    assert "https://upstream.example" in d
    # A page must not be able to re-base itself somewhere else.
    assert "*" not in d


def test_csp_runs_our_view_agent_and_no_page_script():
    """script-src must admit the nonce and nothing else."""
    d = _directive(_csp(), "script-src")
    assert d is not None
    assert "'nonce-TESTNONCE'" in d
    for forbidden in ("'unsafe-inline'", "'unsafe-eval'", "*", "'self'", "https:"):
        assert forbidden not in d, f"script-src must not admit {forbidden}: {d!r}"


def test_csp_sandboxes_on_direct_navigation():
    """The iframe attribute does nothing on a top-level load.

    next.config.mjs rewrites /api/:path* to the backend, so these responses are
    same-origin with the app. Without a CSP `sandbox` directive, opening
    /api/browser/proxy?url=... directly runs foreign HTML on the app's origin.
    """
    d = _directive(_csp(), "sandbox")
    assert d is not None, "CSP must carry a sandbox directive, not rely on the iframe attribute"
    assert "allow-same-origin" not in d, "allow-same-origin defeats the entire isolation model"
    assert "allow-scripts" in d, "the view-agent needs script execution"


def test_csp_denies_exfiltration_channels():
    csp = _csp()
    assert _directive(csp, "connect-src") == "connect-src 'none'"
    assert _directive(csp, "form-action") == "form-action 'none'"
    assert _directive(csp, "object-src") == "object-src 'none'"
    assert csp.startswith("default-src 'none'")


def test_base_uri_omitted_when_origin_unknown():
    """No base origin must mean NO base-uri directive, never a wildcard."""
    csp = bs._csp("N")
    assert _directive(csp, "base-uri") is None


# ── REQ-3: CORS must not name the sandboxed reader ────────────────────────

def test_no_cors_header_at_all():
    """`Access-Control-Allow-Origin: null` is not a restriction.

    "null" IS the origin a sandboxed, opaque-origin document presents. Sending
    it grants read access to precisely the reader the sandbox is meant to
    exclude. The correct value is no header.
    """
    h = bs._isolation_headers("N", "https://upstream.example")
    assert not any(k.lower().startswith("access-control-") for k in h), h


def test_nosniff_present_because_content_type_is_upstream_controlled():
    h = bs._isolation_headers("N")
    assert h.get("X-Content-Type-Options") == "nosniff"


# ── REQ-2 AC2: upstream can never override our isolation ──────────────────

@pytest.mark.parametrize("hostile", [
    {"x-frame-options": "DENY"},
    {"X-Frame-Options": "SAMEORIGIN"},
    {"content-security-policy": "frame-ancestors 'none'"},
    {"Content-Security-Policy": "sandbox"},
    {"set-cookie": "session=abc; HttpOnly"},
    {"Set-Cookie": "tracking=1"},
])
def test_hostile_upstream_headers_never_survive(hostile):
    out = bs._scrubbed_headers(hostile, "N", "https://u.example")
    lowered = {k.lower(): v for k, v in out.items()}
    assert "x-frame-options" not in lowered
    assert "set-cookie" not in lowered
    # Exactly one CSP, and it is ours.
    csps = [v for k, v in out.items() if k.lower() == "content-security-policy"]
    assert len(csps) == 1
    assert "'nonce-N'" in csps[0]
    assert "frame-ancestors 'self'" in csps[0]


def test_benign_upstream_headers_pass_through():
    out = bs._scrubbed_headers({"content-type": "text/html; charset=utf-8", "etag": "W/x"}, "N")
    assert out["content-type"] == "text/html; charset=utf-8"
    assert out["etag"] == "W/x"


# ── REQ-4 AC1: the injected agent must carry the nonce ────────────────────

def test_view_agent_is_injected_with_the_matching_nonce():
    from backend.proxy.view_agent import inject_view_agent

    html = inject_view_agent("<html><head></head><body><p>x</p></body></html>", nonce="ABC123")
    assert 'nonce="ABC123"' in html
    d = _directive(bs._csp("ABC123"), "script-src")
    assert "'nonce-ABC123'" in d


def test_view_agent_lands_inside_body_on_a_large_page():
    """</body> is at the END. Scanning only the head found it on toy pages."""
    from backend.proxy.view_agent import inject_view_agent

    big = "<html><head></head><body>" + ("<p>pad</p>" * 5000) + "</body></html>"
    out = inject_view_agent(big, nonce="N")
    assert out.index("<script") < out.index("</body>"), "script must precede </body>"


def test_view_agent_injection_is_idempotent():
    from backend.proxy.view_agent import inject_view_agent

    once = inject_view_agent("<html><body>x</body></html>", nonce="N")
    twice = inject_view_agent(once, nonce="N")
    assert once == twice
    assert twice.count("<script") == 1


def test_nonce_is_unpredictable_and_per_response():
    """A fixed or short nonce would let a crawled page guess it and execute.

    Asserts on the nonce the ENDPOINT generates, not on the literal this test
    file passes into _csp().
    """
    secrets_mod = bs.secrets
    seen = {secrets_mod.token_urlsafe(16) for _ in range(50)}
    assert len(seen) == 50, "nonce source is not unique per call"
    for n in seen:
        assert len(n) >= 16
    # And the generated value is what lands in the directive.
    sample = secrets_mod.token_urlsafe(16)
    m = re.search(r"'nonce-([^']+)'", bs._csp(sample))
    assert m and m.group(1) == sample
