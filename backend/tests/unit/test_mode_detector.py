"""
Tests for mode_detector.py — AgentMode, ModeDetector, ModeResult, ComplexityLevel
Source: specs/director_mode_system.md
Gate 1 Step 1.2 acceptance criteria.

Manual verify requirements (from GOALS.md):
  - /spec triggers AgentMode.SPEC
  - /debug triggers AgentMode.DEBUG
  - /ask triggers needs_clarification=True
  - unknown input defaults to AgentMode.IMPLEMENT

Run: python -m pytest backend/tests/test_mode_detector.py -v
"""

import pytest


# ── Import sanity ──────────────────────────────────────────────────────────

def test_imports():
    from backend.agent.mode_detector import (
        AgentMode, ModeDetector, ModeResult, ComplexityLevel
    )
    assert AgentMode.SPEC
    assert AgentMode.DEBUG
    assert ComplexityLevel.SIMPLE
    assert ModeResult  # dataclass importable


# ── AgentMode enum ────────────────────────────────────────────────────────

def test_agent_mode_values():
    from backend.agent.mode_detector import AgentMode
    assert AgentMode.SPEC.value      == "spec"
    assert AgentMode.RESEARCH.value  == "research"
    assert AgentMode.IMPLEMENT.value == "implement"
    assert AgentMode.DEBUG.value     == "debug"
    assert AgentMode.TEST.value      == "test"
    assert AgentMode.REVIEW.value    == "review"


# ── ComplexityLevel enum ──────────────────────────────────────────────────

def test_complexity_values():
    from backend.agent.mode_detector import ComplexityLevel
    assert ComplexityLevel.SIMPLE.value  == "simple"
    assert ComplexityLevel.COMPLEX.value == "complex"
    assert ComplexityLevel.UNKNOWN.value == "unknown"


# ── ModeResult dataclass ──────────────────────────────────────────────────

def test_mode_result_fields():
    from backend.agent.mode_detector import AgentMode, ModeResult, ComplexityLevel
    r = ModeResult(
        mode=AgentMode.IMPLEMENT,
        complexity=ComplexityLevel.UNKNOWN,
        needs_clarification=False,
        trigger="default",
        confidence=0.3,
    )
    assert r.mode == AgentMode.IMPLEMENT
    assert r.trigger == "default"
    assert r.confidence == 0.3


# ── Slash commands — deterministic overrides ──────────────────────────────

def test_slash_spec():
    from backend.agent.mode_detector import AgentMode, ModeDetector
    result = ModeDetector().detect("/spec design a login system")
    assert result.mode == AgentMode.SPEC
    assert result.trigger == "slash_command"
    assert result.confidence == 1.0


def test_slash_debug():
    from backend.agent.mode_detector import AgentMode, ModeDetector
    result = ModeDetector().detect("/debug the auth is broken")
    assert result.mode == AgentMode.DEBUG
    assert result.trigger == "slash_command"
    assert result.confidence == 1.0


def test_slash_research():
    from backend.agent.mode_detector import AgentMode, ModeDetector
    result = ModeDetector().detect("/research best vector databases")
    assert result.mode == AgentMode.RESEARCH
    assert result.confidence == 1.0


def test_slash_implement():
    from backend.agent.mode_detector import AgentMode, ModeDetector
    result = ModeDetector().detect("/implement a rate limiter")
    assert result.mode == AgentMode.IMPLEMENT
    assert result.confidence == 1.0


def test_slash_test():
    from backend.agent.mode_detector import AgentMode, ModeDetector
    result = ModeDetector().detect("/test the payment module")
    assert result.mode == AgentMode.TEST
    assert result.confidence == 1.0


def test_slash_review():
    from backend.agent.mode_detector import AgentMode, ModeDetector
    result = ModeDetector().detect("/review this PR")
    assert result.mode == AgentMode.REVIEW
    assert result.confidence == 1.0


def test_slash_ask_triggers_clarification():
    """/ask triggers needs_clarification=True regardless of mode."""
    from backend.agent.mode_detector import ModeDetector
    result = ModeDetector().detect("/ask what stack should we use")
    assert result.needs_clarification is True
    assert result.trigger == "slash_command"


# ── Keyword inference ────────────────────────────────────────────────────

def test_unknown_input_defaults_to_implement():
    from backend.agent.mode_detector import AgentMode, ModeDetector
    result = ModeDetector().detect("hello there")
    assert result.mode == AgentMode.IMPLEMENT


def test_debug_keywords():
    from backend.agent.mode_detector import AgentMode, ModeDetector
    result = ModeDetector().detect("the login is broken and throwing an error")
    assert result.mode == AgentMode.DEBUG


def test_spec_keywords():
    from backend.agent.mode_detector import AgentMode, ModeDetector
    result = ModeDetector().detect("design a new authentication system")
    assert result.mode == AgentMode.SPEC


def test_implement_keywords():
    from backend.agent.mode_detector import AgentMode, ModeDetector
    result = ModeDetector().detect("build a new component")
    assert result.mode == AgentMode.IMPLEMENT


def test_research_keywords():
    from backend.agent.mode_detector import AgentMode, ModeDetector
    result = ModeDetector().detect("compare the best vector database options")
    assert result.mode == AgentMode.RESEARCH


def test_test_keywords():
    from backend.agent.mode_detector import AgentMode, ModeDetector
    result = ModeDetector().detect("write tests for the auth module")
    assert result.mode == AgentMode.TEST


def test_review_keywords():
    from backend.agent.mode_detector import AgentMode, ModeDetector
    result = ModeDetector().detect("review this code and give feedback on it")
    assert result.mode == AgentMode.REVIEW


# ── Complexity detection ──────────────────────────────────────────────────

def test_simple_complexity():
    from backend.agent.mode_detector import ComplexityLevel, ModeDetector
    result = ModeDetector().detect("/spec add a simple button")
    assert result.complexity == ComplexityLevel.SIMPLE


def test_complex_complexity():
    from backend.agent.mode_detector import ComplexityLevel, ModeDetector
    result = ModeDetector().detect("/spec design the full authentication system architecture")
    assert result.complexity == ComplexityLevel.COMPLEX


# ── Never raises ─────────────────────────────────────────────────────────

def test_detect_never_raises_on_empty():
    from backend.agent.mode_detector import AgentMode, ModeDetector
    result = ModeDetector().detect("")
    assert result.mode == AgentMode.IMPLEMENT


def test_detect_never_raises_on_garbage():
    from backend.agent.mode_detector import ModeDetector
    result = ModeDetector().detect("!@#$%^&*() ??? \x00\xff")
    assert result is not None


def test_detect_never_raises_with_broken_context():
    """Even if context_package is malformed, detect() must not raise."""
    from backend.agent.mode_detector import AgentMode, ModeDetector

    class BrokenContext:
        @property
        def topology_primitive(self):
            raise RuntimeError("db down")

    result = ModeDetector().detect(
        "design a system",
        context_package=BrokenContext(),
        is_mature=True,
    )
    assert result.mode == AgentMode.SPEC


# ── Graph suppresses clarification ───────────────────────────────────────

def test_graph_suppresses_clarification_when_mature():
    """If graph has topology_primitive, no need to ask."""
    from backend.agent.mode_detector import ModeDetector
    from unittest.mock import MagicMock

    ctx = MagicMock()
    ctx.topology_primitive = "core"
    ctx.tier1_directives = "[CONDUCT: auto]"

    result = ModeDetector().detect(
        "/spec design a system",
        context_package=ctx,
        is_mature=True,
    )
    # topology known → suppress clarification
    assert result.needs_clarification is False


# ── Confidence ────────────────────────────────────────────────────────────

def test_slash_command_always_full_confidence():
    from backend.agent.mode_detector import ModeDetector
    for cmd in ("/spec", "/debug", "/research", "/implement", "/test", "/review"):
        result = ModeDetector().detect(f"{cmd} do something")
        assert result.confidence == 1.0, f"{cmd} should have confidence 1.0"
