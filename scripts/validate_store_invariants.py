#!/usr/bin/env python3
"""Store invariant suite — does the application store contradict itself?

specs/der-ground-truth/ REQ-6 (T11) + its anti-vacuity self-test (T12).

    python scripts/validate_store_invariants.py
    python scripts/validate_store_invariants.py --db data/memory.db
    python scripts/validate_store_invariants.py --self-test

READ-ONLY. Headless. No application, no dev server, no developer-mode session
(Decisions Locked 2). Exit 0 only when every invariant PASSES.

THE RULE THAT MATTERS: PASS / FAIL / **DEAD**
---------------------------------------------
An invariant whose input cannot be computed reports DEAD, not PASS, and DEAD
exits non-zero. This is the single most important line in the file.

An assertion over an empty table is vacuously true. That is precisely how five
memory substrates sat empty and unnoticed — `der_fan_traces`, `mycelium_edges`,
`semantic_entries`, `mycelium_pins`, and the recall episode channel all held 0
rows while every check over them passed. `backend/agent/outer_loop.py:27-37`
records the same lesson from the other direction: a three-metric gate accepted on
one metric for months because a dead guard read as no objection.

`--self-test` (T12) runs every invariant against an EMPTY database and asserts
that NONE of them report PASS. It is the test that would have caught the whole
condition this spec exists to fix.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Callable, List, Optional

PASS, FAIL, DEAD = "PASS", "FAIL", "DEAD"


@dataclass
class Result:
    name: str
    status: str
    offending: int = 0
    example: str = ""
    detail: str = ""


@dataclass
class Invariant:
    name: str
    describe: str
    check: Callable[[sqlite3.Connection], Result] = field(repr=False)


# ── helpers ────────────────────────────────────────────────────────────────

def _tables(conn: sqlite3.Connection) -> set:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _count(conn: sqlite3.Connection, table: str, where: str = "") -> Optional[int]:
    """Row count, or None when the table is absent — None means DEAD, not zero."""
    try:
        if table not in _tables(conn):
            return None
        sql = f"SELECT COUNT(*) FROM '{table}'" + (f" WHERE {where}" if where else "")
        return int(conn.execute(sql).fetchone()[0])
    except sqlite3.Error:
        return None


def _dead(name: str, why: str) -> Result:
    return Result(name, DEAD, detail=why)


# ── invariants ─────────────────────────────────────────────────────────────

def inv_fan_traces_exist(conn: sqlite3.Connection) -> Result:
    """REQ-1: every executed DER step leaves an execution trace."""
    n = _count(conn, "der_fan_traces")
    if n is None:
        return _dead("every_step_has_fan_trace", "der_fan_traces table absent")
    commits = _count(conn, "der_commits") or 0
    if n == 0 and commits == 0:
        return _dead("every_step_has_fan_trace", "no traces AND no commits - nothing to compare")
    if n == 0:
        return Result("every_step_has_fan_trace", FAIL, offending=commits,
                      detail=f"{commits} commits recorded but ZERO fan traces - "
                             "the execution history is not being written (T4)")
    return Result("every_step_has_fan_trace", PASS, detail=f"{n} traces / {commits} commits")


def inv_failure_reconciliation(conn: sqlite3.Connection) -> Result:
    """REQ-2/REQ-11: the physics layer sees the failures the episode layer saw."""
    ep = _count(conn, "episodes", "outcome_type='failure'")
    tr = _count(conn, "caducean_trajectories", "outcome='failure'")
    if ep is None or tr is None:
        return _dead("failure_reconciliation", "episodes or caducean_trajectories absent")
    ep_all = _count(conn, "episodes") or 0
    tr_all = _count(conn, "caducean_trajectories") or 0
    if ep_all == 0 or tr_all == 0:
        return _dead("failure_reconciliation", "one of the layers is empty - nothing to reconcile")
    ep_rate = ep / ep_all
    tr_rate = tr / tr_all
    # An order-of-magnitude gap is not a rounding difference; it means failures
    # are being lost between the layers.
    if ep_rate > 0 and tr_rate < ep_rate / 5:
        return Result("failure_reconciliation", FAIL, offending=ep - tr,
                      detail=f"episode failure rate {ep_rate:.1%} ({ep}/{ep_all}) vs "
                             f"physics {tr_rate:.1%} ({tr}/{tr_all}) - failures are "
                             "lost before the layer every learner reads (T5)")
    return Result("failure_reconciliation", PASS,
                  detail=f"episode {ep_rate:.1%} vs physics {tr_rate:.1%}")


def inv_commits_labelled(conn: sqlite3.Connection) -> Result:
    """REQ-2 AC2: every commit carries its verified label."""
    n = _count(conn, "der_commits")
    if n is None:
        return _dead("commits_carry_verified_label", "der_commits absent")
    if n == 0:
        return _dead("commits_carry_verified_label", "no commits recorded")
    bad = _count(conn, "der_commits", "verified_label IS NULL OR verified_label=''") or 0
    if bad:
        return Result("commits_carry_verified_label", FAIL, offending=bad)
    return Result("commits_carry_verified_label", PASS, detail=f"{n} commits all labelled")


def inv_footprints_exist(conn: sqlite3.Connection) -> Result:
    """REQ-3: a terminal card leaves a retrievable footprint."""
    n = _count(conn, "semantic_entries")
    if n is None:
        return _dead("terminal_card_has_footprint", "semantic_entries absent")
    if n == 0:
        return _dead("terminal_card_has_footprint",
                     "semantic_entries is EMPTY - the store nothing has ever written to")
    fp = _count(conn, "semantic_entries", "category='card_footprints'") or 0
    if fp == 0:
        return Result("terminal_card_has_footprint", FAIL, offending=n,
                      detail="semantic store has rows but ZERO card footprints (T6)")
    return Result("terminal_card_has_footprint", PASS, detail=f"{fp} footprints")


def inv_pin_links_resolve(conn: sqlite3.Connection) -> Result:
    """REQ-4 AC3: a link that names a pin must find that pin.

    CORRECTION (2026-08-23): an earlier reading of this spec's audit called all
    354 `mycelium_pin_links` rows "orphaned pin links". That was wrong - inferred
    from the table's NAME without checking its shape. The table is polymorphic
    (`source_type`/`source_id`/`target_type`/`target_id`) and every one of those
    354 rows is `node -> node`. There are ZERO pin references in it, so there is
    no orphan problem. The real REQ-4 finding is unaffected: `PinStore` writes
    `mycelium_pins` (0 rows) while `pins` (4 rows, superset schema) is live.
    """
    t = _tables(conn)
    if "mycelium_pin_links" not in t:
        return _dead("pin_links_reference_existing_pins", "mycelium_pin_links absent")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(mycelium_pin_links)")}
    if not {"source_type", "source_id", "target_type", "target_id"} <= cols:
        return _dead("pin_links_reference_existing_pins",
                     "link table is not the expected polymorphic shape")
    # Which pin table is authoritative is REQ-4's determination; check against
    # whichever ones exist so this invariant survives that decision either way.
    pin_tables = [x for x in ("pins", "mycelium_pins") if x in t]
    if not pin_tables:
        return _dead("pin_links_reference_existing_pins", "no pin table present")
    try:
        pin_refs = int(conn.execute(
            "SELECT COUNT(*) FROM mycelium_pin_links "
            "WHERE source_type='pin' OR target_type='pin'"
        ).fetchone()[0])
        if pin_refs == 0:
            return _dead("pin_links_reference_existing_pins",
                         "no link references a pin - nothing to resolve "
                         "(all rows are node->node)")
        clauses = []
        for pt in pin_tables:
            clauses.append(
                f"(source_type='pin' AND NOT EXISTS "
                f"(SELECT 1 FROM '{pt}' p WHERE p.pin_id = source_id))")
        orphan = int(conn.execute(
            "SELECT COUNT(*) FROM mycelium_pin_links WHERE "
            + " AND ".join(clauses)
        ).fetchone()[0])
    except sqlite3.Error as exc:
        return _dead("pin_links_reference_existing_pins", f"query failed: {exc}")
    if orphan:
        return Result("pin_links_reference_existing_pins", FAIL, offending=orphan,
                      detail=f"{orphan}/{pin_refs} pin references resolve to no pin "
                             "in any pin table (T3/T7)")
    return Result("pin_links_reference_existing_pins", PASS,
                  detail=f"{pin_refs} pin references all resolve")


def inv_termination_cause(conn: sqlite3.Connection) -> Result:
    """REQ-9: every completed run records WHY it stopped."""
    n = _count(conn, "caducean_session_exits")
    if n is None:
        return _dead("run_records_termination_cause", "caducean_session_exits absent")
    if n == 0:
        return _dead("run_records_termination_cause", "no session exits recorded")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(caducean_session_exits)")}
    if "termination_cause" not in cols:
        return _dead("run_records_termination_cause",
                     "no termination_cause column - the cause vocabulary is not recorded (T19)")
    bad = _count(conn, "caducean_session_exits",
                 "termination_cause IS NULL OR termination_cause=''") or 0
    if bad:
        return Result("run_records_termination_cause", FAIL, offending=bad)
    return Result("run_records_termination_cause", PASS, detail=f"{n} exits all attributed")


def inv_coupling_substrate(conn: sqlite3.Connection) -> Result:
    """REQ-5: the coordinate edge store the wormhole spec plans to extend."""
    n = _count(conn, "mycelium_edges")
    if n is None:
        return _dead("coupling_substrate_written", "mycelium_edges absent")
    nodes = _count(conn, "mycelium_nodes") or 0
    if nodes == 0:
        return _dead("coupling_substrate_written", "no nodes - nothing could have an edge")
    if n == 0:
        return Result("coupling_substrate_written", FAIL, offending=nodes,
                      detail=f"{nodes} nodes and ZERO edges - the posterior substrate "
                             "specs/wormhole-aperture builds on has never been "
                             "written (T1/T8)")
    return Result("coupling_substrate_written", PASS, detail=f"{n} edges / {nodes} nodes")


def inv_exits_attributable(conn: sqlite3.Connection) -> Result:
    """REQ-9: a session exit must belong to a session that actually ran.

    FOUND 2026-08-23 by the corpus replay (T17), not by the original audit: the
    exit ledger holds 431 rows spanning just TWO session ids (`default`,
    `session_iris`) while `episodes` spans 47, overlapping on ONE. So exits are
    being recorded under a placeholder identity and cannot be joined to the runs
    they describe.

    This matters beyond tidiness. The outer loop's held-out metric is
    `natural_exit_rate` computed over this ledger; if the rows do not correspond
    to real sessions, that metric measures a placeholder. It is the same disease
    as the rest of this spec - a record that exists and does not represent
    reality - in a third place.
    """
    t = _tables(conn)
    if "caducean_session_exits" not in t or "episodes" not in t:
        return _dead("exits_attributable_to_runs", "exit or episode table absent")
    ex = _count(conn, "caducean_session_exits") or 0
    if ex == 0:
        return _dead("exits_attributable_to_runs", "no exits recorded")
    try:
        ex_sessions = int(conn.execute(
            "SELECT COUNT(DISTINCT session_id) FROM caducean_session_exits").fetchone()[0])
        ep_sessions = int(conn.execute(
            "SELECT COUNT(DISTINCT session_id) FROM episodes").fetchone()[0])
        overlap = int(conn.execute(
            "SELECT COUNT(DISTINCT e.session_id) FROM episodes e "
            "JOIN caducean_session_exits x ON x.session_id = e.session_id").fetchone()[0])
    except sqlite3.Error as exc:
        return _dead("exits_attributable_to_runs", f"query failed: {exc}")
    if ep_sessions == 0:
        return _dead("exits_attributable_to_runs", "no episode sessions to attribute to")
    if overlap < max(1, ep_sessions // 10):
        return Result("exits_attributable_to_runs", FAIL, offending=ex,
                      detail=f"{ex} exits over {ex_sessions} session id(s) vs "
                             f"{ep_sessions} episode sessions - overlap {overlap}. "
                             "Exits are recorded under an identity the rest of the "
                             "store does not use, so they join to nothing")
    return Result("exits_attributable_to_runs", PASS,
                  detail=f"{overlap}/{ep_sessions} episode sessions have an exit")


INVARIANTS: List[Invariant] = [
    Invariant("exits_attributable_to_runs", "REQ-9 exits join to real runs", inv_exits_attributable),
    Invariant("every_step_has_fan_trace", "REQ-1 execution history exists", inv_fan_traces_exist),
    Invariant("failure_reconciliation", "REQ-2/11 failures reach the physics layer", inv_failure_reconciliation),
    Invariant("commits_carry_verified_label", "REQ-2 AC2 every commit labelled", inv_commits_labelled),
    Invariant("terminal_card_has_footprint", "REQ-3 footprints persist", inv_footprints_exist),
    Invariant("pin_links_reference_existing_pins", "REQ-4 one pin store", inv_pin_links_resolve),
    Invariant("run_records_termination_cause", "REQ-9 why did it stop", inv_termination_cause),
    Invariant("coupling_substrate_written", "REQ-5 edge store written", inv_coupling_substrate),
]


def run(db_path: str) -> List[Result]:
    results: List[Result] = []
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        return [_dead(i.name, f"cannot open store: {exc}") for i in INVARIANTS]
    try:
        for inv in INVARIANTS:
            try:
                results.append(inv.check(conn))
            except Exception as exc:  # an invariant must never crash the suite
                results.append(_dead(inv.name, f"check raised: {exc}"))
    finally:
        conn.close()
    return results


def report(results: List[Result]) -> str:
    w = max(len(r.name) for r in results) + 2
    lines = [f"{'INVARIANT'.ljust(w)}{'RESULT':<8}{'OFFENDING':<11}DETAIL",
             "-" * (w + 60)]
    for r in results:
        off = str(r.offending) if r.offending else ("-" if r.status != FAIL else "0")
        lines.append(f"{r.name.ljust(w)}{r.status:<8}{off:<11}{r.detail}")
    p = sum(1 for r in results if r.status == PASS)
    f = sum(1 for r in results if r.status == FAIL)
    d = sum(1 for r in results if r.status == DEAD)
    lines.append("-" * (w + 60))
    lines.append(f"{p} PASS - {f} FAIL - {d} DEAD"
                 + ("" if f + d == 0 else "   (DEAD is NOT pass: an uncomputable"
                                          " invariant proves nothing)"))
    return "\n".join(lines)


def terminations(db_path: str, limit: int = 100) -> int:
    """T20 (REQ-9 AC4): what stopped my last N runs, in one query.

    This number is the point of REQ-9. Today it cannot be computed at all, which
    is why every loop pathology needs a live reproduction to diagnose. A healthy
    distribution is dominated by `natural` and `sufficiency`; a tail of
    `cycle_cap` / `token_budget` / `turn_wallclock` says the loop is running OUT
    rather than finishing, and names which bound to look at first.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        print(f"cannot open store: {exc}")
        return 1
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(caducean_session_exits)")}
        if "termination_cause" not in cols:
            print("termination_cause column absent - no run has recorded WHY it "
                  "stopped yet (T19 ships the column; runs must then accumulate).")
            return 1
        rows = list(conn.execute(
            "SELECT COALESCE(termination_cause,'(unrecorded)') AS c, COUNT(*) n, "
            "       AVG(bound_measured), AVG(bound_configured) "
            "FROM (SELECT * FROM caducean_session_exits ORDER BY ts DESC LIMIT ?) "
            "GROUP BY c ORDER BY n DESC", (limit,)))
        total = sum(r[1] for r in rows) or 1
        print(f"TERMINATION DISTRIBUTION - last {limit} runs ({total} recorded)")
        print()
        print(f"{'CAUSE':<22}{'N':>5}{'SHARE':>9}   MEASURED/CONFIGURED")
        print("-" * 62)
        for cause, n, meas, conf in rows:
            hb = f"{meas:.0f}/{conf:.0f}" if meas is not None and conf else "-"
            print(f"{cause:<22}{n:>5}{n / total:>8.0%}   {hb}")
        return 0
    finally:
        conn.close()


def self_test() -> int:
    """T12 / GT-G3: no invariant may report PASS against an EMPTY database.

    This is the anti-vacuity guard. An assertion that passes over an empty table
    reads as coverage where there is none, which is exactly how the condition
    this spec fixes went unnoticed for months.
    """
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        sqlite3.connect(tmp).close()  # a real, completely empty database
        results = run(tmp)
        passed = [r.name for r in results if r.status == PASS]
        print(report(results))
        print()
        if passed:
            print("SELF-TEST FAILED - these reported PASS over an EMPTY store, "
                  "which is vacuous:")
            for n in passed:
                print(f"  - {n}")
            return 1
        print(f"SELF-TEST OK - all {len(results)} invariants correctly refuse to "
              "pass on an empty store.")
        return 0
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.path.join("data", "memory.db"))
    ap.add_argument("--self-test", action="store_true",
                    help="T12: assert no invariant passes on an empty store")
    ap.add_argument("--terminations", action="store_true",
                    help="T20: what stopped the last N runs")
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if args.terminations:
        return terminations(args.db, args.limit)

    if not os.path.exists(args.db):
        print(f"store not found: {args.db}")
        return 1
    results = run(args.db)
    print(f"STORE {args.db}\n")
    print(report(results))
    bad = [r for r in results if r.status in (FAIL, DEAD)]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
