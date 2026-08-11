#!/usr/bin/env python3
"""IRIS Live Benchmark — 12-round WebSocket suite"""

import asyncio, json, time, os, sqlite3, sys
from datetime import datetime

COHERE_KEY = "rtUtK4MUo7ZxhTKc5kfaatpnHDEvSl89mF5fhXgn"
COHERE_URL = "https://api.cohere.com/compatibility/v1"
MODEL = "command-a-03-2025"

PROMPTS = [
    (1, "What files are in my project?", "file_tool"),
    (2, "Search the web for Python async best practices", "web_tool"),
    (3, "Read the project README and summarize it", "file+reasoning"),
    (4, "Remember that I prefer dark mode", "memory_store"),
    (5, "What did I ask you to remember?", "memory_recall"),
    (6, "Create a todo list for my project", "file_write"),
    (7, "Check my git status", "git_tool"),
    (8, "What tools do you have available?", "introspection"),
    (9, "Write a Python function to calculate fibonacci", "code_gen"),
    (10, "Show me my recent memory trajectory", "memory_query"),
    (11, "What phase is the caducean governor in right now?", "introspection"),
    (12, "Summarize everything we have done in this session", "memory+reasoning"),
]

results = []


def query_db():
    data = {}
    dbs = [
        "bootstrap/coordinates.db",
        "data/episodic_memory.db",
        "data/caducean_trajectories.db",
    ]
    for db_path in dbs:
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                c.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [r[0] for r in c.fetchall()]
                info = {}
                for table in tables:
                    c.execute(f'SELECT COUNT(*) FROM "{table}"')
                    info[table] = c.fetchone()[0]
                data[db_path] = info
                conn.close()
            except Exception as e:
                data[db_path] = {"error": str(e)}
    return data


async def run_round(ws, n, text, category):
    print(f"\n--- Round {n}: {text[:50]}... ---")
    t0 = time.time()
    await ws.send(json.dumps({"type": "text_message", "payload": {"text": text}}))

    response = ""
    thinking = ""
    first_token = None
    tool_used = None

    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=120)
            msg = json.loads(raw)
            mtype = msg.get("type", "")
            payload = msg.get("payload", {})

            if mtype == "chat_chunk":
                chunk = payload.get("chunk", "")
                if chunk:
                    if first_token is None:
                        first_token = time.time()
                    response += chunk

            elif mtype == "chat_message":
                response += payload.get("text", "")
                thinking = payload.get("thinking", "") or thinking
                break

            elif mtype == "chat_typing":
                if payload.get("active") is False and response:
                    break

        except asyncio.TimeoutError:
            break

    t1 = time.time()
    ttft = (first_token - t0) * 1000 if first_token else None
    total = (t1 - t0) * 1000

    r = {
        "round": n,
        "category": category,
        "ttft_ms": round(ttft, 0) if ttft else None,
        "total_ms": round(total, 0),
        "len": len(response),
        "thinking": bool(thinking),
        "preview": response[:200],
    }
    results.append(r)

    ttft_str = f"{r['ttft_ms']:.0f}ms" if r["ttft_ms"] else "N/A"
    print(
        f"  TTFT: {ttft_str} | Total: {r['total_ms']:.0f}ms | Len: {r['len']} | Thinking: {r['thinking']}"
    )
    if thinking:
        print(f"  [thinking] {thinking[:150]}")
    print(f"  >> {response[:150]}")
    return r


async def main():
    print("=" * 60)
    print(f"IRIS Live Benchmark — {datetime.now().isoformat()}")
    print(f"Model: {MODEL} | Prompts: {len(PROMPTS)}")
    print("=" * 60)

    pre_db = query_db()
    print("\nPre-benchmark DB state:")
    for db, tables in pre_db.items():
        for t, c in tables.items():
            print(f"  {db}/{t}: {c} rows")

    import websockets

    async with websockets.connect("ws://localhost:8000/ws/benchmark") as ws:
        # Configure API
        print("\n[API Config]")
        await ws.send(json.dumps({"type": "select_category", "category": "agent"}))
        await asyncio.sleep(0.3)
        await ws.send(
            json.dumps({"type": "select_section", "section_id": "model_selection"})
        )
        await asyncio.sleep(0.3)
        await ws.send(
            json.dumps(
                {
                    "type": "confirm_card",
                    "payload": {
                        "section_id": "model_selection",
                        "values": {
                            "model_provider": "api",
                            "api_key": COHERE_KEY,
                            "api_base_url": COHERE_URL,
                            "reasoning_model": MODEL,
                            "tool_model": MODEL,
                        },
                    },
                }
            )
        )
        await asyncio.sleep(1)
        print("  API configured")

        # Run all rounds
        for n, text, category in PROMPTS:
            try:
                await run_round(ws, n, text, category)
            except Exception as e:
                print(f"  Round {n} FAILED: {e}")
            await asyncio.sleep(1)

    # Post-benchmark DB
    post_db = query_db()
    print("\n\nPost-benchmark DB changes:")
    for db, tables in pre_db.items():
        post_tables = post_db.get(db, {})
        for t, pre_c in tables.items():
            post_c = post_tables.get(t, 0)
            delta = post_c - pre_c
            if delta != 0:
                print(f"  {db}/{t}: {pre_c} -> {post_c} ({delta:+d})")

    # Summary
    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)
    print(f"  {'R':<4} {'Category':<18} {'TTFT':<8} {'Total':<8} {'Len':<5}")
    print(f"  {'-' * 4} {'-' * 18} {'-' * 8} {'-' * 8} {'-' * 5}")

    ttfts = []
    totals = []
    for r in results:
        ttft = f"{r['ttft_ms']:.0f}ms" if r["ttft_ms"] else "N/A"
        total = f"{r['total_ms']:.0f}ms"
        print(
            f"  {r['round']:<4} {r['category']:<18} {ttft:<8} {total:<8} {r['len']:<5}"
        )
        if r["ttft_ms"]:
            ttfts.append(r["ttft_ms"])
        totals.append(r["total_ms"])

    if ttfts:
        ttfts.sort()
        print(f"\n  TTFT stats (ms):")
        print(
            f"    P50: {ttfts[len(ttfts) // 2]:.0f} | P95: {ttfts[int(len(ttfts) * 0.95)]:.0f} | Min: {min(ttfts):.0f} | Max: {max(ttfts):.0f}"
        )
    if totals:
        totals.sort()
        print(f"  Total stats (ms):")
        print(
            f"    P50: {totals[len(totals) // 2]:.0f} | P95: {totals[int(len(totals) * 0.95)]:.0f} | Min: {min(totals):.0f} | Max: {max(totals):.0f}"
        )

    print(f"\nCompleted at {datetime.now().isoformat()}")
    print("=" * 60)

    # Output results as JSON for pinning
    print("\n\n---JSON_RESULTS---")
    print(
        json.dumps(
            {
                "results": results,
                "pre_db": {str(k): v for k, v in pre_db.items()},
                "post_db": {str(k): v for k, v in post_db.items()},
            }
        )
    )
    print("---END_JSON_RESULTS---")


if __name__ == "__main__":
    asyncio.run(main())
