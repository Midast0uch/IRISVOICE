"""
Ask User Tool — Director Mode System
File: IRISVOICE/backend/agent/ask_user_tool.py

Structured question tool for the Director.
Questions are built by the Director, presented all at once,
answered together by the user. One round trip per session maximum.
Every answer is ingested into Mycelium as a coordinate signal.

Source: specs/director_mode_system.md
Gate 1 Step 1.3
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json
import re


@dataclass
class AskQuestion:
    id: str
    text: str
    type: str                      # "single_select" | "multi_select" | "free_text"
    options: List[str]             = field(default_factory=list)
    required: bool                 = True


@dataclass
class AskPayload:
    questions: List[AskQuestion]
    context: str                   # one sentence explaining why these are needed


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
        is_mature: bool,
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
                is_mature=is_mature,
            )

            response = self.adapter.infer(
                prompt,
                role="REASONING",
                max_tokens=600,
                temperature=0.1,
            )

            return self._parse_questions(response.raw_text, task, mode)

        except Exception:
            return None

    def ingest_answers(
        self,
        answers: Dict[str, str],
        questions: List[AskQuestion],
        session_id: str,
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

                # Build natural language statement from Q+A pair
                statement = f"{question.text}: {answer}"

                try:
                    self.memory.mycelium_ingest_statement(
                        statement=statement,
                        session_id=session_id,
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
        is_mature: bool,
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
    ) -> Optional[AskPayload]:
        """Parse model response into AskPayload. Returns None on empty or failure."""
        try:
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
                    id=q.get("id", f"q{len(questions) + 1}"),
                    text=q.get("text", ""),
                    type=q.get("type", "single_select"),
                    options=q.get("options", []),
                    required=q.get("required", True),
                ))

            return AskPayload(
                questions=questions,
                context=data.get("context", ""),
            )

        except Exception:
            return None
