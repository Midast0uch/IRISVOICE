"""CT-7: the view_agent postMessage protocol stays exactly 2 in / 2 out.

CONTRACT LOCK — backend/proxy/view_agent.py must not gain commands.

Design decision D1 rejected driving the browser panel's iframe by extending this
protocol, because the frame is sandboxed WITHOUT ``allow-same-origin``: its
opaque origin means neither the parent page nor the backend can read its DOM or
pixels, so a vision model pointed at it would be blind. The real browser lives
server-side (BrowserSession) and the iframe mirrors it.

That decision is only durable if the protocol stays narrow. The temptation this
pin defends against is concrete and will recur: "we already have a channel into
the frame — just add click and type to it." Doing so would reintroduce a second,
unobservable automation path beside the server-side session, splitting the
feature's control flow across two browsers.

The frame speaks (scroll, ready) and accepts (scrollTo, highlight). Four
messages, fixed shapes. Anything else is a design change, not a patch.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_VIEW_AGENT = _REPO / "backend" / "proxy" / "view_agent.py"

# The complete protocol, per the module docstring.
_FRAME_TO_PARENT = {"scroll", "ready"}
_PARENT_TO_FRAME = {"scrollTo", "highlight"}


def _src() -> str:
    assert _VIEW_AGENT.is_file(), f"view_agent.py missing at {_VIEW_AGENT}"
    return _VIEW_AGENT.read_text(encoding="utf-8", errors="replace")


def test_frame_to_parent_messages_are_exactly_two():
    """The frame's outbound vocabulary is scroll + ready and nothing else."""
    src = _src()
    posted = set(re.findall(r'post\(\s*"([A-Za-z]+)"', src))
    assert posted == _FRAME_TO_PARENT, (
        f"frame->parent message kinds changed: expected {sorted(_FRAME_TO_PARENT)}, "
        f"found {sorted(posted)}. Widening this channel reintroduces a second "
        f"automation path beside the server-side BrowserSession (design D1)."
    )


def test_parent_to_frame_commands_are_exactly_two():
    """The frame accepts scrollTo + highlight and nothing else.

    Each accepted command appears as an `m.kind === "<name>"` guard.
    """
    src = _src()
    accepted = set(re.findall(r'm\.kind\s*===\s*"([A-Za-z]+)"', src))
    assert accepted == _PARENT_TO_FRAME, (
        f"parent->frame command set changed: expected {sorted(_PARENT_TO_FRAME)}, "
        f"found {sorted(accepted)}. Adding click/type here is the rejected "
        f"architecture (design D1) — the frame is sandboxed without "
        f"allow-same-origin, so vision cannot see what it would be driving."
    )


def test_no_interaction_primitives_leaked_into_the_frame_script():
    """No click/type/submit automation inside the injected script.

    Named explicitly because these are exactly the verbs a future change would
    add when trying to make the iframe interactive.
    """
    src = _src()
    # Only inspect the injected JS, not the Python docstring/comments.
    js_lines = [ln for ln in src.splitlines() if '"' in ln and "\\n" in ln]
    js = "\n".join(js_lines).lower()
    for verb in (".click(", "dispatchevent(new mouseevent", ".submit(", "keydown"):
        assert verb not in js, (
            f"view_agent's injected script gained an interaction primitive "
            f"({verb!r}). Interaction belongs to the server-side session."
        )


def test_frame_stays_origin_agnostic_on_send():
    """The frame posts to "*" and the PARENT validates, because the sandboxed
    frame has an opaque origin and cannot name the parent's. Pinned so a
    well-meaning "tighten the origin" change cannot silently mute the channel —
    the same class of change that broke three CSP directives previously.
    """
    src = _src()
    assert 'postMessage(msg, "*")' in src, (
        "the frame no longer posts to '*' — an opaque-origin frame cannot "
        "address the parent by origin, so this silently kills the channel"
    )
