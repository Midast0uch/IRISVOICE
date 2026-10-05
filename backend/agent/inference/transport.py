"""
Transport protocol and concrete implementations for LLM inference.

Each transport implements ``Transport.generate()`` which returns
``(text, thinking, tool_calls)`` — the same 3-tuple shape used by
``AgentKernel._dispatch_api`` and friends, so callers can consume it
unchanged.

Parsing details preserved from source (``agent_kernel.py``):
- Streaming SSE chunkuation with ``data:`` prefix and ``[DONE]`` sentinel.
- ``reasoning_content`` / ``reasoning`` delta fields → raw thinking buffer.
- Tool-call accumulation across streaming deltas by index.
- ``_parse_thinking`` (tagged ``<think>`` / ``<thinking>`` + untagged preamble).
- Retry with exponential backoff on 429 rate-limit and transient errors.
- Flush callbacks with empty-string sentinel at end-of-stream.
"""

from __future__ import annotations

import json as _json
import logging
import re as _re
import time as _perf_t
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple, Protocol

from backend.agent.call_context import call_class, priority_index
from backend.agent.inference.errors import EmptyModelResponseError, MalformedToolCallError, RateLimitedError
from backend.agent.rate_meter import get_rate_meter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry-After parsing (REQ-2)
# ---------------------------------------------------------------------------

# Maximum delay we will ever wait for a Retry-After header, so a hostile or
# misconfigured provider cannot stall a voice turn indefinitely.
RETRY_AFTER_MAX_S = float(
    __import__("os").environ.get("IRIS_RETRY_AFTER_MAX_S", "30.0")
)


def parse_retry_after(header_value: Optional[str]) -> Optional[float]:
    """Parse an HTTP ``Retry-After`` header into a delay in seconds.

    Accepts both forms:
      * delta-seconds (e.g. ``"2"`` or ``"2.5"``) — integer or float seconds.
      * HTTP-date (e.g. ``"Wed, 21 Oct 2026 07:28:00 GMT"``) — converted to a
        delta against the local clock.

    Returns ``None`` when the header is absent, unparseable, or negative, so
    the caller falls back to local exponential backoff (REQ-2 AC4). A parsed
    value is clamped to ``[0, RETRY_AFTER_MAX_S]`` (REQ-2 AC3).

    This is a pure function with no I/O, so it is unit-testable without HTTP.
    """
    if not header_value:
        return None
    _value = header_value.strip()
    if not _value:
        return None

    # ── delta-seconds form ──────────────────────────────────────────────
    try:
        _delta = float(_value)
        if _delta < 0:
            return None
        return min(_delta, RETRY_AFTER_MAX_S)
    except ValueError:
        pass

    # ── HTTP-date form ──────────────────────────────────────────────────
    # email.utils.parsedate_to_datetime handles the RFC 1123 / RFC 850 /
    # asctime variants and returns a timezone-aware datetime when a zone is
    # present. We treat an unparseable date as "no header" (REQ-2 AC4).
    try:
        from email.utils import parsedate_to_datetime

        _dt = parsedate_to_datetime(_value)
    except (TypeError, ValueError):
        return None
    if _dt is None:
        return None

    _now = _perf_t.time()
    try:
        _epoch = _dt.timestamp()
    except (ValueError, OverflowError):
        return None
    _delta = _epoch - _now
    if _delta < 0:
        # Clock skew making the date appear to be in the past → clamp to 0
        # (REQ-2 edge case: negative delta clamped to 0).
        return 0.0
    return min(_delta, RETRY_AFTER_MAX_S)


def _sleep_on_429(
    attempt: int,
    response_headers: Any,
    provider_id: str = "unknown",
    budget_check: Optional[Callable[[], None]] = None,
) -> None:
    """Sleep before retrying a 429, per REQ-1 / REQ-2.

    Uses the server's ``Retry-After`` header when present (preferred, REQ-2
    AC1), else exponential backoff with jitter (``base=1.0, cap=8.0``, matching
    ``resilience.py:47-52``). Does NOT sleep on the final attempt
    (``attempt == 2``), per REQ-1 AC4 — no pointless terminal wait. Logs at
    WARNING with provider id, attempt number, and the actual sleep duration
    (REQ-1 AC5).

    ``attempt`` is the 0-indexed loop counter from ``for attempt in range(3)``,
    so ``attempt >= 2`` means this was the last attempt.

    ``budget_check`` (wedge fix, session 363 / pin_35af67d07c5f) is called
    BEFORE the sleep. A server-supplied ``Retry-After`` is an UNBOUNDED
    delay — a server under load can say "retry after 3600" and this sleep
    would honor it for an hour while the DER turn's 600 s budget never fires
    (the budget is only evaluated at the loop condition, between cycles).
    The check raises on exhaustion, which unwinds the ladder immediately.
    """
    import random

    if attempt >= 2:
        return  # final attempt — do not sleep before failing (REQ-1 AC4)
    if budget_check is not None:
        budget_check()
    _retry_after = parse_retry_after(
        getattr(response_headers, "get", lambda _: None)("Retry-After")
        if response_headers is not None
        else None
    )
    if _retry_after is not None:
        _delay = _retry_after
        _source = "retry-after"
    else:
        _delay = min(8.0, 1.0 * (2 ** attempt))
        _delay *= 1 + random.random() * 0.3  # jitter, per resilience.py:47-52
        _source = "exponential-backoff"
    logger.warning(
        "[transport] 429 rate-limit (attempt %d/3) -- sleeping %.2fs before "
        "retry (provider=%s, source=%s)",
        attempt + 1, _delay, provider_id, _source,
    )
    _perf_t.sleep(_delay)


# Per-minute request-limit headers, in priority order. PROVIDER-AGNOSTIC by
# design: nothing here names a vendor and no rpm value is hardcoded — the
# number always comes from whatever the provider sent, and is stored per
# quota_id so each provider learns its own ceiling independently.
#
# Only PER-MINUTE headers belong in this list, and that is a correctness
# requirement rather than a preference. Providers publish minute, hour and day
# limits under nearly identical names (a single response carries
# x-ratelimit-limit-requests-minute: 5 alongside -hour: 150 and -day: 2400).
# Reading an hour or day figure as rpm would set a ceiling hundreds of times too
# high and silently disable the gate — worse than not gating at all, because it
# would look configured. Anything whose period is unknown is ignored.
#
# Extra header names can be added for a provider that uses a different spelling
# via IRIS_RPM_LIMIT_HEADERS (comma-separated), so an unrecognised provider does
# not need a code change.
_RPM_HEADERS: Tuple[str, ...] = tuple(
    _h.strip().lower()
    for _h in (
        __import__("os").environ.get("IRIS_RPM_LIMIT_HEADERS", "").split(",")
        + [
            "x-ratelimit-limit-requests-minute",  # Cerebras and similar
            "anthropic-ratelimit-requests-limit",  # Anthropic (per minute)
            "x-ratelimit-limit-rpm",               # common explicit spelling
            "x-ratelimit-limit-requests",          # OpenAI-style (per minute)
        ]
    )
    if _h.strip()
)

# A published per-minute request limit outside this range is not believable and
# is far more likely to be a differently-scoped number under a familiar name.
# Ignoring it leaves the existing learned ceiling in place, which is the safe
# direction: the meter keeps learning from 429s as it always did.
_RPM_SANE_MIN = 1.0
_RPM_SANE_MAX = float(__import__("os").environ.get("IRIS_RPM_LIMIT_MAX", "10000"))


def _observe_advertised_limit(transport: "object", response_headers: Any) -> None:
    """Feed a provider-published per-minute request ceiling into the rate meter.

    The meter learned ceilings only by being REJECTED — halving on a 429 and
    probing back up from an initial guess of 30 rpm. Providers that publish
    their limit on every response were ignored, so each run re-guessed until it
    had collected enough rejections. Observed live at 5 rpm against a guess of
    30. Applies to any provider that sends one of ``_RPM_HEADERS``.

    Best-effort: metering must never break a call.
    """
    if response_headers is None:
        return
    try:
        _qid = getattr(transport, "_quota_id", None)
        if not _qid:
            return
        _get = getattr(response_headers, "get", None)
        if _get is None:
            return
        for _h in _RPM_HEADERS:
            _raw = _get(_h)
            if _raw is None:
                continue
            try:
                _rpm = float(str(_raw).strip())
            except (TypeError, ValueError):
                continue  # unparseable — try the next spelling
            if not (_RPM_SANE_MIN <= _rpm <= _RPM_SANE_MAX):
                logger.debug(
                    "[transport] ignoring implausible rpm header %s=%s for %s",
                    _h, _raw, _qid,
                )
                continue
            get_rate_meter().observe_advertised_limit(_qid, _rpm)
            return
    except Exception:  # pragma: no cover — metering is best-effort
        pass


def _record_attempt(transport: "object") -> None:
    """REQ-9 / root-cause of the 429 storm: record a logical LLM call attempt
    in the rate window BEFORE sending.

    The window-aware scheduler gate (phase_manager) paces admissions against
    ``window_stats.requests >= ceiling`` — but requests were recorded only on
    SUCCESS (``_record_success``), so every 429'd call was invisible to the
    window, the gate saw infinite headroom and admitted straight into an
    exhausted quota, and the transport's blind 3x retries (30s each, bypassing
    the gate) turned one logical call into 90s of dead time + amplified
    traffic. Recording the ATTEMPT (once per logical call; retries of the same
    call do not double-count) lets the gate actually hold new admissions while
    the provider is saturated. Best-effort — metering must never break a call.
    """
    try:
        _qid = getattr(transport, "_quota_id", None)
        if _qid:
            get_rate_meter().record_request(
                _qid,
                0,
                priority=priority_index(call_class()),
                estimated=True,
                label=getattr(transport, "_provider_id", "unknown"),
            )
    except Exception:  # pragma: no cover — metering is best-effort
        pass


# ---------------------------------------------------------------------------
# Thinking/reasoning extraction  (preserved from AgentKernel._parse_thinking)
# ---------------------------------------------------------------------------

_PREAMBLE_OPENERS = _re.compile(
    r"^(okay[,.]?|alright[,.]?|let me|i need to|i should|i will|"
    r"the user (is|has|wants|asked)|looking at|wait[,.]?|"
    r"so[,.]?\s+(the|i|let)|hmm[,.]?)",
    _re.IGNORECASE,
)


def parse_thinking(text: str) -> Tuple[str, str]:
    """Split model output into ``(thinking, clean_response)``.

    Handles three forms of chain-of-thought output:
    1. ``<think>…</think>`` XML tags (Qwen3 thinking mode).
    2. ``<thinking>…</thinking>`` XML tags (DeepSeek-style).
    3. Untagged preamble paragraphs where the model narrates its reasoning
       before a blank line that separates it from the real answer.
    """
    thinking_parts: List[str] = []

    # A tool-call-only response carries no text at all. Callers pass whatever
    # the provider returned, and every OpenAI-compatible provider returns null
    # content in that case — so accept it here rather than making each call site
    # remember to coerce (2026-08-16).
    if not text:
        return "", ""

    # ── Tagged blocks ────────────────────────────────────────────────
    for m in _re.finditer(r"<think>(.*?)</think>", text, flags=_re.DOTALL):
        thinking_parts.append(m.group(1).strip())
    text = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL)

    for m in _re.finditer(
        r"<thinking>(.*?)</thinking>", text, flags=_re.DOTALL
    ):
        thinking_parts.append(m.group(1).strip())
    text = _re.sub(r"<thinking>.*?</thinking>", "", text, flags=_re.DOTALL)

    text = text.strip()

    # ── Untagged reasoning preamble ──────────────────────────────────
    paragraphs = _re.split(r"\n{2,}", text)
    while len(paragraphs) > 1 and _PREAMBLE_OPENERS.match(
        paragraphs[0].strip()
    ):
        thinking_parts.append(paragraphs.pop(0).strip())
    clean = "\n\n".join(paragraphs).strip()

    return "\n\n".join(thinking_parts), clean


# ---------------------------------------------------------------------------
# Transport protocol  (structural typing via the Protocol class below)
# ---------------------------------------------------------------------------


class Transport(Protocol):
    """Protocol for LLM inference transports.

    Every concrete transport implements ``generate()`` with this exact
    signature and return shape.
    """

    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.6,
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
        timeout_s: Optional[float] = None,
        num_ctx: Optional[int] = None,
        budget_check: Optional[Callable[[], None]] = None,
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        """Run inference and return ``(text, thinking, tool_calls)``.

        ``num_ctx`` is the CONTEXT WINDOW the caller wants this model served
        with, in tokens (2026-09-27). It is a HINT: only a provider whose
        window the client actually owns can honour it.

          - Ollama (local models): honoured as ``options.num_ctx``. This is
            what makes the served window a fact we chose instead of the
            server's default, which nothing here could see.
          - in-process local GGUF: ignored. The window is fixed at load time
            (``n_ctx``) and cannot be changed per request.
          - hosted APIs and OpenAI-compatible endpoints: ignored. The provider
            fixes the window with the model and no client parameter raises it.

        For the ignore cases the ROUTER is responsible for the other half: it
        caps the request's own input to the resolved window, so a call can
        never be sent that is larger than the model can read.
        """
        ...

    def _record_success(
        self, text: str, usage: Optional[Dict[str, int]] = None
    ) -> None:
        """Record a completed (non-429) request against the meter.

        Called by subclasses after a successful ``generate``. Keyed by
        ``self._quota_id``; unmetered quotas are ignored by the meter. When
        *usage* holds real provider-reported tokens (D1), it is recorded with
        ``estimated=False``; otherwise the char/4 estimate is recorded with
        ``estimated=True`` — so real and estimated samples stay distinguishable
        in the meter. Metering must NEVER break a call, so all errors are
        swallowed (T2.2 / T2.5).
        """
        if self._quota_id is None:
            return
        try:
            if usage and usage.get("total_tokens"):
                _tokens, _estimated = usage["total_tokens"], False
            else:
                _tokens, _estimated = max(1, len(text) // 4), True  # estimated tokens: 4 chars ≈ 1 token
            get_rate_meter().record_request(
                self._quota_id,
                _tokens,
                priority=priority_index(call_class()),  # F9: thread real call class from context
                estimated=_estimated,
                label=getattr(self, "_provider_id", "unknown"),
            )
        except Exception as _e:  # pragma: no cover — metering is best-effort
            logger.debug("[transport] meter record failed: %s", _e)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _accumulate_tool_calls(
    tool_calls_acc: Dict[int, Dict[str, Any]],
    delta_tc_list: List[Dict[str, Any]],
) -> None:
    """Accumulate streaming tool-call deltas by index (in-place)."""
    for tc_item in delta_tc_list:
        idx = tc_item.get("index", 0)
        acc = tool_calls_acc.setdefault(
            idx,
            {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            },
        )
        if tc_item.get("id"):
            acc["id"] = tc_item["id"]
        fn = tc_item.get("function") or {}
        if fn.get("name"):
            acc["function"]["name"] = fn["name"]
        if fn.get("arguments"):
            acc["function"]["arguments"] += fn["arguments"]


# ---------------------------------------------------------------------------
# Real token-usage extraction (D1 fix)
# ---------------------------------------------------------------------------
#
# The pill on the frontend reads AgentKernel._tokens_used, which was only ever
# set from a restored conversation-context snapshot — never from a live
# inference call, because the API response's `usage` block was parsed nowhere
# in this module. These two helpers parse REAL provider-reported usage so the
# estimate (`len(text) // 4`) is used ONLY as a fallback when a provider
# genuinely omits usage — never as a substitute for it.


def _extract_usage(payload: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """Parse the OpenAI-shaped ``usage`` block from a chat/completions response.

    Returns ``{"prompt_tokens", "completion_tokens", "total_tokens"}`` when the
    provider reported real usage, or ``None`` when it is absent/malformed.
    Callers MUST treat ``None`` as "no real usage available" and fall back to
    the char/4 estimate rather than fabricating a number.
    """
    _usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(_usage, dict):
        return None
    try:
        _prompt = int(_usage.get("prompt_tokens") or 0)
        _completion = int(_usage.get("completion_tokens") or 0)
        _total = int(_usage.get("total_tokens") or (_prompt + _completion))
    except (TypeError, ValueError):
        return None
    if _total <= 0:
        return None
    return {
        "prompt_tokens": _prompt,
        "completion_tokens": _completion,
        "total_tokens": _total,
    }


def _extract_ollama_usage(payload: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """Parse Ollama's native (non-OpenAI-shaped) usage fields.

    Ollama's ``/api/chat`` response reports ``prompt_eval_count`` /
    ``eval_count`` at the top level instead of a nested ``usage`` object, so it
    needs its own extractor rather than ``_extract_usage``.
    """
    if not isinstance(payload, dict):
        return None
    _prompt_raw = payload.get("prompt_eval_count")
    _completion_raw = payload.get("eval_count")
    if _prompt_raw is None and _completion_raw is None:
        return None
    try:
        _prompt = int(_prompt_raw or 0)
        _completion = int(_completion_raw or 0)
    except (TypeError, ValueError):
        return None
    _total = _prompt + _completion
    if _total <= 0:
        return None
    return {
        "prompt_tokens": _prompt,
        "completion_tokens": _completion,
        "total_tokens": _total,
    }


# ---------------------------------------------------------------------------
# ApiHttpxTransport  — extracted from ``_dispatch_api`` (httpx, Bearer)
# ---------------------------------------------------------------------------


# Upper bound on the hidden-reasoning room added to an API call's max_tokens.
_REASONING_HEADROOM_MAX = 16384


# C6 stall bound (2026-10-02): a hosted model call far past its normal time is
# a provider stall, not work. Live run A3: mercury-2 node calls took 1-3 s, one
# took 121 s (the read timeout was the node's 300 s). The FIRST attempt waits
# at most max(_STALL_MIN_S, _STALL_FACTOR x p90 of the model's recent calls);
# then the existing retry runs once with the full timeout. Needs >= 5 samples.
# Keyed by (base url, model), bounded per key; read and written under a lock.
_STALL_MIN_S = 30.0
_STALL_FACTOR = 4.0
_STALL_SAMPLES = 30
_CALL_TIMES: Dict[Tuple[str, str], List[float]] = {}
_CALL_TIMES_LOCK = __import__("threading").Lock()
# The profile survives a restart (live run A6: a fresh backend had 1-2 samples,
# no bound, and Inception held one call 120 s before a 504). Loaded on first
# use; saved through ONE ordered writer lane, at most every 30 s.
_PROFILE_PATH = __import__("pathlib").Path(
    __import__("os").environ.get("IRIS_MODEL_CALL_PROFILE")
    or __import__("pathlib").Path(__file__).resolve().parents[3] / "data" / "model_call_times.json"
)
_PROFILE_SAVE_EVERY_S = 30.0
_profile_state = {"loaded": False, "saved_at": 0.0}


def _load_profile() -> None:
    """Fill _CALL_TIMES from disk once. Caller holds _CALL_TIMES_LOCK. Never raises."""
    if _profile_state["loaded"]:
        return
    _profile_state["loaded"] = True
    try:
        raw = _json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
        for key, times in (raw or {}).items():
            base, _, model = str(key).rpartition("|")
            if base and model and isinstance(times, list):
                vals = [float(t) for t in times if isinstance(t, (int, float)) and t > 0]
                if vals:
                    _CALL_TIMES.setdefault((base, model), vals[-_STALL_SAMPLES:])
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001 — a bad file is a missing profile
        logger.info("[ApiHttpx] call-time profile not loaded: %s", exc)


def _save_profile(snapshot: Dict[str, List[float]]) -> None:
    """Runs on lane('model_call_times'). Never raises."""
    try:
        tmp = _PROFILE_PATH.with_suffix(".tmp")
        tmp.write_text(_json.dumps(snapshot), encoding="utf-8")
        tmp.replace(_PROFILE_PATH)
    except Exception as exc:  # noqa: BLE001
        logger.info("[ApiHttpx] call-time profile not saved: %s", exc)


def _record_call_time(base: str, model: str, seconds: float) -> None:
    with _CALL_TIMES_LOCK:
        _load_profile()
        times = _CALL_TIMES.setdefault((base, model), [])
        times.append(seconds)
        del times[:-_STALL_SAMPLES]
        now = _perf_t.monotonic()
        if now - _profile_state["saved_at"] < _PROFILE_SAVE_EVERY_S:
            return
        _profile_state["saved_at"] = now
        snapshot = {f"{b}|{m}": list(t) for (b, m), t in _CALL_TIMES.items()}
    try:
        from backend.utils.durability_queue import lane

        lane("model_call_times").submit("save_profile", _save_profile, snapshot)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[ApiHttpx] profile save not queued: %s", exc)


def stall_bound(base: str, model: str, timeout_s: Optional[float]) -> Optional[float]:
    """The first-attempt read limit for this model, or None (no profile yet,
    or the bound would not be shorter than the caller's own timeout)."""
    with _CALL_TIMES_LOCK:
        _load_profile()
        times = sorted(_CALL_TIMES.get((base, model), ()))
    if len(times) < 5:
        return None
    p90 = times[min(len(times) - 1, int(len(times) * 0.9))]
    bound = max(_STALL_MIN_S, _STALL_FACTOR * p90)
    full = timeout_s or 60.0
    return bound if bound < full else None


# Hedged request (2026-10-04): a provider stall answered nothing for 30 s and
# then the SAME request answered in ~3 s (live: 12 of 148 mercury-2.5 calls
# took >= 30 s, p50 3.2 s, p90 4.6 s). Waiting out the stall bound cost 30 s a
# stall. When the first request has no answer after max(_HEDGE_MIN_S,
# _HEDGE_FACTOR x p90), the same request is sent again on the same client and
# the FIRST answer wins - nothing is cancelled to make room, the stall bound
# and its retry still stand behind it. A legitimately long call only costs a
# duplicate request.
_HEDGE_MIN_S = 3.0
_HEDGE_FACTOR = 2.0


def hedge_delay(base: str, model: str, read_s: Optional[float]) -> Optional[float]:
    """Seconds to wait for an answer before the second (hedge) request, or
    None (no profile yet, or not shorter than the read limit)."""
    with _CALL_TIMES_LOCK:
        _load_profile()
        times = sorted(_CALL_TIMES.get((base, model), ()))
    if len(times) < 5:
        return None
    p90 = times[min(len(times) - 1, int(len(times) * 0.9))]
    delay = max(_HEDGE_MIN_S, _HEDGE_FACTOR * p90)
    return delay if (read_s is None or delay < read_s) else None


def _post_hedged(client, url, headers, body, hedge_after: float, on_hedge) -> Any:
    """POST; with no answer after ``hedge_after`` s send the same request again
    and return the FIRST response. Raises the first error only when every
    request failed. The losing request ends when the caller closes ``client``."""
    import threading as _th

    cond = _th.Condition()
    results: List[Tuple[Any, Optional[BaseException]]] = []

    def _one() -> None:
        try:
            out = (client.post(url, headers=headers, json=body), None)
        except BaseException as exc:  # noqa: BLE001 - reported to the waiter
            out = (None, exc)
        with cond:
            results.append(out)
            cond.notify_all()

    _th.Thread(target=_one, daemon=True, name="api-request").start()
    with cond:
        cond.wait_for(lambda: bool(results), timeout=hedge_after)
        sent = 1
        if not results:
            on_hedge()
            _th.Thread(target=_one, daemon=True, name="api-hedge").start()
            sent = 2
        cond.wait_for(lambda: any(r[0] is not None for r in results) or len(results) >= sent)
        for resp, _exc in results:
            if resp is not None:
                return resp
        raise results[0][1]


class ApiHttpxTransport:
    """Remote API provider via direct httpx streaming.

    Preserves the full logic from ``AgentKernel._dispatch_api``:
    - 3-attempt retry with exponential backoff on 429 / transient errors.
    - Streaming SSE parsing (``data:`` lines, ``[DONE]`` sentinel).
    - ``reasoning_content`` / ``reasoning`` delta extraction.
    - Tool-call accumulation across streaming chunks.
    - Thinking-tag extraction via ``parse_thinking`` on the accumulated text.
    - Reasoning-content fallback when empty content but filled reasoning.

    Does **not** use LiteLLM — httpx avoids the thread-pool hang issue.
    """

    def __init__(
        self, api_base_url: str, api_key: str, quota_id: Optional[str] = None
    ) -> None:
        self._api_base_url = api_base_url.rstrip("/")
        self._api_key = api_key
        self._quota_id = quota_id
        # D1: real usage (prompt/completion/total tokens) parsed from the last
        # response, or None when the provider omitted it. Read by
        # InferenceRouter.generate() after each call so the kernel can credit
        # the pill's counter with a REAL number instead of an estimate.
        self.last_usage: Optional[Dict[str, int]] = None
        # model -> hidden reasoning tokens it was seen to spend (bounded: one
        # entry per model). A caller's max_tokens is the ANSWER budget; a model
        # that reasons in hidden tokens spends them from the same cap.
        # 2026-10-02, mercury-2.5 at max_tokens=1024: 818-979 reasoning tokens,
        # finish_reason=length, content 0-345 chars (empty or cut mid-plan).
        self._reasoning_headroom: Dict[str, int] = {}

    def _learn_reasoning(self, model: str, result: Dict[str, Any]) -> int:
        """Record the hidden reasoning tokens a response reports; return them."""
        try:
            _rt = int(((result.get("usage") or {}).get("completion_tokens_details") or {})
                      .get("reasoning_tokens") or 0)
        except (TypeError, ValueError, AttributeError):
            return 0
        if _rt > self._reasoning_headroom.get(model, 0):
            self._reasoning_headroom[model] = min(_rt, _REASONING_HEADROOM_MAX)
        return _rt

    def _record_success(
        self, text: str, usage: Optional[Dict[str, int]] = None
    ) -> None:
        """Record a completed (non-429) request against the meter.

        Keyed by ``self._quota_id``; unmetered quotas are ignored by the meter.
        When *usage* holds real provider-reported tokens (D1), it is recorded
        with ``estimated=False``; otherwise the char/4 estimate is recorded
        with ``estimated=True``. Metering must NEVER break a call, so all
        errors are swallowed.
        """
        if self._quota_id is None:
            return
        try:
            if usage and usage.get("total_tokens"):
                _tokens, _estimated = usage["total_tokens"], False
            else:
                _tokens, _estimated = max(1, len(text) // 4), True  # estimated tokens: 4 chars ≈ 1 token
            get_rate_meter().record_request(
                self._quota_id,
                _tokens,
                priority=priority_index(call_class()),  # F9: thread real call class from context
                estimated=_estimated,
                label=getattr(self, "_provider_id", "unknown"),
            )
            logger.info(
                "[ApiHttpxTransport] tokens recorded=%d estimated=%s provider=%s",
                _tokens, _estimated, getattr(self, "_provider_id", "unknown"),
            )
        except Exception as _e:  # pragma: no cover — metering is best-effort
            logger.debug("[transport] meter record failed: %s", _e)

    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.6,
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
        timeout_s: Optional[float] = None,
        num_ctx: Optional[int] = None,
        budget_check: Optional[Callable[[], None]] = None,
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        import httpx as _httpx
        from backend.utils.ssl_context import get_ssl_context

        # D1: reset per-call so a call that gets no usage (e.g. a stream the
        # provider didn't annotate) never inherits a PREVIOUS call's numbers.
        self.last_usage = None

        # num_ctx accepted and IGNORED (2026-09-27): a hosted API fixes the
        # context window with the model, and no request field raises it. The
        # router caps the input to the resolved window instead.

        # Guard against unset model
        if model in (
            "local-model",
            "Currently Loaded Model",
            "currently-loaded-model",
        ):
            raise RuntimeError(
                "No reasoning model configured. Set a model in Settings -> "
                "Model Selection before sending messages."
            )

        url = f"{self._api_base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        # REQ-1 (specs/local-model-lifecycle-sync): never emit `Authorization:
        # Bearer ` with an empty value — httpx rejects it as an illegal header
        # and the kernel crashes with `Illegal header value b'Bearer '`. The
        # router already raises ProviderNotReadyError(missing_api_key) before
        # building this transport, but guard here too so a transport built
        # directly (tests, legacy callers) fails closed instead of crashing.
        if self._api_key and self._api_key.strip():
            headers["Authorization"] = f"Bearer {self._api_key.strip()}"
        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            # answer budget + the hidden reasoning this model was seen to spend
            "max_tokens": max_tokens + self._reasoning_headroom.get(model, 0),
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        # ── Telemetry ────────────────────────────────────────────────
        try:
            msg_count = len(messages)
            total_chars = sum(
                len(str(m.get("content", ""))) for m in messages
            )
            logger.info(
                "[ApiHttpxTransport] model=%s messages=%d chars=%d "
                "max_tokens=%d temperature=%.2f",
                model,
                msg_count,
                total_chars,
                body["max_tokens"],
                temperature,
            )
        except Exception:
            pass

        if chunk_callback:
            _text, _think, _tools = self._stream(
                url,
                headers,
                body,
                model,
                messages,
                chunk_callback,
                reasoning_callback,
                timeout_s=timeout_s,
                budget_check=budget_check,
            )
        else:
            _text, _think, _tools = self._nonstream(
                url,
                headers,
                body,
                model,
                messages,
                timeout_s=timeout_s,
                budget_check=budget_check,
            )
        self._record_success(_text, self.last_usage)
        return _text, _think, _tools

    # -- streaming path -------------------------------------------------

    def _stream(
        self,
        url: str,
        headers: Dict[str, str],
        body: Dict[str, Any],
        model: str,
        messages: List[Dict[str, Any]],
        chunk_callback: Callable[[str], None],
        reasoning_callback: Optional[Callable[[str], None]] = None,
        timeout_s: Optional[float] = None,
        budget_check: Optional[Callable[[], None]] = None,
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        import httpx as _httpx
        from backend.utils.ssl_context import get_ssl_context

        _t0 = _perf_t.perf_counter()
        full_reply = ""
        _reasoning_buf: List[str] = []
        _tool_calls_acc: Dict[int, Dict[str, Any]] = {}
        _tool_calls: List[Dict[str, Any]] = []
        _rate_limited = False

        for attempt in range(3):
            _record_attempt(self)
            if budget_check is not None:
                budget_check()  # wedge fix: raises if the turn budget expired
            _stream_ok = False
            # Each attempt starts clean: a retry after a partial stream must not
            # append to the failed attempt's text or tool-call fragments (B16).
            full_reply = ""
            _reasoning_buf = []
            _tool_calls_acc = {}
            _emitted = False
            try:
                with _httpx.Client(
                    timeout=_httpx.Timeout(timeout_s or 60.0), verify=get_ssl_context()
                ) as _client:
                    with _client.stream(
                        "POST",
                        url,
                        headers=headers,
                        json={**body, "stream": True},
                    ) as _resp:
                        # ── 429 rate-limit → retry with backoff ─────
                        if _resp.status_code == 429:
                            _rate_limited = True
                            _retry_after = parse_retry_after(
                                _resp.headers.get("Retry-After")
                            )
                            try:
                                _resp.read()
                            except Exception:
                                pass
                            logger.warning(
                                "[ApiHttpx] 429 rate-limit (attempt %d/3) "
                                "-- retrying",
                                attempt + 1,
                            )
                            _sleep_on_429(
                                attempt,
                                _resp.headers,
                                getattr(self, "_provider_id", "unknown"),
                                budget_check,
                            )
                            get_rate_meter().observe_429(
                                self._quota_id, _retry_after
                            )
                            continue

                        # The provider publishes its own RPM ceiling on every response;
                        # learning it only from 429s meant guessing 30 against a real 5.
                        _observe_advertised_limit(self, _resp.headers)
                        if _resp.status_code != 200:
                            try:
                                _first = next(_resp.iter_bytes(), b"")
                                _err_detail = _first[:200].decode(
                                    "utf-8", errors="replace"
                                )
                            except Exception:
                                _err_detail = "(could not read error body)"
                            raise RuntimeError(
                                f"API returned {_resp.status_code}: "
                                f"{_err_detail}"
                            )

                        for _line in _resp.iter_lines():
                            if budget_check is not None:
                                # wedge fix: the read timeout is PER-READ, so a
                                # stream that drips one chunk every 50 s never
                                # times out and the turn budget never fires.
                                budget_check()
                            if not _line or not _line.startswith("data:"):
                                continue
                            _data = _line[5:].strip()
                            if _data == "[DONE]":
                                break
                            _chunk = _json.loads(_data)
                            # D1: some providers (when include_usage is
                            # requested, or unconditionally) send usage on a
                            # final chunk that carries an EMPTY choices list —
                            # so this check must happen BEFORE the
                            # `not _choices` skip below, or that chunk's usage
                            # is silently dropped.
                            _chunk_usage = _extract_usage(_chunk)
                            if _chunk_usage:
                                self.last_usage = _chunk_usage
                            _choices = _chunk.get("choices", [])
                            if not _choices:
                                continue
                            _delta = _choices[0].get("delta", {})

                            # Reasoning content
                            _r = _delta.get(
                                "reasoning_content"
                            ) or _delta.get("reasoning")
                            if _r:
                                _reasoning_buf.append(_r)
                                if reasoning_callback:
                                    _emitted = True
                                    reasoning_callback(_r)

                            # Text content
                            _c = _delta.get("content")
                            if _c:
                                full_reply += _c
                                _emitted = True
                                chunk_callback(_c)

                            # Tool calls
                            _accumulate_tool_calls(
                                _tool_calls_acc,
                                _delta.get("tool_calls") or [],
                            )
                        _stream_ok = True
            except RuntimeError:
                raise
            except Exception as _e:
                logger.warning(
                    "[ApiHttpx] stream error (attempt %d/3): %s",
                    attempt + 1,
                    _e,
                )
                # Text already reached the user: a retry would stream it a
                # second time after the partial copy (execution audit B16).
                if attempt == 2 or _emitted:
                    raise
            if _stream_ok:
                break
            if attempt < 2:
                _perf_t.sleep(1.0 * (2**attempt))

        _tool_calls = list(_tool_calls_acc.values())
        reasoning_text = "".join(_reasoning_buf)

        if reasoning_callback:
            reasoning_callback("")  # end marker
        chunk_callback("")  # force-flush

        # All retries exhausted due to rate-limiting → report honestly
        # (REQ-3 AC2). Do NOT fall through to the "(I see.)" filler, which is
        # reserved for a genuine empty-content 200 (REQ-3 AC3).
        if not _stream_ok and _rate_limited:
            raise RateLimitedError(
                getattr(self, "_provider_id", "unknown"), attempt + 1
            )

        # Reasoning fallback: some models return answer in reasoning_content
        # with empty content.
        if not full_reply.strip() and reasoning_text.strip() and not _tool_calls:
            return reasoning_text, reasoning_text, []

        thinking, clean = parse_thinking(full_reply)
        return clean or "(I see.)", thinking, _tool_calls

    # -- non-streaming path --------------------------------------------

    def _nonstream(
        self,
        url: str,
        headers: Dict[str, str],
        body: Dict[str, Any],
        model: str,
        messages: List[Dict[str, Any]],
        timeout_s: Optional[float] = None,
        budget_check: Optional[Callable[[], None]] = None,
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        import httpx as _httpx
        from backend.utils.ssl_context import get_ssl_context

        _t0 = _perf_t.perf_counter()
        result = None
        _rate_limited = False
        _grown = False
        _stall = stall_bound(self._api_base_url, model, timeout_s)
        for attempt in range(3):
            _record_attempt(self)
            if budget_check is not None:
                budget_check()  # wedge fix: raises if the turn budget expired
            _ta = _perf_t.perf_counter()
            _read = _stall if (attempt == 0 and _stall) else (timeout_s or 60.0)
            _hedge = hedge_delay(self._api_base_url, model, _read) if attempt == 0 else None
            try:
                with _httpx.Client(
                    timeout=_httpx.Timeout(timeout_s or 60.0, read=_read), verify=get_ssl_context()
                ) as _client:
                    if _hedge:
                        def _on_hedge(_h=_hedge):
                            _record_attempt(self)  # the hedge is a request too
                            logger.warning(
                                "[ApiHttpx] hedge: model=%s no answer in %.1f s (2 x p90) "
                                "-- sending the same request again, first answer wins",
                                model, _h,
                            )

                        _resp = _post_hedged(_client, url, headers, body, _hedge, _on_hedge)
                    else:
                        _resp = _client.post(url, headers=headers, json=body)
                    if _resp.status_code == 429:
                        _rate_limited = True
                        _retry_after = parse_retry_after(
                            _resp.headers.get("Retry-After")
                        )
                        logger.warning(
                            "[ApiHttpx] 429 rate-limit (attempt %d/3) "
                            "-- retrying",
                            attempt + 1,
                        )
                        _sleep_on_429(
                            attempt,
                            _resp.headers,
                            getattr(self, "_provider_id", "unknown"),
                            budget_check,
                        )
                        get_rate_meter().observe_429(
                            self._quota_id, _retry_after
                        )
                        continue
                    # The provider publishes its own RPM ceiling on every response;
                    # learning it only from 429s meant guessing 30 against a real 5.
                    _observe_advertised_limit(self, _resp.headers)
                    # A gateway 5xx is the provider's transient fault: retry,
                    # so the caller (a node) keeps its history. Eval c03
                    # 2026-10-02: Inception answered 504 after a 120 s stall,
                    # the node failed and its step ran again from the start.
                    # One retry after 1 s was not enough: 2026-10-05, 11 of 24
                    # single retries got a second 503 ~1.7 s later and the
                    # node failed (r09 conv-871). Up to the third attempt,
                    # waiting 1 s then 3 s (owner-approved).
                    if _resp.status_code in (502, 503, 504) and attempt < 2:
                        logger.warning(
                            "[ApiHttpx] provider %d (attempt %d/3) -- retrying",
                            _resp.status_code, attempt + 1,
                        )
                        _perf_t.sleep(1.0 + 2.0 * attempt)
                        continue
                    if _resp.status_code != 200:
                        raise RuntimeError(
                            f"API returned {_resp.status_code}: "
                            f"{_resp.text[:200]}"
                        )
                    result = _resp.json()
                    # Cut at the cap by hidden reasoning: the SAME payload
                    # would be cut again, so resend once with room for it.
                    _rt = self._learn_reasoning(model, result)
                    if (_rt and not _grown and attempt < 2
                            and result.get("choices", [{}])[0].get("finish_reason") == "length"):
                        _grown = True
                        body = {**body, "max_tokens": body["max_tokens"]
                                + min(2 * _rt, _REASONING_HEADROOM_MAX)}
                        logger.warning(
                            "[ApiHttpx] answer cut by %d hidden reasoning tokens "
                            "(finish_reason=length) -- resending with max_tokens=%d",
                            _rt, body["max_tokens"],
                        )
                        continue
                    # REQ-6 AC6.3: an empty response (no content AND no
                    # tool_calls) retries the SAME payload before raising —
                    # the Empty disease hit 4 downstream call sites
                    # (step-result processing, final synthesis, decision box,
                    # sub-loop); one retry here covers all of them. The final
                    # attempt falls through to the post-loop empty check which
                    # keeps the existing "Empty response from API" error.
                    _msg = result.get("choices", [{}])[0].get("message", {})
                    _reply = _msg.get("content") or ""
                    _tool_calls = _msg.get("tool_calls") or []
                    if not _reply and not _tool_calls and attempt < 2:
                        logger.warning(
                            "[ApiHttpx] empty response (attempt %d/3) "
                            "-- retrying same payload",
                            attempt + 1,
                        )
                        continue
                    _record_call_time(self._api_base_url, model, _perf_t.perf_counter() - _ta)
                    break
            except RuntimeError:
                raise
            except Exception as _e:
                if attempt == 0 and _stall and isinstance(_e, _httpx.ReadTimeout):
                    logger.warning(
                        "[ApiHttpx] stall: model=%s gave no answer in %.0f s "
                        "(its normal p90 x %.0f) -- retrying once with the full timeout",
                        model, _stall, _STALL_FACTOR,
                    )
                    continue
                logger.warning(
                    "[ApiHttpx] request error (attempt %d/3): %s",
                    attempt + 1,
                    _e,
                )
                if attempt == 2:
                    raise
        if result is None:
            if _rate_limited:
                raise RateLimitedError(
                    getattr(self, "_provider_id", "unknown"), 3
                )
            raise RuntimeError("API request failed after retries")

        # D1: real usage lives on the top-level response, not per-choice.
        self.last_usage = _extract_usage(result)

        _msg = result.get("choices", [{}])[0].get("message", {})
        # `.get("content", "")` returns None when the key is PRESENT and null —
        # the default only applies to a missing key. An OpenAI-compatible API
        # sets content=null on a tool-call-only response, which is the normal
        # shape for every tool call, so this fed None straight into
        # parse_thinking and crashed the step with "expected string or
        # bytes-like object, got 'NoneType'" (2026-08-16, DER step 5).
        _reply = _msg.get("content") or ""
        _tool_calls = _msg.get("tool_calls") or []

        if not _reply and not _tool_calls:
            raise EmptyModelResponseError("Empty response from API")

        thinking, clean = parse_thinking(_reply)
        return clean or "(I see.)", thinking, _tool_calls


# ---------------------------------------------------------------------------
# OpenAICompatTransport  — extracted from ``_dispatch_openai_compat``
# ---------------------------------------------------------------------------


class OpenAICompatTransport:
    """Local OpenAI-compatible endpoint via httpx (LM Studio, vllm, llama.cpp).

    Preserves the full logic from ``AgentKernel._dispatch_openai_compat``:
    - Tries ``/v1/chat/completions`` path first, falls back to
      ``/chat/completions`` (older LM Studio).
    - ``extra_body`` with ``chat_template_kwargs.enable_thinking`` heuristic.
    - Same streaming/thinking/tool-call parsing as ``ApiHttpxTransport``.
    - 3-attempt retry with exponential backoff.
    """

    def __init__(self, endpoint: str, quota_id: Optional[str] = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._quota_id = quota_id
        # D1: real usage parsed from the last response, or None when the
        # local server omitted it. Read by InferenceRouter.generate().
        self.last_usage: Optional[Dict[str, int]] = None

    def _record_success(
        self, text: str, usage: Optional[Dict[str, int]] = None
    ) -> None:
        """Record a completed (non-429) request against the meter.

        When *usage* holds real provider-reported tokens (D1), it is recorded
        with ``estimated=False``; otherwise the char/4 estimate is recorded
        with ``estimated=True``.
        """
        if self._quota_id is None:
            return
        try:
            if usage and usage.get("total_tokens"):
                _tokens, _estimated = usage["total_tokens"], False
            else:
                _tokens, _estimated = max(1, len(text) // 4), True  # estimated tokens: 4 chars ≈ 1 token
            get_rate_meter().record_request(
                self._quota_id,
                _tokens,
                priority=priority_index(call_class()),  # F9: thread real call class from context
                estimated=_estimated,
                label=getattr(self, "_provider_id", "unknown"),
            )
            logger.info(
                "[OpenAICompatTransport] tokens recorded=%d estimated=%s provider=%s",
                _tokens, _estimated, getattr(self, "_provider_id", "unknown"),
            )
        except Exception as _e:  # pragma: no cover — metering is best-effort
            logger.debug("[transport] meter record failed: %s", _e)

    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.6,
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
        timeout_s: Optional[float] = None,
        num_ctx: Optional[int] = None,
        budget_check: Optional[Callable[[], None]] = None,
        thinking: Optional[bool] = None,
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        import httpx as _httpx
        from backend.utils.ssl_context import get_ssl_context

        # D1: reset per-call (see ApiHttpxTransport.generate for rationale).
        self.last_usage = None

        # num_ctx accepted and IGNORED (2026-09-27): an OpenAI-compatible
        # endpoint fixes its window when the SERVER starts (llama-server
        # --ctx-size, vLLM max_model_len), not per request. The router caps the
        # input to the resolved window instead.

        _url = f"{self._endpoint}/v1/chat/completions"
        _url_v1 = f"{self._endpoint}/chat/completions"

        _body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            _body["tools"] = tools
            _body["tool_choice"] = "auto"

        # LM Studio extra_body for thinking template hints
        # (enable_thinking heuristic is delegated to the caller; we always
        #  send it as a hint since the backend will ignore if unsupported)
        _body["extra_body"] = {
            "chat_template_kwargs": {"enable_thinking": True}
        }
        # A per-call choice (2026-10-01): node tool calls on the local tool
        # model ask for no hidden reasoning. llama-server reads
        # chat_template_kwargs at the TOP level of the request; "extra_body" is
        # an OpenAI-client convention it does not read.
        if thinking is not None:
            _body["chat_template_kwargs"] = {"enable_thinking": bool(thinking)}
            _body["extra_body"] = {"chat_template_kwargs": {"enable_thinking": bool(thinking)}}

        if chunk_callback:
            _text, _think, _tools = self._stream(
                _url,
                _url_v1,
                _body,
                chunk_callback,
                reasoning_callback,
                timeout_s=timeout_s,
                budget_check=budget_check,
            )
        else:
            _text, _think, _tools = self._nonstream(
                _url, _url_v1, _body, timeout_s=timeout_s, budget_check=budget_check
            )
        self._record_success(_text, self.last_usage)
        return _text, _think, _tools

    # -- streaming path -------------------------------------------------

    def _stream(
        self,
        url: str,
        url_v1: str,
        body: Dict[str, Any],
        chunk_callback: Callable[[str], None],
        reasoning_callback: Optional[Callable[[str], None]] = None,
        timeout_s: Optional[float] = None,
        budget_check: Optional[Callable[[], None]] = None,
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        import httpx as _httpx
        from backend.utils.ssl_context import get_ssl_context

        _t0 = _perf_t.perf_counter()
        full_reply = ""
        _reasoning_buf: List[str] = []
        _tool_calls_acc: Dict[int, Dict[str, Any]] = {}
        _tool_calls: List[Dict[str, Any]] = []
        _rate_limited = False

        for attempt in range(3):
            _record_attempt(self)
            if budget_check is not None:
                budget_check()  # wedge fix: raises if the turn budget expired
            _stream_ok = False
            # Each attempt starts clean: a retry after a partial stream must not
            # append to the failed attempt's text or tool-call fragments (B16).
            full_reply = ""
            _reasoning_buf = []
            _tool_calls_acc = {}
            _emitted = False
            try:
                with _httpx.Client(
                    timeout=_httpx.Timeout(timeout_s or 60.0), verify=get_ssl_context()
                ) as _client:
                    # Try standard v1 path, fall back to v1-less path
                    for _try_url in [url, url_v1]:
                        try:
                            _resp = _client.stream(
                                "POST",
                                _try_url,
                                headers={
                                    "Content-Type": "application/json"
                                },
                                json={**body, "stream": True},
                            )
                            break
                        except Exception:
                            continue
                    else:
                        raise RuntimeError(
                            f"Could not connect to "
                            f"{self._endpoint}"
                        )

                    with _resp as _stream:
                        if _stream.status_code == 429:
                            _rate_limited = True
                            _retry_after = parse_retry_after(
                                _stream.headers.get("Retry-After")
                            )
                            try:
                                _stream.read()
                            except Exception:
                                pass
                            logger.warning(
                                "[OpenAICompat] 429 rate-limit "
                                "(attempt %d/3) -- retrying",
                                attempt + 1,
                            )
                            _sleep_on_429(
                                attempt,
                                _stream.headers,
                                getattr(self, "_provider_id", "unknown"),
                                budget_check,
                            )
                            get_rate_meter().observe_429(
                                self._quota_id, _retry_after
                            )
                            continue
                        if _stream.status_code != 200:
                            # Streaming response: reading `.text` raises
                            # ResponseNotRead ("Attempted to access streaming
                            # response content, without having called read()")
                            # because httpx hasn't consumed the body yet. Read
                            # the first chunk manually for the error detail.
                            try:
                                _first = next(_stream.iter_bytes(), b"")
                                _err_detail = _first[:200].decode(
                                    "utf-8", errors="replace"
                                )
                            except Exception:
                                _err_detail = "(could not read error body)"
                            raise RuntimeError(
                                f"{self._endpoint} returned "
                                f"{_stream.status_code}: "
                                f"{_err_detail}"
                            )
                        for _line in _stream.iter_lines():
                            if budget_check is not None:
                                # wedge fix: the read timeout is PER-READ, so a
                                # stream that drips one chunk every 50 s never
                                # times out and the turn budget never fires.
                                budget_check()
                            if not _line or not _line.startswith("data:"):
                                continue
                            _data = _line[5:].strip()
                            if _data == "[DONE]":
                                break
                            _chunk = _json.loads(_data)
                            # D1: see ApiHttpxTransport._stream — usage may
                            # ride an empty-choices final chunk.
                            _chunk_usage = _extract_usage(_chunk)
                            if _chunk_usage:
                                self.last_usage = _chunk_usage
                            _choices = _chunk.get("choices", [])
                            if not _choices:
                                continue
                            _delta = _choices[0].get("delta", {})

                            _r = _delta.get(
                                "reasoning_content"
                            ) or _delta.get("reasoning")
                            if _r:
                                _reasoning_buf.append(_r)
                                if reasoning_callback:
                                    _emitted = True
                                    reasoning_callback(_r)

                            _c = _delta.get("content")
                            if _c:
                                full_reply += _c
                                _emitted = True
                                chunk_callback(_c)

                            _accumulate_tool_calls(
                                _tool_calls_acc,
                                _delta.get("tool_calls") or [],
                            )
                        _stream_ok = True
            except RuntimeError:
                raise
            except Exception as _e:
                logger.warning(
                    "[OpenAICompat] stream error (attempt %d/3): %s",
                    attempt + 1,
                    _e,
                )
                # Text already reached the user: a retry would stream it a
                # second time after the partial copy (execution audit B16).
                if attempt == 2 or _emitted:
                    raise
            if _stream_ok:
                break
            if attempt < 2:
                _perf_t.sleep(1.0 * (2**attempt))

        _tool_calls = list(_tool_calls_acc.values())
        reasoning_text = "".join(_reasoning_buf)

        if reasoning_callback:
            reasoning_callback("")
        chunk_callback("")

        # All retries exhausted due to rate-limiting → report honestly
        # (REQ-3 AC2). Do NOT fall through to the "(I see.)" filler, which is
        # reserved for a genuine empty-content 200 (REQ-3 AC3).
        if not _stream_ok and _rate_limited:
            raise RateLimitedError(
                getattr(self, "_provider_id", "unknown"), attempt + 1
            )

        if not full_reply.strip() and reasoning_text.strip() and not _tool_calls:
            return reasoning_text, reasoning_text, []

        thinking, clean = parse_thinking(full_reply)
        return clean or "(I see.)", thinking, _tool_calls

    # -- non-streaming path --------------------------------------------

    def _nonstream(
        self,
        url: str,
        url_v1: str,
        body: Dict[str, Any],
        timeout_s: Optional[float] = None,
        budget_check: Optional[Callable[[], None]] = None,
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        # `timeout_s` was USED below (the client is built with
        # `timeout_s or 60.0`) but was missing from this signature, so
        # `generate()`'s call raised
        #   OpenAICompatTransport._nonstream() got an unexpected keyword
        #   argument 'timeout_s'
        # and EVERY call through this transport failed before a request was sent
        # (2026-09-27). It went unnoticed because no shipped provider used this
        # kind until a SERVER-loaded local model started routing here - see
        # InferenceRouter._local_http_endpoint. The parameter is restored rather
        # than the caller changed, because the body already depends on it.
        import httpx as _httpx
        from backend.utils.ssl_context import get_ssl_context

        result = None
        _rate_limited = False
        for attempt in range(3):
            _record_attempt(self)
            if budget_check is not None:
                budget_check()  # wedge fix: raises if the turn budget expired
            try:
                with _httpx.Client(
                    timeout=_httpx.Timeout(timeout_s or 60.0), verify=get_ssl_context()
                ) as _client:
                    _last_5xx = None
                    for _try_url in [url, url_v1]:
                        try:
                            _resp = _client.post(
                                _try_url,
                                headers={
                                    "Content-Type": "application/json"
                                },
                                json=body,
                            )
                            if _resp.status_code >= 500:
                                _last_5xx = _resp
                            if _resp.status_code == 429:
                                _rate_limited = True
                                _retry_after = parse_retry_after(
                                    _resp.headers.get("Retry-After")
                                )
                                logger.warning(
                                    "[OpenAICompat] 429 rate-limit "
                                    "(attempt %d/3) -- retrying",
                                    attempt + 1,
                                )
                                _sleep_on_429(
                                    attempt,
                                    _resp.headers,
                                    getattr(self, "_provider_id", "unknown"),
                                    budget_check,
                                )
                                get_rate_meter().observe_429(
                                    self._quota_id, _retry_after
                                )
                                break
                            if _resp.status_code < 500:
                                break
                        except Exception:
                            continue
                    else:
                        # The server ANSWERED with a 5xx: say what it said. Only
                        # no answer at all is a connection failure.
                        if _last_5xx is not None:
                            _detail = _last_5xx.text or ""
                            if "Failed to parse tool call arguments" in _detail:
                                raise MalformedToolCallError(self._endpoint, _detail[:400])
                            raise RuntimeError(
                                f"{self._endpoint} returned "
                                f"{_last_5xx.status_code}: {_detail[:200]}"
                            )
                        raise RuntimeError(
                            f"Could not connect to "
                            f"{self._endpoint}"
                        )

                    if _resp.status_code == 429:
                        continue
                    # The provider publishes its own RPM ceiling on every response;
                    # learning it only from 429s meant guessing 30 against a real 5.
                    _observe_advertised_limit(self, _resp.headers)
                    if _resp.status_code != 200:
                        raise RuntimeError(
                            f"{self._endpoint} returned "
                            f"{_resp.status_code}: "
                            f"{_resp.text[:200]}"
                        )
                    result = _resp.json()
                    break
            except RuntimeError:
                raise
            except Exception as _e:
                logger.warning(
                    "[OpenAICompat] request error (attempt %d/3): %s",
                    attempt + 1,
                    _e,
                )
                if attempt == 2:
                    raise
        if result is None:
            if _rate_limited:
                raise RateLimitedError(
                    getattr(self, "_provider_id", "unknown"), 3
                )
            raise RuntimeError(
                f"Request to {self._endpoint} failed after retries"
            )

        # D1: real usage (when the local server reports it).
        self.last_usage = _extract_usage(result)

        _msg = result.get("choices", [{}])[0].get("message", {})
        # null content on a tool-call-only response — see the note above.
        _reply = _msg.get("content") or ""
        _tool_calls = _msg.get("tool_calls") or []

        if not _reply and not _tool_calls:
            # NAME THE REAL PROVIDER (2026-09-27). This transport is generic — it
            # serves llama-server (127.0.0.1:8082), llamafile, vLLM and LM Studio
            # alike — but the message hardcoded "LM Studio". A live failure on the
            # LOCAL 8082 model was therefore reported as an LM Studio problem and
            # sent the investigation to port 1234, where nothing runs:
            #   "[WARNING] LM Studio not reachable at http://localhost:1234"
            # A wrong provider name in an error is worse than no name: it points
            # at the one place the fault is NOT.
            raise EmptyModelResponseError(f"Empty response from {self._endpoint}")

        thinking, clean = parse_thinking(_reply)
        return clean or "(I see.)", thinking, _tool_calls


# ---------------------------------------------------------------------------
# InProcessTransport  — extracted from ``_dispatch_inprocess``
# ---------------------------------------------------------------------------


class InProcessTransport:
    """In-process local model inference.

    Delegates to a ``model_manager`` object that implements a ``generate``
    method accepting a prompt string and returning a response string.

    The model manager can be set via the constructor or via
    :meth:`set_model_manager`.  It is **not** owned by this transport —
    the caller (typically the kernel) is responsible for loading/unloading.
    """

    def __init__(
        self, model_manager: Optional[Any] = None, quota_id: Optional[str] = None
    ) -> None:
        self._model_manager = model_manager
        self._quota_id = quota_id

    def set_model_manager(self, mgr: Any) -> None:
        """Replace the model manager reference (e.g. after loading a model)."""
        self._model_manager = mgr

    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.6,
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
        timeout_s: Optional[float] = None,
        num_ctx: Optional[int] = None,
        budget_check: Optional[Callable[[], None]] = None,
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        if budget_check is not None:
            budget_check()  # wedge fix: choke point at the call entry

        # num_ctx accepted and IGNORED (2026-09-27): an in-process local GGUF
        # has its window fixed at LOAD time (`n_ctx`, fixed by the profile
        # duty) and llama.cpp cannot change it per request. Changing it means
        # reloading the model, which the loader already does.
        # Lazy import to avoid circular dependency at module level
        if self._model_manager is not None:
            mgr = self._model_manager
        else:
            # Attempt to discover a model from the global router
            try:
                from backend.agent.model_router import ModelRouter

                router = ModelRouter()
                mgr = router.get_reasoning_model()
            except Exception:
                mgr = None
            # LAST RESORT (2026-09-27): the PROCESS-WIDE local model manager.
            # A router can be built before the manager is attached to it (or
            # rebuilt afterwards), and the old behaviour then raised
            # "No local model loaded for in-process inference" on every call.
            # Measured cost: the planner timed out, retried, fell back to HTTP
            # and only then answered - roughly 1.8 minutes per message for a
            # 2.6B model that is fully offloaded to the GPU and answers in well
            # under a second. Resolving the singleton here removes the failure
            # mode instead of depending on attach ordering.
            if mgr is None:
                try:
                    from backend.agent.local_model_manager import (
                        get_local_model_manager,
                    )

                    mgr = get_local_model_manager()
                except Exception:  # noqa: BLE001 — stay None, caller degrades
                    mgr = None

        if mgr is None:
            raise RuntimeError("No local model loaded for in-process inference")

        # Preferred path (2026-09-27): a LocalModelManager does NOT expose a
        # `generate(prompt)` method - the call below raised
        #   'LocalModelManager' object has no attribute 'generate'
        # on every planning call, which meant no plan, which meant the DER
        # branch was never taken and the step consumers wrote no rows. What the
        # manager DOES expose is an OpenAI-compatible adapter bound to the local
        # server, so use it when it is available and keep `generate` as the
        # legacy fallback for any manager that still implements it.
        _adapter = None
        _getter = getattr(mgr, "get_inprocess_client", None)
        if callable(_getter):
            try:
                _adapter = _getter()
            except Exception:  # noqa: BLE001 — fall back to the legacy call
                _adapter = None

        if _adapter is not None:
            _resp = _adapter.chat.completions.create(
                model=model or "local-model",
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            _msg = _resp.choices[0].message
            reply = (getattr(_msg, "content", None) or "")
            _tool_calls = list(getattr(_msg, "tool_calls", None) or [])
            if chunk_callback and reply:
                chunk_callback(reply)
                chunk_callback("")
            thinking, clean = parse_thinking(reply)
            return clean or "(I see.)", thinking, _tool_calls

        # Legacy path: a manager that takes a single prompt string.
        prompt = (
            messages[-1].get("content", "") if messages else ""
        )
        reply = mgr.generate(prompt)

        # ── FIX (session 154): Invoke chunk_callback on non-streaming path
        # Without this, the TTS pipeline never sees the response text.
        if chunk_callback and reply:
            chunk_callback(reply)
            chunk_callback("")  # force-flush end-of-stream

        thinking, clean = parse_thinking(reply)
        return clean or "(I see.)", thinking, []


# ---------------------------------------------------------------------------
# OllamaTransport  — extracted from the inline ``11434`` call in
#                   ``_respond_direct`` and ``infer``
# ---------------------------------------------------------------------------


def _to_ollama_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """OpenAI-shaped history -> Ollama /api/chat history.

    Ollama wants ``tool_calls[].function.arguments`` as an OBJECT (the kernel
    keeps OpenAI's JSON string) and names a tool result with ``tool_name``.
    Plain messages pass through unchanged.
    """
    out: List[Dict[str, Any]] = []
    for m in messages:
        if m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                fn = dict(tc.get("function") or {})
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        fn["arguments"] = _json.loads(args) if args.strip() else {}
                    except ValueError:
                        fn["arguments"] = {"__raw_arguments__": args}
                calls.append({"function": {"name": fn.get("name", ""), "arguments": fn.get("arguments") or {}}})
            m = {"role": m.get("role", "assistant"), "content": m.get("content") or "", "tool_calls": calls}
        elif m.get("role") == "tool":
            m = {"role": "tool", "content": m.get("content") or "", "tool_name": m.get("name", "")}
        elif isinstance(m.get("content"), list):
            # OpenAI content parts -> Ollama text + "images" (bare base64), e.g.
            # the node's marked page screenshot (V8).
            texts, images = [], []
            for part in m["content"]:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    texts.append(str(part.get("text") or ""))
                elif part.get("type") == "image_url":
                    url = str((part.get("image_url") or {}).get("url") or "")
                    images.append(url.split(",", 1)[1] if url.startswith("data:") and "," in url else url)
            m = {"role": m.get("role", "user"), "content": "\n".join(texts)}
            if images:
                m["images"] = images
        out.append(m)
    return out


def _from_ollama_tool_call(index: int, tc: Dict[str, Any]) -> Dict[str, Any]:
    """Ollama tool call -> the OpenAI shape the kernel consumes (arguments as a JSON string)."""
    fn = tc.get("function") or {}
    args = fn.get("arguments")
    return {
        "id": tc.get("id") or f"call_{index}",
        "type": "function",
        "function": {
            "name": fn.get("name", ""),
            "arguments": args if isinstance(args, str) else _json.dumps(args or {}),
        },
    }


class OllamaTransport:
    """Ollama native API via https.

    Preserves the inline call from ``agent_kernel.py`` (``requests.post``
    replaced with httpx for consistency with other transports).

    No streaming support — Ollama native API is called non-streaming.
    Tools: sent when given; tool calls come back in the OpenAI shape.
    """

    def __init__(
        self, endpoint: str = "http://localhost:11434", quota_id: Optional[str] = None
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._quota_id = quota_id
        # D1: real usage parsed from the last response (Ollama's own
        # prompt_eval_count/eval_count fields — not OpenAI-shaped), or None.
        self.last_usage: Optional[Dict[str, int]] = None

    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.6,
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
        timeout_s: Optional[float] = None,
        num_ctx: Optional[int] = None,
        budget_check: Optional[Callable[[], None]] = None,
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        import httpx as _httpx

        if budget_check is not None:
            budget_check()  # wedge fix: choke point at the call entry

        # D1: reset per-call (see ApiHttpxTransport.generate for rationale).
        self.last_usage = None

        url = f"{self._endpoint}/api/chat"
        payload = {
            "model": model,
            "messages": _to_ollama_messages(messages),
            "stream": False,
            # Session-345 live finding: thinking models (gpt-oss:120b-cloud)
            # can place the ENTIRE answer in message.thinking while content
            # is empty or a stub ("Empty response from Ollama" turn-kill on
            # 2026-09-21 03:58; 15-char synthesis stub at 04:37). Thinking is
            # never consumed downstream — parse_thinking strips it — so the
            # hidden pass is pure cost. Disable it at the source: the model
            # then answers directly in content (faster, fewer tokens).
            "think": False,
        }

        # CONTEXT WINDOW (2026-09-27). Ollama is one of the two providers whose
        # window the CLIENT owns, and until now nothing here ever asked for
        # one: `num_ctx` appeared nowhere in the backend. So the served window
        # was whatever the server happened to default to, which no part of this
        # app could see or record, and the resolver fell back to 8192 - which
        # then capped the WHOLE DER turn, because the turn budget is the
        # smaller window of the two roles.
        #
        # Guard: never send it for a `-cloud` model. Those run on ollama.com,
        # where the window belongs to the server and a request field cannot
        # raise it (the same reason the catalog marks them as cloud).
        if num_ctx and num_ctx > 0 and not model.endswith("-cloud"):
            payload["options"] = {"num_ctx": int(num_ctx)}
            logger.info(
                "[OllamaTransport] requesting num_ctx=%d for model=%s",
                int(num_ctx),
                model,
            )

        # Execution audit B1: tools were never sent, so the Brain on Ollama
        # could not call a tool, and a fixed 30 s timeout cut off any long
        # answer (a file body). Honour the caller's timeout; default 120 s.
        if tools:
            payload["tools"] = tools
        _timeout = float(timeout_s) if timeout_s else 120.0
        _tool_calls: List[Dict[str, Any]] = []
        try:
            # verify=get_ssl_context(): the shared context. Without it httpx
            # built a new one per call (ssl.create_default_context reads the
            # Windows cert store) - 14 stack dumps (~56 s) of one eval turn
            # sat there, every Brain call on Ollama paying it (2026-10-01).
            from backend.utils.ssl_context import get_ssl_context

            with _httpx.Client(
                timeout=_httpx.Timeout(_timeout), verify=get_ssl_context()
            ) as _client:
                _resp = _client.post(url, json=payload)
                # The provider publishes its own RPM ceiling on every response;
                # learning it only from 429s meant guessing 30 against a real 5.
                _observe_advertised_limit(self, _resp.headers)
                if _resp.status_code == 400 and "think" in _resp.text.lower():
                    # Older Ollama servers reject the think flag — retry once
                    # without it rather than failing the turn.
                    logger.warning(
                        "[OllamaTransport] server rejected think flag — retrying without it"
                    )
                    payload.pop("think", None)
                    _resp = _client.post(url, json=payload)
                    _observe_advertised_limit(self, _resp.headers)
                if _resp.status_code != 200:
                    raise RuntimeError(
                        f"Ollama returned {_resp.status_code}: "
                        f"{_resp.text[:200]}"
                    )
                result = _resp.json()
                self.last_usage = _extract_ollama_usage(result)
                _msg = result.get("message", {}) or {}
                _reply = _msg.get("content") or ""
                _tool_calls = [
                    _from_ollama_tool_call(i, tc)
                    for i, tc in enumerate(_msg.get("tool_calls") or [])
                ]
        except Exception:
            logger.warning(
                "[OllamaTransport] inference failed for model=%s", model
            )
            raise

        if _tool_calls:
            thinking, clean = parse_thinking(_reply) if _reply else ("", "")
            return clean, thinking, _tool_calls
        if not _reply:
            raise EmptyModelResponseError("Empty response from Ollama")

        # ── FIX (session 154): fire chunk_callback on non-streaming path
        if chunk_callback and _reply:
            chunk_callback(_reply)
            chunk_callback("")  # force-flush

        thinking, clean = parse_thinking(_reply)
        return clean or "(I see.)", thinking, []
