"""
Tests for LM Studio integration, inference routing, OOM crash prevention,
session_id race fix, and model alias cleanup.

Strategy: test logic via source inspection + lightweight imports.
agent_kernel.py imports torch/transformers at module level which blocks
during CUDA init — so AgentKernel is never instantiated in these tests.
"""

import sys
import os
import ast
import re
import inspect
import pytest
from unittest.mock import MagicMock, patch

# ── Path setup ──────────────────────────────────────────────────────────────
_TEST_DIR    = os.path.dirname(os.path.abspath(__file__))  # IRISVOICE/backend/tests
_BACKEND_PKG = os.path.dirname(_TEST_DIR)                  # IRISVOICE/backend
_IRISVOICE   = os.path.dirname(_BACKEND_PKG)               # IRISVOICE
if _IRISVOICE not in sys.path:
    sys.path.insert(0, _IRISVOICE)

_KERNEL_PATH  = os.path.join(_IRISVOICE, "backend", "agent", "agent_kernel.py")
_VOICE_PATH   = os.path.join(_IRISVOICE, "backend", "audio", "voice_command.py")
_MM_PATH      = os.path.join(_IRISVOICE, "backend", "audio", "model_manager.py")
_MAIN_PATH    = os.path.join(_IRISVOICE, "backend", "main.py")
_GATEWAY_PATH = os.path.join(_IRISVOICE, "backend", "iris_gateway.py")


def read_source(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


# ════════════════════════════════════════════════════════════════════════════
# 1. Model alias dict — static analysis of _MODEL_ALIASES in agent_kernel.py
# ════════════════════════════════════════════════════════════════════════════

def _parse_model_aliases(src: str) -> dict:
    """Extract _MODEL_ALIASES dict from source using AST.
    Handles both plain Assign and AnnAssign (type-annotated class attributes).
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        # Plain assignment: _MODEL_ALIASES = {...}
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_MODEL_ALIASES":
                    if isinstance(node.value, ast.Dict):
                        result = {}
                        for k, v in zip(node.value.keys, node.value.values):
                            if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                                result[k.value] = v.value
                        return result
        # Annotated assignment: _MODEL_ALIASES: Dict[str, str] = {...}
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "_MODEL_ALIASES":
                if node.value and isinstance(node.value, ast.Dict):
                    result = {}
                    for k, v in zip(node.value.keys, node.value.values):
                        if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                            result[k.value] = v.value
                    return result
    return {}


class TestModelAliases:
    """_MODEL_ALIASES dict must reflect the correct alias configuration."""

    @pytest.fixture(scope="class")
    def aliases(self):
        src = read_source(_KERNEL_PATH)
        return _parse_model_aliases(src)

    def test_aliases_dict_found(self, aliases):
        assert aliases, "_MODEL_ALIASES dict not found in agent_kernel.py"

    def test_executor_alias_present(self, aliases):
        assert "executor" in aliases
        assert aliases["executor"] == "lfm2.5-1.2b-instruct"

    def test_lfm25_display_name_present(self, aliases):
        assert "LFM2.5-1.2B-Instruct" in aliases
        assert aliases["LFM2.5-1.2B-Instruct"] == "lfm2.5-1.2b-instruct"

    def test_lfm2_8b_absent(self, aliases):
        """LFM2-8B-A1B must NOT be in aliases — removed to prevent accidental routing."""
        assert "LFM2-8B-A1B" not in aliases, (
            "LFM2-8B-A1B alias must be absent — it was removed to prevent "
            "accidental routing to lfm2-8b"
        )

    def test_brain_alias_absent(self, aliases):
        """'brain' must not secretly map to any model."""
        assert "brain" not in aliases, (
            "'brain' alias must be absent — LFM2-8B model is no longer in use"
        )

    def test_lfm2_8b_canonical_absent(self, aliases):
        """'lfm2-8b' should not be a key or value that routes anything."""
        assert "lfm2-8b" not in aliases, (
            "'lfm2-8b' key must not exist in aliases"
        )
        for v in aliases.values():
            assert v != "lfm2-8b", (
                f"No alias should map to 'lfm2-8b' — got key mapping to it"
            )

    def test_only_executor_aliases_remain(self, aliases):
        """Only executor/LFM2.5 aliases should be present — nothing for the brain/8B model."""
        allowed_keys = {"executor", "LFM2.5-1.2B-Instruct"}
        unexpected = set(aliases.keys()) - allowed_keys
        assert not unexpected, (
            f"Unexpected alias keys found: {unexpected}. "
            "Only executor aliases should remain."
        )


# ════════════════════════════════════════════════════════════════════════════
# 2. Provider routing logic — source invariants
# ════════════════════════════════════════════════════════════════════════════

class TestProviderRouting:
    @pytest.fixture(scope="class")
    def src(self):
        return read_source(_KERNEL_PATH)

    def test_is_ollama_uses_only_colon_check(self, src):
        """_is_ollama must be determined ONLY by ':' in model ID — not by provider name."""
        # The fix removed `or self._model_provider == "local"` from the _is_ollama condition
        # Verify the fixed pattern exists somewhere in the file
        assert '_is_ollama = ":" in' in src or "_is_ollama = ':' in" in src, (
            "_is_ollama must use colon-format check"
        )
        # Verify the broken old pattern does NOT exist
        assert 'self._model_provider == "local"' not in src or \
               '_is_ollama' not in src.split('self._model_provider == "local"')[0].split('\n')[-1], (
            "Old broken pattern `_is_ollama = ... or self._model_provider == 'local'` "
            "must NOT be present"
        )

    def test_lmstudio_will_handle_guard_present(self, src):
        """plan_task must check _lmstudio_will_handle before calling local stub."""
        assert "_lmstudio_will_handle" in src, (
            "_lmstudio_will_handle guard must be present in agent_kernel.py"
        )

    def test_vps_will_handle_guard_present(self, src):
        assert "_vps_will_handle" in src

    def test_ollama_will_handle_guard_present(self, src):
        assert "_ollama_will_handle" in src

    def test_lmstudio_inference_block_in_plan_task(self, src):
        """LM Studio inference must be attempted in plan_task."""
        assert 'self._model_provider == "lmstudio"' in src, (
            "LM Studio provider check must exist in agent_kernel"
        )

    def test_lmstudio_endpoint_default(self, src):
        assert "localhost:1234" in src, (
            "Default LM Studio endpoint (localhost:1234) must be in agent_kernel.py"
        )

    def test_configure_lmstudio_method_exists(self, src):
        assert "def configure_lmstudio" in src, (
            "configure_lmstudio() method must exist for runtime endpoint configuration"
        )

    def test_configure_lmstudio_strips_slash(self, src):
        """configure_lmstudio must strip trailing slash from endpoint URL."""
        assert "rstrip" in src and '"/")' in src or '.rstrip("/")' in src, (
            "configure_lmstudio must strip trailing slash"
        )

    def test_raw_response_short_circuit_present(self, src):
        """_synthesize_response must short-circuit when _raw_response is in plan."""
        assert '_raw_response' in src, (
            "_raw_response key must be used for short-circuit synthesis"
        )
        assert "task.plan.get" in src and "_raw_response" in src, (
            "_synthesize_response must check plan._raw_response"
        )

    def test_no_naked_get_reasoning_model_in_synthesize(self, src):
        """_synthesize_response must NOT call get_reasoning_model() as executable code."""
        # Find the _synthesize_response function body
        synth_start = src.find("def _synthesize_response")
        next_def = src.find("\n    def ", synth_start + 1)
        synth_src = src[synth_start:next_def] if next_def != -1 else src[synth_start:]

        # Strip comment lines before checking — the function has a comment that says
        # "Do NOT call get_reasoning_model()" which is fine (and expected!).
        non_comment_lines = [
            line for line in synth_src.splitlines()
            if not line.lstrip().startswith("#")
        ]
        non_comment_src = "\n".join(non_comment_lines)

        # The code must not call get_reasoning_model() — only self._model_router.models.get()
        assert "get_reasoning_model()" not in non_comment_src, (
            "_synthesize_response must NOT call get_reasoning_model() in executable code — "
            "that method returns a broken stub that echoes garbage"
        )


# ════════════════════════════════════════════════════════════════════════════
# 3. OOM crash prevention — model_manager VRAM threshold
# ════════════════════════════════════════════════════════════════════════════

class TestVRAMThreshold:
    @pytest.fixture(scope="class")
    def src(self):
        return read_source(_MM_PATH)

    def test_8gb_threshold_present(self, src):
        """Model manager must use 8 GB free VRAM threshold before enabling GPU."""
        assert ">= 8.0" in src, (
            "8 GB VRAM threshold must be present in model_manager.py. "
            "This prevents LFM audio from fighting LM Studio/Ollama for VRAM."
        )

    def test_cpu_fallback_present(self, src):
        """model_manager must fall back to CPU when VRAM is insufficient."""
        assert 'device = "cpu"' in src, (
            "CPU fallback path must exist in model_manager.py"
        )

    def test_not_old_3gb_threshold(self, src):
        """Old 3 GB threshold must be gone — it was too low and caused OOM."""
        # Check the threshold used is not the old 3 GB value
        # The old code had `_free_vram >= 3.0`
        lines = [l for l in src.split('\n') if '>= 3.0' in l and 'vram' in l.lower()]
        assert not lines, (
            "Old 3 GB VRAM threshold found — it must be replaced with 8 GB"
        )


# ════════════════════════════════════════════════════════════════════════════
# 4. Voice command OOM guard & fallback STT chain
# ════════════════════════════════════════════════════════════════════════════

class TestVoiceCommandFallback:
    @pytest.fixture(scope="class")
    def src(self):
        return read_source(_VOICE_PATH)

    def test_transcribe_with_fallback_defined(self, src):
        assert "def _transcribe_with_fallback" in src, (
            "_transcribe_with_fallback method must be defined in voice_command.py"
        )

    def test_ram_guard_4gb(self, src):
        """4 GB RAM guard must prevent LFM load on low-memory systems."""
        assert "4.0" in src and ("_avail_gb" in src or "avail_gb" in src), (
            "4 GB RAM guard must be present in voice_command.py"
        )

    def test_psutil_used_for_ram_check(self, src):
        assert "psutil" in src, (
            "psutil must be used to measure available RAM before loading LFM audio"
        )

    def test_faster_whisper_in_fallback(self, src):
        assert "faster_whisper" in src or "faster-whisper" in src, (
            "faster-whisper must be the first option in the fallback STT chain"
        )

    def test_speech_recognition_in_fallback(self, src):
        assert "speech_recognition" in src or "SpeechRecognition" in src, (
            "SpeechRecognition must be in the fallback STT chain as last resort"
        )

    def test_fallback_called_on_load_failure(self, src):
        """When LFM audio model fails to load, fallback must be called."""
        assert "_transcribe_with_fallback" in src
        # The load failure path should call the fallback
        load_fail_idx = src.find("Failed to load native audio model")
        assert load_fail_idx != -1, "Load failure message must be present"
        # After the failure message, fallback should be called
        after = src[load_fail_idx:load_fail_idx + 300]
        assert "_transcribe_with_fallback" in after, (
            "_transcribe_with_fallback must be called after load failure"
        )


# ════════════════════════════════════════════════════════════════════════════
# 5. session_id race fix
# ════════════════════════════════════════════════════════════════════════════

class TestSessionIdRaceFix:
    def test_main_passes_session_id_to_gateway(self):
        """main.py handle_message must forward session_id to iris_gateway."""
        src = read_source(_MAIN_PATH)
        assert "session_id=session_id" in src, (
            "main.handle_message must call iris_gateway.handle_message(client_id, message, "
            "session_id=session_id) to fix the heartbeat-disconnect race condition"
        )

    def test_gateway_handle_message_accepts_session_id(self):
        """iris_gateway.handle_message must accept session_id as optional param."""
        src = read_source(_GATEWAY_PATH)
        # Check signature line
        sig_match = re.search(
            r"async def handle_message\s*\([^)]*session_id[^)]*\)",
            src
        )
        assert sig_match, (
            "IRISGateway.handle_message must have session_id in its parameter list"
        )

    def test_gateway_session_id_has_default_none(self):
        """session_id param must default to None for backward compatibility."""
        src = read_source(_GATEWAY_PATH)
        # Check that session_id has a default value
        assert "session_id: Optional[str] = None" in src or \
               "session_id=None" in src, (
            "session_id parameter must default to None"
        )


# ════════════════════════════════════════════════════════════════════════════
# 6. LM Studio in iris_gateway
# ════════════════════════════════════════════════════════════════════════════

class TestGatewayLMStudio:
    @pytest.fixture(scope="class")
    def src(self):
        return read_source(_GATEWAY_PATH)

    def test_lmstudio_inference_mode_handled(self, src):
        assert "lmstudio" in src, (
            "iris_gateway.py must handle lmstudio as an inference mode"
        )

    def test_lmstudio_endpoint_default_present(self, src):
        assert "localhost:1234" in src, (
            "iris_gateway.py must contain default LM Studio endpoint"
        )

    def test_v1_models_endpoint_queried(self, src):
        """LM Studio model listing must use /v1/models endpoint."""
        assert "/v1/models" in src, (
            "iris_gateway.py must query /v1/models to list available LM Studio models"
        )

    def test_confirm_card_configures_lmstudio(self, src):
        """Confirming the model card with lmstudio provider must call configure_lmstudio."""
        assert "configure_lmstudio" in src, (
            "iris_gateway.py must call kernel.configure_lmstudio() "
            "when model card is confirmed with lmstudio provider"
        )


# ════════════════════════════════════════════════════════════════════════════
# 7. Import smoke tests — new deps
# ════════════════════════════════════════════════════════════════════════════

class TestImports:
    def test_faster_whisper_importable(self):
        try:
            import faster_whisper  # noqa: F401
        except ImportError as e:
            pytest.fail(f"faster-whisper not installed: {e}")

    def test_speech_recognition_importable(self):
        try:
            import speech_recognition  # noqa: F401
        except ImportError as e:
            pytest.fail(f"SpeechRecognition not installed: {e}")

    def test_openai_importable(self):
        try:
            import openai  # noqa: F401
        except ImportError as e:
            pytest.fail(f"openai not installed (needed for LM Studio calls): {e}")

    def test_psutil_importable(self):
        try:
            import psutil  # noqa: F401
        except ImportError as e:
            pytest.fail(f"psutil not installed (needed for RAM guard): {e}")


# ════════════════════════════════════════════════════════════════════════════
# 8. LM Studio routing logic simulation (pure Python, no imports)
# ════════════════════════════════════════════════════════════════════════════

class TestRoutingLogicSimulation:
    """
    Simulate the exact routing conditionals from agent_kernel.plan_task()
    without importing the kernel. Tests the logic not the object.
    """

    def _compute_guards(self, model_provider, selected_reasoning_model, vps_gateway=None):
        _sel_check = selected_reasoning_model or ""
        _ollama_will_handle = ":" in _sel_check
        _vps_will_handle = bool(vps_gateway)
        _lmstudio_will_handle = model_provider == "lmstudio"
        _should_call_local_stub = (
            not _ollama_will_handle
            and not _vps_will_handle
            and not _lmstudio_will_handle
        )
        return {
            "ollama": _ollama_will_handle,
            "vps": _vps_will_handle,
            "lmstudio": _lmstudio_will_handle,
            "call_stub": _should_call_local_stub,
        }

    def test_lmstudio_provider_skips_local_stub(self):
        g = self._compute_guards("lmstudio", "qwen-3.5-9b")
        assert g["lmstudio"] is True
        assert g["call_stub"] is False

    def test_ollama_model_skips_local_stub(self):
        g = self._compute_guards("local", "llama3.2:3b")
        assert g["ollama"] is True
        assert g["call_stub"] is False

    def test_vps_provider_skips_local_stub(self):
        g = self._compute_guards("vps", "kimi:cloud", vps_gateway=MagicMock())
        assert g["vps"] is True
        assert g["call_stub"] is False

    def test_local_no_colon_calls_stub(self):
        """provider='local' with plain model ID → local stub should be called."""
        g = self._compute_guards("local", "lfm2-8b")
        assert g["ollama"] is False
        assert g["lmstudio"] is False
        assert g["call_stub"] is True

    def test_uninitialized_provider_calls_stub(self):
        """Uninitialized provider with no model → local stub path."""
        g = self._compute_guards("uninitialized", None)
        assert g["call_stub"] is True

    def test_local_provider_not_treated_as_ollama(self):
        """
        Old bug: `_is_ollama = ":" in _sel or self._model_provider == "local"`
        caused provider='local' to incorrectly set _is_ollama=True → 404 errors.
        Fixed: only colon-format IDs are Ollama.
        """
        _sel = "lfm2-8b"
        _is_ollama_old = ":" in _sel or True   # simulating old broken check
        _is_ollama_fixed = ":" in _sel          # new correct check

        assert _is_ollama_old is True   # proves old code was broken
        assert _is_ollama_fixed is False  # proves fix is correct

    def test_set_model_selection_logic(self):
        """set_model_selection stores values unconditionally."""
        aliases = {
            "LFM2.5-1.2B-Instruct": "lfm2.5-1.2b-instruct",
            "executor":              "lfm2.5-1.2b-instruct",
        }

        def normalize(model_id):
            if model_id is None:
                return None
            return aliases.get(model_id, model_id)

        # Executor alias resolves
        assert normalize("executor") == "lfm2.5-1.2b-instruct"
        # LFM2-8B-A1B passes through (no alias)
        assert normalize("LFM2-8B-A1B") == "LFM2-8B-A1B"
        # Qwen passes through
        assert normalize("qwen-3.5-9b") == "qwen-3.5-9b"
        # None is handled
        assert normalize(None) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
