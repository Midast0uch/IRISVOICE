"""Unified status snapshot — replaces FE polling.

Returns one JSON aggregating: online state, git status & recent log, pending
writes, and any other state currently scattered across /api/* endpoints.
"""
import asyncio
import json
import logging
import os
import subprocess
import time
from fastapi import APIRouter
from typing import Any

logger = logging.getLogger(__name__)
router = APIRouter()


async def get_git_status() -> dict[str, Any]:
    """Fetch current git status and recent log for the project."""
    try:
        # Get the project root
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

        # Get git status
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5
        )

        status_lines = result.stdout.strip().split("\n") if result.stdout else []

        # Get recent log (last 5 commits)
        log_result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5
        )

        log_entries = log_result.stdout.strip().split("\n") if log_result.stdout else []

        return {
            "status": status_lines,
            "log": log_entries,
            "dirty": len([l for l in status_lines if l.strip()]) > 0
        }
    except subprocess.TimeoutExpired:
        logger.warning("[git_status] git commands timed out")
        return {"error": "timeout", "status": [], "log": [], "dirty": False}
    except FileNotFoundError:
        logger.warning("[git_status] git not found or not a repo")
        return {"error": "not_a_repo", "status": [], "log": [], "dirty": False}
    except Exception as e:
        logger.warning(f"[git_status] error: {e}")
        return {"error": str(e), "status": [], "log": [], "dirty": False}


async def build_snapshot() -> dict[str, Any]:
    """Build a unified status snapshot aggregating all polled endpoints."""
    snap: dict[str, Any] = {"ts": time.time()}

    # online — if backend is responding, it's online
    snap["online"] = True

    # git — status and recent log
    try:
        snap["git"] = await asyncio.wait_for(
            get_git_status(),
            timeout=5.0
        )
    except asyncio.TimeoutError:
        logger.warning("[snapshot] git status timed out")
        snap["git"] = {"error": "timeout"}
    except Exception as e:
        logger.warning(f"[snapshot] git error: {e}")
        snap["git"] = {"error": str(e)}

    # pending_writes — hardcoded to 0 for now (no actual tracking yet)
    snap["pending_writes"] = 0

    return snap


@router.get("/api/status/snapshot")
async def status_snapshot():
    """
    Return unified status snapshot.

    Response schema:
    {
      "ts": float,
      "online": bool,
      "git": {
        "status": [str],       # lines from git status --porcelain
        "log": [str],          # lines from git log --oneline
        "dirty": bool,
        "error": str?          # if present, git command failed
      },
      "pending_writes": int
    }
    """
    return await build_snapshot()
