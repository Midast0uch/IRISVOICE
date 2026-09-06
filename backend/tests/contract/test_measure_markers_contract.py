"""Contract tests for the memory-accounting process markers (CT-4, REQ-23 T36).

Pins the ``scripts/measure_memory.py`` marker coverage that the REQ-23
harness (``backend/scripts/benchmark_websearch_memory.py``) reuses: if a
worker is renamed — or a new backend subprocess added — without extending
``_IRIS_MARKERS``, the process silently drops out of EVERY memory assertion
(the idle gate included) and bloat goes unmeasured.

Also pins that the harness imports the pattern rather than forking it, and
that T36-pinned default bounds exist.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MEASURE_PATH = _REPO_ROOT / "scripts" / "measure_memory.py"
_HARNESS_PATH = _REPO_ROOT / "backend" / "scripts" / "benchmark_websearch_memory.py"

# The worker/process names that must never silently leave accounting.
REQUIRED_MARKERS = frozenset({
    "crawl_worker",
    "browser_pool",
    "uvicorn",
    "parakeet",
    "tts_worker",
    "main.py",
})


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_measure_markers_cover_all_workers():
    """CT-4: _IRIS_MARKERS covers crawl_worker + browser_pool (+ the rest)."""
    assert _MEASURE_PATH.is_file(), "scripts/measure_memory.py must exist"
    mod = _load("iris_measure_memory_ct4", _MEASURE_PATH)
    markers = set(getattr(mod, "_IRIS_MARKERS", ()))
    missing = REQUIRED_MARKERS - markers
    assert not missing, f"_IRIS_MARKERS silently drops workers from accounting: {missing}"


def test_measure_returns_row_dicts():
    """CT-4: measure() yields {pid, name, private_mb, wset_mb} rows (possibly empty)."""
    mod = _load("iris_measure_memory_ct4_rows", _MEASURE_PATH)
    rows = mod.measure()
    assert isinstance(rows, list)
    for r in rows:
        assert {"pid", "name", "private_mb", "wset_mb"} <= set(r), f"bad row shape: {r}"


def test_harness_imports_the_pattern_instead_of_forking_it():
    """CT-4: the harness reuses measure_memory (no drifted duplicate marker set)."""
    assert _HARNESS_PATH.is_file(), "benchmark_websearch_memory.py must exist (T34)"
    src = _HARNESS_PATH.read_text(encoding="utf-8", errors="replace")
    assert "measure_memory.py" in src, "harness must reference scripts/measure_memory.py"
    assert "_IRIS_MARKERS =" not in src, "harness must not fork its own marker set"
    assert "def measure(" not in src, "harness must not reimplement measure()"


def test_harness_has_pinned_default_bounds():
    """T36: default bounds exist and are positive (env overrides win)."""
    src = _HARNESS_PATH.read_text(encoding="utf-8", errors="replace")
    for const in ("DEFAULT_PEAK_BOUND_MB", "DEFAULT_RETURN_BOUND_MB",
                  "DEFAULT_DRIVER_PEAK_BOUND_MB"):
        assert const in src, f"harness must define {const}"
    mod = _load("iris_websearch_harness_ct4", _HARNESS_PATH)
    assert mod.DEFAULT_PEAK_BOUND_MB > 0
    assert mod.DEFAULT_RETURN_BOUND_MB > 0
    assert mod.DEFAULT_DRIVER_PEAK_BOUND_MB > 0
