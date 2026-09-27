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
"""
from __future__ import annotations

import json

import pytest

from backend.agent import consumer_bar as cb
from backend.agent import decision_engine as de


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
    # The env list stays out of the way: this file is about the RECORD path.
    monkeypatch.setenv("IRIS_DECISION_ENFORCE", "")
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
    monkeypatch.setenv("IRIS_DECISION_ENFORCE", "")
    assert de.enforced_consumers() == frozenset()


def test_the_manual_list_still_works_beside_the_record(tmp_path, monkeypatch):
    _write_record(tmp_path, monkeypatch, consumer_id="mode",
                  status="enforced", measured_on="gliner25-decide-onnx-int8")
    monkeypatch.setattr(de, "_current_backend_identity",
                        lambda: "gliner25-decide-onnx-int8")
    monkeypatch.setenv("IRIS_DECISION_ENFORCE", "tool_choice")
    got = de.enforced_consumers()
    assert "tool_choice" in got and "mode" in got
