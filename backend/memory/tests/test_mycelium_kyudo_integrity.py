"""Guards (2026-10-19): the Kyudo INTEGRITY PASS - the memory cleans itself.

Owner decision: "Kyudo should NATURALLY clean up old landmarks or anything that
would interfere with the structural integrity and credibility of the memory."
Measured on a read-only copy of the live store: 97 live landmarks, 83 of them
made 41 DIFFERENT claims on a few shared clusters (the global-top-nodes bug,
c8852bb5), 6,289 landmark edges of which 2,704 pointed at absorbed landmarks,
517 episode-index rows and 45 sector rows pointed at absorbed landmarks, and
81 nodes sat at the confidence floor with no edge and no access. Nothing removed
any of it: LandmarkMerger.collapse_duplicates was not in maintenance.

The pass runs inside MyceliumInterface.run_maintenance (never the answer path).
Every guard drives run_maintenance, so each FAILS on the code before this change.
Rules: hub_cluster / dangling_cluster / no_credibility (landmarks are ABSORBED,
rows kept, reason on the row), dangling references, orphan nodes, then merge of
same-claim duplicates. Bounded per pass, counted, typed, idempotent.
"""
import json
import sqlite3
import struct
import time
import uuid

import pytest

from backend.agent import write_counters
from backend.memory import event_alphabet as ea
from backend.memory.db import initialise_mycelium_schema
from backend.memory.mycelium import integrity
from backend.memory.mycelium.interface import MyceliumInterface
from backend.memory.mycelium.landmark import ensure_landmark_policy_columns
from backend.utils.durability_queue import lane

DAY = 86400.0
FLOOR = 0.4


@pytest.fixture()
def conn():
    # Like the production Mycelium connection: usable from the memory_events lane thread.
    c = sqlite3.connect(":memory:", check_same_thread=False)
    initialise_mycelium_schema(c)
    ensure_landmark_policy_columns(c)
    yield c
    lane("memory_events").flush(10.0)
    c.close()


@pytest.fixture()
def mi(conn):
    return MyceliumInterface(conn)


# -- builders ----------------------------------------------------------------------------

_coord = iter(range(1, 10_000))


def _node(conn, *, space="toolpath", label="tool_x", confidence=FLOOR, access=0, age_days=0.0,
          channel=None):
    """A node with its own coordinates (far from every other: condense must not merge it)."""
    nid = "n_" + uuid.uuid4().hex[:8]
    k = next(_coord)
    coords = struct.pack(">4f", (k % 10) * 0.1, ((k // 10) % 10) * 0.1, (k // 100) * 0.1, 0.5)
    t = time.time() - age_days * DAY
    conn.execute(
        "INSERT INTO mycelium_nodes (node_id, space_id, coordinates, label, confidence,"
        " access_count, created_at, updated_at, last_accessed, source_channel)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (nid, space, coords, label, confidence, access, t, t, t if access else None, channel))
    conn.commit()
    return nid


def _landmark(conn, node_ids, *, task_class="claim", score=0.8, age_days=0.0, activations=0,
              tier="candidate", evidence=(), permanent=False, lid=None):
    lid = lid or "lm_" + uuid.uuid4().hex[:8]
    t = time.time() - age_days * DAY
    cluster = [{"node_id": n, "space_id": "toolpath", "coordinates": [0.1, 0.2, 0.3, 0.4],
                "confidence": 0.5, "access_count": 1} for n in node_ids]
    ev = [{"kind": k, "ref": "r", "session": s, "at": t} for k, s in evidence]
    conn.execute(
        "INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster,"
        " traversal_sequence, cumulative_score, activation_count, is_permanent, conversation_ref,"
        " absorbed, created_at, tier, evidence) VALUES (?, ?, ?, ?, '[]', ?, ?, ?, ?, NULL, ?, ?, ?)",
        (lid, task_class, task_class, json.dumps(cluster), score, activations, int(permanent),
         "sess_" + lid, t, tier, json.dumps(ev)))
    conn.commit()
    return lid


def _episodes(conn, active_days):
    """An episodes table (the application store has one) with one episode on each of the
    last ``active_days`` UTC dates: the activity clock then counts exactly that many."""
    conn.execute("CREATE TABLE IF NOT EXISTS episodes (id INTEGER PRIMARY KEY, timestamp TEXT)")
    today = time.time() // DAY * DAY
    conn.executemany(
        "INSERT INTO episodes (timestamp) VALUES (?)",
        [(time.strftime("%Y-%m-%d 12:00:00", time.gmtime(today - d * DAY)),) for d in range(active_days)])
    conn.commit()


def _absorbed(conn, lid):
    return conn.execute("SELECT absorbed FROM mycelium_landmarks WHERE landmark_id = ?", (lid,)).fetchone()[0]


def _reason(conn, lid):
    return conn.execute("SELECT falsify_if FROM mycelium_landmarks WHERE landmark_id = ?", (lid,)).fetchone()[0]


def _live(conn):
    return {r[0] for r in conn.execute("SELECT landmark_id FROM mycelium_landmarks WHERE absorbed IS NULL")}


def _events(conn, label):
    assert lane("memory_events").flush(10.0)
    return [json.loads(p) for (p,) in conn.execute(
        "SELECT payload FROM memory_events WHERE label = ?", (label,))]


def _maintain(mi):
    assert lane("memory_events").flush(10.0)   # the event lane shares this connection
    mi.run_maintenance()
    assert lane("memory_events").flush(10.0)


def _hub(conn, claims, **kw):
    """``claims`` landmarks, each a DIFFERENT claim, all on one 6-node cluster."""
    nodes = [_node(conn, space="domain", label=f"hub{i}", confidence=0.9, access=3) for i in range(6)]
    return nodes, [_landmark(conn, nodes, task_class=f"claim_{i}", **kw) for i in range(claims)]


# -- the vocabulary ------------------------------------------------------------------------

def test_the_new_event_labels_are_words_in_the_memory_family_not_new_letters():
    labels = ea.registered_labels()
    for word, valence in (("LANDMARK_DISSOLVED", "sets_back"), ("LANDMARK_MERGED", "neutral"),
                          ("MEMORY_PRUNED", "sets_back")):
        assert (labels[word].family, labels[word].valence, labels[word].actor) == ("memory", valence, "agent")
    assert ea.VALENCES == frozenset({"advances", "sets_back", "neutral"})   # the lattice is unchanged


# -- rule 1b: a place that "supports" many claims proves none --------------------------------

def test_hub_cluster_landmarks_are_absorbed_rows_kept_reason_recorded(conn, mi):
    nodes, hub = _hub(conn, 5)
    # Protected, and on the hub place (4 of its 6 nodes each) but not on each other's
    # (2 of 6 shared): the merge rule must not fold them together afterwards.
    proven = _landmark(conn, nodes[:4], task_class="claim_proven", tier="landmark",
                       evidence=[("test_pass", "s1"), ("task_complete", "s2")])
    permanent = _landmark(conn, nodes[2:], task_class="claim_permanent", permanent=True)
    own_nodes = [_node(conn, space="domain", label=f"own{i}", confidence=0.9, access=2) for i in range(3)]
    own = _landmark(conn, own_nodes, task_class="claim_own")
    total = conn.execute("SELECT COUNT(*) FROM mycelium_landmarks").fetchone()[0]
    n0 = write_counters.get("kyudo.integrity.hub_cluster")

    _maintain(mi)

    assert all(_absorbed(conn, h) == 1 for h in hub)                 # absorbed, not deleted
    assert all("| dissolved: hub_cluster" in _reason(conn, h) for h in hub)   # reason on the row
    assert _live(conn) == {proven, permanent, own}                   # proven, permanent, specific stay
    assert conn.execute("SELECT COUNT(*) FROM mycelium_landmarks").fetchone()[0] == total
    assert write_counters.get("kyudo.integrity.hub_cluster") == n0 + 5
    events = _events(conn, "LANDMARK_DISSOLVED")
    assert {e["landmark"] for e in events} == set(hub)
    assert all(e["reason"] == "hub_cluster" and e["total"] == 5 for e in events)


def test_recurrence_between_hub_landmarks_is_not_proof(conn, mi):
    """Landmarks that "recur" only because they share one hub cluster are circular."""
    nodes, hub = _hub(conn, 3)
    circular = _landmark(conn, nodes, task_class="claim_circ", tier="landmark",
                         evidence=[("recurrence", "s1"), ("recurrence", "s2")])
    _maintain(mi)
    assert _live(conn) == set()
    assert _absorbed(conn, circular) == 1


def test_one_claim_on_one_place_is_a_duplicate_and_merges_it_is_not_a_hub(conn, mi):
    nodes = [_node(conn, space="domain", label=f"d{i}", confidence=0.9, access=3) for i in range(4)]
    group = [_landmark(conn, nodes, task_class="same_claim", age_days=i) for i in range(4)]
    _maintain(mi)
    assert len(_live(conn)) == 1                                      # merged into one survivor
    assert all("dissolved" not in (_reason(conn, g) or "") for g in group)
    assert conn.execute("SELECT COUNT(*) FROM mycelium_landmark_merges").fetchone()[0] == 3
    assert {e["reason"] for e in _events(conn, "LANDMARK_MERGED")} == {"duplicate"}
    assert write_counters.get("kyudo.integrity.landmarks_merged") >= 3


def test_hub_landmarks_are_dissolved_before_duplicates_merge(conn, mi):
    """Merging first would crown one of the 41 claims and give it the others' recurrence."""
    _hub(conn, 4)
    _maintain(mi)
    assert _live(conn) == set()
    assert conn.execute("SELECT COUNT(*) FROM mycelium_landmark_merges").fetchone()[0] == 0


# -- rule 1a: coordinates that no longer exist -----------------------------------------------

def test_a_landmark_whose_nodes_are_gone_is_dissolved_one_with_most_of_them_is_not(conn, mi):
    alive = [_node(conn, space="domain", label=f"a{i}", confidence=0.9, access=2) for i in range(6)]
    gone = _landmark(conn, alive[:2] + ["n_deleted_1", "n_deleted_2", "n_deleted_3"], task_class="claim_gone")
    mostly = _landmark(conn, alive[2:5] + ["n_deleted_4"], task_class="claim_mostly")
    _maintain(mi)
    assert _absorbed(conn, gone) == 1 and "| dissolved: dangling_cluster" in _reason(conn, gone)
    assert _absorbed(conn, mostly) is None


# -- rule 2: credibility, the section 11 law on landmarks ------------------------------------

def test_an_unproven_unused_claim_loses_credibility_by_active_days_and_dissolves(conn, mi):
    _episodes(conn, 80)
    def solo(**kw):
        return _landmark(conn, [_node(conn, space="domain", label="s", confidence=0.9, access=2)],
                         task_class="c_" + uuid.uuid4().hex[:6], age_days=120, **kw)
    idle = solo(score=0.45)                              # 0.45 - 0.005 * 80 = 0.05 < 0.08
    used = solo(score=0.45, activations=3)               # a(3) = 1/4: 0.45 - 0.1 = 0.35
    proven = solo(score=0.45, tier="landmark", evidence=[("test_pass", "s1"), ("task_complete", "s2")])
    permanent = solo(score=0.45, permanent=True)
    fresh = _landmark(conn, [_node(conn, space="domain", label="f", confidence=0.9, access=2)],
                      task_class="c_fresh", score=0.45, age_days=2)
    _maintain(mi)
    assert _absorbed(conn, idle) == 1 and "| dissolved: no_credibility" in _reason(conn, idle)
    assert _live(conn) == {used, proven, permanent, fresh}


def test_credibility_counts_active_days_not_calendar_days(conn, mi):
    _episodes(conn, 10)                                  # 200 calendar days idle, 10 active
    lm = _landmark(conn, [_node(conn, space="domain", label="s", confidence=0.9, access=2)],
                   task_class="c_away", score=0.45, age_days=200)
    _maintain(mi)
    assert _absorbed(conn, lm) is None                   # 0.45 - 0.005 * 10 = 0.40


# -- rule 3: dangling references -------------------------------------------------------------

def _edge(conn, a, b, score=0.4):
    conn.execute("INSERT INTO mycelium_landmark_edges (edge_id, from_landmark_id, to_landmark_id,"
                 " score, edge_type, traversal_count, created_at) VALUES (?, ?, ?, ?, 'similarity', 0, ?)",
                 ("e_" + uuid.uuid4().hex[:8], a, b, score, time.time()))
    conn.commit()


def _episode_row(conn, lid):
    iid = "i_" + uuid.uuid4().hex[:8]
    conn.execute("INSERT INTO mycelium_episode_index (idx_id, episode_id, session_id, node_ids, space_ids,"
                 " landmark_id, coordinate_hash, created_at) VALUES (?, 'e', 's', '[]', '[]', ?, 'h', ?)",
                 (iid, lid, time.time()))
    conn.commit()
    return iid


def _sector_row(conn, lid, key="general"):
    conn.execute("INSERT OR IGNORE INTO mycelium_landmark_sectors (landmark_id, sector_key, weight,"
                 " source, created_at) VALUES (?, ?, 1.0, 'rule', ?)", (lid, key, time.time()))
    conn.commit()


def _retire(conn, lid, survivor=None):
    conn.execute("UPDATE mycelium_landmarks SET absorbed = 1 WHERE landmark_id = ?", (lid,))
    if survivor:
        conn.execute("INSERT INTO mycelium_landmark_merges VALUES (?, ?, ?, 0.9, 0.5, 0.5, 0.5, ?)",
                     ("m_" + uuid.uuid4().hex[:6], survivor, lid, time.time()))
    conn.commit()


def test_references_to_absorbed_landmarks_follow_the_merge_chain_or_are_removed(conn, mi):
    mine = lambda tag: [_node(conn, space="domain", label=tag, confidence=0.9, access=2)]   # noqa: E731
    live, other = (_landmark(conn, mine(t), task_class="c_" + t, age_days=1) for t in ("live", "other"))
    mid = _landmark(conn, mine("mid"), task_class="c_mid")
    leaf = _landmark(conn, mine("leaf"), task_class="c_leaf")
    dissolved = _landmark(conn, mine("dis"), task_class="c_dis")
    _retire(conn, mid, survivor=live)            # mid -> live
    _retire(conn, leaf, survivor=mid)            # leaf -> mid -> live (the chain)
    _retire(conn, dissolved)                     # no survivor
    _edge(conn, leaf, other, 0.42)
    _edge(conn, dissolved, other)
    _edge(conn, live, other, 0.9)
    i_leaf, i_dis = _episode_row(conn, leaf), _episode_row(conn, dissolved)
    for lid in (leaf, dissolved, live):
        _sector_row(conn, lid)

    _maintain(mi)

    edges = {(a, b): s for a, b, s in conn.execute(
        "SELECT from_landmark_id, to_landmark_id, score FROM mycelium_landmark_edges")}
    assert edges == {(live, other): 0.9}         # the leaf's edge collided with the survivor's own: dropped
    idx = dict(conn.execute("SELECT idx_id, landmark_id FROM mycelium_episode_index"))
    assert idx[i_leaf] == live and idx[i_dis] is None          # re-pointed; cleared (the row stays)
    sector_owners = {r[0] for r in conn.execute("SELECT landmark_id FROM mycelium_landmark_sectors")}
    assert sector_owners.isdisjoint({leaf, mid, dissolved}) and live in sector_owners
    n = write_counters.get
    assert n("kyudo.integrity.episode_index_repointed") >= 1 and n("kyudo.integrity.episode_index_cleared") >= 1
    assert {e["table"] for e in _events(conn, "MEMORY_PRUNED") if "table" in e} >= {
        "mycelium_landmark_edges", "mycelium_episode_index", "landmark_sector_rows"}


def test_an_edge_re_points_when_the_survivor_has_no_such_pair(conn, mi):
    mine = lambda tag: [_node(conn, space="domain", label=tag, confidence=0.9, access=2)]   # noqa: E731
    live, other, gone = (_landmark(conn, mine(t), task_class="c_" + t, age_days=1) for t in ("a", "b", "c"))
    _retire(conn, gone, survivor=live)
    _edge(conn, gone, other, 0.43)
    _maintain(mi)
    assert conn.execute("SELECT from_landmark_id, to_landmark_id, score FROM mycelium_landmark_edges"
                        ).fetchall() == [(live, other, 0.43)]


def test_node_edges_with_a_missing_endpoint_are_removed(conn, mi):
    a = _node(conn, label="ends_a", confidence=0.9, access=2)
    conn.execute("INSERT INTO mycelium_edges (edge_id, from_node_id, to_node_id, score, edge_type,"
                 " created_at) VALUES ('e_dangling', ?, 'n_missing', 0.5, 'traversal', ?)", (a, time.time()))
    conn.commit()
    _maintain(mi)
    assert conn.execute("SELECT COUNT(*) FROM mycelium_edges WHERE edge_id = 'e_dangling'").fetchone()[0] == 0


# -- rule 4: orphan nodes --------------------------------------------------------------------

def test_an_orphan_node_goes_after_n_active_days_and_each_criterion_protects(conn, mi):
    _episodes(conn, 60)
    old = 200                                            # calendar days; 60 active
    orphan = _node(conn, age_days=old)
    keeps = {
        "has an edge": _node(conn, age_days=old),
        "in a live cluster": _node(conn, age_days=old),
        "was accessed": _node(conn, age_days=old, access=1),
        "above its floor": _node(conn, age_days=old, confidence=0.9),
        "stated by the user": _node(conn, age_days=old, label="stated_style"),
        "recent": _node(conn, age_days=0.2),
    }
    other = _node(conn, age_days=0.2, access=1)
    conn.execute("INSERT INTO mycelium_edges (edge_id, from_node_id, to_node_id, score, edge_type,"
                 " created_at) VALUES ('e_keep', ?, ?, 0.5, 'traversal', ?)",
                 (keeps["has an edge"], other, time.time()))
    conn.commit()
    _landmark(conn, [keeps["in a live cluster"]], task_class="c_holds")
    total = conn.execute("SELECT COUNT(*) FROM mycelium_landmarks").fetchone()[0]

    _maintain(mi)

    ids = {r[0] for r in conn.execute("SELECT node_id FROM mycelium_nodes")}
    assert orphan not in ids
    for why, nid in keeps.items():
        assert nid in ids, f"a node {why} must stay"
    assert conn.execute("SELECT COUNT(*) FROM mycelium_landmarks").fetchone()[0] == total  # rows never deleted
    assert [e["node"] for e in _events(conn, "MEMORY_PRUNED") if "node" in e] == [orphan]


def test_an_orphan_idle_for_fewer_than_n_active_days_stays(conn, mi):
    _episodes(conn, integrity.ORPHAN_NODE_IDLE_ACTIVE_DAYS - 5)
    nid = _node(conn, age_days=200)
    _maintain(mi)
    assert conn.execute("SELECT COUNT(*) FROM mycelium_nodes WHERE node_id = ?", (nid,)).fetchone()[0] == 1


def test_dissolving_a_hub_frees_its_nodes_in_the_same_pass(conn, mi):
    """The order is the point: the nodes a dissolved landmark held are orphans next."""
    _episodes(conn, 60)
    nodes = [_node(conn, label=f"h{i}", age_days=200) for i in range(6)]
    for i in range(4):
        _landmark(conn, nodes, task_class=f"claim_{i}")
    _maintain(mi)
    assert _live(conn) == set()
    assert conn.execute("SELECT COUNT(*) FROM mycelium_nodes").fetchone()[0] == 0


# -- bounds, idempotence, the quorum ------------------------------------------------------------

def test_a_pass_is_bounded_and_the_next_pass_continues(conn, mi, monkeypatch):
    monkeypatch.setattr(integrity, "MAX_LANDMARKS_PER_PASS", 3)
    monkeypatch.setattr(integrity, "MAX_NODES_PER_PASS", 2)
    _episodes(conn, 60)
    _hub(conn, 6)
    orphans = [_node(conn, label=f"o{i}", age_days=200) for i in range(5)]
    _maintain(mi)
    assert len(_live(conn)) == 3                                      # 6 hubs, 3 per pass; none merged
    assert conn.execute("SELECT COUNT(*) FROM mycelium_landmark_merges").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM mycelium_nodes WHERE node_id IN (%s)" % ",".join("?" * 5),
                        orphans).fetchone()[0] == 3                   # 5 orphans, 2 per pass
    _maintain(mi)
    assert len(_live(conn)) == 0


def test_a_second_pass_changes_nothing(conn, mi):
    _episodes(conn, 60)
    _hub(conn, 4)
    _node(conn, age_days=200)
    keep_nodes = [_node(conn, space="domain", label=f"k{i}", confidence=0.9, access=2) for i in range(2)]
    _landmark(conn, keep_nodes, task_class="c_keep")
    _maintain(mi)

    def state():
        return [conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in (
            "mycelium_landmarks", "mycelium_landmark_edges", "mycelium_nodes", "mycelium_edges",
            "mycelium_episode_index", "mycelium_landmark_sectors")]

    before = state()
    n_events = conn.execute("SELECT COUNT(*) FROM memory_events").fetchone()[0]
    report = integrity.run_integrity_pass(conn, mi._store, mi._merger)
    assert lane("memory_events").flush(10.0)
    assert not any(report.values()), report
    assert state() == before
    assert conn.execute("SELECT COUNT(*) FROM memory_events").fetchone()[0] == n_events


def test_the_pass_steps_aside_while_a_quorum_reorganization_holds_the_graph(conn, mi):
    """Slow cleaning and emergency cleaning must not fight over one graph: while
    crystallisation is suspended (QuorumReorganization step 2) the pass does nothing,
    and it resumes when the session ends (clear_session lifts the suspension)."""
    _hub(conn, 4)
    mi._crystallisation_suspended = True
    n0 = write_counters.get("kyudo.integrity.skipped_quorum")
    _maintain(mi)
    assert len(_live(conn)) == 4
    assert write_counters.get("kyudo.integrity.skipped_quorum") == n0 + 1
    mi.clear_session("sess_x")
    assert mi._crystallisation_suspended is False
    _maintain(mi)
    assert _live(conn) == set()


def test_a_failing_rule_is_counted_and_does_not_block_the_next(conn, mi, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("references broke")

    monkeypatch.setattr(integrity, "_sweep_landmark_references", boom)
    _hub(conn, 4)
    n0 = write_counters.get("kyudo.integrity.rule_failed.references")
    _maintain(mi)
    assert write_counters.get("kyudo.integrity.rule_failed.references") == n0 + 1
    assert _live(conn) == set()                                       # rule 1 had already run
