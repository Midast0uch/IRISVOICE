"""Parakeet GPU ASR via sherpa-onnx (no torch/transformers at runtime).

Replaces the transformers subprocess worker (``parakeet_worker.py``), which
paid a ~8-minute cold load (torch import chain + 723-tensor Python dispatch
on HDD). The sherpa runtime is a single native library: ~1-2 s import,
~4-12 s session build cold, sub-second inference — measured 2026-09-03
(pin_fadf292948bb).

Model layout (sherpa transducer)::

    data/models/parakeet-sherpa/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/
        encoder.int8.onnx / decoder.int8.onnx / joiner.int8.onnx / tokens.txt

Notes:
  * Default provider is CPU (2026-09-03 measurement: int8 encoder has no
    CUDA kernels, so CUDA EP silently runs encoder math on CPU anyway while
    costing ~+1 GB RAM and ~1 GB VRAM; CPU is faster at every clip length:
    0.16 s vs 0.30 s short, ~1.05 s vs ~1.45 s for 9 s audio). Override with
    IRIS_PARAKEET_PROVIDER=cuda when true-GPU (fp16) weights land.
  * The CUDA wheel needs cuDNN 9 (``cudnn64_9.dll``). torch already bundles
    it, so :func:`ensure_dll_path` puts ``torch/lib`` on the DLL search
    path — no system install required.
  * Everything here is imported LAZILY from ``voice_command`` (first
    utterance), never at backend boot, to preserve the 0.41 GB idle profile.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Repo root = parents[2] of this file (backend/audio/parakeet_sherpa.py).
_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent

MODEL_DIR = Path(
    os.environ.get(
        "IRIS_PARAKEET_SHERPA_DIR",
        str(
            _PROJECT_DIR
            / "data"
            / "models"
            / "parakeet-sherpa"
            / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
        ),
    )
)

PROVIDER = os.environ.get("IRIS_PARAKEET_PROVIDER", "cpu").strip().lower() or "cpu"

ENCODER = MODEL_DIR / "encoder.int8.onnx"
DECODER = MODEL_DIR / "decoder.int8.onnx"
JOINER = MODEL_DIR / "joiner.int8.onnx"
TOKENS = MODEL_DIR / "tokens.txt"


def model_files_present() -> bool:
    """True when all four sherpa model files exist on disk."""
    return all(p.is_file() for p in (ENCODER, DECODER, JOINER, TOKENS))


def _torch_lib_dir() -> Optional[str]:
    """Locate torch's bundled-cuDNN lib dir WITHOUT importing torch.

    ``import torch`` costs ~0.5–1 GB RAM in the calling process (measured
    2026-09-03: backend 0.4 → 1.4 GB on first speech). Path probing via
    find_spec touches only the filesystem.
    """
    try:
        import importlib.util as _ilu

        _spec = _ilu.find_spec("torch")
        if _spec and _spec.origin:
            _lib = os.path.join(
                os.path.dirname(os.path.dirname(_spec.origin)), "lib"
            )
            if os.path.isdir(_lib):
                return _lib
    except Exception:
        pass
    return None


def torch_lib_dir() -> Optional[str]:
    """Public accessor for the spawner (parent prepends it to the child PATH)."""
    return _torch_lib_dir()


def ensure_dll_path() -> None:
    """Put torch's bundled cuDNN on the Windows DLL search path (best-effort).

    The sherpa CUDA wheel links ``cudnn64_9.dll`` without shipping it; torch
    bundles cuDNN 9, so reuse it instead of requiring a system install.
    Without it the CUDA provider fails to initialise (CPU still works).
    Never imports torch (see _torch_lib_dir).
    """
    try:
        dll_dir = _torch_lib_dir()
        if dll_dir:
            try:
                os.add_dll_directory(dll_dir)
            except Exception:
                # add_dll_directory may raise if already added; PATH fallback.
                os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
            logger.debug("[ParakeetSherpa] torch/lib on DLL path for cuDNN 9")
    except Exception as exc:
        logger.debug("[ParakeetSherpa] torch DLL path unavailable: %s", exc)


def build_recognizer(provider: Optional[str] = None):
    """Build a sherpa OfflineRecognizer for the Parakeet transducer model.

    Tries ``provider`` (default :data:`PROVIDER`), falling back to CPU when
    the requested provider fails — a missing cuDNN must never wedge voice.
    Raises RuntimeError only when every provider fails.
    """
    ensure_dll_path()
    import sherpa_onnx  # lazy: ~1-2 s import, must not run at backend boot

    wanted = (provider or PROVIDER).strip().lower() or "cuda"
    tried = []
    for prov in dict.fromkeys([wanted, "cpu"]):
        try:
            rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(ENCODER),
                decoder=str(DECODER),
                joiner=str(JOINER),
                tokens=str(TOKENS),
                num_threads=2,
                provider=prov,
                model_type="nemo_transducer",
            )
            logger.info("[ParakeetSherpa] recognizer built (provider=%s)", prov)
            return rec, prov
        except Exception as exc:
            tried.append(f"{prov}: {exc}")
            logger.warning(
                "[ParakeetSherpa] provider '%s' failed (%s) — trying next",
                prov,
                str(exc)[:160],
            )
    raise RuntimeError("no sherpa provider available: " + " | ".join(tried))
