"""REQ-2 contract: a stored vector's label is the backend that actually made it.

Wave 2 of specs/memory-recall-reach. Measured on the live store 2026-10-27:
374 of 3,966 sampled "lfm25-emb-350m" chunk vectors (9.4%) had more than half
their components exactly 0 - the signature of the hash fallback - because
``_encode_chunk_with`` returned a hash vector on failure and the caller stamped
it with the requested model's name. These tests FAIL on that code.

They bind the model objects directly (no sidecar, no GGUF): the contract is
about the LABEL and the SPACE of the vector, not about the model's quality.
"""
from __future__ import annotations

import pytest

from backend.memory import embedding as emb
from backend.memory.embedding import (
    BACKEND_HASH,
    BACKEND_LFM,
    EmbeddingService,
    _hash_embed,
)


class _AlwaysFails:
    def embed(self, text):  # noqa: D401 - test stub
        raise RuntimeError("embedding sidecar is down")


class _FirstChunkOnly:
    """First chunk succeeds, every later chunk fails (a mixed document)."""

    def __init__(self):
        self.calls = 0

    def embed(self, text):
        self.calls += 1
        if self.calls == 1:
            return [0.01] * 1024
        raise RuntimeError("context overrun on chunk %d" % self.calls)


class _AlwaysWorks:
    def embed(self, text):
        return [0.02] * 1024


def _service(model) -> EmbeddingService:
    svc = EmbeddingService()
    svc._backend = BACKEND_LFM
    svc._models = {BACKEND_LFM: model}
    svc._backend_loaded = True
    svc._load_active_backend = lambda: None  # never touch a real model
    return svc


def test_a_failed_model_call_is_labelled_hash_not_the_model():
    meta = _service(_AlwaysFails()).encode_with_meta("a chunk the model cannot encode")
    assert meta.backend == BACKEND_HASH, (
        "a vector from the hash fallback must never be labelled "
        f"{BACKEND_LFM!r} (got {meta.backend!r})"
    )


def test_a_mixed_document_is_never_pooled_across_two_spaces():
    # >480 whitespace words -> two chunks for the LFM chunker.
    text = " ".join(f"word{i}" for i in range(700))
    meta = _service(_FirstChunkOnly()).encode_with_meta(text)
    assert meta.backend == BACKEND_HASH
    # The truthful whole-text vector is the hash of the text. A max-pool of
    # hash and model chunks belongs to neither space and would differ here.
    assert meta.vector == pytest.approx(_hash_embed(text, 1024))


def test_a_clean_call_keeps_the_model_label():
    meta = _service(_AlwaysWorks()).encode_with_meta("clean text")
    assert meta.backend == BACKEND_LFM


def test_every_fallback_is_counted_with_its_cause_and_caller():
    svc = _service(_AlwaysFails())
    before = dict(emb.FALLBACK_COUNTERS)
    svc.encode_with_meta("counted once")
    svc.encode_with_meta("counted twice")
    after = emb.FALLBACK_COUNTERS
    assert after["texts"] - before["texts"] == 2
    assert after["chunks"] - before["chunks"] == 2
    assert after["lfm_error"] - before["lfm_error"] == 2
    assert any("test_" in caller for caller in emb.FALLBACK_CALLERS), (
        "the caller that hit the fallback must be recorded: "
        f"{emb.FALLBACK_CALLERS!r}"
    )
