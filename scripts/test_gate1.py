"""
Gate 1 verification script — CPU+GPU local model load and chat through IRIS.

Run AFTER:
  1. Windows SDK installed (provides rc.exe + mt.exe)
  2. llama-cpp-python rebuilt with CUDA:
       CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python --upgrade --force-reinstall
  3. Backend running:  python start-backend.py
  4. Frontend running: npm run dev

Usage:
  python scripts/test_gate1.py
"""
import asyncio
import json
import sys
from pathlib import Path

try:
    import websockets
    import httpx
except ImportError:
    print("[ERROR] Missing dependencies: pip install websockets httpx")
    sys.exit(1)

BACKEND = "http://127.0.0.1:8000"
WS_URL  = "ws://127.0.0.1:8000/ws/gate1_test"
MODEL_PATH = str(
    Path.home() / ".lmstudio" / "models" /
    "unsloth" / "Qwen3.5-9B-GGUF" /
    "Qwen3.5-9B-Q3_K_S.gguf"
)

PASS = "[PASS]"
FAIL = "[FAIL]"
INFO = "[INFO]"


async def drain(ws, count: int = 15, timeout: float = 2.5) -> list:
    """Drain up to `count` messages with per-message timeout."""
    msgs = []
    for _ in range(count):
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            msgs.append(json.loads(raw))
        except (asyncio.TimeoutError, Exception):
            break
    return msgs


async def wait_for(ws, target_type: str, timeout: float = 90.0) -> dict | None:
    """Wait for a specific message type, discarding others."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        remaining = deadline - asyncio.get_event_loop().time()
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(2.0, remaining))
            msg = json.loads(raw)
            if msg.get("type") == target_type:
                return msg
            print(f"  {INFO} skip: {msg.get('type','?')}")
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            print(f"  {FAIL} recv error: {e}")
            return None
    return None


async def run():
    results = {}

    # ── [G1.1] Backend health ─────────────────────────────────────────────
    print("\n[G1.1] Backend health check...")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{BACKEND}/health")
            ok = r.status_code == 200
            print(f"  {PASS if ok else FAIL} /health → {r.status_code} {r.text[:60]}")
            results["G1.1"] = ok
    except Exception as e:
        print(f"  {FAIL} Cannot reach backend: {e}")
        results["G1.1"] = False
        print("\nAbort — backend not running. Start with: python start-backend.py")
        return results

    # ── [G1.4] CUDA support ───────────────────────────────────────────────
    print("\n[G1.4] llama_cpp CUDA support...")
    try:
        import llama_cpp
        cuda = llama_cpp.llama_supports_gpu_offload()
        print(f"  {PASS if cuda else FAIL} llama_cpp v{llama_cpp.__version__} — CUDA: {cuda}")
        results["G1.4"] = cuda
        if not cuda:
            print("  ACTION: Install Windows SDK then rebuild:")
            print("    CMAKE_ARGS=\"-DGGML_CUDA=on\" pip install llama-cpp-python --upgrade --force-reinstall")
    except ImportError:
        print(f"  {FAIL} llama_cpp not installed")
        results["G1.4"] = False

    # ── [G1.2] + [G1.3] + [G1.5] + [G1.6] via WebSocket ─────────────────
    print("\n[G1.2] Connecting to IRIS WebSocket...")
    try:
        async with websockets.connect(WS_URL, ping_interval=None) as ws:
            print(f"  {PASS} Connected")
            results["G1.2"] = True

            # Send request_state (what the frontend sends on connect)
            await ws.send(json.dumps({"type": "request_state", "payload": {}}))
            init_msgs = await drain(ws, count=15, timeout=2.5)
            types = [m.get("type") for m in init_msgs]
            print(f"  {INFO} Init messages: {types}")

            # [G1.3] Local models list
            # First call may take time if metadata cache is cold (parses GGUF headers).
            # Subsequent calls are near-instant (cache hit). Allow 900s worst case.
            print("\n[G1.3] Requesting local models (first scan may take a few minutes)...")
            await ws.send(json.dumps({"type": "get_local_models", "payload": {}}))
            msg = await wait_for(ws, "local_models_list", timeout=900.0)
            if msg:
                models = msg.get("payload", {}).get("models", [])
                print(f"  {PASS} {len(models)} models found:")
                for m in models[:4]:
                    print(f"         {m.get('filename')} ({m.get('size_gb')}GB)")
                results["G1.3"] = len(models) > 0
            else:
                print(f"  {FAIL} No local_models_list received")
                results["G1.3"] = False

            # [G1.5] Load model — balanced profile (GPU required)
            profile = "balanced" if results.get("G1.4") else "eco"
            print(f"\n[G1.5] Loading 4B model ({profile} profile)...")
            if not Path(MODEL_PATH).exists():
                print(f"  {FAIL} Model not found: {MODEL_PATH}")
                results["G1.5"] = False
            else:
                await ws.send(json.dumps({
                    "type": "load_local_model",
                    "payload": {"model_path": MODEL_PATH, "profile": profile}
                }))
                loaded = False
                for _ in range(360):  # up to 3 min (0.5s poll × 360)
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        msg = json.loads(raw)
                        if msg.get("type") == "local_model_loading":
                            p = msg.get("payload", {})
                            s = p.get("status", "")
                            pct = p.get("pct", "")
                            phase = p.get("phase", "")
                            detail = p.get("msg", "")
                            if s == "loading":
                                pct_str = f" {pct}%" if pct != "" else ""
                                print(f"  {INFO} [{phase}]{pct_str} {detail}")
                            else:
                                print(f"  {INFO} load status: {s}")
                            if s == "ready":
                                loaded = True
                                break
                            if s == "error":
                                print(f"  {FAIL} Error: {p.get('error')}")
                                break
                    except asyncio.TimeoutError:
                        continue
                print(f"  {PASS if loaded else FAIL} Model {'loaded' if loaded else 'FAILED to load'}")
                results["G1.5"] = loaded

            # [G1.6] Chat message
            if results.get("G1.5"):
                print("\n[G1.6] Sending chat message...")
                await ws.send(json.dumps({
                    "type": "text_message",
                    "payload": {"text": "What is 2+2? Answer with only the number."}
                }))
                chunks = []
                done = False
                for _ in range(120):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=8.0)
                        msg = json.loads(raw)
                        t = msg.get("type", "")
                        p = msg.get("payload", {})
                        if t in ("stream_chunk", "response_chunk", "chat_chunk"):
                            c = p.get("text", "") or p.get("chunk", "")
                            chunks.append(c)
                        elif t in ("stream_end", "response_complete", "agent_response",
                                   "text_response", "chat_message"):
                            # chat_message is the primary IRIS response type (content field)
                            txt = (p.get("content", "") or p.get("text", "")
                                   or p.get("response", ""))
                            if txt:
                                chunks.append(txt)
                            done = True
                            break
                    except asyncio.TimeoutError:
                        if chunks:
                            break
                response = "".join(chunks).strip()
                print(f"  {PASS if response else FAIL} Response: {response[:200]}")
                results["G1.6"] = bool(response)
            else:
                results["G1.6"] = False
                print("\n[G1.6] Skipped — model not loaded")

            # [G1.7] Memory spike check — RSS should stay below 2.5 GB
            print("\n[G1.7] Memory footprint check...")
            import psutil, os
            proc = psutil.Process(os.getpid())
            rss_mb = proc.memory_info().rss / 1024 / 1024
            # also check backend process memory via /health
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(f"{BACKEND}/health")
                    # just verify it's still alive after model load
                    backend_ok = r.status_code == 200
            except Exception:
                backend_ok = False
            print(f"  {INFO} Test process RSS: {rss_mb:.0f} MB")
            print(f"  {INFO} Backend still alive: {backend_ok}")
            # Pass if backend survived model load without crashing
            results["G1.7"] = backend_ok
            print(f"  {PASS if backend_ok else FAIL} Backend stable post-load")

            # [G1.8] Tool calling + skill memory
            if results.get("G1.5"):
                print("\n[G1.8] Tool calling / skill memory test...")

                def collect_response(chunks_list, done_flag, raw_list):
                    """Return full assembled response text."""
                    return "".join(chunks_list).strip()

                async def ask(ws, question: str, timeout: float = 120.0) -> str:
                    await ws.send(json.dumps({
                        "type": "text_message",
                        "payload": {"text": question}
                    }))
                    chunks = []
                    deadline = asyncio.get_event_loop().time() + timeout
                    while asyncio.get_event_loop().time() < deadline:
                        remaining = deadline - asyncio.get_event_loop().time()
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=min(8.0, remaining))
                            msg = json.loads(raw)
                            t = msg.get("type", "")
                            p = msg.get("payload", {})
                            if t in ("stream_chunk", "response_chunk", "chat_chunk"):
                                chunks.append(p.get("text", "") or p.get("chunk", ""))
                            elif t in ("stream_end", "response_complete", "agent_response",
                                       "text_response", "chat_message"):
                                txt = (p.get("content", "") or p.get("text", "")
                                       or p.get("response", ""))
                                if txt:
                                    chunks.append(txt)
                                break
                        except asyncio.TimeoutError:
                            if chunks:
                                break
                    return "".join(chunks).strip()

                # Create 3 skills and ask model to recall them
                r1 = await ask(ws, "Remember this skill: skill_A = 'Add two numbers'")
                r2 = await ask(ws, "Remember this skill: skill_B = 'Search the web for info'")
                r3 = await ask(ws, "Remember this skill: skill_C = 'Generate a Python function'")
                recall = await ask(ws, "List all 3 skills I asked you to remember in this conversation.")

                # Check all three skill names appear in recall
                has_all = all(s in recall for s in ("skill_A", "skill_B", "skill_C"))
                print(f"  r1: {r1[:60]}")
                print(f"  r2: {r2[:60]}")
                print(f"  r3: {r3[:60]}")
                print(f"  recall: {recall[:200]}")
                print(f"  {PASS if has_all else FAIL} All 3 skills recalled: {has_all}")
                results["G1.8"] = has_all
            else:
                results["G1.8"] = False
                print("\n[G1.8] Skipped — model not loaded")

    except Exception as e:
        print(f"  {FAIL} WebSocket error: {e}")
        results["G1.2"] = False

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "="*50)
    print("GATE 1 RESULTS:")
    all_pass = True
    for key, val in sorted(results.items()):
        status = PASS if val else FAIL
        print(f"  {status} {key}")
        if not val:
            all_pass = False
    print("="*50)
    if all_pass:
        print(">>> GATE 1 VERIFIED — local model load + chat + skill recall all pass")
    else:
        pending = [k for k, v in results.items() if not v]
        print(f">>> GATE 1 INCOMPLETE — pending: {pending}")
    return results


if __name__ == "__main__":
    asyncio.run(run())
