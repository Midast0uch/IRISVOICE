"""
Discipline ladder injection (Gate 3 T7, REQ-9).

A compact static ruleset (<600 tokens) injected into the developer-mode
system prompt at assembly (design Key Decision 5). Intensity levels:
  lite  — MINIMALITY ladder only
  full  — MINIMALITY + DEPTH ladders (default)
  ultra — both ladders + explicit scope-bound emphasis
  off   — inject nothing (REQ-9 AC5)

The active task's SCOPE BOUND (D8) — its DONE = / NOT THIS = lines — is
injected verbatim when a task is active (REQ-9 AC6), read from
data/active_task.json {"done": "...", "not_this": "..."}.

DER workers inherit automatically: they assemble prompts through the same
_build_system_prompt() this feeds (single injection point).

Quality gates: config read is two tiny JSON files, cached with mtime guard;
failure degrades to no-injection, never raises into prompt assembly.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_CONFIG_PATH = os.path.join(_REPO_ROOT, "data", "iris_config.json")
_ACTIVE_TASK_PATH = os.path.join(_REPO_ROOT, "data", "active_task.json")

_VALID_INTENSITIES = ("lite", "full", "ultra", "off")

_LADDERS: dict[str, str] = {
    "minimality": (
        "MINIMALITY LADDER — how small (stop at the first rung that works):\n"
        "1. Does this need to exist at all?\n"
        "2. Is it already in the codebase? (search before writing)\n"
        "3. Standard library?\n"
        "4. Platform-native?\n"
        "5. An installed dependency?\n"
        "6. Can it be one line?\n"
        "7. The minimum that actually works."
    ),
    "depth": (
        "DEPTH LADDER — how sure (all rungs, always):\n"
        "a. Read the code the change touches before writing.\n"
        "b. Trace the real flow, not the assumed one.\n"
        "c. Enumerate edge cases and say which are handled.\n"
        "d. Verify with the project's own tests.\n"
        "e. Optimize only measured hot paths.\n"
        "Rungs run AFTER understanding, never instead of it. Understanding, "
        "verification, error handling, security, accessibility are never minimized."
    ),
}

_ULTRA_EXTRA = (
    "SCOPE DISCIPLINE: producing anything beyond the task's stated bound is "
    "FAILURE even if the code works. When unsure whether something is in scope, it is not."
)

_cache: dict = {"mtime_cfg": None, "intensity": None, "mtime_task": None, "task": None}


def get_intensity() -> str:
    """Ladder intensity from data/iris_config.json ('ladder_intensity'), default 'full'."""
    try:
        mtime = os.path.getmtime(_CONFIG_PATH)
    except OSError:
        return "full"
    if _cache["mtime_cfg"] == mtime and _cache["intensity"] is not None:
        return _cache["intensity"]
    intensity = "full"
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8-sig") as fh:
            cfg = json.load(fh)
        raw = str(cfg.get("ladder_intensity", "full")).strip().lower()
        if raw in _VALID_INTENSITIES:
            intensity = raw
    except Exception as exc:
        logger.debug("[ladder] could not read intensity: %s", exc)
    _cache["mtime_cfg"] = mtime
    _cache["intensity"] = intensity
    return intensity


def get_scope_bound() -> str:
    """The active task's DONE=/NOT THIS= lines verbatim, or '' when none."""
    try:
        mtime = os.path.getmtime(_ACTIVE_TASK_PATH)
    except OSError:
        return ""
    if _cache["mtime_task"] == mtime and _cache["task"] is not None:
        return _cache["task"]
    block = ""
    try:
        with open(_ACTIVE_TASK_PATH, "r", encoding="utf-8-sig") as fh:
            task = json.load(fh)
        done = str(task.get("done", "")).strip()
        not_this = str(task.get("not_this", "")).strip()
        if done or not_this:
            parts = ["ACTIVE TASK SCOPE BOUND:"]
            if done:
                parts.append(f"DONE = {done}")
            if not_this:
                parts.append(f"NOT THIS = {not_this}")
            block = "\n".join(parts)
    except Exception as exc:
        logger.debug("[ladder] could not read active task: %s", exc)
    _cache["mtime_task"] = mtime
    _cache["task"] = block
    return block


def get_ladder_block() -> str:
    """The ruleset (+ scope bound) for the current intensity; '' when off."""
    intensity = get_intensity()
    if intensity == "off":
        return ""
    sections: list[str] = ["--- DISCIPLINE RULESET ({}) ---".format(intensity)]
    if intensity in ("lite", "full", "ultra"):
        sections.append(_LADDERS["minimality"])
    if intensity in ("full", "ultra"):
        sections.append(_LADDERS["depth"])
    if intensity == "ultra":
        sections.append(_ULTRA_EXTRA)
    scope = get_scope_bound()
    if scope:
        sections.append(scope)
    return "\n\n".join(sections)


def clear_cache() -> None:
    _cache.update({"mtime_cfg": None, "intensity": None,
                   "mtime_task": None, "task": None})
