"""
Loaded context-window exposure test (Phase 3, Wave 5, T5.3 / REQ-3 AC1 / CT-L7).

A loaded model must report its REAL configured n_ctx via get_status — this is
the authoritative source for context-window resolution (overrides any table
entry in agent_kernel.resolve_context_window_with_source).
"""

import pytest

from backend.agent.local_model_manager import LocalModelManager


@pytest.fixture
def lmm():
    return LocalModelManager()


class TestLoadedContextExposed:
    def test_get_status_exposes_loaded_n_ctx(self, lmm):
        lmm._current_model_path = "/fake/model.gguf"
        lmm._current_params = {"n_ctx": 12345, "n_gpu_layers": -1, "n_batch": 1024}
        llm_backup = lmm._llm
        lmm._llm = object()  # pretend in-process model is loaded
        try:
            status = lmm.get_status()
        finally:
            lmm._llm = llm_backup
        assert status["loaded"] is True
        assert status["n_ctx"] == 12345, "loaded model must report its real n_ctx"
        assert status["purpose"] == "chat"

    def test_get_status_n_ctx_none_when_unloaded(self, lmm):
        # No model loaded → n_ctx must be None (not a stale value).
        status = lmm.get_status()
        assert status["loaded"] is False
        assert status["n_ctx"] is None
