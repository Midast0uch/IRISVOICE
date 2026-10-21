"""One path from a rule chokepoint to the canonical event writer
(docs/Design/EVENT_TAXONOMY.md section 6, build step 2).

A rule emitter (DER split, click-safety verdict, permission answer, reply exit ...)
calls ``emit(owner, "LABEL", ...)``. The write runs on lane("memory_events") with
the mycelium connection: never on the answer path, never raises. The coordinate
(sigma) is read inside the job - the step's physics may land first.

Light on purpose: chokepoints outside the kernel (ask_user, permissions, the
browser gate, the WS bridge) import this, and none of them may pull in the
21k-line kernel just to emit a row. The kernel is only PEEKED at (``sys.modules``);
a kernel that is not loaded cannot have an episode to attach to.
"""
from __future__ import annotations

import logging
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)


def submit(owner, fn_name: str, *, conversation_id: Optional[str] = None, **kwargs) -> None:
    """Run ``memory_events.<fn_name>(conn, ...)`` on lane("memory_events").

    ``owner`` carries ``_memory_interface`` (a kernel); None falls back to the
    process-wide interface. ``fn_name == "emit_event"`` gets the coordinate as
    sigma_from/sigma_to, every other writer (Wave E) gets ``coords=``.
    The rows the job writes are keyed to the owner's conversation (``conversation_id``, else
    ``owner.conversation_id``): thread_id = conversation, episode_id = "<conversation>:<turn>"
    (memory_events.STRAND). Bound here, at submit time: the kernel moves to the next turn.
    """
    try:
        conv = conversation_id or getattr(owner, "conversation_id", None)
        strand = None
        if isinstance(conv, str) and conv:
            sessions = frozenset(
                s for s in (getattr(owner, "session_id", None), getattr(owner, "_turn_session_id", None))
                if isinstance(s, str) and s
            )
            strand = (conv, sessions)
        mi = getattr(owner, "_memory_interface", None)
        if mi is None and owner is None:
            from backend.memory import get_memory_interface

            mi = get_memory_interface()
        if mi is None:
            return
        from backend.agent.ontology_recall import resolve_mycelium_conn
        from backend.utils.durability_queue import lane

        conn = resolve_mycelium_conn(mi)
        if conn is None:
            return

        def _job() -> None:
            from backend.memory import memory_events as _me
            from backend.memory.db import lane_connection

            # This lane's own connection: its scans never hold the shared one
            # the answer path reads on.
            conn_l = lane_connection(conn)
            # The step's transition: where it started (before) and where it landed
            # (coords). Read inside the job, so the step's physics may land first.
            try:
                from backend.agent.caducean_trajectory import latest_transition_str

                before, coords = latest_transition_str(mi, kwargs.get("thread_id") or "")
            except Exception:  # noqa: BLE001
                before, coords = None, None
            token = _me.SIGMA_BEFORE.set(before)
            strand_token = _me.STRAND.set(strand)
            try:
                if fn_name == "emit_event":
                    _me.ensure_schema(conn_l)
                    kwargs.setdefault("sigma_from", before)
                    kwargs.setdefault("sigma_to", coords)
                    _me.emit_event(conn_l, **kwargs)
                else:
                    getattr(_me, fn_name)(conn_l, coords=coords, **kwargs)
            finally:
                _me.STRAND.reset(strand_token)
                _me.SIGMA_BEFORE.reset(token)

        lane("memory_events").submit(f"memory_events:{fn_name}", _job)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[memory_events] submit %s skipped: %s", fn_name, exc)


def peek_kernel(conversation_id: Optional[str] = None, session_id: Optional[str] = None,
                episode_id: Optional[str] = None) -> Any:
    """The live kernel of a conversation (or session), never constructing one. Several
    kernels can run under one session id ("session_iris"); ``episode_id`` picks the one
    whose current turn it is."""
    try:
        mod = sys.modules.get("backend.agent.agent_kernel")
        live = getattr(mod, "_agent_kernel_instances", None)
        if not live:
            return None
        if conversation_id and conversation_id in live:
            return live[conversation_id]
        if session_id:
            same = [k for k in list(live.values()) if getattr(k, "session_id", None) == session_id]
            for k in same:
                if episode_id and getattr(k, "_event_episode_id", None) == episode_id:
                    return k
            if same:
                return same[0]
    except Exception:  # noqa: BLE001
        pass
    return None


def emit(owner, label: str, *, evidence: str = "none", thread_id: Optional[str] = None,
         episode_id: Optional[str] = None, conversation_id: Optional[str] = None,
         **kw) -> None:
    """Emit one rule-labelled event. ``owner`` is the kernel, or None for a
    chokepoint outside it (the kernel is then looked up by conversation/session).
    thread/episode default from the owner's current turn (``_event_episode_id`` is
    ``f"{session}:{turn_id}"``, the same task id Wave E uses). Never raises."""
    try:
        if owner is None:
            owner = peek_kernel(conversation_id, thread_id, episode_id)
        thread_id = thread_id or getattr(owner, "session_id", None)
        episode_id = episode_id or getattr(owner, "_event_episode_id", None)
        submit(owner, "emit_event", conversation_id=conversation_id, label=label, evidence=evidence,
               thread_id=thread_id, episode_id=episode_id, **kw)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[memory_events] emit %s skipped: %s", label, exc)
