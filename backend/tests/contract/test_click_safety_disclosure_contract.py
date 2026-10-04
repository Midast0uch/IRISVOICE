"""A section toggle is a safe click by rule (live 2026-10-04).

Before: Wikipedia's "Toggle Human history subsection" button missed the
whole-label navigation rule, went to the Brain judge, the judge timed out
(mercury-2.5 cut by hidden reasoning, then an empty answer), and the agent
waited 45 s for the user before the click failed - 53 s for one toggle.
"""

from backend.agent.tools.click_safety import SAFE, UNSAFE, rule_verdict


def _button(name):
    return {"role": "button", "tag": "button", "name": name}


def test_section_disclosure_buttons_are_safe():
    for name in ("Toggle Human history subsection", "Expand all", "Collapse section"):
        assert rule_verdict("click", _button(name))[0] == SAFE, name


def test_a_commit_word_still_wins_over_a_disclosure_verb():
    assert rule_verdict("click", _button("Toggle and delete account"))[0] == UNSAFE
