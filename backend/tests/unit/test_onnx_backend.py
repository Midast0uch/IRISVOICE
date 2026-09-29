"""Unit tests for backend/agent/decision_backend_onnx.py (REQ-21).

AC21.1  labels scored as a schema Task (one Task per decide call).
AC21.5  requirements declared + model path resolution check.
"""

from __future__ import annotations

from pathlib import Path

import backend.agent.decision_backend_onnx as onnx_mod
from backend.agent.decision_backend_onnx import (
    GlinerOnnx,
    Task,
    resolve_model_dir,
)


FRAME = {"goal": "find the current price of a product online"}


class TestLabelsScoredAsSchemaTask:
    def test_labels_scored_as_schema_task(self):
        """AC21.1: the backend scores the caller's option set as ONE schema
        Task whose labels are the options — softmax over labels."""
        # A fake runner stands in for the ONNX session; the Task construction
        # and the softmax mapping are the real thing.
        backend = GlinerOnnx(model_dir="C:/no/such-dir")

        class _FakeRunner:
            def logits(self, text, tasks):
                assert len(tasks) == 1, "one schema Task per decide call"
                t = tasks[0]
                assert isinstance(t, Task)
                assert set(t.labels) == {"read_file", "list_directory", "NONE"}
                assert t.exclusive is True
                return {t.name: {"read_file": -1.0, "list_directory": -4.0,
                                 "NONE": -9.0}}

        backend._runner = _FakeRunner()
        backend._load_attempted = True
        ds = backend.decide("tool_choice",
                            ["read_file", "list_directory", "NONE"], FRAME)
        assert ds is not None
        assert ds.chosen == "read_file"
        assert ds.consumer_id == "tool_choice"
        assert abs(sum(c.prob for c in ds.distribution) - 1.0) < 1e-6
        probs = {c.name: c.prob for c in ds.distribution}
        assert probs["read_file"] > probs["list_directory"] > probs["NONE"]

    def test_task_shape_pinned_to_bench_shape(self):
        """The Task shape is pinned to the measured bench shape (AC22.1
        calibration validity): labels carry no descriptions, the instruction
        is the bench instruction."""
        t = Task(name="tool", labels={"a": None, "b": None},
                 instruction="Which tool should handle this request?",
                 exclusive=True)
        toks = t.tokens()
        # No [DESCRIPTION] pieces rendered — labels carry no descriptions.
        assert not any("[DESCRIPTION]" == p for p in toks)
        assert "[L]" in toks and "a" in toks and "b" in toks


class TestRequirementsAndPathCheck:
    def test_requirements_and_path_check(self):
        """AC21.5: onnxruntime and tokenizers are declared in requirements.txt;
        the model dir resolution finds the shippable location or returns None
        (configured-and-missing = unavailable, never a substitute)."""
        req = Path("requirements.txt").read_text(encoding="utf-8")
        assert "onnxruntime" in req, "onnxruntime undeclared (AC21.5)"
        assert "tokenizers" in req, "tokenizers undeclared (AC21.5)"
        # An explicit path that does not exist is authoritative-missing.
        assert resolve_model_dir("C:/no/such-dir") is None
        # The default resolution finds a complete dir on this machine or None.
        d = resolve_model_dir()
        assert d is None or Path(d, "tokenizer.json").is_file()

    def test_env_override_authoritative(self, monkeypatch):
        """An explicit-env path is authoritative: configured-and-missing means
        unavailable, never silently substitute another model."""
        monkeypatch.setenv("IRIS_DECISION_MODEL_DIR", "C:/no/such-dir")
        assert resolve_model_dir() is None
