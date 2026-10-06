"""Contract: the turn protocol (execution audit Phase 3).

DONE line under test: "Every turn ends with exactly one turn.end. An error
shows in the chat." The backend half is pinned here:

  * every path through a turn (normal, double end, exception, cancellation,
    a body that forgets to end, an end before any part) sends exactly one
    turn.start and exactly one turn.end, start first, end last;
  * part seq numbers are dense (1..N) even when many threads emit at once,
    and turn.end reports N;
  * a part after turn.end is dropped AND counted (never silent);
  * an exception becomes a visible ``error`` part before ``turn.end`` with
    status ``error``;
  * bridged bus events are filed into the live turn as the right part type;
  * the generated TypeScript types match the Python schema;
  * the two producers are wired: the WS event bridge routes into turns and
    the gateway text path opens a TurnEmitter.

The module is loaded by file path: importing ``backend.agent`` pulls in the
whole kernel, and this contract must hold without it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "backend" / "agent" / "turn_protocol.py"


def _load():
    spec = importlib.util.spec_from_file_location("_turn_protocol_contract", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tp = _load()


@pytest.fixture(autouse=True)
def _clean_registry():
    tp.reset_registry_for_testing()
    yield
    tp.reset_registry_for_testing()


class Wire:
    """Collects what the emitter sends, thread-safely, like the WS would."""

    def __init__(self):
        self.msgs = []
        self._lock = threading.Lock()

    def __call__(self, msg):
        with self._lock:
            self.msgs.append(msg)

    def types(self):
        return [m["type"] for m in self.msgs]

    def parts(self):
        return [m["payload"] for m in self.msgs if m["type"] == "turn.part"]

    def end(self):
        ends = [m["payload"] for m in self.msgs if m["type"] == "turn.end"]
        assert len(ends) == 1, f"expected exactly one turn.end, got {len(ends)}"
        return ends[0]


def _emitter(wire, turn_id="t1", conv="conv-1", **kw):
    return tp.TurnEmitter(wire, turn_id=turn_id, conversation_id=conv, **kw)


def _assert_framed(wire):
    types = wire.types()
    assert types.count("turn.start") == 1, types
    assert types.count("turn.end") == 1, types
    assert types[0] == "turn.start", types
    assert types[-1] == "turn.end", types


# ── exactly one turn.end, on every path ─────────────────────────────────────

def test_normal_turn_is_framed_and_end_counts_parts():
    w = Wire()
    em = _emitter(w, prompt="hi", mode="developer")
    em.start()
    em.text("Hel")
    em.text("lo")
    em.reasoning("thinking")
    assert em.end("ok", text="Hello", speak="Hello") is True
    _assert_framed(w)
    start = w.msgs[0]["payload"]
    assert start["turn_id"] == "t1" and start["conversation_id"] == "conv-1"
    assert start["strand_id"] == "conv-1" and start["to"] == ["@iris"] and start["author"] == "user"
    assert start["mode"] == "developer" and start["v"] == tp.PROTOCOL_VERSION
    seqs = [p["seq"] for p in w.parts()]
    assert seqs == [1, 2, 3]
    end = w.end()
    assert end["status"] == "ok" and end["parts"] == 3 and end["text"] == "Hello" and end["speak"] == "Hello"


def test_second_end_is_refused():
    w = Wire()
    em = _emitter(w)
    em.start()
    assert em.end("ok") is True
    assert em.end("error", error="late") is False
    _assert_framed(w)
    assert w.end()["status"] == "ok"


def test_exception_in_the_turn_shows_an_error_part_then_ends_with_error():
    w = Wire()
    with pytest.raises(RuntimeError):
        with _emitter(w):
            raise RuntimeError("API returned 429")
    _assert_framed(w)
    errs = [p["part"] for p in w.parts() if p["part"]["type"] == "error"]
    assert len(errs) == 1 and "API returned 429" in errs[0]["message"]
    end = w.end()
    assert end["status"] == "error" and "API returned 429" in end["error"]
    # the error part comes BEFORE the end, so the chat shows it inside the turn
    assert w.types().index("turn.end") > max(i for i, m in enumerate(w.msgs) if m["type"] == "turn.part")


def test_cancellation_ends_cancelled():
    w = Wire()
    with pytest.raises(asyncio.CancelledError):
        with _emitter(w):
            raise asyncio.CancelledError()
    _assert_framed(w)
    assert w.end()["status"] == "cancelled"


def test_body_that_forgets_to_end_is_closed_by_the_guard():
    w = Wire()
    with _emitter(w) as em:
        em.text("partial")
    _assert_framed(w)
    assert w.end()["status"] == "ok"


def test_end_before_any_part_still_sends_a_start():
    w = Wire()
    em = _emitter(w)
    em.end("error", error="kernel unavailable")
    _assert_framed(w)
    assert w.end()["parts"] == 0


def test_part_before_start_starts_the_turn():
    w = Wire()
    em = _emitter(w)
    em.text("x")
    em.end("ok")
    _assert_framed(w)


def test_bad_status_becomes_error_not_a_second_shape():
    w = Wire()
    em = _emitter(w)
    em.end("done")
    assert w.end()["status"] == "error"


# ── seq numbers: dense under concurrency ────────────────────────────────────

def test_seq_is_dense_when_eight_threads_emit_two_hundred_parts_each():
    w = Wire()
    em = _emitter(w)
    em.start()
    barrier = threading.Barrier(8)

    def worker(i):
        barrier.wait()
        for k in range(200):
            em.text(f"{i}:{k} ")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    em.end("ok")
    seqs = sorted(p["seq"] for p in w.parts())
    assert seqs == list(range(1, 1601))
    assert w.end()["parts"] == 1600


def test_part_after_end_is_dropped_and_counted():
    w = Wire()
    em = _emitter(w)
    em.start()
    em.end("ok")
    assert em.text("late") is None
    assert em.dropped_after_end == 1
    assert "turn.part" not in w.types()


def test_unknown_part_type_is_not_sent():
    w = Wire()
    em = _emitter(w)
    assert em.part("chat_chunk", delta="x") is None
    em.end("ok")
    assert w.parts() == []


def test_a_failing_transport_never_breaks_the_turn():
    calls = []

    def flaky(msg):
        calls.append(msg["type"])
        raise ConnectionError("socket closed")

    em = _emitter(flaky)
    em.start()
    em.text("x")
    assert em.end("ok") is True
    assert calls == ["turn.start", "turn.part", "turn.end"]


# ── bus events filed into the live turn ─────────────────────────────────────

@pytest.mark.parametrize(
    "event,data,ptype",
    [
        ("tool:call", {"tool": "read_file", "turn_id": "t1"}, "tool_call"),
        ("tool:result", {"tool": "read_file", "success": True, "turn_id": "t1"}, "tool_result"),
        ("tool:error", {"tool": "run", "error": "exit 1", "turn_id": "t1"}, "tool_result"),
        ("task:start", {"card_id": "c1", "turn_id": "t1"}, "todo"),
        ("task:progress", {"card_id": "c1", "turn_id": "t1"}, "todo"),
        ("memory:event", {"kind": "recall", "turn_id": "t1"}, "todo"),
        ("document:render", {"title": "Plan", "turn_id": "t1"}, "card"),
        ("permission:request", {"request_id": "r1", "turn_id": "t1"}, "interaction"),
        ("question:ask", {"question_id": "q1", "turn_id": "t1"}, "interaction"),
        ("plan:validation_failed", {"message": "bad plan", "turn_id": "t1"}, "notice"),
        ("agent:error", {"message": "boom", "turn_id": "t1"}, "error"),
    ],
)
def test_bus_events_become_turn_parts(event, data, ptype):
    w = Wire()
    em = _emitter(w)
    em.start()
    seq = tp.route_bus_event(event, data)
    assert seq == 1
    assert w.parts()[0]["part"]["type"] == ptype
    em.end("ok")


def test_tool_error_is_a_failed_tool_result():
    w = Wire()
    em = _emitter(w)
    em.start()
    tp.route_bus_event("tool:error", {"tool": "run", "turn_id": "t1"})
    assert w.parts()[0]["part"]["ok"] is False
    em.end("ok")


def test_bus_event_without_turn_id_goes_to_the_conversations_live_turn():
    w = Wire()
    em = _emitter(w, turn_id="t9", conv="conv-9")
    em.start()
    assert tp.route_bus_event("task:progress", {"card_id": "c"}, conversation_id="conv-9") == 1
    em.end("ok")


def test_events_of_another_conversation_never_land_in_this_turn():
    w = Wire()
    em = _emitter(w, turn_id="t1", conv="conv-A")
    em.start()
    assert tp.route_bus_event("task:progress", {"card_id": "c"}, conversation_id="conv-B") is None
    em.end("ok")
    assert w.parts() == []


def test_a_closed_turn_takes_no_more_bus_events():
    w = Wire()
    em = _emitter(w)
    em.start()
    em.end("ok")
    assert tp.active_turn("t1", "conv-1") is None
    assert tp.route_bus_event("tool:call", {"tool": "x", "turn_id": "t1"}) is None


def test_unrelated_bus_events_are_not_parts():
    w = Wire()
    em = _emitter(w)
    em.start()
    assert tp.route_bus_event("listening_state", {"state": "idle", "turn_id": "t1"}) is None
    assert tp.route_bus_event("context:usage", {"pct": 41, "turn_id": "t1"}) is None
    em.end("ok")


# ── the schema and its generated TypeScript stay in step ────────────────────

def test_generated_typescript_is_current():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_turn_protocol_ts.py"), "--check"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_every_schema_part_type_is_in_the_generated_union():
    ts = (ROOT / "lib" / "turns" / "protocol.ts").read_text(encoding="utf-8")
    for ptype in tp.PART_TYPES:
        assert f"type: '{ptype}'" in ts


# ── both producers are wired (structural guard: fails on the old code) ──────

def test_ws_event_bridge_routes_bridged_events_into_turns():
    src = (ROOT / "backend" / "agent" / "ws_event_bridge.py").read_text(encoding="utf-8")
    assert "route_bus_event" in src


def test_gateway_text_path_opens_a_turn_emitter():
    src = (ROOT / "backend" / "iris_gateway.py").read_text(encoding="utf-8")
    text_branch = src[src.index('if msg_type == "text_message":'):src.index('elif msg_type == "notification_response":')]
    assert "TurnEmitter(" in text_branch
