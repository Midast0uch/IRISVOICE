"""
FAULTLINE — Three-Layer Tool-Failure Taxonomy (session 244).

Errors are INFORMATION, not noise. This module gives every tool failure a
structured, learnable shape so DER's reviewer can reason over failures instead
of guessing from bare exception strings.

THE THREE LAYERS (see docs/architecture/FAULTLINE.md + pin_b808635af544):

  LAYER 1 — DIMENSIONS (stable core, hardcoded deliberately)
      Every failure answers three invariant questions:
        retryable : will trying again help?          yes | no | maybe
        blame     : whose fault is it?               self | world | query
        info_state: does the information exist?      blocked | missing | unknown
      These are invariants — "will retrying help" is meaningful forever.

  LAYER 2 — LABEL REGISTRY (open, dynamic, data-not-code)
      A named label is just a bundle of dimension values plus prose:
        walled   = retryable:no     blame:world  info:blocked
        empty    = retryable:no     blame:query  info:missing
      New label = registry edit (register_error_label), never a loop rewrite.
      Consumers understand new labels through their dimensions immediately.

  LAYER 3 — UNCLASSIFIED BUCKET (how the vocabulary evolves)
      An unrecognized type is NEVER discarded. It is stored raw with full
      details and counted (_unknown_counts). Repeated unknowns are promotion
      candidates: the vocabulary grows from evidence.

WHY LESSONS SCALE: stored records are (dimensions, context, outcome). The
reviewer generalizes by SIMILARITY ACROSS DIMENSIONS ("retryable:no +
blame:world — same shape as last time, don't retry"), not by exact string
match. A failure mode nobody named yet still lands near its neighbors on day
one.

NOTHING IS EVER LOST: the raw exception string always survives in
details["raw"]. FAULTLINE adds structure on top; it never replaces truth.
"""

from __future__ import annotations

import os
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Optional


# ── Layer 1: the stable dimension core ──────────────────────────────────────

RETRYABLE_VALUES = ("yes", "no", "maybe")
BLAME_VALUES = ("self", "world", "query")
INFO_STATE_VALUES = ("blocked", "missing", "unknown")


@dataclass(frozen=True)
class FailureDimensions:
    """Layer 1 — the invariant questions every failure answers."""

    retryable: str = "unknown"   # yes | no | maybe
    blame: str = "unknown"       # self | world | query
    info_state: str = "unknown"  # blocked | missing | unknown

    def as_dict(self) -> Dict[str, str]:
        return {
            "retryable": self.retryable,
            "blame": self.blame,
            "info_state": self.info_state,
        }


UNKNOWN_DIMENSIONS = FailureDimensions()


# ── Layer 2: the open label registry ────────────────────────────────────────

@dataclass(frozen=True)
class LabelSpec:
    """One registered failure label = dimensions + human meaning."""

    label: str
    dimensions: FailureDimensions
    description: str


# Seeded vocabulary. GROW THIS VIA register_error_label() — never inline new
# labels at call sites; an unregistered label silently degrades to Layer 3.
ERROR_LABELS: Dict[str, LabelSpec] = {}
_LABELS_LOCK = threading.Lock()


def register_error_label(
    label: str,
    retryable: str,
    blame: str,
    info_state: str,
    description: str = "",
) -> bool:
    """Layer 2 growth API. Register (or re-register) a failure label.

    Returns True when the label is registered/updated, False when the spec is
    invalid (bad dimension values) — invalid registrations are refused, not
    coerced, so the registry only ever contains well-formed labels.
    """
    if retryable not in RETRYABLE_VALUES or blame not in BLAME_VALUES \
            or info_state not in INFO_STATE_VALUES:
        return False
    with _LABELS_LOCK:
        if label in ERROR_LABELS:
            # REQ-19 edge case: a duplicate registration is REFUSED, not
            # silently overwritten — the first spec to name a failure mode
            # owns its dimensions.
            return False
        ERROR_LABELS[label] = LabelSpec(
            label=label,
            dimensions=FailureDimensions(retryable=retryable, blame=blame, info_state=info_state),
            description=description,
        )
    return True


# Seed vocabulary (the labels the system already knows it needs).
register_error_label(
    "transient", "maybe", "world", "unknown",
    "Temporary world-side condition (timeout, connection blip). Retry MAY win.",
)
register_error_label(
    "walled", "no", "world", "blocked",
    "Source actively blocked us (bot wall, park, paywall). Identical retry "
    "provably fails; diversify sources or ask the user.",
)
register_error_label(
    "rate_limited", "maybe", "world", "blocked",
    "Quota/throttle. Back off, then retry may win.",
)
register_error_label(
    "empty", "no", "query", "missing",
    "The fetch succeeded but the information does not exist there. The QUERY "
    "was the problem — rephrase, don't repeat.",
)
register_error_label(
    "invalid_params", "no", "self", "unknown",
    "The planner made a bad call. Fix the call, don't retry it verbatim.",
)
register_error_label(
    "capability_missing", "no", "self", "unknown",
    "Tool/dependency unavailable in this environment.",
)
register_error_label(
    "crashed", "maybe", "self", "unknown",
    "Unhandled exception inside the tool. Details carry the traceback signal.",
)

# ── REQ-19 AC1: dev/shell surface labels (was FAULTLINE §8 Roadmap) ─────────
# A DATA edit per FAULTLINE §2 — registered vocabulary, never new branches.
# Dimensions come verbatim from REQ-19's AC1 table.
register_error_label(
    "workdir_denied", "no", "query", "blocked",
    "Path outside the registered project roots (REQ-4 AC6 allowlist) — an "
    "identical retry can never succeed.",
)
register_error_label(
    "cap_reached", "yes", "self", "missing",
    "Dev subprocess semaphore full (REQ-5) — the same call succeeds once a "
    "slot frees.",
)
register_error_label(
    "aborted", "maybe", "self", "unknown",
    "User abort (REQ-8) — not a tool defect. Excluded from the failure "
    "budget and the tool-decision veto memory.",
)
register_error_label(
    "shell_spawn_failed", "maybe", "world", "blocked",
    "No shell resolvable or the workdir vanished before spawn.",
)
register_error_label(
    "output_truncated", "no", "world", "missing",
    "Output budget hit (REQ-12); full output is in the terminal panel, "
    "not lost.",
)
register_error_label(
    "injection_suppressed", "no", "self", "blocked",
    "Output matched the injection deny-list (REQ-2 AC4) — it exists but "
    "must not enter context.",
)
register_error_label(
    "worktree_unavailable", "maybe", "world", "blocked",
    "REQ-13 sandbox worktree could not be created; the write was refused.",
)


def resolve_label(label: str) -> Optional[LabelSpec]:
    """Layer 2 lookup. Returns None for unregistered labels (Layer 3 path)."""
    with _LABELS_LOCK:
        return ERROR_LABELS.get(label)


# ── The wall ledger (FAULTLINE read-side, session 247) ──────────────────────
#
# FAULTLINE shipped as a write-only ledger: tool_bridge stamped every failure
# with typed dimensions, but NO dispatch path ever read them back. The live
# proof (session 247, conv-41): spacedaily.com parked with reason=challenge at
# 14:56 — a `walled` label, retryable:no by definition — and was RE-DISPATCHED
# anyway at 15:13, because the parked-source registry is keyed
# run_id|domain and each crawl round mints a NEW run_id. Classification
# without enforcement.
#
# The wall ledger is the missing read side: a small domain-keyed TTL map that
# records non-retryable walls (challenge / bot-protection) as they happen and
# answers ONE question at dispatch time — "did this domain recently prove
# itself walled?" — so the orchestrator can skip instead of re-lose the
# round-trip. TTL-bounded so a wall that later clears (site fixes bot config,
# different egress) resumes normal service without a restart.

_WALL_LEDGER_TTL_S = float(os.environ.get("IRIS_WALL_LEDGER_TTL_S", "900"))
_wall_ledger: Dict[str, float] = {}   # domain -> monotonic timestamp of last walled outcome
_wall_lock = threading.Lock()


def record_wall(domain: str) -> None:
    """Record that `domain` produced a retryable:no wall outcome. Never raises."""
    d = (domain or "").strip().lower()
    if not d:
        return
    try:
        with _wall_lock:
            _wall_ledger[d] = time.monotonic()
    except Exception:
        pass


def is_walled(domain: str) -> bool:
    """True when `domain` has a live (non-expired) wall record — i.e. FAULTLINE
    says retryable:no for it right now. Dispatch sites consult this BEFORE
    spending a crawl round on the domain."""
    d = (domain or "").strip().lower()
    if not d:
        return False
    try:
        now = time.monotonic()
        with _wall_lock:
            ts = _wall_ledger.get(d)
            if ts is None:
                return False
            if now - ts > _WALL_LEDGER_TTL_S:
                # Expired — lazy eviction keeps the map bounded without a sweeper.
                _wall_ledger.pop(d, None)
                return False
            return True
    except Exception:
        return False


def reset_wall_ledger_for_testing() -> None:
    global _wall_ledger
    with _wall_lock:
        _wall_ledger = {}


# ── Layer 3: the unclassified bucket ────────────────────────────────────────

_unknown_counts: Counter = Counter()
_unknown_lock = threading.Lock()


def unknown_label_counts() -> Dict[str, int]:
    """Evidence for vocabulary growth: how often each unnamed pattern appeared."""
    with _unknown_lock:
        return dict(_unknown_counts)


def _record_unknown(label: str) -> None:
    with _unknown_lock:
        _unknown_counts[label] += 1


def promote_unknown(label: str, retryable: str, blame: str, info_state: str,
                    description: str = "") -> bool:
    """Layer 3 → Layer 2 promotion. Call once evidence justifies naming."""
    ok = register_error_label(label, retryable, blame, info_state, description)
    if ok:
        with _unknown_lock:
            _unknown_counts.pop(label, None)
    return ok


# ── The canonical outcome constructor ───────────────────────────────────────

def tool_error(
    label: str,
    message: str,
    *,
    details: Optional[Dict[str, Any]] = None,
    raw: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the canonical structured failure outcome.

    EVERY field downstream needs lives here: error_type (the label),
    retryable/blame/info_state (Layer-1 dimensions resolved through the
    registry), and details["raw"] preserving the original exception string.
    Unregistered labels are accepted but flagged unclassified (Layer 3) —
    the failure is never dropped and never silently reshaped.
    """
    spec = resolve_label(label)
    if spec is not None:
        dims = spec.dimensions
        classified = True
    else:
        _record_unknown(label)
        dims = UNKNOWN_DIMENSIONS
        classified = False

    out: Dict[str, Any] = {
        "success": False,
        "error": message,
        "error_type": label,
        "retryable": dims.retryable,
        "blame": dims.blame,
        "info_state": dims.info_state,
        "details": dict(details or {}),
        "ts": time.time(),
    }
    if raw:
        out["details"]["raw"] = raw
    if not classified:
        out["details"]["unclassified"] = True
        out["details"]["unclassified_count"] = unknown_label_counts().get(label, 1)
    return out


# ── Exception classification (boundary auto-typing) ─────────────────────────

_EXCEPTION_MAP = [
    (TimeoutError, "transient"),
    (ConnectionError, "transient"),
    (PermissionError, "capability_missing"),
    (FileNotFoundError, "capability_missing"),
    (ValueError, "invalid_params"),
    (KeyError, "invalid_params"),
]


def classify_exception(exc: BaseException) -> str:
    """Map an exception to the best-known label. Unknown → 'crashed'."""
    for exc_type, label in _EXCEPTION_MAP:
        if isinstance(exc, exc_type):
            return label
    return "crashed"


def normalize_failure(result: Dict[str, Any]) -> Dict[str, Any]:
    """Boundary enrichment (universal coverage).

    Given ANY failure-shaped result dict, guarantee the FAULTLINE fields exist.
    Tools that already used tool_error() pass through untouched; legacy tools
    returning bare {"success": False, "error": "..."} get classified here —
    which is what makes the taxonomy universal without rewriting every site.
    """
    if not isinstance(result, dict) or result.get("success") is not False:
        return result
    if result.get("error_type"):
        # Already typed (directly or via tool_error) — ensure dimensions exist.
        spec = resolve_label(str(result["error_type"]))
        dims = spec.dimensions if spec else UNKNOWN_DIMENSIONS
        result.setdefault("retryable", dims.retryable)
        result.setdefault("blame", dims.blame)
        result.setdefault("info_state", dims.info_state)
        return result
    label = classify_exception_from_message(str(result.get("error", "")))
    enriched = tool_error(label, str(result.get("error", "unknown failure")),
                          raw=str(result.get("error", "")))
    # Preserve any extra keys the tool attached (documents, conversations...).
    for k, v in result.items():
        if k not in enriched or enriched[k] in (None, ""):
            enriched[k] = v
    result.clear()
    result.update(enriched)
    return result


def classify_exception_from_message(message: str) -> str:
    """Heuristic classifier for string-only failures (legacy boundary)."""
    m = (message or "").lower()
    if "timeout" in m or "timed out" in m or "connection" in m:
        return "transient"
    if "parked" in m or "walled" in m or "403" in m or "challenge" in m:
        return "walled"
    if "not found" in m or "no module" in m or "unavailable" in m or "missing" in m:
        return "capability_missing"
    if "invalid" in m or "expected" in m or "required" in m:
        return "invalid_params"
    return "crashed"
