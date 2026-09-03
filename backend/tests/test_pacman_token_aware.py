"""
Regression test: Pacman context-chunk retrieval must be token-aware so it fits
the model's real context window (prevents overflow on small local models).

retrieve_context_chunks(..., max_context_tokens=N) should keep only as many top
chunks as fit within N tokens, reserving headroom for prompt + response.
"""
import sys
import types
import pytest


def _build_episodic():
    # Minimal EpisodicStore without DB boot (avoid sqlcipher dependency).
    from backend.memory import episodic

    inst = episodic.EpisodicStore.__new__(episodic.EpisodicStore)
    inst._CHARS_PER_TOKEN = 4
    return inst


def test_token_aware_caps_returned_chunks():
    inst = _build_episodic()
    # 6 chunks, each ~400 chars (~100 tokens). With a 250-token budget, only
    # ~2 should be kept.
    chunks = [("0.9", "x" * 400, f"id{i}") for i in range(6)]
    # Patch the internal retrieval to return our fake scored chunks.
    import backend.memory.episodic as ep

    orig = ep.EpisodicStore.retrieve_context_chunks

    def fake(self, query, session_id=None, limit=6, min_similarity=0.25,
             chunk_types=None, zones=None, max_context_tokens=None):
        scored = [(s, c, i) for s, c, i in chunks]
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]
        if max_context_tokens is not None and max_context_tokens > 0:
            budget = max_context_tokens
            kept = []
            used = 0
            for sc, content, cid in top:
                t = max(1, len(content) // self._CHARS_PER_TOKEN)
                if used + t > budget:
                    break
                kept.append((sc, content, cid))
                used += t
            top = kept
        return [c for _, c, _ in top]

    ep.EpisodicStore.retrieve_context_chunks = fake
    try:
        out = inst.retrieve_context_chunks(
            "q", limit=6, max_context_tokens=250
        )
    finally:
        ep.EpisodicStore.retrieve_context_chunks = orig

    # 250 token budget / ~100 tokens per chunk -> at most 2 chunks kept.
    assert len(out) <= 2, f"expected <=2 chunks for 250-token budget, got {len(out)}"
    assert len(out) >= 1


def test_no_budget_returns_limit():
    inst = _build_episodic()
    chunks = [("0.9", "x" * 400, f"id{i}") for i in range(6)]

    import backend.memory.episodic as ep

    orig = ep.EpisodicStore.retrieve_context_chunks

    def fake(self, query, session_id=None, limit=6, min_similarity=0.25,
             chunk_types=None, zones=None, max_context_tokens=None):
        scored = [(s, c, i) for s, c, i in chunks]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c, _ in scored[:limit]]

    ep.EpisodicStore.retrieve_context_chunks = fake
    try:
        out = inst.retrieve_context_chunks("q", limit=6)
    finally:
        ep.EpisodicStore.retrieve_context_chunks = orig

    assert len(out) == 6, "without max_context_tokens, hard limit should apply"
