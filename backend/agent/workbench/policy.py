"""Workbench policy: what may ENTER the namespace (CLM-11).

Pure rules, stdlib only. Every refusal has a name and is counted. Nothing leaves the
Workbench through a policy: values stay in variables and are read by `wb:` reference.
"""
import collections
import json
import re
import threading
from typing import Tuple

PUT_MAX_CHARS = 64_000       # one value entering through put

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_refusals = collections.Counter()
_lock = threading.Lock()


def _refuse(reason: str) -> Tuple[bool, str]:
    with _lock:
        _refusals[reason] += 1
    return False, reason


def refusals() -> dict:
    with _lock:
        return dict(_refusals)


def admit_put(name: str, value) -> Tuple[bool, str]:
    """(ok, reason). Names: identifiers, no dunder. Values: JSON, <= 64,000 chars."""
    if not isinstance(name, str) or not _NAME_RE.match(name) or name.startswith("__"):
        return _refuse("bad_name")
    try:
        text = json.dumps(value)
    except (TypeError, ValueError):
        return _refuse("not_json")
    if len(text) > PUT_MAX_CHARS:
        return _refuse("too_large")
    return True, "ok"
