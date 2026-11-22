"""CLM direct-path offload (requirements "Owner answers" Q-C: the direct chat path gets
offload after TG-2; CLM-2 AC1/AC3/AC4 on that path).

Before: the direct path's history trim dropped the oldest messages with no address -
the blind cut CLM exists to replace. With IRIS_CLM_OFFLOAD=1 the dropped messages leave
ONE placeholder slip naming the chat record (history:<conversation>), OFFLOADED is
emitted, and recall_memory(expand="history:<conversation>") returns the messages from
the chat record, page by page; a forgotten strand expands to `forgotten`.
Flag off: the assembled list is the old one (no slip).
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.agent.context_view import parse_placeholder


def _kernel(monkeypatch):
    from backend.agent.agent_kernel import AgentKernel

    k = AgentKernel.__new__(AgentKernel)
    k._CHARS_PER_TOKEN = 4
    k._DIRECT_CTX_BUDGET = 1500          # tight: the history cannot all fit
    k.session_id = "hist-sess"
    k.conversation_id = "conv-hist"
    k._personality = None
    k._launcher_mode = "personal"
    k._mcm_orch = None
    ep = MagicMock()
    ep.retrieve_context_chunks = MagicMock(return_value=[])
    ep.assemble_episodic_context = MagicMock(return_value="")
    k._memory_interface = MagicMock(episodic=ep)
    return k


HISTORY = [m for i in range(10) for m in (
    {"role": "user", "content": f"Turn {i}: the gateway port is {8000 + i} " + "x" * 400},
    {"role": "assistant", "content": f"Reply {i}: noted " + "y" * 400})]


def _slips(messages):
    return [m for m in messages if parse_placeholder(str(m.get("content") or "")) is not None]


def test_flag_off_the_direct_list_has_no_slip(monkeypatch):
    monkeypatch.delenv("IRIS_CLM_OFFLOAD", raising=False)
    msgs = _kernel(monkeypatch)._assemble_direct_context("what was the first port?", list(HISTORY))
    assert _slips(msgs) == []


def test_dropped_history_leaves_one_slip_and_an_offloaded_event(monkeypatch):
    events = []
    monkeypatch.setattr("backend.agent.event_emit.emit", lambda *a, **k: events.append((a, k)))
    monkeypatch.setenv("IRIS_CLM_OFFLOAD", "1")
    msgs = _kernel(monkeypatch)._assemble_direct_context("what was the first port?", list(HISTORY))
    slips = _slips(msgs)
    assert len(slips) == 1                                            # one slip, not one per message
    ref = parse_placeholder(slips[0]["content"])
    assert (ref.kind, ref.id) == ("history", "conv-hist")
    assert "Turn 0:" not in " ".join(str(m.get("content")) for m in msgs)  # really left the window
    assert [a[1] for a, _k in events] == ["OFFLOADED"]
    assert events[0][1]["payload"]["refs"] == ["history:conv-hist"]


@pytest.fixture()
def cs(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_CONVERSATIONS_DB", str(tmp_path / "conversations.db"))
    import backend.conversation_store as store

    importlib.reload(store)
    yield store
    try:
        store._conn.close()
    except Exception:  # noqa: BLE001
        pass


def test_expand_history_returns_the_messages_from_the_record(cs, monkeypatch):
    from backend.agent import tool_bridge as tb

    monkeypatch.setattr("backend.agent.event_emit.emit", lambda *a, **k: None)
    conv = cs.create_conversation("history expand")
    cid = conv["id"] if isinstance(conv, dict) else conv
    for m in HISTORY[:4]:
        cs.add_message(cid, m["role"], m["content"])
    bridge = SimpleNamespace(_active_conversation_id={},
                             _memory_interface=SimpleNamespace(episodic=None))
    page = tb._expand_tool_result(bridge, "s", {"expand": f"history:{cid}"})
    assert page["success"] and page["messages"] == 4
    assert "gateway port is 8000" in page["content"]                  # the oldest turn, whole
    past = tb._expand_tool_result(bridge, "s", {"expand": f"history:{cid}", "offset": 4})
    assert past["success"] is False and past["case"] == "not_found"
    monkeypatch.setattr(tb, "_strand_forgotten", lambda b, c: c == cid)
    gone = tb._expand_tool_result(bridge, "s", {"expand": f"history:{cid}"})
    assert gone["case"] == "forgotten" and "content" not in gone
