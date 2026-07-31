"""
Subprocess worker for an isolated web crawl.

Run via:  python -m backend.crawler.crawl_worker <params_json_path>

Reads crawl parameters from a JSON file, runs the crawl in THIS process (so a
Chromium C-level crash is contained here and cannot take down the
agent/backend), and reports progress + final result as JSON lines on stdout:

  {"type": "progress", "url": "...", "page_number": 1, "total": 5}
  {"type": "result", "query": "...", "pages": [...], "duration_ms": 1234,
   "crawled_at": "..."}
  {"type": "error", "error": "..."}   # on fatal failure

The parent (crawl_runner) parses these and relays progress to the agent's
event bus, then reconstructs the CrawlResult.
"""
from __future__ import annotations

import json
import os
import sys
import traceback


def _emit(obj: dict) -> None:
    # ensure_ascii=True (default) escapes all non-ASCII as \uXXXX so the worker
    # only ever writes ASCII to stdout — avoids Windows cp1252 encode errors and
    # any mojibake. The parent json.loads decodes the escapes back to Unicode.
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _main() -> int:
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

    try:
        import asyncio

        from backend.crawler.crawler_engine import CrawlerEngine, CrawlerUnavailable
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "error", "error": f"crawler modules unavailable: {exc}"})
        return 3

    def _on_page_done(url: str, page_number: int, total: int, title: str = "", snippet: str = "") -> None:
        _emit(
            {
                "type": "progress",
                "url": url,
                "page_number": page_number,
                "total": total,
                "title": title,
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
                )

        result = asyncio.run(_run())
    except CrawlerUnavailable as exc:
        _emit({"type": "error", "error": str(exc)})
        return 4
    except Exception as exc:  # noqa: BLE001
        # Last-resort fallback: crawl4ai (DefaultMarkdownGenerator) can throw
        # "Separator is not found, and chunk exceed the limit" on pages with no
        # clean separators. Rather than failing the whole research task, fetch
        # each URL over plain HTTP and strip tags so the DER step still gets
        # usable content.
        _emit({"type": "progress", "url": "", "page_number": 0, "total": len(urls),
               "title": "plain-HTTP fallback after crawl4ai failure"})
        _fallback_pages = []
        try:
            import asyncio as _asyncio
            import re as _re

            import httpx as _httpx

            async def _plain_fetch_all(urls_: list) -> list:
                async def _plain_fetch(url: str) -> dict:
                    async with _httpx.AsyncClient(
                        follow_redirects=True, timeout=30.0
                    ) as _hc:
                        _resp = await _hc.get(
                            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                        )
                    _html = _resp.text
                    _stripped = _re.sub(
                        r"<script[\s\S]*?</script>|<style[\s\S]*?</style>",
                        " ", _html, flags=_re.IGNORECASE,
                    )
                    _stripped = _re.sub(r"<[^>]+>", " ", _stripped)
                    _text = _re.sub(r"\s+", " ", _stripped).strip()
                    _m = _re.search(r"<title[^>]*>([^<]+)</title>", _html, _re.IGNORECASE)
                    return {
                        "url": url,
                        "title": (_m.group(1).strip() if _m else url),
                        "markdown": _text,
                        "html": None,
                        "metadata": {},
                        "error": None,
                    }

                _res = await _asyncio.gather(
                    *[_plain_fetch(u) for u in urls_], return_exceptions=True
                )
                return [
                    p for p in _res if isinstance(p, dict) and p.get("markdown")
                ]

            _fallback_pages = _asyncio.run(_plain_fetch_all(urls))
        except Exception as fexc:  # noqa: BLE001
            _emit(
                {
                    "type": "error",
                    "error": f"crawl failed: {exc}; plain-HTTP fallback also failed: {fexc}",
                }
            )
            return 6

        if not _fallback_pages:
            _emit({"type": "error", "error": f"crawl failed: {exc}"})
            return 5
        result = type(
            "FallbackResult",
            (),
            {
                "query": query,
                "pages": [__import__("types").SimpleNamespace(**p) for p in _fallback_pages],
                "duration_ms": 0,
                "crawled_at": __import__(
                    "datetime"
                ).datetime.now(__import__("datetime").timezone.utc).isoformat(),
                "error": None,
                "passages": [],
                "dashboard_data": {},
                "cited_markdown": None,
                "credibility_map": None,
                "citation_index": None,
                "har_entries": [],
                "har_path": None,
            },
        )()

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
