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

EXTENDED 2026-09-18 (this spec's T1, REQ-1): the scan now ALSO catches the
`get_vision_provider()` SINGLETON-ACCESS shape, because the two browser
consumers this spec fixed (`backend/vision/fetch_vision.py`,
`backend/vision/search_discovery.py`) reached tier 3 through the singleton
helper rather than a bare constructor. Scanning only `LFMVLProvider()` would
have left the exact browser bypass this spec exists to close completely
uncovered.

SCAN SCOPE RULE (Decision 17 + OQ-18, RESOLVED 2026-09-18): the scan
separates VISION SERVING (must go through the resolver) from LIFECYCLE
CONTROL and HEALTH (must talk to tier 3 directly). Both shapes are
allowlisted at exactly the sites that legitimately own tier-3 lifecycle/health:

  - `backend/agent/inference/router.py` — the resolver itself; its tier-3
    branch is the ONE place allowed to fall back to a bare `LFMVLProvider()`.
  - `backend/tools/vision_provider.py` — the module's own singleton
    (`get_vision_provider()`).
  - `backend/iris_gateway.py` — T16 verified `self._vision_provider =
    LFMVLProvider()` (`:200`) is a DELIBERATE tier-3 fallback default, not a
    bypass: `_resolve_vision_availability` checks the full hierarchy first and
    only falls through to health-checking this instance when neither brain nor
    tool can see. Also the lifecycle SEED (`:10907-10909`, a health_check
    probe) and the user toggle (`:10972-10976`, `set_vision_enabled` — MUST
    construct tier 3 directly to start/stop it).
  - `backend/inference_router.py` — `:318-319` is a HEALTH check
    (`get_vision_provider().health_check()`), not serving.
  - `backend/tools/vision_mcp_server.py` — the DESKTOP computer-use surface
    (`vision.*` MCP family). It captures the DESKTOP, not a browser page, and
    pairs with `NativeGUIOperator`; it is the desktop SIBLING of the browser
    path, not a bypass of it. Whether its lookup should also route through the
    resolver is a PRIVACY call deferred to a future amendment (D17/OQ-18) — so
    it is allowlisted here rather than silently fixed.

DEVELOPER MODE ONLY (Decision 17): this AST scan is an AUTHORING-TIME guard
for code work, not a runtime gate. In Personal mode it does not run. The mode
read fails CLOSED to `developer` (see `backend/capabilities.py`), and this
repo's working config is developer, so the guard is active here.

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
_SINGLETON_HELPER = "get_vision_provider"

# Sanctioned sites, relative to the repo root, with the reason each is
# allowed. A sixth file appearing here without being added to this dict (or an
# unsanctioned file appearing at all) is exactly the defect this guard exists
# to catch.
_SANCTIONED = {
    "backend/agent/inference/router.py":
        "the resolver itself — tier-3 branch of resolve_vision_client()",
    "backend/tools/vision_provider.py":
        "the module's own singleton (get_vision_provider())",
    "backend/iris_gateway.py":
        "T16-verified deliberate tier-3 fallback default "
        "(self._vision_provider), checked only after the full hierarchy; "
        "plus the lifecycle SEED (:10907-10909) and the user toggle "
        "set_vision_enabled (:10972-10976) which MUST construct tier 3 directly",
    "backend/inference_router.py":
        "HEALTH check (:318-319), not serving (OQ-18)",
    "backend/tools/vision_mcp_server.py":
        "the DESKTOP computer-use surface (vision.* MCP family) — a sibling of "
        "the browser path, not a bypass; resolver routing is a deferred "
        "privacy call (D17/OQ-18)",
}


def _is_vision_provider_call(node: ast.Call) -> bool:
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id == _TARGET_NAME
    if isinstance(fn, ast.Attribute):
        return fn.attr == _TARGET_NAME
    return False


def _is_singleton_access(node: ast.Call) -> bool:
    """True for a `get_vision_provider()` call (the singleton-access shape).

    This is the SECOND bypass shape: `backend/vision/fetch_vision.py` and
    `backend/vision/search_discovery.py` never wrote `LFMVLProvider()` — they
    called the module singleton helper, which constructs tier 3 just as
    surely. Without this the extended scan would have been blind to the exact
    browser bypass T1 fixed.
    """
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id == _SINGLETON_HELPER
    if isinstance(fn, ast.Attribute):
        return fn.attr == _SINGLETON_HELPER
    return False


def _is_bypass_call(node: ast.Call) -> bool:
    return _is_vision_provider_call(node) or _is_singleton_access(node)


def _construction_sites() -> dict:
    """Map of {relative_path: [line numbers]} for every real tier-3 reach
    found under backend/, excluding any tests directory. A "reach" is a
    `LFMVLProvider(...)` construction OR a `get_vision_provider()` singleton
    access. Skips files that fail to parse (none expected; if one does,
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
            if isinstance(node, ast.Call) and _is_bypass_call(node)
        ]
        if lines:
            rel = path.relative_to(_REPO).as_posix()
            sites[rel] = lines
    return sites


def test_no_unsanctioned_vision_provider_construction():
    """The actual guard: every file that reaches tier 3 directly (constructs
    `LFMVLProvider()` OR calls the `get_vision_provider()` singleton) must be
    one of the sanctioned sites. Fails loudly, naming the file, if a sixth
    bypass is ever introduced."""
    sites = _construction_sites()
    unsanctioned = sorted(set(sites) - set(_SANCTIONED))
    assert not unsanctioned, (
        "Found production module(s) reaching tier-3 vision directly "
        "(LFMVLProvider() or get_vision_provider()), bypassing "
        "resolve_vision_client()/resolve_vision_provider(): "
        f"{unsanctioned}. Route through resolve_vision_client() "
        "(backend/agent/inference/router.py) instead, or add the file to "
        "_SANCTIONED above with a stated reason if it is genuinely a new "
        "resolver-tier default."
    )


def test_sanctioned_sites_still_exist_and_still_reach_tier_three():
    """The flip side: if a sanctioned site stops reaching tier 3 (e.g.
    router.py's tier-3 branch gets refactored away), this test goes red too —
    the sanction list must track reality, not just permit it."""
    sites = _construction_sites()
    missing = sorted(f for f in _SANCTIONED if f not in sites)
    assert not missing, (
        f"Sanctioned site(s) no longer reach tier-3 vision: {missing}. "
        "Either the sanction is stale and should be removed from "
        "_SANCTIONED, or something regressed the tier-3 default."
    )


def test_known_bypass_sites_are_now_clean():
    """Regression pin for the bypass sites fixed by T17 AND this spec's T1 —
    all must be ABSENT from the reach map now that they route through
    resolve_vision_client()."""
    sites = _construction_sites()
    for rel in (
        "backend/vision/screen_monitor.py",
        "backend/tools/media_tools.py",
        # T1 (this spec, REQ-1): the two browser consumers that used the
        # singleton helper, not a bare constructor.
        "backend/vision/fetch_vision.py",
        "backend/vision/search_discovery.py",
    ):
        assert rel not in sites, (
            f"{rel} still reaches tier-3 vision directly — the resolver "
            "bypass regressed"
        )


@pytest.mark.parametrize("bad_source", [
    "from backend.tools.vision_provider import LFMVLProvider\n"
    "provider = LFMVLProvider()\n",
    "from backend.tools import vision_provider as vl\n"
    "provider = vl.LFMVLProvider()\n",
    "from backend.tools.vision_provider import get_vision_provider\n"
    "provider = get_vision_provider()\n",
])
def test_the_scanner_actually_detects_a_bypass(tmp_path, bad_source, monkeypatch):
    """Proves the AST scan itself is not a no-op: a synthetic file placed
    under a temp 'backend/' tree with a direct construction (the bare
    `LFMVLProvider()`, the `module.LFMVLProvider()` attribute-call shape, and
    the `get_vision_provider()` singleton shape) is found and would fail the
    guard above if it were unsanctioned."""
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

