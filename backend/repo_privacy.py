"""Repo privacy guard: learned user data must never be written into the project tree.

Why (2026-10-30). The tool ledger holds six attempts to park real user facts in
the repo:

    backend/agent/skills/user-preferences.md              library card number
    backend/agent/skills/user-preferences/library-card.md library card number
    user_preferences.json                                 status colour
    .user_preferences.json                                status colour

The repo is committed and shared, so a write there publishes the user's data.
Learned memory belongs in the application store (``data/memory_config.json`` ->
``db_path``, today ``D:/IRIS/store/memory.db``), which the ``remember`` tool
writes.

This is a PATH rule, not a content scan. A content scan cannot tell a user fact
from source code, and a false positive would block real work. The rule is
deliberately narrow: the names that mark a file as a learned-user-data store,
plus the top level of the skills directory, which only holds skill folders.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / "backend" / "agent" / "skills"

# A whole path component that IS a learned-user-data store: user-preferences.md,
# user_preferences.json, .user_preferences.json, a user-facts/ directory.
# Deliberately anchored, so docs/user-profile-design.md stays allowed.
_LEARNED_NAME = re.compile(
    r"^\.?user[._-]?(?:preference|fact|memory|profile)s?(?:\.[A-Za-z0-9]+)*$",
    re.IGNORECASE,
)

# Files that legitimately sit directly in backend/agent/skills/. Everything else
# at that level is not a skill: skills_loader only reads <name>/SKILL.md.
_SKILLS_TOP_ALLOWED = {"config.yaml", "custom_skill_template.py", "SKILL.md"}


def _resolved_in_repo(raw_path: str) -> Optional[Path]:
    """Resolve ``raw_path`` and return it only when it lands inside the repo.

    A relative path is resolved TWICE: against the process cwd and against the
    repo root. The live backend runs with cwd ``C:/Users/<user>/Documents/IRIS``
    (measured 2026-10-30 from a failed write's tmp path), so a model that says
    ``backend/agent/skills/x.md`` means the repo but resolves to the app dir.
    Testing both interpretations closes that hole without widening the rule.
    """
    raw = Path(raw_path)
    candidates = [raw] if raw.is_absolute() else [Path.cwd() / raw, _REPO_ROOT / raw]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(_REPO_ROOT)
            return resolved
        except (ValueError, OSError):
            continue
    return None


def learned_user_data_error(raw_path: str) -> Optional[Dict[str, Any]]:
    """Return a refusal dict when ``raw_path`` names learned user data in the repo.

    ``None`` means the write is not this guard's business (outside the repo, or a
    legitimate path). Callers return the dict unchanged as the tool result.
    """
    path = _resolved_in_repo(raw_path)
    if path is None:
        return None
    relative = path.relative_to(_REPO_ROOT)
    reason = None
    if any(_LEARNED_NAME.search(part) for part in relative.parts):
        reason = "the path marks a learned-user-data store"
    elif path.parent == _SKILLS_DIR and path.name not in _SKILLS_TOP_ALLOWED:
        reason = "a file at the top level of backend/agent/skills/ is not a skill"
    if reason is None:
        return None
    return {
        "success": False,
        "path": str(path),
        "denied": "learned_user_data_in_repo",
        "error": (
            f"refused: {reason}. The project tree is committed and shared. "
            "Learned user data belongs in the application store (D:/IRIS/store), "
            "which the `remember` tool writes. Do not write user facts, "
            "preferences or profiles into the repo."
        ),
    }
