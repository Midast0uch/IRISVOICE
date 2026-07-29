#!/usr/bin/env python3
"""
eval_embedding_quality.py — Phase 4 (REQ-8) measurement gate.

Evaluates retrieval recall@k and verification quality against probe sets.

Run from the project root::

    python scripts/eval_embedding_quality.py
    python scripts/eval_embedding_quality.py --backend bge-m3 --out results.json

Reports:
  - Retrieval recall@1 / @5 / @10, query latency, active backend.
  - Verification substring scorer baseline (both error directions).
  - Semantic scorer comparison (if encoder available).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# ── Path setup ────────────────────────────────────────────────────────────────
# Allow running from project root (the intended invocation).
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RETRIEVAL_PROBE_PATH = os.path.join(
    _project_root, "backend", "tests", "data", "retrieval_probe.json"
)
VERIFICATION_PROBE_PATH = os.path.join(
    _project_root, "backend", "tests", "data", "verification_probe.json"
)
DEFAULT_OUT_PATH = os.path.join(
    _project_root, "backend", "tests", "data", "eval_results.json"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cosine(a: List[float], b: List[float]) -> float:
    """Cosine similarity."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _substring_score(expected: str, result: str) -> Tuple[float, str]:
    """Replicate the current _verified_fraction logic for substring baseline.

    Splits *expected* on ';', for each assertion ``a`` scores 1.0 if
    ``a.lower() in result.lower()`` else 0.0. Returns (mean, scorer_tag).
    This matches ``SemanticVerifier._substring_score`` exactly.
    """
    result = (result or "").strip()
    if not result:
        return 0.0, "fallback"
    assertions = [a.strip() for a in expected.split(";") if a.strip()]
    if not assertions:
        return 1.0, "fallback"
    scores = [
        1.0 if a.lower() in result.lower() else 0.0
        for a in assertions
    ]
    return sum(scores) / len(scores), "fallback"


# ---------------------------------------------------------------------------
# Retrieval evaluation
# ---------------------------------------------------------------------------

def _load_retrieval_probes(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_retrieval_eval(
    probes: List[Dict[str, Any]],
    service: Any,
) -> Dict[str, Any]:
    """Embed corpus + queries, compute recall@k.

    Returns a result dict with recall@1/5/10, latency, and per-query details.
    """
    backend_tag = getattr(service, "backend", "unknown")
    results: List[Dict[str, Any]] = []
    latencies: List[float] = []

    for probe_idx, probe in enumerate(probes):
        query = probe["query"]
        relevant_ids = set(probe["relevant"])
        corpus = probe["corpus"]

        # ── Embed corpus docs ────────────────────────────────────────────
        doc_ids: List[str] = []
        doc_vecs: List[List[float]] = []
        for doc_id, doc_text in corpus.items():
            doc_ids.append(doc_id)
            doc_vecs.append(service.encode(doc_text))

        # ── Embed query ─────────────────────────────────────────────────
        t0 = time.perf_counter()
        qvec = service.encode(query)
        elapsed = time.perf_counter() - t0
        latencies.append(elapsed)

        # ── Rank ─────────────────────────────────────────────────────────
        sims = [_cosine(qvec, dvec) for dvec in doc_vecs]
        ranked = sorted(
            zip(doc_ids, sims), key=lambda x: x[1], reverse=True
        )
        ranked_ids = [rid for rid, _ in ranked]

        # ── Recall at each k ─────────────────────────────────────────────
        recall_at: Dict[str, float] = {}
        for k in (1, 5, 10):
            top_k = set(ranked_ids[:k])
            if relevant_ids:
                recall_at[f"recall@{k}"] = (
                    len(relevant_ids & top_k) / len(relevant_ids)
                )
            else:
                recall_at[f"recall@{k}"] = 0.0

        results.append({
            "probe_index": probe_idx,
            "query": query[:80],
            "relevant": list(relevant_ids),
            "top_1": ranked_ids[0] if ranked_ids else None,
            **recall_at,
        })

    # Aggregate
    n = len(results)
    mean_recall = {}
    for k in ("recall@1", "recall@5", "recall@10"):
        vals = [r[k] for r in results]
        mean_recall[k] = round(sum(vals) / n, 4) if n else 0.0

    return {
        "backend": backend_tag,
        "num_queries": n,
        "mean_recall": mean_recall,
        "mean_query_latency_ms": round(
            (sum(latencies) / len(latencies)) * 1000, 2
        ),
        "median_query_latency_ms": round(
            sorted(latencies)[len(latencies) // 2] * 1000, 2
        ),
        "per_query": results,
    }


# ---------------------------------------------------------------------------
# Verification evaluation
# ---------------------------------------------------------------------------

def _load_verification_probes(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _classify_verification_result(
    label: str,
    score: float,
) -> Dict[str, Any]:
    """Classify whether the score is correct or which error direction.

    Returns a dict with:
      - correct: True if score is appropriate for the label
      - false_FAILED: True if paraphrase scored 0.0 (should be >0)
      - false_VERIFIED: True if stub/vocab-overlap scored >0 (should be 0)
      - stub_rejected: True if bare_stub scored 0.0
    """
    label_lower = label.lower().replace("-", "_").replace(" ", "_")
    is_correct = False
    false_failed = False
    false_verified = False
    stub_rejected = False

    if label_lower == "paraphrase":
        # Paraphrase SHOULD score > 0 (semantic match).
        # Score == 0 means the scorer failed to recognize it = false_FAILED.
        if score > 0.0:
            is_correct = True
        else:
            false_failed = True
    elif label_lower == "genuine_failure":
        # Should score 0.
        is_correct = (score == 0.0)
    elif label_lower == "bare_stub":
        # MUST score 0 (stub guard).
        stub_rejected = (score == 0.0)
        is_correct = stub_rejected
    elif label_lower == "well_phrased_stub":
        # Should score 0 (no work done). Score > 0 = false_VERIFIED.
        if score == 0.0:
            is_correct = True
        else:
            false_verified = True
    elif label_lower == "vocab_overlap_no_satisfaction":
        # Should score 0 (doesn't actually do the work).
        if score == 0.0:
            is_correct = True
        else:
            false_verified = True
    else:
        # Unknown label — not classified.
        pass

    return {
        "correct": is_correct,
        "false_FAILED": false_failed,
        "false_VERIFIED": false_verified,
        "stub_rejected": stub_rejected,
    }


def run_verification_eval_substring(
    probes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Score verification probes with pure substring containment.

    Replicates the CURRENT ``_verified_fraction`` logic (assertion split on ';',
    exact substring match per assertion, averaged).
    """
    per_probe: List[Dict[str, Any]] = []
    counts = {
        "total": len(probes),
        "correct": 0,
        "false_FAILED": 0,
        "false_VERIFIED": 0,
        "stub_rejected": 0,
    }

    for p in probes:
        expected = p["expected"]
        result = p["result"]
        label = p["label"]

        score, scorer = _substring_score(expected, result)
        classification = _classify_verification_result(label, score)

        per_probe.append({
            "expected": expected[:80],
            "result": result[:80],
            "label": label,
            "score": round(score, 4),
            "scorer": scorer,
            **classification,
        })

        if classification["correct"]:
            counts["correct"] += 1
        if classification["false_FAILED"]:
            counts["false_FAILED"] += 1
        if classification["false_VERIFIED"]:
            counts["false_VERIFIED"] += 1
        if classification["stub_rejected"]:
            counts["stub_rejected"] += 1

    # Summarise by label
    by_label: Dict[str, Dict[str, Any]] = {}
    for p in probes:
        lbl = p["label"]
        if lbl not in by_label:
            by_label[lbl] = {"count": 0, "score_sum": 0.0}
        by_label[lbl]["count"] += 1

    for per in per_probe:
        lbl = per["label"]
        by_label[lbl]["score_sum"] += per["score"]

    label_summary = {}
    for lbl, info in by_label.items():
        label_summary[lbl] = {
            "count": info["count"],
            "mean_score": round(
                info["score_sum"] / info["count"], 4
            ),
        }

    return {
        "scorer": "substring",
        "counts": counts,
        "by_label": label_summary,
        "per_probe": per_probe,
    }


def run_verification_eval_semantic(
    probes: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Score verification probes with the SemanticVerifier (encoder if available).

    Returns None if the encoder is not available.
    """
    try:
        from backend.agent.verifier import SemanticVerifier
    except ImportError:
        return None

    verifier = SemanticVerifier(encoder_fn=None)
    # Check whether the encoder actually loaded or we're on substring fallback.
    if verifier._encoder_fn is None:
        # No encoder available at all.
        return None

    per_probe: List[Dict[str, Any]] = []
    counts = {
        "total": len(probes),
        "correct": 0,
        "false_FAILED": 0,
        "false_VERIFIED": 0,
        "stub_rejected": 0,
    }

    for p in probes:
        expected = p["expected"]
        result = p["result"]
        label = p["label"]

        try:
            score, scorer = verifier.verified_fraction(expected, result)
        except Exception:
            score, scorer = 0.0, "error"

        classification = _classify_verification_result(label, score)

        per_probe.append({
            "expected": expected[:80],
            "result": result[:80],
            "label": label,
            "score": round(score, 4),
            "scorer": scorer,
            **classification,
        })

        if classification["correct"]:
            counts["correct"] += 1
        if classification["false_FAILED"]:
            counts["false_FAILED"] += 1
        if classification["false_VERIFIED"]:
            counts["false_VERIFIED"] += 1
        if classification["stub_rejected"]:
            counts["stub_rejected"] += 1

    # Summarise by label
    by_label: Dict[str, Dict[str, Any]] = {}
    for p in probes:
        lbl = p["label"]
        if lbl not in by_label:
            by_label[lbl] = {"count": 0, "score_sum": 0.0}
        by_label[lbl]["count"] += 1

    for per in per_probe:
        lbl = per["label"]
        by_label[lbl]["score_sum"] += per["score"]

    label_summary = {}
    for lbl, info in by_label.items():
        label_summary[lbl] = {
            "count": info["count"],
            "mean_score": round(
                info["score_sum"] / info["count"], 4
            ),
        }

    return {
        "scorer": "semantic" if any(
            per["scorer"] == "semantic" for per in per_probe
        ) else "substring",
        "counts": counts,
        "by_label": label_summary,
        "per_probe": per_probe,
    }


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def _format_report(retrieval: Dict, verification: Dict,
                   semantic: Optional[Dict],
                   blocked: bool) -> str:
    """Build a human-readable report string."""
    lines = ["=" * 64, "IRIS Voice — Embedding Quality Evaluation", "=" * 64, ""]

    # ── Status line ──────────────────────────────────────────────────────
    if blocked:
        lines.append("STATUS: BLOCKED_MODEL_UNAVAILABLE")
        lines.append(
            "  No neural embedding model (BGE-M3 / LFM2.5-Embedding-350M) is "
            "available."
        )
        lines.append(
            "  All retrieval numbers below were computed with the hash "
            "fallback backend."
        )
        lines.append(
            "  These numbers are NOT comparable to a real BGE-M3 baseline."
        )
        lines.append("")

    # ── Retrieval ────────────────────────────────────────────────────────
    lines.append("─" * 64)
    lines.append("RETRIEVAL EVALUATION")
    lines.append("─" * 64)
    lines.append(f"  Active backend:       {retrieval['backend']}")
    lines.append(f"  Queries evaluated:    {retrieval['num_queries']}")
    lines.append("")
    r = retrieval["mean_recall"]
    lines.append(f"  recall@1              {r.get('recall@1', 'N/A')}")
    lines.append(f"  recall@5              {r.get('recall@5', 'N/A')}")
    lines.append(f"  recall@10             {r.get('recall@10', 'N/A')}")
    lines.append("")
    lines.append(
        f"  mean query latency:   "
        f"{retrieval['mean_query_latency_ms']} ms"
    )
    lines.append(
        f"  median query latency: "
        f"{retrieval['median_query_latency_ms']} ms"
    )
    lines.append("")

    # ── Verification: substring baseline ─────────────────────────────────
    v = verification
    lines.append("─" * 64)
    lines.append("VERIFICATION EVALUATION — Substring Scorer Baseline")
    lines.append("─" * 64)
    vc = v["counts"]
    lines.append(f"  Total probes:         {vc['total']}")
    lines.append(f"  Correct:              {vc['correct']} / {vc['total']}")
    lines.append(f"  false_FAILED:         {vc['false_FAILED']}  "
                 f"(paraphrase wrongly scored 0.0)")
    lines.append(f"  false_VERIFIED:       {vc['false_VERIFIED']}  "
                 f"(well-phrased stub / vocab overlap wrongly scored >0.0)")
    lines.append(f"  stub_rejected:        {vc['stub_rejected']}  "
                 f"(bare stubs correctly scored 0.0)")
    lines.append("")
    lines.append("  By label:")
    for lbl, info in sorted(v.get("by_label", {}).items()):
        lines.append(f"    {lbl:40s}  n={info['count']}  "
                     f"mean_score={info['mean_score']}")
    lines.append("")

    # ── Verification: semantic (if available) ────────────────────────────
    if semantic is not None:
        lines.append("─" * 64)
        lines.append("VERIFICATION EVALUATION — Semantic Scorer Comparison")
        lines.append("─" * 64)
        sc = semantic["counts"]
        lines.append(f"  Scorer used:          {semantic['scorer']}")
        lines.append(f"  Total probes:         {sc['total']}")
        lines.append(f"  Correct:              {sc['correct']} / {sc['total']}")
        lines.append(f"  false_FAILED:         {sc['false_FAILED']}")
        lines.append(f"  false_VERIFIED:       {sc['false_VERIFIED']}")
        lines.append(f"  stub_rejected:        {sc['stub_rejected']}")
        lines.append("")
        lines.append("  By label:")
        for lbl, info in sorted(semantic.get("by_label", {}).items()):
            lines.append(f"    {lbl:40s}  n={info['count']}  "
                         f"mean_score={info['mean_score']}")
    else:
        lines.append("─" * 64)
        lines.append("VERIFICATION EVALUATION — Semantic Scorer Comparison")
        lines.append("─" * 64)
        lines.append("  No semantic encoder available (hash fallback).")
        lines.append("  Semantic comparison requires LFM2.5-Embedding-350M "
                     "or compatible model.")
        lines.append("")

    lines.append("=" * 64)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="IRIS Voice — Embedding Quality Evaluation (REQ-8)",
    )
    parser.add_argument(
        "--backend",
        default=None,
        choices=["bge-m3", "lfm25-emb-350m"],
        help="Request a specific embedding backend. Falls back to hash if "
             "the requested model is unavailable.",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT_PATH,
        help=f"Path for JSON results (default: {DEFAULT_OUT_PATH})",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    # ── Load probes ──────────────────────────────────────────────────────
    print("Loading retrieval probe set...", end=" ")
    ret_probes = _load_retrieval_probes(RETRIEVAL_PROBE_PATH)
    print(f"{len(ret_probes)} queries loaded.")

    print("Loading verification probe set...", end=" ")
    ver_probes = _load_verification_probes(VERIFICATION_PROBE_PATH)
    print(f"{len(ver_probes)} probes loaded.")

    # ── Initialise embedding service ─────────────────────────────────────
    print("Initialising embedding service...", end=" ")
    sys.stdout.flush()
    from backend.memory.embedding import get_embedding_service

    service = get_embedding_service()
    active_backend = getattr(service, "backend", "unknown")
    print(f"active backend = {active_backend}")

    # If a specific backend was requested, check availability.
    requested_backend = args.backend
    if requested_backend and requested_backend != active_backend:
        available = service.available_backends() if hasattr(
            service, "available_backends"
        ) else []
        if requested_backend not in available:
            print(
                f"  Note: requested backend '{requested_backend}' is not "
                f"available. Using active backend '{active_backend}'."
            )

    is_blocked = (active_backend == "hash")

    # ── Run retrieval evaluation ─────────────────────────────────────────
    print("Running retrieval evaluation...")
    ret_results = run_retrieval_eval(ret_probes, service)

    # ── Run verification evaluation (substring baseline) ─────────────────
    print("Running verification evaluation (substring baseline)...")
    ver_substring_results = run_verification_eval_substring(ver_probes)

    # ── Run verification evaluation (semantic, if available) ─────────────
    print("Attempting verification evaluation (semantic scorer)...")
    ver_semantic_results = run_verification_eval_semantic(ver_probes)

    # ── Assemble full result ─────────────────────────────────────────────
    full_result = {
        "eval_tool": "scripts/eval_embedding_quality.py",
        "phase": "phase-4-encoder",
        "gate": "REQ-8",
        "status": "BLOCKED_MODEL_UNAVAILABLE" if is_blocked else "OK",
        "retrieval": ret_results,
        "verification_substring": ver_substring_results,
        "verification_semantic": ver_semantic_results,
    }

    # ── Write output ─────────────────────────────────────────────────────
    out_path = args.out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(full_result, f, indent=2, ensure_ascii=False)
    print(f"\nResults written to {out_path}")

    # ── Print report ─────────────────────────────────────────────────────
    report = _format_report(
        ret_results, ver_substring_results, ver_semantic_results, is_blocked
    )
    print()
    print(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
