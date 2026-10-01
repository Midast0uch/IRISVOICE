"""Research memory: every research result is kept, and new research builds on it.

Spec: specs/research-memory-chain-browser (REQ-1, REQ-2, REQ-3; design D1-D3).

A landed research result (the deferred crawl extraction, the synchronous crawl,
the quick-tier ``search``) is written to THREE homes, all OFF the answer path on
``durability_queue.lane("research_memory")`` and the fragment worker:

  * ``document_data`` row, fmt ``research`` (the record, JSON; the store reuse)
  * an Immortus chain REFERENCE row (``nbl_outcome='research'``, real coordinate
    or NULL, ``file_path`` = document id) - the time layer points at the record
  * a ``research_summary`` fragment, zone ``reference`` (semantic recall; the
    embedder is CPU-only, ~5 s per KB, so it never runs inline)

A later ``search`` / ``crawler_query`` looks for close earlier records
CONCURRENTLY with the web call (bounded, degrades to "no prior"), cross-checks
the earlier claims against the new evidence DETERMINISTICALLY (no model call),
and puts a bounded PRIOR RESEARCH + CROSS-CHECK section at the head of the tool
result, where the synthesis reads it.

Plain functions, no registry: one store, one implementer.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# fmt of the document_data row that holds a research record. The conversation
# document listings exclude it (a research record is memory, not a card).
RESEARCH_FMT = "research"

CHUNK_TYPE = "research_summary"
ZONE = "reference"

PRIOR_TIMEOUT_S = 3.0          # AC2.1: the lookup never costs more than this
SECTION_CAP = 1500             # AC2.2: PRIOR RESEARCH + CROSS-CHECK, chars
PRIOR_MIN_SIMILARITY = 0.55

# Record bounds (memory stays bounded; the fragment is ONE embedder chunk).
_MAX_CLAIMS = 12
_CLAIM_CHARS = 300
_SUMMARY_CHARS = 1500
_MAX_SOURCES = 20
_DASHBOARD_CAP = 48_000        # serialized chars of the stored dashboard payload
_FRAGMENT_CAP = 1000           # < EMBED_MAX_CHARS (1024): header stays in chunk 1

_HEADER_RE = re.compile(r"\[research (\S+) doc=([^\]\s]+)\]")
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CITED_RE = re.compile(
    r"(.+?)\s*\[(?:\d+\]\((https?://[^)\s]+)\)|\?\])", re.DOTALL
)
_STOP = frozenset(
    "the a an of in is are was were to and for on at by with as it its be that "
    "this from or".split()
)
_SUBJECT_MATCH = 0.6           # share of a claim's subject words a sentence must hold


def _get_mi() -> Any:
    """The process memory interface (tests replace this function)."""
    try:
        from backend.memory import get_memory_interface

        return get_memory_interface()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[research_memory] memory interface unavailable: %s", exc)
        return None


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "") or url
    except Exception:  # noqa: BLE001
        return url


# ── record building ────────────────────────────────────────────────────────


def claims_from_dashboard(dashboard: dict, cited_markdown: str = "") -> List[dict]:
    """Claims ({text, urls}) from the extraction: cited summary sentences first
    (they carry their source URL), then key findings, then section items."""
    claims: List[dict] = []
    seen: set = set()

    def _add(text: Any, urls: Optional[list] = None) -> None:
        t = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(t) < 12 or t.lower() in seen or len(claims) >= _MAX_CLAIMS:
            return
        seen.add(t.lower())
        claims.append({"text": t[:_CLAIM_CHARS], "urls": [u for u in (urls or []) if u][:3]})

    for m in _CITED_RE.finditer(cited_markdown or ""):
        _add(m.group(1), [m.group(2)] if m.group(2) else [])
    d = dashboard if isinstance(dashboard, dict) else {}
    for f in d.get("key_findings") or []:
        _add(re.sub(r"\s*\[(?:\d+|\?)\](?:\(\S+?\))?", "", str(f)))
    for sec in d.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        kind = sec.get("type")
        if kind == "metrics":
            for it in sec.get("items") or []:
                if isinstance(it, dict):
                    _add(f"{it.get('label', '')}: {it.get('value', '')}")
        elif kind == "cards":
            for it in sec.get("items") or []:
                if isinstance(it, dict):
                    _add(f"{it.get('title', '')}: {it.get('body', '')}", [it.get("url")])
        elif kind == "table":
            heads = [str(h) for h in sec.get("headers") or []]
            for row in (sec.get("rows") or [])[:6]:
                if isinstance(row, (list, tuple)):
                    _add("; ".join(f"{h}={c}" for h, c in zip(heads, row)) if heads else "; ".join(map(str, row)))
    return claims


def claims_from_sources(source_list: List[dict]) -> List[dict]:
    """Claims from the quick tier: one per source snippet, tagged with its URL."""
    out: List[dict] = []
    for s in source_list or []:
        if not isinstance(s, dict):
            continue
        text = re.sub(r"\s+", " ", str(s.get("snippet") or s.get("title") or "")).strip()
        if len(text) >= 12 and len(out) < _MAX_CLAIMS:
            out.append({"text": text[:_CLAIM_CHARS], "urls": [s.get("url")] if s.get("url") else []})
    return out


def _normalize(record: dict) -> Optional[dict]:
    """A bounded, well-formed record, or None when there is nothing to remember."""
    query = str((record or {}).get("query") or "").strip()
    summary = str(record.get("summary") or "").strip()[:_SUMMARY_CHARS]
    claims = []
    for c in record.get("claims") or []:
        if isinstance(c, dict) and str(c.get("text") or "").strip():
            claims.append({
                "text": str(c["text"]).strip()[:_CLAIM_CHARS],
                "urls": [str(u) for u in (c.get("urls") or []) if u][:3],
            })
    claims = claims[:_MAX_CLAIMS]
    if not query or not (summary or claims):
        return None
    sources: List[str] = []
    for u in list(record.get("sources") or []) + [u for c in claims for u in c["urls"]]:
        u = str(u)
        if u.startswith("http") and u not in sources:
            sources.append(u)
    job_id = str(record.get("job_id") or "")
    # Same job lands the same id (an upsert), so a re-landing never duplicates.
    doc_id = (
        "research_" + hashlib.sha1(job_id.encode()).hexdigest()[:12]
        if job_id else "research_" + uuid.uuid4().hex[:12]
    )
    dashboard = record.get("dashboard")
    try:
        if dashboard is not None and len(json.dumps(dashboard, ensure_ascii=False, default=str)) > _DASHBOARD_CAP:
            dashboard = None  # too large to keep whole; the claims still carry it
    except Exception:  # noqa: BLE001
        dashboard = None
    return {
        "id": doc_id,
        "query": query[:400],
        "summary": summary,
        "claims": claims,
        "sources": sources[:_MAX_SOURCES],
        "created_at": str(record.get("created_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        "conversation_id": str(record.get("conversation_id") or ""),
        "session_id": str(record.get("session_id") or ""),
        "job_id": job_id,
        "dashboard": dashboard,
    }


def fragment_text(rec: dict) -> str:
    """The embedded text. Carries its own id and date: recall returns strings only."""
    head = f"[research {rec['created_at'][:10]} doc={rec['id']}] Q: {rec['query'][:200]}"
    lines = [head]
    if rec.get("summary"):
        lines.append(rec["summary"][:400])
    for c in rec.get("claims") or []:
        host = _host(c["urls"][0]) if c.get("urls") else ""
        lines.append(f"- {c['text'][:160]}" + (f" ({host})" if host else ""))
    text = ""
    for ln in lines:
        if len(text) + len(ln) + 1 > _FRAGMENT_CAP:
            break
        text += ln + "\n"
    return text.strip()


# ── write path (off the answer path) ───────────────────────────────────────


def record_research(record: dict, *, mi: Any = None) -> bool:
    """Queue ONE research record for storage. Never blocks, never raises.

    Returns False when there is nothing to keep or the lane dropped the job.
    The lane job writes the document row, the chain reference row, and hands
    the embedding to the fragment worker.
    """
    try:
        rec = _normalize(record)
        if rec is None:
            return False
        from backend.utils.durability_queue import lane

        return lane("research_memory").submit(f"research:{rec['id']}", _write_record, rec, mi)
    except Exception as exc:  # noqa: BLE001 - bookkeeping never fails a tool call
        logger.warning("[research_memory] record not queued: %s", exc)
        return False


def _latest_coordinate(mi: Any, rec: dict) -> Optional[str]:
    """The agent's real reasoning-state coordinate, or None (never a stand-in)."""
    try:
        from backend.agent.caducean_trajectory import format_coords, get_trajectory_recorder

        recorder = get_trajectory_recorder(mi)
        for sid in (rec.get("session_id"), rec.get("conversation_id")):
            if not sid:
                continue
            c = recorder.get_latest_coordinate(sid)
            if c:
                return format_coords(c["x"], c["y"], c["xi"], c["u"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("[research_memory] coordinate lookup failed id=%s: %s", rec["id"], exc)
    return None


def _write_record(rec: dict, mi: Any = None) -> None:
    """Runs on the research_memory lane. Each home fails alone."""
    mi = mi or _get_mi()
    doc_id, conv = rec["id"], rec["conversation_id"]
    if mi is None:
        logger.info("[research_memory] no memory interface - record not stored id=%s", doc_id)
        return
    content = json.dumps(rec, ensure_ascii=False, default=str)
    meta = {
        "query": rec["query"], "created_at": rec["created_at"],
        "conversation_id": conv, "job_id": rec["job_id"],
        "source_count": len(rec["sources"]), "claim_count": len(rec["claims"]),
    }

    try:
        from backend.agent.document_store import DocumentDataStore

        store = DocumentDataStore.get_for(mi)
        if store is not None:
            store.store(
                doc_id, conv, RESEARCH_FMT, content, {"meta": meta}, [], "untrusted",
                sources=[{"url": u, "title": _host(u)} for u in rec["sources"]],
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[research_memory] document row failed id=%s conv=%s: %s", doc_id, conv, exc)

    try:
        from backend.gateway.iris_ffi import ffi_immortus_chain_append

        coords = _latest_coordinate(mi, rec)
        topic = "general"
        try:
            from backend.memory.mycelium.extractor import resolve_topic_domain

            topic = resolve_topic_domain(rec["query"])
        except Exception:  # noqa: BLE001
            pass
        ref = json.dumps({
            "document_id": doc_id, "format": RESEARCH_FMT, "conversation_id": conv,
            "query": rec["query"], "chars": len(content),
            "head": (rec["summary"] or (rec["claims"][0]["text"] if rec["claims"] else ""))[:400],
        }, ensure_ascii=False)
        ffi_immortus_chain_append(
            thread_id=conv or "research", result=ref,
            coords_from=coords, coords_to=coords,
            nbl_outcome="research", insight=RESEARCH_FMT, file_path=doc_id,
            landmark_id="", topic_domain=topic,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[research_memory] chain row failed id=%s conv=%s: %s", doc_id, conv, exc)

    try:
        episodic = getattr(mi, "episodic", None)
        if episodic is not None:
            from backend.agent.mcm_protocol.actions.pacman_fragment import _submit_fragment_job

            text = fragment_text(rec)
            # One session id per record: fragment_and_store dedups inside a
            # (session, chunk_type) pair, and a fresh record of the same query
            # must not vanish into an older near-identical one.
            _submit_fragment_job(
                lambda: episodic.fragment_and_store(
                    text, f"research:{doc_id}", chunk_type=CHUNK_TYPE, zone=ZONE,
                    tool_name="research",
                ),
                f"{CHUNK_TYPE}/{doc_id} ({len(text)} chars)",
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[research_memory] fragment not queued id=%s: %s", doc_id, exc)
    logger.info("[research_memory] stored id=%s conv=%s claims=%d sources=%d",
                doc_id, conv, len(rec["claims"]), len(rec["sources"]))


def land_dashboard(
    query: str, dashboard: dict, cited_markdown: str = "", source_urls: Optional[list] = None,
    *, conversation_id: str = "", session_id: str = "", job_id: str = "",
) -> bool:
    """The orchestrator landing hook: store the extraction's result."""
    d = dashboard if isinstance(dashboard, dict) else {}
    return record_research({
        "query": query,
        "summary": d.get("summary") or d.get("answer") or "",
        "claims": claims_from_dashboard(d, cited_markdown),
        "sources": source_urls or [],
        "conversation_id": conversation_id, "session_id": session_id, "job_id": job_id,
        "dashboard": d,
    })


def land_quick_search(
    query: str, envelope: dict, *, conversation_id: str = "", session_id: str = "",
) -> bool:
    """The quick-tier hook: the provider's per-source snippets are the claims."""
    return record_research({
        "query": query,
        "summary": "",
        "claims": claims_from_sources(envelope.get("source_list") or []),
        "sources": envelope.get("sources") or [],
        "conversation_id": conversation_id, "session_id": session_id,
    })


# ── read path ──────────────────────────────────────────────────────────────


def load_record(document_id: str, *, mi: Any = None) -> Optional[dict]:
    """One stored research record (with its dashboard payload), or None."""
    try:
        from backend.agent.document_store import DocumentDataStore

        store = DocumentDataStore.get_for(mi or _get_mi())
        row = store.get(document_id) if store is not None else None
        if not row or row.get("format") != RESEARCH_FMT:
            return None
        rec = json.loads(row.get("content") or "{}")
        return rec if isinstance(rec, dict) and rec.get("id") else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[research_memory] load failed id=%s: %s", document_id, exc)
        return None


def list_records(*, conversation_id: str = "", limit: int = 50, mi: Any = None) -> List[dict]:
    """Metadata only (no content blob), newest first."""
    try:
        from backend.agent.document_store import DocumentDataStore

        store = DocumentDataStore.get_for(mi or _get_mi())
        if store is None:
            return []
        out = []
        for r in store.list_by_format(RESEARCH_FMT, limit=limit, conversation_id=conversation_id or None):
            m = (r.get("variants") or {}).get("meta") or {}
            out.append({
                "id": r["document_id"], "query": m.get("query", ""),
                "created_at": m.get("created_at") or r.get("created_at"),
                "conversation_id": r.get("conversation_id") or "",
                "job_id": m.get("job_id", ""),
                "source_count": m.get("source_count", 0), "claim_count": m.get("claim_count", 0),
            })
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("[research_memory] list failed: %s", exc)
        return []


def recall_prior_research(
    query: str, *, limit: int = 3, min_similarity: float = PRIOR_MIN_SIMILARITY,
    exclude_job_id: Optional[str] = None, mi: Any = None,
) -> List[dict]:
    """Earlier research records close in MEANING to ``query`` (any conversation).

    Sync and possibly slow (it embeds the query): callers run it through
    ``PriorLookup`` so a bound applies. Never raises.
    """
    try:
        mi = mi or _get_mi()
        episodic = getattr(mi, "episodic", None) if mi is not None else None
        if episodic is None or not (query or "").strip():
            return []
        chunks = episodic.retrieve_context_chunks(
            query, limit=limit * 2, min_similarity=min_similarity,
            chunk_types=[CHUNK_TYPE], zones=[ZONE],
        )
        out: List[dict] = []
        seen: set = set()
        for chunk in chunks:
            m = _HEADER_RE.search(chunk)
            if not m or m.group(2) in seen:
                continue
            seen.add(m.group(2))
            rec = load_record(m.group(2), mi=mi)
            if rec is None or (exclude_job_id and rec.get("job_id") == exclude_job_id):
                continue
            out.append(rec)
            if len(out) >= limit:
                break
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("[research_memory] prior lookup failed q=%r: %s", (query or "")[:60], exc)
        return []


class PriorLookup:
    """A prior-research lookup running beside the web call.

    Runs on its OWN daemon thread, never the loop's default executor: a loop
    close joins default-executor threads, so a slow embedder would hang the
    tool's loop (the browser-tool bug of 2026-09-30). ``wait`` polls the thread,
    so a finished lookup costs nothing and a slow one costs at most the bound
    measured from the START (it adds no wall time when the web call is slower).
    """

    def __init__(
        self, query: str, *, exclude_job_id: Optional[str] = None, mi: Any = None,
        timeout_s: float = PRIOR_TIMEOUT_S, limit: int = 3,
        min_similarity: float = PRIOR_MIN_SIMILARITY,
    ) -> None:
        self._query = query
        self._deadline = time.monotonic() + timeout_s
        self._done = threading.Event()
        self.records: List[dict] = []
        threading.Thread(
            target=self._run, args=(exclude_job_id, mi, limit, min_similarity),
            daemon=True, name="iris-research-prior",
        ).start()

    def _run(self, exclude_job_id, mi, limit, min_similarity) -> None:
        try:
            self.records = recall_prior_research(
                self._query, limit=limit, min_similarity=min_similarity,
                exclude_job_id=exclude_job_id, mi=mi,
            )
        finally:
            self._done.set()

    async def wait(self) -> List[dict]:
        """The records, or [] once the bound passes (the work is never cancelled)."""
        while not self._done.is_set():
            if time.monotonic() >= self._deadline:
                logger.info("[research_memory] prior lookup timed out q=%r", self._query[:60])
                return []
            await asyncio.sleep(0.02)
        return self.records


def start_prior_lookup(query: str, *, exclude_job_id: Optional[str] = None) -> Optional[PriorLookup]:
    """Begin the lookup beside the web call; None if it could not start."""
    try:
        return PriorLookup(query, exclude_job_id=exclude_job_id)
    except Exception as exc:  # noqa: BLE001 - the web call goes on without it
        logger.warning("[research_memory] prior lookup not started: %s", exc)
        return None


# ── cross-check (deterministic) ────────────────────────────────────────────


def _numbers(text: str) -> set:
    return {n.replace(",", "").rstrip(".") for n in _NUM_RE.findall(text or "")}


def _subject(text: str) -> set:
    from backend.crawler.cite import _tok

    return {t for t in _tok(_NUM_RE.sub(" ", text or "")) if t not in _STOP}


def _sentences(text: str) -> List[tuple]:
    """(sentence, token set) pairs of the new evidence, bounded."""
    from backend.crawler.cite import _tok

    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [(s, _tok(s)) for s in (p.strip() for p in parts[:600]) if len(s) >= 12]


def cross_check(
    prior_records: List[dict], new_text: str, new_claims: Optional[List[str]] = None,
) -> List[dict]:
    """Label each prior claim against the new evidence.

    ``confirmed``     a new sentence holds the claim's subject and ALL its numbers
    ``changed``       the subject matches but every such sentence has other numbers
    ``not_rechecked`` no new sentence says anything about the subject
    ``new``           (from ``new_claims``) a new claim no prior claim covers

    Token overlap and number comparison only - no model on the answer path.
    """
    sents = _sentences(new_text)
    checks: List[dict] = []
    seen: set = set()
    for rec in prior_records[:3]:
        date = str(rec.get("created_at") or "")[:10]
        for claim in (rec.get("claims") or [])[:6]:
            text = str(claim.get("text") or "")
            if not text or text.lower() in seen:
                continue
            seen.add(text.lower())
            subj, nums = _subject(text), _numbers(text)
            label, evidence = "not_rechecked", ""
            if len(subj) >= 2:
                matched = [s for s, toks in sents if len(subj & toks) / len(subj) >= _SUBJECT_MATCH]
                for s in matched:
                    n = _numbers(s)
                    if not nums or nums <= n:
                        label, evidence = "confirmed", s
                        break
                    if n and label != "changed":
                        label, evidence = "changed", s
            checks.append({
                "label": label, "claim": text, "prior_date": date,
                "prior_id": rec.get("id", ""), "urls": claim.get("urls") or [],
                "new_evidence": evidence[:200],
            })
    priors = [_subject(c["claim"]) for c in checks]
    for text in new_claims or []:
        subj = _subject(text)
        if len(subj) >= 2 and not any(
            p and len(subj & p) / len(subj) >= _SUBJECT_MATCH for p in priors
        ):
            checks.append({"label": "new", "claim": str(text)[:_CLAIM_CHARS], "prior_date": "",
                           "prior_id": "", "urls": [], "new_evidence": ""})
    return checks


_LABEL_ORDER = {"changed": 0, "confirmed": 1, "new": 2, "not_rechecked": 3}


def format_prior_section(
    records: List[dict], checks: List[dict], *, today: Optional[str] = None,
) -> str:
    """PRIOR RESEARCH + CROSS-CHECK text, at most SECTION_CAP chars."""
    if not records:
        return ""
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = ["PRIOR RESEARCH (earlier searches close to this one):"]
    for rec in records[:3]:
        body = rec.get("summary") or "; ".join(
            c["text"] for c in (rec.get("claims") or [])[:2]
        )
        lines.append(f"- {str(rec.get('created_at') or '')[:10]} \"{str(rec.get('query'))[:80]}\": {body[:220]}")
    if checks:
        lines.append(f"CROSS-CHECK against the new results (today {today}):")
        for c in sorted(checks, key=lambda c: _LABEL_ORDER.get(c["label"], 9)):
            since = f" since {c['prior_date']}" if c["prior_date"] else ""
            tail = f" -> now: {c['new_evidence']}" if c["label"] == "changed" and c["new_evidence"] else ""
            lines.append(f"- {c['label']}{since}: {c['claim'][:160]}{tail}")
    out = ""
    for ln in lines:
        if len(out) + len(ln) + 1 > SECTION_CAP:
            break
        out += ln + "\n"
    return out.strip()


async def attach_prior(
    result: dict, lookup: Optional[PriorLookup], new_text: str,
    new_claims: Optional[List[str]] = None,
) -> dict:
    """Put the PRIOR + CROSS-CHECK section at the head of ``result["content"]``.

    The head survives the evidence excerpting the synthesis applies. A result
    with no close prior is returned untouched. Never raises.
    """
    try:
        if lookup is None or not isinstance(result, dict) or not result.get("success"):
            return result
        records = await lookup.wait()
        if not records:
            return result
        section = format_prior_section(records, cross_check(records, new_text, new_claims))
        if section:
            result["content"] = section + "\n\n" + (result.get("content") or "")
            result.setdefault("meta", {})["prior_research"] = [r["id"] for r in records]
            logger.info("[research_memory] prior attached ids=%s", [r["id"] for r in records])
    except Exception as exc:  # noqa: BLE001 - the web result stands without it
        logger.warning("[research_memory] attach failed: %s", exc)
    return result


# ── the recall_research tool ───────────────────────────────────────────────


async def recall_research_tool(params: dict) -> dict:
    """``recall_research``: by document_id or by query. A store READ (S11)."""
    params = params or {}
    doc_id = str(params.get("document_id") or "").strip()
    query = str(params.get("query") or "").strip()
    if not doc_id and not query:
        return {"success": False, "error": "recall_research needs a 'query' or a 'document_id'"}
    try:
        if doc_id:
            rec = load_record(doc_id)
            records = [rec] if rec else []
        else:
            records = await PriorLookup(query, timeout_s=10.0, limit=3, min_similarity=0.4).wait()
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"recall_research failed: {exc}"}
    slim = [{k: v for k, v in r.items() if k != "dashboard"} for r in records]
    if not slim:
        return {"success": True, "records": [], "content": "No earlier research found."}
    blocks = []
    for r in slim:
        claims = "\n".join(
            f"  - {c['text']}" + (f" ({', '.join(c['urls'])})" if c["urls"] else "")
            for c in r["claims"]
        )
        blocks.append(
            f"[{r['created_at'][:10]}] {r['query']} (id {r['id']})\n{r['summary']}\n{claims}".strip()
        )
    return {"success": True, "records": slim, "content": "\n\n".join(blocks)}
