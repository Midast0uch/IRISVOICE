"""Guards (2026-10-18, W5/W6): the Mycelium seed can be walked.

Measured on the live store (read-only): 116 nodes, every access_count 0; 0
mycelium_edges; 2,841 episode-index rows all with node_ids '[]'; chrono 0 nodes;
every stated domain/style/conduct node at 0.4 forever. The causes:
  - a session's region came only from navigation, and navigation is gated by
    maturity, so edge scoring and the episode index never had a node;
  - a repeat observation kept max(0.4, 0.4): confidence could never grow, so the
    maturity gate could never open;
  - distillation read episodes' "created_at"; episodes carry "timestamp".
Each guard below FAILS on the code before this change.
"""
import asyncio
import types

from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.mycelium.interface import MyceliumInterface


def _tool_calls(mi, session_id, tool="read_file", n=3):
    for i in range(1, n + 1):
        mi.ingest_tool_call(tool, True, i, 5, session_id)


def test_a_session_that_used_a_tool_has_a_region(mem_conn):
    mi = MyceliumInterface(mem_conn)
    _tool_calls(mi, "sess-region")
    ids, spaces = mi._active_node_state("sess-region")
    assert ids, "the toolpath node the session wrote is its region"
    assert spaces == ["toolpath"]


def test_a_node_the_session_wrote_stays_visible_to_its_navigation(mem_conn):
    # Navigation excludes ACTIVE nodes from entry and fallback; a written node
    # must not join that set, or the session would hide its own knowledge.
    mi = MyceliumInterface(mem_conn)
    _tool_calls(mi, "sess-nav")
    assert mi._registry.get_active("sess-nav") == set()
    assert mi._registry.get_region("sess-nav")


def test_ending_the_session_forgets_its_region(mem_conn):
    mi = MyceliumInterface(mem_conn)
    _tool_calls(mi, "sess-end")
    mi.clear_session("sess-end")
    assert mi._registry.get_region("sess-end") == set()


def test_the_region_is_bounded(mem_conn):
    reg = MyceliumInterface(mem_conn)._registry
    for s in range(reg._MAX_TOUCHED_SESSIONS + 40):
        reg.touch(f"s{s}", "n")
    for n in range(reg._MAX_TOUCHED_PER_SESSION + 40):
        reg.touch("s-last", f"n{n}")
    assert len(reg._touched) == reg._MAX_TOUCHED_SESSIONS
    assert len(reg.get_region("s-last")) == reg._MAX_TOUCHED_PER_SESSION
    assert "n0" not in reg.get_region("s-last")          # oldest dropped
    assert reg.get_region("s0") == set()                 # oldest session dropped


def _domain_nodes(mi):
    return mi._store.get_nodes_by_space("domain")


def test_a_recurring_statement_grows_confidence_until_the_graph_matures(mem_conn):
    mi = MyceliumInterface(mem_conn)
    mi.ingest_hardware()                      # capability (measured, 0.95)
    for _ in range(6):                        # toolpath window -> 0.6
        mi.ingest_tool_call("read_file", True, 1, 1, "sess-mature")
    assert not mi.is_mature()
    mi.ingest_statements(["fix the react frontend"] * 5)
    nodes = _domain_nodes(mi)
    assert len(nodes) == 1, "one domain, observed five times, is one node"
    assert nodes[0].confidence >= 0.6
    assert mi.is_mature()


def test_one_statement_stays_a_stated_value(mem_conn):
    mi = MyceliumInterface(mem_conn)
    mi.ingest_statements(["fix the react frontend"])
    assert [round(n.confidence, 6) for n in _domain_nodes(mi)] == [0.4]


def test_an_inferred_node_never_outranks_a_measured_one(mem_conn):
    mi = MyceliumInterface(mem_conn)
    mi.ingest_statements(["fix the react frontend"] * 200)
    assert _domain_nodes(mi)[0].confidence <= 0.9


def test_distillation_feeds_the_chrono_space_from_episode_timestamps():
    from backend.memory.distillation import DistillationProcess

    seen = {}
    myc = types.SimpleNamespace(
        ingest_statements=lambda texts: None,
        ingest_sessions=lambda ts: seen.setdefault("ts", ts),
        ingest_conduct_outcomes=lambda eps: None,
        run_maintenance=lambda: None,
    )
    # The exact shape episodic.get_recent_for_distillation returns.
    episodes = [
        {"task_summary": "t", "outcome_type": "success", "outcome_score": 1.0,
         "timestamp": f"2026-10-17 1{h}:00:00"}
        for h in range(5)
    ]
    dp = DistillationProcess(memory_interface=None, adapter=None)
    asyncio.run(dp._run_mycelium_maintenance(episodes, myc))
    # 2026-10-17 10:00:00 UTC = 1792231200
    assert seen.get("ts") == [1792231200.0 + 3600.0 * h for h in range(5)]


def test_the_episode_index_sees_the_region_after_the_turn_ended(mem_conn):
    # Production order: the turn ends the session (clear_session, answer path)
    # and THEN the turn-end job stores the episode and indexes it (memory lane).
    # The index read the live region, already empty: 2,857 of 2,857 live rows
    # carry node_ids '[]'.
    mi = MyceliumInterface(mem_conn)
    _tool_calls(mi, "sess-order")
    mi.clear_session("sess-order")
    ids, spaces = mi._active_node_state("sess-order")
    assert ids and spaces == ["toolpath"]
