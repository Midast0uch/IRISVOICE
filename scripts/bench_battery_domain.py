"""Battery lap 4: browser-use, computer-use, coding — the app's domain
center of gravity (owner direction 2026-09-20)."""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.request

PROMPTS = [
    # browser use (in-app crawler + vision surface)
    ("BU-1", "search the web for the LFM2.5 model release notes"),
    ("BU-2", "open nvidia.com in the in-app browser and tell me the main headline"),
    ("BU-3", "check the weather for this weekend online"),
    ("BU-4", "find the current Bitcoin price online"),
    # computer use (vision + GUI primitives)
    ("CU-5", "take a screenshot and describe what is on my screen"),
    ("CU-6", "open the calculator app"),
    ("CU-7", "what application windows are currently open"),
    # coding
    ("CD-8", "read backend/agent/decision_engine.py and tell me its class names"),
    ("CD-9", "create a file called tmp_calib_note.md containing one line: calibration lap 4"),
    ("CD-10", "check git status and tell me how many modified files there are"),
    ("CD-11", "show me the function signature of decide in the decision engine"),
    ("CD-12", "list the tests in backend/tests/unit that mention decision_engine"),
]

from _app_store import app_store_path  # noqa: E402 — the configured store, not a stale copy

DB = app_store_path()
SINCE = "2026-09-20"


def chat(prompt: str) -> dict:
    req = urllib.request.Request(
        "http://127.0.0.1:8090/api/chat",
        data=json.dumps({"text": prompt, "thread_id": "de-domain"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=420) as r:
            return {"ok": True, "s": round(time.time() - t0, 1)}
    except Exception as e:
        return {"ok": False, "s": round(time.time() - t0, 1), "e": str(e)}


def harvest():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    n = 0
    routes = {}
    chosen = {}
    try:
        for r in con.execute(
            "SELECT interaction_payload FROM system_events WHERE "
            "event_type='tool_execution' AND created_at >= ?", (SINCE,),
        ):
            try:
                p = json.loads(r[0] or "{}")
            except Exception:
                continue
            d = p.get("decision")
            if isinstance(d, dict) and d.get("consumer_id") == "tool_choice":
                n += 1
                routes[d.get("route", "?")] = routes.get(d.get("route", "?"), 0) + 1
                ch = d.get("chosen", "?")
                chosen[ch] = chosen.get(ch, 0) + 1
    finally:
        con.close()
    return n, routes, chosen


def main():
    for rid, prompt in PROMPTS:
        r = chat(prompt)
        print(f"{rid}: {'ok' if r['ok'] else 'FAIL'} in {r['s']}s", flush=True)
        time.sleep(2)
    time.sleep(10)
    n, routes, chosen = harvest()
    print(f"\nHarvest tool_choice rows: {n}; routes={routes}")
    print(f"chosen histogram: {chosen}")


if __name__ == "__main__":
    main()
