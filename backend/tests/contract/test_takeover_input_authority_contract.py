"""T25 (specs/vision-browser-stage REQ-14 AC4/AC5) — the NARROWED guards
CT-6b / CT-7b for the grant-gated CDP takeover input path.

Owned by `specs/vision-browser-stage` T25 (owner-authorised 2026-09-17,
`pin_54db2ac956a0`). `specs/vision-browser-e2e-reliability` CONSUMES this file
(its T19) and must not re-own, duplicate, or edit it. CT-6/CT-7 in
`test_non_interference_contract.py` stay UNMODIFIED — this file only ADDS
guards; it never relaxes one.

Why the narrowing exists (from the amendment record): CT-6 and CT-7 are
STRING-shaped guards (grep the overlay for `pointer-events-none`, grep
`browser_session.py` for inbound-channel tokens). Both PASS today while their
INTENT would invert under CDP input — a takeover legitimately introduces a
grant-scoped input channel and a pointer-events:auto capture surface. The
amendment NARROWS both in the same spirit and pins the narrowing:

  CT-6b (AC4): the takeover capture surface is rendered ONLY while a grant is
      open, and the overlay's pointer-events opt-out is intact whenever no
      grant is open.
  CT-7b (AC5): every input path into the session is grant-gated — no ungated
      input route exists, and an input arriving with NO open grant is rejected.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_OVERLAY = _REPO / "components" / "iris" / "browser" / "BrowserNavigationOverlay.tsx"
_SURFACE = _REPO / "components" / "iris" / "browser" / "TakeoverLiveSurface.tsx"
_SESSION = _REPO / "backend" / "vision" / "browser_session.py"
_TAKEOVER = _REPO / "backend" / "vision" / "cdp_takeover.py"


# ── CT-6b: the capture surface exists ONLY under an open grant ──────────────

def test_ct6b_overlay_root_keeps_pointer_events_none():
    """CT-6b: the overlay root's pointer-events opt-out is intact (the capture
    surface is the ONLY exception, and it lives in its own component)."""
    src = _OVERLAY.read_text(encoding="utf-8")
    assert "pointer-events-none" in src, (
        "overlay root lost pointer-events-none — CT-6b: the opt-out must be "
        "intact; only the grant-scoped capture surface may opt in"
    )


def test_ct6b_capture_surface_is_rendered_only_under_a_grant():
    """CT-6b: the takeover capture surface renders ONLY while a grant is open.

    The surface is driven by the takeover state (present only while a
    browser_takeover question is open); it must not be an always-on element.
    """
    src = _SURFACE.read_text(encoding="utf-8")
    assert 'pointerEvents: "auto"' in src, (
        "CT-6b: the capture surface must be the ONE place pointer-events opts "
        "in (grant-scoped)"
    )
    overlay_src = _OVERLAY.read_text(encoding="utf-8")
    assert "takeover ?" in overlay_src or "takeover &&" in overlay_src, (
        "CT-6b: the capture surface must be gated on the takeover state"
    )


def test_ct6b_capture_surface_has_no_interactive_child_tags():
    """CT-6b (CT-6 spirit): the capture surface renders no <button>/<input>/<a>
    that would re-enable hit testing outside the grant-scoped div."""
    src = _SURFACE.read_text(encoding="utf-8")
    for forbidden in ("<button", "<input", "<a href"):
        assert forbidden not in src, (
            f"CT-6b: the capture surface renders {forbidden!r} — an interactive "
            "child defeats the grant-scoped pointer-events design"
        )


# ── CT-7b: every input path is grant-gated ─────────────────────────────────

class _FakeCDP:
    def __init__(self):
        self._h = {}

    def on(self, e, h):
        self._h[e] = h

    async def send(self, *_a):
        return None

    async def detach(self):
        return None


def test_ct7b_input_is_grant_gated_and_rejected_without_a_grant():
    """CT-7b: an input arriving with NO open grant is rejected + counted."""
    from backend.vision import cdp_takeover as cdp

    cdp.clear_registry()
    mgr = cdp.TakeoverManager(
        run_id="ct7b", cdp_factory=lambda _p: _FakeCDP(), frame_sink=lambda _e: None,
    )
    # No grant open -> rejected.
    forwarded = asyncio.run(
        mgr.deliver_input(cdp.TakeoverInput(kind="pointer", x=0.1, y=0.1))
    )
    assert forwarded is False, "CT-7b: input with no open grant must be rejected"
    assert mgr.rejected_inputs == 1, "CT-7b: the rejection must be counted"
    cdp.clear_registry()


def test_ct7b_only_page_level_kinds_are_representable():
    """CT-7b: a browser-level / navigation command is not a representable input
    (no ungated route exists — the allowlist IS the gate for kind)."""
    from backend.vision import cdp_takeover as cdp

    cdp.clear_registry()
    mgr = cdp.TakeoverManager(run_id="ct7b2", cdp_factory=lambda _p: None)
    mgr.open_grant(question_id="q", wall_kind="captcha")
    forwarded = asyncio.run(
        mgr.deliver_input(cdp.TakeoverInput(kind="navigate", text="/etc/passwd"))
    )
    assert forwarded is False, "CT-7b: a navigation command must be rejected"
    cdp.clear_registry()


def test_ct7b_session_module_has_no_ungated_input_route():
    """CT-7b: `browser_session.py` exposes NO inbound route; the input path
    lives ONLY in the grant-gated `cdp_takeover` module."""
    sess = _SESSION.read_text(encoding="utf-8")
    for forbidden in ("APIRouter", "@app.", "WebSocket", "add_api_route", "FastAPI"):
        assert forbidden not in sess, (
            f"CT-7b: browser_session.py grew an ungated inbound channel "
            f"({forbidden}) — the ONLY input route must be grant-gated in "
            f"cdp_takeover"
        )
    take = _TAKEOVER.read_text(encoding="utf-8")
    assert "def deliver_input" in take, "CT-7b: the input entry point must exist"
    assert "if not self.is_open()" in take, (
        "CT-7b: deliver_input must gate on an open grant"
    )

