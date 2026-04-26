Director Mode System
Design · Requirements · Tasks
Mode Detection · Ask User Tool · Spec Engine · DER Token Budget
IRISVOICE/backend/agent/ · March 2026 · IRIS / Torus Network
Part 1: Design
Overview
The Director Mode System gives the agent the ability to recognize what kind
of task it is actually facing before producing any plan. It adds a mode
detection layer between task classification and planning, a structured Ask
User tool for gathering missing context, a Spec Engine for producing
design/requirements/tasks documents, and replaces the DER cycle limit with
a token budget appropriate to each mode.

The core principle: The Director should behave like a senior engineer who reads a request and immediately knows — is this a planning conversation, a research task, an implementation job, a debugging session, or something that needs more information first? Each requires a different approach to the graph, a different planning strategy, and different output.

One new rule added to the non-negotiable: User answers from the Ask User tool are always ingested as coordinate signals. A user who says "Python always" once never gets asked again. The graph learned it.

Architecture
handle()
    │
    ├─ 1. TaskClassifier.classify()           ← existing
    │
    ├─ 2. ModeDetector.detect()               ← NEW
    │         │
    │         ├─ checks for slash commands first (/spec /research /debug etc.)
    │         ├─ reads Mycelium context package for mode inference
    │         └─ returns (Mode, complexity_level, needs_clarification)
    │
    ├─ 3. IF needs_clarification:
    │         AskUserTool.build_questions()   ← NEW
    │         → surface questions to user
    │         → receive answers
    │         → ingest each answer as coordinate signal
    │         → continue with enriched context
    │
    ├─ 4. Director plans in mode context      ← _plan_task() extended
    │         ├─ mode sets token budget
    │         ├─ mode shapes graph read strategy
    │         └─ mode determines output format
    │
    └─ 5. _execute_plan_der()                 ← existing, token-budget aware
The Six Modes
SPEC        Triggered by: /spec, "design", "plan", "architect", "spec out",
                          "how should we build", "what's the approach"
            Graph reads:  topology_primitive (calibrate depth to expertise)
                          active_contracts (what constraints apply)
            Output:       short doc (simple) or full 3-doc set (complex)
            Token budget: 60,000

RESEARCH    Triggered by: /research, "find out", "compare", "what's the best",
                          "investigate", "explore options", "look into"
            Graph reads:  ambient_signals (expand into unmapped territory)
                          concentration_field (find high-density knowledge regions)
            Output:       structured findings doc
            Token budget: 80,000

IMPLEMENT   Triggered by: /implement, "build", "code", "create", "write",
                          "add", "integrate", "make"
            Graph reads:  full context package — directives, predictions,
                          contracts, gradient warnings
            Output:       working code / implementation
            Token budget: 40,000

DEBUG       Triggered by: /debug, "fix", "broken", "error", "not working",
                          "why is", "failing", "exception", "crash"
            Graph reads:  gradient_warnings FIRST (danger map as pre-diagnosis)
                          tier3_failures (past correction patterns)
            Output:       diagnosis + fix
            Token budget: 30,000

TEST        Triggered by: /test, "write tests", "test coverage", "verify",
                          "add tests for", "check that"
            Graph reads:  active_contracts (behavioral invariants to test)
                          causal_context (why things work, what to verify)
            Output:       test suite
            Token budget: 40,000

REVIEW      Triggered by: /review, "review this", "check my", "is this correct",
                          "does this look right", "critique"
            Graph reads:  gradient_warnings (known failure patterns as checklist)
                          tier3_failures (past mistakes to look for)
            Output:       review notes + recommendations
            Token budget: 20,000
Complexity Detection
Within SPEC mode, the Director determines output depth:

python
COMPLEXITY_SIGNALS = {
    "simple": [
        "add a button", "change the color", "rename", "small tweak",
        "quick fix", "minor", "simple", "just need to"
    ],
    "complex": [
        "system", "architecture", "integrate", "redesign", "overhaul",
        "from scratch", "full", "complete", "production", "scalable"
    ]
}
Simple → single lightweight doc (~200-400 lines, one file)
Complex → full three-doc set (design + requirements + tasks)
Ambiguous → Director asks one complexity-gauging question via AskUserTool

Ask User Tool
The Ask User tool is a first-class MCP tool. It is invoked as a CLARIFY
step in the plan. Questions are presented all at once. User answers together.
One round trip maximum per session — the Director cannot ask twice.

Input schema:

python
{
    "questions": [
        {
            "id": "q1",
            "text": "question text",
            "type": "single_select | multi_select | free_text",
            "options": ["opt1", "opt2"],   # required for select types
            "required": True
        }
    ],
    "context": "one sentence explaining why you need this"
}
Output schema:

python
{
    "q1": "selected_option_or_free_text",
    "q2": "..."
}
Coordinate ingestion: Every answer is immediately ingested into Mycelium via ingest_statement() with confidence=0.6. This is higher than the strategy signal confidence (0.4) because explicit user answers are more reliable than inferred behavioral patterns. The graph learns from what users say, not just what they do.

Recency rule: If the graph already has a confident coordinate for the information being asked, the question is suppressed. The Director reads the graph before building questions. It only asks what it genuinely doesn't know.

Spec Engine
The Spec Engine produces spec documents when in SPEC mode. It follows the
same three-document format used throughout this project for complex tasks,
and a lighter single-document format for simple tasks.

Simple output structure:

# Feature: {name}
## What it does
## How it fits into the existing system
## Implementation steps (numbered)
## What NOT to change
Complex output structure:

design.md      — architecture, data models, API changes, sequence diagrams
requirements.md — user stories with acceptance criteria
tasks.md       — phased implementation plan with verification steps
The Spec Engine reads the topology primitive to calibrate depth. CORE users
get lean specs that trust their judgment. ACQUISITION users get detailed
specs with reasoning and alternatives.

Token Budget (replaces DER cycle limit)
python
DER_TOKEN_BUDGETS = {
    "SPEC":       60_000,
    "RESEARCH":   80_000,
    "IMPLEMENT":  40_000,
    "DEBUG":      30_000,
    "TEST":       40_000,
    "REVIEW":     20_000,
    "DEFAULT":    40_000,   # fallback when mode unknown
}

DER_EMERGENCY_STOP    = 200   # cycle count emergency brake only
DER_MAX_VETO_PER_ITEM = 2     # unchanged
The loop checks token budget instead of cycle count:

python
estimated_tokens_used = sum(s.tokens_used for s in plan.steps)
if estimated_tokens_used >= current_token_budget:
    break  # synthesize what we have — graph keeps everything learned
Partial progress is valuable. The graph learned from every completed step.
The next session starts from a richer graph and continues from where this
session ended. The map keeps growing across sessions.

File Map
Class / Component	File	Status
ModeDetector	IRISVOICE/backend/agent/mode_detector.py	CREATE
AskUserTool	IRISVOICE/backend/agent/ask_user_tool.py	CREATE
SpecEngine	IRISVOICE/backend/agent/spec_engine.py	CREATE
AgentMode enum	IRISVOICE/backend/agent/mode_detector.py	CREATE
AgentKernel	IRISVOICE/backend/agent/agent_kernel.py	EXISTS — extend
der_loop.py	IRISVOICE/backend/agent/der_loop.py	EXISTS — update constants
New File: mode_detector.py
python
# CREATE: IRISVOICE/backend/agent/mode_detector.py

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple
import re


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
    trigger: str            # "slash_command" | "inference" | "default"
    confidence: float       # 0.0–1.0 — how sure the detector is


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
            "system design", "blueprint", "outline the", "document"
        ],
        AgentMode.RESEARCH: [
            "research", "find out", "compare", "what's the best",
            "investigate", "explore options", "look into", "survey",
            "what are the options", "pros and cons", "alternatives"
        ],
        AgentMode.DEBUG: [
            "fix", "broken", "error", "not working", "why is",
            "failing", "exception", "crash", "bug", "wrong output",
            "unexpected", "traceback", "doesn't work"
        ],
        AgentMode.TEST: [
            "write tests", "test coverage", "verify", "add tests for",
            "check that", "unit test", "integration test", "test suite",
            "assert", "test the"
        ],
        AgentMode.REVIEW: [
            "review", "check my", "is this correct", "does this look right",
            "critique", "feedback on", "evaluate", "assess", "look at this"
        ],
        AgentMode.IMPLEMENT: [
            "build", "code", "create", "write", "add", "integrate",
            "make", "implement", "generate", "produce"
        ],
    }

    COMPLEXITY_SIMPLE = [
        "small", "quick", "minor", "simple", "just", "tiny",
        "tweak", "rename", "change the", "add a button", "update the"
    ]

    COMPLEXITY_COMPLEX = [
        "system", "architecture", "full", "complete", "production",
        "scalable", "redesign", "overhaul", "from scratch", "integrate",
        "end-to-end", "entire", "whole"
    ]

    def detect(
        self,
        task: str,
        context_package=None,
        is_mature: bool = False
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
                        # /ask triggers clarification in default IMPLEMENT mode
                        return ModeResult(
                            mode=AgentMode.IMPLEMENT,
                            complexity=ComplexityLevel.UNKNOWN,
                            needs_clarification=True,
                            trigger="slash_command",
                            confidence=1.0
                        )
                    return ModeResult(
                        mode=mode,
                        complexity=self._detect_complexity(task_lower),
                        needs_clarification=False,
                        trigger="slash_command",
                        confidence=1.0
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

            # BUT: suppress clarification if graph already has the answer
            if needs_clarification and is_mature and context_package is not None:
                needs_clarification = self._graph_has_answer(
                    mode, complexity, context_package
                )

            return ModeResult(
                mode=mode,
                complexity=complexity,
                needs_clarification=needs_clarification,
                trigger="inference",
                confidence=confidence
            )

        except Exception:
            return ModeResult(
                mode=AgentMode.IMPLEMENT,
                complexity=ComplexityLevel.UNKNOWN,
                needs_clarification=False,
                trigger="default",
                confidence=0.0
            )

    def _infer_mode(self, task_lower: str) -> Tuple[AgentMode, float]:
        """Keyword scoring. Returns (mode, confidence)."""
        scores = {mode: 0 for mode in AgentMode}
        for mode, keywords in self.MODE_KEYWORDS.items():
            for kw in keywords:
                if kw in task_lower:
                    scores[mode] += 1

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
        Check if the Mycelium graph already has enough context that
        clarification questions would be redundant.
        Returns True if clarification is STILL needed (graph doesn't have it).
        Returns False if graph already knows (suppress the ask).
        """
        try:
            # If topology is known and not 'unknown', graph knows the user well
            if context_package.topology_primitive not in ("unknown", ""):
                return False
            # If conduct directives are present, working style is known
            if context_package.tier1_directives:
                return False
            # Graph doesn't have enough — still need to ask
            return True
        except Exception:
            return True  # default to asking if check fails
New File: ask_user_tool.py
python
# CREATE: IRISVOICE/backend/agent/ask_user_tool.py

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json


@dataclass
class AskQuestion:
    id: str
    text: str
    type: str           # "single_select" | "multi_select" | "free_text"
    options: List[str]  = field(default_factory=list)
    required: bool      = True


@dataclass
class AskPayload:
    questions: List[AskQuestion]
    context: str        # one sentence explaining why these are needed


class AskUserTool:
    """
    Structured question tool for the Director.
    Questions are built by the Director, presented all at once,
    answered together by the user.

    One round trip per session maximum.
    Every answer is ingested into Mycelium as a coordinate signal.

    The Director calls build_questions() to generate the payload.
    The payload is surfaced to the user as a CLARIFY step.
    When answers arrive, ingest_answers() persists them to the graph.
    """

    def __init__(self, adapter, memory_interface):
        self.adapter = adapter
        self.memory  = memory_interface

    def build_questions(
        self,
        task: str,
        mode: str,
        context_package,
        is_mature: bool
    ) -> Optional[AskPayload]:
        """
        Generate questions the Director needs answered before planning.
        Returns None if no questions are needed (graph already has context).
        Never raises.
        """
        try:
            prompt = self._build_question_prompt(
                task=task,
                mode=mode,
                context_package=context_package,
                is_mature=is_mature
            )

            response = self.adapter.infer(
                prompt,
                role="REASONING",
                max_tokens=600,
                temperature=0.1
            )

            return self._parse_questions(response.raw_text, task, mode)

        except Exception:
            return None

    def ingest_answers(
        self,
        answers: Dict[str, str],
        questions: List[AskQuestion],
        session_id: str
    ) -> None:
        """
        Ingest every answer as a Mycelium coordinate signal.
        confidence=0.6 — explicit user statements are reliable.
        Never raises.
        """
        try:
            for question in questions:
                answer = answers.get(question.id)
                if not answer:
                    continue

                # Build a natural language statement from Q+A pair
                statement = f"{question.text}: {answer}"

                try:
                    self.memory.mycelium_ingest_statement(
                        statement=statement,
                        session_id=session_id
                    )
                except Exception:
                    pass  # individual answer failure never blocks others

        except Exception:
            pass  # ingestion failure never blocks execution

    def _build_question_prompt(
        self,
        task: str,
        mode: str,
        context_package,
        is_mature: bool
    ) -> str:
        """
        Prompt for the Director to generate clarifying questions.
        Only asks what the graph genuinely doesn't know.
        Maximum 3 questions — never overwhelm the user.
        """
        known_context = ""
        if is_mature and context_package is not None:
            try:
                directives = context_package.tier1_directives or ""
                topology   = context_package.topology_primitive or "unknown"
                known_context = (
                    f"WHAT THE GRAPH ALREADY KNOWS:\n"
                    f"  User topology: {topology}\n"
                    f"  Directives: {directives[:200]}\n"
                )
            except Exception:
                pass

        return (
            f"TASK: {task}\n"
            f"MODE: {mode}\n\n"
            f"{known_context}\n"
            "You are about to plan this task. What information is MISSING "
            "that would significantly change your plan?\n\n"
            "Rules:\n"
            "1. Maximum 3 questions\n"
            "2. Only ask what you genuinely don't know\n"
            "3. Don't ask what the graph already knows (shown above)\n"
            "4. Prefer single_select over free_text — easier for the user\n"
            "5. If you have everything you need, return an empty questions list\n\n"
            "OUTPUT: JSON only.\n"
            '{"context":"why you need this in one sentence",'
            '"questions":['
            '{"id":"q1","text":"question","type":"single_select",'
            '"options":["opt1","opt2"],"required":true}'
            "]}"
        )

    def _parse_questions(
        self, raw: str, task: str, mode: str
    ) -> Optional["AskPayload"]:
        """Parse model response into AskPayload. Returns None on empty or failure."""
        try:
            import re
            m = re.search(r'\{[\s\S]+\}', raw)
            if not m:
                return None

            data = json.loads(m.group())
            raw_questions = data.get("questions", [])

            if not raw_questions:
                return None

            questions = []
            for q in raw_questions[:3]:  # hard cap at 3
                questions.append(AskQuestion(
                    id=q.get("id", f"q{len(questions)+1}"),
                    text=q.get("text", ""),
                    type=q.get("type", "single_select"),
                    options=q.get("options", []),
                    required=q.get("required", True)
                ))

            return AskPayload(
                questions=questions,
                context=data.get("context", "")
            )

        except Exception:
            return None
New File: spec_engine.py
python
# CREATE: IRISVOICE/backend/agent/spec_engine.py

from dataclasses import dataclass
from typing import Optional


@dataclass
class SpecOutput:
    """Output from the Spec Engine."""
    title: str
    is_complex: bool
    # Simple output
    single_doc: Optional[str] = None
    # Complex output
    design_doc: Optional[str] = None
    requirements_doc: Optional[str] = None
    tasks_doc: Optional[str] = None


class SpecEngine:
    """
    Produces spec documents when the Director is in SPEC mode.

    Simple tasks  → single lightweight doc
    Complex tasks → full three-doc set (design + requirements + tasks)

    Reads topology_primitive from context package to calibrate depth:
    - CORE user       → lean, assumes context, no hand-holding
    - ACQUISITION     → detailed, includes reasoning and alternatives
    - EXPLORATION     → includes theory-to-practice bridging
    - Everything else → standard depth

    Never raises. Returns SpecOutput with None fields on failure.
    """

    DEPTH_BY_TOPOLOGY = {
        "core":        "lean",      # trusts judgment, minimal scaffolding
        "acquisition": "detailed",  # includes reasoning, alternatives
        "exploration": "bridged",   # theory-to-practice connections
        "transfer":    "standard",
        "orbit":       "detailed",  # extra clarity — user is circling a gap
        "evolution":   "lean",      # user has grown past this area
        "unknown":     "standard",
    }

    def __init__(self, adapter, memory_interface):
        self.adapter = adapter
        self.memory  = memory_interface

    def produce(
        self,
        task: str,
        is_complex: bool,
        context_package,
        is_mature: bool,
        session_id: str
    ) -> SpecOutput:
        """
        Produces spec output appropriate to task complexity.
        Never raises. Returns SpecOutput with None fields on failure.
        """
        try:
            topology  = "unknown"
            depth     = "standard"

            if is_mature and context_package is not None:
                try:
                    topology = context_package.topology_primitive
                    depth    = self.DEPTH_BY_TOPOLOGY.get(topology, "standard")
                except Exception:
                    pass

            title = self._extract_title(task)

            if is_complex:
                return self._produce_complex(
                    task=task, title=title, depth=depth,
                    context_package=context_package, is_mature=is_mature
                )
            else:
                return self._produce_simple(
                    task=task, title=title, depth=depth,
                    context_package=context_package, is_mature=is_mature
                )

        except Exception:
            return SpecOutput(title=task[:60], is_complex=is_complex)

    def _produce_simple(
        self, task, title, depth, context_package, is_mature
    ) -> SpecOutput:
        """Single lightweight doc for simple features."""
        context_block = ""
        if is_mature and context_package is not None:
            try:
                context_block = (
                    f"KNOWN CONTEXT:\n"
                    f"{context_package.get_system_zone_content()[:400]}\n\n"
                )
            except Exception:
                pass

        depth_instruction = {
            "lean":     "Be concise. User is an expert. No hand-holding.",
            "detailed": "Include reasoning for each step. Explain alternatives considered.",
            "bridged":  "Connect theory to practice. Explain the why before the how.",
            "standard": "Standard depth — clear and complete.",
        }.get(depth, "Standard depth.")

        prompt = (
            f"{context_block}"
            f"TASK: {task}\n\n"
            f"DEPTH INSTRUCTION: {depth_instruction}\n\n"
            "Produce a concise feature spec with these sections:\n"
            "# Feature: {title}\n"
            "## What it does\n"
            "## How it fits into the existing system\n"
            "## Implementation steps (numbered, specific)\n"
            "## What NOT to change\n\n"
            "Target: 150-400 lines. Actionable. No padding."
        )

        response = self.adapter.infer(
            prompt, role="REASONING", max_tokens=2000, temperature=0.1
        )

        return SpecOutput(
            title=title,
            is_complex=False,
            single_doc=response.raw_text
        )

    def _produce_complex(
        self, task, title, depth, context_package, is_mature
    ) -> SpecOutput:
        """Full three-doc set for complex systems."""
        context_block = ""
        if is_mature and context_package is not None:
            try:
                context_block = (
                    f"KNOWN CONTEXT:\n"
                    f"{context_package.get_system_zone_content()[:600]}\n\n"
                )
            except Exception:
                pass

        depth_instruction = {
            "lean":     "Expert audience. Lean docs. Trust their judgment.",
            "detailed": "Include reasoning, alternatives, and decision rationale.",
            "bridged":  "Bridge theory to implementation. Explain architectural decisions.",
            "standard": "Complete and precise. Standard engineering doc quality.",
        }.get(depth, "Complete and precise.")

        base_prompt = (
            f"{context_block}"
            f"TASK: {task}\n\n"
            f"DEPTH INSTRUCTION: {depth_instruction}\n\n"
        )

        # Produce all three docs
        design_doc = self._produce_design(base_prompt, title)
        requirements_doc = self._produce_requirements(base_prompt, title)
        tasks_doc = self._produce_tasks(base_prompt, title)

        return SpecOutput(
            title=title,
            is_complex=True,
            design_doc=design_doc,
            requirements_doc=requirements_doc,
            tasks_doc=tasks_doc
        )

    def _produce_design(self, base_prompt: str, title: str) -> str:
        prompt = (
            base_prompt +
            f"Produce design.md for: {title}\n"
            "Include: overview, file map, architecture diagram (ASCII),\n"
            "data models, API changes, sequence diagrams, error handling,\n"
            "what does NOT change.\n"
            "Follow the IRIS spec format established in this project."
        )
        r = self.adapter.infer(prompt, role="REASONING",
                               max_tokens=3000, temperature=0.1)
        return r.raw_text

    def _produce_requirements(self, base_prompt: str, title: str) -> str:
        prompt = (
            base_prompt +
            f"Produce requirements.md for: {title}\n"
            "Each requirement: user story + numbered acceptance criteria.\n"
            "Use THE SYSTEM SHALL format.\n"
            "Include non-requirements section at end.\n"
            "Follow the IRIS spec format established in this project."
        )
        r = self.adapter.infer(prompt, role="REASONING",
                               max_tokens=3000, temperature=0.1)
        return r.raw_text

    def _produce_tasks(self, base_prompt: str, title: str) -> str:
        prompt = (
            base_prompt +
            f"Produce tasks.md for: {title}\n"
            "Phased implementation plan. Each phase has a goal and\n"
            "a final check (run test suite, verify behavior).\n"
            "Each task has: file to modify, what to add, key rules,\n"
            "verification snippet (runnable Python).\n"
            "Include final verification checklist.\n"
            "Follow the IRIS spec format established in this project."
        )
        r = self.adapter.infer(prompt, role="REASONING",
                               max_tokens=3000, temperature=0.1)
        return r.raw_text

    def _extract_title(self, task: str) -> str:
        """Extract a short title from the task string."""
        words = task.strip().split()
        return " ".join(words[:6]).title() if words else "Feature Spec"
Part 2: Requirements
Requirement 28: AgentMode Enum and ModeDetector
THE SYSTEM SHALL create AgentMode enum in mode_detector.py with values: SPEC, RESEARCH, IMPLEMENT, DEBUG, TEST, REVIEW
THE SYSTEM SHALL create ModeDetector class with detect(task, context_package, is_mature) method
detect() SHALL check slash commands first — slash commands are deterministic overrides
detect() SHALL return ModeResult with fields: mode, complexity, needs_clarification, trigger, confidence
WHEN no slash command matches, SHALL infer mode from keyword scoring
WHEN inference confidence is below 0.5 AND task length > 15 words, SHALL set needs_clarification=True
WHEN is_mature=True and graph has sufficient context, SHALL suppress clarification even when confidence is low
detect() SHALL never raise — falls back to (IMPLEMENT, UNKNOWN, False)
THE SYSTEM SHALL define SLASH_COMMANDS mapping /spec, /research, /implement, /debug, /test, /review, /ask to their modes
/ask SHALL trigger needs_clarification=True in current mode regardless of task content
Requirement 29: Complexity Detection
THE SYSTEM SHALL detect ComplexityLevel as SIMPLE, COMPLEX, or UNKNOWN
SIMPLE signals: "small", "quick", "minor", "simple", "just", "tiny", "tweak", "rename", "change the", "add a button", "update the"
COMPLEX signals: "system", "architecture", "full", "complete", "production", "scalable", "redesign", "overhaul", "from scratch", "integrate", "end-to-end", "entire", "whole"
WHEN complex signals outnumber simple signals, SHALL return COMPLEX
WHEN simple signals outnumber complex signals, SHALL return SIMPLE
WHEN signals are equal, SHALL return UNKNOWN
Requirement 30: AskUserTool
THE SYSTEM SHALL create AskUserTool in ask_user_tool.py with build_questions() and ingest_answers() methods
build_questions() SHALL call the model with a prompt that shows what the graph already knows and asks only for genuinely missing context
build_questions() SHALL cap questions at 3 — never overwhelm the user
build_questions() SHALL return None when the model returns an empty questions list — no unnecessary asks
build_questions() SHALL return None on any exception — never blocks
ALL questions SHALL be presented to the user simultaneously — one round trip
ingest_answers() SHALL call mycelium_ingest_statement() for every answer as "{question_text}: {answer}" with confidence=0.6
ingest_answers() SHALL wrap each individual ingest in try/except pass
ingest_answers() SHALL never raise — answer ingestion never blocks execution
THE SYSTEM SHALL instantiate AskUserTool once in AgentKernel.__init__()
Requirement 31: SpecEngine
THE SYSTEM SHALL create SpecEngine in spec_engine.py with produce() method
WHEN is_complex=False, produce() SHALL call _produce_simple() and return SpecOutput with single_doc populated
WHEN is_complex=True, produce() SHALL call all three doc producers and return SpecOutput with design_doc, requirements_doc, tasks_doc
BOTH paths SHALL read topology_primitive and apply depth calibration:
core → lean (expert audience, minimal scaffolding)
acquisition → detailed (reasoning, alternatives)
orbit → detailed (extra clarity for circling user)
exploration → bridged (theory-to-practice connections)
evolution / transfer / unknown → standard
produce() SHALL never raise — returns SpecOutput with None fields on failure
THE SYSTEM SHALL instantiate SpecEngine once in AgentKernel.__init__()
Requirement 32: Mode Detection in handle()
THE SYSTEM SHALL add ModeDetector.detect() call in handle() between TaskClassifier.classify() and get_task_context_package()
THE SYSTEM SHALL store mode result: mode_result = self._mode_detector.detect(...)
THE SYSTEM SHALL pass mode_result.mode.value to _plan_task() as agent_mode parameter with safe default "implement"
WHEN mode_result.needs_clarification=True, THE SYSTEM SHALL call AskUserTool.build_questions() before planning
WHEN build_questions() returns questions, THE SYSTEM SHALL surface them to the user as a CLARIFY step in the plan and wait for answers
WHEN answers arrive, THE SYSTEM SHALL call ingest_answers() immediately before proceeding to _plan_task()
WHEN build_questions() returns None, THE SYSTEM SHALL proceed to planning without asking — graceful skip
Requirement 33: SPEC Mode Routing
WHEN mode_result.mode == AgentMode.SPEC, THE SYSTEM SHALL route execution to SpecEngine.produce() instead of _execute_plan_der()
THE SYSTEM SHALL pass is_complex=(mode_result.complexity == ComplexityLevel.COMPLEX)
WHEN complexity is UNKNOWN in SPEC mode, THE SYSTEM SHALL default to COMPLEX if the task text is over 20 words, SIMPLE if under
SpecEngine output SHALL be stored as the task result and returned to the user
SpecEngine output SHALL be stored via store_episode() unchanged
Requirement 34: Mode-Aware Graph Reads in _plan_task()
WHEN agent_mode == "debug", _plan_task() SHALL prepend gradient_warnings to tier1_directives before building the planning prompt — danger map first
WHEN agent_mode == "research", _plan_task() SHALL include ambient_signals prominently in the prompt — exploration prioritized over known landmarks
WHEN agent_mode == "test", _plan_task() SHALL include active_contracts and causal_context prominently — test against known behavioral invariants
WHEN agent_mode == "review", _plan_task() SHALL include gradient_warnings and tier3_failures as the primary context — known failure patterns as checklist
WHEN agent_mode == "implement" or "spec", SHALL use full context package in standard biological priority order — unchanged from existing behavior
Requirement 35: Token Budget Replaces Cycle Limit
THE SYSTEM SHALL remove DER_MAX_CYCLES = 40 from agent_kernel.py
THE SYSTEM SHALL define DER_TOKEN_BUDGETS dict in agent_kernel.py: SPEC=60000, RESEARCH=80000, IMPLEMENT=40000, DEBUG=30000, TEST=40000, REVIEW=20000, DEFAULT=40000
THE SYSTEM SHALL define DER_EMERGENCY_STOP = 200 as cycle count emergency brake only — should never be reached in normal operation
_execute_plan_der() SHALL check token budget each cycle: sum(s.tokens_used for s in plan.steps) >= current_token_budget
WHEN token budget is exceeded, SHALL break and call _synthesize_plan_results()
The graph preserves all coordinates learned before budget was hit
DER_EMERGENCY_STOP cycle check SHALL remain as a secondary guard
Requirement 36: Slash Command Stripping
WHEN a slash command is detected, THE SYSTEM SHALL strip it from the task text before passing to the planner: /spec build a login system becomes build a login system
Stripping SHALL be done by ModeDetector.strip_command(task) method
The stripped task SHALL be used for all downstream processing
Part 3: Tasks
Phase 7 — Mode System Foundation
Goal: new files exist and import cleanly. Zero behavior change.
Task 7.1 — Create mode_detector.py
File: IRISVOICE/backend/agent/mode_detector.py

Build: AgentMode, ComplexityLevel, ModeResult, ModeDetector from design above.

Verify:

python
from IRISVOICE.backend.agent.mode_detector import ModeDetector, AgentMode

d = ModeDetector()

# Slash command detection
r = d.detect("/spec build a login system")
assert r.mode == AgentMode.SPEC
assert r.trigger == "slash_command"
assert r.confidence == 1.0

# Inference
r = d.detect("fix the broken authentication")
assert r.mode == AgentMode.DEBUG

# /ask triggers clarification
r = d.detect("/ask I need help")
assert r.needs_clarification == True

# Fallback never raises
r = d.detect("")
assert r.mode == AgentMode.IMPLEMENT

# Slash stripping
from IRISVOICE.backend.agent.mode_detector import ModeDetector
d = ModeDetector()
assert d.strip_command("/spec build login") == "build login"
assert d.strip_command("build login") == "build login"
Reqs: 28, 29, 36

Task 7.2 — Create ask_user_tool.py
File: IRISVOICE/backend/agent/ask_user_tool.py

Build: AskQuestion, AskPayload, AskUserTool from design above.

Verify:

python
from unittest.mock import MagicMock
from IRISVOICE.backend.agent.ask_user_tool import AskUserTool

# build_questions returns None when model returns empty list
adapter = MagicMock()
adapter.infer.return_value = MagicMock(
    raw_text='{"context":"ok","questions":[]}'
)
tool = AskUserTool(adapter=adapter, memory_interface=MagicMock())
result = tool.build_questions("build login", "implement", None, False)
assert result is None

# build_questions returns None on exception
adapter.infer.side_effect = Exception("down")
result = tool.build_questions("build login", "implement", None, False)
assert result is None

# ingest_answers never raises with None mycelium
mi = MagicMock()
mi.mycelium_ingest_statement.side_effect = Exception("fail")
tool = AskUserTool(adapter=MagicMock(), memory_interface=mi)
from IRISVOICE.backend.agent.ask_user_tool import AskQuestion
tool.ingest_answers(
    answers={"q1": "Python"},
    questions=[AskQuestion(id="q1", text="Language?",
                           type="single_select", options=["Python"])],
    session_id="s1"
)  # must not raise
Reqs: 30

Task 7.3 — Create spec_engine.py
File: IRISVOICE/backend/agent/spec_engine.py

Build: SpecOutput, SpecEngine from design above.

Verify:

python
from unittest.mock import MagicMock
from IRISVOICE.backend.agent.spec_engine import SpecEngine, SpecOutput

adapter = MagicMock()
adapter.infer.return_value = MagicMock(raw_text="# Feature Spec\n## What it does\ntest")
engine = SpecEngine(adapter=adapter, memory_interface=MagicMock())

# Simple output
result = engine.produce(
    task="add a logout button",
    is_complex=False,
    context_package=None,
    is_mature=False,
    session_id="s1"
)
assert result.single_doc is not None
assert result.design_doc is None

# Complex output
result = engine.produce(
    task="redesign the authentication system from scratch",
    is_complex=True,
    context_package=None,
    is_mature=False,
    session_id="s1"
)
assert result.design_doc is not None
assert result.requirements_doc is not None
assert result.tasks_doc is not None

# Never raises with broken adapter
adapter.infer.side_effect = Exception("down")
result = engine.produce("any task", True, None, False, "s1")
assert isinstance(result, SpecOutput)
Reqs: 31

Phase 7 Final Check
bash
pytest IRISVOICE/backend/ -v --tb=short
Zero failures. All three new files import without error.

Phase 8 — AgentKernel Integration
Goal: Mode detection, Ask tool, SpecEngine wired into handle().
Task 8.1 — Add new instances to AgentKernel.init()
Add imports:

python
from backend.agent.mode_detector import ModeDetector
from backend.agent.ask_user_tool import AskUserTool
from backend.agent.spec_engine   import SpecEngine
Add to init() body:

python
self._mode_detector = ModeDetector()
self._ask_user_tool = AskUserTool(
    adapter=self.adapter,
    memory_interface=self.memory
)
self._spec_engine = SpecEngine(
    adapter=self.adapter,
    memory_interface=self.memory
)
Reqs: 30, 31

Task 8.2 — Add mode detection to handle()
Position: After audit.log("TASK_RECEIVED") and before self._task_classifier.classify().

Add:

python
# Strip slash command before classification
clean_input = self._mode_detector.strip_command(raw_input)

# Detect mode
mode_result = self._mode_detector.detect(
    task=clean_input,
    context_package=None,    # context not assembled yet — use raw detection
    is_mature=False          # don't suppress ask before we have context
)
Note: Mode detection runs on raw input before context assembly. The graph context is used to SUPPRESS clarification questions (if graph already knows the answer) — not to detect the mode. Keep it simple.

Reqs: 32

Task 8.3 — Handle clarification questions in handle()
Position: After context assembly (Step 2), when mode_result.needs_clarification.

Add:

python
# Re-run mode suppression check now that we have context
if mode_result.needs_clarification and is_mature:
    still_needs = self._mode_detector._graph_has_answer(
        mode_result.mode,
        mode_result.complexity,
        context_package
    )
    if not still_needs:
        mode_result = ModeResult(
            mode=mode_result.mode,
            complexity=mode_result.complexity,
            needs_clarification=False,
            trigger=mode_result.trigger,
            confidence=mode_result.confidence
        )

# Surface questions if still needed
ask_payload = None
if mode_result.needs_clarification:
    ask_payload = self._ask_user_tool.build_questions(
        task=clean_input,
        mode=mode_result.mode.value,
        context_package=context_package,
        is_mature=is_mature
    )
    if ask_payload:
        # Return questions to user — execution pauses here
        return {
            "type": "clarification",
            "ask_payload": {
                "context": ask_payload.context,
                "questions": [
                    {
                        "id": q.id, "text": q.text,
                        "type": q.type, "options": q.options,
                        "required": q.required
                    }
                    for q in ask_payload.questions
                ]
            },
            "session_id": session_id,
            "pending_mode": mode_result.mode.value
        }
When answers come back (as a separate handle() call with the answers):

python
# Detect that this is an answer response
if isinstance(raw_input, dict) and raw_input.get("type") == "ask_response":
    answers  = raw_input.get("answers", {})
    questions = raw_input.get("questions", [])
    # Rebuild AskQuestion objects from the payload
    from backend.agent.ask_user_tool import AskQuestion as AQ
    aq_list = [AQ(**q) for q in questions]
    self._ask_user_tool.ingest_answers(
        answers=answers,
        questions=aq_list,
        session_id=session_id
    )
    # Re-assemble context with enriched graph and continue
    context_package, is_mature = self.memory.get_task_context_package(
        task=raw_input.get("original_task", ""),
        session_id=session_id,
        space_subset=space_subset
    )
    clean_input = raw_input.get("original_task", "")
Reqs: 32, 33

Task 8.4 — Route SPEC mode to SpecEngine
Position: In handle(), replace the execution routing block.

Current:

python
if plan.strategy == "spawn_children":
    result = self._coordinate_workers(msg, plan)
elif plan.strategy == "delegate_external":
    result = self._delegate_external(msg, plan)
else:
    result = self._execute_plan_der(...)
Replace with:

python
from backend.agent.mode_detector import AgentMode, ComplexityLevel

if mode_result.mode == AgentMode.SPEC:
    # SPEC mode — SpecEngine produces docs, no DER loop
    is_complex = (
        mode_result.complexity == ComplexityLevel.COMPLEX
        or (mode_result.complexity == ComplexityLevel.UNKNOWN
            and len(clean_input.split()) > 20)
    )
    spec_output = self._spec_engine.produce(
        task=clean_input,
        is_complex=is_complex,
        context_package=context_package,
        is_mature=is_mature,
        session_id=session_id
    )
    result = {
        "type": "spec",
        "title": spec_output.title,
        "is_complex": spec_output.is_complex,
        "single_doc": spec_output.single_doc,
        "design_doc": spec_output.design_doc,
        "requirements_doc": spec_output.requirements_doc,
        "tasks_doc": spec_output.tasks_doc,
    }

elif plan.strategy == "spawn_children":
    result = self._coordinate_workers(msg, plan)
elif plan.strategy == "delegate_external":
    result = self._delegate_external(msg, plan)
else:
    result = self._execute_plan_der(
        msg=msg, plan=plan,
        context_package=context_package,
        is_mature=is_mature,
        task_class=task_class,
        session_id=session_id,
        agent_mode=mode_result.mode.value
    )
Reqs: 33

Task 8.5 — Update DER token budget
In agent_kernel.py, replace:

python
DER_MAX_CYCLES        = 40
With:

python
DER_TOKEN_BUDGETS = {
    "spec":       60_000,
    "research":   80_000,
    "implement":  40_000,
    "debug":      30_000,
    "test":       40_000,
    "review":     20_000,
    "default":    40_000,
}
DER_EMERGENCY_STOP    = 200
DER_MAX_VETO_PER_ITEM = 2
In _execute_plan_der() signature, add agent_mode: str = "implement"

In the while loop condition, replace cycle check with:

python
current_budget = DER_TOKEN_BUDGETS.get(agent_mode, DER_TOKEN_BUDGETS["default"])
tokens_used    = sum(s.tokens_used for s in plan.steps)

while (
    not queue.is_complete()
    and queue.cycle_count < DER_EMERGENCY_STOP
    and tokens_used < current_budget
):
    queue.cycle_count += 1
    tokens_used = sum(s.tokens_used for s in plan.steps)
    ...
Reqs: 35

Task 8.6 — Mode-aware graph reads in _plan_task()
Add agent_mode: str = "implement" parameter to _plan_task() with safe default.

After context section extraction, add:

python
# Mode-aware graph read strategy
if agent_mode == "debug" and gradient_warnings_block:
    # Danger map first — pre-diagnosis before any plan
    tier1_directives = gradient_warnings_block + "\n\n" + tier1_directives
elif agent_mode == "research" and ambient_block:
    # Ambient signals first — exploration over known landmarks
    tier1_directives = ambient_block + "\n\n" + tier1_directives
elif agent_mode == "test":
    # Contracts + causal context first — test behavioral invariants
    contracts_causal = contracts_block + "\n" + causal_block
    tier1_directives = contracts_causal + "\n\n" + tier1_directives
elif agent_mode == "review":
    # Gradient warnings + failure corrections first — review against known mistakes
    tier1_directives = gradient_warnings_block + "\n" + failures_block + "\n\n" + tier1_directives
# implement and spec use standard order — no change
Where gradient_warnings_block, ambient_block, contracts_block, causal_block, failures_block are extracted from context_package when mature, empty string when not.

Reqs: 34

Phase 8 Final Check
bash
pytest IRISVOICE/backend/ -v --tb=short
Zero failures. Manually verify:

/spec add a logout button → returns {"type": "spec", "single_doc": "..."} (simple)
/spec redesign the auth system from scratch → returns {"type": "spec", "design_doc": "...", ...} (complex)
/debug fix the login error → plan has gradient_warnings in tier1 before other context
/ask what should I build → returns {"type": "clarification", "ask_payload": {...}}
Regular task "build a login form" → routes to DER loop as IMPLEMENT
Token budget check: task in debug mode uses budget 30000 not 40000
Final Verification Checklist (additions to existing checklist)
Mode System
 mode_detector.py exists with AgentMode, ModeDetector, ModeResult
 All 7 slash commands detected correctly
 /ask sets needs_clarification=True
 Slash command stripped from task before passing to planner
 Mode inference never raises — falls back to IMPLEMENT
 ask_user_tool.py exists with AskUserTool
 build_questions() caps at 3 questions
 build_questions() returns None on empty or exception
 ingest_answers() ingests every answer as coordinate signal
 ingest_answers() never raises
 spec_engine.py exists with SpecEngine
 Simple task → single_doc populated, design_doc None
 Complex task → all three docs populated
 Depth calibrated to topology_primitive
 produce() never raises
handle() Mode Wiring
 ModeDetector instantiated in __init__()
 AskUserTool instantiated in __init__()
 SpecEngine instantiated in __init__()
 Mode detection runs before classification on clean_input
 Clarification suppressed when graph has answer
 SPEC mode routes to SpecEngine, not DER loop
 All other modes route to DER loop with agent_mode passed
 Agent mode passed through to _plan_task() and _execute_plan_der()
Token Budget
 DER_MAX_CYCLES = 40 removed
 DER_TOKEN_BUDGETS dict defined with all 6 modes + default
 DER_EMERGENCY_STOP = 200 defined (cycle count backup only)
 DER loop checks token budget each cycle
 DER loop still checks DER_EMERGENCY_STOP as backup
 Graph preserves all coordinates learned before budget hit
Director Mode System Mode Detection · Ask User Tool · Spec Engine · DER Token Budget Additive to agent_loop_design.md + agent_loop_requirements.md + agent_loop_tasks.md March 2026 · IRISVOICE / IRIS / Torus Network · Confidential

