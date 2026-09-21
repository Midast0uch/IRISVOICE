"""Decisive probe: does the grade helper emit the card settle?"""
import sys, time
sys.path.insert(0, r"C:\dev\IRISVOICE")
from backend.agent.event_bus import get_event_bus, IRISStreamEvent
from backend.agent.agent_kernel import get_agent_kernel

events = []

def cb(payload):
    events.append({
        "event": getattr(payload, "event", None),
        "data": dict(getattr(payload, "data", {}) or {}),
    })

bus = get_event_bus()
bus.subscribe(IRISStreamEvent.TASK_DONE, cb)
bus.subscribe(IRISStreamEvent.TASK_FAIL, cb)

kernel = get_agent_kernel("conv-csprobe", "session-csprobe")
print("running text probe...")
resp = kernel.process_text_message("What is 2 plus 2? Reply with one word.")
time.sleep(1)

print("response len:", len(resp or ""))
print("events captured:", len(events))
for e in events:
    print("  ", e["event"], "=>", {k: v for k, v in e["data"].items() if k in ("card_id", "task_id", "conversation_id", "outcome")})
