"""RC1 — pre-execution tool validation (Phase 0.3 of the hardening plan).

Verifies that a planned step is validated against the tool registry BEFORE
execution: unknown tools and missing required params are caught (the
historical ``tool:null`` bug class) instead of failing at runtime.
"""
import pytest

from backend.agent.tool_registry import validate_tool_call


def test_nonexistent_tool_is_invalid():
    valid, err = validate_tool_call("this_tool_does_not_exist_xyz", {})
    assert valid is False
    assert "not found" in err


def test_known_tool_with_empty_params_passes():
    # optional params are allowed — only tool existence is enforced (RC1)
    valid, err = validate_tool_call("speak", {})
    assert valid is True
    assert err == ""


def test_known_tool_with_supplied_params_passes():
    valid, err = validate_tool_call("read_file", {"path": "/tmp/example.txt"})
    assert valid is True
    assert err == ""


def test_non_dict_params_is_invalid():
    valid, err = validate_tool_call("read_file", "not-a-dict")
    assert valid is False
    assert "dict" in err.lower()
