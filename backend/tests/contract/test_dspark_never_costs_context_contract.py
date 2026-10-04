"""A DSpark drafter never costs the model its context (live 2026-10-03).

Before: the drafter's VRAM reserve joined the pre-flight check, the check
failed at the profile's n_ctx 32768, and the GPU-only ladder cut the context to
8192 - the tool model loaded from the UI ran at a quarter of its context so a
speed helper could fit.

Now: the drafter is checked at the FULL config first; if it does not fit it is
dropped, and only then may the ladder touch n_ctx. Its reserve grows with the
context (measured 2.6B drafter: +800 MiB at 8k, +1040 MiB at 32k).
"""

import asyncio

import pytest

from backend.agent.local_model_manager import LocalModelManager


class _Stop(Exception):
    pass


def _drive(monkeypatch, tmp_path, fits_with_draft: bool):
    model = tmp_path / "LFM2.5-2.6B-QAD-Q4_0.gguf"
    model.write_bytes(b"\0" * 1024)
    mgr = LocalModelManager()
    seen = {}

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr("backend.agent.local_model_manager.kill_orphan_servers", lambda: None)
    monkeypatch.setattr(mgr, "unload_model", _noop)
    monkeypatch.setattr(mgr, "parse_gguf_metadata", lambda p: {
        "architecture": "lfm2", "block_count": 30, "context_length": 128000})
    monkeypatch.setattr(mgr, "_find_projector_for_model", lambda p: (None, 0.0))
    monkeypatch.setattr(mgr, "_find_drafter_for_model", lambda p: ("D:/m/X-DSpark.gguf", 0.19))
    monkeypatch.setattr(mgr, "_inprocess_enabled", lambda: False)

    def _preflight(model_path, params, model_meta=None, purpose="chat", mmproj_size_gb=0.0):
        seen.setdefault("checks", []).append((int(params.get("n_ctx") or 0), round(mmproj_size_gb, 2)))
        # as live: with the drafter only a cut context fits
        if mmproj_size_gb > 0 and not fits_with_draft and int(params.get("n_ctx") or 0) > 8192:
            return "VRAM tight"
        return None

    monkeypatch.setattr(mgr, "_preflight_resource_check", _preflight)

    def _cmd(model_path, params, is_mtp=False, mmproj_path=None, purpose="chat", draft_path=None):
        seen["n_ctx"], seen["draft"] = params.get("n_ctx"), draft_path
        raise _Stop()

    monkeypatch.setattr(mgr, "_build_server_cmd", _cmd)
    with pytest.raises(_Stop):
        asyncio.run(mgr.load_model(str(model), profile="balanced",
                                   custom_params={"n_ctx": 32768}, purpose="tool"))
    return seen


def test_a_drafter_that_does_not_fit_is_dropped_before_the_context_is_cut(monkeypatch, tmp_path):
    seen = _drive(monkeypatch, tmp_path, fits_with_draft=False)
    assert seen["n_ctx"] == 32768
    assert seen["draft"] is None
    # the drafter was checked at the full context, with its 32k-sized reserve
    assert seen["checks"][0] == (32768, round(LocalModelManager.draft_reserve_gb(0.19, 32768), 2))


def test_a_drafter_that_fits_loads_with_the_full_context(monkeypatch, tmp_path):
    seen = _drive(monkeypatch, tmp_path, fits_with_draft=True)
    assert seen["draft"] == "D:/m/X-DSpark.gguf"
    assert seen["n_ctx"] == 32768


def test_the_reserve_grows_with_the_context():
    r8, r32 = (LocalModelManager.draft_reserve_gb(0.19, n) for n in (8192, 32768))
    # measured: +800 MiB at 8k, +1040 MiB at 32k (file 0.19 GB included)
    assert 0.75 <= r8 <= 0.85 and 0.95 <= r32 <= 1.10 and r32 > r8
