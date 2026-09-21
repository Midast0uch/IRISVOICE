"""Battery lap 3: ten prompts across decision classes."""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.request
from datetime import datetime

PROMPTS = [
    ("DE-12", "what time is it"),
    ("DE-13", "show me the README"),
    ("DE-14", "list files in the project root"),
    ("DE-15", "what is the capital of France"),
    ("DE-16", "take a screenshot of my screen"),
    ("DE-17", "recall what we discussed about the orb"),
    ("DE-18", "open package.json and tell me the version"),
    ("DE-19", "set a reminder style note: stand up and stretch"),
    ("DE-20", "compare the chat view and dashboard view structure briefly"),
]

DB = r"C:\dev\IRISVOICE\data\memory.db"
SINCE = "2026-09-20"


def chat(prompt: str) -> dict:
    req = urllib.request.Request(
        "http://127.0.0.1:8090/api/chat",
        data=json.dumps({"text": prompt, "thread_id": "de-calib"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return {"ok": True, "s": round(time.time() - t0, 1)}
    except Exception as e:
        return {"ok": False, "s": round(time.time() - t0, 1), "e": str(e)}


def harvest():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    n = 0
    routes = {}
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
            if isinstance(d, dict):
                n += 1
                routes[d.get("route", "?")] = routes.get(d.get("route", "?"), 0) + 1
    finally:
        con.close()
    return n, routes


def main():
    for rid, prompt in PROMPTS:
        r = chat(prompt)
        print(f"{rid}: {'ok' if r['ok'] else 'FAIL'} in {r['s']}s")
        time.sleep(2)
    time.sleep(10)
    n, routes = harvest()
    print(f"\nHarvest: {n} decision rows; routes={routes}")


if __name__ == "__main__":
    main()
