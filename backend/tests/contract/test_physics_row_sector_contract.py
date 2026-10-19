"""Guard (2026-10-18): the physics row records the step's real SECTOR.

``_der_submit_physics`` read ``topic_domain`` from the QueueItem, which has no such
field, so every ``caducean_trajectories`` row said "general" (7,089 of 7,089 live rows).
The sector is stamped on the NodeRecord in ``_der_finalize_step`` before the submit.
"""
from __future__ import annotations

from types import SimpleNamespace


def test_the_physics_row_takes_the_sector_from_the_node_record(monkeypatch):
    from backend.agent import agent_kernel as ak

    jobs: list = []
    monkeypatch.setattr(
        "backend.utils.durability_queue.lane",
        lambda name: SimpleNamespace(submit=lambda key, fn: jobs.append(fn) or True),
    )
    seen: dict = {}
    k = ak.AgentKernel.__new__(ak.AgentKernel)
    k.conversation_id = "conv-sector"
    k._der_physics_step = lambda fold, vals, rec, item: seen.update(vals)

    item = SimpleNamespace(step_number=3, step_id="s3", tool=None, description="index the table",
                           params={}, is_subloop=False, node_calls=[])
    rec = SimpleNamespace(topic_domain="data", execution_domain="der", node_type="step")
    k._der_submit_physics(item, node_record=rec, step_success=True, verified="VERIFIED",
                          session="sess-sector", from_voice=False, n_children=0,
                          mediator="", mediator_source="")
    assert len(jobs) == 1
    jobs[0]()
    assert seen["topic_domain"] == "data"
