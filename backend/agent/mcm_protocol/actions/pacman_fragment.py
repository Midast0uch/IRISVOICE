"""
Action: pacman_fragment
Stores the current LLM response as an episodic fragment for future recall.
Skips conversational turns — only stores tool outputs and DER results.
"""
from __future__ import annotations
import logging
import queue
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Minimum chars to bother storing
_MIN_FRAGMENT_CHARS = 80

# Keywords that indicate a DER/tool output worth storing
_DER_SIGNALS = [
    "completed", "created", "updated", "wrote", "found", "error",
    "step", "result", "output", "tool", "file", "function",
]

# Tools whose output derives from external/web sources. Their fragments are
# routed to the 'reference' zone (episodic.py:_ZONE_REFERENCE, reserved for
# "external content (future)") so untrusted web content is never mixed into
# the trusted/user or tool zones. See trust-routing plan W1.
_EXTERNAL_TOOLS = frozenset({"web_search", "crawler_query"})

# Zone used for external/web-derived fragments. Reuses the existing 'reference'
# slot rather than introducing a new enum value (plan decision #1).
_EXTERNAL_ZONE = "reference"


def _zone_for_tool(tool_name: str) -> str | None:
    """Return the zone a fragment should land in for ``tool_name``.

    External/web tools -> 'reference'; everything else -> None (let
    EpisodicStore apply its chunk_type default: trusted / tool).
    """
    if tool_name and tool_name in _EXTERNAL_TOOLS:
        return _EXTERNAL_ZONE
    return None


def is_external_tool(tool_name: str) -> bool:
    """True if ``tool_name`` derives output from external/web sources.

    Shared by W1 (zone routing) and W2 (per-turn external flag) so the
    external-tool vocabulary lives in exactly one place.
    """
    return bool(tool_name) and tool_name in _EXTERNAL_TOOLS


def _serialize_credibility(meta: dict) -> str:
    """Compact, stable JSON for credibility/citation metadata (REQ-22)."""
    import json
    try:
        return json.dumps(meta, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        return json.dumps({"_unserializable": True}, default=str)


def _store_credibility_metadata(episodic, session_id: str, tool_name: str,
                                 credibility_map, citation_index) -> None:
    """Persist credibility + citation provenance to the 'reference' (untrusted)
    zone so untrusted web scoring is recallable but never mixed into trusted
    zones (REQ-22). Never raises.
    """
    try:
        payload: dict = {}
        if credibility_map is not None:
            # CredibilityMap may be a dataclass or dict; normalize to primitives.
            if hasattr(credibility_map, "__dict__"):
                cm = {k: v for k, v in vars(credibility_map).items()
                      if not k.startswith("_")}
            elif isinstance(credibility_map, dict):
                cm = credibility_map
            else:
                cm = {"value": str(credibility_map)}
            payload["credibility_map"] = cm
        if citation_index is not None:
            payload["citation_index"] = citation_index
        if not payload:
            return
        blob = (
            f"<CREDIBILITY_META tool={tool_name}>\n"
            f"{_serialize_credibility(payload)}\n"
            f"</CREDIBILITY_META>"
        )
        episodic.fragment_and_store(
            content=blob,
            session_id=session_id,
            chunk_type="der_output",
            zone=_EXTERNAL_ZONE,  # reference / untrusted
            tool_name=tool_name or None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[pacman_fragment] credibility metadata skipped: %s", exc)


def fragment_document_provenance(episodic, document_id: str, conversation_id: str,
                                 sources: list, har_path: str | None = None) -> None:
    """Write a document-linked, queryable reference-zone entry carrying a
    document's full provenance (sources + HAR evidence path). Complements the
    ``document_data`` columns so future recall can retrieve provenance by
    ``document_id`` (REQ-17), not just as an opaque blob.

    Reuses the existing ``reference`` zone + episodic store. Never raises
    (T0d degradation: a Pacman write failure must not affect the doc store).
    """
    try:
        if not episodic or not hasattr(episodic, "fragment_and_store"):
            return
        if not document_id:
            return
        payload = {
            "document_id": document_id,
            "conversation_id": conversation_id,
            "sources": sources or [],
            "har_path": har_path,
        }
        blob = (
            f"<DOC_PROVENANCE document_id=\"{document_id}\" "
            f"conversation_id=\"{conversation_id}\">\n"
            f"{_serialize_credibility(payload)}\n"
            f"</DOC_PROVENANCE>"
        )
        episodic.fragment_and_store(
            content=blob,
            session_id=conversation_id,
            chunk_type="der_output",
            zone=_EXTERNAL_ZONE,  # reference / untrusted
            tool_name="crawler_query",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[pacman_fragment] document provenance skipped: %s", exc)


# ── Off-critical-path fragment writer (2026-08-17) ─────────────────────────
# Storing a fragment means EMBEDDING it, and the embedder is CPU-only by spec
# (REQ-1 AC6 / Phase 3 — n_gpu_layers=0 in memory/embedding.py). Measured on
# this host: 2.9 s per ~1 KB chunk, so a 14-chunk tool result costs ~41 s.
#
# That was being paid INSIDE the DER step loop, so the user's answer waited on
# memory bookkeeping: last step finished 12:16:00, answer arrived 12:17:19.
# Roughly 70 of those 79 seconds were embedding, not thinking.
#
# This action is already contractually best-effort ("Never blocks", "a Pacman
# write failure must not affect the doc store"), so moving it off the turn's
# critical path keeps the contract and returns the time to the user. A SINGLE
# serialized worker (not a thread per call) so CPU embedding never thrashes,
# and a bounded queue so a burst degrades by dropping the oldest bookkeeping
# rather than growing without limit.
_FRAGMENT_QUEUE: "queue.Queue[tuple[Callable[[], None], str]]" = queue.Queue(maxsize=64)
_FRAGMENT_WORKER: Optional[threading.Thread] = None
_FRAGMENT_WORKER_LOCK = threading.Lock()


def _fragment_worker_loop() -> None:
    # Filing happens in the background, so nothing downstream waits on it and
    # nothing checks that it landed (user decision 2026-08-17: speed preferred).
    # That makes the LOG the only evidence the note was actually filed — every
    # job reports success or failure at INFO with its queue depth, so a silent
    # breakage is visible in the log instead of showing up as missing memory
    # weeks later.
    while True:
        job, label = _FRAGMENT_QUEUE.get()
        _t0 = time.time()
        try:
            job()
            logger.info(
                "[pacman_fragment] FILED %s in %.1fs (queue depth %d)",
                label, time.time() - _t0, _FRAGMENT_QUEUE.qsize(),
            )
        except Exception as exc:  # noqa: BLE001 — bookkeeping never escalates
            logger.error(
                "[pacman_fragment] FILE FAILED %s after %.1fs: %s",
                label, time.time() - _t0, exc, exc_info=True,
            )
        finally:
            _FRAGMENT_QUEUE.task_done()


def _submit_fragment_job(job: "Callable[[], None]", label: str = "fragment") -> bool:
    """Hand a store to the background worker. True if queued.

    Returns False when the queue is saturated so the caller can decide; the
    caller drops it, because a late fragment is worth less than a stalled turn.
    """
    global _FRAGMENT_WORKER
    if _FRAGMENT_WORKER is None or not _FRAGMENT_WORKER.is_alive():
        with _FRAGMENT_WORKER_LOCK:
            if _FRAGMENT_WORKER is None or not _FRAGMENT_WORKER.is_alive():
                _FRAGMENT_WORKER = threading.Thread(
                    target=_fragment_worker_loop,
                    daemon=True,
                    name="iris-pacman-fragment",
                )
                _FRAGMENT_WORKER.start()
    try:
        _FRAGMENT_QUEUE.put_nowait((job, label))
        return True
    except queue.Full:
        # Loud: a dropped fragment is memory that will never exist, and the
        # user explicitly asked to be able to track filing failures.
        logger.error(
            "[pacman_fragment] QUEUE FULL — dropped %s (memory not filed)", label,
        )
        return False


def _is_fragment_candidate(text: str) -> bool:
    """Return True if text looks like a DER step output worth storing."""
    if len(text) < _MIN_FRAGMENT_CHARS:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in _DER_SIGNALS)


def execute(ctx: dict, params: dict) -> dict:
    """
    ctx keys read:    mi, session_id, response_text, tool_name
    Never raises.
    """
    try:
        mi            = ctx.get("mi")
        response_text = ctx.get("response_text", "")
        tool_name     = ctx.get("tool_name", "")
        session_id    = ctx.get("session_id", "")

        if not mi or not response_text:
            return ctx

        episodic = getattr(mi, "episodic", None)
        if not episodic or not hasattr(episodic, "fragment_and_store"):
            return ctx

        # Strip MCM_MITO tags before storing
        import re
        clean_text = re.sub(r"<MCM_MITO>.*?</MCM_MITO>", "", response_text,
                            flags=re.DOTALL).strip()

        _is_external = is_external_tool(tool_name)
        _credibility = ctx.get("credibility_map")
        _citations = ctx.get("citation_index")
        _store_content = _is_fragment_candidate(clean_text)
        if not _store_content and not _is_external:
            return ctx

        chunk_type = "der_output" if tool_name else "context_fragment"
        # An explicit zone hint (e.g. from a turn that touched external
        # sources) wins; otherwise route by tool_name. See trust-routing W2.
        zone = ctx.get("zone") or _zone_for_tool(tool_name)

        def _do_store() -> None:
            # Credibility/citation provenance for external/web tools (REQ-22)
            # goes in BEFORE the content fragment, so the untrusted scoring is
            # recallable in the reference zone. Order preserved by running both
            # inside one job on the single serialized worker.
            if _is_external:
                _store_credibility_metadata(
                    episodic, session_id, tool_name, _credibility, _citations,
                )
            if _store_content:
                episodic.fragment_and_store(
                    content=clean_text,
                    session_id=session_id,
                    chunk_type=chunk_type,
                    zone=zone,
                    tool_name=tool_name or None,
                )
                logger.debug(
                    "[pacman_fragment] stored %s fragment (%d chars)",
                    chunk_type, len(clean_text),
                )

        _submit_fragment_job(
            _do_store,
            f"{chunk_type}/{tool_name or 'conversation'} ({len(clean_text)} chars)",
        )

    except Exception as exc:
        logger.debug("[pacman_fragment] skipped: %s", exc)

    return ctx
