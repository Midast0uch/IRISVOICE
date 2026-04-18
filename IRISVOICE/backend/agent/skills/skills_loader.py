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
    Respects the disabled_skills list in config.yaml.

    Returns:
        dict mapping skill_name (directory name) → full SKILL.md text content.
    """
    skills: Dict[str, str] = {}
    
    # Load disabled skills list
    disabled_skills = set()
    try:
        config_path = _SKILLS_DIR / "config.yaml"
        if config_path.exists():
            import yaml
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            disabled_skills = set(data.get("disabled_skills", []))
            if disabled_skills:
                logger.info(f"[SkillsLoader] Skipping {len(disabled_skills)} disabled skill(s): {list(disabled_skills)}")
    except Exception as e:
        logger.warning(f"[SkillsLoader] Could not read config.yaml: {e}")

    try:
        if not _SKILLS_DIR.is_dir():
            logger.warning(f"[SkillsLoader] Skills directory not found: {_SKILLS_DIR}")
            return skills

        for child in sorted(_SKILLS_DIR.iterdir()):
            if not child.is_dir():
                continue
            
            # Skip if explicitly disabled
            if child.name in disabled_skills:
                logger.debug(f"[SkillsLoader] Skipping disabled skill: {child.name}")
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

    logger.info(f"[SkillsLoader] Loaded {len(skills)} skill(s) into context: {list(skills.keys())}")
    return skills


def extract_description(skill_content: str) -> str:
    """
    Pull the 'description:' value from YAML frontmatter.
    Falls back to the first non-empty, non-header line after the frontmatter closes.

    Args:
        skill_content: Full text of a SKILL.md file.

    Returns:
        A single-line description string (max ~120 chars, word-boundary truncated).
    """
    in_frontmatter = False
    frontmatter_seen = False

    for line in skill_content.splitlines():
        stripped = line.strip()
        if stripped == "---":
            if not frontmatter_seen:
                # Opening delimiter
                in_frontmatter = True
                frontmatter_seen = True
            else:
                # Closing delimiter
                in_frontmatter = False
            continue
        if in_frontmatter and stripped.startswith("description:"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'")

    # Fallback: first non-empty, non-header line AFTER the frontmatter closes.
    # Re-scan with proper frontmatter tracking so YAML fields are skipped.
    in_frontmatter = False
    frontmatter_seen = False
    frontmatter_closed = False

    for line in skill_content.splitlines():
        stripped = line.strip()
        if stripped == "---":
            if not frontmatter_seen:
                in_frontmatter = True
                frontmatter_seen = True
            elif in_frontmatter:
                in_frontmatter = False
                frontmatter_closed = True
            continue
        if in_frontmatter:
            continue  # Skip all YAML content inside frontmatter
        if stripped and not stripped.startswith("#"):
            # Word-boundary truncation with ellipsis
            if len(stripped) <= 120:
                return stripped
            truncated = stripped[:120]
            last_space = truncated.rfind(" ")
            return (truncated[:last_space] if last_space > 80 else truncated) + "…"

    return "(no description)"


def get_skill_prompt_context() -> str:
    """
    Return a formatted string of all loaded skills suitable for inclusion
    in a planner prompt (the 'available skills' context the planner receives).

    Returns:
        Multi-line string listing skill names and descriptions, or empty string
        if no skills are loaded.
    """
    try:
        skills = load_all_skills()
        if not skills:
            return ""
        lines = ["## Available Skills"]
        for skill_name, content in skills.items():
            description = extract_description(content)
            lines.append(f"- {skill_name}: {description}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"[SkillsLoader] get_skill_prompt_context failed: {e}")
        return ""
