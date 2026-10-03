"""Live check: a long browser task through IRIS, in the browser's own session.

usage: python live_browser_task.py personal|developer
Prints tool calls, browser/vision events and the reply; restores mode at the end.
"""
import asyncio, json, sys, tempfile, time, urllib.request
from collections import Counter
from pathlib import Path
import websockets

MODE = sys.argv[1] if len(sys.argv) > 1 else "personal"
HTTP = "http://127.0.0.1:8090"
PROMPT = ("Use the in-app browser: open https://en.wikipedia.org, type 'Mount Kilimanjaro' into the "
          "Wikipedia search box, and open the article. Then tell me its height in metres and the year "
          "of the first recorded ascent.")
NOISE = {"ping", "audio_envelope", "listening_state", "system_status", "context:usage"}


def http(method, path, body=None, timeout=90):
    req = urllib.request.Request(HTTP + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


async def main():
    original_mode = http("GET", "/api/mode").get("mode")
    cfg_path = Path(r"C:\dev\IRISVOICE\data\iris_config.json")
    original_projects = json.loads(cfg_path.read_text(encoding="utf-8")).get("projects") or []
    work = Path(tempfile.gettempdir()) / "iris-evals" / "live-browser"
    work.mkdir(parents=True, exist_ok=True)
    if MODE == "developer":
        http("POST", "/api/projects", {"projects": [p for p in original_projects if p.get("id") != "iris-evals"] + [
            {"id": "iris-evals", "name": "IRIS evals", "path": str(work.parent), "mode": "developer", "driveType": "local"}]})
    http("POST", "/api/mode", {"mode": MODE})
    counts, t0 = Counter(), time.monotonic()
    try:
        async with websockets.connect("ws://127.0.0.1:8090/ws/live-browser?session_id=session_iris",
                                      max_size=2**24, ping_interval=None) as ws:
            await ws.send(json.dumps({"type": "set_web_mode", "payload": {"enabled": True}}))
            await asyncio.sleep(1)
            if MODE == "developer":
                await ws.send(json.dumps({"type": "dev_cli", "payload": {"query": PROMPT, "workdir": str(work)}}))
                finals = {"text_response"}
            else:
                await ws.send(json.dumps({"type": "text_message", "payload": {"text": PROMPT}}))
                finals = {"chat_message", "text_response"}
            while time.monotonic() - t0 < 600:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                except asyncio.TimeoutError:
                    continue
                t = m.get("type", "")
                p = m.get("payload") if isinstance(m.get("payload"), dict) else m
                counts[t] += 1
                if t == "ping":
                    await ws.send(json.dumps({"type": "pong", "payload": {}}))
                    continue
                if t in NOISE:
                    continue
                el = f"{time.monotonic()-t0:6.1f}s"
                if t.startswith("tool:") or "browser" in t or "vision" in t or "cursor" in t or t in ("open_tab", "permission:request"):
                    keys = {k: (str(v)[:70]) for k, v in p.items() if k in ("tool", "tool_name", "name", "action", "url", "element_id", "text", "status", "phase", "kind", "error", "ok", "label")}
                    print(f"{el} {t} {keys}", flush=True)
                    if t == "permission:request":
                        await ws.send(json.dumps({"type": "notification_response", "payload": {
                            "notification_id": p.get("request_id", ""), "action": "confirm" if p.get("requires_confirmation") else "grant"}}))
                if t in finals:
                    text = p.get("content") or p.get("text") or ""
                    if t == "chat_message" and p.get("role") not in (None, "assistant", "error"):
                        continue
                    print(f"{el} REPLY ({t}): {str(text)[:600]}", flush=True)
                    break
    finally:
        print("event counts:", dict(counts.most_common(25)), flush=True)
        if MODE == "developer":
            http("POST", "/api/projects", {"projects": original_projects})
        http("POST", "/api/mode", {"mode": original_mode or "personal"})
        print("restored mode", original_mode, flush=True)


asyncio.run(main())
