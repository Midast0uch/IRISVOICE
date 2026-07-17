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
_crawl_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_CRAWLS)

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
    async with _crawl_semaphore:
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
                    line = await proc.stdout.readline()
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

        if error_msg and result is None:
            return CrawlResult(
                query=query, pages=[], duration_ms=0, crawled_at=_now_iso(), error=error_msg
            )
        if result is None:
            return CrawlResult(
                query=query,
                pages=[],
                duration_ms=0,
                crawled_at=_now_iso(),
                error="crawl produced no result",
            )
        return result
