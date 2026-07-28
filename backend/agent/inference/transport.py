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
from backend.agent.inference.errors import RateLimitedError
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
    """
    import random

    if attempt >= 2:
        return  # final attempt — do not sleep before failing (REQ-1 AC4)
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
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        """Run inference and return ``(text, thinking, tool_calls)``."""
        ...

    def _record_success(self, text: str) -> None:
        """Record a completed (non-429) request against the meter.

        Called by subclasses after a successful ``generate``. Keyed by
        ``self._quota_id``; unmetered quotas are ignored by the meter. Metering
        must NEVER break a call, so all errors are swallowed (T2.2 / T2.5).
        """
        if self._quota_id is None:
            return
        try:
            get_rate_meter().record_request(
                self._quota_id,
                max(1, len(text) // 4),  # estimated tokens: 4 chars ≈ 1 token
                priority=priority_index(call_class()),  # F9: thread real call class from context
                estimated=True,
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
# ApiHttpxTransport  — extracted from ``_dispatch_api`` (httpx, Bearer)
# ---------------------------------------------------------------------------


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

    def _record_success(self, text: str) -> None:
        """Record a completed (non-429) request against the meter.

        Keyed by ``self._quota_id``; unmetered quotas are ignored by the meter.
        Metering must NEVER break a call, so all errors are swallowed.
        """
        if self._quota_id is None:
            return
        try:
            get_rate_meter().record_request(
                self._quota_id,
                max(1, len(text) // 4),  # estimated tokens: 4 chars ≈ 1 token
                priority=priority_index(call_class()),  # F9: thread real call class from context
                estimated=True,
                label=getattr(self, "_provider_id", "unknown"),
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
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        import httpx as _httpx
        from backend.utils.ssl_context import get_ssl_context

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
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
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
                max_tokens,
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
            )
        else:
            _text, _think, _tools = self._nonstream(
                url, headers, body, model, messages
            )
        self._record_success(_text)
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
            _stream_ok = False
            try:
                with _httpx.Client(
                    timeout=_httpx.Timeout(60.0), verify=get_ssl_context()
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
                            )
                            get_rate_meter().observe_429(
                                self._quota_id, _retry_after
                            )
                            continue

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
                            if not _line or not _line.startswith("data:"):
                                continue
                            _data = _line[5:].strip()
                            if _data == "[DONE]":
                                break
                            _chunk = _json.loads(_data)
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
                                    reasoning_callback(_r)

                            # Text content
                            _c = _delta.get("content")
                            if _c:
                                full_reply += _c
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
                if attempt == 2:
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
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        import httpx as _httpx
        from backend.utils.ssl_context import get_ssl_context

        _t0 = _perf_t.perf_counter()
        result = None
        _rate_limited = False
        for attempt in range(3):
            try:
                with _httpx.Client(
                    timeout=_httpx.Timeout(60.0), verify=get_ssl_context()
                ) as _client:
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
                        )
                        get_rate_meter().observe_429(
                            self._quota_id, _retry_after
                        )
                        continue
                    if _resp.status_code != 200:
                        raise RuntimeError(
                            f"API returned {_resp.status_code}: "
                            f"{_resp.text[:200]}"
                        )
                    result = _resp.json()
                    break
            except RuntimeError:
                raise
            except Exception as _e:
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

        _msg = result.get("choices", [{}])[0].get("message", {})
        _reply = _msg.get("content", "")
        _tool_calls = _msg.get("tool_calls") or []

        if not _reply and not _tool_calls:
            raise RuntimeError("Empty response from API")

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

    def _record_success(self, text: str) -> None:
        """Record a completed (non-429) request against the meter."""
        if self._quota_id is None:
            return
        try:
            get_rate_meter().record_request(
                self._quota_id,
                max(1, len(text) // 4),  # estimated tokens: 4 chars ≈ 1 token
                priority=priority_index(call_class()),  # F9: thread real call class from context
                estimated=True,
                label=getattr(self, "_provider_id", "unknown"),
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
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        import httpx as _httpx
        from backend.utils.ssl_context import get_ssl_context

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

        if chunk_callback:
            _text, _think, _tools = self._stream(
                _url,
                _url_v1,
                _body,
                chunk_callback,
                reasoning_callback,
            )
        else:
            _text, _think, _tools = self._nonstream(_url, _url_v1, _body)
        self._record_success(_text)
        return _text, _think, _tools

    # -- streaming path -------------------------------------------------

    def _stream(
        self,
        url: str,
        url_v1: str,
        body: Dict[str, Any],
        chunk_callback: Callable[[str], None],
        reasoning_callback: Optional[Callable[[str], None]] = None,
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
            _stream_ok = False
            try:
                with _httpx.Client(
                    timeout=_httpx.Timeout(60.0), verify=get_ssl_context()
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
                            f"Could not connect to LM Studio at "
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
                            )
                            get_rate_meter().observe_429(
                                self._quota_id, _retry_after
                            )
                            continue
                        if _stream.status_code != 200:
                            raise RuntimeError(
                                f"LM Studio returned "
                                f"{_stream.status_code}: "
                                f"{_stream.text[:200]}"
                            )
                        for _line in _stream.iter_lines():
                            if not _line or not _line.startswith("data:"):
                                continue
                            _data = _line[5:].strip()
                            if _data == "[DONE]":
                                break
                            _chunk = _json.loads(_data)
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
                                    reasoning_callback(_r)

                            _c = _delta.get("content")
                            if _c:
                                full_reply += _c
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
                if attempt == 2:
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
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        import httpx as _httpx
        from backend.utils.ssl_context import get_ssl_context

        result = None
        _rate_limited = False
        for attempt in range(3):
            try:
                with _httpx.Client(
                    timeout=_httpx.Timeout(60.0), verify=get_ssl_context()
                ) as _client:
                    for _try_url in [url, url_v1]:
                        try:
                            _resp = _client.post(
                                _try_url,
                                headers={
                                    "Content-Type": "application/json"
                                },
                                json=body,
                            )
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
                        raise RuntimeError(
                            f"Could not connect to LM Studio at "
                            f"{self._endpoint}"
                        )

                    if _resp.status_code == 429:
                        continue
                    if _resp.status_code != 200:
                        raise RuntimeError(
                            f"LM Studio returned "
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
            raise RuntimeError("LM Studio request failed after retries")

        _msg = result.get("choices", [{}])[0].get("message", {})
        _reply = _msg.get("content", "")
        _tool_calls = _msg.get("tool_calls") or []

        if not _reply and not _tool_calls:
            raise RuntimeError("Empty response from LM Studio")

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
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
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

        if mgr is None:
            raise RuntimeError("No local model loaded for in-process inference")

        # In-process models typically take a single prompt string
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


class OllamaTransport:
    """Ollama native API via https.

    Preserves the inline call from ``agent_kernel.py`` (``requests.post``
    replaced with httpx for consistency with other transports).

    No streaming support — Ollama native API is called non-streaming.
    No tool support.
    """

    def __init__(
        self, endpoint: str = "http://localhost:11434", quota_id: Optional[str] = None
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._quota_id = quota_id

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
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        import httpx as _httpx

        url = f"{self._endpoint}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }

        try:
            with _httpx.Client(timeout=_httpx.Timeout(30.0)) as _client:
                _resp = _client.post(url, json=payload)
                if _resp.status_code != 200:
                    raise RuntimeError(
                        f"Ollama returned {_resp.status_code}: "
                        f"{_resp.text[:200]}"
                    )
                result = _resp.json()
                _reply = result.get("message", {}).get("content", "")
        except Exception:
            logger.warning(
                "[OllamaTransport] inference failed for model=%s", model
            )
            raise

        if not _reply:
            raise RuntimeError("Empty response from Ollama")

        # ── FIX (session 154): fire chunk_callback on non-streaming path
        if chunk_callback and _reply:
            chunk_callback(_reply)
            chunk_callback("")  # force-flush

        thinking, clean = parse_thinking(_reply)
        return clean or "(I see.)", thinking, []
