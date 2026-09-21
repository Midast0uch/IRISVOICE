"""
setup_fast_next_cache - Relocate the Next.js .next cache to a fast local path.

On Windows, IRISVOICE often lives on a slow drive (e.g. Desktop under OneDrive
or behind antivirus real-time scanning). Next.js dev compilation in .next can
hang for minutes and balloon to 1-15 GB on slow drives.

This script creates a directory junction so `IRISVOICE/.next` resolves to a
fast local path.  The junction is transparent to Next.js - it just sees a
normal `.next` directory.

Idempotent: safe to run on every startup. If .next is already a junction to
the right target, exits cleanly. If it is a real directory with content, the
content is moved into the target first. If the target doesn't exist, it is
created.

Usage (from start-iris.bat or manually):
    python scripts/setup_fast_next_cache.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NEXT_DIR = REPO_ROOT / ".next"
FAST_TARGET = Path(os.environ.get("IRIS_NEXT_CACHE_DIR")
                   or (Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
                       / "iris-next-cache"))


def _is_junction(path: Path) -> bool:
    """Return True if path is an NTFS junction (or symlink)."""
    if not path.exists():
        return False
    try:
        attrs = subprocess.check_output(
            ["cmd", "/c", "fsutil", "reparsepoint", "query", str(path)],
            stderr=subprocess.DEVNULL, text=True,
        )
        return "Reparse Tag" in attrs
    except subprocess.CalledProcessError:
        return False


def _junction_target(path: Path) -> Path | None:
    """Return the target of the reparse point AT `path` (no recursion).

    Uses `fsutil reparsepoint query`, which reports the reparse point on the
    path itself. The previous implementation ran `dir /AL <path>`, which lists
    the path's CONTENTS — so once a nested junction existed inside the cache
    (the node_modules shim), `dir` reported THAT one instead of `.next`'s own
    target. The setup then mis-detected a healthy junction as wrong and
    churned it on every start. (Caught 2026-09-15.)
    """
    if not path.exists():
        return None
    try:
        out = subprocess.check_output(
            ["cmd", "/c", "fsutil", "reparsepoint", "query", str(path)],
            text=True, stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return None
    for line in out.splitlines():
        stripped = line.strip()
        # Match "Print Name:" exactly — NOT the "Print Name offset:" line.
        if stripped.startswith("Print Name:"):
            target = stripped.split(":", 1)[1].strip()
            if target:
                return Path(target)
    return None


def _ensure_cache_node_modules() -> None:
    """Put a `node_modules` junction at the cache root.

    The `.next` junction alone BREAKS Node's module resolution: Turbopack
    resolves the cache to its REAL path (LOCALAPPDATA\\...), then walks UP
    looking for `node_modules` and finds none, so every external import dies
    with `Failed to load external module react/jsx-runtime` (observed
    2026-09-15). A `node_modules` junction at the cache root makes that walk
    succeed at the single real node_modules — no duplicate React, so no
    "invalid hook call". Idempotent; a no-op once correct.
    """
    nm_real = REPO_ROOT / "node_modules"
    nm_link = FAST_TARGET / "node_modules"
    if not nm_real.exists():
        return
    if _is_junction(nm_link):
        existing = _junction_target(nm_link)
        if existing and existing.resolve() == nm_real.resolve():
            return
        print(f"[fix] {nm_link} is a junction to {existing}, expected {nm_real}")
        nm_link.rmdir()
    elif nm_link.exists():
        print(f"[warn] {nm_link} exists but is not a junction; leaving as-is")
        return
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(nm_link), str(nm_real)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"[ok] created junction {nm_link} -> {nm_real}")
    else:
        print(f"[warn] node_modules junction failed: {result.stderr or result.stdout}")


def main() -> int:
    if sys.platform != "win32":
        print(f"[skip] non-Windows platform; .next left at {NEXT_DIR}")
        return 0

    # Ensure target exists
    FAST_TARGET.mkdir(parents=True, exist_ok=True)
    print(f"[info] fast cache target: {FAST_TARGET}")

    # Case 1: .next is already a junction to the right place
    if _is_junction(NEXT_DIR):
        existing = _junction_target(NEXT_DIR)
        if existing and existing.resolve() == FAST_TARGET.resolve():
            print(f"[ok] {NEXT_DIR} is already a junction to {FAST_TARGET}")
            # Still ensure the node_modules shim — it is required for Node
            # module resolution from the cache's real path, and must be
            # (re)established even when .next is already correct.
            _ensure_cache_node_modules()
            return 0
        else:
            print(f"[fix] {NEXT_DIR} is a junction to {existing}, expected {FAST_TARGET}")
            NEXT_DIR.rmdir()

    # Case 2: .next is a real (non-empty) directory - move its contents to the
    # target, then replace with a junction. This preserves any in-progress
    # build artifacts so we don't trigger a full recompile.
    if NEXT_DIR.exists() or NEXT_DIR.is_symlink():
        if NEXT_DIR.is_symlink() or not _is_junction(NEXT_DIR):
            contents = list(NEXT_DIR.iterdir())
            if contents:
                print(f"[move] relocating {len(contents)} entries from {NEXT_DIR} to {FAST_TARGET}")
                for entry in contents:
                    dest = FAST_TARGET / entry.name
                    if dest.exists():
                        if dest.is_dir():
                            shutil.rmtree(dest, ignore_errors=True)
                        else:
                            dest.unlink()
                    shutil.move(str(entry), str(dest))
            try:
                NEXT_DIR.rmdir()
            except OSError:
                # Junction case handled above; here it's a real dir - use rmdir /S /Q
                subprocess.run(["cmd", "/c", "rmdir", "/S", "/Q", str(NEXT_DIR)],
                               check=False, capture_output=True)
        # else: empty directory
        if NEXT_DIR.exists():
            try:
                NEXT_DIR.rmdir()
            except OSError:
                pass

    # Case 3: Create the junction
    if not NEXT_DIR.exists():
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(NEXT_DIR), str(FAST_TARGET)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"[error] mklink failed: {result.stderr or result.stdout}")
            print("[fallback] .next will be created in the project root")
            return 1
        print(f"[ok] created junction {NEXT_DIR} -> {FAST_TARGET}")
    else:
        # Already exists - re-verify
        if _is_junction(NEXT_DIR):
            print(f"[ok] {NEXT_DIR} -> {_junction_target(NEXT_DIR)}")
        else:
            print(f"[warn] {NEXT_DIR} exists but is not a junction; leaving as-is")

    # Node resolves the junction to its real path, then walks up for
    # node_modules. Without a shim at the cache root every external import
    # (react/jsx-runtime) fails to load. Always ensure it.
    _ensure_cache_node_modules()
    return 0


if __name__ == "__main__":
    sys.exit(main())
