"""Contract tests for the CDP takeover transport (REQ-13..REQ-16; T19).

Hermetic: a fake CDP session stands in for Playwright's CDP connection -- no
browser, no network. Pins:

  - REQ-16 AC1: the frame envelope shape + monotonic frame_seq.
  - REQ-16 AC3: bounded delivery (at most one in flight; latest-wins drop +
    dropped counter).
  - REQ-16 edge: a frame with no open grant is dropped (unattributable).
  - REQ-14 AC1: input is rejected outside an open grant and COUNTED.
  - REQ-14 AC3: only page-level input kinds are representable.
  - REQ-14 AC4: a typed value is forwarded, never logged.
  - REQ-14 AC5/AC6: a credential is applied with a value-free audit record.
  - REQ-15 AC5: consent is required and revocable.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from backend.vision import cdp_takeover as cdp


class _FakeCDP:
    """Records every CDP command sent; lets a test fire screencast frames."""

    def __init__(self):
        self.sent: list = []
        self._handlers: dict = {}

    def on(self, event: str, handler) -> None:
        self._handlers[event] = handler

    async def send(self, method: str, params: dict) -> None:
        self.sent.append((method, params))

    async def detach(self) -> None:
        self.sent.append(("detach", {}))

    def fire_frame(self, data: str, session_id: int = 1) -> None:
        self._handlers["Page.screencastFrame"]({
            "data": data, "sessionId": session_id,
            "metadata": {"deviceWidth": 1280, "deviceHeight": 720},
        })

    def methods(self) -> list:
        return [m for m, _ in self.sent]


@pytest.fixture(autouse=True)
def _clean_registry():
    cdp.clear_registry()
    yield
    cdp.clear_registry()


def _manager(frames: list | None = None):
    cdp_sess = _FakeCDP()
    sink = (frames.append if frames is not None else (lambda _e: None))
    mgr = cdp.TakeoverManager(
        run_id="run-1", cdp_factory=lambda _p: cdp_sess, frame_sink=sink,
    )
    return mgr, cdp_sess


def test_start_screencast_sends_start_and_stops_cleanly():
    mgr, cdp_sess = _manager()
    mgr.open_grant(question_id="q1", wall_kind="captcha")
    ok = asyncio.run(mgr.start_screencast(object()))
    assert ok is True
    assert "Page.startScreencast" in cdp_sess.methods()
    asyncio.run(mgr.stop_screencast())
    assert "Page.stopScreencast" in cdp_sess.methods()
    assert "detach" in cdp_sess.methods()


def test_frame_envelope_shape_and_monotonic_frame_seq():
    frames: list = []
    mgr, cdp_sess = _manager(frames)
    mgr.open_grant(question_id="q1", wall_kind="login")
    asyncio.run(mgr.start_screencast(object()))

    cdp_sess.fire_frame("AAAA")
    cdp_sess.fire_frame("BBBB")

    assert len(frames) >= 1
    f0 = frames[0]
    for key in ("run_id", "question_id", "seq", "frame_seq", "ts",
                "viewport_w", "viewport_h", "format", "bytes"):
        assert key in f0, f"frame envelope missing {key} (REQ-16 AC1)"
    assert f0["question_id"] == "q1"
    assert f0["viewport_w"] == 1280 and f0["viewport_h"] == 720
    # frame_seq is monotonic across delivered frames.
    seqs = [f["frame_seq"] for f in frames]
    assert seqs == sorted(seqs)


def test_frame_dropped_when_no_open_grant():
    """REQ-16 edge: a frame without an owner is dropped, not delivered."""
    frames: list = []
    mgr, cdp_sess = _manager(frames)
    # No grant opened.
    asyncio.run(mgr.start_screencast(object()))
    cdp_sess.fire_frame("AAAA")
    assert frames == [], "a frame with no open grant was delivered (REQ-16 edge)"


def test_bounded_delivery_latest_wins_with_dropped_counter():
    """REQ-16 AC3: at most one frame in flight; a new frame while unacked is
    dropped latest-wins and counted."""
    frames: list = []
    mgr, cdp_sess = _manager(frames)
    mgr.open_grant(question_id="q1", wall_kind="captcha")
    asyncio.run(mgr.start_screencast(object()))

    cdp_sess.fire_frame("AAAA")   # delivered (in flight, unacked)
    cdp_sess.fire_frame("BBBB")   # pending (latest-wins)
    cdp_sess.fire_frame("CCCC")   # replaces pending -> one drop counted
    assert len(frames) == 1, "more than one frame was in flight (REQ-16 AC3)"
    assert mgr.stats.dropped >= 1

    # Ack releases the slot and flushes the latest pending (CCCC).
    mgr.ack_frame()
    assert len(frames) == 2
    assert frames[-1]["bytes"] == "CCCC"


def test_input_rejected_without_open_grant_and_counted():
    """REQ-14 AC1: input outside an open grant is rejected + counted."""
    mgr, _ = _manager()
    forwarded = asyncio.run(
        mgr.deliver_input(cdp.TakeoverInput(kind="pointer", x=0.1, y=0.2))
    )
    assert forwarded is False
    assert mgr.rejected_inputs == 1


def test_only_page_level_input_kinds_are_representable():
    """REQ-14 AC3: a browser-level / navigation command is rejected."""
    mgr, _ = _manager()
    mgr.open_grant(question_id="q1", wall_kind="captcha")
    forwarded = asyncio.run(
        mgr.deliver_input(cdp.TakeoverInput(kind="navigate", text="/etc"))
    )
    assert forwarded is False
    assert mgr.rejected_inputs == 1


def test_page_level_input_is_forwarded_when_grant_open():
    mgr, cdp_sess = _manager()
    mgr.open_grant(question_id="q1", wall_kind="captcha")
    asyncio.run(mgr.start_screencast(object()))
    ok = asyncio.run(mgr.deliver_input(cdp.TakeoverInput(kind="pointer", x=0.5, y=0.5)))
    assert ok is True
    assert "Input.dispatchMouseEvent" in cdp_sess.methods()


def test_typed_value_is_never_logged(caplog):
    """REQ-14 AC4: a typed value is forwarded, never written to a log."""
    mgr, cdp_sess = _manager()
    mgr.open_grant(question_id="q1", wall_kind="login")
    asyncio.run(mgr.start_screencast(object()))
    with caplog.at_level(logging.DEBUG):
        asyncio.run(mgr.deliver_input(cdp.TakeoverInput(kind="text", text="s3cr3t-value")))
    assert "s3cr3t-value" not in caplog.text, (
        "a typed value leaked into a log line (REQ-14 AC4)"
    )
    assert "Input.insertText" in cdp_sess.methods()


def test_credential_record_is_value_free(caplog):
    """REQ-14 AC5/AC6: the audit record holds a reference, never the value."""
    mgr, _ = _manager()
    mgr.open_grant(question_id="q1", wall_kind="login")
    with caplog.at_level(logging.DEBUG):
        rec = mgr.apply_credential(
            secret_ref="keyring://host/user", field_handle="#password",
            value="hunter2",
        )
    assert rec.secret_ref == "keyring://host/user"
    assert rec.outcome == "applied"
    assert "hunter2" not in caplog.text, "the secret value leaked into a log (REQ-14 AC5)"
    assert "hunter2" not in repr(mgr.credential_records)


def test_consent_is_required_and_revocable():
    """REQ-15 AC5: nothing is persisted without consent; consent is revocable."""
    mgr, _ = _manager()
    assert mgr.has_consent("example.com") is False
    mgr.grant_consent("example.com")
    assert mgr.has_consent("example.com") is True
    mgr.revoke_consent("example.com")
    assert mgr.has_consent("example.com") is False


def test_second_open_reuses_the_live_grant():
    """REQ-13 edge: never two live screencasts on one page -- a second open
    reuses the open grant."""
    mgr, _ = _manager()
    g1 = mgr.open_grant(question_id="q1", wall_kind="captcha")
    g2 = mgr.open_grant(question_id="q2", wall_kind="login")
    assert g1.grant_id == g2.grant_id



# ── T23: credential used-not-seen (REQ-14 AC5/AC6) ──────────────────────────

def test_keyring_credential_declined_is_recorded_value_free(monkeypatch):
    """REQ-14 AC6: no authorisation -> no application; the record is value-free."""
    mgr, _ = _manager()
    mgr.open_grant(question_id="q1", wall_kind="login")
    rec = asyncio.run(mgr.apply_keyring_credential(
        host="bank.example", provider_id="bank.example", field_handle="#pw",
        authorized=False,
    ))
    assert rec.outcome == "declined"
    assert "keyring:" in rec.secret_ref


def test_keyring_credential_no_entry_degrades_to_manual(monkeypatch):
    """REQ-14 edge: a host with no keyring entry degrades to the manual
    takeover -- never a guessed credential."""
    import backend.agent.inference.keyring as kr

    monkeypatch.setattr(kr, "get_secret", lambda _pid: None)
    mgr, _ = _manager()
    mgr.open_grant(question_id="q1", wall_kind="login")
    rec = asyncio.run(mgr.apply_keyring_credential(
        host="bank.example", provider_id="bank.example", field_handle="#pw",
        authorized=True,
    ))
    assert rec.outcome == "no_secret"


def test_keyring_credential_applied_never_logs_value(monkeypatch, caplog):
    """REQ-14 AC5: the value is USED (typed into the field) but never logged,
    never stored on the record."""
    import backend.agent.inference.keyring as kr

    monkeypatch.setattr(kr, "get_secret", lambda _pid: "TOP-SECRET-9x")
    mgr, cdp_sess = _manager()
    mgr.open_grant(question_id="q1", wall_kind="login")
    asyncio.run(mgr.start_screencast(object()))
    with caplog.at_level(logging.DEBUG):
        rec = asyncio.run(mgr.apply_keyring_credential(
            host="bank.example", provider_id="bank.example", field_handle="#pw",
            authorized=True,
        ))
    assert rec.outcome == "applied"
    assert "TOP-SECRET-9x" not in caplog.text, "the secret leaked into a log (REQ-14 AC5)"
    assert "TOP-SECRET-9x" not in repr(mgr.credential_records)
    # It WAS used: a CDP Runtime.evaluate typed it into the field.
    assert "Runtime.evaluate" in cdp_sess.methods()


# ── T24: post-takeover continuation (REQ-15 AC5/AC6) ────────────────────────

def test_consent_prompt_names_host_and_is_revocable():
    """REQ-15 AC5: the affordance names the host + what will be stored."""
    mgr, _ = _manager()
    prompt = mgr.consent_prompt("shop.example")
    assert "shop.example" in prompt["message"]
    assert "session cookies" in prompt["message"]
    assert prompt["revocable"] is True


def test_off_domain_does_not_auto_park_when_allowed():
    """REQ-15 AC6: a domain change must NOT auto-park; continue if not blocked."""
    mgr, _ = _manager()
    decision = mgr.evaluate_continuation(
        target_host="target.example", current_host="other.example",
        guardrails_block=False,
    )
    assert decision["action"] == "continue"
    assert decision["reason"] == "off_domain_allowed"


def test_off_domain_guardrail_block_asks_not_parks():
    """REQ-15 AC6: when a guardrail would block off-domain, ASK the user rather
    than silently parking or silently proceeding."""
    mgr, _ = _manager()
    decision = mgr.evaluate_continuation(
        target_host="target.example", current_host="other.example",
        guardrails_block=True,
    )
    assert decision["action"] == "ask"
    assert decision["options"]
    assert "other.example" in decision["question"]

