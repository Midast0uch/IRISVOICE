"""Behavioral tests for the vision loop quality (REQ-3, REQ-4, REQ-9; T5/T6/T7).

Drive the FULL ``FetchVisionCapability.fetch_one`` loop with a fake session and
provider -- no browser, no network, no live model. Assert EMERGENT properties:

  - REQ-3: the trajectory window reaches the provider's prompt on the NEXT call.
  - REQ-4: a productive multi-scroll session is NOT stopped by a kind-repeat
    heuristic (the TG-2 gate), while a genuinely stalled page IS stopped.
  - REQ-9: the frame for one settled state is observed once, and a changed
    frame always gets a fresh observation.
"""

from __future__ import annotations

import asyncio

from backend.vision.fetch_vision import (
    NO_PROGRESS_LIMIT,
    FetchVisionCapability,
)


class _FakeSession:
    """In-memory session whose screenshot CHANGES when the page scrolls.

    ``frames`` is a list of distinct byte strings; each scroll advances the
    index, so a scroll produces a measurable visual delta. A non-scroll action
    leaves the frame unchanged (a no-progress action).
    """

    def __init__(self, job_id, url, goal, bounds=None, page_offset=0):
        self.job_id = job_id
        self.url = url
        self.goal = goal
        self.acts: list = []
        self.closed = False
        self.screenshot_calls = 0
        self._frames = [bytes([i]) * 32 for i in range(1, 40)]
        self._idx = 0

    async def open(self):
        pass

    def available(self):
        return True

    async def detect_wall(self):
        return None

    async def screenshot(self):
        self.screenshot_calls += 1
        return self._frames[self._idx]

    async def act(self, action):
        self.acts.append(action)
        if action.kind == "scroll":
            self._idx = min(self._idx + 1, len(self._frames) - 1)

    async def settle(self):
        return "<html><body>" + ("content " * 40) + "</body></html>"

    async def close(self):
        self.closed = True

    async def request_takeover(self, wall, **kwargs):
        return False


class _TrajectoryRecordingProvider:
    """Provider that records the `trajectory=` text it receives (T5)."""

    def __init__(self, actions):
        self._actions = list(actions)
        self.trajectories: list = []

    def suggest_action(self, img_bytes, goal, trajectory=None):
        self.trajectories.append(trajectory)
        if self._actions:
            return self._actions.pop(0)
        return {"action": "error", "target": "", "reasoning": "done"}

    def read_text(self, img_bytes):
        return ""

    def analyze_screen(self, img_bytes, question=""):
        return ""

    def describe_live_frame(self, img_bytes):
        return "no new content"


def test_long_scroll_session_is_not_stopped_by_kind_repeat():
    """REQ-4 AC2/AC3 (TG-2 gate): a scroll-dominated session that CHANGES the
    page each step must run to its bound, NOT be stopped by a repeated action
    kind. The old '3 identical kinds = stuck' heuristic stopped exactly this."""
    sess = _FakeSession("j-long", "https://a.example/", "read the long article")
    # 12 scrolls, each changing the page, then stop.
    provider = _TrajectoryRecordingProvider(
        [{"action": "scroll", "target": "", "reasoning": "more"}] * 12
        + [{"action": "error", "target": "", "reasoning": "done"}]
    )
    cap = FetchVisionCapability(provider=provider, session_cls=lambda *a, **k: sess)

    asyncio.run(cap.fetch_one("https://a.example/", "read", "j-long"))

    # A productive multi-scroll session performed many scrolls -- far more than
    # the old heuristic's 3-kind cutoff.
    scrolls = [a for a in sess.acts if a.kind == "scroll"]
    assert len(scrolls) > 3, (
        f"a changing scroll session was stopped early after {len(scrolls)} "
        "scrolls -- the repeat-kind heuristic regressed (REQ-4 AC2/AC3)"
    )


def test_genuinely_stalled_page_is_stopped():
    """REQ-4 AC2: a page that does NOT change is stopped within the bound --
    measured no-progress, not a kind-repeat guess."""
    class _StalledSession(_FakeSession):
        async def act(self, action):
            self.acts.append(action)
            # A scroll that does NOT move the page: frame never changes.

    sess = _StalledSession("j-stall", "https://a.example/", "read")
    provider = _TrajectoryRecordingProvider(
        [{"action": "scroll", "target": "", "reasoning": "more"}] * 20
    )
    cap = FetchVisionCapability(provider=provider, session_cls=lambda *a, **k: sess)

    asyncio.run(cap.fetch_one("https://a.example/", "read", "j-stall"))

    # Stopped by measured no-progress, not by exhausting the 20-action script.
    assert len(sess.acts) <= NO_PROGRESS_LIMIT + 1, (
        f"a stalled page ran {len(sess.acts)} actions -- no-progress termination "
        "did not fire (REQ-4 AC2)"
    )


def test_trajectory_window_reaches_the_provider_prompt():
    """REQ-3 AC1/AC2: the recent action window is fed into the provider on the
    NEXT suggestion call (the data was recorded but never wired before T5)."""
    sess = _FakeSession("j-traj", "https://a.example/", "read")
    provider = _TrajectoryRecordingProvider([
        {"action": "scroll", "target": "", "reasoning": "a"},
        {"action": "scroll", "target": "", "reasoning": "b"},
        {"action": "error", "target": "", "reasoning": "done"},
    ])
    cap = FetchVisionCapability(provider=provider, session_cls=lambda *a, **k: sess)

    asyncio.run(cap.fetch_one("https://a.example/", "read", "j-traj"))

    # First call: empty window (baseline). Later calls: the window text.
    assert provider.trajectories[0] in (None, "")
    later = [t for t in provider.trajectories[1:] if t]
    assert later, "the action trajectory never reached the provider prompt (REQ-3)"
    assert "scroll" in later[0]


def test_first_action_sends_un_augmented_baseline():
    """REQ-3 edge: the first action has an EMPTY window, so the provider is
    called with no trajectory text (baseline prompt)."""
    sess = _FakeSession("j-first", "https://a.example/", "read")
    provider = _TrajectoryRecordingProvider([
        {"action": "error", "target": "", "reasoning": "done"},
    ])
    cap = FetchVisionCapability(provider=provider, session_cls=lambda *a, **k: sess)

    asyncio.run(cap.fetch_one("https://a.example/", "read", "j-first"))
    assert provider.trajectories[0] in (None, "")


def test_one_observation_per_settled_state():
    """REQ-9 AC3: for an UNCHANGED page, the suggestion reuses the cached frame
    rather than taking a fresh screenshot per decision."""
    sess = _FakeSession("j-once", "https://a.example/", "read")
    # Several no-op actions (wait) that do NOT change the frame, then stop.
    provider = _TrajectoryRecordingProvider([
        {"action": "wait", "target": "", "reasoning": "a"},
        {"action": "wait", "target": "", "reasoning": "b"},
        {"action": "error", "target": "", "reasoning": "done"},
    ])
    cap = FetchVisionCapability(provider=provider, session_cls=lambda *a, **k: sess)

    asyncio.run(cap.fetch_one("https://a.example/", "read", "j-once"))

    # REQ-9 AC3: the settled frame is captured ONCE and reused across decisions
    # for an unchanged page, so captures are NOT one-per-decision. Without the
    # cache, every decision would take its own screenshot.
    decisions = len(provider.trajectories)
    actions = len(sess.acts)
    assert sess.screenshot_calls < decisions + actions, (
        f"{sess.screenshot_calls} screenshots for {decisions} decisions / "
        f"{actions} actions -- REQ-9 AC3 one-observation-per-state regressed "
        "(the frame is no longer reused across an unchanged settled state)"
    )

