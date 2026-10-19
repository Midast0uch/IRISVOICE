"""Guard (2026-10-19, W9 task B): sectors in SHADOW mode.

MEMORY-FOUNDATION-ANALYSIS 5.1. A sector is a stable text path; the 13 topic-domain
registry keys are the proven roots. Landmarks get a sector at creation (rule, then
cluster, then general), live landmarks are backfilled once, and the lifecycle
(birth, closure, split, merge with alias, dissolve) is COMPUTED and LOGGED as
SECTOR_* memory events. Nothing reads a sector. Each guard FAILS on the code
before this change (the module and the tables did not exist).
"""
import json
import os
import re
import sqlite3
import time
import uuid

import pytest

from backend.memory import event_alphabet as ea
from backend.memory.db import initialise_mycelium_schema
from backend.memory.mycelium import sectors as sx
from backend.memory.mycelium.landmark import Landmark, LandmarkIndex
from backend.utils.durability_queue import lane

T0 = 1_800_000_000.0
BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")


@pytest.fixture()
def conn():
    # Like the production Mycelium connection: usable from the memory_events lane thread.
    c = sqlite3.connect(":memory:", check_same_thread=False)
    initialise_mycelium_schema(c)
    yield c
    lane("memory_events").flush(10.0)
    c.close()


def _lm(c, label, session, *, tier="candidate", kinds=(), cluster=None, lid=None):
    lid = lid or "lm_" + uuid.uuid4().hex[:8]
    evidence = [{"kind": k, "ref": "t", "session": session, "at": T0} for k in kinds]
    c.execute(
        "INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster,"
        " traversal_sequence, cumulative_score, activation_count, is_permanent, conversation_ref,"
        " absorbed, created_at, tier, evidence) VALUES (?, ?, 'tc', ?, '[]', 0.8, 0, 0, ?, NULL, ?, ?, ?)",
        (lid, label, json.dumps(cluster or []), session, T0, tier, json.dumps(evidence)))
    c.commit()
    return lid


def _channel(c, session, channel):
    c.execute("INSERT INTO mycelium_episode_index (idx_id, episode_id, session_id, node_ids, space_ids,"
              " coordinate_hash, source_channel, created_at) VALUES (?, 'e', ?, '[]', '[]', 'h', ?, ?)",
              (uuid.uuid4().hex, session, channel, T0))
    c.commit()


def _quokkas(c, n=4, **kw):
    """n landmarks, n sessions, one shared term ("quokka"), no topic keyword: all land in general."""
    words = ["alpha", "beta", "gamma", "delta", "sigma", "omega"]
    return [_lm(c, f"quokka {words[i]}", f"s{i}", **kw) for i in range(n)]


def _run(c, **kw):
    """One lifecycle pass. The event lane commits on this shared test connection, so a
    pass starts only after the previous pass's events are written."""
    assert lane("memory_events").flush(10.0)
    return sx.run_sector_lifecycle(c, **kw)


def _sectors(c):
    return {r[0]: r[1:] for r in c.execute(
        "SELECT sector_key, status, alias_of, parent_key, depth FROM mycelium_sectors")}


def _events(c, label):
    assert lane("memory_events").flush(10.0)
    return c.execute("SELECT topic_domain, payload FROM memory_events WHERE label = ?", (label,)).fetchall()


def _sector_rows(c, lid):
    return c.execute("SELECT sector_key, weight, source FROM mycelium_landmark_sectors"
                     " WHERE landmark_id = ? ORDER BY sector_key", (lid,)).fetchall()


# -- schema, roots, labels ----------------------------------------------------------------

def test_the_store_schema_creates_the_tables_and_the_thirteen_roots(conn):
    sectors = _sectors(conn)
    assert {k for k, v in sectors.items() if v[2] is None} == set(ea_roots())
    assert all(v[0] == "proven" and v[3] == 0 for k, v in sectors.items())
    cols = {r[1] for r in conn.execute("PRAGMA table_info(mycelium_landmark_sectors)")}
    assert cols == {"landmark_id", "sector_key", "weight", "source", "created_at"}


def ea_roots():
    from backend.memory.mycelium.spaces import DOMAIN_IDS
    return DOMAIN_IDS


def test_the_five_lifecycle_labels_sit_inside_the_closed_alphabet():
    for label in ("SECTOR_BORN", "SECTOR_PROVEN", "SECTOR_SPLIT", "SECTOR_MERGED", "SECTOR_DISSOLVED"):
        spec = ea.registered_labels()[label]
        assert spec.family == "memory" and spec.valence in ea.VALENCES and spec.actor in ea.ACTORS


# -- a landmark's sector at creation: rule, cluster, general ---------------------------------

def _domain_node(c, node_id, label, confidence):
    c.execute("INSERT INTO mycelium_nodes (node_id, space_id, coordinates, label, confidence, created_at,"
              " updated_at, access_count) VALUES (?, 'domain', x'00', ?, ?, ?, ?, 1)",
              (node_id, label, confidence, T0, T0))
    c.commit()
    return {"node_id": node_id, "space_id": "domain", "confidence": confidence}


def _new_landmark(label, cluster):
    return Landmark(landmark_id="lm_" + uuid.uuid4().hex[:8], label=label, task_class="tc",
                    coordinate_cluster=cluster, traversal_sequence=[], cumulative_score=0.8,
                    micro_abstract=None, micro_abstract_text=None, activation_count=0,
                    is_permanent=False, conversation_ref="s", created_at=T0, last_activated=None)


def test_creation_rule_path_resolves_the_task_label(conn):
    lm = _new_landmark("tune the kubernetes cluster", [])
    LandmarkIndex(conn).save(lm)
    assert _sector_rows(conn, lm.landmark_id) == [("devops", 1.0, "rule")]


def test_creation_cluster_path_weights_the_domain_nodes_of_its_own_cluster(conn):
    cluster = [_domain_node(conn, "d1", "domain_hardware", 0.6),
               _domain_node(conn, "d2", "domain_finance", 0.2),
               _domain_node(conn, "d3", "domain_hardware", 0.2),
               {"node_id": "t1", "space_id": "toolpath", "confidence": 0.9}]
    lm = _new_landmark("something with no topic words", cluster)
    LandmarkIndex(conn).save(lm)
    rows = _sector_rows(conn, lm.landmark_id)
    assert [(k, s) for k, _, s in rows] == [("finance", "cluster"), ("hardware", "cluster")]
    weights = {k: w for k, w, _ in rows}
    assert weights["hardware"] == pytest.approx(0.8) and weights["finance"] == pytest.approx(0.2)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_creation_falls_back_to_general(conn):
    lm = _new_landmark("something with no topic words", [{"node_id": "t1", "space_id": "toolpath"}])
    LandmarkIndex(conn).save(lm)
    assert _sector_rows(conn, lm.landmark_id) == [("general", 1.0, "general")]


def test_the_rule_wins_over_the_cluster(conn):
    cluster = [_domain_node(conn, "d1", "domain_finance", 0.9)]
    lm = _new_landmark("debug the react frontend", cluster)
    LandmarkIndex(conn).save(lm)
    assert _sector_rows(conn, lm.landmark_id) == [("web", 1.0, "rule")]


# -- the backfill ---------------------------------------------------------------------------

def test_backfill_gives_every_live_landmark_a_sector_and_is_idempotent(conn):
    a = _lm(conn, "tune the kubernetes deploy", "s1")
    b = _lm(conn, "nothing topical here", "s2")
    c = _lm(conn, "x", "s3", cluster=[_domain_node(conn, "d9", "domain_science", 0.5)])
    gone = _lm(conn, "absorbed one", "s4")
    conn.execute("UPDATE mycelium_landmarks SET absorbed = 1 WHERE landmark_id = ?", (gone,))
    conn.commit()
    first = sx.backfill_landmark_sectors(conn)
    assert first == {"assigned": 3, "rule": 1, "cluster": 1, "general": 1}
    assert [r[0] for r in _sector_rows(conn, a)] == ["devops"]
    assert [r[0] for r in _sector_rows(conn, b)] == ["general"]
    assert [r[0] for r in _sector_rows(conn, c)] == ["science"]
    assert _sector_rows(conn, gone) == []                      # an absorbed row is not live
    before = conn.execute("SELECT COUNT(*) FROM mycelium_landmark_sectors").fetchone()[0]
    assert sx.backfill_landmark_sectors(conn)["assigned"] == 0
    assert conn.execute("SELECT COUNT(*) FROM mycelium_landmark_sectors").fetchone()[0] == before


# -- the lifecycle: computed and logged -------------------------------------------------------

def test_birth_is_logged_once_and_a_second_pass_is_silent(conn):
    ids = _quokkas(conn)
    out = _run(conn, now=T0)
    assert out["born"] == ["general/quokka"]
    assert _sectors(conn)["general/quokka"] == ("candidate", None, "general", 1)
    assert {r[0] for r in conn.execute(
        "SELECT landmark_id FROM mycelium_landmark_sectors WHERE sector_key = 'general/quokka'")} == set(ids)
    (topic, payload), = _events(conn, "SECTOR_BORN")
    assert topic == "general" and json.loads(payload)["sector"] == "general/quokka"
    again = _run(conn, now=T0 + 60)
    assert all(not again[k] for k in ("born", "proven", "split", "merged", "dissolved"))
    assert len(_events(conn, "SECTOR_BORN")) == 1


def test_a_term_in_fewer_than_three_sessions_is_not_born(conn):
    _quokkas(conn, n=2)
    assert _run(conn, now=T0)["born"] == []


def test_kyudo_a_channel_the_domain_lock_refuses_cannot_create_a_candidate(conn):
    _quokkas(conn, n=4)
    _channel(conn, "s0", 0)            # UNTRUSTED: below the domain write lock (EXTERNAL)
    _channel(conn, "s1", 0)
    assert _run(conn, now=T0)["born"] == []     # only 2 admitted sessions left


def _born_with(conn, channels, evidenced):
    ids = _quokkas(conn)
    for i, ch in enumerate(channels):
        _channel(conn, f"s{i}", ch)
    assert _run(conn, now=T0)["born"] == ["general/quokka"]
    # The event lane commits on this shared connection: let it finish before the test writes.
    assert lane("memory_events").flush(10.0)
    for i in evidenced:
        conn.execute("UPDATE mycelium_landmarks SET evidence = ? WHERE landmark_id = ?",
                     (json.dumps([{"kind": "test_pass", "session": f"s{i}"}]), ids[i]))
    conn.commit()
    return ids


def test_closure_needs_two_outside_evidenced_landmarks_from_two_sessions(conn):
    _born_with(conn, [3, 3, 3, 3], evidenced=[0, 1])
    out = _run(conn, now=T0 + 60)
    assert out["proven"] == ["general/quokka"]
    assert _sectors(conn)["general/quokka"][0] == "proven"
    (_, payload), = _events(conn, "SECTOR_PROVEN")
    assert json.loads(payload)["sessions"] == 2


def test_closure_refuses_one_evidenced_landmark(conn):
    _born_with(conn, [3, 3, 3, 3], evidenced=[0])
    assert _run(conn, now=T0 + 60)["proven"] == []


def test_kyudo_an_external_source_proposes_but_never_closes(conn):
    # The evidence sits in EXTERNAL sessions (admitted to propose, below VERIFIED to close).
    _born_with(conn, [1, 1, 1, 1], evidenced=[0, 1])
    assert _run(conn, now=T0 + 60)["proven"] == []
    assert _sectors(conn)["general/quokka"][0] == "candidate"


def test_kyudo_the_thirty_percent_cap_holds_on_a_sectors_evidence(conn):
    # 2 of 4 members (50%) are EXTERNAL: over the 30% cap, even with trusted evidence.
    _born_with(conn, [3, 3, 1, 1], evidenced=[0, 1])
    assert _run(conn, now=T0 + 60)["proven"] == []
    # Control: one of four (25%) is within the cap.
    conn.execute("UPDATE mycelium_episode_index SET source_channel = 3 WHERE session_id = 's2'")
    conn.commit()
    assert _run(conn, now=T0 + 120)["proven"] == ["general/quokka"]


def test_an_unclosed_candidate_dissolves_into_its_parent_and_the_alias_resolves(conn):
    _quokkas(conn)
    _run(conn, now=T0)
    assert _run(conn, now=T0 + sx.SECTOR_CANDIDATE_TTL_S - 1)["dissolved"] == []
    out = _run(conn, now=T0 + sx.SECTOR_CANDIDATE_TTL_S + 1)
    assert out["dissolved"] == ["general/quokka"]
    assert _sectors(conn)["general/quokka"][:2] == ("dissolved", "general")
    assert sx.resolve_sector_key(conn, "general/quokka") == "general"
    assert len(_events(conn, "SECTOR_DISSOLVED")) == 1
    assert _run(conn, now=T0 + 2 * sx.SECTOR_CANDIDATE_TTL_S)["dissolved"] == []


def test_two_sectors_with_the_same_landmarks_merge_and_the_absorbed_key_is_an_alias(conn):
    for i, w in enumerate(["one", "two", "tre", "for"]):
        _lm(conn, f"quokka marsupial {w}", f"s{i}")
    out = _run(conn, now=T0)
    assert sorted(out["born"]) == ["general/marsupial", "general/quokka"]
    assert out["merged"] == ["general/marsupial"]
    assert _sectors(conn)["general/marsupial"][:2] == ("merged", "general/quokka")
    assert sx.resolve_sector_key(conn, "general/marsupial") == "general/quokka"
    (_, payload), = _events(conn, "SECTOR_MERGED")
    assert json.loads(payload)["survivor"] == "general/quokka"


def _web_landmarks(conn, good, bad):
    for i in range(good):
        _lm(conn, f"react ok build{i}", "one-session", tier="landmark")
    for i in range(bad):
        _lm(conn, f"react flaky build{i}", "one-session", tier="demoted")


def test_a_proven_sector_whose_outcomes_disagree_splits(conn):
    _web_landmarks(conn, good=4, bad=2)        # +1 x4, -1 x2: variance 0.89 > 0.40
    out = _run(conn, now=T0)
    assert out["split"] == ["web/flaky"]
    (topic, payload), = _events(conn, "SECTOR_SPLIT")
    assert topic == "web" and json.loads(payload)["variance"] > sx.SPLIT_VARIANCE


def test_a_sector_whose_outcomes_agree_does_not_split(conn):
    _web_landmarks(conn, good=6, bad=0)
    assert _run(conn, now=T0)["split"] == []


def test_growth_has_a_budget_children_cap_and_depth(conn):
    _quokkas(conn)
    for i in range(sx.SECTOR_MAX_CHILDREN):    # the parent is full
        conn.execute("INSERT INTO mycelium_sectors (sector_key, parent_key, depth, status, created_at,"
                     " updated_at) VALUES (?, 'general', 1, 'dissolved', ?, ?)", (f"general/x{i}", T0, T0))
    conn.commit()
    assert _run(conn, now=T0)["born"] == []
    # depth: a sector already at the maximum depth has no children.
    c2 = sqlite3.connect(":memory:", check_same_thread=False)
    initialise_mycelium_schema(c2)
    deepest = "general/a/b/c"
    assert sx.SECTOR_MAX_DEPTH == 3
    c2.execute("INSERT INTO mycelium_sectors (sector_key, parent_key, depth, status, created_at, updated_at)"
               " VALUES (?, 'general/a/b', 3, 'proven', ?, ?)", (deepest, T0, T0))
    for i, lid in enumerate(_quokkas(c2)):
        c2.execute("INSERT INTO mycelium_landmark_sectors VALUES (?, ?, 2.0, 'cluster', ?)", (lid, deepest, T0))
    c2.commit()
    assert _run(c2, now=T0)["born"] == []
    c2.close()


# -- shadow: consumed by nothing ----------------------------------------------------------------

_READERS = re.compile(r"mycelium_sectors|mycelium_landmark_sectors|SECTOR_(BORN|PROVEN|SPLIT|MERGED|DISSOLVED)")
# The writer, its schema/startup wiring, and the label registry. Nothing else may name them.
_ALLOWED = {"memory/mycelium/sectors.py", "memory/db.py", "memory/event_alphabet.py"}


def _consumers(files):
    return sorted(rel for rel, text in files if _READERS.search(text) and rel not in _ALLOWED)


def _production_files():
    root = os.path.abspath(BACKEND)
    for dirpath, dirnames, names in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("tests", "__pycache__", "node_modules")]
        for name in names:
            if name.endswith(".py"):
                path = os.path.join(dirpath, name)
                yield os.path.relpath(path, root).replace(os.sep, "/"), open(path, encoding="utf-8").read()


def test_no_production_code_reads_a_sector_or_a_sector_event():
    assert _consumers(_production_files()) == []


def test_the_consumer_scan_sees_a_reader():
    assert _consumers([("agent/x.py", 'conn.execute("SELECT * FROM mycelium_sectors")')]) == ["agent/x.py"]
    assert _consumers([("agent/y.py", 'if label == "SECTOR_BORN": pass')]) == ["agent/y.py"]
