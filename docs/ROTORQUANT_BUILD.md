# RotorQuant — Building the Turbo KV-Cache Fork

RotorQuant (scrya-com/rotorquant) is a drop-in replacement for `llama-cpp-python`
that adds PlanarQuant / IsoQuant KV cache compression — 5–10× smaller KV cache
than stock `q8_0`, which is what makes 70B-class models fit in 8 GB of VRAM
when paired with 64 GB of system RAM.

IRIS ships with the stock library; RotorQuant is opt-in. When the fork is
installed, `LocalModelManager` detects it automatically and the
`research_rotorquant` profile becomes usable. Without the fork, that profile
falls back to `performance` with a warning logged.

---

## Prerequisites (Windows + CUDA)

- CUDA Toolkit 12.x (match the version `llama-cpp-python` was built against in
  IRIS's current environment)
- Visual Studio 2022 Build Tools with the C++ workload
- NVIDIA driver ≥ R525 for CC 8.6 (RTX 3070)
- CMake 3.22 or newer (bundled with VS2022 installer)
- Python 3.11 or 3.12 (match your IRIS backend interpreter exactly)

## Prerequisites (Linux)

- CUDA 12.x + `gcc-11` or newer
- Python ≥ 3.10
- CMake 3.22+

---

## Build — Windows (PowerShell)

Run from a *Developer Command Prompt for VS 2022* (so `cl.exe` is on PATH):

```powershell
# Tell the llama-cpp-python build to enable CUDA for Ampere (RTX 30xx = CC 8.6).
$env:CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=86"
$env:FORCE_CMAKE=1

# Install the fork — replaces stock llama-cpp-python in-place.
pip install --force-reinstall --no-cache-dir `
  git+https://github.com/johndpope/llama-cpp-turboquant.git@feature/planarquant-kv-cache
```

The compile takes 5–15 minutes depending on host CPU and whether ccache is
available.

## Build — Linux

```bash
export CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=86"
export FORCE_CMAKE=1
pip install --force-reinstall --no-cache-dir \
  git+https://github.com/johndpope/llama-cpp-turboquant.git@feature/planarquant-kv-cache
```

---

## Verify the fork is active

```bash
python -c "from llama_cpp import Llama; import inspect; print('cache_type_k' in inspect.signature(Llama.__init__).parameters)"
```

Expected output: `True`

When you restart the IRIS backend you should see:

```
[LocalModelManager] RotorQuant (planar3/iso3) available: True
```

If it says `False`, the install did not take — verify with
`pip show llama-cpp-python` (the `Home-page` should be the fork repo, not
abetlen/llama-cpp-python) and rebuild.

---

## Usage — IRIS research_rotorquant profile

Profile definition (in `backend/agent/local_model_manager.py::PROFILES`):

```python
"research_rotorquant": {
    "n_gpu_layers": -1,
    "n_ctx": 131072,             # 128 k — unlocked by planar3 compression
    "flash_attn": True,
    "cache_type_k": "planar3",
    "cache_type_v": "planar3",
    "n_batch": 2048,
    "offload_kv_cache": True,
    "unified_kv_cache": True,
    "keep_model_in_memory": True,
    "use_mmap": True,
    "requires_fork": "llama-cpp-turboquant",
},
```

Select it from the ModelsScreen or via `apply_inference_settings` with
`profile: "research_rotorquant"`. When the fork isn't installed,
`LocalModelManager._resolve_profile_for_environment()` silently falls back to
`performance` and logs a warning — the load still succeeds.

---

## Rollback

```bash
pip install --force-reinstall --no-cache-dir llama-cpp-python
```

That restores the upstream package. `research_rotorquant` will fall back to
`performance` automatically at load time.
