"""CLM-5 AC6 + AC7 (specs/clm-memory T4.4): the claims header and L1 thread placeholders.

- AC6: a node step shows a FIXED-SIZE header of the proven claims of its topic (the
  sector rule the claims are filed under); a stale claim is flagged; a "general"
  goal or a sector with no proven claim gets no section (never padded); candidates
  and absorbed claims never show.
- AC7: L1 (thread_context) gets a LIVE writer - every chunk write folds its vectors
  into its thread's row (before 2026-11-22 the rows froze on 2026-11-01) - and its
  first production reader: recall_memory names a matching earlier thread as ONE
  placeholder line, and expand=thread:<id> returns that thread's chunks by page,
  or a NAMED failure. The current thread is never offered back to itself.
- Flag off (IRIS_CLM_OFFLOAD unset): recall_memory carries no thread leg (the
  menu path stays as it was).

Real EpisodicStore on a temp file (stub embedder on the STORE, never the
singleton), the real levels functions, the real recall payload and expand, the
real node loop.
"""
from __future__ import annotations

import copy
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest

from backend.memory.embedding import BACKEND_LFM, Embedding

DIM = 1024


def _unit(i: int) -> np.ndarray:
    v = np.zeros(DIM, dtype="<f4")
    v[i] = 1.0
    return v


@pytest.fixture()
def store(tmp_path):
    from backend.memory.episodic import EpisodicStore

    path = str(tmp_path / "memory.db")
    seed = sqlite3.connect(path)          # plaintext seed: see test_memory_chunk_fts_contract
    seed.execute("PRAGMA journal_mode=WAL")
    seed.execute("CREATE TABLE _plain_seed (x INTEGER)")
    seed.commit()
    seed.close()
    st = EpisodicStore(db_path=path, biometric_key=b"\0" * 32)
    vec = {"v": _unit(0)}

    class _Stub:
        @staticmethod
        def encode_with_meta(text):
            return Embedding(vector=vec["v"].tolist(), backend=BACKEND_LFM,
                             chunk_count=1, truncated=False)

    st._embed = _Stub()
    yield st, vec
    from backend.memory import recall_reach

    recall_reach._INDEXES.pop(path, None)


# -- AC7: the live writer ------------------------------------------------------------

def test_ac7_a_chunk_write_keeps_its_threads_l1_row_current(store):
    st, vec = store
    vec["v"] = _unit(3)
    st.fragment_and_store("the auth token rotates every hour on the gateway", "thread-a")
    row = st.db.execute(
        "SELECT n_chunks, centroid_i8 FROM thread_context WHERE thread_id = 'thread-a'").fetchone()
    assert row is not None and row[0] == 1 and row[1] is not None     # was: no row at all
    st.fragment_and_store("a second fact: the gateway listens on port 8443 today", "thread-a")
    assert st.db.execute(
        "SELECT n_chunks FROM thread_context WHERE thread_id = 'thread-a'").fetchone()[0] == 2


# -- AC7: the reader -----------------------------------------------------------------

def test_ac7_thread_matches_names_the_matching_earlier_thread_and_never_the_current(store):
    from backend.memory import levels

    st, vec = store
    vec["v"] = _unit(5)
    st.fragment_and_store("we decided to use OAuth device flow for the TV app", "thread-auth")
    st.fragment_and_store("we decided to use OAuth device flow for the TV app, again", "thread-now")
    vec["v"] = _unit(9)
    st.fragment_and_store("a recipe for bread with rye flour and caraway", "thread-bread")
    got = levels.thread_matches(st.db, _unit(5), exclude="thread-now")
    assert [m["thread_id"] for m in got] == ["thread-auth"]           # bread is below the floor
    assert got[0]["n_chunks"] == 1 and got[0]["score"] >= levels.THREAD_MATCH_MIN
    assert levels.thread_matches(st.db, _unit(700), exclude="") == []  # nothing matches: empty


def test_ac7_recall_offers_one_placeholder_per_thread_only_with_the_flag(store, monkeypatch):
    from backend.agent import tool_bridge
    from backend.agent.context_view import parse_placeholder

    st, vec = store
    vec["v"] = _unit(5)
    st.fragment_and_store("we decided to use OAuth device flow for the TV app", "thread-auth")
    monkeypatch.delenv("IRIS_CLM_OFFLOAD", raising=False)
    assert "threads" not in tool_bridge._recall_memory_payload(st, "auth decision")
    monkeypatch.setenv("IRIS_CLM_OFFLOAD", "1")
    out = tool_bridge._recall_memory_payload(st, "auth decision", exclude_thread="thread-now")
    assert len(out["threads"]) == 1
    ph = parse_placeholder(out["threads"][0])
    assert ph is not None and (ph.kind, ph.id) == ("thread", "thread-auth")
    out2 = tool_bridge._recall_memory_payload(st, "auth decision", exclude_thread="thread-auth")
    assert out2["threads"] == []                                       # never offered to itself


def test_ac7_expand_thread_returns_its_chunks_by_page_or_a_named_failure(store, monkeypatch):
    from backend.agent import tool_bridge

    st, vec = store
    for i in range(3):
        vec["v"] = _unit(20 + i)      # distinct: an identical vector is folded as a duplicate
        st.fragment_and_store(f"step {i}: the migration renamed column user_{i} to account_{i}",
                              "thread-mig")
    bridge = SimpleNamespace(_memory_interface=SimpleNamespace(episodic=st),
                             _active_conversation_id={})
    events = []
    monkeypatch.setattr("backend.agent.event_emit.emit",
                        lambda *a, **k: events.append((a, k)))
    page = tool_bridge._expand_tool_result(bridge, "s", {"expand": "thread:thread-mig"})
    assert page["success"] and page["chunks"] == 3
    assert "user_0" in page["content"] and "user_2" in page["content"]
    assert [a[1] for a, _k in events] == ["RESTRETCHED"]
    nxt = tool_bridge._expand_tool_result(bridge, "s", {"expand": "thread:thread-mig", "offset": 3})
    assert nxt["success"] is False and nxt["case"] == "not_found"
    gone = tool_bridge._expand_tool_result(bridge, "s", {"expand": "thread:no-such"})
    assert gone["success"] is False and gone["case"] == "not_found" and gone["error"]


def test_ac7_a_forgotten_chunk_never_comes_back_through_its_thread(store):
    from backend.memory import levels

    st, _vec = store
    st.fragment_and_store("the locker code is 4417 and nobody else knows it", "thread-x")
    st.db.execute("UPDATE context_chunks SET folded_into = 'forgotten-by-user' "
                  "WHERE session_id = 'thread-x'")
    st.db.commit()
    assert levels.thread_page(st.db, "thread-x")["case"] == "not_found"


# -- AC6: the claims header ----------------------------------------------------------

def _claims_conn():
    from backend.memory.mycelium.sectors import ensure_sector_tables

    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.execute("CREATE TABLE mycelium_landmarks (landmark_id TEXT PRIMARY KEY, label TEXT, "
                "tier TEXT, absorbed INTEGER, activation_count INTEGER, cumulative_score REAL)")
    ensure_sector_tables(con)
    rows = [("l1", "parquet files read faster with pyarrow than csv", "landmark", 0, 9, 1.0),
            ("l2", "the sales export has a header row on line 2", "stale", 0, 5, 1.0),
            ("l3", "candidate: dates are ISO in the export", "candidate", 0, 99, 1.0),
            ("l4", "absorbed claim about the export", "landmark", 1, 50, 1.0),
            ("l5", "pandas groupby needs observed=True for categories", "landmark", 0, 4, 1.0),
            ("l6", "a fourth proven data claim", "landmark", 0, 1, 1.0)]
    for r in rows:
        con.execute("INSERT INTO mycelium_landmarks VALUES (?,?,?,?,?,?)", r)
        con.execute("INSERT INTO mycelium_landmark_sectors (landmark_id, sector_key, weight, "
                    "source, created_at) VALUES (?, 'data', 1.0, 'rule', 0)", (r[0],))
    con.commit()
    return con


def _kernel(con):
    return SimpleNamespace(_memory_interface=SimpleNamespace(_mycelium=SimpleNamespace(_conn=con)))


def test_ac6_the_header_is_fixed_size_flags_stale_and_skips_candidates_and_absorbed():
    from backend.agent.kernel.der import node
    from backend.memory.mycelium.extractor import resolve_topic_domain

    goal = "load the sales export into a pandas dataframe and compute the mean per region"
    assert resolve_topic_domain(goal) == "data"     # the rule this header keys on
    lines = node._clm_landmark_header(_kernel(_claims_conn()), goal)
    assert len(lines) == node._CLM_HEADER_MAX
    assert lines[0].startswith("parquet files")                      # most used first
    assert any("header row on line 2" in s and "(stale:" in s for s in lines)
    assert not any("candidate" in s or "absorbed" in s for s in lines)


def test_ac6_a_general_goal_or_no_store_gets_no_header():
    from backend.agent.kernel.der import node

    assert node._clm_landmark_header(_kernel(_claims_conn()), "say hello to me") == []
    assert node._clm_landmark_header(SimpleNamespace(), "load the sales export into a pandas dataframe") == []


def test_ac6_the_section_reaches_the_step_only_when_there_are_claims():
    from backend.agent import node_executor as ne

    def run(landmarks):
        seen = []

        def generate(role, messages, tools=None, **kw):
            seen.append(copy.deepcopy(messages))
            return "Done.\nSTATUS: done", "", []

        ne.run_node("Sum the sales", ne.NodeContext(
            generate=generate, execute=lambda n, p: {"success": True},
            format_result=lambda n, r: str(r), tools=[], conv_id="t44",
            landmarks=list(landmarks)))
        return seen[0][1]["content"]

    with_claims = run(["parquet files read faster", "a header row (stale: re-check before relying on it)"])
    assert "KNOWN CLAIMS" in with_claims and "\n- parquet files read faster" in with_claims
    assert "KNOWN CLAIMS" not in run([])                               # never padded
