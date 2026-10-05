"""The PRIOR RESEARCH section lists each earlier finding once.

Eval r09 (2026-10-05, conv-834): every quick search lands a new record under a
fresh id and the lookup deduped by id only, so the same search run three
times came back as three priors with the same text. The section printed one
line 3x above the new results, and the reply writer then called the prior
facts "not returned".
"""
from types import SimpleNamespace

from backend.agent import research_memory as rm


def _recall(records_by_id):
    chunks = [f"[research 2026-10-05 doc={doc_id}] ..." for doc_id in records_by_id]
    mi = SimpleNamespace(episodic=SimpleNamespace(
        retrieve_context_chunks=lambda *a, **k: chunks))
    original = rm.load_record
    rm.load_record = lambda doc_id, mi=None: records_by_id.get(doc_id)
    try:
        return rm.recall_prior_research("eiffel tower height", mi=mi)
    finally:
        rm.load_record = original


def _rec(doc_id, summary):
    return {"id": doc_id, "query": "Eiffel Tower height", "summary": summary,
            "claims": [], "created_at": "2026-10-05", "job_id": doc_id}


def test_the_same_finding_stored_three_times_comes_back_once():
    same = "Height: 330 meters (1,083 feet)."
    out = _recall({"a": _rec("a", same), "b": _rec("b", same), "c": _rec("c", " " + same.upper())})
    assert [r["id"] for r in out] == ["a"]


def test_different_findings_all_come_back():
    out = _recall({"a": _rec("a", "Height: 330 meters."), "b": _rec("b", "Opened in 1889.")})
    assert [r["id"] for r in out] == ["a", "b"]


def test_the_reply_writer_is_told_a_prior_fact_is_not_missing():
    import inspect

    from backend.agent.agent_kernel import AgentKernel

    src = inspect.getsource(AgentKernel._synthesize_response)
    assert "PRIOR RESEARCH lines are results of earlier searches" in src
