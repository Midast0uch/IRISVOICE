"""Guards (2026-10-19): growth and decay are ONE law, and the reorganization is
that law, faster (mycelium/decay.py; MEMORY-FOUNDATION-ANALYSIS.md §11; the
Kyudo Layer Guide, Parts 3-4).

What was wrong (code-read + live store, read-only):
  - decay subtracted the WHOLE idle time again on every pass (compounded);
  - growth is weighted by the evidence (1/(1+n)), decay was not: a route with
    100 proofs used once a day still lost score every day;
  - nodes carried no Kyudo channel, so a web document decayed like the user's
    own words and entered at confidence 0.8; the 30% trust cap never ran;
  - nothing decayed node confidence, so repetition only ever ratcheted it up;
  - the quorum reorganization decayed EVERY edge by its own rule, never nodes,
    never re-rendered the profile (wrong attribute), never logged (wrong
    columns: 0 conflict rows ever); the threat level never faded; the
    crystallisation suspension never ended.
Each guard below FAILS on the code before this change.
"""
import struct
import time
import uuid

import pytest

from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.mycelium.decay import ensure_decay_columns
from backend.memory.mycelium.interface import MyceliumInterface
from backend.memory.mycelium.kyudo import QUORUM_DECAY_MULTIPLIER, QuorumReorganization
from backend.memory.mycelium.scorer import EdgeScorer
from backend.memory.mycelium.store import CoordinateStore

DAY = 86400.0


@pytest.fixture
def conn(mem_conn):
    ensure_decay_columns(mem_conn)   # the application store's shape (db.py)
    return mem_conn


def _node(conn, space="domain", channel=None, confidence=0.7, age_days=0.0):
    nid = str(uuid.uuid4())
    t = time.time() - age_days * DAY
    conn.execute(
        "INSERT INTO mycelium_nodes (node_id, space_id, coordinates, label, confidence,"
        " access_count, created_at, updated_at, last_accessed, source_channel)"
        " VALUES (?, ?, ?, 'n', ?, 0, ?, ?, ?, ?)",
        (nid, space, struct.pack(">4f", 0.5, 0.5, 0.5, 0.5), confidence, t, t, t, channel),
    )
    conn.commit()
    return nid


def _edge(conn, a, b, score=0.5, rate=0.01, idle_days=10.0, n=0):
    eid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO mycelium_edges (edge_id, from_node_id, to_node_id, score, edge_type,"
        " decay_rate, created_at, last_traversed, observation_count)"
        " VALUES (?, ?, ?, ?, 'traversal', ?, ?, ?, ?)",
        (eid, a, b, score, rate, time.time(), time.time() - idle_days * DAY, n),
    )
    conn.commit()
    return eid


def _score(conn, eid):
    return conn.execute("SELECT score FROM mycelium_edges WHERE edge_id = ?", (eid,)).fetchone()[0]


def _conf(conn, nid):
    return conn.execute("SELECT confidence FROM mycelium_nodes WHERE node_id = ?", (nid,)).fetchone()[0]


# ── the law ──────────────────────────────────────────────────────────────────

def test_an_idle_span_is_counted_once(conn):
    e = _edge(conn, _node(conn), _node(conn))
    scorer = EdgeScorer(CoordinateStore(conn))
    scorer.apply_decay()
    scorer.apply_decay()                     # a second pass, no time in between
    assert _score(conn, e) == pytest.approx(0.40, abs=1e-3)   # 0.5 - 0.01 * 10, once


def test_decay_carries_the_same_evidence_weight_as_growth(conn):
    fresh = _edge(conn, _node(conn), _node(conn), n=0)
    proven = _edge(conn, _node(conn), _node(conn), n=9)
    EdgeScorer(CoordinateStore(conn)).apply_decay()
    assert 0.5 - _score(conn, fresh) == pytest.approx(0.10, abs=1e-3)
    assert 0.5 - _score(conn, proven) == pytest.approx(0.01, abs=1e-3)   # 1/(1+9)


@pytest.mark.parametrize("n", [0, 50])
def test_a_route_used_often_enough_grows_at_any_age(conn, n):
    # toolpath: hit +0.05, decay 0.02/day -> one hit a day keeps growing,
    # for a young AND an old route (f* = rate / delta, not a function of n).
    e = _edge(conn, _node(conn, "toolpath"), _node(conn, "toolpath"), idle_days=0.0, n=n)
    scorer = EdgeScorer(CoordinateStore(conn))
    before = _score(conn, e)
    scorer.record_outcome([e], "hit")
    conn.execute("UPDATE mycelium_edges SET last_traversed = ? WHERE edge_id = ?",
                 (time.time() - DAY, e))
    conn.commit()
    scorer.apply_decay()
    assert _score(conn, e) > before


def test_a_weak_source_fades_faster(conn):
    user = _edge(conn, _node(conn, channel=3), _node(conn, channel=3))
    web = _edge(conn, _node(conn, channel=1), _node(conn, channel=3))   # weakest end
    EdgeScorer(CoordinateStore(conn)).apply_decay()
    assert (0.5 - _score(conn, web)) == pytest.approx(3.0 * (0.5 - _score(conn, user)), rel=1e-3)


# ── node confidence: the counterpart of accumulation ─────────────────────────

def test_unrepeated_confidence_falls_back_to_the_stated_value(conn):
    nid = _node(conn, confidence=0.7, age_days=30.0)
    stated = _node(conn, confidence=0.4, age_days=30.0)
    scorer = EdgeScorer(CoordinateStore(conn))
    scorer.apply_node_decay()
    once = _conf(conn, nid)
    scorer.apply_node_decay()
    assert 0.4 < once < 0.7
    assert _conf(conn, nid) == pytest.approx(once, abs=1e-9)   # counted once
    assert _conf(conn, stated) == pytest.approx(0.4)          # what was stated stays


# ── Kyudo channels ───────────────────────────────────────────────────────────

def test_one_external_observation_cannot_carry_high_confidence(conn):
    node = CoordinateStore(conn).upsert_node("context", [0.1, 0.2, 0.3, 1.0], "doc", 0.8, channel=1)
    assert node.confidence == pytest.approx(0.30)
    assert conn.execute("SELECT source_channel FROM mycelium_nodes WHERE node_id = ?",
                        (node.node_id,)).fetchone()[0] == 1


def test_a_trusted_reconfirmation_earns_the_node_its_channel(conn):
    store = CoordinateStore(conn)
    a = store.upsert_node("domain", [0.5, 0.5, 0.5], "x", 0.3, channel=1)
    store.upsert_node("domain", [0.5, 0.5, 0.5], "x", 0.4, channel=3)
    assert conn.execute("SELECT source_channel FROM mycelium_nodes WHERE node_id = ?",
                        (a.node_id,)).fetchone()[0] == 3


def test_the_trust_cap_runs_on_the_cluster_itself(conn):
    from backend.memory.mycelium.landmark import LandmarkCondenser

    store = CoordinateStore(conn)
    ids = [_node(conn, channel=1) for _ in range(2)] + [_node(conn, channel=3)]
    cluster = [store.get_node_by_id(i) for i in ids]
    assert LandmarkCondenser(store)._cluster_untrusted_fraction(cluster) == pytest.approx(2 / 3)


# ── the reorganization: the same law, faster, on what is suspect ─────────────

def test_the_reorganization_strips_new_growth_and_spares_proven_memory(conn):
    mi = MyceliumInterface(conn)
    new = _edge(conn, _node(conn), _node(conn), idle_days=0.0, n=0)
    proven = _edge(conn, _node(conn), _node(conn), idle_days=0.0, n=50)
    old = _edge(conn, _node(conn), _node(conn), idle_days=10.0, n=0)
    QuorumReorganization().fire(mi, "sess-q")
    assert 0.5 - _score(conn, new) == pytest.approx(0.01 * QUORUM_DECAY_MULTIPLIER, abs=1e-3)
    assert 0.5 - _score(conn, proven) < (0.5 - _score(conn, new)) / 10
    assert _score(conn, old) == pytest.approx(0.5)            # outside the suspect window


def test_the_reorganization_lowers_suspect_node_confidence(conn):
    mi = MyceliumInterface(conn)
    fresh = _node(conn, confidence=0.8, age_days=0.0)
    QuorumReorganization().fire(mi, "sess-q")
    assert 0.4 < _conf(conn, fresh) < 0.8


def test_the_reorganization_is_logged_and_re_renders_the_profile(conn):
    mi = MyceliumInterface(conn)
    rendered = []
    mi._renderer.render_dirty_sections = lambda: rendered.append(True)
    QuorumReorganization().fire(mi, "sess-q")
    assert rendered == [True]
    assert conn.execute(
        "SELECT COUNT(*) FROM mycelium_conflicts WHERE resolution_basis = 'quorum_reorganization'"
    ).fetchone()[0] == 1


# ── the immune memory ────────────────────────────────────────────────────────

def test_an_isolated_anomaly_fades_after_clean_sessions(conn):
    mi = MyceliumInterface(conn)
    mi.record_anomaly("sess-a", "update_velocity_anomaly")      # 0.20
    mi.clear_session("sess-a")                                 # signalled: no fade
    assert mi._quorum_sensor.threat_level == pytest.approx(0.20)
    mi.clear_session("sess-b")                                 # clean
    assert mi._quorum_sensor.threat_level == pytest.approx(0.15)


def test_the_crystallisation_suspension_ends_with_the_session(conn):
    mi = MyceliumInterface(conn)
    QuorumReorganization().fire(mi, "sess-q")
    assert mi._crystallisation_suspended is True
    mi.clear_session("sess-q")
    assert mi._crystallisation_suspended is False


# ── the Caducean phase over the span ─────────────────────────────────────────

def _trajectory(conn, us):
    conn.execute("CREATE TABLE IF NOT EXISTS caducean_trajectories "
                 "(id INTEGER PRIMARY KEY, ts REAL, session_id TEXT, u REAL)")
    t = time.time() - DAY
    conn.executemany("INSERT INTO caducean_trajectories (ts, session_id, u) VALUES (?, 's', ?)",
                     [(t + i, u) for i, u in enumerate(us)])
    conn.commit()


@pytest.mark.parametrize("us, factor", [
    ([0.6, 0.4], 0.5),            # expanding: preserve
    ([-0.6, -0.4], 1.8),          # compressing: prune
    ([0.6, -0.4], (0.5 + 1.8) / 2),
])
def test_the_span_phase_changes_how_fast_memory_fades(conn, us, factor):
    # The scorer asked the STORE for get_latest_u (only the interface has it),
    # so the phase was 1.0 on every pass. It is the time-mean of the steps'
    # multipliers over the decayed span.
    _trajectory(conn, us)
    e = _edge(conn, _node(conn), _node(conn))
    EdgeScorer(CoordinateStore(conn)).apply_decay()
    assert 0.5 - _score(conn, e) == pytest.approx(0.10 * factor, abs=1e-3)


# ── the activity clock (owner decision 2026-10-19, §11.4) ────────────────────

def _episodes(conn, days_ago):
    """An episodes table (the application store has one) with an episode on
    each of the given days (UTC noon)."""
    conn.execute("CREATE TABLE IF NOT EXISTS episodes (id INTEGER PRIMARY KEY, timestamp TEXT)")
    today = time.time() // DAY * DAY
    conn.executemany(
        "INSERT INTO episodes (timestamp) VALUES (?)",
        [(time.strftime("%Y-%m-%d 12:00:00", time.gmtime(today - d * DAY)),) for d in days_ago],
    )
    conn.commit()


def test_an_away_month_forgets_nothing(conn):
    _episodes(conn, [30, 30, 31])                 # activity only up to the last use
    e = _edge(conn, _node(conn), _node(conn), idle_days=30.0)
    EdgeScorer(CoordinateStore(conn)).apply_decay()
    assert _score(conn, e) == pytest.approx(0.5)


def test_decay_counts_the_days_the_memory_was_in_use(conn):
    _episodes(conn, [9, 9, 9, 5, 1])              # three active days after the last use
    e = _edge(conn, _node(conn), _node(conn), idle_days=10.0)
    EdgeScorer(CoordinateStore(conn)).apply_decay()
    assert 0.5 - _score(conn, e) == pytest.approx(0.03, abs=1e-6)


def test_no_activity_at_all_means_nothing_decays(conn):
    _episodes(conn, [])
    e = _edge(conn, _node(conn), _node(conn), idle_days=10.0)
    nid = _node(conn, confidence=0.7, age_days=10.0)
    scorer = EdgeScorer(CoordinateStore(conn))
    scorer.apply_decay()
    scorer.apply_node_decay()
    assert _score(conn, e) == pytest.approx(0.5)
    assert _conf(conn, nid) == pytest.approx(0.7)


def test_node_confidence_runs_on_the_same_clock(conn):
    from backend.memory.mycelium.decay import NODE_DECAY_RATE_DEFAULT, node_confidence_after

    _episodes(conn, [20, 2])                      # one active day after the last touch
    nid = _node(conn, confidence=0.7, age_days=20.0)
    EdgeScorer(CoordinateStore(conn)).apply_node_decay()
    assert _conf(conn, nid) == pytest.approx(
        node_confidence_after(0.7, NODE_DECAY_RATE_DEFAULT, 1.0, 1.0), abs=1e-9)
