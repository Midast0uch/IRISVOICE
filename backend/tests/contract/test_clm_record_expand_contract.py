"""CT-2 (durable resolver) + CT-3 (expand by reference) + CT-4 (events on the lane)
for the CLM Wave 2 wiring (specs/clm-memory): the kernel's node hooks write a long
tool result to the chat record, the reference resolves to the WHOLE text, and
recall_memory(expand=<ref>) returns it byte for byte, one page at a time, or a
NAMED failure - never an empty block.

Real store in a temp file (IRIS_CONVERSATIONS_DB + reload), the real kernel hook
builder and the real recall_memory expand function.
"""
from __future__ import annotations

import importlib
import time
from types import SimpleNamespace

import pytest


@pytest.fixture()
def cs(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_CONVERSATIONS_DB", str(tmp_path / "conversations.db"))
    import backend.conversation_store as store

    importlib.reload(store)
    yield store
    lane = store._tr_lane()
    deadline = time.monotonic() + 10.0
    while lane.pending() and time.monotonic() < deadline:
        time.sleep(0.01)
    lane.flush(10.0)
    try:
        store._conn.close()
    except Exception:  # noqa: BLE001
        pass


class _Kernel:
    conversation_id = "conv-clm"
    _DER_READ_TOOLS = {"get_rendered_documents"}

    def resolve_context_window_with_source(self, role="reasoning"):
        return SimpleNamespace(tokens=8000, source="test")


def _hooks(monkeypatch, events):
    from backend.agent.kernel import base
    from backend.agent.kernel.der import node

    monkeypatch.setattr(base, "_emit_event",
                        lambda owner, label, **kw: events.append((label, kw.get("payload"))))
    return node._clm_node_hooks(_Kernel(), SimpleNamespace(step_id="s1"), "turn-1")


def test_a_long_result_is_recorded_and_resolves_whole(cs, monkeypatch):
    events = []
    h = _hooks(monkeypatch, events)
    text = "first line\n" + "é" * 9000 + "\nlast line"
    rid = h["record_result"]("read_file", {"path": "big.txt"}, text, 0)
    assert rid
    assert h["ref_readable"](rid) is True          # waits for its own queued write
    row = cs.get_tool_result(rid)
    assert row["content"] == text and row["tool"] == "read_file" and row["target"] == "big.txt"
    assert row["conversation_id"] == "conv-clm" and row["turn_id"] == "turn-1"
    assert h["window"] == 8000


def test_short_results_store_reads_and_expands_are_never_recorded(cs, monkeypatch):
    h = _hooks(monkeypatch, [])
    assert h["record_result"]("read_file", {"path": "a"}, "short", 0) == ""
    assert h["record_result"]("get_rendered_documents", {}, "d" * 9000, 1) == ""
    assert h["record_result"]("recall_memory", {"expand": "x"}, "r" * 9000, 2) == ""


def test_a_cut_row_is_not_readable_for_exact_return(cs, monkeypatch):
    h = _hooks(monkeypatch, [])
    rid = h["record_result"]("read_file", {"path": "huge"}, "h" * (cs.TOOL_RESULT_MAX_CHARS + 10), 0)
    assert rid
    assert h["ref_readable"](rid) is False         # the gate must not offload it


def test_expand_returns_the_exact_text_page_by_page(cs, monkeypatch):
    from backend.agent import tool_bridge as tb

    h = _hooks(monkeypatch, [])
    text = "".join(f"{i:05d}\n" for i in range(3000))   # 18,000 chars, every char distinct by position
    rid = h["record_result"]("run_command", {"command": "ls"}, text, 0)
    assert h["ref_readable"](rid)
    bridge = SimpleNamespace(_active_conversation_id={"s": "conv-clm"})
    got, offset = "", 0
    while True:
        out = tb._expand_tool_result(bridge, "s", {"expand": f"tool_result:{rid}", "offset": offset})
        assert out["success"] and out["chars"] == len(text)
        assert len(out["content"]) <= tb._EXPAND_PAGE_CHARS
        got += out["content"]
        if "next_offset" not in out:
            break
        offset = out["next_offset"]
    assert got == text                              # byte for byte, not a summary


@pytest.mark.parametrize("ref,case", [
    ("tool_result:nope", "not_found"),
    ("chunk:abc", "malformed_ref"),
    ("tool_result:", "malformed_ref"),
])
def test_expand_names_its_failure_and_never_returns_an_empty_block(cs, ref, case):
    from backend.agent import tool_bridge as tb

    out = tb._expand_tool_result(SimpleNamespace(_active_conversation_id={}), "s", {"expand": ref})
    assert out["success"] is False and out["case"] == case and out.get("error")
    assert "content" not in out


def test_expand_emits_restretched_off_the_caller_thread(cs, monkeypatch):
    """CT-4: the event goes through event_emit (the memory-events lane), never
    an inline store write on the caller's thread."""
    from backend.agent import event_emit
    from backend.agent import tool_bridge as tb

    seen = []
    monkeypatch.setattr(event_emit, "emit", lambda owner, label, **kw: seen.append((label, kw)))
    h = _hooks(monkeypatch, [])
    rid = h["record_result"]("read_file", {"path": "x"}, "x" * 4000, 0)
    assert h["ref_readable"](rid)
    tb._expand_tool_result(SimpleNamespace(_active_conversation_id={"s": "conv-clm"}), "s",
                           {"expand": f"tool_result:{rid}"})
    assert [label for label, _ in seen] == ["RESTRETCHED"]
    payload = seen[0][1]["payload"]
    assert payload["ref"] == f"tool_result:{rid}" and "content" not in payload


def test_the_node_event_hook_carries_step_and_turn(cs, monkeypatch):
    events = []
    h = _hooks(monkeypatch, events)
    h["on_clm_event"]("OFFLOADED", {"refs": ["tool_result:a"], "saving": 900})
    assert events == [("OFFLOADED", {"refs": ["tool_result:a"], "saving": 900,
                                     "step": "s1", "turn": "turn-1"})]


def test_the_recall_menu_offers_expand_and_does_not_require_query():
    from backend.agent.kernel.der import node

    full = [{"type": "function", "function": {"name": "recall_memory", "parameters": {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
            {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
    narrowed = [full[1]]                               # the Oracle narrowing dropped recall_memory
    menu = node._clm_recall_menu(narrowed, full)
    rm = next(t for t in menu if t["function"]["name"] == "recall_memory")
    assert "expand" in rm["function"]["parameters"]["properties"]
    assert "query" not in rm["function"]["parameters"]["required"]
    assert full[0]["function"]["parameters"]["required"] == ["query"]   # the source is not mutated
