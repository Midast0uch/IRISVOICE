"""CT-2 (specs/unified-vision-routing/design.md Testing Strategy): a
permanent guard against the bug actually observed live — 3 of 18
`/api/models` rows were CLIP projectors (`mmproj-*.gguf`) offered as
loadable brains. `scan_models()` must NEVER emit an entry whose filename
starts with `mmproj-` (any separator/case), and every entry with
`has_vision: true` must carry a READABLE `mmproj_path` (a non-empty string
naming a file that actually exists).

Unlike `backend/tests/unit/test_scan_models_baseline.py` (single base +
single projector, full field-set pin), this file drives a LARGER, messier
directory — several base models, several projectors, an orphan projector
with no matching base, and projectors/bases split across subdirectories —
because that shape is exactly what broke live. No GPU, no network, no real
GGUF content: `parse_gguf_metadata` short-circuits on a missing magic
header.
"""

from __future__ import annotations

from pathlib import Path

from backend.agent.local_model_manager import LocalModelManager


def _make_manager(models_dir) -> LocalModelManager:
    mgr = LocalModelManager()
    mgr.set_models_directory(str(models_dir))
    return mgr


def _write_fake_gguf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"NOT-A-REAL-GGUF-HEADER-JUST-BYTES-FOR-SCAN-TESTS-0123456789")


class TestNoProjectorRowIsEverEmitted:
    def test_multiple_projectors_across_subdirectories_never_become_rows(self, tmp_path):
        """Reproduces the live shape: several base models and several
        projectors, matched across DIFFERENT subdirectories (base and
        projector quantized independently, rarely co-located)."""
        _write_fake_gguf(tmp_path / "chat" / "gemma-4-E4B-it-Q4_K_M.gguf")
        _write_fake_gguf(tmp_path / "vision" / "mmproj-gemma-4-E4B-it-BF16.gguf")
        _write_fake_gguf(tmp_path / "chat" / "qwen3-9b-Q4_K_M.gguf")
        _write_fake_gguf(tmp_path / "vision" / "mmproj-qwen3-9b-F16.gguf")
        _write_fake_gguf(tmp_path / "chat" / "cohere-command-Q4_K_M.gguf")  # no projector
        # An orphan projector with no matching base model anywhere.
        _write_fake_gguf(tmp_path / "vision" / "mmproj-orphan-model-F16.gguf")

        mgr = _make_manager(tmp_path)
        models = mgr.scan_models()

        filenames = {m["filename"] for m in models}
        assert not any(f.lower().startswith("mmproj-") for f in filenames), (
            f"a projector row leaked into scan_models(): {filenames}"
        )
        # The three real chat models, and NOT the orphan projector either
        # (an orphan is excluded entirely, never becomes its own row).
        assert filenames == {
            "gemma-4-E4B-it-Q4_K_M.gguf",
            "qwen3-9b-Q4_K_M.gguf",
            "cohere-command-Q4_K_M.gguf",
        }

    def test_projector_prefix_matched_case_and_separator_insensitively(self, tmp_path):
        """`_is_projector_filename` matches `mmproj[-_.]` case-insensitively
        — cover the separator/case variants a real models directory has
        actually contained."""
        _write_fake_gguf(tmp_path / "base-one-Q4_K_M.gguf")
        _write_fake_gguf(tmp_path / "MMPROJ-base-one-F16.gguf")
        _write_fake_gguf(tmp_path / "base-two-Q4_K_M.gguf")
        _write_fake_gguf(tmp_path / "mmproj_base-two_F16.gguf")
        _write_fake_gguf(tmp_path / "base-three-Q4_K_M.gguf")
        _write_fake_gguf(tmp_path / "mmproj.base-three.F16.gguf")

        mgr = _make_manager(tmp_path)
        models = mgr.scan_models()

        filenames = {m["filename"] for m in models}
        assert not any(f.lower().startswith("mmproj") for f in filenames), filenames
        assert filenames == {
            "base-one-Q4_K_M.gguf",
            "base-two-Q4_K_M.gguf",
            "base-three-Q4_K_M.gguf",
        }


class TestHasVisionEntriesCarryAReadableMmprojPath:
    def test_every_has_vision_true_entry_has_an_existing_mmproj_path(self, tmp_path):
        _write_fake_gguf(tmp_path / "a" / "gemma-4-E4B-it-Q4_K_M.gguf")
        _write_fake_gguf(tmp_path / "b" / "mmproj-gemma-4-E4B-it-BF16.gguf")
        _write_fake_gguf(tmp_path / "a" / "no-vision-model-Q4_K_M.gguf")

        mgr = _make_manager(tmp_path)
        models = mgr.scan_models()

        vision_entries = [m for m in models if m["has_vision"] is True]
        assert len(vision_entries) == 1
        for entry in vision_entries:
            mmproj_path = entry["mmproj_path"]
            assert isinstance(mmproj_path, str) and mmproj_path, (
                "has_vision=True but mmproj_path is not a readable string"
            )
            assert Path(mmproj_path).exists(), (
                f"mmproj_path {mmproj_path!r} does not point at a real file"
            )

        non_vision_entries = [m for m in models if m["has_vision"] is False]
        assert len(non_vision_entries) == 1
        assert non_vision_entries[0]["mmproj_path"] is None

    def test_orphan_projector_attaches_to_nothing_and_has_vision_stays_false(self, tmp_path):
        """An orphan projector (no base model with a matching normalized
        stem) must not falsely mark any entry has_vision=True."""
        _write_fake_gguf(tmp_path / "solo-model-Q4_K_M.gguf")
        _write_fake_gguf(tmp_path / "mmproj-totally-unrelated-model-F16.gguf")

        mgr = _make_manager(tmp_path)
        models = mgr.scan_models()

        assert len(models) == 1
        assert models[0]["has_vision"] is False
        assert models[0]["mmproj_path"] is None
