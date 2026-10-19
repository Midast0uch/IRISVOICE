"""Guards (2026-10-19): the coordinate spaces are an OPEN registry and each space
declares its WRITE LOCK (W10 + Kyudo proposal 6; MEMORY-FOUNDATION-ANALYSIS.md
§5.2, §10, §12.2 #6, §12.3).

What was wrong (code-read):
  - SPACES / _SPACE_ORDER / RENDER_ORDER / RESONANCE_SPACES / TASK_CLASS_SPACE_MAP /
    the renderer map were seven-space lists in seven places: an eighth space would
    never condense, expand, render, resonate or be navigated;
  - CellWall reused the guide's CONTEXT-WINDOW zones as WRITE permissions and failed
    OPEN: an unknown space went to REFERENCE_ZONE (any channel may write), and
    `toolpath` (what IRIS's tools did) sat in REFERENCE, so the document bridge
    filed UNTRUSTED documents into it;
  - _register_spaces was INSERT OR REPLACE: the code overwrote the table on every start.
Each guard below FAILS on the code before this change.
"""
import json
import struct
import time
import uuid

import pytest

from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.mycelium.decay import ensure_decay_columns
from backend.memory.mycelium.interface import MyceliumInterface
from backend.memory.mycelium.kyudo import (
    SUBAGENT_CHANNEL_PROFILES,
    CellWall,
    HyphaChannel,
    TaskClassifier,
)

SEVEN = ["domain", "style", "conduct", "chrono", "capability", "context", "toolpath"]
NEW = "testspace"


@pytest.fixture
def conn(mem_conn):
    ensure_decay_columns(mem_conn)   # the application store's shape (db.py)
    return mem_conn


def _add_space(conn, space_id=NEW, **terms):
    """Register a space the way a reviewed row would be added to the table."""
    from backend.memory.mycelium.registry import ensure_space_columns

    ensure_space_columns(conn)
    row = {
        "write_lock": 3,                       # USER
        "decay_rate": 0.2,
        "confidence_floor": 0.5,
        "render_order": 0,                     # before every other section
        "resonance": 1,
        "task_classes": json.dumps(["full", "code_task"]),
        "writers": json.dumps(["code_worker"]),
    }
    row.update(terms)
    cols = ", ".join(row)
    conn.execute(
        f"INSERT INTO mycelium_spaces (space_id, axes, dtype, value_range, description, {cols}) "
        f"VALUES (?, ?, 'float', '[0.0, 1.0]', 'a test space', {', '.join('?' for _ in row)})",
        (space_id, json.dumps(["a", "b", "c"]), *row.values()),
    )
    conn.commit()


def _node(conn, space, confidence, age_days=0.0):
    nid = str(uuid.uuid4())
    t = time.time() - age_days * 86400.0
    conn.execute(
        "INSERT INTO mycelium_nodes (node_id, space_id, coordinates, label, confidence,"
        " access_count, created_at, updated_at, last_accessed, source_channel)"
        " VALUES (?, ?, ?, 'n', ?, 0, ?, ?, ?, NULL)",
        (nid, space, struct.pack(">3f", 0.5, 0.5, 0.5), confidence, t, t, t),
    )
    conn.commit()
    return nid


# ── the 8th space, end to end (the DONE test) ───────────────────────────────

def test_an_eighth_space_works_end_to_end(conn, monkeypatch):
    _add_space(conn)
    mi = MyceliumInterface(conn)

    # a node upserts into it
    node = mi._store.upsert_node(NEW, [0.3, 0.4, 0.5], "first", 0.8)
    assert node.space_id == NEW

    # condense and expand visit it, after the seven (a new space is appended)
    visited = {"condense": [], "expand": []}
    for kind in visited:
        original = getattr(mi._map_manager, kind)

        def track(space_id, _kind=kind, _orig=original):
            visited[_kind].append(space_id)
            return _orig(space_id)

        monkeypatch.setattr(mi._map_manager, kind, track)
    mi._map_manager.run_condense()
    mi._map_manager.run_expand()
    assert visited["condense"] == SEVEN + [NEW]
    assert visited["expand"] == SEVEN + [NEW]

    # decay uses ITS rate and ITS floor (a legacy node: channel None -> m = 1)
    old = _node(conn, NEW, 0.9, age_days=10.0)
    ref = _node(conn, "domain", 0.9, age_days=10.0)      # the default rate, floor 0.4
    mi._scorer.apply_node_decay()
    import math
    got = conn.execute("SELECT confidence FROM mycelium_nodes WHERE node_id = ?", (old,)).fetchone()[0]
    assert got == pytest.approx(0.5 + 0.4 * math.exp(-0.2 * 10.0), abs=1e-3)
    dom = conn.execute("SELECT confidence FROM mycelium_nodes WHERE node_id = ?", (ref,)).fetchone()[0]
    assert dom == pytest.approx(0.4 + 0.5 * math.exp(-0.005 * 10.0), abs=1e-3)

    # the CellWall applies its lock (USER)
    wall = mi._cell_wall
    assert wall.can_write_space(HyphaChannel.USER, NEW) is True
    assert wall.can_write_space(HyphaChannel.SYSTEM, NEW) is True
    assert wall.can_write_space(HyphaChannel.VERIFIED, NEW) is False
    assert wall.can_write_space(HyphaChannel.EXTERNAL, NEW) is False

    # the 'full' task class includes it; the real classifier returns it
    monkeypatch.setattr(TaskClassifier, "_get_encoder", classmethod(lambda cls: None))
    text = " ".join(["please"] + ["consider"] * 30 + ["everything"])   # >=20 words, no keyword
    task_class, subset = mi._task_classifier.classify(text)
    assert task_class == "full"
    assert NEW in subset
    assert NEW in mi._spaces.spaces_for_class("code_task")
    assert NEW not in mi._spaces.spaces_for_class("quick_edit")

    # resonance participation is declared
    assert NEW in mi._spaces.resonance_spaces

    # the render order is respected: a section is written at ITS position
    mi._store.upsert_node("domain", [0.0, 0.9, 0.9], "web", 0.8)
    mi._renderer.render_dirty_sections()
    rows = dict(conn.execute("SELECT space_id, render_order FROM mycelium_profile").fetchall())
    assert rows[NEW] == 0 and rows["domain"] == 1
    sections = mi._renderer.get_readable_profile().split("\n\n")
    assert len(sections) >= 2                        # the new space AND the domain section
    assert sections[0].startswith("a test space")    # render_order 0 comes first


# ── fail closed ──────────────────────────────────────────────────────────────

def test_an_unknown_space_needs_system():
    wall = CellWall()
    assert wall.can_write_space(HyphaChannel.SYSTEM, "no_such_space") is True
    for channel in (HyphaChannel.USER, HyphaChannel.VERIFIED, HyphaChannel.EXTERNAL,
                    HyphaChannel.UNTRUSTED):
        assert wall.can_write_space(channel, "no_such_space") is False, channel.name


def test_an_unknown_or_missing_channel_counts_as_untrusted():
    wall = CellWall()
    # domain is the weakest lock (EXTERNAL = 1): UNTRUSTED (0) is still refused
    assert wall.can_write_space(HyphaChannel.UNTRUSTED, "domain") is False
    for bad in (None, 99, -1, "x"):
        assert wall.can_write_space(bad, "domain") is False, bad
    assert wall.can_write_space(HyphaChannel.EXTERNAL, "domain") is True


def test_a_row_with_no_write_lock_needs_system(conn):
    _add_space(conn, write_lock=None)
    mi = MyceliumInterface(conn)
    assert mi._cell_wall.can_write_space(HyphaChannel.USER, NEW) is False
    assert mi._cell_wall.can_write_space(HyphaChannel.SYSTEM, NEW) is True


@pytest.mark.parametrize("space,lowest", [
    ("conduct", HyphaChannel.USER),
    ("style", HyphaChannel.USER),
    ("chrono", HyphaChannel.USER),
    ("capability", HyphaChannel.SYSTEM),
    ("toolpath", HyphaChannel.SYSTEM),
    ("context", HyphaChannel.VERIFIED),
    ("domain", HyphaChannel.EXTERNAL),
])
def test_the_write_locks_of_the_seven(space, lowest):
    wall = CellWall()
    for channel in HyphaChannel:
        assert wall.can_write_space(channel, space) is (channel >= lowest), (space, channel.name)


# ── the document bridge ──────────────────────────────────────────────────────

def test_an_external_document_cannot_write_toolpath(conn):
    mi = MyceliumInterface(conn)
    mi.ingest_document_data(
        content="<html>pages</html>", trust="untrusted", session_id="s1",
        coords=[0.2, 0.2, 0.2, 0.2], label="doc",
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM mycelium_nodes WHERE space_id = 'toolpath'").fetchone()[0] == 0
    assert mi.refused_writes[("toolpath", "EXTERNAL")] == 1        # logged and counted
    # the episode index row, with its channel, is still written
    assert conn.execute(
        "SELECT source_channel FROM mycelium_episode_index WHERE session_id = 's1'"
    ).fetchone()[0] == int(HyphaChannel.EXTERNAL)


def test_a_trusted_document_still_writes_context(conn):
    mi = MyceliumInterface(conn)
    mi.ingest_document_data(
        content="spec", trust="trusted", session_id="s2", coords=[0.5, 0.5, 0.5, 0.5], label="d",
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM mycelium_nodes WHERE space_id = 'context'").fetchone()[0] == 1
    assert mi.refused_writes == {}


# ── the table is the source of truth ─────────────────────────────────────────

def test_a_row_edited_in_the_table_is_not_overwritten_by_the_seed(conn):
    MyceliumInterface(conn)                                   # first start: seeds the rows
    conn.execute(
        "UPDATE mycelium_spaces SET write_lock = 4, decay_rate = 0.123, render_order = NULL, "
        "description = 'edited by hand', task_classes = '[]' WHERE space_id = 'style'")
    conn.commit()
    mi = MyceliumInterface(conn)                              # restart
    row = conn.execute(
        "SELECT write_lock, decay_rate, render_order, description, task_classes "
        "FROM mycelium_spaces WHERE space_id = 'style'").fetchone()
    assert row == (4, 0.123, None, "edited by hand", "[]")
    assert mi._cell_wall.can_write_space(HyphaChannel.USER, "style") is False
    assert "style" not in mi._spaces.render_order
    assert mi._spaces.decay_rate("style") == pytest.approx(0.123)


def test_a_row_that_predates_the_columns_gets_the_seed_terms_once(conn):
    # the shape every store had before this change: 4 columns, nothing else
    conn.execute("INSERT INTO mycelium_spaces (space_id, axes, dtype, value_range) "
                 "VALUES ('toolpath', '[]', 'float32', '[0.0,1.0]')")
    conn.commit()
    mi = MyceliumInterface(conn)
    assert conn.execute("SELECT write_lock, decay_rate, description FROM mycelium_spaces "
                        "WHERE space_id = 'toolpath'").fetchone()[:2] == (4, 0.02)
    assert mi._cell_wall.can_write_space(HyphaChannel.EXTERNAL, "toolpath") is False


# ── the derived lists equal today's values for the seven ────────────────────

def test_the_derived_lists_equal_todays_values(conn):
    from backend.memory.mycelium import kyudo, spaces

    mi = MyceliumInterface(conn)
    reg = mi._spaces
    assert list(reg.ids) == SEVEN                                    # was scorer._SPACE_ORDER
    assert reg.render_order == {"domain": 1, "conduct": 2, "chrono": 3, "style": 4,
                                "capability": 5, "context": 6}       # was RENDER_ORDER
    six = frozenset({"domain", "conduct", "chrono", "style", "capability", "context"})
    assert reg.resonance_spaces == six                               # was RESONANCE_SPACES
    today = {
        "quick_edit":    {"conduct", "context"},
        "code_task":     {"conduct", "domain", "toolpath", "context"},
        "research_task": {"domain", "style", "context", "chrono"},
        "planning_task": {"domain", "conduct", "style", "context", "capability"},
        "full":          {"conduct", "domain", "style", "chrono", "context", "capability"},
    }
    for task_class, members in today.items():                        # was TASK_CLASS_SPACE_MAP
        assert set(reg.spaces_for_class(task_class)) == members, task_class
        assert set(kyudo.TASK_CLASS_SPACE_MAP[task_class]) == members, task_class
    # the module constants are derived from the same definitions
    assert spaces.RENDER_ORDER == reg.render_order
    assert spaces.RESONANCE_SPACES == six
    # rates and floors: conduct 0.008, toolpath 0.02, context 0.025, else 0.005; floor 0.4
    rates = {"conduct": 0.008, "toolpath": 0.02, "context": 0.025}
    for space_id in SEVEN:
        assert reg.decay_rate(space_id) == pytest.approx(rates.get(space_id, 0.005)), space_id
        assert reg.confidence_floor(space_id) == pytest.approx(0.4), space_id
    # edges: only the never-rendered (behavioural) space overrides the stored edge rate
    assert reg.edge_rate_override("toolpath") == pytest.approx(0.02)
    assert all(reg.edge_rate_override(s) is None for s in SEVEN if s != "toolpath")


def test_the_declared_writers_match_the_subagent_profiles(conn):
    mi = MyceliumInterface(conn)
    for profile, spec in SUBAGENT_CHANNEL_PROFILES.items():
        declared = {s for s in mi._spaces.ids if profile in mi._spaces.writers(s)}
        assert declared == set(spec["write"]), profile


def test_the_derived_lists_follow_the_table(conn):
    MyceliumInterface(conn)
    conn.execute("UPDATE mycelium_spaces SET render_order = 9, resonance = 0 "
                 "WHERE space_id = 'context'")
    conn.commit()
    reg = MyceliumInterface(conn)._spaces
    assert reg.render_order["context"] == 9
    assert "context" not in reg.resonance_spaces


def test_the_lock_values_are_the_hypha_channel_values():
    from backend.memory.mycelium import spaces

    assert (spaces._SYSTEM, spaces._USER, spaces._VERIFIED, spaces._EXTERNAL) == (
        int(HyphaChannel.SYSTEM), int(HyphaChannel.USER),
        int(HyphaChannel.VERIFIED), int(HyphaChannel.EXTERNAL))
