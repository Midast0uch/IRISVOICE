"""T17 (REQ-2) — the guard that would have caught all five bypasses at once.

Five separate production call sites were found constructing `LFMVLProvider()`
directly instead of going through `resolve_vision_client()` /
`resolve_vision_provider()` — discovered across TWO rounds (T16 found three:
`automation/vision.py`, `agent/vision_guided_operator.py`,
`iris_gateway.py:195`; T17 found two more: `vision/screen_monitor.py`,
`tools/media_tools.py`). Each bypass always spawns tier 3 regardless of what
the bound brain/tool can already do — the hierarchy silently does nothing for
that caller. The real gap was never having a test for the SHAPE of this
mistake, only ever chasing individual instances.

This is a real SOURCE-LEVEL scan over backend/ (excluding tests): it parses
every production `.py` file with `ast` and finds every `Call` node whose
callee is (or ends in) the name `LFMVLProvider` — a real construction,
immune to `# LFMVLProvider()` mentions in docstrings/comments (see
test_search_provider_wiring.py's `_calls_in` for the same AST-over-grep
technique in this repo).

Sanctioned exceptions (named here, not silently allowed):
  - `backend/agent/inference/router.py` — the resolver itself; its tier-3
    branch is the ONE place allowed to fall back to a bare `LFMVLProvider()`.
  - `backend/tools/lfm_vl_provider.py` — the module's own singleton
    (`get_lfm_vl_provider()` at `:290`).
  - `backend/iris_gateway.py` — T16 verified `self._vision_provider =
    LFMVLProvider()` (`:200`) is a DELIBERATE tier-3 fallback default, not a
    bypass: `_resolve_vision_availability` checks the full hierarchy first
    and only falls through to health-checking this instance when neither
    brain nor tool can see. Sanctioned explicitly, with this reason, not
    silently allowed by a broad exclude.

No GPU, no network, no real model loads — pure source-text/AST scan.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_BACKEND = _REPO / "backend"

_TARGET_NAME = "LFMVLProvider"

# Sanctioned construction sites, relative to the repo root, with the reason
# each is allowed. A sixth file appearing here without being added to this
# dict (or an unsanctioned file appearing at all) is exactly the defect this
# guard exists to catch.
_SANCTIONED = {
    "backend/agent/inference/router.py":
        "the resolver itself — tier-3 branch of resolve_vision_client()",
    "backend/tools/lfm_vl_provider.py":
        "the module's own singleton (get_lfm_vl_provider())",
    "backend/iris_gateway.py":
        "T16-verified deliberate tier-3 fallback default "
        "(self._vision_provider), checked only after the full hierarchy",
}


def _is_lfm_vl_provider_call(node: ast.Call) -> bool:
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id == _TARGET_NAME
    if isinstance(fn, ast.Attribute):
        return fn.attr == _TARGET_NAME
    return False


def _construction_sites() -> dict:
    """Map of {relative_path: [line numbers]} for every real
    `LFMVLProvider(...)` call found under backend/, excluding any tests
    directory. Skips files that fail to parse (none expected; if one does,
    that is a separate, louder failure elsewhere in the suite)."""
    sites: dict = {}
    for path in _BACKEND.rglob("*.py"):
        parts = path.parts
        if "tests" in parts or "__pycache__" in parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _is_lfm_vl_provider_call(node)
        ]
        if lines:
            rel = path.relative_to(_REPO).as_posix()
            sites[rel] = lines
    return sites


def test_no_unsanctioned_lfm_vl_provider_construction():
    """The actual guard: every file that constructs LFMVLProvider() directly
    must be one of the exactly-three sanctioned sites. Fails loudly, naming
    the file, if a sixth bypass is ever introduced."""
    sites = _construction_sites()
    unsanctioned = sorted(set(sites) - set(_SANCTIONED))
    assert not unsanctioned, (
        "Found production module(s) constructing LFMVLProvider() directly, "
        "bypassing resolve_vision_client()/resolve_vision_provider(): "
        f"{unsanctioned}. Route through resolve_vision_client() "
        "(backend/agent/inference/router.py) instead, or add the file to "
        "_SANCTIONED above with a stated reason if it is genuinely a new "
        "resolver-tier default."
    )


def test_sanctioned_sites_still_exist_and_still_construct_it():
    """The flip side: if a sanctioned site stops constructing LFMVLProvider
    (e.g. router.py's tier-3 branch gets refactored away), this test goes
    red too — the sanction list must track reality, not just permit it."""
    sites = _construction_sites()
    missing = sorted(f for f in _SANCTIONED if f not in sites)
    assert not missing, (
        f"Sanctioned site(s) no longer construct LFMVLProvider(): {missing}. "
        "Either the sanction is stale and should be removed from "
        "_SANCTIONED, or something regressed the tier-3 default."
    )


def test_known_bypass_sites_are_now_clean():
    """Regression pin for the exact two sites T17 fixed — both must be
    ABSENT from the construction-site map now that they route through
    resolve_vision_client()."""
    sites = _construction_sites()
    for rel in (
        "backend/vision/screen_monitor.py",
        "backend/tools/media_tools.py",
    ):
        assert rel not in sites, (
            f"{rel} still constructs LFMVLProvider() directly — T17's fix "
            "regressed"
        )


@pytest.mark.parametrize("bad_source", [
    "from backend.tools.lfm_vl_provider import LFMVLProvider\n"
    "provider = LFMVLProvider()\n",
    "from backend.tools import lfm_vl_provider as vl\n"
    "provider = vl.LFMVLProvider()\n",
])
def test_the_scanner_actually_detects_a_bypass(tmp_path, bad_source, monkeypatch):
    """Proves the AST scan itself is not a no-op: a synthetic file placed
    under a temp 'backend/' tree with a direct construction (both the bare
    `LFMVLProvider()` and the `module.LFMVLProvider()` attribute-call shape)
    is found and would fail the guard above if it were unsanctioned."""
    fake_backend = tmp_path / "backend"
    fake_backend.mkdir()
    bad_file = fake_backend / "a_new_bypass.py"
    bad_file.write_text(bad_source, encoding="utf-8")

    # Patch this module's own globals directly (not via a dotted import
    # string) — the exact qualified name pytest imports this file under
    # depends on rootdir/package discovery, which is not worth pinning here.
    this_module = sys.modules[__name__]
    monkeypatch.setattr(this_module, "_BACKEND", fake_backend)
    monkeypatch.setattr(this_module, "_REPO", tmp_path)
    sites = _construction_sites()
    assert "backend/a_new_bypass.py" in sites
