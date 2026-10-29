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


def test_the_off_switch_ships_and_stops_injection(chain_store, monkeypatch):
    assert ontology_recall.TURN_START_RECALL, (
        "ON by default since the 2026-10-28 A/B (owner decision); "
        "IRIS_TURN_START_RECALL=0 is the off switch"
    )
    monkeypatch.setattr(ontology_recall, "TURN_START_RECALL", False)
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


# ── CT-W10-4 (REQ-12 AC4, T43): the gate reads `content` and a user row ranks
# BEFORE the keep-slice. Old code: (a) ignored `content`, so a fact held only in
# the legacy column was invisible; (b) sliced to 3 newest, THEN sorted user rows,
# so an older user fact was already gone (live m03).

def test_the_gate_reads_the_legacy_content_column():
    from backend.agent.ontology_recall import relevance_gate

    rows = [{"content": TAUGHT_INSIGHT, "insight": "", "result": ""}]
    assert relevance_gate(rows, USER_QUESTION, prefix_match=True) == rows, (
        "a user_turn row keeps its text in `content`; omitting it hides the fact")


def test_an_older_user_fact_ranks_before_newer_plan_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(ontology_recall, "TURN_START_RECALL", True)
    con = sqlite3.connect(str(tmp_path / "rank.db"))
    con.execute(
        "CREATE TABLE memory_chain ("
        "entry_id TEXT, thread_id TEXT, session_id TEXT, sequence INTEGER, role TEXT, "
        "content TEXT, metadata TEXT, result TEXT, distilled INTEGER DEFAULT 0, "
        "created_at REAL, chain_id TEXT, insight TEXT, topic_domain TEXT, "
        "node_type TEXT, coords_from TEXT)")
    # three newer PLAN rows that merely repeat the question
    for i, ts in enumerate((4000.0, 3000.0, 2000.0)):
        con.execute(
            "INSERT INTO memory_chain (thread_id, insight, result, created_at, role) "
            "VALUES ('plan', ?, 'success', ?, 'agent')", (TAUGHT_INSIGHT, ts))
    # the OLDEST row is the user's own statement
    con.execute(
        "INSERT INTO memory_chain (thread_id, insight, content, result, created_at, role) "
        "VALUES ('seed', 'my staging deployment is named osprey-west', "
        "'my staging deployment is named osprey-west', '', 1000.0, 'user')")
    con.commit()

    kept = turn_start_prior_memory(con, USER_QUESTION, thread_id="ask")
    con.close()

    assert kept, "the user fact is relevant to the user's own question"
    assert kept[0].get("role") == "user", (
        "the user's own statement outranks a plan step that repeats the question")
    assert "osprey-west" in (kept[0].get("insight") or kept[0].get("content") or "")
    assert len(kept) == 3


# ── WAVE 10 / T48: a taught fact must survive ONE turn of chain churn ────────
# Measured on the live store 2026-10-29: one memory turn writes ~25 chain rows
# (turn/event/step/NARRATED/CARD_SHOWN bookkeeping). With a 24-row newest-first
# candidate pool, the fact taught in the previous turn sat at position 26 of 26
# when the next turn asked for it, the pool held 0 relevant rows, and the memory
# eval scored 1/3 (m01 answered a stale/absent name, m03 lost the suffix).
# The pool is 96 now; this test fails at 24.
def test_a_taught_fact_survives_one_turn_of_chain_churn(tmp_path, monkeypatch):
    monkeypatch.setattr(ontology_recall, "TURN_START_RECALL", True)
    con = sqlite3.connect(str(tmp_path / "churn.db"))
    con.execute(
        "CREATE TABLE memory_chain ("
        "entry_id TEXT, thread_id TEXT, session_id TEXT, sequence INTEGER, role TEXT, "
        "content TEXT, metadata TEXT, result TEXT, distilled INTEGER DEFAULT 0, "
        "created_at REAL, chain_id TEXT, insight TEXT, topic_domain TEXT, "
        "node_type TEXT, coords_from TEXT)")
    con.execute(
        "INSERT INTO memory_chain (thread_id, insight, result, created_at) "
        "VALUES ('t', ?, 'success', 1000.0)", (TAUGHT_INSIGHT,))
    for i in range(30):
        con.execute(
            "INSERT INTO memory_chain (thread_id, insight, result, created_at) "
            "VALUES ('t', ?, 'ok', ?)",
            ('{"type": "CARD_SHOWN", "event_id": "ev-%d"}' % i, 1001.0 + i))
    con.commit()

    kept = turn_start_prior_memory(con, USER_QUESTION)
    con.close()

    assert kept, "the taught fact was evicted by one turn of chain churn"
    assert "kestrel-blue" in (kept[0].get("insight") or kept[0].get("result") or "")
