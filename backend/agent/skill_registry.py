#!/usr/bin/env python3
"""
Skill Registry

This module provides a registry for managing and accessing available skills,
integrating with the ToolExecutor for actual tool execution.
"""

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)
from .tool_executor import ToolExecutor, get_tool_executor


class SkillRegistry:
    """A registry for skills that the agent can use."""

    def __init__(self):
        self.skills: Dict[str, Callable[..., Any]] = {}
        self._tool_executor: Optional[ToolExecutor] = None
        self._register_default_skills()

    def _get_tool_executor(self) -> ToolExecutor:
        """Lazy-load the tool executor."""
        if self._tool_executor is None:
            self._tool_executor = get_tool_executor()
        return self._tool_executor

    def _register_default_skills(self):
        """Registers the default skills available to the agent."""
        # Register tool-based skills that delegate to the ToolExecutor
        self.register_skill("execute_tool", self._execute_tool_skill)
        self.register_skill("list_tools", self._list_tools_skill)
        self.register_skill("get_tool_info", self._get_tool_info_skill)

    def register_skill(self, name: str, skill: Callable[..., Any]):
        """Registers a new skill."""
        self.skills[name] = skill
        logger.info(f"[SkillRegistry] Registered skill: {name}")

    def get_skill(self, name: str) -> Optional[Callable[..., Any]]:
        """Retrieves a skill by name."""
        return self.skills.get(name)

    def list_registered_skills(self) -> list[str]:
        """List all registered skill names."""
        return list(self.skills.keys())

    async def _execute_tool_skill(self, tool_name: str, **kwargs) -> Any:
        """Skill for executing tools via ToolExecutor."""
        executor = self._get_tool_executor()
        result = await executor.execute(tool_name, kwargs)
        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "execution_time": result.execution_time
        }

    def _list_tools_skill(self, **kwargs) -> Any:
        """Skill for listing available tools."""
        executor = self._get_tool_executor()
        return {"tools": executor.list_tools()}

    def _get_tool_info_skill(self, tool_name: str = "", **kwargs) -> Any:
        """Skill for getting information about a specific tool."""
        executor = self._get_tool_executor()
        tool = executor.get_tool(tool_name)
        if tool:
            return {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category.value,
                "parameters": tool.parameters,
                "required_params": tool.required_params
            }
        return {"error": f"Tool '{tool_name}' not found"}

    # Legacy methods for backward compatibility
    def file_system_skill(self, operation: str, **kwargs) -> Any:
        """A skill for interacting with the file system."""
        # Use the tool executor for actual file operations
        tool_mapping = {
            "read": "read_file",
            "write": "write_file",
            "list": "list_directory",
            "create": "create_directory",
            "delete": "delete_file"
        }
        
        tool_name = tool_mapping.get(operation)
        if not tool_name:
            return {"error": f"Unsupported file system operation: {operation}"}

        # Map parameters
        params = {}
        if operation == "read":
            params = {"path": kwargs.get("path", "")}
        elif operation == "write":
            params = {"path": kwargs.get("path", ""), "content": kwargs.get("content", "")}
        elif operation in ("list", "create", "delete"):
            params = {"path": kwargs.get("path", "")}

        # Execute synchronously for backward compatibility
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If already in async context, create a task
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self._execute_tool_skill(tool_name, **params))
                    return future.result()
            else:
                return asyncio.run(self._execute_tool_skill(tool_name, **params))
        except Exception as e:
            return {"error": str(e)}
