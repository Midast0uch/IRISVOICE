"""Memory corrections v1, CLAIMS ONLY (MEMORY-SURFACE-BUILD.md section 5; MEMORY-UX-PLAN.md section 11 decision 2).

  POST /api/memory/correct        {action: confirm | wrong | forget, target: "claim:<landmark_id>", reason?}
  POST /api/memory/correct/undo   {correction_id}
  GET  /api/memory/corrections?limit=

The user says a claim is right, wrong or to be forgotten. Each correction is USER evidence:

  confirm  one `user_confirm` evidence entry (landmark.add_landmark_evidence; it re-derives the tier)
  wrong    one contradiction (landmark.contradict_landmark); a proven claim drops to 'candidate'
  forget   absorbed = 1 and " | dissolved: forgotten by you" in falsify_if - Kyudo's own absorb
           (integrity._dissolve). The row is never deleted; recall reads `absorbed IS NULL` only.

Every correction types ONE memory event (evidence "user") and the event IS the record: its payload holds the
prior state, so undo needs no table (CONFIRMATION | CORRECTION | CLAIM_FORGOTTEN; undo = CORRECTION_UNDONE).
All writes go through db.app_write (the one writer) and run ON lane("memory_events") - the lane that already types
the promotion a confirm causes - so a correction never races another writer on the shared connection; the request
waits for the job's answer (a click, not the answer path). A read of a row we decide on follows an app_flush.
A claim absorbed by a MERGE is corrected on its survivor (mycelium_landmark_merges, bounded chain, as
surface_queries.claim follows it); a claim absorbed by forget or dissolved has no survivor: 409.
Pins and strand actions are a later step.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import uuid
from concurrent.futures import Future, TimeoutError as FutureTimeout
from typing import Any, Optional

from backend.memory import memory_events as me
from backend.memory.db import app_flush, app_write
from backend.memory.mycelium import landmark as lm
from backend.memory.surface_queries import MERGE_HOPS, clip
from backend.utils import memory_live
from backend.utils.durability_queue import lane

logger = logging.getLogger(__name__)

UNDO_WINDOW_S = 600
FORGET_REASON = "forgotten by you"
LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX = 20, 100
_CLAIM_TEXT = 160
_FALSIFY_KEEP = 700          # the prior falsify_if kept whole in the event payload (_PAYLOAD_MAX is 2000)
_EVIDENCE_MAX = 50           # add_landmark_evidence keeps the newest 50 entries
_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")

_ACTIONS = {"confirm": ("feedback", "CONFIRMATION"), "wrong": ("feedback", "CORRECTION"),
            "forget": ("memory", "CLAIM_FORGOTTEN")}
_UNDONE = ("feedback", "CORRECTION_UNDONE")

_JOB_WAIT_S = 30.0           # how long a click waits for the lane; a longer wait answers 503 (the job still runs)


class CorrectionError(Exception):
    """An outcome the caller answers with ``status``."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _now() -> float:
    return time.time()


def _on_lane(fn):
    """Run ``fn()`` on lane("memory_events") and return its result (or raise its exception). A correction is a
    read-decide-write on one row: one ordered writer per resource, not a lock."""
    lane_ = lane("memory_events")
    if lane_.in_worker():
        return fn()
    box: Future = Future()

    def _job() -> None:
        try:
            box.set_result(fn())
        except BaseException as exc:  # noqa: BLE001 - handed to the waiting request, never lost on the lane
            box.set_exception(exc)

    if not lane_.submit("memory_correction", _job):
        raise CorrectionError(503, "the memory is busy; try again")
    try:
        return box.result(timeout=_JOB_WAIT_S)
    except FutureTimeout:
        raise CorrectionError(503, "the memory is still working; check your corrections") from None


# -- the row ----------------------------------------------------------------------------------------
_ROW_SQL = ("SELECT tier, contradictions, absorbed, falsify_if, evidence, last_verified, is_permanent "
            "FROM mycelium_landmarks WHERE landmark_id = ?")


def _row(conn, landmark_id: str) -> Optional[dict]:
    r = conn.execute(_ROW_SQL, (landmark_id,)).fetchone()
    if r is None:
        return None
    try:
        evidence = [e for e in json.loads(r[4] or "[]") if isinstance(e, dict)]
    except (ValueError, TypeError):
        evidence = []
    return {"tier": r[0] or "candidate", "contradictions": r[1] or 0, "absorbed": bool(r[2]),
            "falsify_if": r[3], "evidence": evidence, "last_verified": r[5], "permanent": int(r[6] or 0)}


def _shown(row: dict) -> dict:
    """The four values the API shows (before / after)."""
    return {"tier": row["tier"], "contradictions": row["contradictions"], "absorbed": row["absorbed"],
            "evidence_count": len(row["evidence"])}


def _survivor(conn, landmark_id: str) -> str:
    """The live claim a correction on ``landmark_id`` lands on. 404 unknown; 409 absorbed with no
    survivor (forgotten or dissolved)."""
    cur, hops = landmark_id, 0
    while True:
        row = _row(conn, cur)
        if row is None:
            if hops == 0:
                raise CorrectionError(404, "unknown claim")
            raise CorrectionError(409, "this claim was absorbed and its survivor is gone")
        if not row["absorbed"]:
            return cur
        if hops >= MERGE_HOPS:
            raise CorrectionError(409, "this claim was absorbed")
        try:
            m = conn.execute("SELECT survivor_id FROM mycelium_landmark_merges WHERE absorbed_id = ? "
                             "ORDER BY created_at DESC LIMIT 1", (cur,)).fetchone()
        except sqlite3.OperationalError:     # a store from before merges existed: nothing to follow
            m = None
        if m is None:
            raise CorrectionError(409, "this claim was forgotten or dissolved")
        cur, hops = m[0], hops + 1


def _tap(landmark_id: str, row: dict, absorbed_now: bool) -> None:
    """The live tap of a state we wrote (never raises). Kinds are the tap's own set."""
    if absorbed_now:
        memory_live.landmark_update(landmark_id, "dissolved")
    else:
        kind = {"landmark": "promoted", "stale": "stale"}.get(row["tier"], "demoted")
        memory_live.landmark_update(landmark_id, kind, tier=row["tier"])


# -- the events -------------------------------------------------------------------------------------
def _needle(correction_id: str) -> str:
    return f'"correction_id": "{correction_id}"'        # json.dumps' form, as emit_event stores it


def _find_event(conn, family: str, label: str, correction_id: str) -> Optional[tuple]:
    # PLAN -> SEARCH memory_events USING INDEX idx_memory_events_label (family=? AND label=?) + TEMP B-TREE
    return conn.execute(
        "SELECT event_id, ts, payload FROM memory_events WHERE family = ? AND label = ? AND instr(payload, ?) > 0 "
        "ORDER BY ts DESC LIMIT 1", (family, label, _needle(correction_id))).fetchone()


def _emit(conn, family: str, label: str, payload: dict) -> tuple[str, float]:
    """Type the event (evidence "user") and read back its timestamp. A refused write raises (500)."""
    eid = me.emit_event(conn, label=label, evidence="user", actor="user", label_source="user",
                        family_hint=family, payload=payload, chain=False)
    if not eid:
        raise CorrectionError(500, "the event was not written")
    app_flush()
    r = conn.execute("SELECT ts FROM memory_events WHERE event_id = ?", (eid,)).fetchone()
    return eid, (r[0] if r else _now())


def _prepare(conn) -> None:
    lm.ensure_landmark_policy_columns(conn)
    me.ensure_schema(conn)
    app_flush()           # earlier queued evidence / absorb writes must be on disk before this read


# -- correct ----------------------------------------------------------------------------------------
def correct(conn, action: Any, target: Any, reason: Any = None) -> dict:
    if action not in _ACTIONS:
        raise CorrectionError(400, "action must be confirm, wrong or forget")
    if not isinstance(target, str) or not target.startswith("claim:") or not _ID_RE.match(target[6:]):
        raise CorrectionError(400, 'target must be "claim:<landmark_id>"')
    why = (reason.strip()[:120] if isinstance(reason, str) else "") or ""
    return _on_lane(lambda: _correct_job(conn, action, target, why))


def _correct_job(conn, action: str, target: str, why: str) -> dict:
    family, label = _ACTIONS[action]
    _prepare(conn)
    lid = _survivor(conn, target[6:])
    prior = _row(conn, lid)
    cid = "cor-" + uuid.uuid4().hex[:12]
    falsify = prior["falsify_if"]
    before_full = {                        # what undo restores; the first four are the API's `before`
        **_shown(prior),
        "last_verified": prior["last_verified"],
        "is_permanent": prior["permanent"],
        "falsify_if": None if falsify is None else falsify[:_FALSIFY_KEEP],
        "falsify_len": None if falsify is None else len(falsify),
        # confirm appends one entry and the list keeps the newest 50: the oldest may fall off
        "evidence_dropped": (prior["evidence"][0]
                             if action == "confirm" and len(prior["evidence"]) >= _EVIDENCE_MAX else None),
    }
    if action == "confirm":
        lm.add_landmark_evidence(conn, lid, "user_confirm", ref=cid, session="user")
    elif action == "wrong":
        lm.contradict_landmark(conn, lid, why or "marked wrong by you")
        # a claim you call wrong is no longer permanent: Kyudo skips permanent claims, so it would never dissolve it
        app_write(conn, "UPDATE mycelium_landmarks SET is_permanent = 0 WHERE landmark_id = ?", (lid,))
    else:
        app_write(conn, "UPDATE mycelium_landmarks SET absorbed = 1, falsify_if = COALESCE(falsify_if, '') || ? "
                  "WHERE landmark_id = ? AND absorbed IS NULL", (f" | dissolved: {FORGET_REASON}", lid))
        memory_live.landmark_update(lid, "dissolved")
    app_flush()
    after = _row(conn, lid)
    payload = {"correction_id": cid, "action": action, "target": target, "landmark_id": lid,
               "before": before_full, **({"reason": why} if why else {})}
    try:
        _, ts = _emit(conn, family, label, payload)
    except CorrectionError:
        _restore(conn, lid, cid, before_full, action)         # no event = no record = no change
        raise
    # live taps: add_landmark_evidence taps a promotion, contradict_landmark its new tier, forget above
    logger.info("[memory_corrections] correction=%s action=%s landmark=%s tier %s -> %s", cid, action, lid,
                prior["tier"], after["tier"] if after else "?")
    return {"correction_id": cid, "action": action, "target": target, "landmark_id": lid,
            "before": _shown(prior), "after": _shown(after), "undo_until": ts + UNDO_WINDOW_S}


# -- undo -------------------------------------------------------------------------------------------
def _restore(conn, lid: str, cid: str, before: dict, action: str) -> dict:
    """Put back the exact prior state of the row: tier, contradictions, absorbed, falsify_if, last_verified, and
    (confirm) the evidence list without the entry this correction added."""
    now = _row(conn, lid)
    if now is None:
        raise CorrectionError(409, "the claim is gone")
    falsify = before.get("falsify_if")
    if before.get("falsify_len") is not None and before["falsify_len"] > _FALSIFY_KEEP:
        falsify = (now["falsify_if"] or "")[:before["falsify_len"]]    # the writers only append: cut back
    evidence = now["evidence"]
    if action == "confirm":
        evidence = [e for e in evidence if not (e.get("kind") == "user_confirm" and e.get("ref") == cid)]
        if before.get("evidence_dropped"):
            evidence = [before["evidence_dropped"]] + evidence
    app_write(conn, "UPDATE mycelium_landmarks SET tier = ?, contradictions = ?, absorbed = ?, falsify_if = ?, "
              "evidence = ?, last_verified = ?, is_permanent = ? WHERE landmark_id = ?",
              (before["tier"], before["contradictions"], 1 if before["absorbed"] else None, falsify,
               json.dumps(evidence), before.get("last_verified"), before.get("is_permanent", now["permanent"]), lid))
    app_flush()
    restored = _row(conn, lid)
    if restored is not None:
        _tap(lid, restored, restored["absorbed"])
    return restored


def undo(conn, correction_id: Any) -> dict:
    if not isinstance(correction_id, str) or not _ID_RE.match(correction_id):
        raise CorrectionError(404, "unknown correction")
    return _on_lane(lambda: _undo_job(conn, correction_id))


def _undo_job(conn, correction_id: str) -> dict:
    _prepare(conn)
    found = next((e for fam, lab in _ACTIONS.values() if (e := _find_event(conn, fam, lab, correction_id))), None)
    if found is None:
        raise CorrectionError(404, "unknown correction")
    ts, payload = found[1], json.loads(found[2])
    if _find_event(conn, *_UNDONE, correction_id) is not None:
        raise CorrectionError(409, "already undone")
    if _now() > ts + UNDO_WINDOW_S:
        raise CorrectionError(409, "the undo window is over")
    lid, action = payload["landmark_id"], payload["action"]
    after = _restore(conn, lid, correction_id, payload["before"], action)
    _emit(conn, *_UNDONE, {"correction_id": correction_id, "action": action, "landmark_id": lid})
    logger.info("[memory_corrections] undone correction=%s action=%s landmark=%s", correction_id, action, lid)
    return {"undone": True, "landmark_id": lid, "after": _shown(after)}


# -- list -------------------------------------------------------------------------------------------
def list_corrections(conn, limit: int = LIST_LIMIT_DEFAULT) -> dict:
    """Newest first. Reads the correction events by (family, label): SEARCH on idx_memory_events_label."""
    limit = max(1, min(int(limit), LIST_LIMIT_MAX))
    app_flush()
    rows: list[tuple[float, dict]] = []
    for family, label in _ACTIONS.values():
        # PLAN -> SEARCH memory_events USING INDEX idx_memory_events_label (family=? AND label=?) + TEMP B-TREE
        for ts, payload in conn.execute(
                "SELECT ts, payload FROM memory_events WHERE family = ? AND label = ? AND instr(payload, ?) > 0 "
                "ORDER BY ts DESC LIMIT ?", (family, label, '"correction_id"', limit)):
            try:
                rows.append((ts, json.loads(payload)))
            except (ValueError, TypeError):
                continue
    rows.sort(key=lambda r: r[0], reverse=True)
    rows = rows[:limit]
    undone: set[str] = set()
    if rows:
        # PLAN -> SEARCH memory_events USING INDEX idx_memory_events_label (family=? AND label=?)
        for (payload,) in conn.execute(
                "SELECT payload FROM memory_events WHERE family = ? AND label = ? AND ts >= ?",
                (*_UNDONE, rows[-1][0])):
            try:
                undone.add(json.loads(payload).get("correction_id"))
            except (ValueError, TypeError, AttributeError):
                continue
    out = []
    for ts, p in rows:
        # PLAN -> SEARCH mycelium_landmarks USING INDEX sqlite_autoindex_mycelium_landmarks_1 (landmark_id=?)
        t = conn.execute("SELECT micro_abstract_text, label FROM mycelium_landmarks WHERE landmark_id = ?",
                         (p.get("landmark_id"),)).fetchone()
        out.append({"correction_id": p.get("correction_id"), "ts": ts, "action": p.get("action"),
                    "target": p.get("target"), "landmark_id": p.get("landmark_id"),
                    "claim": clip((t[0] or (t[1] or "").replace("_", " ")) if t else "", _CLAIM_TEXT),
                    "undone": p.get("correction_id") in undone, "undo_until": ts + UNDO_WINDOW_S})
    return {"corrections": out}
