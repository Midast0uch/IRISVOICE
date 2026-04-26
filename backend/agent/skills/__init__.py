# Skills Package
"""
Skills package — provides SkillsLoader and get_skills_loader() for the agent.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SkillsLoader:
    """
    Stateful wrapper around skills_loader module functions.
    Provides reload() and list_skills() for runtime use (e.g. iris_gateway).
    """

    def __init__(self) -> None:
        self._skills: Dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        """Re-scan the skills/ directory and update the in-memory cache."""
        try:
            from .skills_loader import load_all_skills
            self._skills = load_all_skills()
        except Exception as e:
            logger.warning(f"[SkillsLoader] reload() failed: {e}")
            self._skills = {}

    def list_skills(self) -> List[str]:
        """Return list of currently loaded skill names."""
        return list(self._skills.keys())

    def get_skill_content(self, name: str) -> Optional[str]:
        """Return SKILL.md content for a named skill, or None if not found."""
        return self._skills.get(name)

    def get_prompt_context(self) -> str:
        """Return formatted skills context string for planner prompts."""
        try:
            from .skills_loader import get_skill_prompt_context
            return get_skill_prompt_context()
        except Exception as e:
            logger.warning(f"[SkillsLoader] get_prompt_context failed: {e}")
            return ""


_loader_instance: Optional[SkillsLoader] = None


def get_skills_loader() -> SkillsLoader:
    """Return the singleton SkillsLoader instance (lazy-init)."""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = SkillsLoader()
    return _loader_instance
