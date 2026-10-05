"""A node that searched three facts hands all three to the reply.

Eval r09 (2026-10-05, conv-810): one node made three searches (Eiffel Tower,
Golden Gate Bridge, Harry Potter) and closed in the same answer; the goal
contract read C=1.0, but the reply said two facts were missing. The node
result joined the three ~9k-char results and the synthesis window (8,000
chars, head 70% + tail 30%) kept the first search's header block and the
third search's tail: the middle search was cut out whole. Over 186 stored
searches the fact sits at char <= 2,144 of its result, so each call's HEAD is
what the reply needs.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from backend.agent.agent_kernel import AgentKernel
from backend.agent.node_executor import NodeContext, run_node

TOOLS = [{"type": "function", "function": {"name": "search", "parameters": {}}}]
FACTS = {"Eiffel Tower height": "330 metres", "Golden Gate Bridge opened": "1937",
         "first Harry Potter book": "1997"}


def _page(query: str) -> str:
    # a realistic result: a 2,000-char header block, the fact, then 7k of page
    return ("PRIOR RESEARCH | menu | " * 90)[:2000] + f" {query}: {FACTS[query]}. " + "x" * 7000


def _node_result():
    calls = [{"id": f"c{i}", "type": "function", "function": {"name": "search", "arguments":
              json.dumps({"query": q, "step_done": True, "step_summary": "Searched."})}}
             for i, q in enumerate(FACTS)]
    replies = [("", calls)]
    ctx = NodeContext(
        generate=lambda role, messages, **k: (replies.pop(0)[0], "", calls) if replies
        else ("STATUS: done", "", []),
        execute=lambda name, params: {"success": True, "content": _page(params["query"])},
        format_result=lambda name, raw: raw["content"], tools=TOOLS,
    )
    return run_node("look up three facts", ctx)


def test_every_call_of_a_closing_answer_reaches_the_reply_evidence():
    result = _node_result()
    assert result.success and len(result.calls) == 3
    item = SimpleNamespace(tool=None, params={}, node_call_log=result.calls,
                           result=result.as_step_result(), node_record=None)
    evidence = AgentKernel._der_node_record_evidence(item)
    for fact in FACTS.values():
        assert fact in evidence, f"{fact!r} cut out of the reply evidence"
    # conv-820: the synthesis prompt cut each step AGAIN (6,000 head+tail)
    from backend.agent.agent_kernel import TaskContext

    task = TaskContext(task_id="t", user_message="three facts", session_id="s",
                       conversation_history=[], plan={},
                       step_results=[{"tool": None, "action": "look up", "result": evidence,
                                      "bounded": True, "success": True}])
    prompt_part = task.get_results_summary()
    for fact in FACTS.values():
        assert fact in prompt_part, f"{fact!r} cut out of the synthesis prompt"


def test_the_der_synthesis_marks_its_evidence_bounded():
    import inspect

    src = inspect.getsource(AgentKernel)
    i = src.index('"result": self._der_node_record_evidence(ci)')
    assert '"bounded": True' in src[i:i + 200]
