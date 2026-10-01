"""Trajectory export and curation quality for the memory_events stream
(docs/Design/EVENT_TAXONOMY.md sections 7 and 8, build step 4).

Two read-only functions over a connection to the app store:

  export_episode(conn, episode_id)  the episode's events in order + a DERIVED reward
  curation_report(conn)             the section 8 measurements, as a dict

Rewards are COMPUTED here, never stored: a versioned function over the immutable
record, so a policy change never rewrites history (section 7). Version 1 is
SUCCESS-GATED, then cost among successes:

  success   the episode holds a VERIFIED_* event whose evidence is OUTSIDE evidence
            (test / completion / user / recurrence / corroboration) AND whose label
            is a fact, not a guess (``counts_as_outside_evidence``: label_source rule
            or user). A run the verifier liked but nobody outside confirmed is NOT a
            success, so it earns 0.0 - it never ranks with, or above, a success.
  reward    0.0 for a non-success; for a success 1.0 minus a cost penalty in [0, 0.5),
            so every success outranks every non-success and cheaper successes rank
            higher. The penalty constants are v1 start values.

Plain functions over sqlite; no writes (the report is safe against the live store).
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any, Dict, List, Optional

from backend.memory.event_alphabet import OUTSIDE_EVIDENCE, counts_as_outside_evidence

logger = logging.getLogger(__name__)

REWARD_VERSION = 1
# v1 start values of the cost penalty: 10 steps, 60 s or 50k tokens each halve the
# efficiency term. The reward is derived, so these can change without touching history.
_STEPS_SCALE = 10.0
_MS_SCALE = 60_000.0
_TOKENS_SCALE = 50_000.0
_MAX_PENALTY = 0.5

_COLUMNS = (
    "event_id, ts, episode_id, step_index, thread_id, family, label, valence, actor, evidence, "
    "cause_key, outcome_key, trigger, exec_domain, topic_domain, label_source, label_confidence, "
    "hash_signature, action_signature, cost, links, payload"
)
_JSON_FIELDS = ("cost", "links", "payload")


def _has_table(conn) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'memory_events'"
    ).fetchone() is not None


def _decode(row: tuple) -> Dict[str, Any]:
    ev = dict(zip([c.strip() for c in _COLUMNS.split(",")], row))
    for key in _JSON_FIELDS:
        try:
            ev[key] = json.loads(ev[key]) if ev.get(key) else None
        except Exception:  # noqa: BLE001 - a malformed blob is kept as None, never fatal
            ev[key] = None
    return ev


def reward_v1(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The version 1 reward of one episode's events (see the module docstring)."""
    if not events:
        return {"version": REWARD_VERSION, "success": False, "reward": None, "cost": {}}
    verified = [
        e for e in events
        if str(e.get("label") or "").startswith("VERIFIED_")
        and counts_as_outside_evidence(e.get("evidence") or "", e.get("label_source") or "")
    ]
    cost = {
        "steps": len({e.get("step_index") for e in events if e.get("step_index")}),
        "ms": 0, "tokens": 0, "tool_calls": 0,
    }
    for e in events:
        c = e.get("cost") or {}
        cost["ms"] += int(c.get("ms") or 0)
        cost["tokens"] += int(c.get("tokens_in") or 0) + int(c.get("tokens_out") or 0)
        cost["tool_calls"] += int(c.get("tool_calls") or 0)
    if not verified:
        return {"version": REWARD_VERSION, "success": False, "reward": 0.0, "cost": cost}
    burden = (cost["steps"] / _STEPS_SCALE + cost["ms"] / _MS_SCALE + cost["tokens"] / _TOKENS_SCALE)
    penalty = _MAX_PENALTY * (1.0 - 1.0 / (1.0 + burden))
    return {
        "version": REWARD_VERSION, "success": True, "reward": round(1.0 - penalty, 6), "cost": cost,
        "evidence": sorted({e["evidence"] for e in verified}),
    }


def export_episode(conn, episode_id: str) -> Dict[str, Any]:
    """One episode as a trajectory: its events in order (state hash, action, cost,
    outcome, evidence, links) and the derived reward. Read-only; never raises."""
    try:
        if not _has_table(conn):
            return {"episode_id": episode_id, "events": [], "reward": reward_v1([])}
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM memory_events WHERE episode_id = ? ORDER BY ts, rowid",
            (episode_id,),
        ).fetchall()
        events = [_decode(r) for r in rows]
        return {"episode_id": episode_id, "events": events, "reward": reward_v1(events)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[event_export] export failed episode=%s: %s", episode_id, exc)
        return {"episode_id": episode_id, "events": [], "reward": reward_v1([]), "error": str(exc)}


def curation_report(conn) -> Dict[str, Any]:
    """EVENT_TAXONOMY section 8, as a dict (the script prints it). Read-only."""
    if not _has_table(conn):
        return {"events": 0}
    q = conn.execute
    total = q("SELECT COUNT(*) FROM memory_events").fetchone()[0]
    by_label = [
        {"family": f, "label": lab, "n": n}
        for f, lab, n in q(
            "SELECT family, label, COUNT(*) FROM memory_events GROUP BY family, label "
            "ORDER BY COUNT(*) DESC"
        ).fetchall()
    ]
    by_family = Counter()
    for row in by_label:
        by_family[row["family"] or "(unclassified)"] += row["n"]
    sources = dict(q("SELECT label_source, COUNT(*) FROM memory_events GROUP BY label_source").fetchall())
    unclassified = q("SELECT COUNT(*) FROM memory_events WHERE family IS NULL").fetchone()[0]
    unknown_labels = q(
        "SELECT label, COUNT(*) FROM memory_events WHERE family IS NULL GROUP BY label "
        "ORDER BY COUNT(*) DESC LIMIT 10"
    ).fetchall()

    # Episodes: outside evidence is counted ONLY for fact labels (rule / user). Evidence
    # of an outside kind on a guessed label (oracle / brain) is reported on its own.
    trusted, guessed, episodes = set(), set(), set()
    for ep, evidence, source in q(
        "SELECT episode_id, evidence, label_source FROM memory_events WHERE episode_id IS NOT NULL"
    ).fetchall():
        episodes.add(ep)
        if evidence in OUTSIDE_EVIDENCE:
            (trusted if counts_as_outside_evidence(evidence, source) else guessed).add(ep)
    guessed_only = guessed - trusted

    # Recall attribution: delivered traces and how many reached a HELPED / MISLED outcome.
    delivered, helped, misled = set(), set(), set()
    for label, links in q(
        "SELECT label, links FROM memory_events WHERE label IN "
        "('RECALL_DELIVERED', 'RECALL_HELPED', 'RECALL_MISLED')"
    ).fetchall():
        try:
            trace = (json.loads(links or "{}") or {}).get("recall_trace_id")
        except Exception:  # noqa: BLE001
            trace = None
        if trace:
            {"RECALL_DELIVERED": delivered, "RECALL_HELPED": helped, "RECALL_MISLED": misled}[label].add(trace)
    resolved = delivered & (helped | misled)

    lm = {lab: n for lab, n in q(
        "SELECT label, COUNT(*) FROM memory_events WHERE label IN "
        "('LANDMARK_PROMOTED', 'LANDMARK_STALE', 'LANDMARK_DEMOTED') GROUP BY label"
    ).fetchall()}

    def _share(part: int, whole: int) -> Optional[float]:
        return round(part / whole, 4) if whole else None

    return {
        "events": total,
        "by_family": dict(by_family),
        "by_label": by_label,
        "label_source": sources,
        "unclassified": {"n": unclassified, "rate": _share(unclassified, total),
                         "top_labels": [{"label": lab, "n": n} for lab, n in unknown_labels]},
        "episodes": {
            "total": len(episodes),
            "with_outside_evidence": len(trusted),
            "share_with_outside_evidence": _share(len(trusted), len(episodes)),
            "guessed_outside_only": len(guessed_only),
            "share_guessed_outside_only": _share(len(guessed_only), len(episodes)),
        },
        "recall_attribution": {
            "delivered": len(delivered), "helped": len(helped & delivered),
            "misled": len(misled & delivered), "coverage": _share(len(resolved), len(delivered)),
        },
        "landmarks": {"promoted": lm.get("LANDMARK_PROMOTED", 0), "stale": lm.get("LANDMARK_STALE", 0),
                      "demoted": lm.get("LANDMARK_DEMOTED", 0)},
    }
