"""
Bundled-binary resolution for the IRIS Tauri widget.

When IRIS ships as the desktop widget, companion binaries (the llama-server
used by the vision model and the legacy subprocess brain path) are bundled via
Tauri's `externalBin` mechanism. Tauri v2 copies them next to the application
executable at runtime:

    Windows:  <app_root>/llama-server-<target-triple>.exe
    Linux:    <app_root>/llama-server-<target-triple>
    macOS:    <app_root>/llama-server-<target-triple>

This module centralises discovery so `LocalModelManager` and
`lfm_vl_provider` can find the bundled `llama-server` without hard-coding
machine-specific paths. Resolution order:

    1. Explicit env override (IRIS_LLAMA_SERVER)
    2. Bundled binary next to the running backend executable
    3. PATH (shutil.which)

No heavy imports at module load — keeps backend startup memory flat.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _target_triple() -> str | None:
    """Best-effort detection of the platform target triple for Tauri's
    externalBin suffix (e.g. ``x86_64-pc-windows-msvc``)."""
    plat = sys.platform
    if plat == "win32":
        return "x86_64-pc-windows-msvc"
    if plat == "darwin":
        # Universal/Intel — Tauri uses the build target; Intel is the safe guess.
        return "x86_64-apple-darwin"
    if plat == "linux":
        return "x86_64-unknown-linux-gnu"
    return None


def _bundled_candidates(name: str) -> list[Path]:
    """Candidate paths for a Tauri-bundled binary next to the running exe."""
    exe = sys.executable
    try:
        here = Path(exe).resolve().parent
    except (OSError, RuntimeError):
        return []
    triple = _target_triple()
    out: list[Path] = []
    if triple:
        suffix = ".exe" if sys.platform == "win32" else ""
        out.append(here / f"{name}-{triple}{suffix}")
    # Tauri `externalBin` layout (single-file sidecars).
    out.append(here / "resources" / "bin" / (f"{name}{'.exe' if sys.platform == 'win32' else ''}"))
    # Tauri `bundle.resources` layout: we ship the whole llama-server folder
    # (exe + its DLLs) as "llama-server/", resolved next to the backend exe.
    suffix = ".exe" if sys.platform == "win32" else ""
    out.append(here / name / f"{name}{suffix}")
    return out


def find_binary(name: str, *, env_var: str = "IRIS_LLAMA_SERVER") -> str | None:
    """Return an absolute path to ``name`` (e.g. ``llama-server``) or None.

    Checks, in order: explicit env override, a Tauri-bundled binary sitting
    next to the running backend executable, then PATH.
    """
    # 1. Explicit override
    env_path = os.environ.get(env_var)
    if env_path and Path(env_path).is_file():
        return env_path

    # 2. Bundled next to the backend executable (Tauri externalBin layout)
    for cand in _bundled_candidates(name):
        if cand.is_file():
            return str(cand)

    # 3. PATH
    found = shutil.which(name)
    if found:
        return found
    return None
