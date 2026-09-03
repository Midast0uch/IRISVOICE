"""Capture replay store for the in-app browser surface (REQ-1, T5).

Persists the raw captured HTML the crawler fetched, keyed by ``job_id`` +
``page_number``, with provenance (source URL, fetch timestamp). This is the
bytes the agent reasoned over — REQ-1 AC2 requires rendering from the capture,
never a second live fetch.

Design constraints (design.md "Capture replay store"):
  - Bounded retention: 100 pages AND 256 MB total (T2 decision, from measured
    capture sizes), oldest-first eviction.
  - Eviction SHALL NOT fail an in-flight task (REQ-1 AC5): writes are
    best-effort and never raise into the crawl hot path.
  - Off the crawl hot path: the engine calls ``save`` after each page fetch;
    a failure to store never fails the fetch.
  - Thread-safe: crawls run under a concurrent loop + gather.

Layout (file-backed, mirroring data/har/<job_id>.har):
    data/captures/<job_id>/<page_number>.html   raw captured HTML
    data/captures/<job_id>/<page_number>.json   provenance {url, fetched_at, job_id, page_number, html_bytes}
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── capture ADDRESS vs UI COUNTER ──────────────────────────────────────────
# These are two different numbers and conflating them is what made the browser
# panel 404. `page_number` in a CRAWLER_PAGE_FETCHED payload is the outer run's
# progress counter ("reading 3 of 5"); the capture address is where the bytes
# were actually written. They diverge for two independent reasons:
#   1. Per-URL dispatch runs one single-URL crawl per URL, so every URL's only
#      page is number 1 and all of them overwrite <job>/1.html.
#   2. A vision escalation publishes MANY frames for ONE URL, so a single slot
#      number cannot address them at all — and starting each session at 1 makes
#      URL 4's frames overwrite URL 1's captured page, serving the WRONG bytes.
# Each URL therefore gets a reserved block of the job's address space, and the
# emitted payload carries the address explicitly alongside the counter.
CAPTURE_SLOT_STRIDE = int(os.environ.get("IRIS_CAPTURE_SLOT_STRIDE", "100"))


def slot_capture_offset(slot: int) -> int:
    """First capture address reserved for dispatch slot *slot* (0-based), minus 1.

    Slot 0 owns 1..99, slot 1 owns 101..199, and so on. Passed as ``page_offset``
    into the crawl (whose page 1 becomes offset+1) and into the vision session
    (whose frames take offset+2 onward, after the crawl's offset+1).
    """
    return max(0, int(slot)) * CAPTURE_SLOT_STRIDE


def accepts_capture_page(cb: Optional[Callable]) -> bool:
    """True when *cb* accepts the ``capture_page`` progress kwarg.

    The capture address is NEWER than the on_page_done contract, and test fakes
    / older relays implement the 5-positional shape only. Probed by signature,
    never by catching TypeError from a call: that cannot distinguish a signature
    mismatch from a failure raised inside the callback, and retrying on it would
    emit the same page twice. A ``**kwargs`` callback accepts it too.
    """
    if cb is None:
        return False
    try:
        import inspect

        params = inspect.signature(cb).parameters
        if "capture_page" in params:
            return True
        return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    except (TypeError, ValueError):  # builtins / C callables expose no signature
        return False

# Bounds (T1/T2 decision, recorded in requirements.md Decisions Locked).
MAX_CAPTURE_PAGES = int(os.environ.get("IRIS_CAPTURE_MAX_PAGES", "100"))
MAX_CAPTURE_BYTES = int(os.environ.get("IRIS_CAPTURE_MAX_BYTES", str(256 * 1024 * 1024)))


def _captures_dir() -> str:
    """Absolute path to data/captures under the repo root (parents[2] of this file)."""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(repo_root, "data", "captures")


class CaptureStore:
    """Bounded, file-backed store of captured HTML keyed by job_id+page_number."""

    def __init__(self, root: Optional[str] = None) -> None:
        self._root = root or _captures_dir()
        self._lock = threading.Lock()

    # ── write path (off the crawl hot path; never raises) ──────────────────

    def save(
        self,
        job_id: str,
        page_number: int,
        url: str,
        html: str,
        fetched_at: Optional[str] = None,
    ) -> bool:
        """Persist one captured page. Best-effort: returns False on failure,
        never raises (REQ-1 AC5: eviction/storage failure never fails a task)."""
        try:
            if not html:
                return False
            job_dir = os.path.join(self._root, _safe_job(job_id))
            os.makedirs(job_dir, exist_ok=True)
            html_path = os.path.join(job_dir, f"{int(page_number)}.html")
            meta_path = os.path.join(job_dir, f"{int(page_number)}.json")
            with open(html_path, "w", encoding="utf-8", errors="replace") as fh:
                fh.write(html)
            meta = {
                "url": url,
                "page_number": int(page_number),
                "html_bytes": len(html),
                "fetched_at": fetched_at or _now_iso(),
            }
            with open(meta_path, "w", encoding="utf-8") as fh:
                json.dump(meta, fh)
            self._evict_if_over_budget()
            return True
        except Exception as exc:  # noqa: BLE001 — never fail the crawl
            logger.warning("[capture_store] save failed job=%s page=%s: %s", job_id, page_number, exc)
            return False

    # ── read path (replay endpoint) ────────────────────────────────────────

    def load(self, job_id: str, page_number: int) -> Optional[dict]:
        """Return {html, url, page_number, fetched_at} or None if unavailable."""
        job_dir = os.path.join(self._root, _safe_job(job_id))
        html_path = os.path.join(job_dir, f"{int(page_number)}.html")
        meta_path = os.path.join(job_dir, f"{int(page_number)}.json")
        if not os.path.isfile(html_path):
            return None
        try:
            with open(html_path, "r", encoding="utf-8", errors="replace") as fh:
                html = fh.read()
            meta: dict = {}
            if os.path.isfile(meta_path):
                with open(meta_path, "r", encoding="utf-8") as fh:
                    meta = json.load(fh)
            return {
                "html": html,
                "url": meta.get("url", ""),
                "page_number": int(page_number),
                "fetched_at": meta.get("fetched_at", ""),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("[capture_store] load failed job=%s page=%s: %s", job_id, page_number, exc)
            return None

    def has(self, job_id: str, page_number: int) -> bool:
        return os.path.isfile(
            os.path.join(self._root, _safe_job(job_id), f"{int(page_number)}.html")
        )

    # ── retention / eviction (REQ-1 AC5) ───────────────────────────────────

    def _evict_if_over_budget(self) -> None:
        """Evict oldest-first until under both bounds. Best-effort; never raises."""
        try:
            with self._lock:
                entries = self._scan()
                if len(entries) <= MAX_CAPTURE_PAGES and entries_total(entries) <= MAX_CAPTURE_BYTES:
                    return
                # Oldest-first by mtime.
                entries.sort(key=lambda e: e["mtime"])
                while entries and (
                    len(entries) > MAX_CAPTURE_PAGES
                    or entries_total(entries) > MAX_CAPTURE_BYTES
                ):
                    victim = entries.pop(0)
                    _safe_unlink(victim["html"])
                    _safe_unlink(victim["meta"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[capture_store] eviction failed: %s", exc)

    def stats(self) -> dict:
        """Current page count + total bytes (for tests / observability)."""
        entries = self._scan()
        return {"pages": len(entries), "bytes": entries_total(entries)}

    def _scan(self) -> list:
        entries = []
        if not os.path.isdir(self._root):
            return entries
        for job in os.listdir(self._root):
            job_dir = os.path.join(self._root, job)
            if not os.path.isdir(job_dir):
                continue
            for name in os.listdir(job_dir):
                if not name.endswith(".html"):
                    continue
                html_path = os.path.join(job_dir, name)
                meta_path = html_path[:-5] + ".json"
                try:
                    entries.append({
                        "html": html_path,
                        "meta": meta_path,
                        "mtime": os.path.getmtime(html_path),
                        "bytes": os.path.getsize(html_path),
                    })
                except OSError:
                    continue
        return entries


def entries_total(entries: list) -> int:
    return sum(e["bytes"] for e in entries)


def _safe_job(job_id: str) -> str:
    """Sanitize a job_id for use as a directory name (path-traversal guard)."""
    return "".join(c for c in (job_id or "") if c.isalnum() or c in "-_.")[:128] or "unknown"


def _safe_unlink(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.unlink(path)
    except OSError:
        pass


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# Module-level singleton (thread-safe; WAL SQLite elsewhere, file store here).
_store: Optional[CaptureStore] = None
_store_lock = threading.Lock()


def get_capture_store() -> CaptureStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = CaptureStore()
    return _store