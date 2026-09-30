"""Execution audit B8 (2026-09-29): in developer mode every request that is
not chitchat goes to the work loop.

The Tier 0 verb list matches substrings and has no "fix" / "implement" /
"refactor" / "debug", so "fix the bug in parser.py" took the direct path.
The list itself is pinned by the routing contract suite and is unchanged;
the launcher mode decides instead.
"""

from backend.agent.semantic_gate import SemanticLogicGate


def _der(text, developer):
    return SemanticLogicGate(tool_mode="auto").compile_dag(text, developer=developer).requires_der_kernel


def test_coding_request_goes_to_der_in_developer_mode():
    assert _der("fix the bug in parser.py", developer=True) is True
    assert _der("why does parse_duration return None for 1h30m", developer=True) is True


def test_personal_mode_routing_is_unchanged():
    assert _der("why does parse_duration return None for 1h30m", developer=False) is False


def test_chitchat_stays_direct_in_developer_mode():
    assert _der("thanks", developer=True) is False
