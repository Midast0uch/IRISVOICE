"""
Passage reranking (REQ-7).

Hybrid scoring: BM25 + embedding similarity to the query. A cross-encoder reranker
is applied over the top candidates when available; otherwise the hybrid score is
used. Passages below the threshold are dropped. When the top score is below
threshold, the caller is signaled to prefer re-querying (REQ-7 AC3).

Embedding / cross-encoder models are OPTIONAL and imported lazily so the funnel
works without them (falls back to BM25-only). No network calls at import time.
"""
from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

from .orchestrator import Passage

logger = logging.getLogger(__name__)

RERANK_THRESHOLD = float(__import__("os").environ.get("CRAWL_RERANK_THRESHOLD", "0.3"))


class RerankState(str, Enum):
    """Distinguishable rerank return states (REQ-3 AC1).

    The old bare ``[]`` collapsed two very different situations into one
    value whose meaning lived only in a comment. Callers must be able to tell
    "nothing was produced" from "content was produced but all of it scored
    below threshold" because they escalate differently.
    """

    OK = "ok"                        # >=1 passage kept
    NO_PASSAGES = "no_passages"      # input was empty (page set empty — REQ-2 covers it)
    BELOW_THRESHOLD = "below_threshold"  # scored but every score < threshold


@dataclass
class RerankOutcome:
    """Return type of :func:`rerank_passages` (REQ-3).

    Iterable over ``kept`` so existing callers that treated the old return as
    a plain list (``for p in kept``) keep working; the ``state`` and
    ``top_score`` are the actionable signal for the orchestrator.
    """

    state: RerankState
    kept: list[Passage] = field(default_factory=list)
    top_score: float = 0.0

    def __iter__(self):
        return iter(self.kept)

    def __len__(self) -> int:
        return len(self.kept)

# ── Cross-encoder refinement (OFF by default — see _cross_encoder_rerank) ──
# The hybrid score (BM25 + embedding cosine + credibility) is a complete
# ranking on its own. The cross-encoder only re-sorts it, at the cost of
# loading a transformer in the request path, so it is opt-in.
CROSS_ENCODER_ENABLED = (
    __import__("os").environ.get("CRAWL_CROSS_ENCODER", "0").strip().lower()
    in ("1", "true", "yes", "on")
)
CROSS_ENCODER_MODEL = __import__("os").environ.get(
    "CRAWL_CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
)
# Below this many candidates a reorder cannot repay a model load.
CROSS_ENCODER_MIN_CANDIDATES = int(
    __import__("os").environ.get("CRAWL_CROSS_ENCODER_MIN_CANDIDATES", "8")
)


# ---------------------------------------------------------------------------
# BM25 (no deps)
# ---------------------------------------------------------------------------
_STOP = set("the a an and or of to in for on with is are was were be been being this that these those it its as at by from".split())


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOP]


def _bm25(query_tokens: list[str], docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    n = len(docs)
    if n == 0:
        return []
    df: dict[str, int] = defaultdict(int)
    for d in docs:
        for t in set(d):
            df[t] += 1
    avg_len = sum(len(d) for d in docs) / max(1, n)
    scores: list[float] = []
    for d in docs:
        dl = len(d)
        score = 0.0
        freq = defaultdict(int)
        for t in d:
            freq[t] += 1
        for qt in query_tokens:
            if qt not in df:
                continue
            f = freq.get(qt, 0)
            if f == 0:
                continue
            idf = math.log((n - df[qt] + 0.5) / (df[qt] + 0.5) + 1)
            score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / max(1, avg_len)))
        scores.append(score)
    return scores


# ---------------------------------------------------------------------------
# Embedding similarity (optional, lazy)
# ---------------------------------------------------------------------------
def _embed(texts: list[str]) -> Optional[list[list[float]]]:
    """Encode texts via EmbeddingService (Phase 4 LFM2.5 integration).

    Routes through ``EmbeddingService.encode`` instead of loading a
    standalone SentenceTransformer, so the same backend selection and
    chunking logic applies (T1.6).
    """
    try:
        from backend.memory.embedding import get_embedding_service
        svc = get_embedding_service()
        return [svc.encode(t) for t in texts]
    except Exception as exc:
        logger.warning("[rerank] embedding service unavailable: %s", exc)
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def rerank_passages(passages: list[Passage], query: str, cred_map) -> RerankOutcome:
    """Rank + threshold passages (REQ-7 AC1-AC4).

    Returns a :class:`RerankOutcome` (REQ-3 AC1): ``NO_PASSAGES`` when nothing
    was produced (an empty page set is REQ-2's concern — do not double
    escalate), ``BELOW_THRESHOLD`` when content was scored but nothing met the
    bar (the caller MUST escalate, never cite empty), and ``OK`` with the kept
    passages otherwise. The outcome is iterable over kept passages for
    backward compatibility with list-style callers.
    """
    if not passages:
        return RerankOutcome(state=RerankState.NO_PASSAGES)
    q_tokens = _tokenize(query)
    doc_tokens = [_tokenize(p.text) for p in passages]
    bm25 = _bm25(q_tokens, doc_tokens)

    emb_query = None
    emb_docs = _embed([p.text for p in passages])
    if emb_docs:
        q_emb = _embed([query])
        emb_query = q_emb[0] if q_emb else None

    for i, p in enumerate(passages):
        hybrid = bm25[i] if i < len(bm25) else 0.0
        if emb_query is not None and emb_docs is not None:
            sim = _cosine(emb_query, emb_docs[i])
            hybrid = 0.5 * hybrid + 0.5 * sim
        # credibility weighting (REQ-5/7): credible sources rank higher
        src_cred = cred_map.per_source.get(p.url, 0.5) if cred_map else 0.5
        p.score = round(hybrid * (0.6 + 0.4 * src_cred), 4)

    # cross-encoder rerank over top candidates (optional)
    passages = _cross_encoder_rerank(passages, query)

    passages.sort(key=lambda p: p.score, reverse=True)

    # threshold drop (REQ-7 AC2)
    kept = [p for p in passages if p.score >= RERANK_THRESHOLD]
    if kept:
        return RerankOutcome(
            state=RerankState.OK, kept=kept,
            top_score=max(p.score for p in kept),
        )

    # REQ-7 AC3 / REQ-3 AC1: signal re-query preference EXPLICITLY — the old
    # bare `[]` with the comment "handled at call site" was never handled at
    # the call site (orchestrator fell through to citation with empty
    # passages). Callers must distinguish this from an empty input.
    best = max(p.score for p in passages)
    logger.info(
        "[rerank] top score %.3f below threshold %.3f -> prefer re-query",
        best, RERANK_THRESHOLD,
    )
    return RerankOutcome(state=RerankState.BELOW_THRESHOLD, top_score=best)


def _cross_encoder_rerank(passages: list[Passage], query: str) -> list[Passage]:
    """Optional refinement pass. Returns ``passages`` unchanged when skipped.

    THIS IS A REFINEMENT, NOT A REQUIREMENT. By the time it is called, every
    passage already carries a complete hybrid score: BM25 lexical + embedding
    cosine + source-credibility weighting (see rerank_passages above). The
    cross-encoder only re-sorts an ordering that already exists.

    It is therefore OFF BY DEFAULT. Three things went wrong when it was on and
    unconditional:

    1. It loaded a transformer INSIDE THE REQUEST PATH. On this host
       ``import sentence_transformers`` takes ~13 minutes (torchcodec 0.13
       probes FFmpeg 4-7; the host has FFmpeg 8), and a live stack dump caught
       a DER web-search step parked on exactly this line.
    2. Its ``except Exception`` guard was UNREACHABLE. It was written for
       "cross-encoder not installed", but a hang is not an exception, so the
       intended graceful degrade could never run.
    3. It ran for ANY candidate count. Re-sorting a handful of passages from
       two pages cannot repay a model load.

    Note ``_embed`` above already routes through ``EmbeddingService`` rather
    than loading a standalone SentenceTransformer — this function is now
    consistent with that discipline instead of bypassing it.

    Enable with CRAWL_CROSS_ENCODER=1. When enabled the load is bounded and
    logged via backend.utils.heavy_import, and a timeout degrades to the
    hybrid order the caller already has.
    """
    if not CROSS_ENCODER_ENABLED:
        return passages
    if len(passages) < CROSS_ENCODER_MIN_CANDIDATES:
        logger.debug(
            "[rerank] %d passage(s) < %d — cross-encoder not worth a model load",
            len(passages), CROSS_ENCODER_MIN_CANDIDATES,
        )
        return passages

    from backend.utils.heavy_import import load_bounded

    def _load():
        from sentence_transformers import CrossEncoder  # type: ignore

        return CrossEncoder(CROSS_ENCODER_MODEL)

    model = load_bounded(f"cross-encoder:{CROSS_ENCODER_MODEL}", _load)
    if model is None:
        # Bounded loader already logged why. Keep the hybrid order — exactly
        # what the original (unreachable) fallback intended.
        return passages

    try:
        scores = model.predict([(query, p.text) for p in passages])
        for p, s in zip(passages, scores):
            # blend: keep credibility-aware hybrid but let cross-encoder rerank
            p.score = round(0.5 * p.score + 0.5 * float(s), 4)
        return passages
    except Exception as exc:
        logger.warning("[rerank] cross-encoder scoring failed: %s", exc)
        return passages
