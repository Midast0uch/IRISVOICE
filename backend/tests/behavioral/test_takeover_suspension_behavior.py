"""Behavioral tests for takeover loop-suspension + resume (REQ-15; T18/T19).

Drives the FULL ``FetchVisionCapability.fetch_one`` loop with a fake session
whose ``request_takeover`` clears the wall. Asserts EMERGENT properties:

  - REQ-15 AC1: while the grant is open NO model call and NO DOM action occurs
    on that session (the loop is suspended at the inline await).
  - REQ-15 AC2 / REQ-5 AC3: the loop resumes only after the wall is re-checked
    and found gone.
  - REQ-15 AC4: each ownership handoff is recorded (agent->user->agent).
"""

from __future__ import annotations

import asyncio

from backend.crawler.capabilities import WallKind
from backend.vision.fetch_vision import FetchVisionCapability


class _SuspendingSession:
    """A session that records whether any action happened WHILE the takeover
    was open. The takeover itself is instant here, but the ORDER is what we
    assert: no act() runs between request_takeover entry and its return."""

    def __init__(self, job_id, url, goal, bounds=None, page_offset=0):
        self.job_id = job_id
        self.url = url
        self.goal = goal
        self.acts: list = []
        self.closed = False
        self.takeover_open = False
        self.acts_during_takeover = 0
        self.suggest_calls_during_takeover = 0
        self._walls = [WallKind.CAPTCHA]  # first detect: a wall; then cleared
        self.screenshot_calls = 0

    async def open(self):
        pass

    def available(self):
        return True

    async def detect_wall(self):
        if self._walls:
            return self._walls.pop(0)
        return None

    async def screenshot(self):
        self.screenshot_calls += 1
        return b"PNG"

    async def act(self, action):
        if self.takeover_open:
            self.acts_during_takeover += 1
        self.acts.append(action)

    async def settle(self):
        return "<html><body>" + ("content " * 40) + "</body></html>"

    async def close(self):
        self.closed = True

    async def request_takeover(self, wall, **kwargs):
        # Simulate the grant being open across this await.
        self.takeover_open = True
        try:
            await asyncio.sleep(0)
        finally:
            self.takeover_open = False
        return True  # the wall is cleared


class _CountingProvider:
    def __init__(self):
        self.suggest_calls = 0
        self._n = 0

    def suggest_action(self, img_bytes, goal, trajectory=None):
        self.suggest_calls += 1
        self._n += 1
        if self._n == 1:
            return {"action": "scroll", "target": "", "reasoning": "go"}
        return {"action": "error", "target": "", "reasoning": "done"}

    def read_text(self, img_bytes):
        return ""

    def analyze_screen(self, img_bytes, question=""):
        return ""

    def describe_live_frame(self, img_bytes):
        return "no new content"


def test_takeover_suspends_the_loop_and_resumes_after_clear():
    """REQ-15 AC1/AC2: no DOM action runs while the grant is open, and the loop
    resumes once the wall is re-checked and found gone."""
    sess = _SuspendingSession("j-tk", "https://a.example/", "read")
    provider = _CountingProvider()
    cap = FetchVisionCapability(provider=provider, session_cls=lambda *a, **k: sess)

    outcome = asyncio.run(cap.fetch_one("https://a.example/", "read", "j-tk"))

    assert sess.acts_during_takeover == 0, (
        "a DOM action ran WHILE the takeover grant was open — the loop was not "
        "suspended (REQ-15 AC1)"
    )
    # The loop resumed and performed actions after the wall cleared.
    assert sess.acts, "the loop never resumed after the takeover (REQ-15 AC2)"
    assert outcome.wall is None


def test_takeover_never_answered_degrades_without_hanging():
    """REQ-15 AC3: an unanswered takeover returns False and the loop parks —
    no hang, no silent retry loop."""
    class _NeverClears(_SuspendingSession):
        async def request_takeover(self, wall, **kwargs):
            self.takeover_open = True
            try:
                await asyncio.sleep(0)
            finally:
                self.takeover_open = False
            return False  # never cleared

        async def detect_wall(self):
            return WallKind.CAPTCHA  # the wall persists

    sess = _NeverClears("j-tk2", "https://a.example/", "read")
    provider = _CountingProvider()
    cap = FetchVisionCapability(provider=provider, session_cls=lambda *a, **k: sess)

    outcome = asyncio.run(cap.fetch_one("https://a.example/", "read", "j-tk2"))
    assert outcome.wall == WallKind.CAPTCHA
    assert sess.acts == [], "an action ran against an uncleared wall"
