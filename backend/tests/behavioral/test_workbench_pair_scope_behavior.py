"""The Workbench PAIR path (IRIS_WB_TWO_CALL) is for BROWSER code nodes only (2026-11-22).

The pair (gather + compute in one model response, max 2 calls) was built and gated on the
browser cohorts (Round 6, wb_gate-20261122-084556). Flag-wide it also took coding code
nodes: c12 with the Workbench on went 2/3, reply median 128 s against 59 s off
(evals/results/wb_gate-20261122-125231). A non-browser code node keeps the single-script
path the TG-7 full re-run measured on coding, context and data tasks.

Drives the REAL _der_run_node through the browser behavior rig (real worker, fake box).
"""
from __future__ import annotations

import json

import pytest

from backend.tests.behavioral.test_workbench_browser_behavior import Rig


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setenv("IRIS_WB_TWO_CALL", "1")
    r = Rig(monkeypatch)
    try:
        yield r
    finally:
        r.close()


def _code_system(k) -> str:
    kinds = k.st.gen_kinds
    assert "code_node" in kinds, f"the node never entered code mode: {kinds}"
    return json.loads(k.st.systems[kinds.index("code_node")])["content"]


def test_a_file_code_node_keeps_the_single_script_path_with_the_pair_flag_on(rig):
    k = rig.kernel("f1", scripts=["total = 1 + 2 + 3"], item=Rig.file_item("f1"))
    rig.run(k)
    assert _code_system(k) != rig.mod._WB_TWO_CALL_SYSTEM


def test_a_browser_code_node_takes_the_pair_path_with_the_flag_on(rig):
    rig.page = "https://shop.test/a"
    k = rig.kernel("s1", scripts=["price = '1'"], item=Rig.browser_item("s1"))
    rig.run(k)
    assert _code_system(k) == rig.mod._WB_TWO_CALL_SYSTEM
