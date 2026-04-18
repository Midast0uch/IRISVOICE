"""
Spec Engine — Director Mode System
File: IRISVOICE/backend/agent/spec_engine.py

Produces spec documents when the Director is in SPEC mode.
Simple tasks  → single lightweight doc
Complex tasks → full three-doc set (design + requirements + tasks)

Source: specs/director_mode_system.md
Gate 1 Step 1.4
"""

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
    - CORE        → lean (expert audience, minimal scaffolding)
    - ACQUISITION → detailed (reasoning, alternatives)
    - EXPLORATION → bridged (theory-to-practice connections)
    - ORBIT       → detailed (extra clarity — user is circling a gap)
    - EVOLUTION   → lean (user has grown past this area)
    - Everything else → standard

    Never raises. Returns SpecOutput with None fields on failure.
    """

    DEPTH_BY_TOPOLOGY = {
        "core":        "lean",
        "acquisition": "detailed",
        "exploration": "bridged",
        "transfer":    "standard",
        "orbit":       "detailed",
        "evolution":   "lean",
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
        session_id: str,
    ) -> SpecOutput:
        """
        Produces spec output appropriate to task complexity.
        Never raises. Returns SpecOutput with None fields on failure.
        """
        try:
            topology = "unknown"
            depth    = "standard"

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
                    context_package=context_package, is_mature=is_mature,
                )
            else:
                return self._produce_simple(
                    task=task, title=title, depth=depth,
                    context_package=context_package, is_mature=is_mature,
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
            f"# Feature: {title}\n"
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
            single_doc=response.raw_text,
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

        design_doc       = self._produce_design(base_prompt, title)
        requirements_doc = self._produce_requirements(base_prompt, title)
        tasks_doc        = self._produce_tasks(base_prompt, title)

        return SpecOutput(
            title=title,
            is_complex=True,
            design_doc=design_doc,
            requirements_doc=requirements_doc,
            tasks_doc=tasks_doc,
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
