"""
Search tools — ripgrep-backed grep_files / glob_files (REQ-18 / T0h).

Two read-only tools over ONE bundled rg binary, resolved from the app bundle
before PATH (REQ-18 AC6). The speed comes from what ripgrep SKIPS and what the
wrappers RETURN, not from scan rate:

  - .gitignore respected by default (opt-out flag) — this is what avoids the
    node_modules tree that cannot be counted in 100s (measured in REQ-18).
  - files_with_matches by default returns PATHS ONLY (AC5) — contents on
    default would convert one cheap call into a context flood.
  - every result set is capped and SAYS SO when truncated (AC4).

Quality-check gates applied:
  - rg resolved lazily per call; no binary probing at import time.
  - subprocess calls are sync helpers meant for asyncio.to_thread callers.
  - bounded enumeration everywhere; no unbounded walks.
  - invalid regex is an explicit error naming the pattern — an empty result
    and a bad pattern must never look alike.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

# Result caps (AC4). Generous enough for real work, small enough that a
# flooded result cannot become a context-window failure.
_GREP_DEFAULT_CAP = 100
_GLOB_DEFAULT_CAP = 200
_GLOB_ENUMERATION_HARD_BOUND = 10_000

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

_rg_cache: Optional[str] = None
_rg_resolved = False


def resolve_rg() -> Optional[str]:
    """Resolve the bundled rg binary — app bundle locations before PATH.

    Order: IRIS_RG_PATH env → src-tauri/resources → src-tauri/binaries → PATH.
    Returns None when no rg exists anywhere (callers must surface that as an
    explicit error, never as an empty search result).
    """
    global _rg_cache, _rg_resolved
    if _rg_resolved:
        return _rg_cache
    _rg_resolved = True

    candidates: List[str] = []
    env_path = os.environ.get("IRIS_RG_PATH")
    if env_path:
        candidates.append(env_path)
    candidates.append(os.path.join(_REPO_ROOT, "src-tauri", "resources", "rg.exe"))
    candidates.append(os.path.join(_REPO_ROOT, "src-tauri", "resources", "rg"))
    candidates.append(os.path.join(_REPO_ROOT, "src-tauri", "binaries", "rg.exe"))
    for cand in candidates:
        if cand and os.path.isfile(cand):
            _rg_cache = cand
            return _rg_cache
    _rg_cache = shutil.which("rg")
    return _rg_cache


def reset_rg_cache_for_testing() -> None:
    global _rg_cache, _rg_resolved
    _rg_cache = None
    _rg_resolved = False


def _run_rg(args: List[str], cwd: str, timeout: int = 60):
    proc = subprocess.run(
        [resolve_rg()] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return proc


def grep_files(
    pattern: str,
    path: Optional[str] = None,
    glob: Optional[str] = None,
    output_mode: str = "files_with_matches",
    context_lines: int = 0,
    max_results: int = _GREP_DEFAULT_CAP,
    case_sensitive: bool = False,
    no_ignore: bool = False,
) -> Dict[str, Any]:
    """Content search (REQ-18 AC1). Returns paths / counts / content lines."""
    rg = resolve_rg()
    if not rg:
        return {"success": False, "error": "ripgrep (rg) is not available — cannot search"}
    if not pattern:
        return {"success": False, "error": "pattern is required"}

    scope = path or os.getcwd()
    if not os.path.isdir(scope):
        return {"success": False, "error": f"search path does not exist or is not a directory: {scope}"}

    if output_mode not in ("files_with_matches", "content", "count"):
        return {"success": False, "error": f"unknown output_mode '{output_mode}' (use files_with_matches | content | count)"}

    args = ["--no-messages", "--no-require-git"]
    # --no-require-git: honour .gitignore even OUTSIDE a git repo — a project
    # directory with a .gitignore but no .git still gets ignore semantics.
    if not case_sensitive:
        args.append("-i")
    if glob:
        args += ["--glob", glob]
    if no_ignore:
        args.append("--no-ignore")  # AC3 opt-out: .gitignore respected by default
    if output_mode == "files_with_matches":
        args.append("-l")
    elif output_mode == "count":
        args.append("-c")
    else:  # content
        args.append("-n")
        if context_lines > 0:
            args += ["-C", str(context_lines)]
    args += ["-e", pattern, "."]

    try:
        proc = _run_rg(args, cwd=scope)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"grep_files timed out after 60s searching '{scope}'"}

    if proc.returncode == 2:
        # rg usage/regex error — name the pattern explicitly (never silent-empty)
        stderr = (proc.stderr or "").strip() or "invalid pattern"
        return {"success": False, "error": f"grep_files: invalid regex pattern '{pattern}': {stderr}"}

    lines = [ln for ln in (proc.stdout or "").splitlines() if ln]
    truncated = len(lines) > max_results
    matches = lines[:max_results]

    out: Dict[str, Any] = {
        "success": True,
        "mode": output_mode,
        "pattern": pattern,
        "scope": scope,
        "matches": matches,
        "returned": len(matches),
    }
    if truncated:
        out["truncated"] = True
        out["notice"] = (
            f"Results truncated at {max_results} — refine the pattern, narrow the "
            f"path, or raise max_results. More matches exist."
        )
    elif proc.returncode == 1:
        out["notice"] = "No matches."
    return out


def glob_files(
    pattern: str,
    path: Optional[str] = None,
    max_results: int = _GLOB_DEFAULT_CAP,
    no_ignore: bool = False,
) -> Dict[str, Any]:
    """Path search (REQ-18 AC2): glob pattern, most-recently-modified first."""
    rg = resolve_rg()
    if not rg:
        return {"success": False, "error": "ripgrep (rg) is not available — cannot search"}
    if not pattern:
        return {"success": False, "error": "pattern is required"}

    scope = path or os.getcwd()
    if not os.path.isdir(scope):
        return {"success": False, "error": f"search path does not exist or is not a directory: {scope}"}

    args = ["--files", "--no-messages", "--no-require-git"]
    if no_ignore:
        args.append("--no-ignore")
    args += ["--glob", pattern]

    try:
        proc = _run_rg(args, cwd=scope)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"glob_files timed out after 60s searching '{scope}'"}
    if proc.returncode == 2:
        stderr = (proc.stderr or "").strip() or "invalid glob"
        return {"success": False, "error": f"glob_files: invalid glob pattern '{pattern}': {stderr}"}

    all_paths = [ln for ln in (proc.stdout or "").splitlines() if ln]
    if len(all_paths) > _GLOB_ENUMERATION_HARD_BOUND:
        all_paths = all_paths[:_GLOB_ENUMERATION_HARD_BOUND]

    # mtime-descending (AC2). stat only relative to scope — cheap even at thousands.
    def _mtime(rel: str) -> float:
        try:
            return os.stat(os.path.join(scope, rel)).st_mtime
        except OSError:
            return 0.0

    ranked = sorted(all_paths, key=_mtime, reverse=True)
    truncated = len(ranked) > max_results
    matches = ranked[:max_results]

    out: Dict[str, Any] = {
        "success": True,
        "pattern": pattern,
        "scope": scope,
        "matches": matches,
        "returned": len(matches),
        "total_found": len(all_paths),
    }
    if truncated:
        out["truncated"] = True
        out["notice"] = (
            f"Results truncated at {max_results} of {len(all_paths)} found — "
            f"most-recently-modified kept. Narrow the glob or raise max_results."
        )
    elif not matches:
        out["notice"] = "No files match this glob."
    return out
