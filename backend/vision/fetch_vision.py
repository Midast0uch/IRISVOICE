"""fetch.vision capability node (T10, REQ-6/REQ-7).

Composes the Wave-2 pieces into one goal-directed fetch capability:
  - BrowserSession (T8): persistent Playwright page, bounded by SessionBounds
  - no lease (specs/vision-single-server): the shared multimodal server is
    someone else's process and stays warm on its own
  - frame extraction (T12a): triage-before-extract, bounded by max_extractions
  - page_is_usable (T1): vision-derived text is NOT trusted by virtue of being
    vision-derived — it goes through the same predicate as crawl content

Outcome contract (REQ-6 AC5): the settled DOM is handed back via
FetchOutcome.settled_dom so a fetch.crawl pass can run on it — the reversal
edge that makes `crawl -> vision -> crawl` a normal traversal. Wall detection
feeds T14 (REQ-7): CAPTCHA / LOGIN / PAYWALL are returned in FetchOutcome.wall.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field as dc_field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:  # pragma: no cover — typing only, zero runtime cost
    from backend.core_models import GoalAnatomy

from backend.crawler.capabilities import FetchCapability, FetchOutcome, WallKind
from backend.crawler.crawler_engine import PageData
from backend.crawler.usability import (
    MIN_CONTENT_CHARS,
    UsabilityReason,
    UsabilityVerdict,
    page_is_usable,
)
# specs/vision-single-server: no lease API anymore — the shared multimodal
# server stays up on its owner's watch; borrow discovery never idles it down.
from backend.vision.action_allowlist import evaluate_task_guardrails
from backend.vision.browser_session import (
    BrowserSession,
    SessionBounds,
    VisionAction,
)
from backend.vision.frame_extraction import extract_page_frames, reconcile
from backend.vision.session_vision_adapter import SessionVisionAdapter
from backend.vision.stage_timing import StageTimer, record_stage

logger = logging.getLogger(__name__)

# Vision loops need a hard iteration cap independent of wall-clock: a model
# that keeps suggesting actions must not loop forever even within budget.
_MAX_LOOP_STEPS = int(os.environ.get("IRIS_VISION_MAX_LOOP_STEPS", "8"))


# ---------------------------------------------------------------------------
# Action trajectory + perceptual visual delta (goal-directed-search REQ-17, T7).
# Intra-tool sliding window over the last actions, formatted into the action
# suggestion prompt for whichever model drives (AC17.2); zero-progress loops
# terminate into DOM settle (AC17.3). Pure data + pure functions: the live
# loop wiring lives in BrowserSession (T8).
# ---------------------------------------------------------------------------

#: Below this perceptual delta an action counts as no visible progress (AC4.2).
NO_PROGRESS_DELTA = 0.05
#: Sliding window size for the suggestion prompt (AC17.2).
TRAJECTORY_WINDOW = 3
#: Consecutive no-progress actions before the loop terminates (AC17.3).
NO_PROGRESS_LIMIT = 3


def visual_delta(prev_png: Optional[bytes], cur_png: Optional[bytes]) -> float:
    """Perceptual delta between two screenshots in [0.0, 1.0].

    0.0 == identical. First frame (prev None) scores 1.0 (treated as changed).
    Uses PIL grayscale 64x64 mean-absolute-difference when available;
    otherwise falls back to exact-equality (0.0 vs 1.0, magnitude unknown).
    Never raises: undecodable bytes score 1.0 (assume changed, keep going).
    """
    if prev_png is None:
        return 1.0
    if cur_png is None:
        return 1.0
    if prev_png == cur_png:
        return 0.0
    try:
        from PIL import Image
        import io as _io

        def _signature(raw: bytes) -> list:
            with Image.open(_io.BytesIO(raw)) as img:
                flat = img.convert("L").resize((64, 64))
                get_flat = getattr(flat, "get_flattened_data", None)
                return list(get_flat() if callable(get_flat) else flat.getdata())

        prev_px = _signature(prev_png)
        cur_px = _signature(cur_png)
        if len(prev_px) != len(cur_px) or not prev_px:
            return 1.0
        diff = sum(abs(a - b) for a, b in zip(prev_px, cur_px))
        return min(1.0, diff / (len(prev_px) * 255.0))
    except Exception:
        return 1.0


@dataclass
class TrajectoryStep:
    """One micro-step: action + target + parameters + outcome + delta."""
    action: str
    target: str = ""
    params: Dict[str, Any] = dc_field(default_factory=dict)
    outcome: str = ""
    visual_delta: float = 1.0


class ActionTrajectory:
    """Sliding window (last N steps) with no-progress detection (REQ-17)."""

    def __init__(self, window: int = TRAJECTORY_WINDOW):
        self._window = max(1, int(window))
        self._steps: List[TrajectoryStep] = []

    def __len__(self) -> int:
        return len(self._steps)

    def record(
        self,
        action: str,
        target: str = "",
        params: Optional[Dict[str, Any]] = None,
        outcome: str = "",
        visual_delta: float = 1.0,
    ) -> TrajectoryStep:
        """Append a step, evicting the oldest beyond the window."""
        step = TrajectoryStep(action=action, target=target,
                              params=dict(params or {}), outcome=outcome,
                              visual_delta=visual_delta)
        self._steps.append(step)
        del self._steps[: max(0, len(self._steps) - self._window)]
        return step

    def window_steps(self) -> List[TrajectoryStep]:
        return list(self._steps)

    def _step_is_no_progress(self, idx: int) -> bool:
        """A step is no-progress when its own delta is negligible (AC4.2) OR
        it retargets the same element as its predecessor twice in a row.
        Steps are counted individually (not as transitions): three trailing
        no-progress ACTIONS trip the AC17.3 limit."""
        if idx < 0 or idx >= len(self._steps):
            return False
        step = self._steps[idx]
        if step.visual_delta < NO_PROGRESS_DELTA:
            return True
        if idx == 0:
            return False
        prev = self._steps[idx - 1]
        return bool(step.target) and step.target == prev.target

    def no_progress_streak(self) -> int:
        """Trailing count of consecutive no-progress actions."""
        streak = 0
        for idx in range(len(self._steps) - 1, -1, -1):
            if self._step_is_no_progress(idx):
                streak += 1
            else:
                break
        return streak

    @property
    def should_terminate(self) -> bool:
        """AC17.3: 3 consecutive no-progress actions end the action loop."""
        return self.no_progress_streak() >= NO_PROGRESS_LIMIT

    def format_prompt(self) -> str:
        """Render the window for the action-suggestion prompt (AC17.2),
        including the negative constraint when progress has stalled."""
        if not self._steps:
            return "No prior actions this session."
        lines = []
        for i, step in enumerate(self._steps, 1):
            params = ", ".join(f"{k}={v}" for k, v in step.params.items())
            lines.append(
                f"{i}. {step.action} target={step.target!r}"
                + (f" params=({params})" if params else "")
                + f" -> {step.outcome or 'n/a'} "
                f"(delta={step.visual_delta:.2f})"
            )
        streak = self.no_progress_streak()
        if streak > 0:
            last = self._steps[-1]
            lines.append(
                f"Negative constraint: do NOT repeat {last.action!r} on "
                f"{last.target!r} — the last {streak} action(s) made no "
                f"visible progress."
            )
        if self.should_terminate:
            lines.append(
                "TERMINATE the action loop and proceed to DOM settle."
            )
        return "\n".join(lines)


def _make_session(session_cls, job_id, url, goal, bounds, page_offset: int):
    """Construct a browser session, passing ``page_offset`` only if it takes one.

    session_cls is injectable (test doubles implement the 4-positional shape),
    so the capture-block offset is passed by capability, not assumed. Decided by
    signature rather than by catching TypeError from the constructor: a
    TypeError raised inside a real __init__ would be misread as "no such
    parameter" and silently drop the offset, restoring the overwrite bug.
    """
    if page_offset:
        try:
            import inspect

            _params = inspect.signature(session_cls).parameters
            if "page_offset" in _params or any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in _params.values()
            ):
                return session_cls(job_id, url, goal, bounds, page_offset=page_offset)
            logger.warning(
                "[fetch.vision] session_cls %s takes no page_offset — frames for "
                "job_id=%s will number from 1 and may overwrite another URL's capture",
                getattr(session_cls, "__name__", session_cls), job_id,
            )
        except (TypeError, ValueError):
            pass
    return session_cls(job_id, url, goal, bounds)


class FetchVisionCapability(FetchCapability):
    """Vision-guided browser fetch (REQ-6/REQ-7)."""

    name = "fetch.vision"

    def __init__(
        self,
        provider: Optional[object] = None,
        session_cls: type = BrowserSession,
        bounds: Optional[SessionBounds] = None,
    ):
        self._provider = provider  # lazy get_lfm_vl_provider() when None
        self._session_cls = session_cls
        self._bounds = bounds or SessionBounds()
        self._provider_singleton = None

    # ── FetchCapability ───────────────────────────────────────────────────

    async def available(self) -> bool:
        """True when the vision provider resolves AND a browser session could
        open. Never raises; a missing stack degrades to unavailable (REQ-6
        AC1 edge)."""
        try:
            provider = self._get_provider()
            if provider is None:
                return False
            return True
        except Exception as exc:  # noqa: BLE001
            logger.info("[fetch.vision] unavailable: %s", exc)
            return False

    async def fetch_one(
        self,
        url: str,
        goal: str | GoalAnatomy,
        job_id: str,
        on_action: Optional[Callable[[dict], None]] = None,
        page_offset: int = 0,
    ) -> FetchOutcome:
        """Run the goal-directed action loop for one URL, bounded by
        SessionBounds. Always returns a FetchOutcome — never raises.

        ``on_action`` (REQ-11 AC4) receives one payload per performed action so
        the panel can annotate its existing animation surface. It is an OPTIONAL
        keyword: the FetchCapability protocol is a 3-positional-arg call, so
        fetch.crawl and fetch.vision stay interchangeable (REQ-6 AC1). It is a
        per-call parameter rather than instance state on purpose — the capability
        singleton is shared across concurrent runs, and an emitter stored on it
        would cross-wire their events.

        ``page_offset`` is this URL's reserved block of the job's CAPTURE address
        space, and it is a CORRECTNESS fix, not a cosmetic one. A session
        publishes one capture per distinct frame, numbering from 1, into the
        SHARED job_id directory — so an escalation on URL 4 overwrote the crawl
        captures of URLs 1, 2, 3 and the panel served URL 4's frames under URL
        1's tab. Wrong bytes presented as evidence is worse than a 404. Also a
        per-call parameter: concurrent dispatch runs several sessions at once,
        each owning a different block.
        """
        t0 = time.monotonic()
        bounds = self._bounds
        # REQ-26 AC26.1–26.3 (T39): structured goals ride the union. Text edges
        # keep the string protocol (GoalAnatomy.__str__ IS to_prompt); the
        # REQ-20 gate evaluates the goal's own guardrails (defaults for str).
        if isinstance(goal, str):
            _goal_text = goal
            _guards = ["NO_PURCHASE", "DOMAIN_BOUND"]
        else:
            try:
                _render = getattr(goal, "to_prompt", None)
                _goal_text = _render() if callable(_render) else str(goal)
            except Exception:  # noqa: BLE001 — rendering never breaks the loop
                _goal_text = ""
            _guards = list(getattr(goal, "guardrails", None) or []) or [
                "NO_PURCHASE", "DOMAIN_BOUND",
            ]
        session = _make_session(self._session_cls, job_id, url, _goal_text, bounds, page_offset)
        wall: Optional[WallKind] = None
        actions = 0
        # REQ-10 AC1 (T4): the termination cause + last step index are recorded
        # for the tuning line. Initialised here so the finally block can always
        # report them, even on an early return or an exception.
        _termination_cause = "not_started"
        step = -1
        try:
            await session.open()
            if not session.available():
                return FetchOutcome(
                    url=url, capability=self.name, page=None,
                    verdict=UsabilityVerdict(
                        usable=False, reason=UsabilityReason.TRANSPORT_ERROR,
                        detail="vision browser unavailable",
                    ),
                    actions_taken=0,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )

            # ── action loop (REQ-7): suggest -> guard -> act -> wall check ──
            trajectory = ActionTrajectory()
            # REQ-9 AC3 (T7): ONE observation per settled state. `_current_frame`
            # is the settled frame for the CURRENT decision; it is captured
            # once, fed to the suggestion, and refreshed ONLY after an action
            # changes the page. The first decision captures it lazily.
            _current_frame: Optional[bytes] = None
            # REQ-6 AC4 (this spec's T3): a monotonic per-run sequence number
            # stamped on every emitted vision action so a dropped or reordered
            # event is detectable by the consumer. run_id scopes it to this run.
            _run_id = job_id
            _seq = 0
            for step in range(_MAX_LOOP_STEPS):
                # Wall check first (cheap DOM heuristics, no VLM).
                try:
                    wall = await session.detect_wall()
                except Exception as exc:  # noqa: BLE001
                    logger.info("[fetch.vision] wall-detect failed: %s", exc)
                    wall = None
                if wall is not None:
                    logger.info(
                        "[fetch.vision] job_id=%s url=%s wall=%s (REQ-7)",
                        job_id, url, wall.value,
                    )
                    # T11 (REQ-10 AC1): a user-solvable wall (CAPTCHA/login)
                    # is offered to the panel BEFORE parking. request_takeover
                    # is a no-op (returns False) for paywalls, missing ask
                    # tooling, timeouts, and unresolved walls — so the old
                    # park path still handles everything it used to.
                    try:
                        _cleared = await session.request_takeover(wall)
                    except Exception as _tk_exc:  # noqa: BLE001 — takeover must
                        # never break the loop; fall through to the old park.
                        logger.info("[fetch.vision] takeover failed: %s", _tk_exc)
                        _cleared = False
                    if _cleared:
                        # AC3: wall verified gone; resume the action loop.
                        wall = None
                        continue
                    _termination_cause = f"wall_unresolved:{wall.value}"
                    break

                # REQ-9 AC3 (T7): capture the settled frame ONCE for this
                # decision (lazily; it is refreshed only after an action that
                # changed the page). Both the suggestion below and any later
                # reuse in this iteration share this ONE capture — no second
                # screenshot for the same settled state.
                if _current_frame is None:
                    try:
                        _current_frame = await session.screenshot()
                    except Exception:  # noqa: BLE001 — a lost frame is not fatal
                        _current_frame = None
                suggestion = await self._suggest_action(
                    session, _goal_text, job_id,
                    trajectory=trajectory, img=_current_frame,
                )
                action = self._map_action(suggestion)
                if action is None:
                    # Model said error/unknown — settle and hand back.
                    logger.info(
                        "[fetch.vision] job_id=%s url=%s stop-loop step=%d suggestion=%r (REQ-7)",
                        job_id, url, step, suggestion,
                    )
                    _termination_cause = "model_stop"
                    break

                # REQ-4 AC2 (T6): measured-progress termination. After N
                # consecutive actions whose measured visual delta is below the
                # no-progress threshold (or which re-target the same element
                # twice), the loop settles. A productive multi-scroll or
                # multi-click session keeps a changing delta and is NOT stopped.
                if trajectory.should_terminate:
                    logger.info(
                        "[fetch.vision] job_id=%s url=%s no-progress streak=%d "
                        "-> settling (REQ-4 AC2)",
                        job_id, url, trajectory.no_progress_streak(),
                    )
                    _termination_cause = "no_progress"
                    break

                # REQ-20 AC20.1/AC20.3 (T31 + T39): task guardrails gate BEFORE
                # any act. A structured goal's own guardrails are evaluated;
                # a plain string keeps the defaults. A block settles the page
                # and hands back (bounded, no extra VLM rounds); the rejection
                # is recorded on the trajectory.
                try:
                    _gate = evaluate_task_guardrails(
                        _guards,
                        {"action_type": action.kind,
                         "target_name": action.target or "",
                         "url": url},
                        {"url": url},
                    )
                except Exception:  # noqa: BLE001 — gate never breaks the loop
                    _gate = None
                if _gate is not None and not _gate.allowed:
                    trajectory.record(
                        action.kind, target=action.target or "",
                        outcome=f"rejected_guardrail:{_gate.violated}",
                    )
                    logger.warning(
                        "[fetch.vision] job_id=%s url=%s blocked %s: %s (REQ-20)",
                        job_id, url, _gate.violated, _gate.reason,
                    )
                    _termination_cause = f"guardrail:{_gate.violated}"
                    break

                # REQ-4 (T6): termination is decided by MEASURED PROGRESS, not
                # by a repeated action KIND. The former `repeats` list and its
                # "3 identical kinds = stuck" stop are REMOVED — a long page is
                # legitimately scroll-dominated, so a kind-repeat heuristic
                # stops exactly the sessions it should keep. The post-action
                # visual delta recorded onto the trajectory (below) is the
                # progress signal; `trajectory.should_terminate` ends the loop
                # only after N consecutive no-progress actions.

                try:
                    await session.act(action)
                    actions += 1
                    # REQ-4 AC1/AC3 (T6): measure the perceptual delta this
                    # action produced and record it on the trajectory, so a
                    # measurable change resets the no-progress streak even when
                    # the action KIND repeats. `_post is None` (a lost frame)
                    # scores as changed per visual_delta's contract, so a
                    # degraded capture never falsely stalls the loop.
                    try:
                        _post = await session.screenshot()
                    except Exception:  # noqa: BLE001 — a lost frame is not progress
                        _post = None
                    _delta = visual_delta(_current_frame, _post)
                    trajectory.record(
                        action.kind, target=action.target or "",
                        outcome="ok", visual_delta=_delta,
                    )
                    if _post is not None:
                        _current_frame = _post
                    # REQ-10 AC1 (T4): per-step tuning signal — the action
                    # cadence (kind + step index) AND the measured no-progress
                    # delta + streak. Off the critical path.
                    record_stage(
                        job_id, "cadence", 0,
                        step=step, kind=action.kind, actions=actions,
                        delta=round(_delta, 3),
                        streak=trajectory.no_progress_streak(),
                    )
                    # REQ-11 AC4: announce the action so the panel can annotate
                    # it. Best-effort — a failing emitter must never break the
                    # loop (REQ-16 AC7: instrumentation is off the critical path).
                    if on_action is not None:
                        try:
                            _seq += 1
                            payload = {
                                # REQ-6 AC4: run-scoped monotonic sequence so a
                                # dropped/reordered event is detectable.
                                "run_id": _run_id,
                                "seq": _seq,
                                "job_id": job_id,
                                "url": url,
                                "kind": action.kind,
                                "reason": action.reason or "",
                                "action_index": actions,
                                "total": _MAX_LOOP_STEPS,
                            }
                            # REQ-16 AC7: fold in the best-effort cursor point
                            # BrowserSession captured for this action (click/
                            # type -> x/y/viewport_w/viewport_h; scroll ->
                            # scroll_dx/scroll_dy). Read via getattr — fakes in
                            # the contract tests do not set this attribute, and
                            # its absence must never break emission.
                            point = getattr(session, "last_action_point", None)
                            if point:
                                payload.update(point)
                            # The session publishes a capture per distinct frame,
                            # but nothing told the panel WHERE. Without the
                            # address those frames were written and never read —
                            # the built-but-never-reached shape this codebase
                            # keeps producing. getattr: fakes do not set it.
                            _frame = getattr(session, "current_capture_page", None)
                            if _frame is not None:
                                payload["capture_page"] = int(_frame)
                            on_action(payload)
                        except Exception as _emit_exc:  # noqa: BLE001
                            logger.debug(
                                "[fetch.vision] on_action emit failed: %s", _emit_exc,
                            )
                except Exception as exc:  # noqa: BLE001
                    # SessionBudgetExceeded or a broken action: observation is
                    # surfaced, loop ends gracefully (REQ-7 AC6).
                    logger.info(
                        "[fetch.vision] job_id=%s url=%s act %s failed: %s (REQ-7 AC6)",
                        job_id, url, action.kind, exc,
                    )
                    _termination_cause = f"action_error:{action.kind}"
                    break
            else:
                # REQ-4 AC4 (T6): the hard step bound is the outer limit. Reached
                # only when every step made progress and the loop ran out of
                # iterations — recorded distinctly from a stall.
                _termination_cause = "max_steps"

            # ── extraction (T12a): triage-before-extract, bounded ──
            # SessionVisionAdapter binds the SESSION (frames + scrolling) and
            # the PROVIDER (VLM calls) into the single object
            # extract_page_frames expects (backend/vision/
            # session_vision_adapter.py) — this call site used to pass
            # `session` positionally into extract_page_frames' `provider`
            # parameter AND `provider=` as a keyword, a guaranteed
            # `TypeError: got multiple values for argument 'provider'` that
            # ran in EVERY vision session and was swallowed silently below.
            provider = self._get_provider()
            frames = []
            if provider is not None:
                try:
                    adapter = SessionVisionAdapter(session, provider)
                    frames = await extract_page_frames(adapter, _goal_text, bounds)
                except Exception as exc:  # noqa: BLE001 — non-fatal: the
                    # session still returns its settled DOM below. WARNING
                    # (not info) + url/job_id: this exact failure ran silent
                    # in production for weeks because it logged at info and
                    # nothing asserted extraction actually produced frames.
                    logger.warning(
                        "[fetch.vision] extraction failed job_id=%s url=%s: %s",
                        job_id, url, exc,
                    )

            # ── settled-DOM handback (REQ-6 AC5) + page build ──
            settled_dom = await session.settle()
            vision_text = "\n\n".join(f.text for f in frames if f.text).strip()
            page = self._build_page(url, settled_dom, vision_text)
            verdict = page_is_usable(page)
            # REQ-17 AC3/AC4: reconcile crawl vs vision into an evidence record
            # is done by the caller (orchestrator). Here we only build the page.
            return FetchOutcome(
                url=url,
                capability=self.name,
                page=page if verdict.usable else None,
                verdict=verdict,
                settled_dom=settled_dom or None,
                wall=wall,
                actions_taken=actions,
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
        except Exception as exc:  # noqa: BLE001 — capability must never raise
            logger.warning("[fetch.vision] job_id=%s url=%s error: %s", job_id, url, exc)
            return FetchOutcome(
                url=url, capability=self.name, page=None,
                verdict=UsabilityVerdict(
                    usable=False, reason=UsabilityReason.TRANSPORT_ERROR,
                    detail=str(exc)[:200],
                ),
                actions_taken=actions,
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
        finally:
            try:
                await session.close()
            except Exception as exc:  # noqa: BLE001
                logger.info("[fetch.vision] close failed: %s", exc)
            # REQ-8 AC1 (T4): total session duration, scoped by run id. Also
            # carries the REQ-10 tuning signals captured during the loop
            # (termination cause + action cadence) so one line answers "why did
            # this run end and how fast was it" without cross-referencing.
            record_stage(
                job_id, "session", int((time.monotonic() - t0) * 1000),
                actions=actions, steps=step + 1,
                termination=_termination_cause,
            )

    # ── internals ─────────────────────────────────────────────────────────

    def _get_provider(self):
        """Resolve the vision serving client through the ONE resolver (REQ-1).

        Before this, the browser path constructed the tier-3 ``LFMVLProvider``
        directly (via ``get_lfm_vl_provider``), so a bound multimodal brain/tool
        was silently ignored and tier 3 was always used â€” the confirmed REQ-1
        defect. ``resolve_vision_client()`` is the same single source of vision
        serving every other consumer uses, and it preserves the method surface
        (``analyze_screen`` / ``read_text`` / ``suggest_action`` /
        ``health_check``), so nothing downstream of this method changes.

        Degrades exactly as before on failure (REQ-1 AC3): a resolver that
        raises ``VisionModelUnavailable`` (or any other error) yields ``None``,
        which callers already read as "vision unavailable" — never a raise into
        the crawl/vision hot path. Specs/vision-single-server: there is no
        owned tier-3 server and no lease — the resolver's tier-3 client borrows
        the shared multimodal server.
        """
        if self._provider is not None:
            return self._provider
        if self._provider_singleton is None:
            try:
                from backend.agent.inference.router import resolve_vision_client

                _resolution, client = resolve_vision_client()
                self._provider_singleton = client
            except Exception as exc:  # noqa: BLE001 â€” degrade, never raise (REQ-1 AC3)
                logger.info("[fetch.vision] provider init failed: %s", exc)
                self._provider_singleton = None
        return self._provider_singleton

    async def _suggest_action(
        self, session: BrowserSession, goal: str | GoalAnatomy, run_id: str = "",
        trajectory: Optional["ActionTrajectory"] = None,
        img: Optional[bytes] = None,
    ) -> dict:
        """Ask the VLM for the next action, feeding a BROWSER screenshot
        (REQ-9 AC2: never the desktop). Graceful when vision is down.

        REQ-3 (T5): the recent `ActionTrajectory` window and its no-repeat
        constraint are fed into the prompt as ADDITIONAL CONTEXT (a separate
        `trajectory` argument, never folded into `goal` — the goal stays the
        objective, so goal-propagation callers are unaffected). The window is
        rendered by `ActionTrajectory.format_prompt()`; an EMPTY window sends
        the un-augmented baseline (REQ-3 edge), and a formatting failure falls
        back to the baseline prompt without failing the action request
        (REQ-3 AC4). Only providers that ACCEPT a `trajectory` keyword receive
        it (decided by signature, mirroring `_make_session`) so a fake with the
        bare `(img, goal)` shape is called unchanged.

        REQ-9 AC3 (T7): when the caller already captured the settled-state frame
        it passes it as `img` and this method does NOT take a second screenshot
        for the same decision — one observation per settled state serves the
        suggestion.
        """
        provider = self._get_provider()
        if provider is None:
            return {"action": "error", "target": "", "reasoning": "vision unavailable"}
        # REQ-3 AC1/AC2: build the window text. Never raises (AC4).
        _traj_text = ""
        if trajectory is not None:
            try:
                if len(trajectory) > 0:
                    _traj_text = trajectory.format_prompt()
            except Exception as exc:  # noqa: BLE001 — fall back to baseline (AC4)
                logger.info("[fetch.vision] trajectory format failed: %s", exc)
                _traj_text = ""
        try:
            # REQ-9 AC3: reuse the caller's frame when given, else capture once.
            if img is None:
                img = await session.screenshot()
            if img is None:
                return {"action": "error", "target": "", "reasoning": "no browser frame"}
            # to_thread, NOT a direct call. suggest_action is SYNCHRONOUS and
            # reaches _ensure_vision_server_running, whose readiness loop sleeps
            # 0.5s x 60 = up to THIRTY SECONDS, followed by a blocking httpx
            # call with a 30s timeout. Called inline from this already-running
            # event loop it froze the whole backend — WebSocket, TTS and all —
            # which is the "app stopped responding when the vision server
            # launched" observed live on 2026-08-11. SessionVisionAdapter
            # already dispatches every provider call this way; this was the one
            # provider call that had been left on the loop.
            #
            # REQ-8 AC1 (T4): time the MODEL INFERENCE stage (the await only —
            # the screenshot above is timed by the session as its own stage).
            _inf_t0 = time.monotonic()
            if _traj_text and self._provider_accepts_trajectory(provider):
                _result = await asyncio.to_thread(
                    provider.suggest_action, img, goal, trajectory=_traj_text,
                ) or {}
            else:
                _result = await asyncio.to_thread(provider.suggest_action, img, goal) or {}
            record_stage(
                run_id or getattr(session, "job_id", "") or "",
                "inference", int((time.monotonic() - _inf_t0) * 1000),
            )
            return _result
        except Exception as exc:  # noqa: BLE001
            logger.info("[fetch.vision] suggest failed: %s", exc)
            return {"action": "error", "target": "", "reasoning": str(exc)}

    def _provider_accepts_trajectory(self, provider: object) -> bool:
        """True when `provider.suggest_action` accepts a `trajectory=` keyword.

        Decided by signature (like `_make_session`) rather than by catching a
        TypeError from the call, so a TypeError raised INSIDE a real provider is
        never misread as "no such parameter". Fakes with the bare `(img, goal)`
        shape keep working unchanged.
        """
        try:
            import inspect

            _params = inspect.signature(provider.suggest_action).parameters
            if "trajectory" in _params:
                return True
            return any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in _params.values()
            )
        except Exception:  # noqa: BLE001 — undecidable means "don't pass it"
            return False

    def _map_action(self, suggestion: dict) -> Optional[VisionAction]:
        """Map a VLM suggestion dict to a VisionAction, or None to stop.

        REQ-2 AC3 (this spec's T2): the suggestion's `target` is the resolvable
        handle and `value` is the `type` input, carried in its OWN field.
        `type` populates `VisionAction.value` from the suggestion's `value`
        and never embeds the input text in `target`. A `type` with no value is
        still a resolvable action here; the executor (browser_session.act,
        REQ-2 AC2/T8) records the missing-value case as a `last_error`
        observation rather than silently typing an empty string.
        """
        action = str((suggestion or {}).get("action", "")).strip().lower()
        target = str((suggestion or {}).get("target", "")).strip()
        # REQ-2 AC3: the input value rides its own field. Fall back to a
        # `text`/`input` alias a model may emit, but NEVER fold it into target.
        value = str(
            (suggestion or {}).get("value", "")
            or (suggestion or {}).get("text", "")
            or (suggestion or {}).get("input", "")
        ).strip()
        reason = str((suggestion or {}).get("reasoning", "")).strip()
        if action in ("error", "unknown", "done", "stop", "none"):
            return None
        kind = {
            "click": "click",
            "type": "type",
            "scroll": "scroll",
            "wait": "wait",
            "navigate": "navigate",
            "reload": "reload",
            "back": "back",
            "forward": "forward",
        }.get(action)
        if kind is None:
            return None
        return VisionAction(kind=kind, target=target or None, value=value or None, reason=reason)

    def _build_page(self, url: str, settled_dom: str, vision_text: str) -> PageData:
        """Build PageData for the outcome. Vision text wins when present and
        usable; otherwise a light strip of the settled DOM is the fallback so
        page_is_usable can judge it (REQ-17 AC5: vision text is not trusted by
        provenance — it is judged by the same predicate)."""
        import re

        def _strip(html: str) -> str:
            text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
            text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            return re.sub(r"\s+", " ", text).strip()

        md = vision_text or _strip(settled_dom or "")
        return PageData(
            url=url,
            title="",
            markdown=md,
            html=settled_dom or None,
            metadata={},
            error=None,
            html_bytes=len(settled_dom or ""),
        )


_vision_capability: Optional[FetchVisionCapability] = None


def get_fetch_vision() -> FetchVisionCapability:
    """Module-level singleton so the registry holds ONE vision capability."""
    global _vision_capability
    if _vision_capability is None:
        _vision_capability = FetchVisionCapability()
    return _vision_capability
