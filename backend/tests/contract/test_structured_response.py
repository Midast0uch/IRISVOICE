"""Contract tests for Issue C.1 structured speak/show response parsing.

``parse_structured_response`` is the single source of truth for the
speak/show separation contract.  It must:
  * extract ``speak`` (TTS summary) and ``show`` (visual payload) from valid JSON
  * tolerate markdown code fences around the JSON
  * fall back to ``(None, None)`` for plain text / invalid / non-dict JSON
    so non-structured responses pass through unchanged (backward compatible)
"""
import json

from backend.agent.structured_response import parse_structured_response


def test_full_structured():
    text = json.dumps(
        {
            "speak": "Here's what I found.",
            "show": {
                "format": "markdown",
                "content": "# Comparison\n\n| A | B |",
                "alternatives": ["table", "diagram"],
            },
        }
    )
    speak, show = parse_structured_response(text)
    assert speak == "Here's what I found."
    assert show["format"] == "markdown"
    assert "Comparison" in show["content"]
    assert show["alternatives"] == ["table", "diagram"]


def test_show_only_no_speak():
    text = json.dumps({"show": {"format": "table", "content": "x"}})
    speak, show = parse_structured_response(text)
    assert speak is None
    assert show["format"] == "table"


def test_plain_text_falls_through():
    speak, show = parse_structured_response("Just a normal reply, no JSON.")
    assert speak is None
    assert show is None


def test_json_without_speak_or_show_keys():
    speak, show = parse_structured_response(json.dumps({"foo": "bar"}))
    assert speak is None
    assert show is None


def test_fenced_json_stripped():
    text = "```json\n" + json.dumps(
        {"speak": "Hi.", "show": {"format": "html", "content": "<b>hi</b>"}}
    ) + "\n```"
    speak, show = parse_structured_response(text)
    assert speak == "Hi."
    assert show["format"] == "html"


def test_invalid_json_falls_through():
    speak, show = parse_structured_response("{not valid json")
    assert speak is None
    assert show is None


def test_array_json_falls_through():
    speak, show = parse_structured_response(json.dumps([1, 2, 3]))
    assert speak is None
    assert show is None


def test_speak_not_a_string_dropped():
    text = json.dumps({"speak": 123, "show": {"format": "text", "content": "c"}})
    speak, show = parse_structured_response(text)
    assert speak is None
    assert show["content"] == "c"


def test_empty_string():
    speak, show = parse_structured_response("")
    assert speak is None
    assert show is None
