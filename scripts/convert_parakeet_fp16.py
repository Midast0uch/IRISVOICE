"""Pre-convert the Parakeet ASR model to fp16 and cache it locally.

The stock checkpoint is a 2.39 GB fp32 safetensors file. Loading it at runtime
reads 2.39 GB from disk AND converts fp32->fp16, which is why the Parakeet
worker takes ~5 min to become ready. This script converts the model to fp16
once and saves it to ``data/models/parakeet-fp16/`` (~1.2 GB), so the worker
loads the fp16 file directly — roughly halving the disk read and skipping the
conversion.

Run once after a fresh clone / model update:
    python scripts/convert_parakeet_fp16.py

The worker (backend/audio/parakeet_worker.py) automatically uses the fp16 cache
when ``data/models/parakeet-fp16/model.safetensors`` exists, and falls back to
the HF checkpoint otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CACHE = _REPO_ROOT / "data" / "models" / "parakeet-fp16"
_MODEL_NAME = "nvidia/parakeet-tdt-0.6b-v3"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        default=str(_DEFAULT_CACHE),
        help="where to write the fp16 model (default: data/models/parakeet-fp16)",
    )
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    import torch
    from transformers import AutoProcessor, ParakeetForTDT

    print(f"Loading {_MODEL_NAME} (fp32 -> fp16)...")
    model = ParakeetForTDT.from_pretrained(_MODEL_NAME, torch_dtype=torch.float16)
    processor = AutoProcessor.from_pretrained(_MODEL_NAME)

    print(f"Saving fp16 model + processor to {cache_dir} ...")
    model.save_pretrained(str(cache_dir), safe_serialization=True)
    processor.save_pretrained(str(cache_dir))

    size_mb = sum(
        p.stat().st_size for p in cache_dir.rglob("*") if p.is_file()
    ) / (1024**2)
    print(f"Done. fp16 cache written ({size_mb:.1f} MB).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())