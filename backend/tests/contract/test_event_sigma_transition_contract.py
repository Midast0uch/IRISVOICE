"""Guard (2026-10-18): an event records the step's Σ TRANSITION, not one value twice.

The emit job read only the newest coordinate and wrote it into BOTH sigma_from and
sigma_to, so 11,887 of 11,887 live rows had sigma_from = sigma_to: no event said how
the work moved. The job now reads the session's last two positions (before, after).
Real lane, real store (``_events_fixture``); only the trajectory recorder is a stand-in.
"""
from __future__ import annotations

from types import SimpleNamespace

from backend.tests.contract._events_fixture import memory_interface, rows, store  # noqa: F401

BEFORE = {"x": 2.0, "y": 1.0, "xi": 1.05, "u": 0.35}
AFTER = {"x": 2.0, "y": 2.0, "xi": 1.50, "u": -0.20}


def _recorder(monkeypatch, coords):
    monkeypatch.setattr(
        "backend.agent.caducean_trajectory.get_trajectory_recorder",
        lambda mi: SimpleNamespace(get_last_coordinates=lambda sid, n=2: list(coords)[:n]),
    )


def test_an_event_carries_where_the_step_started_and_where_it_landed(store, monkeypatch):
    from backend.agent import event_emit
    from backend.agent.caducean_trajectory import format_coords

    _recorder(monkeypatch, [AFTER, BEFORE])   # newest first
    owner = SimpleNamespace(_memory_interface=memory_interface(store))
    event_emit.submit(owner, "emit_event", label="PLAN_MADE", evidence="claim", thread_id="t-sigma")
    row = rows(store, "PLAN_MADE")[0]
    assert row["sigma_from"] == format_coords(*BEFORE.values())
    assert row["sigma_to"] == format_coords(*AFTER.values())
    assert row["sigma_from"] != row["sigma_to"]


def test_the_first_step_of_a_session_has_no_known_start(store, monkeypatch):
    from backend.agent import event_emit

    _recorder(monkeypatch, [AFTER])
    owner = SimpleNamespace(_memory_interface=memory_interface(store))
    event_emit.submit(owner, "emit_event", label="PLAN_MADE", evidence="claim", thread_id="t-first")
    row = rows(store, "PLAN_MADE")[0]
    assert row["sigma_from"] is None   # unknown is NULL, never a stand-in
    assert row["sigma_to"] is not None