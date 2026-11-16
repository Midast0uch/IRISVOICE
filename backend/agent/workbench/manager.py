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

from .client import WorkbenchClient, resolve_interpreter

logger = logging.getLogger(__name__)

IDLE_END_S = 600.0
MAX_LIVE = 2
BUDGET_BYTES = 768 << 20      # process-wide RSS of all live workbenches (whole trees)
NEW_WORKBENCH_BYTES = 30 << 20  # what a fresh interpreter adds, counted against the budget


class WorkbenchCapReached(RuntimeError):
    """All live slots hold a busy Workbench; the new conversation is refused."""


class WorkbenchBudgetReached(WorkbenchCapReached):
    """The live workbenches hold the memory budget and every one is busy."""

    case = "workbench_budget"


WorkbenchCapReached.case = "workbench_cap"


class _Entry:
    __slots__ = ("client", "workdir", "last_used")

    def __init__(self, client: WorkbenchClient, workdir: str):
        self.client, self.workdir, self.last_used = client, workdir, time.monotonic()


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


class WorkbenchManager:
    def __init__(self, idle_s: float = IDLE_END_S, max_live: int = MAX_LIVE, budget_bytes: int = BUDGET_BYTES,
                 reap_every_s: Optional[float] = None, resolver=resolve_interpreter):
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
                        "cap_refused": 0, "budget_evicted": 0, "budget_refused": 0, "workdir_changed": 0, "closed": 0, "start_failed": 0}

    # --- lookup / start ------------------------------------------------------
    def workbench_for(self, conversation_id: str, workdir: str) -> Optional[WorkbenchClient]:
        """The conversation's live Workbench (started on first use), or None when no
        interpreter exists (counted `unavailable`). Raises WorkbenchCapReached when
        every slot is busy. Blocking (process start): call from a worker thread."""
        wd = _norm(workdir)
        with self._lock:
            ent = self._entries.get(conversation_id)
            if ent is not None and (ent.workdir != wd or not ent.client.alive):
                moved = ent.workdir != wd
                if moved:
                    self._counts["workdir_changed"] += 1
                self._end(conversation_id, "workdir changed" if moved else "process dead")
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
            self._entries[conversation_id] = _Entry(client, wd)
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
            self._end(oldest, f"evicted for the {kind} (oldest idle)")

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

    # --- ending --------------------------------------------------------------
    def _end(self, conversation_id: str, why: str) -> None:
        ent = self._entries.pop(conversation_id, None)
        if ent is None:
            return
        logger.info("[Workbench][%s] ending: %s", ent.client.incarnation[:8] or "-", why)
        try:
            ent.client.close()
        except Exception as exc:  # noqa: BLE001 - never fail the caller
            logger.error("[Workbench] close failed (%s): %s", conversation_id, exc)

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
        with self._lock:
            for cid, e in list(self._entries.items()):
                if not e.client.alive:
                    self._end(cid, "process dead")
                elif not e.client.busy and now - e.last_used > self._idle_s:
                    self._counts["idle_ended"] += 1
                    self._end(cid, f"idle > {self._idle_s:g}s")
                    n += 1
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


def get_manager() -> WorkbenchManager:
    """The process-wide manager. Registers its close_all at interpreter exit."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = WorkbenchManager()
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

    client = (manager or get_manager()).client_for_incarnation(inc)
    if client is None:
        return gone("the workbench that held this value has ended (variables are lost)")
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
