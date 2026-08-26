"""Git operations for IRIS backend — developer mode support."""

import os
import subprocess
import logging

logger = logging.getLogger("irisvoice")


def _get_project_root() -> str:
    """Return the IRIS project root directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_git_root(start_path: str) -> str | None:
    """Walk up from start_path to find a .git directory."""
    current = start_path
    for _ in range(20):  # safety limit
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def _get_worktree_path(root: str) -> str:
    """Return the agent sandbox worktree path."""
    return os.path.join(root, ".iris-worktree")


def _run_git(args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd or _get_project_root(),
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        logger.warning("[git_ops] git executable not found")
        return 1, "", "git not found"


# ── Public API ───────────────────────────────────────────────

def get_git_status() -> dict:
    """Return git status for the active project."""
    root = _find_git_root(_get_project_root())
    if not root:
        return {"clean": True, "branch": "unknown", "modified": [], "untracked": []}

    rc, out, _ = _run_git(["status", "--porcelain", "-b"], cwd=root)
    if rc != 0:
        return {"clean": True, "branch": "unknown", "modified": [], "untracked": []}

    lines = out.splitlines()
    branch = "unknown"
    modified = []
    untracked = []

    for line in lines:
        if line.startswith("##"):
            branch = line[3:].split("...")[0].strip()
        elif len(line) >= 2:
            status = line[:2]
            path = line[3:].strip()
            if status.strip():
                modified.append(path)
            elif status == "??":
                untracked.append(path)

    return {
        "clean": not (modified or untracked),
        "branch": branch,
        "modified": modified,
        "untracked": untracked,
    }


def get_git_log(limit: int = 20) -> dict:
    """Return recent commits."""
    root = _find_git_root(_get_project_root())
    if not root:
        return {"commits": []}

    rc, out, _ = _run_git(
        ["log", f"-{limit}", "--pretty=format:%H|%s|%an|%ad", "--date=short"],
        cwd=root,
    )
    if rc != 0:
        return {"commits": []}

    commits = []
    for line in out.strip().splitlines():
        parts = line.split("|", 3)
        if len(parts) >= 3:
            commits.append({
                "hash": parts[0][:8],
                "message": parts[1],
                "author": parts[2],
                "date": parts[3] if len(parts) > 3 else "",
            })

    return {"commits": commits}


def commit_all(message: str) -> dict:
    """Stage all changes and commit."""
    root = _find_git_root(_get_project_root())
    if not root:
        return {"status": "error", "error": "not a git repository"}

    _run_git(["add", "."], cwd=root)
    rc, out, err = _run_git(["commit", "-m", message], cwd=root)
    if rc == 0:
        return {"status": "ok", "commit": out.strip()}
    return {"status": "error", "error": err or out}


def rollback(target: str) -> dict:
    """Hard reset to target commit."""
    root = _find_git_root(_get_project_root())
    if not root:
        return {"status": "error", "error": "not a git repository"}

    rc, out, err = _run_git(["reset", "--hard", target], cwd=root)
    if rc == 0:
        return {"status": "ok", "message": f"reset to {target}"}
    return {"status": "error", "error": err or out}


# ── Diff review / pending writes ─────────────────────────────
# REQ-14 (T0e): the queue is PER-SESSION and BOUNDED (was a process-global
# unbounded list — violated REQ-5 AC1). approve/reject are REAL gates:
# approve stages the path and commits it in the sandbox worktree (returning
# the hash); reject discards the change so nothing survives on disk.
# Promotion of approved worktree commits into the LIVE tree stays a separate
# user action (/api/git/worktree/merge) — REQ-13 AC2.

import threading

_PENDING_LOCK = threading.Lock()
_pending_writes: dict[str, list[dict]] = {}  # session_id -> bounded queue
_MAX_QUEUE_PER_SESSION = 50
_write_counter = 0


def get_pending_writes(session_id: str | None = None) -> dict:
    """Return pending agent writes awaiting diff review (one session or all)."""
    with _PENDING_LOCK:
        if session_id is not None:
            return {"writes": [dict(w) for w in _pending_writes.get(session_id, [])]}
        all_writes = [dict(w) for q in _pending_writes.values() for w in q]
        return {"writes": all_writes}


def queue_write(path: str, diff: str, description: str = "",
                session_id: str = "default") -> str:
    """Queue a write for diff review. Oldest evicted past the bound."""
    global _write_counter
    with _PENDING_LOCK:
        _write_counter += 1
        write_id = f"write-{_write_counter}"
        queue = _pending_writes.setdefault(session_id, [])
        if len(queue) >= _MAX_QUEUE_PER_SESSION:
            queue.pop(0)
        queue.append({
            "id": write_id,
            "session_id": session_id,
            "path": path,
            "diff": diff,
            "description": description,
            "status": "pending",
        })
    return write_id


def _find_write(write_id: str) -> tuple[str | None, dict | None]:
    with _PENDING_LOCK:
        for session_queue in _pending_writes.values():
            for w in session_queue:
                if w["id"] == write_id:
                    return session_queue, w
    return None, None


def _remove_write(write_id: str) -> None:
    with _PENDING_LOCK:
        for session_queue in _pending_writes.values():
            session_queue[:] = [w for w in session_queue if w["id"] != write_id]


def approve_write(write_id: str) -> dict:
    """Approve a pending write: stage its path and COMMIT it in the sandbox
    worktree, returning the commit hash. The change was already written to
    the worktree by the agent (pre-apply gate, REQ-13/REQ-14 AC3); approval
    makes it durable on the sandbox branch. It does NOT touch the live tree —
    promotion is /api/git/worktree/merge."""
    _, write = _find_write(write_id)
    if write is None:
        return {"status": "error", "error": "write not found"}

    root = _find_git_root(_get_project_root())
    wt = _get_worktree_path(root) if root else None
    cwd = wt if wt and os.path.isdir(wt) else root
    if not cwd:
        return {"status": "error", "error": "not a git repository"}

    path = write["path"]
    rc, out, err = _run_git(["add", "--", path], cwd=cwd)
    if rc != 0:
        return {"status": "error", "error": f"git add failed: {err or out}"}
    message = write.get("description") or f"approve write {write_id}: {path}"
    rc, out, err = _run_git(["commit", "-m", message, "--", path], cwd=cwd)
    if rc != 0:
        # Nothing was committed — surface why (conflict, nothing to commit…)
        return {"status": "error", "error": f"git commit failed: {err or out}"}
    _remove_write(write_id)
    return {"status": "ok", "writeId": write_id, "commit": out.strip()}


def reject_write(write_id: str) -> dict:
    """Reject a pending write: discard the change so it leaves no trace —
    tracked files restored to HEAD, untracked files deleted."""
    _, write = _find_write(write_id)
    if write is None:
        return {"status": "error", "error": "write not found"}

    root = _find_git_root(_get_project_root())
    wt = _get_worktree_path(root) if root else None
    cwd = wt if wt and os.path.isdir(wt) else root
    if not cwd:
        return {"status": "error", "error": "not a git repository"}

    path = write["path"]
    rc, out, err = _run_git(["restore", "--", path], cwd=cwd)
    if rc != 0:
        # Not a tracked modification — likely an untracked new file: delete it.
        target = os.path.join(cwd, path)
        try:
            if os.path.isfile(target):
                os.remove(target)
            elif os.path.isdir(target):
                import shutil
                shutil.rmtree(target)
        except OSError as exc:
            return {"status": "error", "error": f"could not discard {path}: {exc}"}
    _remove_write(write_id)
    return {"status": "ok", "writeId": write_id}


# ── Worktree API ─────────────────────────────────────────────

def get_worktree_status() -> dict:
    """Return agent sandbox worktree status."""
    root = _find_git_root(_get_project_root())
    if not root:
        return {"exists": False, "status": "no git root"}

    wt = _get_worktree_path(root)
    exists = os.path.isdir(wt)
    return {"exists": exists, "path": wt if exists else None}


def ensure_worktree() -> dict:
    """Create the agent sandbox worktree."""
    root = _find_git_root(_get_project_root())
    if not root:
        return {"status": "error", "error": "not a git repository"}

    wt = _get_worktree_path(root)
    if os.path.isdir(wt):
        return {"status": "ok", "message": "worktree already exists"}

    rc, out, err = _run_git(["worktree", "add", "-B", "agent-sandbox", wt], cwd=root)
    if rc == 0:
        return {"status": "ok", "path": wt}
    return {"status": "error", "error": err or out}


def remove_worktree() -> dict:
    """Remove the agent sandbox worktree."""
    root = _find_git_root(_get_project_root())
    if not root:
        return {"status": "error", "error": "not a git repository"}

    wt = _get_worktree_path(root)
    rc, _, err = _run_git(["worktree", "remove", "-f", wt], cwd=root)
    if rc == 0 or not os.path.isdir(wt):
        return {"status": "ok"}
    return {"status": "error", "error": err}


def commit_worktree(message: str) -> dict:
    """Commit all changes in the worktree."""
    root = _find_git_root(_get_project_root())
    if not root:
        return {"status": "error", "error": "not a git repository"}

    wt = _get_worktree_path(root)
    cwd = wt if os.path.isdir(wt) else root
    _run_git(["add", "."], cwd=cwd)
    rc, out, err = _run_git(["commit", "-m", message], cwd=cwd)
    if rc == 0:
        return {"status": "ok", "commit": out.strip()}
    return {"status": "error", "error": err or out}


def merge_worktree(strategy: str = "squash") -> dict:
    """Merge sandbox into main branch."""
    root = _find_git_root(_get_project_root())
    if not root:
        return {"status": "error", "error": "not a git repository"}

    rc, out, err = _run_git(["merge", f"--{strategy}", "agent-sandbox"], cwd=root)
    if rc == 0:
        return {"status": "ok"}
    return {"status": "error", "error": err or out}


def reset_worktree() -> dict:
    """Hard reset worktree to main HEAD."""
    root = _find_git_root(_get_project_root())
    if not root:
        return {"status": "error", "error": "not a git repository"}

    wt = _get_worktree_path(root)
    cwd = wt if os.path.isdir(wt) else root
    rc, out, err = _run_git(["reset", "--hard", "HEAD"], cwd=cwd)
    if rc == 0:
        return {"status": "ok"}
    return {"status": "error", "error": err or out}
