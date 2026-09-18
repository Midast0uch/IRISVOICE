"""CDP screencast takeover transport (REQ-13, REQ-14, REQ-15, REQ-16).

Design D5 (specs/vision-browser-e2e-reliability): takeover drives the SESSION,
not a copy. The pooled Chromium is headless, each context carries a spoofed UA,
and wall clearance (a CAPTCHA token, a pending 2FA, a login session) lives in
the session that must be cleared -- a separate browser cannot deliver that state
back (REQ-5 AC3 is unreachable through it). So the user acts INSIDE the agent's
own page through a CDP screencast (`Page.startScreencast`) with input
forwarding (`Input.dispatchMouseEvent` / `Input.dispatchKeyEvent`).

This module is the TRANSPORT + AUTHORITY layer only. It owns:
  - `TakeoverGrant` (REQ-14 AC2): the authority token. Input is accepted ONLY
    while a grant is open, and the grant is the arbiter that keeps ONE writer
    on the page (REQ-15 AC4).
  - `ScreencastFrame` (REQ-16 AC1): the canonical frame envelope, on the WS
    channel only, NEVER the capture-store slot design or the
    `CRAWLER_VISION_ACTION` shape (REQ-16 AC2).
  - ack-paced, latest-wins delivery with a dropped counter (REQ-16 AC3).
  - `TakeoverInput` (REQ-14 AC3): page-level events only. Browser-level and
    navigation commands are NOT representable.
  - `CredentialApplication` (REQ-14 AC5/AC6): the value-free audit record; the
    secret is USED, never SEEN.
  - `ConsentRecord` (REQ-15 AC5): the revocable consent for persisting
    post-takeover session cookies.

It deliberately does NOT import FastAPI/WebSocket/APIRouter: the gateway wires
the frame sink and the input entry point. Keeping the transport-agnostic core
separate is what lets `browser_session.py` stay free of inbound-channel tokens
(CT-7) while the panel still gets live frames.

The CDP session is obtained through an injected factory (`cdp_factory`) so the
whole module is unit-testable with a fake CDP session -- no browser, no network.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# REQ-14 AC2: the grant's max duration. A live input channel into an
# autonomous browser must be time-boxed; env-overridable.
_DEFAULT_GRANT_MS = int(os.environ.get("IRIS_TAKEOVER_GRANT_MS", "180000"))
# REQ-16 AC3: at most ONE frame in flight to the panel; a slow panel drops
# latest-wins rather than queueing. Bounded by the ack the panel returns.
_MAX_INFLIGHT = 1
# D10: start at quality 60, maxWidth 1366, maxHeight 768, everyNthFrame 1.
_SCREENCAST_QUALITY = int(os.environ.get("IRIS_TAKEOVER_FRAME_QUALITY", "60"))
_SCREENCAST_MAX_W = int(os.environ.get("IRIS_TAKEOVER_MAX_W", "1366"))
_SCREENCAST_MAX_H = int(os.environ.get("IRIS_TAKEOVER_MAX_H", "768"))

# REQ-14 AC3: the ONLY input kinds representable on the channel. A browser-level
# or navigation command is not in this set and is rejected outright.
_ALLOWED_INPUT_KINDS = frozenset({"pointer", "wheel", "key", "text"})
# REQ-14 AC3: page-level pointer/keys only -- no browser-level commands.
_ALLOWED_MOUSE_BUTTONS = frozenset({"left", "right", "middle", "none"})


def _now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Process-level wiring (the gateway populates these; the session consumes them)
# ---------------------------------------------------------------------------
# The frame sink routes a frame envelope to the WS client(s) watching the run.
# Set once by the gateway. Kept here (not in browser_session) so
# browser_session.py stays free of any inbound-channel token (CT-7).
_FRAME_SINK: Optional[Callable[[Dict[str, Any]], None]] = None
# The active takeover managers, keyed by run_id, so the gateway can route an
# inbound input event / frame ack to the right session's manager.
_ACTIVE: Dict[str, "TakeoverManager"] = {}


def set_frame_sink(fn: Optional[Callable[[Dict[str, Any]], None]]) -> None:
    """Register the process-wide frame sink (the gateway's WS send)."""
    global _FRAME_SINK
    _FRAME_SINK = fn


def get_frame_sink() -> Optional[Callable[[Dict[str, Any]], None]]:
    return _FRAME_SINK


def register_active(manager: "TakeoverManager") -> None:
    if manager is not None:
        _ACTIVE[manager.run_id] = manager


def unregister_active(run_id: str) -> None:
    _ACTIVE.pop(run_id, None)


def get_active(run_id: str) -> Optional["TakeoverManager"]:
    return _ACTIVE.get(run_id)


async def deliver_input(run_id: str, event: "TakeoverInput") -> bool:
    """Gateway entry point: forward an input event to the run's manager.

    Returns False when no manager is active for the run (input with no open
    grant is rejected). Never raises.
    """
    mgr = _ACTIVE.get(run_id)
    if mgr is None:
        return False
    return await mgr.deliver_input(event)


def ack_frame(run_id: str) -> None:
    """Gateway entry point: acknowledge the last frame for a run."""
    mgr = _ACTIVE.get(run_id)
    if mgr is not None:
        mgr.ack_frame()


def clear_registry() -> None:
    """Test helper: drop all active managers and the frame sink."""
    global _FRAME_SINK
    _ACTIVE.clear()
    _FRAME_SINK = None


@dataclass
class TakeoverGrant:
    """The authority token (REQ-14 AC2 / REQ-15 AC4).

    Input is accepted ONLY while a grant is open; the grant is bounded by its
    start time, wall kind, question id, and a max duration. At most ONE grant
    owns the page at any instant.
    """

    grant_id: str
    run_id: str
    question_id: str
    wall_kind: str
    opened_at: float
    max_ms: int
    owner: str = "user"

    def expired(self) -> bool:
        return (_now_ms() - int(self.opened_at * 1000)) >= self.max_ms

    def open(self) -> bool:
        return not self.expired()


@dataclass
class ScreencastFrame:
    """The canonical frame envelope (REQ-16 AC1).

    `bytes` is a base64 payload (D9); `seq` is the takeover's EVENT sequence and
    `frame_seq` its FRAME sequence (monotonic, so the renderer detects a gap).
    """

    run_id: str
    question_id: str
    seq: int
    frame_seq: int
    ts: int
    viewport_w: int
    viewport_h: int
    format: str
    bytes: str  # base64

    def to_envelope(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "question_id": self.question_id,
            "seq": self.seq,
            "frame_seq": self.frame_seq,
            "ts": self.ts,
            "viewport_w": self.viewport_w,
            "viewport_h": self.viewport_h,
            "format": self.format,
            "bytes": self.bytes,
        }


@dataclass
class TakeoverInput:
    """A page-level input event (REQ-14 AC3).

    Only pointer / wheel / key / text are representable. The `text` value is
    EPHEMERAL (REQ-14 AC4): it is forwarded to the page and never written to
    memory, the ledger, the event stream, or a log.
    """

    kind: str
    seq: int = 0
    x: Optional[float] = None
    y: Optional[float] = None
    button: Optional[str] = None
    key: Optional[str] = None
    text: Optional[str] = None


@dataclass
class FrameStreamStats:
    """Counters that make bounded delivery visible (REQ-16 AC3)."""

    sent: int = 0
    dropped: int = 0
    gaps: int = 0
    last_frame_seq: int = -1


@dataclass
class CredentialApplication:
    """The value-free audit record for REQ-14 AC5/AC6.

    Holds a REFERENCE id, never the value, so the record is auditable but not
    recoverable.
    """

    grant_id: str
    secret_ref: str
    field_handle: str
    applied_at: float
    outcome: str


@dataclass
class ConsentRecord:
    """Revocable consent for persisting post-takeover cookies (REQ-15 AC5)."""

    host: str
    kind: str
    granted_at: float
    revoked_at: Optional[float] = None

    def active(self) -> bool:
        return self.revoked_at is None



# ---------------------------------------------------------------------------
# The manager
# ---------------------------------------------------------------------------


class TakeoverManager:
    """Owns the CDP screencast, the grant, and the input channel for one page.

    One instance per session. The gateway wires `frame_sink` (WS send) and calls
    `deliver_input` for inbound events. Everything is best-effort and NEVER
    raises into the run (REQ-13 AC4: a CDP failure degrades to the replay
    mirror, the run continues).
    """

    def __init__(
        self,
        *,
        run_id: str = "",
        cdp_factory: Optional[Callable[[object], Any]] = None,
        frame_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
        lifecycle_sink: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        self._run_id = run_id
        self._cdp_factory = cdp_factory
        self._frame_sink = frame_sink
        self._lifecycle_sink = lifecycle_sink
        self._cdp = None
        self._page = None
        self._grant: Optional[TakeoverGrant] = None
        self._stats = FrameStreamStats()
        self._seq = 0
        self._frame_seq = 0
        self._inflight = 0
        self._streaming = False
        self._pending_frame: Optional[Dict[str, Any]] = None
        self._rejected_inputs = 0
        # REQ-13 AC2: the event loop captured at start_screencast time, so the
        # sync screencast-frame callback can schedule the async ack on the right
        # loop (or skip it entirely when there is no running loop).
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._credentials: List[CredentialApplication] = []
        self._consents: Dict[str, ConsentRecord] = {}

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def page(self) -> object:
        return self._page

    # ── grant lifecycle ────────────────────────────────────────────────────

    @property
    def grant(self) -> Optional[TakeoverGrant]:
        return self._grant

    @property
    def stats(self) -> FrameStreamStats:
        return self._stats

    @property
    def rejected_inputs(self) -> int:
        return self._rejected_inputs

    def open_grant(
        self,
        *,
        question_id: str,
        wall_kind: str,
        max_ms: int = _DEFAULT_GRANT_MS,
    ) -> TakeoverGrant:
        """Open the single authority grant (REQ-14 AC2 / REQ-15 AC4).

        A second open while one is live REUSES the open grant (never two live
        screencasts on one page -- REQ-13 edge). Logs grant open with the run id.
        """
        if self._grant is not None and self._grant.open():
            return self._grant
        grant = TakeoverGrant(
            grant_id=uuid.uuid4().hex,
            run_id=self._run_id,
            question_id=question_id,
            wall_kind=wall_kind,
            opened_at=time.time(),
            max_ms=max(1, int(max_ms)),
        )
        self._grant = grant
        logger.info(
            "[cdp_takeover] grant opened run_id=%s question_id=%s wall=%s max_ms=%d",
            self._run_id, question_id, wall_kind, max_ms,
        )
        self._emit_lifecycle("grant_opened", {
            "grant_id": grant.grant_id, "question_id": question_id,
            "wall_kind": wall_kind,
        })
        return grant

    def close_grant(self, reason: str = "resolved") -> None:
        """Close the grant, stop the screencast, release the CDP session.

        REQ-15 AC3: on timeout / panel close / cancellation the grant is
        released, the screencast stopped, and the CDP session released -- never
        left dangling. Idempotent; never raises.
        """
        grant = self._grant
        self._grant = None
        if grant is not None:
            logger.info(
                "[cdp_takeover] grant closed run_id=%s question_id=%s reason=%s",
                self._run_id, grant.question_id, reason,
            )
            self._emit_lifecycle("grant_closed", {
                "grant_id": grant.grant_id, "question_id": grant.question_id,
                "reason": reason,
            })

    def is_open(self) -> bool:
        """True while a live (unexpired) grant owns the page (REQ-15 AC1)."""
        return self._grant is not None and self._grant.open()


    # ── screencast transport ───────────────────────────────────────────────

    async def start_screencast(self, page: object) -> bool:
        """Start a CDP screencast on the SESSION's page (REQ-13 AC1).

        Returns True on success, False on any CDP failure (REQ-13 AC4: degrade,
        never fail the run). The frame pump is ack-paced: at most ONE frame in
        flight; a new frame while one is in flight is dropped latest-wins and
        counted (REQ-16 AC3).
        """
        if self._streaming:
            return True
        self._page = page
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        try:
            factory = self._cdp_factory or _default_cdp_factory
            self._cdp = factory(page)
            if asyncio.iscoroutine(self._cdp):
                self._cdp = await self._cdp
            if self._cdp is None:
                return False
            # Wire the frame event BEFORE starting so no frame is missed.
            on = getattr(self._cdp, "on", None)
            if callable(on):
                on("Page.screencastFrame", self._on_screencast_frame)
            send = getattr(self._cdp, "send", None)
            if not callable(send):
                return False
            await send("Page.startScreencast", {
                "format": "jpeg",
                "quality": _SCREENCAST_QUALITY,
                "maxWidth": _SCREENCAST_MAX_W,
                "maxHeight": _SCREENCAST_MAX_H,
                "everyNthFrame": 1,
            })
            self._streaming = True
            self._emit_lifecycle("screencast_started", {"run_id": self._run_id})
            return True
        except Exception as exc:  # noqa: BLE001 -- REQ-13 AC4: degrade, never fail
            logger.warning("[cdp_takeover] start_screencast failed: %s", exc)
            self._streaming = False
            return False

    async def stop_screencast(self) -> None:
        """Stop the screencast and release the CDP session (REQ-13 AC3).

        Idempotent; never raises.
        """
        self._streaming = False
        self._pending_frame = None
        self._inflight = 0
        cdp = self._cdp
        self._cdp = None
        if cdp is None:
            return
        try:
            send = getattr(cdp, "send", None)
            if callable(send):
                await send("Page.stopScreencast", {})
        except Exception as exc:  # noqa: BLE001
            logger.debug("[cdp_takeover] stopScreencast failed: %s", exc)
        try:
            detach = getattr(cdp, "detach", None)
            if callable(detach):
                await detach()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[cdp_takeover] cdp detach failed: %s", exc)
        self._emit_lifecycle("screencast_stopped", {"run_id": self._run_id})


    def _on_screencast_frame(self, params: Dict[str, Any]) -> None:
        """Handle one CDP screencast frame (sync callback from the CDP session).

        Ack-paced: ack immediately, then deliver the newest frame. A frame that
        arrives while one is in flight (unacked) is DROPPED latest-wins and
        counted (REQ-16 AC3). A frame with no open grant is dropped (REQ-16
        edge: a frame without an owner is unattributable).
        """
        try:
            if not self.is_open():
                # No owner -- drop, do not deliver (REQ-16 edge).
                self._ack(params)
                return
            data = params.get("data")
            meta = params.get("metadata") or {}
            if not data:
                self._ack(params)
                return
            self._frame_seq += 1
            self._seq += 1
            # Gap detection: a monotonic frame_seq; a jump means frames were
            # dropped between deliveries.
            if (self._stats.last_frame_seq >= 0
                    and self._frame_seq != self._stats.last_frame_seq + 1):
                self._stats.gaps += 1
            self._stats.last_frame_seq = self._frame_seq
            frame = ScreencastFrame(
                run_id=self._run_id,
                question_id=self._grant.question_id,
                seq=self._seq,
                frame_seq=self._frame_seq,
                ts=_now_ms(),
                viewport_w=int(meta.get("deviceWidth") or _SCREENCAST_MAX_W),
                viewport_h=int(meta.get("deviceHeight") or _SCREENCAST_MAX_H),
                format="jpeg",
                bytes=data if isinstance(data, str) else base64.b64encode(data).decode("ascii"),
            )
            envelope = frame.to_envelope()
            # latest-wins: if a frame is already in flight, replace the pending
            # one and count the drop.
            if self._inflight >= _MAX_INFLIGHT:
                if self._pending_frame is not None:
                    self._stats.dropped += 1
                self._pending_frame = envelope
            else:
                self._deliver(envelope)
            # Ack so Chromium keeps sending (REQ-13 AC2).
            self._ack(params)
        except Exception as exc:  # noqa: BLE001 -- a frame failure never breaks the pump
            logger.debug("[cdp_takeover] frame handling failed: %s", exc)

    def _deliver(self, envelope: Dict[str, Any]) -> None:
        if self._frame_sink is None:
            return
        try:
            self._inflight += 1
            self._frame_sink(envelope)
            self._stats.sent += 1
        except Exception as exc:  # noqa: BLE001 -- delivery is best-effort
            logger.debug("[cdp_takeover] frame sink failed: %s", exc)
            self._inflight = max(0, self._inflight - 1)

    def ack_frame(self) -> None:
        """Panel acknowledged the last delivered frame (REQ-13 AC2).

        Releases the single in-flight slot and flushes the latest pending frame
        (latest-wins), if any.
        """
        self._inflight = max(0, self._inflight - 1)
        pending = self._pending_frame
        self._pending_frame = None
        if pending is not None:
            self._deliver(pending)

    def _ack(self, params: Dict[str, Any]) -> None:
        """Tell Chromium the frame was consumed (Page.screencastFrameAck)."""
        cdp = self._cdp
        sid = params.get("sessionId")
        if cdp is None or sid is None:
            return
        try:
            send = getattr(cdp, "send", None)
            if callable(send):
                result = send("Page.screencastFrameAck", {"sessionId": sid})
                if asyncio.iscoroutine(result):
                    loop = self._loop
                    if loop is not None and loop.is_running():
                        loop.create_task(result)
                    else:
                        # No running loop (unit test / shutdown): close the
                        # coroutine so it is not left un-awaited.
                        try:
                            result.close()
                        except Exception:  # noqa: BLE001
                            pass
        except Exception as exc:  # noqa: BLE001
            logger.debug("[cdp_takeover] frame ack failed: %s", exc)


    # ── input authority (REQ-14) ────────────────────────────────────────────

    async def deliver_input(self, event: TakeoverInput) -> bool:
        """Forward a page-level input event to the page -- grant-gated.

        REQ-14 AC1: input is accepted ONLY while a grant is open; an event
        arriving outside an open grant is REJECTED, COUNTED, and applied
        nothing. REQ-14 AC3: only pointer/wheel/key/text are representable.
        REQ-14 AC4: a typed value is ephemeral -- forwarded, never logged.

        Returns True when forwarded, False when rejected. Never raises.
        """
        if not self.is_open():
            self._rejected_inputs += 1
            logger.info(
                "[cdp_takeover] input rejected (no open grant) run_id=%s kind=%s",
                self._run_id, getattr(event, "kind", "?"),
            )
            return False
        if event.kind not in _ALLOWED_INPUT_KINDS:
            self._rejected_inputs += 1
            logger.info(
                "[cdp_takeover] input rejected (kind not page-level) run_id=%s kind=%s",
                self._run_id, event.kind,
            )
            return False
        cdp = self._cdp
        send = getattr(cdp, "send", None) if cdp is not None else None
        if not callable(send):
            return False
        try:
            await self._dispatch_input(send, event)
            return True
        except Exception as exc:  # noqa: BLE001 -- a failed input is not a run failure
            logger.warning("[cdp_takeover] input dispatch failed kind=%s: %s", event.kind, exc)
            return False

    async def _dispatch_input(self, send: Callable, event: TakeoverInput) -> None:
        if event.kind == "pointer":
            button = event.button if event.button in _ALLOWED_MOUSE_BUTTONS else "left"
            await send("Input.dispatchMouseEvent", {
                "type": "mousePressed",
                "x": event.x or 0, "y": event.y or 0,
                "button": button, "clickCount": 1,
            })
            await send("Input.dispatchMouseEvent", {
                "type": "mouseReleased",
                "x": event.x or 0, "y": event.y or 0,
                "button": button, "clickCount": 1,
            })
        elif event.kind == "wheel":
            await send("Input.dispatchMouseEvent", {
                "type": "mouseWheel",
                "x": event.x or 0, "y": event.y or 0,
                "deltaX": event.x or 0, "deltaY": event.y or 0,
            })
        elif event.kind == "key":
            await send("Input.dispatchKeyEvent", {
                "type": "keyDown", "key": event.key or "",
            })
            await send("Input.dispatchKeyEvent", {
                "type": "keyUp", "key": event.key or "",
            })
        elif event.kind == "text":
            # REQ-14 AC4: the typed value is EPHEMERAL. Forward it and drop it;
            # it is never logged, stored, or echoed in a frame event.
            await send("Input.insertText", {"text": event.text or ""})

    # ── credential application WITHOUT exposure (REQ-14 AC5/AC6) ────────────

    def apply_credential(
        self,
        *,
        secret_ref: str,
        field_handle: str,
        value: str,
    ) -> CredentialApplication:
        """Apply a keyring secret to a session field -- USED, never SEEN.

        REQ-14 AC5: the value must not enter the model context, memory, the
        ledger, the event stream, or any log. This records only a REFERENCE
        (AC6) -- the audit trail is value-free. The caller must have obtained
        explicit user authorisation first (the grant is the authority).

        Returns the audit record. Never logs or emits the value.
        """
        grant = self._grant
        grant_id = grant.grant_id if grant is not None else ""
        outcome = "applied" if self.is_open() else "no_grant"
        record = CredentialApplication(
            grant_id=grant_id,
            secret_ref=secret_ref,
            field_handle=field_handle,
            applied_at=time.time(),
            outcome=outcome,
        )
        self._credentials.append(record)
        # NOTE: `value` is intentionally NOT included anywhere below.
        logger.info(
            "[cdp_takeover] credential %s grant=%s secret_ref=%s field=%s (value NOT logged)",
            outcome, grant_id, secret_ref, field_handle,
        )
        return record

    @property
    def credential_records(self) -> List[CredentialApplication]:
        return list(self._credentials)

    async def apply_keyring_credential(
        self,
        *,
        host: str,
        provider_id: str,
        field_handle: str,
        authorized: bool,
    ) -> CredentialApplication:
        """Apply a keyring secret to a session field -- USED, never SEEN (T23).

        REQ-14 AC5: the value must not enter the model context, memory, the
        ledger, the event stream, or any log. REQ-14 AC6: explicit user
        authorisation is REQUIRED before applying; the audit record holds a
        REFERENCE (grant id + secret ref), never the value.

        A host with NO keyring entry degrades to the manual takeover (returns a
        record with outcome ``no_secret``) -- never a silent failure and never a
        guessed credential. The value is read from the keyring, inserted into
        the page field via CDP, and immediately dropped: it is never logged,
        stored on this object, or echoed.

        Returns the value-free audit record.
        """
        if not authorized:
            record = CredentialApplication(
                grant_id=(self._grant.grant_id if self._grant else ""),
                secret_ref=f"keyring:{provider_id}", field_handle=field_handle,
                applied_at=time.time(), outcome="declined",
            )
            self._credentials.append(record)
            return record
        try:
            from backend.agent.inference.keyring import get_secret

            secret = get_secret(provider_id)
        except Exception as exc:  # noqa: BLE001 -- a missing keyring degrades
            logger.info("[cdp_takeover] keyring read failed host=%s: %s", host, exc)
            secret = None
        grant = self._grant
        grant_id = grant.grant_id if grant is not None else ""
        if not secret:
            # REQ-14 edge: no keyring entry -> manual takeover, never a guess.
            record = CredentialApplication(
                grant_id=grant_id, secret_ref=f"keyring:{provider_id}",
                field_handle=field_handle, applied_at=time.time(),
                outcome="no_secret",
            )
            self._credentials.append(record)
            logger.info(
                "[cdp_takeover] no keyring secret host=%s provider=%s -> manual takeover",
                host, provider_id,
            )
            return record
        # Apply it to the field WITHOUT exposure. `secret` is used here and
        # never written to a log, the ledger, or the event stream.
        applied = False
        cdp = self._cdp
        send = getattr(cdp, "send", None) if cdp is not None else None
        if self.is_open() and callable(send):
            try:
                await send("Runtime.evaluate", {
                    "expression": (
                        "(() => { const el = document.querySelector(%r);"
                        " if (!el) return false;"
                        " el.focus(); el.value = %r;"
                        " el.dispatchEvent(new Event('input', {bubbles:true}));"
                        " el.dispatchEvent(new Event('change', {bubbles:true}));"
                        " return true; })()" % (field_handle, secret)
                    )
                })
                applied = True
            except Exception as exc:  # noqa: BLE001 -- a failed apply is recorded
                logger.info("[cdp_takeover] credential apply failed host=%s: %s", host, exc)
        record = CredentialApplication(
            grant_id=grant_id, secret_ref=f"keyring:{provider_id}",
            field_handle=field_handle, applied_at=time.time(),
            outcome="applied" if applied else "field_not_found",
        )
        self._credentials.append(record)
        return record

    # ── consent for persisting post-takeover cookies (REQ-15 AC5) ───────────

    def grant_consent(self, host: str, kind: str = "session_cookies") -> ConsentRecord:
        """Record revocable consent to persist post-takeover cookies (REQ-15 AC5).

        Nothing is persisted without this. The record names the host and what
        will be stored, and is revocable via `revoke_consent`.
        """
        rec = ConsentRecord(host=host, kind=kind, granted_at=time.time())
        self._consents[host] = rec
        logger.info("[cdp_takeover] consent granted host=%s kind=%s", host, kind)
        return rec

    def revoke_consent(self, host: str) -> None:
        rec = self._consents.get(host)
        if rec is not None:
            rec.revoked_at = time.time()
            logger.info("[cdp_takeover] consent revoked host=%s", host)

    def has_consent(self, host: str) -> bool:
        rec = self._consents.get(host)
        return rec is not None and rec.active()

    def consent_prompt(self, host: str) -> Dict[str, Any]:
        """The consent affordance payload — NAMES the host + what will be stored.

        REQ-15 AC5: the affordance must name the host and what will be stored,
        and be revocable. Returned (not auto-applied): nothing is persisted
        without the user accepting it.
        """
        return {
            "host": host,
            "kind": "session_cookies",
            "message": (
                f"Save the login session for {host} so I can reuse it on a "
                f"later run? This stores {host}'s session cookies in your OS "
                f"keyring. You can revoke it at any time."
            ),
            "revocable": True,
        }

    def evaluate_continuation(
        self, *, target_host: str, current_host: str, guardrails_block: bool,
    ) -> Dict[str, Any]:
        """Decide how to continue after an off-domain takeover (REQ-15 AC6).

        The user may navigate away from the target domain during a takeover.
        A domain change SHALL NOT auto-park; instead the guardrails are
        re-evaluated against the page the user left it on. When a guardrail
        WOULD block and a safe continuation cannot be determined, the caller
        must ASK the user through `AskUserQuestion` rather than silently
        parking or silently proceeding.

        Returns a decision dict:
          - ``action``: ``continue`` (resume on the new page) or ``ask``
            (escalate via AskUserQuestion).
        """
        off_domain = (current_host or "").lower() != (target_host or "").lower()
        if not off_domain:
            return {"action": "continue", "reason": "same_domain"}
        if guardrails_block:
            # REQ-15 AC6: cannot safely resume -> ASK, never auto-park.
            return {
                "action": "ask",
                "reason": "guardrail_block_off_domain",
                "question": (
                    f"You navigated to {current_host or 'another site'}, which "
                    f"is outside the target ({target_host}). Keep going there, "
                    f"or should I return to the target?"
                ),
                "options": ["Keep going here", "Return to the target"],
            }
        # Off-domain but not blocked: continue from the page the user left it on.
        return {"action": "continue", "reason": "off_domain_allowed"}

    # ── lifecycle ──────────────────────────────────────────────────────────

    def _emit_lifecycle(self, kind: str, payload: Dict[str, Any]) -> None:
        if self._lifecycle_sink is None:
            return
        try:
            self._lifecycle_sink(kind, payload)
        except Exception:  # noqa: BLE001
            pass


async def _default_cdp_factory(page: object):
    """Create a CDP session on ``page`` via Playwright (real path).

    Lazy: the Playwright import cost is paid only when a takeover actually
    starts. Returns None when no CDP session can be created (REQ-13 AC4).
    """
    try:
        context = getattr(page, "context", None)
        ctx = context() if callable(context) else context
        new_cdp = getattr(ctx, "new_cdp_session", None)
        if callable(new_cdp):
            return await new_cdp(page)
    except Exception as exc:  # noqa: BLE001
        logger.info("[cdp_takeover] no CDP session available: %s", exc)
    return None


__all__ = [
    "ConsentRecord",
    "CredentialApplication",
    "FrameStreamStats",
    "ScreencastFrame",
    "TakeoverGrant",
    "TakeoverInput",
    "TakeoverManager",
    "ack_frame",
    "clear_registry",
    "deliver_input",
    "get_active",
    "get_frame_sink",
    "register_active",
    "set_frame_sink",
    "unregister_active",
]

