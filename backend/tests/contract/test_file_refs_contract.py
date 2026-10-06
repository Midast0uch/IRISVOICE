"""Contract: a `file:<path>` ref in a text_message payload reaches the agent as an address.

Boundary pinned (composer -> gateway -> agent): the composer's "#" picks project files and
sends `refs: ["file:backend/router.py", ...]`. The gateway must hand the agent those
ADDRESSES as one per-turn system block ("[Referenced files]"), never the file content, so the
agent can read them with its own file tools. A ref that is not a file (a task card, an
artifact, a strand) adds no such line. The block is bounded (count and path length).

Before this change `refs` only reached `turn.start.refs` (the UI); the agent never saw them.

The gateway handler is driven for real (`_handle_chat`, text_message); only the agent kernel,
the socket manager and the stores around it are stand-ins, because what is pinned is the
payload -> `process_text_message(card_context=...)` hand-off.
"""

import asyncio
import logging.handlers
from unittest.mock import AsyncMock, MagicMock

import pytest

# backend/core/logging_config.py imports ShareableRotatingFileHandler from
# backend.monitoring.structured_logger, which no committed file defines, so importing the
# gateway fails on a clean checkout (pre-existing). Bridge it here only when it is missing.
import backend.monitoring.structured_logger as _sl

if not hasattr(_sl, "ShareableRotatingFileHandler"):
    _sl.ShareableRotatingFileHandler = logging.handlers.RotatingFileHandler

import backend.iris_gateway as gw_mod  # noqa: E402

SESSION = "sess_file_refs"
CLIENT = "client_file_refs"
CONV = "conv_file_refs"


def _run_turn(monkeypatch, payload_extra):
    """Send one text_message through the gateway; return what the agent was handed."""
    seen = {}

    class _Kernel:
        _tool_bridge = object()
        _pending_thinking = ""
        _last_spoken_text = "ok"
        _selected_reasoning_model = "stub"

        def process_text_message(self, text, **kw):
            seen["text"] = text
            seen["card_context"] = kw.get("card_context")
            return "done"

        def prepare_spoken_text(self, response, text):
            return "ok"

    monkeypatch.setattr(gw_mod, "get_agent_kernel", lambda *a, **k: _Kernel())

    ws = MagicMock()
    ws.send_to_client = AsyncMock(return_value=True)
    ws.broadcast_to_session = AsyncMock(return_value=None)
    ws.buffer_message = MagicMock()

    gw = gw_mod.IRISGateway.__new__(gw_mod.IRISGateway)
    gw._logger = MagicMock()
    gw._ws_manager = ws
    gw._active_conversation_id = {}
    gw._main_loop = None
    gw._chat_heartbeat = AsyncMock(return_value=None)

    payload = {"text": "look at it", "conversation_id": CONV, "mode": "developer"}
    payload.update(payload_extra)
    asyncio.run(gw._handle_chat(SESSION, CLIENT, {"type": "text_message", "payload": payload}))
    assert "card_context" in seen, "the turn never reached the agent kernel"
    return seen["card_context"]


def test_a_file_ref_reaches_the_agent_as_an_address(monkeypatch):
    ctx = _run_turn(monkeypatch, {"refs": ["file:backend/router.py", "file:./IRISVOICE"]})
    assert ctx is not None and ctx.startswith("[Referenced files]")
    assert "file:backend/router.py" in ctx.splitlines()
    assert "file:./IRISVOICE" in ctx.splitlines()


def test_a_ref_that_is_not_a_file_adds_no_files_line(monkeypatch):
    ctx = _run_turn(monkeypatch, {"refs": ["#T-38", "#strand_plan", "#A-12"]})
    assert ctx is None or "[Referenced files]" not in ctx


def test_file_and_other_refs_together_list_only_the_files(monkeypatch):
    ctx = _run_turn(monkeypatch, {"refs": ["#T-38", "file:src/a.py", "#A-12"]})
    assert ctx.splitlines()[1:] == ["file:src/a.py"]


def test_the_block_is_bounded_and_has_no_content(monkeypatch):
    too_many = [f"file:src/f{i}.py" for i in range(gw_mod._MAX_FILE_REFS + 9)]
    too_long = "file:" + "x" * (gw_mod._MAX_FILE_REF_PATH + 1)
    ctx = _run_turn(monkeypatch, {"refs": [too_long, *too_many, "file:src/f0.py"]})
    lines = ctx.splitlines()[1:]
    assert len(lines) == gw_mod._MAX_FILE_REFS  # count bound; the duplicate and the long path dropped
    assert lines[0] == "file:src/f0.py"
    assert all(len(l) <= len("file:") + gw_mod._MAX_FILE_REF_PATH for l in lines)


@pytest.mark.parametrize("bad", [None, "file:x.py", {"a": "file:x.py"}, [None, 3, "file:", "file:  "]])
def test_a_malformed_refs_field_adds_nothing(monkeypatch, bad):
    ctx = _run_turn(monkeypatch, {"refs": bad})
    assert ctx is None
