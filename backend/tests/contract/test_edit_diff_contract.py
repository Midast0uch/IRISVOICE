"""Contract: every agent file edit carries a diff, and the diff can be undone.

Plain words: when the agent changes a file, the chat must be able to show WHAT
changed (a ``±`` per edit, reviewed hunk by hunk) and the user must be able to
take it back. Taking it back must never overwrite newer work, and it must tell
IRIS the change was not wanted. This file pins each seam:

  bridge chokepoint -> tool result ``diff`` -> step -> ``tool:result`` event
  -> turn ``tool_result`` part -> ``diff_undo`` -> file restored -> IRIS told.

The tests drive the real file server through the real bridge dispatch
(``AgentToolBridge.execute_mcp_tool``), the real ``_der_finalize_step`` emit and
the real gateway handler. They fail on the code before this change (no ``diff``
key, no ``edit_diffs`` module, no ``diff_undo`` route).
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from backend.agent import edit_diffs
from backend.agent.tool_bridge import AgentToolBridge
from backend.mcp.builtin_servers import FileManagerServer

SESSION = "sess-diff"
CONV = "conv-diff"


@pytest.fixture(autouse=True)
def _fresh_ledger():
    edit_diffs.clear_ledger_for_testing()
    yield
    edit_diffs.clear_ledger_for_testing()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _bridge():
    """A bridge with the REAL file_manager server behind it (no stub that cannot fail)."""
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    bridge._mcp_servers = {"file_manager": FileManagerServer()}
    bridge._security_filter = None
    bridge._audit_logger = None
    bridge._session_workdirs = {}
    bridge._active_conversation_id = {SESSION: CONV}
    return bridge


def _call(tool, params, bridge=None):
    bridge = bridge or _bridge()
    return _run(bridge.execute_mcp_tool("file_manager", tool, params, SESSION))


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def _numbered(n, mark=None):
    return "".join(f"line {i}{mark if mark and i % 100 == 0 else ''}\n" for i in range(1, n + 1))


# ── 1. the chokepoint: a diff on every edit ─────────────────────────────────

def test_edit_file_through_dispatch_carries_a_diff(tmp_path):
    p = tmp_path / "a.txt"
    _write(p, "one\ntwo\nthree\nfour\nfive\n")
    res = _call("edit_file", {"path": str(p), "old": "three", "new": "THREE"})
    assert res["success"] is True, res
    d = res["diff"]
    assert set(d) >= {"diff_id", "path", "added", "removed", "hunks", "truncated", "undoable"}
    assert d["path"] == str(p)
    assert (d["added"], d["removed"]) == (1, 1)
    assert d["truncated"] is False and d["undoable"] is True
    assert len(d["hunks"]) == 1
    h = d["hunks"][0]
    assert h["header"] == "@@ -1,5 +1,5 @@"
    assert h["lines"] == [" one", " two", "-three", "+THREE", " four", " five"]


def test_write_file_new_file_and_overwrite_each_carry_a_diff(tmp_path):
    p = tmp_path / "new.txt"
    res = _call("write_file", {"path": str(p), "content": "a\nb\n"})
    assert res["success"] is True
    assert res["diff"]["new_file"] is True
    assert (res["diff"]["added"], res["diff"]["removed"]) == (2, 0)
    assert res["diff"]["hunks"][0]["lines"] == ["+a", "+b"]

    res2 = _call("write_file", {"file_path": str(p), "contents": "a\nc\n"})
    assert res2["success"] is True
    assert res2["diff"]["new_file"] is False
    assert (res2["diff"]["added"], res2["diff"]["removed"]) == (1, 1)


def test_relative_path_is_diffed_at_the_anchored_path(tmp_path):
    """The diff path is the file the tool really wrote (the session workdir anchor)."""
    bridge = _bridge()
    bridge._session_workdirs = {SESSION: str(tmp_path)}
    _write(tmp_path / "rel.txt", "x\n")
    res = _call("edit_file", {"path": "rel.txt", "old": "x", "new": "y"}, bridge)
    assert res["diff"]["path"] == os.path.join(str(tmp_path), "rel.txt")


def test_failed_python_edit_still_reports_the_change(tmp_path):
    """An edit the tool flags as failed ("no longer compiles") DID change the file."""
    p = tmp_path / "m.py"
    _write(p, "x = 1\n")
    res = _call("edit_file", {"path": str(p), "old": "x = 1", "new": "x = ("})
    assert res["success"] is False and res.get("written") is True
    assert res["diff"]["added"] == 1 and res["diff"]["removed"] == 1


def test_no_diff_when_nothing_changed_or_the_edit_was_refused(tmp_path):
    p = tmp_path / "same.txt"
    _write(p, "keep\n")
    assert "diff" not in _call("write_file", {"path": str(p), "content": "keep\n"})
    refused = _call("edit_file", {"path": str(p), "old": "absent", "new": "x"})
    assert refused["success"] is False and "diff" not in refused
    assert "diff" not in _call("read_file", {"path": str(p)})


def test_binary_file_has_no_diff(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"\x00\x01\x02 old")
    res = _call("write_file", {"path": str(p), "content": "text now"})
    assert res["success"] is True and "diff" not in res


# ── 2. bounds ───────────────────────────────────────────────────────────────

def test_diff_is_capped_at_400_lines_and_64kb(tmp_path):
    p = tmp_path / "big.txt"
    _write(p, "".join(f"old {i}\n" for i in range(1500)))
    res = _call("write_file", {"path": str(p), "content": "".join(f"new {i}\n" for i in range(1500))})
    d = res["diff"]
    shown = sum(len(h["lines"]) for h in d["hunks"])
    assert d["truncated"] is True
    assert shown <= edit_diffs.MAX_DIFF_LINES == 400
    assert (d["added"], d["removed"]) == (1500, 1500), "counts stay true when the lines are cut"

    wide = tmp_path / "wide.txt"
    _write(wide, "x\n")
    res2 = _call("write_file", {"path": str(wide), "content": "".join("y" * 900 + "\n" for _ in range(300))})
    d2 = res2["diff"]
    assert d2["truncated"] is True
    assert sum(len(r) + 1 for h in d2["hunks"] for r in h["lines"]) <= edit_diffs.MAX_DIFF_BYTES == 64 * 1024


def test_preimage_over_2mb_is_diffed_but_not_undoable(tmp_path):
    p = tmp_path / "huge.txt"
    _write(p, ("z" * 99 + "\n") * 25000 + "tail\n")  # ~2.5 MB
    assert os.path.getsize(p) > edit_diffs.MAX_PREIMAGE_BYTES == 2 * 1024 * 1024
    res = _call("edit_file", {"path": str(p), "old": "tail", "new": "TAIL"})
    d = res["diff"]
    assert d["hunks"] and d["undoable"] is False
    out = edit_diffs.undo(d["diff_id"])
    assert out["ok"] is False and "too large" in out["reason"]
    assert _read(p).endswith("TAIL\n"), "a refused undo leaves the file alone"


def test_file_over_8mb_gets_a_stub_not_a_read(tmp_path):
    p = tmp_path / "giant.txt"
    with open(p, "wb") as f:
        f.truncate(edit_diffs.MAX_READ_BYTES + 10)
    snap = edit_diffs.snapshot(str(p))
    assert snap.too_big and snap.data is None
    with open(p, "ab") as f:
        f.write(b"more")
    d = edit_diffs.record_after(snap, SESSION, CONV)
    assert d["hunks"] == [] and d["truncated"] is True and d["undoable"] is False


def test_ledger_is_bounded_in_count_and_bytes(tmp_path):
    p = tmp_path / "n.txt"
    _write(p, "0\n")
    ids = []
    for i in range(1, 251):
        ids.append(_call("write_file", {"path": str(p), "content": f"{i}\n"})["diff"]["diff_id"])
    st = edit_diffs.ledger_stats()
    assert st["diffs"] == edit_diffs.LEDGER_MAX_DIFFS == 200
    assert edit_diffs.undo(ids[0])["ok"] is False, "the oldest was evicted"
    assert edit_diffs.undo(ids[-1])["ok"] is True, "the newest is kept"

    edit_diffs.clear_ledger_for_testing()
    q = tmp_path / "mb.txt"
    body = ("m" * 99 + "\n") * 10000  # ~1 MB kept as the pre-image of every edit
    for i in range(80):
        _write(q, body)
        _call("edit_file", {"path": str(q), "old": "m" * 99, "new": f"c{i:03d}" + "m" * 94})
    assert edit_diffs.ledger_stats()["bytes"] <= edit_diffs.LEDGER_MAX_BYTES == 64 * 1024 * 1024
    assert edit_diffs.ledger_stats()["diffs"] < 80, "bytes forced an eviction"


# ── 3. undo: whole file ─────────────────────────────────────────────────────

def test_whole_file_undo_restores_the_exact_bytes(tmp_path):
    p = tmp_path / "crlf.txt"
    original = "a\r\nb\r\nc\r\n"
    _write(p, original)
    d = _call("edit_file", {"path": str(p), "old": "b", "new": "B"})["diff"]
    assert _read(p) == "a\r\nB\r\nc\r\n"
    out = edit_diffs.undo(d["diff_id"])
    assert out["ok"] is True
    assert _read(p) == original, "line endings and content come back exactly"
    again = edit_diffs.undo(d["diff_id"])
    assert again["ok"] is False and "already" in again["reason"]


def test_whole_file_undo_refuses_when_the_file_changed_since(tmp_path):
    p = tmp_path / "drift.txt"
    _write(p, "one\ntwo\n")
    d = _call("edit_file", {"path": str(p), "old": "one", "new": "ONE"})["diff"]
    _write(p, "ONE\ntwo\nthe user typed this\n")
    out = edit_diffs.undo(d["diff_id"])
    assert out["ok"] is False
    assert "changed" in out["reason"]
    assert _read(p) == "ONE\ntwo\nthe user typed this\n", "never clobbers newer work"


def test_undo_of_a_new_file_removes_it_and_refuses_after_drift(tmp_path):
    p = tmp_path / "made.txt"
    d = _call("write_file", {"path": str(p), "content": "hello\n"})["diff"]
    assert edit_diffs.undo(d["diff_id"])["ok"] is True
    assert not p.exists()

    q = tmp_path / "made2.txt"
    d2 = _call("write_file", {"path": str(q), "content": "hello\n"})["diff"]
    _write(q, "hello\nmore\n")
    assert edit_diffs.undo(d2["diff_id"])["ok"] is False
    assert q.exists()


def test_unknown_diff_id_is_refused_with_a_reason():
    out = edit_diffs.undo("does-not-exist")
    assert out["ok"] is False and out["reason"]


# ── 4. undo: one hunk ───────────────────────────────────────────────────────

def _two_hunk_edit(tmp_path):
    p = tmp_path / "two.txt"
    base = _numbered(60)
    _write(p, base)
    new = base.replace("line 5\n", "LINE FIVE\n").replace("line 50\n", "LINE FIFTY\n")
    d = _call("write_file", {"path": str(p), "content": new})["diff"]
    assert len(d["hunks"]) == 2
    return p, base, new, d


def test_single_hunk_undo_reverts_only_that_hunk(tmp_path):
    p, base, new, d = _two_hunk_edit(tmp_path)
    out = edit_diffs.undo(d["diff_id"], 1)
    assert out["ok"] is True and out["hunk_index"] == 1
    text = _read(p)
    assert "line 50\n" in text and "LINE FIFTY" not in text
    assert "LINE FIVE\n" in text, "the other hunk stays"
    out0 = edit_diffs.undo(d["diff_id"], 0)
    assert out0["ok"] is True
    assert _read(p) == base


def test_hunk_undo_then_whole_undo_returns_to_the_original(tmp_path):
    p, base, new, d = _two_hunk_edit(tmp_path)
    assert edit_diffs.undo(d["diff_id"], 0)["ok"] is True
    assert edit_diffs.undo(d["diff_id"])["ok"] is True, "the file is still as IRIS left it"
    assert _read(p) == base


def test_hunk_undo_finds_its_lines_after_an_earlier_hunk_moved_them(tmp_path):
    p = tmp_path / "shift.txt"
    base = _numbered(60)
    _write(p, base)
    new = base.replace("line 5\n", "five a\nfive b\nfive c\n").replace("line 50\n", "LINE FIFTY\n")
    d = _call("write_file", {"path": str(p), "content": new})["diff"]
    assert edit_diffs.undo(d["diff_id"], 0)["ok"] is True  # shrinks the file by 2 lines
    assert edit_diffs.undo(d["diff_id"], 1)["ok"] is True
    assert _read(p) == base


def test_hunk_undo_refuses_when_its_lines_drifted(tmp_path):
    p, base, new, d = _two_hunk_edit(tmp_path)
    _write(p, new.replace("LINE FIFTY\n", "the user rewrote this\n"))
    out = edit_diffs.undo(d["diff_id"], 1)
    assert out["ok"] is False and "no longer match" in out["reason"]
    assert "the user rewrote this" in _read(p)
    assert edit_diffs.undo(d["diff_id"], 0)["ok"] is True, "an untouched hunk can still go"


def test_hunk_undo_rejects_a_bad_index_and_a_second_undo(tmp_path):
    p, base, new, d = _two_hunk_edit(tmp_path)
    assert edit_diffs.undo(d["diff_id"], 7)["ok"] is False
    assert edit_diffs.undo(d["diff_id"], -1)["ok"] is False
    assert edit_diffs.undo(d["diff_id"], 0)["ok"] is True
    again = edit_diffs.undo(d["diff_id"], 0)
    assert again["ok"] is False and "already" in again["reason"]


def test_hunk_undo_keeps_crlf(tmp_path):
    p = tmp_path / "crlf2.txt"
    base = "".join(f"l{i}\r\n" for i in range(40))
    _write(p, base)
    d = _call("write_file", {"path": str(p), "content": base.replace("l3\r\n", "L3\r\n").replace("l30\r\n", "L30\r\n")})["diff"]
    assert edit_diffs.undo(d["diff_id"], 1)["ok"] is True
    assert _read(p) == base.replace("l3\r\n", "L3\r\n")


# ── 5. the diff reaches the event, the turn part and the chat ───────────────

class _Item:
    step_id = "s1"
    step_number = 1
    description = "edit the file"
    tool = "edit_file"
    expected_output = None
    result = "ok"
    is_subloop = False


def _finalize(item, bus):
    from backend.agent import agent_kernel

    kernel = MagicMock()
    kernel.conversation_id = CONV
    kernel.resolve_context_window.return_value = 8000
    kernel._memory_interface = None
    kernel._mcm_orch = None
    kernel._der_last_u_mag = 0.0
    kernel._card_envelope.return_value = {}
    kernel._verify_step_result.return_value = "VERIFIED"
    queue = MagicMock()
    queue.failed_ids = []
    with patch("backend.agent.event_bus.get_event_bus", return_value=bus):
        agent_kernel.AgentKernel._der_finalize_step.__get__(kernel, agent_kernel.AgentKernel)(
            item=item, step_result="edited", step_success=True, step_outputs=[], completed_items=[],
            _tokens_used=0, _token_budget=50000, _session=SESSION, _turn_id="t1", _phase=0,
            is_mature=False, _live_ctx=None, plan=None, context_package=None, queue=queue,
            verdict=MagicMock(),
        )


def _tool_result_data(bus):
    from backend.agent.event_bus import IRISStreamEvent

    calls = [c for c in bus.emit.call_args_list if c.args and c.args[0] == IRISStreamEvent.TOOL_RESULT]
    assert calls, "no tool:result was emitted"
    return calls[0].kwargs["data"]


def test_the_step_carries_the_bridge_diff_onto_its_tool_result_event(tmp_path):
    from backend.agent import agent_kernel
    from backend.agent.der_loop import QueueItem
    from backend.agent.tool_decision import DispatchResult

    p = tmp_path / "ev.txt"
    _write(p, "a\nb\n")
    raw = _call("edit_file", {"path": str(p), "old": "a", "new": "A"})
    diff = raw["diff"]

    item = QueueItem(step_id="s1", step_number=1, description="edit", tool="edit_file")
    dr = DispatchResult(success=True, result=raw)
    kernel = MagicMock()
    kernel.conversation_id = CONV
    agent_kernel.AgentKernel._der_after_call.__get__(kernel, agent_kernel.AgentKernel)(
        item, "edit_file", {"path": str(p)}, dr, SESSION, "t1", capture=False,
    )
    assert "diff" not in raw, "the model and the step text never read the diff"
    assert item.edit_diffs == [diff]
    assert "diff" not in agent_kernel.AgentKernel._format_tool_result_for_step(raw, "edit_file")

    bus = MagicMock()
    _finalize(item, bus)
    data = _tool_result_data(bus)
    assert data["diff"] == diff
    assert "diffs" not in data, "one edit: only `diff`"
    # the other fields are unchanged
    assert data["tool_name"] == "edit_file" and data["step_number"] == 1 and data["task_id"] == "t1"


def test_a_step_with_two_edits_lists_both(tmp_path):
    from backend.agent.der_loop import QueueItem

    item = QueueItem(step_id="s1", step_number=1, description="edit", tool=None)
    item.edit_diffs = [{"diff_id": "d1"}, {"diff_id": "d2"}]
    bus = MagicMock()
    _finalize(item, bus)
    data = _tool_result_data(bus)
    assert data["diff"] == {"diff_id": "d2"}
    assert data["diffs"] == [{"diff_id": "d1"}, {"diff_id": "d2"}]


def test_a_step_without_edits_adds_no_diff_fields():
    from backend.agent.der_loop import QueueItem

    bus = MagicMock()
    _finalize(QueueItem(step_id="s1", step_number=1, description="read", tool="read_file"), bus)
    data = _tool_result_data(bus)
    assert "diff" not in data and "diffs" not in data


def test_the_turn_tool_result_part_carries_the_diff(tmp_path):
    from backend.agent.turn_protocol import TurnEmitter, route_bus_event

    sent = []
    em = TurnEmitter(sent.append, turn_id="t-part", conversation_id=CONV)
    em.start()
    try:
        diff = {"diff_id": "d9", "path": "x", "added": 1, "removed": 0, "hunks": [], "truncated": False, "undoable": True}
        assert route_bus_event("tool:result", {"task_id": "t-part", "tool_name": "edit_file", "diff": diff},
                               turn_id="t-part", conversation_id=CONV)
        part = [m for m in sent if m["type"] == "turn.part"][-1]["payload"]["part"]
        assert part["type"] == "tool_result" and part["data"]["diff"] == diff
    finally:
        em.end("ok")


def test_a_card_free_turn_still_shows_the_edit_diff_in_its_turn():
    """The card bound withholds tool:result for a small turn. An edit's ± must still
    reach the turn (and no legacy card frame may go out, or a phantom card appears)."""
    from backend.agent.artifact_policy import clear_card_gate_for_testing, suppress_card_for_turn
    from backend.agent.event_bus import IRISStreamEvent, get_event_bus
    from backend.agent.turn_protocol import TurnEmitter
    from backend.agent.ws_event_bridge import WSEventBridge

    clear_card_gate_for_testing()
    suppress_card_for_turn("t-free")
    sent = []
    em = TurnEmitter(sent.append, turn_id="t-free", conversation_id=CONV)
    em.start()
    ws = MagicMock()
    bridge = WSEventBridge(ws)
    loop = asyncio.new_event_loop()
    scheduled = []
    try:
        with patch("backend.agent.ws_event_bridge.asyncio.run_coroutine_threadsafe",
                   lambda coro, lp: (scheduled.append(coro), MagicMock())[1]):
            bridge.set_main_loop(loop)
            bridge.start()
            diff = {"diff_id": "dfree", "path": "f", "added": 1, "removed": 1, "hunks": [], "truncated": False, "undoable": True}
            get_event_bus().emit(IRISStreamEvent.TOOL_RESULT, data={"task_id": "t-free", "diff": diff},
                                 turn_id="t-free", conversation_id=CONV, session_id=SESSION)
            get_event_bus().emit(IRISStreamEvent.TOOL_RESULT, data={"task_id": "t-free", "tool_name": "read_file"},
                                 turn_id="t-free", conversation_id=CONV, session_id=SESSION)
        for coro in scheduled:
            coro.close()
        assert scheduled == [], "the legacy tool:result frame stays withheld"
        parts = [m["payload"]["part"] for m in sent if m["type"] == "turn.part"]
        results = [p for p in parts if p["type"] == "tool_result"]
        assert len(results) == 1 and results[0]["data"]["diff"] == diff, "only the diff rides the turn"
    finally:
        bridge.stop()
        loop.close()
        em.end("ok")
        clear_card_gate_for_testing()


# ── 6. the gateway message and "tells IRIS" ─────────────────────────────────

def _gateway():
    from backend.iris_gateway import IRISGateway

    gw = IRISGateway.__new__(IRISGateway)
    gw._logger = MagicMock()
    gw._ws_manager = MagicMock()
    sent = []

    async def _send(client_id, message):
        sent.append(message)
        return True

    gw._ws_manager.send_to_client = _send
    return gw, sent


class _Memory:
    def __init__(self):
        self.messages = []

    def add_message(self, role, content, *a, **k):
        self.messages.append({"role": role, "content": content})

    def get_context(self, max_messages=None):
        return list(self.messages)


@pytest.fixture
def live_kernel():
    """A live kernel for the conversation, with a real in-memory conversation window."""
    mod = sys.modules.get("backend.agent.agent_kernel")
    if mod is None:
        import backend.agent.agent_kernel as mod  # noqa: F401
        mod = sys.modules["backend.agent.agent_kernel"]
    mem = _Memory()
    kernel = types.SimpleNamespace(_conversation_memory=mem, session_id=SESSION, _memory_interface=None)
    instances = getattr(mod, "_agent_kernel_instances")
    had = CONV in instances
    old = instances.get(CONV)
    instances[CONV] = kernel
    try:
        yield mem
    finally:
        if had:
            instances[CONV] = old
        else:
            instances.pop(CONV, None)


def _undo_msg(diff_id, hunk_index=None):
    payload = {"diff_id": diff_id}
    if hunk_index is not None:
        payload["hunk_index"] = hunk_index
    return {"type": "diff_undo", "payload": payload}


def test_diff_undo_message_restores_the_file_and_replies(tmp_path, live_kernel):
    p = tmp_path / "gw.txt"
    _write(p, "keep\nold\n")
    d = _call("edit_file", {"path": str(p), "old": "old", "new": "new"})["diff"]
    gw, sent = _gateway()
    _run(gw._handle_diff_undo(SESSION, "client-1", _undo_msg(d["diff_id"])))
    assert _read(p) == "keep\nold\n"
    reply = sent[-1]
    assert reply["type"] == "diff_undo_result"
    assert reply["payload"]["diff_id"] == d["diff_id"]
    assert reply["payload"]["hunk_index"] is None and reply["payload"]["ok"] is True


def test_diff_undo_message_refuses_with_a_reason_on_drift(tmp_path, live_kernel):
    p = tmp_path / "gw2.txt"
    _write(p, "a\nb\n")
    d = _call("edit_file", {"path": str(p), "old": "a", "new": "A"})["diff"]
    _write(p, "A\nb\nnewer\n")
    gw, sent = _gateway()
    _run(gw._handle_diff_undo(SESSION, "client-1", _undo_msg(d["diff_id"])))
    pl = sent[-1]["payload"]
    assert pl["ok"] is False and "changed" in pl["reason"]
    assert _read(p) == "A\nb\nnewer\n"
    assert live_kernel.messages == [], "a refused undo tells IRIS nothing"


def test_diff_undo_message_validates_its_payload():
    gw, sent = _gateway()
    _run(gw._handle_diff_undo(SESSION, "c", {"type": "diff_undo", "payload": {}}))
    assert sent[-1]["payload"]["ok"] is False
    _run(gw._handle_diff_undo(SESSION, "c", {"type": "diff_undo", "payload": {"diff_id": "x", "hunk_index": "1"}}))
    assert sent[-1]["payload"]["ok"] is False


def test_diff_undo_is_routed_and_does_not_wait_behind_the_running_turn():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    with open(os.path.join(root, "backend", "iris_gateway.py"), encoding="utf-8") as f:
        gateway_src = f.read()
    with open(os.path.join(root, "backend", "main.py"), encoding="utf-8") as f:
        main_src = f.read()
    assert 'msg_type == "diff_undo"' in gateway_src
    import re

    m = re.search(r"^_UNLOCKED_FRAMES\s*=\s*\{([^}]*)\}", main_src, re.M)
    assert m and '"diff_undo"' in m.group(1), "the undo must bypass the per-session turn lock"


def test_a_successful_undo_tells_iris_where_the_next_turn_reads(tmp_path, live_kernel):
    p = tmp_path / "tell.txt"
    _write(p, "x\ny\n")
    d = _call("edit_file", {"path": str(p), "old": "x", "new": "X"})["diff"]
    gw, sent = _gateway()
    emitted = []
    with patch("backend.agent.event_emit.emit", lambda *a, **k: emitted.append((a, k))):
        _run(gw._handle_diff_undo(SESSION, "client-1", _undo_msg(d["diff_id"])))
    ctx = live_kernel.get_context()
    assert len(ctx) == 1 and ctx[0]["role"] == "system"
    note = ctx[0]["content"]
    assert str(p) in note and "did not want" in note and "again" in note
    assert sent[-1]["payload"]["told_iris"] is True
    assert emitted and emitted[0][0][1] == "CORRECTION" and emitted[0][1]["evidence"] == "user"


def test_a_hunk_undo_tells_iris_which_change(tmp_path, live_kernel):
    p, base, new, d = _two_hunk_edit(tmp_path)
    gw, sent = _gateway()
    with patch("backend.agent.event_emit.emit", lambda *a, **k: None):
        _run(gw._handle_diff_undo(SESSION, "client-1", _undo_msg(d["diff_id"], 1)))
    note = live_kernel.get_context()[0]["content"]
    assert "one change near line 50" in note and str(p) in note
