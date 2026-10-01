"""Contract: the DELIVERY events of the taxonomy (docs/Design/EVENT_TAXONOMY.md
section 4) - what reached the user - are emitted by the REAL chokepoints:

  ANSWER_GIVEN      - AgentKernel._finalize_response, the single exit of the reply contract
  ARTIFACT_PRODUCED - AgentKernel._store_document_data, where every document passes
  NARRATED          - SpeechScheduler._finish_node, when a play finished
  CARD_SHOWN        - WSEventBridge's handler, after the card-free-turn gate

References only: ids and lengths, never the text (S12). The last test: a blocked
memory_events lane never delays a delivery chokepoint.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest

import backend.memory as _memory_pkg
from backend.agent import artifact_policy
from backend.agent.agent_kernel import AgentKernel
from backend.agent.event_bus import EventPayload, IRISStreamEvent
from backend.agent.speech_lanes import NARRATION, REPLY, SpeechObservability, SpeechScheduler, UtteranceNode
from backend.agent.ws_event_bridge import WSEventBridge
from backend.tests.contract._events_fixture import BlockedLane, memory_interface, rows, store  # noqa: F401

EPISODE = "sess-dl:turn-dl"
ANSWER = "The capital of France is Paris, and it has been for a very long time."
SPOKEN = "It is Paris."


def _kernel(store):  # noqa: F811
    k = AgentKernel.__new__(AgentKernel)
    k.session_id = "sess-dl"
    k._turn_session_id = "sess-dl"
    k._event_episode_id = EPISODE
    k._memory_interface = memory_interface(store)
    k._last_render_emitted = False
    k._last_spoken_text = ""
    return k


def _no_text_in_row(row, *texts):
    blob = json.dumps(row, default=str)
    for t in texts:
        assert t not in blob, "a delivery event carries ids and lengths, never the text"


def test_answer_given_row_at_the_reply_exit(store):  # noqa: F811
    k = _kernel(store)
    shown = k._finalize_response(ANSWER, SPOKEN)
    assert shown == ANSWER  # the contract's return value is unchanged
    (row,) = rows(store, "ANSWER_GIVEN")
    assert (row["family"], row["evidence"], row["episode_id"], row["thread_id"]) == (
        "delivery", "none", EPISODE, "sess-dl")
    assert json.loads(row["payload"]) == {"display_chars": len(ANSWER), "spoken_chars": len(SPOKEN)}
    _no_text_in_row(row, ANSWER, SPOKEN)


def test_answer_given_through_the_real_structured_response_path(store):  # noqa: F811
    k = _kernel(store)
    # The presentation observer is a daemon thread that loads the decision engine: it is not
    # under test here and its CPU use starves the lane drain (measured: ~10 s on a cold run).
    k._observe_surface_async = lambda *a, **kw: None
    out = AgentKernel._process_structured_response(k, ANSWER, turn_id="turn-dl", conversation_id="c1")
    assert out == ANSWER
    (row,) = rows(store, "ANSWER_GIVEN")
    assert json.loads(row["payload"])["display_chars"] == len(ANSWER)


def test_an_empty_reply_is_not_an_answer(store):  # noqa: F811
    k = _kernel(store)
    assert k._finalize_response("", None) == ""
    assert rows(store) == []


def test_artifact_produced_row_when_a_document_is_stored(store):  # noqa: F811
    k = _kernel(store)
    saved = []

    class _Store:
        def store(self, **kw):
            saved.append(kw["document_id"])

    k._get_document_store = lambda: _Store()
    body = "# Report\n\nsecret body text that must never reach the event row"
    AgentKernel._store_document_data(
        k, document_id="doc-1", show={"format": "markdown", "content": body}, trust="trusted",
        turn_id="turn-dl", conversation_id="c1",
    )
    assert saved == ["doc-1"]
    (row,) = rows(store, "ARTIFACT_PRODUCED")
    assert (row["family"], row["episode_id"], row["thread_id"]) == ("delivery", EPISODE, "sess-dl")
    payload = json.loads(row["payload"])
    assert payload["document_id"] == "doc-1" and payload["chars"] == len(body)
    assert payload["stored"] is True
    _no_text_in_row(row, body)


def test_artifact_produced_records_a_failed_store(store):  # noqa: F811
    k = _kernel(store)

    class _Broken:
        def store(self, **kw):
            raise RuntimeError("disk full")

    k._get_document_store = lambda: _Broken()
    AgentKernel._store_document_data(
        k, document_id="doc-2", show={"format": "markdown", "content": "x"}, trust="trusted",
        turn_id="turn-dl", conversation_id="c1",
    )
    (row,) = rows(store, "ARTIFACT_PRODUCED")
    assert json.loads(row["payload"])["stored"] is False


def _node(lane, text="hello there", turn="turn-dl", session="sess-dl"):
    return UtteranceNode(
        id=f"utt_{time.time_ns()}", lane=lane,
        trigger={"source": "test", "label": lane, "rule_fired": "L1:test"},
        turn_id=turn, session_id=session, content={"kind": "text", "text": text},
    )


def _play(node_lane, store, monkeypatch, text="hello there"):
    monkeypatch.setattr(_memory_pkg, "_memory_interface", memory_interface(store))
    done = threading.Event()
    sched = SpeechScheduler(play=lambda n: done.set(), observability=SpeechObservability(),
                            auto_start=True)
    try:
        sched.admit(_node(node_lane, text))
        assert done.wait(10)
        # _finish_node runs just after the play callable returns
        deadline = time.time() + 5
        while time.time() < deadline and sched.is_playing():
            time.sleep(0.01)
    finally:
        sched.stop()


@pytest.mark.parametrize("lane", [NARRATION, REPLY])
def test_narrated_row_when_a_play_finishes(store, monkeypatch, lane):  # noqa: F811
    _play(lane, store, monkeypatch, text="a spoken sentence that stays out of the row")
    (row,) = rows(store, "NARRATED")
    assert (row["family"], row["episode_id"], row["thread_id"]) == ("delivery", EPISODE, "sess-dl")
    payload = json.loads(row["payload"])
    assert payload["lane"] == lane and payload["chars"] == len("a spoken sentence that stays out of the row")
    _no_text_in_row(row, "a spoken sentence")


def test_a_play_that_raised_is_not_narrated(store, monkeypatch):  # noqa: F811
    monkeypatch.setattr(_memory_pkg, "_memory_interface", memory_interface(store))
    calls = []

    def _boom(node):
        calls.append(node.id)
        raise RuntimeError("synth died")

    sched = SpeechScheduler(play=_boom, observability=SpeechObservability(), auto_start=True)
    try:
        sched.admit(_node(NARRATION))
        end = time.time() + 5
        while time.time() < end and not calls:
            time.sleep(0.01)
        time.sleep(0.3)
    finally:
        sched.stop()
    assert rows(store, "NARRATED") == []


class _Ws:
    def session_exists(self, _sid):
        return False

    async def broadcast(self, _msg):
        return None

    async def broadcast_to_session(self, _sid, _msg):
        return None


@pytest.fixture()
def bridge(monkeypatch):
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    b = WSEventBridge(_Ws())
    b.set_main_loop(loop)
    yield b
    loop.call_soon_threadsafe(loop.stop)
    t.join(5)
    loop.close()
    artifact_policy.clear_card_gate_for_testing()


def _deliver(bridge, evt, data, turn="turn-dl", session="sess-dl", conv="c1"):
    bridge._make_handler(evt)(EventPayload(event=evt, data=data, turn_id=turn,
                                           conversation_id=conv, session_id=session))


@pytest.mark.parametrize("evt,ref_key", [
    (IRISStreamEvent.TASK_START, "card_id"),
    (IRISStreamEvent.DOCUMENT_RENDER, "document_id"),
    (IRISStreamEvent.QUESTION_ASK, "question_id"),
    (IRISStreamEvent.PERMISSION_REQUEST, "request_id"),
])
def test_card_shown_row_for_a_delivered_card(store, bridge, monkeypatch, evt, ref_key):  # noqa: F811
    monkeypatch.setattr(_memory_pkg, "_memory_interface", memory_interface(store))
    _deliver(bridge, evt, {ref_key: "ref-1", "content": "card body that stays out"})
    (row,) = rows(store, "CARD_SHOWN")
    assert (row["family"], row["thread_id"], row["episode_id"]) == ("delivery", "sess-dl", EPISODE)
    payload = json.loads(row["payload"])
    assert payload == {"event": evt.value, ref_key: "ref-1"}
    _no_text_in_row(row, "card body")


def test_a_withheld_card_is_not_a_shown_card(store, bridge, monkeypatch):  # noqa: F811
    """The card-free-turn gate runs first: the phantom-card guard stays checkable."""
    monkeypatch.setattr(_memory_pkg, "_memory_interface", memory_interface(store))
    artifact_policy.suppress_card_for_turn("turn-dl")
    _deliver(bridge, IRISStreamEvent.TASK_START, {"card_id": "card_turn-dl"})
    assert rows(store, "CARD_SHOWN") == []


def test_progress_frames_are_not_new_cards(store, bridge, monkeypatch):  # noqa: F811
    monkeypatch.setattr(_memory_pkg, "_memory_interface", memory_interface(store))
    _deliver(bridge, IRISStreamEvent.TASK_PROGRESS, {"card_id": "card_turn-dl"})
    assert rows(store, "CARD_SHOWN") == []


def test_blocked_memory_events_lane_does_not_delay_a_delivery_chokepoint(store, bridge, monkeypatch):  # noqa: F811
    monkeypatch.setattr(_memory_pkg, "_memory_interface", memory_interface(store))
    k = _kernel(store)
    with BlockedLane():
        t0 = time.monotonic()
        k._finalize_response(ANSWER, SPOKEN)
        _deliver(bridge, IRISStreamEvent.DOCUMENT_RENDER, {"document_id": "d1"})
        assert time.monotonic() - t0 < 1.0
    assert sorted(r["label"] for r in rows(store)) == ["ANSWER_GIVEN", "CARD_SHOWN"]
