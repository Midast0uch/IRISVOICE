#!/usr/bin/env python3
"""
Test MTP model detection and print model scan results.
Run from repo root: python scripts/test_mtp_detection.py
"""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "agent"))

from local_model_manager import LocalModelManager, IRISVOICE_ROOT


def main():
    mgr = LocalModelManager()
    print(f"MODELS_DIR: {mgr.MODELS_DIR}")
    print(f"IRISVOICE_ROOT: {IRISVOICE_ROOT}")
    print()

    models = mgr.scan_models()
    print(f"Total models found: {len(models)}")

    mtp_models = [m for m in models if m.get("is_mtp_capable")]
    print(f"MTP-capable models: {len(mtp_models)}")
    for m in mtp_models:
        print(f"  - {m['display_name']} (MTP={m['is_mtp_capable']})")
        print(f"    Path: {m['path']}")
        print(f"    Quant: {m['quantization']}, VRAM est: {m['vram_estimate_gb']} GB")

    # Find Qwopus specifically
    qwopus = [m for m in models if "qwopus" in m["display_name"].lower()]
    if qwopus:
        print(f"\nQwopus models found: {len(qwopus)}")
        for m in qwopus:
            print(f"  - {m['display_name']} -> is_mtp_capable={m['is_mtp_capable']}")
    else:
        print("\nNo Qwopus models found. Check MODELS_DIR.")


if __name__ == "__main__":
    main()
