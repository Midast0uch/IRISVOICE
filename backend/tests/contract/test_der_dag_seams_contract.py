"""The DER-DAG seams listed in docs/architecture/DER_DAG.md §9 (2026-10-05).

1. a node step with no expected_output was VERIFIED whenever its tools ran,
   also when the tests it ran on its own change failed; and no required fact
   ever mapped to a planner step (the mapper read expected_output only);
2. node steps skipped the failure router and the missing-artifact graft
   (both read item.tool, which a node step never has);
3. dead executor removed; all_ready_items returned nothing under COMPRESS
   where next_ready falls back to the first ready item;
5. the reply model said "the results did not include X" for an X the goal
   contract had proven present - the reply is written once more.
"""
import inspect
from types import SimpleNamespace

from backend.agent import goal_contract as gc
from backend.agent.agent_kernel import (
    AgentKernel,
    _claims_missing,
    _node_failed_after_change,
)


def _node(*calls):
    return SimpleNamespace(tool=None, node_call_log=[
        {"tool": t, "ok": ok, "target": "", "args": {}} for t, ok in calls])


# ── seam 1 ──────────────────────────────────────────────────────────────────

def test_a_failed_run_after_the_nodes_own_change_is_not_verified():
    assert _node_failed_after_change(_node(("edit_file", True), ("run_command", False)))
    assert not _node_failed_after_change(_node(("edit_file", True), ("run_command", True)))
    # the last run decides
    assert not _node_failed_after_change(
        _node(("edit_file", True), ("run_command", False), ("run_command", True)))
    # observing failing tests without a change is a met step (eval c14)
    assert not _node_failed_after_change(_node(("read_file", True), ("run_command", False)))
    # a run before the change says nothing about the change
    assert not _node_failed_after_change(_node(("run_command", False), ("edit_file", True)))
    assert not _node_failed_after_change(SimpleNamespace(tool="run_command"))


def test_the_finalize_verdict_reads_it():
    src = inspect.getsource(AgentKernel._der_finalize_step)
    i = src.index("_verified = self._verify_step_result(")
    assert "_node_failed_after_change(item)" in src[i:i + 600]


def test_a_required_fact_maps_to_the_planner_step_that_names_it():
    steps = [SimpleNamespace(description="Search the web for the height of the Eiffel Tower in metres"),
             SimpleNamespace(description="Find the year the Golden Gate Bridge opened")]
    facts = ("the height of the Eiffel Tower in metres", "the year the Golden Gate Bridge opened",
             "the year the first Harry Potter book was published")
    assert gc.map_to_steps(facts, steps) == ("the year the first Harry Potter book was published",)


# ── seam 2 ──────────────────────────────────────────────────────────────────

def test_node_failures_reach_the_failure_router():
    src = inspect.getsource(AgentKernel._der_route_step_failure)
    assert "_step_decisive_call(item)" in src


def test_the_missing_artifact_graft_reads_what_the_step_did(tmp_path):
    src = inspect.getsource(AgentKernel._der_graft_missing_artifacts)
    assert "_step_calls(item)" in src and 'getattr(item, "tool"' not in src
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert not AgentKernel._artifact_missing("a.py", str(tmp_path))
    assert AgentKernel._artifact_missing("b.py", str(tmp_path))


# ── seam 3 ──────────────────────────────────────────────────────────────────

def test_the_dead_semaphore_executor_is_gone():
    assert not hasattr(AgentKernel, "_der_exec_steps_concurrent")
    assert not hasattr(AgentKernel, "_der_run_step_execution_async")


def test_all_ready_items_falls_back_like_next_ready_under_compress(monkeypatch):
    from backend.agent.der_loop import DirectorQueue, QueueItem
    import backend.gateway.iris_ffi as ffi

    monkeypatch.setattr(ffi, "ffi_caducean_recommend", lambda _s: 1)
    q = DirectorQueue("o", [QueueItem(step_id="s1", step_number=1, description="a", critical=False)])
    assert [i.step_id for i in q.all_ready_items("s")] == ["s1"]
    assert q.next_ready("s").step_id == "s1"


# ── seam 5 ──────────────────────────────────────────────────────────────────

def test_the_three_live_misreads_are_recognised():
    for reply in (
        "However, the search results did not return the height of the Eiffel Tower in metres.",
        "I found the publication year, but the tool results did not include the height.",
        "The tools failed to verify the publication year of the first Harry Potter book.",
    ):
        assert _claims_missing(reply), reply
    assert not _claims_missing(
        "The Eiffel Tower is 330 metres tall, the bridge opened in 1937 and the book came out in 1997.")


def test_a_misread_with_all_facts_covered_is_written_again():
    src = inspect.getsource(AgentKernel._der_synthesize_success_outcome)
    i = src.index("_claims_missing(_syn_text)")
    assert 'float(_gc_st.get("C", 0.0)) >= 1.0' in src[i - 200:i]
    assert "self._synthesize_response(_task, _step_results)" in src[i:i + 1200]
