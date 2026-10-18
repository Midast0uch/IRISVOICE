"""Exactly ONE playback lock exists in the process (2026-10-16).

The one-utterance rule needs a single lock object. A lock is per module object,
so the trap is a dual import: ``backend.audio.pipeline`` and the bare
``audio.pipeline`` (when a harness puts ``backend/`` on ``sys.path``) are two
module objects. Without care they build two locks, and the rule silently stops
working — the code still runs, the value (the lock) is wrong.

``backend/audio/pipeline.py`` anchors the lock on the ``sys`` module (a true
process singleton) to defeat this. This file pins that anchor:

  * in-process: no two loaded ``*pipeline`` modules hold different locks
  * in a subprocess: importing BOTH paths yields ONE lock object

``test_both_import_paths_share_one_lock`` fails on pre-anchor code with
"two playback locks".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _loaded_pipeline_locks() -> dict:
    import backend.audio.pipeline  # noqa: F401  (ensure the canonical one is loaded)

    locks = {}
    for name, mod in list(sys.modules.items()):
        if not name.endswith("pipeline"):
            continue
        lock = getattr(mod, "_PLAYBACK_LOCK", None)
        if lock is not None:
            locks[name] = id(lock)
    return locks


def test_no_two_loaded_pipeline_modules_hold_different_locks():
    locks = _loaded_pipeline_locks()
    assert locks, "no pipeline module exposing _PLAYBACK_LOCK was loaded"
    assert len(set(locks.values())) == 1, f"more than one playback lock: {locks}"


def test_both_import_paths_share_one_lock():
    """A harness that puts ``backend/`` on sys.path must not create a second
    lock. This is the dual-import trap, pinned."""
    code = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import backend.audio.pipeline as a\n"
        f"sys.path.insert(0, {str(ROOT / 'backend')!r})\n"
        "import audio.pipeline as b\n"
        "print(json.dumps({\n"
        "  'same': a._PLAYBACK_LOCK is b._PLAYBACK_LOCK,\n"
        "  'modules': [m for m in sys.modules if m.endswith('pipeline')],\n"
        "}))\n"
    )
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)  # never inherit the sandbox sitecustomize
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
        env=env,
    )
    assert proc.returncode == 0, f"probe failed: {proc.stderr[-500:]}"
    out = json.loads((proc.stdout or "").strip().splitlines()[-1])
    assert out["same"] is True, (
        "two playback locks: backend.audio.pipeline and audio.pipeline are "
        f"separate module objects with separate locks ({out['modules']})"
    )
