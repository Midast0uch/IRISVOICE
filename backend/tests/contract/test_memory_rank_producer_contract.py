"""CT-W10-13 (T48, REQ-12 AC2): the memory rank must weight the PRODUCER.

`trusted` only means "not outside content". The user's statement and this
agent's own earlier answer are both `context_fragment`/`trusted`, so the zone
channel weight scored them identically (measured on the live store: five m03
candidates all tied at 1.000). The producer is the dimension that separates
them, and it lives in the rank - not as a second multiplier in the retriever.
"""

from __future__ import annotations

import pytest

from backend.memory import memory_rank


def _row(zone="trusted", session="s", rc=0, ts=1700000000.0, tool=None):
    return {"zone": zone, "session": session, "retrieval_count": rc,
            "timestamp": ts, "tool_name": tool}


def test_producer_weight_table():
    assert memory_rank.producer_weight("user_turn") == 1.0
    assert memory_rank.producer_weight("der_step") < 1.0
    assert memory_rank.producer_weight("") == memory_rank.LEGACY_PRODUCER_WEIGHT
    assert memory_rank.producer_weight("run_command") == memory_rank.TOOL_PRODUCER_WEIGHT


def test_the_user_statement_outranks_its_own_echo(tmp_path):
    """Equal relevance, equal zone: only the producer can decide."""
    import sqlite3

    con = sqlite3.connect(":memory:")
    memory_rank.ensure_schema(con)

    scored = [
        (1.0, "user statement", "c-user"),
        (1.0, "agent echo", "c-echo"),
        (1.0, "tool output", "c-tool"),
    ]
    info = {
        "c-user": _row(tool="user_turn"),
        "c-echo": _row(tool="der_step"),
        "c-tool": _row(tool="run_command"),
    }

    ranked, feats = memory_rank.rank_rows(con, scored, info)

    order = [cid for _score, _content, cid in ranked]
    assert order[0] == "c-user", "the user's own statement must lead"
    assert order.index("c-echo") > order.index("c-user"), (
        "the agent's own echo must rank below the statement it echoes")
    assert order.index("c-tool") < order.index("c-echo"), (
        "a tool output is evidence: it outranks a self-echo")
    assert len({f["trust"] for f in feats}) > 1, (
        "zero variance in trust means the producer is not weighted")
