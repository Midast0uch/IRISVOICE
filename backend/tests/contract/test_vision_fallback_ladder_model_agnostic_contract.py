"""T15 (REQ-10) — REQUIRED GUARD named in tasks.md's T15 entry:

  "Add a contract test asserting no hardcoded GGUF id in the fallback path
   and graceful degradation when configured models are absent from disk."

This is the user's own stated intent made mechanically enforceable: "i dont
want to really hardcode anything i want to make sure things stay model
agnostic and give users a choice." A future edit that slips a literal model
id back into the discovery/selection/spawn path breaks this test, not just
a docstring promise.

Two halves:
  (a) SOURCE-LEVEL assertion (real, not a docstring check) — the functions
      that make up the fallback path contain no hardcoded GGUF model
      family/id literal (REQ-3's own examples, LFM2.5-VL-3B / -450M,
      included — the spec is explicit those are DEFAULTS AND EXAMPLES, not
      a contract T15 may re-embed).
  (b) BEHAVIORAL — a configured ladder naming a model missing from disk (or
      whose projector is gone) degrades gracefully: skipped, logged,
      selection continues to the next entry, and when NOTHING configured
      resolves it fails through the existing REQ-3 AC4/AC6 contract rather
      than crashing with an unrelated exception (KeyError, AttributeError,
      TypeError).
"""
from __future__ import annotations

import inspect
import re

import pytest

from backend.agent.local_model_manager import LocalModelManager
from backend.tools import lfm_vl_provider as vl


# ---------------------------------------------------------------------------
# (a) Source-level: no hardcoded GGUF model id in the fallback path.
# ---------------------------------------------------------------------------

# Literal model-family/id patterns REQ-3's own text used as DEFAULTS AND
# EXAMPLES (REQ-10's "Note for the implementer") — a real regression would
# reintroduce one of these as a selection literal, not just as historical
# prose elsewhere in the module (which this test deliberately does not scan
# — see FALLBACK_PATH_FUNCTIONS below for the precise scope).
_FORBIDDEN_MODEL_ID_PATTERN = re.compile(
    r"LFM2\.5-VL-(3B|450M)|lfm2\.5-vl-(3b|450m)|(?<![\w.])(3B|450M)(?![\w.])",
)

# The functions that actually MAKE UP the fallback path: discovery,
# configured-ladder resolution, size-selection, GPU-layer sizing, the spawn,
# and the request payload. Scoped here (rather than the whole file) because
# other parts of the module carry HISTORICAL prose (e.g. "vision was
# upgraded to LFM2.5-VL-3B on 2026-08-12") describing why a constant like
# _VISION_VRAM_RESERVE_GB has the value it does — narrative, not selection
# logic, and not what REQ-10 AC7 is guarding against.
_FALLBACK_PATH_FUNCTIONS = [
    vl._discover_vision_candidates,
    vl._configured_vision_ladder,
    vl._find_vision_model,
    vl._compute_vision_gpu_layers,
    vl._ensure_vision_server_running,
    vl.LFMVLProvider._call,
]


@pytest.mark.parametrize("fn", _FALLBACK_PATH_FUNCTIONS, ids=lambda f: f.__qualname__)
def test_fallback_path_function_contains_no_hardcoded_model_id(fn):
    source = inspect.getsource(fn)
    match = _FORBIDDEN_MODEL_ID_PATTERN.search(source)
    assert match is None, (
        f"{fn.__qualname__} contains a hardcoded vision model id/family "
        f"literal ({match.group(0) if match else ''!r}) — REQ-10 AC7 "
        f"requires the fallback path to name no specific GGUF model."
    )


def test_search_dirs_hint_list_is_gone():
    """The concrete gap this task closes: T7 left DISCOVERY HINT directories
    named after specific model families (`LFM2.5-VL-3B`, `LFM2.5-VL-450M`,
    their `LiquidAI/*-GGUF` siblings) inside `_discover_vision_candidates`.
    Asserts the whole discovery function no longer constructs any such
    directory literal at all — discovery is scan_models()-sourced now, not
    a directory glob of any shape."""
    source = inspect.getsource(vl._discover_vision_candidates)
    for literal in ("LiquidAI", "LFM2.5-VL-3B", "LFM2.5-VL-450M", ".glob(", ".rglob("):
        assert literal not in source, (
            f"_discover_vision_candidates still references {literal!r} — "
            f"the hardcoded directory-hint discovery must be fully removed."
        )
    assert "scan_models" in source, (
        "_discover_vision_candidates must source candidates from "
        "LocalModelManager.scan_models() (REQ-10 AC1), not reinvent a "
        "second discovery mechanism."
    )


# ---------------------------------------------------------------------------
# (b) Graceful degradation when configured models are absent from disk.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_real_nvidia_smi(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)


@pytest.fixture(autouse=True)
def _clean_event_bus():
    from backend.agent.event_bus import reset_event_bus_for_testing

    reset_event_bus_for_testing()
    yield
    reset_event_bus_for_testing()


def _isolate_models_dir(monkeypatch, tmp_path):
    models_dir = tmp_path / "models_dir"
    models_dir.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setattr(LocalModelManager, "MODELS_DIR", models_dir)
    monkeypatch.setattr(vl.Path, "home", staticmethod(lambda: home_dir))
    return models_dir


def _configure_ladder(monkeypatch, ladder):
    import types

    fake_cfg = types.SimpleNamespace(
        inference=types.SimpleNamespace(vision_fallback_ladder=ladder)
    )
    monkeypatch.setattr(vl, "_load_vl_config", lambda: fake_cfg)


def _patch_hardware(monkeypatch, *, cuda_available=True, vram_free_gb=8.0):
    def _fake(self, force_refresh: bool = False):
        return {"cuda_available": cuda_available, "vram_free_gb": vram_free_gb}

    monkeypatch.setattr(LocalModelManager, "get_hardware_info", _fake)


def test_configured_ladder_naming_only_a_missing_model_degrades_to_the_existing_no_fit_contract(
    monkeypatch, tmp_path,
):
    """The user configured a ladder, but the ONE model they named is not on
    disk at all (moved, deleted, typo'd path). This must degrade to the
    EXISTING REQ-3 AC4/AC6 "nothing available" contract — VisionModelUnavailable,
    never an unrelated crash (KeyError / AttributeError / TypeError)."""
    _isolate_models_dir(monkeypatch, tmp_path)
    _configure_ladder(monkeypatch, ["C:/models/does-not-exist/ghost.gguf"])
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=8.0)

    with pytest.raises(vl.VisionModelUnavailable):
        vl._find_vision_model()


def test_configured_ladder_skips_missing_entry_and_selects_the_next_real_one(
    monkeypatch, tmp_path, caplog,
):
    """A configured ladder naming TWO models, the first missing from disk —
    selection must skip it (logged) and continue to the second, real one,
    never treat one bad entry as a hard failure (REQ-10 AC6)."""
    import logging

    models_dir = _isolate_models_dir(monkeypatch, tmp_path)
    real_dir = models_dir / "my-vision-model"
    real_dir.mkdir(parents=True)
    model_path = real_dir / "my-vision-model-Q4_K_M.gguf"
    mmproj_path = real_dir / "mmproj-my-vision-model-F16.gguf"
    model_path.write_bytes(b"\0")
    mmproj_path.write_bytes(b"\0")
    sizes = {str(model_path): int(0.5 * 1024 ** 3), str(mmproj_path): int(0.1 * 1024 ** 3)}
    monkeypatch.setattr("os.path.getsize", lambda p: sizes[str(p)])

    missing_id = "C:/models/does-not-exist/ghost.gguf"
    _configure_ladder(monkeypatch, [missing_id, str(model_path)])
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=8.0)

    with caplog.at_level(logging.INFO, logger="backend.tools.lfm_vl_provider"):
        found_model_path, found_mmproj_path = vl._find_vision_model()

    assert found_model_path == str(model_path)
    assert found_mmproj_path == str(mmproj_path)
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "SKIPPED" in log_text
    assert missing_id in log_text


def test_no_configured_ladder_falls_back_to_auto_widest_first(monkeypatch, tmp_path):
    """Absent config (AC5) must still work end to end through the SAME
    scan_models()-sourced discovery, picking the widest has_vision model
    that fits — proving the auto path never needs a hardcoded id either."""
    models_dir = _isolate_models_dir(monkeypatch, tmp_path)
    sizes: dict = {}

    def _place(name, model_gb, mmproj_gb):
        d = models_dir / name
        d.mkdir(parents=True)
        m = d / f"{name}-Q4_K_M.gguf"
        p = d / f"mmproj-{name}-F16.gguf"
        m.write_bytes(b"\0")
        p.write_bytes(b"\0")
        sizes[str(m)] = int(model_gb * 1024 ** 3)
        sizes[str(p)] = int(mmproj_gb * 1024 ** 3)
        return m

    wide = _place("candidate-a", 2.0, 0.38)
    _place("candidate-b", 0.4, 0.076)
    monkeypatch.setattr("os.path.getsize", lambda p: sizes[str(p)])
    _configure_ladder(monkeypatch, [])  # explicit empty = auto (AC5)
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=10.0)

    found_model_path, _found_mmproj_path = vl._find_vision_model()
    assert found_model_path == str(wide)
