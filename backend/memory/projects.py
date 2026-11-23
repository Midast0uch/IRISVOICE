"""Projects: WHERE the memory's work happened (owner, 2026-11-23 - "Lens + record at source").

The galaxies sort the memory by meaning (one per domain). A project is the other axis: the folder the work ran in
- IRIS working on itself, an app being built, an MCP server being built. Measured before this module: every
conversation's project_id empty (1,137), project_registry 0 rows, no claim knew its project, so a project's work
was mixed into the topic galaxies for good.

ONE resolver (`project_of`) and ONE writer (`note_path`, on the `projects` lane). The tool bridge calls `note_path`
when a session works in a new folder; `claim_finding` keeps the project on a new claim; the surface reads them back.
Design: docs/plans/2026-11-23-memory-projects-and-constellations-design.md.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# a project root is the first folder upward that holds one of these
ROOT_MARKERS = (".git", "package.json", "pyproject.toml", "Cargo.toml", "go.mod", "setup.py")
EVAL_FOLDER = "iris-evals"        # an evaluation's throwaway workspace (evals/run_evals.py EVAL_ROOT): never a project
MAX_UP = 8                      # levels walked upward from a folder
MANIFEST_READ = 65536           # bytes of package.json / pyproject.toml read to tell an MCP server
IRIS_ROOT = os.path.normcase(os.path.normpath(str(Path(__file__).resolve().parents[2])))
KINDS = ("iris", "app", "mcp")

REGISTRY_DDL = ("CREATE TABLE IF NOT EXISTS project_registry (project_id TEXT PRIMARY KEY, name TEXT NOT NULL, "
                "path TEXT, description TEXT, tags TEXT, created_at REAL, last_active REAL)")


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def _stop(folder: str) -> bool:
    """Never a project root: the home folder or a drive root."""
    return folder == _norm(str(Path.home())) or os.path.dirname(folder) == folder


_MCP_DEP = re.compile(r"[\"']mcp[\[<>=~!\s\"']")   # a dependency named mcp ("mcp>=1.2", 'mcp[cli]')


def _is_mcp(root: str, name: str) -> bool:
    if "mcp" in name.lower().replace("_", "-").split("-") or name.lower().startswith("mcp") or name.lower().endswith("mcp"):
        return True
    for fn in ("package.json", "pyproject.toml"):
        try:
            with open(os.path.join(root, fn), "r", encoding="utf-8", errors="replace") as f:
                text = f.read(MANIFEST_READ).lower()
        except OSError:
            continue
        if "@modelcontextprotocol" in text or "fastmcp" in text or _MCP_DEP.search(text):
            return True
    return False


def _is_iris_worktree(root: str) -> bool:
    """A git worktree of IRIS (the self-edit sandbox): its `.git` is a FILE that points into IRIS's own .git."""
    try:
        with open(os.path.join(root, ".git"), "r", encoding="utf-8", errors="replace") as f:
            line = f.read(4096).strip()
    except OSError:      # a folder (a normal repo), or none
        return False
    return line.startswith("gitdir:") and _norm(line[7:].strip()).startswith(os.path.join(IRIS_ROOT, ".git") + os.sep)


def _describe(root: str) -> dict:
    """{id, name, path, kind} of a project root (already normalised)."""
    iris = root == IRIS_ROOT or root.startswith(IRIS_ROOT + os.sep) or _is_iris_worktree(root)
    name = "IRIS" if iris else (os.path.basename(root) or root)
    kind = "iris" if iris else ("mcp" if _is_mcp(root, name) else "app")
    if iris:
        root = IRIS_ROOT    # the self-edit sandbox worktree is IRIS too: one project
    return {"id": "proj_" + hashlib.sha1(root.encode("utf-8")).hexdigest()[:12], "name": name, "path": root, "kind": kind}


@lru_cache(maxsize=256)
def _root_of(folder: str) -> Optional[str]:
    cur = folder
    for _ in range(MAX_UP):
        if _stop(cur):
            return None
        if any(os.path.exists(os.path.join(cur, m)) for m in ROOT_MARKERS):
            return cur
        up = os.path.dirname(cur)
        if up == cur:
            return None
        cur = up
    return None


def project_of(folder: Optional[str], probe: bool = True) -> Optional[dict]:
    """The project a folder belongs to, or None (a loose folder is not a project).

    probe=True walks up the disk to the first root marker (bounded, cached). probe=False never touches the disk: the
    folder itself is taken as the root (old claims name a folder that may be gone). Never raises."""
    if not folder or not isinstance(folder, str):
        return None
    try:
        f = _norm(folder.strip().strip("\"'").rstrip("\\/") or folder)
        if EVAL_FOLDER in f.split(os.sep):
            return None
        if not probe:
            return None if _stop(f) else _describe(f)
        if os.path.isfile(f):
            f = os.path.dirname(f)
        root = _root_of(f)
        return _describe(root) if root else None
    except Exception as exc:  # noqa: BLE001 - a project is a label; the work stands without it
        logger.warning("[projects] project_of failed folder=%r: %s", folder, exc)
        return None


def project_of_path(path: Optional[str], base: Optional[str] = None) -> Optional[dict]:
    """The project of a tool's file path: absolute as given, relative against `base` (the session workdir, else
    the backend's own folder = IRIS)."""
    if not path or not isinstance(path, str) or not path.strip():
        return None
    p = path.strip()
    if not os.path.isabs(p):
        p = os.path.join(base or IRIS_ROOT, p)
    return project_of(os.path.dirname(p) if os.path.splitext(p)[1] else p)


def ensure_registry(conn) -> None:
    conn.execute(REGISTRY_DDL)
    have = {r[1] for r in conn.execute("PRAGMA table_info(project_registry)")}
    if "kind" not in have:
        conn.execute("ALTER TABLE project_registry ADD COLUMN kind TEXT")


def _store_conn():
    """The app store's shared connection (the memory interface's), or None."""
    from backend.agent.ontology_recall import resolve_mycelium_conn
    from backend.memory import get_memory_interface

    return resolve_mycelium_conn(get_memory_interface())


def _write(conversation_id: Optional[str], project: dict) -> None:
    """Lane body: upsert the registry row, stamp an EMPTY conversation. Logs, never raises."""
    now = time.time()
    try:
        from backend.memory.db import app_write

        conn = _store_conn()
        if conn is not None:
            ensure_registry(conn)
            app_write(conn, "INSERT INTO project_registry (project_id, name, path, kind, tags, created_at, last_active) "
                            "VALUES (?, ?, ?, ?, '[]', ?, ?) ON CONFLICT(project_id) DO UPDATE SET last_active = "
                            "excluded.last_active, name = excluded.name, kind = excluded.kind",
                      (project["id"], project["name"], project["path"], project["kind"], now, now))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[projects] registry not written project=%s: %s", project.get("id"), exc)
    if conversation_id:
        try:
            from backend import conversation_store

            conversation_store.set_project_if_empty(conversation_id, project["id"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[projects] conversation not stamped conv=%s project=%s: %s", conversation_id, project.get("id"), exc)


def _resolve_and_write(conversation_id: Optional[str], path: str, base: Optional[str]) -> None:
    project = project_of_path(path, base)
    if project:
        _write(conversation_id, project)


def note_path(conversation_id: Optional[str], path: Optional[str], base: Optional[str] = None) -> bool:
    """Record that a conversation works where `path` is (a file or a folder; relative against `base`). The disk walk
    and both writes run on the `projects` lane (one ordered writer), never on the answer path. False when there is
    nothing to record or the lane dropped it."""
    if not path or not isinstance(path, str) or not path.strip():
        return False
    from backend.utils.durability_queue import lane

    return lane("projects").submit("project_note", _resolve_and_write, conversation_id, path, base)


def short(project: Optional[dict]) -> Optional[dict]:
    """What a claim keeps: {id, name, kind}."""
    return {k: project[k] for k in ("id", "name", "kind")} if project else None


def from_json(text) -> Optional[dict]:
    try:
        d = json.loads(text) if isinstance(text, str) else text
        p = d.get("project") if isinstance(d, dict) else None
        return p if isinstance(p, dict) and p.get("id") else None
    except Exception:  # noqa: BLE001 - an unreadable finding has no project
        return None
