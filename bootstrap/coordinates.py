"""
Bootstrap Coordinate Store — IRIS Voice
Minimal bootstrap for MCM-EML-SDK2.0 compatibility.

Provides _resolve_coordinates_db() so mcm/mcp.py can find the database.
"""

import os
import sqlite3

# Local database path
_db_path = os.path.join(os.path.dirname(__file__), "coordinates.db")


def _resolve_coordinates_db():
    """Resolve the active coordinates database path.

    Priority:
    1. Try local bootstrap/coordinates.db
    2. Try ~/.mcm/coordinates.db (centralized)
    3. Walk up from cwd and search standard locations
    """
    # 1. Local bootstrap/coordinates.db
    if os.path.isfile(_db_path):
        try:
            conn = sqlite3.connect(_db_path, timeout=5)
            conn.close()
            return os.path.abspath(_db_path)
        except (sqlite3.OperationalError, OSError):
            pass

    # 2. Centralized ~/.mcm/coordinates.db
    home = os.path.expanduser("~")
    centralized = os.path.join(home, ".mcm", "coordinates.db")
    if os.path.isfile(centralized):
        try:
            conn = sqlite3.connect(centralized, timeout=5)
            conn.close()
            return os.path.abspath(centralized)
        except (sqlite3.OperationalError, OSError):
            pass

    # 3. Walk up from cwd to find project root, check standard locations
    cwd = os.getcwd()
    project_root = cwd
    current = cwd
    for _ in range(10):
        if os.path.isfile(os.path.join(current, "AGENT.md")) or os.path.isdir(
            os.path.join(current, "bootstrap")
        ):
            project_root = current
            break
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    candidates = []
    for root in [project_root, cwd]:
        for subpath in [
            os.path.join("data", "databases", "coordinates.db"),
            os.path.join("bootstrap", "coordinates.db"),
        ]:
            candidate = os.path.abspath(os.path.join(root, subpath))
            if os.path.isfile(candidate):
                candidates.append((os.path.getmtime(candidate), candidate))

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]

    return os.path.abspath(_db_path)


COORDINATES_DB = _resolve_coordinates_db()
