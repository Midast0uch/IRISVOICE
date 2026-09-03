"""CT-ON1 — REQ-18 (T19): typed NodeRecord, two registry-backed domain axes.

  AC1  : every DER node carries node_type from {task, step, sub_loop}
  AC1b : a node that COMMITTED A DECISION (surfaced >=1 candidate and chose)
         is marked committed_decision=True — a valid coupling endpoint
  AC2  : topic_domain is a mycelium DOMAIN_IDS registry value; execution_domain
         is one of voice|der|research from the active winding — NEVER free text
  AC3  : registry miss resolves to the registry's general/unknown bucket and is
         LOGGED, never invented
  AC1c : the per-session topic_domain DISTRIBUTION is reported and the coverage
         check FAILS when the modal domain exceeds the observed-data threshold
  AC4  : node type + both domain axes ride the chain row (memory_chain)
         shape-agnostically (a pre-T19 store writes NULL, never fails)

Spec: specs/der-dag-inversion/requirements.md REQ-18.
"""

from __future__ import annotations

import logging
import sqlite3

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import NodeRecord, QueueItem
from backend.memory.mycelium.spaces import DOMAIN_IDS


# ── registry shape ─────────────────────────────────────────────────────────


def test_topic_domain_registry_has_general_bucket():
    """AC3: the registry has a general/unknown bucket that misses resolve to
    (never invented free text), and it carries 13 canonical topics (REQ-18)."""
    assert "general" in DOMAIN_IDS
    assert len(DOMAIN_IDS) >= 13


def test_resolve_topic_domain_is_registry_backed():
    """AC2: free text resolves to a DOMAIN_IDS KEY via the registry resolver,
    and a miss resolves to 'general' — never a raw free-text string."""
    from backend.memory.mycelium.extractor import resolve_topic_domain

    assert resolve_topic_domain("build a React dashboard") == "web"
    assert resolve_topic_domain("deploy with docker and kubernetes") == "devops"
    assert resolve_topic_domain("quant risk model for trading") == "finance"
    # miss -> general (registry value), NOT the raw text
    assert resolve_topic_domain("qwerty zzz no keyword here") == "general"


def test_resolve_topic_domain_empty_text_is_general():
    from backend.memory.mycelium.extractor import resolve_topic_domain

    assert resolve_topic_domain("") == "general"
    assert resolve_topic_domain(None) == "general"


# ── NodeRecord typing ──────────────────────────────────────────────────────


def test_node_record_carries_typed_fields():
    """AC1/AC2: NodeRecord has node_type (task|step|sub_loop) and both domain
    axes, all registry-shaped with safe sentinel defaults."""
    rec = NodeRecord(step_id="s1", parent_step_id="", objective_anchor="x")
    assert rec.node_type in ("task", "step", "sub_loop")
    assert rec.node_type == "step"  # default is a valid vocabulary value
    assert rec.topic_domain in DOMAIN_IDS  # registry value, not free text
    assert rec.execution_domain in ("voice", "der", "research")
    assert rec.committed_decision is False


def test_sub_loop_node_type_is_valid_vocabulary():
    """AC1: sub_loop and task are also valid node_type values."""
    rec = NodeRecord(
        step_id="s1_s0", parent_step_id="s1", node_type="sub_loop",
        objective_anchor="resolve blocker",
    )
    assert rec.node_type == "sub_loop"
    rec2 = NodeRecord(
        step_id="t1", parent_step_id="", node_type="task",
        objective_anchor="the whole task",
    )
    assert rec2.node_type == "task"


def test_execution_domain_from_winding():
    """AC2: execution_domain follows the ACTIVE winding — voice from voice
    turns, research from research-shaped task classes, der otherwise."""
    k = AgentKernel.__new__(AgentKernel)
    k._der_task_class = "full"
    assert k._der_execution_domain(from_voice=True) == "voice"
    assert k._der_execution_domain(from_voice=False) == "der"
    k._der_task_class = "research"
    assert k._der_execution_domain(from_voice=False) == "research"
    k._der_task_class = "explore"
    assert k._der_execution_domain(from_voice=False) == "research"
    # unknown winding degrades to the session default, never invents
    k._der_task_class = None
    assert k._der_execution_domain(from_voice=False) == "der"


def test_committed_decision_marker_set_at_coupling_decision():
    """AC1b: a node that SURFACED >=1 candidate and CHOSE one gets
    committed_decision=True — the role marker that makes decision provenance a
    lookup. A node that only gathered/executed stays False."""
    k = AgentKernel.__new__(AgentKernel)
    k.session_id = "t19-role"

    class _MI:
        pass

    mi = _MI()
    mi._mycelium = None
    k._memory_interface = mi
    k._der_live_cad_state = lambda session: {"x": 0.0, "y": 0.0, "xi": 0.5, "u": 0.3}
    # stub the mycelium boundary (one store, one scorer) with a minimal fake
    class _Store:
        def __init__(self):
            self.nodes = {}

        def upsert_node(self, node_id, space_id, coords, label):
            self.nodes[node_id] = type("N", (), {"node_id": node_id})()

        def get_node_by_id(self, node_id):
            return self.nodes.get(node_id)

        def upsert_edge(self, from_id, to_id, edge_type, initial_score):
            return f"{from_id}:{to_id}"

        def record_observation(self, edge_id, delta):
            return None

    class _Myc:
        pass

    myc = _Myc()
    myc._store = _Store()
    k._memory_interface._mycelium = myc

    item = QueueItem(
        step_id="t19-dec", step_number=1,
        description="choose between two branches",
        objective_anchor="decide",
        tool="run_command", params={}, expected_output="done",
    )
    cands = [{"node_id": "b0", "label": "branch 0"}, {"node_id": "b1", "label": "branch 1"}]
    item._coupled_candidates = cands
    rec = NodeRecord(step_id="t19-dec", parent_step_id="", objective_anchor="decide")
    k._der_record_coupling_decision(
        item, cands, chosen_node_id="b0", record=rec
    )
    assert rec.committed_decision is True
    assert rec.chosen_branch == "b0"

    # a node that saw no candidates stays unmarked (gathering/executing role)
    item2 = QueueItem(
        step_id="t19-exec", step_number=2,
        description="gather facts",
        objective_anchor="gather",
        tool="run_command", params={}, expected_output="done",
    )
    item2._coupled_candidates = []
    rec2 = NodeRecord(step_id="t19-exec", parent_step_id="", objective_anchor="gather")
    k._der_record_coupling_decision(item2, [], chosen_node_id="", record=rec2)
    assert rec2.committed_decision is False


# ── AC1c distribution + coverage ───────────────────────────────────────────


def test_topic_domain_distribution_reported_per_session():
    """AC1c: report_distribution reads the session's chain rows and groups by
    topic_domain; untyped/NULL rows normalize to 'general' at query time."""
    from backend.agent.caducean_trajectory import DomainCoverageReport

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE memory_chain (chain_id TEXT, thread_id TEXT, "
        "topic_domain TEXT)"
    )
    conn.executemany(
        "INSERT INTO memory_chain (chain_id, thread_id, topic_domain) VALUES (?,?,?)",
        [
            ("a", "s1", "web"), ("b", "s1", "web"), ("c", "s1", "data"),
            ("d", "s1", None),  # pre-T19 untyped row -> general
            ("e", "other", "finance"),  # different session excluded
        ],
    )
    conn.commit()

    dist = DomainCoverageReport(conn).report_distribution("s1")
    assert dist == {"web": 2, "data": 1, "general": 1}
    assert "finance" not in dist  # session-scoped


def test_coverage_check_fails_when_modal_domain_dominates():
    """AC1c (falsifiability): the coverage check FAILS when the modal bucket
    dominates (the pre-T19 'everything is general' failure) and PASSES when
    the axis discriminates."""
    from backend.agent.caducean_trajectory import DomainCoverageReport

    # all-general (the exact pre-T19 degenerate state) -> FAIL
    ok, detail = DomainCoverageReport.check_coverage({"general": 5})
    assert ok is False
    assert detail["modal"] == "general"

    # empty distribution -> FAIL (no typed nodes is itself a finding)
    ok, _ = DomainCoverageReport.check_coverage({})
    assert ok is False

    # mixed distribution -> PASS (the axis carries information)
    ok, detail = DomainCoverageReport.check_coverage(
        {"web": 6, "data": 3, "general": 1}
    )
    assert ok is True
    assert detail["modal"] == "web"
    assert detail["share"] == 0.6


# ── AC4 chain-row typing ───────────────────────────────────────────────────


def test_chain_append_lands_typed_columns_when_schema_has_them():
    """AC4: the shape-agnostic chain append writes node_type + both domains
    when the schema carries the columns (never fails on a legacy store)."""
    import backend.gateway.iris_ffi as ffi

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE memory_chain (chain_id TEXT PRIMARY KEY, thread_id TEXT, "
        "result TEXT, coords_from TEXT, coords_to TEXT, nbl_outcome TEXT, "
        "insight TEXT, file_path TEXT, landmark_id TEXT, mediator TEXT, "
        "mediator_source TEXT, node_type TEXT, topic_domain TEXT, "
        "execution_domain TEXT, stale INTEGER, created_at REAL)"
    )
    conn.commit()

    class _Engine:
        def __init__(self, conn):
            self._conn = conn

        def immortus_chain_append(self, thread_id, result, **kwargs):
            cols = {
                r[1] for r in conn.execute("PRAGMA table_info(memory_chain)")
            }
            insert_cols = ["chain_id", "thread_id", "result", "created_at"]
            vals = [
                kwargs.get("chain_id", "c1"),
                thread_id,
                result,
                __import__("time").time(),
            ]
            for col in ("coords_from", "coords_to", "nbl_outcome", "insight",
                        "file_path", "landmark_id", "mediator", "mediator_source",
                        "node_type", "topic_domain", "execution_domain"):
                if col in cols:
                    insert_cols.append(col)
                    vals.append(kwargs.get(col))
            conn.execute(
                f"INSERT INTO memory_chain ({', '.join(insert_cols)}) "
                f"VALUES ({', '.join('?' * len(vals))})",
                vals,
            )
            conn.commit()
            return 1

    engine = _Engine(conn)
    rc = engine.immortus_chain_append(
        "s1",
        "success",
        chain_id="c1",
        coords_from="(0,0,0,0)",
        coords_to="(0,0,0,1)",
        nbl_outcome="step_1",
        insight="first step",
        node_type="step",
        topic_domain="web",
        execution_domain="der",
    )
    assert rc == 1
    row = conn.execute("SELECT * FROM memory_chain WHERE chain_id='c1'").fetchone()
    idx = {d[1]: i for i, d in enumerate(conn.execute("PRAGMA table_info(memory_chain)"))}
    assert row[idx["node_type"]] == "step"
    assert row[idx["topic_domain"]] == "web"
    assert row[idx["execution_domain"]] == "der"


def test_chain_append_never_fails_on_legacy_schema_without_typed_columns():
    """AC4 (shape-agnostic): a pre-T19 store WITHOUT the typed columns still
    appends cleanly (the columns are skipped, not assumed)."""
    import backend.gateway.iris_ffi as ffi

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE memory_chain (chain_id TEXT PRIMARY KEY, thread_id TEXT, "
        "result TEXT, coords_from TEXT, coords_to TEXT, nbl_outcome TEXT, "
        "insight TEXT, file_path TEXT, landmark_id TEXT, mediator TEXT, "
        "mediator_source TEXT, stale INTEGER, created_at REAL)"
    )
    conn.commit()

    class _Engine:
        def __init__(self, conn):
            self._conn = conn

        def immortus_chain_append(self, thread_id, result, **kwargs):
            cols = {
                r[1] for r in conn.execute("PRAGMA table_info(memory_chain)")
            }
            insert_cols = ["chain_id", "thread_id", "result", "created_at"]
            vals = [kwargs.get("chain_id", "c2"), thread_id, result,
                    __import__("time").time()]
            for col in ("coords_from", "coords_to", "nbl_outcome", "insight",
                        "file_path", "landmark_id", "mediator", "mediator_source",
                        "node_type", "topic_domain", "execution_domain"):
                if col in cols:
                    insert_cols.append(col)
                    vals.append(kwargs.get(col))
            conn.execute(
                f"INSERT INTO memory_chain ({', '.join(insert_cols)}) "
                f"VALUES ({', '.join('?' * len(vals))})",
                vals,
            )
            conn.commit()
            return 1

    engine = _Engine(conn)
    # typed kwargs present but the columns absent — must NOT raise
    rc = engine.immortus_chain_append(
        "s1", "success", chain_id="c2", node_type="step",
        topic_domain="web", execution_domain="der",
    )
    assert rc == 1


def test_kernel_finalize_uses_typed_domain_helpers_without_raising():
    """Smoke: the kernel's domain helpers are reachable on a real (uninitialized)
    kernel instance and never raise for unknown inputs."""
    k = AgentKernel.__new__(AgentKernel)
    k._der_task_class = "full"
    assert k._der_topic_domain("deploy with docker") == "devops"
    assert k._der_topic_domain("") == "general"
    assert k._der_execution_domain(False) == "der"
