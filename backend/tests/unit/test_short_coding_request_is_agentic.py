"""Execution audit B13 (2026-09-29): a short coding request is not QUICK.

"code_task" (normalised to "code") and the encoder's "quick_edit" matched no
branch of _decide_mode, so "fix parser.py" fell to the length heuristic, ran in
QUICK, and QUICK never continues past its plan.
"""

from backend.agent.der_loop import DirectorQueue, ExecutionMode


def test_short_coding_requests_are_agentic():
    for cls in ("code_task", "code", "quick_edit"):
        assert DirectorQueue._decide_mode(task_class=cls, message_text="fix parser.py",
                                          confidence=0.4) == ExecutionMode.AGENTIC


def test_short_question_is_still_quick():
    assert DirectorQueue._decide_mode(task_class="question", message_text="What's 2+2?",
                                      confidence=0.4) == ExecutionMode.QUICK
