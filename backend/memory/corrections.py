"""Memory corrections v1 (MEMORY-SURFACE-BUILD.md section 5; MEMORY-UX-PLAN.md section 11 decision 2).

  POST /api/memory/correct        {action, target, reason?, confirm?}
  POST /api/memory/correct/undo   {correction_id}
  GET  /api/memory/corrections?limit=

  target "claim:<landmark_id>"      confirm | wrong | forget | pin
  target "pin:<pin_id>"             unpin | hold | release
  target "turn:<conv>:<turn>"       pin
  target "artifact:<document_id>"   pin
  target "strand:<id>"              forget_learned | purge (purge needs confirm == the strand id)

The user says a claim is right, wrong or to be forgotten. Each correction is USER evidence:

  confirm  one `user_confirm` evidence entry (landmark.add_landmark_evidence; it re-derives the tier)
  wrong    one contradiction (landmark.contradict_landmark); a proven claim drops to 'candidate'
  forget   absorbed = 1 and " | dissolved: forgotten by you" in falsify_if - Kyudo's own absorb
           (integrity._dissolve). The row is never deleted; recall reads `absorbed IS NULL` only.

Pins go through the pin store's own methods (pin_store.PinStore: add / link / delete / update / restore). "Held in
context" has no column: the pin carries the tag "held" (surface_queries reads "held" or "context"), so hold adds the
tag and release removes both. An unpin keeps the whole pin and its link rows in its event, so undo puts the SAME pin
back (a pin too big for the event budget is refused, never dropped without a way back).

A strand's "forget what IRIS learned here" absorbs the claims whose ONLY evidence came from it (evidence `session`
== the strand or its conversation; the suffix names the strand) and types ONE marker event. Recall leaves the
strand's memory out while a marker is not undone: `forgotten_strands` is read at the recall chokepoint
(ontology_recall.filtered_chain_recall / chain_timeline). The events are kept for history.
A purge rewrites the TEXT of the strand's rows (memory_events payload strings, memory_chain content / insight /
result, episodes task_summary / full_content) to "[removed by you]"; ids, links, timestamps and structure stay, so every
reference stays valid. It deletes nothing, needs the strand id typed again, and cannot be undone.

Every correction types ONE memory event (evidence "user") and the event IS the record: its payload holds the
prior state, so undo needs no table (CONFIRMATION | CORRECTION | CLAIM_FORGOTTEN | PIN_CORRECTED |
STRAND_LEARNING_FORGOTTEN | STRAND_PURGED; undo = CORRECTION_UNDONE).
All writes go through db.app_write (the one writer) and run ON lane("memory_events") - the lane that already types
the promotion a confirm causes - so a correction never races another writer on the shared connection; the request
waits for the job's answer (a click, not the answer path). A read of a row we decide on follows an app_flush.
A claim absorbed by a MERGE is corrected on its survivor (mycelium_landmark_merges, bounded chain, as
surface_queries.claim follows it); a claim absorbed by forget or dissolved has no survivor: 409.
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
from backend.memory.pin_store import PinStore
from backend.memory.surface_queries import MERGE_HOPS, clip, pretty_thread
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

_CLAIM_ACTIONS = ("confirm", "wrong", "forget")
_PIN_ACTIONS = ("unpin", "hold", "release")
_ACTIONS = {"confirm": ("feedback", "CONFIRMATION"), "wrong": ("feedback", "CORRECTION"),
            "forget": ("memory", "CLAIM_FORGOTTEN"),
            "pin": ("memory", "PIN_CORRECTED"), "unpin": ("memory", "PIN_CORRECTED"),
            "hold": ("memory", "PIN_CORRECTED"), "release": ("memory", "PIN_CORRECTED"),
            "forget_learned": ("memory", "STRAND_LEARNING_FORGOTTEN"), "purge": ("memory", "STRAND_PURGED")}
_LABELS = tuple(dict.fromkeys(_ACTIONS.values()))     # one (family, label) per event kind: the reads below search each
_UNDONE = ("feedback", "CORRECTION_UNDONE")
# which actions a target kind takes (the kind is the text before the first ":")
_TARGET_ACTIONS = {"claim": _CLAIM_ACTIONS + ("pin",), "pin": _PIN_ACTIONS, "turn": ("pin",), "artifact": ("pin",),
                   "strand": ("forget_learned", "purge")}
_PAYLOAD_FIT = 1800          # chars of an event payload kept whole for undo (memory_events._PAYLOAD_MAX is 2000)
_HELD_TAGS = ("held", "context")        # surface_queries reads a pin as held when it carries either tag
REMOVED = "[removed by you]"
# payload keys whose strings are REFERENCES (ids of rows elsewhere); a purge keeps them so every link stays valid
_REF_KEY = re.compile(r"(^|_)(ids?|refs?|step|task|case|trace|landmark|target)$")
_PURGE_BATCH = 500

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
def _parse_target(target: Any) -> tuple[str, str]:
    """(kind, ref) of a target, or a 400. A turn's ref is "<conversation>:<turn>"."""
    if isinstance(target, str) and ":" in target:
        kind, rest = target.split(":", 1)
        if kind == "turn":
            conv, _, turn = rest.partition(":")
            if _ID_RE.match(conv) and _ID_RE.match(turn):
                return kind, rest
        elif kind in _TARGET_ACTIONS and _ID_RE.match(rest):
            return kind, rest
    raise CorrectionError(400, 'target must be "claim:<id>", "pin:<id>", "turn:<conversation>:<turn>", '
                               '"artifact:<id>" or "strand:<id>"')


def correct(conn, action: Any, target: Any, reason: Any = None, confirm: Any = None) -> dict:
    if action not in _ACTIONS:
        raise CorrectionError(400, "action must be one of " + ", ".join(_ACTIONS))
    kind, ref = _parse_target(target)
    if action not in _TARGET_ACTIONS[kind]:
        raise CorrectionError(400, f"{action} does not apply to a {kind}")
    if action == "purge" and confirm != ref:
        raise CorrectionError(400, "a purge needs confirm set to the strand id")
    why = (reason.strip()[:120] if isinstance(reason, str) else "") or ""
    if action in _CLAIM_ACTIONS:
        return _on_lane(lambda: _correct_job(conn, action, target, why))
    if action == "pin":
        return _on_lane(lambda: _pin_create_job(conn, target, kind, ref))
    if action in _PIN_ACTIONS:
        return _on_lane(lambda: _pin_edit_job(conn, action, target, ref))
    if action == "forget_learned":
        return _on_lane(lambda: _strand_forget_job(conn, target, ref))
    return _on_lane(lambda: _strand_purge_job(conn, target, ref))


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
    found = next((e for fam, lab in _LABELS if (e := _find_event(conn, fam, lab, correction_id))), None)
    if found is None:
        raise CorrectionError(404, "unknown correction")
    ts, payload = found[1], json.loads(found[2])
    action = payload["action"]
    if action == "purge":
        raise CorrectionError(409, "a purge cannot be undone")
    if _find_event(conn, *_UNDONE, correction_id) is not None:
        raise CorrectionError(409, "already undone")
    if _now() > ts + UNDO_WINDOW_S:
        raise CorrectionError(409, "the undo window is over")
    if action in _CLAIM_ACTIONS:
        lid = payload["landmark_id"]
        out = {"undone": True, "landmark_id": lid,
               "after": _shown(_restore(conn, lid, correction_id, payload["before"], action))}
    elif action == "forget_learned":
        out = _strand_unforget(conn, payload)
    else:
        out = _pin_undo(conn, payload)
    _emit(conn, *_UNDONE, {"correction_id": correction_id, "action": action, "target": payload.get("target"),
                           "landmark_id": payload.get("landmark_id")})
    logger.info("[memory_corrections] undone correction=%s action=%s target=%s", correction_id, action,
                payload.get("target"))
    return out


# -- list -------------------------------------------------------------------------------------------
def list_corrections(conn, limit: int = LIST_LIMIT_DEFAULT) -> dict:
    """Newest first. Reads the correction events by (family, label): SEARCH on idx_memory_events_label."""
    limit = max(1, min(int(limit), LIST_LIMIT_MAX))
    app_flush()
    rows: list[tuple[float, dict]] = []
    for family, label in _LABELS:
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
        target = p.get("target") or ""
        if p.get("landmark_id"):
            # PLAN -> SEARCH mycelium_landmarks USING INDEX sqlite_autoindex_mycelium_landmarks_1 (landmark_id=?)
            t = conn.execute("SELECT micro_abstract_text, label FROM mycelium_landmarks WHERE landmark_id = ?",
                             (p.get("landmark_id"),)).fetchone()
            what = (t[0] or (t[1] or "").replace("_", " ")) if t else ""
        elif target.startswith("strand:"):
            what = pretty_thread(target[7:])
        else:
            what = p.get("title") or ""         # a pin: the title kept in its event
        out.append({"correction_id": p.get("correction_id"), "ts": ts, "action": p.get("action"),
                    "target": p.get("target"), "landmark_id": p.get("landmark_id"),
                    "claim": clip(what, _CLAIM_TEXT), "undone": p.get("correction_id") in undone,
                    "undo_until": None if p.get("action") == "purge" else ts + UNDO_WINDOW_S})
    return {"corrections": out}


# -- pins -------------------------------------------------------------------------------------------
_PIN_LINKS_MAX = 50          # link rows an unpin keeps for its undo; more and the unpin is refused (409)
_PIN_LINK_COLS = "link_id, source_type, source_id, target_type, target_id, relationship, weight, created_at"


def _fits(payload: dict, what: str) -> None:
    """The event payload is the record: it must stay whole (memory_events._bounded_json would replace a long one by
    a truncated head and undo would find nothing). Checked BEFORE the first write of a correction."""
    if len(json.dumps(payload, ensure_ascii=False, default=str)) > _PAYLOAD_FIT:
        raise CorrectionError(409, f"{what} is too big to keep for an undo, so it was not changed")


def _pin_state(pin) -> dict:
    return {"held": bool(set(_HELD_TAGS) & set(pin.tags)), "exists": True}


def _pin_links(conn, pin_id: str) -> list[dict]:
    # PLAN -> MULTI-INDEX OR: SEARCH mycelium_pin_links USING INDEX idx_pin_links_source (source_type=? AND source_id=?)
    #                         and USING INDEX idx_pin_links_target (target_type=? AND target_id=?)
    cur = conn.execute(f"SELECT {_PIN_LINK_COLS} FROM mycelium_pin_links "
                       "WHERE (source_type = 'pin' AND source_id = ?) OR (target_type = 'pin' AND target_id = ?) LIMIT ?",
                       (pin_id, pin_id, _PIN_LINKS_MAX + 1))
    names = [d[0] for d in cur.description]
    rows = [dict(zip(names, r)) for r in cur.fetchall()]
    if len(rows) > _PIN_LINKS_MAX:
        raise CorrectionError(409, "this pin has too many links to keep for an undo, so it was not changed")
    return rows


def _pin_subject(conn, kind: str, ref: str) -> tuple[str, str, str, Optional[str]]:
    """What a new pin holds: (title, link target type, link target id, landmark id or None). 404 / 409 when
    nothing is there to pin."""
    if kind == "claim":
        lid = _survivor(conn, ref)
        # PLAN -> SEARCH mycelium_landmarks USING INDEX sqlite_autoindex_mycelium_landmarks_1 (landmark_id=?)
        t = conn.execute("SELECT micro_abstract_text, label FROM mycelium_landmarks WHERE landmark_id = ?",
                         (lid,)).fetchone()
        return clip((t[0] or (t[1] or "").replace("_", " ")) if t else lid, 80), "landmark", lid, lid
    if kind == "turn":
        conv, turn = ref.split(":", 1)
        # A turn's events carry episode_id "<conversation>:<turn>" (strand_ids.conversation_row_ids); older rows the bare turn.
        # PLAN -> SEARCH memory_events USING INDEX idx_memory_events_episode (episode_id=?) (both statements)
        hit = (conn.execute("SELECT 1 FROM memory_events WHERE episode_id = ? LIMIT 1", (ref,)).fetchone()
               or conn.execute("SELECT 1 FROM memory_events WHERE episode_id = ? AND thread_id = ? LIMIT 1",
                               (turn, conv)).fetchone())
        if hit is None:
            raise CorrectionError(404, "unknown turn")
        return f"Turn {turn}", "turn", ref, None
    # PLAN -> SEARCH document_data USING INDEX sqlite_autoindex_document_data_1 (document_id=?)
    try:
        row = conn.execute("SELECT title FROM document_data WHERE document_id = ?", (ref,)).fetchone()
    except sqlite3.OperationalError:               # a store whose documents have no title column
        try:
            row = (None,) if conn.execute("SELECT 1 FROM document_data WHERE document_id = ?", (ref,)).fetchone() else None
        except sqlite3.OperationalError:
            row = None
    if row is None:
        raise CorrectionError(404, "unknown artifact")
    return clip(row[0] or f"artifact {ref[:8]}", 80), "artifact", ref, None


def _pin_create_job(conn, target: str, kind: str, ref: str) -> dict:
    _prepare(conn)
    title, link_type, link_id, lid = _pin_subject(conn, kind, ref)
    store = PinStore(conn)
    # PLAN -> SEARCH mycelium_pin_links USING INDEX idx_pin_links_target (target_type=? AND target_id=?)
    for (src,) in conn.execute("SELECT source_id FROM mycelium_pin_links WHERE target_type = ? AND target_id = ? "
                               "AND source_type = 'pin' AND relationship = 'references' LIMIT 20", (link_type, link_id)):
        if store.get(src) is not None:
            raise CorrectionError(409, "this is already pinned")
    cid = "cor-" + uuid.uuid4().hex[:12]
    pin_id = store.add(title=title, pin_type="note", tags=["user", kind])
    store.link(pin_id, link_id, "references", source_type="pin", target_type=link_type)
    app_flush()
    before, after = {"held": False, "exists": False}, {"held": False, "exists": True}
    payload = {"correction_id": cid, "action": "pin", "target": target, "pin_id": pin_id, "title": title,
               "before": before, **({"landmark_id": lid} if lid else {})}
    try:
        _, ts = _emit(conn, *_ACTIONS["pin"], payload)
    except CorrectionError:
        store.delete(pin_id)                                   # no event = no record = no change
        app_flush()
        raise
    logger.info("[memory_corrections] correction=%s action=pin target=%s pin=%s", cid, target, pin_id)
    return {"correction_id": cid, "action": "pin", "target": target, "pin_id": pin_id,
            "before": before, "after": after, "undo_until": ts + UNDO_WINDOW_S}


def _pin_edit_job(conn, action: str, target: str, pin_id: str) -> dict:
    _prepare(conn)
    store = PinStore(conn)
    pin = store.get(pin_id)
    if pin is None:
        raise CorrectionError(404, "unknown pin")
    prior = _pin_state(pin)
    cid = "cor-" + uuid.uuid4().hex[:12]
    if action == "hold":
        if prior["held"]:
            raise CorrectionError(409, "this pin is already held")
        before_full = {**prior, "tags": list(pin.tags), "updated_at": pin.updated_at}
    elif action == "release":
        if not prior["held"]:
            raise CorrectionError(409, "this pin is not held")
        before_full = {**prior, "tags": list(pin.tags), "updated_at": pin.updated_at}
    else:
        before_full = {**prior, "snapshot": {"pin": pin.to_dict(), "links": _pin_links(conn, pin_id)}}
    payload = {"correction_id": cid, "action": action, "target": target, "pin_id": pin_id,
               "title": clip(pin.title, 80), "before": before_full}
    _fits(payload, "this pin")
    if action == "hold":
        store.update(pin_id, tags=[*pin.tags, "held"])
    elif action == "release":
        store.update(pin_id, tags=[t for t in pin.tags if t not in _HELD_TAGS])
    else:
        store.delete(pin_id)
    app_flush()
    now = store.get(pin_id)
    after = _pin_state(now) if now is not None else {"held": False, "exists": False}
    try:
        _, ts = _emit(conn, *_ACTIONS[action], payload)
    except CorrectionError:
        _pin_put_back(store, before_full, action, pin_id)      # no event = no record = no change
        raise
    logger.info("[memory_corrections] correction=%s action=%s pin=%s held %s -> %s", cid, action, pin_id,
                prior["held"], after["held"])
    return {"correction_id": cid, "action": action, "target": target, "pin_id": pin_id,
            "before": {"held": prior["held"], "exists": True}, "after": after, "undo_until": ts + UNDO_WINDOW_S}


def _pin_put_back(store: PinStore, before: dict, action: str, pin_id: str) -> bool:
    """The pin as it was before ``action``. False when it cannot be put back (the pin is gone, or the id is taken)."""
    if action == "pin":                                        # the undo of a pin is its removal
        return store.delete(pin_id)
    if action == "unpin":
        return store.restore(before["snapshot"]["pin"], before["snapshot"]["links"])
    return store.update(pin_id, tags=before["tags"], updated_at=before["updated_at"])


def _pin_undo(conn, payload: dict) -> dict:
    action, pin_id = payload["action"], payload["pin_id"]
    store = PinStore(conn)
    if not _pin_put_back(store, payload["before"], action, pin_id):
        raise CorrectionError(409, "a pin with this id exists again" if action == "unpin" else "the pin is gone")
    app_flush()
    b = payload["before"]
    return {"undone": True, "pin_id": pin_id, "after": {"held": b["held"], "exists": b["exists"]}}


# -- strands ----------------------------------------------------------------------------------------
_STRAND_FORGET = _ACTIONS["forget_learned"]
_MARKS_MAX = 500             # forget markers read at once (a user forgets a handful of strands, not hundreds)


def _strand_ids(conn, sid: str) -> list[str]:
    """The ids a strand's rows and evidence carry: its own and, when it is a session of ONE conversation, that
    conversation (strand_ids.resolve_strand: ambiguous sessions resolve to nothing, never a guess)."""
    from backend.memory.strand_ids import resolve_strand

    ids = [sid]
    try:
        conv = resolve_strand(sid, conn)
    except Exception as exc:  # noqa: BLE001 - a lookup that fails leaves the strand's own id
        logger.warning("[memory_corrections] strand=%s conversation lookup failed: %s", sid, exc)
        conv = None
    if conv and conv not in ids:
        ids.append(conv)
    return ids


def _strand_known(conn, ids: list[str]) -> bool:
    """Does the memory hold anything of this strand? Three indexed single-row reads per id."""
    for i in ids:
        # PLAN -> SEARCH memory_events USING COVERING INDEX idx_memory_events_thread_ts (thread_id=?)
        if conn.execute("SELECT 1 FROM memory_events WHERE thread_id = ? LIMIT 1", (i,)).fetchone():
            return True
        # PLAN -> SEARCH memory_chain USING COVERING INDEX idx_memory_chain_thread (thread_id=?)
        if conn.execute("SELECT 1 FROM memory_chain WHERE thread_id = ? LIMIT 1", (i,)).fetchone():
            return True
        try:
            # PLAN -> SEARCH episodes USING COVERING INDEX idx_ep_session (session_id=?)
            if conn.execute("SELECT 1 FROM episodes WHERE session_id = ? LIMIT 1", (i,)).fetchone():
                return True
        except sqlite3.OperationalError:
            pass
    return False


def _events_of(conn, ids: list[str]) -> int:
    # PLAN -> SEARCH memory_events USING COVERING INDEX idx_memory_events_thread_ts (thread_id=?)
    return sum(conn.execute("SELECT COUNT(*) FROM memory_events WHERE thread_id = ?", (i,)).fetchone()[0] for i in ids)


def forgotten_strands(conn) -> frozenset:
    """The thread ids whose learning the user told IRIS to forget and did not undo. Recall leaves their memory
    out (ontology_recall.filtered_chain_recall / chain_timeline). Two bounded searches on the label index; never
    raises: a failed read leaves recall as it was, and says so."""
    try:
        # PLAN -> SEARCH memory_events USING INDEX idx_memory_events_label (family=? AND label=?)
        marks = [json.loads(p) for (p,) in conn.execute(
            "SELECT payload FROM memory_events WHERE family = ? AND label = ? LIMIT ?", (*_STRAND_FORGET, _MARKS_MAX))]
        if not marks:
            return frozenset()
        # PLAN -> SEARCH memory_events USING INDEX idx_memory_events_label (family=? AND label=?)
        undone = {json.loads(p).get("correction_id") for (p,) in conn.execute(
            "SELECT payload FROM memory_events WHERE family = ? AND label = ? AND instr(payload, ?) > 0 LIMIT ?",
            (*_UNDONE, '"action": "forget_learned"', _MARKS_MAX))}
        return frozenset(i for m in marks if m.get("correction_id") not in undone
                         for i in (m.get("session_ids") or []) if isinstance(i, str))
    except Exception as exc:  # noqa: BLE001 - recall must still answer
        logger.warning("[memory_corrections] forgotten strands not read (recall is unfiltered): %s", exc)
        return frozenset()


def _learned_only_here(conn, ids: list[str]) -> list[tuple[str, Optional[str]]]:
    """(landmark_id, falsify_if) of the LIVE claims whose every evidence entry came from one of ``ids`` (and that have
    at least one). The evidence is a JSON column, so this is one SCAN of mycelium_landmarks (3.3k rows live)
    narrowed by instr; the exact test is made in Python."""
    where = " OR ".join("instr(evidence, ?) > 0" for _ in ids)
    out = []
    for lid, raw, falsify in conn.execute(
            f"SELECT landmark_id, evidence, falsify_if FROM mycelium_landmarks WHERE absorbed IS NULL AND ({where}) "
            "LIMIT 2000", ids):
        try:
            entries = json.loads(raw or "[]")
        except (ValueError, TypeError):
            continue
        if entries and all(isinstance(e, dict) and e.get("session") in ids for e in entries):
            out.append((lid, falsify))
    return out


def _forget_suffix(sid: str) -> str:
    return f" | dissolved: {FORGET_REASON} (strand {sid})"


def _strand_forget_job(conn, target: str, sid: str) -> dict:
    _prepare(conn)
    ids = _strand_ids(conn, sid)
    if not _strand_known(conn, ids):
        raise CorrectionError(404, "unknown strand")
    claims = _learned_only_here(conn, ids)
    marked = _events_of(conn, ids)
    was_marked = bool(set(ids) & forgotten_strands(conn))
    shown_before = {"claims_absorbed": 0, "events_marked": marked if was_marked else 0}
    cid = "cor-" + uuid.uuid4().hex[:12]
    payload = {"correction_id": cid, "action": "forget_learned", "target": target, "strand_id": sid,
               "session_ids": ids,
               "before": {"claim_ids": [c[0] for c in claims], "null_prior_ids": [c[0] for c in claims if c[1] is None],
                          "shown": shown_before}}
    _fits(payload, "what this strand taught")
    for lid, _ in claims:
        app_write(conn, "UPDATE mycelium_landmarks SET absorbed = 1, falsify_if = COALESCE(falsify_if, '') || ? "
                  "WHERE landmark_id = ? AND absorbed IS NULL", (_forget_suffix(sid), lid))
        memory_live.landmark_update(lid, "dissolved")
    app_flush()
    try:
        _, ts = _emit(conn, *_ACTIONS["forget_learned"], payload)
    except CorrectionError:
        _strand_restore(conn, payload)                         # no event = no record = no change
        raise
    logger.info("[memory_corrections] correction=%s action=forget_learned strand=%s claims=%d events=%d", cid, sid,
                len(claims), marked)
    return {"correction_id": cid, "action": "forget_learned", "target": target, "before": shown_before,
            "after": {"claims_absorbed": len(claims), "events_marked": marked}, "undo_until": ts + UNDO_WINDOW_S}


def _strand_restore(conn, payload: dict) -> int:
    """Put back the claims a forget absorbed: absorbed = NULL and the falsify_if it had (the suffix is the tail; a
    claim whose tail is not ours any more is left as it is). Returns how many were restored."""
    sid, before = payload["strand_id"], payload["before"]
    suffix, nulls, restored = _forget_suffix(sid), set(before["null_prior_ids"]), 0
    for lid in before["claim_ids"]:
        r = conn.execute("SELECT absorbed, falsify_if FROM mycelium_landmarks WHERE landmark_id = ?", (lid,)).fetchone()
        if r is None or not r[0] or not (r[1] or "").endswith(suffix):
            logger.warning("[memory_corrections] strand=%s claim=%s was changed since the forget; left as it is", sid, lid)
            continue
        prior = r[1][:-len(suffix)]
        app_write(conn, "UPDATE mycelium_landmarks SET absorbed = NULL, falsify_if = ? WHERE landmark_id = ?",
                  (None if (lid in nulls and prior == "") else prior, lid))
        restored += 1
    app_flush()
    for lid in before["claim_ids"]:
        row = _row(conn, lid)
        if row is not None and not row["absorbed"]:
            _tap(lid, row, False)
    return restored


def _strand_unforget(conn, payload: dict) -> dict:
    _strand_restore(conn, payload)
    return {"undone": True, "strand_id": payload["strand_id"], "after": payload["before"]["shown"]}


def _scrub(value: Any, key: str = "") -> Any:
    """``value`` with every string replaced by REMOVED, except the strings under a reference key (an id of a row
    elsewhere). Keys, numbers, booleans, nulls and the shape of lists and objects stay."""
    if isinstance(value, str):
        return value if _REF_KEY.search(key) else REMOVED
    if isinstance(value, list):
        return [_scrub(v, key) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v, k) for k, v in value.items()}
    return value


def _purge_events(conn, tid: str) -> int:
    """Rewrite the payload strings of one thread's events, in (ts, event_id) batches. Returns the rows changed."""
    changed, last = 0, (-1.0, "")
    while True:
        # PLAN -> SEARCH memory_events USING INDEX idx_memory_events_thread_ts (thread_id=?) + TEMP B-TREE FOR RIGHT PART OF ORDER BY
        batch = conn.execute("SELECT event_id, ts, payload FROM memory_events WHERE thread_id = ? AND (ts, event_id) > (?, ?) "
                             "ORDER BY ts, event_id LIMIT ?", (tid, *last, _PURGE_BATCH)).fetchall()
        for eid, ts, raw in batch:
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                data = raw                                     # not JSON: the whole value is text
            new = _scrub(data)
            if new != data:
                app_write(conn, "UPDATE memory_events SET payload = ? WHERE event_id = ?",
                          (json.dumps(new, ensure_ascii=False), eid))
                changed += 1
        if len(batch) < _PURGE_BATCH:
            return changed
        last = (batch[-1][1], batch[-1][0])


def _purge_chain(conn, tid: str) -> int:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(memory_chain)")}
    fields = [f for f in ("content", "insight", "result") if f in cols]
    cond = " OR ".join(f"({f} IS NOT NULL AND {f} != '' AND {f} != ?)" for f in fields)
    # PLAN -> SEARCH memory_chain USING INDEX idx_memory_chain_thread (thread_id=?)
    n = conn.execute(f"SELECT COUNT(*) FROM memory_chain WHERE thread_id = ? AND ({cond})",
                     (tid, *([REMOVED] * len(fields)))).fetchone()[0]
    if n:
        sets = ", ".join(f"{f} = CASE WHEN {f} IS NOT NULL AND {f} != '' THEN ? ELSE {f} END" for f in fields)
        app_write(conn, f"UPDATE memory_chain SET {sets} WHERE thread_id = ? AND ({cond})",
                  (*([REMOVED] * len(fields)), tid, *([REMOVED] * len(fields))))
    return n


def _purge_episodes(conn, sid: str) -> int:
    fields = ("task_summary", "full_content")
    cond = " OR ".join(f"({f} IS NOT NULL AND {f} != '' AND {f} != ?)" for f in fields)
    try:
        # PLAN -> SEARCH episodes USING INDEX idx_ep_session (session_id=?)
        n = conn.execute(f"SELECT COUNT(*) FROM episodes WHERE session_id = ? AND ({cond})",
                         (sid, REMOVED, REMOVED)).fetchone()[0]
    except sqlite3.OperationalError:                           # a store with no episodes table
        return 0
    if n:
        sets = ", ".join(f"{f} = CASE WHEN {f} IS NOT NULL AND {f} != '' THEN ? ELSE {f} END" for f in fields)
        app_write(conn, f"UPDATE episodes SET {sets} WHERE session_id = ? AND ({cond})",
                  (REMOVED, REMOVED, sid, REMOVED, REMOVED))
    return n


def _strand_purge_job(conn, target: str, sid: str) -> dict:
    _prepare(conn)
    ids = _strand_ids(conn, sid)
    if not _strand_known(conn, ids):
        raise CorrectionError(404, "unknown strand")
    rows = {"memory_events": 0, "memory_chain": 0, "episodes": 0}
    for i in ids:
        rows["memory_events"] += _purge_events(conn, i)
        rows["memory_chain"] += _purge_chain(conn, i)
        rows["episodes"] += _purge_episodes(conn, i)
    app_flush()
    cid = "cor-" + uuid.uuid4().hex[:12]
    # the record carries no `before`: nothing is kept to undo with, by design
    _emit(conn, *_ACTIONS["purge"], {"correction_id": cid, "action": "purge", "target": target, "strand_id": sid,
                                     "session_ids": ids, "rows_changed": rows})
    logger.info("[memory_corrections] correction=%s action=purge strand=%s rows=%s", cid, sid, rows)
    return {"correction_id": cid, "action": "purge", "target": target, "before": None,
            "after": {"rows_changed": rows}, "undo_until": None}
