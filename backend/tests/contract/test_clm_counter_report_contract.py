"""CLM-7 AC3 + CLM-8 AC4 (specs/clm-memory T5.2): one report script for the counter set.

The view's decisions reach logs/clm_baseline.jsonl as `event` rows (values only, on the
instrument lane, only with IRIS_CLM_BASELINE=1), and evals/context_report.py turns
them into the counters: offloads by actor, re-stretches, premature evictions,
re-recall cost, repeated dead-end actions, stale claims shown. Before 2026-11-22 the
report's offload column read rows nobody wrote ("n/a" on every run).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _report_module():
    spec = importlib.util.spec_from_file_location("context_report", ROOT / "evals" / "context_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def log(tmp_path, monkeypatch):
    from backend.agent.inference import clm_baseline

    path = tmp_path / "clm_baseline.jsonl"
    monkeypatch.setattr(clm_baseline, "_PATH", path)
    return path


def _flush():
    from backend.utils.durability_queue import lane

    lane("clm_baseline").flush(10.0)


def test_view_decisions_become_rows_and_the_report_counts_them(log, monkeypatch):
    from backend.agent.kernel.der import node

    monkeypatch.setenv("IRIS_CLM_BASELINE", "1")
    node._clm_measure("conv-r", "OFFLOADED", {"refs": ["tool_result:a"], "saving": 900})
    node._clm_measure("conv-r", "OFFLOADED", {"refs": ["tool_result:b"], "by": "model"})
    node._clm_measure("conv-r", "RESTRETCHED", {"refs": ["tool_result:a"], "trigger": "dead_end_match"})
    node._clm_measure("conv-r", "PREMATURE_EVICTION", {"refs": ["tool_result:a"]})
    from backend.agent.inference import clm_baseline

    clm_baseline.record_event("conv-r", "restretched", actor="model", trigger="expand", chars=7000)
    clm_baseline.record_event("conv-r", "landmark_header", n=3, stale=1)
    _flush()
    rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert [r["event"] for r in rows] == ["offloaded", "offloaded", "restretched",
                                         "premature_eviction", "restretched", "landmark_header"]
    assert all("content" not in r for r in rows)                      # values only
    rep = _report_module()
    got = rep._offload([], rep._rows(log)["conv-r"]["event"])
    assert got == {"offloaded": 2, "restretched": 2, "model_set_aside": 1, "model_expand": 1,
                   "premature_eviction": 1, "re_recall_tokens": 2000, "repeated_dead_ends": 1,
                   "headers": 1, "stale_landmarks_shown": 1}


def test_flag_off_writes_nothing(log, monkeypatch):
    from backend.agent.inference import clm_baseline
    from backend.agent.kernel.der import node

    monkeypatch.delenv("IRIS_CLM_BASELINE", raising=False)
    node._clm_measure("conv-r", "OFFLOADED", {"refs": ["tool_result:a"]})
    clm_baseline.record_event("conv-r", "landmark_header", n=1, stale=0)
    _flush()
    assert not log.exists()


# -- T5.3 (CLM-10 AC1, AC3): cached tokens and the edit-cost report --------------------

@pytest.mark.parametrize("payload,cached", [
    ({"usage": {"prompt_tokens": 900, "completion_tokens": 10,
                "prompt_tokens_details": {"cached_tokens": 640}}}, 640),          # OpenAI shape
    ({"usage": {"prompt_tokens": 900, "completion_tokens": 10,
                "prompt_cache_hit_tokens": 512}}, 512),                            # DeepSeek shape
    ({"usage": {"prompt_tokens": 900, "completion_tokens": 10},
      "timings": {"cache_n": 300}}, 300),                                          # llama.cpp shape
    ({"usage": {"prompt_tokens": 900, "completion_tokens": 10}}, None),            # not reported
])
def test_cached_prompt_tokens_are_read_when_the_server_reports_them(payload, cached):
    from backend.agent.inference.transport import _extract_usage

    u = _extract_usage(payload)
    assert u["prompt_tokens"] == 900
    assert u.get("cached_tokens") == cached        # absent stays absent - never a fake 0


def test_edit_cost_splits_edits_from_appends_and_flags_an_unstable_prefix():
    import importlib.util as _u

    spec = _u.spec_from_file_location("clm_baseline_report", ROOT / "scripts" / "clm_baseline_report.py")
    rep = _u.module_from_spec(spec)
    spec.loader.exec_module(rep)

    def call(seq, node, prefix, asides, prompt, cached):
        return {"event": "call", "seq": seq, "node_key": node, "prefix_hash": prefix, "asides": asides,
                "provider": "p", "model": "m", "usage": {"prompt_tokens": prompt, "cached_tokens": cached}}

    rows = [call(1, "n1", "A", 0, 1000, 0), call(2, "n1", "A", 0, 1500, 1000),   # append: 500 new
            call(3, "n1", "A", 1, 1200, 300),                                    # edit: 900 again
            call(4, "n2", "B", 0, 800, 0), call(5, "n2", "C", 0, 900, 0)]        # menu changed mid-node
    out = rep.edit_cost(rows)
    assert out["nodes_with_2plus_calls"] == 2 and out["prefix_unstable_nodes"] == 1
    d = out["reprocessed_tokens"]["p/m"]
    assert d["append"]["n"] == 2 and d["edit"] == {"n": 1, "median": 900, "p95": 900}
