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

from .orchestrator import Passage

logger = logging.getLogger(__name__)

RERANK_THRESHOLD = float(__import__("os").environ.get("CRAWL_RERANK_THRESHOLD", "0.3"))


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


def rerank_passages(passages: list[Passage], query: str, cred_map) -> list[Passage]:
    """Rank + threshold passages (REQ-7 AC1-AC4). Returns kept passages, scored desc."""
    if not passages:
        return []
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
        return kept

    # REQ-7 AC3: signal re-query preference by leaving passages empty but marking
    # the best score so the orchestrator can narrow the query and re-run Plan->Fetch.
    if passages:
        best = max(p.score for p in passages)
        logger.info("[rerank] top score %.3f below threshold %.3f -> prefer re-query", best, RERANK_THRESHOLD)
    return []  # empty => orchestrator should re-query (handled at call site)


def _cross_encoder_rerank(passages: list[Passage], query: str) -> list[Passage]:
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
    except Exception:
        return passages  # no cross-encoder -> keep hybrid order
    try:
        model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        pairs = [(query, p.text) for p in passages]
        scores = model.predict(pairs)
        for p, s in zip(passages, scores):
            # blend: keep credibility-aware hybrid but let cross-encoder rerank
            p.score = round(0.5 * p.score + 0.5 * float(s), 4)
        return passages
    except Exception as exc:
        logger.warning("[rerank] cross-encoder unavailable: %s", exc)
        return passages
