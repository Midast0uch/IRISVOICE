"""V12 guard (audit addendum 2026-10-02): recall must pass a relevance gate
before it can add plan steps.

Live run (Wikipedia 'search Kilimanjaro, report height + first ascent',
personal mode, 18:16): the streak gate fired, the re-plan was planned from the
directive ALONE ("Replan required: the run is stuck (...)"), episodic recall
searched with that header, and other stuck runs' episodes became the new plan:
"Read the existing notes file" -> read_file notes.txt -> the task failed.

Two chokepoints:
  - _der_apply_steering plans from the user's request + the directive, and
    recall searches with the request alone;
  - EpisodicStore.retrieve_failures has a floor (unrelated failures measured
    <= 0.27 on the live store; no floor = the 2 nearest always injected).
"""

import types

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, QueueItem
from backend.memory import episodic as E


class _Bus:
    def emit(self, *a, **k):
        pass


def _kernel(captured):
    from backend.core_models import ExecutionPlan, PlanStep

    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv_v12"
    k.session_id = "conv_v12"
    k._der_stop_requested = False
    k._memory_interface = None
    plan = ExecutionPlan(
        plan_id="p", original_task="search Kilimanjaro on Wikipedia and report its height",
        strategy="do_it_myself", reasoning="", plan_title="Kilimanjaro",
        steps=[PlanStep(step_id="s1", step_number=1, description="open wikipedia")],
    )

    def _plan_task(self, text, **kw):
        captured.append((text, kw.get("recall_query")))
        return plan

    k._plan_task = types.MethodType(_plan_task, k)
    return k, plan


def test_replan_plans_from_the_request_and_recalls_with_it(monkeypatch):
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: _Bus())
    captured = []
    k, plan = _kernel(captured)
    q = DirectorQueue(objective=plan.original_task)
    q.add_item(QueueItem(step_id="step-1", step_number=1, description="open wikipedia"))
    directive = "Replan required: the run is stuck (coverage_rate:repeat). Revise the plan."
    k._der_apply_steering(directive, "conv_v12", plan, q)
    text, recall = captured[0]
    assert plan.original_task in text and directive in text
    assert recall == plan.original_task


def _store(rows):
    store = E.EpisodicStore.__new__(E.EpisodicStore)
    store._db = types.SimpleNamespace(execute=lambda *a, **k: types.SimpleNamespace(
        fetchall=lambda: rows))
    store._embed = types.SimpleNamespace(
        encode_with_meta=lambda t: types.SimpleNamespace(vector=[1.0], backend="lfm"))
    return store


def test_unrelated_failures_never_reach_the_planner(monkeypatch):
    monkeypatch.setattr(E, "get_reindex_manager", lambda: None)
    monkeypatch.setattr(E, "_unpack_embedding", lambda blob: [1.0])
    # the measured live values: unrelated <= 0.27, the same task 0.87
    sims = {"notes": 0.27, "space": 0.24, "kili": 0.87}
    rows = [(1, "Read the existing notes file", "no such file", b"notes", "lfm"),
            (2, "space headlines", "timeout", b"space", "lfm")]
    order = iter(["notes", "space"])
    monkeypatch.setattr(E, "compare_embeddings", lambda q, qb, v, vb: sims[next(order)])
    assert _store(rows).retrieve_failures("search Kilimanjaro on Wikipedia") == []

    order2 = iter(["notes", "kili"])
    monkeypatch.setattr(E, "compare_embeddings", lambda q, qb, v, vb: sims[next(order2)])
    rows2 = [rows[0], (3, "search Kilimanjaro height", "browser stalled", b"kili", "lfm")]
    got = _store(rows2).retrieve_failures("search Kilimanjaro on Wikipedia")
    assert [g["task_summary"] for g in got] == ["search Kilimanjaro height"]
