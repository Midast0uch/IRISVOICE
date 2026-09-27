#!/usr/bin/env python3
"""Per-consumer enforcement report — the T22/T52 instrument (REQ-31, TG-7).

WHAT IT DOES
    Reads the decision rows the engine already writes into `data/memory.db`
    (`system_events.event_type='tool_execution'`, the `decision` block), groups
    them BY CONSUMER, and reports for each one:

        rows, rows above threshold, precision, ECE, Brier

    then derives the enforcement status against TG-7's bar (>= 100 rows AND
    precision >= 0.90 AND ECE <= bound) and, with `--write`, persists the
    result to `benchmarks/consumer_bar_record.json` via
    `backend.agent.consumer_bar.record_bars`.

WHY IT EXISTS
    Wave 7 flips a consumer to enforced only on measured evidence. The bar
    record existed (`consumer_bar.py`) but nothing wrote it, so "why is this
    consumer enforced?" had no answer and a flip measured at a superseded
    configuration could not be detected (AC31.5/AC31.6). This is that caller.

THE LABEL (be explicit — a precision number is meaningless without it)
    A DISPATCHED row (a real tool ran) is correct when the event outcome is
    `success`/`reason` — the same rule `scripts/calibrate_decision_threshold.py`
    (`_load_decisions`) already applies, kept identical on purpose so the two
    instruments cannot disagree.

    A SHADOW row (the engine scored, the legacy path decided — `route="shadow"`)
    is correct when the engine's `chosen` AGREES with the Brain's ACTUAL answer.
    That agreement IS the parity TG-7 measures (BT-DEI-8): the row carries both
    halves, so the reference is recorded, not assumed. The reference arrives in
    one of two shapes, because consumers answer in two kinds (2026-09-27):

      - `brain_bool`  — a BOOL consumer (sufficient, done, on_track, has_gaps,
        use_thinking, escalate_incomplete, needs_action). The Brain's answer IS
        a boolean, so `chosen` is compared as a boolean.
      - `brain_choice` — a LABEL consumer (mode, review_verdict, web_intent,
        recovery_strategy, retry_same, tool_choice, presentation, narration).
        Its answer is a NAME, and comparing names is the only honest test:
        collapsing a name to a bool would manufacture agreement and inflate
        precision.

    A shadow row with neither reference carries NO label and is counted
    separately as skipped — never silently scored as correct.

READ-ONLY apart from `--write`. Never hits the network.

Usage:
    python scripts/consumer_enforcement_report.py                 # report
    python scripts/consumer_enforcement_report.py --json          # machine
    python scripts/consumer_enforcement_report.py --write         # + bar record
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from backend.agent.consumer_bar import (  # noqa: E402
    MAX_ECE,
    MIN_PRECISION,
    MIN_ROWS,
    derive_status,
    record_bars,
)

# REQ-18 AC18.1: reuse the project's ONE calibration implementation rather than
# writing a second one that could disagree with it.
from scripts.calibrate_decision_threshold import _ece_brier  # noqa: E402


def load_rows(
    db: str, backend_id: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Every labelled decision row, plus the skip counters.

    Skips are counted, never hidden: a row without a label cannot produce a
    precision number and must not be silently read as a success.

    ``backend_id`` scopes the sample to ONE engine when given (2026-09-27). A
    threshold belongs to the backend it was measured on (AC25.8), so a row
    measured on a DIFFERENT backend cannot speak for this one. Measured: 457 of
    522 tool_choice rows came from the retired LFM2-350M-Extract engine and held
    the reported precision at 0.442 while the active engine had 65 rows of its
    own. Rows from another backend are counted under ``other_backend`` - never
    dropped in silence. None keeps every row (the pre-existing behaviour).
    """
    rows: List[Dict[str, Any]] = []
    skipped = {"unreadable": 0, "no_confidence": 0, "no_label": 0,
               "other_backend": 0}
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        cur = c.execute(
            "SELECT outcome, interaction_payload FROM system_events "
            "WHERE event_type='tool_execution'"
        )
        for r in cur:
            try:
                payload = json.loads(r["interaction_payload"] or "{}")
            except Exception:
                skipped["unreadable"] += 1
                continue
            d = payload.get("decision")
            if not isinstance(d, dict):
                continue
            cid = d.get("consumer_id")
            conf = d.get("confidence")
            if cid is None or conf is None:
                skipped["no_confidence"] += 1
                continue
            # One engine's rows, when a backend was named (see load_rows).
            if backend_id and d.get("engine") and str(d["engine"]) != backend_id:
                skipped["other_backend"] += 1
                continue
            shadow = bool(d.get("shadow")) or str(d.get("route") or "") == "shadow"
            if shadow:
                # TWO reference shapes, because there are two kinds of consumer
                # (2026-09-27):
                #   - a BOOL consumer (sufficient, done, has_gaps, ...) records
                #     the Brain's answer as `brain_bool`;
                #   - a LABEL consumer (mode, review_verdict, web_intent, ...)
                #     records it as `brain_choice`, because its answer is a NAME.
                # Collapsing a name to a bool would manufacture agreement and
                # inflate precision, so a name is compared with a name. A row
                # carrying NEITHER reference still has no label and is counted
                # separately as skipped, never assumed correct.
                brain_bool = d.get("brain_bool")
                brain_choice = d.get("brain_choice")
                if brain_choice is not None:
                    correct = str(d.get("chosen")) == str(brain_choice)
                elif brain_bool is not None:
                    correct = bool(d.get("chosen")) == bool(brain_bool)
                else:
                    skipped["no_label"] += 1
                    continue
            else:
                # Identical to _load_decisions: a route-only row carries no
                # outcome, so it is not evidence of a wrong pick.
                outcome = None if payload.get("tool") == "no_tool" else r["outcome"]
                correct = outcome in ("success", "reason", None)
            rows.append({
                "consumer_id": str(cid),
                "engine": str(d.get("engine") or ""),
                "route": str(d.get("route") or ""),
                "shadow": shadow,
                "confidence": float(conf),
                "correct": bool(correct),
            })
    finally:
        c.close()
    return rows, skipped


def thresholds_by_consumer() -> Tuple[Dict[str, Optional[float]], Dict[str, Any]]:
    """The RESOLVED threshold per consumer for the ACTIVE backend.

    AC25.8: a threshold belongs to the backend it was measured on. A consumer
    with no entry for the active backend resolves to None and is fail-closed
    (never enforced) — the report shows that rather than guessing a number.
    """
    from backend.agent.decision_engine import load_engine_config

    cfg = load_engine_config()
    backend_id = ""
    identity_source = "unresolved"
    try:
        # A loaded engine knows its identity; this process usually has not
        # loaded it, so fall back to the DECLARED variant — constructing the
        # backend does not load its weights (`_load` is separate).
        from backend.agent.decision_engine import get_decision_engine

        loaded = str(getattr(get_decision_engine(), "model_id", "") or "")
        if loaded:
            backend_id, identity_source = loaded, "loaded engine"
        else:
            from backend.agent.decision_backend_onnx import GlinerOnnx, resolve_model_dir

            backend_id = GlinerOnnx(model_dir=resolve_model_dir(None)).backend_id
            identity_source = "declared ONNX variant"
    except Exception:  # noqa: BLE001 — identity is best-effort, never fatal
        pass
    # AC25.8: resolve the thresholds BY that identity.
    cfg.backend_id = backend_id or None
    consumers = (
        "tool_choice", "presentation", "narration", "recovery_strategy",
        "review_verdict", "sufficient", "done", "on_track",
        "mode", "web_intent", "retry_same",
        "has_gaps", "use_thinking", "escalate_incomplete", "needs_action",
    )
    out = {cid: cfg.threshold_for(cid) for cid in consumers}
    config = {
        "backend_id": backend_id,
        "backend_identity_source": identity_source,
        "candidate_cap": int(getattr(cfg, "candidate_cap", 0) or 0),
        "calibrated_cap": int(getattr(cfg, "calibrated_cap", 0) or 0),
    }
    return out, config


def measure(
    rows: List[Dict[str, Any]],
    thresholds: Dict[str, Optional[float]],
) -> Dict[str, Dict[str, Any]]:
    """Per-consumer rows/precision/ECE.

    Precision is at the THRESHOLD — TG-7's `P(correct | conf >= threshold)`.
    The full row count travels next to it as the evidence volume, so neither
    number hides the other.
    """
    by_consumer: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_consumer[r["consumer_id"]].append(r)

    measured: Dict[str, Dict[str, Any]] = {}
    for cid, grp in by_consumer.items():
        th = thresholds.get(cid)
        above = [r for r in grp if th is not None and r["confidence"] >= th]
        precision = (
            sum(1 for r in above if r["correct"]) / len(above) if above else 0.0
        )
        ece, brier = _ece_brier(grp)
        measured[cid] = {
            "rows": len(grp),
            "rows_above_threshold": len(above),
            "precision": round(precision, 4),
            "ece": ece,
            "brier": brier,
            "threshold": th,
            "shadow_rows": sum(1 for r in grp if r["shadow"]),
            "engines": sorted({r["engine"] for r in grp if r["engine"]}),
        }
    return measured


def bar_rows(measured: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The `{rows, precision, ece}` shape `consumer_bar.record_bars` reads.

    A consumer whose ACTIVE backend has no threshold entry carries no ECE into
    the record, so `derive_status` cannot flip it — fail-closed is preserved in
    the persisted artifact, not only in this report (AC25.8).
    """
    return {
        cid: {
            "rows": m["rows"],
            "precision": m["precision"],
            "ece": None if m["threshold"] is None else m["ece"],
        }
        for cid, m in measured.items()
    }


def build_report(
    measured: Dict[str, Dict[str, Any]],
    skipped: Dict[str, int],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Per-consumer status against TG-7's bar, with the gap named."""
    consumers = {}
    for cid, m in sorted(measured.items()):
        if m["threshold"] is None:
            status = "shadow"
            gap = "no threshold for the active backend (fail-closed)"
        else:
            status, gap = derive_status(m["rows"], m["precision"], m["ece"])
        consumers[cid] = {**m, "status": status, "gap": gap}
    return {
        "config": config,
        "bar": {
            "min_rows": MIN_ROWS,
            "min_precision": MIN_PRECISION,
            "max_ece": MAX_ECE,
        },
        "skipped": skipped,
        "n_consumers": len(consumers),
        "flipped": sorted(c for c, v in consumers.items() if v["status"] == "enforced"),
        "consumers": consumers,
    }


def _print_report(rep: Dict[str, Any]) -> None:
    print(f"deployed config: backend={rep['config']['backend_id']} "
          f"cap={rep['config']['candidate_cap']}")
    print(f"bar: rows >= {rep['bar']['min_rows']}, "
          f"precision >= {rep['bar']['min_precision']}, "
          f"ECE <= {rep['bar']['max_ece']}")
    print("label: a DISPATCHED row judges on the event outcome; a SHADOW row "
          "judges on engine-vs-Brain agreement (parity)")
    sk = rep["skipped"]
    print(f"skipped rows: no_label={sk.get('no_label', 0)} "
          f"no_confidence={sk.get('no_confidence', 0)} "
          f"unreadable={sk.get('unreadable', 0)} "
          f"other_backend={sk.get('other_backend', 0)} "
          f"(measured on a different engine; this report scores the active one)")
    print(f"consumers measured: {rep['n_consumers']}")
    for cid, m in rep["consumers"].items():
        print(f"\n[{cid}] rows={m['rows']} above_threshold={m['rows_above_threshold']} "
              f"shadow_rows={m['shadow_rows']}")
        print(f"  threshold={m['threshold']} precision={m['precision']} "
              f"ece={m['ece']} brier={m['brier']}")
        print(f"  engines={m['engines']}")
        print(f"  status={m['status']}"
              + (f"  gap: {m['gap']}" if m["gap"] else "  (flip allowed)"))
    print("\nFLIPPED: " + (", ".join(rep["flipped"]) or "(none)"))
    shy = [f"{c} ({v['gap']})" for c, v in rep["consumers"].items()
           if v["status"] != "enforced"]
    print("SHADOW : " + ("; ".join(shy) or "(none)"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-consumer enforcement report (TG-7).")
    ap.add_argument("--db", default=str(_REPO / "data" / "memory.db"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true",
                    help="persist the bar record (benchmarks/consumer_bar_record.json)")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.is_file():
        print(f"UNVERIFIED: db not found: {db}")
        return 4
    thresholds, config = thresholds_by_consumer()
    try:
        # Scoped to the ACTIVE backend: rows from a retired engine cannot speak
        # for the model actually deployed (AC25.8).
        rows, skipped = load_rows(str(db), config.get("backend_id"))
    except sqlite3.Error as e:
        print(f"UNVERIFIED: cannot read ledger ({e})")
        return 4

    measured = measure(rows, thresholds)
    rep = build_report(measured, skipped, config)

    if args.write:
        record_bars(bar_rows(measured), config=config)
        rep["written"] = True

    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        _print_report(rep)
        if args.write:
            print("\nbar record written: benchmarks/consumer_bar_record.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
