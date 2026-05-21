"""
Git Operations Module — IRISVOICE Backend

Provides subprocess-based git operations for the iris-launcher developer mode.
All operations target the active project path (from iris_config.json).

Pending writes are stored in-memory as a dict keyed by write_id.
This is sufficient for the current architecture; persistence can be added later
if agent writes need to survive backend restarts.
"""

import os
import json
import subprocess
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# In-memory pending writes queue (id -> PendingWrite)
_pending_writes: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _get_project_root() -> str:
    """Return the active project path from config, or the IRIS repo itself."""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "iris_config.json",
    )
    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            projects = cfg.get("projects", [])
            if projects:
                return projects[0].get("path", os.path.dirname(config_path))
    except Exception:
        pass
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_git_root(start_path: str) -> str:
    """Find the actual git repository root by walking up from start_path."""
    current = os.path.abspath(start_path)
    while True:
        git_dir = os.path.join(current, ".git")
        if os.path.isdir(git_dir):
            # Verify it's a real git repo
            rc, _, _ = _run_git(["rev-parse", "--git-dir"], cwd=current)
            if rc == 0:
                return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return start_path


def _run_git(args: list[str], cwd: Optional[str] = None) -> tuple[int, str, str]:
    """Run a git command and return (exit_code, stdout, stderr)."""
    cwd = cwd or _get_project_root()
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        logger.error("git executable not found in PATH")
        return 127, "", "git executable not found"
    except subprocess.TimeoutExpired:
        return 1, "", "git command timed out"
    except Exception as exc:
        logger.error(f"git command failed: {exc}")
        return 1, "", str(exc)


# ---------------------------------------------------------------------------
# Git status
# ---------------------------------------------------------------------------

def get_git_status() -> dict:
    """Return git status for the active project."""
    root = _find_git_root(_get_project_root())
    if not os.path.isdir(os.path.join(root, ".git")):
        return {
            "branch": "",
            "clean": True,
            "lastCommit": "",
            "lastCommitMessage": "",
            "lastGoodCommit": "",
            "uncommittedFiles": [],
            "error": "Not a git repository",
        }

    # Branch
    rc, out, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    branch = out.strip() if rc == 0 else ""

    # Last commit
    rc, out, _ = _run_git(["log", "-1", "--format=%H|%s|%ci"], cwd=root)
    last_commit, last_msg, last_time = "", "", ""
    if rc == 0 and "|" in out:
        parts = out.strip().split("|", 2)
        if len(parts) == 3:
            last_commit, last_msg, last_time = parts

    # Last good commit (for rollback)
    rc, out, _ = _run_git(["log", "-1", "--format=%H"], cwd=root)
    last_good = out.strip() if rc == 0 else ""

    # Uncommitted files
    rc, out, _ = _run_git(["status", "--porcelain"], cwd=root)
    uncommitted = [line[3:].strip() for line in out.splitlines() if line.strip()]
    clean = len(uncommitted) == 0

    return {
        "branch": branch,
        "clean": clean,
        "lastCommit": last_commit,
        "lastCommitMessage": last_msg,
        "lastGoodCommit": last_good,
        "uncommittedFiles": uncommitted,
    }


# ---------------------------------------------------------------------------
# Git log
# ---------------------------------------------------------------------------

def get_git_log(limit: int = 20) -> dict:
    """Return recent commits."""
    root = _find_git_root(_get_project_root())
    if not os.path.isdir(os.path.join(root, ".git")):
        return {"commits": [], "error": "Not a git repository"}

    rc, out, _ = _run_git(
        ["log", f"--max-count={limit}", "--format=%H|%s|%ci|%ae"],
        cwd=root,
    )
    commits = []
    if rc == 0:
        for line in out.splitlines():
            parts = line.split("|", 3)
            if len(parts) >= 3:
                commits.append({
                    "hash": parts[0],
                    "message": parts[1],
                    "time": parts[2],
                    "auto": "auto:" in parts[1].lower() or "agent" in parts[3].lower(),
                })
    return {"commits": commits}


# ---------------------------------------------------------------------------
# Commit / rollback
# ---------------------------------------------------------------------------

import re

# Windows reserved filenames that cannot be used in git
_RESERVED_WIN = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])($|\.)", re.IGNORECASE
)


def commit_all(message: str) -> dict:
    """Stage all changes and commit."""
    root = _find_git_root(_get_project_root())
    if not os.path.isdir(os.path.join(root, ".git")):
        return {"status": "error", "error": "Not a git repository"}

    # Stage all, excluding Windows reserved filenames (nul, con, etc.)
    # Git pathspec negation: add everything except matching files
    _run_git(["add", "--", ":!nul", ":!NUL", ":!con", ":!CON"], cwd=root)

    # Commit
    rc, out, err = _run_git(["commit", "-m", message], cwd=root)
    if rc != 0:
        # nothing to commit is OK
        if "nothing to commit" in (out + err).lower():
            return {"status": "ok", "message": "Nothing to commit"}
        return {"status": "error", "error": f"git commit failed: {err}"}

    # Get new commit hash
    rc, out, _ = _run_git(["rev-parse", "HEAD"], cwd=root)
    return {"status": "ok", "hash": out.strip(), "message": message}


def rollback(target: str) -> dict:
    """Hard reset to target commit."""
    root = _find_git_root(_get_project_root())
    if not os.path.isdir(os.path.join(root, ".git")):
        return {"status": "error", "error": "Not a git repository"}

    rc, _, err = _run_git(["reset", "--hard", target], cwd=root)
    if rc != 0:
        return {"status": "error", "error": f"git reset failed: {err}"}
    return {"status": "ok", "target": target}


# ---------------------------------------------------------------------------
# Pending writes (diff review)
# ---------------------------------------------------------------------------

def get_pending_writes() -> dict:
    """Return all pending agent writes."""
    return {
        "pending": list(_pending_writes.values()),
    }


def queue_write(path: str, diff: str, description: str, content: str = "") -> str:
    """Queue a write for diff review. Called by iris_gateway after agent edits."""
    write_id = f"write_{datetime.utcnow().isoformat()}"
    _pending_writes[write_id] = {
        "id": write_id,
        "path": path,
        "diff": diff,
        "description": description,
        "timestamp": datetime.utcnow().isoformat(),
        "content": content,
    }
    logger.info(f"[DiffReview] Queued write {write_id} for {path}")
    return write_id


def approve_write(write_id: str) -> dict:
    """Approve a pending write — apply to disk and commit."""
    entry = _pending_writes.pop(write_id, None)
    if entry is None:
        return {"status": "error", "error": "Write not found"}

    root = _get_project_root()
    file_path = os.path.join(root, entry["path"])
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(entry["content"])
    except Exception as exc:
        return {"status": "error", "error": f"Failed to write file: {exc}"}

    # Auto-commit the approved write
    msg = f"agent: approve {entry['path']}"
    commit_result = commit_all(msg)
    if commit_result.get("status") != "ok":
        return {"status": "error", "error": commit_result.get("error", "commit failed")}

    return {"status": "ok", "path": entry["path"]}


def reject_write(write_id: str) -> dict:
    """Reject a pending write — discard without applying."""
    entry = _pending_writes.pop(write_id, None)
    if entry is None:
        return {"status": "error", "error": "Write not found"}
    logger.info(f"[DiffReview] Rejected write {write_id} for {entry['path']}")
    return {"status": "ok", "path": entry["path"]}
