"""
Run a web crawl in an ISOLATED subprocess.

A Chromium C-level crash (segfault / access violation) inside Crawl4AI cannot be
caught by try/except in the same process — it kills the whole process, taking
the agent/backend down with it. By running the crawl in a child process we
contain that risk: if the child dies, the parent survives and degrades
gracefully (returns a CrawlResult with .error set instead of crashing).

Progress events are relayed from the child's stdout back to the caller via the
on_page_done callback so the UI still shows live "Reading <host> (N/M)" updates.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Optional

from .crawler_engine import CrawlResult, PageData, _coerce_headers, _write_har_file
# Single-source-of-truth predicate + challenge detection (REQ-1). The
# challenge detector lived here at :453 with one caller inside the plain-HTTP
# fallback; it moved to usability.py so the shared predicate can judge
# challenges and the primary path can reach it (REQ-4). The alias keeps the
# module-global name for existing callers/tests that import or patch it.
from .usability import is_challenge_page as _is_challenge_page  # noqa: E402,F401
from .usability import page_is_usable  # noqa: E402,F401

logger = logging.getLogger(__name__)

# Repo root = parents[2] of this file (backend/crawler/crawl_runner.py).
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# D3 (T36 live smoke, 2026-08-09): was 45s. The REAL cause of the 45s timeouts
# was the stdout read-buffer deadlock fixed by _STDIO_LIMIT below (see that
# comment) — raising the timeout alone would NOT have fixed it (a deadlock
# just re-hits whatever ceiling is set). This is still raised, on separate,
# real evidence: a COLD Playwright/Chromium launch (AsyncWebCrawler.start() in
# crawler_engine.py) measured 16.76s here vs 2.25s once the OS file cache was
# warm. crawl_runner spawns a brand-new worker subprocess per crawl (isolation
# for crash safety), so that cold-start cost is paid on every call, not
# amortized, and 45s left too little margin over it once page-fetch time is
# added. Raised to give headroom for a cold launch (~25s conservative ceiling)
# + up to 5 page fetches at the 10s per-page ceiling (_TIMEOUT_MS) + delays.
_DEFAULT_TIMEOUT_S = float(os.environ.get("CRAWL_SUBPROCESS_TIMEOUT_S", "90"))

# D3 root cause: asyncio.create_subprocess_exec()'s StreamReader defaults to a
# 64 KiB (65536-byte) line-length limit (asyncio default `limit=`). The worker
# emits its ENTIRE crawl result as ONE JSON line on stdout (crawl_worker.py
# _emit); a real multi-page crawl routinely exceeds 64 KiB — e.g. a single
# Wikipedia article's extracted markdown alone measured 221KB in a live run
# here. When the result line exceeds the limit, proc.stdout.readline() raises
# LimitOverrunError -> ValueError (CPython asyncio/streams.py), which
# _drain()'s `except (ValueError, OSError)` below treats as "pipe closed" and
# breaks the read loop — but the CHILD process is still alive and blocked
# writing the rest of that oversized line into a pipe nobody is draining
# anymore (Windows anonymous-pipe write() blocks once the OS buffer fills).
# The child never reaches process exit, so `await proc.wait()` hangs until the
# OUTER asyncio.wait_for(..., timeout=timeout_s) fires — which is why the
# worker looked "stuck" for exactly the timeout duration regardless of its
# value: it wasn't slow, it was deadlocked. Verified live: 4/4 page-fetch
# progress events arrived in <20s every time; the timeout only ever fired
# waiting on the oversized result line. 20 MiB comfortably covers a full
# max_pages batch of large real pages while staying bounded (not unlimited).
_STDIO_LIMIT = 20 * 1024 * 1024

# Concurrency cap (REQ-17 AC3): parallel DER Sub-Loop children must not OOM the
# host. Bound simultaneous crawl subprocesses. Override via env for testing.
_MAX_CONCURRENT_CRAWLS = int(os.environ.get("CRAWL_MAX_CONCURRENT", "2"))

# Per-event-loop semaphore (REQ-17 AC3). A module-level asyncio.Semaphore is
# bound to the loop that exists at import time; under asyncio.run() (fresh loop
# per call) that binding is stale and raises "bound to a different event loop".
# Lazily create one semaphore per running loop instead.
_crawl_semaphores: dict = {}


def _get_crawl_semaphore() -> asyncio.Semaphore:
    # Use get_running_loop() (the loop actually driving the coroutine) and bind
    # the semaphore to it explicitly. asyncio.Semaphore() with no loop arg can
    # bind to a different loop object than get_event_loop() returns, which would
    # defeat per-loop sharing. Key the cache by the running loop's id.
    loop = asyncio.get_running_loop()
    key = id(loop)
    sem = _crawl_semaphores.get(key)
    if sem is None:
        # Created inside the running loop, so it binds to `loop` automatically.
        sem = asyncio.Semaphore(_MAX_CONCURRENT_CRAWLS)
        _crawl_semaphores[key] = sem
    return sem

# On Windows, spawn the worker in its own process group so we can tear down the
# ENTIRE tree (Chromium renderer/GPU children) on timeout/crash — a bare
# proc.kill() only kills the direct child and orphans Chromium (REQ-17 AC2).
if sys.platform == "win32":
    _SPAWN_FLAGS = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
else:
    _SPAWN_FLAGS = 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_unlink(path: str) -> None:
    try:
        os.remove(path)
    except Exception:
        pass


async def _drain_stderr(proc, ring: deque) -> None:
    """Drain the worker's stderr into a bounded ring buffer.

    The buffer is logged when the worker fails (see run_crawl_subprocess), so a
    crash traceback is never lost to DEVNULL. Tolerates test fakes without a
    stderr stream, and pipes that close mid-read (worker died).
    """
    stream = getattr(proc, "stderr", None)
    if stream is None:
        return
    try:
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").rstrip()
            if text:
                ring.append(text)
    except Exception:  # noqa: BLE001 — stderr capture must never fail the crawl
        pass


def _clean_page(p: dict) -> dict:
    return {
        "url": p.get("url", ""),
        "title": p.get("title", ""),
        "markdown": p.get("markdown", "") or "",
        "html": p.get("html"),
        "metadata": p.get("metadata") or {},
        "error": p.get("error"),
    }


async def _kill_tree(proc) -> None:
    """Kill the crawl worker AND its child process tree (Chromium children).

    On Windows we use ``taskkill /T /F`` against the worker PID (the worker was
    spawned in its own process group via CREATE_NEW_PROCESS_GROUP). On POSIX we
    send SIGKILL to the worker's process group. Falls back to a direct kill if
    the tree-kill tools are unavailable. Never raises.
    """
    pid = proc.pid if proc is not None else None
    if pid is None:
        return
    if sys.platform == "win32":
        try:
            # /T = tree, /F = force. Kills Chromium renderer/GPU orphans too.
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(pid), 9)  # SIGKILL the whole group
        except Exception:
            pass
    # Best-effort direct kill + reap, in case the tree-kill missed the parent.
    try:
        proc.kill()
    except Exception:
        pass
    try:
        await proc.wait()
    except Exception:
        pass


async def run_crawl_subprocess(
    query: str,
    urls: list[str],
    instructions: str,
    on_page_done: Optional[Callable[[str, int, int], None]] = None,
    max_pages: int = 5,
    delay_ms: int = 1000,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    job_id: Optional[str] = None,
) -> CrawlResult:
    """Run the crawl in a child process.

    Never raises for crawl failures — returns a CrawlResult with pages=[]
    and error set on any failure (spawn error, crash, timeout, unavailable).
    """
    params = {
        "query": query,
        "urls": urls,
        "instructions": instructions,
        "max_pages": max_pages,
        "delay_ms": delay_ms,
        "job_id": job_id,
    }
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(params, tmp)
    tmp.close()
    params_path = tmp.name

    cmd = [sys.executable, "-m", "backend.crawler.crawl_worker", params_path]
    env = dict(os.environ)
    env["PYTHONPATH"] = _REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    # Belt-and-suspenders: force UTF-8 stdio in the child so any stray output
    # is encoded consistently (the worker itself emits ASCII-safe JSON).
    env["PYTHONIOENCODING"] = "utf-8"

    proc = None
    result: Optional[CrawlResult] = None
    error_msg: Optional[str] = None
    stderr_task: Optional[asyncio.Task] = None
    stderr_ring: deque = deque(maxlen=200)
    # Concurrency cap (REQ-17 AC3): block until a crawl slot is free so parallel
    # DER Sub-Loop children cannot exhaust host memory.
    async with _get_crawl_semaphore():
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=_REPO_ROOT,
                env=env,
                creationflags=_SPAWN_FLAGS,
                limit=_STDIO_LIMIT,
            )

            assert proc.stdout is not None

            # Drain worker stderr into a ring buffer (previously DEVNULL —
            # every crash was an unexplained "pipe closed" with no traceback).
            stderr_task = asyncio.create_task(_drain_stderr(proc, stderr_ring))

            async def _drain() -> None:
                nonlocal result, error_msg
                while True:
                    try:
                        line = await proc.stdout.readline()
                    except (ValueError, OSError) as _pe:
                        # Windows ProactorEventLoop raises ValueError (carrying
                        # the pipe's last buffer text) when the worker subprocess
                        # dies abruptly — treat it as EOF and let proc.wait()
                        # report the real exit code instead of a misleading error.
                        logger.debug("[crawl_runner] stdout pipe closed while reading: %s", _pe)
                        break
                    if not line:
                        break  # EOF — child ended
                    text = line.decode("utf-8", "replace").strip()
                    if not text:
                        continue
                    try:
                        msg = json.loads(text)
                    except json.JSONDecodeError:
                        logger.debug("[crawl_runner] ignoring non-JSON line: %s", text[:200])
                        continue
                    _type = msg.get("type")
                    if _type == "progress":
                        if on_page_done:
                            try:
                                on_page_done(
                                    msg.get("url", ""),
                                    int(msg.get("page_number", 0)),
                                    int(msg.get("total", 0)),
                                    msg.get("title", ""),
                                    msg.get("snippet", ""),
                                )
                            except Exception:  # noqa: BLE001
                                pass
                    elif _type == "result":
                        pages = [PageData(**_clean_page(p)) for p in msg.get("pages", [])]
                        result = CrawlResult(
                            query=msg.get("query", query),
                            pages=pages,
                            duration_ms=int(msg.get("duration_ms", 0)),
                            crawled_at=msg.get("crawled_at", _now_iso()),
                            har_entries=msg.get("har_entries") or [],
                            har_path=msg.get("har_path"),
                        )
                    elif _type == "error":
                        error_msg = msg.get("error", "unknown worker error")

                # Child closed stdout; confirm exit code.
                rc = await proc.wait()
                if rc != 0 and result is None:
                    error_msg = error_msg or f"crawl worker exited with code {rc}"

            await asyncio.wait_for(_drain(), timeout=timeout_s)
        except asyncio.TimeoutError:
            logger.error(
                "[crawl_runner] crawl timed out after %.0fs; killing worker tree", timeout_s
            )
            if proc is not None:
                await _kill_tree(proc)
            error_msg = f"crawl timed out after {timeout_s:g}s"
        except Exception as exc:  # noqa: BLE001
            logger.error("[crawl_runner] unexpected error: %s", exc)
            if proc is not None:
                await _kill_tree(proc)
            error_msg = f"crawl runner error: {exc}"
        finally:
            if stderr_task is not None:
                stderr_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stderr_task
            # Explicitly close the pipe transports. When the worker is killed
            # (timeout / tree-kill) the pipe handles close abruptly and the
            # transports linger until GC, emitting noisy
            # "Exception ignored in: _ProactorBasePipeTransport.__del__ /
            #  I/O operation on closed pipe" warnings on every crawl. Closing
            # them here suppresses that noise and frees the handles promptly.
            if proc is not None:
                for _stream in (getattr(proc, "stdout", None), getattr(proc, "stderr", None)):
                    if _stream is None:
                        continue
                    try:
                        _tr = getattr(_stream, "_transport", None)
                        if _tr is not None:
                            _tr.close()
                    except Exception:  # noqa: BLE001 — best effort
                        pass
            _safe_unlink(params_path)

        # Diagnosability: if the worker died without producing a result, the
        # stderr ring buffer holds its real traceback — log it so the cause is
        # in the backend log instead of an unexplained pipe-closed line.
        if result is None and stderr_ring:
            logger.error(
                "[crawl_runner] worker failed; stderr tail (%d lines):\n%s",
                len(stderr_ring),
                "\n".join(list(stderr_ring)[-50:]),
            )

        _usable_pages = result.pages if result is not None else None
        # REQ-1: single shared predicate — the local `if p.markdown` judge is
        # gone. Every layer that decides "usable" calls page_is_usable.
        _good_pages = [p for p in (_usable_pages or []) if page_is_usable(p).usable]

        # REQ-16 AC2/AC6: per-URL terminal outcome with the shared predicate's
        # reason, keyed by run id — even on success, so "what did each URL
        # actually yield?" is answerable from logs (compact: only unusable
        # URLs carry a reason; usable ones are implied by the count).
        if _usable_pages:
            _unusable = [
                "%s reason=%s" % (
                    (p.url or "?")[:52], page_is_usable(p).reason.value,
                )
                for p in _usable_pages if not page_is_usable(p).usable
            ]
            logger.info(
                "[crawl_runner] per-URL outcome job_id=%s usable=%d/%d %s",
                job_id, len(_good_pages), len(_usable_pages),
                ("unusable: " + "; ".join(_unusable)) if _unusable else "",
            )

        # DIAGNOSABILITY: "worker returned zero usable pages" and "worker
        # crashed" produced the SAME downstream log line ("worker failed"),
        # with no record of which. That cost a full investigation cycle —
        # the crash hypothesis was chased through import traces and torchcodec
        # stack dumps when the worker had in fact run cleanly and simply
        # extracted nothing. State which it is, and for the zero-pages case
        # state PER URL why, because "the sites blocked us" and "extraction
        # produced empty markdown" need completely different fixes.
        if result is None:
            logger.warning(
                "[crawl_runner] worker produced NO RESULT (crash/timeout) — "
                "see the stderr tail above if present"
            )
        elif not _good_pages:
            logger.warning(
                "[crawl_runner] worker RAN but returned 0 usable pages of %d "
                "fetched — job_id=%s per-URL: %s",
                len(_usable_pages or []),
                job_id,
                [
                    "%s -> %s" % (
                        (p.url or "?")[:52],
                        # REQ-1 AC4: the reason comes from the verdict, not a
                        # local guess — error is None alone is not usability.
                        "reason=%s detail=%s" % (
                            page_is_usable(p).reason.value,
                            page_is_usable(p).detail[:40],
                        ),
                    )
                    for p in (_usable_pages or [])[:6]
                ] or "no pages at all",
            )
        if _usable_pages is not None and _good_pages:
            # Partial success: re-fetch ONLY the URLs the shared predicate
            # judged unusable over plain HTTP and merge them in, so a single
            # broken page (huge / separator-less / JS-heavy / challenged) no
            # longer silently starves DER.
            _failed = [p for p in _usable_pages if not page_is_usable(p).usable and p.url]
            if _failed:
                _fb_pages, _fb_har = await _plain_http_fetch(
                    [p.url for p in _failed], job_id=job_id, on_page_done=on_page_done,
                )
                if _fb_pages:
                    result.pages = _good_pages + _fb_pages
                    result.har_entries = (result.har_entries or []) + _fb_har
                    if job_id:
                        result.har_path = _write_har_file(job_id, result.har_entries)
                    logger.info(
                        "[crawl_runner] plain-HTTP merge recovered %d/%d failed URLs",
                        len(_fb_pages), len(_failed),
                    )
            return result

        if not _good_pages:
            # Worker subprocess failed (crash / browser death / timeout) OR
            # returned zero usable pages. Last-resort fallback: fetch the
            # planned URLs over plain HTTP. This path has zero
            # crawl4ai/browser dependency (it cannot hit the crawl4ai chunking
            # failure), and it now emits the FULL result contract (HAR
            # evidence + metadata + har_path) so the downstream DER summarize /
            # citation / frontend pipeline is fed exactly as if crawl4ai had
            # succeeded.
            _fb_pages, _fb_har = await _plain_http_fetch(
                urls, job_id=job_id, on_page_done=on_page_done,
            )
            if _fb_pages:
                _har_path = _write_har_file(job_id, _fb_har) if job_id else None
                return CrawlResult(
                    query=query,
                    pages=_fb_pages,
                    duration_ms=0,
                    crawled_at=_now_iso(),
                    error=None,
                    passages=[],
                    dashboard_data={},
                    cited_markdown=None,
                    credibility_map=None,
                    citation_index=None,
                    har_entries=_fb_har,
                    har_path=_har_path,
                )
            return CrawlResult(
                query=query,
                pages=[],
                duration_ms=0,
                crawled_at=_now_iso(),
                error=error_msg or "crawl produced no result",
            )
        return result


async def _plain_http_fetch(
    urls: list,
    job_id: Optional[str] = None,
    on_page_done: Optional[Callable[..., None]] = None,
) -> "tuple[list, list]":
    """Fetch URLs over plain HTTP and strip HTML tags.

    Returns (pages, har_entries): PageData objects plus light HAR evidence per
    request (REQ-13), so the fallback emits the FULL CrawlResult contract and
    the downstream DER summarize / citation / frontend pipeline is fed exactly
    as if crawl4ai had succeeded. Zero crawl4ai/browser dependency — this path
    cannot hit the crawl4ai chunking failure. All fetches run in parallel and
    are individually bounded (30s), so the fallback completes in ~30s worst
    case regardless of page count. ``job_id`` (when known) keys capture-store
    writes for the browser panel replay (REQ-1).
    """
    import hashlib as _hashlib
    import re as _re
    import time as _time

    import httpx as _httpx

    async def _one(url: str, page_number: int):
        t0 = _time.monotonic()
        try:
            async with _httpx.AsyncClient(follow_redirects=True, timeout=30.0) as _hc:
                _resp = await _hc.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                )
            _html = _resp.text
            _stripped = _re.sub(
                r"<script[\s\S]*?</script>|<style[\s\S]*?</style>",
                " ", _html, flags=_re.IGNORECASE,
            )
            _stripped = _re.sub(r"<[^>]+>", " ", _stripped)
            _text = _re.sub(r"\s+", " ", _stripped).strip()
            _m = _re.search(r"<title[^>]*>([^<]+)</title>", _html, _re.IGNORECASE)
            _har = {
                "url": url, "method": "GET", "status": _resp.status_code,
                "response_headers": _coerce_headers(dict(_resp.headers)),
                "duration_ms": int((_time.monotonic() - t0) * 1000),
                "content_length": len(_html),
                "body_sha256": _hashlib.sha256(_html.encode("utf-8", "replace")).hexdigest(),
                "error": None,
            }
            # REQ-10 (T12): a bot-challenge interstitial (Cloudflare/Turnstile)
            # is NOT the page's content — do NOT save it to the capture store,
            # and mark the page so the orchestrator can penalize the source.
            _challenged = _is_challenge_page(_html)
            if _challenged:
                logger.warning(
                    "[crawl_runner] CHALLENGE url=%s status=%s — page not saved",
                    url, _resp.status_code,
                )
                _har["error"] = "challenge"
            _page = PageData(
                url=url,
                title=(_m.group(1).strip() if _m else url),
                markdown=_text,
                html=None,
                metadata={},
                error="challenge" if _challenged else None,
                html_bytes=len(_html),
            )
            # T5 (REQ-1 AC1/AC2): persist raw captured HTML for the browser
            # panel replay. Best-effort; never fails the fetch. SKIPPED for
            # challenge pages (REQ-10 T12) — their boilerplate is not content.
            if not _challenged:
                try:
                    from .capture_store import get_capture_store

                    get_capture_store().save(
                        job_id=job_id,
                        page_number=page_number,
                        url=url,
                        html=_html,
                    )
                except Exception:  # noqa: BLE001
                    pass
            # Report progress exactly as the crawl4ai worker does. Without this
            # the fallback fetched pages SILENTLY: the UI got CRAWLER_STARTED
            # and CRAWLER_COMPLETE but no CRAWLER_PAGE_FETCHED in between, so
            # the browser panel could not show pages arriving. The fallback is
            # not a rare path — the worker times out on multi-URL crawls and
            # this runs most of the time.
            if on_page_done:
                try:
                    on_page_done(
                        url, page_number, len(urls),
                        (_m.group(1).strip() if _m else url), "",
                    )
                except Exception:  # noqa: BLE001
                    pass  # never fail a fetch on a progress emit
            return _page, _har
        except Exception as _e:  # noqa: BLE001
            logger.warning("[crawl_runner] plain-HTTP fallback fetch failed %s: %s", url, _e)
            _har = {
                "url": url, "method": "GET", "status": None,
                "response_headers": {}, "duration_ms": int((_time.monotonic() - t0) * 1000),
                "content_length": 0, "body_sha256": "",
                "error": str(_e),
            }
            return None, _har

    _results = await asyncio.gather(*[_one(u, i + 1) for i, u in enumerate(urls)], return_exceptions=True)
    _pages: list = []
    _har_entries: list = []
    for _r in _results:
        if isinstance(_r, Exception):
            continue
        _page, _har = _r
        _har_entries.append(_har)
        if _page is not None:
            _pages.append(_page)
    if _pages:
        logger.info(
            "[crawl_runner] plain-HTTP fallback produced %d pages "
            "(worker returned no usable pages — see the reason line above; "
            "this is NOT necessarily a worker crash)",
            len(_pages),
        )
    return _pages, _har_entries
