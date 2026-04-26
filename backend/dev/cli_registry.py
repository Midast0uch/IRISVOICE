"""
CLI Registry — loads cli_tools.yaml and exposes tool lookup / selection.

Quality-check gates applied:
  - YAML loaded once at import time, stored in module-level singleton.
  - No subprocess spawning here — that is SubprocessManager's responsibility.
  - No shared mutable state across sessions.
  - Every public method returns a typed dataclass or None — no raw dicts.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_YAML_PATH = Path(__file__).parent / "cli_tools.yaml"


@dataclass(frozen=True)
class CLITool:
    """Immutable descriptor for a registered CLI tool."""
    name: str
    display_name: str
    command: str
    args_template: list[str]
    when_to_use: str
    workdir_required: bool
    stream_output: bool
    timeout_seconds: int
    tags: list[str]

    def build_args(self, query: str) -> list[str]:
        """Replace {query} placeholder in args_template with the actual query."""
        return [a.replace("{query}", query) for a in self.args_template]

    def is_available(self) -> bool:
        """Return True if the command exists on PATH or is an absolute path."""
        import shutil
        return bool(shutil.which(self.command))


class CLIRegistry:
    """
    Loads cli_tools.yaml once and exposes tool lookup.
    Thread-safe for concurrent reads; no writes after init.
    """

    def __init__(self, yaml_path: Path = _YAML_PATH) -> None:
        self._tools: dict[str, CLITool] = {}
        self._load(yaml_path)

    def _load(self, path: Path) -> None:
        if not path.exists():
            logger.warning("[CLIRegistry] cli_tools.yaml not found at %s", path)
            return
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            for entry in data.get("tools", []):
                tool = CLITool(
                    name=entry["name"],
                    display_name=entry.get("display_name", entry["name"]),
                    command=entry["command"],
                    args_template=entry.get("args_template", ["{query}"]),
                    when_to_use=entry.get("when_to_use", ""),
                    workdir_required=entry.get("workdir_required", False),
                    stream_output=entry.get("stream_output", True),
                    timeout_seconds=int(entry.get("timeout_seconds", 300)),
                    tags=entry.get("tags", []),
                )
                self._tools[tool.name] = tool
            logger.info("[CLIRegistry] Loaded %d tools from %s", len(self._tools), path)
        except Exception as exc:
            logger.error("[CLIRegistry] Failed to load yaml: %s", exc)

    # ── Public API ──────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[CLITool]:
        """Return a tool by name, or None if unknown."""
        return self._tools.get(name)

    def all_tools(self) -> list[CLITool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def available_tools(self) -> list[CLITool]:
        """Return only tools whose command exists on PATH."""
        return [t for t in self._tools.values() if t.is_available()]

    def build_selection_context(self) -> str:
        """
        Return a formatted string describing all tools for the orchestrator's
        LLM prompt. Each tool's when_to_use description is included verbatim.
        """
        lines = ["Available CLI tools (pick exactly one name):"]
        for tool in self.available_tools():
            lines.append(f"\n  name: {tool.name}")
            lines.append(f"  description: {tool.when_to_use.strip()}")
        if not self.available_tools():
            lines.append("\n  (no tools currently available on PATH)")
        return "\n".join(lines)

    def select_tool_for_query(self, tool_name: str) -> Optional[CLITool]:
        """
        Return the tool matching tool_name if it is available, else fall back
        to the first available tool, else None.
        Used after the LLM has chosen a tool name.
        """
        tool = self._tools.get(tool_name)
        if tool and tool.is_available():
            return tool
        # Fallback: first available tool
        available = self.available_tools()
        if available:
            logger.warning(
                "[CLIRegistry] Requested tool '%s' unavailable; falling back to '%s'",
                tool_name, available[0].name
            )
            return available[0]
        logger.error("[CLIRegistry] No CLI tools available on PATH")
        return None


# ── Module-level singleton ──────────────────────────────────────────────────

_registry: Optional[CLIRegistry] = None


def get_cli_registry() -> CLIRegistry:
    """Return the module-level CLIRegistry singleton (lazy-init)."""
    global _registry
    if _registry is None:
        _registry = CLIRegistry()
    return _registry
