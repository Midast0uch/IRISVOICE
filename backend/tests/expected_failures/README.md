# Expected Failures

Tests in this folder are **intentionally red** in CI — they are behavioral proofs that require hardware or a live server that CI does not have. They are not broken tests to fix by weakening the assertion; they are the spec’s acceptance gates.

## Why this folder exists
- Normal `pytest` should be green without hardware. That’s `backend/tests/unit`, `contract`, `behavioral` (mocked).
- Tests here need a real `llama-server` + GPU or a faked in-process path that the current test harness does not force. Keeping them here makes `git status` / CI clearly show `expected_failures` vs real regressions, so a new contributor doesn’t delete a critical spec test confusing it for a flake.

## Contents
- `test_closed_loop_tuning.py` — Phase 3 Wave 4 T12 (`REQ-2 AC1-2 / REQ-5`). Injects 3× sub-target `record_tps(5.0)` then asserts next `load_model` uses reduced `n_ctx`. Red cause: `LocalModelManager._inprocess_gpu_capable()==False` (venv `llama-cpp-python` no CUDA) → `load_model` ignores the `_load_inprocess` patch and spawns a real `llama-server.exe` → 180s timeout → `captured=={}`. Fix is **not** to weaken to `assert captured.get("params")` — fix is to patch `_inprocess_enabled`/`_inprocess_gpu_capable` to `True` (see `T12` in `specs/closed-loop-local-model-tuning/tasks.md`).

## How to run
```bash
# normal — green, no hardware
pytest backend/tests/unit backend/tests/contract backend/tests/behavioral -q

# expected-failures — requires GPU or the T12 mock fix; may be red here by design
pytest backend/tests/expected_failures -v

# run all including expected (for the live-test harness)
pytest backend/tests -v --tb=short
```

## Adding a new expected failure
1. Move the file here, do NOT add `xfail` in the original location to hide it.
2. Add a row below with REQ, wave, and the hardware/harness requirement.
3. Add a `pin_add` explaining the env and the fix (so `mcm_recall` surfaces it).

| File | REQ | Env needed | Fix |
|------|-----|------------|-----|
| `test_closed_loop_tuning.py::test_next_load_uses_reduced_context` | REQ-2 AC1/AC2, REQ-5 | GPU offload or mocked `_load_inprocess` force | Patch `_inprocess_enabled`/`_inprocess_gpu_capable` → True |

## Live-test logs that must be tracked
Live validation before landmark needs these artefacts (see `pin_33e6ce48d448`):
- `.iris-config/local_model_configs.json` (`measured_tps` non-null) + `local_model_machine_bandwidth.json` (`effective_bandwidth` non-null)
- `get_ledger_snapshot()` → `{ledger:{vision:1.2, brain:…}, budget, headroom}`
- `get_failure_info()` → `{failure_class, retry_count}` on OOM vs `unusable` on corrupt
- `derive_config` log line `base_tps=… source=machine_bandwidth|uncalibrated_default` and `uncalibrated conservative cap …` / `grow capped …`
- `inference_event` WS unchanged + `generate()` still 3-tuple (CT-2)
Store live logs under `.iris-logs/live/<date>/` (gitignored, per-machine) and pin a redacted summary.
