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


def _gateway_vision_whitelist() -> set:
    """The key tuple iris_gateway copies onto the crawler_vision_action message.

    Located by its loop variable (`for _coord_key in (...)`) so it is found
    wherever in the file it lives.
    """
    tree = ast.parse(_GATEWAY.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        if getattr(node.target, "id", None) != "_coord_key":
            continue
        if isinstance(node.iter, (ast.Tuple, ast.List, ast.Set)):
            return {
                e.value
                for e in node.iter.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            }
    return set()


def test_gateway_whitelist_carries_every_coordinate_the_session_records():
    produced = _last_action_point_keys()
    assert produced, (
        "parsed no last_action_point keys from browser_session.py — the AST walk "
        "is wrong, and this test would pass vacuously"
    )

    forwarded = _gateway_vision_whitelist()
    assert forwarded, (
        "found no `for _coord_key in (...)` whitelist in iris_gateway.py — either "
        "it was renamed (update this test) or the copy loop is gone"
    )

    dropped = sorted(produced - forwarded)
    assert not dropped, (
        f"BrowserSession records {dropped} on last_action_point but the gateway's "
        f"crawler_vision_action whitelist does not carry them, so they die in the "
        f"forwarder and the panel never sees them. Whitelist: {sorted(forwarded)}"
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
