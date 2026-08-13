"""Redact credentials out of text before it reaches a log sink.

Why this exists
---------------
``backend/main.py`` logged every inbound WebSocket frame verbatim::

    logger.info(f"[WS] Received from {client_id}: {data[:200]}")

The settings UI emits a ``field_update`` frame per KEYSTROKE, so typing an API
key into the Provider panel wrote ~30 progressively longer prefixes of that key
to disk, the last of which is the complete credential. A committed log file
(``backend/logs/irisvoice.log.1``) carried a full Cerebras key into a public
repository this way.

Design notes
------------
Redaction runs BEFORE truncation. Truncating first (``data[:200]``) does not
protect anything — it just publishes the first 200 characters of the secret.

Two shapes are handled, because the leak used the second one:

  direct    {"api_key": "csk-live-…"}          -> key name IS the credential name
  indirect  {"field_id": "api_key",             -> a SIBLING names the credential
             "value": "csk-live-…"}                and the secret sits in `value`

A name-based pass alone misses the indirect shape, and a pattern-based pass
alone misses credentials with no recognizable prefix. Both run.

This is a log-hygiene control, not an access control: it is best-effort by
design and must never raise, because a redaction bug must not take down the
WebSocket receive loop.
"""

from __future__ import annotations

import json
import re
from typing import Any

REDACTED = "[REDACTED]"

# Field names whose VALUE is a credential.
_CREDENTIAL_NAMES = frozenset(
    {
        "api_key", "apikey", "api-key",
        "secret", "client_secret", "app_secret",
        "token", "access_token", "refresh_token", "auth_token", "id_token",
        "password", "passwd", "pwd",
        "authorization", "auth",
        "private_key", "credential", "credentials",
        "cohere_key", "cerebras_key", "venice_key", "chutes_key",
        "deepseek_key", "openai_key", "anthropic_key", "hf_token",
    }
)

# Sibling keys that NAME the field a `value` belongs to (the indirect shape).
_NAME_CARRIER_KEYS = ("field_id", "field", "id", "name", "key")

# Values that look like credentials regardless of what they are called.
_VALUE_PATTERNS = [
    re.compile(r"csk-[A-Za-z0-9_-]{8,}"),                 # Cerebras
    re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"),             # Anthropic
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),                 # OpenAI & compatibles
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),            # GitHub
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"hf_[A-Za-z0-9]{20,}"),                   # HuggingFace
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),                 # Google
    re.compile(r"AKIA[0-9A-Z]{16}"),                      # AWS
    re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),          # Slack
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

# Last-resort textual pass for frames that did not parse as JSON.
_TEXT_ASSIGN = re.compile(
    r"""(?ix)
    (\\?["']?)                                   # optional opening quote
    (api[_-]?key|apikey|secret|token|password|passwd|
     auth[_-]?token|access[_-]?token|client[_-]?secret)
    (\\?["']?\s*[:=]\s*\\?["'])                  # separator + opening quote
    ([^"'\\]{4,})                                # the credential
    """,
)


def _is_credential_name(name: Any) -> bool:
    return isinstance(name, str) and name.strip().lower() in _CREDENTIAL_NAMES


def _redact_value(value: Any) -> Any:
    """Blank a credential, preserving type so downstream shape checks survive."""
    if isinstance(value, str):
        return REDACTED if value else value
    if value is None:
        return None
    return REDACTED


def _scrub_patterns(text: str) -> str:
    for pat in _VALUE_PATTERNS:
        text = pat.sub(REDACTED, text)
    return text


def _walk(node: Any) -> Any:
    """Recursively redact credentials in a parsed JSON structure."""
    if isinstance(node, dict):
        # Indirect shape: a sibling names this object's `value` as a credential.
        names_a_credential = any(
            _is_credential_name(node.get(k)) for k in _NAME_CARRIER_KEYS
        )
        out = {}
        for k, v in node.items():
            if _is_credential_name(k):
                out[k] = _redact_value(v)
            elif names_a_credential and k == "value":
                out[k] = _redact_value(v)
            else:
                out[k] = _walk(v)
        return out
    if isinstance(node, list):
        return [_walk(item) for item in node]
    if isinstance(node, str):
        return _scrub_patterns(node)
    return node


def redact(text: str, limit: int | None = None) -> str:
    """Return *text* with credentials replaced by ``[REDACTED]``.

    Args:
        text:  Raw frame / payload text.
        limit: Optional max length applied AFTER redaction. Truncating before
               redacting would simply publish a prefix of the secret.

    Never raises — on any internal failure it degrades to the pattern pass, and
    failing that, to a fully elided placeholder. Losing log detail is always
    preferable to leaking a credential or killing the receive loop.
    """
    if not text:
        return text
    try:
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            out = _scrub_patterns(_TEXT_ASSIGN.sub(r"\1\2\3" + REDACTED, text))
        else:
            out = json.dumps(_walk(parsed), separators=(",", ":"), default=str)
    except Exception:
        try:
            out = _scrub_patterns(text)
        except Exception:
            return "[REDACTION FAILED — payload elided]"
    if limit is not None and len(out) > limit:
        out = out[:limit]
    return out
