"""A node is ONE step (owner 2026-10-03), not the old composite of steps.

Before: the only bound was 300 s. Live 2026-10-03 (personal mode, mercury-2 tool
model) a browser node for "search for Mount Kilimanjaro and open the article"
opened it, then clicked through linked articles (Summit, Topographic
isolation, Cite...) for its whole 300 s, ~22 calls; the step failed, recovery
split it and the 600 s turn budget ran out with no answer.

Now: at NodeContext.max_calls (12 = p99 of 1,334 successful nodes in the log;
93% use <= 5) the node stops calling tools and says whether its step is met.
Only an explicit `STATUS: done` counts as success.
"""

import json

from backend.agent.node_executor import NodeContext, _SYSTEM, run_node

TOOLS = [{"type": "function", "function": {"name": n, "parameters": {}}}
         for n in ("browser_act", "browser_observe")]


def _wanderer(final_text):
    """A model that clicks a new element every turn until it is told to stop."""
    seen = {"calls": 0, "closing": None}

    def gen(role, messages, tools=None, **kw):
        if tools is None:  # the close: no tools offered
            seen["closing"] = messages[-1]["content"]
            return final_text, "", []
        seen["calls"] += 1
        i = seen["calls"]
        return "", "", [{"id": f"c{i}", "type": "function", "function": {
            "name": "browser_act", "arguments": json.dumps({"action": "click", "element_id": i})}}]

    ctx = NodeContext(generate=gen, execute=lambda n, p: {"success": True, "content": f"page {p}"},
                      format_result=lambda n, r: r["content"], tools=TOOLS)
    return ctx, seen


def test_the_step_bound_is_twelve_calls_by_default():
    assert NodeContext(generate=None, execute=None, format_result=None, tools=[]).max_calls == 12


def test_a_wandering_node_stops_at_the_bound_and_reports_its_step():
    ctx, seen = _wanderer("Opened the article; the height is in the infobox.\nSTATUS: done")
    r = run_node("Search for Mount Kilimanjaro and open the article", ctx)
    assert len(r.calls) == 12 and seen["calls"] == 12
    assert "step call limit reached" in seen["closing"]
    assert r.success is True and "STATUS" not in r.summary


def test_at_the_bound_only_an_explicit_done_is_success():
    for text in ("I clicked around.", "Still looking.\nSTATUS: failed: article not found"):
        ctx, _ = _wanderer(text)
        r = run_node("open the article", ctx)
        assert r.success is False and r.error


def test_the_prompt_keeps_the_node_inside_its_step():
    assert "later steps do the rest of the task" in _SYSTEM
