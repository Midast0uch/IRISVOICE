"""
LiteLLM-based unified LLM service.

Replaces all direct OpenAI / Cohere SDK calls in agent_kernel.py
with a single `litellm.completion()` call.  Provides:

- Automatic retries with exponential backoff (liteLLM built-in)
- Fallback chains (primary → secondary → tertiary model)
- Cost tracking per request
- Unified streaming format across 100+ providers
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

# litellm import can be slow on first call (probes all providers).
from litellm import completion

logger = logging.getLogger("llm_service")


class LLMService:
    """LiteLLM wrapper with retries and fallbacks."""

    def __init__(self) -> None:
        self.default_model = "cohere/command-a-03-2025"
        self.max_retries = int(os.getenv("LITELLM_MAX_RETRIES", "3"))
        self.request_timeout = int(os.getenv("LITELLM_REQUEST_TIMEOUT", "60"))

        # Fallback chains: primary → [fallback1, fallback2, ...]
        # When the primary model fails (rate limit, downtime, error),
        # LiteLLM auto-tries the next model in the chain.
        self.fallbacks: Dict[str, List[str]] = {
            "cohere/command-r-plus-08-2024": [
                "cohere/command-r-08-2024",
                "openai/gpt-4o-mini",
            ],
            "cohere/command-r-08-2024": [
                "openai/gpt-4o-mini",
            ],
        }

    def complete(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream: bool = False,
        max_tokens: int = 4096,
        temperature: float = 0.6,
        extra_headers: Optional[Dict[str, str]] = None,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """Unified completion call.

        For custom OpenAI-compatible endpoints (Chutes, LM Studio, vLLM,
        etc.) the standard ``openai`` SDK is used directly — it handles
        SSE ``[DONE]`` termination correctly and avoids LiteLLM's stream
        handoff overhead.

        For native LiteLLM providers (Cohere SDK, Groq, etc.) the
        ``litellm.completion()`` route is used for provider abstraction.

        Args:
            model: Full model name; may include provider prefix.
            messages: OpenAI-format message list.
            stream: If True, returns a streaming response iterator.
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature.
            extra_headers: Optional HTTP headers to include.
            api_key: API key.
            api_base: Custom base URL (e.g. Chutes, LM Studio).
            **kwargs: Additional arguments.

        Returns:
            Completion response.  If ``stream=True``, yields
            ``ChatCompletionChunk`` objects (OpenAI-compatible format).
        """
        resolved_model = self._resolve_model(model)

        # ── Custom OpenAI-compatible endpoint (Chutes, vLLM, LM Studio) ──
        # Use the OpenAI SDK directly for correct SSE termination handling.
        if api_base:
            from openai import OpenAI as _OpenAI
            import httpx as _httpx

            if api_key and not api_key.startswith("sk-"):
                _openai_key = api_key if api_key else "placeholder"
            else:
                _openai_key = api_key or "placeholder"

            _client = _OpenAI(
                api_key=_openai_key,
                base_url=api_base,
                timeout=_httpx.Timeout(connect=10, read=120, write=10, pool=10),
            )
            _bare = model.split("/")[-1]
            _call_kwargs: Dict[str, Any] = dict(
                model=_bare,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if extra_headers:
                _call_kwargs["extra_headers"] = extra_headers
            if stream:
                _call_kwargs["stream"] = stream

            logger.info(
                f"[LLMService] direct OpenAI client: model={_bare} "
                f"api_base={api_base} stream={stream}"
            )
            return _client.chat.completions.create(**_call_kwargs)

        # ── Native LiteLLM providers (Cohere SDK, Groq, etc.) ──────────
        call_kwargs: Dict[str, Any] = dict(
            model=resolved_model,
            messages=messages,
            stream=stream,
            max_tokens=max_tokens,
            temperature=temperature,
            max_retries=self.max_retries,
            request_timeout=self.request_timeout,
            fallbacks=self.fallbacks.get(model),
        )
        if extra_headers:
            call_kwargs["extra_headers"] = extra_headers
        if api_key:
            call_kwargs["api_key"] = api_key

        reasoning_effort = kwargs.pop("reasoning_effort", None)
        if reasoning_effort:
            call_kwargs["reasoning_effort"] = reasoning_effort
        call_kwargs.update(kwargs)

        logger.info(
            f"[LLMService] LiteLLM completion: model={resolved_model} stream={stream}"
        )
        return completion(**call_kwargs)

    def _resolve_model(self, model: str) -> str:
        """Convert a bare model name to LiteLLM provider-prefixed format.

        Rules:
          - Models starting with ``"openai/"``, ``"cohere/"``, ``"groq/"``, etc.
            are passed through as-is.
          - Bare names like ``"command-r-plus-08-2024"`` get the default
            provider prefix.
          - ``"local-model"`` → returned as-is (handled by agent_kernel fallback).
        """
        if "/" in model or model in ("local-model", "Currently Loaded Model"):
            return model
        return f"cohere/{model}"


# Module-level singleton — imported once, shared everywhere.
llm = LLMService()
