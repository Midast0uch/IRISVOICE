"""Contract tests for build_reformat_payload (Issue D.2).

The reformat payload builder is the core of the reformat_document flow: it
turns an LLM reformat response (structured JSON or plain text) into the
DOCUMENT_RENDER payload.  Pure and dependency-free, so it is directly testable.
"""
import json
import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from backend.agent.structured_response import build_reformat_payload


def test_structured_json_payload():
    text = json.dumps(
        {
            "show": {
                "format": "table",
                "content": "| a | b |",
                "alternatives": ["diagram"],
            }
        }
    )
    p = build_reformat_payload(text, target_format="table", original_format="markdown")
    assert p["format"] == "table"
    assert p["content"] == "| a | b |"
    assert "diagram" in p["alternatives"]
    # The original format is offered back so the user can toggle.
    assert "markdown" in p["alternatives"]
    assert p["reformatted"] is True


def test_plain_text_payload():
    p = build_reformat_payload("Just plain reformatted text", target_format="text")
    assert p["format"] == "text"
    assert p["content"] == "Just plain reformatted text"
    assert p["reformatted"] is True


def test_original_format_offered_as_alternative():
    p = build_reformat_payload(
        "content here", target_format="html", original_format="markdown"
    )
    assert p["alternatives"][0] == "markdown"


def test_no_duplicate_original_alternative():
    text = json.dumps(
        {"show": {"format": "table", "content": "x", "alternatives": ["markdown"]}}
    )
    p = build_reformat_payload(text, target_format="table", original_format="markdown")
    assert p["alternatives"].count("markdown") == 1
