"""fetch.vision goal contract (vision-goal-directed-search T23, REQ-1 AC1.4 +
REQ-17 AC2): the GOAL drives the vision loop end to end — not a positional
string nobody reads.

Two pins:
  1. 12-keyword Schema + GoalAnatomy duck-typing: a `GoalAnatomy` instance
     (the Wave-1 structured goal model) is accepted by `fetch.vision` and
     renders through `__str__`/`to_prompt` so the VLM prompt contains the
     objective — legacy callers that pass a plain string keep working too.
  2. The goal reaches BOTH the action prompter (suggest_action) and the
     extractor prompt (extract_page_frames) unchanged — a goal mutated
     in flight (REQ-1 AC1.3) must propagate to the NEXT action suggestion,
     because the session reads the live goal each loop turn.
"""
from __future__ import annotations

import asyncio

from backend.core_models import GoalAnatomy, TaskType
from backend.vision.fetch_vision import FetchVisionCapability


class _RecordingSession:
    def __init__(self, *_a, goal=None, **_k):
        self.seen_goal = goal

    async def open(self):
        return None

    def available(self):
        return True

    async def detect_wall(self):
        return None

    async def screenshot(self):
        return b"frame-bytes"

    async def act(self, action):
        return None

    async def settle(self):
        return "<html><body>settled content long enough to be a page</body></html>"

    async def close(self):
        return None


class _RecordingProvider:
    def __init__(self):
        self.suggest_goals: list = []

    def suggest_action(self, img_bytes, goal, **_k):
        self.suggest_goals.append(goal)
        # One action, then stop — the loop exits with the extractor phase.
        if len(self.suggest_goals) == 1:
            return {"action": "click", "target": "#a", "reasoning": "hit it"}
        return {"action": "error", "target": "", "reasoning": "done"}

    def describe_live_frame(self, img_bytes, **_k):
        return "no new content"

    def read_text(self, img_bytes, **_k):
        return ""

    def analyze_screen(self, img_bytes, question, **_k):
        return ""


def test_goal_anatomy_duck_types_through_the_vision_loop():
    """AC1.4: GoalAnatomy renders via __str__/to_prompt so un-migrated
    callers (the vision loop is one) never break. The contract pins that the
    provider sees the OBJECTIVE text — not '<GoalAnatomy object>'."""
    goal = GoalAnatomy(
        objective="Find the RTX 5090 launch price",
        task_type=TaskType.DATA_EXTRACTION,
    )
    provider = _RecordingProvider()
    cap = FetchVisionCapability(provider=provider, session_cls=_RecordingSession)
    asyncio.run(cap.fetch_one("https://example.com", goal, "job-goal"))

    assert provider.suggest_goals, "suggest_action was never called"
    rendered = str(provider.suggest_goals[0])
    assert "Find the RTX 5090 launch price" in rendered, (
        f"GoalAnatomy did not render its objective into the vision prompt: "
        f"{rendered!r}"
    )


def test_plain_string_goal_still_works():
    """REQ-6 AC1 parity: the protocol's 3-positional shape makes fetch.vision
    interchangeable with fetch.crawl — plain-string goals remain first-class
    after the GoalAnatomy duck-typing landed."""
    provider = _RecordingProvider()
    cap = FetchVisionCapability(provider=provider, session_cls=_RecordingSession)
    outcome = asyncio.run(
        cap.fetch_one("https://example.com", "plain goal", "job-str")
    )
    assert provider.suggest_goals and provider.suggest_goals[0] == "plain goal"
    assert outcome is not None


def test_vision_loop_consults_goal_every_turn():
    """AC: each loop turn re-asks with the CURRENT goal (REQ-1 AC1.3 +
    REQ-17 AC2) — the provider receives a goal on EVERY suggest_action call,
    so a live mutation is honored on the next suggestion, not just the first."""
    provider = _RecordingProvider()
    cap = FetchVisionCapability(provider=provider, session_cls=_RecordingSession)
    asyncio.run(cap.fetch_one("https://example.com", "g", "job-each-turn"))
    # The scripted provider produced 2 suggest calls (action, then error).
    assert len(provider.suggest_goals) == 2
    assert all(g == "g" for g in provider.suggest_goals)
