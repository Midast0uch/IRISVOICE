"""
Download LFM2.5-VL-450M GGUF files from HuggingFace.
Saves to ~/models/LFM2.5-VL-450M/ (cross-platform).

Usage:
    python scripts/download_vl_model.py

Requires: huggingface_hub  (pip install huggingface_hub)
          HF_TOKEN env var or prior `huggingface-cli login`
"""
import os
import sys
from pathlib import Path

REPO_ID   = "LiquidAI/LFM2.5-VL-450M-GGUF"
MODEL_FILE  = "LFM2.5-VL-450M-Q4_0.gguf"
MMPROJ_FILE = "mmproj-LFM2.5-VL-450m-Q8_0.gguf"
LOCAL_DIR   = Path.home() / "models" / "LFM2.5-VL-450M"

def main():
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("[ERROR] huggingface_hub not installed. Run: pip install huggingface_hub")
        sys.exit(1)

    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")

    files = [MODEL_FILE, MMPROJ_FILE]
    for filename in files:
        dest = LOCAL_DIR / filename
        if dest.exists():
            print(f"[SKIP] Already exists: {dest}")
            continue
        print(f"[DOWNLOAD] {filename} → {dest}")
        hf_hub_download(
            repo_id=REPO_ID,
            filename=filename,
            local_dir=str(LOCAL_DIR),
            token=token,
        )
        print(f"[OK] {filename}")

    print(f"\nAll files saved to: {LOCAL_DIR}")
    print("Start vision server: pwsh scripts/start_vl.ps1  (Windows) or bash start_vl.sh  (Linux/macOS)")

if __name__ == "__main__":
    main()
