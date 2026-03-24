"""
Mode Detector — Director Mode System
File: IRISVOICE/backend/agent/mode_detector.py

Detects operating mode for a given task.
Slash commands are deterministic overrides — always win.
Inference is keyword-based with Mycelium context weighting.
Falls back to IMPLEMENT when uncertain — doing beats asking.

Source: specs/director_mode_system.md
Gate 1 Step 1.2
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class AgentMode(Enum):
    SPEC      = "spec"
    RESEARCH  = "research"
    IMPLEMENT = "implement"
    DEBUG     = "debug"
    TEST      = "test"
    REVIEW    = "review"


class ComplexityLevel(Enum):
    SIMPLE  = "simple"
    COMPLEX = "complex"
    UNKNOWN = "unknown"


@dataclass
class ModeResult:
    mode: AgentMode
    complexity: ComplexityLevel
    needs_clarification: bool
    trigger: str        # "slash_command" | "inference" | "default"
    confidence: float   # 0.0–1.0 — how sure the detector is


class ModeDetector:
    """
    Detects the operating mode for a given task.
    Slash commands are deterministic overrides — always win.
    Inference is keyword-based with Mycelium context weighting.
    Falls back to IMPLEMENT when uncertain — doing beats asking.
    """

    SLASH_COMMANDS = {
        "/spec":       AgentMode.SPEC,
        "/research":   AgentMode.RESEARCH,
        "/implement":  AgentMode.IMPLEMENT,
        "/debug":      AgentMode.DEBUG,
        "/test":       AgentMode.TEST,
        "/review":     AgentMode.REVIEW,
        "/ask":        None,   # triggers clarification in current mode
    }

    MODE_KEYWORDS = {
        AgentMode.SPEC: [
            "design", "plan", "architect", "spec", "spec out",
            "how should we build", "what's the approach", "structure",
            "system design", "blueprint", "outline the", "document",
        ],
        AgentMode.RESEARCH: [
            "research", "find out", "compare", "what's the best",
            "investigate", "explore options", "look into", "survey",
            "what are the options", "pros and cons", "alternatives",
        ],
        AgentMode.DEBUG: [
            "fix", "broken", "error", "not working", "why is",
            "failing", "exception", "crash", "bug", "wrong output",
            "unexpected", "traceback", "doesn't work",
        ],
        AgentMode.TEST: [
            "write tests", "test coverage", "verify", "add tests for",
            "check that", "unit test", "integration test", "test suite",
            "assert", "test the",
        ],
        AgentMode.REVIEW: [
            "review", "check my", "is this correct", "does this look right",
            "critique", "feedback on", "evaluate", "assess", "look at this",
        ],
        AgentMode.IMPLEMENT: [
            "build", "code", "create", "write", "add", "integrate",
            "make", "implement", "generate", "produce",
        ],
    }

    COMPLEXITY_SIMPLE = [
        "small", "quick", "minor", "simple", "just", "tiny",
        "tweak", "rename", "change the", "add a button", "update the",
    ]

    COMPLEXITY_COMPLEX = [
        "system", "architecture", "full", "complete", "production",
        "scalable", "redesign", "overhaul", "from scratch", "integrate",
        "end-to-end", "entire", "whole",
    ]

    def detect(
        self,
        task: str,
        context_package=None,
        is_mature: bool = False,
    ) -> ModeResult:
        """
        Returns ModeResult. Never raises.
        Priority: slash commands > keyword inference > default (IMPLEMENT)
        """
        try:
            task_lower = task.lower().strip()

            # 1. Slash command check — deterministic override
            for cmd, mode in self.SLASH_COMMANDS.items():
                if task_lower.startswith(cmd):
                    if cmd == "/ask":
                        return ModeResult(
                            mode=AgentMode.IMPLEMENT,
                            complexity=ComplexityLevel.UNKNOWN,
                            needs_clarification=True,
                            trigger="slash_command",
                            confidence=1.0,
                        )
                    return ModeResult(
                        mode=mode,
                        complexity=self._detect_complexity(task_lower),
                        needs_clarification=False,
                        trigger="slash_command",
                        confidence=1.0,
                    )

            # 2. Keyword inference
            mode, confidence = self._infer_mode(task_lower)

            # 3. Complexity detection
            complexity = self._detect_complexity(task_lower)

            # 4. Needs clarification?
            # Ask when: SPEC mode + UNKNOWN complexity,
            # OR confidence < 0.5 and task is long/ambiguous
            needs_clarification = (
                (mode == AgentMode.SPEC and complexity == ComplexityLevel.UNKNOWN)
                or (confidence < 0.5 and len(task.split()) > 15)
            )

            # Suppress clarification if graph already has the answer
            if needs_clarification and is_mature and context_package is not None:
                needs_clarification = self._graph_has_answer(
                    mode, complexity, context_package
                )

            return ModeResult(
                mode=mode,
                complexity=complexity,
                needs_clarification=needs_clarification,
                trigger="inference",
                confidence=confidence,
            )

        except Exception:
            return ModeResult(
                mode=AgentMode.IMPLEMENT,
                complexity=ComplexityLevel.UNKNOWN,
                needs_clarification=False,
                trigger="default",
                confidence=0.0,
            )

    def _infer_mode(self, task_lower: str) -> Tuple[AgentMode, float]:
        """Keyword scoring. Returns (mode, confidence).
        Multi-word keywords score by word count so 'write tests' (2) beats 'write' (1).
        """
        scores = {mode: 0 for mode in AgentMode}
        for mode, keywords in self.MODE_KEYWORDS.items():
            for kw in keywords:
                if kw in task_lower:
                    scores[mode] += len(kw.split())  # weight by specificity

        total = sum(scores.values())
        if total == 0:
            return AgentMode.IMPLEMENT, 0.3   # default fallback

        best_mode = max(scores, key=scores.get)
        confidence = scores[best_mode] / max(total, 1)
        confidence = min(confidence + 0.3, 1.0)  # floor boost for any match

        return best_mode, confidence

    def _detect_complexity(self, task_lower: str) -> ComplexityLevel:
        """Simple keyword scan for complexity signals."""
        simple_hits  = sum(1 for kw in self.COMPLEXITY_SIMPLE if kw in task_lower)
        complex_hits = sum(1 for kw in self.COMPLEXITY_COMPLEX if kw in task_lower)

        if complex_hits > simple_hits:
            return ComplexityLevel.COMPLEX
        if simple_hits > complex_hits:
            return ComplexityLevel.SIMPLE
        return ComplexityLevel.UNKNOWN

    def _graph_has_answer(
        self, mode: AgentMode, complexity: ComplexityLevel, context_package
    ) -> bool:
        """
        Check if Mycelium graph already has enough context that
        clarification questions would be redundant.
        Returns True if clarification is STILL needed.
        Returns False if graph already knows (suppress the ask).
        """
        try:
            if context_package.topology_primitive not in ("unknown", ""):
                return False
            if context_package.tier1_directives:
                return False
            return True
        except Exception:
            return True  # default to asking if check fails
