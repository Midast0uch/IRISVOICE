"""
Subprocess worker for an isolated web crawl.

Run via:  python -m backend.crawler.crawl_worker <params_json_path>
    OR:   python -m backend.crawler.crawl_worker --serve [idle_timeout_s]

Reads crawl parameters from a JSON file, runs the crawl in THIS process (so a
Chromium C-level crash is contained here and cannot take down the
agent/backend), and reports progress + final result as JSON lines on stdout:

  {"type": "progress", "url": "...", "page_number": 1, "total": 5, "capture_page": 1}
  {"type": "result", "query": "...", "pages": [...], "duration_ms": 1234,
   "crawled_at": "..."}
  {"type": "error", "error": "..."}   # on fatal failure

The parent (crawl_runner) parses these and relays progress to the agent's
event bus, then reconstructs the CrawlResult.

── SERVE MODE (session 248, warm crawl pool) ────────────────────────────────
The one-shot mode boots Crawl4AI + Chromium per invocation (~19s INIT even
with a warm OS file cache). With per-URL dispatch that cost was paid once PER
URL PER SEARCH (5 URLs ≈ 72s of pure boot, live conv-52 follow-up). Serve mode
keeps ONE engine alive across jobs:

  stdin:  one JSON job line per crawl (same params dict as the file variant)
  stdout: {"type":"ready"} once the browser is up, then per-job
          progress/result/error lines exactly like one-shot mode.
  exit:   stdin EOF (parent gone) or idle_timeout_s without a job.

Crash isolation is preserved: a Chromium crash kills only this process; the
parent pool detects the dead pipe and respawns (or falls back to one-shot).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from typing import Optional


def _emit(obj: dict) -> None:
    # ensure_ascii=True (default) escapes all non-ASCII as \uXXXX so the worker
    # only ever writes ASCII to stdout — avoids Windows cp1252 encode errors and
    # any mojibake. The parent json.loads decodes the escapes back to Unicode.
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _serve(idle_timeout_s: float) -> int:
    """Resident mode: keep one CrawlerEngine alive across stdin jobs.

    Job lines carry the same params dict the file-based mode reads. Per-job
    run-scoped state (cookie jar, challenge domains) is reset between jobs so
    T11 REQ-5 (cookies die with the run) still holds — a persistent browser
    must not become a persistent identity.
    """
    import asyncio
    import time as _time

    try:
        from backend.crawler.crawler_engine import CrawlerEngine, CrawlerUnavailable
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "error", "error": f"crawler modules unavailable: {exc}"})
        return 3

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    t_last_job = _time.monotonic()

    # Session 248 FIX: boot the browser EAGERLY and emit {"type":"ready"}.
    # The original revision created the engine lazily inside the first job,
    # so no ready line ever appeared at startup and the parent pool's boot
    # wait timed out ("pool worker boot timed out") even though the worker
    # was healthy. Eager boot is also the POINT of the pool: the INIT cost
    # is paid at backend pre-warm, never mid-search.
    engine: Optional[CrawlerEngine] = None
    try:
        t0 = _time.monotonic()
        engine = CrawlerEngine()
        loop.run_until_complete(engine.__aenter__())
        _emit({"type": "ready", "boot_ms": int((_time.monotonic() - t0) * 1000)})
    except CrawlerUnavailable as exc:
        _emit({"type": "error", "error": str(exc)})
        return 4
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "error", "error": f"crawl worker boot failed: {exc}"})
        traceback.print_exc()
        return 5

    def _idle_watchdog() -> None:
        # No job within the idle window: exit so RAM returns. The parent pool
        # lazily respawns on the next job (or the backend boot pre-warm does).
        if engine is not None:
            try:
                loop.run_until_complete(engine.__aexit__(None, None, None))
            except Exception:  # noqa: BLE001 — best-effort teardown
                pass
        _emit({"type": "idle_exit"})
        os._exit(0)

    watchdog = threading.Timer(idle_timeout_s, _idle_watchdog)
    watchdog.daemon = True
    watchdog.start()

    try:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                params = json.loads(raw)
            except json.JSONDecodeError as exc:
                _emit({"type": "error", "error": f"bad job line: {exc}"})
                continue
            if params.get("type") == "shutdown":
                break

            # Re-arm the idle watchdog per job.
            watchdog.cancel()
            watchdog = threading.Timer(idle_timeout_s, _idle_watchdog)
            watchdog.daemon = True
            watchdog.start()

            query = params.get("query", "")
            urls = params.get("urls", []) or []
            instructions = params.get("instructions", "") or ""
            max_pages = int(params.get("max_pages", 5))
            delay_ms = int(params.get("delay_ms", 1000))
            job_id = params.get("job_id")
            page_offset = int(params.get("page_offset", 0) or 0)
            # Session 248: per-job watchdog INSIDE the worker. The parent's
            # tree-kill is a last resort — a worker that answers "timed out"
            # and exits cleanly keeps the protocol sane (no half-dead pipes,
            # no reader races); the parent respawns a fresh worker.
            job_timeout_s = float(params.get("job_timeout_s", 0) or 0)

            def _on_page_done(
                url: str,
                page_number: int,
                total: int,
                title: str = "",
                snippet: str = "",
                capture_page: Optional[int] = None,
            ) -> None:
                _emit(
                    {
                        "type": "progress",
                        "url": url,
                        "page_number": page_number,
                        "total": total,
                        "title": title,
                        "capture_page": (
                            int(capture_page) if capture_page is not None else page_number
                        ),
                    }
                )

            try:
                if engine is None:
                    # Unreachable after eager boot above; kept as a safety net
                    # in case a fatal job tore the engine down mid-session.
                    t0 = _time.monotonic()
                    engine = CrawlerEngine()
                    loop.run_until_complete(engine.__aenter__())
                    _emit(
                        {
                            "type": "ready",
                            "boot_ms": int((_time.monotonic() - t0) * 1000),
                        }
                    )
                else:
                    # Per-job run-scoped state reset (see docstring).
                    if engine._cookie_jar is not None:
                        engine._cookie_jar.clear()
                        engine._cookie_jar = None
                    engine._challenge_domains.clear()

                crawl_coro = engine.crawl(
                    query=query,
                    urls=urls,
                    instructions=instructions,
                    max_pages=max_pages,
                    delay_ms=delay_ms,
                    on_page_done=_on_page_done,
                    job_id=job_id,
                    page_offset=page_offset,
                )
                if job_timeout_s > 0:
                    try:
                        result = loop.run_until_complete(
                            asyncio.wait_for(crawl_coro, timeout=job_timeout_s)
                        )
                    except asyncio.TimeoutError:
                        _emit({
                            "type": "error",
                            "error": f"job timed out inside worker after {job_timeout_s:g}s",
                        })
                        # A hung crawl can leave Chromium wedged — tear down
                        # and exit so the parent respawns a clean worker.
                        try:
                            loop.run_until_complete(engine.__aexit__(None, None, None))
                        except Exception:  # noqa: BLE001
                            pass
                        return 5
                else:
                    result = loop.run_until_complete(crawl_coro)
            except CrawlerUnavailable as exc:
                _emit({"type": "error", "error": str(exc)})
                return 4
            except Exception as exc:  # noqa: BLE001
                # A job-level failure may have corrupted the browser (Playwright
                # targets die with the page). Tear the engine down and EXIT so
                # the parent respawns a clean worker — same isolation guarantee
                # as the one-shot mode.
                _emit({"type": "error", "error": f"crawl worker failed: {exc}"})
                traceback.print_exc()
                if engine is not None:
                    try:
                        loop.run_until_complete(engine.__aexit__(None, None, None))
                    except Exception:  # noqa: BLE001
                        pass
                return 5

            pages = [
                {
                    "url": p.url,
                    "title": p.title,
                    "markdown": p.markdown,
                    "html": p.html,
                    "metadata": p.metadata,
                    "error": p.error,
                }
                for p in result.pages
            ]
            _emit(
                {
                    "type": "result",
                    "query": result.query,
                    "pages": pages,
                    "duration_ms": result.duration_ms,
                    "crawled_at": result.crawled_at,
                    "har_entries": result.har_entries,
                    "har_path": result.har_path,
                }
            )
        # stdin EOF — parent is gone.
        return 0
    finally:
        watchdog.cancel()
        if engine is not None:
            try:
                loop.run_until_complete(engine.__aexit__(None, None, None))
            except Exception:  # noqa: BLE001 — best-effort teardown
                pass
        try:
            loop.close()
        except Exception:  # noqa: BLE001
            pass


def _main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--serve":
        idle_s = float(sys.argv[2]) if len(sys.argv) > 2 else 900.0
        return _serve(idle_s)

    if len(sys.argv) < 2:
        _emit({"type": "error", "error": "crawl_worker: missing params file argument"})
        return 2

    params_path = sys.argv[1]
    try:
        with open(params_path, "r", encoding="utf-8-sig") as fh:
            params = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "error", "error": f"crawl_worker: bad params: {exc}"})
        return 2
    finally:
        # Best-effort cleanup of the temp params file.
        try:
            os.remove(params_path)
        except Exception:
            pass

    query = params.get("query", "")
    urls = params.get("urls", []) or []
    instructions = params.get("instructions", "") or ""
    max_pages = int(params.get("max_pages", 5))
    delay_ms = int(params.get("delay_ms", 1000))
    job_id = params.get("job_id")
    page_offset = int(params.get("page_offset", 0) or 0)

    try:
        import asyncio

        from backend.crawler.crawler_engine import CrawlerEngine, CrawlerUnavailable
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "error", "error": f"crawler modules unavailable: {exc}"})
        return 3

    def _on_page_done(
        url: str,
        page_number: int,
        total: int,
        title: str = "",
        snippet: str = "",
        capture_page: Optional[int] = None,
    ) -> None:
        # capture_page is the capture-store address the bytes were saved under.
        # It differs from page_number whenever page_offset is set (per-URL
        # dispatch), and the panel builds its iframe src from it — relaying only
        # page_number is what made /api/browser/capture/<job>/<n> 404.
        _emit(
            {
                "type": "progress",
                "url": url,
                "page_number": page_number,
                "total": total,
                "title": title,
                "capture_page": (
                    int(capture_page) if capture_page is not None else page_number
                ),
            }
        )

    try:
        async def _run() -> "object":
            async with CrawlerEngine() as engine:
                return await engine.crawl(
                    query=query,
                    urls=urls,
                    instructions=instructions,
                    max_pages=max_pages,
                    delay_ms=delay_ms,
                    on_page_done=_on_page_done,
                    job_id=job_id,
                    page_offset=page_offset,
                )

        result = asyncio.run(_run())
    except CrawlerUnavailable as exc:
        _emit({"type": "error", "error": str(exc)})
        return 4
    except Exception as exc:  # noqa: BLE001
        # Worker-level failure (crawl4ai/browser crash, launch failure, ...).
        # The fallback lives in ONE place — the runner's plain-HTTP path, which
        # re-fetches with the full contract (HAR evidence + metadata). Emit the
        # error so the runner fails fast, and print the traceback to stderr:
        # the runner drains stderr into a ring buffer and logs it on failure,
        # so the REAL cause lands in the backend log (stderr used to go to
        # DEVNULL, turning every crash into an unexplained pipe-close).
        _emit({"type": "error", "error": f"crawl worker failed: {exc}"})
        traceback.print_exc()
        return 5

    pages = [
        {
            "url": p.url,
            "title": p.title,
            "markdown": p.markdown,
            "html": p.html,
            "metadata": p.metadata,
            "error": p.error,
        }
        for p in result.pages
    ]
    _emit(
        {
            "type": "result",
            "query": result.query,
            "pages": pages,
            "duration_ms": result.duration_ms,
            "crawled_at": result.crawled_at,
            "har_entries": result.har_entries,
            "har_path": result.har_path,
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(_main())
