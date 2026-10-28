"""Turn-start prior memory: a taught fact competes on the USER'S words.

Live finding (eval m01, 2026-10-28): the per-step chain gate compares the STEP
the planner invented with the chain. "What is the name of my staging
deployment?" became file-search steps; the taught fact shared no tokens with
them and never entered the context - while the same fact IS reachable when the
gate runs on the user's own words. ``turn_start_prior_memory`` is that recall:
OFF by default (IRIS_TURN_START_RECALL=1 enables it), same pool, same relevance
gate. These tests fail on the code before 2026-10-28 (no turn-start recall).
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.agent import ontology_recall
from backend.agent.ontology_recall import turn_start_prior_memory

USER_QUESTION = "What is the name of my staging deployment? Answer with the name only."
PLANNER_STEP = ("Locate the project directory and read the deployment configuration "
                "to find the deployment name.")
# The REAL seed insight (live run 2026-10-28 01:52): the DER step wrote "is
# named", not "name" - the exact-token gate rejected it at 2/6 shared (0.33
# coverage < 0.4) and the fact never entered the context. The turn-start path
# matches token PREFIXES for exactly this reason.
TAUGHT_INSIGHT = ("Store the fact that the user's staging deployment is named "
                  "kestrel-blue in persistent memory for later recall.")


@pytest.fixture()
def chain_store(tmp_path):
    path = str(tmp_path / "memory.db")
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE memory_chain ("
        "entry_id TEXT, thread_id TEXT, session_id TEXT, sequence INTEGER, role TEXT, "
        "content TEXT, metadata TEXT, result TEXT, distilled INTEGER DEFAULT 0, "
        "created_at REAL, chain_id TEXT, insight TEXT, topic_domain TEXT, "
        "node_type TEXT, coords_from TEXT)")
    con.execute(
        "INSERT INTO memory_chain (thread_id, insight, result, created_at) "
        "VALUES ('seed-thread', ?, 'success', 1000.0)",
        (TAUGHT_INSIGHT,))
    con.commit()
    yield con
    con.close()


def test_off_by_default_nothing_is_injected(chain_store):
    assert not ontology_recall.TURN_START_RECALL, (
        "the switch ships OFF; it flips only on the A/B evidence"
    )
    assert turn_start_prior_memory(chain_store, USER_QUESTION) == []


def test_the_user_question_reaches_the_taught_fact(chain_store, monkeypatch):
    monkeypatch.setattr(ontology_recall, "TURN_START_RECALL", True)
    kept = turn_start_prior_memory(chain_store, USER_QUESTION, thread_id="ask-thread")
    assert kept, (
        "the taught fact is kept on the user's words even though the memory says "
        "'is named' and the question says 'the name of' (prefix match)"
    )
    assert "kestrel-blue" in (kept[0].get("insight") or kept[0].get("result") or "")


def test_the_per_step_gate_keeps_its_exact_match(chain_store, monkeypatch):
    """The shared gate's default is UNCHANGED: the per-step path (whose
    behaviour the t21 contracts pin) still exact-matches, so 'is named' does
    NOT satisfy a 'the name of' step goal there."""
    monkeypatch.setattr(ontology_recall, "TURN_START_RECALL", True)
    from backend.agent.ontology_recall import relevance_gate

    rows = [{"insight": TAUGHT_INSIGHT, "result": "success"}]
    assert relevance_gate(rows, USER_QUESTION) == []
    assert relevance_gate(rows, USER_QUESTION, prefix_match=True) == rows


def test_the_planner_step_still_misses_it_the_gate_is_not_loosened(chain_store, monkeypatch):
    monkeypatch.setattr(ontology_recall, "TURN_START_RECALL", True)
    kept = turn_start_prior_memory(chain_store, PLANNER_STEP, thread_id="ask-thread")
    assert not kept, (
        "the m01 mechanism, pinned: a file-search goal shares no tokens with the "
        "taught fact - the turn-start recall must not become a context firehose"
    )


def test_an_irrelevant_question_gets_nothing(chain_store, monkeypatch):
    monkeypatch.setattr(ontology_recall, "TURN_START_RECALL", True)
    assert turn_start_prior_memory(chain_store, "Play some jazz music please.") == []
    assert turn_start_prior_memory(chain_store, "") == []
