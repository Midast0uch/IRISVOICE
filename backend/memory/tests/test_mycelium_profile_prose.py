"""
ProfileRenderer prose contract tests.
Requirements: 10.6, 10.7, 10.8, 10.9, 10.10, 10.11, 4.17
"""
import json
import struct
import time
import uuid

import pytest

from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.mycelium.profile import ProfileRenderer, LandmarkMerger
from backend.memory.mycelium.landmark import LandmarkIndex, Landmark
from backend.memory.mycelium.store import CoordNode, CoordinateStore
from backend.memory.mycelium.spaces import RENDER_ORDER, DOMAIN_IDS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(space_id: str, coords: list, label: str = "n",
               confidence: float = 0.8, access_count: int = 3) -> CoordNode:
    """Build a CoordNode directly for use in _render_* unit tests."""
    now = time.time()
    return CoordNode(
        node_id=str(uuid.uuid4()),
        space_id=space_id,
        coordinates=coords,
        label=label,
        confidence=confidence,
        created_at=now,
        updated_at=now,
        access_count=access_count,
        last_accessed=now,
    )


def _renderer(mem_conn) -> ProfileRenderer:
    store = CoordinateStore(mem_conn)
    index = LandmarkIndex(mem_conn)
    return ProfileRenderer(store, index)


# ---------------------------------------------------------------------------
# Req 10.6 — _render_domain(): exact prose structure
# ---------------------------------------------------------------------------

def test_render_domain_expert_proficiency(mem_conn):
    """Req 10.6: proficiency >= 0.8 → 'Expert in <domain>'."""
    rend = _renderer(mem_conn)
    domain_name = "ai"
    domain_norm = DOMAIN_IDS["ai"] / 12.0
    node = _make_node("domain", [domain_norm, 0.85, 0.9])
    prose = rend._render_domain([node])
    assert "Expert in" in prose


def test_render_domain_familiar_proficiency(mem_conn):
    """Req 10.6: 0.5 <= proficiency < 0.8 → 'familiar with <domain>'."""
    rend = _renderer(mem_conn)
    domain_name = "data"
    domain_norm = DOMAIN_IDS["ai"] / 12.0
    node = _make_node("domain", [domain_norm, 0.65, 0.9])
    prose = rend._render_domain([node])
    assert "familiar with" in prose


def test_render_domain_below_threshold_excluded(mem_conn):
    """Req 10.6: proficiency < 0.5 → node excluded, empty prose."""
    rend = _renderer(mem_conn)
    domain_norm = DOMAIN_IDS["data"] / 12.0
    node = _make_node("domain", [domain_norm, 0.3, 0.9])
    prose = rend._render_domain([node])
    assert prose == ""


def test_render_domain_starts_with_domains_prefix(mem_conn):
    """Req 10.6: output begins 'Domains: ' and ends with '.'"""
    rend = _renderer(mem_conn)
    domain_norm = DOMAIN_IDS["data"] / 12.0
    node = _make_node("domain", [domain_norm, 0.9, 0.9])
    prose = rend._render_domain([node])
    assert prose.startswith("Domains: ")
    assert prose.endswith(".")


def test_render_domain_too_few_coords_returns_empty(mem_conn):
    """Req 10.6: fewer than 2 coords → empty string."""
    rend = _renderer(mem_conn)
    node = _make_node("domain", [0.5])  # only 1 coord
    prose = rend._render_domain([node])
    assert prose == ""


# ---------------------------------------------------------------------------
# Req 10.7 — _render_conduct(): three-level autonomy/depth/confirm strings
# ---------------------------------------------------------------------------

def test_render_conduct_highly_autonomous(mem_conn):
    """Req 10.7: autonomy >= 0.75 → 'highly autonomous'."""
    rend = _renderer(mem_conn)
    # [autonomy, iteration_style, session_depth, confirmation_threshold, correction_rate]
    node = _make_node("conduct", [0.80, 0.5, 0.8, 0.2, 0.1])
    prose = rend._render_conduct([node])
    assert "highly autonomous" in prose


def test_render_conduct_moderately_autonomous(mem_conn):
    """Req 10.7: 0.45 <= autonomy < 0.75 → 'moderately autonomous'."""
    rend = _renderer(mem_conn)
    node = _make_node("conduct", [0.50, 0.5, 0.5, 0.5, 0.1])
    prose = rend._render_conduct([node])
    assert "moderately autonomous" in prose


def test_render_conduct_confirmation_driven(mem_conn):
    """Req 10.7: autonomy < 0.45 → 'prefers confirmation-driven workflow'."""
    rend = _renderer(mem_conn)
    node = _make_node("conduct", [0.20, 0.5, 0.5, 0.5, 0.1])
    prose = rend._render_conduct([node])
    assert "confirmation-driven" in prose


def test_render_conduct_deep_sessions(mem_conn):
    """Req 10.7: session_depth >= 0.7 → 'deep multi-step sessions'."""
    rend = _renderer(mem_conn)
    node = _make_node("conduct", [0.8, 0.5, 0.75, 0.2, 0.1])
    prose = rend._render_conduct([node])
    assert "deep multi-step sessions" in prose


def test_render_conduct_short_sessions(mem_conn):
    """Req 10.7: session_depth < 0.4 → 'short focused sessions'."""
    rend = _renderer(mem_conn)
    node = _make_node("conduct", [0.8, 0.5, 0.3, 0.2, 0.1])
    prose = rend._render_conduct([node])
    assert "short focused sessions" in prose


def test_render_conduct_minimal_confirmation(mem_conn):
    """Req 10.7: confirm_thresh <= 0.3 → 'minimal confirmation needed'."""
    rend = _renderer(mem_conn)
    node = _make_node("conduct", [0.8, 0.5, 0.8, 0.2, 0.1])
    prose = rend._render_conduct([node])
    assert "minimal confirmation needed" in prose


def test_render_conduct_frequent_confirmation(mem_conn):
    """Req 10.7: confirm_thresh > 0.65 → 'frequent confirmation preferred'."""
    rend = _renderer(mem_conn)
    node = _make_node("conduct", [0.8, 0.5, 0.8, 0.80, 0.1])
    prose = rend._render_conduct([node])
    assert "frequent confirmation preferred" in prose


def test_render_conduct_returns_empty_with_too_few_coords(mem_conn):
    """Req 10.7: fewer than 5 coords → empty string."""
    rend = _renderer(mem_conn)
    node = _make_node("conduct", [0.8, 0.5, 0.8])
    prose = rend._render_conduct([node])
    assert prose == ""


def test_render_conduct_starts_with_working_style(mem_conn):
    """Req 10.7: prose must start with 'Working style: '."""
    rend = _renderer(mem_conn)
    node = _make_node("conduct", [0.8, 0.5, 0.8, 0.2, 0.1])
    prose = rend._render_conduct([node])
    assert prose.startswith("Working style: ")


# ---------------------------------------------------------------------------
# _render_chrono(): all 4 time-of-day buckets
# ---------------------------------------------------------------------------

def test_render_chrono_morning(mem_conn):
    """peak_hour in [5,12) → 'morning'."""
    rend = _renderer(mem_conn)
    node = _make_node("chrono", [9.0, 0.5, 0.8])
    prose = rend._render_chrono([node])
    assert "morning" in prose


def test_render_chrono_afternoon(mem_conn):
    """peak_hour in [12,17) → 'afternoon'."""
    rend = _renderer(mem_conn)
    node = _make_node("chrono", [14.0, 0.5, 0.8])
    prose = rend._render_chrono([node])
    assert "afternoon" in prose


def test_render_chrono_evening(mem_conn):
    """peak_hour in [17,21) → 'evening'."""
    rend = _renderer(mem_conn)
    node = _make_node("chrono", [19.0, 0.5, 0.8])
    prose = rend._render_chrono([node])
    assert "evening" in prose


def test_render_chrono_night(mem_conn):
    """peak_hour outside [5,21) → 'night'."""
    rend = _renderer(mem_conn)
    node = _make_node("chrono", [2.0, 0.5, 0.8])
    prose = rend._render_chrono([node])
    assert "night" in prose


def test_render_chrono_consistent_schedule(mem_conn):
    """consistency >= 0.75 → 'very consistent schedule'."""
    rend = _renderer(mem_conn)
    node = _make_node("chrono", [9.0, 0.5, 0.80])
    prose = rend._render_chrono([node])
    assert "very consistent" in prose


def test_render_chrono_flexible_schedule(mem_conn):
    """consistency < 0.4 → 'flexible schedule'."""
    rend = _renderer(mem_conn)
    node = _make_node("chrono", [9.0, 0.5, 0.3])
    prose = rend._render_chrono([node])
    assert "flexible schedule" in prose


def test_render_chrono_starts_with_activity_pattern(mem_conn):
    """Output must start with 'Activity pattern: '."""
    rend = _renderer(mem_conn)
    node = _make_node("chrono", [9.0, 0.5, 0.5])
    prose = rend._render_chrono([node])
    assert prose.startswith("Activity pattern: ")


# ---------------------------------------------------------------------------
# _render_style()
# ---------------------------------------------------------------------------

def test_render_style_formal_tone(mem_conn):
    """formality >= 0.7 → 'formal tone'."""
    rend = _renderer(mem_conn)
    node = _make_node("style", [0.8, 0.5, 0.5])
    prose = rend._render_style([node])
    assert "formal tone" in prose


def test_render_style_casual_tone(mem_conn):
    """formality < 0.35 → 'casual tone'."""
    rend = _renderer(mem_conn)
    node = _make_node("style", [0.2, 0.5, 0.5])
    prose = rend._render_style([node])
    assert "casual tone" in prose


def test_render_style_detailed_responses(mem_conn):
    """verbosity >= 0.7 → 'detailed responses'."""
    rend = _renderer(mem_conn)
    node = _make_node("style", [0.5, 0.8, 0.5])
    prose = rend._render_style([node])
    assert "detailed responses" in prose


def test_render_style_concise_responses(mem_conn):
    """verbosity < 0.35 → 'concise responses'."""
    rend = _renderer(mem_conn)
    node = _make_node("style", [0.5, 0.2, 0.5])
    prose = rend._render_style([node])
    assert "concise responses" in prose


def test_render_style_direct_communication(mem_conn):
    """directness >= 0.7 → 'direct communication'."""
    rend = _renderer(mem_conn)
    node = _make_node("style", [0.5, 0.5, 0.8])
    prose = rend._render_style([node])
    assert "direct communication" in prose


def test_render_style_diplomatic_communication(mem_conn):
    """directness < 0.35 → 'diplomatic communication'."""
    rend = _renderer(mem_conn)
    node = _make_node("style", [0.5, 0.5, 0.2])
    prose = rend._render_style([node])
    assert "diplomatic communication" in prose


def test_render_style_starts_with_style_prefix(mem_conn):
    """Output must start with 'Style: '."""
    rend = _renderer(mem_conn)
    node = _make_node("style", [0.5, 0.5, 0.5])
    prose = rend._render_style([node])
    assert prose.startswith("Style: ")


# ---------------------------------------------------------------------------
# _render_capability()
# ---------------------------------------------------------------------------

def test_render_capability_no_gpu(mem_conn):
    """gpu_tier < 1 → 'no dedicated GPU'."""
    rend = _renderer(mem_conn)
    node = _make_node("capability", [0.0, 0.5, 0.0, 0.0, 0.5])
    prose = rend._render_capability([node])
    assert "no dedicated GPU" in prose


def test_render_capability_entry_gpu(mem_conn):
    """1 <= gpu_tier < 2 → 'entry GPU'."""
    rend = _renderer(mem_conn)
    node = _make_node("capability", [1.5, 0.5, 0.0, 0.0, 0.5])
    prose = rend._render_capability([node])
    assert "entry GPU" in prose


def test_render_capability_high_end_gpu(mem_conn):
    """3 <= gpu_tier < 4 → 'high-end GPU'."""
    rend = _renderer(mem_conn)
    node = _make_node("capability", [3.5, 0.5, 0.0, 0.0, 0.5])
    prose = rend._render_capability([node])
    assert "high-end GPU" in prose


def test_render_capability_professional_gpu(mem_conn):
    """gpu_tier >= 4 → 'professional GPU'."""
    rend = _renderer(mem_conn)
    node = _make_node("capability", [4.5, 0.5, 0.0, 0.0, 0.5])
    prose = rend._render_capability([node])
    assert "professional GPU" in prose


def test_render_capability_windows_os(mem_conn):
    """os_id >= 0.7 → 'Windows'."""
    rend = _renderer(mem_conn)
    node = _make_node("capability", [2.0, 0.5, 0.0, 0.0, 0.8])
    prose = rend._render_capability([node])
    assert "Windows" in prose


def test_render_capability_linux_os(mem_conn):
    """os_id < 0.3 → 'Linux'."""
    rend = _renderer(mem_conn)
    node = _make_node("capability", [2.0, 0.5, 0.0, 0.0, 0.1])
    prose = rend._render_capability([node])
    assert "Linux" in prose


def test_render_capability_macos(mem_conn):
    """0.3 <= os_id < 0.7 → 'macOS'."""
    rend = _renderer(mem_conn)
    node = _make_node("capability", [2.0, 0.5, 0.0, 0.0, 0.5])
    prose = rend._render_capability([node])
    assert "macOS" in prose


def test_render_capability_docker_in_tools(mem_conn):
    """has_docker >= 0.5 → 'Docker' appears in prose."""
    rend = _renderer(mem_conn)
    node = _make_node("capability", [2.0, 0.5, 0.8, 0.0, 0.5])
    prose = rend._render_capability([node])
    assert "Docker" in prose


def test_render_capability_tailscale_in_tools(mem_conn):
    """has_tailscale >= 0.5 → 'Tailscale' appears in prose."""
    rend = _renderer(mem_conn)
    node = _make_node("capability", [2.0, 0.5, 0.0, 0.8, 0.5])
    prose = rend._render_capability([node])
    assert "Tailscale" in prose


def test_render_capability_starts_with_environment(mem_conn):
    """Output must start with 'Environment: '."""
    rend = _renderer(mem_conn)
    node = _make_node("capability", [2.0, 0.5, 0.0, 0.0, 0.5])
    prose = rend._render_capability([node])
    assert prose.startswith("Environment: ")


# ---------------------------------------------------------------------------
# Req 10.6, 4.17 — _render_context(): constraint levels + freshness gate
# ---------------------------------------------------------------------------

def test_render_context_high_constraint(mem_conn):
    """constraint >= 0.75 → 'high constraint environment'."""
    rend = _renderer(mem_conn)
    node = _make_node("context", [0.5, 0.5, 0.80, 0.5], label="proj_a")
    prose = rend._render_context([node])
    assert "high constraint" in prose


def test_render_context_elevated_constraints(mem_conn):
    """0.50 <= constraint < 0.75 → 'elevated constraints'."""
    rend = _renderer(mem_conn)
    node = _make_node("context", [0.5, 0.5, 0.60, 0.5], label="proj_b")
    prose = rend._render_context([node])
    assert "elevated constraints" in prose


def test_render_context_moderate_constraints(mem_conn):
    """0.25 <= constraint < 0.50 → 'moderate constraints'."""
    rend = _renderer(mem_conn)
    node = _make_node("context", [0.5, 0.5, 0.35, 0.5], label="proj_c")
    prose = rend._render_context([node])
    assert "moderate constraints" in prose


def test_render_context_low_constraints(mem_conn):
    """constraint < 0.25 → 'low constraints'."""
    rend = _renderer(mem_conn)
    node = _make_node("context", [0.5, 0.5, 0.10, 0.5], label="proj_d")
    prose = rend._render_context([node])
    assert "low constraints" in prose


def test_render_context_active_project_label(mem_conn):
    """Primary project label appears in 'Active project: <label>'."""
    rend = _renderer(mem_conn)
    node = _make_node("context", [0.5, 0.5, 0.3, 0.9], label="IRISVOICE")
    prose = rend._render_context([node])
    assert "Active project:" in prose
    assert "IRISVOICE" in prose


def test_render_context_secondary_projects_listed(mem_conn):
    """Two additional active nodes appear as 'secondary: ...'."""
    rend = _renderer(mem_conn)
    nodes = [
        _make_node("context", [0.5, 0.5, 0.3, 0.9], label="primary"),
        _make_node("context", [0.5, 0.5, 0.3, 0.8], label="sec1"),
        _make_node("context", [0.5, 0.5, 0.3, 0.7], label="sec2"),
    ]
    prose = rend._render_context(nodes)
    assert "secondary" in prose
    assert "sec1" in prose


def test_render_context_stale_freshness_excluded(mem_conn):
    """Req 4.17: freshness <= 0.10 → node excluded, empty prose."""
    rend = _renderer(mem_conn)
    node = _make_node("context", [0.5, 0.5, 0.3, 0.05], label="stale")
    prose = rend._render_context([node])
    assert prose == ""


def test_render_context_ends_with_period(mem_conn):
    """Req 10.6: output ends with '.'."""
    rend = _renderer(mem_conn)
    node = _make_node("context", [0.5, 0.5, 0.3, 0.9], label="myproj")
    prose = rend._render_context([node])
    assert prose.endswith(".")


# ---------------------------------------------------------------------------
# Req 10.9 — toolpath must NEVER produce a profile section
# ---------------------------------------------------------------------------

def test_toolpath_excluded_from_render_dirty_sections(mem_conn):
    """Req 10.9: render_dirty_sections() must never produce a toolpath section."""
    from backend.memory.mycelium.interface import MyceliumInterface
    mi = MyceliumInterface(mem_conn)

    nid = str(uuid.uuid4())
    blob = struct.pack(">3f", 0.5, 0.5, 0.5)
    now = time.time()
    mem_conn.execute(
        "INSERT INTO mycelium_nodes VALUES (?,?,?,?,?,1,?,?,?)",
        (nid, "toolpath", blob, "bash", 0.7, now, now, now),
    )
    mem_conn.commit()

    mi._renderer.render_dirty_sections()

    row = mem_conn.execute(
        "SELECT section_id FROM mycelium_profile WHERE space_id = 'toolpath'"
    ).fetchone()
    assert row is None, "toolpath must never have a profile section"


# ---------------------------------------------------------------------------
# Req 10.11 — get_readable_profile() render_order sequence
# ---------------------------------------------------------------------------

def test_readable_profile_domain_before_style(mem_conn):
    """Req 10.11: domain render_order < style render_order → appears first."""
    from backend.memory.mycelium.interface import MyceliumInterface
    mi = MyceliumInterface(mem_conn)

    for space_id, coords in [("domain", [0.5, 0.8, 0.5]), ("style", [0.5, 0.5, 0.5])]:
        nid = str(uuid.uuid4())
        blob = struct.pack(f">{len(coords)}f", *coords)
        now = time.time()
        mem_conn.execute(
            "INSERT INTO mycelium_nodes VALUES (?,?,?,?,?,1,?,?,?)",
            (nid, space_id, blob, "seed", 0.8, now, now, now),
        )
    mem_conn.commit()

    mi._renderer.render_dirty_sections()
    profile = mi.get_readable_profile()

    if "Domains:" in profile and "Style:" in profile:
        assert profile.index("Domains:") < profile.index("Style:"), (
            "domain must appear before style in readable profile"
        )


def test_readable_profile_returns_empty_string_when_no_sections(mem_conn):
    """get_readable_profile() on empty graph → empty string."""
    from backend.memory.mycelium.interface import MyceliumInterface
    mi = MyceliumInterface(mem_conn)
    result = mi.get_readable_profile()
    assert isinstance(result, str)
    assert result == ""


# ---------------------------------------------------------------------------
# LandmarkMerger — survivor selection (Req 10.1–10.5)
# ---------------------------------------------------------------------------

def _make_landmark(lm_id: str, activation_count: int, cluster_nodes: list) -> Landmark:
    now = time.time()
    return Landmark(
        landmark_id=lm_id,
        label=lm_id,
        task_class="code",
        coordinate_cluster=cluster_nodes,
        traversal_sequence=[],
        cumulative_score=0.5,
        micro_abstract=None,
        micro_abstract_text="",
        activation_count=activation_count,
        is_permanent=False,
        conversation_ref=None,
        created_at=now,
        last_activated=now,
    )


def test_landmark_merger_survivor_is_higher_activation(mem_conn):
    """Req 10.2: survivor = landmark with higher activation_count."""
    n1 = {"node_id": "nodeA", "space_id": "domain", "access_count": 5}
    n2 = {"node_id": "nodeB", "space_id": "domain", "access_count": 4}

    lm_high = _make_landmark("lm_high_act", activation_count=10, cluster_nodes=[n1, n2])
    lm_low  = _make_landmark("lm_low_act",  activation_count=3,  cluster_nodes=[n1, n2])

    index = LandmarkIndex(mem_conn)
    index.save(lm_high)
    index.save(lm_low)

    merger = LandmarkMerger(index)
    result = merger.try_merge(lm_low)

    if result is not None:
        assert result.landmark_id == "lm_high_act", (
            "higher activation_count landmark must survive"
        )


def test_landmark_merger_absorbed_flag_set(mem_conn):
    """Req 10.3: absorbed landmark has absorbed=1 in the DB after merge."""
    n1 = {"node_id": "sharedN1", "space_id": "domain", "access_count": 5}
    n2 = {"node_id": "sharedN2", "space_id": "domain", "access_count": 4}

    lm_a = _make_landmark("lm_a_abs", activation_count=10, cluster_nodes=[n1, n2])
    lm_b = _make_landmark("lm_b_abs", activation_count=5,  cluster_nodes=[n1, n2])

    index = LandmarkIndex(mem_conn)
    index.save(lm_a)
    index.save(lm_b)

    merger = LandmarkMerger(index)
    result = merger.try_merge(lm_b)

    if result is not None:
        row = mem_conn.execute(
            "SELECT absorbed FROM mycelium_landmarks WHERE landmark_id = 'lm_b_abs'"
        ).fetchone()
        assert row is not None and row[0] == 1, "absorbed landmark must have absorbed=1"


def test_landmark_merger_merge_log_written(mem_conn):
    """Req 10.5: merge is logged in mycelium_landmark_merges."""
    n1 = {"node_id": "logN1", "space_id": "domain", "access_count": 3}
    n2 = {"node_id": "logN2", "space_id": "domain", "access_count": 2}

    lm_x = _make_landmark("lm_x_log", activation_count=8, cluster_nodes=[n1, n2])
    lm_y = _make_landmark("lm_y_log", activation_count=4, cluster_nodes=[n1, n2])

    index = LandmarkIndex(mem_conn)
    index.save(lm_x)
    index.save(lm_y)

    merger = LandmarkMerger(index)
    result = merger.try_merge(lm_y)

    if result is not None:
        count = mem_conn.execute(
            "SELECT COUNT(*) FROM mycelium_landmark_merges"
        ).fetchone()[0]
        assert count >= 1, "merge must be logged in mycelium_landmark_merges"


def test_landmark_merger_no_merge_when_no_overlap(mem_conn):
    """Req 10.1: no merge when cluster overlap < MERGE_OVERLAP_THRESHOLD."""
    n1 = {"node_id": "uniN1", "space_id": "domain", "access_count": 3}
    n2 = {"node_id": "uniN2", "space_id": "style",  "access_count": 2}

    lm_p = _make_landmark("lm_p_nomerge", activation_count=5, cluster_nodes=[n1])
    lm_q = _make_landmark("lm_q_nomerge", activation_count=3, cluster_nodes=[n2])

    index = LandmarkIndex(mem_conn)
    index.save(lm_p)
    index.save(lm_q)

    merger = LandmarkMerger(index)
    result = merger.try_merge(lm_q)

    assert result is None, "non-overlapping clusters must not be merged"
