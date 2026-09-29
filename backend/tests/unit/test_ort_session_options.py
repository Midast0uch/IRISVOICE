"""Unit tests: explicit ORT session options (REQ-30 AC30.1, T38).

AC30.1 — the engine SHALL set explicit `intra_op_num_threads`,
`inter_op_num_threads`, `graph_optimization_level` and `execution_mode` sized
to the host CPU, and SHALL record the effective values.

Before T38 the reference runner set only an OPTIONAL `intra_op_num_threads` and
the bench never passed it, so onnxruntime's defaults applied and nothing was
recorded. The recorded dict is what makes the tuning verifiable.
"""

from __future__ import annotations

import os

from backend.agent.decision_backend_onnx import (
    _EXECUTION_MODE_NAME,
    _GRAPH_OPT_LEVEL_NAME,
    _INTER_OP_THREADS,
    GlinerOnnx,
)


class TestExplicitSessionOptions:
    def test_explicit_session_options_recorded(self, onnx_backend):
        """AC30.1: all four options are set AND the effective values recorded."""
        opts = onnx_backend.session_options

        assert opts, "the backend exposed no effective session options"
        assert opts["intra_op_num_threads"] >= 1
        assert opts["intra_op_num_threads"] <= (os.cpu_count() or 1), (
            "intra_op threads exceed the host core count"
        )
        assert opts["inter_op_num_threads"] == _INTER_OP_THREADS
        assert opts["graph_optimization_level"] == _GRAPH_OPT_LEVEL_NAME
        assert opts["execution_mode"] == _EXECUTION_MODE_NAME
        assert opts["providers"] == ["CPUExecutionProvider"]  # AC21.3, no VRAM
        assert opts["host_cpu_count"] == (os.cpu_count() or 1)
        assert opts["clamped"] is False

    def test_intra_threads_clamped_to_the_host(self):
        """REQ-30 edge: fewer cores than configured → clamp, and say so."""
        backend = GlinerOnnx(threads=9999)
        if not backend.load():
            import pytest

            pytest.skip("ONNX decision model unavailable")

        opts = backend.session_options
        assert opts["intra_op_num_threads"] == (os.cpu_count() or 1), (
            "an over-large thread request was not clamped to the host"
        )
        assert opts["clamped"] is True, (
            "the clamp was silent — the effective values must record it"
        )
        backend.shutdown()

    def test_explicit_request_is_honoured_when_it_fits(self):
        """A request at or below the core count is used as given."""
        backend = GlinerOnnx(threads=1)
        if not backend.load():
            import pytest

            pytest.skip("ONNX decision model unavailable")

        assert backend.session_options["intra_op_num_threads"] == 1
        backend.shutdown()
