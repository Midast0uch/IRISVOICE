# Scripts — Reference Index

> Utility scripts organized by purpose. Run from project root unless noted.

## Directory Structure

| Subdirectory | Purpose | Contents |
|-------------|---------|----------|
| `benchmarks/` | Performance benchmarks & profiling | 7 files |
| `build/` | Build, install & download helpers | 6 files |
| `playwright/` | Playwright UI automation & exploration | 10 files |
| *(root)* | Standalone demos & smoke tests | 2 files |

---

## `benchmarks/`

| File | Description |
|------|-------------|
| `bench_9b_tps.py` | Tokens-per-second benchmark for 9B model |
| `benchmark_mtp.py` | MTP (Multi-Turn Predict) benchmark |
| `benchmark_runner.py` | Benchmark runner utility |
| `compute_model_profiles.py` | Compute model capability profiles |
| `iris_benchmark.mjs` | IRIS frontend interaction benchmark (Playwright) |
| `profile_backend_idle.py` | Backend idle resource profiling |
| `run_benchmark.py` | Main benchmark orchestrator |

## `build/`

| File | Description |
|------|-------------|
| `build_backend.py` | PyInstaller build for Tauri sidecar binary |
| `download_models.py` | Download ML models from HuggingFace |
| `download_vl_model.py` | Download Vision-Language model |
| `start-launcher.bat` | Windows batch launcher |
| `start_vl.ps1` | PowerShell start script for VL model |
| `uninstall_old_vl.py` | Remove old VL model files + HF cache |

## `playwright/`

| File | Description |
|------|-------------|
| `click_chat.mjs` | Click chat element and verify |
| `explore_ui_v5.mjs` | **Latest** — UI exploration with screenshot + click + element scan |
| `interact_ui.mjs` | General UI interaction test |
| `navigate_ui.mjs` | UI navigation test |
| `open_chat.mjs` | Open chat panel |
| `page_structure.mjs` | Page structure analysis |
| `test_pw.mjs` | Minimal Playwright connectivity test |
| `use_ui.mjs` | UI usage flow test |
| `verify_frontend.mjs` | Frontend verification |
| `wait_and_click.mjs` | Wait-for-element + click pattern |

## Root (`scripts/`)

| File | Description |
|------|-------------|
| `paint_iris_demo.py` | Keyboard-first + Vision-verified Paint operator demo |
| `smoke_tts.py` | CosyVoice3 TTS smoke test |

---

## Notes

- Old `explore_ui` variants (v1–v4) were deleted — superseded by `explore_ui_v5.mjs`.
- Archived WS/OpenAI test scripts removed — superseded by `backend/tests/` and the REST API.
