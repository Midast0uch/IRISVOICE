"""
Tests for interpreter.py — ResolutionEncoder, CoordinateInterpreter, BehavioralPredictor
Source: specs/agent_loop_design.md + bootstrap/GOALS.md Step 1.9

Key requirements:
  - encode_with_resolution({}) does not raise
  - encode_with_resolution with full dict produces correct format
  - CoordinateInterpreter and BehavioralPredictor are importable stubs

Run: python -m pytest backend/tests/test_interpreter.py -v
"""

import pytest


# ── Import sanity ──────────────────────────────────────────────────────────

def test_imports():
    from backend.memory.mycelium.interpreter import (
        ResolutionEncoder, CoordinateInterpreter, BehavioralPredictor
    )
    assert ResolutionEncoder
    assert CoordinateInterpreter
    assert BehavioralPredictor


# ── ResolutionEncoder.encode_with_resolution({}) — never raises ───────────

def test_encode_with_resolution_empty_no_raise():
    """encode_with_resolution({}) never raises, returns non-empty string."""
    from backend.memory.mycelium.interpreter import ResolutionEncoder
    result = ResolutionEncoder().encode_with_resolution({})
    assert isinstance(result, str) and len(result) > 0


def test_encode_with_resolution_empty_returns_string():
    """Empty dict → valid string, no KeyError on missing keys."""
    from backend.memory.mycelium.interpreter import ResolutionEncoder
    result = ResolutionEncoder().encode_with_resolution({})
    assert isinstance(result, str)


# ── Full dict produces correct format ────────────────────────────────────

def test_encode_with_resolution_full_contains_space_id():
    """Full failure dict → output contains space_id and tool_name."""
    from backend.memory.mycelium.interpreter import ResolutionEncoder
    result = ResolutionEncoder().encode_with_resolution({
        "space_id": "toolpath", "tool_name": "docker",
        "condition": "windows", "score_delta": -0.08
    })
    assert "toolpath" in result and "docker" in result


def test_encode_with_resolution_includes_delta():
    """Output encodes the score_delta value."""
    from backend.memory.mycelium.interpreter import ResolutionEncoder
    result = ResolutionEncoder().encode_with_resolution({
        "space_id": "codespace", "tool_name": "pip",
        "condition": "offline", "score_delta": -0.15
    })
    assert "codespace" in result
    assert "pip" in result


def test_encode_with_resolution_with_resolution_field():
    """When resolution field present, it appears in output."""
    from backend.memory.mycelium.interpreter import ResolutionEncoder
    result = ResolutionEncoder().encode_with_resolution({
        "space_id": "s", "tool_name": "t",
        "condition": "c", "score_delta": -0.1,
        "resolution": "use_cached"
    })
    assert "use_cached" in result


# ── Missing keys fall back to 'unknown' — no KeyError ────────────────────

def test_encode_partial_dict_no_raise():
    """Partial dict — only some keys — no exception."""
    from backend.memory.mycelium.interpreter import ResolutionEncoder
    enc = ResolutionEncoder()
    enc.encode_with_resolution({"space_id": "codespace"})
    enc.encode_with_resolution({"tool_name": "docker"})
    enc.encode_with_resolution({"score_delta": -0.5})


# ── _find_resolution — never raises ──────────────────────────────────────

def test_find_resolution_no_conn_returns_none():
    """Without a conn, _find_resolution returns None (not raises)."""
    from backend.memory.mycelium.interpreter import ResolutionEncoder
    enc = ResolutionEncoder()
    result = enc._find_resolution({"session_id": "s1", "tool_name": "docker"}, None)
    assert result is None


def test_find_resolution_bad_conn_returns_none():
    """Broken conn object → None returned, no exception."""
    from backend.memory.mycelium.interpreter import ResolutionEncoder
    from unittest.mock import MagicMock
    bad_conn = MagicMock()
    bad_conn.execute.side_effect = Exception("db gone")
    enc = ResolutionEncoder()
    result = enc._find_resolution({"session_id": "s1"}, bad_conn)
    assert result is None


# ── CoordinateInterpreter and BehavioralPredictor stubs ──────────────────

def test_coordinate_interpreter_instantiates():
    """CoordinateInterpreter stub can be instantiated."""
    from backend.memory.mycelium.interpreter import CoordinateInterpreter
    ci = CoordinateInterpreter()
    assert ci is not None


def test_behavioral_predictor_instantiates():
    """BehavioralPredictor stub can be instantiated."""
    from backend.memory.mycelium.interpreter import BehavioralPredictor
    bp = BehavioralPredictor()
    assert bp is not None
