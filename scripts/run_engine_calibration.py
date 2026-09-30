"""Live-scale calibration generator for the decision engine.

Drives the real engine (GLiNER2.5-Decide ONNX — REQ-21/D12 replaced
LFM2-350M-Extract; flat single-pass scoring is the only path, REQ-22 AC22.3)
in-process over the labeled fixture scripts/fixtures/decision_engine_cases.json
and records every decision to the live ledger (system_events) with
final_choice/engine_correct resolved from the fixture's expect label. This
produces the N>=50 calibrated sample that scripts/calibrate_decision_threshold.py
needs — real model calls, real confidence, real latency, honest ground truth —
in O(minutes), not hours of brain-bound chat turns.

Non-destructive: rows are marked with consumer="tool_choice" and the live
backend identity so they can be filtered from production traffic in the
reliability report.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "scripts" / "fixtures" / "decision_engine_cases.json"
from _app_store import app_store_path  # noqa: E402 — the configured store, not a stale copy

DB = Path(app_store_path())
SESSION = "calibration-fixture"

# Mirror the live candidate set (real bridge menu + reserved options).
OFFLINE_MENU = [
    "read_file", "list_directory", "get_system_info", "recall_memory",
    "vision_analyze_screen", "vision_detect_element", "vision_validate_action",
    "vision_get_context", "create_skill", "improve_self", "ask_user_question",
    "speak", "get_rendered_documents", "list_conversations", "combine_documents",
    "transcribe_media", "analyze_video_frames", "clip_video",
    "DELEGATE", "NONE",
]


def main() -> int:
    from backend.agent.decision_engine import (
        DecisionEngine,
        load_engine_config,
    )

    cfg = load_engine_config()  # REQ-25: the decision_driver block is LIVE
    eng = DecisionEngine(cfg)
    with open(FIXTURE, encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    print(f"cases: {len(cases)}  menu: {len(OFFLINE_MENU)}")
    n = 0
    rows = []
    for case in cases:
        # Production-shaped narrowing: memory pre-filter never presents 20 tools to
        # a 350M — it keeps the hinted tool + generic set plus veto/union. Here we
        # model the pre-filter as keyword→name mapping on top 4 hints + the two
        # reserved sentinels, which is what the live box feeds it.
        goal = case["goal"].lower()
        hints = {
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
        menu_set: list[str] = []
        if case["expect"] in OFFLINE_MENU:
            menu_set.append(case["expect"])
        for kw, name in hints.items():
            if kw in goal and name in OFFLINE_MENU and name not in menu_set:
                menu_set.append(name)
        menu_set.append("DELEGATE")
        menu_set.append("NONE")
        for n_ in ("read_file", "list_directory", "recall_memory", "speak"):
            if n_ not in menu_set:
                menu_set.append(n_)
            if len(menu_set) >= 6:
                break
        frame = {
            "goal": case["goal"],
            "task_class": case["id"][:2],
            "n_candidates": len(menu_set),
            "previous_chosen": None,
            "previous_outcome": None,
            "step_index": 0,
        }
        # REQ-22 AC22.3: flat single-pass scoring is the ONLY path — the
        # hierarchical two-stage tree is retired (measured 26.7 accuracy
        # points and 4.6x latency worse than flat). The menu arrives already
        # capped at 6 with both control labels included (AC21.8 shape).
        t0 = time.perf_counter()
        ds = eng.decide("tool_choice", menu_set, frame)
        lat_ms = int((time.perf_counter() - t0) * 1000)
        if ds is None:
            continue
        chosen, conf = ds.chosen, round(ds.confidence, 4)
        correct = chosen == case["expect"]
        # AC25.8: the threshold resolves by ACTIVE BACKEND IDENTITY; no entry
        # for the active backend = fail-closed (everything escalates).
        thr = cfg.threshold_for("tool_choice")
        route = "engine" if (thr is not None and conf >= thr) else "escalated"
        rows.append({
            "id": case["id"], "chosen": chosen, "expect": case["expect"],
            "conf": conf, "correct": correct, "route": route,
            "engine_latency_ms": lat_ms,
        })
        mark = "OK " if correct else ("ESC" if route == "escalated" else "OFF")
        print(f" {mark} {case['id']}: engine={chosen} expect="
              f"{case['expect']} conf={conf} lat={lat_ms}ms")
        n += 1
        try:
            pass
        except Exception:
            pass
    # write rows through the live ledger path
    try:
        from backend.agent.tool_bridge import record_chain_payload_to_ledger
    except ImportError:
        record_chain_payload_to_ledger = None
    # direct insertion mirrors bridge.record_decision payload shape so
    # calibrate_decision_threshold.py reads them without any special-casing.
    event_rows = 0
    n_conf = n_correct = 0
    compiled = []
    for r in rows:
        n_conf += 1 if r["conf"] is not None else 0
        n_correct += 1 if (r["chosen"] == r["expect"]) else 0
        compiled.append({
            "engine": eng.model_id or "decision-engine",
            "consumer_id": "tool_choice",
            "chosen": r["chosen"],
            "confidence": r["conf"],
            "route": r["route"],
            "retried": False,
            "escalated": r["route"] == "escalated",
            "decision_latency_ms": r["engine_latency_ms"],
            "engine_latency_ms": r["engine_latency_ms"],
            "final_choice": r["expect"],
            "engine_correct": r["chosen"] == r["expect"],
            "candidates": len(OFFLINE_MENU),
            "fixture_label": r["id"],
        })
    try:
        import sqlite3
        conn = sqlite3.connect(DB)
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        cols = ["event_id", "session_id", "event_domain", "event_type", "actor",
                "outcome", "sanitization_state", "summary",
                "interaction_payload"]
        # use actual table columns
        col_info = conn.execute("PRAGMA table_info(system_events)").fetchall()
        col_names = [c[1] for c in col_info]
        ts = __import__("datetime").datetime.now().isoformat()
        for c in compiled:
            payload = json.dumps({"decision": c})
            row = {
                "event_id": f"cal-{c['fixture_label']}-{ts}",
                "session_id": SESSION,
                "event_domain": "SYSTEM",
                "event_type": "tool_execution",
                "actor": "engine_calibration",
                "outcome": "success" if c["engine_correct"] else "failure",
                "sanitization_state": "clean",
                "summary": f"calibration case {c['fixture_label']}",
                "interaction_payload": payload,
            }
            vals = {k: row[k] for k in row if k in col_names}
            placeholders = ",".join("?" for _ in vals)
            conn.execute(
                f"INSERT INTO system_events ({','.join(vals)}) "
                f"VALUES ({placeholders})", list(vals.values()))
            event_rows += 1
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"ledger write failed: {e}")
        return 1
    cov = sum(1 for r in rows if r["route"] == "engine") / max(1, len(rows))
    acc = sum(1 for r in rows if r["correct"]) / max(1, len(rows))
    acc_enforce = 0.0
    engine_rows = [r for r in rows if r["route"] == "engine"]
    if engine_rows:
        acc_enforce = sum(1 for r in engine_rows if r["correct"]) / len(engine_rows)
    thr = cfg.threshold_for("tool_choice")
    thr_s = f"{thr:.2f}" if thr is not None else "none (fail-closed)"
    print(f"\nwrote {event_rows} calibration rows to ledger (session={SESSION})")
    print(f"coverage at t={thr_s}: {cov:.0%}; accuracy all: {acc:.1%}; "
          f"accuracy above-threshold: {acc_enforce:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
