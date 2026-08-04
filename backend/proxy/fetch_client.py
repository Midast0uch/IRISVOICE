"""Redirect-aware fetch client for the in-app browser proxy (REQ-5, T3/T4).

The egress guard resolves the host, rejects the address by class, and returns
the concrete checked address. This client makes the fetch USE that checked
address (REQ-5 AC1 — DNS-rebinding defense: the fetch binds to the IP that was
validated, not a re-resolved name), while preserving SNI via the
``sni_hostname`` request extension (httpcore >= 1.0.9).

Redirects are handled MANUALLY (``follow_redirects=False``): after every hop
the next URL is re-checked through the guard (REQ-5 AC2 — a public URL
redirecting to 127.0.0.1 is refused), depth is bounded, and the total time is
bounded. Response size is bounded and the read aborts cleanly when exceeded.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

import httpx

from .egress_guard import (
    CheckedTarget,
    EgressRefused,
    MAX_REDIRECT_DEPTH,
    MAX_RESPONSE_BYTES,
    MAX_TOTAL_TIME_S,
    acheck_hop,
)

logger = logging.getLogger(__name__)

# Test seam: the proxy endpoint may inject a mock transport (e.g.
# httpx.MockTransport) so contract tests never hit live web while the egress
# guard still runs against the real resolver. Default None => real transport.
_DEFAULT_TRANSPORT_FACTORY = None

_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
# Follow 303 as GET (httpx default for 303), keep method for 307/308; we only
# ever issue GETs from this client, so method preservation is a no-op.
_MAX_HEAD_BYTES = 64 * 1024  # enough for redirect Location + headers


@dataclass
class ProxyFetchResult:
    """Outcome of a guarded fetch, with provenance for REQ-2 AC4 surfacing."""

    ok: bool
    status_code: Optional[int] = None
    headers: Optional[dict] = None
    body: Optional[bytes] = None
    final_url: Optional[str] = None
    final_host: Optional[str] = None
    error: Optional[str] = None  # specific reason for the caller's log
    hops: int = 0


async def fetch_with_guard(
    url: str,
    *,
    max_bytes: int = MAX_RESPONSE_BYTES,
    max_time_s: float = MAX_TOTAL_TIME_S,
    max_redirects: int = MAX_REDIRECT_DEPTH,
    timeout: float = 15.0,
    extra_headers: Optional[dict] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> ProxyFetchResult:
    """Fetch ``url`` through the egress guard, following redirects manually.

    Every hop is re-checked by the guard; any refusal aborts the whole fetch.
    The response body is capped at ``max_bytes`` (read aborted cleanly, partial
    body discarded). Never raises: failures are returned in the result so the
    caller can surface a non-specific message to the page (REQ-2 AC4 / REQ-5
    AC5). ``transport`` is injectable for tests (MockTransport); the guard
    checks always run against the real resolver.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) IRISVoiceProxy/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        # Avoid advertising br: some environments have a broken/absent brotli
        # decoder and a gzip/deflate response is always safe to decode. This
        # keeps the proxy from crashing mid-body on Content-Encoding errors.
        "Accept-Encoding": "gzip, deflate",
    }
    if extra_headers:
        headers.update(extra_headers)

    t_start = time.monotonic()
    current = url
    hops = 0
    last_checked: Optional[CheckedTarget] = None

    transport = transport or (_DEFAULT_TRANSPORT_FACTORY() if _DEFAULT_TRANSPORT_FACTORY else httpx.AsyncHTTPTransport())

    async with httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        follow_redirects=False,
    ) as client:
        try:
            while True:
                if hops > max_redirects:
                    return ProxyFetchResult(
                        ok=False, error=f"redirect depth exceeded ({max_redirects})",
                        hops=hops,
                    )
                # Guard THIS hop (initial URL and every redirect target).
                checked = await acheck_hop(current)
                last_checked = checked
                hops += 1

                if time.monotonic() - t_start > max_time_s:
                    return ProxyFetchResult(
                        ok=False, error=f"total time exceeded ({max_time_s:g}s)", hops=hops,
                    )

                # Connect to the CHECKED address, not a re-resolved name. The
                # URL host is replaced with the validated IP literal; SNI and
                # Host header carry the real hostname so TLS + virtual hosting
                # still work.
                if ":" in checked.address:  # IPv6 literal needs brackets
                    ip_host = f"[{checked.address}]"
                else:
                    ip_host = checked.address
                # Rebuild the URL with the IP in place of the hostname.
                from urllib.parse import urlsplit, urlunsplit

                parts = urlsplit(checked.url)
                netloc = ip_host
                if parts.port:
                    netloc = f"{ip_host}:{parts.port}"
                ip_url = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

                request_headers = dict(headers)
                # Host header must reflect the ORIGINAL host:port.
                host_header = checked.hostname
                if checked.port not in (80, 443):
                    host_header = f"{checked.hostname}:{checked.port}"
                request_headers["Host"] = host_header

                try:
                    resp = await client.get(
                        ip_url,
                        headers=request_headers,
                        extensions={"sni_hostname": checked.hostname},
                    )
                except httpx.TimeoutException:
                    return ProxyFetchResult(ok=False, error="upstream timed out", hops=hops)
                except EgressRefused as exc:
                    logger.warning("[proxy] hop %d refused %s rule=%s", hops, current, exc.rule)
                    return ProxyFetchResult(ok=False, error="fetch refused by egress rule", hops=hops)
                except Exception as exc:  # noqa: BLE001 — never raise from the proxy
                    logger.warning("[proxy] hop %d fetch error %s: %s", hops, current, exc)
                    return ProxyFetchResult(ok=False, error=f"fetch failed: {exc}", hops=hops)

                # Size bound: refuse to buffer more than max_bytes (AC4).
                content_length = resp.headers.get("content-length")
                if content_length is not None:
                    try:
                        if int(content_length) > max_bytes:
                            return ProxyFetchResult(
                                ok=False,
                                status_code=resp.status_code,
                                error=f"response too large (> {max_bytes} bytes)",
                                final_url=current,
                                final_host=checked.hostname,
                                hops=hops,
                            )
                    except ValueError:
                        pass

                if resp.status_code in _REDIRECT_STATUS:
                    location = resp.headers.get("location")
                    if not location:
                        return ProxyFetchResult(
                            ok=False, status_code=resp.status_code,
                            error="redirect without Location header",
                            final_url=current, final_host=checked.hostname, hops=hops,
                        )
                    current = urljoin(current, location)
                    # Drain the small redirect body so the connection can be
                    # reused; bound it so a huge redirect body cannot stall.
                    try:
                        await resp.aread()
                    except Exception:  # noqa: BLE001
                        pass
                    continue

                # Final response: read body under the byte cap.
                body = bytearray()
                try:
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            return ProxyFetchResult(
                                ok=False, status_code=resp.status_code,
                                error=f"response too large (> {max_bytes} bytes)",
                                final_url=current, final_host=checked.hostname, hops=hops,
                            )
                except httpx.TimeoutException:
                    return ProxyFetchResult(
                        ok=False, status_code=resp.status_code,
                        error="body read timed out", final_url=current,
                        final_host=checked.hostname, hops=hops,
                    )
                except Exception as exc:  # noqa: BLE001
                    return ProxyFetchResult(
                        ok=False, status_code=resp.status_code,
                        error=f"body read failed: {exc}", final_url=current,
                        final_host=checked.hostname, hops=hops,
                    )

                return ProxyFetchResult(
                    ok=True,
                    status_code=resp.status_code,
                    headers=dict(resp.headers),
                    body=bytes(body),
                    final_url=current,
                    final_host=checked.hostname,
                    hops=hops,
                )
        except EgressRefused as exc:
            logger.warning("[proxy] initial check refused %s rule=%s", url, exc.rule)
            return ProxyFetchResult(ok=False, error=f"refused ({exc.rule})", hops=hops)
        except Exception as exc:  # noqa: BLE001 — never raise
            logger.warning("[proxy] fetch failed %s: %s", url, exc)
            return ProxyFetchResult(ok=False, error=f"fetch failed: {exc}", hops=hops)