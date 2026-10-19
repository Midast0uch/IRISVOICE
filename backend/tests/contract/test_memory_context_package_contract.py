"""
Contract: the memory reaches the DER loop as a ContextPackage.

MEMORY-FOUNDATION-ANALYSIS 13.1: nothing in production built a ContextPackage -
MemoryInterface.get_task_context_package always returned a string (its direct
get_context_path(..., space_subset=...) call raised TypeError), so the Mycelium
path, predictions and warnings never reached a step prompt. These tests pin the
boundary: kernel <- (ContextPackage, True) on a mature graph, the old
(str, False) on an immature graph or with IRIS_MEMORY_CONTEXT_PACKAGE=0, the
size cap, the time budget, and the seams 13.2 named (PredictiveLoader.pre_warm,
the TaskClassifier label check, the live refresh).
"""

import struct
import time
import uuid
from types import SimpleNamespace

import pytest

from backend.memory.tests.conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.interface import MemoryInterface
from backend.memory.live_context import LiveContextPackage
from backend.memory.mycelium import interface as myc_interface
from backend.memory.mycelium.interface import ContextPackage, MyceliumInterface

TASK = "implement the parser fix"


def _node(conn, space, label, conf=0.8):
    nid = str(uuid.uuid4())
    now = time.time()
    conn.execute(
        "INSERT INTO mycelium_nodes VALUES (?,?,?,?,?,1,?,?,?)",
        (nid, space, struct.pack(">3f", 0.7, 0.7, 0.7), label, conf, now, now, now),
    )
    return nid


def _mature(conn):
    """A mature graph: 3+ confident spaces, a 'parser' node linked to a tool."""
    domain = _node(conn, "domain", "parser")
    _node(conn, "conduct", "terse")
    _node(conn, "style", "plain")
    tool = _node(conn, "toolpath", "tool:grep")
    conn.execute(
        "INSERT INTO mycelium_edges (edge_id,from_node_id,to_node_id,score,edge_type,"
        "traversal_count,hit_count,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), domain, tool, 0.9, "tool_choice", 0, 0, time.time()),
    )
    conn.commit()
    myc = MyceliumInterface(conn)
    myc._is_mature_cached = False
    assert myc.is_mature()
    return myc


def _memory(myc):
    """The real MemoryInterface methods over a real MyceliumInterface."""
    mi = MemoryInterface.__new__(MemoryInterface)
    mi._mycelium = myc
    return mi


@pytest.fixture
def myc(mem_conn):  # noqa: F811
    return _mature(mem_conn)


# -- the boundary the kernel reads ---------------------------------------------

def test_mature_graph_gives_kernel_a_context_package(myc):
    result, is_mature = _memory(myc).get_task_context_package(
        TASK, "s1", task_class="code_task"
    )
    assert isinstance(result, ContextPackage), type(result)
    assert is_mature is True
    zone = result.get_system_zone_content()
    assert "MYCELIUM:" in zone and "parser" in zone
    assert result.task_class == "code_task"
    # tier2 comes from BehavioralPredictor over the walked region
    assert result.get_tier2_predictions() == "grep"


def test_package_build_walks_once_and_does_not_reclassify(myc):
    calls = {"walk": 0, "classify": 0}
    real_walk = myc._navigator.navigate_from_task
    real_classify = myc._task_classifier.classify

    def walk(*a, **k):
        calls["walk"] += 1
        return real_walk(*a, **k)

    def classify(*a, **k):
        calls["classify"] += 1
        return real_classify(*a, **k)

    myc._navigator.navigate_from_task = walk
    myc._task_classifier.classify = classify
    result, _ = _memory(myc).get_task_context_package(TASK, "s1", task_class="code_task")
    assert isinstance(result, ContextPackage)
    assert calls == {"walk": 1, "classify": 0}


def test_immature_graph_gives_the_string(mem_conn):  # noqa: F811
    myc = MyceliumInterface(mem_conn)
    assert not myc.is_mature()
    mi = _memory(myc)
    mi.get_task_context = lambda task, sid: "prose header"
    result, is_mature = mi.get_task_context_package(TASK, "s1")
    assert result == "prose header" and is_mature is False


def test_off_switch_restores_the_string_path(myc, monkeypatch):
    monkeypatch.setenv("IRIS_MEMORY_CONTEXT_PACKAGE", "0")
    built = []
    myc.build_context_package = lambda *a, **k: built.append(1)
    mi = _memory(myc)
    mi.get_task_context = lambda task, sid: "string path"
    result, is_mature = mi.get_task_context_package(TASK, "s1", task_class="code_task")
    assert (result, is_mature) == ("string path", False)
    assert built == []


def test_empty_walk_falls_back_without_a_second_walk(mem_conn):  # noqa: F811
    myc = _mature(mem_conn)
    walks = []
    real_walk = myc._navigator.navigate_from_task
    myc._navigator.navigate_from_task = lambda *a, **k: (walks.append(1), real_walk(*a, **k))[1]
    mem_conn.execute("DELETE FROM mycelium_nodes")
    mem_conn.commit()
    mi = _memory(myc)
    mi.semantic = SimpleNamespace(get_startup_header=lambda: "header")
    mi.episodic = SimpleNamespace(assemble_episodic_context=lambda t: "")
    mi.context = SimpleNamespace(assemble_for_task=lambda s, t, h, e: h)
    result, is_mature = mi.get_task_context_package(TASK, "s1", task_class="code_task")
    assert (result, is_mature) == ("header", False)
    assert len(walks) == 1


# -- the cap and the budget -------------------------------------------------------

def test_system_zone_content_is_capped():
    big = "\n".join(f"line {i} " + "x" * 80 for i in range(200))
    pkg = ContextPackage(
        mycelium_path="MYCELIUM: head", topology_path="", manifest={},
        tier1_directives="", tier2_predictions="", tier3_failures="",
        active_contracts="", gradient_warnings=big, causal_context="",
        ambient_signals="", topology_position="", task_class="full",
    )
    zone = pkg.get_system_zone_content()
    assert len(zone) <= myc_interface.CONTEXT_PACKAGE_MAX_CHARS
    assert zone.endswith("[context capped]")
    assert "line 0 " in zone  # whole leading lines survive


def test_spent_budget_skips_optional_parts_but_still_builds(myc):
    pkg = myc.build_context_package(TASK, "s1", task_class="code_task", budget_s=0.0)
    assert isinstance(pkg, ContextPackage)
    assert "MYCELIUM:" in pkg.mycelium_path
    assert pkg.tier2_predictions == "" and pkg.tier3_failures == ""


# -- producers and consumers ----------------------------------------------------

def test_topology_primitive_reads_the_encoders_format():
    pkg = ContextPackage(
        mycelium_path="", topology_path="TOPOLOGY: prim:core z:+0.10", manifest={},
        tier1_directives="", tier2_predictions="", tier3_failures="",
        active_contracts="", gradient_warnings="", causal_context="",
        ambient_signals="", topology_position="", task_class="full",
    )
    assert pkg.topology_primitive == "core"


def test_live_refresh_updates_the_real_package_fields(myc):
    mi = _memory(myc)
    mi.mycelium_get_warnings = lambda session_id, tool_names: ["grep failed twice"]
    mi.mycelium_get_active_contracts = lambda session_id: ["answer tersely"]
    pkg, _ = mi.get_task_context_package(TASK, "s1", task_class="code_task")
    pkg.tier2_predictions = ""
    live = LiveContextPackage(pkg, mi, "s1")
    live.refresh(SimpleNamespace(tool="read_file"), [SimpleNamespace(tool="read_file")])
    assert live.package.gradient_warnings == "grep failed twice"
    assert live.package.active_contracts == "answer tersely"
    assert live.package.tier2_predictions == "grep"  # region ids reach the predictor
    assert "grep failed twice" in live.package.get_system_zone_content()


def test_pre_warm_walks_with_the_real_navigator_and_hits(myc):
    myc.get_context_path(TASK, "s1")
    region_before = set(myc._registry.get_active("s1"))
    myc.clear_session("s1")
    entry = myc._predictive_loader._prediction_cache.get("s1")
    assert entry is not None and entry["hint_text"] == TASK and entry["path"].nodes
    # the speculative walk neither counts as node use nor fills a region
    assert not myc._registry.get_active("s1:prewarm")
    assert region_before  # the real walk did register
    accessed = myc._store.get_nodes_by_space("domain")[0].access_count
    path = myc.get_context_path(TASK, "s1")
    assert isinstance(path, str) and "MYCELIUM:" in path
    assert myc._predictive_loader._hit_count == 1
    assert myc._store.get_nodes_by_space("domain")[0].access_count == accessed + 1


def test_execution_domain_reads_the_classifiers_real_label():
    from backend.agent.agent_kernel import AgentKernel

    kernel = AgentKernel.__new__(AgentKernel)
    kernel._der_task_class = "research_task"
    assert kernel._der_execution_domain(from_voice=False) == "research"
    kernel._der_task_class = "code_task"
    assert kernel._der_execution_domain(from_voice=False) == "der"
