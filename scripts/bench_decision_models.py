"""Decision battery harness: GLiNER2.5-Decide ONNX (the deployed backend).

Scores the labeled battery (scripts/fixtures/decision_engine_cases.json) with
the per-case candidate menu, so accuracy and latency are directly comparable
to the recorded baselines (BENCH-2026-09-25-model-comparison.md).

HISTORY (REQ-21/D12): this script was the head-to-head comparison harness
(LFM2-350M-Extract vs GLiNER2.5-Decide, flat vs tree) that produced the model
decision. The LFM/tree sides are retired with the model swap — the engine has
no llama_cpp path anymore, so an LFM side routed through it would silently run
ONNX while labelled LFM. The comparison result is recorded; only the ONNX
battery remains.

READ-ONLY with respect to the ledger: unlike scripts/run_engine_calibration.py
this never writes to data/memory.db. It only prints metrics.

Run:
    .venv/Scripts/python scripts/bench_decision_models.py
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "scripts" / "fixtures" / "decision_engine_cases.json"

# Mirrors scripts/run_engine_calibration.py so the menus are identical.
OFFLINE_MENU = [
    "read_file", "list_directory", "get_system_info", "recall_memory",
    "vision_analyze_screen", "vision_detect_element", "vision_validate_action",
    "vision_get_context", "create_skill", "improve_self", "ask_user_question",
    "speak", "get_rendered_documents", "list_conversations", "combine_documents",
    "transcribe_media", "analyze_video_frames", "clip_video",
    "DELEGATE", "NONE",
]

HINTS = {
    "read": "read_file", "show": "read_file", "open": "read_file",
    "package.json": "read_file", "readme": "read_file",
    "list": "list_directory", "files": "list_directory", "folders": "list_directory",
    "remember": "recall_memory", "recall": "recall_memory", "notes": "recall_memory",
    "screen": "vision_analyze_screen", "see": "vision_analyze_screen",
    "view": "vision_analyze_screen", "gonna": "vision_analyze_screen",
    "button": "vision_detect_element", "icon": "vision_detect_element",
    "find": "vision_detect_element", "locate": "vision_detect_element",
    "confirm": "vision_validate_action", "verify": "vision_validate_action",
    "validate": "vision_validate_action",
    "time": "NONE", "joke": "NONE", "capital": "NONE", "2+2": "NONE",
    "hello": "NONE", "status": "NONE",
    "cpu": "get_system_info", "ram": "get_system_info", "gpu": "get_system_info",
    "processes": "get_system_info", "system": "get_system_info",
    "ask": "ask_user_question", "double-check": "ask_user_question",
    "say": "speak", "open microphone": "speak", "speak": "speak",
    "narrate": "speak", "ready": "speak", "turn the": "speak",
    "skill": "create_skill", "reusable": "create_skill", "codify": "create_skill",
    "improve": "improve_self", "self-review": "improve_self",
    "documents": "get_rendered_documents", "card": "get_rendered_documents",
    "rendered": "get_rendered_documents",
    "conversations": "list_conversations", "threads": "list_conversations",
    "merge": "combine_documents", "combine": "combine_documents",
    "transcribe": "transcribe_media", "meeting": "transcribe_media",
    "video": "analyze_video_frames", "frames": "analyze_video_frames",
    "clip": "clip_video", "trim": "clip_video",
}


def load_cases(path: Path | None = None) -> list[dict]:
    with open(path or FIXTURE, encoding="utf-8") as f:
        return json.load(f)["cases"]


def build_menu(case: dict) -> list[str]:
    """Same narrowing the live box applies (run_engine_calibration.py:52-97).

    REQ-9 AC9.2 (T12): a case may carry an explicit ``menu``. The two WEB intent
    classes (`search` = instant lookup, `crawler_query` = research) need
    internet-gated tools the offline menu deliberately omits, and supplying the
    menu PER CASE keeps every other case's candidate set byte-identical — so
    the Wave 8 baseline (BT-DEI-13) is untouched by adding the class battery.
    """
    if case.get("menu"):
        return list(case["menu"])
    goal = case["goal"].lower()
    menu_set: list[str] = []
    if case["expect"] in OFFLINE_MENU:
        menu_set.append(case["expect"])
    for kw, name in HINTS.items():
        if kw in goal and name in OFFLINE_MENU and name not in menu_set:
            menu_set.append(name)
    menu_set.append("DELEGATE")
    menu_set.append("NONE")
    for n_ in ("read_file", "list_directory", "recall_memory", "speak"):
        if n_ not in menu_set:
            menu_set.append(n_)
        if len(menu_set) >= 6:
            break
    return menu_set


def pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    xs = sorted(vals)
    return xs[min(len(xs) - 1, max(0, int(p * len(xs))))]


def summarise(name: str, rows: list[dict], threshold: float = 0.40) -> dict:
    n = len(rows)
    if not n:
        return {"model": name, "n": 0}
    correct = sum(1 for r in rows if r["correct"])
    above = [r for r in rows if r["conf"] is not None and r["conf"] >= threshold]
    acc_above = (
        sum(1 for r in above if r["correct"]) / len(above) if above else None
    )
    lats = [r["ms"] for r in rows]
    return {
        "model": name,
        "n": n,
        "accuracy_all": round(correct / n, 4),
        "coverage_at_threshold": round(len(above) / n, 4),
        "accuracy_above_threshold": round(acc_above, 4) if acc_above is not None else None,
        "latency_p50_ms": round(pct(lats, 0.50) or 0, 1),
        "latency_p95_ms": round(pct(lats, 0.95) or 0, 1),
        "latency_mean_ms": round(statistics.fmean(lats), 1),
        "rows": rows,
    }


def run_gliner_onnx(cases: list[dict], model_dir: str,
                    variant: str = "model_int8.onnx") -> list[dict]:
    """GLiNER2.5-Decide via its torch-free ONNX export.

    Uses the production backend (backend/agent/decision_backend_onnx.py) so
    the battery exercises the SAME code the engine runs. One exclusive task
    whose labels are the candidate menu -> softmax over labels, directly
    comparable to the engine's distribution.
    """
    from backend.agent.decision_backend_onnx import GlinerOnnx

    model = GlinerOnnx(model_dir=model_dir, variant=variant)
    rows = []
    for case in cases:
        menu_set = build_menu(case)
        frame = {
            "goal": case["goal"], "task_class": case["id"][:2],
            "n_candidates": len(menu_set), "previous_chosen": None,
            "previous_outcome": None, "step_index": 0,
        }
        t0 = time.perf_counter()
        try:
            ds = model.decide("tool_choice", menu_set, frame)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {case['id']}: {e!r}")
            continue
        ms = (time.perf_counter() - t0) * 1000
        if ds is None:
            continue
        rows.append({
            "id": case["id"], "goal": case["goal"], "expect": case["expect"],
            "chosen": ds.chosen, "conf": round(ds.confidence, 4),
            "correct": ds.chosen == case["expect"], "ms": ms,
        })
    model.shutdown()
    return rows


def print_report(res: dict, show_rows: bool = True) -> None:
    if not res.get("n"):
        print(f"[{res['model']}] no rows")
        return
    print(f"\n=== {res['model']} ===")
    print(f"  cases                : {res['n']}")
    print(f"  accuracy (all)       : {res['accuracy_all']:.1%}")
    print(f"  coverage @0.40       : {res['coverage_at_threshold']:.1%}")
    aat = res["accuracy_above_threshold"]
    print(f"  accuracy >=0.40      : {aat:.1%}" if aat is not None else
          "  accuracy >=0.40      : n/a (no confidence reported)")
    print(f"  latency p50/p95/mean : {res['latency_p50_ms']} / "
          f"{res['latency_p95_ms']} / {res['latency_mean_ms']} ms")
    if show_rows:
        wrong = [r for r in res["rows"] if not r["correct"]]
        print(f"  wrong ({len(wrong)}):")
        for r in wrong:
            print(f"    {r['id']}: chose={r['chosen']} expect={r['expect']} "
                  f"conf={r['conf']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx-dir", default=None,
                    help="dir holding the GLiNER ONNX export + tokenizer "
                         "(default: the shippable location, then C:\\temp\\gliner-onnx)")
    ap.add_argument("--onnx-variant", default="model_int8.onnx",
                    choices=["model_int8.onnx", "model_fp16.onnx", "model.onnx"])
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--cases", default=None,
                    help="alternative labeled battery (default: the 60-case "
                         "offline battery). Use scripts/fixtures/"
                         "decision_engine_web_intent_cases.json for the REQ-9 "
                         "instant-lookup-vs-research class battery.")
    args = ap.parse_args()

    cases = load_cases(Path(args.cases) if args.cases else None)
    print(f"battery: {len(cases)} labeled cases")
    print(f"\n--- running GLiNER2.5-Decide ONNX ({args.onnx_variant}) ---")
    t0 = time.time()
    try:
        rows = run_gliner_onnx(cases, args.onnx_dir, args.onnx_variant)
    except Exception as e:  # noqa: BLE001
        print(f"  ONNX path unavailable: {e!r}")
        return 2
    print(f"  ({time.time() - t0:.1f}s wall incl. session init)")
    res = summarise(f"GLiNER2.5-Decide ONNX {args.onnx_variant}", rows)
    print_report(res)

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps([{k: v for k, v in r.items() if k != "rows"}],
                       indent=2), encoding="utf-8")
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
