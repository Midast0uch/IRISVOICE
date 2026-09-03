# Migration Notes: Picovoice/Porcupine → Violawake

> Session 278 (2026-09-01). Part of the audio-pipeline overhaul spec
> (`specs/replace-picovoice-wakeword/`).

## What changed

The wake word detector moved from Picovoice Porcupine (proprietary, requires an
access key, uses `.ppn` files) to Violawake (open-source, Apache 2.0, custom
ONNX head + OpenWakeWord backbone).

- **Old**: `PorcupineWakeWordDetector` + `pvporcupine` + `PICOVOICE_ACCESS_KEY` + `.ppn` files
- **New**: `ViolawakeWakeWordDetector` + `violawake[oww]` + `data/hey iris_237_1788045452.onnx`

## Persisted settings migration

The following persisted settings are affected. The migration is **automatic and
non-destructive** — old values are ignored, not deleted.

| Setting | Old meaning | New meaning |
|---------|-------------|-------------|
| `wake_phrase` | pvporcupine builtin keyword (jarvis/computer/bumblebee/porcupine) or custom `.ppn` name | Single validated "Hey Iris" |
| `custom_model_path` | Path to a `.ppn` file | Path to the ONNX model (or None → project-root default) |
| `detection_sensitivity` | Porcupine sensitivity 0.0-1.0 | Detector threshold with a 0.8 floor (see pin_f55516e6715c) |
| `PICOVOICE_ACCESS_KEY` | Required for Porcupine | **Ignored** — no longer read |

### What happens on upgrade

1. `WakeConfig` defaults to `wake_phrase="Hey Iris"`, `custom_model_path=None`.
2. `get_custom_model_path()` resolves the project-root ONNX model if no explicit
   path is set.
3. `main.py` discovery calls `resolve_onnx_model()` which finds
   `data/hey iris_237_1788045452.onnx`.
4. The engine constructs `ViolawakeWakeWordDetector` with the resolved path.
5. Any stale `PICOVOICE_ACCESS_KEY` in `.env`/`.env.local` is ignored.

### What is NOT deleted automatically

- `models/wake_words/hey-iris_en_windows_v4_0_0.ppn` — kept for rollback.
- `PICOVOICE_ACCESS_KEY` in `.env` — kept but ignored.
- `pvporcupine` package — removed from `requirements.txt` but not uninstalled
  from an existing venv (a fresh `pip install -r requirements.txt` will not
  install it; an existing install is harmless).

## Rollback

To roll back to Porcupine:
1. Re-add `pvporcupine>=4.0.0` to `requirements.txt` and `pip install`.
2. Restore `PICOVOICE_ACCESS_KEY` in `.env`.
3. Revert `backend/audio/engine.py` to use `PorcupineWakeWordDetector`.
4. Restore the `.ppn` discovery path in `wake_word_discovery.py`.

## Dependencies

- Added: `violawake[oww]>=0.2.10` (pulls `openwakeword>=0.6`, `onnxruntime`)
- Removed: `pvporcupine>=4.0.0`
- The ONNX model `data/hey iris_237_1788045452.onnx` is the source artifact and
  must not be deleted.