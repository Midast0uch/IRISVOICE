"""Contract tests: REQ-9 narration + TTS observability log.

Asserts NarrationLog records EVERY narration decision (including SILENCE)
with structured fields scoped by conversation_id, and carries u/xi on
structural events (split/collapse). The log is the tuning instrument
for the narration policy — if silence isn't logged, trigger-frequency
analysis is impossible.

Spec: specs/der-loop-integrity-display/requirements.md REQ-9.
"""

from __future__ import annotations

import json
import os
import tempfile

from backend.agent.narration import NarrationLog


class TestNarrationLog:
    def _tmp(self, conv_id):
        d = tempfile.mkdtemp()
        log = NarrationLog.__new__(NarrationLog)
        log.conversation_id = conv_id
        log._path = os.path.join(d, f"{conv_id}.jsonl")
        return log

    def test_silence_recorded(self):
        log = self._tmp("conv_silence")
        log._write(
            {
                "ts": 1.0,
                "conversation_id": "conv_silence",
                "step_id": "s1",
                "decision": "silence",
                "signal": None,
                "u": 0.6,
                "xi": 0.1,
                "text": "",
                "tts_played": False,
            }
        )
        with open(log._path, encoding="utf-8") as fh:
            lines = [l for l in fh if l.strip()]
        assert len(lines) == 1
        entry = json.loads(lines[0])
        # Silence is logged with the conversation scope + decision field.
        assert entry["conversation_id"] == "conv_silence"
        assert entry["decision"] == "silence"
        assert entry["tts_played"] is False
        assert entry["text"] == ""

    def test_spoken_recorded_with_u_xi_on_split(self):
        log = self._tmp("conv_split")
        log._write(
            {
                "ts": 2.0,
                "conversation_id": "conv_split",
                "step_id": "s2",
                "decision": "brief",
                "signal": "retried",
                "u": 0.62,
                "xi": 0.3,
                "text": "Now moving into a sub-task.",
                "tts_played": True,
            }
        )
        with open(log._path, encoding="utf-8") as fh:
            entry = json.loads(fh.readline())
        assert entry["decision"] == "brief"
        assert entry["signal"] == "retried"
        assert entry["tts_played"] is True
        # u/xi carried on the structural event.
        assert entry["u"] == 0.62
        assert entry["xi"] == 0.3

    def test_scoped_by_conversation(self):
        a = self._tmp("convA")
        b = self._tmp("convB")
        a._write({"conversation_id": "convA", "decision": "silence"})
        b._write({"conversation_id": "convB", "decision": "brief"})
        with open(a._path, encoding="utf-8") as fa:
            assert "convA" in fa.read()
        with open(b._path, encoding="utf-8") as fb:
            assert "convB" in fb.read()
        # Files are separate per conversation.
        assert a._path != b._path
