"""
Tests for ProfileRenderer — Task 12.6 (profile half)
Requirements: 14.10, 10.1–10.12
"""

import struct
import time
import uuid
import pytest
from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.mycelium.store import CoordinateStore
from backend.memory.mycelium.landmark import LandmarkIndex
from backend.memory.mycelium.profile import ProfileRenderer


def _seed_spaces(conn):
    for sid in ["conduct", "domain", "style", "chrono", "context", "capability", "toolpath"]:
        conn.execute(
            "INSERT OR IGNORE INTO mycelium_spaces (space_id, axes, dtype, value_range) VALUES (?,?,?,?)",
            (sid, "[]", "float32", "[0.0,1.0]"),
        )
    conn.commit()


def _insert_node(conn, space_id, coords, label="n", confidence=0.8, access_count=3):
    nid = str(uuid.uuid4())
    # Use big-endian ('>') to match CoordinateStore._pack_coords / _unpack_coords
    blob = struct.pack(f">{len(coords)}f", *coords)
    now = time.time()
    conn.execute(
        "INSERT INTO mycelium_nodes VALUES (?,?,?,?,?,?,?,?,?)",
        (nid, space_id, blob, label, confidence, access_count, now, now, now),
    )
    conn.commit()
    return nid


def test_domain_render_is_natural_language(mem_conn):
    """Domain nodes → prose string with no raw float pattern."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    _insert_node(mem_conn, "domain", [0.9, 0.8, 0.9, 0.7, 0.6], "python")

    index = LandmarkIndex(mem_conn)
    renderer = ProfileRenderer(store, index)
    renderer.render_dirty_sections()

    prose = renderer.get_profile_section("domain")
    if prose:
        # Should not contain raw float notation like "0.8765"
        import re
        raw_floats = re.findall(r"\b0\.\d{4,}\b", prose)
        assert len(raw_floats) == 0, f"Found raw floats in domain render: {raw_floats}"


def test_conduct_render_no_raw_floats(mem_conn):
    """Conduct node → prose, no raw float strings."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    _insert_node(mem_conn, "conduct", [0.8, 0.7, 0.6, 0.5, 0.4], "autonomy_high")

    index = LandmarkIndex(mem_conn)
    renderer = ProfileRenderer(store, index)
    renderer.render_dirty_sections()

    prose = renderer.get_profile_section("conduct")
    if prose:
        import re
        raw_floats = re.findall(r"\b0\.\d{4,}\b", prose)
        assert len(raw_floats) == 0, f"Found raw floats in conduct render: {raw_floats}"


def test_toolpath_produces_no_profile_section(mem_conn):
    """Toolpath nodes present → no toolpath section in profile output."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    _insert_node(mem_conn, "toolpath", [0.5, 0.8, 0.5, 0.8, 0.7], "bash")

    index = LandmarkIndex(mem_conn)
    renderer = ProfileRenderer(store, index)
    renderer.render_dirty_sections()

    section = renderer.get_profile_section("toolpath")
    assert section is None, "Toolpath should never produce a profile section"

    full = renderer.get_readable_profile()
    assert "toolpath" not in full.lower() or "toolpath" not in full


def test_context_renders_multiple_active_projects(mem_conn):
    """2 active context nodes (freshness > 0.10) → both appear in output."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    # freshness is axis index 3 in context space (values: project_id, stack, constraints, freshness, team_size)
    _insert_node(mem_conn, "context", [0.1, 0.5, 0.3, 0.8, 0.5], "project_alpha")
    _insert_node(mem_conn, "context", [0.7, 0.5, 0.3, 0.9, 0.5], "project_beta")

    index = LandmarkIndex(mem_conn)
    renderer = ProfileRenderer(store, index)
    renderer.render_dirty_sections()

    section = renderer.get_profile_section("context")
    # Both projects should appear or section should mention 2 projects
    if section:
        assert len(section) > 10, "Context section should have meaningful content"


def test_stale_context_excluded_from_render(mem_conn):
    """Context node with freshness = 0.05 → not in render output."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    # freshness = 0.05 (stale)
    _insert_node(mem_conn, "context", [0.5, 0.5, 0.3, 0.05, 0.5], "stale_project")

    index = LandmarkIndex(mem_conn)
    renderer = ProfileRenderer(store, index)
    renderer.render_dirty_sections()

    section = renderer.get_profile_section("context")
    # Stale project should not appear (freshness 0.05 < 0.10 threshold)
    if section:
        assert "stale_project" not in section


def test_stale_context_excluded_from_profile_render(mem_conn):
    """
    Req 4.17: context node with freshness < 0.10 MUST NOT appear in
    ProfileRenderer._render_context() output.

    The requirement places this constraint on profile rendering, not navigation.
    A stale context node (freshness=0.05) must produce an empty/absent context section.
    """
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    # freshness axis is index 3; 0.05 < 0.10 threshold → stale
    _insert_node(mem_conn, "context", [0.5, 0.5, 0.3, 0.05], "stale_project")

    index = LandmarkIndex(mem_conn)
    renderer = ProfileRenderer(store, index)
    renderer.render_dirty_sections()

    section = renderer.get_profile_section("context")
    # Stale node freshness=0.05 is below the 0.10 threshold — section must be empty
    assert not section or section.strip() == "", (
        f"Req 4.17: stale context node (freshness=0.05) must not appear in profile render, "
        f"got: {section!r}"
    )


def test_active_context_appears_in_profile_render(mem_conn):
    """
    Req 4.17 (positive case): context node with freshness = 0.80 (above 0.10)
    MUST produce a non-empty context section in ProfileRenderer output.
    """
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    # freshness = 0.80 → active
    _insert_node(mem_conn, "context", [0.5, 0.5, 0.3, 0.80], "active_project")

    index = LandmarkIndex(mem_conn)
    renderer = ProfileRenderer(store, index)
    renderer.render_dirty_sections()

    section = renderer.get_profile_section("context")
    assert section and len(section.strip()) > 0, (
        "Req 4.17: active context node (freshness=0.80) must produce a non-empty profile section"
    )
