"""
Contract tests for batch dispatch (T4.6 / CT-5, CT-8).

Pins:
  * CT-5: QueueItem shape (is_subloop, tool, step_id, step_number)
  * CT-8: abandon() drops a pending group (soft-cancel / turn boundary)
"""
import math

from backend.agent.batch_dispatch import SubLoopBatcher
from backend.agent.phase_manager import get_registry


class _FakeChild:
    def __init__(self, step_id, is_subloop=True, tool=None):
        self.step_id = step_id
        self.step_number = int(step_id.split("_s")[0].lstrip("p"))
        self.is_subloop = is_subloop
        self.tool = tool
        # REQ-18 AC1: only independent sub-loop children are batchable.
        self.independent = True
        self.description = "test"
        self.expected_output = "test"


def test_ct5_queue_item_shape():
    """CT-5: QueueItem shape — batcher expects is_subloop, tool, step_id."""
    _b = SubLoopBatcher()
    # Non-subloop → pass through
    _c = _FakeChild("p1_s1", is_subloop=False)
    assert _b.offer(_c, "q1") is None  # not batched, pass through
    # Subloop with tool → pass through
    _c2 = _FakeChild("p1_s2", tool="compute")
    assert _b.offer(_c2, "q1") is None  # has a tool, can't batch
    # Subloop without tool → batched
    _c3 = _FakeChild("p1_s3")
    assert _b.offer(_c3, "q1") is None  # batched (awaiting more)


def test_ct8_abandon_before_flush():
    """CT-8: abandon(join_point) drops a pending group — soft-cancel."""
    # Model a valid batchable child: independent (REQ-18 AC1) AND its quota's
    # oscillator placed at the firing point π so the phase-window gate (AC2)
    # admits it into a pending group.
    _osc = get_registry().register("q1:SUBLOOP", quota_id="q1", independent=True)
    _osc.theta = math.pi
    _b = SubLoopBatcher()
    _b.offer(_FakeChild("p1_s1"), "q1")
    assert len(_b._groups) == 1
    _b.abandon("p1")
    assert len(_b._groups) == 0


# ── CT-9: batched dispatch routes through the ROUTER's role binding ────────
# Root cause (found live 2026-08-06): _der_dispatch_batch_group passed the
# LEGACY _selected_reasoning_model string as router.generate's first arg. The
# router treats that arg as a ROLE, so a model string failed resolve() and the
# batched call fell back to provider='ollama' ("der_batch_dispatch failed:
# Ollama returned 500") while per-step calls routed to cerebras. The batched
# call MUST use the role "reasoning" so it resolves the SAME bound provider as
# its siblings.

class _Child:
    def __init__(self, step_id):
        self.step_id = step_id
        self.step_number = 1
        self.is_subloop = True
        self.independent = True
        self.description = "q"
        self.expected_output = "q"


class _BatchRouter:
    """Records the first arg (role-or-model) and returns per-child results."""

    def __init__(self):
        self.roles = []

    def generate(self, role, messages, tools=None, **kw):
        self.roles.append(role)
        ids = [f"p1_s{i}" for i in range(len([m for m in messages if m.get('role') == 'user']))]
        return (
            '<subloop id="p1_s0">A</subloop>'
            '<subloop id="p1_s1">B</subloop>'
            '<subloop id="p1_s2">C</subloop>',
            "",
            [],
        )


def test_ct9_batch_dispatch_uses_role_binding():
    """The batched call routes through the router ROLE, not a legacy model id.

    Regression: passing a model string ("llama3.2:latest") as router.generate's
    first arg made the router treat it as a role, fail resolve(), and fall back
    to the broken Ollama provider. The call must be keyed on the "reasoning"
    role so it resolves the same bound instance as per-step calls.
    """
    from backend.agent import agent_kernel
    from backend.agent.agent_kernel import AgentKernel
    from backend.agent.batch_dispatch import BatchGroup

    from types import SimpleNamespace

    _router = _BatchRouter()
    k = AgentKernel.__new__(AgentKernel)
    k._router = _router
    # Legacy field intentionally set to the WRONG model — the bug used it.
    k._selected_reasoning_model = "llama3.2:latest"
    k._der_turn_calls = 0
    k._live_ctx = None
    k._memory_interface = None
    k._der_batch_base_messages = lambda sess: [{"role": "system", "content": "s"}]

    _g = BatchGroup(
        join_point="p1", quota_id="q1",
        children=[_Child("p1_s0"), _Child("p1_s1"), _Child("p1_s2")],
    )
    _g.batched_prompt = "<subloop id=\"p1_s0\">a</subloop>"
    queue = SimpleNamespace()
    queue.items = []

    def _add(item):
        queue.items.append(item)

    queue.add_item = _add

    k._der_dispatch_batch_group(_g, queue, "sess", "turn")

    # The router must have been called with the ROLE, never the legacy model.
    assert _router.roles == ["reasoning"], f"got {_router.roles}"
    # AC3: the dispatched group increments the per-turn call counter.
    assert k._der_turn_calls == 1
    # All three children queued.
    assert len(queue.items) == 3
