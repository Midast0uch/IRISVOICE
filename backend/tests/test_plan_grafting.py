"""
Tests for Phase 1.4 — step failure handling + plan grafting.

Run: python -m pytest backend/tests/test_plan_grafting.py -v
"""

from unittest.mock import patch, MagicMock


def _make_kernel():
    from backend.agent.agent_kernel import AgentKernel

    with patch.object(AgentKernel, "__init__", lambda self, *a, **kw: None):
        k = AgentKernel.__new__(AgentKernel)
    return k


class _InferResult:
    def __init__(self, raw_text):
        self.raw_text = raw_text


def test_graft_recovery_plan_parses_steps():
    k = _make_kernel()
    graft_json = (
        '{"steps": [{"step_id": "r1", "description": "retry via alt tool", '
        '"tool": "web_search", "params": {"q": "x"}, "depends_on": []}]}'
    )
    k.infer = MagicMock(return_value=_InferResult(graft_json))
    from backend.agent.der_loop import QueueItem

    failed = QueueItem(step_id="s2", step_number=2, description="broken", tool="x")
    grafted = k._der_graft_recovery_plan("objective", failed, "boom", "sess")
    assert len(grafted) == 1
    assert grafted[0].step_id == "r1"
    assert grafted[0].depends_on == []  # not auto-bound to the failed step


def test_handle_step_failure_grafts_when_budget_remains():
    k = _make_kernel()
    graft_json = '{"steps": [{"step_id": "r1", "description": "recover", "tool": "x"}]}'
    k.infer = MagicMock(return_value=_InferResult(graft_json))
    from backend.agent.der_loop import QueueItem, DirectorQueue

    q = DirectorQueue(objective="obj")
    q.items = [
        QueueItem(step_id="s1", step_number=1, description="ok"),
        QueueItem(step_id="s2", step_number=2, description="broken", critical=True),
    ]
    plan = MagicMock()
    plan.original_task = "obj"
    item = q.items[1]
    before = len(q.items)
    k._der_handle_step_failure(item, q, plan, "sess", "turn", None)
    # s2 marked failed + graft added
    assert "s2" in q.failed_ids
    assert len(q.items) == before + 1
    assert q.graft_attempts == 1


def test_handle_step_failure_no_graft_when_budget_exhausted():
    k = _make_kernel()
    k.infer = MagicMock(return_value=_InferResult("{}"))
    from backend.agent.der_loop import QueueItem, DirectorQueue

    q = DirectorQueue(objective="obj")
    q.items = [
        QueueItem(step_id="s2", step_number=2, description="broken", critical=True)
    ]
    q.graft_attempts = 3  # at DER_MAX_GRAFTS
    plan = MagicMock()
    plan.original_task = "obj"
    item = q.items[0]
    before = len(q.items)
    k._der_handle_step_failure(item, q, plan, "sess", "turn", None)
    assert "s2" in q.failed_ids
    # no graft added when budget exhausted
    assert len(q.items) == before
    assert q.graft_attempts == 3


def test_handle_step_failure_non_critical_no_graft():
    k = _make_kernel()
    k.infer = MagicMock(return_value=_InferResult('{"steps": [{"step_id":"r1"}]}'))
    from backend.agent.der_loop import QueueItem, DirectorQueue

    q = DirectorQueue(objective="obj")
    q.items = [
        QueueItem(step_id="s2", step_number=2, description="broken", critical=False)
    ]
    plan = MagicMock()
    plan.original_task = "obj"
    item = q.items[0]
    before = len(q.items)
    k._der_handle_step_failure(item, q, plan, "sess", "turn", None)
    assert "s2" in q.failed_ids
    # non-critical steps are not grafted
    assert len(q.items) == before
