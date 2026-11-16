"""Workbench manager: which conversation owns which child process (CLM-11, AC7/AC8).

One WorkbenchClient per conversation, started lazily at the first run_python, ended on
idle (reaper thread), conversation close, workdir change, or backend exit. At most
`max_live` processes process-wide. Stdlib only; thread-safe.
"""
import atexit
import logging
import os
import re
import threading
import time
from typing import Dict, List, Optional

from . import digest as _digest
from .client import WorkbenchClient, resolve_interpreter

logger = logging.getLogger(__name__)

IDLE_END_S = 600.0
MAX_LIVE = 2
BUDGET_BYTES = 768 << 20      # process-wide RSS of all live workbenches (whole trees)
NEW_WORKBENCH_BYTES = 30 << 20  # what a fresh interpreter adds, counted against the budget


# The spill (T7.10): when a Workbench ends with a live process, the values digest.named
# lists are written as tool_results rows, so `wb:<incarnation>/<name>` still expands. D8: those
# are the brief's declared outputs (a passed check), the `out<n>` refs, or - with no brief - the
# last script's named values; loop temporaries never. Text form, each capped; never the namespace. The row
# id is derived from the ref, so expand needs no index. A crash or hard kill spills nothing.
SPILL_VALUE_CHARS = 32_000   # one spilled value (the store caps a row at 128,000)
SPILL_READ_S = 5.0           # total time one spill may spend reading values from the child
SPILL_WAIT_S = 5.0           # how long close / fresh wait for the writes before they say done
SPILL_TOOL = "wb_spill"


def spill_id(incarnation: str, name: str) -> str:
    return f"wbspill-{incarnation}-{name}"


class StoreSink:
    """Where a spill goes: conversation_store.tool_results (its lane, its caps). Lazy import:
    the package stays stdlib-only until a spill happens."""

    def write(self, conversation_id: str, incarnation: str, name: str, text: str) -> Optional[str]:
        """Queue one row on lane("tool_results") and return its id, or None when refused."""
        from backend import conversation_store as cs

        rid = spill_id(incarnation, name)
        ok = cs.add_tool_result(rid, conversation_id, None, None, None, SPILL_TOOL,
                                _digest.make_ref(incarnation, name), text or "(empty)", min_chars=0)
        return rid if ok else None

    def wait(self, rid: str, wait_s: float) -> bool:
        """True when the row is written (get_tool_result waits for that id's own write)."""
        from backend import conversation_store as cs

        return cs.get_tool_result(rid, wait_s=max(0.0, wait_s)) is not None

    def read(self, incarnation: str, name: str) -> Optional[dict]:
        from backend import conversation_store as cs

        return cs.get_tool_result(spill_id(incarnation, name), wait_s=2.0)


class WorkbenchCapReached(RuntimeError):
    """All live slots hold a busy Workbench; the new conversation is refused."""


class WorkbenchBudgetReached(WorkbenchCapReached):
    """The live workbenches hold the memory budget and every one is busy."""

    case = "workbench_budget"


WorkbenchCapReached.case = "workbench_cap"


class WorkbenchScopeRefused(WorkbenchCapReached):
    """Personal mode: the workdir is at or under the IRIS repo. The bridge's existing
    WorkbenchCapReached handler turns it into {"success": False, "case": "workbench_scope"}."""

    case = "workbench_scope"


class _Entry:
    __slots__ = ("client", "workdir", "last_used", "mode")

    def __init__(self, client: WorkbenchClient, workdir: str, mode: Optional[str] = None):
        self.client, self.workdir, self.last_used, self.mode = client, workdir, time.monotonic(), mode


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


# The directory that holds backend/: the IRIS repo. Personal mode never works inside it.
IRIS_REPO_ROOT = _norm(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))


def _under_repo(wd: str) -> bool:
    try:
        return os.path.commonpath([wd, IRIS_REPO_ROOT]) == IRIS_REPO_ROOT
    except ValueError:  # different drives
        return False


class WorkbenchManager:
    def __init__(self, idle_s: float = IDLE_END_S, max_live: int = MAX_LIVE, budget_bytes: int = BUDGET_BYTES,
                 reap_every_s: Optional[float] = None, resolver=resolve_interpreter, mode_of=None,
                 sink=None):
        # mode_of() -> "personal" | "developer"; None = no scope rule (get_manager() sets it).
        # sink: where a spill goes (StoreSink); None = no spill (the stand-alone tests).
        self._mode_of = mode_of
        self._sink = sink
        self._idle_s = idle_s
        self._max_live = max_live
        self._budget = budget_bytes
        self._reap_every_s = reap_every_s if reap_every_s is not None else max(0.05, min(30.0, idle_s / 4))
        self._resolver = resolver
        self._lock = threading.RLock()
        self._entries: Dict[str, _Entry] = {}
        self._stop = threading.Event()
        self._reaper: Optional[threading.Thread] = None
        self._counts = {"started": 0, "unavailable": 0, "idle_ended": 0, "cap_evicted": 0,
                        "cap_refused": 0, "budget_evicted": 0, "budget_refused": 0, "workdir_changed": 0, "closed": 0, "start_failed": 0,
                        "scope_refused": 0, "mode_changed": 0,
                        "spilled": 0, "spill_refused": 0, "spill_budget": 0, "spill_unconfirmed": 0}

    # --- lookup / start ------------------------------------------------------
    def workbench_for(self, conversation_id: str, workdir: str) -> Optional[WorkbenchClient]:
        """The conversation's live Workbench (started on first use), or None when no
        interpreter exists (counted `unavailable`). Raises WorkbenchCapReached when
        every slot is busy, WorkbenchScopeRefused (a WorkbenchCapReached) in personal mode
        for a workdir at or under the IRIS repo. Blocking (process start): call from a worker thread."""
        wd = _norm(workdir)
        mode = self._mode_of() if self._mode_of else None
        with self._lock:
            ent = self._entries.get(conversation_id)
            if ent is not None and ent.mode != mode:   # a mode change never keeps a workbench
                self._counts["mode_changed"] += 1
                self._end(conversation_id, f"mode changed to {mode}", spill=True)
                ent = None
            if mode == "personal" and _under_repo(wd):
                self._counts["scope_refused"] += 1
                logger.warning("[Workbench][%s] personal mode refuses a workdir inside the IRIS repo", conversation_id)
                raise WorkbenchScopeRefused("personal mode does not run Python inside the IRIS repo; "
                                            "work in a project folder outside it")
            if ent is not None and (ent.workdir != wd or not ent.client.alive):
                moved = ent.workdir != wd
                if moved:
                    self._counts["workdir_changed"] += 1
                self._end(conversation_id, "workdir changed" if moved else "process dead", spill=moved)
                ent = None
            if ent is not None:
                ent.last_used = time.monotonic()
                return ent.client
            exe = self._resolver(workdir)
            if not exe:
                self._counts["unavailable"] += 1
                logger.warning("[Workbench][%s] no interpreter found; unavailable", conversation_id)
                return None
            self._make_room()
            client = WorkbenchClient(exe, workdir)
            try:
                client.start()
            except Exception as exc:  # noqa: BLE001 - counted, reported as unavailable
                self._counts["start_failed"] += 1
                logger.error("[Workbench][%s] start failed: %s", conversation_id, exc)
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass
                return None
            self._entries[conversation_id] = _Entry(client, wd, mode)
            self._counts["started"] += 1
            self._ensure_reaper()
            return client

    def _live_bytes(self) -> int:
        return sum(e.client.rss_bytes() or 0 for e in self._entries.values())

    def _make_room(self) -> None:
        """Before a start: free a slot (cap) and memory (budget), oldest idle first."""
        for cid, e in list(self._entries.items()):   # dead processes free their slot first
            if not e.client.alive:
                self._end(cid, "process dead")
        while self._entries:
            over_cap = len(self._entries) >= self._max_live
            over_budget = (not over_cap) and self._live_bytes() + NEW_WORKBENCH_BYTES > self._budget
            if not over_cap and not over_budget:
                return
            kind = "cap" if over_cap else "budget"
            idle = [(e.last_used, cid) for cid, e in self._entries.items() if not e.client.busy]
            if not idle:
                self._counts[f"{kind}_refused"] += 1
                logger.warning("[Workbench] %s reached and every Workbench is busy", kind)
                exc = WorkbenchCapReached if kind == "cap" else WorkbenchBudgetReached
                raise exc(f"the workbench {kind} is reached ({len(self._entries)} running, all busy)")
            _, oldest = min(idle)
            self._counts[f"{kind}_evicted"] += 1
            self._end(oldest, f"evicted for the {kind} (oldest idle)", spill=True)

    def touch(self, conversation_id: str) -> None:
        with self._lock:
            ent = self._entries.get(conversation_id)
            if ent is not None:
                ent.last_used = time.monotonic()

    def client_for_incarnation(self, incarnation: str) -> Optional[WorkbenchClient]:
        """The live client whose current incarnation is `incarnation`, else None."""
        with self._lock:
            for e in self._entries.values():
                if e.client.alive and e.client.incarnation == incarnation:
                    e.last_used = time.monotonic()
                    return e.client
        return None

    def _bump(self, key: str) -> None:
        with self._lock:                 # an RLock: safe under _end's caller too
            self._counts[key] += 1

    # --- ending --------------------------------------------------------------
    def _spill(self, conversation_id: str, client: WorkbenchClient) -> List[str]:
        """Write the values the digests named as tool_results rows; the ids queued. Reads the
        child (blocking, bounded by SPILL_READ_S); the writes go on the store's lane. Never raises."""
        if self._sink is None or not client.alive:
            return []
        inc = client.incarnation
        ids: List[str] = []
        try:
            deadline = time.monotonic() + SPILL_READ_S
            for name in reversed(_digest.named(inc)):          # newest first: a cut loses the oldest
                if time.monotonic() > deadline:
                    self._bump("spill_budget")
                    logger.warning("[Workbench][%s] spill read budget reached", inc[:8])
                    break
                rep = client.inspect(name, 0, SPILL_VALUE_CHARS)
                if not rep.get("ok") or rep.get("incarnation") != inc:   # deleted, or restarted under us
                    continue
                text, total = rep.get("text") or "", int(rep.get("total") or 0)
                if total > len(text):
                    text += f"\n[spill cut: first {len(text)} of {total} chars]"
                rid = self._sink.write(conversation_id, inc, name, text)
                if rid is None:
                    self._bump("spill_refused")
                    continue
                ids.append(rid)
                self._bump("spilled")
        except Exception as exc:  # noqa: BLE001 - a spill never fails the end
            logger.error("[Workbench][%s] spill failed (%s): %r", inc[:8], conversation_id, exc)
        return ids

    def _await_spill(self, ids: List[str], wait_s: float) -> bool:
        """True when every spill row is written. A timeout is counted and logged, never raised."""
        if not ids or self._sink is None:
            return True
        deadline = time.monotonic() + wait_s
        try:
            for rid in ids:
                if not self._sink.wait(rid, deadline - time.monotonic()):
                    self._bump("spill_unconfirmed")
                    logger.warning("[Workbench] spill row %s not confirmed within %gs", rid, wait_s)
                    return False
        except Exception as exc:  # noqa: BLE001
            self._bump("spill_unconfirmed")
            logger.error("[Workbench] spill wait failed: %r", exc)
            return False
        return True

    def spill_read(self, incarnation: str, name: str) -> Optional[dict]:
        """The spilled row of a ref (`content`, `cut`), or None. Blocking."""
        if self._sink is None:
            return None
        try:
            return self._sink.read(incarnation, name)
        except Exception as exc:  # noqa: BLE001
            logger.error("[Workbench] spill read failed: %r", exc)
            return None

    def _end(self, conversation_id: str, why: str, spill: bool = False) -> List[str]:
        """Close the conversation's Workbench; with `spill`, first write its named values.
        Returns the spill row ids queued (the caller may wait for them)."""
        return self._finish(conversation_id, self._entries.pop(conversation_id, None), why, spill)

    def _finish(self, conversation_id: str, ent: Optional["_Entry"], why: str, spill: bool) -> List[str]:
        """Spill (when asked) and close an entry already removed from the map. Callers that
        can run it OUTSIDE self._lock do: a spill reads the child for up to SPILL_READ_S, and
        under the lock every other conversation's workbench_for would wait for it."""
        if ent is None:
            return []
        logger.info("[Workbench][%s] ending: %s", ent.client.incarnation[:8] or "-", why)
        ids = self._spill(conversation_id, ent.client) if spill else []
        try:
            ent.client.close()
        except Exception as exc:  # noqa: BLE001 - never fail the caller
            logger.error("[Workbench] close failed (%s): %s", conversation_id, exc)
        return ids

    def end_spilled(self, conversation_id: str, why: str, wait_s: float = SPILL_WAIT_S) -> dict:
        """run_python close / fresh: spill, end the process, then wait (bounded) until the
        spill rows are written, so the reply can say done. -> {"ended", "spilled", "confirmed"}."""
        with self._lock:
            ent = self._entries.pop(conversation_id, None)
            if ent is not None:
                self._counts["closed"] += 1
        ids = self._finish(conversation_id, ent, why, spill=True)   # outside the lock
        return {"ended": ent is not None, "spilled": len(ids), "confirmed": self._await_spill(ids, wait_s)}

    def close(self, conversation_id: str) -> bool:
        with self._lock:
            had = conversation_id in self._entries
            if had:
                self._counts["closed"] += 1
                self._end(conversation_id, "conversation closed")
            return had

    def close_all(self) -> None:
        with self._lock:
            for cid in list(self._entries):
                self._end(cid, "backend exit")

    # --- idle reaper ---------------------------------------------------------
    def _ensure_reaper(self) -> None:
        if self._reaper is None or not self._reaper.is_alive():
            self._stop.clear()
            self._reaper = threading.Thread(target=self._reap_loop, name="wb-reaper", daemon=True)
            self._reaper.start()

    def _reap_loop(self) -> None:
        while not self._stop.wait(self._reap_every_s):
            try:
                self.reap_once()
            except Exception as exc:  # noqa: BLE001 - the reaper must not die
                logger.error("[Workbench] reaper error: %s", exc)

    def reap_once(self) -> int:
        now = time.monotonic()
        n = 0
        ending = []
        with self._lock:
            for cid, e in list(self._entries.items()):
                if not e.client.alive:
                    ending.append((cid, self._entries.pop(cid), "process dead", False))
                elif not e.client.busy and now - e.last_used > self._idle_s:
                    self._counts["idle_ended"] += 1
                    ending.append((cid, self._entries.pop(cid), f"idle > {self._idle_s:g}s", True))
                    n += 1
        for cid, e, why, spill in ending:                 # spill + close outside the lock
            self._finish(cid, e, why, spill)
        return n

    def shutdown(self) -> None:
        self._stop.set()
        self.close_all()

    def stats(self) -> dict:
        with self._lock:
            now = time.monotonic()
            conv: List[dict] = [
                {"conversation_id": cid, "pid": e.client.pid, "incarnation": e.client.incarnation,
                 "idle_s": round(now - e.last_used, 1), "busy": e.client.busy}
                for cid, e in self._entries.items()]
            return {"live": len(self._entries), "max_live": self._max_live, "idle_end_s": self._idle_s, "budget_bytes": self._budget,
                    **self._counts, "conversations": conv}


_MANAGER: Optional[WorkbenchManager] = None
_MANAGER_LOCK = threading.Lock()


def _current_mode() -> str:
    from backend.capabilities import CapabilitySet   # lazy: the manager stays stdlib-only at import

    return CapabilitySet.get_mode()


def get_manager() -> WorkbenchManager:
    """The process-wide manager. Registers its close_all at interpreter exit."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = WorkbenchManager(mode_of=_current_mode, sink=StoreSink())
            atexit.register(_MANAGER.close_all)
        return _MANAGER


EXPAND_PAGE_CHARS = 6000
_NAME_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def expand(ref: str, offset: int = 0, page: int = EXPAND_PAGE_CHARS,
           manager: Optional[WorkbenchManager] = None) -> dict:
    """recall_memory(expand="wb:<incarnation>/<name>") -> one page of the value, or a
    NAMED failure: `malformed_ref`, or `workbench_gone` (the incarnation ended, or the
    name no longer exists) with the purpose of the execution that made it. Blocking."""
    from . import digest as _digest

    parsed = _digest.parse_ref(ref)
    if parsed is None or not _NAME_OK.match(parsed[1]):
        return {"success": False, "ref": ref, "case": "malformed_ref",
                "error": "expand takes a reference such as wb:<incarnation>/<name>"}
    inc, name = parsed

    def gone(why: str) -> dict:
        out = {"success": False, "ref": ref, "case": "workbench_gone", "error": why}
        purpose = _digest.origin_of(inc, name)
        if purpose:
            out["purpose"] = purpose
        return out

    mgr = manager or get_manager()
    client = mgr.client_for_incarnation(inc)
    if client is None:
        row = mgr.spill_read(inc, name)
        if row is None:
            return gone("the workbench that held this value has ended (variables are lost)")
        content = row.get("content") or ""
        offset = max(0, int(offset))
        page_text = content[offset:offset + int(page)]
        out = {"success": True, "ref": ref, "chars": len(content), "offset": offset, "content": page_text,
               "spilled": True, "note": "the workbench has ended; this is the text it saved"}
        if offset + len(page_text) < len(content):
            out["next_offset"] = offset + len(page_text)
        return out
    rep = client.inspect(name, offset=max(0, int(offset)), limit=int(page))
    if not rep.get("ok"):
        return gone(f"{name} no longer exists in the workbench"
                    if (rep.get("error") or {}).get("type") in ("NameError", "KeyError")
                    else f"the workbench could not read {name}: {(rep.get('error') or {}).get('message')}")
    text, total = rep.get("text") or "", int(rep.get("total") or 0)
    out = {"success": True, "ref": ref, "chars": total, "offset": offset, "content": text}
    if offset + len(text) < total:
        out["next_offset"] = offset + len(text)
    return out
