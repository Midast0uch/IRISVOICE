"""T7 (REQ-3, REQ-9): comprehensive coverage for the size-selected VL fallback
ladder in `backend/tools/lfm_vl_provider.py`.

Complements `test_vision_selection_baseline.py` (which pins/inverts the
pre-existing baseline assertions). This file adds the NEW scenarios T7 was
asked to cover: ladder selection across several free-VRAM levels, the
projector's own size entering the fit decision (REQ-3 AC2), the no-fit FAIL
LOUDLY contract raising AND emitting VISION_UNAVAILABLE with the required
payload fields (REQ-3 AC4/AC6), free-VRAM-unreadable choosing the most
conservative candidate (edge case), and a candidate missing its projector
being skipped (edge case).

Discovery roots (T7 scope note): `_discover_vision_candidates` still walks a
FIXED set of name-patterned directories (LFM2.5-VL-3B / 450M and their
LiquidAI/*-GGUF siblings) — REQ-10 (a later task) replaces this with a fully
user-configured, model-agnostic ladder. T7's job is the SELECTION arithmetic
over whatever is found there, so these tests place synthetic candidates at
those same fixed slots rather than inventing new discovery paths.

No GPU, no real models, no network: `shutil.which` is patched so nvidia-smi
is never actually invoked, and `LocalModelManager.get_hardware_info` is
patched AT THE CLASS so the REAL singleton (and therefore its real
`estimate_vram_gb` / `parse_gguf_metadata`) still does the weights/KV math —
only the VRAM figure itself is controlled per test.
"""
import pytest

from backend.agent.local_model_manager import LocalModelManager
from backend.tools import lfm_vl_provider as vl


@pytest.fixture(autouse=True)
def _no_real_nvidia_smi(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)


@pytest.fixture(autouse=True)
def _clean_event_bus():
    from backend.agent.event_bus import reset_event_bus_for_testing

    reset_event_bus_for_testing()
    yield
    reset_event_bus_for_testing()


def _fixed_slots(models_dir, home_dir):
    """The concrete directories `_discover_vision_candidates` actually walks
    today, given `LocalModelManager.MODELS_DIR=models_dir` and
    `Path.home()=home_dir`."""
    return [
        models_dir / "LFM2.5-VL-3B",
        models_dir / "LiquidAI" / "LFM2.5-VL-3B-GGUF",
        models_dir / "LFM2.5-VL-450M",
        models_dir / "LiquidAI" / "LFM2.5-VL-450M-GGUF",
        home_dir / "models" / "LFM2.5-VL-3B",
        home_dir / "models" / "LFM2.5-VL-450M",
        home_dir / ".iris" / "models" / "LFM2.5-VL-3B",
        home_dir / ".iris" / "models" / "LFM2.5-VL-450M",
    ]


def _setup(monkeypatch, tmp_path):
    """Isolate every search root and return the fixed candidate slots."""
    models_dir = tmp_path / "models_dir"
    models_dir.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setattr(LocalModelManager, "MODELS_DIR", models_dir)
    monkeypatch.setattr(vl.Path, "home", staticmethod(lambda: home_dir))
    return _fixed_slots(models_dir, home_dir)


def _place_candidate(slot_dir, *, model_gb, mmproj_gb, sizes,
                      model_name=None, mmproj_name=None):
    """Write a (model, mmproj) pair at `slot_dir` and register their FAKED
    sizes into the shared `sizes` dict this test's `os.path.getsize` patch
    reads from.

    INPUT CHANGE (T15, called out per CLAUDE.md): default names are now
    DERIVED from `slot_dir`'s own directory name (every fixed slot already
    has a distinct name, so this is free uniqueness) instead of the old
    fixed placeholder pair "model.gguf" / "mmproj-x.gguf". T15 sources
    `_discover_vision_candidates` from `LocalModelManager.scan_models()`'s
    `has_vision`-tagged entries, which requires (a) the base model and its
    projector to stem-match, and (b) distinct base filenames across
    directories — `scan_models()` dedupes by filename stem GLOBALLY (its
    split-shard grouping), so identical placeholder names in different
    directories collapsed into one phantom entry under the old convention.
    Every assertion in this file is UNCHANGED; only the fixture's file
    identity was updated so multiple candidates are actually discovered as
    multiple candidates under the new (correct, AC1-compliant) source.
    """
    slot_dir.mkdir(parents=True, exist_ok=True)
    base_name = slot_dir.name
    if model_name is None:
        model_name = f"{base_name}-Q4_K_M.gguf"
    if mmproj_name is None:
        mmproj_name = f"mmproj-{base_name}-F16.gguf"
    model_path = slot_dir / model_name
    mmproj_path = slot_dir / mmproj_name
    model_path.write_bytes(b"\0")
    mmproj_path.write_bytes(b"\0")
    sizes[str(model_path)] = int(model_gb * 1024 ** 3)
    sizes[str(mmproj_path)] = int(mmproj_gb * 1024 ** 3)
    return model_path, mmproj_path


def _patch_hardware(monkeypatch, *, cuda_available=True, vram_free_gb=8.0):
    def _fake(self, force_refresh: bool = False):
        return {"cuda_available": cuda_available, "vram_free_gb": vram_free_gb}

    monkeypatch.setattr(LocalModelManager, "get_hardware_info", _fake)


def _patch_hardware_raises(monkeypatch):
    """Simulate free VRAM being genuinely UNREADABLE — both nvidia-smi (via
    the autouse fixture above) and the LocalModelManager fallback fail."""
    def _fake(self, force_refresh: bool = False):
        raise RuntimeError("hardware probe unavailable (simulated)")

    monkeypatch.setattr(LocalModelManager, "get_hardware_info", _fake)


def _subscribe_capture(monkeypatch):
    from backend.agent.event_bus import get_event_bus, IRISStreamEvent

    captured = []
    get_event_bus().subscribe(IRISStreamEvent.VISION_UNAVAILABLE, lambda p: captured.append(p.data))
    return captured


# --- Ladder selection at several free-VRAM levels ----------------------------


@pytest.mark.parametrize(
    "free_gb,expect_slot,expect_none",
    [
        # headroom = free - 1.0GB reserve.
        (10.0, 0, False),   # headroom 9.0 -> widest (slot 0, ~2.5GB) fits
        (3.2, 1, False),    # headroom 2.2 -> slot 0 (2.5GB) rejected, slot 1 (~1.5GB) fits
        (1.8, 2, False),    # headroom 0.8 -> slot 0+1 rejected, slot 2 (~0.5GB) fits
        (1.0, None, True),  # headroom 0.0 -> nothing fits (even ~0.5GB > 0)
    ],
)
def test_ladder_selection_at_several_vram_levels(tmp_path, monkeypatch, free_gb, expect_slot, expect_none):
    slots = _setup(monkeypatch, tmp_path)
    sizes: dict = {}
    m0, _ = _place_candidate(slots[0], model_gb=2.0, mmproj_gb=0.38, sizes=sizes)   # ~2.5GB total
    m1, _ = _place_candidate(slots[1], model_gb=1.2, mmproj_gb=0.23, sizes=sizes)   # ~1.5GB total
    m2, _ = _place_candidate(slots[2], model_gb=0.4, mmproj_gb=0.076, sizes=sizes)  # ~0.5GB total
    expected_paths = [m0, m1, m2]
    monkeypatch.setattr("os.path.getsize", lambda p: sizes[str(p)])
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=free_gb)

    if expect_none:
        with pytest.raises(vl.VisionModelUnavailable):
            vl._find_vision_model()
        return

    model_path, _mmproj_path = vl._find_vision_model()
    assert model_path == str(expected_paths[expect_slot])


# --- Projector size enters the estimate (REQ-3 AC2) --------------------------


def test_projector_size_enters_the_fit_decision_small_projector_fits(tmp_path, monkeypatch):
    """0.9GB model + 0.05GB projector = 0.95 * 1.05 ~= 0.9975GB <= 1.0GB
    headroom -> fits."""
    slots = _setup(monkeypatch, tmp_path)
    sizes: dict = {}
    expected_model_path, _ = _place_candidate(slots[0], model_gb=0.9, mmproj_gb=0.05, sizes=sizes)
    monkeypatch.setattr("os.path.getsize", lambda p: sizes[str(p)])
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=2.0)

    model_path, _mmproj_path = vl._find_vision_model()
    assert model_path == str(expected_model_path)


def test_projector_size_enters_the_fit_decision_large_projector_fails(tmp_path, monkeypatch):
    """SAME base model size (0.9GB) as the test above, only the projector
    grows to 0.5GB: (0.9+0.5)*1.05 = 1.47GB > 1.0GB headroom -> now fails.
    Proves the projector's OWN size — not just the base model's — decides
    the fit (REQ-3 AC2): a model that alone (0.9*1.05=0.945GB) would fit is
    tipped over by its projector.
    """
    slots = _setup(monkeypatch, tmp_path)
    sizes: dict = {}
    _place_candidate(slots[0], model_gb=0.9, mmproj_gb=0.5, sizes=sizes)
    monkeypatch.setattr("os.path.getsize", lambda p: sizes[str(p)])
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=2.0)
    captured = _subscribe_capture(monkeypatch)

    with pytest.raises(vl.VisionModelUnavailable) as exc_info:
        vl._find_vision_model()

    assert exc_info.value.smallest_requirement_gb > 1.0
    assert len(captured) == 1


# --- No-fit: raise AND emit VISION_UNAVAILABLE with required payload fields --


def test_no_fit_raises_and_emits_full_payload(tmp_path, monkeypatch):
    slots = _setup(monkeypatch, tmp_path)
    sizes: dict = {}
    _place_candidate(slots[0], model_gb=1.5, mmproj_gb=0.3, sizes=sizes)
    _place_candidate(slots[1], model_gb=0.8, mmproj_gb=0.15, sizes=sizes)
    monkeypatch.setattr("os.path.getsize", lambda p: sizes[str(p)])
    # free=0.5, reserve=1.0 -> headroom is NEGATIVE: nothing can ever fit.
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=0.5)
    captured = _subscribe_capture(monkeypatch)

    with pytest.raises(vl.VisionModelUnavailable) as exc_info:
        vl._find_vision_model()

    exc = exc_info.value
    assert exc.free_gb == 0.5
    assert exc.smallest_requirement_gb > 0
    assert len(exc.ladder) == 2
    for entry in exc.ladder:
        assert "model_path" in entry
        assert "needed_gb" in entry
        assert "reason" in entry

    assert len(captured) == 1
    payload = captured[0]
    assert payload["message"]
    assert payload["free_vram_gb"] == 0.5
    assert payload["smallest_requirement_gb"] > 0
    assert len(payload["ladder"]) == 2
    for entry in payload["ladder"]:
        assert "model_path" in entry
        assert "needed_gb" in entry
        assert "reason" in entry


# --- Free VRAM unreadable -> most conservative candidate ---------------------


def test_unreadable_vram_chooses_most_conservative_candidate(tmp_path, monkeypatch):
    slots = _setup(monkeypatch, tmp_path)
    sizes: dict = {}
    _place_candidate(slots[0], model_gb=2.0, mmproj_gb=0.38, sizes=sizes)  # widest
    m_small, _ = _place_candidate(slots[1], model_gb=0.4, mmproj_gb=0.076, sizes=sizes)  # narrowest
    monkeypatch.setattr("os.path.getsize", lambda p: sizes[str(p)])
    _patch_hardware_raises(monkeypatch)

    model_path, _mmproj_path = vl._find_vision_model()

    assert model_path == str(m_small)


def test_unreadable_vram_via_missing_key_also_chooses_conservative(tmp_path, monkeypatch):
    """A second flavor of "unreadable": get_hardware_info returns a dict with
    no `vram_free_gb` key at all (rather than raising) — still readable=False."""
    slots = _setup(monkeypatch, tmp_path)
    sizes: dict = {}
    _place_candidate(slots[0], model_gb=2.0, mmproj_gb=0.38, sizes=sizes)
    m_small, _ = _place_candidate(slots[1], model_gb=0.4, mmproj_gb=0.076, sizes=sizes)
    monkeypatch.setattr("os.path.getsize", lambda p: sizes[str(p)])

    def _fake(self, force_refresh: bool = False):
        return {"cuda_available": True}  # no vram_free_gb key

    monkeypatch.setattr(LocalModelManager, "get_hardware_info", _fake)

    model_path, _mmproj_path = vl._find_vision_model()
    assert model_path == str(m_small)


# --- A candidate missing its projector is skipped, logged --------------------
#
# REPLACED (T15, called out per CLAUDE.md): the old scenario placed a GGUF
# with no sibling mmproj*.gguf inside one of the RETIRED hardcoded VL-family
# directories and asserted a per-directory "no projector found" skip. That
# log site no longer exists — discovery is scan_models()-sourced now (REQ-10
# AC1), where a base model with no matching projector simply never becomes
# `has_vision: true` and is not logged (the overwhelmingly common case for
# every non-vision model in a real library; logging one line per such model
# would be noise, not signal). The CURRENT, still-real "skip a broken
# candidate and keep going" contract is REQ-10 AC6: a model NAMED in the
# user's CONFIGURED ladder that is no longer vision-capable (deleted, or its
# projector deleted) is skipped, logged, and the ladder walk continues. This
# is the same guarantee (one bad candidate never blocks selection), applied
# through the mechanism that actually still exists.


def test_configured_candidate_no_longer_vision_capable_is_skipped_and_logged(
    tmp_path, monkeypatch, caplog,
):
    import logging

    slots = _setup(monkeypatch, tmp_path)
    sizes: dict = {}

    # Named in the ladder but never placed on disk — models a projector (or
    # the model itself) that was deleted after the user configured it.
    ghost_path = str(slots[0] / "ghost-Q4_K_M.gguf")

    # Valid candidate — has both files, at a different fixed slot.
    m_valid, _ = _place_candidate(slots[1], model_gb=0.5, mmproj_gb=0.1, sizes=sizes)

    monkeypatch.setattr("os.path.getsize", lambda p: sizes[str(p)])
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=8.0)

    import types

    fake_cfg = types.SimpleNamespace(
        inference=types.SimpleNamespace(vision_fallback_ladder=[ghost_path, str(m_valid)])
    )
    monkeypatch.setattr(vl, "_load_vl_config", lambda: fake_cfg)

    with caplog.at_level(logging.INFO, logger="backend.tools.lfm_vl_provider"):
        model_path, _mmproj_path = vl._find_vision_model()

    assert model_path == str(m_valid)
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "SKIPPED" in log_text
    assert ghost_path in log_text
