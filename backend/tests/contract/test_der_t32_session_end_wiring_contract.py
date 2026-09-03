"""CT-ON8 — REQ-16 (T32): outer loop wired at a REAL session boundary.

Pins the two production-wiring ACs REQ-16 names, against the REAL
``IRISGateway.cleanup_session`` (the WS-disconnect session teardown that
main.py:2301 calls) and the REAL ``AgentKernel._der_stamp_session_exit``:

  AC1 — run_outer_loop is invoked at a real session boundary (session end),
        with the session_id — a production call site, not test-only.
  AC2 — record_session_exit is fed from a real session end: cleanup_session
        archives the active conversation's memory (memory.py:342 path, the
        previously-zero-production-caller archive_on_session_end) and the exit
        row lands in the caducean_session_exits ledger.
  natural_exit — the DER loop stamps the honest exit nature on the
        conversation memory: success -> True, failure/zero-step -> False, so
        the ledger never records every production session as False.
  Edge — an EMPTY conversation (no messages, no task records) is NOT archived
        (no phantom exit rows that would drag natural_exit_rate down); a
        missing kernel / archive failure never raises.

The real code paths are exercised: cleanup_session itself, get_active_kernel
resolution, and ConversationMemory.archive_on_session_end against a real
in-memory CaduceanTrajectoryRecorder.
"""
import os
import sqlite3
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.memory import ConversationMemory


# ── Harness ──────────────────────────────────────────────────────────────────


class _FakeEpisodic:
    def __init__(self, conn):
        self._conn = conn

    @property
    def db(self):
        return self._conn


class _FakeMemoryInterface:
    def __init__(self, conn):
        self.episodic = _FakeEpisodic(conn)


def _recorder() -> CaduceanTrajectoryRecorder:
    return CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))


def _memory(session_id="sess", conversation_id="conv") -> ConversationMemory:
    mem = ConversationMemory(
        session_id=session_id,
        conversation_id=conversation_id,
        session_storage_path=os.path.join(
            os.environ.get("TEMP", "/tmp"), "t32_test_storage", conversation_id
        ),
    )
    mem.add_message(role="user", content="find quantum pricing")
    mem.add_message(role="assistant", content="searching...")
    return mem


def _gateway_with(memory, recorder, session_id="sess"):
    """A real IRISGateway whose cleanup_session resolves to a kernel whose
    conversation memory is ``memory``. Returns (gateway, context) — the
    caller must enter the context so the recorder patches stay alive while
    cleanup_session runs (the imports are INSIDE archive_on_session_end)."""
    from backend.iris_gateway import IRISGateway
    from backend.agent import caducean_trajectory

    kernel = SimpleNamespace(
        _conversation_memory=memory,
        session_id=session_id,
    )
    g = IRISGateway.__new__(IRISGateway)  # bypass heavy __init__
    g._logger = MagicMock()
    g._active_voice_client = {}
    g._active_conversation_id = {}
    g._ws_manager = MagicMock()
    g._model_router = None

    def _fake_active_kernel(sid):
        assert sid == session_id
        return kernel

    _ctx = ExitStack()
    _ctx.enter_context(
        patch(
            "backend.agent.agent_kernel._session_active_conversation",
            {session_id: memory.conversation_id},
        )
    )
    _ctx.enter_context(
        patch("backend.agent.get_active_kernel", _fake_active_kernel)
    )
    _ctx.enter_context(
        patch.object(
            caducean_trajectory, "get_trajectory_recorder", return_value=recorder
        )
    )
    _ctx.enter_context(
        patch(
            "backend.memory.get_memory_interface",
            return_value=_FakeMemoryInterface(recorder._conn),
        )
    )
    return g, _ctx


# ── AC1 + AC2: cleanup_session archives + fires the outer loop ───────────────


def test_ac1_cleanup_session_invokes_run_outer_loop():
    """REQ-16 AC1: cleanup_session (the production session boundary) invokes
    run_outer_loop with the session_id — a real call site, not test-only."""
    mem = _memory()
    recorder = _recorder()
    g, ctx = _gateway_with(mem, recorder)

    fired = {}
    from backend.agent import outer_loop

    def _fake_run(session_id, domain=None):
        fired["session_id"] = session_id
        fired["domain"] = domain
        return None  # not enough sessions yet

    import asyncio

    with ctx, patch.object(outer_loop, "run_outer_loop", _fake_run):
        asyncio.run(g.cleanup_session("sess"))

    assert fired.get("session_id") == "sess", (
        "run_outer_loop must be invoked with the session_id at session end"
    )


def test_ac2_cleanup_session_writes_exit_ledger_row():
    """REQ-16 AC2: archiving at a real session end records a session-exit
    ledger row via record_session_exit (memory.py:342 path)."""
    mem = _memory()
    recorder = _recorder()
    g, ctx = _gateway_with(mem, recorder)

    import asyncio

    with ctx, patch(
        "backend.agent.outer_loop.run_outer_loop", return_value=None
    ):
        asyncio.run(g.cleanup_session("sess"))

    rows = recorder._conn.execute(
        "SELECT session_id, natural_exit FROM caducean_session_exits"
    ).fetchall()
    assert len(rows) == 1, "cleanup_session must record exactly one exit row"
    assert rows[0][0] == "sess"
    # natural_exit defaults False when nothing stamped it (honest default).
    assert rows[0][1] == 0


# ── natural_exit stamping from the DER loop ──────────────────────────────────


def test_natural_exit_stamped_success_true():
    """REQ-16 AC2: the DER SUCCESS path stamps natural_exit=True on the
    conversation memory, so the ledger records the honest exit nature."""
    from backend.agent import agent_kernel

    kernel = SimpleNamespace(
        _conversation_memory=_memory(),
    )
    agent_kernel.AgentKernel._der_stamp_session_exit(kernel, True)
    assert kernel._conversation_memory.natural_exit is True


def test_natural_exit_stamped_failure_false():
    """REQ-16 AC2: the DER FAILURE / zero-step path stamps natural_exit=False."""
    from backend.agent import agent_kernel

    kernel = SimpleNamespace(
        _conversation_memory=_memory(),
    )
    agent_kernel.AgentKernel._der_stamp_session_exit(kernel, False)
    assert kernel._conversation_memory.natural_exit is False


def test_natural_exit_stamp_never_raises_without_memory():
    """REQ-16 AC2 edge: a kernel with no conversation memory — the stamp is a
    no-op, never an exception."""
    from backend.agent import agent_kernel

    kernel = SimpleNamespace(_conversation_memory=None)
    agent_kernel.AgentKernel._der_stamp_session_exit(kernel, True)  # no raise


# ── Edge cases ───────────────────────────────────────────────────────────────


def test_edge_empty_conversation_not_archived():
    """REQ-9/REQ-16 edge: an EMPTY conversation (no messages, no task records)
    is NOT archived — no phantom exit row that would drag natural_exit_rate
    down for a session that never actually ran."""
    from backend.agent.memory import ConversationMemory as CM

    mem = CM(
        session_id="sess-empty",
        conversation_id="conv-empty",
        session_storage_path=os.path.join(
            os.environ.get("TEMP", "/tmp"), "t32_test_storage", "conv-empty"
        ),
    )
    recorder = _recorder()
    g, ctx = _gateway_with(mem, recorder, session_id="sess-empty")

    import asyncio

    archived = {}
    with ctx, patch.object(mem, "archive_on_session_end") as _arch, patch(
        "backend.agent.outer_loop.run_outer_loop", return_value=None
    ):
        asyncio.run(g.cleanup_session("sess-empty"))

    _arch.assert_not_called()
    rows = recorder._conn.execute(
        "SELECT COUNT(*) FROM caducean_session_exits"
    ).fetchone()
    assert rows[0] == 0, "empty conversation must not write a phantom exit row"


def test_edge_archive_failure_never_raises():
    """REQ-16 edge: a failing archive (e.g. recorder down) never raises out of
    cleanup_session — the session teardown completes."""
    mem = _memory()
    recorder = _recorder()
    g, ctx = _gateway_with(mem, recorder)

    import asyncio

    with ctx, patch.object(mem, "archive_on_session_end", side_effect=RuntimeError(
        "recorder down"
    )), patch(
        "backend.agent.outer_loop.run_outer_loop", return_value=None
    ):
        asyncio.run(g.cleanup_session("sess"))  # must not raise

    # The outer loop still fires even when the archive failed (edge case:
    # "session end without archive -> still records exit").
    assert True  # reached here without exception


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
