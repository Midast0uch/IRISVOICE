"""The wake path never loads torch into the backend (2026-10-27).

violawake_sdk/vad.py imported the silero_vad package at module level, which
imports torch (CUDA build, ~40 DLLs). The backend died with a native access
violation inside torch's _load_dll_libraries on the iris-wake-audio-init
thread on 3 boots (2026-10-25 11:56, 14:43; 2026-10-27 12:57). The Silero
gate now runs the same ONNX model on onnxruntime (_SileroOnnxVAD); measured
parity with violawake's SileroVAD on two recorded phrases: max |diff| 0.0.

Driven in a fresh interpreter (torch must not be in sys.modules afterwards).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

_PROBE = r"""
import json, sys
sys.path.insert(0, %r)
import backend.voice.violawake_detector as d
vad = d._SileroOnnxVAD()
quiet = vad.process_frame(b"\0" * 640)
vad.reset()
from violawake_sdk import WakeDetector  # noqa: F401 - the package import the wake head needs
print(json.dumps({"torch": "torch" in sys.modules, "quiet": quiet}))
"""


def test_the_wake_path_runs_its_vad_without_loading_torch():
    out = subprocess.run([sys.executable, "-c", _PROBE % str(ROOT)], capture_output=True, text=True,
                         timeout=180, cwd=str(ROOT))
    assert out.returncode == 0, out.stderr[-2000:]
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert res["torch"] is False, "torch was imported into the backend by the wake path"
    assert 0.0 <= res["quiet"] < 0.5          # silence is not speech


def test_the_detector_uses_the_onnx_vad():
    src = (ROOT / "backend" / "voice" / "violawake_detector.py").read_text(encoding="utf-8")
    assert "from violawake_sdk.vad import SileroVAD" not in src
    assert "self._vad = _SileroOnnxVAD()" in src
