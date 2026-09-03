"""
T0a (Wave 0) — characterization baseline for LocalModelManager.scan_models().

PURPOSE: originally pinned the OLD behavior of scan_models() (projector files
returned as their own loadable-model rows). T1 (REQ-5) has now landed:
mmproj-*.gguf is excluded from scan_models results and attached to its base
model instead, as has_vision / mmproj_path / mmproj_size_gb (matched by
normalized stem — see LocalModelManager._normalize_stem_for_vision_match).

BASELINE GAP (specs/unified-vision-routing/tasks.md, Wave 0): the existing
weak test (backend/tests/behavioral/test_local_model_load.py:163) only asserts
each entry has path/filename/loaded. Nothing pinned the projector rows T1
removed, so this file closes that gap — now pinning the NEW behavior instead
of the old one.

This file was edited exactly once, by T1 (the task that changes the behavior
it pins), per the sanctioned exception in tasks.md's preamble. See T1's report
for the assertion-by-assertion diff.
"""

import pytest

from backend.agent.local_model_manager import LocalModelManager


def _make_manager(models_dir) -> LocalModelManager:
    """Construct a LocalModelManager pointed at a tmp models directory."""
    mgr = LocalModelManager()
    mgr.set_models_directory(str(models_dir))
    return mgr


# The full field set scan_models() puts on every entry, post-T1. Enumerated
# from the entry dict built in LocalModelManager.scan_models()
# (local_model_manager.py). has_vision / mmproj_path / mmproj_size_gb are the
# three fields T1 (REQ-5) added; the rest are unchanged from the pre-T1
# baseline.
EXPECTED_ENTRY_FIELDS = {
    "path",
    "filename",
    "display_name",
    "size_gb",
    "architecture",
    "params_b",
    "native_ctx",
    "quantization",
    "vram_estimate_gb",
    "plan",
    "loaded",
    "pinned",
    "last_profile",
    "last_ctx",
    "last_gpu_layers",
    "shard_count",
    "is_mtp_capable",
    "has_vision",
    "mmproj_path",
    "mmproj_size_gb",
}


def _write_fake_gguf(path) -> None:
    """Write a file that looks like a GGUF from the filename only.

    parse_gguf_metadata() checks the magic bytes (b"GGUF") before doing any
    real parsing; anything else short-circuits to an empty metadata dict
    without raising. scan_models() doesn't need real GGUF content to produce
    an entry — filename-based quant sniffing (_quant_from_filename) covers
    the rest.
    """
    path.write_bytes(b"NOT-A-REAL-GGUF-HEADER-JUST-BYTES-FOR-SCAN-TESTS-0123456789")


class TestProjectorTreatedAsLoadableModel:
    """T1 (REQ-5) CHANGED this.

    Before T1, scan_models() had no concept of a vision projector — a
    mmproj-*.gguf sibling was just another *.gguf file in the directory, so
    it got its own top-level entry exactly like a real chat model. T1 fixed
    this bug by excluding mmproj-*.gguf from the top-level scan and
    attaching it to its base model instead (has_vision / mmproj_path /
    mmproj_size_gb, matched by normalized stem).
    """

    def test_projector_sibling_is_not_returned_as_its_own_entry(self, tmp_path):
        base = tmp_path / "test-model.Q4_K_M.gguf"
        mmproj = tmp_path / "mmproj-test-model-f16.gguf"
        _write_fake_gguf(base)
        _write_fake_gguf(mmproj)

        mgr = _make_manager(tmp_path)
        models = mgr.scan_models()

        filenames = {m["filename"] for m in models}
        # T1 CHANGED this — the projector no longer comes back as its own
        # loadable-model row. It is folded into the base model's
        # has_vision/mmproj_path fields instead (REQ-5 AC1).
        assert filenames == {"test-model.Q4_K_M.gguf"}
        assert len(models) == 1

    def test_base_model_entry_has_the_new_vision_field_set(self, tmp_path):
        base = tmp_path / "test-model.Q4_K_M.gguf"
        mmproj = tmp_path / "mmproj-test-model-f16.gguf"
        _write_fake_gguf(base)
        _write_fake_gguf(mmproj)

        mgr = _make_manager(tmp_path)
        models = mgr.scan_models()
        assert len(models) == 1

        for entry in models:
            # T1 CHANGED this — the field set is now extended with
            # has_vision / mmproj_path / mmproj_size_gb (REQ-5 AC2). The
            # assertion stays a full set-equality check, not a subset check,
            # so no field can silently disappear or appear unnoticed.
            assert set(entry.keys()) == EXPECTED_ENTRY_FIELDS, entry.keys()


class TestVisionFieldsAttachedToBaseModel:
    """T1 (REQ-5) CHANGED this.

    Before T1, neither has_vision nor mmproj_path/mmproj_size_gb existed on
    any entry. T1 attaches all three to the base model whose stem matches
    the projector (REQ-5 AC2)."""

    def test_base_model_carries_has_vision_and_mmproj_path(self, tmp_path):
        base = tmp_path / "test-model.Q4_K_M.gguf"
        mmproj = tmp_path / "mmproj-test-model-f16.gguf"
        _write_fake_gguf(base)
        _write_fake_gguf(mmproj)

        mgr = _make_manager(tmp_path)
        models = mgr.scan_models()
        assert len(models) == 1

        entry = models[0]
        assert entry["has_vision"] is True
        assert entry["mmproj_path"] == str(mmproj)
        # Same formula scan_models() uses for every size_gb field:
        # round(bytes / 1024**3, 2). The fixture file is tiny, so this is
        # 0.0 — asserted against the real stat rather than a magnitude
        # threshold that would be dishonest for a byte-sized fixture.
        assert entry["mmproj_size_gb"] == round(mmproj.stat().st_size / (1024**3), 2)

    def test_model_with_no_projector_has_vision_false(self, tmp_path):
        base = tmp_path / "solo-model.Q4_K_M.gguf"
        _write_fake_gguf(base)

        mgr = _make_manager(tmp_path)
        models = mgr.scan_models()
        assert len(models) == 1

        entry = models[0]
        assert entry["has_vision"] is False
        assert entry["mmproj_path"] is None
        assert entry["mmproj_size_gb"] == 0.0
