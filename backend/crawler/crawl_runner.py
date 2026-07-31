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
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Callable, Optional

from .crawler_engine import CrawlResult, PageData

logger = logging.getLogger(__name__)

# Repo root = parents[2] of this file (backend/crawler/crawl_runner.py).
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

_DEFAULT_TIMEOUT_S = float(os.environ.get("CRAWL_SUBPROCESS_TIMEOUT_S", "90"))

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
    # Concurrency cap (REQ-17 AC3): block until a crawl slot is free so parallel
    # DER Sub-Loop children cannot exhaust host memory.
    async with _get_crawl_semaphore():
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=_REPO_ROOT,
                env=env,
                creationflags=_SPAWN_FLAGS,
            )

            assert proc.stdout is not None

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
            _safe_unlink(params_path)

        _usable_pages = result.pages if result is not None else None
        if not _usable_pages:
            # Worker subprocess failed (crash / chunking error / browser death)
            # OR returned an empty result (all fetches failed). Last-resort
            # fallback: fetch the planned URLs over plain HTTP and strip tags
            # so the DER step still gets usable content.
            _fb = await _plain_http_fallback(urls)
            if _fb:
                return CrawlResult(
                    query=query,
                    pages=_fb,
                    duration_ms=0,
                    crawled_at=_now_iso(),
                    error=None,
                    passages=[],
                    dashboard_data={},
                    cited_markdown=None,
                    credibility_map=None,
                    citation_index=None,
                    har_entries=[],
                    har_path=None,
                )
            return CrawlResult(
                query=query,
                pages=[],
                duration_ms=0,
                crawled_at=_now_iso(),
                error=error_msg or "crawl produced no result",
            )
        return result


async def _plain_http_fallback(urls: list) -> list:
    """Fetch URLs over plain HTTP and strip HTML tags. Returns list of dicts
    shaped like PageData (url/title/markdown/html/metadata/error). Empty if all
    fetches fail. Used when the crawl4ai worker subprocess crashes — this path
    has zero crawl4ai/browser dependency, so it cannot hit the chunking bug."""
    import re as _re

    import httpx as _httpx

    pages: list = []

    async def _one(url: str) -> dict:
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
            if not _text:
                return None
            _m = _re.search(r"<title[^>]*>([^<]+)</title>", _html, _re.IGNORECASE)
            return {
                "url": url,
                "title": (_m.group(1).strip() if _m else url),
                "markdown": _text,
                "html": None,
                "metadata": {},
                "error": None,
            }
        except Exception as _e:  # noqa: BLE001
            logger.warning("[crawl_runner] plain-HTTP fallback fetch failed %s: %s", url, _e)
            return None

    _results = await asyncio.gather(*[_one(u) for u in urls], return_exceptions=True)
    for _r in _results:
        if isinstance(_r, dict) and _r.get("markdown"):
            pages.append(PageData(**_clean_page(_r)))
    if pages:
        logger.info(
            "[crawl_runner] plain-HTTP fallback produced %d pages (worker failed)",
            len(pages),
        )
    return pages
