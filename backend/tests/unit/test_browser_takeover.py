"""T11 (REQ-10): Contextual Human-in-the-Loop Browser Takeover.

Pins:
- Question carries kind="browser_takeover" + takeover_url + reason (design
  §3 Data Model — additive; a plain question keeps kind="choice" and None
  takeover fields).
- QUESTION_ASK payload carries the takeover fields so the frontend card can
  render the unlock + "I've Completed It" affordance (AC10.2).
- A dedicated event fires with takeover_url/job_id/reason/question_id so
  the panel's pointer-events unlock subscribes to IT, not the generic
  question channel (AC10.1, design §3 lifecycle step 4).
- Guidance text is generated from page context: explicit site_name wins,
  else the URL's hostname; never a bare string (AC10.1 "contextual
  guidance", lifecycle step 2).
- "I've Completed It" resolves as answer="completed" through the SAME
  single funnel; kind survives resolution (AC10.2/AC10.3).
- Timeout is an ordinary outcome, never a raise — the run must not die
  because the user walked away (Non-goal hard rule).
"""
from __future__ import annotations

from backend.agent.event_bus import EventBus, IRISStreamEvent
from backend.agent.tools.ask_user_tool import AskUserTool


def _tool_with_spy() -> tuple[AskUserTool, list[tuple[str, dict]]]:
    """A real tool on a FRESH bus (never the singleton) with all emissions
    recorded. Async handlers are irrelevant here — the tool emits to the
    ring buffer and to sync subscribers, so a sync listener sees every
    event in order."""
    bus = EventBus()
    events: list[tuple[str, dict]] = []

    bus.subscribe(
        IRISStreamEvent.QUESTION_ASK,
        lambda p: events.append(("question:ask", dict(p.data or {}))),
    )
    bus.subscribe(
        IRISStreamEvent.BROWSER_TAKEOVER_REQUESTED,
        lambda p: events.append(("browser:takeover_requested", dict(p.data or {}))),
    )
    return AskUserTool(event_bus=bus), events


class TestBrowserTakeover:
    def test_question_carries_takeover_fields(self):
        """Design §3 Data Model: kind/takeover_url/reason live on Question;
        plain questions default to kind=choice with no takeover fields."""
        tool, _ = _tool_with_spy()
        q = tool.ask_browser_takeover(
            takeover_url="https://store.example/checkout",
            reason="cloudflare_turnstile",
        )
        assert q.kind == "browser_takeover"
        assert q.takeover_url == "https://store.example/checkout"
        assert q.reason == "cloudflare_turnstile"

        q2 = tool.ask(text="pick one?", options=["a", "b"])
        assert q2.kind == "choice"
        assert q2.takeover_url is None
        assert q2.reason is None

    def test_question_ask_payload_carries_takeover_fields(self):
        tool, events = _tool_with_spy()
        tool.ask_browser_takeover(
            takeover_url="https://bank.example/2fa",
            reason="two_factor",
        )
        ask_events = [d for t, d in events if t == "question:ask"]
        assert ask_events, "QUESTION_ASK was never emitted"
        payload = ask_events[-1]
        assert payload["kind"] == "browser_takeover"
        assert payload["takeover_url"] == "https://bank.example/2fa"
        assert payload["reason"] == "two_factor"
        assert payload["question_id"]

    def test_dedicated_event_fires_for_panel_unlock(self):
        tool, events = _tool_with_spy()
        q = tool.ask_browser_takeover(
            takeover_url="https://bank.example/2fa",
            reason="two_factor",
            job_id="job-t1",
        )
        takeover_events = [d for t, d in events if t == "browser:takeover_requested"]
        assert takeover_events, (
            "no takeover event — the panel's pointer-events unlock has "
            "nothing to subscribe to"
        )
        payload = takeover_events[-1]
        assert payload == {
            "takeover_url": "https://bank.example/2fa",
            "reason": "two_factor",
            "job_id": "job-t1",
            "question_id": q.question_id,
        }

    def test_guidance_text_uses_page_context(self):
        """AC10.1: the message names what the user must do and where, not a
        generic 'please help'."""
        tool, _ = _tool_with_spy()
        q = tool.ask_browser_takeover(
            takeover_url="https://cloud.example/console",
            reason="captcha",
            site_name="Cloud Console",
        )
        assert "Cloud Console" in q.text
        assert "solve" in q.text.lower() or "complete" in q.text.lower()
        assert "browser" in q.text.lower()  # names the surface (the panel)

        q2 = tool.ask_browser_takeover(
            takeover_url="https://mail.example/inbox",
            reason="login_wall",
        )
        assert "mail.example" in q2.text or "mail" in q2.text.lower()

    def test_completed_answer_routes_through_same_funnel(self):
        """AC10.2→AC10.3: the card's primary action resolves as
        answer='completed'; the kind field survives resolution."""
        tool, _ = _tool_with_spy()
        q = tool.ask_browser_takeover(
            takeover_url="https://store.example/checkout",
            reason="cloudflare_turnstile",
        )
        resolved = tool.resolve_answer(q.question_id, "completed")
        assert resolved is not None
        assert resolved.answer == "completed"
        assert resolved.kind == "browser_takeover"

    def test_timeout_is_a_terminal_outcome_not_a_crash(self):
        tool, events = _tool_with_spy()
        q = tool.ask_browser_takeover(
            takeover_url="https://store.example/checkout",
            reason="captcha",
            timeout_seconds=0.2,
        )
        # filler_interval>timeout so no filler path runs; the wait returns
        # after the timeout with a terminal status.
        final = tool.wait_for_answer(q, poll_interval=0.01, filler_interval=10.0)
        assert final.status == "timed_out"
        timeouts = [d for t, d in events if t == "question:timeout"]
        assert not timeouts or timeouts[-1]["question_id"] == q.question_id
