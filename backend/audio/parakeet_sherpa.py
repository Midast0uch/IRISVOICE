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
  * Provider is resolved from ``IRIS_PARAKEET_PROVIDER`` (default ``cpu``).
    Set it to ``cuda`` to run on the GPU; the operator's choice in ``.env``
    is authoritative (2026-09-12).
  * HISTORY / why the CUDA path was dead until 2026-09-12: this module used
    to document CPU as the default because a 2026-09-03 measurement showed
    CPU faster (0.16 s vs 0.30 s short). That measurement was taken while
    ``_torch_lib_dir`` was returning the WRONG directory, so the CUDA
    provider could never actually load — every "CUDA" run was silently CPU
    with ORT noise, and the timings compared CPU against CPU. After the path
    fix, ``IRIS_PARAKEET_PROVIDER=cuda`` builds the recognizer on the GPU in
    ~10-12 s. Re-measure before claiming CPU is faster.
  * The CUDA wheel needs cuDNN 9 (``cudnn64_9.dll``). torch already bundles
    it under ``<torch>/lib``, so :func:`ensure_dll_path` puts THAT directory
    on the DLL search path — no system install required.
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

# Default is cuda — the documented operator decision (audio-pipeline.md:70,
# HANDOFF_AUDIO_PIPELINE.md:261: "CUDA is the wired default (user decision)").
# This defaulted to "cpu" from the 2026-09-03 swap until 2026-09-12, which is
# half of why Parakeet silently ran on CPU for ~9 days. A missing cuDNN now
# falls back to CPU with a LOUD warning (see build_recognizer), so a machine
# without the CUDA stack still works — it just cannot be quiet about it.
# Override with IRIS_PARAKEET_PROVIDER=cpu to force the CPU path.
PROVIDER = os.environ.get("IRIS_PARAKEET_PROVIDER", "cuda").strip().lower() or "cuda"

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
            # torch's bundled cuDNN lives in <torch>/lib, i.e.
            # site-packages/torch/lib — NOT site-packages/lib. The previous
            # grandparent join put the WRONG directory on PATH, so
            # cudnn64_9.dll was never found and the CUDA provider silently
            # fell back to CPU (ORT logs "Error loading ... cudnn64_9.dll ...
            # missing", then build_recognizer's except-branch retries CPU).
            # Result: the worker built the 758 MB int8 recognizer on CPU while
            # docs/architecture/audio-pipeline.md claimed "Parakeet GPU".
            # Fixed 2026-09-12 — verified cuda now builds in ~10-12 s.
            _lib = os.path.join(os.path.dirname(_spec.origin), "lib")
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
            if prov != wanted:
                # A silent fallback hid a real cuDNN path bug for months
                # (see module docstring). Never let it be quiet again.
                logger.warning(
                    "[ParakeetSherpa] FALLBACK: requested provider=%r but built "
                    "provider=%r — GPU path unavailable. Set IRIS_PARAKEET_PROVIDER "
                    "correctly or install cuDNN 9.",
                    wanted,
                    prov,
                )
            return rec, prov
        except Exception as exc:
            tried.append(f"{prov}: {exc}")
            logger.warning(
                "[ParakeetSherpa] provider '%s' failed (%s) — trying next",
                prov,
                str(exc)[:160],
            )
    raise RuntimeError("no sherpa provider available: " + " | ".join(tried))
