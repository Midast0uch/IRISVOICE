"""In-app browser surface endpoints (specs/in-app-browser-surface).

Two content paths, one sandboxed HTTP serving mechanism (T2 decision):

  GET /api/browser/capture/{job_id}/{page_number}   REQ-1 replay
       - Serves the RAW captured HTML the crawler fetched for that page (the
         exact bytes the agent reasoned over — REQ-1 AC2, never a second live
         fetch). Includes provenance headers (AC4) and the REQ-3 AC4 CSP.
       - "capture unavailable" (AC3): a 404 with an explicit marker, never a
         silent live fallback.

  GET /api/browser/proxy?url=...                      REQ-2 live proxy (T6)
       - Server-side fetch through the egress guard; strips frame-blocking
         headers; rewrites/anchors relative refs; forwards NO credentials.
       - Surfaced in Wave 3 (T6/T7).

Isolation (REQ-3):
  - The iframe the frontend renders these into is sandboxed WITHOUT
    allow-same-origin (T8), so these responses must NOT carry permissive CORS
    toward the app origin (T7) and MUST carry the REQ-3 AC4 CSP. The CSP here
    is defense-in-depth: the frame's opaque origin already blocks same-origin
    access to app resources.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from backend.api.browser_auth import (
    COOKIE_NAME,
    client_address_allowed,
    issue_token,
    require_browser_surface_access,
)
from backend.crawler.capture_store import get_capture_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/browser", tags=["browser-surface"])

# ── REQ-3 AC4 CSP for served content ─────────────────────────────────────
#
# THREE DIRECTIVES HERE ARE LOAD-BEARING IN OPPOSITE DIRECTIONS. An earlier
# revision set `frame-ancestors 'none'`, `base-uri 'none'` and `script-src
# 'none'`, each of which silently disabled a mechanism this file implements:
#
#   frame-ancestors 'none'  is X-Frame-Options: DENY by another name. It made
#       every served page UNFRAMEABLE — the exact failure the feature exists to
#       fix. (The directive that restricts what the page may EMBED is
#       `frame-src`; `frame-ancestors` restricts who may embed the PAGE.)
#   base-uri 'none'         made the browser ignore the <base href> that
#       _rewrite_html injects, so relative refs resolved against the APP origin
#       instead of upstream (REQ-2 AC3 dead).
#   script-src 'none'       stopped the injected view-agent from ever running,
#       so no scroll/ready message could reach the parent (REQ-4 dead).
#
# All three were verified in a real browser, not reasoned about. Do not
# "tighten" any of them back without re-running tests/contract/
# test_browser_surface_headers.py, which pins each one.
#
# What actually provides the isolation:
#   sandbox allow-scripts  — a CSP DIRECTIVE, not just the iframe attribute.
#       This matters because next.config.mjs rewrites /api/:path* to the
#       backend, so these responses are same-origin with the app. The iframe
#       attribute does nothing on a TOP-LEVEL navigation; a user or link
#       opening /api/browser/proxy?url=... directly would otherwise run foreign
#       HTML on the app's origin. The CSP directive applies either way.
#   script-src 'nonce-…'   — runs OUR view-agent and nothing else. Page script
#       never executes, which is a stronger guarantee than the sandbox alone.
_FRAME_ANCESTORS = "'self' tauri://localhost https://tauri.localhost"


def _csp(nonce: str, base_origin: str | None = None) -> str:
    directives = [
        "default-src 'none'",
        # Enforced on direct navigation too — see note above.
        "sandbox allow-scripts",
        f"script-src 'nonce-{nonce}'",
        # External stylesheets must load or every page renders unstyled.
        "style-src 'unsafe-inline' https: http: data:",
        "img-src * data: blob:",
        "font-src * data:",
        "media-src *",
        "connect-src 'none'",
        "frame-src 'none'",
        "object-src 'none'",
        "form-action 'none'",
        f"frame-ancestors {_FRAME_ANCESTORS}",
    ]
    # Allow ONLY the base we inject; a page cannot re-base itself elsewhere.
    if base_origin:
        directives.append(f"base-uri {base_origin}")
    return "; ".join(directives)


def _isolation_headers(nonce: str, base_origin: str | None = None) -> dict:
    """Headers every served response carries, whatever the branch."""
    return {
        "Content-Security-Policy": _csp(nonce, base_origin),
        # Content-Type is passed through from upstream on the proxy path, so
        # the browser must not be allowed to sniff past it.
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        # NOTE: no Access-Control-Allow-Origin. An earlier revision set it to
        # "null" believing that was restrictive — but "null" IS the opaque
        # origin of a sandboxed frame, so it granted read access to exactly the
        # reader it meant to exclude. Omitting the header denies all of them.
    }


def _origin_of(url: str) -> str | None:
    try:
        from urllib.parse import urlsplit

        p = urlsplit(url)
        return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else None
    except Exception:  # noqa: BLE001 - a bad URL simply means no base-uri
        return None


_CAPTURE_UNAVAILABLE = "capture unavailable"


@router.get(
    "/capture/{job_id}/{page_number}",
    response_class=HTMLResponse,
    include_in_schema=False,
    dependencies=[Depends(require_browser_surface_access)],
)
async def capture_replay(job_id: str, page_number: int, request: Request):
    """REQ-1: serve the captured HTML for (job_id, page_number).

    The bytes served are the bytes the crawler stored at fetch time — the
    panel NEVER issues a second request for the same URL (REQ-1 AC2). When no
    capture exists the response is an explicit 404 marked "capture
    unavailable" (REQ-1 AC3) — never a silent live fallback.
    """
    nonce = secrets.token_urlsafe(16)
    capture = get_capture_store().load(job_id, page_number)
    if capture is None:
        logger.warning(
            "[browser-surface] capture unavailable job=%s page=%s",
            job_id, page_number,
        )
        headers = _isolation_headers(nonce)
        headers["X-Capture-Status"] = "unavailable"
        return PlainTextResponse(
            _CAPTURE_UNAVAILABLE, status_code=404, headers=headers,
        )
    # REQ-1 AC4: provenance in the panel chrome (headers the frontend reads).
    headers = _isolation_headers(nonce, _origin_of(capture["url"]))
    headers.update({
        "X-Capture-Status": "available",
        "X-Capture-Url": capture["url"],
        "X-Capture-Fetched-At": capture["fetched_at"],
        "X-Capture-Job-Id": job_id,
        "X-Capture-Page-Number": str(page_number),
    })
    html = capture["html"]
    # REQ-4 (T9): inject the view-agent so the sandboxed frame can speak OUT
    # (scroll/ready). Idempotent; a stripped script degrades to coarse states
    # (REQ-4 AC5) — the replay bytes themselves are never altered otherwise.
    from backend.proxy.view_agent import inject_view_agent

    html = inject_view_agent(html, nonce=nonce)
    return HTMLResponse(content=html, headers=headers)


# ── REQ-2: user-typed URL fetch proxy (T6) ────────────────────────────────
# The proxy is PART of the egress guard: every hop goes through the guard, and
# the fetch binds to the checked address. Responses are scrubbed (frame
# headers stripped, relative refs anchored), credentials are NEVER forwarded,
# and specific failures are surfaced to the panel (REQ-2 AC4).

# Strip these response headers before serving (REQ-2 AC2).
_STRIP_RESPONSE_HEADERS = frozenset({
    "x-frame-options",
    "content-security-policy",  # replaced by ours (REQ-3 AC4)
    "set-cookie",               # never plant cookies from proxied content
    # The fetch client already decoded the body (gzip/deflate); re-serving it
    # with a stale Content-Encoding/length would double-decode or truncate.
    "content-encoding",
    "content-length",
})
# NOTE: there is no _DROP_REQUEST_HEADERS list here on purpose. An earlier
# revision defined one and never referenced it — a guard that looks present
# in review and does nothing. Credentials are excluded structurally instead:
# fetch_client builds a fresh header dict per request and never copies the
# caller's (REQ-3 AC5).


def _rewrite_html(html: str, base_url: str) -> str:
    """Anchor relative references so stylesheets/images resolve (REQ-2 AC3).

    Injects a ``<base href=...>`` right after <head> (or before the first tag).
    Does NOT touch absolute URLs; does not parse/rewrite the body, so the byte
    cost is O(1) for all but the leading chunk. Called AFTER content-encoding
    is already decoded (T6: decode before rewriting).
    """
    base_attr = _html_escape(base_url)
    base_tag = f'<base href="{base_attr}">'
    lower = html[:8192].lower()
    head_idx = lower.find("<head")
    if head_idx != -1:
        end = html.find(">", head_idx)
        if end != -1:
            return html[: end + 1] + base_tag + html[end + 1 :]
    first_tag = html.find("<")
    if first_tag != -1:
        return html[:first_tag] + base_tag + html[first_tag:]
    return base_tag + html


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    )


@router.get(
    "/proxy",
    include_in_schema=False,
    dependencies=[Depends(require_browser_surface_access)],
)
async def fetch_proxy(
    url: str = Query(..., description="http/https URL to fetch"),
):
    """REQ-2: server-side fetch of a user-typed URL through the egress guard.

    Never forwards cookies or Authorization (REQ-3 AC5). Strips frame-blocking
    headers so the sandboxed panel iframe can render (REQ-2 AC2) and anchors
    relative refs (REQ-2 AC3). Specific failures (status, reason) are returned
    in-band for the panel (REQ-2 AC4); the egress guard's refusal is logged
    specifically but surfaced non-specifically (REQ-5 AC5).
    """
    from backend.proxy.fetch_client import fetch_with_guard
    from backend.agent.tool_registry import ToolSpec, capability_denied_by

    nonce = secrets.token_urlsafe(16)

    # REQ-6/T7: the proxy is a server-side fetcher and is gated by the SAME
    # capability gate as crawler_query/open_url — one internet gate for every
    # module (REQ-17 AC3). With the gate closed, the proxy refuses BEFORE any
    # fetch; with it open (or never wired), the module remains optional and DER
    # completion is unaffected.
    denied = capability_denied_by(
        ToolSpec(name="browser_proxy", description="in-app browser fetch proxy", requires_internet=True)
    )
    if denied is not None:
        logger.info("[browser-surface] proxy refused: internet gate closed")
        headers = _isolation_headers(nonce)
        headers["X-Proxy-Error"] = "internet disabled"
        return PlainTextResponse(
            "proxy error: internet access is disabled",
            status_code=403,
            headers=headers,
        )

    # The fetch client sends ONLY User-Agent + Accept (fresh client, no cookie
    # jar, no auth) — user credentials are never forwarded (REQ-3 AC5). The
    # egress guard runs on every hop inside the client.
    result = await fetch_with_guard(url)

    if not result.ok:
        # REQ-2 AC4: surface the SPECIFIC failure in-band so the panel shows
        # status/reason instead of a blank frame.
        reason = result.error or "fetch failed"
        status_code = result.status_code or 502
        headers = _isolation_headers(nonce)
        headers["X-Proxy-Error"] = reason
        return PlainTextResponse(
            f"proxy error: {reason}",
            status_code=status_code,
            headers=headers,
        )

    # Content-type check first: never rewrite/corrupt non-HTML bodies (T6).
    content_type = (result.headers or {}).get("content-type", "")
    status_code = result.status_code or 200
    headers = _scrubbed_headers(result.headers, nonce, _origin_of(result.final_url or url))
    # REQ-2 AC4: surface the SPECIFIC upstream status to the panel (e.g. 404)
    # even when the body itself is served — the panel can show the reason
    # instead of a blank or confusing frame.
    if status_code >= 400:
        headers["X-Proxy-Error"] = f"upstream status {status_code}"
    if not content_type.lower().startswith("text/html"):
        # Pass through non-HTML (images, PDFs) with frame headers stripped and
        # no rewriting — the sandboxed frame can render images directly.
        body = result.body or b""
        return HTMLResponse(
            content=body,
            status_code=status_code,
            headers=headers,
        )

    # Decode is already done by httpx (auto content-encoding). Rewrite for
    # relative refs (REQ-2 AC3) and serve under the REQ-3 AC4 CSP.
    html_text = (result.body or b"").decode("utf-8", errors="replace")
    anchored = _rewrite_html(html_text, result.final_url or url)
    # REQ-4 (T9): view-agent injection, idempotent, degrades to coarse overlay.
    from backend.proxy.view_agent import inject_view_agent

    anchored = inject_view_agent(anchored, nonce=nonce)
    return HTMLResponse(
        content=anchored,
        status_code=status_code,
        headers=headers,
    )


def _scrubbed_headers(upstream_headers, nonce: str, base_origin: str | None = None) -> dict:
    """Copy upstream headers minus frame-blocking/CSP/cookie headers, then apply
    OUR isolation headers last so upstream can never override them
    (REQ-2 AC2, REQ-3 AC4/T7)."""
    headers = {}
    for k, v in (upstream_headers or {}).items():
        if k.lower() in _STRIP_RESPONSE_HEADERS:
            continue
        headers[k] = v
    headers.update(_isolation_headers(nonce, base_origin))
    headers["X-Proxy-Source"] = "proxy"
    return headers


# ── Session bootstrap ─────────────────────────────────────────────────────
# The content endpoints require a token, but an <iframe src> cannot carry a
# header — so the token must be a cookie. This endpoint sets it, and is gated
# on the ADDRESS check alone (loopback/tailnet). That is the bootstrap: the
# network position proves locality once, the token proves it on every
# subsequent content request even if the address check were ever loosened.
#
# The token is never returned in a URL or a query string — only as an HttpOnly
# cookie, so page JavaScript in the sandboxed frame cannot read it either.
@router.post("/session", include_in_schema=False)
async def browser_session(request: Request):
    if not client_address_allowed(request):
        peer = getattr(getattr(request, "client", None), "host", "?")
        logger.warning("[browser-surface] session refused for %s", peer)
        raise HTTPException(status_code=404, detail="not found")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        COOKIE_NAME,
        issue_token(),
        httponly=True,
        samesite="strict",
        path="/api/browser",
        max_age=60 * 60 * 12,
    )
    return resp
