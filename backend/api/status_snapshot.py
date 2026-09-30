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

# Git status is expensive on this machine (HDD + huge worktree with
# node_modules/.next/models). The status broadcast loop polls every 1s when the
# user is active; re-running `git status` that often thrashes the disk. Cache
# the result for GIT_STATUS_TTL_SEC so the subprocess runs at most once per TTL
# regardless of poll frequency. (Each call carries timeout=5, so a slow run
# cannot leak a subprocess.)
GIT_STATUS_TTL_SEC: float = 5.0
# The TTL also scales with what the last run COST (2026-09-30): a run that
# takes d seconds is not repeated for GIT_STATUS_COST_FACTOR * d seconds, so
# this poll uses at most ~1/GIT_STATUS_COST_FACTOR of the disk's time. With a
# fixed 5 s TTL and a 5 s timeout, a slow repo ran git back to back forever:
# every run timed out (useless result) and kept the hard disk busy for its
# whole 5 s, next to SQLite, the TTS load and pytest (eval c07, 2026-09-30:
# "[git_status] git commands timed out" every ~5 s). A timeout counts as 5 s.
GIT_STATUS_COST_FACTOR: float = 10.0
_git_status_cache: dict[str, Any] = {"ts": 0.0, "value": None, "cost": 0.0}


def get_git_status() -> dict[str, Any]:
    """Fetch current git status and recent log for the project.

    SYNCHRONOUS on purpose — callers must run it off the event loop
    (asyncio.to_thread). It shells out to git, which blocks.
    """
    try:
        # Get the project root
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

        # Get git status. `timeout=` alone already kills the child and waits
        # for it (subprocess.run terminates the process on TimeoutExpired by
        # default since Python 3.6), so the subprocess cannot leak.
        #
        # NOTE: `kill_on_timeout=True` was tried here and is NOT a valid
        # subprocess kwarg — every call raised
        #   TypeError: Popen.__init__() got an unexpected keyword argument
        # git status therefore never ran, and the exception was logged as a
        # WARNING every 5s forever (a large share of the ~1 GB iris.log).
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )

        status_lines = result.stdout.strip().split("\n") if result.stdout else []

        # Get recent log (last 5 commits)
        log_result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
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


def _cached_git_status() -> dict[str, Any]:
    """Return git status, re-running the subprocess at most once per TTL."""
    now = time.monotonic()
    ttl = max(GIT_STATUS_TTL_SEC, GIT_STATUS_COST_FACTOR * _git_status_cache["cost"])
    if _git_status_cache["value"] is not None and now - _git_status_cache["ts"] < ttl:
        return _git_status_cache["value"]
    value = get_git_status()
    done = time.monotonic()
    _git_status_cache["ts"] = done
    _git_status_cache["value"] = value
    _git_status_cache["cost"] = done - now
    return value


async def build_snapshot() -> dict[str, Any]:
    """Build a unified status snapshot aggregating all polled endpoints."""
    snap: dict[str, Any] = {"ts": time.time()}

    # online — if backend is responding, it's online
    snap["online"] = True

    # git — status and recent log. Run OFF the event loop: get_git_status()
    # shells out to git (blocking subprocess.run) and must never stall WS
    # heartbeats / the status broadcast loop (frontend freeze, session 279).
    # Cached so the subprocess runs at most once per GIT_STATUS_TTL_SEC.
    try:
        snap["git"] = await asyncio.wait_for(
            asyncio.to_thread(_cached_git_status),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        logger.warning("[snapshot] git status timed out")
        snap["git"] = {"error": "timeout"}
    except Exception as e:
        logger.warning(f"[snapshot] git error: {e}")
        snap["git"] = {"error": str(e)}

    # pending_writes — hardcoded to 0 for now (no actual tracking yet)
    snap["pending_writes"] = 0

    # inference — provider registry + role bindings (single source of truth
    # for the frontend's provider/role selection UI).
    try:
        from backend.agent import get_active_kernel

        # Wave 5: resolve the active session's kernel instead of always
        # materialising a phantom "default" kernel just to read router state.
        _kernel = get_active_kernel("session_iris")
        _router = getattr(_kernel, "_router", None)
        if _router is not None:
            snap["inference"] = _router.snapshot()
        else:
            snap["inference"] = {
                "providers": [],
                "role_bindings": [],
                "default_role": None,
            }
    except Exception as e:
        logger.warning(f"[snapshot] inference state error: {e}")
        snap["inference"] = {"error": str(e)}

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
