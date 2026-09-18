"""A vision action's fields must survive BOTH forwarders, and an unbound
session must be representable.

Two pins, both for bug classes this repo has now produced repeatedly.

── 1. The SECOND forwarder ──────────────────────────────────────────────────
`test_ui_forwarder_contract` pins the agent-path forwarder (tool_bridge's
`_crawl_ui_emitter`), which forwards payloads WHOLESALE. But there is a second,
independent forwarder on the gateway's own crawl path — `_on_progress` in
iris_gateway — and for CRAWLER_VISION_ACTION it copies coordinates through a
HAND-WRITTEN KEY TUPLE. Nothing tested it.

That is the same shape as every failure the sibling module's docstring lists: a
correct producer, a correct consumer, and a middle that quietly keeps a subset.
Live 2026-08-12: BrowserSession began recording `scroll_y`/`scroll_height` so the
panel could mirror the session's scroll into the iframe the user watches, and the
field reached this whitelist and stopped, because the whitelist did not know
about it.

`_on_progress` is a closure inside a request handler, so this is a SOURCE-level
contract rather than a behavioural one — deliberately. The property worth pinning
is not "one payload survived once" but "the whitelist is not allowed to fall
behind the producer", and that is a statement about the two sources together.
Add a key to `last_action_point` and forget the gateway, and this fails.

── 2. "No active thread" must be representable ──────────────────────────────
`set_active_conversation` used to be reachable only with a real id, so the
gateway's new_conversation handler expressed "the user left a thread and has not
started the next one" as `conversation_id or session_id` — binding the session to
a pseudo-thread and clearing THAT kernel while the thread the user actually left
stayed bound and live. A wake word or a reconnect then resolved straight back
into it (the "new conversation reverts to the old one" report, 2026-08-12).
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SESSION = _REPO / "backend" / "vision" / "browser_session.py"
_GATEWAY = _REPO / "backend" / "iris_gateway.py"


def _last_action_point_keys() -> set:
    """Every literal key BrowserSession writes into `last_action_point`.

    Read from the SOURCE, so a newly recorded coordinate is caught here rather
    than being silently undeliverable. Covers both whole-dict assignment
    (`self.last_action_point = {...}`) and later key writes
    (`self.last_action_point["scroll_y"] = ...`).
    """
    tree = ast.parse(_SESSION.read_text(encoding="utf-8", errors="replace"))
    keys: set = set()

    def _is_lap(node: ast.AST) -> bool:
        return isinstance(node, ast.Attribute) and node.attr == "last_action_point"

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            # self.last_action_point = {"scroll_dx": ..., "scroll_dy": ...}
            if _is_lap(target) and isinstance(node.value, ast.Dict):
                for k in node.value.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        keys.add(k.value)
            # self.last_action_point["scroll_y"] = ...
            if (
                isinstance(target, ast.Subscript)
                and _is_lap(target.value)
                and isinstance(target.slice, ast.Constant)
                and isinstance(target.slice.value, str)
            ):
                keys.add(target.slice.value)
    return keys


def _gateway_forwards_vision_payload_whole() -> bool:
    """True when iris_gateway's crawler_vision_action branch merges the
    producer's WHOLE payload (`pl`) into the emitted message rather than
    copying a fixed key subset.

    REQ-6 AC1 (this spec's T3) replaced the old hand-written `_coord_key`
    allowlist with wholesale forwarding: the branch merges the payload over
    the canonical shape from `tool_bridge._UI_EVENT_DEFAULTS`. This helper
    locates that merge — a comprehension of the form
    `{k: v for k, v in pl.items() ...}` inside the CRAWLER_VISION_ACTION
    branch — so the guard below can assert the forwarder CANNOT drop a field
    by construction. If the branch is ever reduced back to a key tuple, this
    returns False and the guard fails loudly.
    """
    tree = ast.parse(_GATEWAY.read_text(encoding="utf-8", errors="replace"))

    def _iterates_pl(node: ast.AST) -> bool:
        # {k: v for k, v in pl.items() ...}
        if not isinstance(node, ast.DictComp):
            return False
        it = node.generators[0].iter if node.generators else None
        # pl.items()  ->  Attribute(value=Name('pl'), attr='items')
        return (
            isinstance(it, ast.Call)
            and isinstance(it.func, ast.Attribute)
            and it.func.attr == "items"
            and isinstance(it.func.value, ast.Name)
            and it.func.value.id == "pl"
        )

    for node in ast.walk(tree):
        if _iterates_pl(node):
            return True
    return False


def _gateway_still_has_a_coord_key_whitelist() -> bool:
    """True if a `for _coord_key in (...)` subsetting loop is still present.

    After T3 it must NOT be: the whole point of REQ-6 AC1 is that no middle
    allowlist can drop a field. This is asserted as a negative so a future
    edit that reintroduces the pattern is caught immediately.
    """
    tree = ast.parse(_GATEWAY.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and getattr(node.target, "id", None) == "_coord_key":
            return True
    return False


def test_gateway_forwards_the_whole_vision_payload_not_a_whitelist():
    """REQ-6 AC1 (T3): the gateway's crawler_vision_action branch forwards the
    producer's whole payload, so EVERY field BrowserSession records (scroll_y,
    scroll_height, x, y, viewport_w, viewport_h, capture_page, escalated, and
    any future coordinate) survives to the panel by construction.

    The predecessor of this test pinned a `_coord_key` whitelist and failed
    each time a new coordinate was added but the whitelist was not. The fix is
    structural: the whitelist is GONE and the payload rides whole, which is a
    strictly stronger guarantee — there is no list left to fall behind.
    """
    produced = _last_action_point_keys()
    assert produced, (
        "parsed no last_action_point keys from browser_session.py — the AST "
        "walk is wrong, and this test would pass vacuously"
    )

    assert _gateway_forwards_vision_payload_whole(), (
        "iris_gateway's crawler_vision_action branch no longer merges the "
        "producer's whole payload (`{k: v for k, v in pl.items() ...}`) — a "
        "hand-maintained subset has crept back in, which is the exact REQ-6 "
        "AC1 defect this guard exists to catch"
    )

    assert not _gateway_still_has_a_coord_key_whitelist(), (
        "iris_gateway still contains a `for _coord_key in (...)` subsetting "
        "loop on the crawler_vision_action path — the REQ-6 AC1 whole-payload "
        "forwarding regressed"
    )


def test_scroll_actions_carry_an_absolute_position_not_only_a_delta():
    """The panel mirrors the session's scroll into the iframe the user watches.

    A delta cannot be mirrored: the iframe and the headless page do not start
    from the same offset, and a single dropped event desynchronises them for the
    rest of the run. An absolute offset re-anchors on every event. This pins the
    absolute field's existence so a future refactor cannot quietly reduce the
    payload back to deltas and leave the iframe frozen.
    """
    produced = _last_action_point_keys()
    assert "scroll_y" in produced, (
        "a scroll action no longer records an absolute scroll_y — the panel can "
        "only mirror deltas, which desynchronise permanently on one dropped event"
    )


def test_a_session_with_no_active_conversation_is_representable():
    """`set_active_conversation(sid, None)` must UNBIND, not store a placeholder.

    Without this, "the user left a thread and has not started the next one" has
    no representation, and the gateway substituted the session id — which bound
    the session to a pseudo-thread and left the real previous thread live.
    """
    from backend.agent.agent_kernel import (
        _session_active_conversation,
        set_active_conversation,
    )

    sid = "session_unbind_contract"
    try:
        set_active_conversation(sid, "conv-42")
        assert _session_active_conversation.get(sid) == "conv-42"

        set_active_conversation(sid, None)
        assert sid not in _session_active_conversation, (
            "unbinding left the session in the registry; a later lookup would "
            "resolve the thread the user just walked away from"
        )
    finally:
        _session_active_conversation.pop(sid, None)
