"""page_relevance and page_blocked - two SHADOW questions in the research path (2026-11-10).

Both are noul (yes/no) consults the crawler asks the Oracle about ONE fetched
page. Nothing here decides anything: the crawler still extracts every usable
page and still escalates every page it escalated before. The rows exist so the
two questions can earn the bar (docs/architecture/oracle.md, the bar section)
before any site acts on them.

page_relevance - "does this fetched page answer the question?"
  WHERE: ``CrawlOrchestrator._research_inner``, once per usable page, after
  the final fetch and BEFORE the passage split / rerank / extraction (the
  8-52 s step a future site could skip for an irrelevant page).
  FRAME: the research query, the page title, url and a bounded text head.
  Never anything from the extraction or the answer.
  LABEL (outside, joined at the turn verdict, ``turn_verdict_label``):
    True  = the turn PASSED and the extraction for this job cited the page
            (the page url is the bound source of >= 1 summary sentence or key
            finding: ``cite._bind_citations`` writes ``[n](url)``);
    False = the turn PASSED, the extraction cited at least one page, and it
            did not cite this one;
    none  = the turn FAILED (a failed answer cannot say which page was
            needed), the job consulted ONE page (the binding cites the only
            page by construction), no verdict arrives (live turns), the
            extraction never
            landed before the verdict (deferred path, or an honest rerank
            failure), or it cited no page at all (nothing to compare against).
  WHAT IT CANNOT SEE: whether the final reply used the cited claim (on the
  crawler_query path the agent reads raw page content, not the extraction);
  the citation binding is token overlap, so a near-duplicate page can take a
  sentence from the page that really carried it; pages fetched by the rerank
  re-query or the same-site hop are cited but never consulted (no row).

page_blocked - "is this page blocked from being read?"
  WHERE: ``FetchCrawlCapability.fetch_one``, at the Tier-1 -> Tier-2 fork:
  the fast HTTP fetch came back unusable (a challenge page, empty or too
  short) and the crawler is about to spend a pooled-browser fetch on it.
  FRAME: the Tier-1 page as fetched - url, title, HTTP status, text head.
  TEXT ONLY: no screenshot exists at this fork (Tier 1 is httpx, Tier 2
  takes none); the job declares no image field.
  LABEL (outside, observed AFTER the consult - the label job runs behind the
  consult job on the same FIFO lane):
    True  = the browser fetch navigated (it produced a request record) and
            ``usability.page_is_usable`` judged its content NOT usable;
    False = the browser fetch produced usable content;
    none  = the browser fetch raised before a request record (pool lease,
            launch or navigation timeout) or was cancelled (a lost crawl/vision
            race): an environment fact, not a page fact.
  Tier-1 fetches that raised (no page text) are not consulted: no frame.

Both consults run on ``lane("oracle_shadow")`` - never on the fetch path.
Bounded: the held page_blocked rows and the per-job citation sets are
drop-oldest maps, and every drop is counted (``stats``).
"""
from __future__ import annotations

import logging
import re
import threading
import uuid
from collections import OrderedDict
from typing import Any, Callable, Dict, Iterable, Optional

logger = logging.getLogger("page_shadow")

PAGE_RELEVANCE = "page_relevance"
PAGE_BLOCKED = "page_blocked"
RELEVANCE_INSTRUCTION = "Does this fetched page answer the question?"
BLOCKED_INSTRUCTION = (
    "Is this page blocked from being read (a cookie or consent wall, a login "
    "wall, a captcha, a paywall or an error page)?"
)
RELEVANCE_VERSION = "page_relevance/v1"
BLOCKED_VERSION = "page_blocked/text-v1"

# Frame caps (chars). The jobs' budgets (decision_engine ORACLE_JOBS
# judge_page 384 ids, inspect_page 256 ids) hold these with the field labels;
# the head renders LAST, so a budget cut trims the head, never the question.
_GOAL_CAP = 300
_TITLE_CAP = 150
_URL_CAP = 200
_RELEVANCE_HEAD_CAP = 800
_BLOCKED_HEAD_CAP = 600
_STATE_CAP = 2000

_MIN_JOB_PAGES = 2    # a citation can only CHOOSE between >= 2 pages
_JOB_CAP = 256        # jobs whose citation set is held for the verdict join
_HELD_CAP = 256       # page_blocked rows awaiting the browser fetch outcome
_CITED_URL = re.compile(r"\]\((https?://[^)\s]+)\)")

# Sentinel: adopt the module-level engine singleton. ``ENGINE = None`` means NO
# ENGINE - a shadow scorer never loads the model. Tests replace ENGINE.
AUTO_ENGINE = object()
ENGINE: Any = AUTO_ENGINE

_ROW_SINK: Optional[Callable[[dict], None]] = None
_LOCK = threading.Lock()
_CITED: "OrderedDict[str, frozenset]" = OrderedDict()
_HELD: "OrderedDict[str, dict]" = OrderedDict()
_STATS: Dict[str, int] = {
    "relevance_queued": 0, "blocked_queued": 0, "lane_dropped": 0,
    "no_score": 0, "cited_jobs_dropped": 0, "held_dropped": 0,
    "blocked_unlabelled": 0,
}


def _count(key: str, n: int = 1) -> None:
    with _LOCK:
        _STATS[key] = _STATS.get(key, 0) + n


def set_row_sink(sink: Optional[Callable[[dict], None]]) -> None:
    """Install (or clear) the process-wide row sink (the kernel's ledger)."""
    global _ROW_SINK
    _ROW_SINK = sink


def emit_row(row: Optional[dict]) -> None:
    """Hand a row to the installed sink, else log it. Never raises."""
    if not row:
        return
    sink = _ROW_SINK
    if callable(sink):
        try:
            sink(row)
            return
        except Exception as e:  # noqa: BLE001 - an observer never blocks
            logger.warning("[page_shadow] row sink failed consumer=%s: %r",
                           row.get("consumer_id"), e)
    logger.info("[page_shadow] row consumer=%s chosen=%s conf=%s label=%s url=%s",
                row.get("consumer_id"), row.get("chosen"), row.get("confidence"),
                row.get("outside_label"), str(row.get("url") or "")[:80])


def _register(consumer_id: str, instruction: str) -> None:
    from backend.agent.decision_engine import (
        get_consumer_spec,
        needs_upgrade,
        register_declared,
    )

    if needs_upgrade(get_consumer_spec(consumer_id)):
        register_declared(consumer_id, instruction, ("yes", "no"))


def _scope_now() -> Dict[str, str]:
    """The turn/step ids as VALUES on the caller's thread (the lane's own
    context says nothing)."""
    try:
        from backend.agent.decision_engine import scope_now

        return dict(scope_now() or {})
    except Exception:  # noqa: BLE001 - scope is best-effort
        return {}


def _flat(text: Any, cap: int) -> str:
    return " ".join(str(text or "").split())[:cap]


def relevance_frame(query: str, title: str, url: str, text: str) -> Dict[str, Any]:
    """The page_relevance frame: the question and what the fetch saw."""
    return {
        "goal": _flat(query, _GOAL_CAP),
        "title": _flat(title, _TITLE_CAP) or None,
        "url": str(url or "")[:_URL_CAP] or None,
        "page_head": _flat(text, _RELEVANCE_HEAD_CAP) or None,
    }


def blocked_frame(url: str, title: str, status: Any, text: str) -> Dict[str, Any]:
    """The page_blocked frame: the Tier-1 page as fetched (no question)."""
    return {
        "url": str(url or "")[:_URL_CAP] or None,
        "title": _flat(title, _TITLE_CAP) or None,
        "status": str(status) if status not in (None, "") else None,
        "page_head": _flat(text, _BLOCKED_HEAD_CAP) or None,
    }


def _state_and_key(consumer_id: str, frame: Dict[str, Any]) -> tuple:
    try:
        from backend.agent.decision_engine import job_input
        from backend.agent.surface_shadow import input_key

        state = job_input(consumer_id, frame).text[:_STATE_CAP]
        return state, input_key(consumer_id, state, None)
    except Exception:  # noqa: BLE001 - a replay key never blocks a row
        return "", ""


def _score(consumer_id: str, instruction: str, frame: Dict[str, Any]) -> Optional[dict]:
    """One noul consult -> the row's score fields, or None. Blocking (lane only)."""
    engine = ENGINE
    if engine is AUTO_ENGINE:
        from backend.agent.decision_engine import get_decision_engine

        engine = get_decision_engine()
    if engine is None:
        return None
    _register(consumer_id, instruction)
    noul = engine.noul(consumer_id, instruction, frame, true_label="yes", false_label="no")
    if noul is None:
        _count("no_score")
        return None
    p = float(noul.probability)
    return {
        "consumer_id": consumer_id,
        "engine": str(getattr(engine, "model_id", "") or ""),
        "chosen": p >= 0.5,
        # confidence in the CHOSEN answer; the raw P(true) beside it
        "confidence": round(max(p, 1.0 - p), 4),
        "probability": round(p, 4),
        "engine_latency_ms": getattr(noul, "engine_latency_ms", None),
        "shadow": True,
    }


# -- page_relevance -----------------------------------------------------------


def _relevance_label(row: dict, passed: bool) -> Optional[bool]:
    """The verdict-time label (see the module docstring). Never raises."""
    if not passed:
        row["unlabelled"] = "turn_failed"
        return None
    if int(row.get("job_pages") or 0) < _MIN_JOB_PAGES:
        # the binding gives every summary sentence to the best-overlap page:
        # with one page that page is cited by construction (measured in the
        # replay: 47 of 53 single-page inputs cited) - the label cannot vary
        row["unlabelled"] = "single_page_job"
        return None
    with _LOCK:
        cited = _CITED.get(str(row.get("job_id") or ""))
    if cited is None:
        row["unlabelled"] = "extraction_not_landed"
        return None
    if not cited:
        row["unlabelled"] = "extraction_cited_nothing"
        return None
    return str(row.get("url") or "") in cited


def _relevance_job(frame: Dict[str, Any], state: str, key: str, url: str,
                   job_id: str, scope: Dict[str, str], job_pages: int) -> None:
    """Lane job: score one page, then hold the row for its turn verdict."""
    try:
        row = _score(PAGE_RELEVANCE, RELEVANCE_INSTRUCTION, frame)
        if row is None:
            return
        row.update({
            "job": "judge_page", "criteria_version": RELEVANCE_VERSION,
            "input_key": key, "state": state, "url": url, "job_id": job_id,
            "job_pages": int(job_pages),
        })
        row.update(scope)
        from backend.agent import turn_verdict_label as _tvl

        if not _tvl.defer(row, emit_row, label=_relevance_label):
            row["unlabelled"] = "no_turn"
            emit_row(row)
    except Exception as e:  # noqa: BLE001 - a shadow never raises
        logger.warning("[page_shadow] relevance consult failed job_id=%s url=%s: %r",
                       job_id, url[:80], e)


def submit_page_relevance(query: str, pages: Iterable[Any], job_id: str) -> int:
    """Queue one page_relevance consult per page on the oracle_shadow lane.

    ``pages`` are the crawler's usable PageData. The values are bound NOW.
    Returns the count queued. Never raises, never blocks the crawl.
    """
    queued = 0
    try:
        from backend.utils.durability_queue import lane

        scope = _scope_now()
        distinct: Dict[str, Any] = {}
        for p in pages or ():
            url = str(getattr(p, "url", "") or "")
            if url and url not in distinct:
                distinct[url] = p
        for url, p in distinct.items():
            frame = relevance_frame(query, getattr(p, "title", ""), url,
                                    getattr(p, "markdown", "") or "")
            state, key = _state_and_key(PAGE_RELEVANCE, frame)
            if lane("oracle_shadow").submit(PAGE_RELEVANCE, _relevance_job, frame,
                                            state, key, url, str(job_id or ""), scope,
                                            len(distinct)):
                queued += 1
            else:
                _count("lane_dropped")
        _count("relevance_queued", queued)
    except Exception as e:  # noqa: BLE001
        logger.warning("[page_shadow] relevance submit failed job_id=%s: %r", job_id, e)
    return queued


def cited_urls(dashboard: Any, cited_markdown: str = "") -> frozenset:
    """The page urls the extraction bound a claim to (summary + key findings)."""
    texts = [str(cited_markdown or "")]
    if isinstance(dashboard, dict):
        texts += [str(f) for f in (dashboard.get("key_findings") or [])]
    return frozenset(m for t in texts for m in _CITED_URL.findall(t))


def note_extraction(job_id: str, dashboard: Any, cited_markdown: str = "") -> None:
    """Record which pages this job's extraction cited (the label's evidence).

    Called where the extraction lands (sync path and web_extract lane). Bounded
    drop-oldest; the drop is counted. Never raises.
    """
    try:
        jid = str(job_id or "")
        if not jid:
            return
        urls = cited_urls(dashboard, cited_markdown)
        with _LOCK:
            _CITED[jid] = urls
            _CITED.move_to_end(jid)
            while len(_CITED) > _JOB_CAP:
                _CITED.popitem(last=False)
                _STATS["cited_jobs_dropped"] += 1
    except Exception as e:  # noqa: BLE001
        logger.warning("[page_shadow] note_extraction failed job_id=%s: %r", job_id, e)


# -- page_blocked -------------------------------------------------------------


def _blocked_job(consult_id: str, frame: Dict[str, Any], state: str, key: str,
                 url: str, job_id: str, scope: Dict[str, str]) -> None:
    """Lane job 1: score the Tier-1 page and hold the row for the outcome."""
    try:
        row = _score(PAGE_BLOCKED, BLOCKED_INSTRUCTION, frame)
        if row is None:
            return
        row.update({
            "job": "inspect_page", "criteria_version": BLOCKED_VERSION,
            "input_key": key, "state": state, "url": url, "job_id": job_id,
        })
        row.update(scope)
        with _LOCK:
            _HELD[consult_id] = row
            while len(_HELD) > _HELD_CAP:
                _HELD.popitem(last=False)
                _STATS["held_dropped"] += 1
    except Exception as e:  # noqa: BLE001
        logger.warning("[page_shadow] blocked consult failed job_id=%s url=%s: %r",
                       job_id, url[:80], e)


def _blocked_label_job(consult_id: str, label: Optional[bool], reason: str) -> None:
    """Lane job 2 (FIFO behind job 1): stamp the outcome and write the row."""
    with _LOCK:
        row = _HELD.pop(consult_id, None)
    if row is None:
        return  # no score (engine away) or dropped from the bounded hold
    if label is None:
        row["unlabelled"] = reason
        _count("blocked_unlabelled")
    else:
        row["outside_label"] = bool(label)
        row["label_source"] = "outcome"
        row["label_detail"] = reason
    emit_row(row)


def submit_page_blocked(url: str, title: str, status: Any, text: str,
                        job_id: str) -> Optional[str]:
    """Queue the page_blocked consult for a page about to be escalated.

    Returns the consult id to hand to ``resolve_page_blocked``, or None when
    nothing was queued. Never raises, never blocks the fetch.
    """
    try:
        if not str(text or "").strip() and not str(title or "").strip():
            return None  # nothing the fetch saw: no frame to judge
        from backend.utils.durability_queue import lane

        frame = blocked_frame(url, title, status, text)
        state, key = _state_and_key(PAGE_BLOCKED, frame)
        consult_id = uuid.uuid4().hex
        if not lane("oracle_shadow").submit(PAGE_BLOCKED, _blocked_job, consult_id, frame,
                                            state, key, str(url or ""), str(job_id or ""),
                                            _scope_now()):
            _count("lane_dropped")
            return None
        _count("blocked_queued")
        return consult_id
    except Exception as e:  # noqa: BLE001
        logger.warning("[page_shadow] blocked submit failed job_id=%s: %r", job_id, e)
        return None


def resolve_page_blocked(consult_id: Optional[str], outcome: Any) -> None:
    """Join the browser fetch's outcome to the held consult. Never raises."""
    if not consult_id:
        return
    try:
        verdict = getattr(outcome, "verdict", None)
        if not getattr(outcome, "har_entries", None) or verdict is None:
            # raised before a request record, or cancelled (a lost race)
            label, reason = None, "no_browser_request"
        else:
            usable = bool(getattr(verdict, "usable", False))
            label = not usable
            reason = "browser_usable" if usable else (
                "browser_unusable:" + str(getattr(getattr(verdict, "reason", None), "value", "")))
        from backend.utils.durability_queue import lane

        if not lane("oracle_shadow").submit("page_blocked_label", _blocked_label_job,
                                            consult_id, label, reason):
            _count("lane_dropped")
    except Exception as e:  # noqa: BLE001
        logger.warning("[page_shadow] blocked resolve failed consult=%s: %r", consult_id, e)


def stats() -> Dict[str, int]:
    """Counters (queued, drops, unlabelled) for the log and tests."""
    with _LOCK:
        out = dict(_STATS)
        out["cited_jobs"] = len(_CITED)
        out["blocked_held"] = len(_HELD)
        return out


def reset() -> None:
    """Test seam."""
    with _LOCK:
        _CITED.clear()
        _HELD.clear()
        for k in _STATS:
            _STATS[k] = 0
