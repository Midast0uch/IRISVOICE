"""BT-14 (vision-goal-directed-search REQ-26, T39): structured goal plumbing.

AC26.1: fetch_one accepts a GoalAnatomy without breaking string callers.
AC26.2: model/capability edges receive the to_prompt() rendering (string
  protocol preserved end to end — session, VLM suggestion, frame triage).
AC26.3: the REQ-20 gate evaluates the goal's OWN guardrails; a plain string
  keeps the defaults.
AC26.4: the existing duck-typing suite passes UNCHANGED (asserted by running
  it, not by touching it).

Drives the REAL FetchVisionCapability.fetch_one with a fake session class +
scripted provider — no browser, no model, no network.
"""
from __future__ import annotations

import asyncio

from backend.core_models import GoalAnatomy
from backend.vision.fetch_vision import FetchVisionCapability


class _FakeSession:
    """4-positional session stand-in recording the goal it was built with."""

    seen_goals: list = []

    def __init__(self, job_id, url, goal, bounds):
        type(self).seen_goals.append(goal)
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
        CAP.acts.append(action)

    async def settle(self):
        return "<html><body>settled content long enough to pass</body></html>"

    async def close(self):
        return None


class _ScriptedProvider:
    """Suggests one password-typing action, then ends the loop."""

    def __init__(self):
        self.goals: list = []
        self.calls = 0

    def suggest_action(self, img_bytes, goal, **_k):
        self.goals.append(goal)
        self.calls += 1
        if self.calls == 1:
            return {"action": "type", "target": "#password", "reasoning": "fill secret"}
        return {"action": "error", "target": "", "reasoning": "done"}

    def describe_live_frame(self, img_bytes, **_k):
        return "no new content"

    def read_text(self, img_bytes, **_k):
        return ""

    def analyze_screen(self, img_bytes, question, **_k):
        return ""


class CAP:
    acts: list = []


def _run(goal):
    _FakeSession.seen_goals = []
    CAP.acts = []
    provider = _ScriptedProvider()
    cap = FetchVisionCapability(provider=provider, session_cls=_FakeSession)
    outcome = asyncio.run(cap.fetch_one("https://example.com/login", goal, "job-t39"))
    return outcome, provider


def test_custom_guardrails_block_what_defaults_permit():
    """AC26.3: GoalAnatomy(guardrails=[NO_EXTERNAL_AUTH]) blocks the
    password-typing action that the string-goal defaults permit — proving the
    CUSTOM list, not the defaults, was evaluated."""
    goal = GoalAnatomy(objective="check prices", guardrails=["NO_EXTERNAL_AUTH"])
    _run(goal)
    assert CAP.acts == [], f"password typing must be blocked, got {CAP.acts}"

    _run("check prices")
    assert len(CAP.acts) == 1, (
        "defaults (NO_PURCHASE + DOMAIN_BOUND) permit typing — the block above "
        "came from the custom list"
    )
    assert CAP.acts[0].kind == "type"


def test_model_edges_receive_prompt_rendering():
    """AC26.1+AC26.2: the object reaches fetch_one; every text edge (session
    construction, VLM suggestion) receives the to_prompt() string."""
    goal = GoalAnatomy(objective="check prices", guardrails=["NO_EXTERNAL_AUTH"])
    _run(goal)
    assert _FakeSession.seen_goals != []
    for seen in _FakeSession.seen_goals:
        assert isinstance(seen, str) and seen == goal.to_prompt()

    _, provider = _run(goal)
    assert provider.goals != []
    for seen in provider.goals:
        assert isinstance(seen, str) and seen == goal.to_prompt()


def test_defaults_equivalent_object_matches_its_string_rendering():
    """AC26.3 edge: a default-guardrails object behaves identically to its
    string rendering (same permit), while still rendering as text downstream."""
    goal = GoalAnatomy(objective="check prices")
    assert goal.guardrails == ["NO_PURCHASE", "DOMAIN_BOUND"]
    _run(goal)
    assert len(CAP.acts) == 1
    assert _FakeSession.seen_goals[0] == str(goal) == goal.to_prompt()


def test_empty_guardrails_fall_back_to_defaults():
    """Edge: guardrails=None/[] fails safe to the defaults (never fail open)."""
    goal = GoalAnatomy(objective="check prices", guardrails=[])
    _run(goal)
    assert len(CAP.acts) == 1
    goal_none = GoalAnatomy(objective="check prices", guardrails=None)
    _run(goal_none)
    assert len(CAP.acts) == 1
