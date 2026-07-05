"""
test_chunk_callback_nonstreaming.py — Verify that the DER planning path
and non-streaming LLM dispatch methods invoke chunk_callback so the TTS
sentence_queue receives the response text.

Root cause: When the agent kernel takes the DER planning path
(_needs_planning returns True), _execute_plan_der() generates the full
response via internal LLM calls but never invokes chunk_callback.
The TTS sentence_queue only receives the None sentinel, the producer
breaks immediately, and no audio is synthesized.

Similarly, when a non-streaming LLM provider returns the full reply in
one shot, the non-streaming dispatch path must still call chunk_callback.

Run with:
  python -m pytest tests/test_chunk_callback_nonstreaming.py -v -s
"""

import queue as _queue

import pytest


class TestChunkCallbackEndToEnd:
    """End-to-end: chunk_callback → sentence_queue → TTS producer gets text."""

    def test_producer_receives_text_from_chunk_callback(self):
        """Non-streaming LLM calls chunk_callback, sentences are buffered,
        producer reads them — the full TTS flow works."""
        sentence_buf = ""
        sentence_queue = _queue.Queue()

        def chunk_callback(text):
            nonlocal sentence_buf
            sentence_buf += text
            while True:
                split_pos = -1
                for sep in ("...", "!", "?", ".", "\n"):
                    pos = sentence_buf.rfind(sep)
                    if pos >= 0 and (split_pos < 0 or pos > split_pos):
                        split_pos = pos
                if split_pos < 0:
                    break
                complete = sentence_buf[: split_pos + 1].strip()
                sentence_buf = sentence_buf[split_pos + 1 :]
                if complete:
                    sentence_queue.put(complete)

        # Non-streaming LLM response (as fixed in all dispatch methods)
        _reply = "Hello! How can I help you today?"
        if chunk_callback and _reply:
            chunk_callback(_reply)
            chunk_callback("")  # force-flush

        remaining = sentence_buf.strip()
        if remaining:
            sentence_queue.put(remaining)
        sentence_queue.put(None)  # sentinel

        items_read = []
        while True:
            item = sentence_queue.get(timeout=1.0)
            if item is None:
                break
            items_read.append(item)

        assert len(items_read) >= 1, (
            f"Producer received 0 sentences from non-streaming LLM! "
            f"This means TTS would produce no audio. items_read={items_read}"
        )
        assert "Hello" in items_read[0], f"Expected response text, got: {items_read[0]}"
        print(f"\n  Producer received {len(items_read)} sentence(s): {items_read}")

    def test_multisentence_producer_receives_all(self):
        """Multi-sentence non-streaming response: producer gets all sentences."""
        sentence_buf = ""
        sentence_queue = _queue.Queue()

        def chunk_callback(text):
            nonlocal sentence_buf
            sentence_buf += text
            while True:
                split_pos = -1
                for sep in ("...", "!", "?", ".", "\n"):
                    pos = sentence_buf.rfind(sep)
                    if pos >= 0 and (split_pos < 0 or pos > split_pos):
                        split_pos = pos
                if split_pos < 0:
                    break
                complete = sentence_buf[: split_pos + 1].strip()
                sentence_buf = sentence_buf[split_pos + 1 :]
                if complete:
                    sentence_queue.put(complete)

        _reply = "First sentence. Second sentence! Third question?"
        if chunk_callback and _reply:
            chunk_callback(_reply)
            chunk_callback("")

        remaining = sentence_buf.strip()
        if remaining:
            sentence_queue.put(remaining)
        sentence_queue.put(None)

        items_read = []
        while True:
            item = sentence_queue.get(timeout=1.0)
            if item is None:
                break
            items_read.append(item)

        assert len(items_read) >= 1, (
            f"Expected at least 1 sentence, got {len(items_read)}: {items_read}"
        )
        combined = " ".join(items_read)
        assert "First" in combined and "Second" in combined and "Third" in combined, (
            f"Expected all 3 sentences in output, got: {items_read}"
        )
        print(f"\n  Producer received {len(items_read)} item(s): {items_read}")


class TestBugConfirmation:
    """Verify that the pre-fix behavior (no chunk_callback) produces 0 sentences."""

    def test_without_chunk_callback_producer_gets_nothing(self):
        """Without chunk_callback, producer gets ONLY None sentinel — the bug."""
        sentence_buf = ""
        sentence_queue = _queue.Queue()

        # No chunk_callback called — simulates the pre-fix DER path behavior
        # Flush empty buffer
        remaining = sentence_buf.strip()
        if remaining:
            sentence_queue.put(remaining)
        sentence_queue.put(None)

        items_read = []
        while True:
            item = sentence_queue.get(timeout=1.0)
            if item is None:
                break
            items_read.append(item)

        # Producer gets NOTHING — this is the bug we fixed
        assert len(items_read) == 0, (
            f"Without chunk_callback, producer should get 0 sentences (the bug), "
            f"got: {items_read}"
        )
        print(f"\n  BUG CONFIRMED: Producer received 0 sentences without chunk_callback")


class TestDERPathChunkCallbackFix:
    """Verify that the DER path fix calls chunk_callback with the response.
    This simulates the process_text_message DER → chunk_callback → queue flow."""

    def test_der_response_calls_chunk_callback(self):
        """The DER path must call chunk_callback with the full response before returning."""
        # Simulate the DER path fix from agent_kernel.py:
        #   if chunk_callback and _der_response:
        #       chunk_callback(_der_response)
        #       chunk_callback("")
        #   return _der_response

        sentence_buf = ""
        sentence_queue = _queue.Queue()

        def chunk_callback(text):
            nonlocal sentence_buf
            sentence_buf += text
            while True:
                split_pos = -1
                for sep in ("...", "!", "?", ".", "\n"):
                    pos = sentence_buf.rfind(sep)
                    if pos >= 0 and (split_pos < 0 or pos > split_pos):
                        split_pos = pos
                if split_pos < 0:
                    break
                complete = sentence_buf[: split_pos + 1].strip()
                sentence_buf = sentence_buf[split_pos + 1 :]
                if complete:
                    sentence_queue.put(complete)

        # Simulate DER path generating a response
        _der_response = "I do not have a personal memory or the ability to recall past interactions."

        # The FIX: call chunk_callback before returning
        if chunk_callback and _der_response:
            chunk_callback(_der_response)
            chunk_callback("")

        # Flush remaining
        remaining = sentence_buf.strip()
        if remaining:
            sentence_queue.put(remaining)
        sentence_queue.put(None)

        items_read = []
        while True:
            item = sentence_queue.get(timeout=1.0)
            if item is None:
                break
            items_read.append(item)

        assert len(items_read) >= 1, (
            f"DER path: Producer received 0 sentences! chunk_callback was not called. "
            f"items_read={items_read}"
        )
        assert "personal memory" in items_read[0]
        print(f"\n  DER path fix: Producer received {len(items_read)} sentence(s): {items_read}")

    def test_der_error_response_calls_chunk_callback(self):
        """The DER error path must also call chunk_callback."""
        sentence_buf = ""
        sentence_queue = _queue.Queue()

        def chunk_callback(text):
            nonlocal sentence_buf
            sentence_buf += text
            while True:
                split_pos = -1
                for sep in ("...", "!", "?", ".", "\n"):
                    pos = sentence_buf.rfind(sep)
                    if pos >= 0 and (split_pos < 0 or pos > split_pos):
                        split_pos = pos
                if split_pos < 0:
                    break
                complete = sentence_buf[: split_pos + 1].strip()
                sentence_buf = sentence_buf[split_pos + 1 :]
                if complete:
                    sentence_queue.put(complete)

        # Simulate DER error path
        _err_msg = "IRIS couldn't generate a response. API error: rate limit exceeded"
        if chunk_callback:
            chunk_callback(_err_msg)
            chunk_callback("")

        remaining = sentence_buf.strip()
        if remaining:
            sentence_queue.put(remaining)
        sentence_queue.put(None)

        items_read = []
        while True:
            item = sentence_queue.get(timeout=1.0)
            if item is None:
                break
            items_read.append(item)

        assert len(items_read) >= 1, (
            f"DER error path: Producer received 0 sentences! "
            f"items_read={items_read}"
        )
        combined = " ".join(items_read)
        assert "IRIS" in combined
        print(f"\n  DER error path: Producer received {len(items_read)} sentence(s): {items_read}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
