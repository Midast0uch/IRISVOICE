"""
download_models.py — IRIS Model Setup Script

Downloads and verifies all AI models required for IRIS voice pipeline:
  1. CosyVoice3-0.5B   — Zero-shot TTS + voice cloning (primary engine)
  2. CosyVoice source  — Python package cloned from GitHub (required by AutoModel)

Run from the IRISVOICE/ directory:
  python scripts/download_models.py

Optional flags:
  --skip-source      Skip re-cloning the CosyVoice source repo (if already present)
  --force            Re-download model weights even if they already exist
  --check            Only verify paths — do not download anything
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Load .env so HF_TOKEN / HUGGING_FACE_HUB_TOKEN are available to huggingface_hub.
# Must happen before any huggingface_hub import.
try:
    from dotenv import load_dotenv as _load_dotenv
    _env_file = Path(__file__).parent.parent / ".env"
    if _env_file.exists():
        _load_dotenv(_env_file)
except ImportError:
    pass  # python-dotenv not installed — env vars must be set in the shell

# ---------------------------------------------------------------------------
# Paths (relative to this file: scripts/download_models.py)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR  = Path(__file__).parent              # IRISVOICE/scripts/
_PROJECT_DIR  = _SCRIPTS_DIR.parent               # IRISVOICE/
_BACKEND_DIR  = _PROJECT_DIR / "backend"
_VOICE_DIR    = _BACKEND_DIR / "voice"

COSYVOICE_REPO_DIR = _VOICE_DIR / "CosyVoice"
MODEL_DIR          = _VOICE_DIR / "pretrained_models" / "CosyVoice3-0.5B"
REFERENCE_AUDIO    = _PROJECT_DIR / "data" / "TOMV2.wav"
DATA_DIR           = _PROJECT_DIR / "data"

COSYVOICE_GITHUB   = "https://github.com/FunAudioLLM/CosyVoice.git"
COSYVOICE_HF_REPO  = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"

# Sentinel files that indicate a valid model download
MODEL_SENTINEL_FILES = ["cosyvoice3.yaml"]


def _green(s: str) -> str:
    return f"\033[92m{s}\033[0m"


def _yellow(s: str) -> str:
    return f"\033[93m{s}\033[0m"


def _red(s: str) -> str:
    return f"\033[91m{s}\033[0m"


def _bold(s: str) -> str:
    return f"\033[1m{s}\033[0m"


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------

def check_model_dir() -> bool:
    """Return True if CosyVoice3-0.5B model appears fully downloaded."""
    if not MODEL_DIR.exists():
        return False
    for sentinel in MODEL_SENTINEL_FILES:
        # Sentinel files may live at root or one level deep
        found = list(MODEL_DIR.glob(f"**/{sentinel}"))
        if not found:
            return False
    return True


def check_cosyvoice_source() -> bool:
    """Return True if CosyVoice source repo is present and has expected structure."""
    return (COSYVOICE_REPO_DIR / "cosyvoice" / "cli" / "cosyvoice.py").exists()


def check_reference_audio() -> bool:
    """Return True if the voice cloning reference audio exists."""
    return REFERENCE_AUDIO.exists()


def check_huggingface_hub() -> bool:
    """Return True if huggingface_hub is importable."""
    try:
        import huggingface_hub  # noqa: F401
        return True
    except ImportError:
        return False


def check_git() -> bool:
    """Return True if git is available in PATH."""
    try:
        result = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def clone_cosyvoice_source() -> bool:
    """Clone the CosyVoice GitHub repo and initialise submodules."""
    print(f"\n{_bold('[CosyVoice Source]')} Cloning {COSYVOICE_GITHUB}...")
    print(f"  Target: {COSYVOICE_REPO_DIR}")

    _VOICE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            ["git", "clone", "--recursive", COSYVOICE_GITHUB, str(COSYVOICE_REPO_DIR)],
            capture_output=False,
            timeout=300,
        )
        if result.returncode != 0:
            print(_red("  [FAIL] git clone failed"))
            return False

        # Initialise submodules (Matcha-TTS lives in third_party/)
        subprocess.run(
            ["git", "-C", str(COSYVOICE_REPO_DIR), "submodule", "update", "--init", "--recursive"],
            capture_output=False,
            timeout=120,
        )
        print(_green("  [OK] CosyVoice source cloned successfully"))
        return True

    except subprocess.TimeoutExpired:
        print(_red("  [FAIL] git clone timed out"))
        return False
    except Exception as exc:
        print(_red(f"  [FAIL] {exc}"))
        return False


def update_cosyvoice_source() -> bool:
    """Pull latest CosyVoice source and update submodules."""
    print(f"\n{_bold('[CosyVoice Source]')} Updating {COSYVOICE_REPO_DIR}...")
    try:
        subprocess.run(
            ["git", "-C", str(COSYVOICE_REPO_DIR), "pull", "--ff-only"],
            capture_output=False, timeout=60,
        )
        subprocess.run(
            ["git", "-C", str(COSYVOICE_REPO_DIR), "submodule", "update", "--recursive"],
            capture_output=False, timeout=60,
        )
        print(_green("  [OK] CosyVoice source up to date"))
        return True
    except Exception as exc:
        print(_yellow(f"  [WARN] git pull failed ({exc}) — using existing source"))
        return True  # non-fatal; existing source is fine


def download_cosyvoice3_weights(force: bool = False) -> bool:
    """Download CosyVoice3-0.5B model weights from HuggingFace."""
    print(f"\n{_bold('[CosyVoice3-0.5B Weights]')} Downloading from HuggingFace...")
    print(f"  Repo:   {COSYVOICE_HF_REPO}")
    print(f"  Target: {MODEL_DIR}")

    if check_model_dir() and not force:
        print(_green("  [OK] Model already present — skipping (use --force to re-download)"))
        return True

    if not check_huggingface_hub():
        print(_red("  [FAIL] huggingface_hub not installed."))
        print("  Run: pip install huggingface-hub>=0.20.0")
        return False

    from huggingface_hub import snapshot_download  # type: ignore

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # Resolve HuggingFace token — check common env var names
    hf_token = (
        os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        or os.environ.get("HUGGINGFACE_TOKEN")
    )
    if hf_token:
        print(f"  HuggingFace token: found ({hf_token[:8]}...)")
    else:
        print(_yellow(
            "  [WARN] No HuggingFace token found in environment.\n"
            "  If CosyVoice3-0.5B is a gated model, the download will fail.\n"
            "  Set HF_TOKEN in your .env file or shell and re-run."
        ))

    try:
        print("  Downloading (this may take several minutes — model is ~1 GB)...")
        snapshot_download(
            repo_id=COSYVOICE_HF_REPO,
            local_dir=str(MODEL_DIR),
            local_dir_use_symlinks=False,
            token=hf_token or None,
            ignore_patterns=["*.msgpack", "*.h5", "flax_model*"],
        )
        print(_green("  [OK] CosyVoice3-0.5B downloaded successfully"))
        return True

    except Exception as exc:
        print(_red(f"  [FAIL] Download failed: {exc}"))
        if "401" in str(exc) or "authentication" in str(exc).lower() or "token" in str(exc).lower():
            print("  This looks like an auth error. Make sure HF_TOKEN is set in your .env file.")
        else:
            print("  Check your internet connection and HuggingFace access.")
        return False


def ensure_data_dir_and_reference_audio() -> None:
    """Create data/ directory and print instructions for reference audio."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if check_reference_audio():
        print(_green(f"  [OK] Reference audio found: {REFERENCE_AUDIO}"))
    else:
        print(_yellow(f"\n  [ACTION REQUIRED] Voice cloning reference audio not found."))
        print(f"  Expected path: {REFERENCE_AUDIO}")
        print()
        print("  To enable voice cloning:")
        print("    1. Record 10-30 seconds of the target voice as a WAV file (16kHz, mono)")
        print("    2. Save it to: IRISVOICE/data/TOMV2.wav")
        print()
        print("  Without this file, IRIS will use CosyVoice3 with a default voice.")
        print("  TTS will still work — voice cloning just won't be active.")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def run_verification() -> dict:
    """Run all checks and return a status dict."""
    return {
        "git":              check_git(),
        "huggingface_hub":  check_huggingface_hub(),
        "cosyvoice_source": check_cosyvoice_source(),
        "model_weights":    check_model_dir(),
        "reference_audio":  check_reference_audio(),
    }


def print_status(status: dict) -> None:
    print(f"\n{_bold('=== IRIS Voice Pipeline — Setup Status ===')}")
    checks = [
        ("git",             "git available"),
        ("huggingface_hub", "huggingface_hub installed"),
        ("cosyvoice_source","CosyVoice source (backend/voice/CosyVoice/)"),
        ("model_weights",   "CosyVoice3-0.5B weights (backend/voice/pretrained_models/)"),
        ("reference_audio", "Voice cloning audio (data/TOMV2.wav)"),
    ]
    all_ok = True
    for key, label in checks:
        ok = status.get(key, False)
        icon = _green("[OK]") if ok else _yellow("[MISSING]")
        print(f"  {icon}  {label}")
        if not ok:
            all_ok = False

    if all_ok:
        print(f"\n{_green(_bold('All checks passed — CosyVoice3 TTS pipeline is ready.'))}")
    else:
        missing = [label for key, label in checks if not status.get(key)]
        print(f"\n{_yellow(_bold('Setup incomplete.'))} Missing: {', '.join(missing)}")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="IRIS model setup")
    parser.add_argument("--skip-source", action="store_true",
                        help="Skip CosyVoice source repo clone/update")
    parser.add_argument("--force", action="store_true",
                        help="Re-download model weights even if already present")
    parser.add_argument("--check", action="store_true",
                        help="Only print status — download nothing")
    args = parser.parse_args()

    print(f"\n{_bold('IRIS Voice Pipeline — Model Setup')}")
    print(f"Project root: {_PROJECT_DIR}\n")

    # Always show current status first
    status = run_verification()
    print_status(status)

    if args.check:
        sys.exit(0 if all(status.values()) else 1)

    errors = []

    # --- Step 1: CosyVoice source repo ---
    if not args.skip_source:
        if not status["cosyvoice_source"]:
            if not check_git():
                print(_red("[ERROR] git not found in PATH. Cannot clone CosyVoice source."))
                print("  Install git from https://git-scm.com/ and re-run.")
                errors.append("git_missing")
            else:
                if not clone_cosyvoice_source():
                    errors.append("cosyvoice_source_clone_failed")
        else:
            # Repo exists — offer to update
            update_cosyvoice_source()
    else:
        if not status["cosyvoice_source"]:
            print(_yellow("[WARN] --skip-source passed but CosyVoice source missing."))
            print(f"  Expected: {COSYVOICE_REPO_DIR}")

    # --- Step 2: Model weights ---
    if not download_cosyvoice3_weights(force=args.force):
        errors.append("model_download_failed")

    # --- Step 3: Reference audio guidance ---
    ensure_data_dir_and_reference_audio()

    # --- Final status ---
    print(f"\n{_bold('=== Final Status ===')}")
    final_status = run_verification()
    print_status(final_status)

    if errors:
        print(_red(f"Setup completed with errors: {', '.join(errors)}"))
        print("Fix the errors above and re-run this script.")
        sys.exit(1)
    else:
        print(_green("Setup complete. Start the backend with: uvicorn backend.main:app --port 8000"))
        sys.exit(0)


if __name__ == "__main__":
    main()
