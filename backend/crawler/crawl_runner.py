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
from .capture_store import accepts_capture_page as _accepts_capture_page  # noqa: E402

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


# ── Warm crawl pool (session 248) ───────────────────────────────────────────
#
# Live conv-52 follow-up: per-URL dispatch spawned ONE worker subprocess per
# URL, each paying ~19s of Crawl4AI/Chromium INIT even with a warm OS file
# cache. Five URLs behind the concurrency cap took ~72s of pure boot before
# content flowed — the search felt dead. The pool keeps resident `--serve`
# workers (see crawl_worker._serve) so INIT is paid ONCE per pool lifetime,
# at backend boot via prewarm_crawl_pool(), never mid-search.
#
# Crash isolation is preserved: a Chromium crash kills only its worker
# process; the pool detects the dead pipe, respawns lazily, and the caller
# falls back to the proven one-shot path if the pool cannot serve at all.
# Set IRIS_CRAWL_POOL=0 to disable (unit tests, debugging).

_POOL_SIZE = int(os.environ.get("IRIS_CRAWL_POOL", str(_MAX_CONCURRENT_CRAWLS)))
_POOL_IDLE_S = float(os.environ.get("IRIS_CRAWL_POOL_IDLE_S", "900"))
_POOL_BOOT_TIMEOUT_S = float(os.environ.get("IRIS_CRAWL_POOL_BOOT_S", "120"))


class _JobState:
    """One in-flight job on a worker. The permanent reader fills it; the
    driver awaits its done event."""

    __slots__ = ("on_page_done", "relay", "result", "error", "emitted", "done", "_loop")

    def __init__(self, on_page_done, relay: bool, loop) -> None:
        self.on_page_done = on_page_done
        self.relay = relay
        self.result = None
        self.error = None
        self.emitted = False
        self.done = asyncio.Event()
        self._loop = loop

    def set_done(self) -> None:
        # The reader task runs on the SAME owner loop as the awaiting driver,
        # so a direct set is correct and immediate. The threadsafe path is a
        # defensive fallback only.
        try:
            self.done.set()
        except RuntimeError:
            try:
                self._loop.call_soon_threadsafe(self.done.set)
            except RuntimeError:
                pass


class _WarmWorker:
    __slots__ = ("proc", "busy", "alive", "ready", "job", "reader_task")

    def __init__(self, proc) -> None:
        self.proc = proc
        self.busy = False
        self.alive = True
        self.ready = None       # asyncio.Event — set when the ready line lands
        self.job = None         # active _JobState (exactly one at a time)
        self.reader_task = None  # THE single stdout reader for this worker


class _WarmCrawlPool:
    """Resident crawl-worker pool.

    Session 248 ARCHITECTURE: subprocess pipe transports (stdin/stdout) are
    bound to the event loop that spawned the process. Jobs arrive from
    WHATEVER loop the caller is on (gateway startup, DER dispatch executor
    loops), so driving a prewarmed worker from a different loop blew up with
    "got Future attached to a different loop" on every job. The pool therefore
    owns ONE dedicated background loop ("owner loop"); every spawn/drive runs
    there, and public methods hop over via run_coroutine_threadsafe. When the
    pool is enabled it is the SOLE execution path — no mixed one-shot overlap,
    so the REQ-17 AC3 concurrency cap holds by construction (one semaphore
    instance, one loop)."""

    def __init__(self, size: int) -> None:
        self._size = max(0, size)
        self._workers: list[_WarmWorker] = []
        self._started = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def enabled(self) -> bool:
        return self._size > 0

    def _owner_loop(self) -> asyncio.AbstractEventLoop:
        """Lazily start the dedicated pool loop thread (idempotent)."""
        if self._loop is None or self._loop.is_closed():
            import threading

            self._loop = asyncio.new_event_loop()
            t = threading.Thread(
                target=self._loop.run_forever,
                daemon=True,
                name="crawl-pool-loop",
            )
            t.start()
        return self._loop

    async def _hop(self, coro):
        """Run `coro` on the owner loop; awaitable from any loop."""
        owner = self._owner_loop()
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is owner:
            return await coro
        fut = asyncio.run_coroutine_threadsafe(coro, owner)
        return await asyncio.wrap_future(fut)

    async def prewarm(self) -> int:
        """Spawn all pool workers now (backend boot). Returns live count."""
        if not self.enabled():
            return 0
        return await self._hop(self._prewarm_impl())

    async def _prewarm_impl(self) -> int:
        await self._ensure_started()
        return sum(1 for w in self._workers if w.alive)

    async def _ensure_started(self) -> None:
        if self._started:
            return
        self._started = True
        for _ in range(self._size):
            try:
                # REQ-17 AC3: boot-time spawns respect the same crawl cap.
                async with _get_crawl_semaphore():
                    await self._spawn_worker()
            except Exception as exc:  # noqa: BLE001 — pool loss falls back
                logger.warning("[crawl_pool] prewarm spawn failed: %s", exc)

    def _worker_cmd(self) -> tuple:
        cmd = [
            sys.executable, "-m", "backend.crawler.crawl_worker",
            "--serve", str(_POOL_IDLE_S),
        ]
        env = dict(os.environ)
        env["PYTHONPATH"] = _REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONIOENCODING"] = "utf-8"
        return cmd, env

    async def _spawn_worker(self, boot_timeout_s: Optional[float] = None) -> _WarmWorker:
        cmd, env = self._worker_cmd()
        # NOTE: no semaphore here. Every caller is already inside the pool's
        # per-loop crawl semaphore (_execute_impl wraps the whole job;
        # _ensure_started takes it per spawn below) — a second acquire would
        # deadlock on the non-reentrant Semaphore.
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=_REPO_ROOT,
            env=env,
            creationflags=_SPAWN_FLAGS,
            limit=_STDIO_LIMIT,
        )
        worker = _WarmWorker(proc)
        self._workers.append(worker)

        # Session 248 FIX (readuntil race): ONE permanent reader task owns
        # proc.stdout for the worker's ENTIRE life. The previous design
        # started a fresh readline() loop per job — any overlap between a
        # timed-out job's reader and the next job's reader crashed with
        # "readuntil() called while another coroutine is already waiting",
        # which is exactly what zeroed the conv-52 AI-news run (usable=0).
        worker.ready = asyncio.Event()
        worker.reader_task = asyncio.create_task(self._reader_loop(worker))

        # Wait for the ready line (browser booted) so the FIRST job through
        # this worker doesn't pay INIT inside its own timeout budget.
        effective_boot = min(_POOL_BOOT_TIMEOUT_S, max(boot_timeout_s or 0, 30.0)) \
            if boot_timeout_s else _POOL_BOOT_TIMEOUT_S
        try:
            await asyncio.wait_for(worker.ready.wait(), timeout=effective_boot)
        except asyncio.TimeoutError:
            worker.alive = False
            await _kill_tree(proc)
            raise TimeoutError("pool worker boot timed out")
        if not worker.alive:
            raise RuntimeError("pool worker exited during boot")
        logger.info(
            "[crawl_pool] worker ready pid=%s", proc.pid,
        )
        return worker

    async def _reader_loop(self, worker: _WarmWorker) -> None:
        """THE single stdout reader for this worker. Routes lines to the
        current job (if any). Never restarted, never duplicated — this is
        what makes concurrent readuntil structurally impossible."""
        proc = worker.proc
        try:
            while True:
                try:
                    line = await proc.stdout.readline()
                except (ValueError, OSError, RuntimeError):
                    break
                if not line:
                    break
                text = line.decode("utf-8", "replace").strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue
                mtype = msg.get("type")
                job = worker.job
                if mtype == "ready":
                    if worker.ready is not None:
                        worker.ready.set()
                    continue
                if job is None:
                    continue  # stray line between jobs — drop
                if mtype == "progress":
                    job.emitted = True
                    if job.on_page_done:
                        try:
                            pn = int(msg.get("page_number", 0))
                            kw = {}
                            if job.relay:
                                kw["capture_page"] = int(msg.get("capture_page", pn) or pn)
                            job.on_page_done(
                                msg.get("url", ""), pn, int(msg.get("total", 0)),
                                msg.get("title", ""), msg.get("snippet", ""), **kw,
                            )
                        except Exception:  # noqa: BLE001
                            pass
                elif mtype == "result":
                    pages = [PageData(**_clean_page(p)) for p in msg.get("pages", [])]
                    job.result = CrawlResult(
                        query=msg.get("query", ""),
                        pages=pages,
                        duration_ms=int(msg.get("duration_ms", 0)),
                        crawled_at=msg.get("crawled_at", _now_iso()),
                        har_entries=msg.get("har_entries") or [],
                        har_path=msg.get("har_path"),
                    )
                    job.set_done()
                elif mtype == "error":
                    job.error = msg.get("error", "unknown pool worker error")
                    job.set_done()
                elif mtype == "idle_exit":
                    # Worker is going away cleanly; fail any current job so
                    # the driver doesn't hang on its timeout.
                    if job.error is None and job.result is None:
                        job.error = "pool worker idle exit"
                        job.set_done()
                    break
        finally:
            worker.alive = False
            # Wake the boot waiter (if still waiting) — an EOF during boot
            # must fail fast, not ride out the full boot timeout.
            if worker.ready is not None:
                worker.ready.set()
            job = worker.job
            if job is not None and job.result is None and job.error is None:
                job.error = "pool worker died"
                job.set_done()

    async def _acquire_idle(self) -> Optional[_WarmWorker]:
        """Wait for an idle live worker. None only if the pool is broken.

        Session 248 FIX: this used to be an asyncio.Condition cached on
        whichever loop first touched the pool — the prewarm runs on the
        gateway startup loop while dispatch_urls runs on ANOTHER loop, and
        the cross-loop Future blew up every job ("got Future attached to a
        different loop"). A busy-flag poll has no loop-bound state at all,
        so the pool is usable from any loop (workers are plain subprocesses;
        only Python-side bookkeeping lives here)."""
        deadline = asyncio.get_running_loop().time() + 30.0
        while True:
            for w in self._workers:
                if w.alive and not w.busy:
                    w.busy = True
                    return w
            if not any(w.alive for w in self._workers):
                return None
            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(0.05)

    def _release(self, worker: _WarmWorker) -> None:
        worker.busy = False

    async def _respawn_replacement(self) -> None:
        """Replace one dead worker in the background.

        Lock-free on purpose: an asyncio.Lock here would bind to whichever
        loop first took it (prewarm loop vs dispatch loop — see
        _acquire_idle), and a threading.Lock held across await would stall
        a loop. A rare extra worker beyond _size is harmless; idle-stop
        reclaims it."""
        alive = sum(1 for w in self._workers if w.alive)
        if alive >= self._size:
            return
        try:
            await self._spawn_worker()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[crawl_pool] respawn failed: %s", exc)

    async def execute(
        self,
        params: dict,
        on_page_done: Optional[Callable[[str, int, int], None]] = None,
        relay_capture_page: bool = False,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        oneshot_fn=None,
    ):
        """Run one crawl job. THE crawl path when the pool is enabled.

        Hops to the owner loop, then: acquire a warm worker (or spawn one),
        drive the job, retry ONCE on a pre-emission failure (dead pipe before
        any progress was relayed — a retry after partial progress would
        double-emit page events and corrupt the UI counters). If NO worker
        can be spawned at all, falls back to ``oneshot_fn`` (the legacy
        one-shot spawn) executed HERE on the owner loop — same loop, same
        semaphore, so the REQ-17 AC3 cap holds across both paths.

        Returns (CrawlResult|None, error_msg|None) — never None itself; the
        caller's shared tail (plain-HTTP fallback included) applies exactly
        as it does for a failed one-shot spawn.

        Session 248 HARDENING (live conv-53): an internal pool failure used
        to PROPAGATE ("The future belongs to a different loop...") and fail
        every URL in the batch — usable=0, DER answered "no browsing
        capability". The pool must never be a single point of failure: any
        exception here degrades to the proven one-shot spawn on the caller's
        own loop.
        """
        try:
            return await self._hop(
                self._execute_impl(params, on_page_done, relay_capture_page, timeout_s, oneshot_fn)
            )
        except Exception as exc:  # noqa: BLE001 — pool must never break dispatch
            logger.warning(
                "[crawl_pool] execute raised (%s); falling back to one-shot "
                "on caller loop", exc,
            )
            if oneshot_fn is not None:
                try:
                    return await oneshot_fn(
                        params, on_page_done, relay_capture_page, timeout_s,
                    )
                except Exception as exc2:  # noqa: BLE001
                    return None, f"crawl pool and oneshot both failed: {exc2}"
            return None, f"crawl pool failed: {exc}"

    async def _execute_impl(
        self,
        params: dict,
        on_page_done: Optional[Callable[[str, int, int], None]],
        relay_capture_page: bool,
        timeout_s: float,
        oneshot_fn,
    ):
        # Runs ONLY on the owner loop. The per-loop semaphore instance created
        # here is therefore always the same object — the REQ-17 AC3 cap holds
        # for every pool spawn AND job by construction.
        async with _get_crawl_semaphore():
            for attempt in (1, 2):
                worker = await self._acquire_idle()
                if worker is None:
                    try:
                        worker = await self._spawn_worker(boot_timeout_s=timeout_s)
                        worker.busy = True
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "[crawl_pool] no live worker and respawn failed (%s); "
                            "falling back to one-shot on pool loop", exc,
                        )
                        if oneshot_fn is not None:
                            return await oneshot_fn(
                                params, on_page_done, relay_capture_page,
                                timeout_s, use_semaphore=False,
                            )
                        return None, f"crawl pool unavailable: {exc}"
                was_alive = worker.alive
                try:
                    outcome = await self._drive(
                        worker, params, on_page_done, relay_capture_page, timeout_s,
                    )
                finally:
                    self._release(worker)
                    if not worker.alive and was_alive:
                        asyncio.create_task(self._respawn_replacement())
                if outcome is None:
                    # Dead pipe BEFORE the job started — safe to retry.
                    if attempt == 1:
                        continue
                    if oneshot_fn is not None:
                        return await oneshot_fn(
                            params, on_page_done, relay_capture_page,
                            timeout_s, use_semaphore=False,
                        )
                    return None, "crawl pool worker unavailable"
                result, error_msg, emitted = outcome
                if (
                    result is None
                    and error_msg
                    and "died mid-job" in error_msg
                    and not emitted
                    and attempt == 1
                ):
                    # Worker crashed before emitting anything — retry once on
                    # a fresh worker; a crash AFTER partial progress is NOT
                    # retried (double-emitted page events corrupt the panel).
                    continue
                return result, error_msg
            if oneshot_fn is not None:
                return await oneshot_fn(
                    params, on_page_done, relay_capture_page,
                    timeout_s, use_semaphore=False,
                )
            return None, "crawl pool exhausted"

    async def _drive(self, worker, params, on_page_done, relay_capture_page, timeout_s):
        """Drive one job. Returns (result, error_msg, emitted_any_progress);
        bare None means the job never started (dead pipe) — retryable.

        Session 248: no reader lives here any more. The worker's permanent
        reader task routes lines into the _JobState; this coroutine just
        writes the job line and awaits its done event."""
        proc = worker.proc
        job_line = json.dumps(params) + "\n"
        try:
            proc.stdin.write(job_line.encode("utf-8"))
            await proc.stdin.drain()
        except Exception as exc:  # noqa: BLE001
            # Dead pipe: worker exited (idle-stop / crash). Mark dead; caller
            # retries on another worker or falls back.
            worker.alive = False
            logger.warning("[crawl_pool] write to worker failed: %s", exc)
            return None

        job = _JobState(on_page_done, relay_capture_page,
                        asyncio.get_running_loop())
        worker.job = job
        try:
            try:
                await asyncio.wait_for(job.done.wait(), timeout=timeout_s)
            except asyncio.TimeoutError:
                logger.error(
                    "[crawl_pool] job timed out after %.0fs; killing worker tree",
                    timeout_s,
                )
                await _kill_tree(proc)
                worker.alive = False
                return None, f"crawl timed out after {timeout_s:g}s", job.emitted
        finally:
            worker.job = None
        return job.result, job.error, job.emitted


_pool: Optional[_WarmCrawlPool] = None


def get_crawl_pool() -> _WarmCrawlPool:
    global _pool
    if _pool is None:
        _pool = _WarmCrawlPool(_POOL_SIZE)
    return _pool


def pool_enabled() -> bool:
    return get_crawl_pool().enabled()


async def prewarm_crawl_pool() -> int:
    """Backend-boot hook: start the resident workers NOW so no search ever
    pays Chromium INIT mid-run. Returns the number of live workers."""
    return await get_crawl_pool().prewarm()


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
    page_offset: int = 0,
) -> CrawlResult:
    """Run the crawl in a child process.

    Never raises for crawl failures — returns a CrawlResult with pages=[]
    and error set on any failure (spawn error, crash, timeout, unavailable).

    ``page_offset`` reserves this call's block in the job's capture address
    space (see CrawlerEngine.crawl). Default 0 = unchanged batch numbering.
    """
    params = {
        "query": query,
        "urls": urls,
        "instructions": instructions,
        "max_pages": max_pages,
        "delay_ms": delay_ms,
        "job_id": job_id,
        "page_offset": page_offset,
    }
    # Session 248: the worker enforces its OWN job watchdog (15s inside the
    # parent's ceiling) so a hung page answers with an error line and exits
    # cleanly instead of hanging until the parent tree-kills it.
    params["job_timeout_s"] = max(timeout_s - 15, 30)
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

    # Probed once (not per page): see _accepts_capture_page's docstring for why
    # a per-call TypeError retry is the wrong shape here.
    _relay_capture_page = _accepts_capture_page(on_page_done)

    # ── Warm-pool path (session 248) ───────────────────────────────────
    # A resident worker already has Chromium booted, so fetching starts in
    # ~1-2s instead of paying ~19s of Crawl4AI INIT per URL per search
    # (live conv-52 follow-up: 5 URLs ≈ 72s of pure boot). When the pool is
    # enabled it is the SOLE execution path: execute() runs BOTH the warm
    # drive AND (on failure) the one-shot spawn below — on ITS owner loop,
    # under ONE semaphore instance — so the REQ-17 AC3 cap holds by
    # construction and every spawn site sees the same patched environment.
    if pool_enabled():
        _pool_result, _pool_error = await get_crawl_pool().execute(
            params,
            on_page_done=on_page_done,
            relay_capture_page=_relay_capture_page,
            timeout_s=timeout_s,
            oneshot_fn=_run_oneshot_spawn,
        )
        return await _finalize_crawl_result(
            _pool_result, _pool_error, query, urls, job_id,
            on_page_done, page_offset,
        )

    _result, _error = await _run_oneshot_spawn(
        params, on_page_done, _relay_capture_page, timeout_s,
    )
    return await _finalize_crawl_result(
        _result, _error, query, urls, job_id, on_page_done, page_offset,
    )


def _null_async_ctx():
    """An async no-op context manager (for optional semaphore acquisition)."""
    import contextlib

    return contextlib.AsyncExitStack()


async def _run_oneshot_spawn(
    params: dict,
    on_page_done: Optional[Callable[[str, int, int], None]],
    relay_capture_page: bool,
    timeout_s: float,
    use_semaphore: bool = True,
):
    """Legacy one-shot spawn + drain. Returns (result|None, error_msg|None).

    Session 248: extracted verbatim from run_crawl_subprocess so the POOL can
    fall back to it ON ITS OWNER LOOP when no worker can be spawned — one
    loop, one semaphore, one patched create_subprocess_exec surface."""
    params_path = None
    proc = None
    result: Optional[CrawlResult] = None
    error_msg: Optional[str] = None
    stderr_task: Optional[asyncio.Task] = None
    stderr_ring: deque = deque(maxlen=200)
    # Concurrency cap (REQ-17 AC3): block until a crawl slot is free so parallel
    # DER Sub-Loop children cannot exhaust host memory. use_semaphore=False
    # when the POOL calls this: its caller (_execute_impl) already holds the
    # slot — a second acquire deadlocks on the non-reentrant Semaphore.
    _sem_ctx = _get_crawl_semaphore() if use_semaphore else None
    async with (_sem_ctx if _sem_ctx is not None else _null_async_ctx()):
        try:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            )
            json.dump(params, tmp)
            tmp.close()
            params_path = tmp.name

            cmd = [sys.executable, "-m", "backend.crawler.crawl_worker", params_path]
            env = dict(os.environ)
            env["PYTHONPATH"] = _REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
            # Belt-and-suspenders: force UTF-8 stdio in the child so any stray
            # output is encoded consistently (the worker emits ASCII-safe JSON).
            env["PYTHONIOENCODING"] = "utf-8"

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
                                _pn = int(msg.get("page_number", 0))
                                _kw = {}
                                if relay_capture_page:
                                    # Relay the capture ADDRESS the child saved
                                    # under. Dropping it here is what left the
                                    # panel building its iframe src from the UI
                                    # counter instead (404 on pages 2..N).
                                    _kw["capture_page"] = int(
                                        msg.get("capture_page", _pn) or _pn
                                    )
                                on_page_done(
                                    msg.get("url", ""),
                                    _pn,
                                    int(msg.get("total", 0)),
                                    msg.get("title", ""),
                                    msg.get("snippet", ""),
                                    **_kw,
                                )
                            except Exception:  # noqa: BLE001
                                pass
                    elif _type == "result":
                        pages = [PageData(**_clean_page(p)) for p in msg.get("pages", [])]
                        result = CrawlResult(
                            query=msg.get("query", params.get("query", "")),
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

        return result, error_msg


async def _finalize_crawl_result(
    result: Optional[CrawlResult],
    error_msg: Optional[str],
    query: str,
    urls: list,
    job_id: Optional[str],
    on_page_done: Optional[Callable[[str, int, int], None]],
    page_offset: int,
) -> CrawlResult:
    """Shared post-processing for BOTH worker paths (one-shot + warm pool).

    REQ-1 usable-predicate judging, per-URL outcome logging, the plain-HTTP
    merge/fallback and the terminal CrawlResult contract live here exactly
    once so a pool failure is indistinguishable from a spawn failure
    downstream.
    """
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
        # Keep each failed page's ORIGINAL slot. Re-fetching [u2, u4] as a
        # fresh 1..2 list wrote their bytes over u1's and u2's captures — the
        # panel then served the wrong page's content under u1's tab. The
        # re-fetch is the SAME page, so it must reuse the SAME address.
        _failed_slots = [
            (i, p) for i, p in enumerate(_usable_pages)
            if not page_is_usable(p).usable and p.url
        ]
        _failed = [p for _, p in _failed_slots]
        if _failed:
            _fb_pages, _fb_har = await _plain_http_fetch(
                [p.url for p in _failed], job_id=job_id, on_page_done=on_page_done,
                page_offset=page_offset,
                capture_pages=[page_offset + i + 1 for i, _ in _failed_slots],
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
            page_offset=page_offset,
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
    page_offset: int = 0,
    capture_pages: Optional[list] = None,
) -> "tuple[list, list]":
    """Fetch URLs over plain HTTP and strip HTML tags.

    Returns (pages, har_entries): PageData objects plus light HAR evidence per
    request (REQ-13), so the fallback emits the FULL CrawlResult contract and
    the downstream DER summarize / citation / frontend pipeline is fed exactly
    as if crawl4ai had succeeded. Zero crawl4ai/browser dependency — this path
    cannot hit the crawl4ai chunking failure. All fetches run in parallel and
    are individually bounded (30s), so the fallback completes in ~30s worst
    case regardless of page count. ``job_id`` (when known) keys capture-store
    writes for the browser panel replay (REQ-1), and ``page_offset`` reserves
    this call's block of the job's capture address space so a single-URL
    dispatch does not overwrite another URL's captured bytes. ``capture_pages``
    overrides the address per URL — used when re-fetching a FAILED SUBSET, whose
    members must keep the addresses they already own rather than be renumbered
    1..N over their neighbours' bytes.
    """
    import hashlib as _hashlib
    import re as _re
    import time as _time

    import httpx as _httpx

    _fb_relay_capture_page = _accepts_capture_page(on_page_done)

    async def _one(url: str, page_number: int, capture_page: int):
        # page_number is this fetch's own counter; capture_page is the storage
        # address (caller-supplied, or this call's reserved block).
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
                        page_number=capture_page,
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
                    _kw = {"capture_page": capture_page} if _fb_relay_capture_page else {}
                    on_page_done(
                        url, page_number, len(urls),
                        (_m.group(1).strip() if _m else url), "",
                        **_kw,
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

    def _addr(i: int) -> int:
        if capture_pages is not None and i < len(capture_pages):
            return int(capture_pages[i])
        return page_offset + i + 1

    _results = await asyncio.gather(
        *[_one(u, i + 1, _addr(i)) for i, u in enumerate(urls)],
        return_exceptions=True,
    )
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
