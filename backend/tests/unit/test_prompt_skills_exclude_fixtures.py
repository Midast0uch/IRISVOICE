"""Execution audit B17 (2026-09-29): `_`-prefixed test-fixture skills stay out
of the live system prompt, while load_all_skills() still lists them."""

import shutil
from pathlib import Path

from backend.agent.skills import skills_loader as sl


def test_underscore_skill_is_loaded_but_not_prompted():
    d = Path(sl.__file__).parent / "_test_prompt_filter_skill"
    try:
        d.mkdir(exist_ok=True)
        (d / "SKILL.md").write_text("---\nname: x\ndescription: fixture\n---\n", encoding="utf-8")
        assert "_test_prompt_filter_skill" in sl.load_all_skills()
        prompted = sl.prompt_skills()
        assert "_test_prompt_filter_skill" not in prompted
        assert "skill-creator" in prompted
    finally:
        shutil.rmtree(d, ignore_errors=True)
