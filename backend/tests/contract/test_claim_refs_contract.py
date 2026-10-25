"""The composer's "#claim:<id>" references reach the agent as what the memory holds (MEMORY-UX-PLAN 4.6).

The memory surface's "ask IRIS about it" puts a #claim chip in the chat composer. Before 2026-10-25 the gateway passed
only `file:` references to the agent, so a claim chip reached the turn record and nothing else. Now
iris_gateway._referenced_claims_block turns each claim address into one line: its state and its words, read once
(primary key) through the memory surface's read-only reader.
"""
from __future__ import annotations

import sqlite3

import backend.iris_gateway as gw


def _store(tmp_path):
    p = tmp_path / "memory.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE mycelium_landmarks (landmark_id TEXT PRIMARY KEY, label TEXT, micro_abstract_text TEXT, "
                "tier TEXT, absorbed INTEGER)")
    con.executemany("INSERT INTO mycelium_landmarks VALUES (?,?,?,?,?)", [
        ("L1", "fix the import", "Fix the import error in app.py", "landmark", None),
        ("L2", "the music now", None, "candidate", None),
        ("L3", "old", "Forgotten words", "candidate", 1),
    ])
    con.commit()
    con.close()
    return p


def test_claim_refs_become_one_line_each_with_their_state(tmp_path, monkeypatch):
    from backend.memory import surface_queries as sq
    p = _store(tmp_path)
    monkeypatch.setattr(sq, "memory_db_path", lambda: p)
    block = gw._referenced_claims_block(["file:a.py", "claim:L1", "claim:L2", "claim:L3", "claim:NOPE", "claim:L1"])
    lines = block.splitlines()
    assert lines[0].startswith("[Referenced claims]")
    assert lines[1:] == ["claim:L1 · proven · Fix the import error in app.py",
                         "claim:L2 · still learning · the music now",
                         "claim:L3 · forgotten · Forgotten words"]          # unknown ids drop, repeats once


def test_no_claim_refs_no_block(tmp_path, monkeypatch):
    from backend.memory import surface_queries as sq
    monkeypatch.setattr(sq, "memory_db_path", lambda: _store(tmp_path))
    assert gw._referenced_claims_block(["file:a.py"]) is None
    assert gw._referenced_claims_block(None) is None
