"""A node step's evidence keeps what it read (live 2026-10-04, run x3_3).

Before: later steps, the window and the synthesis sized a step's evidence by
item.tool. A node step has none, so it got the 400-char default: the node's
~275-char summary filled it and its "Tool results" (the page digest with
"Elevation 5,895 m ... First ascent 6 October 1889") were cut. The reply said
the facts were missing.
"""

from backend.agent.agent_kernel import AgentKernel, _step_evidence_cap
from backend.agent.der_loop import QueueItem

# The real shape: summary, then the page text with the facts in the middle,
# then the long element list (the excerpt keeps head and tail).
_RESULT = ("Opened the article and read the infobox for the step. " * 5
           + "\n\nTool results:\n[browser_observe]\nPage: Mount Kilimanjaro\nText: "
           + "From Wikipedia, the free encyclopedia ... " * 4
           + "Elevation 5,895 m (19,341 ft) ... First ascent 6 October 1889 ... "
           + "Elements (pass the number as element_id to browser_act):\n"
           + "\n".join(f'[{i}] link "Section {i}"' for i in range(1, 80)))


def test_a_node_steps_evidence_keeps_the_facts_it_read():
    item = QueueItem(step_id="s3", step_number=3, description="Extract height and first ascent")
    item.node_call_log = [{"tool": "browser_observe", "target": "", "ok": True, "args": {}}]
    assert len(_RESULT) > 400
    evidence = AgentKernel._smart_excerpt(_RESULT, _step_evidence_cap(item))
    assert "5,895 m" in evidence and "1889" in evidence


def test_a_direct_step_keeps_its_by_tool_window():
    item = QueueItem(step_id="s1", step_number=1, description="x", tool="launch_app")
    assert _step_evidence_cap(item) == AgentKernel._der_evidence_cap("launch_app")
