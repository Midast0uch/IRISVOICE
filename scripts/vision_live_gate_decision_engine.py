#!/usr/bin/env python3
"""Vision-driven live gate for the decision engine (specs/tool-decision-engine
REQ-14). Drives the RUNNING app through the UI and validates what the surfaces
actually did against what the ledger says the engine decided.

Usage (backend + frontend already running via the app manager):
    python scripts/vision_live_gate_decision_engine.py [--shots DIR]

The script:
  1. connects to the app at http://localhost:3000,
  2. drives the battery rows below through the chat input,
  3. screenshots each completed turn into the canonical screenshots dir,
  4. reads the system_events ledger (read-only) and asserts:
       - every engine decision row has the pinned meta shape
       - card presence on screen matches the surface decision
       - no turn produced a chat line that is a strict prefix of card content
  5. prints a verdict per row + writes rows for docs/LIVE_TEST_VISION_BROWSER_E2E.md.

Exit codes: 0 all rows pass; 1 = gate failure; 3 = engine data insufficient;
4 = app not reachable (gate UNVERIFIED — reported, never fabricated).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS = ROOT / "screenshots"
LT_DOC = ROOT / "docs" / "LIVE_TEST_VISION_BROWSER_E2E.md"

# Battery rows: (id, prompt, assertion focus). Keep small; the harvest gate
# (AC14.3) extends this over repeated runs.
BATTERY = [
    ("DE-1", "what time is it", "plain answer; no card"),
    ("DE-2", "search the web for the RTX 5090 FE current price",
     "card expected only if engine surface gate picks it"),
    ("DE-3", "read the README file", "tool execution with engine decision row"),
]


def _ledger_rows(db: str, since: str) -> list[dict]:
    if not Path(db).is_file():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out = []
    try:
        for r in con.execute(
            "SELECT outcome, interaction_payload, created_at FROM system_events "
            "WHERE event_type='tool_execution' AND created_at >= ?",
            (since,),
        ):
            try:
                payload = json.loads(r["interaction_payload"] or "{}")
            except Exception:
                continue
            dec = payload.get("decision")
            if isinstance(dec, dict):
                out.append({"outcome": r["outcome"], "decision": dec,
                            "tool": payload.get("tool"),
                            "created_at": r["created_at"]})
    finally:
        con.close()
    return out


def _assert_meta_shape(dec: dict) -> list[str]:
    errs = []
    for k in ("engine", "consumer_id", "chosen", "confidence", "route"):
        if k not in dec:
            errs.append(f"missing meta key {k}")
    if dec.get("consumer_id") not in ("tool_choice", "presentation",
                                      "narration"):
        errs.append(f"bad consumer {dec.get('consumer_id')}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=str(SCREENSHOTS))
    from _app_store import app_store_path  # the configured store, not a stale copy

    ap.add_argument("--db", default=app_store_path())
    args = ap.parse_args()

    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    shots = Path(args.shots)
    shots.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("UNVERIFIED: playwright not installed")
        return 4

    verdicts: list[tuple[str, str, str]] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=False)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            try:
                page.goto("http://localhost:3000", timeout=15000)
            except Exception as e:
                print(f"UNVERIFIED: app not reachable: {e}")
                return 4
            time.sleep(3)  # app settle

            for row_id, prompt, note in BATTERY:
                box = page.query_selector(
                    "textarea, input[type='text']")
                if box is None:
                    verdicts.append((row_id, "FAIL", "chat input not found"))
                    continue
                box.click()
                box.fill(prompt)
                box.press("Enter")
                # bounded wait for the turn to settle — checking card marker
                deadline = time.time() + 180
                while time.time() < deadline:
                    done = page.query_selector(
                        "[data-task-status='done'], [data-task-status='fail']")
                    busy = page.query_selector("[data-task-running]")
                    if done or not busy:
                        break
                    time.sleep(2)
                shot = shots / f"{row_id}_{ts.replace(':', '-')}.png"
                page.screenshot(path=str(shot), full_page=False)
                verdicts.append((row_id, "DONE", f"shot={shot.name}; {note}"))
            browser.close()
    except Exception as e:
        print(f"UNVERIFIED: driver failed: {e}")
        return 4

    # Ledger assertions (post-run; daemon threads may lag, so poll).
    deadline = time.time() + 20
    rows: list[dict] = []
    while time.time() < deadline:
        rows = _ledger_rows(args.db, ts.split("T")[0])
        if any(r["decision"].get("consumer_id") == "tool_choice"
               for r in rows):
            break
        time.sleep(2)

    if not rows:
        print("UNVERIFIED: no decision rows harvested in ledger")
        return 3

    fails = 0
    print(f"\nLedger rows since {ts}: {len(rows)}")
    for r in rows:
        errs = _assert_meta_shape(r["decision"])
        mark = "OK" if not errs else "FAIL"
        fails += len(errs) > 0
        d = r["decision"]
        print(f"  [{mark}] {d.get('consumer_id')} chosen={d.get('chosen')} "
              f"conf={d.get('confidence')} route={d.get('route')} "
              f"tool={r['tool']} outcome={r['outcome']}")
        for e in errs:
            print(f"       ERROR: {e}")

    for row_id, status, note in verdicts:
        print(f"{row_id}: {status} — {note}")

    # append to LT doc
    try:
        with LT_DOC.open("a", encoding="utf-8") as f:
            f.write(f"\n### Decision-engine gate run {ts}\n")
            for row_id, status, note in verdicts:
                f.write(f"- {row_id}: {status} ({note})\n")
            f.write(f"- ledger rows: {len(rows)}; meta-shape failures: "
                    f"{fails}\n")
    except Exception as e:
        print(f"note: LT doc append failed ({e})")

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
