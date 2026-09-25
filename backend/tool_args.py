"""Argument-name resolvers shared by every file-tool implementation.

Why this exists (live evidence, 2026-09-25). The tool schema declares ``path``
and ``content``; the model sent ``file_path`` and ``contents``. Each
implementation read ONE name with a ``""`` default, so:

  * ``write_file`` created an EMPTY file and answered success — the audit log
    holds ``"arguments": {"path": "ww_a.md", "contents": "- Tea"}`` next to
    ``"result": "{'success': True, ..., 'bytes': 0}"``. The user was told the
    file was written, and the agent then read nothing back;
  * ``write_file`` crashed with ``[Errno 2] No such file or directory: ''`` when
    the path arrived as ``file_path``.

Two implementations serve these tools — ``backend/agent/tool_executor.py`` and
the MCP ``file_manager`` server in ``backend/mcp/builtin_servers.py`` (which is
the one the agent actually reaches: ``tool_bridge`` maps
``"write_file": ("file_manager", "write_file")``). They resolve their arguments
here, so the acceptance list cannot drift apart again.

Dependency-free on purpose: both packages import it.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Every spelling the model has been seen to use, most canonical first.
PATH_KEYS = (
    "path", "file_path", "filepath", "filename", "file", "target_path",
    "directory", "dir",
)
BODY_KEYS = (
    "content", "contents", "text", "body", "file_content", "file_contents", "data",
)


def _usable(value: Any) -> Optional[str]:
    """A usable string argument, else None. Lists/dicts are not accepted."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def path_arg(params: Dict[str, Any]) -> str:
    """The file/directory path under any spelling, or "" when absent."""
    for key in PATH_KEYS:
        value = _usable((params or {}).get(key))
        if value and value.strip():
            return value.strip()
    return ""


def body_arg(params: Dict[str, Any]) -> Optional[str]:
    """The body for a write, or None when no body key was supplied at all.

    ``None`` is deliberately different from ``""``: a caller passing
    ``content=""`` means an empty file, while a caller passing NO body key is a
    mistake the tool must report — that mistake wrote empty files in silence.
    """
    for key in BODY_KEYS:
        if key in (params or {}):
            value = _usable((params or {}).get(key))
            if value is not None:
                return value
    return None


def missing_arg_error(tool: str, arg: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """An explicit error that names what arrived, instead of a silent default."""
    keys = ", ".join(sorted(str(k) for k in (params or {}))) or "(none)"
    return {
        "success": False,
        "error": f"{tool} requires '{arg}' — Keys received: {keys}",
    }
