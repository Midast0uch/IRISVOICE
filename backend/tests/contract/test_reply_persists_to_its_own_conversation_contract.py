"""A WS text turn saves its reply to the turn's OWN conversation.

Live 2026-10-06 (strands): a strand turn ran in `strand-...` (the kernel, the
task card and the user message all named the strand), but the reply was saved
to the thread root `conv-941`, because the save preferred the session's active
mapping, which a reconnect had re-bound. The frame's conversation_id must win;
the mapping is only the fallback for a frame that names no conversation.

Guard: fails on the old order (the mapping first).
"""
from __future__ import annotations

import inspect


def test_the_frame_conversation_wins_over_the_session_mapping():
    from backend.iris_gateway import IRISGateway

    src = inspect.getsource(IRISGateway)
    at = src.index("persisted assistant turn to conv")
    block = src[max(0, at - 2500):at]
    pick = block[block.index("_conv_for_turn = "):]
    assert pick.index('payload.get("conversation_id")') < pick.index("self._active_conversation_id.get(")
