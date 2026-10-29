"""CT-W10-8 / CT-W10-9 (T46/T47, REQ-13 AC2-AC4): the Mycelium profile is
GATED and actually READ.

Before Wave 10 three things were true at once:

1. ``ProfileRenderer._render_space`` rendered every node it was given: no
   ``confidence_floor``, no ``channel_weight(write_lock) * freshness`` and no
   resonance filter. A 0.05-confidence guess reached the prompt with the same
   weight as a user-stated fact.
2. ``get_profile_section`` read ``mycelium_profile`` without rendering when the
   row was missing or ``dirty = 1`` - a stale or absent section stayed that way.
3. ``_plan_task`` read ``context_package.tier1_directives``, which the interface
   hardcodes to ``""``, and never read ``mycelium_path`` or the tier3 failures;
   ``_assemble_direct_context`` assumed ``_build_system_prompt`` carried the
   profile, and it does not.

Each test fails on the code before this change.
"""

from __future__ import annotations

import struct
import time
import uuid

import pytest

from backend.memory.tests.conftest_mycelium import mem_conn  # noqa: F401
from backend.memory.mycelium.landmark import LandmarkIndex
from backend.memory.mycelium.profile import ProfileRenderer
from backend.memory.mycelium.store import CoordinateStore

SPACES_MOD = "backend.memory.mycelium.spaces"


def _node(conn, space, label, conf=0.8, age_days=0.0):
    nid = str(uuid.uuid4())
    ts = time.time() - age_days * 86400.0
    conn.execute(
        "INSERT INTO mycelium_nodes VALUES (?,?,?,?,?,1,?,?,?)",
        (nid, space, struct.pack(">3f", 0.7, 0.7, 0.7), label, conf, ts, ts, ts),
    )
    return nid


def _renderer(conn):
    store = CoordinateStore(conn)
    return ProfileRenderer(store, LandmarkIndex(conn)), store


# ---------------------------------------------------------------------------
# CT-W10-8 - the renderer gate
# ---------------------------------------------------------------------------

def test_toolpath_never_enters_the_profile(mem_conn):
    """render_order=None means never rendered (Req 10.9), even at confidence 1.0."""
    renderer, _store = _renderer(mem_conn)
    _node(mem_conn, "toolpath", "tool:grep used 400 times", 0.99)
    _node(mem_conn, "style", "plain direct prose", 0.95)
    mem_conn.commit()

    renderer.render_dirty_sections()

    assert renderer.get_profile_section("toolpath") is None
    assert "tool:grep" not in renderer.get_readable_profile()


def test_external_space_is_capped_at_the_documented_weight(mem_conn):
    """An EXTERNAL space enters at 0.30 and cannot clear the 0.4 floor."""
    renderer, store = _renderer(mem_conn)
    _node(mem_conn, "domain", "python expertise", 1.0)
    mem_conn.commit()

    node = store.get_nodes_by_space("domain")[0]
    space = store.spaces.get("domain")
    weighted = renderer._effective_confidence(node, space)

    assert abs(weighted - 0.30) < 1e-6, (
        f"a fresh external node scored {weighted}, not the 0.30 cap")
    assert weighted < space.confidence_floor, "the cap must not clear the floor"
    assert renderer.get_profile_section("domain") is None, (
        "an external-only space must not render a section")


def test_a_node_below_its_space_floor_is_dropped(mem_conn):
    renderer, _store = _renderer(mem_conn)
    _node(mem_conn, "style", "a weak guess", 0.2)
    _node(mem_conn, "chrono", "a strong pattern", 0.9)
    mem_conn.commit()

    renderer.render_dirty_sections()

    assert renderer.get_profile_section("style") is None, (
        "a 0.2-confidence node must not reach the profile")
    assert renderer.get_profile_section("chrono")


def test_a_missing_section_renders_lazily(mem_conn):
    """A read must not depend on someone having run a render pass first."""
    renderer, _store = _renderer(mem_conn)
    _node(mem_conn, "style", "terse and direct", 0.9)
    mem_conn.commit()
    assert mem_conn.execute(
        "SELECT COUNT(*) FROM mycelium_profile").fetchone()[0] == 0

    prose = renderer.get_profile_section("style")

    assert prose, "a missing section must be rendered on read"
    row = mem_conn.execute(
        "SELECT dirty FROM mycelium_profile WHERE space_id = 'style'").fetchone()
    assert row is not None and row[0] == 0, "the lazy render must persist clean"


def test_a_dirty_section_is_rerendered(mem_conn):
    renderer, _store = _renderer(mem_conn)
    _node(mem_conn, "style", "terse and direct", 0.9)
    mem_conn.commit()
    mem_conn.execute(
        "INSERT INTO mycelium_profile (section_id, space_id, render_order, prose, dirty) "
        "VALUES ('prof_style', 'style', 4, 'STALE SECTION', 1)")
    mem_conn.commit()

    prose = renderer.get_profile_section("style")

    assert prose and "STALE SECTION" not in prose


def test_task_class_limits_the_profile_to_its_spaces(mem_conn):
    """style is a planning_task space; chrono is not (REQ-13 AC3)."""
    from backend.memory.mycelium.interface import MyceliumInterface
    from backend.memory.mycelium.store import MemoryPath

    _node(mem_conn, "style", "plain direct prose", 0.95)
    _node(mem_conn, "chrono", "peak activity at nine", 0.95)
    _node(mem_conn, "context", "repo root", 0.95)  # third space: graph is mature
    mem_conn.commit()

    renderer, store = _renderer(mem_conn)
    renderer.render_dirty_sections()
    style_prose = renderer.get_profile_section("style")
    chrono_prose = renderer.get_profile_section("chrono")
    assert style_prose and chrono_prose

    mi = MyceliumInterface(mem_conn)
    nodes = [n for space in ("style", "chrono")
             for n in store.get_nodes_by_space(space)]
    path = MemoryPath(
        nodes=nodes, cumulative_score=1.0, token_encoding="",
        spaces_covered=["style", "chrono"],
        traversal_id="t-w10",
    )
    mi._navigator.navigate_from_task = lambda **_kw: path

    parts = mi._context_parts("plan the build", "s-w10", task_class="planning_task")

    assert parts is not None
    assert style_prose in parts.partial_profile
    assert chrono_prose not in parts.partial_profile, (
        "chrono is not a planning_task space")


# ---------------------------------------------------------------------------
# CT-W10-9 - the wiring into the kernel
# ---------------------------------------------------------------------------

def _pkg(**over):
    from backend.memory.mycelium.interface import ContextPackage

    base = dict(
        mycelium_path="MYCELIUM: conduct:[terse] | confidence:0.88",
        topology_path="TOPOLOGY: prim:core z:+0.10",
        manifest={},
        tier1_directives="",
        tier2_predictions="use ripgrep",
        tier3_failures="avoid: blind rewrite of the parser",
        active_contracts="",
        gradient_warnings="",
        causal_context="",
        ambient_signals="",
        topology_position="core",
        task_class="full",
    )
    base.update(over)
    return ContextPackage(**base)


def test_planning_fields_come_from_the_mycelium_path():
    """tier1_directives is hardcoded "" - Layer 1 lives in mycelium_path."""
    from backend.agent.agent_kernel import AgentKernel

    kernel = AgentKernel.__new__(AgentKernel)
    fields = kernel._context_package_fields(_pkg())

    assert fields["tier1"] == "MYCELIUM: conduct:[terse] | confidence:0.88"
    assert fields["failure_warnings"] == "avoid: blind rewrite of the parser"
    assert fields["preds"] == "use ripgrep"
    assert fields["strategy_hint"] == "core"

    prompt = kernel._build_planning_prompt(
        task="fix the parser",
        tier1_directives=fields["tier1"],
        failure_warnings=fields["failure_warnings"],
    )
    assert "MYCELIUM: conduct" in prompt
    assert "avoid: blind rewrite" in prompt


def test_direct_path_injects_the_profile_only_when_mature():
    from backend.agent.agent_kernel import AgentKernel

    class _Iface:
        def __init__(self, pkg, ok):
            self._pkg, self._ok = pkg, ok

        def get_task_context_package(self, text, session_id):
            return self._pkg, self._ok

    kernel = AgentKernel.__new__(AgentKernel)

    kernel._memory_interface = _Iface(_pkg(), True)
    msgs = kernel._mycelium_profile_messages("check the gpu", "s1")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user" and msgs[1]["role"] == "assistant"
    assert "<mycelium_profile>" in msgs[0]["content"]
    assert "MYCELIUM: conduct" in msgs[0]["content"]

    kernel._memory_interface = _Iface(_pkg(), False)   # immature graph
    assert kernel._mycelium_profile_messages("check the gpu", "s1") == []

    kernel._memory_interface = None
    assert kernel._mycelium_profile_messages("check the gpu", "s1") == []
