"""needs_action decides on the SAME frame its calibrated rows were measured on.

Found 2026-11-09: the outcome rows (the bar's evidence, needs_action/v7) carry
{"goal", "expected"} - `expected` is what moved the hard write goals from 'no'
to 'yes' (oracle.md 4.1) - while the pre-step consult that moves a step to
DIRECT sent the goal alone. An enforced consumer would then act on a question
its threshold was never fitted for. The method is too large to drive, so the
seam is pinned structurally: the deciding consult passes the row's frame.
"""
import inspect
import re

from backend.agent.agent_kernel import AgentKernel


def _decide_block(src: str) -> str:
    at = src.index('if _de_na.decides("needs_action") is not None:')
    return src[at:src.index("item.mode = _xr_mode.DIRECT", at)]


def test_the_deciding_consult_carries_goal_and_expected():
    block = _decide_block(inspect.getsource(AgentKernel._der_run_node))
    assert "score_surface_bool(" in block
    assert re.search(r'frame=\{"goal": goal,\s*"expected":', block), block


def test_the_outcome_row_carries_the_same_keys():
    src = inspect.getsource(AgentKernel._der_run_node)
    assert '{"goal": goal, "expected": _na_expected}' in src
