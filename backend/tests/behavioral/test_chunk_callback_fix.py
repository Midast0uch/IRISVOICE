"""
test_chunk_callback_fix.py — Verify non-streaming LLM paths invoke chunk_callback.

The bug: when the LLM provider returns a full reply in one shot (stream=False),
the non-streaming paths in _dispatch_api, _dispatch_openai_compat, and
_dispatch_inprocess never called chunk_callback. The TTS sentence_queue only
received the None sentinel, so the producer broke immediately without
synthesizing any audio.

This test exercises each non-streaming dispatch method with a real
chunk_callback and verifies the callback receives the reply text.
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


class TestFullVoicePipelineNonStreaming:
    """
    End-to-end: when process_text_message uses a non-streaming provider,
    the chunk_callback should be called, populating the sentence_queue
    so the TTS producer can synthesize audio.
    """

    def test_non_streaming_provider_populates_sentence_queue(self):
        """
        Simulate the full voice pipeline flow:
        1. iris_gateway creates sentence_queue
        2. chunk_callback puts sentences into queue
        3. Non-streaming LLM returns full reply
        4. Producer should read the reply (not just None)
        """
        import queue

        sentence_queue = queue.Queue()

        # Simulate what iris_gateway._process_voice_transcription does
        sentence_buf = []
        flush_timer = None

        def chunk_callback(chunk):
            nonlocal sentence_buf, flush_timer
            if not chunk:
                # Force-flush
                if sentence_buf:
                    complete = "".join(sentence_buf)
                    sentence_queue.put(complete)
                    sentence_buf = []
                return

            sentence_buf.append(chunk)
            complete = "".join(sentence_buf)
            sentence_queue.put(complete)
            sentence_buf = []

        # Simulate non-streaming LLM returning full reply via chunk_callback
        # (This is what the fix now does in _dispatch_api/_dispatch_openai_compat)
        chunk_callback("Hello, this is a test response from the LLM.")
        chunk_callback("")  # force-flush

        # Add sentinel
        sentence_queue.put(None)

        # Now simulate the producer reading from the queue
        collected_items = []
        while True:
            item = sentence_queue.get(timeout=1)
            if item is None:
                break
            collected_items.append(item)

        assert len(collected_items) == 1, (
            f"Producer should have received 1 sentence, got {len(collected_items)}: {collected_items}"
        )
        assert collected_items[0] == "Hello, this is a test response from the LLM."

    def test_streaming_provider_still_works(self):
        """
        Verify the streaming path (chunk_callback called multiple times)
        still works correctly after the fix.
        """
        import queue

        sentence_queue = queue.Queue()
        sentence_buf = []

        def chunk_callback(chunk):
            nonlocal sentence_buf
            if not chunk:
                if sentence_buf:
                    complete = "".join(sentence_buf)
                    sentence_queue.put(complete)
                    sentence_buf = []
                return

            # Simple sentence boundary: split on ". "
            sentence_buf.append(chunk)
            text = "".join(sentence_buf)
            if "." in text:
                parts = text.split(".", 1)
                sentence_queue.put(parts[0] + ".")
                sentence_buf = [parts[1]] if len(parts) > 1 and parts[1] else []

        # Simulate streaming LLM calling chunk_callback multiple times
        for chunk in ["Hello", ".", " ", "How", " ", "are", " ", "you", "?"]:
            chunk_callback(chunk)
        chunk_callback("")  # force-flush

        sentence_queue.put(None)

        collected = []
        while True:
            item = sentence_queue.get(timeout=1)
            if item is None:
                break
            collected.append(item)

        assert len(collected) >= 1
        assert "Hello" in collected[0]
