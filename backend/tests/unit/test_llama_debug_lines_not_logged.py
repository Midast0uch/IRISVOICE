"""Regression (2026-09-29): llama-server's per-token debug lines stay out of
logs/iris.log, while its info/warning/error lines are still forwarded.

At -lv 5 the server prints ~10 "D" lines per generated token; forwarding every
line grew logs/iris.log to 2 GB. The sample lines are copied from that log.
"""

from backend.agent.local_model_manager import _LLAMA_DEBUG_LINE

_PER_TOKEN = [
    "8.19.557.938 D que    start_loop: waiting for new tasks",
    "8.19.557.965 D slot handle_last_: id  0 | task 1058 | slot decode token, id=4695, n_ctx = 32768, n_tokens = 6453, truncated = 0",
    "8.19.558.501 D ggml_backend_cuda_graph_compute: CUDA graph warmup complete",
]
_KEPT = [
    "0.02.606.320 I load_tensors: offloaded 31/31 layers to GPU",
    "0.00.426.322 I llama_prepare_model_devices: using device CUDA0 (NVIDIA GeForce RTX 3070)",
    "0.00.100.000 E error loading model: unknown model architecture",
    "main: server is listening on http://127.0.0.1:8082",
]


def test_per_token_debug_lines_are_dropped():
    assert all(_LLAMA_DEBUG_LINE.match(line) for line in _PER_TOKEN)


def test_info_and_error_lines_are_kept():
    assert not any(_LLAMA_DEBUG_LINE.match(line) for line in _KEPT)
