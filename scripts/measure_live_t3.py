"""Live T3 — detached driver for a real 5-step FULL-mode DER task.

Binds reasoning/tool_execution to the REGISTERED provider (cerebras /
gemma-4-31b, keyed via cred_ref in data/iris_config.json), sends a 5-step
task, and streams every WS event to a log file with timestamps so the run
survives shell timeouts. The [LAYERS] line (der_steps / der_calls) is emitted
by the backend's observability.py — grep the backend log for the same turn_id.

Run detached:  python scripts/measure_live_t3.py <out.log> [session_suffix]
"""
import asyncio
import json
import sys
import time

import websockets

SUFFIX = sys.argv[2] if len(sys.argv) > 2 else "t3"
OUT = sys.argv[1] if len(sys.argv) > 1 else "live_t3_out.log"
WS_URL = f"ws://127.0.0.1:8090/ws/live_{SUFFIX}?session_id=session_live_{SUFFIX}"
PROMPT = (
    "Do research and find information about this: plan exactly five steps to "
    "investigate how voice assistants handle authentication. Steps: (1) outline "
    "the auth options, (2) describe local vs cloud auth, (3) describe session "
    "handling, (4) describe key storage, (5) write a final summary of findings. "
    "Do all five steps and give me the complete result."
)
STEPS = 5


def log(line: str) -> None:
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {line}\n")
    print(line, flush=True)


async def main() -> int:
    open(OUT, "w", encoding="utf-8").close()  # fresh log
    log(f"connecting {WS_URL}")
    async with websockets.connect(WS_URL) as ws:
        for role in ("reasoning", "tool_execution"):
            await ws.send(json.dumps({
                "type": "set_role_binding",
                "payload": {"role": role, "instance_id": "cerebras",
                            "model_override": "gemma-4-31b"},
            }))
            log(f"bound {role} -> cerebras/gemma-4-31b")
            await asyncio.sleep(0.5)

        # Web mode ON so research intent routes through DER (not the disabled
        # internet gate).
        await ws.send(json.dumps({"type": "set_web_mode", "payload": {"enabled": True}}))
        log("web_mode -> ON")
        await asyncio.sleep(0.5)

        log(f"sending {STEPS}-step task")
        await ws.send(json.dumps({
            "type": "text_message",
            "payload": {"text": PROMPT},
        }))

        started = time.time()
        got_response = False
        turn_ids = set()
        while time.time() - started < 1500:  # 25 min cap
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            except asyncio.TimeoutError:
                log(f"  ...waiting ({int(time.time()-started)}s elapsed)")
                continue
            try:
                data = json.loads(msg)
            except Exception:
                continue
            t = data.get("type") or data.get("event") or data.get("kind")
            if t == "system_status":  # 1/sec heartbeat — skip, drowns the log
                continue
            tid = data.get("turn_id") or data.get("task_id") or ""
            if tid:
                turn_ids.add(tid)
            short = json.dumps(data)[:400]
            log(f"[WS] {t} tid={tid} {short}")
            if t in ("chat_message", "message") and data.get("payload", {}).get("text"):
                got_response = True
                log(f"RESPONSE {json.dumps(data)[:800]}")
                break
            if t == "error":
                log(f"ERROR {json.dumps(data)[:400]}")
                break

        log(f"DONE got_response={got_response} turn_ids={sorted(turn_ids)}")
        # Keep the socket open briefly so the backend finishes writing [LAYERS].
        await asyncio.sleep(2)
        return 0 if got_response else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
