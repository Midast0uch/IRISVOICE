#!/usr/bin/env python
"""Standing CDD harness for Phase 4 (LFM2.5 Encoder Integration).

Asserts the 9 load-bearing invariants from design.md Wave 5 T5.2 on EVERY run.
Exits non-zero if any assertion fails. Run:  python scripts/validate_encoder_path.py

The harness is the gap-finding instrument: it replays the contracts + behaviors
that the unit/contract/behavioral suites pin, and fails loudly if any regresses.
DB-heavy re-index assertions are delegated to the dedicated (passing) behavioral
tests via subprocess, so the harness stays a single green/red gate.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed: list = []
failed: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        passed.append(name)
        print(f"  PASS  {name}")
    else:
        failed.append(name)
        print(f"  FAIL  {name}  {detail}")


def cos(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def main() -> None:
    from backend.memory.embedding import (
        EmbeddingService,
        get_embedding_service,
        BACKEND_BGE,
        BACKEND_LFM,
        BACKEND_HASH,
        max_pool,
        Chunker,
        compare_embeddings,
        CrossSpaceComparisonError,
    )

    # ── CT-E1: singleton + signatures unchanged ───────────────────────────────
    svc = get_embedding_service()
    check("CT-E1 singleton", isinstance(svc, EmbeddingService))
    v = svc.encode("hello world")
    check("CT-E1 encode 1024-dim", len(v) == 1024)
    vb = svc.encode_batch(["a", "b"])
    check("CT-E1 encode_batch", len(vb) == 2 and all(len(x) == 1024 for x in vb))

    # ── CT-E2: 1024-dim + backend tag on every persisted vector ───────────────
    meta = svc.encode_with_meta("hello world")
    check("CT-E2 dim", len(meta.vector) == 1024)
    check("CT-E2 backend tag", meta.backend in (BACKEND_BGE, BACKEND_LFM, BACKEND_HASH) and bool(meta.backend))

    # ── CT-E3: bands 0.8/0.3 + labels unchanged (no AgentKernel instantiation) ─
    from backend.agent.agent_kernel import AgentKernel

    class _S:
        _STUB_RE = re.compile(r"\[step\s+\d+\s+completed\]", re.IGNORECASE)

        def _verified_fraction(self, expected, result):
            return self._f

    for frac, label in [(0.9, "VERIFIED"), (0.5, "UNVERIFIED"), (0.1, "FAILED")]:
        s = _S()
        s._f = frac
        check(f"CT-E3 band {label}", AgentKernel._verify_step_result(s, "g", "e", "r") == label)

    # ── CT-E4: stub guard survives a scorer stubbed to 1.0 ────────────────────
    from backend.agent.verifier import SemanticVerifier

    sv = SemanticVerifier(encoder_fn=lambda a, r: 1.0)
    frac_stub, _ = sv.verified_fraction("do the thing", "[step 1 completed]")
    check("CT-E4 stub guard", frac_stub == 0.0, f"frac={frac_stub}")
    frac_ok, _ = sv.verified_fraction("do the thing", "the thing was completed")
    check("CT-E4 semantic scores", frac_ok > 0.0, f"frac={frac_ok}")

    # ── CT-E5: verified_label present (label string is the verified_label) ─────
    s = _S()
    s._f = 0.9
    lab = AgentKernel._verify_step_result(s, "g", "e", "r")
    check("CT-E5 label shape", lab in ("VERIFIED", "UNVERIFIED", "FAILED"))

    # ── CT-E6: cross-backend comparison raises; same-backend ok ───────────────
    try:
        compare_embeddings([1.0, 0.0], [BACKEND_LFM], [0.0, 1.0], [BACKEND_BGE])
        check("CT-E6 refusal", False, "no raise")
    except CrossSpaceComparisonError:
        check("CT-E6 refusal", True)
    check("CT-E6 same-space", compare_embeddings([1.0, 0.0], [BACKEND_LFM], [1.0, 0.0], [BACKEND_LFM]) == 1.0)

    # ── CT-E7: provider registration (purpose=embedding, CPU) ─────────────────
    from backend.agent.inference.provider import register_builtin_encoder_providers
    from backend.agent.inference.registry import get_provider_registry
    from backend.agent.local_model_manager import resolve_device_policy

    register_builtin_encoder_providers()
    reg = get_provider_registry()
    emb = reg.get("embedding:lfm25-emb-350m")
    check("CT-E7 registered", emb is not None)
    check("CT-E7 purpose", emb is not None and emb.purpose == "embedding")
    pol = resolve_device_policy("embedding")
    check("CT-E7 cpu", pol.device == "cpu" and pol.counts_against_vram is False and pol.ladder == ())

    # ── Assertion 3 (design): 4x-window doc retrievable from EACH chunk ────────
    def fake_embed(t):
        vec = [0.0] * 64
        for tok in t.split():
            h = int(hashlib.sha256(tok.encode()).hexdigest(), 16) % 64
            vec[h] += 1.0
        n = math.sqrt(sum(x * x for x in vec))
        return [x / n for x in vec] if n > 0 else vec

    svc._encode_chunk_with = staticmethod(lambda text, backend: fake_embed(text))
    svc._chunker_for = staticmethod(lambda backend: Chunker(window=4, chunk_tokens=4, overlap_tokens=0))
    sections = [
        "alpha one two three",
        "beta four five six",
        "gamma seven eight nine",
        "delta ten eleven twelve",
    ]
    doc = " ".join(sections)
    doc_vec = svc.encode(doc)
    for i, sec in enumerate(sections):
        q = svc.encode(sec)
        check(f"tail-retrievable chunk {i}", cos(q, doc_vec) > 0.4, f"cos={cos(q, doc_vec):.3f}")

    # ── Assertion 4 (design): max-pool is NOT mean-pool ───────────────────────
    a = [1.0, 0.0, 0.0]
    mp = max_pool([a] + [[0.0, 0.0, 0.0]] * 3)
    check("max-pool not mean", mp == [1.0, 0.0, 0.0])

    # ── Assertion 8 (design): both encoders CPU, VRAM-free ────────────────────
    check(
        "encoders cpu/vram-free",
        resolve_device_policy("embedding").counts_against_vram is False
        and resolve_device_policy("rerank").counts_against_vram is False,
    )

    # ── Assertion 9 (design): chat context derivation unaffected ───────────────
    chat_pol = resolve_device_policy("chat")
    check(
        "chat context separate",
        chat_pol.counts_against_vram is True and chat_pol.ladder != (),
    )

    # ── Assertion 6 (design): interrupted re-index resumes (delegate to tests) ──
    r = subprocess.run(
        [sys.executable, "-m", "pytest",
         "backend/tests/behavioral/test_reindex_resumes.py",
         "backend/tests/behavioral/test_reindex_write_before_mark.py",
         "-p", "no:cacheprovider", "-q"],
        capture_output=True, text=True,
    )
    check("reindex resume + write-before-mark", r.returncode == 0, r.stdout[-400:])

    print(f"\n{len(passed)} passed, {len(failed)} failed")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)
    print("ALL PHASE-4 CDD ASSERTIONS HOLD")


if __name__ == "__main__":
    main()
