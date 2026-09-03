"""
Per-provider credential storage.

Tries to use the ``keyring`` library for OS-backed storage.  Falls back
to a JSON file at ``data/provider_secrets.json`` when ``keyring`` is not
available (e.g. headless CI environments).

Secrets are keyed by ``provider_id`` (e.g. ``"cerebras"``).  The secret
value is never logged.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Path relative to project root
_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
_FALLBACK_PATH = _DATA_DIR / "provider_secrets.json"

_HAS_KEYRING = False
try:
    import keyring as _keyring_lib

    _HAS_KEYRING = True
except ImportError:
    _keyring_lib = None  # type: ignore[assignment]


def _ensure_data_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_fallback() -> dict[str, str]:
    _ensure_data_dir()
    if _FALLBACK_PATH.exists():
        try:
            with open(_FALLBACK_PATH, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as exc:
            logger.warning(f"[keyring] Failed to read fallback secrets: {exc}")
    return {}


def _write_fallback(secrets: dict[str, str]) -> None:
    _ensure_data_dir()
    try:
        with open(_FALLBACK_PATH, "w") as f:
            json.dump(secrets, f)
    except Exception as exc:
        logger.warning(f"[keyring] Failed to write fallback secrets: {exc}")


def get_secret(provider_id: str) -> Optional[str]:
    """Return the API key for *provider_id*, or *None* if not stored."""
    if _HAS_KEYRING:
        try:
            return _keyring_lib.get_password(
                f"iris_voice:provider:{provider_id}", provider_id
            )
        except Exception as exc:
            logger.warning(
                f"[keyring] get_secret keyring failed for {provider_id}: {exc}"
            )
    # Fallback
    secrets = _read_fallback()
    return secrets.get(provider_id)


def set_secret(provider_id: str, key: str) -> None:
    """Store *key* for *provider_id*.

    Never logs *key*. Strips surrounding whitespace — keys are pasted from
    dashboards/emails and a stray space makes every provider reject the
    credential (401) because it is sent verbatim as ``Bearer  <key>``.
    """
    if key:
        key = key.strip()
    if _HAS_KEYRING:
        try:
            _keyring_lib.set_password(
                f"iris_voice:provider:{provider_id}", provider_id, key
            )
            return
        except Exception as exc:
            logger.warning(
                f"[keyring] set_secret keyring failed for {provider_id}: {exc}"
            )
    # Fallback
    secrets = _read_fallback()
    secrets[provider_id] = key
    _write_fallback(secrets)
