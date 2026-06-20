"""
Inference Router — Single resolver for all backend inference paths.

Every chat message flows through resolve_backend().  It reads the
canonical config, selects the right provider, and yields response chunks.
No other module should call OpenAI, Cohere, LM Studio, or the swarm
directly.

Usage:
    from backend.inference_router import resolve_backend
    from backend.config import load_config

    cfg = load_config()
    async for chunk in resolve_backend("What is 2+2?", cfg, chunk_callback=cb):
        print(chunk)
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Callable, Dict, List, Optional

from backend.iris_config import IRISConfig, RoutingMode
from backend.llm_service import llm

logger = logging.getLogger("irisvoice")


class ModelConnectError(Exception):
    """Raised when the model endpoint is unreachable."""

    pass


class ModelGenerationError(Exception):
    """Raised when the model generates an error response."""

    pass


async def resolve_backend(
    message: str,
    config: IRISConfig,
    context: Optional[List[Dict]] = None,
    chunk_callback: Optional[Callable[[str], None]] = None,
    reasoning_callback: Optional[Callable[[str], None]] = None,
) -> AsyncGenerator[str, None]:
    """Single entry point for all inference.

    Args:
        message: User text message.
        config: Canonical IRISConfig (loaded from iris_config.json).
        context: Optional conversation history.
        chunk_callback: Sync callback for each response chunk.
        reasoning_callback: Sync callback for reasoning/thinking chunks.

    Yields:
        Final response text (may be empty if chunk_callback consumed everything).
    """
    mode = config.routing.mode
    inf = config.inference

    # Resolve generation parameters
    max_tokens = {"short": 1024, "medium": 4096, "long": 8192}.get(
        inf.response_length, 4096
    )
    temperature = {"fast": 0.9, "balanced": 0.6, "accurate": 0.3}.get(
        inf.reasoning_effort, 0.6
    )

    messages = _build_messages(message, context)

    try:
        match mode:
            case RoutingMode.SINGLE_API:
                async for chunk in _call_api(
                    messages, inf, max_tokens, temperature, chunk_callback, reasoning_callback
                ):
                    yield chunk

            case RoutingMode.SINGLE_LOCAL:
                async for chunk in _call_local(
                    messages, inf, max_tokens, temperature, chunk_callback, reasoning_callback
                ):
                    yield chunk

            case RoutingMode.SWARM_QUALITY | RoutingMode.SWARM_TURBO | RoutingMode.SWARM_HYBRID:
                async for chunk in _call_swarm(
                    messages,
                    inf,
                    max_tokens,
                    temperature,
                    chunk_callback,
                    reasoning_callback,
                    mode=mode,
                ):
                    yield chunk

            case _:
                yield "ERROR: Unknown routing mode. Check configuration."

    except ModelConnectError as exc:
        logger.warning(f"[InferenceRouter] Connection error: {exc}")
        yield f"I'm unable to reach the language model: {exc}"
    except ModelGenerationError as exc:
        logger.error(f"[InferenceRouter] Generation error: {exc}")
        yield f"The model encountered an error: {exc}"
    except Exception as exc:
        logger.error(f"[InferenceRouter] Unexpected error: {exc}", exc_info=True)
        yield f"An unexpected error occurred: {type(exc).__name__}"


def _build_messages(
    message: str, context: Optional[List[Dict]]
) -> List[Dict[str, str]]:
    """Build OpenAI-format message list from user text + optional history."""
    messages: List[Dict[str, str]] = []
    if context:
        for msg in context:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})
    return messages


# ---------------------------------------------------------------------------
# Provider dispatch implementations
# ---------------------------------------------------------------------------

async def _call_api(
    messages: List[Dict[str, str]],
    inf,
    max_tokens: int,
    temperature: float,
    chunk_callback: Optional[Callable[[str], None]],
    reasoning_callback: Optional[Callable[[str], None]],
) -> AsyncGenerator[str, None]:
    """Dispatch to a remote API provider (Chutes, OpenAI, Cohere, etc.)."""
    model = inf.reasoning_model or "local-model"
    if model in ("local-model", "Currently Loaded Model", "currently-loaded-model"):
        model = "command-a-03-2025"

    api_key = inf.api_key
    api_base = inf.api_base_url

    if not api_base:
        raise ModelConnectError("No API base URL configured.")

    # Sanity-check endpoint
    _sanity_check_endpoint(api_base, api_key)

    _api_kwargs = dict(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        api_key=api_key,
        api_base=api_base,
    )

    if chunk_callback:
        _api_kwargs["stream"] = True
        resp = llm.complete(**_api_kwargs)
        full_reply = ""
        for chunk in resp:
            _content = _extract_chunk_text(chunk)
            if _content:
                full_reply += _content
                chunk_callback(_content)
        yield full_reply or "(I see.)"
    else:
        resp = llm.complete(**_api_kwargs)
        reply = resp.choices[0].message.content or ""
        yield reply


async def _call_local(
    messages: List[Dict[str, str]],
    inf,
    max_tokens: int,
    temperature: float,
    chunk_callback: Optional[Callable[[str], None]],
    reasoning_callback: Optional[Callable[[str], None]],
) -> AsyncGenerator[str, None]:
    """Dispatch to a local GGUF or in-process model."""
    model = inf.local_model_id or inf.reasoning_model or "local-model"

    # Use LLMService which handles the local path via iris_local provider
    _kwargs = dict(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    if chunk_callback:
        _kwargs["stream"] = True
        resp = llm.complete(**_kwargs)
        full_reply = ""
        for chunk in resp:
            _content = _extract_chunk_text(chunk)
            if _content:
                full_reply += _content
                chunk_callback(_content)
        yield full_reply or "(I see.)"
    else:
        resp = llm.complete(**_kwargs)
        reply = resp.choices[0].message.content or ""
        yield reply


async def _call_swarm(
    messages: List[Dict[str, str]],
    inf,
    max_tokens: int,
    temperature: float,
    chunk_callback: Optional[Callable[[str], None]],
    reasoning_callback: Optional[Callable[[str], None]],
    mode: RoutingMode,
) -> AsyncGenerator[str, None]:
    """Dispatch to swarm inference (Director + Workers).

    Swarm modes:
        SWARM_QUALITY  → director=qk3,   workers=turbo
        SWARM_TURBO    → director=turbo, workers=turbo
        SWARM_HYBRID   → director=api,   workers=local
    """
    try:
        from backend.agent.swarm_inference_manager import SwarmInferenceManager

        swarm = SwarmInferenceManager()
        # TODO: configure director/worker endpoints based on mode
        # For now, delegate to the existing swarm path
        yield "[Swarm mode not yet fully implemented in router. Falling back to single API.]"
    except ImportError:
        yield "[Swarm inference manager not available.]"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanity_check_endpoint(api_base: str, api_key: str) -> None:
    """Lightweight endpoint reachability check (2s timeout).

    Raises ModelConnectError if the endpoint appears unreachable.
    """
    import httpx

    try:
        _url = f"{api_base.rstrip('/').removesuffix('/v1')}/v1/models"
        _headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        _r = httpx.get(_url, timeout=2.0, headers=_headers)
        if _r.status_code not in (200, 401, 403, 404):
            raise ModelConnectError(
                f"Endpoint returned status {_r.status_code}"
            )
    except httpx.ConnectError as exc:
        raise ModelConnectError(f"Cannot connect to {api_base}: {exc}")
    except httpx.TimeoutException:
        raise ModelConnectError(f"Endpoint {api_base} timed out")


def _extract_chunk_text(chunk) -> str:
    """Extract text content from a streaming chunk (OpenAI / LiteLLM shape)."""
    try:
        _choices = getattr(chunk, "choices", None)
        if _choices and len(_choices) > 0:
            _delta = getattr(_choices[0], "delta", None)
            if _delta:
                return getattr(_delta, "content", None) or ""
    except Exception:
        pass
    if isinstance(chunk, str):
        return chunk
    return ""
