"""
Skills Loader

Scans the skills/ directory for subdirectories containing SKILL.md files
and loads their content into memory so the PersonalityManager can inject
them into the IRIS agent's system prompt.
"""

import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent


def load_all_skills() -> Dict[str, str]:
    """
    Scan the skills directory for subdirectories that contain a SKILL.md file.

    Returns:
        dict mapping skill_name (directory name) → full SKILL.md text content.
        Returns an empty dict if no skills are found or if errors occur.
    """
    skills: Dict[str, str] = {}

    try:
        if not _SKILLS_DIR.is_dir():
            logger.warning(f"[SkillsLoader] Skills directory not found: {_SKILLS_DIR}")
            return skills

        for child in sorted(_SKILLS_DIR.iterdir()):
            if not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                content = skill_md.read_text(encoding="utf-8")
                skills[child.name] = content
                logger.debug(f"[SkillsLoader] Loaded skill: {child.name}")
            except Exception as read_err:
                logger.warning(f"[SkillsLoader] Could not read {skill_md}: {read_err}")

    except Exception as e:
        logger.error(f"[SkillsLoader] Failed to scan skills directory: {e}")

    logger.info(f"[SkillsLoader] Loaded {len(skills)} skill(s): {list(skills.keys())}")
    return skills


def extract_description(skill_content: str) -> str:
    """
    Pull the 'description:' value from YAML frontmatter.
    Falls back to the first non-empty, non-YAML line.

    Args:
        skill_content: Full text of a SKILL.md file.

    Returns:
        A single-line description string.
    """
    in_frontmatter = False
    for line in skill_content.splitlines():
        stripped = line.strip()
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter and stripped.startswith("description:"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'")

    # Fallback: first non-empty, non-YAML-marker line outside frontmatter
    for line in skill_content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and stripped != "---":
            return stripped[:120]

    return "(no description)"
