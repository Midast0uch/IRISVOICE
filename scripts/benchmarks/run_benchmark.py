#!/usr/bin/env python3
"""IRIS Live Benchmark — WebSocket-driven 20-round suite"""

import asyncio, json, time, sqlite3, os, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WS_URL = "ws://localhost:8000/ws/benchmark_harness"
BACKEND_HTTP = "http://localhost:8000"
COHERE_KEY = "rtUtK4MUo7ZxhTKc5kfaatpnHDEvSl89mF5fhXgn"
COHERE_URL = "https://api.cohere.com/compatibility/v1"
MODEL = "command-a-03-2025"

BENCHMARK_PROMPTS = [
    (1, "What files are in my project?", "file_tool"),
    (2, "Search the web for Python async best practices", "web_tool"),
    (3, "Read the README and summarize it", "file+reasoning"),
    (4, "Remember that I prefer dark mode", "memory_store"),
    (5, "What did I ask you to remember?", "memory_recall"),
    (6, "Create a todo list for my project", "file_write"),
    (7, "Check my git status", "git_tool"),
    (8, "What tools do you have available?", "introspection"),
    (9, "List all test files and tell me which are slow", "file+analysis"),
    (10, "Write a Python function to calculate fibonacci", "code_gen"),
    (11, "Show me my recent memory trajectory", "memory_query"),
    (12, "Summarize everything we have done in this session", "memory+reasoning"),
]

results = []
ws_log = []


async def send(ws, msg):
    payload = json.dumps(msg)
    ws_log.append((">>", time.time(), msg))
    await ws.send(payload)


async def recv(ws, timeout=60):
    try:
        data = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(data)
        ws_log.append(("<<", time.time(), msg))
        return msg
    except asyncio.TimeoutError:
        return None


class Timer:
    def __init__(self):
        self.start = None
        self.first_token = None
        self.end = None

    def begin(self):
        self.start = time.perf_counter()

    def on_token(self):
        if self.first_token is None:
            self.first_token = time.perf_counter()

    def finish(self):
        self.end = time.perf_counter()

    @property
    def ttft(self):
        if self.start and self.first_token:
            return (self.first_token - self.start) * 1000
        return None

    @property
    def total(self):
        if self.start and self.end:
            return (self.end - self.start) * 1000
        return None


async def configure_api(ws):
    """Configure Cohere API via navigation messages"""
    print("  [config] Sending select_category: agent...")
    await send(ws, {"type": "select_category", "category": "agent"})
    await asyncio.sleep(0.5)

    print("  [config] Sending select_section: model_selection...")
    await send(ws, {"type": "select_section", "section_id": "model_selection"})
    await asyncio.sleep(0.5)

    print("  [config] Sending confirm_card with Cohere credentials...")
    await send(
        ws,
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
                    "inference_mode": "direct",
                },
            },
        },
    )
    await asyncio.sleep(1)
    print("  [config] Done")


async def run_prompt(ws, n, text, category):
    """Send a prompt and wait for response"""
    print(f"\n--- Round {n}: {text[:60]}... ---")

    timer = Timer()
    timer.begin()
    response_text = ""
    thinking_text = ""
    response_complete = False

    await send(ws, {"type": "text_message", "payload": {"text": text}})

    while True:
        msg = await recv(ws, timeout=120)
        if msg is None:
            print(f"  TIMEOUT after 120s")
            break

        mtype = msg.get("type", "")

        if mtype == "chat_message" or mtype == "text_response":
            sender = msg.get("sender", "")
            if sender == "assistant":
                response_text = msg.get("text", response_text)
                thinking_text = msg.get("thinking", thinking_text) or thinking_text
                timer.on_token()
                response_complete = True
                break
            elif sender == "user":
                continue

        elif mtype == "chat_chunk":
            timer.on_token()
            response_text += msg.get("text", "")

        elif mtype == "chat_typing":
            if msg.get("active") == False and timer.first_token:
                # Typing done after we've seen tokens - response is complete
                response_complete = True
                break

    timer.finish()

    result = {
        "round": n,
        "category": category,
        "prompt": text[:80],
        "ttft_ms": round(timer.ttft, 1) if timer.ttft else None,
        "total_ms": round(timer.total, 1) if timer.total else None,
        "response_length": len(response_text),
        "has_thinking": bool(thinking_text),
        "response_preview": response_text[:200] if response_text else "(empty)",
    }
    results.append(result)

    print(
        f"  TTFT: {result['ttft_ms']}ms | Total: {result['total_ms']}ms | Len: {result['response_length']} chars"
    )
    if result["has_thinking"]:
        print(f"  Thinking: {thinking_text[:100]}...")
    print(f"  Preview: {result['response_preview'][:100]}")

    return result


async def query_caducean():
    """Query Caducean trajectory data"""
    db_paths = [
        "data/caducean_trajectories.db",
        "bootstrap/coordinates.db",
        "data/episodic_memory.db",
    ]

    data = {}
    for db_path in db_paths:
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                # Get table list
                c.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [r[0] for r in c.fetchall()]
                table_info = {}
                for table in tables:
                    c.execute(f'SELECT COUNT(*) FROM "{table}"')
                    count = c.fetchone()[0]
                    table_info[table] = count
                data[db_path] = {"tables": table_info}

                # If trajectories table exists, get recent entries
                if (
                    "caducean_trajectories" in table_info
                    or "trajectories" in table_info
                ):
                    tbl = (
                        "caducean_trajectories"
                        if "caducean_trajectories" in table_info
                        else "trajectories"
                    )
                    c.execute(f'SELECT COUNT(*) FROM "{tbl}"')
                    data[db_path]["trajectory_count"] = c.fetchone()[0]

                    c.execute(f'SELECT * FROM "{tbl}" ORDER BY rowid DESC LIMIT 3')
                    cols = [desc[0] for desc in c.description]
                    rows = []
                    for row in c.fetchall():
                        rows.append(dict(zip(cols, [str(r)[:50] for r in row])))
                    data[db_path]["recent_trajectories"] = rows

                conn.close()
            except Exception as e:
                data[db_path] = {"error": str(e)}

    return data


async def check_backend_health():
    """Check backend health endpoint"""
    import urllib.request

    try:
        r = urllib.request.urlopen(f"{BACKEND_HTTP}/health", timeout=5)
        return {"status": r.status, "body": r.read().decode()[:200]}
    except Exception as e:
        return {"error": str(e)}


async def main():
    print("=" * 60)
    print("IRIS Live Benchmark — Domain 19 Caducean DER Governor")
    print("=" * 60)
    print(f"Start time: {datetime.now(timezone.utc).isoformat()}")
    print(f"Model: {MODEL}")
    print(f"Endpoint: {COHERE_URL}")
    print(f"Prompts: {len(BENCHMARK_PROMPTS)}")
    print()

    # 1. Check backend health
    print("[1/5] Checking backend health...")
    health = await check_backend_health()
    print(f"  Health: {health.get('status', health.get('error', '?'))}")

    # 2. Query pre-benchmark Caducean state
    print("\n[2/5] Querying pre-benchmark Caducean state...")
    pre_caducean = await query_caducean()
    for db, info in pre_caducean.items():
        print(f"  {db}:")
        if "tables" in info:
            for table, count in info["tables"].items():
                print(f"    {table}: {count} rows")

    # 3. Connect WebSocket and configure API
    print("\n[3/5] Connecting WebSocket and configuring API...")
    import websockets

    async with websockets.connect(WS_URL) as ws:
        print(f"  Connected to {WS_URL}")

        # Configure API via navigation messages
        await configure_api(ws)

        # 4. Run benchmark prompts
        print("\n[4/5] Running benchmark prompts...")
        await asyncio.sleep(1)  # Let config settle

        for n, text, category in BENCHMARK_PROMPTS:
            try:
                await run_prompt(ws, n, text, category)
            except Exception as e:
                print(f"  ERROR in round {n}: {e}")
                import traceback

                traceback.print_exc()
            await asyncio.sleep(1)  # Brief pause between rounds

    # 5. Query post-benchmark Caducean state
    print("\n\n[5/5] Querying post-benchmark Caducean state...")
    post_caducean = await query_caducean()
    for db, info in post_caducean.items():
        if "tables" in info:
            for table, count in info["tables"].items():
                print(f"  {db}/{table}: {count} rows")

    # Generate report
    print("\n" + "=" * 60)
    print("FINAL REPORT")
    print("=" * 60)

    if results:
        # Latency stats
        ttft_values = [r["ttft_ms"] for r in results if r["ttft_ms"] is not None]
        total_values = [r["total_ms"] for r in results if r["total_ms"] is not None]

        if ttft_values:
            ttft_values.sort()
            print(f"\n📊 Latency (TTFT):")
            print(f"  P50: {ttft_values[len(ttft_values) // 2]:.0f}ms")
            print(f"  P95: {ttft_values[int(len(ttft_values) * 0.95)]:.0f}ms")
            print(
                f"  P99: {ttft_values[int(len(ttft_values) * 0.99)]:.0f}ms"
                if len(ttft_values) > 10
                else ""
            )
            print(f"  Min: {min(ttft_values):.0f}ms | Max: {max(ttft_values):.0f}ms")

        if total_values:
            total_values.sort()
            print(f"\n📊 End-to-End Latency:")
            print(f"  P50: {total_values[len(total_values) // 2]:.0f}ms")
            print(f"  P95: {total_values[int(len(total_values) * 0.95)]:.0f}ms")

        print(f"\n📊 Per-Round Results:")
        print(f"  {'Round':<6} {'Category':<18} {'TTFT':<8} {'Total':<8} {'Len':<6}")
        print(f"  {'-' * 6} {'-' * 18} {'-' * 8} {'-' * 8} {'-' * 6}")
        for r in results:
            ttft = f"{r['ttft_ms']}ms" if r["ttft_ms"] else "N/A"
            total = f"{r['total_ms']}ms" if r["total_ms"] else "N/A"
            print(
                f"  {r['round']:<6} {r['category']:<18} {ttft:<8} {total:<8} {r['response_length']:<6}"
            )

    # Caducean diff
    print(f"\n📊 Caducean Trajectories:")
    for db in pre_caducean:
        pre_count = pre_caducean[db].get("trajectory_count", 0)
        post_count = (
            post_caducean[db].get("trajectory_count", 0) if db in post_caducean else 0
        )
        delta = post_count - pre_count
        print(f"  {db}: {pre_count} → {post_count} ({delta:+,d} rows)")

    print(f"\n✅ Benchmark complete at {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
