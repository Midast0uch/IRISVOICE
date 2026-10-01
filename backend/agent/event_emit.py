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


def submit(owner, fn_name: str, **kwargs) -> None:
    """Run ``memory_events.<fn_name>(conn, ...)`` on lane("memory_events").

    ``owner`` carries ``_memory_interface`` (a kernel); None falls back to the
    process-wide interface. ``fn_name == "emit_event"`` gets the coordinate as
    sigma_from/sigma_to, every other writer (Wave E) gets ``coords=``.
    """
    try:
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

            try:
                from backend.agent.caducean_trajectory import latest_coords_str

                coords = latest_coords_str(mi, kwargs.get("thread_id") or "")
            except Exception:  # noqa: BLE001
                coords = None
            if fn_name == "emit_event":
                _me.ensure_schema(conn)
                kwargs.setdefault("sigma_from", coords)
                kwargs.setdefault("sigma_to", coords)
                _me.emit_event(conn, **kwargs)
            else:
                getattr(_me, fn_name)(conn, coords=coords, **kwargs)

        lane("memory_events").submit(f"memory_events:{fn_name}", _job)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[memory_events] submit %s skipped: %s", fn_name, exc)


def peek_kernel(conversation_id: Optional[str] = None, session_id: Optional[str] = None) -> Any:
    """The live kernel of a conversation (or session), never constructing one."""
    try:
        mod = sys.modules.get("backend.agent.agent_kernel")
        live = getattr(mod, "_agent_kernel_instances", None)
        if not live:
            return None
        if conversation_id and conversation_id in live:
            return live[conversation_id]
        if session_id:
            for k in list(live.values()):
                if getattr(k, "session_id", None) == session_id:
                    return k
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
            owner = peek_kernel(conversation_id, thread_id)
        thread_id = thread_id or getattr(owner, "session_id", None)
        episode_id = episode_id or getattr(owner, "_event_episode_id", None)
        submit(owner, "emit_event", label=label, evidence=evidence, thread_id=thread_id,
               episode_id=episode_id, **kw)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[memory_events] emit %s skipped: %s", label, exc)
