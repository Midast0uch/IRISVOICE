"""Wave 0 baseline (T0c, pins T7): characterize vision model selection.

`backend/tools/lfm_vl_provider.py` had ZERO tests on either function before
T0c pinned TODAY-then's behavior (single (model, mmproj) pair, unconditional
3B preference, CPU-fallback-0 on no-fit). T7 (REQ-3, REQ-9) has now landed:
size-selection over a widest-first ladder against REAL free VRAM, ONE shared
estimator, and FAIL LOUDLY (raise + VISION_UNAVAILABLE chat system message)
when nothing fits. This file is updated IN PLACE, once, by T7 itself, per the
task's own instruction ("you ARE authorized to update that ONE file").

~~CONFLICT~~ RESOLVED 2026-08-18 by the user: "fail loudly and alert the user
through a system message." REQ-3 AC4 stands. The old CPU-fallback-on-no-fit
behavior this file used to pin is REMOVED (except for the genuinely distinct
"no CUDA device at all" case, which is not a VRAM-fit failure and is kept
unchanged below — see `test_resolve_gpu_layers_cpu_when_no_cuda`). Every
assertion that pinned the CPU-degrade / unconditional-3B / single-estimator-
free behavior has been INVERTED below; each inversion is called out in the
docstring of the test that carries it.
"""
import os

import pytest

from backend.agent.local_model_manager import LocalModelManager
from backend.tools import lfm_vl_provider as vl


# --- _find_vision_model ------------------------------------------------------
# Signature UNCHANGED where a candidate is found: still Optional[Tuple[str,
# str]]. What changed (T7): (a) the choice is now VRAM-aware — real free VRAM
# decides which candidate wins, not directory search order — and (b) when
# NOTHING fits (or nothing exists at all), the function now RAISES
# `VisionModelUnavailable` instead of silently returning None.


@pytest.fixture(autouse=True)
def _no_real_nvidia_smi(monkeypatch):
    """Block the real `nvidia-smi` subprocess call in every test in this file.

    Both `_find_vision_model` (via `_read_free_vram_gb`) and
    `_compute_vision_gpu_layers` shell out to nvidia-smi first and only fall
    back to LocalModelManager.get_hardware_info() when nvidia-smi is absent.
    This dev machine has a real GPU + nvidia-smi, so without this patch every
    "fits" / "does not fit" test below would be at the mercy of whatever is
    actually resident on the card right now.
    """
    monkeypatch.setattr("shutil.which", lambda _name: None)


@pytest.fixture(autouse=True)
def _clean_event_bus():
    """VISION_UNAVAILABLE is emitted on the EventBus singleton — reset the
    ring buffer/subscribers around each test so assertions never see a
    previous test's emission."""
    from backend.agent.event_bus import reset_event_bus_for_testing

    reset_event_bus_for_testing()
    yield
    reset_event_bus_for_testing()


def _default_mmproj_name(model_name: str) -> str:
    """Derive a projector filename that stem-matches `model_name` under
    `LocalModelManager._normalize_stem_for_vision_match` — the SAME function
    `scan_models()` uses to pair a projector to its base model. Shared by
    `_make_model_dir`'s default and by tests that need to predict the
    filename `_make_model_dir` will actually write (e.g. to key a faked
    `os.path.getsize` map)."""
    stem = model_name[:-len(".gguf")] if model_name.endswith(".gguf") else model_name
    match_key = LocalModelManager._normalize_stem_for_vision_match(stem)
    return f"mmproj-{match_key}-F16.gguf"


def _make_model_dir(base, dirname, model_name="model.gguf", mmproj_name=None):
    """Create <base>/<dirname>/ containing a .gguf and a mmproj*.gguf file.

    INPUT CHANGE (T15, called out per CLAUDE.md): `mmproj_name` now AUTO-
    DERIVES (`_default_mmproj_name`) from `model_name`'s normalized stem,
    instead of the old fixed placeholder "mmproj-x.gguf". T15 (REQ-10)
    sources `_discover_vision_candidates` from `LocalModelManager.
    scan_models()`'s `has_vision`-tagged entries rather than the retired
    per-directory glob (which paired ANY gguf + ANY mmproj*.gguf found in
    the SAME directory, regardless of name). Under scan_models()'s
    stem-based matching a mismatched placeholder pair like "model.gguf" +
    "mmproj-x.gguf" never becomes `has_vision: true`. Every assertion in
    this file is UNCHANGED; only the fixture's file-naming convention was
    updated so the projector still actually resolves to its base model
    under the new (correct, AC1-compliant) discovery source.
    """
    d = base / dirname
    d.mkdir(parents=True, exist_ok=True)
    if mmproj_name is None:
        mmproj_name = _default_mmproj_name(model_name)
    (d / model_name).write_bytes(b"\0")
    (d / mmproj_name).write_bytes(b"\0")
    return d


def _patch_hardware(monkeypatch, *, cuda_available=True, vram_free_gb=8.0):
    """Patch LocalModelManager.get_hardware_info AT THE CLASS so the REAL
    singleton (and therefore its real `estimate_vram_gb` / `parse_gguf_
    metadata`) is still used for the weights/KV math — only the VRAM figure
    itself is controlled."""
    def _fake(self, force_refresh: bool = False):
        return {"cuda_available": cuda_available, "vram_free_gb": vram_free_gb}

    monkeypatch.setattr(LocalModelManager, "get_hardware_info", _fake)


def _isolate_search_dirs(monkeypatch, tmp_path):
    """Redirect Path.home() to an empty tmp dir so this dev machine's real
    `~/models/LFM2.5-VL-450M` (present on the box this was authored on)
    never leaks into a ladder-selection assertion."""
    empty_home = tmp_path / "home"
    empty_home.mkdir(exist_ok=True)
    monkeypatch.setattr(vl.Path, "home", staticmethod(lambda: empty_home))


def _subscribe_capture(monkeypatch):
    """Subscribe to VISION_UNAVAILABLE and return a list that captures every
    emitted payload's `.data`."""
    from backend.agent.event_bus import get_event_bus, IRISStreamEvent

    captured = []
    get_event_bus().subscribe(IRISStreamEvent.VISION_UNAVAILABLE, lambda p: captured.append(p.data))
    return captured


def test_find_vision_model_raises_when_nothing_found(tmp_path, monkeypatch):
    """No model anywhere the function looks -> FAIL LOUDLY (REQ-3 AC4 edge
    case: "No VL model present on disk -> explicit error naming the expected
    repos"), not the old silent `None`.

    INVERTED from `test_find_vision_model_returns_none_when_nothing_found`:
    old assertion `vl._find_vision_model() is None` -> now
    `pytest.raises(vl.VisionModelUnavailable)`, and the message must name
    what IRIS expected to find so the user can act on it. Also asserts the
    VISION_UNAVAILABLE chat system message (REQ-3 AC6) fires with an empty
    ladder (nothing was even discovered).
    """
    empty_models_dir = tmp_path / "models_dir"
    empty_models_dir.mkdir()
    empty_home = tmp_path / "home"
    empty_home.mkdir()

    monkeypatch.setattr(LocalModelManager, "MODELS_DIR", empty_models_dir)
    monkeypatch.setattr(vl.Path, "home", staticmethod(lambda: empty_home))
    captured = _subscribe_capture(monkeypatch)

    with pytest.raises(vl.VisionModelUnavailable) as exc_info:
        vl._find_vision_model()

    msg = str(exc_info.value)
    assert "LFM2.5-VL" in msg or "download_vision_model" in msg
    assert exc_info.value.ladder == []

    assert len(captured) == 1
    assert captured[0]["ladder"] == []
    assert captured[0]["free_vram_gb"] == 0.0


def test_find_vision_model_returns_single_pair_when_it_fits(tmp_path, monkeypatch):
    """Return type when a candidate fits is still Optional[Tuple[str, str]]
    — UNCHANGED shape, now reached via the VRAM-aware path (generous free
    VRAM patched so the single candidate fits)."""
    models_dir = tmp_path / "models_dir"
    models_dir.mkdir()
    _make_model_dir(models_dir, "LFM2.5-VL-3B")

    monkeypatch.setattr(LocalModelManager, "MODELS_DIR", models_dir)
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=8.0)

    result = vl._find_vision_model()

    assert isinstance(result, tuple)
    assert len(result) == 2
    model_path, mmproj_path = result
    assert isinstance(model_path, str)
    assert isinstance(mmproj_path, str)


def test_find_vision_model_is_vram_aware_not_unconditional(tmp_path, monkeypatch):
    """INVERTED from `test_find_vision_model_prefers_3b_unconditionally`:
    the old test proved the function took NO vram argument and picked the 3B
    regardless. Now it DOES consult free VRAM — with both the 3B and 450M
    present and free VRAM near zero, NEITHER fits the reserve, so the
    function fails loudly instead of unconditionally returning the 3B.
    """
    models_dir = tmp_path / "models_dir"
    models_dir.mkdir()
    _make_model_dir(models_dir, "LFM2.5-VL-3B", model_name="LFM2.5-VL-3B-Q4_K_M.gguf")
    _make_model_dir(models_dir, "LFM2.5-VL-450M", model_name="LFM2.5-VL-450M-Q8_0.gguf")

    monkeypatch.setattr(LocalModelManager, "MODELS_DIR", models_dir)
    _isolate_search_dirs(monkeypatch, tmp_path)
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=0.01)
    captured = _subscribe_capture(monkeypatch)

    with pytest.raises(vl.VisionModelUnavailable) as exc_info:
        vl._find_vision_model()

    assert exc_info.value.free_gb == 0.01
    assert len(exc_info.value.ladder) == 2  # both candidates rejected, both logged
    assert len(captured) == 1
    assert captured[0]["free_vram_gb"] == 0.01
    assert len(captured[0]["ladder"]) == 2


def test_find_vision_model_size_selects_smaller_when_larger_does_not_fit(tmp_path, monkeypatch):
    """New coverage (REQ-3 AC1): widest-first, TAKE THE FIRST THAT FITS. With
    moderate free VRAM the 3B-sized candidate is rejected but the 450M-sized
    one fits, and IS the one returned — proving size-selection, not a fixed
    preference in either direction."""
    models_dir = tmp_path / "models_dir"
    models_dir.mkdir()
    model_3b_name = "LFM2.5-VL-3B-Q4_K_M.gguf"
    model_450_name = "LFM2.5-VL-450M-Q8_0.gguf"
    d3b = _make_model_dir(models_dir, "LFM2.5-VL-3B", model_name=model_3b_name)
    d450 = _make_model_dir(models_dir, "LFM2.5-VL-450M", model_name=model_450_name)

    _sizes = {
        str(d3b / model_3b_name): int(2.0 * 1024 ** 3),
        str(d3b / _default_mmproj_name(model_3b_name)): int(0.5 * 1024 ** 3),
        str(d450 / model_450_name): int(0.5 * 1024 ** 3),
        str(d450 / _default_mmproj_name(model_450_name)): int(0.1 * 1024 ** 3),
    }
    monkeypatch.setattr("os.path.getsize", lambda p: _sizes[str(p)])
    monkeypatch.setattr(LocalModelManager, "MODELS_DIR", models_dir)
    _isolate_search_dirs(monkeypatch, tmp_path)
    # free=2.0, reserve=1.0 -> headroom=1.0. 3B needs ~(2.5*1.05)=2.625 -> rejected.
    # 450M needs ~(0.6*1.05)=0.63 -> fits.
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=2.0)

    model_path, mmproj_path = vl._find_vision_model()

    assert "450M" in model_path
    assert "3B" not in model_path


def test_find_vision_model_prefers_widest_when_it_fits(tmp_path, monkeypatch):
    """New coverage (REQ-3 AC1): with generous free VRAM the WIDER (3B-sized)
    candidate fits and IS selected — proves the ladder is widest-first, not
    smallest-first."""
    models_dir = tmp_path / "models_dir"
    models_dir.mkdir()
    model_3b_name = "LFM2.5-VL-3B-Q4_K_M.gguf"
    model_450_name = "LFM2.5-VL-450M-Q8_0.gguf"
    d3b = _make_model_dir(models_dir, "LFM2.5-VL-3B", model_name=model_3b_name)
    d450 = _make_model_dir(models_dir, "LFM2.5-VL-450M", model_name=model_450_name)

    _sizes = {
        str(d3b / model_3b_name): int(2.0 * 1024 ** 3),
        str(d3b / _default_mmproj_name(model_3b_name)): int(0.5 * 1024 ** 3),
        str(d450 / model_450_name): int(0.5 * 1024 ** 3),
        str(d450 / _default_mmproj_name(model_450_name)): int(0.1 * 1024 ** 3),
    }
    monkeypatch.setattr("os.path.getsize", lambda p: _sizes[str(p)])
    monkeypatch.setattr(LocalModelManager, "MODELS_DIR", models_dir)
    _isolate_search_dirs(monkeypatch, tmp_path)
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=10.0)

    model_path, mmproj_path = vl._find_vision_model()

    assert "3B" in model_path


# --- _compute_vision_gpu_layers ----------------------------------------------
# tasks.md / requirements.md call this function `_resolve_gpu_layers`; no such
# name exists in lfm_vl_provider.py today (verified: only `_compute_vision_gpu_
# layers` is defined). Pinning the function that actually exists.


def test_resolve_gpu_layers_zero_when_model_path_falsy():
    """UNCHANGED: an empty model path is a degenerate-input guard, not a
    "does not fit" VRAM decision — REQ-3 AC4's fail-loudly contract does not
    apply here."""
    assert vl._compute_vision_gpu_layers("", "/some/mmproj.gguf") == 0


def test_resolve_gpu_layers_zero_when_mmproj_path_falsy():
    """UNCHANGED — see above."""
    assert vl._compute_vision_gpu_layers("/some/model.gguf", "") == 0


def test_resolve_gpu_layers_full_offload_when_it_fits(tmp_path, monkeypatch):
    """needed_gb <= free_gb - _VISION_VRAM_RESERVE_GB -> 999 (all layers).

    UPDATED comment only (outcome unchanged, still 999): T7 removed the
    inline `model_gb + mmproj_gb + 0.3` estimator this test's comment used to
    describe. The KV term is now computed by the SAME estimator
    `_find_vision_model` uses (`_estimate_vision_footprint_gb` ->
    `LocalModelManager.estimate_vram_gb`); for these synthetic, header-less
    fake files it resolves to a 0.0 GB KV term (no parseable GGUF metadata),
    so the fit decision here is effectively weights-only — which still fits
    comfortably under the same 1.0GB headroom the old test asserted.
    """
    model_path = tmp_path / "model.gguf"
    mmproj_path = tmp_path / "mmproj.gguf"
    model_path.touch()
    mmproj_path.touch()
    # 400 MiB model + 100 MiB mmproj = ~0.488 GiB weights. Sizes are FAKED via
    # os.path.getsize (not real disk writes) — controlled, instant, and avoids
    # multi-hundred-MB sparse-file writes tripping antivirus scanning on CI/dev.
    _sizes = {str(model_path): 400 * 1024 * 1024, str(mmproj_path): 100 * 1024 * 1024}
    monkeypatch.setattr("os.path.getsize", lambda p: _sizes[str(p)])
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=2.0)

    # free_gb(2.0) - reserve(1.0) = 1.0 headroom. weights ~0.513GiB (with
    # driver/alloc overhead) + KV 0.0 (no parseable GGUF header) <= 1.0 -> fits.
    assert vl._VISION_VRAM_RESERVE_GB == 1.0
    result = vl._compute_vision_gpu_layers(str(model_path), str(mmproj_path))
    assert result == 999


def test_resolve_gpu_layers_raises_when_it_does_not_fit(tmp_path, monkeypatch):
    """INVERTED from `test_resolve_gpu_layers_cpu_fallback_when_kv_overhead_
    tips_it_over`. The old test proved a hardcoded `+0.3` KV constant was the
    thing that tipped a fit into a CPU fallback. That constant is GONE (T7:
    ONE shared, GQA-aware estimator, no local hardcoded KV number) so it can
    no longer be the deciding factor — this test instead sizes the WEIGHTS
    alone past the headroom, and asserts the new REQ-3 AC4 contract: a
    hard raise (`VisionModelUnavailable`) naming the free VRAM and the
    requirement, not a silent CPU degrade. Also asserts the VISION_UNAVAILABLE
    chat system message (REQ-3 AC6) carries the same facts.
    """
    model_path = tmp_path / "model.gguf"
    mmproj_path = tmp_path / "mmproj.gguf"
    model_path.touch()
    mmproj_path.touch()
    # 900 MiB model + 900 MiB mmproj = ~1.76 GiB weights * 1.05 overhead
    # ~= 1.85 GiB — comfortably over the 1.0GB headroom on its own, with no
    # KV constant needed to tip it.
    _sizes = {str(model_path): 900 * 1024 * 1024, str(mmproj_path): 900 * 1024 * 1024}
    monkeypatch.setattr("os.path.getsize", lambda p: _sizes[str(p)])
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=2.0)
    captured = _subscribe_capture(monkeypatch)

    with pytest.raises(vl.VisionModelUnavailable) as exc_info:
        vl._compute_vision_gpu_layers(str(model_path), str(mmproj_path))

    assert exc_info.value.free_gb == 2.0
    assert exc_info.value.smallest_requirement_gb > 1.0  # exceeds the 1.0GB headroom
    assert len(captured) == 1
    assert captured[0]["free_vram_gb"] == 2.0
    assert captured[0]["ladder"][0]["model_path"] == str(model_path)


def test_resolve_gpu_layers_cpu_when_no_cuda(tmp_path, monkeypatch):
    """UNCHANGED: no GPU at all is a DIFFERENT case from "does not fit" — a
    machine with no CUDA device has no VRAM budget to fail against, so CPU
    (0) remains correct and this is not part of REQ-3 AC4's fail-loudly
    contract (see `_compute_vision_gpu_layers` docstring)."""
    model_path = tmp_path / "model.gguf"
    mmproj_path = tmp_path / "mmproj.gguf"
    model_path.write_bytes(b"\0" * 1024)
    mmproj_path.write_bytes(b"\0" * 1024)

    _patch_hardware(monkeypatch, cuda_available=False, vram_free_gb=0.0)

    assert vl._compute_vision_gpu_layers(str(model_path), str(mmproj_path)) == 0
