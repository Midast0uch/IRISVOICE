"""A chat turn's episode belongs to the chat conversation; the claim graph keeps the session the turn ran on.

Live 2026-10-26: every chat turn's episode was filed under the WS session ("session_iris", 185 rows) while its
chain rows and events were under the conversation ("thread:..."). A claim's uses, a forget of that chat and the
memory surface could not see the chat's episodes. The Mycelium wiring (outcome, landmark use, crystallize,
episode index) is keyed by the session the turn ingested under and must not move with it.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from backend.agent.agent_kernel import AgentKernel
from backend.memory.episodic import Episode
from backend.memory.interface import MemoryInterface


def test_a_chat_turn_files_its_episode_under_the_conversation():
    got = []
    k = object.__new__(AgentKernel)
    k._memory_interface = SimpleNamespace(store_episode=got.append)
    k.session_id = "session_iris"
    k.conversation_id = "thread:chat-1"
    AgentKernel._store_task_episode(k, task_summary="t", full_content="c", session_id="session_iris")
    assert len(got) == 1
    assert got[0].session_id == "thread:chat-1"
    assert got[0].graph_session_id == "session_iris"


def test_a_turn_with_no_conversation_keeps_the_session():
    got = []
    k = object.__new__(AgentKernel)
    k._memory_interface = SimpleNamespace(store_episode=got.append)
    k.session_id = "voice_headless"
    k.conversation_id = None
    AgentKernel._store_task_episode(k, task_summary="t", full_content="c")
    assert got[0].session_id == "voice_headless" and got[0].graph_session_id == "voice_headless"


def test_the_claim_graph_is_wired_with_the_graph_session_not_the_thread():
    calls = []

    class _Myc:
        def record_outcome(self, _path, _outcome, sid, _label):
            calls.append(("record_outcome", sid))

        def observe_landmark_use(self, sid, _outcome):
            calls.append(("observe_landmark_use", sid))

        def crystallize_landmark(self, session_id, **_kw):
            calls.append(("crystallize_landmark", session_id))

    stored = []
    mi = object.__new__(MemoryInterface)
    mi.episodic = SimpleNamespace(store=lambda ep, score: stored.append(ep) or "ep-1",
                                  fragment_and_store=lambda **kw: stored.append(kw))
    mi._mycelium = _Myc()
    ep = Episode(session_id="thread:chat-1", task_summary="t", full_content="c", tool_sequence=[],
                 outcome_type="success", graph_session_id="session_iris")
    mi.store_episode(ep)
    assert stored[0].session_id == "thread:chat-1"
    assert stored[1]["session_id"] == "thread:chat-1"            # its context chunks belong to the conversation
    assert calls == [("record_outcome", "session_iris"), ("observe_landmark_use", "session_iris"),
                     ("crystallize_landmark", "session_iris")]


def test_a_claim_learned_in_a_chat_names_the_chat_so_its_forget_can_absorb_it():
    """Live 2026-10-26: a forget of chat conv-5082 absorbed 0 claims - every claim a chat taught named the WS session
    as its evidence source and conversation, so no chat ever 'alone' taught anything."""
    import sqlite3

    from backend.memory import corrections
    from backend.memory.mycelium.interface import MyceliumInterface
    from backend.tests.unit.test_crystallization_seeding import SCHEMA, HyphaChannel, _seed_spaces

    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    _seed_spaces(conn)
    mi = MyceliumInterface(conn)
    mi.ingest_document_data(content='{"document_id":"doc-1","format":"markdown","content":"trusted spec"}',
                            trust="trusted", session_id="session_iris", coords=[0.5, 0.5, 0.5, 0.5], label="doc-1")
    # the turn walked the node it wrote: that is the session's region (a session with no region forms no claim)
    for (nid,) in conn.execute("SELECT node_id FROM mycelium_nodes"):
        mi._registry.touch("session_iris", nid)
    lm = mi.crystallize_landmark("session_iris", 0.8, "hit", "trusted doc", source_channel=HyphaChannel.VERIFIED.value,
                                 evidence_kinds=["task_complete"], thread_id="conv-chat-1")
    assert lm is not None
    ref, raw = conn.execute("SELECT conversation_ref, evidence FROM mycelium_landmarks WHERE landmark_id = ?",
                            (lm.landmark_id,)).fetchone()
    assert ref == "conv-chat-1"
    sessions = {e["session"] for e in json.loads(raw)}
    assert sessions == {"conv-chat-1"}, sessions
    assert [lid for lid, _f in corrections._learned_only_here(conn, ["conv-chat-1"])] == [lm.landmark_id]
    assert corrections._learned_only_here(conn, ["session_iris"]) == []
