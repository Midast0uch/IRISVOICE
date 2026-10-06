#!/usr/bin/env python3
"""Per-consumer enforcement report — the T22/T52 instrument (REQ-31, TG-7).

WHAT IT DOES
    Reads the decision rows the engine already writes into `data/memory.db`
    (`system_events.event_type='tool_execution'`, the `decision` block), groups
    them BY CONSUMER, and reports for each one:

        rows (raw and distinct), rows above threshold, precision, ECE, Brier,
        and the HONEST out-of-fold numbers (AUROC, calibrated ECE, calibrated
        threshold, rows above it)

    then derives the enforcement status against the hardened bar
    (`consumer_bar.derive_status`, Oracle Stage A 2026-10-05) and, with
    `--write`, persists the result to `benchmarks/consumer_bar_record.json` via
    `backend.agent.consumer_bar.record_bars`.

    The honest numbers come from `scripts/fit_oracle_calibration.fit_consumer`
    on the DISTINCT rows: a repeated input counts once (web_intent had 654
    distinct of 2690 rows) and a yes/no consumer's confidence is its confidence
    in the CHOSEN answer, not P(true) (which inverted the AUROC of every "no").

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
from typing import Any, Dict, List, Optional, Sequence, Tuple

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from backend.agent.consumer_bar import (  # noqa: E402
    MAX_ECE,
    MIN_AUROC,
    MIN_MINORITY,
    MIN_PRECISION,
    MIN_ROWS,
    MIN_ROWS_ABOVE,
    MIN_WILSON_LB,
    derive_status,
    record_bars,
)
from backend.agent.oracle_calibration import binary_consumers  # noqa: E402

# REQ-18 AC18.1: reuse the project's ONE calibration implementation rather than
# writing a second one that could disagree with it.
from scripts.calibrate_decision_threshold import (  # noqa: E402
    _auroc,
    _ece_brier,
    decision_label,
)
from scripts.fit_oracle_calibration import fit_consumer  # noqa: E402


def load_rows(
    db: str, backend_id: Optional[str] = None,
    *, binary: Optional[frozenset] = None, dedupe: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Every labelled DISTINCT decision row, plus the skip counters.

    Two corrections to what the ledger holds (Oracle Stage A, 2026-10-05):

    * CONFIDENCE IS IN THE CHOSEN ANSWER. A yes/no consumer (``binary`` = the
      consumers whose engine spec is a ("yes", "no") Noul; read from the specs
      when not given) used to write P(true) as its confidence, so a "no" with
      0.1 was a SURE no and every rank metric came out inverted (web_intent
      AUROC 0.218, escalate_incomplete 0.003). Old rows carry P(true) in
      ``confidence`` whatever they chose, so P(true) = confidence and the
      confidence becomes max(p, 1-p); a new row carries ``probability`` and the
      same rule applies (idempotent on a row already normalised).
    * ONE ROW PER INPUT. The same input is rescored many times (web_intent: 654
      distinct of 2690 rows; presentation: 2 of 918) and a repeat is not new
      evidence for precision, ECE or the bar. Rows with the same (consumer,
      engine, confidence, chosen, reference, label) collapse into one that
      carries ``repeats``; the ledger holds no turn or goal key to use instead.
      Counted under ``skipped["duplicates"]``. ``dedupe=False`` keeps them all.

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
               "other_backend": 0, "duplicates": 0}
    if binary is None:
        binary = binary_consumers()
    seen: Dict[tuple, Dict[str, Any]] = {}
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
            # THE label (calibrate_decision_threshold.decision_label): shadow
            # rows by parity with the Brain (name vs name, bool vs bool),
            # dispatched rows by outcome. One rule, so the two instruments
            # cannot disagree again (they did: web_intent 1.0 vs 0.377).
            correct = decision_label(r["outcome"], payload, d)
            if correct is None:
                skipped["no_label"] += 1
                continue
            conf = float(conf)
            prob = None
            if str(cid) in binary:
                prob = (float(d["probability"]) if d.get("probability") is not None
                        else conf)
                conf = max(prob, 1.0 - prob)
            ref = d.get("brain_choice")
            if ref is None:
                ref = d.get("brain_bool")
            engine = str(d.get("engine") or "")
            key = (str(cid), engine, round(conf, 4), str(d.get("chosen")),
                   str(ref), bool(correct))
            if dedupe and key in seen:
                seen[key]["repeats"] += 1
                skipped["duplicates"] += 1
                continue
            row = {
                "consumer_id": str(cid),
                "engine": engine,
                "route": str(d.get("route") or ""),
                "shadow": shadow,
                "confidence": conf,
                "probability": prob,
                "chosen": d.get("chosen"),
                "reference": ref,
                "correct": bool(correct),
                "repeats": 1,
            }
            seen[key] = row
            rows.append(row)
    finally:
        c.close()
    return rows, skipped


def thresholds_by_consumer(
    extra: Sequence[str] = (),
) -> Tuple[Dict[str, Optional[float]], Dict[str, Any]]:
    """The RESOLVED threshold per consumer for the ACTIVE backend.

    AC25.8: a threshold belongs to the backend it was measured on. A consumer
    with no entry for the active backend resolves to None and is fail-closed
    (never enforced) — the report shows that rather than guessing a number.

    Looked up for EVERY consumer in ``decision_engine.CONSUMERS`` (a hard-coded
    list of 15 omitted ``depth_met``, so it showed "no threshold") plus
    ``extra``: consumers that registered themselves and appear only in the ledger.
    """
    from backend.agent.decision_engine import CONSUMERS, load_engine_config

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
    out = {cid: cfg.threshold_for(cid) for cid in (*CONSUMERS, *extra)}
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
    # A consumer with a threshold lookup but no rows still gets a line: zero
    # evidence is a result, and a missing line reads as "not checked".
    for cid in thresholds:
        by_consumer.setdefault(cid, [])

    measured: Dict[str, Dict[str, Any]] = {}
    for cid, grp in by_consumer.items():
        th = thresholds.get(cid)
        above = [r for r in grp if th is not None and r["confidence"] >= th]
        precision = (
            sum(1 for r in above if r["correct"]) / len(above) if above else 0.0
        )
        ece, brier = _ece_brier(grp)
        measured[cid] = {
            # DISTINCT rows: `rows_raw` is what the ledger holds, and the gap
            # between them is how often the same input was rescored.
            "rows": len(grp),
            "rows_raw": sum(int(r.get("repeats", 1)) for r in grp),
            # The out-of-fold numbers the hardened bar reads (fit_consumer).
            "honest": fit_consumer(grp),
            "rows_above_threshold": len(above),
            "precision": round(precision, 4),
            "ece": ece,
            "brier": brier,
            # oracle-addendum 25.4: does CONFIDENCE RANK errors? Precision and
            # ECE describe the operating point; AUROC describes whether the
            # confidence signal is usable at all - which is what the JEV cascade
            # depends on, since it accepts/escalates ON confidence. This is the
            # RAW (in-sample) AUROC; the bar gates on the out-of-fold one in
            # `honest` (owner-approved 2026-10-05, Oracle Stage A).
            "auroc": _auroc(grp),
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
            # The hardened bar travels into the record too, so `--write` cannot
            # persist a flip the report would refuse. No backend threshold = no
            # honest block: the legacy clauses then fail on the missing ECE.
            "honest": None if m["threshold"] is None else m.get("honest"),
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
            status, gap = derive_status(
                m["rows"], m["precision"], m["ece"], honest=m.get("honest"),
            )
        consumers[cid] = {**m, "status": status, "gap": gap}
    return {
        "config": config,
        "bar": {
            "min_rows": MIN_ROWS,
            "min_precision": MIN_PRECISION,
            "max_ece": MAX_ECE,
            "min_minority": MIN_MINORITY,
            "min_auroc": MIN_AUROC,
            "min_rows_above": MIN_ROWS_ABOVE,
            "min_wilson_lb": MIN_WILSON_LB,
        },
        "skipped": skipped,
        "n_consumers": len(consumers),
        "flipped": sorted(c for c, v in consumers.items() if v["status"] == "enforced"),
        "consumers": consumers,
    }


def _print_report(rep: Dict[str, Any]) -> None:
    b = rep["bar"]
    print(f"deployed config: backend={rep['config']['backend_id']} "
          f"cap={rep['config']['candidate_cap']}")
    print(f"HARDENED BAR (all required): distinct rows >= {b['min_rows']}; "
          f"reference has 2 classes, minority >= {b['min_minority']:.0%}; "
          f"out-of-fold AUROC >= {b['min_auroc']}; a calibrated threshold with "
          f"precision >= {b['min_precision']} (Wilson LB >= {b['min_wilson_lb']}) "
          f"on >= {b['min_rows_above']} distinct rows; "
          f"out-of-fold calibrated ECE <= {b['max_ece']}")
    print("label: a DISPATCHED row judges on the event outcome; a SHADOW row "
          "judges on engine-vs-Brain agreement (parity)")
    print("rows: DISTINCT inputs (a repeat counts once); a yes/no consumer's "
          "confidence is its confidence in the CHOSEN answer")
    sk = rep["skipped"]
    print(f"skipped rows: no_label={sk.get('no_label', 0)} "
          f"no_confidence={sk.get('no_confidence', 0)} "
          f"unreadable={sk.get('unreadable', 0)} "
          f"other_backend={sk.get('other_backend', 0)} "
          f"(measured on a different engine; this report scores the active one) "
          f"duplicates={sk.get('duplicates', 0)} (repeats collapsed into distinct rows)")
    print(f"consumers: {rep['n_consumers']} (every CONSUMERS entry plus any "
          f"consumer seen in the ledger)")
    for cid, m in rep["consumers"].items():
        h = m.get("honest") or {}
        o = h.get("oof") or {}
        print(f"\n[{cid}] distinct={m['rows']} raw={m.get('rows_raw', m['rows'])} "
              f"classes={h.get('classes')} shadow_rows={m['shadow_rows']}")
        print(f"  raw (in-sample, legacy threshold {m['threshold']}): "
              f"above={m['rows_above_threshold']} precision={m['precision']} "
              f"ece={m['ece']} brier={m['brier']} auroc={m.get('auroc')}")
        print(f"  honest (5-fold out-of-fold): auroc={o.get('auroc')} "
              f"ece={o.get('ece')} brier={o.get('brier')} "
              f"calibrated_threshold={h.get('threshold')} "
              f"above={h.get('rows_above')} precision@t={o.get('precision_at_t')} "
              f"wilson_lb={o.get('wilson_lb')}")
        print(f"  engines={m['engines']}")
        print(f"  status={m['status']}"
              + (f"  gap: {m['gap']}" if m["gap"] else "  (flip allowed)"))
    print("\nWOULD EARN THE BAR: " + (", ".join(rep["flipped"]) or "(none)")
          + "   (nothing is switched on: no bar record is written without --write)")
    shy = [f"{c} ({v['gap']})" for c, v in rep["consumers"].items()
           if v["status"] != "enforced"]
    print("SHADOW : " + ("; ".join(shy) or "(none)"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-consumer enforcement report (TG-7).")
    from _app_store import app_store_path  # the configured store, not a stale copy

    ap.add_argument("--db", default=app_store_path())
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true",
                    help="persist the bar record (benchmarks/consumer_bar_record.json)")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.is_file():
        print(f"UNVERIFIED: db not found: {db}")
        return 4
    _, config = thresholds_by_consumer()
    try:
        # Scoped to the ACTIVE backend: rows from a retired engine cannot speak
        # for the model actually deployed (AC25.8).
        rows, skipped = load_rows(str(db), config.get("backend_id"))
    except sqlite3.Error as e:
        print(f"UNVERIFIED: cannot read ledger ({e})")
        return 4
    # A threshold lookup for every CONSUMERS entry and every consumer in the ledger.
    thresholds, config = thresholds_by_consumer(sorted({r["consumer_id"] for r in rows}))

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
