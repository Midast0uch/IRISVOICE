"""BT (vision-goal-directed-search T31 / REQ-20 AC20.1-20.3): task
guardrails gate BEFORE the action allowlist in the fetch.vision loop.

A model-suggested purchase click must NEVER reach `session.act` — the gate
blocks it, records `rejected_guardrail` on the trajectory, and the run
settles gracefully. A benign click passes the gate and acts normally.
"""
from __future__ import annotations

import asyncio

from backend.vision.fetch_vision import FetchVisionCapability


class _Session:
    def __init__(self, *_a, **_k):
        self.acts: list = []

    async def open(self):
        return None

    def available(self):
        return True

    async def detect_wall(self):
        return None

    async def screenshot(self):
        return b"frame-bytes"

    async def act(self, action):
        self.acts.append(action)

    async def settle(self):
        return "<html><body>settled content long enough to be a page</body></html>"

    async def close(self):
        return None


class _ScriptedProvider:
    """First suggestion is the scripted action, then stop."""

    def __init__(self, first: dict):
        self._first = first
        self._calls = 0

    def suggest_action(self, img_bytes, goal, **_k):
        self._calls += 1
        if self._calls == 1:
            return dict(self._first)
        return {"action": "error", "target": "", "reasoning": "done"}

    def describe_live_frame(self, img_bytes, **_k):
        return "no new content"

    def read_text(self, img_bytes, **_k):
        return ""

    def analyze_screen(self, img_bytes, question, **_k):
        return ""


def _run(url: str, first: dict):
    session_holder: dict = {}

    orig_init = _Session.__init__

    def _capture_init(self, *a, **k):
        orig_init(self, *a, **k)
        session_holder["session"] = self

    _Session.__init__ = _capture_init
    try:
        cap = FetchVisionCapability(
            provider=_ScriptedProvider(first), session_cls=_Session
        )
        outcome = asyncio.run(cap.fetch_one(url, "buy nothing", "job-guard"))
    finally:
        _Session.__init__ = orig_init
    return session_holder["session"], outcome


def test_purchase_click_never_reaches_act():
    """AC20.1/AC20.2: NO_PURCHASE blocks a checkout click before act."""
    session, outcome = _run(
        "https://shop.example/item",
        {"action": "click", "target": "Buy Now — checkout", "reasoning": "buy it"},
    )
    assert session.acts == [], (
        f"guardrail failure: purchase click reached act(): {session.acts!r}"
    )
    assert outcome is not None  # the run settles gracefully, never raises
    assert outcome.actions_taken == 0


def test_benign_click_passes_the_gate():
    """Change-safety: ordinary navigation still acts — the gate is not a
    blanket click ban."""
    session, outcome = _run(
        "https://docs.example/guide",
        {"action": "click", "target": "Next section", "reasoning": "read on"},
    )
    assert len(session.acts) == 1
    assert session.acts[0].kind == "click"
    assert outcome.actions_taken == 1
