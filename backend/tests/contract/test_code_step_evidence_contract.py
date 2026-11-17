"""A Workbench code step's manifest reaches the synthesis whole (TG-7 v2 full, 2026-11-17).

_der_node_record_evidence gives a step that called a gather/read tool a wide excerpt of its
result, and every other step a compressed record ("summary: <content_summary[:300]>"). A code
step calls run_python - in neither set - so its outputs manifest was cut at 300 chars: the call
dump of conv-8235 (c51) showed "per_row = [... 'sprocket', ... 15.0}," with the total and
"check: passed" gone, and c51 failed 2/5 and x02 1/5 with "the output was truncated".
"""
from types import SimpleNamespace

from backend.agent.agent_kernel import AgentKernel

_MANIFEST = (
    "Compute exact total revenue from sales.csv\n\nOutputs:\n"
    "per_row = [" + ", ".join(
        f"{{'product': 'p{i}', 'units': {i}, 'price': 2.5, 'revenue': {2.5 * i}}}" for i in range(1, 7))
    + "]\ntotal = 64.5\nrows = 6\n\ncheck: passed"
)


def _code_step():
    rec = SimpleNamespace(content_summary=_MANIFEST, expected_output="the exact total",
                          remaining="", ruled_out="")
    return SimpleNamespace(tool=None, result=_MANIFEST, node_record=rec, footprint=None,
                           node_call_log=[{"tool": "run_python", "target": "compute", "ok": True}])


def test_a_code_step_gives_the_synthesis_its_whole_manifest():
    assert len(_MANIFEST) > 300
    ev = AgentKernel._der_node_record_evidence(_code_step())
    assert "total = 64.5" in ev and "check: passed" in ev and "'p6'" in ev


def test_a_step_with_no_read_or_code_call_keeps_the_compressed_record():
    item = _code_step()
    item.node_call_log = [{"tool": "write_file", "target": "x", "ok": True}]
    ev = AgentKernel._der_node_record_evidence(item)
    assert ev.startswith("summary: ") and "check: passed" not in ev
