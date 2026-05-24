"""Developer worktree isolation — agent writes in a sandboxed git worktree."""

import os
import subprocess
import logging
from datetime import datetime, timezone

logger = logging.getLogger("irisvoice")


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_git_root(start_path: str) -> str | None:
    current = start_path
    for _ in range(20):
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def _run_git(args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd or _project_root(),
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return 1, "", "git not found"


def _branch_name() -> str:
    """Generate today's agent sandbox branch name."""
    return f"iris-agent-{datetime.now(timezone.utc).strftime('%Y%m%d')}"


def setup(project_path: str | None = None) -> dict:
    """
    Create an isolated git worktree for the agent sandbox.
    Returns {status, worktree_path, branch}.
    """
    root = _find_git_root(project_path or _project_root())
    if not root:
        return {"status": "error", "error": "not a git repository"}

    branch = _branch_name()
    wt = os.path.join(root, ".iris-worktree")

    # Check if worktree already exists
    if os.path.isdir(wt):
        rc, out, _ = _run_git(["worktree", "list", "--porcelain"], cwd=root)
        if rc == 0 and wt in out:
            return {"status": "ok", "worktree_path": wt, "branch": branch}

    # Ensure the branch exists (create from current HEAD if not)
    rc, _, _ = _run_git(["rev-parse", "--verify", branch], cwd=root)
    if rc != 0:
        rc2, _, err2 = _run_git(["branch", branch], cwd=root)
        if rc2 != 0:
            return {"status": "error", "error": f"failed to create branch: {err2}"}

    # Create worktree
    rc, out, err = _run_git(["worktree", "add", "-B", branch, wt], cwd=root)
    if rc == 0:
        logger.info(f"[dev_worktree] Created worktree at {wt} on branch {branch}")
        return {"status": "ok", "worktree_path": wt, "branch": branch}
    return {"status": "error", "error": err or out}


def teardown(merge: bool = False) -> dict:
    """
    Remove the agent sandbox worktree.
    If merge=True, merge the sandbox branch into main first.
    """
    root = _find_git_root(_project_root())
    if not root:
        return {"status": "error", "error": "not a git repository"}

    wt = os.path.join(root, ".iris-worktree")
    branch = _branch_name()

    if merge:
        # Merge worktree branch into current HEAD branch
        rc, _, err = _run_git(["merge", "--squash", branch], cwd=root)
        if rc == 0:
            logger.info(f"[dev_worktree] Merged {branch} into main branch")
        else:
            logger.warning(f"[dev_worktree] Merge failed: {err}")

    # Remove worktree
    rc, _, err = _run_git(["worktree", "remove", "--force", wt], cwd=root)
    if rc == 0 or not os.path.isdir(wt):
        logger.info(f"[dev_worktree] Removed worktree {wt}")
        return {"status": "ok"}
    return {"status": "error", "error": err}


def status() -> dict:
    """Return current worktree status: branch, uncommitted files, diff summary."""
    root = _find_git_root(_project_root())
    if not root:
        return {"exists": False, "branch": None, "uncommitted_files": [], "diff_summary": ""}

    wt = os.path.join(root, ".iris-worktree")
    if not os.path.isdir(wt):
        return {"exists": False, "branch": None, "uncommitted_files": [], "diff_summary": ""}

    branch = _branch_name()

    # Uncommitted files
    rc, out, _ = _run_git(["status", "--porcelain"], cwd=wt)
    files = []
    if rc == 0:
        for line in out.strip().splitlines():
            if len(line) >= 3:
                files.append({"status": line[:2], "path": line[3:]})

    # Diff summary
    rc2, diff_out, _ = _run_git(["diff", "--stat"], cwd=wt)
    diff_summary = diff_out.strip() if rc2 == 0 else ""

    return {
        "exists": True,
        "worktree_path": wt,
        "branch": branch,
        "uncommitted_files": files,
        "diff_summary": diff_summary,
    }


def get_worktree_path() -> str | None:
    """Return the worktree path if it exists, else None."""
    root = _find_git_root(_project_root())
    if not root:
        return None
    wt = os.path.join(root, ".iris-worktree")
    return wt if os.path.isdir(wt) else None
