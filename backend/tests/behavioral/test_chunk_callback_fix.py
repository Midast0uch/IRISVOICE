"""
test_chunk_callback_fix.py — Verify non-streaming LLM paths invoke chunk_callback.

SCOPE: the KERNEL dispatch paths only (`_dispatch_api`, `_dispatch_openai_compat`).
These tests run the real methods with a mocked httpx client and assert the reply
reaches chunk_callback plus the force-flush sentinel.

NOT in scope: the voice pipeline itself. A previous version of this file carried
a `TestFullVoicePipelineNonStreaming` class that re-implemented the gateway's
sentence queue INSIDE the test and asserted the copy worked - it guarded
nothing and was removed on 2026-10-07. The voice reply path (turn framing, the
answer, the spoken line, no legacy courier) is guarded for real in
`backend/tests/contract/test_voice_turn_protocol_contract.py`, which drives the
actual `_process_voice_transcription` from a transcript.

The bug this file guards: when the LLM provider returns a full reply in one shot
(stream=False), the non-streaming paths in _dispatch_api, _dispatch_openai_compat,
and _dispatch_inprocess never called chunk_callback. The TTS sentence_queue only
received the None sentinel, so the producer broke immediately without synthesizing
any audio.
"""

import json
import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock
import pytest


def _stub_router(provider, model):
    """Private router with `provider`/`model` bound to the reasoning role.

    Replaces the old `k._model_provider = ...` / `k._selected_reasoning_model
    = ...` staging: both are read-only properties derived from the binding as
    of 2026-08-16. The registry and role table here are LOCAL instances, not
    the process-wide singletons, so this stub cannot leak into another test.
    """
    from backend.agent.inference.provider import ProviderInstance, ProviderKind
    from backend.agent.inference.registry import ProviderRegistry
    from backend.agent.inference.roles import RoleBindingTable
    from backend.agent.inference.router import InferenceRouter

    # Kind chosen so `_provider_string_for_instance` maps back to the exact
    # provider string the stub asked for (OLLAMA->"local", INPROCESS->
    # "iris_local", LOCAL_OPENAI->"lmstudio", API->the instance id).
    _kind = {
        "local": ProviderKind.OLLAMA,
        "iris_local": ProviderKind.INPROCESS,
        "lmstudio": ProviderKind.LOCAL_OPENAI,
    }.get(provider, ProviderKind.API)
    _reg = ProviderRegistry()
    _reg.add(
        ProviderInstance(id=provider, label=provider, kind=_kind, model=model)
    )
    _r = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(_r, "_registry", _reg)
    object.__setattr__(_r, "_roles", RoleBindingTable(_reg))
    object.__setattr__(_r, "_default_role", "reasoning")
    object.__setattr__(_r, "_transports", {})
    object.__setattr__(_r, "_inprocess_mgr", None)
    _r.bind_role("reasoning", provider, model_override=model)
    return _r



class TestDispatchAPINonStreamingChunkCallback:
    """_dispatch_api non-streaming path must call chunk_callback."""

    def test_chunk_callback_called_on_non_streaming_api_response(self):
        """When stream=False, _dispatch_api should call chunk_callback with the reply."""
        from backend.agent.agent_kernel import AgentKernel

        kernel = AgentKernel.__new__(AgentKernel)
        kernel._router = _stub_router("test", "test-model")
        kernel._api_key = "test-key"
        kernel._api_base_url = "https://test.api.com/v1"
        kernel._broadcast_inference_event = MagicMock()
        kernel._lmstudio_endpoint = "http://localhost:1234"

        # Mock httpx to return a non-streaming response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello, world!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        collected = []
        def chunk_callback(chunk):
            collected.append(chunk)

        with patch("httpx.Client") as mock_client_cls, patch("httpx.Timeout") as mock_timeout:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            # Streaming path is taken when chunk_callback is provided; mock it.
            _stream_obj = MagicMock()
            _stream_obj.status_code = 200
            _stream_obj.iter_lines.return_value = [
                "data: " + json.dumps({"choices": [{"delta": {"content": "Hello, world!"}}]}),
                "data: [DONE]",
            ]
            _stream_cm = MagicMock()
            _stream_cm.__enter__ = MagicMock(return_value=_stream_obj)
            _stream_cm.__exit__ = MagicMock(return_value=False)
            mock_client.stream.return_value = _stream_cm
            mock_client_cls.return_value = mock_client
            mock_timeout.return_value = MagicMock()

            messages = [{"role": "user", "content": "hi"}]
            result = kernel._dispatch_api(
                messages=messages,
                max_tokens=100,
                temperature=0.7,
                chunk_callback=chunk_callback,
            )

        # Verify chunk_callback was called
        assert len(collected) >= 1, (
            f"chunk_callback was never called. collected={collected}"
        )
        assert collected[0] == "Hello, world!", (
            f"First chunk should be the full reply, got: {collected[0]}"
        )
        # Verify force-flush empty string at the end
        assert collected[-1] == "", (
            f"Last chunk should be empty string (force-flush), got: {collected[-1]}"
        )
        # Response text should still be correct
        assert "Hello, world!" in result[0]

    def test_no_chunk_callback_when_none(self):
        """When chunk_callback is None, non-streaming path should work normally."""
        from backend.agent.agent_kernel import AgentKernel

        kernel = AgentKernel.__new__(AgentKernel)
        kernel._router = _stub_router("test", "test-model")
        kernel._api_key = "test-key"
        kernel._api_base_url = "https://test.api.com/v1"
        kernel._broadcast_inference_event = MagicMock()
        kernel._lmstudio_endpoint = "http://localhost:1234"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Reply text"}}],
            "usage": {},
        }

        with patch("httpx.Client") as mock_client_cls, patch("httpx.Timeout") as mock_timeout:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client
            mock_timeout.return_value = MagicMock()

            messages = [{"role": "user", "content": "hi"}]
            result = kernel._dispatch_api(
                messages=messages,
                max_tokens=100,
                temperature=0.7,
                chunk_callback=None,
            )

        assert "Reply text" in result[0]


class TestDispatchOpenAICompatNonStreamingChunkCallback:
    """_dispatch_openai_compat non-streaming path must call chunk_callback."""

    def test_chunk_callback_called_on_non_streaming_compat_response(self):
        """When stream=False, _dispatch_openai_compat should call chunk_callback."""
        from backend.agent.agent_kernel import AgentKernel

        kernel = AgentKernel.__new__(AgentKernel)
        kernel._router = _stub_router("test", "test-model")
        kernel._api_key = "test-key"
        kernel._api_base_url = "http://localhost:1234/v1"
        kernel._broadcast_inference_event = MagicMock()
        kernel._lmstudio_endpoint = "http://localhost:1234"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Local model says hello"}}],
            "usage": {},
        }

        collected = []
        def chunk_callback(chunk):
            collected.append(chunk)

        with patch("httpx.Client") as mock_client_cls, patch("httpx.Timeout") as mock_timeout:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            # Streaming path is taken when chunk_callback is provided; mock it.
            _stream_obj = MagicMock()
            _stream_obj.status_code = 200
            _stream_obj.iter_lines.return_value = [
                "data: " + json.dumps({"choices": [{"delta": {"content": "Local model says hello"}}]}),
                "data: [DONE]",
            ]
            _stream_cm = MagicMock()
            _stream_cm.__enter__ = MagicMock(return_value=_stream_obj)
            _stream_cm.__exit__ = MagicMock(return_value=False)
            mock_client.stream.return_value = _stream_cm
            mock_client_cls.return_value = mock_client
            mock_timeout.return_value = MagicMock()

            messages = [{"role": "user", "content": "hi"}]
            result = kernel._dispatch_openai_compat(
                messages=messages,
                max_tokens=100,
                temperature=0.7,
                chunk_callback=chunk_callback,
            )

        assert len(collected) >= 1, (
            f"chunk_callback was never called. collected={collected}"
        )
        assert collected[0] == "Local model says hello"
        assert collected[-1] == ""  # force-flush


# ─────────────────────────────────────────────────────────────────────────────
# REMOVED 2026-10-07: class TestFullVoicePipelineNonStreaming.
#
# It claimed to test "the full voice pipeline", but both of its tests built a
# local queue.Queue and a local COPY of the chunk_callback logic, then asserted
# that the copy behaved as the copy. No backend code was involved, so it could
# not fail when the gateway broke - it guarded nothing. (The project rule: a
# stand-in that re-implements the logic it claims to guard silently skips the
# guarded read.)
#
# The voice reply path is now guarded for real, with no wake word needed, in
# backend/tests/contract/test_voice_turn_protocol_contract.py: it drives the
# REAL _process_voice_transcription from a transcript and asserts what reaches
# the wire - one turn.start / dense turn.part / one turn.end, the answer with
# its spoken line, and none of the retired reply frames.
#
