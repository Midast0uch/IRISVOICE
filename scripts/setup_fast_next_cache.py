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
    if not path.exists():
        return None
    try:
        out = subprocess.check_output(
            ["cmd", "/c", "dir", "/AL", str(path)], text=True, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        return None
    # Look for a "<JUNCTION>   name   target [path]" line
    for line in out.splitlines():
        if "<JUNCTION>" in line:
            parts = line.split()
            if not parts:
                continue
            # Last token is the target path
            return Path(parts[-1])
    return None


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

    return 0


if __name__ == "__main__":
    sys.exit(main())
