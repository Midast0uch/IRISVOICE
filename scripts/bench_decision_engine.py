"""Bench: decision engine latency across plausible configs. Real model, real
paths — no fakes. Run standalone:
    .venv/Scripts/python scripts/bench_decision_engine.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.decision_engine import DecisionEngine, EngineConfig

MODEL = (r"C:\Users\midas\.lmstudio\models\mradermacher"
         r"\LFM2-350M-Extract-GGUF\LFM2-350M-Extract.Q4_K_M.gguf")

CASES = [
    ("price", "tool_choice",
     ["crawler_query", "read_file", "speak", "DELEGATE", "NONE"],
     {"goal": "find the current price of the RTX 5090 FE online"}),
    ("readme", "tool_choice",
     ["read_file", "write_file", "DELEGATE", "NONE"],
     {"goal": "read the README"}),
    ("surface", "presentation",
     ["plain_text", "prism_card", "card_plus_summary"],
     {"goal": "present a long search answer", "content_chars": "large"}),
    ("vision", "tool_choice",
     ["read_file", "vision_analyze_screen", "DELEGATE", "NONE"],
     {"goal": "take a screenshot of the chart", "needs_vision": True}),
]


def run(label: str, **cfg_kw):
    e = DecisionEngine(EngineConfig(model_path=MODEL, **cfg_kw))
    t0 = time.time()
    d0 = e.decide(*CASES[0][1:])
    warm_up_ms = round((time.time() - t0) * 1000)
    print(f"[{label}] load+warm: {warm_up_ms}ms")
    rows = []
    for name, consumer, opts, frame in CASES:
        for rep in range(2):
            t = time.time()
            d = e.decide(consumer, opts, frame)
            ms = round((time.time() - t) * 1000)
            rows.append((name, rep, ms, d.chosen if d else None,
                         round(d.confidence, 3) if d else None))
    for r in rows:
        print(f"  {r[0]:<10} rep{r[1]}: {r[1+1]:>5}ms "
              f"chosen={r[3]} conf={r[4]}")
    e.shutdown()
    return rows


if __name__ == "__main__":
    print("=== default (CPU, head-cache, tau=0.5) ===")
    run("default")
    print("\n=== n_threads=4, n_ctx=768 ===")
    run("lean-ctx")
