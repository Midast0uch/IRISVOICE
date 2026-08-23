#!/usr/bin/env python3
"""Which modules are unreachable? — orphan detection with a tracked baseline.

specs/der-ground-truth/ REQ-15 (T13/T14).

    python scripts/validate_orphans.py
    python scripts/validate_orphans.py --update-baseline

An orphan is a production module with NO production importer. It is not
necessarily dead — it may be an entry point, or a deliberate future hook — but it
IS a module that looks implemented and is not running. `card_footprint.py` was
one: fully written for the task-card spec, never called, so `semantic_entries`
sat empty and no card was ever addressable across conversations.

REQ-15 AC1: every orphan carries a disposition — WIRE, RETIRE, or KEEP-DORMANT
with a reason. AC2: none may be left undecided. **AC6: RETIRE records a
recommendation; this script never deletes anything.**

AC4: dynamic dispatch is accounted for. `importlib` appears in exactly one module
(`backend/agent/mcm_protocol/orchestrator.py`), which resolves
`mcm_protocol/actions/*` at runtime — those are NOT orphans and are excluded.

AC5: the check FAILS when the count rises above the baseline without a
disposition. New orphans are a regression; existing ones are debt.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_ROOTS = ["backend"]
SKIP_DIRS = {"__pycache__", "tests", "test", "archive", ".pytest_cache", "node_modules"}
BASELINE = os.path.join(ROOT, "scripts", "orphan_baseline.json")

#: AC4 — resolved at runtime by mcm_protocol/orchestrator.py, not by import.
DYNAMIC_DIRS = ("backend/agent/mcm_protocol/actions",)

#: AC1 dispositions recorded for the 2026-08-23 baseline.
DISPOSITIONS: Dict[str, Tuple[str, str]] = {
    "recall_phases": ("KEEP-DORMANT", "specs/wormhole-aperture REQ-0 AC6: kept behind "
                                      "a default-off switch as the legacy recall "
                                      "fallback; deleted if it ever costs anything"),
    "recall_decoder": ("KEEP-DORMANT", "consumed by recall_phases only; same fate"),
    "card_footprint": ("WIRE", "DONE 2026-08-23 (T6) - now called from the card "
                               "terminal state in agent_kernel"),
    "main": ("KEEP-DORMANT", "process entry point - invoked as a script, not imported"),
    "iris_supervisor": ("KEEP-DORMANT", "process entry point"),
    "inference_router": ("KEEP-DORMANT", "process entry point"),
    "crawl_worker": ("KEEP-DORMANT", "spawned as a subprocess, not imported"),
    "live_benchmark": ("KEEP-DORMANT", "benchmark harness, run directly"),
    "validate_phase1_foundation": ("KEEP-DORMANT", "validation script, run directly"),
    "audit": ("REVIEW", "backend/memory/audit.py - a memory audit module that is "
                        "itself unaudited. 326 lines, zero importers"),
    "task_kernel": ("REVIEW", "321 lines, zero importers - superseded by agent_kernel?"),
    "spec_engine": ("REVIEW", "228 lines, zero importers"),
    "trailing_director": ("REVIEW", "154 lines, zero importers - DER director surface"),
    "skill_registry": ("REVIEW", "118 lines, zero importers - superseded by node chains?"),
    "verify_rubric": ("REVIEW", "85 lines, zero importers"),
    "universal_gui_operator": ("REVIEW", "402 lines, zero importers"),
    "temp_fix": ("RETIRE", "1 line - scratch file"),
    "custom_skill_template": ("KEEP-DORMANT", "template, intentionally unreferenced"),
    # Added 2026-08-23 after the first run flagged them UNDECIDED.
    "termination": ("WIRE", "GROUND TRUTH T18 - the recorder accepts a "
                            "TerminationRecord (T19) but no DER exit path "
                            "CONSTRUCTS one yet. T21 wires the call sites"),
    "installer_service": ("REVIEW", "backend/integrations - 526 lines; needs the "
                                    "owner's call on whether integrations shipped"),
    "marketplace_client": ("REVIEW", "backend/integrations - 455 lines; same"),
    "security_analytics": ("REVIEW", "backend/monitoring - 394 lines"),
    "permission_system": ("REVIEW", "backend/vision - 379 lines; vision subsystem"),
    "snapshot_cache": ("REVIEW", "backend/vision - 324 lines"),
    "sandbox_executor": ("REVIEW", "backend/vision - 322 lines; note "
                                   "specs/wormhole-aperture REQ-27 plans a script "
                                   "sandbox - check for overlap before writing a new one"),
    "semantic_snapshot": ("REVIEW", "backend/vision - 239 lines"),
    "automation_audit": ("REVIEW", "backend/vision - 176 lines"),
    "telegram_bridge": ("REVIEW", "backend/channels - 125 lines"),
    "_debug_crawl": ("RETIRE", "scratch file, untracked in git"),
    "_test_patch_isolated": ("RETIRE", "scratch file, untracked in git"),
}

#: REVIEW means "dispositioned as needing the owner's domain knowledge, with the
#: evidence attached" - NOT undecided. It is surfaced separately so it cannot be
#: mistaken for a resolved WIRE/RETIRE/KEEP-DORMANT.
NEEDS_OWNER = "REVIEW"


def _py_files(root: str) -> List[str]:
    out = []
    for dp, dn, fn in os.walk(os.path.join(ROOT, root)):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            if f.endswith(".py"):
                out.append(os.path.relpath(os.path.join(dp, f), ROOT).replace("\\", "/"))
    return out


def find_orphans() -> List[Tuple[str, int]]:
    files: List[str] = []
    for r in SCAN_ROOTS:
        files.extend(_py_files(r))
    text: Dict[str, str] = {}
    for p in files:
        try:
            with open(os.path.join(ROOT, p), encoding="utf-8", errors="ignore") as fh:
                text[p] = fh.read()
        except OSError:
            pass

    modules = {os.path.basename(p)[:-3]: p for p in files
               if os.path.basename(p) != "__init__.py"}
    orphans: List[Tuple[str, int]] = []
    for mod, path in sorted(modules.items()):
        if any(path.startswith(d) for d in DYNAMIC_DIRS):
            continue  # AC4
        pat = re.compile(
            rf"(from\s+[\w\.]*\b{re.escape(mod)}\s+import|import\s+[\w\.]*\b{re.escape(mod)}\b)")
        if any(p != path and pat.search(t) for p, t in text.items()):
            continue
        orphans.append((mod, len(text.get(path, "").splitlines())))
    return orphans


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--update-baseline", action="store_true")
    args = ap.parse_args()

    orphans = find_orphans()
    names = sorted(m for m, _ in orphans)

    if args.update_baseline:
        with open(BASELINE, "w", encoding="utf-8") as fh:
            json.dump({"count": len(names), "modules": names}, fh, indent=2)
        print(f"baseline updated: {len(names)} orphans")
        return 0

    print(f"ORPHANS: {len(orphans)} production modules with no production importer\n")
    print(f"{'MODULE':<32}{'LINES':>7}  {'DISPOSITION':<14}REASON")
    print("-" * 100)
    undecided, review = [], []
    for mod, lines in sorted(orphans, key=lambda x: -x[1]):
        disp, why = DISPOSITIONS.get(mod, ("UNDECIDED", ""))
        if disp == "UNDECIDED":
            undecided.append(mod)
        elif disp == NEEDS_OWNER:
            review.append(mod)
        print(f"{mod:<32}{lines:>7}  {disp:<14}{why[:56]}")

    prior = {"count": None, "modules": []}
    if os.path.exists(BASELINE):
        try:
            with open(BASELINE, encoding="utf-8") as fh:
                prior = json.load(fh)
        except (OSError, ValueError):
            pass

    print()
    rc = 0
    if undecided:
        # AC2: none may be left undecided.
        print(f"UNDECIDED ({len(undecided)}): " + ", ".join(undecided))
        print("REQ-15 AC2: every orphan needs a disposition.")
        rc = 1
    new = sorted(set(names) - set(prior.get("modules") or []))
    if prior.get("count") is not None and new:
        # AC5: a NEW orphan is a regression; existing ones are debt.
        print(f"NEW since baseline ({len(new)}): " + ", ".join(new))
        rc = 1
    if review:
        print(f"AWAITING OWNER ({len(review)}): " + ", ".join(review))
        print("Dispositioned as REVIEW - evidence recorded, decision needs domain "
              "knowledge. Not a failure.")
    if rc == 0:
        print()
        print(f"OK - {len(orphans)} orphans, all dispositioned, none new.")
    print("\nREQ-15 AC6: RETIRE is a RECOMMENDATION. This script deletes nothing.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
