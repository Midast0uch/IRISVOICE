"""Document recombination (document-rehydration spec, REQ-9/10/11).

Combines multiple rendered documents into one (the "combine A + B" path) and
provides the HAR-consult decision primitive so the agent re-crawls a source
ONLY when its captured evidence is missing or stale (never blindly re-crawl).
"""
import os
import uuid
from typing import Dict, List, Optional


def combine_documents(
    store,
    document_ids: List[str],
    conversation_id: str,
    trust: str = "trusted",
) -> Optional[Dict]:
    """Combine several rendered documents into a single new render (REQ-9).

    Content is concatenated (separated by a horizontal rule); ``sources`` is the
    UNION of all input sources (deduped by URL) so provenance is preserved on
    the combined doc. Returns the new document record, or None if no inputs
    resolved. Never raises on missing ids — they are skipped.
    """
    docs = []
    for did in document_ids:
        try:
            rec = store.get(did)
        except Exception:
            rec = None
        if rec:
            docs.append(rec)
    if not docs:
        return None

    combined_content = "\n\n---\n\n".join(
        (d.get("content") or "") for d in docs
    )
    all_sources: List[Dict] = []
    seen = set()
    for d in docs:
        for s in (d.get("sources") or []):
            url = s.get("url")
            if url and url not in seen:
                seen.add(url)
                all_sources.append(s)

    new_id = str(uuid.uuid4())
    store.store(
        new_id,
        conversation_id,
        "markdown",
        combined_content,
        {},
        [],
        trust,
        sources=all_sources,
    )
    return {
        "document_id": new_id,
        "content": combined_content,
        "sources": all_sources,
        "conversation_id": conversation_id,
    }


def urls_needing_recrawl(
    sources: List[Dict],
    max_age_s: int = 3600,
    now: Optional[float] = None,
) -> List[str]:
    """HAR consult (REQ-10/11): decide which sources must be re-crawled.

    A source needs re-crawl when it has NO captured HAR evidence, or the HAR
    file is missing/stale (older than ``max_age_s``). Sources with fresh HAR
    evidence are reused — the agent does NOT blindly re-crawl. Tolerant: a
    missing/invalid HAR path is treated as "needs recrawl" rather than raising.
    """
    import time

    if now is None:
        now = time.time()
    needed: List[str] = []
    for s in (sources or []):
        url = s.get("url")
        if not url:
            continue
        har_path = s.get("har_path")
        if not har_path:
            needed.append(url)
            continue
        try:
            mtime = os.path.getmtime(har_path)
        except Exception:
            needed.append(url)
            continue
        if (now - mtime) > max_age_s:
            needed.append(url)
    return needed
