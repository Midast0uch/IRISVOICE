"""Write turn-protocol replay fixtures for the frontend tests.

    python scripts/gen_turn_replay_fixtures.py

Each fixture is the exact message list the REAL backend emitter
(backend/agent/turn_protocol.py: TurnEmitter + route_bus_event, the same
code the gateway and the WS event bridge run) sends for one scripted turn.
They are scripted, not captured from a live run: to replace one with a real
recording, run the app with IRIS_TURN_RECORD_DIR=<dir>, then convert the
<turn_id>.jsonl it writes with ``--from-jsonl <file> <name>``.

Output: __tests__/fixtures/turns/<name>.json  ({"name", "source", "messages"}).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "__tests__" / "fixtures" / "turns"


def _load():
    spec = importlib.util.spec_from_file_location("_tp_fixtures", ROOT / "backend" / "agent" / "turn_protocol.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tp = _load()


def _scrub(msgs):
    # Fixed timestamps so fixtures are stable across runs.
    for i, m in enumerate(msgs):
        m["payload"]["ts"] = 1_790_000_000 + i * 0.25
    return msgs


def personal_research():
    msgs = []
    em = tp.TurnEmitter(msgs.append, turn_id="turn-res-1", conversation_id="conv-personal", mode="personal",
                        prompt="compare the three STT engines and give me a page", client_ref="msg-user-1")
    em.start()
    em.reasoning("Three engines, three independent searches. ")
    tp.route_bus_event("task:start", {"card_id": "card-1", "turn_id": "turn-res-1", "plan_title": "Compare STT engines",
                                      "steps": [{"id": "s1", "description": "Search WhisperX"}, {"id": "s2", "description": "Search Parakeet"}]})
    tp.route_bus_event("tool:call", {"tool": "web_search", "call_id": "c1", "turn_id": "turn-res-1", "args": {"query": "whisperx benchmark"}})
    tp.route_bus_event("tool:result", {"tool": "web_search", "call_id": "c1", "success": True, "turn_id": "turn-res-1", "summary": "6 sources"})
    tp.route_bus_event("permission:request", {"request_id": "p1", "turn_id": "turn-res-1", "tool": "run_command", "command": "pip show faster-whisper"})
    tp.route_bus_event("permission:granted", {"request_id": "p1", "turn_id": "turn-res-1"})
    tp.route_bus_event("document:render", {"turn_id": "turn-res-1", "document_id": "doc-1", "card_id": "art-1", "title": "STT engine comparison",
                                           "kind": "page", "summary": "Benchmark table, latency chart, sources", "format": "html"})
    tp.route_bus_event("task:done", {"card_id": "card-1", "turn_id": "turn-res-1"})
    for chunk in ["**WhisperX** is the best fit. ", "It is the fastest on your GPU ", "and has word timing."]:
        em.text(chunk)
    em.end("ok", text="**WhisperX** is the best fit. It is the fastest on your GPU and has word timing.",
           speak="WhisperX is the best fit.")
    return _scrub(msgs)


def developer_fix():
    msgs = []
    em = tp.TurnEmitter(msgs.append, turn_id="turn-dev-1", conversation_id="conv-dev", mode="developer",
                        prompt="the router test fails after the window change, fix it")
    em.start()
    em.reasoning("The cap subtracts max_tokens but not the reserve. ")
    tp.route_bus_event("task:start", {"card_id": "card-d", "turn_id": "turn-dev-1", "plan_title": "Fix the router window test"})
    tp.route_bus_event("tool:call", {"tool": "read_file", "call_id": "r1", "turn_id": "turn-dev-1", "path": "backend/agent/inference/router.py"})
    tp.route_bus_event("tool:result", {"tool": "read_file", "call_id": "r1", "success": True, "turn_id": "turn-dev-1"})
    tp.route_bus_event("tool:call", {"tool": "run_command", "call_id": "x1", "turn_id": "turn-dev-1", "command": "pytest tests/unit/test_router.py -q"})
    tp.route_bus_event("tool:error", {"tool": "run_command", "call_id": "x1", "turn_id": "turn-dev-1", "error": "exit 1: 1 failed, 11 passed"})
    em.error("pytest exited 1: NameError: _RESERVE is not defined", code="node_error", recoverable=True)
    tp.route_bus_event("tool:call", {"tool": "edit_file", "call_id": "e1", "turn_id": "turn-dev-1", "path": "router.py"})
    tp.route_bus_event("tool:result", {"tool": "edit_file", "call_id": "e1", "success": True, "turn_id": "turn-dev-1"})
    tp.route_bus_event("tool:call", {"tool": "run_command", "call_id": "x2", "turn_id": "turn-dev-1", "command": "pytest tests/unit/test_router.py -q"})
    tp.route_bus_event("tool:result", {"tool": "run_command", "call_id": "x2", "success": True, "turn_id": "turn-dev-1", "summary": "12 passed"})
    tp.route_bus_event("task:done", {"card_id": "card-d", "turn_id": "turn-dev-1"})
    em.text("Fixed. The cap now subtracts the 256-token reserve; 12 router tests pass.")
    em.end("ok", text="Fixed. The cap now subtracts the 256-token reserve; 12 router tests pass.", speak="Fixed. The router tests pass.")
    return _scrub(msgs)


def error_turn():
    msgs = []
    try:
        with tp.TurnEmitter(msgs.append, turn_id="turn-err-1", conversation_id="conv-personal", prompt="what changed in Tauri 2.3?") as em:
            em.reasoning("One search for the release notes. ")
            raise RuntimeError("API returned 429: rate limit")
    except RuntimeError:
        pass
    return _scrub(msgs)


def cancelled_turn():
    import asyncio
    msgs = []
    try:
        with tp.TurnEmitter(msgs.append, turn_id="turn-cancel-1", conversation_id="conv-dev", mode="developer", prompt="refactor the planner") as em:
            em.text("Starting with the planner")
            raise asyncio.CancelledError()
    except asyncio.CancelledError:
        pass
    return _scrub(msgs)


def reordered_delivery():
    # The socket may deliver parts out of seq order; the store must not care.
    msgs = []
    em = tp.TurnEmitter(msgs.append, turn_id="turn-ooo-1", conversation_id="conv-personal", prompt="say hello")
    em.start()
    for chunk in ["Hel", "lo, ", "wor", "ld."]:
        em.text(chunk)
    em.end("ok", text="", speak="Hello, world.")
    msgs = _scrub(msgs)
    start, p1, p2, p3, p4, end = msgs
    return [p2, start, p4, p1, end, p3]  # parts after the end, start after a part


SCENARIOS = {
    "personal_research": personal_research,
    "developer_fix": developer_fix,
    "error_turn": error_turn,
    "cancelled_turn": cancelled_turn,
    "reordered_delivery": reordered_delivery,
}


def _write(name: str, messages: list, source: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    path.write_text(json.dumps({"name": name, "source": source, "messages": messages}, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(ROOT)} ({len(messages)} messages)")


def main(argv: list) -> int:
    if argv[:1] == ["--from-jsonl"] and len(argv) == 3:
        lines = Path(argv[1]).read_text(encoding="utf-8").splitlines()
        _write(argv[2], [json.loads(l) for l in lines if l.strip()], f"recorded: {Path(argv[1]).name}")
        return 0
    for name, fn in SCENARIOS.items():
        tp.reset_registry_for_testing()
        _write(name, fn(), "scripted through the real TurnEmitter + route_bus_event")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
