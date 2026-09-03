"""
Remove LFM2.5-VL-1.6B model files and HuggingFace cache.
Safe to run multiple times (idempotent).

Usage:
    python scripts/uninstall_old_vl.py
"""
import shutil
from pathlib import Path

TARGETS = [
    Path.home() / "models" / "LFM2.5-VL-1.6B",
    Path.home() / ".cache" / "huggingface" / "hub" / "models--LiquidAI--LFM2.5-VL-1.6B-GGUF",
]

removed = []
for path in TARGETS:
    if path.exists():
        print(f"[REMOVING] {path}")
        shutil.rmtree(path, ignore_errors=True)
        removed.append(str(path))
    else:
        print(f"[SKIP] Not found: {path}")

print()
if removed:
    print(f"Removed {len(removed)} path(s). Old LFM2.5-VL-1.6B uninstalled.")
else:
    print("Nothing to remove — old model already gone.")
