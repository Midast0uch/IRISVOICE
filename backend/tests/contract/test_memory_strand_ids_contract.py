"""Contract: every memory_events row typed during a chat turn carries
  thread_id = <conversation id>   and   episode_id = "<conversation id>:<turn id>"
(MEMORY-UX-PLAN 4.2, MEMORY-SURFACE-BUILD section 4 case 5).

Measured on the live store (read-only, 2026-10-21; non-eval rows only, 5,217): 3,311 rows had an
episode id that was not "<conversation>:<turn>" (GOAL_SET / GOAL_REFINED / CONFIRMATION ... of the
event Oracle wrote the bare turn id) and 1,539 rows had a thread_id that was no conversation
(the DER events carried the WebSocket session id "session_iris"). A memory view could not link
those rows to a strand.

The rows come from the REAL emitters (kernel finalize, the DER recall seam, the speech seam, the
event Oracle hook and the turn entry's call into it) through the REAL lane into a REAL temp
store. The kernel runs under a SESSION id that is NOT its conversation id, the shape that broke.
"""
from __future__ import annotations

import sqlite3
import time
from types import SimpleNamespace

import pytest

import backend.agent.event_oracle as eo
from backend.agent import agent_kernel as ak
from backend.agent import speech_lanes
from backend.agent.agent_kernel import AgentKernel
from backend.agent.event_emit import emit
from backend.memory import memory_events as me
from backend.memory import strand_ids
from backend.memory.strand_ids import conversation_row_ids
from backend.tests.contract._events_fixture import memory_interface, rows, store  # noqa: F401
from backend.utils.durability_queue import lane

SESSION, CONV, TURN = "session_iris", "conv-42", "turn-7"
EPISODE = f"{CONV}:{TURN}"


def _kernel(store, session=SESSION, conv=CONV, turn=TURN):  # noqa: F811
    k = AgentKernel.__new__(AgentKernel)
    k.session_id = session
    k._turn_session_id = session
    k.conversation_id = conv
    k._event_episode_id = f"{session}:{turn}"
    k._der_turn_id = turn
    k._memory_interface = memory_interface(store)
    k._last_render_emitted = False
    k._last_spoken_text = ""
    return k


def assert_strand_ids(rs, conv=CONV, episode=EPISODE):
    """THE rule, asserted on every row (shared by the behavioral cases below)."""
    assert rs, "the emitter wrote no row"
    for r in rs:
        assert r["thread_id"] == conv, f"{r['label']}: thread_id {r['thread_id']!r} is not the conversation {conv!r}"
        assert r["episode_id"] == episode, (
            f"{r['label']}: episode_id {r['episode_id']!r} is not '<conversation>:<turn>' {episode!r}")


def test_kernel_events_under_a_session_id_are_keyed_to_the_conversation(store):  # noqa: F811
    k = _kernel(store)
    k._finalize_response("The capital of France is Paris, and it has been for a long time.", "It is Paris.")
    ak._emit_event(k, "PLAN_MADE", thread_id=SESSION)
    ak._der_recall_delivered(k, SimpleNamespace(step_id="s1"), "neighbors", ["m1"], SESSION)
    rs = rows(store)
    assert {r["label"] for r in rs} == {"ANSWER_GIVEN", "PLAN_MADE", "RECALL_DELIVERED"}
    assert_strand_ids(rs)


def test_the_case_and_chain_keys_keep_the_session_id(store, monkeypatch):  # noqa: F811
    """Only the ROW is re-keyed: the chain reference (and cases) stay on the id the caller holds."""
    chain = []
    monkeypatch.setattr(me, "_append_event", lambda thread_id, *a, **kw: chain.append(thread_id))
    k = _kernel(store)
    emit(k, "PIVOT", thread_id=SESSION)
    assert_strand_ids(rows(store, "PIVOT"))
    assert chain == [SESSION]


def test_speech_narration_finds_the_kernel_of_its_own_turn(store, monkeypatch):  # noqa: F811
    """Two conversations run under one session id; the NARRATED row belongs to the one whose
    turn it is (the speech node carries a session id and a turn id, never a conversation)."""
    mine = _kernel(store, conv=CONV, turn=TURN)
    other = _kernel(store, conv="conv-99", turn="turn-1")
    monkeypatch.setitem(ak._agent_kernel_instances, "conv-99", other)
    monkeypatch.setitem(ak._agent_kernel_instances, CONV, mine)
    node = speech_lanes.UtteranceNode(
        id=f"utt_{time.time_ns()}", lane=speech_lanes.NARRATION,
        trigger={"source": "test", "label": "n", "rule_fired": "L1:test"},
        turn_id=TURN, session_id=SESSION, content={"kind": "text", "text": "working on it"},
    )
    speech_lanes._emit_narrated(node)
    assert_strand_ids(rows(store, "NARRATED"))


def test_a_kernel_without_a_conversation_keeps_the_ids_it_was_given(store):  # noqa: F811
    k = _kernel(store, conv=None)
    emit(k, "PIVOT", thread_id=SESSION)
    (r,) = rows(store, "PIVOT")
    assert (r["thread_id"], r["episode_id"]) == (SESSION, f"{SESSION}:{TURN}")


class _Engine:
    """STUB (said plainly): the decision engine is not under test; it answers "new_request"."""

    def decide(self, consumer_id, options, frame, instruction=None):
        from backend.agent.decision_engine import DecisionScore

        chosen = "new_request" if "new_request" in options else options[0]
        return DecisionScore(consumer_id=consumer_id, chosen=chosen, confidence=0.9,
                             distribution=(), engine_latency_ms=1)


def test_the_user_message_event_carries_the_conversation_and_turn_ids(monkeypatch):
    """The turn entry hands the event Oracle "<conversation>:<turn>" (it handed the bare turn id)
    and the real hook writes it: rows GOAL_SET / CORRECTION ... join the strand and the turn."""
    from backend.agent.decision_engine import CONSUMER_TASKS

    saved = dict(CONSUMER_TASKS)
    monkeypatch.setenv(eo.BRAIN_RATE_ENV, "0")
    monkeypatch.setenv(eo.RULE_SAMPLE_ENV, "0")
    monkeypatch.setattr(eo, "_GATES", {})
    monkeypatch.setattr(eo, "_PASS_STATE", {"watermark": 0.0, "last_pass": 0.0})
    monkeypatch.setattr(me, "_append_event", lambda *a, **k: None)   # the Immortus FFI is not under test
    monkeypatch.setattr(eo, "ENGINE", _Engine())
    c = sqlite3.connect(":memory:", check_same_thread=False)
    me.ensure_schema(c)
    seen = {}
    real = eo.observe_user_message

    def _spy(owner, text, **kw):
        seen.update(kw)
        return True

    class _Stop(Exception):
        pass

    def _boom(*a, **kw):
        raise _Stop

    k = AgentKernel.__new__(AgentKernel)
    k.clear_turn_trust_flag = lambda: None
    k.session_id = SESSION
    eo.observe_user_message = _spy
    orig_metrics = ak.TurnMetrics
    ak.TurnMetrics = _boom
    try:
        try:
            k.process_text_message("hi", session_id=SESSION, conversation_id=CONV, turn_id=TURN)
        except _Stop:
            pass
    finally:
        eo.observe_user_message = real
        ak.TurnMetrics = orig_metrics
    assert seen.get("thread_id") == CONV
    try:
        eo.set_row_sink(lambda row: None)
        owner = SimpleNamespace(
            _conversation_memory=SimpleNamespace(messages=[]),
            _memory_interface=SimpleNamespace(_mycelium=SimpleNamespace(conn=c)),
        )
        assert real(owner, "no, it is Canberra", **seen)
        for _ in range(2):
            assert lane("event_oracle").flush(10.0)
            assert lane("memory_events").flush(10.0)
    finally:
        eo.set_row_sink(None)
        monkeypatch.setattr(eo, "ENGINE", eo.AUTO_ENGINE)
        CONSUMER_TASKS.clear()
        CONSUMER_TASKS.update(saved)
    cur = c.execute("SELECT label, thread_id, episode_id FROM memory_events")
    got = [dict(zip(("label", "thread_id", "episode_id"), r)) for r in cur.fetchall()]
    c.close()
    assert got, "the user-message hook wrote no event"
    assert_strand_ids(got)


# ── the resolver (read-only) and the writer's pure half ─────────────────────

@pytest.fixture()
def mem():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE caducean_session_exits (id INTEGER PRIMARY KEY, session_id TEXT, conversation_id TEXT)")
    me.ensure_schema(c)
    yield c
    c.close()


@pytest.fixture()
def chat(monkeypatch):
    live = {"conv-1", "conv-2"}
    monkeypatch.setattr(strand_ids, "_is_conversation", lambda cid: cid in live)


def test_resolver_a_conversation_id_is_its_own_strand(mem, chat):
    assert strand_ids.resolve_strand("conv-1", mem) == "conv-1"
    assert strand_ids.resolve_strand("conv-1") == "conv-1"


def test_resolver_a_session_id_resolves_through_the_session_exits(mem, chat):
    mem.execute("INSERT INTO caducean_session_exits (session_id, conversation_id) VALUES ('sess-a', 'conv-1')")
    mem.execute("INSERT INTO caducean_session_exits (session_id, conversation_id) VALUES ('sess-a', 'conv-1')")
    assert strand_ids.resolve_strand("sess-a", mem) == "conv-1"
    assert strand_ids.resolve_strand("sess-a") is None   # no store: step 1 only


def test_resolver_a_session_shared_by_two_conversations_is_ambiguous_not_guessed(mem, chat):
    for cid in ("conv-1", "conv-2"):
        mem.execute("INSERT INTO caducean_session_exits (session_id, conversation_id) VALUES ('session_iris', ?)", (cid,))
    assert strand_ids.resolve_strand("session_iris", mem) is None


def test_resolver_outside_chat_ids_resolve_to_none(mem, chat):
    mem.execute("INSERT INTO caducean_session_exits (session_id, conversation_id) VALUES ('default', 'default')")
    mem.execute("INSERT INTO caducean_session_exits (session_id, conversation_id) VALUES ('sess-x', 'conv-gone')")
    for tid in ("eval-abc", "t23-inet", "default", "sess-x", "", None):
        assert strand_ids.resolve_strand(tid, mem) is None, tid


def test_resolver_a_deleted_conversation_stays_a_strand_through_its_tombstone(mem, chat):
    assert strand_ids.resolve_strand("conv-gone", mem) is None
    me.record_strand_tombstone(mem, label="STRAND_DELETED", thread_id="conv-gone", payload={"title": "T"})
    assert strand_ids.resolve_strand("conv-gone", mem) == "conv-gone"
    mem.execute("INSERT INTO caducean_session_exits (session_id, conversation_id) VALUES ('sess-g', 'conv-gone')")
    assert strand_ids.resolve_strand("sess-g", mem) == "conv-gone"


def test_resolver_is_read_only(mem, chat):
    mem.execute("INSERT INTO caducean_session_exits (session_id, conversation_id) VALUES ('sess-a', 'conv-1')")
    before = mem.total_changes
    strand_ids.resolve_strand("sess-a", mem)
    strand_ids.resolve_strand("nope", mem)
    assert mem.total_changes == before


def test_row_ids_rule():
    s = frozenset({"session_iris"})
    assert conversation_row_ids(CONV, s, "session_iris", "session_iris:turn-7") == (CONV, EPISODE)
    assert conversation_row_ids(CONV, s, None, None) == (CONV, None)
    assert conversation_row_ids(CONV, s, CONV, EPISODE) == (CONV, EPISODE)
    assert conversation_row_ids(CONV, s, "research", "research:x") == ("research", "research:x")
    assert conversation_row_ids(None, s, "session_iris", "session_iris:t") == ("session_iris", "session_iris:t")
