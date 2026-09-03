#!/usr/bin/env python3
"""
Standing Violawake wake-pipeline validation harness.

Validates (REQ-8):
  1. ONNX model discovery resolves deterministically.
  2. The Violawake detector loads and reports ready.
  3. A short offline replay of silence produces no false detection.
  4. Detector failure (missing model) fails closed without disabling audio/STT.

Run:  python scripts/validate_wake_pipeline.py
Exit: 0 on success, 1 on any failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# Project root (scripts/ -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

PASS = 0
FAIL = 1


def check(name: str, ok: bool, detail: str = "") -> bool:
    """Print a check result and return whether it passed."""
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    print("=== Violawake Wake Pipeline Validation ===")
    all_ok = True

    # 1. Model discovery
    print("\n[1] ONNX model discovery")
    try:
        from backend.voice.wake_word_discovery import WakeWordDiscovery

        model = WakeWordDiscovery().resolve_onnx_model()
        all_ok &= check(
            "resolve_onnx_model returns a model",
            model is not None,
            model.path if model else "no model found",
        )
        if model:
            all_ok &= check(
                "model is .onnx",
                model.path.endswith(".onnx"),
                model.filename,
            )
    except Exception as exc:
        all_ok &= check("model discovery", False, str(exc))

    # 2. Detector readiness
    print("\n[2] Detector readiness")
    try:
        from backend.voice.violawake_detector import ViolawakeWakeWordDetector

        det = ViolawakeWakeWordDetector()
        status = det.get_status()
        all_ok &= check(
            "detector enabled",
            det.is_enabled(),
            f"state={status['state']}",
        )
        all_ok &= check(
            "sample_rate=16000", det.sample_rate == 16000, str(det.sample_rate)
        )
        all_ok &= check(
            "frame_length=320", det.frame_length == 320, str(det.frame_length)
        )
    except Exception as exc:
        all_ok &= check("detector readiness", False, str(exc))
        det = None

    # 3. Offline silence replay (no false detection)
    print("\n[3] Offline silence replay")
    if det is not None and det.is_enabled():
        false_positives = 0
        for _ in range(100):
            detected, _name = det.process_frame(np.zeros(320, dtype=np.int16))
            if detected:
                false_positives += 1
        all_ok &= check(
            "no false detection on 100 silence frames",
            false_positives == 0,
            f"{false_positives} false positives",
        )
        det.cleanup()
    else:
        all_ok &= check("silence replay", False, "detector not available")

    # 4. Fail-closed on missing model
    print("\n[4] Fail-closed on missing model")
    try:
        from backend.voice.violawake_detector import ViolawakeWakeWordDetector

        bad = ViolawakeWakeWordDetector(model_path="/nonexistent/model.onnx")
        all_ok &= check(
            "missing model disables detector",
            not bad.is_enabled(),
            f"state={bad.get_status()['state']}",
        )
        # process_frame must still return safe values (audio/STT unaffected)
        detected, name = bad.process_frame(np.zeros(320, dtype=np.int16))
        all_ok &= check(
            "disabled detector returns safe values",
            detected is False and name is None,
        )
        bad.cleanup()
    except Exception as exc:
        all_ok &= check("fail-closed", False, str(exc))

    print("\n" + ("=== ALL CHECKS PASSED ===" if all_ok else "=== FAILURES DETECTED ==="))
    return PASS if all_ok else FAIL


if __name__ == "__main__":
    sys.exit(main())