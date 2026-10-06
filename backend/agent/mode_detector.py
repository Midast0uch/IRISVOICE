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

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)


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

    MODE_CONSUMER = "mode"
    MODE_LABELS = ("spec", "research", "implement", "debug", "test", "review")
    MODE_INSTRUCTION = "Which operating mode should this task run in?"

    def __init__(self) -> None:
        # REQ-15 (T19): the `mode` engine consumer, SHADOW. `None` means no
        # engine is wired — `detect()` then behaves exactly as it did before
        # (hand-set keyword confidence), so no call site changes.
        self._mode_engine = None
        self.last_mode_shadow: Optional[dict] = None

    def set_mode_engine(self, engine) -> None:
        """Wire the shadow-scoring engine. None disables it explicitly — the
        module singleton is never adopted implicitly (a shadow must not be
        able to load a 651MB model as a side effect of detecting a mode)."""
        self._mode_engine = engine

    def _engine_mode_shadow(
        self, task_lower: str, keyword_mode: "AgentMode"
    ) -> Optional[dict]:
        """Score the mode with the engine; return the shadow row (AC15.1/AC15.2).

        SHADOW ONLY: the returned dict carries the engine's own pick AND the
        keyword's pick, so parity is measurable — the loop still runs the
        keyword mode. The CONFIDENCE reported on the inference branch becomes
        the engine's measured probability for the keyword-chosen mode: pairing
        a mode with a foreign confidence would be incoherent.

        Returns None (no row, no confidence change) when no engine is wired,
        the engine cannot answer, or the engine's option set does not include
        the keyword mode. Never raises.
        """
        try:
            if self._mode_engine is None:
                return None
            from backend.agent.decision_backend_onnx import (
                ConsumerSpec,
                get_consumer_spec,
                register_consumer_spec,
            )
            if get_consumer_spec(self.MODE_CONSUMER) is None:
                register_consumer_spec(ConsumerSpec(
                    consumer_id=self.MODE_CONSUMER,
                    task_name=self.MODE_CONSUMER,
                    instruction=self.MODE_INSTRUCTION,
                    labels=self.MODE_LABELS,
                ))

            ds = self._mode_engine.decide(
                self.MODE_CONSUMER, list(self.MODE_LABELS),
                {"goal": task_lower[:400]},
            )
            if ds is None:
                return None
            dist = {c.name: float(c.prob) for c in (ds.distribution or ())}
            if keyword_mode.value not in dist:
                return None  # never pair a mode with a foreign confidence
            return {
                "consumer_id": self.MODE_CONSUMER,
                # The canonical parity pair the report reads: the engine's pick,
                # and the Brain's ACTUAL pick. `chosen`/`brain_choice` are the
                # field names the single writer and the enforcement report both
                # expect (2026-09-27). This row previously carried the same two
                # facts under `engine_mode`/`keyword_mode`, which the ledger's
                # meta whitelist does not pass, so the row landed with no parity
                # reference and could never be scored.
                "chosen": ds.chosen,
                "brain_choice": keyword_mode.value,
                # ECE pairs a row's confidence with THAT ROW'S `chosen`, and this
                # row's `chosen` is the ENGINE's pick. Reporting the probability
                # of the KEYWORD mode here was incoherent: the engine is often
                # right while giving its own pick only a modest probability, so
                # every correct row read as under-confident and the calibration
                # error came out at 0.268 against a 0.05 bar (measured
                # 2026-09-27, 102 rows).
                "confidence": round(dist.get(ds.chosen, dist[keyword_mode.value]), 4),
                # The LIVE branch's number is unchanged: it reports the engine's
                # probability for the mode that actually runs, as its docstring
                # requires. Two callers, two coherent meanings.
                "keyword_confidence": round(dist[keyword_mode.value], 4),
                "engine_latency_ms": ds.engine_latency_ms,
                "shadow": True,
            }
        except Exception as e:  # noqa: BLE001 — a shadow never breaks routing
            logger.debug("[mode_detector] shadow failed: %r", e)
            return None

    def _shadow_mode_async(self, task_lower: str, keyword_mode: "AgentMode") -> None:
        """Score the mode on the ``oracle_shadow`` lane and expose the row from
        there (``last_mode_shadow``; the kernel forwards it once). The reply never
        waits: measured 446 ms per turn when this ran inline. Never raises."""
        if self._mode_engine is None:
            return

        def _job() -> None:
            row = self._engine_mode_shadow(task_lower, keyword_mode)
            if row is not None:
                self.last_mode_shadow = row

        try:
            from backend.utils.durability_queue import lane

            if not lane("oracle_shadow").submit("shadow:mode", _job):
                logger.warning("[mode_detector] mode shadow dropped (lane full)")
        except Exception as e:  # noqa: BLE001 — a shadow never breaks routing
            logger.warning("[mode_detector] mode shadow submit failed: %r", e)

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

            # REQ-15 AC15.2 (T19): on the INFERENCE branch the reported
            # confidence may be the ENGINE's measured probability for the chosen
            # mode, not the hand-set keyword float — a claim replaced by a
            # measurement. The MODE stays keyword-decided (AC15.1 shadow: the
            # engine's own pick is recorded, never applied, until AC15.4's
            # measured bar is met). No engine → today's float, unchanged.
            #
            # Stage B (2026-10-05): the replacement happens ONLY through the
            # enforcement chokepoint. It used to happen always, though `mode` is
            # not enforced, so an unearned probability fed `needs_clarification`
            # (confidence < 0.5 on a long task). Not deciding -> the keyword
            # confidence stands and the score runs on the lane.
            from backend.agent.decision_engine import decides, oracle_acts

            if decides(self.MODE_CONSUMER) is None:
                self._shadow_mode_async(task_lower, mode)
            else:
                _shadow = self._engine_mode_shadow(task_lower, mode)
                if _shadow is not None:
                    self.last_mode_shadow = _shadow
                    # The row's `confidence` is the engine's probability for the
                    # engine's PICK (what ECE is computed against); acting
                    # needs the chosen answer's confidence on that scale.
                    if oracle_acts(self.MODE_CONSUMER, _shadow["confidence"]):
                        # The live confidence is the engine's probability for the
                        # mode that RUNS (the keyword mode).
                        confidence = _shadow.get(
                            "keyword_confidence", _shadow["confidence"]
                        )

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
