"""W1 (memory cortex plan, 2026-11-22): a strand says what it did, without the chat dropdown.

The durable record of what a strand did is `episodes.tool_sequence` (tool, params, target,
success, step, description) in the encrypted memory store; the surface read only the tool
NAMES from it. W1:
  * strand rows (the corridor) carry up to 12 step lines, the snapshot up to 5 per episode
    (the hover card shows 5 and "+N more") - short text, never tool output;
  * the exact output of a step comes from the chat record on a click only
    (GET /api/memory/tool-result), with "no longer kept" when IRIS evicted it;
  * eval and dev conversations lose their tool_results rows first (measured: all 4,000 live
    rows were eval rows, so a user's output lasted about 4 days).

Each test FAILS on the code before this change.
"""
from __future__ import annotations

import json
import sqlite3

from backend.tests.contract.test_memory_api_contract import env  # noqa: F401  (the fixture)


def _seq(n):
    out = []
    for i in range(n):
        out.append({"tool": "read_file" if i % 2 else "run_python", "params": {"path": f"data/f{i}.csv"},
                    "target": None if i == 0 else f"data/f{i}.csv", "success": i != 3, "step": i + 1,
                    "description": "  Read   the\nfile  " + "x" * 200})
    return out


def _episode(env, eid, session, seq):
    con = sqlite3.connect(str(env.sq.memory_db_path()))
    con.execute("INSERT INTO episodes (id, session_id, task_summary, outcome_type, tool_sequence, timestamp)"
                " VALUES (?, ?, 'many steps', 'success', ?, '2026-10-21 11:00:00')", (eid, session, json.dumps(seq)))
    con.commit()
    con.close()


def test_step_lines_are_short_text_from_the_tool_sequence():
    from backend.memory import surface_queries as sq

    tools, steps, n = sq.episode_steps(json.dumps(_seq(8) + [{"no": "tool"}]), 5)
    assert n == 8 and len(steps) == 5 and len(tools) == 8
    assert steps[0]["target"] == "data/f0.csv"                 # no target: taken from the params
    assert steps[0]["what"].startswith("Read the file x") and len(steps[0]["what"]) == sq.STEP_WHAT_MAX
    assert steps[3]["ok"] is False and steps[1]["ok"] is True and steps[1]["step"] == 2
    assert set(steps[0]) == {"tool", "target", "what", "ok", "step"}   # never params, never output


def test_the_strand_and_the_snapshot_carry_the_step_lines(env):  # noqa: F811
    root = env.ids["root"]
    _episode(env, "ep-many", root, _seq(14))
    strand = env.client.get(f"/api/memory/strand/{root}").json()
    ep = next(e for e in strand["episodes"] if e["id"] == "ep-many")
    assert len(ep["steps"]) == 12 and ep["step_count"] == 14
    snap = env.client.get("/api/memory/snapshot").json()
    ep = next(e for e in snap["episodes"] if e["id"] == "ep-many")
    assert len(ep["steps"]) == 5 and ep["step_count"] == 14


def test_the_exact_output_comes_on_click_and_says_when_it_is_gone(env):  # noqa: F811
    import backend.conversation_store as cs

    root = env.ids["root"]
    rid = cs.new_tool_result_id()
    assert cs.add_tool_result(rid, root, "T1", "s1", 0, "read_file", "notes.txt", "A" * 5000, min_chars=0)
    assert cs.get_tool_result(rid, wait_s=5.0) is not None
    d = env.client.get("/api/memory/tool-result", params={"conversation": root, "tool": "read_file",
                                                          "target": "notes.txt"}).json()
    assert d["plaintext"] is True and len(d["rows"]) == 1
    row = d["rows"][0]
    assert row["turn"] == "T1" and row["step"] == "s1" and len(row["text"]) == 4000 and row["more"] is True
    assert env.client.get("/api/memory/tool-result", params={"conversation": root, "tool": "write_file"}).json() \
        == {"rows": [], "gone": 0, "plaintext": True}
    assert env.client.get("/api/memory/tool-result").status_code == 400


def test_eval_rows_are_evicted_before_the_users(env, monkeypatch):  # noqa: F811
    import backend.conversation_store as cs

    monkeypatch.setattr(cs, "TOOL_RESULTS_MAX_ROWS", 3)
    user, ev = env.ids["root"], env.ids["eval_root"]
    ids = []
    for conv, n in ((user, 2), (ev, 3)):          # the user's rows are OLDER (lower rowid)
        for i in range(n):
            rid = cs.new_tool_result_id()
            cs.add_tool_result(rid, conv, "T", f"s{i}", i, "read_file", f"{conv}-{i}", "z" * 10, min_chars=0)
            assert cs.get_tool_result(rid, wait_s=5.0) is not None or conv == ev
            ids.append((conv, rid))
    kept = {rid for conv, rid in ids if cs.get_tool_result(rid, wait_s=0.5) is not None}
    assert all(rid in kept for conv, rid in ids if conv == user), "a user's row went before an eval row"
    assert len(kept) == 3
