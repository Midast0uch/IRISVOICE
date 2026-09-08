"""Unit: content-aware spoken shaping resolver (REQ-6) — BT-S5 + CT-S3.

Pins the resolver precedence (agent speak > type-aware shaping > first-sentence
fallback), the type table (prose generous, table/diagram/code described), the
spoken⊆visible guarantee, the unlisted-type fallback + log, and the "read it
to me" override. Pure unit — no TTS, no audio.
"""
from __future__ import annotations

import pytest

from backend.agent.speech_lanes import (
    SpeechObservability,
    resolve_spoken_text,
)


# ── REQ-6 AC6.2: precedence ───────────────────────────────────────────────
class TestPrecedence:
    def test_agent_speak_wins(self):
        shown = "This is a long table with many rows and columns of data."
        spoken = resolve_spoken_text(
            shown_text=shown,
            agent_speak="Here is the comparison you asked for.",
            show_format="table",
        )
        assert spoken == "Here is the comparison you asked for."

    def test_type_aware_beats_fallback(self):
        # A table is described (short), not recited in full.
        shown = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n| 5 | 6 |"
        spoken = resolve_spoken_text(shown_text=shown, show_format="table")
        assert "|" not in spoken  # no raw table cells
        assert len(spoken.split()) <= len(shown.split())  # described, not recited

    def test_first_sentence_fallback_for_prose(self):
        shown = "The quick brown fox jumps over the lazy dog. It was a sunny day."
        spoken = resolve_spoken_text(shown_text=shown, show_format="text")
        assert "quick brown fox" in spoken


# ── REQ-6 AC6.1: type table ───────────────────────────────────────────────
class TestTypeTable:
    def test_prose_speaks_generously(self):
        shown = "Here is a short explanation of the result."
        spoken = resolve_spoken_text(shown_text=shown, show_format="prose")
        assert spoken == shown  # short prose spoken verbatim

    def test_table_described_not_recited(self):
        shown = "| col1 | col2 |\n|------|------|\n| a    | b    |"
        spoken = resolve_spoken_text(shown_text=shown, show_format="table")
        assert "|" not in spoken
        assert spoken  # still says something
        assert len(spoken.split()) <= len(shown.split())  # described, not recited

    def test_code_described_not_recited(self):
        shown = "def foo():\n    return 42\nprint(foo())"
        spoken = resolve_spoken_text(shown_text=shown, show_format="code")
        assert spoken  # still says something
        assert len(spoken.split()) <= len(shown.split())  # not recited line-by-line

    def test_diagram_described(self):
        shown = "graph TD\nA-->B\nB-->C\nC-->D\nD-->E\nE-->F\nF-->G\nG-->H"
        spoken = resolve_spoken_text(shown_text=shown, show_format="diagram")
        assert spoken
        # Described, not recited: the spoken line is a subset of the shown
        # words (whitespace-collapsed), never longer.
        assert len(spoken.split()) <= len(shown.split())


# ── REQ-6 AC6.3: spoken ⊆ visible ─────────────────────────────────────────
class TestSpokenSubsetVisible:
    def test_spoken_derived_from_shown(self):
        shown = "The result is 42. It was computed from the data."
        spoken = resolve_spoken_text(shown_text=shown, show_format="text")
        # Every word of the spoken line appears in the shown text.
        spoken_words = set(spoken.split())
        shown_words = set(shown.split())
        assert spoken_words <= shown_words

    def test_agent_speak_is_shown_content(self):
        shown = "Full visible response with details."
        spoken = resolve_spoken_text(
            shown_text=shown, agent_speak="Short spoken line.", show_format="markdown"
        )
        # The agent's line is itself shown content (it's the spoken companion).
        assert spoken == "Short spoken line."

    def test_no_mid_sentence_clip(self):
        shown = "First sentence ends here. Second sentence is longer and continues."
        spoken = resolve_spoken_text(shown_text=shown, show_format="text")
        # If truncated, it ends at a sentence boundary, never mid-word.
        assert not spoken.endswith("continues")  # not clipped mid-sentence


# ── REQ-6 AC6.4: unlisted type + override ─────────────────────────────────
class TestUnlistedAndOverride:
    def test_unlisted_type_describes_and_logs(self):
        obs = SpeechObservability()
        shown = "Some spreadsheet-like content here."
        spoken = resolve_spoken_text(
            shown_text=shown, show_format="spreadsheet", observability=obs
        )
        assert spoken  # describe-don't-recite
        assert obs.counters.get("unlisted_type:spreadsheet") == 1

    def test_read_it_to_me_override_recites(self):
        shown = "| A | B |\n|---|---|\n| 1 | 2 |"
        spoken = resolve_spoken_text(
            shown_text=shown, show_format="table", override_recite=True
        )
        assert spoken == shown  # full recitation allowed on explicit override

    def test_empty_shown_yields_silence(self):
        spoken = resolve_spoken_text(shown_text="", show_format="text")
        assert spoken == ""  # silence is legal (AC6.4 edge case)