"""A bar-record flip may only fire on the engine it was MEASURED on.

Owner decision 2026-09-27 (option B): passing the bar turns a consumer on with no
hand-edited list. Two conditions, both required:

  * the record says ``enforced`` - which derive_status sets only when rows >= 100
    AND precision >= 0.90 AND ECE <= 0.05, never a partial flip;
  * the record was measured against the CURRENT engine identity.

The second condition exists because of a measured defect: 457 of 522 tool_choice
rows came from the retired LFM2-350M-Extract engine, and averaging them with the
active engine's rows reported precision 0.442 for a model that was right every
time. A flip carrying over from a retired model is the same error pointed the
other way - it would trust a model that is no longer the one answering.

CHANGED (2026-10-05, Oracle Stage B, owner-approved): a record alone no longer
enforces. `enforced_consumers()` is the INTERSECTION of the owner's switch
(IRIS_DECISION_ENFORCE, default empty), the earned bar and a fitted threshold.
Each test below therefore provides the OTHER keys (the owner switch on `mode`
and a fitted threshold) through `_write_record`, so the one thing that varies is
what the test is about; the assertions are unchanged except
`test_the_manual_list_still_works_beside_the_record`, which pinned the old union.
"""
from __future__ import annotations

import json

import pytest

from backend.agent import consumer_bar as cb
from backend.agent import decision_engine as de
from backend.agent import oracle_calibration as oc


def _write_record(tmp_path, monkeypatch, *, consumer_id, status, measured_on):
    bar = {
        "consumer_id": consumer_id,
        "rows": 120,
        "precision": 1.0,
        "ece": 0.01,
        "status": status,
        "gap": "",
        "config": {"backend_id": measured_on},
    }
    path = tmp_path / "consumer_bar_record.json"
    path.write_text(json.dumps({consumer_id: bar}), encoding="utf-8")
    monkeypatch.setattr(cb, "BAR_PATH", path)
    # The other two keys are PRESENT (owner switch, fitted threshold) so this
    # file stays about the RECORD path: only the record varies per test.
    monkeypatch.setenv("IRIS_DECISION_ENFORCE", consumer_id)
    cal = tmp_path / "oracle_calibration.json"
    cal.write_text(json.dumps({"gliner25-decide-onnx-int8": {
        consumer_id: {"knots": [[0.5, 0.5], [1.0, 1.0]], "threshold": 0.8}}}),
        encoding="utf-8")
    monkeypatch.setattr(oc, "CALIBRATION_PATH", cal)
    oc._CACHE.clear()
    return path


def test_a_flip_measured_on_the_active_engine_is_enforced(tmp_path, monkeypatch):
    _write_record(tmp_path, monkeypatch, consumer_id="mode",
                  status="enforced", measured_on="gliner25-decide-onnx-int8")
    monkeypatch.setattr(de, "_current_backend_identity",
                        lambda: "gliner25-decide-onnx-int8")
    assert "mode" in de.enforced_consumers()


def test_a_flip_measured_on_a_RETIRED_engine_is_refused(tmp_path, monkeypatch):
    """The point of the guard: the flip must be re-earned on the deployed model."""
    _write_record(tmp_path, monkeypatch, consumer_id="mode",
                  status="enforced", measured_on="LFM2-350M-Extract")
    monkeypatch.setattr(de, "_current_backend_identity",
                        lambda: "gliner25-decide-onnx-int8")
    assert "mode" not in de.enforced_consumers()


def test_a_shadow_record_enforces_nothing(tmp_path, monkeypatch):
    _write_record(tmp_path, monkeypatch, consumer_id="mode",
                  status="shadow", measured_on="gliner25-decide-onnx-int8")
    monkeypatch.setattr(de, "_current_backend_identity",
                        lambda: "gliner25-decide-onnx-int8")
    assert "mode" not in de.enforced_consumers()


def test_an_unknown_engine_identity_cannot_unlock_a_flip(tmp_path, monkeypatch):
    """An identity we cannot resolve must never be treated as a match."""
    _write_record(tmp_path, monkeypatch, consumer_id="mode",
                  status="enforced", measured_on="gliner25-decide-onnx-int8")
    monkeypatch.setattr(de, "_current_backend_identity", lambda: "")
    assert "mode" not in de.enforced_consumers()


def test_a_record_with_no_engine_recorded_cannot_unlock_a_flip(tmp_path, monkeypatch):
    _write_record(tmp_path, monkeypatch, consumer_id="mode",
                  status="enforced", measured_on="")
    monkeypatch.setattr(de, "_current_backend_identity",
                        lambda: "gliner25-decide-onnx-int8")
    assert "mode" not in de.enforced_consumers()


def test_no_record_is_the_safe_default(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "BAR_PATH", tmp_path / "absent.json")
    # Switched on by the owner, but there is no record: nothing decides.
    monkeypatch.setenv("IRIS_DECISION_ENFORCE", "mode")
    assert de.enforced_consumers() == frozenset()


def test_the_manual_list_alone_enforces_nothing(tmp_path, monkeypatch):
    """SUCCESSOR (2026-10-05) of `test_the_manual_list_still_works_beside_the_
    record`, which pinned the UNION (the list enforced a consumer the record had
    not earned). The owner's switch is now ONE of four keys: a consumer on the
    list that has not earned its bar is not enforced, and an earned consumer
    that is not on the list is not either."""
    _write_record(tmp_path, monkeypatch, consumer_id="mode",
                  status="enforced", measured_on="gliner25-decide-onnx-int8")
    monkeypatch.setattr(de, "_current_backend_identity",
                        lambda: "gliner25-decide-onnx-int8")
    monkeypatch.setenv("IRIS_DECISION_ENFORCE", "tool_choice")
    assert de.enforced_consumers() == frozenset()
    monkeypatch.setenv("IRIS_DECISION_ENFORCE", "tool_choice,mode")
    assert de.enforced_consumers() == frozenset({"mode"})
