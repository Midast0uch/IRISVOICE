"""W2 (memory cortex plan, 2026-11-22): how full a strand's context got, step by step.

Measured before: the fill of the context per step was stored nowhere (the CLM view lives in
memory only), and der_fan_traces - the one row per DER node - was keyed by the WebSocket
session (eval-c47_...-ac8a62), never by the strand's conversation. The corridor's context
band (W3) needs, per node: its conversation and turn, the node's peak input estimate and the
role's window; and per CLM edit: the fill after the edit. Live, the surface needs a tap.

Each test FAILS on the code before this change.
"""
from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from backend.agent import node_executor as ne
from backend.tests.contract.test_memory_api_contract import env  # noqa: F401  (the fixture)


def test_a_node_records_its_peak_input():
    script = [("", [{"id": "c1", "type": "function", "function": {
        "name": "read_file", "arguments": json.dumps({"path": "a.txt"})}}]), ("Done.\nSTATUS: done", [])]
    tools = [{"type": "function", "function": {"name": "read_file", "description": "read",
                                               "parameters": {"type": "object", "properties": {}}}}]
    ctx = ne.NodeContext(generate=lambda role, messages, tools=None, **kw: (lambda t: (t[0], "", t[1]))(script.pop(0)),
                         execute=lambda name, params: {"success": True, "content": "x" * 7000},
                         format_result=lambda name, raw: raw["content"], tools=tools, task="read",
                         conv_id="w2", max_calls=3)
    ne.run_node("Read a.txt", ctx)
    # the second call carries the 7,000-char result: the peak is at least its estimate
    assert int(ctx.stats.get("peak_tokens") or 0) >= 2000


def test_every_clm_edit_carries_the_fill_after_it():
    from backend.tests.behavioral.test_clm_offload_node_behavior import _run

    _seen, _store, events, _result = _run(with_clm=True)
    offloads = [p for label, p in events if label == "OFFLOADED"]
    assert offloads, "the pressure fixture must set something aside"
    assert all(isinstance(p.get("fill"), float) and 0 < p["fill"] < 1.5 for p in offloads), offloads


def test_an_old_trace_table_gains_the_columns_and_the_writer_fills_them():
    from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("CREATE TABLE der_fan_traces (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, session_id TEXT,"
                 " step_id TEXT, tool TEXT, args_hash TEXT, outcome TEXT, u REAL, xi REAL)")   # the old shape
    rec = CaduceanTrajectoryRecorder(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(der_fan_traces)")}
    assert {"conversation_id", "turn_id", "ctx_tokens", "ctx_window"} <= cols
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'idx_ft_conv'").fetchone()
    rec.record_fan_trace(session_id="eval-x-1", step_id="s1", tool="run_python", args_hash="", outcome="VERIFIED",
                         conversation_id="conv-1", turn_id="t1", ctx_tokens=3000, ctx_window=8192)
    from backend.memory.db import app_flush
    app_flush()
    assert conn.execute("SELECT conversation_id, turn_id, ctx_tokens, ctx_window FROM der_fan_traces").fetchone() \
        == ("conv-1", "t1", 3000, 8192)


def test_the_surface_gets_a_live_context_gauge(monkeypatch):
    from backend.utils import memory_live

    monkeypatch.delenv("IRIS_MEMORY_LIVE", raising=False)
    monkeypatch.setattr(memory_live, "_start_drain", lambda: None)
    monkeypatch.setattr(memory_live, "_wake", threading.Event())
    memory_live.reset()
    sent: list = []
    memory_live.set_sender(lambda msg: sent.append(msg) or True)
    try:
        memory_live.context_gauge(conversation_id="conv-1", turn_id="t1", step_id="s1", tokens=4096, window=8192)
        memory_live.flush_once()
    finally:
        memory_live.set_sender(None)
        memory_live.reset()
    msg = next(m for m in sent if m["type"] == "context_gauge")
    g = msg["payload"]["gauges"][0]
    assert (g["conversation_id"], g["step_id"], g["tokens"], g["window"], g["fill"]) == ("conv-1", "s1", 4096, 8192, 0.5)


def test_the_strand_carries_its_context_series_and_the_edits(env):  # noqa: F811
    root = env.ids["root"]
    con = sqlite3.connect(str(env.sq.memory_db_path()))
    con.execute("CREATE TABLE IF NOT EXISTS der_fan_traces (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, session_id TEXT,"
                " step_id TEXT, tool TEXT, args_hash TEXT, outcome TEXT, u REAL, xi REAL, conversation_id TEXT,"
                " turn_id TEXT, ctx_tokens INTEGER, ctx_window INTEGER)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ft_conv ON der_fan_traces(conversation_id)")
    for i, tok in enumerate((1200, 6100, 2500)):
        con.execute("INSERT INTO der_fan_traces (ts, session_id, step_id, tool, outcome, conversation_id, turn_id,"
                    " ctx_tokens, ctx_window) VALUES (?, 'eval-sess', ?, 'read_file', 'VERIFIED', ?, 'T1', ?, 8192)",
                    (1800000000.0 + i, f"s{i + 1}", root, tok))
    from backend.tests.contract.test_memory_api_contract import NOW, _ev

    # inside the fixture's time window (its events start an hour ago; the strand read falls back to it)
    _ev(con, "e-off", NOW - 3600 + 30, "OFFLOADED", root, family="memory",
        payload={"refs": ["tool_result:abc"], "tools": ["read_file"], "saving": 2100,
                 "window": 8192, "fill": 0.41, "secret_text": "never returned"})
    con.commit()
    con.close()
    d = env.client.get(f"/api/memory/strand/{root}").json()
    assert [c["step"] for c in d["context"]] == ["s1", "s2", "s3"]
    assert d["context"][1]["fill"] == round(6100 / 8192, 3) and d["context"][1]["turn"] == "T1"
    off = next(e for e in d["events"] if e["id"] == "e-off")
    assert off["clm"] == {"refs": ["tool_result:abc"], "tools": ["read_file"], "saving": 2100, "window": 8192,
                          "fill": 0.41, "by": None}
    assert all(e["clm"] is None for e in d["events"] if e["label"] != "OFFLOADED")
    # W3's timeline ring: the snapshot's session row carries the strand's peak fill (None when not recorded)
    snap = env.client.get("/api/memory/snapshot").json()
    by_id = {s["id"]: s for s in snap["sessions"]}
    assert by_id[root]["ctx_peak"] == round(6100 / 8192, 3)
    assert all(s["ctx_peak"] is None for s in snap["sessions"] if s["id"] != root)


def test_the_fill_reads_every_context_the_node_ran(monkeypatch):
    """Live finding (wb_gate-20261122-220420): a Workbench code node runs a ctx built with stats={},
    so its peak was never read and every code node wrote no fill. The note takes them all."""
    from types import SimpleNamespace

    from backend.agent.kernel.der.node import _note_context_fill

    # the note also sends a live tap; off here, or it leaves a buffered message (and a drain
    # thread) that another test file's live-tap assertions then receive
    monkeypatch.setenv("IRIS_MEMORY_LIVE", "0")

    kernel = SimpleNamespace(conversation_id="conv-1",
                             resolve_context_window_with_source=lambda role: SimpleNamespace(tokens=8192))
    item = SimpleNamespace(step_id="s1")
    plain, code = SimpleNamespace(stats={}, window=0), SimpleNamespace(stats={"peak_tokens": 3000}, window=0)
    _note_context_fill(kernel, item, [plain, code], "t1")
    assert (item._ctx_tokens, item._ctx_window) == (3000, 8192)
