"""scripts/undo_wrong_landmark_merges.py - the repair of merges that joined DIFFERENT tasks.

A temp store with one wrong merge (hockey -> python, its evidence copied onto the survivor), one right
merge (the same eval task from two temp folders), and a later same-task merge the copy travelled through.
The repair brings the wrong one back, takes back exactly what it copied, leaves the right one, and a
second run changes nothing.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "undo_wrong_landmark_merges.py"

HOCKEY = "Go to scrapethissite.com, open the hockey teams page, and show me a screenshot of it."
PYTHON = "Who created the Python programming language?"
RUN = r"The project is in C:\Temp\iris-evals\{}\c06_fix_import_error. Fix the import error."


def _store(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE mycelium_landmarks (landmark_id TEXT PRIMARY KEY, label TEXT, absorbed INTEGER, tier TEXT,
          evidence TEXT DEFAULT '[]');
        CREATE TABLE mycelium_landmark_merges (merge_id TEXT PRIMARY KEY, survivor_id TEXT, absorbed_id TEXT,
          overlap_score REAL, pre_merge_score_s REAL, pre_merge_score_a REAL, post_merge_score REAL, created_at REAL);
    """)
    hockey_ev = [{"kind": "test_pass", "ref": "episode", "session": "s_hockey"},
                 {"kind": "task_complete", "ref": "episode", "session": "s_hockey"}]
    python_own = [{"kind": "task_complete", "ref": "episode", "session": "s_python"}]
    copied = hockey_ev + [{"kind": "recurrence", "ref": "merged L_HOCKEY", "session": "s_python"}]
    rows = [
        ("L_HOCKEY", HOCKEY, 1, "landmark", hockey_ev),
        ("L_PY", PYTHON, 1, "landmark", python_own + copied),           # later absorbed by L_PY2 (same task)
        ("L_PY2", PYTHON, None, "landmark", python_own + copied),        # the copy travelled on through m3
        ("L_RUN_A", RUN.format("20261018"), 1, "candidate", [{"kind": "test_pass", "ref": "episode", "session": "s_a"}]),
        ("L_RUN_B", RUN.format("20261024"), None, "landmark", [{"kind": "test_pass", "ref": "episode", "session": "s_a"},
                                                               {"kind": "test_pass", "ref": "episode", "session": "s_b"}]),
    ]
    con.executemany("INSERT INTO mycelium_landmarks VALUES (?,?,?,?,?)",
                    [(i, l, a, t, json.dumps(e)) for i, l, a, t, e in rows])
    con.executemany("INSERT INTO mycelium_landmark_merges VALUES (?,?,?,1.0,0,0,0,?)",
                    [("m1", "L_PY", "L_HOCKEY", 1.0), ("m2", "L_RUN_B", "L_RUN_A", 2.0), ("m3", "L_PY2", "L_PY", 3.0)])
    con.commit()
    con.close()


def _run(db: Path, *extra: str) -> str:
    out = subprocess.run([sys.executable, str(SCRIPT), "--db", str(db), *extra], capture_output=True, text=True,
                         cwd=REPO, timeout=300)
    assert out.returncode == 0, out.stdout + out.stderr
    return out.stdout


def _rows(db: Path) -> dict:
    con = sqlite3.connect(db)
    try:
        return {r[0]: {"absorbed": r[1], "tier": r[2], "evidence": json.loads(r[3])}
                for r in con.execute("SELECT landmark_id, absorbed, tier, evidence FROM mycelium_landmarks")}
    finally:
        con.close()


def test_the_repair_restores_only_wrong_merges_takes_back_the_copy_and_is_idempotent(tmp_path):
    db = tmp_path / "memory.db"
    _store(db)
    before = _rows(db)
    assert "dry run" in _run(db) and _rows(db) == before                  # the default writes nothing
    _run(db, "--apply")
    after = _rows(db)
    assert after["L_HOCKEY"]["absorbed"] is None                           # the different task is back
    assert after["L_RUN_A"]["absorbed"] == 1                               # the same task stays merged
    assert after["L_PY"]["absorbed"] == 1                                  # a same-task merge stays
    sessions = lambda lid: [e["session"] for e in after[lid]["evidence"]]
    assert sessions("L_PY") == ["s_python"]                                # the copy is taken back ...
    assert sessions("L_PY2") == ["s_python"]                               # ... also where it travelled on
    assert after["L_PY2"]["tier"] == "candidate"                           # its proof was borrowed (1 piece left)
    assert after["L_RUN_B"]["evidence"] == before["L_RUN_B"]["evidence"]   # a right merge is untouched
    assert len(list(tmp_path.glob("landmark_merge_undo-*.json"))) == 1     # values before, logged
    assert "nothing to do" in _run(db, "--apply") and _rows(db) == after   # idempotent
