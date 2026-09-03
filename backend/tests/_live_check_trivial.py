#!/usr/bin/env python3
"""Live end-to-end check for FIX B: send a TRIVIAL prompt through the
running backend WebSocket and confirm the log shows the 0-step guard
('plan has 0 steps — skipping DER/card') instead of a TASK_START card.

Run while backend is live on :8090:
    python backend/tests/_live_check_trivial.py
"""
import sys, time, json, asyncio, websockets

URL = "ws://127.0.0.1:8090/ws/chat"
PROMPT = "hello there, just saying hi"


async def main():
    async with websockets.connect(URL) as ws:
        # handshake / identify (mirror frontend connect)
        await ws.send(json.dumps({
            "type": "identify",
            "client_id": "live_check_001",
            "session_id": "sess_live_check",
        }))
        # send a trivial text message
        await ws.send(json.dumps({
            "type": "text_message",
            "client_id": "live_check_001",
            "session_id": "sess_live_check",
            "conversation_id": "conv_live_check",
            "text": PROMPT,
        }))
        print(f"[sent] trivial prompt: {PROMPT!r}")
        # collect events for a few seconds
        _t0 = time.time()
        _saw_card = False
        _saw_guard = False
        while time.time() - _t0 < 12:
            try:
                _msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                break
            try:
                _ev = json.loads(_msg)
            except Exception:
                continue
            _t = _ev.get("type") or _ev.get("event") or ""
            if _t == "task:start" or _t == "task_start":
                _saw_card = True
                print(f"[RECEIVED] CARD event: {json.dumps(_ev)[:200]}")
            if "skipping DER" in str(_ev) or "0 steps" in str(_ev):
                _saw_guard = True
        print(f"\nRESULT: card_shown={_saw_card}  guard_fired={_saw_guard}")
        print("PASS" if (_saw_guard and not _saw_card) else "CHECK LOG")


if __name__ == "__main__":
    asyncio.run(main())
