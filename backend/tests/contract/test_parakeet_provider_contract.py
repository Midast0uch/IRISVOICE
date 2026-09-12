"""CT-PP — Parakeet provider contract (regression pin, 2026-09-12).

Pins the two defects that silently moved Parakeet off the GPU for ~9 days
(2026-09-03 → 2026-09-12):

  1. ``_torch_lib_dir`` returned ``<site-packages>/lib`` instead of
     ``<site-packages>/torch/lib``. torch bundles cuDNN 9 there, so the CUDA
     provider could never find ``cudnn64_9.dll`` and ORT fell back to CPU.
  2. The CPU fallback was SILENT (a warning that read like a normal retry),
     so every "GPU" run was really CPU while the docs claimed "Parakeet GPU".

Contract:
  CT-PP1  ``torch_lib_dir()`` resolves to ``<torch>/lib`` — the directory
          that actually holds torch's bundled cuDNN — never ``site-packages/lib``.
  CT-PP2  The provider is read from ``IRIS_PARAKEET_PROVIDER`` (env wins).
  CT-PP3  ``.env`` wires ``cuda`` (the documented operator decision).
  CT-PP4  A provider fallback is LOUD — it logs a FALLBACK warning naming both
          the requested and the built provider.

Run: python -m pytest backend/tests/contract/test_parakeet_provider_contract.py -q
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


# ── CT-PP1: the cuDNN directory ────────────────────────────────────────────


def test_torch_lib_dir_points_at_torch_lib_not_site_packages():
    """The returned dir MUST be <torch>/lib, not its parent.

    This is the exact off-by-one that killed the CUDA path: cuDNN lives in
    ``.../site-packages/torch/lib``, but the old code joined one level too
    high and returned ``.../site-packages/lib`` (which does not exist / has no
    cuDNN), so ``ensure_dll_path`` put a useless directory on the DLL path.
    """
    from backend.audio import parakeet_sherpa as ps

    lib = ps.torch_lib_dir()
    if lib is None:
        pytest.skip("torch is not installed in this environment")

    assert os.path.basename(lib).lower() == "lib", f"expected a 'lib' dir, got {lib}"
    assert os.path.basename(os.path.dirname(lib)).lower() == "torch", (
        f"torch_lib_dir() must be <...>/torch/lib (cuDNN lives there); got {lib}. "
        "A 'site-packages/lib' result is the 2026-09-12 regression."
    )


def test_torch_lib_dir_is_where_the_cudnn_dlls_actually_are():
    """If torch bundles cuDNN, the returned path must be the dir holding it.

    Structural assertion with a data check: on a CUDA torch build the returned
    directory contains ``cudnn*`` DLLs; if it does not (CPU-only torch), the
    test is skipped rather than failing — the structural test above still
    guards the path shape.
    """
    from backend.audio import parakeet_sherpa as ps

    lib = ps.torch_lib_dir()
    if lib is None or not os.path.isdir(lib):
        pytest.skip("torch/lib not present")

    cudnns = [n for n in os.listdir(lib) if n.lower().startswith("cudnn")]
    if not cudnns:
        pytest.skip("torch build bundles no cuDNN (CPU-only torch)")
    assert any(n.lower() == "cudnn64_9.dll" for n in cudnns), (
        f"expected cudnn64_9.dll in {lib}; found {cudnns}"
    )


# ── CT-PP2: env override ───────────────────────────────────────────────────


def test_provider_env_overrides_the_default():
    """``IRIS_PARAKEET_PROVIDER`` must be honored at import.

    Run in a subprocess so the module-level PROVIDER constant is read fresh
    and this test cannot pollute the in-process module for other suites.
    """
    code = (
        "import os; os.environ['IRIS_PARAKEET_PROVIDER']='cuda'; "
        "from backend.audio import parakeet_sherpa as p; print(p.PROVIDER)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=_REPO, timeout=120,
    )
    assert out.returncode == 0, f"subprocess failed: {out.stderr[-400:]}"
    assert out.stdout.strip().lower() == "cuda", out.stdout


# ── CT-PP3: the shipped default is the documented GPU decision ─────────────


def test_code_default_provider_is_cuda():
    """The CODE default must be cuda — the documented operator decision.

    Asserted against the code (not .env, which is gitignored and so cannot
    carry the fix to a fresh clone). The 2026-09-03 swap left this at "cpu"
    while the docs recorded CUDA as wired; that mismatch is half the ~9-day
    silent-CPU regression. Run in a subprocess with the env var REMOVED so the
    module-level default is read, not an inherited override.
    """
    code = (
        "import os; os.environ.pop('IRIS_PARAKEET_PROVIDER', None); "
        "from backend.audio import parakeet_sherpa as p; print(p.PROVIDER)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=_REPO, timeout=120,
        env={k: v for k, v in os.environ.items() if k != "IRIS_PARAKEET_PROVIDER"},
    )
    assert out.returncode == 0, f"subprocess failed: {out.stderr[-400:]}"
    assert out.stdout.strip().lower() == "cuda", (
        "the code default must be cuda (documented operator decision); got "
        f"{out.stdout.strip()!r}. A 'cpu' default is the 2026-09-03 regression."
    )


def test_env_example_documents_the_provider():
    """.env.example (tracked) must document IRIS_PARAKEET_PROVIDER.

    .env is gitignored, so the tracked template is where the setting is
    discoverable to a fresh clone.
    """
    path = os.path.join(_REPO, ".env.example")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert "IRIS_PARAKEET_PROVIDER" in text, (
        ".env.example must document IRIS_PARAKEET_PROVIDER so the GPU default "
        "is discoverable (the real .env is gitignored)."
    )


# ── CT-PP4: fallback is loud ───────────────────────────────────────────────


def test_provider_fallback_logs_a_loud_warning(monkeypatch, caplog):
    """When cuda fails and cpu is used, a FALLBACK warning must be logged.

    Directly pins the silent-downgrade defect: the old code logged only
    "trying next", which read as routine. The fix must make a downgrade
    impossible to miss.
    """
    from backend.audio import parakeet_sherpa as ps

    class _FakeRecognizer:
        pass

    class _FakeOffline:
        @staticmethod
        def from_transducer(**kwargs):
            if str(kwargs.get("provider", "")).lower() == "cuda":
                raise RuntimeError("simulated missing cudnn64_9.dll")
            return _FakeRecognizer()

    fake_sherpa = SimpleNamespace(OfflineRecognizer=_FakeOffline)
    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake_sherpa)

    with caplog.at_level(logging.WARNING, logger="backend.audio.parakeet_sherpa"):
        rec, prov = ps.build_recognizer(provider="cuda")

    assert prov == "cpu", "cuda must fall back to cpu when the CUDA EP cannot load"
    assert any("FALLBACK" in r.getMessage() for r in caplog.records), (
        "a provider downgrade must log a FALLBACK warning; silent fallback is the "
        "defect this pin exists to prevent. Records: "
        f"{[r.getMessage() for r in caplog.records]}"
    )
