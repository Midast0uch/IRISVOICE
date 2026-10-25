"""Memory surface search - the contract (MEMORY-SURFACE-BUILD.md section 3).

  GET /api/memory/search?q=&kinds=&limit=40

Text only, built for memory.db: what the memory holds about a thing, and how much it holds it. What this pins, against a TEMP
store (the live schema, a small cast):
  * the query language parses server-side and comes back in the response (words, "phrases", facets, unknown facet = a word);
  * every kind is found: claims (live and cleaned), steps, moments, tasks, pins, artifacts, nodes, strands (and the ghost of a
    deleted one, and a strand found by the name it had before a rename);
  * ranking is the memory's law: a user-confirmed proven claim above a learning one with the same text, a fading claim says so,
    a cleaned claim ranks after every live result and carries its fate and its survivor;
  * evaluation threads are hidden unless the eval facet; the newest-N window of the two big tables is reported, and bounded;
  * a search is NOT a recall: the store is byte-identical (logical digest) after any number of searches, every connection is
    read-only, a search answered from the prepared corpus opens no connection at all;
  * no statement scans a big table; a store that lacks optional tables answers; a missing store is a resting 503;
  * the result shape is bounded: title <= 140, snippet <= 160, at most 8 per kind, at most `limit` overall.
"""
from __future__ import annotations

import contextlib
import importlib
import json
import re
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tests.contract.test_memory_api_contract import (MEMORY_DDL, MINIMAL_DDL, _chain, _ev, _file_digest,
                                                             _plan_lines)

NOW = time.time()
T0 = NOW - 3600
DAY = 86400.0

# tables the search reads that the API contract's DDL does not carry (live schema, the columns the search selects)
EXTRA_DDL = """
CREATE TABLE pins (pin_id TEXT PRIMARY KEY, title TEXT NOT NULL, pin_type TEXT DEFAULT 'note', content TEXT, tags TEXT DEFAULT '[]',
  created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE document_data (document_id TEXT PRIMARY KEY, conversation_id TEXT, fmt TEXT, content TEXT, title TEXT, kind TEXT,
  summary TEXT, created_at REAL, capture_path TEXT);
CREATE INDEX idx_document_data_created ON document_data(created_at);
CREATE TABLE mycelium_nodes (node_id TEXT PRIMARY KEY, space_id TEXT, label TEXT, confidence REAL, created_at REAL, updated_at REAL,
  access_count INTEGER DEFAULT 0, last_accessed REAL, last_decayed_at REAL, source_channel INTEGER);
CREATE INDEX idx_ep_timestamp ON episodes(timestamp);
"""


def _claim(con, lid, text, *, tier="candidate", absorbed=None, kinds=(), acts=0, created=T0, contradictions=0, ref=None,
           falsify=None, score=0.6, permanent=0, label=None, cls="task_x"):
    ev = json.dumps([{"kind": k, "at": created + i, "session": ref or "s"} for i, k in enumerate(kinds)])
    con.execute("INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster, traversal_sequence,"
                " cumulative_score, micro_abstract_text, activation_count, is_permanent, conversation_ref, absorbed, created_at,"
                " tier, evidence, falsify_if, contradictions) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (lid, label or lid.lower(), cls, "[]", "[]", score, text, acts, permanent, ref, absorbed, created, tier, ev,
                 falsify, contradictions))


def _seed(path: Path, ids: dict) -> None:
    con = sqlite3.connect(path)
    con.executescript(MEMORY_DDL)
    con.executescript(EXTRA_DDL)
    root, strand, ev_chat = ids["root"], ids["strand"], ids["eval_root"]
    # claims: the same match text on purpose, so only the strength can order them
    blue = "Deploy using the blue pipeline"
    _claim(con, "C_USER", blue, tier="landmark", kinds=("user_confirm", "test_pass"), acts=14, ref=root)
    _claim(con, "C_USER_SYS", blue, tier="landmark", kinds=("user_confirm", "test_pass"), acts=14, ref=root)
    _claim(con, "C_LEARN", blue, tier="candidate", kinds=("task_complete",), acts=0, ref=root)
    _claim(con, "C_TEST", blue, tier="landmark", kinds=("test_pass",), acts=2, ref=root)
    _claim(con, "C_SURV", "Deploy using the blue pipeline, survivor text", tier="landmark", kinds=("recurrence",), acts=5, ref=root)
    _claim(con, "C_OLD", blue, tier="candidate", absorbed=1, ref=root)
    _claim(con, "C_GONE", "blue pipeline stale note", absorbed=1, falsify="dissolved: no_credibility", ref=root)
    _claim(con, "C_REV", "Reverse order: pipeline blue", tier="candidate", ref=root)
    _claim(con, "C_ACC", "Résumé of the café plan", tier="candidate", ref=root)
    _claim(con, "C_BAD", "Prefer the old red pipeline", tier="candidate", contradictions=2, ref=root)
    _claim(con, "C_EVAL", "blue pipeline eval claim", tier="candidate", ref="eval-c1_thing-abc123")
    _claim(con, "C_OUT", "blue pipeline from a system thread", tier="candidate", ref="sys_test_thread")
    _claim(con, "C_WEB", "Search the web before answering", tier="landmark", kinds=("test_pass",), ref=root)
    _claim(con, "C_FADE", "Fading habit of the bluebird", tier="candidate", created=NOW - 40 * DAY, ref=root)
    _claim(con, "C_LONG", "Long " + "word " * 80 + "needleword " + "tail " * 40, ref=root)
    con.execute("INSERT INTO mycelium_landmark_merges VALUES ('m1','C_SURV','C_OLD',1.0,0.8,0.7,0.9,?)", (T0 + 20,))
    con.execute("INSERT INTO mycelium_sectors (sector_key, parent_key, status, members, created_at, updated_at) VALUES"
                " ('web', NULL, 'proven', 0, ?, ?), ('general', NULL, 'proven', 0, ?, ?), ('web/search', 'web', 'candidate', 1, ?, ?)",
                (T0, T0, T0, T0, T0, T0))
    con.execute("INSERT INTO mycelium_landmark_sectors VALUES ('C_WEB','web/search',1.0,'t',?)", (T0,))
    con.execute("INSERT INTO mycelium_landmark_sectors VALUES ('C_USER','web/search',1.0,'t',?)", (T0,))
    con.execute("INSERT INTO mycelium_landmark_sectors VALUES ('C_USER_SYS','web/search',1.0,'t',?)", (T0,))
    con.execute("INSERT INTO mycelium_episode_index VALUES ('i1','ep-a',?,'[]','[]','C_USER','h',0,?)", (root, T0))   # channel 0 = UNTRUSTED
    con.execute("INSERT INTO mycelium_episode_index VALUES ('i2','ep-b',?,'[]','[]','C_USER_SYS','h2',4,?)", (root, T0))   # 4 = SYSTEM
    # steps: two real steps of the root, a failed one, an echo row (no mediator: not a step), an evaluation step
    _chain(con, root, 0, T0 + 10, "deployed the blue pipeline to staging", cid="chain-r-0", tool="run_command:abc")
    _chain(con, root, 1, T0 + 11, "tried the green pipeline", cid="chain-r-1", tool="read_file:def")
    con.execute("UPDATE memory_chain SET result = 'failure' WHERE chain_id = 'chain-r-1'")
    con.execute("INSERT INTO memory_chain (thread_id, sequence, role, content, created_at, chain_id, insight) VALUES (?,?,?,?,?,?,?)",
                (root, 2, "agent", "c", T0 + 12, "chain-echo", "blue pipeline echo of an event"))
    _chain(con, "eval-c1_thing-abc123", 0, T0 + 13, "blue pipeline eval step", cid="chain-e-0")
    # moments
    _ev(con, "e-goal", T0 + 20, "GOAL_SET", root, episode="T1", family="intent", payload={"text": "ship the blue pipeline today"})
    _ev(con, "e-contra", T0 + 21, "CLAIM_CONTRADICTED", root, episode="T1", family="knowledge")
    _ev(con, "e-help", T0 + 22, "RECALL_HELPED", root, episode="T1", family="memory", links={"recall_trace_id": "rt-1"})
    _ev(con, "e-eval", T0 + 23, "GOAL_SET", "eval-c1_thing-abc123", episode="x", family="intent", payload={"text": "blue pipeline eval"})
    _ev(con, "e-out", T0 + 24, "GOAL_SET", "sys_test_thread", episode="y", family="intent", payload={"text": "blue pipeline system"})
    con.execute("UPDATE memory_events SET evidence = 'user', actor = 'user' WHERE event_id = 'e-goal'")
    con.execute("UPDATE memory_events SET valence = 'sets_back' WHERE event_id = 'e-contra'")
    # tombstones: a deleted conversation (a ghost) and a renamed one
    _ev(con, "e-del", T0 + 30, "STRAND_DELETED", "conv-gone-1", family="memory",
        payload={"title": "Lisbon holiday plan", "parent_id": None, "tags": ["trip"], "at": T0 + 30})
    _ev(con, "e-ren", T0 + 31, "STRAND_RENAMED", root, family="memory", payload={"old_title": "Zebra roadmap", "new_title": "Plan the release"})
    # tasks
    for i in range(30):    # 30 active days, so a 40-day-old claim has idled long enough to fade
        d = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        con.execute("INSERT INTO episodes (id, session_id, task_summary, outcome_type, timestamp) VALUES (?,?,?,?,?)",
                    (f"day-{i}", root, f"routine work {i}", "success", f"{d} 10:00:00"))
    con.execute("INSERT INTO episodes (id, session_id, task_summary, outcome_type, user_confirmed, timestamp) VALUES"
                " ('ep-ok', ?, 'deploy the blue pipeline', 'success', 1, ?)", (root, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")))
    con.execute("INSERT INTO episodes (id, session_id, task_summary, outcome_type, failure_reason, timestamp) VALUES"
                " ('ep-bad', ?, 'deploy to production', 'failure', 'blue pipeline timeout', ?)",
                (root, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")))
    con.execute("INSERT INTO episodes (id, session_id, task_summary, outcome_type, timestamp) VALUES ('ep-ev', 'eval-c1_thing-abc123',"
                " 'blue pipeline eval task', 'success', ?)", (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),))
    # pins (the pin store's two tables), artifacts, nodes
    con.execute("INSERT INTO pins (pin_id, title, pin_type, content, tags, created_at, updated_at) VALUES"
                " ('pin-1','Blue pipeline notes','note','how the pipeline deploys','[\"ops\"]',?,?)", (T0, T0))
    con.execute("INSERT INTO mycelium_pins (pin_id, title, pin_type, content, tags, created_at, updated_at) VALUES"
                " ('mpin-1','Keep the staging key rotated','note','rotate monthly','[\"security\"]',?,?)", (T0, T0))
    con.execute("INSERT INTO document_data (document_id, conversation_id, fmt, title, kind, created_at) VALUES"
                " ('doc-1', ?, 'markdown', 'Blue pipeline runbook', 'markdown', ?)", (root, T0))
    con.execute("INSERT INTO mycelium_nodes (node_id, space_id, label, confidence, created_at, updated_at, access_count, source_channel)"
                " VALUES ('node-1','toolpath','tool_blue_pipeline',0.7,?,?,3,4)", (T0, T0))
    con.commit()
    con.close()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Built ONCE per module (the real conversation store is slow to start): a real conversation store on a temp file and a
    seeded memory store. Each test gets its own COPY of the memory file."""
    root_dir = tmp_path_factory.mktemp("memory_search")
    mp = pytest.MonkeyPatch()
    mp.setenv("IRIS_CONVERSATIONS_DB", str(root_dir / "conversations.db"))
    import backend.conversation_store as cs

    importlib.reload(cs)
    root = cs.create_conversation(title="Plan the release")["id"]
    strand = cs.create_strand(root, "side check of staging")["id"]
    eval_root = cs.create_conversation(title="[eval] c1_thing")["id"]
    ids = {"root": root, "strand": strand, "eval_root": eval_root}
    base = root_dir / "memory_base.db"
    _seed(base, ids)
    yield type("World", (), {"cs": cs, "ids": ids, "base": base, "dir": root_dir})
    mp.undo()


@pytest.fixture()
def env(world, tmp_path, monkeypatch):
    """The real router over a COPY of the seeded memory store. The prepared-corpus cache is off (TTL 0): every call reads the
    store, so a test that changes the store sees the change."""
    mem = tmp_path / "memory.db"
    shutil.copyfile(world.base, mem)

    from backend.memory import surface_queries as sq
    import backend.api.memory as api

    monkeypatch.setattr(sq, "memory_db_path", lambda: mem)
    monkeypatch.setattr(sq, "SEARCH_CORPUS_TTL_S", 0)
    sq._corpus.clear()
    app = FastAPI()
    app.include_router(api.router)
    client = TestClient(app)

    def find(q, **kw):
        r = client.get("/api/memory/search", params={"q": q, **kw})
        assert r.status_code == 200, (q, r.text)
        return r.json()

    yield type("Env", (), {"client": client, "sq": sq, "api": api, "mem": mem, "ids": world.ids, "cs": world.cs,
                           "find": staticmethod(find)})
    sq._corpus.clear()


def _ids(d, kind=None):
    return [r["id"] for r in d["results"] if kind is None or r["kind"] == kind]


# -- the query language ----------------------------------------------------------------------------
def test_parse_words_phrases_and_facets():
    from backend.memory import surface_queries as sq

    p = sq.parse_query('Deploy "Blue Pipeline" proven kind:claim in:release territory:web from:you before:2026-10-01 '
                       'after:2026-09-01 last week failed helped pinned cleaned contradicted outside eval learning', now=NOW)
    assert p["words"] == ["deploy"] and p["phrases"] == ["blue pipeline"] and p["ignored"] == []
    got = {(f["facet"], f["value"]) for f in p["facets"]}
    assert got == {("proven", None), ("kind", "claim"), ("in", "release"), ("territory", "web"), ("from", "you"), ("before", "2026-10-01"),
                   ("after", "2026-09-01"), ("last", "week"), ("failed", None), ("helped", None), ("pinned", None), ("cleaned", None),
                   ("contradicted", None), ("outside", None), ("eval", None), ("learning", None)}
    by = {f["facet"]: f for f in p["facets"]}
    assert by["kind"]["text"] == "kind:claim" and by["proven"]["text"] == "proven" and by["last"]["text"] == "last week"
    assert by["last"]["at"] == pytest.approx(NOW - 7 * DAY)
    assert by["after"]["at"] == datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()      # after:D = from D's first second
    assert by["before"]["at"] == datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp()
    assert by["from"]["kinds"] == ["claim", "moment"] and by["pinned"]["kinds"] == ["pin"]
    # "last day" / "last month"
    assert {f["value"] for f in sq.parse_query("last day last month", now=NOW)["facets"]} == {"day", "month"}


def test_unknown_facet_words_are_plain_words_and_quotes_protect_facets():
    from backend.memory import surface_queries as sq

    p = sq.parse_query('kind:nothing from:nobody before:soon "proven kind:claim"', now=NOW)
    assert p["facets"] == []
    assert p["words"] == ["kind", "nothing", "from", "nobody", "before", "soon"]
    assert p["phrases"] == ["proven kind claim"]
    # terms beyond SEARCH_TERMS_MAX are reported, not silently dropped
    many = sq.parse_query(" ".join(f"w{i}" for i in range(sq.SEARCH_TERMS_MAX + 2)), now=NOW)
    assert len(many["words"]) == sq.SEARCH_TERMS_MAX and many["ignored"] == [f"w{i}" for i in range(sq.SEARCH_TERMS_MAX, sq.SEARCH_TERMS_MAX + 2)]
    p = sq.parse_query('in:"weekly plan" CafÉ', now=NOW)
    assert [(f["facet"], f["value"]) for f in p["facets"]] == [("in", "weekly plan")] and p["words"] == ["cafe"]


def test_the_parse_comes_back_in_the_response(env):
    d = env.find('deploy "blue pipeline" proven kind:claim')
    assert d["parse"]["words"] == ["deploy"] and d["parse"]["phrases"] == ["blue pipeline"]
    assert [f["text"] for f in d["parse"]["facets"]] == ["proven", "kind:claim"]
    assert d["kinds"] == ["claim"]
    assert set(d) >= {"q", "parse", "kinds", "limit", "per_kind", "results", "totals", "shown", "searched", "notes", "elapsed_ms"}


# -- matching ------------------------------------------------------------------------------------------
def test_words_are_and_prefix_case_and_accent_insensitive(env):
    assert "C_USER" in _ids(env.find("DEPLOY Blue PIPELINE", kinds="claim"))                 # case
    assert _ids(env.find("pipe blue", kinds="claim")) and "C_USER" in _ids(env.find("pipe blue", kinds="claim"))   # prefix, any order
    assert "C_USER" not in _ids(env.find("deploy red", kinds="claim"))                     # AND: every word must match
    assert "C_ACC" in _ids(env.find("cafe resume", kinds="claim"))                         # accent-insensitive both ways
    assert "C_ACC" in _ids(env.find("RÉSUMÉ", kinds="claim"))
    assert "C_USER" not in _ids(env.find("ploy", kinds="claim"))                           # a word PREFIX, not a substring


def test_a_camelcase_word_is_its_words(env):
    """2026-10-25, live: "import error" found no claim saying "ImportError" ("error" never started a word); the claims
    of the eval tasks name errors and classes this way. The snippet still shows the original text."""
    con = sqlite3.connect(env.mem)
    _claim(con, "C_CAMEL", "Running python app.py fails with an ImportError. Fix the shapes package.")
    con.commit()
    con.close()
    d = env.find("import error", kinds="claim")
    hit = next(r for r in d["results"] if r["id"] == "C_CAMEL")
    assert "ImportError" in hit["snippet"] or "ImportError" in hit["title"]
    assert "C_CAMEL" in _ids(env.find("ImportError", kinds="claim"))               # the query splits the same way
    assert "C_USER" not in _ids(env.find("ploy", kinds="claim"))                     # still a word PREFIX, not a substring


def test_a_quoted_phrase_is_exact(env):
    words = _ids(env.find("blue pipeline", kinds="claim"))
    phrase = _ids(env.find('"blue pipeline"', kinds="claim"))
    assert "C_REV" in words and "C_REV" not in phrase and "C_USER" in phrase


def test_each_kind_is_found(env):
    d = env.find("blue pipeline", limit=100)
    found ={k: _ids(d, k) for k in ("claim", "step", "moment", "turn", "pin", "artifact", "node")}
    assert "C_USER" in found["claim"]
    assert found["step"] == ["chain-r-0"]                                  # the echo row has no tool: it is not a step
    assert set(found["moment"]) == {"e-goal", "e-out"}                     # by payload text; the evaluation one ("e-eval") is hidden
    assert env.ids["root"] + ":ep-ok" in found["turn"]
    assert found["pin"] == ["pin-1"] and found["artifact"] == ["doc-1"] and found["node"] == ["node-1"]
    # the other pin table, a strand by title, tags
    assert _ids(env.find("staging key", kinds="pin"), "pin") == ["mpin-1"]
    assert env.ids["strand"] in _ids(env.find("side check", kinds="strand"))
    # a moment by the plain words of its label, and by its family word
    assert "e-goal" in _ids(env.find("you set a goal", kinds="moment"))
    assert "e-help" in _ids(env.find("remembering this helped", kinds="moment"))
    # a node by its layer word, a task by its failure reason, a step by its tool
    assert "node-1" in _ids(env.find("which tools worked", kinds="node"))
    assert env.ids["root"] + ":ep-bad" in _ids(env.find("timeout", kinds="turn"))
    assert "chain-r-0" in _ids(env.find("run command", kinds="step"))
    # each result carries the ids the UI navigates with
    ref = {r["kind"]: r["ref"] for r in d["results"]}
    assert ref["claim"]["claim"] and ref["step"]["strand"] == env.ids["root"] and ref["turn"]["turn"].startswith(env.ids["root"] + ":")
    assert ref["artifact"]["artifact"] == "doc-1" and ref["node"]["node"] == "node-1" and ref["pin"]["pin"] == "pin-1"


def test_strands_ghosts_and_old_names(env):
    ghost = env.find("lisbon", kinds="strand")["results"]
    assert [r["id"] for r in ghost] == ["conv-gone-1"] and ghost[0]["ref"]["ghost"] is True
    assert ghost[0]["title"] == "Lisbon holiday plan" and "deleted in chat" in ghost[0]["why"]
    renamed = env.find("zebra", kinds="strand")["results"]
    assert [r["id"] for r in renamed] == [env.ids["root"]] and "renamed" in renamed[0]["why"] and "Zebra roadmap" in renamed[0]["why"]
    assert renamed[0]["title"] == "Plan the release"
    assert env.find("trip", kinds="strand")["results"][0]["id"] == "conv-gone-1"           # the deleted strand's tags are searched too


def test_message_bodies_are_not_searched(env):
    env.cs.add_message(env.ids["root"], role="user", text="a distinctive wombat sentence")
    assert env.find("wombat")["results"] == []


# -- ranking: the memory's own law ---------------------------------------------------------------------
def test_user_confirmed_proven_claim_outranks_learning_one_with_the_same_match(env):
    d = env.find('"blue pipeline"', kinds="claim", limit=100)
    order = _ids(d)
    rank = {r["id"]: r["rank"] for r in d["results"]}
    # the same text, so the same match: only the strength orders them. you confirmed > a test passed > still learning
    assert order.index("C_USER_SYS") < order.index("C_TEST") < order.index("C_LEARN")
    assert rank["C_USER_SYS"] > rank["C_TEST"] > rank["C_LEARN"]
    # a pin never fades: it says so
    assert "held, it does not fade" in env.find("blue pipeline notes", kinds="pin")["results"][0]["why"]


def test_untrusted_source_counts_less_and_the_why_line_says_so(env):
    d = env.find('"blue pipeline"', kinds="claim", limit=100)
    rank = {r["id"]: r["rank"] for r in d["results"]}
    # C_USER and C_USER_SYS are the same claim with the same evidence; only the Kyudo channel differs (0 untrusted, 4 system)
    assert rank["C_USER"] < rank["C_USER_SYS"]
    assert rank["C_USER"] / rank["C_USER_SYS"] == pytest.approx(0.6, abs=0.01)     # trust = 0.5 + 0.5 / decay multiplier (5.0)
    user = next(r for r in d["results"] if r["id"] == "C_USER")
    assert user["why"] == "proven · used 14 times · you confirmed it · from a source it does not trust"
    assert "does not trust" not in next(r for r in d["results"] if r["id"] == "C_USER_SYS")["why"]


def test_a_cleaned_claim_ranks_last_with_its_fate_and_survivor(env):
    # the exact phrase leaves 6 live claims + the 2 cleaned ones = 8, the most a kind shows before "show more"
    d = env.find('"blue pipeline"', limit=100)
    order = _ids(d)
    assert d["totals"]["claim"] == 8
    cleaned = [r for r in d["results"] if r["kind"] == "claim" and r["ref"]["cleaned"]]
    assert {r["id"] for r in cleaned} == {"C_OLD", "C_GONE"}
    assert set(order[-2:]) == {"C_OLD", "C_GONE"}                        # after every live result of every kind
    old = next(r for r in cleaned if r["id"] == "C_OLD")
    assert old["ref"]["survivor"] == "C_SURV" and old["why"].startswith("cleaned - merged into Deploy using the blue pipeline, survivor")
    gone = next(r for r in cleaned if r["id"] == "C_GONE")
    assert gone["ref"]["survivor"] is None and gone["why"].startswith("cleaned - no use and no evidence")
    assert order[-2:] == [c["id"] for c in sorted(cleaned, key=lambda c: -c["rank"])]    # and by rank among themselves


def test_a_fading_claim_says_for_how_many_active_days(env):
    r = env.find("bluebird", kinds="claim")["results"][0]
    assert r["id"] == "C_FADE" and r["why"].startswith("learning") and "fading - not used or confirmed for" in r["why"]
    assert re.search(r"for (\d+) active days", r["why"]) and int(re.search(r"for (\d+) active days", r["why"]).group(1)) >= 25


def test_why_is_one_plain_line_and_titles_snippets_are_bounded(env):
    d = env.find("needleword", kinds="claim")
    (r,) = d["results"]
    assert r["id"] == "C_LONG" and len(r["title"]) <= 140 and r["title"].endswith("...")
    assert len(r["snippet"]) <= 160 and "needleword" in r["snippet"]       # the matching part, not the head
    for x in env.find("blue pipeline", limit=100)["results"]:
        assert "\n" not in x["why"] and x["why"] and len(x["title"]) <= 140 and len(x["snippet"]) <= 160


# -- facets ------------------------------------------------------------------------------------------------
def test_state_facets(env):
    proven = set(_ids(env.find("proven pipeline", limit=100)))
    assert {"C_USER", "C_USER_SYS", "C_TEST", "C_SURV"} <= proven and not ({"C_LEARN", "C_OLD", "C_REV"} & proven)
    learning = set(_ids(env.find("learning pipeline", limit=100)))
    assert {"C_LEARN", "C_REV", "C_BAD"} <= learning and not ({"C_USER", "C_OLD"} & learning)
    assert set(_ids(env.find("cleaned", limit=100))) == {"C_OLD", "C_GONE"}
    assert set(_ids(env.find("contradicted"))) >= {"C_BAD", "e-contra"} and "C_USER" not in _ids(env.find("contradicted"))
    assert set(_ids(env.find("pinned"))) == {"pin-1", "mpin-1"}
    assert set(_ids(env.find("helped"))) == {"e-help"}
    failed = env.find("failed", limit=100)
    assert "chain-r-1" in _ids(failed, "step") and env.ids["root"] + ":ep-bad" in _ids(failed, "turn") and "e-contra" in _ids(failed, "moment")
    assert "chain-r-0" not in _ids(failed)


def test_from_maps_plain_words_onto_the_evidence_alphabet(env):
    assert set(_ids(env.find("from:you", kinds="claim", limit=100))) == {"C_USER", "C_USER_SYS"}
    assert set(_ids(env.find("from:test", kinds="claim", limit=100))) == {"C_USER", "C_USER_SYS", "C_TEST", "C_WEB"}
    assert set(_ids(env.find("from:finished", kinds="claim", limit=100))) == {"C_LEARN"}
    assert set(_ids(env.find("from:held-up", kinds="claim", limit=100))) == {"C_SURV"}
    assert "e-goal" in _ids(env.find("from:you", kinds="moment"))                 # the same ladder on events


def test_territory_in_kind_outside_and_time_facets(env):
    assert set(_ids(env.find("territory:web", kinds="claim"))) == {"C_WEB", "C_USER", "C_USER_SYS"}
    assert _ids(env.find("territory:web search", kinds="claim")) == ["C_WEB"]
    assert env.ids["root"] in _ids(env.find("in:release", kinds="strand"))
    assert env.ids["strand"] not in _ids(env.find("in:release", kinds="strand"))
    assert _ids(env.find("kind:pin")) and {r["kind"] for r in env.find("kind:pin")["results"]} == {"pin"}
    out = env.find("outside blue pipeline", limit=100)
    assert "C_OUT" in _ids(out) and "e-out" in _ids(out) and "C_USER" not in _ids(out)      # a thread chat does not know
    day = datetime.fromtimestamp(NOW - 40 * DAY, timezone.utc).strftime("%Y-%m-%d")
    assert _ids(env.find(f"before:{day} bluebird", kinds="claim")) == []                    # before that day begins
    assert _ids(env.find(f"after:{day} bluebird", kinds="claim")) == ["C_FADE"]
    assert _ids(env.find("last week bluebird", kinds="claim")) == []                         # made 40 days ago
    assert _ids(env.find("last month bluebird", kinds="claim")) == []                        # a month is 30 days
    assert "C_USER" in _ids(env.find("last week deploy", kinds="claim"))                     # made an hour ago


def test_facets_that_exclude_each_other_say_so(env):
    d = env.find("pinned kind:claim")
    assert d["results"] == [] and any("no kind of memory" in n for n in d["notes"])
    assert env.find("")["results"] == [] and env.find("   ")["notes"]


# -- evaluation traffic -------------------------------------------------------------------------------------
def test_eval_threads_are_hidden_unless_the_eval_facet(env):
    plain = env.find("blue pipeline", limit=100)
    assert not ({"C_EVAL", "e-eval", "chain-e-0", env.ids["root"] + ":x"} & set(_ids(plain)))
    assert not any("ep-ev" in r["id"] for r in plain["results"])
    assert any("evaluation runs hidden" in n for n in plain["notes"])
    with_eval = env.find("eval blue pipeline", limit=100)
    assert {"C_EVAL", "e-eval", "chain-e-0", "eval-c1_thing-abc123:ep-ev"} <= set(_ids(with_eval))
    assert env.find("eval", kinds="strand", limit=100)["totals"]["strand"] >= 1          # the evaluation chat itself


# -- bounds -------------------------------------------------------------------------------------------------------
def test_the_big_tables_are_searched_as_a_bounded_newest_window_and_it_says_so(env, monkeypatch):
    con = sqlite3.connect(env.mem)
    for i in range(40):
        _chain(con, env.ids["root"], 100 + i, T0 - 1000 + i, f"ancient pipeline step {i}", cid=f"old-{i}")
        _ev(con, f"old-ev-{i}", T0 - 1000 + i, "GOAL_SET", env.ids["root"], family="intent", payload={"text": f"ancient pipeline {i}"})
    con.commit()
    con.close()
    # the seed holds 4 chain rows and 9 events newer than the 40 old rows each: a window of 4 reaches none of the old ones
    monkeypatch.setattr(env.sq, "SEARCH_WINDOW_STEPS", 4)
    monkeypatch.setattr(env.sq, "SEARCH_WINDOW_MOMENTS", 4)
    d = env.find("ancient pipeline", kinds="step,moment", limit=100)
    assert d["results"] == []
    assert d["searched"]["step"]["window"] == 4 and d["searched"]["step"]["read"] == 4 and d["searched"]["step"]["complete"] is False
    assert d["searched"]["moment"]["read"] == 4
    assert any(n.startswith("searched the newest 4 rows of the step log") for n in d["notes"])
    assert any(n.startswith("searched the newest 4 moments") for n in d["notes"])
    monkeypatch.setattr(env.sq, "SEARCH_WINDOW_STEPS", 6000)
    monkeypatch.setattr(env.sq, "SEARCH_WINDOW_MOMENTS", 6000)
    d = env.find("ancient pipeline", kinds="step,moment", limit=100)
    assert len(_ids(d, "step")) == 8 and d["totals"]["step"] == 40         # 8 shown, the total says how many more
    assert d["searched"]["step"]["complete"] is True and any(n.startswith("searched all") for n in d["notes"])


def test_results_are_bounded_per_kind_and_overall(env):
    con = sqlite3.connect(env.mem)
    for i in range(30):
        _claim(con, f"C_MANY{i}", f"many claims about zebras {i}", ref=env.ids["root"])
    con.commit()
    con.close()
    d = env.find("zebras", limit=100)
    assert d["shown"]["claim"] == 8 and d["totals"]["claim"] == 30 and d["per_kind"] == 8
    one = env.find("zebras", kinds="claim", limit=100)                    # one kind: up to `limit` of it
    assert len(one["results"]) == 30
    assert len(env.find("zebras", kinds="claim", limit=5)["results"]) == 5
    assert env.find("zebras", kinds="claim", limit=100000)["limit"] == env.sq.SEARCH_LIMIT_MAX
    assert env.find("zebras", kinds="claim", limit=0)["limit"] == 1
    many = env.find("blue pipeline", limit=3)
    assert len(many["results"]) == 3


def test_bad_parameters_are_400(env):
    assert env.client.get("/api/memory/search", params={"q": "x", "kinds": "claim,bogus"}).status_code == 400
    assert env.client.get("/api/memory/search", params={"q": "x" * 301}).status_code == 400


# -- a search is not a recall --------------------------------------------------------------------------------
QUERIES = ["blue pipeline", "proven", "cleaned", "from:you", "lisbon", "eval blue", "failed", "kind:step run", "last week",
           '"blue pipeline"', "territory:web", "outside", "zebra", "pinned"]


def test_a_search_writes_nothing_and_opens_only_read_only_connections(env, monkeypatch):
    opened = []
    real_connect = sqlite3.connect

    def spy(database, *a, **kw):
        opened.append((str(database), kw.get("uri", False)))
        return real_connect(database, *a, **kw)

    monkeypatch.setattr(env.sq.sqlite3, "connect", spy)
    def counters():
        con = sqlite3.connect("file:" + env.mem.as_posix() + "?mode=ro", uri=True)    # (the spy counts every connect: read-only here too)
        try:   # what a recall would move: activations, last_activated, and a RECALL_* event; plus every row count
            return (con.execute("SELECT SUM(activation_count), COUNT(last_activated) FROM mycelium_landmarks").fetchone(),
                    con.execute("SELECT COUNT(*) FROM memory_events WHERE label LIKE 'RECALL%'").fetchone()[0],
                    con.execute("SELECT COUNT(*) FROM memory_events").fetchone()[0], con.execute("SELECT COUNT(*) FROM memory_chain").fetchone()[0])
        finally:
            con.close()

    before = (_file_digest(env.mem), _file_digest(Path(env.cs._DB_PATH)), counters())
    for q in QUERIES:
        env.find(q)
    after = (_file_digest(env.mem), _file_digest(Path(env.cs._DB_PATH)), counters())
    assert opened and all(uri and database.endswith("?mode=ro") for database, uri in opened), opened
    assert before == after, "a search changed a store"
    assert before[2][0][0] > 0 and before[2][1] == 1       # the counters are live (activations seeded, one RECALL event), and did not move


def test_the_store_bytes_are_unchanged_on_disk(env):
    raw_before = env.mem.read_bytes()
    for q in QUERIES:
        env.find(q)
    assert env.mem.read_bytes() == raw_before


def test_a_search_answered_from_the_prepared_corpus_opens_no_connection(env, monkeypatch):
    monkeypatch.setattr(env.sq, "SEARCH_CORPUS_TTL_S", 60.0)
    env.sq._corpus.clear()
    env.find("blue pipeline")                                            # reads and prepares
    opened = []
    real_connect = sqlite3.connect
    monkeypatch.setattr(env.sq.sqlite3, "connect", lambda *a, **kw: opened.append(a) or real_connect(*a, **kw))
    again = env.find("blue pipeline")
    other = env.find("deploy")                                           # another word, the same prepared rows
    assert opened == [], "a keystroke re-read the store"
    assert again["results"] and other["results"]
    assert len(env.sq._corpus) <= env.sq.SEARCH_CORPUS_MAX


def test_the_corpus_cache_is_bounded(env, monkeypatch):
    monkeypatch.setattr(env.sq, "SEARCH_CORPUS_TTL_S", 60.0)
    monkeypatch.setattr(env.sq, "SEARCH_CORPUS_MAX", 3)
    env.sq._corpus.clear()
    env.find("blue pipeline")
    assert len(env.sq._corpus) == 3


# -- plans, missing tables, missing store -------------------------------------------------------------------
def test_no_statement_scans_a_big_table(env, monkeypatch):
    seen: list[tuple[str, str]] = []
    orig = env.sq.read_only

    @contextlib.contextmanager
    def traced(path):
        with orig(path) as con:
            name = Path(path).name
            con.set_trace_callback(lambda s: seen.append((name, s)) if s.lstrip().upper().startswith(("SELECT", "WITH")) else None)
            yield con

    monkeypatch.setattr(env.sq, "read_only", traced)
    for q in QUERIES:
        env.find(q)
    con = sqlite3.connect(env.mem)
    mem = [s for db, s in seen if db == env.mem.name]
    assert any("FROM memory_chain" in s for s in mem) and any("FROM memory_events" in s for s in mem)
    bad = []
    for sql in mem:
        for line in _plan_lines(con, sql):
            if re.match(r"SCAN (memory_chain|memory_events|context_chunks)\b", line):
                bad.append((line, " ".join(sql.split())[:140]))
    assert not bad, bad
    # every statement that reads a big table carries a LIMIT
    assert all("LIMIT" in s.upper() for s in mem if re.search(r"FROM (memory_chain|memory_events)", s)), mem
    con.close()


def test_store_missing_optional_tables_still_answers(env, tmp_path, monkeypatch):
    mini = tmp_path / "old_memory.db"
    con = sqlite3.connect(mini)
    con.executescript(MINIMAL_DDL)
    _chain(con, env.ids["root"], 0, NOW, "blue pipeline step")
    _ev(con, "e1", NOW, "GOAL_SET", env.ids["root"], episode="T1", family="intent")
    con.execute("INSERT INTO mycelium_landmarks (landmark_id, task_class, coordinate_cluster, traversal_sequence,"
                " cumulative_score, micro_abstract_text, created_at, tier) VALUES ('L1','c','[]','[]',0.5,'a blue claim',?, 'candidate')",
                (NOW,))
    con.commit()
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert not {"mycelium_sectors", "mycelium_pins", "pins", "document_data", "mycelium_nodes", "episodes", "mycelium_landmark_merges",
                "mycelium_episode_index"} & have
    monkeypatch.setattr(env.sq, "memory_db_path", lambda: mini)
    d = env.find("blue", limit=100)
    assert "L1" in _ids(d, "claim")
    for q in ("proven", "cleaned", "territory:web", "from:you", "lisbon", "kind:pin x", "outside", "last week"):
        env.find(q)
    for kind in ("pin", "artifact", "node", "turn"):
        info = env.find("blue", kinds=kind)["searched"][kind]
        assert info.get("available") is False or info.get("read") == 0, (kind, info)


def test_empty_store_answers(env, tmp_path, monkeypatch):
    empty = tmp_path / "empty.db"
    con = sqlite3.connect(empty)
    con.executescript(MEMORY_DDL)
    con.commit()
    con.close()
    monkeypatch.setattr(env.sq, "memory_db_path", lambda: empty)
    d = env.find("anything", limit=100)
    assert d["results"] == [] and all(v == 0 for v in d["totals"].values())


def test_missing_store_is_a_resting_503_not_a_crash(env, tmp_path, monkeypatch):
    monkeypatch.setattr(env.sq, "memory_db_path", lambda: tmp_path / "nothing.db")
    r = env.client.get("/api/memory/search", params={"q": "blue"})
    assert r.status_code == 503 and r.json()["error"] == "the memory is resting" and r.json()["ref"]


def test_the_handler_is_a_worker_thread_function_and_the_route_exists(env):
    import inspect

    routes = {r.path: r for r in env.api.router.routes}
    assert "/api/memory/search" in routes and not inspect.iscoroutinefunction(routes["/api/memory/search"].endpoint)
