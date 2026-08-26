"""T14 (specs/vision-browser-stage REQ-14): non-interference contracts.

Two facts were TRUE in audit but UNPINNED — exactly the kind of guarantee
that rots silently:

  CT-6 (AC1): the overlay consumes NO pointer events, ever. It sits above
      the iframe at z-30; one missing `pointer-events-none would make the
      shutter steal every click meant for the page.

  CT-7 (AC2): the vision session's Playwright page has NO inbound control
      channel from the UI. The agent acts server-side; the iframe is a
      downstream mirror. Nothing in the frontend may drive the session, and
      BrowserSession must expose nothing a frontend could drive.

  AC3: the scroll mirror affects only the local iframe view — sendScrollTo
      posts INTO the sandboxed frame via the view protocol; it must never
      reach toward the backend.
"""

from __future__ import annotations

import re
from pathlib import Path

OVERLAY = Path("components/iris/browser/BrowserNavigationOverlay.tsx")
SESSION = Path("backend/vision/browser_session.py")
VIEW_PROTOCOL = Path("hooks/useViewProtocol.ts")


def test_ct6_overlay_root_is_pointer_events_none():
    """REQ-14 AC1: the overlay root carries pointer-events:none."""
    src = OVERLAY.read_text(encoding="utf-8")
    assert "pointer-events-none" in src, (
        "overlay root lost pointer-events-none — the shutter would swallow "
        "every click meant for the iframe beneath it"
    )


def test_ct6_canvas_explicitly_opts_out_and_no_interactive_children():
    """The border canvas explicitly opts out too (belt and braces), and the
    component renders no interactive element that would re-enable hit testing."""
    src = OVERLAY.read_text(encoding="utf-8")
    assert 'pointerEvents: "none"' in src, (
        "the border canvas must explicitly set pointerEvents none"
    )
    for forbidden in ("<button", "<input", "<a href"):
        assert forbidden not in src, (
            f"overlay renders {forbidden!r} - an interactive child defeats "
            "the pointer-events-none root"
        )


def test_ct7_browser_session_has_no_inbound_control_channel():
    """REQ-14 AC2: the vision session is driven by code, not by the UI.
    No HTTP/WS route may live in the session module, and the frontend must
    never import it."""
    src = SESSION.read_text(encoding="utf-8")
    for forbidden in ("APIRouter", "@app.", "WebSocket", "add_api_route", "FastAPI"):
        assert forbidden not in src, (
            f"BrowserSession grew an inbound channel ({forbidden}) - the "
            "agent's browser must never be controllable from the UI"
        )

    hits = []
    # Frontend must not reference the vision session module at all.
    for base in ("components", "hooks", "app", "lib"):
        for p in Path(base).rglob("*"):
            if p.suffix in (".ts", ".tsx") and "browser_session" in p.read_text(
                encoding="utf-8", errors="ignore"
            ):
                hits.append(str(p))
    assert not hits, f"frontend references the vision session module: {hits}"


def test_ct7_scroll_mirror_never_reaches_toward_the_backend():
    """REQ-14 AC3: sendScrollTo posts into the LOCAL frame only."""
    src = VIEW_PROTOCOL.read_text(encoding="utf-8")
    assert "postMessage" in src, "scroll mirror works via postMessage into the frame"
    start = src.find("const sendScrollTo")
    end = src.find("return { sendScrollTo")
    assert start != -1 and end != -1 and end > start, "hook structure changed"
    body = src[start:end]
    # sendScrollTo delegates to the hook's frame-only `send(...) helper, whose
    # sole primitive is postMessage INTO the frame. No backendward path (WS
    # send / HTTP fetch / app event dispatch) may appear.
    assert re.search(r"send\(\s*.scrollTo", body), (
        "sendScrollTo must route through the frame-only send helper"
    )
    assert not re.search(r"sendMessage|fetch\(", body), (
        "sendScrollTo gained a backendward path - the mirror must stay local"
    )
