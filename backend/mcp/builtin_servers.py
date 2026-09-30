"""
Built-in MCP Servers - Local implementations of common tools
"""
import asyncio
import json
import os
import subprocess
from typing import Any, Dict, List, Optional
from pathlib import Path

from .protocol import MCPRequest, MCPResponse, MCPTool, MCPMessageType


class BuiltinServer:
    """Base class for built-in MCP servers"""

    def __init__(self, name: str):
        self.name = name
        self._tools: List[MCPTool] = []
        self._setup_tools()

    def _setup_tools(self):
        """Override to define tools"""
        pass

    def get_tools(self) -> List[MCPTool]:
        """Get available tools"""
        return self._tools

    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """Handle MCP request"""
        if request.method == MCPMessageType.TOOLS_LIST:
            return MCPResponse(
                id=request.id,
                result={"tools": [t.to_dict() for t in self._tools]}
            )
        elif request.method == MCPMessageType.TOOLS_CALL:
            return await self._handle_tool_call(request)
        else:
            return MCPResponse(
                id=request.id,
                error={"code": -32601,
                       "message": f"Method not found: {request.method}"}
            )

    async def _handle_tool_call(self, request: MCPRequest) -> MCPResponse:
        """Handle tool execution"""
        params = request.params or {}
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        result = await self.execute_tool(tool_name, arguments)

        return MCPResponse(
            id=request.id,
            result=result
        )

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a tool - override in subclasses"""
        return {"error": "Not implemented"}


class BrowserServer(BuiltinServer):
    """Browser control MCP server"""

    def __init__(self):
        super().__init__("browser")

    def _setup_tools(self):
        self._tools = [
            MCPTool(
                name="open_url",
                description="Open a URL in the default browser",
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to open"}
                    },
                    "required": ["url"]
                }
            ),
            MCPTool(
                name="search",
                description="Search using default search engine",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                }
            ),
            MCPTool(
                name="open_incognito",
                description="Open URL in incognito/private mode",
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to open"}
                    },
                    "required": ["url"]
                }
            )
        ]

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "open_url":
            # REQ-16 (T27/T28): agent-initiated navigation is in-app only.
            # AgentToolBridge intercepts "open_url" BEFORE this MCP dispatch
            # table (tool_bridge.py _execute_open_url -> in-app open_tab + headless
            # fetch). This branch is unreachable from the live agent path; it is
            # dead-code-guarded so a direct MCP caller can never hijack the user's
            # OS browser (webbrowser.open is banned for agent-initiated navigation).
            url = arguments.get("url", "")
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            return {
                "success": False,
                "error": (
                    "open_url is handled in-app (REQ-16). AgentToolBridge routes "
                    "it to the in-app browser surface; the OS browser is never "
                    "launched by the agent."
                ),
                "url": url,
            }

        elif name == "search":
            query = arguments.get("query", "")
            # REQ-16 (T28): the tool_bridge search interception (_execute_web_search)
            # is the pattern reference for in-app routing. This raw branch keeps the
            # same in-app-only guard: never webbrowser.open for agent navigation.
            return {
                "success": False,
                "error": (
                    "search is handled in-app (REQ-16). AgentToolBridge routes "
                    "it to the in-app browser surface; the OS browser is never "
                    "launched by the agent."
                ),
                "query": query,
            }

        elif name == "open_incognito":
            url = arguments.get("url", "")
            # Note: incognito opening is browser-specific
            # This is a simplified version
            return {"success": False, "message": "Incognito mode not implemented for this browser"}

        return {"error": f"Unknown tool: {name}"}


class AppLauncherServer(BuiltinServer):
    """Application launcher MCP server"""

    def __init__(self):
        super().__init__("app_launcher")

    def _setup_tools(self):
        self._tools = [
            MCPTool(
                name="launch_app",
                description="Launch an application by name",
                input_schema={
                    "type": "object",
                    "properties": {
                        "app_name": {"type": "string", "description": "Application name"}
                    },
                    "required": ["app_name"]
                }
            ),
            MCPTool(
                name="open_file",
                description="Open a file with its default application",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to file"}
                    },
                    "required": ["file_path"]
                }
            ),
            MCPTool(
                name="list_running_apps",
                description="List currently running applications",
                input_schema={"type": "object", "properties": {}}
            )
        ]

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "launch_app":
            app_name = arguments.get("app_name", "")
            try:
                if os.name == "nt":  # Windows
                    subprocess.Popen(["cmd", "/c", "start", "", app_name])
                else:  # macOS/Linux
                    subprocess.Popen([app_name])
                return {"success": True, "message": f"Launched {app_name}"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif name == "open_file":
            file_path = arguments.get("file_path", "")
            try:
                if os.name == "nt":
                    os.startfile(file_path)
                elif os.name == "posix":
                    subprocess.call(
                        ["open" if os.uname().sysname == "Darwin" else "xdg-open", file_path])
                return {"success": True, "message": f"Opened {file_path}"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif name == "list_running_apps":
            # Platform-specific implementation would go here
            return {"success": True, "apps": ["Feature requires platform-specific implementation"]}

        return {"error": f"Unknown tool: {name}"}


class SystemServer(BuiltinServer):
    """System control MCP server"""

    def __init__(self):
        super().__init__("system")

    def _setup_tools(self):
        self._tools = [
            MCPTool(
                name="get_system_info",
                description="Get system information",
                input_schema={"type": "object", "properties": {}}
            ),
            MCPTool(
                name="shutdown",
                description="Shutdown the system",
                input_schema={
                    "type": "object",
                    "properties": {
                        "delay": {"type": "integer", "description": "Delay in seconds", "default": 0}
                    }
                }
            ),
            MCPTool(
                name="restart",
                description="Restart the system",
                input_schema={
                    "type": "object",
                    "properties": {
                        "delay": {"type": "integer", "description": "Delay in seconds", "default": 0}
                    }
                }
            ),
            MCPTool(
                name="sleep",
                description="Put system to sleep",
                input_schema={"type": "object", "properties": {}}
            ),
            MCPTool(
                name="lock",
                description="Lock the screen",
                input_schema={"type": "object", "properties": {}}
            )
        ]

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "get_system_info":
            import platform
            return {
                "success": True,
                "info": {
                    "platform": platform.system(),
                    "release": platform.release(),
                    "version": platform.version(),
                    "machine": platform.machine(),
                    "processor": platform.processor()
                }
            }

        elif name == "shutdown":
            delay = arguments.get("delay", 0)
            # Note: This requires elevated permissions
            try:
                if os.name == "nt":
                    subprocess.run(["shutdown", "/s", "/t", str(delay)])
                else:
                    subprocess.run(["shutdown", "-h", "+", str(delay)])
                return {"success": True, "message": f"Shutdown scheduled in {delay} seconds"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif name == "restart":
            delay = arguments.get("delay", 0)
            try:
                if os.name == "nt":
                    subprocess.run(["shutdown", "/r", "/t", str(delay)])
                else:
                    subprocess.run(["shutdown", "-r", "+", str(delay)])
                return {"success": True, "message": f"Restart scheduled in {delay} seconds"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif name == "sleep":
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
                elif os.uname().sysname == "Darwin":
                    subprocess.run(["pmset", "sleepnow"])
                else:
                    subprocess.run(["systemctl", "suspend"])
                return {"success": True, "message": "Sleep initiated"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif name == "lock":
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["rundll32.exe", "user32.dll,LockWorkStation"])
                elif os.uname().sysname == "Darwin":
                    subprocess.run(
                        ["/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession", "-suspend"])
                else:
                    subprocess.run(["gnome-screensaver-command", "-l"])
                return {"success": True, "message": "Screen locked"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"error": f"Unknown tool: {name}"}


def _atomic_write(path: str, text: str, newline: Optional[str] = None) -> None:
    """Write via a temp file + os.replace: a crash leaves the old file, never a half one."""
    import tempfile

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)),
                               prefix=".iris-write-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _line_arg(arguments: Dict[str, Any], key: str) -> Optional[int]:
    """A positive line number from a tool argument, or None (models send "12" too)."""
    try:
        value = int(arguments.get(key))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _first_str(arguments: Dict[str, Any], keys: tuple) -> Optional[str]:
    for key in keys:
        value = arguments.get(key)
        if isinstance(value, str):
            return value
    return None


def _reroot_if_missing(path: str) -> tuple:
    """Return ``(usable_path, note)`` for a path that may not exist.

    WHY THIS EXISTS (session-364, measured live three times). The model invents
    absolute POSIX paths for files that live in the workspace - it asked for
    ``/home/user/scripts`` when it meant this repo's own ``scripts`` folder - and
    on Windows that becomes ``\\home\\user\\scripts``. ``list_directory`` then
    raised ``[WinError 3] The system cannot find the path specified``, whose text
    matches ``tool_decision._TERMINAL_FAILURE_SIGNALS`` ("cannot find"). That
    classifies the failure as TERMINAL, so NO GRAFT happens and the whole TURN
    finalizes (agent_kernel.py:12685 "critical step failed with an unrecoverable
    cause - no graft, finalizing honestly"). Measured cost: a 4-step plan was
    truncated to 2 steps, which is also what kept the completion monitors
    (>= 3 completed steps) at zero rows.

    SAFETY. This only ever fires when the ORIGINAL path does NOT exist, so a
    valid path can never be redirected; it corrects a non-existent path rather
    than imposing a policy on existing ones. Candidates are tried from the
    longest suffix to the shortest, so ``/home/user/scripts`` prefers
    ``<cwd>/user/scripts`` and falls back to ``<cwd>/scripts``. When it
    substitutes, the caller MUST surface ``note`` in the result so the
    substitution is observable instead of silent.

    This does NOT add workspace confinement - the file tools still accept any
    existing absolute path. Confinement is a separate decision.
    """
    if not path:
        return path, ""
    try:
        if Path(path).exists():
            return path, ""
    except (OSError, ValueError):
        return path, ""
    # Only absolute paths (POSIX, UNC/backslash, or drive-letter) are candidates.
    _is_abs = path.startswith(("/", "\\")) or (
        len(path) > 1 and path[1] == ":" and path[0].isalpha()
    )
    if not _is_abs:
        return path, ""
    parts = [
        seg for seg in path.replace("\\", "/").split("/")
        if seg and seg not in (".", "..")
    ]
    if parts and len(parts[0]) == 2 and parts[0][1] == ":":
        parts = parts[1:]  # drop a leading "C:" style drive token
    if not parts:
        return path, ""
    base = Path.cwd()
    for i in range(len(parts)):
        candidate = base.joinpath(*parts[i:])
        try:
            if candidate.exists():
                return str(candidate), (
                    f"'{path}' does not exist; used '{candidate}' instead "
                    f"(the path was re-rooted onto the workspace)"
                )
        except OSError:
            continue
    return path, ""


class FileManagerServer(BuiltinServer):
    """File manager MCP server"""

    def __init__(self):
        super().__init__("file_manager")

    def _setup_tools(self):
        self._tools = [
            MCPTool(
                name="read_file",
                description="Read a file. Optional start_line/end_line (1-based, inclusive) read part of it.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path"},
                        "start_line": {"type": "integer", "description": "First line to read (1-based)"},
                        "end_line": {"type": "integer", "description": "Last line to read (inclusive)"}
                    },
                    "required": ["path"]
                }
            ),
            MCPTool(
                name="write_file",
                description="Create a new file, or replace a whole file, with the given content",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path"},
                        "content": {"type": "string", "description": "Content to write"}
                    },
                    "required": ["path", "content"]
                }
            ),
            MCPTool(
                name="edit_file",
                description="Change part of an existing file: replace the exact text `old` (must occur exactly once) with `new`",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path"},
                        "old": {"type": "string", "description": "Exact text to replace; must match once"},
                        "new": {"type": "string", "description": "Replacement text"}
                    },
                    "required": ["path", "old", "new"]
                }
            ),
            MCPTool(
                name="list_directory",
                description="List contents of a directory",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path"},
                        "recursive": {"type": "boolean", "description": "List recursively", "default": False}
                    },
                    "required": ["path"]
                }
            ),
            MCPTool(
                name="create_directory",
                description="Create a new directory",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path"}
                    },
                    "required": ["path"]
                }
            ),
            MCPTool(
                name="delete_file",
                description="Delete a file or directory",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to delete"}
                    },
                    "required": ["path"]
                }
            )
        ]

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        # Argument names are resolved centrally (backend/tool_args.py): the schema
        # says `path`/`content`, the model sends `file_path`/`contents`, and each
        # of these handlers used to read one name with a "" default — which wrote
        # EMPTY files and answered success, or crashed opening "".
        from backend.tool_args import body_arg, missing_arg_error, path_arg

        if name == "read_file":
            path = path_arg(arguments)
            if not path:
                return missing_arg_error("read_file", "path", arguments)
            # session-364: a hallucinated absolute path (e.g. /home/user/x) is a
            # TERMINAL failure for the whole turn; re-root it onto the workspace.
            path, _reroot_note = _reroot_if_missing(path)
            try:
                content = await asyncio.to_thread(self._sync_read_file, path)
                result = {"success": True, "content": content, "path": path,
                          "bytes": len(content)}
                start, end = _line_arg(arguments, "start_line"), _line_arg(arguments, "end_line")
                if start or end:
                    lines = content.splitlines(keepends=True)
                    first = max(1, start or 1)
                    last = min(len(lines), end or len(lines))
                    result["content"] = "".join(lines[first - 1:last])
                    result.update(start_line=first, end_line=last, total_lines=len(lines))
                if _reroot_note:
                    result["notice"] = _reroot_note
                return result
            except Exception as e:
                return {"success": False, "error": str(e), "path": path}

        elif name == "edit_file":
            path = path_arg(arguments)
            if not path:
                return missing_arg_error("edit_file", "path", arguments)
            old = _first_str(arguments, ("old", "old_string", "old_text"))
            new = _first_str(arguments, ("new", "new_string", "new_text"))
            if not old:
                return missing_arg_error("edit_file", "old", arguments)
            if new is None:
                return missing_arg_error("edit_file", "new", arguments)
            try:
                return await asyncio.to_thread(self._sync_edit_file, path, old, new)
            except Exception as e:
                return {"success": False, "error": str(e), "path": path}

        elif name == "write_file":
            path = path_arg(arguments)
            if not path:
                return missing_arg_error("write_file", "path", arguments)
            content = body_arg(arguments)
            if content is None:
                return missing_arg_error("write_file", "content", arguments)
            try:
                await asyncio.to_thread(self._sync_write_file, path, content)
                # A non-empty body that produced an empty file is a BUG, not
                # success: it is how the user was told a file had been written
                # while nothing landed on disk.
                try:
                    _on_disk = Path(path).stat().st_size
                except OSError:
                    _on_disk = len(content.encode("utf-8"))
                if content and _on_disk == 0:
                    return {
                        "success": False,
                        "error": f"write_file wrote 0 bytes to {path} "
                                 f"(body had {len(content)} chars)",
                    }
                return {
                    "success": True,
                    "message": f"Written to {path}",
                    "bytes": len(content),
                    "bytes_on_disk": _on_disk,
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif name == "list_directory":
            path = path_arg(arguments) or "."
            recursive = arguments.get("recursive", False)
            # session-364: '/home/user/scripts' for the repo's own scripts folder
            # crashed here with WinError 3, which _TERMINAL_FAILURE_SIGNALS reads
            # as terminal -> no graft -> the whole turn finalized. Re-root it.
            path, _reroot_note = _reroot_if_missing(path)
            try:
                listing = await asyncio.to_thread(
                    self._sync_list_directory, path, recursive
                )
                result = {"success": True, "items": listing["items"], "path": path}
                if _reroot_note:
                    result["notice"] = _reroot_note
                if listing["truncated"]:
                    # REQ-18 AC4: a silently truncated listing reads as complete.
                    result["truncated"] = True
                    result["notice"] = (
                        f"Listing truncated at {len(listing['items'])} entries — "
                        f"use glob_files for recursive discovery."
                    )
                return result
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif name == "create_directory":
            path = path_arg(arguments)
            if not path:
                return missing_arg_error("create_directory", "path", arguments)
            try:
                await asyncio.to_thread(self._sync_create_directory, path)
                return {"success": True, "message": f"Created directory {path}"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif name == "delete_file":
            path = path_arg(arguments)
            if not path:
                return missing_arg_error("delete_file", "path", arguments)
            try:
                await asyncio.to_thread(self._sync_delete_file, path)
                return {"success": True, "message": f"Deleted {path}"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"error": f"Unknown tool: {name}"}

    # ── Sync helpers: run in a worker thread via asyncio.to_thread so file
    # I/O never blocks the asyncio event loop (RC10). ──
    @staticmethod
    def _sync_read_file(path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _sync_write_file(path: str, content: str) -> None:
        _atomic_write(path, content)

    @staticmethod
    def _sync_edit_file(path: str, old: str, new: str) -> dict:
        """Replace the one exact occurrence of `old` with `new` (B9).

        Read and written with newline="" so CRLF files keep their endings. An
        LF-only `old` is retried as CRLF against a CRLF file, because a model
        quotes code with bare newlines.
        """
        with open(path, "r", encoding="utf-8", newline="") as f:
            text = f.read()
        count = text.count(old)
        if count == 0 and "\r\n" in text and "\r\n" not in old and "\n" in old:
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
            count = text.count(old)
        if count == 0:
            return {"success": False, "path": path,
                    "error": "edit_file: `old` text was not found in the file; "
                             "read the file and quote the exact current text"}
        if count > 1:
            return {"success": False, "path": path,
                    "error": f"edit_file: `old` text occurs {count} times; "
                             "include more surrounding lines so it matches once"}
        updated = text.replace(old, new, 1)
        _atomic_write(path, updated, newline="")
        line = text[: text.index(old)].count("\n") + 1
        return {"success": True, "path": path, "message": f"Edited {path} at line {line}",
                "line": line, "bytes": len(updated.encode("utf-8"))}

    @staticmethod
    def _sync_list_directory(path: str, recursive: bool) -> dict:
        # REQ-18: recursive listing is BOUNDED — the old unbounded
        # Path.rglob("*") walked node_modules/.next/venv into agent context
        # with no ignore rules and no end. Recursive discovery belongs to
        # glob_files (ripgrep); this bound is a backstop, not a search.
        max_entries = 2000
        items = []
        truncated = False
        p = Path(path)
        it = p.rglob("*") if recursive else p.iterdir()
        for entry in it:
            if len(items) >= max_entries:
                truncated = True
                break
            items.append({
                "name": entry.name,
                "path": str(entry),
                "type": "directory" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else None,
            })
        return {"items": items, "truncated": truncated}

    @staticmethod
    def _sync_create_directory(path: str) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sync_delete_file(path: str) -> None:
        p = Path(path)
        if p.is_dir():
            import shutil
            shutil.rmtree(p)
        else:
            p.unlink()


class GUIAutomationServer(BuiltinServer):
    """GUI automation MCP server"""

    def __init__(self):
        super().__init__("gui_automation")

    def _setup_tools(self):
        self._tools = [
            MCPTool(
                name="click",
                description="Click at screen coordinates",
                input_schema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "X coordinate"},
                        "y": {"type": "integer", "description": "Y coordinate"},
                        "button": {"type": "string", "description": "Mouse button (left/right/middle)", "default": "left"}
                    },
                    "required": ["x", "y"]
                }
            ),
            MCPTool(
                name="type_text",
                description="Type text at current cursor position",
                input_schema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to type"}
                    },
                    "required": ["text"]
                }
            ),
            MCPTool(
                name="press_key",
                description="Press a keyboard key",
                input_schema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Key to press (e.g., 'enter', 'tab', 'ctrl+c')"}
                    },
                    "required": ["key"]
                }
            ),
            MCPTool(
                name="move_mouse",
                description="Move mouse to coordinates",
                input_schema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "X coordinate"},
                        "y": {"type": "integer", "description": "Y coordinate"}
                    },
                    "required": ["x", "y"]
                }
            ),
            MCPTool(
                name="screenshot",
                description="Take a screenshot",
                input_schema={
                    "type": "object",
                    "properties": {
                        "region": {
                            "type": "object",
                            "description": "Region to capture (x, y, width, height)",
                            "properties": {
                                "x": {"type": "integer"},
                                "y": {"type": "integer"},
                                "width": {"type": "integer"},
                                "height": {"type": "integer"}
                            }
                        }
                    }
                }
            )
        ]

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute GUI automation tool"""
        try:
            import pyautogui
        except ImportError:
            return {"success": False, "error": "pyautogui not installed. Install with: pip install pyautogui"}

        if name == "click":
            x = arguments.get("x")
            y = arguments.get("y")
            button = arguments.get("button", "left")
            try:
                pyautogui.click(x, y, button=button)
                return {"success": True, "message": f"Clicked at ({x}, {y}) with {button} button"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif name == "type_text":
            text = arguments.get("text", "")
            try:
                pyautogui.write(text)
                return {"success": True, "message": f"Typed: {text}"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif name == "press_key":
            key = arguments.get("key", "")
            try:
                # Handle key combinations like "ctrl+c"
                if "+" in key:
                    keys = key.split("+")
                    pyautogui.hotkey(*keys)
                else:
                    pyautogui.press(key)
                return {"success": True, "message": f"Pressed key: {key}"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif name == "move_mouse":
            x = arguments.get("x")
            y = arguments.get("y")
            try:
                pyautogui.moveTo(x, y)
                return {"success": True, "message": f"Moved mouse to ({x}, {y})"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif name == "screenshot":
            region = arguments.get("region")
            try:
                if region:
                    screenshot = pyautogui.screenshot(region=(
                        region["x"], region["y"], region["width"], region["height"]
                    ))
                else:
                    screenshot = pyautogui.screenshot()

                # Save to temp file
                import tempfile
                temp_file = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".png")
                screenshot.save(temp_file.name)

                return {
                    "success": True,
                    "message": "Screenshot captured",
                    "path": temp_file.name,
                    "size": {"width": screenshot.width, "height": screenshot.height}
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"error": f"Unknown tool: {name}"}


class InternalCapabilityServer(BuiltinServer):
    """Internal capability server for agent self-improvement and skill creation"""

    def __init__(self):
        super().__init__("internal")
        # backend/mcp/builtin_servers.py -> backend/agent/skills
        self.skills_dir = Path(__file__).parent.parent / "agent" / "skills"

    def _setup_tools(self):
        self._tools = [
            MCPTool(
                name="create_skill",
                description="Create a new learned skill for IRIS. The skill will be stored as a SKILL.md file in a new directory.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Skill name (kebab-case, e.g. 'python-expert')"},
                        "description": {"type": "string", "description": "Brief description of what the skill does"},
                        "content": {"type": "string", "description": "Full markdown content of the SKILL.md file (including YAML frontmatter)"}
                    },
                    "required": ["name", "content"]
                }
            )
        ]

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "create_skill":
            skill_name = arguments.get(
                "name", "").strip().lower().replace(" ", "-")
            content = arguments.get("content", "")

            if not skill_name:
                return {"success": False, "error": "Skill name is required"}

            target_dir = self.skills_dir / skill_name
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                skill_file = target_dir / "SKILL.md"
                skill_file.write_text(content, encoding="utf-8")

                return {
                    "success": True,
                    "message": f"Skill '{skill_name}' created successfully at {skill_file}",
                    "path": str(skill_file)
                }
            except Exception as e:
                return {"success": False, "error": f"Failed to create skill: {str(e)}"}

        return {"error": f"Unknown tool: {name}"}
