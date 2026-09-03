"""
Build the IRIS backend sidecar binary for Tauri bundling.

Usage:
    python scripts/build_backend.py

Output:
    src-tauri/binaries/iris-backend-x86_64-pc-windows-msvc.exe  (Windows)
    src-tauri/binaries/iris-backend-x86_64-unknown-linux-gnu    (Linux)
    src-tauri/binaries/iris-backend-x86_64-apple-darwin          (macOS)

Requirements:
    pip install pyinstaller

Notes:
    - The Tauri sidecar name must match tauri.conf.json "externalBin": ["binaries/iris-backend"]
    - PyInstaller embeds Python + all dependencies; no Python install required on target machine
    - Run this script whenever backend source changes before doing `cargo tauri build`
"""

import os
import sys
import subprocess
import platform
import shutil
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
BINARIES_DIR = PROJECT_ROOT / "src-tauri" / "binaries"
ENTRY_POINT  = PROJECT_ROOT / "start-backend.py"
BUILD_DIR    = PROJECT_ROOT / "build_pyinstaller"

# ── Target triple (must match Tauri's expected sidecar filename) ────────────
_MACHINE = platform.machine().lower()
_ARCH    = "x86_64" if ("x86_64" in _MACHINE or "amd64" in _MACHINE) else _MACHINE

PLATFORM_TRIPLE = {
    "win32":  f"{_ARCH}-pc-windows-msvc",
    "linux":  f"{_ARCH}-unknown-linux-gnu",
    "darwin": f"{_ARCH}-apple-darwin",
}.get(sys.platform, f"{_ARCH}-unknown")

SIDECAR_NAME = f"iris-backend-{PLATFORM_TRIPLE}"
if sys.platform == "win32":
    SIDECAR_NAME += ".exe"

OUTPUT_PATH = BINARIES_DIR / SIDECAR_NAME


def check_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        return False


def main() -> None:
    print(f">> IRIS Backend Build Script")
    print(f"   Platform:  {sys.platform}")
    print(f"   Triple:    {PLATFORM_TRIPLE}")
    print(f"   Entry:     {ENTRY_POINT}")
    print(f"   Output:    {OUTPUT_PATH}")
    print()

    if not check_pyinstaller():
        print("[ERROR] PyInstaller not found. Run: pip install pyinstaller")
        sys.exit(1)

    if not ENTRY_POINT.exists():
        print(f"[ERROR] Entry point not found: {ENTRY_POINT}")
        sys.exit(1)

    BINARIES_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    # Collect hidden imports needed by the backend
    # Add more if PyInstaller misses dynamic imports
    HIDDEN_IMPORTS = [
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi",
        "starlette",
        "pydantic",
        "dotenv",
        "sqlite3",
        "json",
        "asyncio",
    ]

    hidden_flags = []
    for imp in HIDDEN_IMPORTS:
        hidden_flags += ["--hidden-import", imp]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "iris-backend",
        "--distpath", str(BINARIES_DIR),
        "--workpath", str(BUILD_DIR / "work"),
        "--specpath", str(BUILD_DIR),
        "--noconfirm",
        "--paths", str(PROJECT_ROOT),
    ] + hidden_flags + [str(ENTRY_POINT)]

    print(f"Running PyInstaller...")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode != 0:
        print("[ERROR] PyInstaller failed — see output above")
        sys.exit(1)

    # PyInstaller outputs as "iris-backend[.exe]" — rename to platform-triple form
    raw_output = BINARIES_DIR / ("iris-backend.exe" if sys.platform == "win32" else "iris-backend")
    if raw_output.exists() and raw_output != OUTPUT_PATH:
        shutil.move(str(raw_output), str(OUTPUT_PATH))
        print(f"\n[OK] Binary renamed to: {OUTPUT_PATH.name}")
    elif OUTPUT_PATH.exists():
        print(f"\n[OK] Binary already at correct path: {OUTPUT_PATH.name}")
    else:
        print(f"\n[WARN] Expected output not found at {OUTPUT_PATH}")

    size_mb = OUTPUT_PATH.stat().st_size / (1024 * 1024) if OUTPUT_PATH.exists() else 0
    print(f"[OK] Build complete — {size_mb:.1f} MB")
    print()
    print("Next steps:")
    print("  1. cargo tauri build   (bundles the new binary)")
    print("  2. Install MSI and verify backend starts automatically")


if __name__ == "__main__":
    main()
