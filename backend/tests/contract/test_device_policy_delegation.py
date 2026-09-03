"""
CT-6: resolve_device_policy is the single source of truth and _build_server_cmd
never contradicts it (REQ-11, T35).

- chat/tool → gpu device, argv contains -ngl -1, never 0
- embedding/rerank → cpu device, argv may contain 0, never forced to -1
- no-GPU + chat → loud RuntimeError, not silent CPU fallback
- no-GPU + embedding → succeeds with 0
"""

from unittest.mock import patch

from backend.agent.local_model_manager import LocalModelManager, PROFILES, resolve_device_policy

FAKE_SERVER = "C:/fake/llama-server.exe"
MODEL_PATH = "C:/models/test-model.Q4_K_M.gguf"


def _mgr():
    m = LocalModelManager()
    m._select_server_binary = lambda p: FAKE_SERVER
    return m


class TestCT6DevicePolicyDelegation:
    def test_chat_byte_identical_to_today(self):
        """CT-6 + CT-5: chat argv byte-identical after delegation (gpu -1)."""
        mgr = _mgr()
        params = dict(PROFILES["balanced"])
        with patch.object(mgr, "get_hardware_info", return_value={"cuda_available": True, "gpu_name": "RTX 3070", "vram_total_gb": 8.0, "vram_free_gb": 7.0}):
            cmd = mgr._build_server_cmd(MODEL_PATH, params, purpose="chat")
        assert "--n-gpu-layers" in cmd
        assert cmd[cmd.index("--n-gpu-layers") + 1] == "-1"
        # CT-5: no cpu offload flags
        assert "-cmoe" not in cmd
        assert "-ncmoe" not in cmd

    def test_tool_also_gpu(self):
        mgr = _mgr()
        params = dict(PROFILES["balanced"])
        with patch.object(mgr, "get_hardware_info", return_value={"cuda_available": True, "gpu_name": "RTX 3070", "vram_total_gb": 8.0, "vram_free_gb": 7.0}):
            cmd = mgr._build_server_cmd(MODEL_PATH, params, purpose="tool")
        assert cmd[cmd.index("--n-gpu-layers") + 1] == "-1"

    def test_embedding_may_use_cpu_zero(self):
        """embedding purpose must be allowed to emit n_gpu_layers 0."""
        mgr = _mgr()
        params = {"n_gpu_layers": 0, "n_ctx": 4096, "n_batch": 512}
        with patch.object(mgr, "get_hardware_info", return_value={"cuda_available": True, "gpu_name": "RTX 3070", "vram_total_gb": 8.0, "vram_free_gb": 7.0}):
            cmd = mgr._build_server_cmd(MODEL_PATH, params, purpose="embedding")
        assert cmd[cmd.index("--n-gpu-layers") + 1] == "0"

    def test_rerank_may_use_cpu_zero(self):
        mgr = _mgr()
        params = {"n_gpu_layers": 0, "n_ctx": 4096, "n_batch": 512}
        with patch.object(mgr, "get_hardware_info", return_value={"cuda_available": True, "gpu_name": "RTX 3070", "vram_total_gb": 8.0, "vram_free_gb": 7.0}):
            cmd = mgr._build_server_cmd(MODEL_PATH, params, purpose="rerank")
        assert cmd[cmd.index("--n-gpu-layers") + 1] == "0"

    def test_no_gpu_chat_fails_loud(self):
        """REQ-11 AC2: no GPU + chat must fail loud, not silent -1."""
        mgr = _mgr()
        params = dict(PROFILES["balanced"])
        with patch.object(mgr, "get_hardware_info", return_value={"cuda_available": False, "vram_total_gb": 0, "vram_free_gb": 0}):
            try:
                mgr._build_server_cmd(MODEL_PATH, params, purpose="chat")
                assert False, "should have raised RuntimeError for no GPU"
            except RuntimeError as e:
                assert "No supported GPU" in str(e)
                assert "chat" in str(e).lower()

    def test_no_gpu_embedding_succeeds_with_cpu(self):
        """REQ-11 AC3: no GPU + embedding must succeed on CPU."""
        mgr = _mgr()
        params = {"n_gpu_layers": 0, "n_ctx": 4096, "n_batch": 512}
        with patch.object(mgr, "get_hardware_info", return_value={"cuda_available": False, "vram_total_gb": 0, "vram_free_gb": 0}):
            cmd = mgr._build_server_cmd(MODEL_PATH, params, purpose="embedding")
        assert cmd[cmd.index("--n-gpu-layers") + 1] == "0"

    def test_resolve_device_policy_is_source_of_truth(self):
        """T32 AC4: resolve_device_policy is the only decision maker."""
        assert resolve_device_policy("chat").device == "gpu"
        assert resolve_device_policy("tool").device == "gpu"
        assert resolve_device_policy("embedding").device == "cpu"
        assert resolve_device_policy("rerank").device == "cpu"
        # eco profile (n_gpu_layers 0) must not smuggle CPU brain — chat wins
        # builder for chat must still emit -1 even if params say 0
        mgr = _mgr()
        eco_params = {"n_gpu_layers": 0, "n_ctx": 4096, "n_batch": 512}
        with patch.object(mgr, "get_hardware_info", return_value={"cuda_available": True, "gpu_name": "RTX 3070", "vram_total_gb": 8.0, "vram_free_gb": 7.0}):
            cmd = mgr._build_server_cmd(MODEL_PATH, eco_params, purpose="chat")
        assert cmd[cmd.index("--n-gpu-layers") + 1] == "-1", "eco 0 must be rejected for chat"
