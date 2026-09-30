"""Contract CT-K1: every Immortus chain writer stores a REAL coordinate or NULL.

Spec: specs/research-memory-chain-browser REQ-4 AC4.1 / task K1.
  A chain row's coords_from / coords_to are ``format_coords`` output or None -
  never ``rest:...`` / ``thread:...`` pseudo values, a Python list, an empty
  string, or ``0.00,0.00,0.00,0.00`` standing in for "unknown".

One test per writer, each driven through the REAL writer code with the chain
append captured at the ffi seam (``backend.gateway.iris_ffi.ffi_immortus_chain_append``)
and the trajectory recorder replaced by a fake that returns a known coordinate
or None. Each writer is run twice: with a coordinate (must be format_coords) and
without one (must be None).
"""
from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace
from unittest import mock

import pytest

from backend.agent.caducean_trajectory import format_coords

COORD = {"x": 0.12, "y": 0.34, "xi": 0.5, "u": 0.7}
COORD_STR = format_coords(0.12, 0.34, 0.5, 0.7)  # "0.12,0.34,0.50,0.70"
_REAL = re.compile(r"^-?\d+\.\d{2},-?\d+\.\d{2},-?\d+\.\d{2},-?\d+\.\d{2}$")


class FakeRecorder:
    def __init__(self, coord):
        self._coord = coord

    def get_latest_coordinate(self, session_id):
        return self._coord

    def record(self, **kw):
        return None


def _assert_real_or_null(value, expected):
    """The contract: format_coords text (equal to what the recorder held) or None.

    The regex rejects ``rest:..``, ``thread:..``, lists and ``""``; the equality
    rejects ``0.00,0.00,0.00,0.00`` standing in for an unknown coordinate.
    """
    assert value == expected, value
    assert value is None or _REAL.match(value), value


@pytest.fixture()
def chain(monkeypatch):
    """Capture every chain append at the ffi seam."""
    rows: list = []
    monkeypatch.setattr(
        "backend.gateway.iris_ffi.ffi_immortus_chain_append",
        lambda **kw: (rows.append(kw) or 0),
    )
    return rows


def _recorder(monkeypatch, coord):
    monkeypatch.setattr(
        "backend.agent.caducean_trajectory.get_trajectory_recorder",
        lambda mi: FakeRecorder(coord),
    )


# ── api/chat.py: the REST exchange row ──────────────────────────────────


@pytest.mark.parametrize("coord,expected", [(COORD, COORD_STR), (None, None)])
def test_chat_exchange_row(chain, monkeypatch, coord, expected):
    from backend.api.chat import _record_to_immortus

    _recorder(monkeypatch, coord)
    monkeypatch.setattr("backend.memory.get_memory_interface", lambda: object())
    _record_to_immortus("thread-k1", "hello", "hi", "turn1")
    assert len(chain) == 1
    _assert_real_or_null(chain[0]["coords_from"], expected)
    _assert_real_or_null(chain[0]["coords_to"], expected)


def test_chat_fork_row_is_null(chain):
    """A fork is a thread relation, not a point in state: NULL, not ``thread:<id>``."""
    from backend.api import chat as chat_mod

    parent = {"title": "p", "messages": [{"id": "m1", "role": "user", "text": "x"}]}
    with mock.patch("backend.conversation_store.get_conversation", return_value=parent), \
         mock.patch("backend.conversation_store.create_conversation",
                    return_value={"title": "f"}), \
         mock.patch("backend.conversation_store.add_message"):
        asyncio.run(chat_mod.fork_thread(
            "parent-k1", chat_mod.ForkRequest(message_id="m1", title="fork")
        ))
    assert len(chain) == 1 and chain[0]["result"] == "fork"
    assert chain[0]["coords_from"] is None and chain[0]["coords_to"] is None


# ── agent/mcm.py: the compress landmark row ─────────────────────────────


@pytest.mark.parametrize("coord,expected", [(COORD, COORD_STR), (None, None)])
def test_mcm_compress_row(chain, monkeypatch, coord, expected):
    from backend.agent.mcm import MCM

    _recorder(monkeypatch, coord)
    mcm = MCM(memory_interface=object(), session_id="sess-k1", thread_id="thread-k1")
    mcm.compress(active_task="task")
    landmarks = [r for r in chain if r["result"] == "landmark"]
    assert len(landmarks) == 1, "compress must write its chain row through the one writer"
    _assert_real_or_null(landmarks[0]["coords_from"], expected)
    _assert_real_or_null(landmarks[0]["coords_to"], expected)


# ── agent_kernel: document row (``_store_document_data``) ───────────────


@pytest.mark.parametrize("coord,expected", [(COORD, COORD_STR), (None, None)])
def test_document_row(chain, monkeypatch, coord, expected):
    from backend.tests.contract.test_document_data_store import (
        TRUSTED_RESPONSE,
        _run_process,
    )

    _bus, immortus, _k = _run_process(TRUSTED_RESPONSE, coord=coord)
    assert len(immortus) == 1
    _assert_real_or_null(immortus[0]["coords_from"], expected)
    _assert_real_or_null(immortus[0]["coords_to"], expected)


# ── agent_kernel: DER step fold (``_der_physics_step``) ─────────────────


def _run_step_fold(monkeypatch, before_coord):
    """Drive the REAL ``_der_physics_step`` with stand-in physics and capture the chain row."""
    import threading

    from backend.agent import agent_kernel as ak

    rows: list = []
    state = {"x": 1.0, "y": 0.0, "xi": 1.05, "u": 0.35}
    monkeypatch.setattr(
        "backend.gateway.iris_ffi.ffi_immortus_chain_append",
        lambda **kw: (rows.append(kw) or 0),
    )
    monkeypatch.setattr("backend.gateway.iris_ffi.ffi_calculate_eml", lambda s: (1.0, 1.0, 0.0))
    monkeypatch.setattr("backend.gateway.iris_ffi.ffi_caducean_update", lambda *a, **k: None)
    monkeypatch.setattr("backend.gateway.iris_ffi.ffi_caducean_recommend", lambda s: 0)
    monkeypatch.setattr("backend.gateway.iris_ffi.ffi_caducean_get_state", lambda s: dict(state))
    monkeypatch.setattr(
        "backend.agent.caducean_trajectory.get_trajectory_recorder",
        lambda mi: FakeRecorder(before_coord),
    )
    # The narration log appends a JSONL file under backend/data - not under test here.
    monkeypatch.setattr(
        "backend.agent.narration.NarrationLog",
        lambda conv: SimpleNamespace(_write=lambda rec: None),
    )
    k = ak.AgentKernel.__new__(ak.AgentKernel)
    k._memory_interface = object()
    k._der_last_u_mag = 0.0
    item = SimpleNamespace(envelope=None, step_number=1, step_id="s1", tool="write_file",
                           description="edit a file", params={}, is_subloop=False)
    fold = SimpleNamespace(ready=threading.Event(), done=threading.Event(),
                           lock=threading.Lock(), coords_from=None, coords_to=None,
                           rec=None, step=1)
    vals = {
        "session": "sess-k1", "step_number": 1, "step_id": "s1", "tool": "write_file",
        "success": True, "verified": "VERIFIED", "from_voice": False, "n_children": 0,
        "is_subloop": False, "execution_domain": "der", "topic_domain": "general",
        "insight": "edit a file", "file_path": "", "mediator": "", "mediator_source": "",
        "node_type": "step", "rec_topic_domain": "general", "rec_execution_domain": "der",
        "conversation_id": "conv-k1",
    }
    k._der_physics_step(fold, vals, None, item)
    assert len(rows) == 1, rows
    return rows[0]


def test_step_fold_row_with_prior_coordinate(monkeypatch):
    row = _run_step_fold(monkeypatch, COORD)
    _assert_real_or_null(row["coords_from"], COORD_STR)
    _assert_real_or_null(row["coords_to"], format_coords(1.0, 0.0, 1.05, 0.35))


def test_step_fold_row_without_prior_coordinate_is_null(monkeypatch):
    """No prior coordinate is UNKNOWN: NULL, never ``0.00,0.00,0.00,0.00``."""
    row = _run_step_fold(monkeypatch, None)
    assert row["coords_from"] is None, row["coords_from"]
    _assert_real_or_null(row["coords_to"], format_coords(1.0, 0.0, 1.05, 0.35))
