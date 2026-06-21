# Env-Local API Key Configuration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users configure API keys (Picovoice, HuggingFace, and arbitrary custom keys) via the iris-launcher UI, persisting them to `IRISVOICE/.env.local` with backend hot-reload — no manual file editing, no backend restart.

**Architecture:** Backend FastAPI router (`/api/env-keys/*`) reads/writes `IRISVOICE/.env.local` with comment preservation, key masking, backup-before-write, and hot-reload via `load_dotenv(override=True)`. Tauri filesystem commands provide a fallback path when the backend is down (first-run scenario). Launcher React pages (ConfigPage for first-run, SettingsPage for dashboard) call the backend API with Tauri fallback.

**Tech Stack:** Python 3 / FastAPI / python-dotenv / pytest (backend); Rust / Tauri v2 (launcher native); TypeScript / React 18 / Vite / react-router-dom (launcher frontend)

---

## Critical Context (READ BEFORE STARTING)

### File Locations (DO NOT GET THESE WRONG)

| What | Path | Notes |
|------|------|-------|
| `.env.local` (real keys) | `C:\dev\IRISVOICE\.env.local` | **ROOT of repo, NOT iris-launcher/**. Already exists with real Picovoice + HF keys. Gitignored. |
| `.env.example` (template) | `C:\dev\IRISVOICE\.env.example` | Documents known keys with help links. Committed. |
| Backend env loading | `C:\dev\IRISVOICE\start-backend.py:24-25` | `load_dotenv(".env")` then `load_dotenv(".env.local", override=True)` |
| Backend config SSOT | `C:\dev\IRISVOICE\backend\iris_config.py` | Handles `data/iris_config.json` — NOT env keys. Do not conflate. |
| Picovoice consumer | `C:\dev\IRISVOICE\backend\voice\porcupine_detector.py:79` | `os.getenv("PICOVOICE_ACCESS_KEY")` |
| HuggingFace consumer | `huggingface_hub` library | Auto-reads `HF_TOKEN` from env |
| Launcher app entry | `C:\dev\IRISVOICE\iris-launcher\src\App.tsx` | Routes + providers |
| Launcher API client | `C:\dev\IRISVOICE\iris-launcher\src\lib\iris-api.ts` | `BASE = import.meta.env.VITE_IRIS_BACKEND_URL` |
| Launcher context | `C:\dev\IRISVOICE\iris-launcher\src\contexts\AppContext.tsx` | localStorage-backed state |
| Tauri config | `C:\dev\IRISVOICE\iris-launcher\src-tauri\tauri.conf.json` | No fs plugin yet |
| Tauri main | `C:\dev\IRISVOICE\iris-launcher\src-tauri\src\main.rs` | Empty builder — no commands registered |

### Security Rules (NON-NEGOTIABLE)

1. **NEVER log full API key values** — always mask before logging
2. **NEVER return full key values in API responses** — mask in GET, omit in POST responses
3. **NEVER commit `.env.local`** — it is gitignored (`.env*.local` in root `.gitignore:28`)
4. **NEVER copy real keys from `.env.local` into any repo file** — private memory only
5. **Backup `.env.local` → `.env.local.bak` before every write**
6. **File lock during write** — prevent concurrent corruption

### Existing Conventions to Match

- Backend tests: `pytest`, class-based (`class TestX:`), descriptive method names, `monkeypatch` for env
- Backend API: FastAPI `APIRouter` pattern (see `backend/api/status_snapshot.py`)
- Launcher pages: default export, `useApp()` for context, `irisApi` for backend calls
- Launcher UI: Tailwind + `glass-card` + `LiquidIcon` + framer-motion + `PageTransition`

### How to Run Tests

```bash
# Backend tests (from repo root)
.venv\Scripts\activate
python -m pytest backend/tests/test_env_keys.py -v

# Launcher dev (from iris-launcher/)
cd iris-launcher
npm run dev   # serves on :8080

# Tauri dev (from iris-launcher/)
cd iris-launcher
npm run tauri dev
```

---

## Task 1: Backend — env_keys.py parser

**Files:**
- Create: `backend/env_keys.py`
- Test: `backend/tests/test_env_keys.py`

**Step 1: Write the failing test**

Create `backend/tests/test_env_keys.py`:

```python
"""
Tests for backend.env_keys — .env.local parser/writer/masker.

Run: python -m pytest backend/tests/test_env_keys.py -v
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


class TestParseEnvLocal:
    """parse_env_local() reads a .env file into a dict, preserving comments."""

    def test_parse_simple_key_value(self, tmp_path):
        f = tmp_path / ".env.local"
        f.write_text("HF_TOKEN=hf_abc123\n", encoding="utf-8")
        from backend.env_keys import parse_env_local
        result = parse_env_local(f)
        assert result == {"HF_TOKEN": "hf_abc123"}

    def test_parse_skips_comments(self, tmp_path):
        f = tmp_path / ".env.local"
        f.write_text("# This is a comment\nHF_TOKEN=hf_abc123\n# Another\n", encoding="utf-8")
        from backend.env_keys import parse_env_local
        result = parse_env_local(f)
        assert result == {"HF_TOKEN": "hf_abc123"}

    def test_parse_skips_blank_lines(self, tmp_path):
        f = tmp_path / ".env.local"
        f.write_text("\nHF_TOKEN=hf_abc123\n\n\n", encoding="utf-8")
        from backend.env_keys import parse_env_local
        result = parse_env_local(f)
        assert result == {"HF_TOKEN": "hf_abc123"}

    def test_parse_strips_whitespace(self, tmp_path):
        f = tmp_path / ".env.local"
        f.write_text("  HF_TOKEN  =  hf_abc123  \n", encoding="utf-8")
        from backend.env_keys import parse_env_local
        result = parse_env_local(f)
        assert result == {"HF_TOKEN": "hf_abc123"}

    def test_parse_empty_file_returns_empty_dict(self, tmp_path):
        f = tmp_path / ".env.local"
        f.write_text("", encoding="utf-8")
        from backend.env_keys import parse_env_local
        result = parse_env_local(f)
        assert result == {}

    def test_parse_missing_file_returns_empty_dict(self, tmp_path):
        f = tmp_path / ".env.local"  # does not exist
        from backend.env_keys import parse_env_local
        result = parse_env_local(f)
        assert result == {}

    def test_parse_preserves_value_with_equals_sign(self, tmp_path):
        f = tmp_path / ".env.local"
        f.write_text("PICOVOICE_ACCESS_KEY=wIQ/h4D4+0E56z==\n", encoding="utf-8")
        from backend.env_keys import parse_env_local
        result = parse_env_local(f)
        assert result == {"PICOVOICE_ACCESS_KEY": "wIQ/h4D4+0E56z=="}
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_env_keys.py::TestParseEnvLocal -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.env_keys'`

**Step 3: Write minimal implementation**

Create `backend/env_keys.py`:

```python
"""
.env.local manager — parse, write, mask, and reload API keys.

The .env.local file lives at the IRISVOICE repo root (NOT in iris-launcher/).
It is gitignored and contains real API keys (Picovoice, HuggingFace, custom).

This module is the ONLY code that should read/write .env.local directly.
All API endpoints go through these functions.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("irisvoice")

# ── Path resolution ────────────────────────────────────────────────────────
# backend/env_keys.py is at IRISVOICE/backend/env_keys.py
# .env.local is at IRISVOICE/.env.local  →  two levels up
_REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_LOCAL_PATH = _REPO_ROOT / ".env.local"
ENV_EXAMPLE_PATH = _REPO_ROOT / ".env.example"

# File lock — serializes concurrent writes to .env.local
_write_lock = threading.Lock()


def parse_env_local(path: Path = ENV_LOCAL_PATH) -> Dict[str, str]:
    """Parse a .env file into a {key: value} dict.

    - Skips comment lines (starting with #) and blank lines.
    - Strips whitespace around keys and values.
    - Preserves equals signs inside values.
    - Returns {} if file does not exist.
    """
    if not path.exists():
        return {}

    result: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip()
    except Exception as exc:
        logger.warning(f"[env_keys] Failed to parse {path}: {exc}")
        return {}

    return result
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_env_keys.py::TestParseEnvLocal -v`
Expected: PASS (7 tests)

**Step 5: Commit**

```bash
git add backend/env_keys.py backend/tests/test_env_keys.py
git commit -m "feat(env-keys): add .env.local parser with comment preservation"
```

---

## Task 2: Backend — env_keys.py writer with backup

**Files:**
- Modify: `backend/env_keys.py`
- Modify: `backend/tests/test_env_keys.py`

**Step 1: Write the failing test**

Append to `backend/tests/test_env_keys.py`:

```python
class TestWriteEnvLocal:
    """write_env_local() writes keys to file, creating backup first."""

    def test_write_creates_file_if_missing(self, tmp_path):
        from backend.env_keys import write_env_local
        f = tmp_path / ".env.local"
        write_env_local({"HF_TOKEN": "hf_abc"}, path=f)
        assert f.exists()
        content = f.read_text(encoding="utf-8")
        assert "HF_TOKEN=hf_abc" in content

    def test_write_creates_backup_before_overwrite(self, tmp_path):
        from backend.env_keys import write_env_local
        f = tmp_path / ".env.local"
        f.write_text("OLD_KEY=old_value\n", encoding="utf-8")
        write_env_local({"NEW_KEY": "new_value"}, path=f)
        bak = tmp_path / ".env.local.bak"
        assert bak.exists()
        assert "OLD_KEY=old_value" in bak.read_text(encoding="utf-8")

    def test_write_preserves_comments_from_existing_file(self, tmp_path):
        """Comments in the existing file are carried into the backup, not the new file."""
        from backend.env_keys import write_env_local
        f = tmp_path / ".env.local"
        original = "# Picovoice key\nPICOVOICE_ACCESS_KEY=abc\n# HF key\nHF_TOKEN=def\n"
        f.write_text(original, encoding="utf-8")
        write_env_local({"PICOVOICE_ACCESS_KEY": "abc", "HF_TOKEN": "def"}, path=f)
        # New file should have the keys (comments are not preserved in new write —
        # they live in .env.example which is the schema source)
        content = f.read_text(encoding="utf-8")
        assert "PICOVOICE_ACCESS_KEY=abc" in content
        assert "HF_TOKEN=def" in content

    def test_write_is_atomic_via_lock(self, tmp_path):
        """write_env_local uses a threading lock — no exception under concurrent calls."""
        import threading
        from backend.env_keys import write_env_local
        f = tmp_path / ".env.local"
        errors = []

        def writer():
            try:
                write_env_local({"K": "v"}, path=f)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_env_keys.py::TestWriteEnvLocal -v`
Expected: FAIL with `ImportError: cannot import name 'write_env_local'`

**Step 3: Write minimal implementation**

Add to `backend/env_keys.py` (after `parse_env_local`):

```python
def write_env_local(keys: Dict[str, str], path: Path = ENV_LOCAL_PATH) -> None:
    """Write keys to .env.local, creating a backup first.

    - Acquires _write_lock to serialize concurrent writes.
    - Backs up existing file to <path>.bak before overwriting.
    - Writes in KEY=value format, one per line, sorted alphabetically.
    - Does NOT preserve comments (those live in .env.example).
    """
    with _write_lock:
        # Backup existing file
        if path.exists():
            bak_path = path.with_suffix(path.suffix + ".bak")
            try:
                bak_path.write_bytes(path.read_bytes())
            except Exception as exc:
                logger.warning(f"[env_keys] Backup failed: {exc}")

        # Write new content
        try:
            lines = [f"{k}={v}" for k, v in sorted(keys.items())]
            content = "\n".join(lines) + "\n" if lines else ""
            path.write_text(content, encoding="utf-8")
            logger.info(f"[env_keys] Wrote {len(keys)} keys to {path}")
        except Exception as exc:
            logger.error(f"[env_keys] Failed to write {path}: {exc}")
            raise
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_env_keys.py::TestWriteEnvLocal -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add backend/env_keys.py backend/tests/test_env_keys.py
git commit -m "feat(env-keys): add write_env_local with backup and file lock"
```

---

## Task 3: Backend — env_keys.py key masking

**Files:**
- Modify: `backend/env_keys.py`
- Modify: `backend/tests/test_env_keys.py`

**Step 1: Write the failing test**

Append to `backend/tests/test_env_keys.py`:

```python
class TestMaskKey:
    """mask_key() returns a redacted version safe for display/API responses."""

    def test_mask_long_key_shows_first3_and_last3(self):
        from backend.env_keys import mask_key
        assert mask_key("hf_TEST") == "hf_***"

    def test_mask_short_key_shows_only_stars(self):
        from backend.env_keys import mask_key
        assert mask_key("abc") == "***"

    def test_mask_empty_key_returns_empty(self):
        from backend.env_keys import mask_key
        assert mask_key("") == ""

    def test_mask_exact_6_chars(self):
        from backend.env_keys import mask_key
        assert mask_key("abcdef") == "abc***def"

    def test_mask_7_chars(self):
        from backend.env_keys import mask_key
        assert mask_key("abcdefg") == "abc***efg"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_env_keys.py::TestMaskKey -v`
Expected: FAIL with `ImportError: cannot import name 'mask_key'`

**Step 3: Write minimal implementation**

Add to `backend/env_keys.py`:

```python
def mask_key(value: str) -> str:
    """Return a masked version of a key safe for display.

    - Empty string → empty string
    - <= 6 chars → "***"
    - > 6 chars → first 3 + "***...***" + last 3
    """
    if not value:
        return ""
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***...***{value[-3:]}"
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_env_keys.py::TestMaskKey -v`
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add backend/env_keys.py backend/tests/test_env_keys.py
git commit -m "feat(env-keys): add mask_key for safe key display"
```

---

## Task 4: Backend — parse .env.example for known key schema

**Files:**
- Modify: `backend/env_keys.py`
- Modify: `backend/tests/test_env_keys.py`

**Step 1: Write the failing test**

Append to `backend/tests/test_env_keys.py`:

```python
class TestGetKnownKeys:
    """get_known_keys() parses .env.example to find documented keys."""

    def test_parses_keys_from_env_example(self, tmp_path):
        example = tmp_path / ".env.example"
        example.write_text(
            "# Picovoice (Porcupine wake word detection)\n"
            "# Get a free key at: https://console.picovoice.ai/\n"
            "PICOVOICE_ACCESS_KEY=your_picovoice_access_key_here\n"
            "\n"
            "# Hugging Face (model downloads)\n"
            "HF_TOKEN=your_huggingface_token_here\n",
            encoding="utf-8",
        )
        from backend.env_keys import get_known_keys
        result = get_known_keys(example)
        assert "PICOVOICE_ACCESS_KEY" in result
        assert "HF_TOKEN" in result

    def test_returns_help_url_from_comment(self, tmp_path):
        example = tmp_path / ".env.example"
        example.write_text(
            "# Picovoice (Porcupine wake word detection)\n"
            "# Get a free key at: https://console.picovoice.ai/\n"
            "PICOVOICE_ACCESS_KEY=your_picovoice_access_key_here\n",
            encoding="utf-8",
        )
        from backend.env_keys import get_known_keys
        result = get_known_keys(example)
        assert result["PICOVOICE_ACCESS_KEY"]["help_url"] == "https://console.picovoice.ai/"

    def test_returns_description_from_comment(self, tmp_path):
        example = tmp_path / ".env.example"
        example.write_text(
            "# Picovoice (Porcupine wake word detection)\n"
            "PICOVOICE_ACCESS_KEY=your_picovoice_access_key_here\n",
            encoding="utf-8",
        )
        from backend.env_keys import get_known_keys
        result = get_known_keys(example)
        assert "Picovoice" in result["PICOVOICE_ACCESS_KEY"]["description"]

    def test_missing_example_returns_empty(self, tmp_path):
        from backend.env_keys import get_known_keys
        result = get_known_keys(tmp_path / "nonexistent")
        assert result == {}
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_env_keys.py::TestGetKnownKeys -v`
Expected: FAIL with `ImportError: cannot import name 'get_known_keys'`

**Step 3: Write minimal implementation**

Add to `backend/env_keys.py`:

```python
import re

# Regex to find URLs in comment lines
_URL_RE = re.compile(r"https?://[^\s)]+")


def get_known_keys(path: Path = ENV_EXAMPLE_PATH) -> Dict[str, Dict[str, str]]:
    """Parse .env.example to extract known key definitions.

    Returns: { "KEY_NAME": { "description": str, "help_url": str | "" } }

    - Scans comment lines above each KEY= line for description and help URL.
    - Returns {} if file does not exist.
    """
    if not path.exists():
        return {}

    result: Dict[str, Dict[str, str]] = {}
    pending_comments: List[str] = []

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    pending_comments = []
                    continue
                if stripped.startswith("#"):
                    pending_comments.append(stripped.lstrip("#").strip())
                    continue
                if "=" in stripped:
                    key, _, _ = stripped.partition("=")
                    key = key.strip()
                    if key:
                        description = " ".join(pending_comments).strip()
                        url_match = _URL_RE.search(description)
                        help_url = url_match.group(0) if url_match else ""
                        # Clean description: remove the URL part
                        if help_url:
                            description = description.replace(help_url, "").strip()
                        result[key] = {
                            "description": description,
                            "help_url": help_url,
                        }
                    pending_comments = []
    except Exception as exc:
        logger.warning(f"[env_keys] Failed to parse known keys from {path}: {exc}")
        return {}

    return result
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_env_keys.py::TestGetKnownKeys -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add backend/env_keys.py backend/tests/test_env_keys.py
git commit -m "feat(env-keys): parse .env.example for known key schema with help URLs"
```

---

## Task 5: Backend — reload_env into os.environ

**Files:**
- Modify: `backend/env_keys.py`
- Modify: `backend/tests/test_env_keys.py`

**Step 1: Write the failing test**

Append to `backend/tests/test_env_keys.py`:

```python
class TestReloadEnv:
    """reload_env() re-runs load_dotenv with override=True on .env.local."""

    def test_reload_sets_env_var(self, tmp_path, monkeypatch):
        f = tmp_path / ".env.local"
        f.write_text("TEST_RELOAD_KEY=reload_value\n", encoding="utf-8")
        monkeypatch.delenv("TEST_RELOAD_KEY", raising=False)
        from backend.env_keys import reload_env
        reload_env(f)
        assert os.environ.get("TEST_RELOAD_KEY") == "reload_value"

    def test_reload_overrides_existing_env_var(self, tmp_path, monkeypatch):
        f = tmp_path / ".env.local"
        f.write_text("TEST_OVERRIDE_KEY=new_value\n", encoding="utf-8")
        monkeypatch.setenv("TEST_OVERRIDE_KEY", "old_value")
        from backend.env_keys import reload_env
        reload_env(f)
        assert os.environ.get("TEST_OVERRIDE_KEY") == "new_value"

    def test_reload_missing_file_does_not_raise(self, tmp_path, monkeypatch):
        from backend.env_keys import reload_env
        f = tmp_path / "nonexistent"
        # Should not raise
        reload_env(f)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_env_keys.py::TestReloadEnv -v`
Expected: FAIL with `ImportError: cannot import name 'reload_env'`

**Step 3: Write minimal implementation**

Add to `backend/env_keys.py`:

```python
def reload_env(path: Path = ENV_LOCAL_PATH) -> None:
    """Re-run load_dotenv on .env.local with override=True.

    This hot-reloads keys into os.environ without restarting the backend.
    Safe to call if file does not exist (load_dotenv handles missing files).
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=True)
        logger.info(f"[env_keys] Reloaded env from {path}")
    except Exception as exc:
        logger.warning(f"[env_keys] Failed to reload env from {path}: {exc}")
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_env_keys.py::TestReloadEnv -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add backend/env_keys.py backend/tests/test_env_keys.py
git commit -m "feat(env-keys): add reload_env for hot-reload without restart"
```

---

## Task 6: Backend — set_key and delete_key helpers

**Files:**
- Modify: `backend/env_keys.py`
- Modify: `backend/tests/test_env_keys.py`

**Step 1: Write the failing test**

Append to `backend/tests/test_env_keys.py`:

```python
class TestSetDeleteKey:
    """set_key and delete_key modify .env.local in place."""

    def test_set_key_adds_new_key(self, tmp_path):
        from backend.env_keys import set_key, parse_env_local
        f = tmp_path / ".env.local"
        f.write_text("EXISTING=val\n", encoding="utf-8")
        set_key("NEW_KEY", "new_val", path=f)
        result = parse_env_local(f)
        assert result["NEW_KEY"] == "new_val"
        assert result["EXISTING"] == "val"

    def test_set_key_updates_existing_key(self, tmp_path):
        from backend.env_keys import set_key, parse_env_local
        f = tmp_path / ".env.local"
        f.write_text("HF_TOKEN=old\n", encoding="utf-8")
        set_key("HF_TOKEN", "new", path=f)
        result = parse_env_local(f)
        assert result["HF_TOKEN"] == "new"

    def test_delete_key_removes_key(self, tmp_path):
        from backend.env_keys import delete_key, parse_env_local
        f = tmp_path / ".env.local"
        f.write_text("HF_TOKEN=val\nOTHER=val2\n", encoding="utf-8")
        delete_key("HF_TOKEN", path=f)
        result = parse_env_local(f)
        assert "HF_TOKEN" not in result
        assert result["OTHER"] == "val2"

    def test_delete_missing_key_does_not_raise(self, tmp_path):
        from backend.env_keys import delete_key
        f = tmp_path / ".env.local"
        f.write_text("OTHER=val\n", encoding="utf-8")
        # Should not raise
        delete_key("NONEXISTENT", path=f)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_env_keys.py::TestSetDeleteKey -v`
Expected: FAIL with `ImportError: cannot import name 'set_key'`

**Step 3: Write minimal implementation**

Add to `backend/env_keys.py`:

```python
def set_key(key: str, value: str, path: Path = ENV_LOCAL_PATH) -> None:
    """Add or update a single key in .env.local, preserving other keys.

    Reads existing keys, updates the one, writes all back (with backup).
    """
    keys = parse_env_local(path)
    keys[key] = value
    write_env_local(keys, path)


def delete_key(key: str, path: Path = ENV_LOCAL_PATH) -> None:
    """Remove a key from .env.local. No-op if key does not exist."""
    keys = parse_env_local(path)
    if key in keys:
        del keys[key]
        write_env_local(keys, path)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_env_keys.py::TestSetDeleteKey -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add backend/env_keys.py backend/tests/test_env_keys.py
git commit -m "feat(env-keys): add set_key and delete_key helpers"
```

---

## Task 7: Backend — FastAPI router for /api/env-keys

**Files:**
- Create: `backend/api/env_keys.py`
- Modify: `backend/main.py` (register router — after line 765)
- Test: `backend/tests/test_env_keys_api.py`

**Step 1: Write the failing test**

Create `backend/tests/test_env_keys_api.py`:

```python
"""
Integration tests for /api/env-keys FastAPI router.

Run: python -m pytest backend/tests/test_env_keys_api.py -v
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def env_local_tmp(tmp_path, monkeypatch):
    """Point env_keys module at a temp .env.local and .env.example."""
    env_local = tmp_path / ".env.local"
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "# Picovoice\n# Get key at: https://console.picovoice.ai/\n"
        "PICOVOICE_ACCESS_KEY=placeholder\n"
        "# Hugging Face\nHF_TOKEN=placeholder\n",
        encoding="utf-8",
    )
    import backend.env_keys as ek
    monkeypatch.setattr(ek, "ENV_LOCAL_PATH", env_local)
    monkeypatch.setattr(ek, "ENV_EXAMPLE_PATH", env_example)
    return env_local


@pytest.fixture
def client(env_local_tmp):
    """Create a TestClient with only the env_keys router (no full backend)."""
    from fastapi import FastAPI
    from backend.api.env_keys import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestGetEnvKeys:
    def test_get_returns_masked_keys(self, client, env_local_tmp):
        env_local_tmp.write_text("HF_TOKEN=hf_TEST\n", encoding="utf-8")
        resp = client.get("/api/env-keys")
        assert resp.status_code == 200
        data = resp.json()
        assert data["keys"]["HF_TOKEN"] == "hf_***...***xyz"

    def test_get_returns_known_key_schema(self, client):
        resp = client.get("/api/env-keys")
        data = resp.json()
        assert "PICOVOICE_ACCESS_KEY" in data["known_keys"]
        assert data["known_keys"]["PICOVOICE_ACCESS_KEY"]["help_url"] == "https://console.picovoice.ai/"

    def test_get_returns_configured_status(self, client, env_local_tmp):
        env_local_tmp.write_text("HF_TOKEN=hf_abc\n", encoding="utf-8")
        resp = client.get("/api/env-keys")
        data = resp.json()
        assert data["keys"]["HF_TOKEN"] != ""  # has a value


class TestPostEnvKey:
    def test_post_adds_key(self, client, env_local_tmp):
        resp = client.post("/api/env-keys", json={"key": "OPENAI_API_KEY", "value": "sk-test123"})
        assert resp.status_code == 200
        assert env_local_tmp.read_text(encoding="utf-8").strip() == "OPENAI_API_KEY=sk-test123"

    def test_post_does_not_return_value(self, client, env_local_tmp):
        resp = client.post("/api/env-keys", json={"key": "OPENAI_API_KEY", "value": "sk-secret"})
        data = resp.json()
        assert "value" not in data  # never echo the value back

    def test_post_updates_existing_key(self, client, env_local_tmp):
        env_local_tmp.write_text("HF_TOKEN=old\n", encoding="utf-8")
        resp = client.post("/api/env-keys", json={"key": "HF_TOKEN", "value": "new"})
        assert resp.status_code == 200
        from backend.env_keys import parse_env_local
        assert parse_env_local(env_local_tmp)["HF_TOKEN"] == "new"

    def test_post_empty_key_returns_400(self, client):
        resp = client.post("/api/env-keys", json={"key": "", "value": "val"})
        assert resp.status_code == 400


class TestDeleteEnvKey:
    def test_delete_removes_key(self, client, env_local_tmp):
        env_local_tmp.write_text("HF_TOKEN=val\nOTHER=val2\n", encoding="utf-8")
        resp = client.delete("/api/env-keys/HF_TOKEN")
        assert resp.status_code == 200
        from backend.env_keys import parse_env_local
        assert "HF_TOKEN" not in parse_env_local(env_local_tmp)

    def test_delete_missing_key_returns_200(self, client):
        resp = client.delete("/api/env-keys/NONEXISTENT")
        assert resp.status_code == 200  # idempotent


class TestReloadEnvKeys:
    def test_reload_returns_ok(self, client, env_local_tmp):
        env_local_tmp.write_text("TEST_KEY=val\n", encoding="utf-8")
        resp = client.post("/api/env-keys/reload")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert os.environ.get("TEST_KEY") == "val"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_env_keys_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.api.env_keys'`

**Step 3: Write minimal implementation**

Create `backend/api/env_keys.py`:

```python
"""
FastAPI router for .env.local API key management.

Endpoints:
  GET    /api/env-keys          — list all keys (masked) + known key schema
  POST   /api/env-keys          — add/update a key  {key, value}
  DELETE /api/env-keys/{key}    — remove a key
  POST   /api/env-keys/reload   — hot-reload .env.local into os.environ
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any

from backend.env_keys import (
    parse_env_local,
    set_key,
    delete_key,
    mask_key,
    get_known_keys,
    reload_env,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/env-keys", tags=["env-keys"])


class SetKeyRequest(BaseModel):
    key: str
    value: str


@router.get("")
async def list_env_keys() -> Dict[str, Any]:
    """Return all keys (masked) and the known-key schema from .env.example."""
    raw = parse_env_local()
    masked = {k: mask_key(v) for k, v in raw.items()}
    known = get_known_keys()
    return {
        "keys": masked,
        "known_keys": known,
    }


@router.post("")
async def set_env_key(req: SetKeyRequest) -> Dict[str, Any]:
    """Add or update a key in .env.local. Never echoes the value back."""
    if not req.key.strip():
        raise HTTPException(status_code=400, detail="key is required")
    try:
        set_key(req.key.strip(), req.value)
        return {"status": "ok", "key": req.key.strip()}
    except Exception as exc:
        logger.error(f"[env-keys] POST failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{key}")
async def remove_env_key(key: str) -> Dict[str, Any]:
    """Remove a key from .env.local. Idempotent — 200 even if key missing."""
    try:
        delete_key(key)
        return {"status": "ok", "key": key}
    except Exception as exc:
        logger.error(f"[env-keys] DELETE failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/reload")
async def reload_env_keys() -> Dict[str, Any]:
    """Hot-reload .env.local into os.environ without backend restart."""
    try:
        reload_env()
        return {"status": "ok"}
    except Exception as exc:
        logger.error(f"[env-keys] reload failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
```

**Step 4: Register router in main.py**

In `backend/main.py`, after line 765 (`app.include_router(chat_router)`), add:

```python
from backend.api.env_keys import router as env_keys_router
app.include_router(env_keys_router)
```

**Step 5: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_env_keys_api.py -v`
Expected: PASS (9 tests)

**Step 6: Commit**

```bash
git add backend/api/env_keys.py backend/tests/test_env_keys_api.py backend/main.py
git commit -m "feat(env-keys): add FastAPI router for /api/env-keys CRUD + reload"
```

---

## Task 8: Backend — fix porcupine_detector.py dotenv bug

**Files:**
- Modify: `backend/voice/porcupine_detector.py:13,18`

**Step 1: Write the failing test**

Append to `backend/tests/test_env_keys.py`:

```python
class TestPorcupineDotenvFix:
    """porcupine_detector should NOT call bare load_dotenv() — start-backend.py
    already loads .env.local with the correct path. A bare load_dotenv() only
    loads .env (not .env.local), so PICOVOICE_ACCESS_KEY would be missing.
    """

    def test_porcupine_detector_does_not_call_bare_load_dotenv(self):
        """The module should not call load_dotenv() with no path argument."""
        import inspect
        import backend.voice.porcupine_detector as mod
        source = inspect.getsource(mod)
        # The bare call "load_dotenv()" (no args) should be removed.
        # We allow load_dotenv with an explicit path argument.
        lines = source.split("\n")
        bare_calls = [l for l in lines if "load_dotenv()" in l and "load_dotenv(" in l]
        assert bare_calls == [], f"Found bare load_dotenv() calls: {bare_calls}"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_env_keys.py::TestPorcupineDotenvFix -v`
Expected: FAIL — the source contains `load_dotenv()` on line 18

**Step 3: Fix the code**

In `backend/voice/porcupine_detector.py`:

Remove line 13: `from dotenv import load_dotenv`
Remove line 18: `load_dotenv()`

The module already reads `os.getenv("PICOVOICE_ACCESS_KEY")` on line 79, and `start-backend.py` loads `.env.local` before the backend starts. The bare `load_dotenv()` was loading only `.env` (not `.env.local`), which is a bug.

**Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_env_keys.py::TestPorcupineDotenvFix -v`
Expected: PASS

**Step 5: Run existing porcupine tests to verify no regression**

Run: `python -m pytest backend/tests/test_domain2_voice.py::TestPorcupineGracefulDisable -v`
Expected: PASS (2 tests)

**Step 6: Commit**

```bash
git add backend/voice/porcupine_detector.py backend/tests/test_env_keys.py
git commit -m "fix(porcupine): remove bare load_dotenv() — start-backend.py loads .env.local"
```

---

## Task 9: Tauri — add filesystem commands for .env.local fallback

**Files:**
- Modify: `iris-launcher/src-tauri/Cargo.toml`
- Modify: `iris-launcher/src-tauri/src/main.rs`
- Modify: `iris-launcher/src-tauri/tauri.conf.json`

**Step 1: Add fs plugin dependency**

In `iris-launcher/src-tauri/Cargo.toml`, add to `[dependencies]`:

```toml
tauri-plugin-fs = "2"
```

**Step 2: Update tauri.conf.json to grant fs scope**

In `iris-launcher/src-tauri/tauri.conf.json`, add a `plugins` section inside `app`:

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "IRIS Launcher",
  "version": "0.1.0",
  "identifier": "com.iris.launcher",
  "build": {
    "beforeBuildCommand": "npm run build",
    "beforeDevCommand": "npm run dev",
    "devUrl": "http://localhost:8080",
    "frontendDist": "../dist"
  },
  "app": {
    "windows": [
      {
        "label": "main",
        "title": "IRIS Launcher",
        "width": 1100,
        "height": 720,
        "minWidth": 900,
        "minHeight": 600,
        "resizable": true,
        "maximizable": true,
        "decorations": true,
        "transparent": false,
        "alwaysOnTop": false,
        "center": true,
        "visible": true
      }
    ],
    "security": {
      "csp": null
    },
    "trayIcon": {
      "iconPath": "icons/icon.png",
      "iconAsTemplate": true
    }
  },
  "bundle": {
    "active": true,
    "targets": ["deb", "appimage"],
    "icon": [
      "icons/32x32.png",
      "icons/128x128.png",
      "icons/128x128@2x.png",
      "icons/icon.icns",
      "icons/icon.ico"
    ]
  },
  "plugins": {
    "fs": {
      "scope": ["$RESOURCE/.env.local", "$RESOURCE/.env.example", "$RESOURCE/../.env.local", "$RESOURCE/../.env.example"]
    }
  }
}
```

**Step 3: Add Rust commands for reading/writing .env.local**

Replace `iris-launcher/src-tauri/src/main.rs` with:

```rust
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs;
use std::path::PathBuf;
use tauri::Manager;

/// Resolve the IRISVOICE repo root (parent of the launcher directory).
/// In dev: the launcher runs from iris-launcher/src-tauri/, so root is 3 levels up.
/// In production: we fall back to the resource directory parent.
fn resolve_iris_root(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    // Try resource dir first (production)
    if let Ok(resource) = app.path().resource_dir() {
        let candidate = resource.parent()
            .map(|p| p.to_path_buf())
            .unwrap_or(resource);
        if candidate.join(".env.local").exists() || candidate.join(".env.example").exists() {
            return Ok(candidate);
        }
    }

    // Dev fallback: walk up from current dir until we find .env.example
    let mut current = std::env::current_dir().map_err(|e| e.to_string())?;
    for _ in 0..5 {
        if current.join(".env.example").exists() {
            return Ok(current);
        }
        if !current.pop() {
            break;
        }
    }
    Err("Could not locate IRISVOICE root (no .env.example found)".to_string())
}

#[tauri::command]
fn read_env_local(app: tauri::AppHandle) -> Result<String, String> {
    let root = resolve_iris_root(&app)?;
    let path = root.join(".env.local");
    if !path.exists() {
        return Ok(String::new());
    }
    fs::read_to_string(&path).map_err(|e| format!("Failed to read .env.local: {}", e))
}

#[tauri::command]
fn write_env_local(app: tauri::AppHandle, content: String) -> Result<(), String> {
    let root = resolve_iris_root(&app)?;
    let path = root.join(".env.local");

    // Backup before write
    if path.exists() {
        let bak = root.join(".env.local.bak");
        let _ = fs::copy(&path, &bak);
    }

    fs::write(&path, content).map_err(|e| format!("Failed to write .env.local: {}", e))
}

#[tauri::command]
fn get_iris_root(app: tauri::AppHandle) -> Result<String, String> {
    let root = resolve_iris_root(&app)?;
    root.to_str().map(|s| s.to_string()).ok_or("Invalid path".to_string())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_fs::init())
        .invoke_handler(tauri::generate_handler![
            read_env_local,
            write_env_local,
            get_iris_root
        ])
        .build(tauri::generate_context!())
        .expect("error while building IRIS Launcher")
        .run(|_app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {}
        });
}
```

**Step 4: Verify it compiles**

Run: `cd iris-launcher && npm run tauri build -- --debug` (or `npm run tauri dev` to test in dev)
Expected: Compiles without errors. If `tauri-plugin-fs` is not found, run `cargo update` in `src-tauri/`.

**Step 5: Commit**

```bash
git add iris-launcher/src-tauri/Cargo.toml iris-launcher/src-tauri/src/main.rs iris-launcher/src-tauri/tauri.conf.json
git commit -m "feat(tauri): add fs commands for .env.local read/write fallback"
```

---

## Task 10: Launcher — extend iris-api.ts with env key methods

**Files:**
- Modify: `iris-launcher/src/lib/iris-api.ts`

**Step 1: Add env key types and methods**

Add to `iris-launcher/src/lib/iris-api.ts` (before the final `export const irisApi`):

```typescript
// ── Env Keys (.env.local management) ────────────────────────────────────────

export interface EnvKeyKnown {
  description: string;
  help_url: string;
}

export interface EnvKeysResponse {
  keys: Record<string, string>;        // masked values, e.g. "hf_***...***dQp"
  known_keys: Record<string, EnvKeyKnown>;
}
```

Add to the `irisApi` object (before the closing `}`):

```typescript
  // ── Env Keys (.env.local) ────────────────────────────────────────────────
  getEnvKeys: () =>
    apiFetch<EnvKeysResponse>("/api/env-keys"),

  setEnvKey: (key: string, value: string) =>
    apiFetch<{ status: string; key: string }>("/api/env-keys", {
      method: "POST",
      body: JSON.stringify({ key, value }),
    }),

  deleteEnvKey: (key: string) =>
    apiFetch<{ status: string; key: string }>(`/api/env-keys/${encodeURIComponent(key)}`, {
      method: "DELETE",
    }),

  reloadEnvKeys: () =>
    apiFetch<{ status: string }>("/api/env-keys/reload", {
      method: "POST",
    }),
```

**Step 2: Verify TypeScript compiles**

Run: `cd iris-launcher && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add iris-launcher/src/lib/iris-api.ts
git commit -m "feat(launcher): add env key API methods to iris-api client"
```

---

## Task 11: Launcher — use-env-keys hook with Tauri fallback

**Files:**
- Create: `iris-launcher/src/hooks/use-env-keys.ts`

**Step 1: Write the hook**

Create `iris-launcher/src/hooks/use-env-keys.ts`:

```typescript
/**
 * useEnvKeys — read/write .env.local API keys with Tauri fallback.
 *
 * Primary path: backend /api/env-keys (when backend is running).
 * Fallback path: Tauri fs commands (when backend is down — first-run scenario).
 *
 * Usage:
 *   const { keys, knownKeys, loading, saveKey, deleteKey, reload } = useEnvKeys();
 */

import { useState, useEffect, useCallback } from "react";
import { irisApi, EnvKeysResponse } from "@/lib/iris-api";

// Tauri invoke — only available in Tauri runtime, not in browser dev mode.
// Dynamic import so Vite doesn't try to bundle @tauri-apps/api in browser.
async function tauriInvoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    return await invoke<T>(cmd, args);
  } catch {
    throw new Error(`Tauri command '${cmd}' unavailable (running in browser?)`);
  }
}

// Parse .env.local raw text into {key: value} — mirrors backend parse_env_local.
function parseEnvText(text: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    if (!trimmed.includes("=")) continue;
    const [key, ...rest] = trimmed.split("=");
    result[key.trim()] = rest.join("=").trim();
  }
  return result;
}

function maskKey(value: string): string {
  if (!value) return "";
  if (value.length <= 6) return "***";
  return `${value.slice(0, 3)}***...***${value.slice(-3)}`;
}

export function useEnvKeys() {
  const [keys, setKeys] = useState<Record<string, string>>({});       // masked
  const [knownKeys, setKnownKeys] = useState<Record<string, { description: string; help_url: string }>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [usingTauri, setUsingTauri] = useState(false);

  const fetchKeys = useCallback(async () => {
    setLoading(true);
    setError(null);

    // Try backend first
    try {
      const data = await irisApi.getEnvKeys();
      setKeys(data.keys);
      setKnownKeys(data.known_keys);
      setUsingTauri(false);
      return;
    } catch {
      // Backend down — fall through to Tauri
    }

    // Fallback: Tauri fs
    try {
      const raw = await tauriInvoke<string>("read_env_local");
      const parsed = parseEnvText(raw);
      const masked = Object.fromEntries(
        Object.entries(parsed).map(([k, v]) => [k, maskKey(v)])
      );
      setKeys(masked);
      setKnownKeys({});  // no known-key schema in Tauri fallback
      setUsingTauri(true);
    } catch (err) {
      setError(String(err));
      setKeys({});
      setKnownKeys({});
    }
  }, []);

  useEffect(() => {
    fetchKeys();
  }, [fetchKeys]);

  const saveKey = useCallback(async (key: string, value: string): Promise<void> => {
    if (!usingTauri) {
      await irisApi.setEnvKey(key, value);
      await fetchKeys();  // refresh masked display
      return;
    }

    // Tauri fallback: read, update, write
    const raw = await tauriInvoke<string>("read_env_local");
    const parsed = parseEnvText(raw);
    parsed[key] = value;
    const content = Object.entries(parsed)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => `${k}=${v}`)
      .join("\n") + "\n";
    await tauriInvoke<void>("write_env_local", { content });
    await fetchKeys();
  }, [usingTauri, fetchKeys]);

  const deleteKey = useCallback(async (key: string): Promise<void> => {
    if (!usingTauri) {
      await irisApi.deleteEnvKey(key);
      await fetchKeys();
      return;
    }

    const raw = await tauriInvoke<string>("read_env_local");
    const parsed = parseEnvText(raw);
    delete parsed[key];
    const content = Object.entries(parsed)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => `${k}=${v}`)
      .join("\n") + "\n";
    await tauriInvoke<void>("write_env_local", { content });
    await fetchKeys();
  }, [usingTauri, fetchKeys]);

  const reload = useCallback(async (): Promise<void> => {
    if (!usingTauri) {
      await irisApi.reloadEnvKeys();
    }
    // Tauri fallback: no reload needed (backend will load on next start)
  }, [usingTauri]);

  return {
    keys,
    knownKeys,
    loading,
    error,
    usingTauri,
    saveKey,
    deleteKey,
    reload,
    refresh: fetchKeys,
  };
}
```

**Step 2: Verify TypeScript compiles**

Run: `cd iris-launcher && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add iris-launcher/src/hooks/use-env-keys.ts
git commit -m "feat(launcher): add useEnvKeys hook with Tauri fallback"
```

---

## Task 12: Launcher — ConfigPage (first-run API key setup)

**Files:**
- Create: `iris-launcher/src/pages/ConfigPage.tsx`

**Step 1: Write the page**

Create `iris-launcher/src/pages/ConfigPage.tsx`:

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Key, Plus, Trash2, ExternalLink, CheckCircle, Loader2, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LiquidIcon } from "@/components/dashboard/LiquidIcon";
import { useEnvKeys } from "@/hooks/use-env-keys";
import { useApp } from "@/contexts/AppContext";
import { toast } from "@/hooks/use-toast";

const ConfigPage = () => {
  const navigate = useNavigate();
  const { setEnvKeysConfigured } = useApp();
  const { keys, knownKeys, loading, usingTauri, saveKey, deleteKey, reload } = useEnvKeys();

  // Track which known keys are being edited
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState<string | null>(null);

  // Custom key form
  const [customKeyName, setCustomKeyName] = useState("");
  const [customKeyValue, setCustomKeyValue] = useState("");

  const knownKeyNames = Object.keys(knownKeys);
  const customKeyNames = Object.keys(keys).filter((k) => !knownKeys[k]);

  const handleSaveKnown = async (keyName: string) => {
    if (!editValue.trim()) {
      toast({ title: "Value required", variant: "destructive" });
      return;
    }
    setSaving(keyName);
    try {
      await saveKey(keyName, editValue.trim());
      await reload();
      setEditingKey(null);
      setEditValue("");
      toast({ title: `${keyName} saved` });
    } catch (err) {
      toast({ title: "Save failed", description: String(err), variant: "destructive" });
    } finally {
      setSaving(null);
    }
  };

  const handleAddCustom = async () => {
    const name = customKeyName.trim().toUpperCase().replace(/\s/g, "_");
    if (!name || !customKeyValue.trim()) {
      toast({ title: "Key name and value required", variant: "destructive" });
      return;
    }
    setSaving(name);
    try {
      await saveKey(name, customKeyValue.trim());
      await reload();
      setCustomKeyName("");
      setCustomKeyValue("");
      toast({ title: `${name} added` });
    } catch (err) {
      toast({ title: "Add failed", description: String(err), variant: "destructive" });
    } finally {
      setSaving(null);
    }
  };

  const handleDelete = async (keyName: string) => {
    setSaving(keyName);
    try {
      await deleteKey(keyName);
      toast({ title: `${keyName} removed` });
    } catch (err) {
      toast({ title: "Delete failed", description: String(err), variant: "destructive" });
    } finally {
      setSaving(null);
    }
  };

  const handleContinue = () => {
    setEnvKeysConfigured(true);
    navigate("/mode-select");
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <motion.div
        className="w-full max-w-2xl"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        {/* Header */}
        <div className="text-center mb-8">
          <div className="flex justify-center mb-4">
            <LiquidIcon color="primary" size="lg" bounce>
              <Key className="h-6 w-6" />
            </LiquidIcon>
          </div>
          <h1 className="text-xl font-bold text-foreground mb-2">API Key Configuration</h1>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            Configure the API keys IRIS needs. Keys are stored locally in{" "}
            <code className="text-xs font-mono text-primary">.env.local</code> and never leave this machine.
          </p>
          {usingTauri && (
            <div className="mt-3 inline-flex items-center gap-2 text-xs font-mono text-warning bg-warning/10 rounded-lg px-3 py-1.5">
              <AlertTriangle className="h-3 w-3" />
              Backend offline — using local file mode
            </div>
          )}
        </div>

        {/* Known Keys */}
        {knownKeyNames.length > 0 && (
          <div className="space-y-4 mb-8">
            <h2 className="text-xs font-mono uppercase tracking-[0.2em] text-muted-foreground">
              Required Keys
            </h2>
            {knownKeyNames.map((keyName) => {
              const known = knownKeys[keyName];
              const currentValue = keys[keyName];
              const isConfigured = currentValue && currentValue !== "";
              const isEditing = editingKey === keyName;
              const isSaving = saving === keyName;

              return (
                <div key={keyName} className="glass-card rounded-xl p-4 space-y-3">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-mono font-semibold text-foreground">{keyName}</span>
                        {isConfigured && (
                          <CheckCircle className="h-3.5 w-3.5 text-success" />
                        )}
                      </div>
                      {known.description && (
                        <p className="text-xs text-muted-foreground mt-0.5">{known.description}</p>
                      )}
                      {known.help_url && (
                        <a
                          href={known.help_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-primary hover:underline mt-1"
                        >
                          Get key <ExternalLink className="h-3 w-3" />
                        </a>
                      )}
                    </div>
                    {isConfigured && !isEditing && (
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono text-muted-foreground">{currentValue}</span>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={isSaving}
                          onClick={() => { setEditingKey(keyName); setEditValue(""); }}
                        >
                          Edit
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={isSaving}
                          onClick={() => handleDelete(keyName)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    )}
                  </div>

                  {(!isConfigured || isEditing) && (
                    <div className="flex items-center gap-2">
                      <Input
                        type="password"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        placeholder={isConfigured ? "Enter new value to replace" : "Enter key value"}
                        className="font-mono glass-subtle border-0"
                        onKeyDown={(e) => e.key === "Enter" && handleSaveKnown(keyName)}
                      />
                      <Button
                        size="sm"
                        disabled={isSaving || !editValue.trim()}
                        onClick={() => handleSaveKnown(keyName)}
                      >
                        {isSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save"}
                      </Button>
                      {isEditing && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => { setEditingKey(null); setEditValue(""); }}
                        >
                          Cancel
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Custom Keys */}
        <div className="space-y-4 mb-8">
          <h2 className="text-xs font-mono uppercase tracking-[0.2em] text-muted-foreground">
            Custom Keys
          </h2>

          {/* Add custom key form */}
          <div className="glass-card rounded-xl p-4 space-y-3">
            <div className="flex items-center gap-2">
              <Input
                value={customKeyName}
                onChange={(e) => setCustomKeyName(e.target.value)}
                placeholder="KEY_NAME (e.g. OPENAI_API_KEY)"
                className="font-mono glass-subtle border-0"
              />
              <Input
                type="password"
                value={customKeyValue}
                onChange={(e) => setCustomKeyValue(e.target.value)}
                placeholder="Value"
                className="font-mono glass-subtle border-0"
              />
              <Button
                size="sm"
                disabled={saving !== null || !customKeyName.trim() || !customKeyValue.trim()}
                onClick={handleAddCustom}
              >
                {saving && saving !== customKeyName.toUpperCase() ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Plus className="h-3.5 w-3.5" />
                )}
              </Button>
            </div>
          </div>

          {/* List existing custom keys */}
          {customKeyNames.map((keyName) => {
            const isSaving = saving === keyName;
            return (
              <div key={keyName} className="glass-card rounded-xl p-4 flex items-center justify-between">
                <div>
                  <span className="text-sm font-mono font-semibold text-foreground">{keyName}</span>
                  <span className="ml-3 text-xs font-mono text-muted-foreground">{keys[keyName]}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Button variant="ghost" size="sm" disabled={isSaving} onClick={() => { setEditingKey(keyName); setEditValue(""); }}>
                    Edit
                  </Button>
                  <Button variant="ghost" size="sm" disabled={isSaving} onClick={() => handleDelete(keyName)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            );
          })}
        </div>

        {/* Continue */}
        <div className="flex items-center justify-between">
          <Button variant="ghost" onClick={handleContinue}>
            Skip for now
          </Button>
          <Button onClick={handleContinue}>
            Continue
          </Button>
        </div>
      </motion.div>
    </div>
  );
};

export default ConfigPage;
```

**Step 2: Verify TypeScript compiles**

Run: `cd iris-launcher && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add iris-launcher/src/pages/ConfigPage.tsx
git commit -m "feat(launcher): add ConfigPage for first-run API key setup"
```

---

## Task 13: Launcher — SettingsPage (dashboard config editor)

**Files:**
- Create: `iris-launcher/src/pages/SettingsPage.tsx`

**Step 1: Write the page**

Create `iris-launcher/src/pages/SettingsPage.tsx`:

```tsx
import { useState } from "react";
import { motion } from "framer-motion";
import { Key, Plus, Trash2, ExternalLink, CheckCircle, Loader2, RefreshCw, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SectionHeader } from "@/components/dashboard/DashboardPrimitives";
import { LiquidIcon } from "@/components/dashboard/LiquidIcon";
import { PageTransition } from "@/components/dashboard/PageTransition";
import { useEnvKeys } from "@/hooks/use-env-keys";
import { toast } from "@/hooks/use-toast";

const SettingsPage = () => {
  const { keys, knownKeys, loading, usingTauri, error, saveKey, deleteKey, reload, refresh } = useEnvKeys();

  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState<string | null>(null);
  const [reloading, setReloading] = useState(false);

  const [customKeyName, setCustomKeyName] = useState("");
  const [customKeyValue, setCustomKeyValue] = useState("");

  const knownKeyNames = Object.keys(knownKeys);
  const customKeyNames = Object.keys(keys).filter((k) => !knownKeys[k]);

  const handleSaveKnown = async (keyName: string) => {
    if (!editValue.trim()) return;
    setSaving(keyName);
    try {
      await saveKey(keyName, editValue.trim());
      await reload();
      setEditingKey(null);
      setEditValue("");
      toast({ title: `${keyName} saved`, description: "Backend reloaded." });
    } catch (err) {
      toast({ title: "Save failed", description: String(err), variant: "destructive" });
    } finally {
      setSaving(null);
    }
  };

  const handleAddCustom = async () => {
    const name = customKeyName.trim().toUpperCase().replace(/\s/g, "_");
    if (!name || !customKeyValue.trim()) return;
    setSaving(name);
    try {
      await saveKey(name, customKeyValue.trim());
      await reload();
      setCustomKeyName("");
      setCustomKeyValue("");
      toast({ title: `${name} added` });
    } catch (err) {
      toast({ title: "Add failed", description: String(err), variant: "destructive" });
    } finally {
      setSaving(null);
    }
  };

  const handleDelete = async (keyName: string) => {
    setSaving(keyName);
    try {
      await deleteKey(keyName);
      toast({ title: `${keyName} removed` });
    } catch (err) {
      toast({ title: "Delete failed", description: String(err), variant: "destructive" });
    } finally {
      setSaving(null);
    }
  };

  const handleReload = async () => {
    setReloading(true);
    try {
      await reload();
      await refresh();
      toast({ title: "Backend reloaded", description: "All keys hot-reloaded into os.environ." });
    } catch (err) {
      toast({ title: "Reload failed", description: String(err), variant: "destructive" });
    } finally {
      setReloading(false);
    }
  };

  const renderKeyRow = (keyName: string, description?: string, helpUrl?: string) => {
    const currentValue = keys[keyName];
    const isConfigured = currentValue && currentValue !== "";
    const isEditing = editingKey === keyName;
    const isSaving = saving === keyName;

    return (
      <div key={keyName} className="glass-card rounded-xl p-4 space-y-3">
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-mono font-semibold text-foreground">{keyName}</span>
              {isConfigured && <CheckCircle className="h-3.5 w-3.5 text-success" />}
            </div>
            {description && <p className="text-xs text-muted-foreground mt-0.5">{description}</p>}
            {helpUrl && (
              <a href={helpUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-primary hover:underline mt-1">
                Get key <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
          {isConfigured && !isEditing && (
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-muted-foreground">{currentValue}</span>
              <Button variant="ghost" size="sm" disabled={isSaving} onClick={() => { setEditingKey(keyName); setEditValue(""); }}>Edit</Button>
              <Button variant="ghost" size="sm" disabled={isSaving} onClick={() => handleDelete(keyName)}><Trash2 className="h-3.5 w-3.5" /></Button>
            </div>
          )}
        </div>
        {(!isConfigured || isEditing) && (
          <div className="flex items-center gap-2">
            <Input
              type="password"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              placeholder={isConfigured ? "Enter new value to replace" : "Enter key value"}
              className="font-mono glass-subtle border-0"
              onKeyDown={(e) => e.key === "Enter" && handleSaveKnown(keyName)}
            />
            <Button size="sm" disabled={isSaving || !editValue.trim()} onClick={() => handleSaveKnown(keyName)}>
              {isSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save"}
            </Button>
            {isEditing && <Button variant="ghost" size="sm" onClick={() => { setEditingKey(null); setEditValue(""); }}>Cancel</Button>}
          </div>
        )}
      </div>
    );
  };

  return (
    <PageTransition variant="blur">
      <div className="space-y-8">
        <SectionHeader
          title="API Keys"
          description="Manage keys stored in .env.local"
          action={
            <Button variant="ghost" size="sm" disabled={reloading || usingTauri} onClick={handleReload}>
              {reloading ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <RefreshCw className="h-3.5 w-3.5 mr-1" />}
              Reload Backend
            </Button>
          }
        />

        {usingTauri && (
          <div className="glass-card rounded-xl p-4 flex items-center gap-3 border-warning/30">
            <AlertTriangle className="h-4 w-4 text-warning shrink-0" />
            <div className="text-xs text-muted-foreground">
              Backend is offline. Keys are being written directly to <code className="font-mono text-warning">.env.local</code>.
              Start the backend and click "Reload Backend" to apply.
            </div>
          </div>
        )}

        {error && (
          <div className="glass-card rounded-xl p-4 flex items-center gap-3 border-destructive/30">
            <AlertTriangle className="h-4 w-4 text-destructive shrink-0" />
            <div className="text-xs text-destructive font-mono">{error}</div>
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : (
          <motion.div className="space-y-8" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            {/* Known Keys */}
            {knownKeyNames.length > 0 && (
              <div className="space-y-4">
                <h2 className="text-xs font-mono uppercase tracking-[0.2em] text-muted-foreground">Known Keys</h2>
                {knownKeyNames.map((k) => renderKeyRow(k, knownKeys[k].description, knownKeys[k].help_url))}
              </div>
            )}

            {/* Custom Keys */}
            <div className="space-y-4">
              <h2 className="text-xs font-mono uppercase tracking-[0.2em] text-muted-foreground">Custom Keys</h2>
              <div className="glass-card rounded-xl p-4">
                <div className="flex items-center gap-2">
                  <Input value={customKeyName} onChange={(e) => setCustomKeyName(e.target.value)} placeholder="KEY_NAME" className="font-mono glass-subtle border-0" />
                  <Input type="password" value={customKeyValue} onChange={(e) => setCustomKeyValue(e.target.value)} placeholder="Value" className="font-mono glass-subtle border-0" />
                  <Button size="sm" disabled={saving !== null || !customKeyName.trim() || !customKeyValue.trim()} onClick={handleAddCustom}>
                    <Plus className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
              {customKeyNames.map((k) => renderKeyRow(k))}
            </div>
          </motion.div>
        )}
      </div>
    </PageTransition>
  );
};

export default SettingsPage;
```

**Step 2: Verify TypeScript compiles**

Run: `cd iris-launcher && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add iris-launcher/src/pages/SettingsPage.tsx
git commit -m "feat(launcher): add SettingsPage for dashboard API key management"
```

---

## Task 14: Launcher — extend AppContext with envKeysConfigured flag

**Files:**
- Modify: `iris-launcher/src/contexts/AppContext.tsx`

**Step 1: Add envKeysConfigured state**

In `iris-launcher/src/contexts/AppContext.tsx`:

Add to `AppContextType` interface (after `isHydrated: boolean;`):

```typescript
  envKeysConfigured: boolean;
  setEnvKeysConfigured: (configured: boolean) => void;
```

Add state inside `AppProvider` (after `const [isHydrated, setIsHydrated] = useState<boolean>(false);`):

```typescript
  const [envKeysConfigured, setEnvKeysConfiguredState] = useState<boolean>(false);
```

Add to the hydration `useEffect` (after the GitHub hydration block, before `setIsHydrated(true);`):

```typescript
    try {
      const storedEnvConfigured = localStorage.getItem("iris-env-keys-configured") === "true";
      setEnvKeysConfiguredState(storedEnvConfigured);
    } catch {
      // Corrupt entry — ignore and keep false
    }
```

Add the setter callback (after `setGitHubConnected`):

```typescript
  const setEnvKeysConfigured = useCallback((configured: boolean) => {
    setEnvKeysConfiguredState(configured);
    if (configured) {
      localStorage.setItem("iris-env-keys-configured", "true");
    } else {
      localStorage.removeItem("iris-env-keys-configured");
    }
  }, []);
```

Add to the Provider value (add `envKeysConfigured, setEnvKeysConfigured,` to the value object):

```typescript
  return (
    <AppContext.Provider value={{
      identity, setIdentity, mode, setMode, clearIdentity,
      gitHubConnected, setGitHubConnected,
      envKeysConfigured, setEnvKeysConfigured,
      isHydrated
    }}>
      {children}
    </AppContext.Provider>
  );
```

**Step 2: Verify TypeScript compiles**

Run: `cd iris-launcher && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add iris-launcher/src/contexts/AppContext.tsx
git commit -m "feat(launcher): add envKeysConfigured flag to AppContext"
```

---

## Task 15: Launcher — update App.tsx routing with config gate

**Files:**
- Modify: `iris-launcher/src/App.tsx`

**Step 1: Update routing logic**

In `iris-launcher/src/App.tsx`:

Add import (after `import ModeSelectPage from "./pages/ModeSelectPage";`):

```typescript
import ConfigPage from "./pages/ConfigPage";
```

Update `AppRoutes` to add the config gate. Replace the `return` block inside `AppRoutes` with:

```typescript
  return (
    <Routes>
      <Route path="/config" element={<ConfigPage />} />
      <Route path="/first-run" element={<div className="min-h-screen"><FirstRunPage /></div>} />
      <Route path="/mode-select" element={<ModeSelectPage />} />
      <Route
        path="*"
        element={
          !envKeysConfigured ? <Navigate to="/config" replace /> :
          mode ? <DashboardLayout /> : <Navigate to="/mode-select" replace />
        }
      />
    </Routes>
  );
```

Update the `useApp` destructure in `AppRoutes` to include `envKeysConfigured`:

```typescript
  const { mode, isHydrated, envKeysConfigured } = useApp();
```

**Step 2: Verify TypeScript compiles**

Run: `cd iris-launcher && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add iris-launcher/src/App.tsx
git commit -m "feat(launcher): add /config route gate before mode-select"
```

---

## Task 16: Launcher — add Settings route + sidebar link

**Files:**
- Modify: `iris-launcher/src/components/AnimatedRoutes.tsx`
- Modify: `iris-launcher/src/components/AppSidebar.tsx`

**Step 1: Add Settings route**

In `iris-launcher/src/components/AnimatedRoutes.tsx`:

Add import:

```typescript
import SettingsPage from "@/pages/SettingsPage";
```

Add route (after the `/` route, before the developer-only block):

```typescript
        <Route path="/settings" element={<SettingsPage />} />
```

**Step 2: Add sidebar link**

Read `iris-launcher/src/components/AppSidebar.tsx` to find the nav items array, then add a Settings link. The exact edit depends on the existing structure — look for the nav items definition and add:

```typescript
  { label: "Settings", to: "/settings", icon: Settings }
```

(Import `Settings` from `lucide-react` at the top of the file.)

**Step 3: Verify TypeScript compiles**

Run: `cd iris-launcher && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add iris-launcher/src/components/AnimatedRoutes.tsx iris-launcher/src/components/AppSidebar.tsx
git commit -m "feat(launcher): add /settings route and sidebar link"
```

---

## Task 17: End-to-end smoke test

**Step 1: Start the backend**

```bash
cd C:\dev\IRISVOICE
.venv\Scripts\activate
python start-backend.py
```

Expected: Backend starts on port 8090 (or configured port).

**Step 2: Verify the API endpoints work**

```bash
# GET — should return masked keys + known schema
curl http://localhost:8090/api/env-keys

# Expected: {"keys":{"PICOVOICE_ACCESS_KEY":"wIQ***...***Yg==","HF_TOKEN":"hf_***...***dQp"},"known_keys":{...}}

# POST — add a test key
curl -X POST http://localhost:8090/api/env-keys -H "Content-Type: application/json" -d "{\"key\":\"TEST_KEY\",\"value\":\"test123\"}"

# Expected: {"status":"ok","key":"TEST_KEY"}

# Reload
curl -X POST http://localhost:8090/api/env-keys/reload

# Expected: {"status":"ok"}

# Delete the test key
curl -X DELETE http://localhost:8090/api/env-keys/TEST_KEY

# Expected: {"status":"ok","key":"TEST_KEY"}
```

**Step 3: Verify .env.local was not corrupted**

Check that `C:\dev\IRISVOICE\.env.local` still contains the original Picovoice and HF keys (the test key should have been added then removed).

**Step 4: Start the launcher**

```bash
cd C:\dev\IRISVOICE\iris-launcher
npm run dev
```

Open `http://localhost:8080` in a browser.

**Step 5: Test the first-run flow**

1. Clear localStorage: `localStorage.clear()` in browser console, then reload.
2. Should redirect to `/config`.
3. Should show Picovoice and HuggingFace as known keys (with help links).
4. Both should show as "configured" (masked values visible).
5. Click "Continue" → should go to `/mode-select`.
6. Select a mode → should go to dashboard.
7. Click "Settings" in sidebar → should show SettingsPage with the same keys.

**Step 6: Test adding a custom key**

1. In SettingsPage, add `TEST_CUSTOM_KEY` = `test_value`.
2. Should appear in the custom keys list.
3. Verify it was written to `.env.local` (check file).
4. Click "Reload Backend".
5. Delete the test key.
6. Verify it was removed from `.env.local`.

**Step 7: Commit final state**

```bash
git add -A
git commit -m "test: e2e smoke test passed for env-keys config flow"
```

---

## Summary

| Task | Component | Files | Tests |
|------|-----------|-------|-------|
| 1 | Backend parser | `backend/env_keys.py` | 7 |
| 2 | Backend writer | `backend/env_keys.py` | 4 |
| 3 | Backend masker | `backend/env_keys.py` | 5 |
| 4 | Backend known keys | `backend/env_keys.py` | 4 |
| 5 | Backend reload | `backend/env_keys.py` | 3 |
| 6 | Backend set/delete | `backend/env_keys.py` | 4 |
| 7 | Backend API router | `backend/api/env_keys.py`, `main.py` | 9 |
| 8 | Backend porcupine fix | `backend/voice/porcupine_detector.py` | 1 |
| 9 | Tauri fs commands | `src-tauri/` | compile check |
| 10 | Launcher API client | `iris-api.ts` | tsc check |
| 11 | Launcher hook | `use-env-keys.ts` | tsc check |
| 12 | Launcher ConfigPage | `ConfigPage.tsx` | tsc check |
| 13 | Launcher SettingsPage | `SettingsPage.tsx` | tsc check |
| 14 | Launcher AppContext | `AppContext.tsx` | tsc check |
| 15 | Launcher routing | `App.tsx` | tsc check |
| 16 | Launcher sidebar | `AnimatedRoutes.tsx`, `AppSidebar.tsx` | tsc check |
| 17 | E2E smoke test | — | manual |

**Total: 41 automated tests + 1 compile check + 1 manual e2e**

---

## Notes for the Implementer

1. **Run tasks in order** — each builds on the previous.
2. **Run the full test suite after each task**: `python -m pytest backend/tests/test_env_keys.py backend/tests/test_env_keys_api.py -v`
3. **Never commit `.env.local`** — it contains real keys. The `.gitignore` already handles this, but double-check with `git status` before each commit.
4. **The `.env.local.bak` file** is also gitignored (matches `.env*.local` pattern) — but verify.
5. **If Tauri build fails** on Task 9, it's likely a missing `tauri-plugin-fs` version. Check https://v2.tauri.app/plugin/file-system/ for the latest version.
6. **The ConfigPage "Skip for now" button** sets `envKeysConfigured=true` without requiring any keys — this is intentional. Users can configure keys later via SettingsPage.
7. **Key masking shows first 3 + last 3 chars** — this is enough to identify which key it is without exposing it. If a key is <= 6 chars, it shows `***` only.
