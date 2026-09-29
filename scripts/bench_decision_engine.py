"""Bench: decision engine latency + accuracy assertions (REQ-6 AC6.2/AC6.3, T7;
REQ-30 AC30.6/AC30.7/AC30.8, T38).

Real ONNX backend, real paths — no fakes. Asserts:
  * CPU decision scoring <= 180ms p50 (the sub-450ms target's scoring stage)
  * zero vision false positives across the search question battery — a
    factual search query must never choose a vision tool

REQ-30 (T38) adds the two things that make a tuning change ATTRIBUTABLE:
  * the per-stage latency breakdown (tokenize / encode / session / post), so a
    delta can be blamed on a stage instead of on "the engine";
  * a RECORDED baseline (p50/p95/accuracy) that every run is measured against,
    with a p95 regression recorded and reported for revert rather than kept
    silently (AC30.8). A regression is never absorbed into the baseline.

HISTORY (REQ-21/D12): the LFM GGUF configs this bench used to sweep are
retired with the model swap; the assertions are the surviving instrument.

Run standalone:
    .venv/Scripts/python scripts/bench_decision_engine.py
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.decision_engine import DecisionEngine, load_engine_config

# Search question battery: factual lookups that must NEVER choose a vision
# tool (REQ-6 AC6.3 / T7 — zero vision false positives).
SEARCH_CASES = [
    ("price", "find the current price of the RTX 5090 FE online"),
    ("weather", "what's the weather in Seattle"),
    ("capital", "what's the capital of France"),
    ("news", "search for the latest news about the merger"),
    ("lookup", "look up the population of Japan"),
]

VISION_CASES = [
    ("chart", "take a screenshot of the chart"),
    ("button", "find the button on the image"),
]

MENU = ["crawler_query", "read_file", "speak", "recall_memory",
        "vision_analyze_screen", "NONE"]

# AC30.7/AC30.8: the recorded baseline every run is measured against.
BASELINE_PATH = (
    Path(__file__).resolve().parent.parent
    / "benchmarks" / "decision_engine_baseline.json"
)
# A p95 within this fraction of the baseline is noise, not a regression.
P95_TOLERANCE = 0.15


def _load_baseline() -> dict:
    try:
        if BASELINE_PATH.is_file():
            return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — an unreadable baseline is absent
        print(f"  [baseline] unreadable ({exc}) — treating as absent")
    return {}


def _save_baseline(payload: dict) -> None:
    try:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"  [baseline] recorded -> {BASELINE_PATH}")
    except Exception as exc:  # noqa: BLE001 — recording is best-effort
        print(f"  [baseline] write failed ({exc})")


def _stage_breakdown(engine: DecisionEngine) -> dict:
    """AC30.6: the backend's per-stage breakdown for the last call."""
    backend = getattr(engine, "_backend", None)
    return dict(getattr(backend, "stage_ms", None) or {})


def _detect_regressions(observed: dict, baseline: dict) -> list:
    """AC30.7/AC30.8: compare this run against the RECORDED baseline.

    Returns a list of human-readable regression strings (empty = no
    regression). p95 is allowed `P95_TOLERANCE` of noise; accuracy is not
    allowed to drop at all. An absent baseline is not a regression — it is
    simply not yet recorded.
    """
    out: list = []
    if not baseline:
        return out
    base_p95 = baseline.get("p95_ms")
    base_acc = baseline.get("accuracy")
    p95 = observed.get("p95_ms")
    acc = observed.get("accuracy")
    if isinstance(base_p95, (int, float)) and isinstance(p95, (int, float)):
        if p95 > base_p95 * (1.0 + P95_TOLERANCE):
            out.append(
                f"p95 {p95}ms > baseline {base_p95}ms "
                f"(+{(p95 / base_p95 - 1) * 100:.0f}%, tolerance "
                f"{P95_TOLERANCE * 100:.0f}%)"
            )
    if isinstance(base_acc, (int, float)) and isinstance(acc, (int, float)):
        if acc < base_acc:
            out.append(f"accuracy {acc:.3f} < baseline {base_acc:.3f}")
    return out


def main() -> int:
    cfg = load_engine_config()
    e = DecisionEngine(cfg)
    t0 = time.time()
    d0 = e.decide("tool_choice", MENU, {"goal": "warm"})
    warm_up_ms = round((time.time() - t0) * 1000)
    print(f"[load+warm] {warm_up_ms}ms  backend={e.model_id}")

    rows = []
    vision_fps = []
    for name, goal in SEARCH_CASES + VISION_CASES:
        for rep in range(3):
            t = time.time()
            d = e.decide("tool_choice", MENU, {"goal": goal})
            ms = round((time.time() - t) * 1000)
            chosen = d.chosen if d else None
            conf = round(d.confidence, 3) if d else None
            rows.append((name, rep, ms, chosen, conf))
            is_search = (name, goal) in SEARCH_CASES
            if is_search and chosen is not None and chosen.startswith("vision"):
                vision_fps.append((name, chosen, conf))
            print(f"  {name:<10} rep{rep}: {ms:>5}ms chosen={chosen} conf={conf}")

    lats = sorted(r[2] for r in rows)
    p50 = statistics.median(lats)
    # Nearest-rank p95 on a small battery — honest for n=21, no interpolation.
    p95 = lats[max(0, min(len(lats) - 1, int(round(0.95 * len(lats))) - 1))]
    scored = [r for r in rows if r[3] is not None]
    accuracy = round(len(scored) / len(rows), 4) if rows else 0.0

    print(f"\n  scoring p50: {p50:.0f}ms  p95: {p95}ms  (assert p50 <= 180ms)")
    print(f"  scored: {len(scored)}/{len(rows)}  accuracy={accuracy:.3f}")
    print(f"  vision false positives on search: {len(vision_fps)} (assert 0)")
    for name, chosen, conf in vision_fps:
        print(f"    FP {name}: chose={chosen} conf={conf}")

    # AC30.6: attribute the time to a stage.
    stages = _stage_breakdown(e)
    if stages:
        print(
            "  breakdown (last call): "
            + "  ".join(f"{k}={v}ms" for k, v in sorted(stages.items()))
        )
    else:
        print("  breakdown: unavailable (backend exposed no stage_ms)")

    opts = getattr(getattr(e, "_backend", None), "session_options", None)
    if opts:
        print(
            "  session options: "
            + ", ".join(f"{k}={v}" for k, v in sorted(opts.items()))
        )

    e.shutdown()

    # ── AC30.7/AC30.8: measured against the recorded baseline ──────────────
    baseline = _load_baseline()
    observed = {"p50_ms": p50, "p95_ms": p95, "accuracy": accuracy}
    regressions = _detect_regressions(observed, baseline)
    if baseline:
        print(
            f"  [baseline] p95 {p95}ms vs {baseline.get('p95_ms')}ms  "
            f"accuracy {accuracy:.3f} vs {baseline.get('accuracy')}"
        )
    else:
        print("  [baseline] absent — recording this run as the baseline")

    failures = 0
    if p50 > 180:
        print("FAIL: scoring p50 > 180ms (REQ-6 AC6.2)")
        failures += 1
    if vision_fps:
        print("FAIL: vision false positives on search queries (REQ-6 AC6.3)")
        failures += 1
    if regressions:
        # AC30.8: record it and say so — never keep a regression silently.
        for r in regressions:
            print(f"REGRESSION (recorded, revert required): {r}")
        failures += 1
        baseline.setdefault("regressions", []).append(
            {"p50_ms": p50, "p95_ms": p95, "accuracy": accuracy,
             "detail": regressions}
        )
        _save_baseline(baseline)
    elif not baseline:
        _save_baseline({
            "p50_ms": p50, "p95_ms": p95, "accuracy": accuracy,
            "warm_up_ms": warm_up_ms, "backend": e.model_id,
            "stage_ms": stages, "session_options": opts,
        })
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
