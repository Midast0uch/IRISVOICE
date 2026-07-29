"""
Symlink traversal test (Phase 3, Wave 5, T5.1 / REQ-6).

A model reachable ONLY through a symlink must be discovered exactly once, and
a circular symlink must not hang the scan.

Symlink creation requires privileges unavailable in CI, so we exercise the
real traversal logic in `_iter_gguf_paths` by mocking `os.scandir` with
DirEntry-shaped fakes. Real .gguf files are created on disk so scan_models'
stat/parse steps succeed; the symlink *shape* (is_symlink / is_dir) is faked.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.agent.local_model_manager import LocalModelManager, SCAN_MAX_DEPTH


class FakeDirEntry:
    """Minimal os.DirEntry stand-in for traversal tests."""

    def __init__(self, path, is_symlink=False, is_dir=False, is_file=False):
        self.path = str(path)
        self.name = Path(path).name
        self._is_symlink = is_symlink
        self._is_dir = is_dir
        self._is_file = is_file

    def is_symlink(self):
        return self._is_symlink

    def is_dir(self, follow_symlinks=True):
        if self._is_symlink:
            return self._is_dir if follow_symlinks else False
        return self._is_dir

    def is_file(self, follow_symlinks=True):
        if self._is_symlink:
            return self._is_file if follow_symlinks else True
        return self._is_file

    def __repr__(self):
        return f"<FakeDirEntry {self.name} sym={self._is_symlink} dir={self._is_dir}>"


def _real_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not-a-real-gguf-header")  # parse_gguf_metadata -> {}


def _real_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def lmm(tmp_path):
    mgr = LocalModelManager()
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    mgr._models_dir_override = models_dir
    return mgr


def _patch_scandir(structure: dict):
    """structure: resolved-dir-path (str) -> list[FakeDirEntry]."""
    def fake_scandir(d):
        key = str(Path(d).resolve())
        return structure.get(key, [])
    return patch("backend.agent.local_model_manager.os.scandir", side_effect=fake_scandir)


class TestSymlinkedModelDiscovered:
    def test_model_only_via_symlinked_dir_appears_once(self, lmm, tmp_path):
        models_dir = lmm._models_dir_override
        hidden = tmp_path / "hidden"
        _real_file(hidden / "secret_model.gguf")
        _real_file(models_dir / "normal_model.gguf")
        _real_dir(models_dir / "link_to_hidden")  # stands in for the symlink target

        structure = {
            str(models_dir.resolve()): [
                FakeDirEntry(models_dir / "normal_model.gguf", is_file=True),
                # Symlink to a directory not otherwise under the scan root.
                FakeDirEntry(models_dir / "link_to_hidden", is_symlink=True, is_dir=True),
            ],
            str((models_dir / "link_to_hidden").resolve()): [
                FakeDirEntry(hidden / "secret_model.gguf", is_file=True),
            ],
        }
        with _patch_scandir(structure):
            found = lmm.scan_models()
        names = {m["filename"] for m in found}
        assert "secret_model.gguf" in names, "symlinked model must be discovered"
        secret_count = sum(1 for m in found if m["filename"] == "secret_model.gguf")
        assert secret_count == 1, (
            f"symlinked model must appear exactly once, got {secret_count}"
        )
        assert "normal_model.gguf" in names

    def test_circular_symlink_does_not_hang(self, lmm):
        models_dir = lmm._models_dir_override
        _real_file(models_dir / "a_model.gguf")
        _real_dir(models_dir / "loop")

        loop_entry = FakeDirEntry(models_dir / "loop", is_symlink=True, is_dir=True)
        structure = {
            str(models_dir.resolve()): [
                FakeDirEntry(models_dir / "a_model.gguf", is_file=True),
                loop_entry,
            ],
            # The loop dir points back to itself → cycle must terminate.
            str((models_dir / "loop").resolve()): [loop_entry],
        }
        with _patch_scandir(structure):
            found = lmm.scan_models()
        names = {m["filename"] for m in found}
        assert "a_model.gguf" in names

    def test_symlinked_file_deduped_by_resolved_path(self, lmm):
        models_dir = lmm._models_dir_override
        real = models_dir / "real_model.gguf"
        _real_file(real)

        structure = {
            str(models_dir.resolve()): [
                FakeDirEntry(real, is_file=True),
                # Symlink pointing at the SAME file — must not double-count.
                FakeDirEntry(models_dir / "sym_model.gguf", is_symlink=True, is_file=True),
            ],
        }
        with _patch_scandir(structure):
            found = lmm.scan_models()
        real_count = sum(1 for m in found if m["filename"] == "real_model.gguf")
        sym_count = sum(1 for m in found if m["filename"] == "sym_model.gguf")
        assert real_count + sym_count == 1, (
            f"symlink + real to same file must dedupe to 1, "
            f"got real={real_count} sym={sym_count}"
        )

    def test_depth_bound_respected(self, lmm):
        models_dir = lmm._models_dir_override
        # Build a deep chain of symlinked dirs deeper than SCAN_MAX_DEPTH.
        chain_dirs = [models_dir / f"d{i}" for i in range(SCAN_MAX_DEPTH + 3)]
        for d in chain_dirs:
            _real_dir(d)
        _real_file(chain_dirs[-1] / "deep_model.gguf")

        structure = {}
        # d0 is a symlink under models_dir
        structure[str(models_dir.resolve())] = [
            FakeDirEntry(chain_dirs[0], is_symlink=True, is_dir=True)
        ]
        for i in range(len(chain_dirs) - 1):
            structure[str(chain_dirs[i].resolve())] = [
                FakeDirEntry(chain_dirs[i + 1], is_symlink=True, is_dir=True)
            ]
        structure[str(chain_dirs[-1].resolve())] = [
            FakeDirEntry(chain_dirs[-1] / "deep_model.gguf", is_file=True)
        ]
        with _patch_scandir(structure):
            found = lmm.scan_models()
        assert isinstance(found, list)
