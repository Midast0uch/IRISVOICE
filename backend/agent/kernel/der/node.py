# Moved from backend/agent/agent_kernel.py by scripts/kernel_split_check.py move.
# Bodies are byte-identical to the originals (guard: kernel_split_check.py manifest --check).
from __future__ import annotations

import re
import hashlib
import threading
import os
from backend.agent.inference.errors import RateLimitedError
from backend.agent.call_context import (
    CallClass,
    set_call_class,
    restores_call_class,
)
from backend.agent.tool_decision import ToolDecisionBox, Decision, DecisionKind, DispatchResult
from typing import Any, Dict, Optional, List, Callable, Tuple, Sequence
import json
import time
from backend.agent.kernel.base import (
    _CLAIM_LOCKS,
    _CLAIM_LOCKS_GUARD,
    _DER_NODE_QUOTA,
    _DER_PARALLEL,
    _NODE_CLAIMS,
    _SCREEN_CLAIM,
    _step_evidence_cap,
    logger,
)
from backend.agent.kernel.planning import (
    _voice_turn_note,
)


def _node_claim_of(tool: str) -> Optional[str]:
    for _claim, _tools in _NODE_CLAIMS.items():
        if tool in _tools:
            return _claim
    return None

def _node_call_parallel_ok(name: str, params: dict) -> bool:
    """A node call may run side by side with its siblings: no side effect (the
    permission tier, the one authority on that) and no exclusive resource
    (browser page / screen - two calls of one node would wait on its own claim)."""
    from backend.agent.permissions import PermissionTier, classify_tool

    return (_node_claim_of(name) is None
            and classify_tool(name, params) == PermissionTier.READ_ONLY)

def _der_node_load() -> float:
    """Load of the node domain: the share of the node provider's learned rate
    ceiling in use (the router's own rate meter). Never live Sigma (CT-3/4)."""
    _q = _DER_NODE_QUOTA.get("quota")
    if not _q:
        return 0.0
    from backend.agent.phase_manager import get_registry

    return get_registry()._load_fraction(_q)

def _der_node_domain():
    """The ONE phase domain for DER node starts ("execution.der_nodes"): the
    same black box as the Oracle's. It decides WHEN a ready node starts; the
    DAG decided that it is ready. Fail-open: an error starts the node."""
    from backend.agent.phase_domain import get_phase_domain

    return get_phase_domain(
        "execution.der_nodes",
        # A node runs seconds; its first model call is the burst to spread.
        period_s=0.5, max_wait_s=0.5, k=0.6, load_fn=_der_node_load,
    )

_NODE_CORE_TOOLS = frozenset({
    "read_file", "edit_file", "write_file", "run_command",
    "list_directory", "glob_files", "grep_files",
})

def _narrow_node_tools(tools, goal, engine=None, k=None):
    """Advisory narrowing: keep the CORE coding tools + the Oracle's top picks.

    MEASURED 2026-11-06: a node's menu was 17 tools (~14k chars of JSON) on
    every model call, and most calls only need the basic coding tools. The
    Oracle already ranks the same menu for tool_choice. Keeping the core tools
    plus its top picks cuts the payload without removing basic capability.

    Falls back to the FULL list whenever the engine is unavailable or any step
    fails - a narrowing never removes capability it cannot justify. ``k`` (or
    IRIS_NODE_TOOL_MENU_K) <= 0 disables it.
    """
    try:
        if k is None:
            _k_env = os.environ.get("IRIS_NODE_TOOL_MENU_K", "")
            if not _k_env.strip():
                # With the class decision on, the Oracle narrows EVERY call on
                # the step's live state; this goal-only cut would only remove
                # tools for the whole step with no way back (live 2026-11-09:
                # it dropped screenshot_page from a web step). MEASURED
                # 2026-11-09 (c14, 3 runs each, same code): reply 64/26/42 s
                # with the cut, 35/29/64 s without; the cut saves ~21% prompt
                # tokens (median 2742 vs 3330) and costs one d1 call per step.
                # An explicit IRIS_NODE_TOOL_MENU_K still wins.
                from backend.agent.tool_choice_action_class import (
                    class_decision_enabled,
                )

                if class_decision_enabled():
                    return tools
            k = int(_k_env or 12)
        names = [
            t.get("function", {}).get("name") for t in (tools or [])
        ]
        names = [n for n in names if n]
        if k <= 0 or len(names) <= k:
            return tools
        keep = {n for n in names if n in _NODE_CORE_TOOLS}
        if engine is None:
            try:
                from backend.agent.decision_engine import get_decision_engine

                engine = get_decision_engine()
            except Exception:  # noqa: BLE001 - full menu stands
                engine = None
        ranked = []
        if engine is not None:
            ds = engine.decide(
                "tool_choice", names, {"goal": str(goal or "")[:400]}
            )
            if ds is not None and getattr(ds, "distribution", None):
                ranked = [
                    c.name for c in sorted(
                        ds.distribution, key=lambda c: -float(c.prob))
                ]
        if not ranked:
            # no Oracle ranking: never drop a tool for a reason we cannot state
            return tools
        for n in ranked:
            if len(keep) >= k:
                break
            if n in names:
                keep.add(n)
        kept = [t for t in tools if t.get("function", {}).get("name") in keep]
        if kept and len(kept) < len(tools):
            logger.info(
                "[DER] node tool menu narrowed %d -> %d (dropped=%s)",
                len(tools), len(kept), sorted(set(names) - keep),
            )
        return kept or tools
    except Exception as exc:  # noqa: BLE001 - narrowing never breaks a step
        logger.debug("[DER] tool menu narrowing skipped: %r", exc)
        return tools

def _der_start_node(self, item, run_step, inflight, finished, *, verdict, phase) -> None:
    """Start one node on its own thread (parallel nodes, owner 2026-10-04).

    The phase domain "execution.der_nodes" decides WHEN it starts (its
    position on the dial; fail-open). A direct step whose tool drives an
    exclusive resource (browser, screen) claims it for the whole step; a
    node claims lazily at its first such call (_der_run_node). The thread
    boxes (result, success) or the exception and posts the step id to
    ``finished``; the loop settles it with _der_post_step."""
    from backend.agent.resilience import retry_with_backoff_sync

    try:
        from backend.agent.inference.router import quota_key

        _DER_NODE_QUOTA["quota"] = quota_key(self._router.resolve("tool_execution"))
    except Exception:  # noqa: BLE001 - no quota = no load signal (0.0)
        pass
    box: dict = {}

    def _work() -> None:
        _dom = _der_node_domain()
        _tok = None
        _held: List[str] = []
        try:
            _tok = _dom.enter(f"node:{self.conversation_id or 'default'}")
            _claim = _node_claim_of(item.tool or "") if item.tool else None
            if _claim and _der_claim(self, _claim, item):
                _held.append(_claim)
            box["res"] = retry_with_backoff_sync(
                run_step, max_retries=2, base=1.0, cap=4.0,
                label=f"step_{item.step_number}:{item.tool}",
            )
        except BaseException as _step_exc:  # noqa: BLE001 - boxed, settled by the loop
            box["exc"] = _step_exc
        finally:
            for _c in _held:
                _der_release(self, _c)
            if _tok is not None:
                try:
                    _dom.exit(_tok)
                except Exception:  # noqa: BLE001
                    pass
            finished.put(item.step_id)

    _t = threading.Thread(target=_work, daemon=True, name=f"der-node-{item.step_id}")
    inflight[item.step_id] = {"item": item, "box": box, "verdict": verdict,
                              "phase": phase, "t0": time.perf_counter()}
    _t.start()
    logger.info("[DER] node start step=%s in_flight=%d", item.step_id, len(inflight))

def _der_take_finished(self, finished, inflight, block: bool = False,
                       timeout: Optional[float] = None):
    """The next finished node as (item, step_result, step_success, verdict,
    phase), or None (nothing finished / the wait ran out)."""
    import queue as _queue_mod

    try:
        _sid = finished.get(block=block, timeout=timeout if block else None)
    except _queue_mod.Empty:
        return None
    rec = inflight.pop(_sid, None)
    if rec is None:
        return None
    item, box = rec["item"], rec["box"]
    logger.info("[DER] node done step=%s in %.1fs (in_flight=%d)", _sid,
                time.perf_counter() - rec["t0"], len(inflight))
    if "exc" in box:
        _exc = box["exc"]
        # RateLimitedError carries structured context (provider id, retry
        # count) - preserve it verbatim for the ledger (REQ-3 AC4 / REQ-4
        # AC2). Do NOT stringify into a generic message.
        if isinstance(_exc, RateLimitedError):
            logger.warning(
                "[DER] Step %s rate-limited by provider %s after %d attempts "
                "â€” recording FAILED (no DER-layer retry)",
                item.step_number, _exc.provider_id, _exc.attempts,
            )
            return (item, f"RateLimitedError(provider={_exc.provider_id}, "
                          f"attempts={_exc.attempts}, retry_after={_exc.retry_after})",
                    False, rec["verdict"], rec["phase"])
        return item, str(_exc), False, rec["verdict"], rec["phase"]
    step_result, step_success = box.get("res", ("", False))
    return item, step_result, step_success, rec["verdict"], rec["phase"]

def _der_claim(self, claim: str, item) -> bool:
    """Wait for an exclusive resource (browser page / screen) while the
    node's turn is live. True = held (pair with _der_release)."""
    lock = _SCREEN_CLAIM if claim == "screen" else _der_claim_lock(self, claim)
    t0 = time.perf_counter()
    while not lock.acquire(timeout=0.5):
        if (getattr(self, "_der_stop_requested", False)
                or getattr(item, "_node_cancelled", "")):
            return False
    _w = time.perf_counter() - t0
    if _w >= 0.5:
        logger.info("[DER] node %s waited %.1fs for the %s", item.step_id, _w, claim)
    return True

def _der_release(self, claim: str) -> None:
    lock = _SCREEN_CLAIM if claim == "screen" else _der_claim_lock(self, claim)
    try:
        lock.release()
    except RuntimeError:  # not held - never raise from a finally
        pass

def _der_claim_lock(self, claim: str):
    """The lock of one exclusive resource of this conversation (its browser
    page) - keyed by conversation id at module level, so a stand-in kernel
    gets a real lock too."""
    _key = (str(getattr(self, "conversation_id", "") or ""), claim)
    with _CLAIM_LOCKS_GUARD:
        return _CLAIM_LOCKS.setdefault(_key, threading.Lock())


class DerNodeMixin:
    def _der_tool_deadline(self, tool: Optional[str]) -> float:
        """Session-318 T18 (REQ-11 AC11.1): per-family dispatch deadline in
        seconds. Gather covers the 90s crawler ceilings with margin;
        everything else takes the default. Constants-only tuning (REQ-12).
        Never raises.

        Session-331 (live T3): when a tool will WAIT for user consent, the
        approval window must NOT be charged against the execution budget â€” a
        gated call used to time out at 90s while the permission card's window
        is 120s, so the tool died before a human could approve it. The consent
        wait is not execution, so add the applicable permission window (plus a
        small margin) to the deadline whenever this call will actually gate.
        With Auto-approve ON (the default) nothing waits and the base deadline
        stands unchanged â€” the common path pays nothing.
        """
        try:
            from backend.agent.tool_envelope import tool_family as _tf
            from backend.agent.der_constants import (
                DEADLINE_CRAWL_S, DEADLINE_READ_S, DEADLINE_DEFAULT_S,
                DEADLINE_COMMAND_S, DEADLINE_BROWSER_S,
            )
            _fam = _tf(tool)
            if (tool or "").lower() == "run_command":
                _base = max(float(DEADLINE_COMMAND_S), 1.0)
            elif (tool or "").lower().startswith("browser_"):
                _base = max(float(DEADLINE_BROWSER_S), 1.0)
            elif _fam == "gather":
                _base = max(float(DEADLINE_CRAWL_S), 1.0)
            elif _fam == "read":
                _base = max(float(DEADLINE_READ_S), 1.0)
            else:
                _base = max(float(DEADLINE_DEFAULT_S), 1.0)
            # Add the consent window only when this exact call will wait.
            try:
                from backend.agent.permissions import (
                    classify_tool,
                    get_auto_approve,
                    get_permission_action,
                    PERMISSION_TIMEOUT_SIDE_EFFECT,
                    PERMISSION_TIMEOUT_DESTRUCTIVE,
                )

                _tier = classify_tool(tool, None)
                _action = get_permission_action(
                    _tier, auto_approve=get_auto_approve()
                )
                if _action.value == "require_confirmation":
                    _base += float(PERMISSION_TIMEOUT_DESTRUCTIVE) + 15.0
                elif _action.value == "require_approval":
                    _base += float(PERMISSION_TIMEOUT_SIDE_EFFECT) + 15.0
            except Exception:
                pass  # permission read must never break the deadline
            # A new file with no folder chosen asks the user where to save it
            # (tool_bridge._folder_for_new_file): that wait is not execution.
            if (tool or "").lower() in ("write_file", "create_directory"):
                try:
                    from backend.agent.tools.ask_user_tool import ASK_USER_QUESTION_TIMEOUT

                    _base += float(ASK_USER_QUESTION_TIMEOUT) + 15.0
                except Exception:
                    pass
            return _base
        except Exception:
            return 90.0

    def _der_warm_vision_browser(self, _why: str = "") -> None:
        """AC9.6 (session-319): fire-and-forget warm of the pooled vision browser
        when a websearch is requested.

        WHY: the recovery lane is useless if the browser is cold. The pool stops
        the shared browser after ``_IDLE_TIMEOUT`` (180s, browser_pool.py:55) and
        the next vision use then pays a full cold start â€” the live log records
        ``[browser_session] browser acquired in 32918ms (cold pool)``. Boot-time
        warming (main.py:777) only covers the first search after a restart, so
        every later search went cold again. Starting the warm AT DISPATCH means
        the ~33s overlaps the 85-100s crawl instead of blocking recovery.

        Best-effort and non-blocking by design: the crawl must never wait on
        Chromium, and a machine without Playwright degrades on its own terms
        (browser_session.available() == False). Never raises.
        """
        try:
            from backend.vision.browser_pool import acquire_browser
        except Exception:
            return  # vision not installed â€” nothing to warm

        async def _warm() -> None:
            try:
                # Returns (browser, lease) â€” NOT a context manager. The lease
                # must be released on every path or the pool's idle watchdog
                # defers forever and the browser is never reclaimed.
                _browser, lease = await acquire_browser()
                try:
                    logger.debug("[DER] vision browser warmed (%s)", _why)
                finally:
                    lease.release()
            except Exception as _wexc:  # noqa: BLE001 â€” best effort by design
                logger.debug("[DER] vision browser warm skipped: %s", _wexc)

        try:
            import asyncio as _aio_warm
            _loop = getattr(self, "_broadcast_loop", None)
            if _loop is not None and not _loop.is_closed():
                _aio_warm.run_coroutine_threadsafe(_warm(), _loop)
                return
            # No captured loop (e.g. a sync test context): only safe to schedule
            # if THIS thread already owns a running loop.
            _aio_warm.get_running_loop().create_task(_warm())
        except Exception:
            pass  # no loop available â€” recovery simply pays the cold start

    @staticmethod
    def _der_evidence_cap(tool: Optional[str]) -> int:
        """Evidence window for a step result, by tool kind."""
        _t = (tool or "").lower()
        if _t in AgentKernel._DER_GATHER_TOOLS or _t in AgentKernel._DER_SEARCH_TOOLS:
            return 8000
        if _t in AgentKernel._DER_READ_TOOLS:
            return 8000
        # Execution audit B5: command and git output carried 400 chars into
        # later steps, so a test failure's traceback never reached the step
        # that had to fix it. The excerpt keeps head AND tail.
        if _t in AgentKernel._SHELL_RESULT_TOOLS or _t.startswith("git_"):
            return 8000
        return 400

    @staticmethod
    def _der_query_has_reference(query: str) -> bool:
        """Heuristic: does the search query contain an ambiguous reference that
        needs the conversation history to resolve?"""
        import re as _re

        _q = query or ""
        _ref_re = _re.compile(
            r"\b(it|its|they|them|those|that|this|the same|above|earlier|"
            r"previous|mentioned|same)\b",
            _re.IGNORECASE,
        )
        if _ref_re.search(_q):
            return True
        _ql = _q.lower()
        return any(
            _p in _ql
            for _p in (
                "pricing of", "price of", "cost of", "the pricing",
                "the price", "the cost", "do the", "the websearch",
                "the search", "what we",
            )
        )

    def _der_refine_query(self, query: str, _session: str) -> str:
        """
        Phase 2.2: resolve ambiguous references in a search query against the
        full conversation history via a quick LLM call. Returns the refined
        query, or the original on any failure / no change.
        """
        try:
            _history = []
            if self._conversation_memory is not None:
                _history = self._conversation_memory.get_context()
            if not _history:
                return query
            _history_str = "\n".join(
                f"{(m.get('role') or 'user').upper()}: {m.get('content') or ''}"
                for m in _history
            )
            _refine_prompt = (
                "CONVERSATION HISTORY (FULL):\n"
                f"{_history_str}\n\n"
                f"CURRENT QUERY: {query}\n\n"
                "Rewrite the search query to resolve any ambiguous pronouns or "
                "references based on the full conversation history. Output the "
                "query string only."
            )
            _refined = self.infer(
                _refine_prompt, role="reasoning", max_tokens=30, temperature=0.0
            )
            _out = (_refined.raw_text or "").strip().strip('"').strip()
            if _out and _out.lower() != query.lower():
                logger.info("[DER] refined query %r -> %r", query, _out)
                return _out
        except Exception as _e:
            logger.debug("[DER] query refinement failed: %s", _e)
        return query

    @staticmethod
    def _format_tool_result(raw) -> str:
        """Phase 4b: normalize a raw tool-bridge result into clean text for
        downstream consumption (dependent steps, working memory, final answer).

        - strings pass through unchanged
        - dicts: surface errors explicitly; otherwise extract the most useful
          content key (result/results/content/output/text/data/response);
          fall back to compact JSON for unrecognized dicts / lists
        - never raises; any failure falls back to str(raw)

        Note: the full structured result is still captured verbatim by
        _capture_tool_result (document store) â€” this only shapes the textual
        flow, so nothing is lost for later reformatting.
        """
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            try:
                if raw.get("success") is False:
                    _err = raw.get("error") or raw.get("message") or "unknown error"
                    return (
                        _err
                        if isinstance(_err, str)
                        else json.dumps(_err, ensure_ascii=False, default=str)
                    )
                for _key in (
                    "result", "results", "content", "output",
                    "text", "data", "response",
                ):
                    _val = raw.get(_key)
                    if _val is None:
                        continue
                    if isinstance(_val, str):
                        return _val
                    return json.dumps(_val, ensure_ascii=False, default=str)
                # Document envelopes (e.g. get_rendered_documents) carry no
                # content key â€” without this they fell to compact JSON and the
                # raw payload (success/conversation_id/documents) rendered
                # verbatim on task-card rows (live 2026-09-09). Summarize
                # human-side; full data stays in the document store.
                _docs = raw.get("documents")
                if isinstance(_docs, list):
                    _titles = [
                        d.get("title") or d.get("document_id") or ""
                        for d in _docs
                        if isinstance(d, dict)
                    ]
                    _titles = [t for t in _titles if t][:3]
                    _base = (
                        f"{len(_docs)} document(s) retrieved"
                    )
                    return (
                        f"{_base}: {', '.join(_titles)}"
                        if _titles
                        else _base
                    )
                # Conversation index (e.g. list_conversations) carries no
                # content key either â€” without this it fell to compact JSON
                # and the raw index rendered verbatim on task-card rows AND
                # entered working memory with no next-action pointer (live
                # conv-98: the planner read the index as retrieved content
                # and skipped the get_rendered_documents follow-up). The
                # result repeats the pointer the registry description already
                # gives, because the result is what survives into memory.
                _convs = raw.get("conversations")
                if isinstance(_convs, list):
                    _tops = [
                        f"{c.get('conversation_id')} "
                        f"({c.get('doc_count') or 0} docs)"
                        for c in _convs
                        if isinstance(c, dict) and c.get("conversation_id")
                    ][:3]
                    _cbase = (
                        f"{len(_convs)} conversation(s) with documents "
                        f"(index only â€” call get_rendered_documents("
                        f"conversation_id=...) to read one)"
                    )
                    return (
                        f"{_cbase}: {', '.join(_tops)}"
                        if _tops
                        else _cbase
                    )
                # `diff` (edit diffs) is for the chat, never for the model.
                return json.dumps(
                    {k: v for k, v in raw.items() if k != "diff"},
                    ensure_ascii=False, default=str,
                )
            except Exception:
                return str(raw)
        try:
            return json.dumps(raw, ensure_ascii=False, default=str)
        except Exception:
            return str(raw)

    @staticmethod
    def _format_tool_result_for_step(raw, tool=None) -> str:
        """Step-result shaping for the DER execution path (not card rows).

        Session-323: a rerouted READ (get_rendered_documents after a guard
        REPEAT block) delivers the same gathered bytes through the document
        store â€” but _format_tool_result reduces that envelope to a title
        line ("1 document(s) retrieved"), so the step result starves and
        synthesis honestly reports IDs-only (live B3-repeat). For read
        tools, keep the header line AND append a bounded content excerpt
        per doc (IDs + sources kept). All other tools delegate unchanged,
        so card snapshots and the pinned format contract never move.
        Never raises; falls back to _format_tool_result.
        """
        try:
            _t = (tool or "").lower()
            # Execution audit B4/B5 (2026-09-29): a shell result has no content
            # key, so it fell to compact JSON - output escaped inside a string,
            # exit code buried. Readable text with the exit code FIRST, so the
            # verifier and every later step can see whether the command failed.
            if _t in AgentKernel._SHELL_RESULT_TOOLS and isinstance(raw, dict) \
                    and ("returncode" in raw or "running" in raw or "stdout" in raw):
                _out = "\n".join(
                    s for s in (str(raw.get("stdout") or "").rstrip(),
                                str(raw.get("stderr") or "").rstrip()) if s
                )
                # A command still running (stalled or a server), or one that
                # was stopped / timed out, says so first - with its output.
                if raw.get("running"):
                    _head = f"[still running, handle {raw.get('handle')}] {raw.get('note') or ''}".rstrip()
                elif raw.get("returncode") is not None:
                    _head = f"[exit code {raw.get('returncode')}]"
                elif raw.get("success") is False:
                    _head = f"[{raw.get('error') or 'command failed'}]"
                else:
                    _head = f"[{raw.get('status') or 'done'}]"
                return f"{_head}\n{_out or '(no output)'}"
            if _t in AgentKernel._DER_READ_TOOLS and isinstance(raw, dict):
                _docs = raw.get("documents")
                if isinstance(_docs, list) and _docs:
                    _head = AgentKernel._format_tool_result(raw)
                    _parts = [_head]
                    for _d in _docs[:3]:
                        if not isinstance(_d, dict):
                            continue
                        _did = str(_d.get("document_id") or "")[:12]
                        _title = str(_d.get("title") or _did or "doc")
                        _content = _d.get("content") or ""
                        if not isinstance(_content, str):
                            try:
                                import json as _js323
                                _content = _js323.dumps(_content, ensure_ascii=False, default=str)
                            except Exception:
                                _content = str(_content)
                        if not _content.strip():
                            try:
                                _vars = _d.get("variants") or {}
                                if isinstance(_vars, dict):
                                    for _v in _vars.values():
                                        if isinstance(_v, str) and _v.strip():
                                            _content = _v
                                            break
                            except Exception:
                                pass
                        _srcs = _d.get("sources") or []
                        try:
                            _src_line = ""
                            if isinstance(_srcs, list) and _srcs:
                                _src_line = "sources: " + ", ".join(str(u) for u in _srcs[:5])
                            elif isinstance(_srcs, str) and _srcs.strip():
                                _src_line = "sources: " + _srcs.strip()[:400]
                        except Exception:
                            _src_line = ""
                        _excerpt = AgentKernel._smart_excerpt(_content, 2500) if _content.strip() else "(no stored text)"
                        _block = f"--- Doc {_title} [{_did}] ---\n{_excerpt}"
                        if _src_line:
                            _block += f"\n{_src_line}"
                        _parts.append(_block)
                    return "\n".join(_parts)
        except Exception:
            pass
        return AgentKernel._format_tool_result(raw)

    def _run_step_direct(self, item, context_package, session_id: str) -> str:
        """
        Execute a tool-less DER step via direct model inference.
        Returns the model's response text, or an error placeholder.
        Injects accumulated working memory (prior step findings) into the prompt.
        """
        try:
            cp_str = ""
            if context_package and hasattr(context_package, "get_system_zone_content"):
                try:
                    cp_str = context_package.get_system_zone_content() or ""
                except Exception:
                    pass

            # Working memory: include what earlier steps found this session.
            # Uses ContextManager.render() which applies compression at 80% threshold.
            wm_str = ""
            try:
                if self._memory_interface:
                    wm_str = (
                        self._memory_interface.get_assembled_context(session_id) or ""
                    )
            except Exception:
                pass
            # P1 (live conv-98): working memory enters this prompt unbounded â€”
            # a 15KB+ crawl dump emptied the provider here while the
            # compressed-record final synthesis on the same provider
            # succeeded. Bound with an explicit truncation marker (never a
            # silent amputation); prompts under the cap are byte-identical.
            if len(wm_str) > 6000:
                wm_str = self._smart_excerpt(wm_str, 6000)

            # Phase 1 (D1.6): inject the memory-coupled evidence block so the
            # acting prompt is conditioned on proven paths / failures / state.
            evidence_str = ""
            try:
                from backend.agent.evidence import assemble_evidence

                _mi = getattr(self, "_memory_interface", None)
                _myc = getattr(_mi, "_mycelium", None) if _mi is not None else None
                _task_class = getattr(self, "_der_task_class", "full") or "full"
                _completed = list(getattr(self, "_der_completed_tools", []) or [])
                evidence_str = assemble_evidence(
                    goal=item.description or item.objective_anchor or "",
                    session_id=session_id,
                    myc=_myc,
                    completed_tools=_completed,
                    task_class=_task_class,
                    memory_interface=self._memory_interface,
                )
            except Exception as _ev_err:
                logger.debug("[DER] evidence build failed: %s", _ev_err)

            prompt = (
                f"{cp_str}\n\n"
                + (f"SESSION FINDINGS SO FAR:\n{wm_str}\n\n" if wm_str else "")
                + (f"{evidence_str}\n\n" if evidence_str else "")
                + f"OBJECTIVE: {item.objective_anchor}\n"
                + (f"{_voice_turn_note(self)}\n" if _voice_turn_note(self) else "")
                + f"STEP {item.step_number}: {item.description}\n\n"
                "Complete this step. Respond with the result only."
            ).strip()
            # OBSERVABILITY (2026-10-29, T48): did THIS step prompt carry the
            # memory-of-facts line? Counted per turn and reported with the path.
            if "MEMORY         :" in (evidence_str or ""):
                self._turn_mem_prompts = int(
                    getattr(self, "_turn_mem_prompts", 0)) + 1
            # THINKING RUNS ON THE BRAIN (2026-08-16). This is the tool-less
            # step path â€” there is no tool to execute, only reasoning â€” so it
            # belongs to the reasoning binding. It used to run on
            # role="EXECUTION" (the tool_execution binding), which meant that
            # with Brain and Tool on different models the actual thinking was
            # done by whichever model the user picked for TOOLS. The Tool model
            # executes tools; it does not think.
            result = self.infer(
                prompt, role="reasoning", max_tokens=512, temperature=0.3
            )
            if not (result.raw_text or "").strip():
                # P3 (live conv-98): an Empty response here fell through to
                # the "[step N completed]" placeholder, failed verification,
                # and burned 3 sub-loop retries on the same bloated prompt.
                # Retry ONCE with shrunk context (excerpted findings) before
                # surrendering to the placeholder â€” same provider, bounded
                # prompt is the combination proven to succeed.
                logger.info(
                    "[DER] step-direct infer empty â€” retrying once with "
                    "shrunk context (step %s)", item.step_number,
                )
                _shrunk = (
                    f"{cp_str}\n\n"
                    + (
                        "SESSION FINDINGS SO FAR (excerpted):\n"
                        f"{self._smart_excerpt(wm_str, 1500)}\n\n"
                        if wm_str else ""
                    )
                    + (f"{evidence_str}\n\n" if evidence_str else "")
                    + f"OBJECTIVE: {item.objective_anchor}\n"
                    f"STEP {item.step_number}: {item.description}\n\n"
                    "Complete this step. Respond with the result only."
                ).strip()
                result = self.infer(
                    _shrunk, role="reasoning", max_tokens=512, temperature=0.3
                )
            return result.raw_text or f"[step {item.step_number} completed]"
        except Exception as _e:
            return f"[step {item.step_number} error: {_e}]"

    def _der_note_quick_tier(self, tool: Optional[str], result: Any) -> None:
        """Spec A4: keep the quick-tier -> crawler_query escalation state.

        A `search` result that says ``requires_deep_crawl`` marks this
        conversation so the gather gate (_mem_lookup) resolves the NEXT web goal
        to `crawler_query`; dispatching a `crawler_query` spends that escalation,
        so it happens once. Never raises - bookkeeping must not fail a step.
        """
        try:
            _key = (
                getattr(self, "conversation_id", "")
                or getattr(self, "session_id", "")
                or ""
            )
            _due = set(getattr(self, "_der_quick_insufficient", ()))
            if tool == "crawler_query":
                _due.discard(_key)
            elif (
                tool in ("search", "web_search")
                and isinstance(result, dict)
                and result.get("requires_deep_crawl")
            ):
                _due.add(_key)
                logger.info(
                    "[DER] quick tier insufficient conv=%s -> next web goal escalates "
                    "to crawler_query (once)", _key,
                )
            self._der_quick_insufficient = _due
        except Exception:  # noqa: BLE001
            pass

    def _der_pre_dispatch_guard(self, item: "QueueItem") -> Optional[Dict[str, Any]]:
        """T6B (specs/tool-result-envelope REQ-2/REQ-3 AC3.3, KD-10): the
        pre-dispatch HARD-RULE guard â€” prevention decides, the envelope
        testifies. Runs BEFORE a tool call is paid for; reads turn memory
        (seen dispatches + crawled URLs) and the wall ledger ONLY â€” adds no
        inference and no store writes.

        Hierarchy C hard rules (never overridable in-run):
          * WALLED â€” the target domain has a live wall record (is_walled):
            the tool is NEVER retried; the step fails honestly.
          * CIRCLING â€” this exact tool+params (or an all-known-URLs gather)
            already ran this conversation: NEVER re-executed; the step is
            rerouted to READ the original result via the document store
            (get_rendered_documents), and the original envelope is re-stamped
            confirmed load-bearing (AC1.6 retroactive half).

        Returns None when the call may proceed, or a dict:
          {"reason": ..., "reroute_tool": str|None, "reroute_params": dict,
           "original_step_id": str}
        Never raises â€” a broken guard must not change loop semantics
        (advisory-gate principle).
        """
        try:
            from backend.agent.tool_envelope import (
                mark_consumed, params_digest,
            )
            from backend.agent.tool_errors import is_walled

            _conv = self.conversation_id or ""
            _counters = getattr(self, "_envelope_counters", None)
            if _counters is None:
                _counters = {
                    "written": 0, "raw_ref_fetches": 0,
                    "crit_confirmed": 0, "gate_fired": 0,
                    "gate_blocked": 0, "hard_blocks": 0,
                    "suggest_overrides": 0,
                }
                self._envelope_counters = _counters

            # â”€â”€ HARD RULE 1: walled domain â€” never retried in-run â”€â”€â”€â”€â”€â”€â”€â”€â”€
            _target = ""
            try:
                _p = item.params or {}
                _candidate = str(
                    _p.get("url") or _p.get("base_url") or ""
                )
                if _candidate.startswith("http"):
                    from urllib.parse import urlparse as _urlparse

                    _target = _urlparse(_candidate).hostname or ""
            except Exception:
                _target = ""
            if _target and is_walled(_target):
                _counters["hard_blocks"] += 1
                logger.info(
                    "[DER:guard] WALLED tool refused pre-dispatch "
                    "(conv=%s step=%s tool=%s domain=%s) â€” never retried "
                    "in-run",
                    _conv, getattr(item, "step_id", "?"),
                    getattr(item, "tool", None), _target,
                )
                return {
                    "reason": f"walled domain {_target}",
                    "reroute_tool": None,
                    "reroute_params": {},
                    "original_step_id": "",
                }

            # â”€â”€ HARD RULE 2: repeat â€” never re-executed; read instead â”€â”€â”€â”€â”€
            _digest = params_digest(
                getattr(item, "tool", None), getattr(item, "params", None)
            )
            _seen = getattr(self, "_der_seen_dispatches", {}).get(_conv, {})
            _original_step_id = _seen.get(_digest, "")
            # Execution audit B3 (2026-09-29): the repeat rule protects WEB
            # fetches, whose repeat returns the same page. Local tools read state
            # that changes - re-running the tests after an edit, or re-reading a
            # file after writing it, is the coding loop itself - so they are
            # never blocked as repeats.
            if _original_step_id and str(getattr(item, "tool", "") or "").lower() \
                    not in AgentKernel._REPEAT_GUARDED_TOOLS:
                _original_step_id = ""
            if _original_step_id:
                # Find the original envelope for the doc pointer (bounded
                # scan of the FIFO-capped registry).
                _original_env = None
                _bucket = getattr(self, "_der_envelope_registry", {}).get(
                    _conv, {}
                )
                for _env in _bucket.values():
                    if getattr(_env, "step_id", "") == _original_step_id:
                        _original_env = _env
                        break
                if _original_env is not None:
                    try:
                        _before, _after = mark_consumed(_original_env)
                        _counters["crit_confirmed"] += 1
                        if _before[0] != "load-bearing":
                            logger.info(
                                "[envelope] criticality divergence: step %s "
                                "declared %s but a later step consumed its "
                                "doc (now %s) â€” tuning signal",
                                _original_step_id, _before[0], _after[0],
                            )
                    except Exception:
                        pass
                _counters["hard_blocks"] += 1
                logger.info(
                    "[DER:guard] REPEAT blocked pre-dispatch (conv=%s "
                    "step=%s tool=%s original=%s) â€” rerouting to read the "
                    "gathered documents instead of re-executing",
                    _conv, getattr(item, "step_id", "?"),
                    getattr(item, "tool", None), _original_step_id,
                )
                return {
                    "reason": f"repeat of step {_original_step_id}",
                    "reroute_tool": "get_rendered_documents",
                    "reroute_params": {"conversation_id": _conv},
                    "original_step_id": _original_step_id,
                }

            # â”€â”€ Gather URL-subset check: all fetch targets already crawled â”€
            # Compares NORMALIZED addresses so a trailing slash or fragment
            # drift cannot re-open a visited page (session-321 B-probe fix).
            _p = item.params or {}
            _urls = _p.get("known_urls") or (
                [_p["url"]] if _p.get("url") else []
            )
            _crawled = getattr(self, "_der_crawled_urls", {}).get(_conv, set())
            try:
                from backend.agent.tool_envelope import normalize_url as _norm_guard
                _urls_n = [_norm_guard(str(u)) for u in _urls]
                _crawled_n = set(_norm_guard(str(u)) for u in _crawled)
            except Exception:
                _urls_n = [str(u) for u in _urls]
                _crawled_n = set(str(u) for u in _crawled)
            if _urls and _crawled and all(
                u in _crawled_n for u in _urls_n if u
            ):
                _counters["hard_blocks"] += 1
                logger.info(
                    "[DER:guard] URL-repeat blocked pre-dispatch (conv=%s "
                    "step=%s): all %d fetch targets already crawled this "
                    "conversation â€” rerouting to read",
                    _conv, getattr(item, "step_id", "?"), len(_urls),
                )
                return {
                    "reason": "all fetch targets already crawled this turn",
                    "reroute_tool": "get_rendered_documents",
                    "reroute_params": {"conversation_id": _conv},
                    "original_step_id": "",
                }
            return None
        except Exception as _guard_exc:
            logger.debug(
                "[DER:guard] pre-dispatch guard skipped: %s", _guard_exc
            )
            return None

    def _der_before_call(self, tool: str, _session: str) -> None:
        """Per-call bookkeeping BEFORE one DER tool dispatch - one place for the
        direct step and every node call (a node web call skipped all of it
        until 2026-10-03: no external mark, no browser warm)."""
        # Trust-routing W2: mark external for web/crawler tools
        self.mark_external_tool(tool)
        # pin_42ddd255162d: render tools need the conversation registry on the
        # bridge; DER paths never received it.
        try:
            self._tool_bridge._active_conversation_id[_session] = self.conversation_id or ""
        except Exception:
            pass
        # AC9.6 (session-319): warm the pooled vision browser the moment a WEB
        # tool is dispatched, so its cold start overlaps the crawl instead of
        # blocking recovery later. Fire-and-forget - the crawl never waits.
        if tool in self._WEB_CONTENT_TOOLS:
            self._der_warm_vision_browser(tool)

    def _der_after_call(self, item, tool: str, params, dr, _session: str, _turn_id: Optional[str],
                        capture: bool = True) -> None:
        """Per-call bookkeeping AFTER one DER tool dispatch (direct step or node
        call): crawl budget, ToolCallTree row, quick tier, result capture
        (sources / har_path for the reply). Never raises."""
        if not dr:
            return
        # Edit diffs: the diff rides the tool result from the bridge. It goes
        # onto the step (-> its tool:result event) and OFF the result, so the
        # model and the step text never read it.
        _res = getattr(dr, "result", None)
        if isinstance(_res, dict) and "diff" in _res:
            try:
                _d = _res.pop("diff")
                if isinstance(_d, dict):
                    _eds = getattr(item, "edit_diffs", None)
                    if not isinstance(_eds, list):
                        _eds = []
                        item.edit_diffs = _eds
                    _eds.append(_d)
                    del _eds[:-12]  # bounded: a node makes at most 12 calls
            except Exception:  # noqa: BLE001 - a diff never fails a step
                logger.debug("[DER] edit diff capture skipped", exc_info=True)
        # pin_42ddd255162d: dispatch-time gather sanction - the dispatch runs
        # for EVERY crawl (real or dedupe-hit), so record the query hash here:
        # guaranteed bookkeeping for the per-task crawl budget/veto. A deadline
        # expiry did not crawl.
        if (tool in self._WEB_CONTENT_TOOLS and self.conversation_id
                and getattr(dr, "error_type", None) != "timeout"):
            try:
                from backend.agent.der_execution_ledger import make_action_key

                # D2: same stable action key as the gather gate.
                _gq = make_action_key(item.description or tool)
                with _der_claim_lock(self, "crawl_attempts"):  # parallel nodes
                    _cs = dict(getattr(self, "_der_crawl_attempts", {}))
                    _cs[self.conversation_id] = _cs.get(self.conversation_id, set()) | {_gq}
                    self._der_crawl_attempts = _cs
            except Exception:
                pass
        # â”€â”€ Record tool call for ToolCallTree (REQ-13) â”€â”€
        try:
            _result_str = str(getattr(dr, "result", ""))[:200] or str(getattr(dr, "error", ""))[:200]
            self._get_tool_box().record_tool_call(
                step_id=str(getattr(item, "step_id", "")) or "",
                tool=tool,
                args_hash=hashlib.md5(str(params).encode()).hexdigest()[:12],
                result_summary=_result_str,
                error_type=getattr(dr, "error_type", None),
                source="tool",
                split_depth=int(getattr(item, "depth_layer", 0)) or 0,
                parent_step_id=str(getattr(item, "parent_step_id", "")) or None,
            )
        except Exception as _rc_err:
            logger.warning("[DER] record_tool_call failed: %s", _rc_err)
        self._der_note_quick_tier(tool, getattr(dr, "result", None))
        # W9 (O3): capture structured tool results
        if capture and getattr(dr, "result", None) is not None:
            try:
                _doc = self._capture_tool_result(
                    tool, dr.result, self.conversation_id, _turn_id, _session,
                )
                if _doc:
                    item.captured_doc_id = _doc
            except Exception as _cap_err:
                logger.warning("[DER] tool-result capture failed: %s", _cap_err)

    def _der_run_direct_node(self, item, goal: str, task: str = "") -> tuple:
        """A "direct" node: answer the goal from the model's own knowledge.

        The cheap half of the unification - no plan, no node prompt, no tool
        loop. It is STILL a node, and that is what makes the mode an execution
        detail rather than a second lane:

          * it returns the SAME ``(step_result, success)`` shape ``_der_run_node``
            returns, so the finalize site (Â§5) and the failure seam
            (``_der_handle_step_failure``) are unchanged and still see it;
          * it stamps the SAME bookkeeping the DAG reads (``node_calls`` /
            ``node_call_log`` / ``node_digest``), so repeat detection and the
            step budget count it;
          * the envelope is stamped at the finalize site, not here.

        One model call, no tools. Never raises.
        """
        text = ""
        try:
            _msgs = [{"role": "user", "content": (task or goal)}]
            _text, _thinking, _calls = self._router.generate("reasoning", _msgs)
            text = str(_text or "").strip()
        except Exception as exc:  # noqa: BLE001 â€” a node never crashes the turn
            logger.debug("[DER] direct node failed: %r", exc)
        item.node_calls = []
        item.node_call_log = []
        try:
            from backend.agent.tool_envelope import params_digest

            item.node_digest = params_digest(
                "run_node_direct", {"goal": (goal or "")[:200]}
            )
        except Exception:  # noqa: BLE001 â€” bookkeeping never fails a step
            pass
        return text, bool(text)

    def _der_run_node(self, item, _session: str, _turn_id: Optional[str], _prior_results: list, task: str = "") -> tuple:
        """Adapter for node_executor.run_node: this kernel's router, the box's
        dispatch (ledger rows, deadlines, permissions) and the developer tools."""
        from backend.agent.node_executor import (
            NODE_SCREEN_TOOLS, NODE_TOOLS, NodeContext, run_node,
        )
        from backend.agent.tool_decision import _vision_relevant

        box = self._get_tool_box()

        # A node belongs to ONE turn. Eval C c04 (2026-10-02, conv-622): the
        # 600 s budget sent the reply while a recovery node was starting in a
        # batch thread; the turn's finally then made the router's choke check
        # inert and the node made model and tool calls for 3 more minutes,
        # into the next task. Every node call first checks that its turn is
        # still the live one and was not stopped (budget or user "stop").
        # A stand-in kernel with no DER state counts as live.
        def _turn_live() -> bool:
            if getattr(self, "_der_stop_requested", False):
                return False
            # parallel nodes: the split race was won by a sibling, or the
            # plan / turn this node belongs to was dropped
            if getattr(item, "_race_lost", "") or getattr(item, "_node_cancelled", ""):
                return False
            if getattr(self, "_der_turn_active", True) is False:
                return False
            live_id = getattr(self, "_der_turn_id", None)
            return _turn_id is None or live_id is None or live_id == _turn_id

        _ended = "turn ended (reply sent or stopped); this node does no more work"

        def _generate(role, messages, **kw):
            if not _turn_live():
                logger.info("[run_node] conv=%s turn=%s %s", self.conversation_id, _turn_id, _ended)
                raise RuntimeError(_ended)
            out = self._router.generate(role, messages, **kw)
            self._accrue_tokens("", getattr(self._router, "last_usage", None), source="run_node")
            return out

        _held: List[str] = []

        # One domain correction per step (2026-10-08). Bounded deliberately:
        # unbounded re-steering is the TrailingDirector failure mode.
        _domain_steered = [False]

        def _execute(name, params):
            if not _turn_live():
                return {"success": False, "error": _ended, "error_type": "aborted"}
            # â”€â”€ Domain guard (2026-10-08) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # A step whose goal names an EXTERNAL resource, but which reaches
            # for a LOCAL tool, is searching the wrong domain. Measured live: a
            # plan step "Read the README and main files from the OpenAI math
            # repository" ran glob_files/grep_files INSIDE the project root for
            # ~6 minutes and ended "no dedicated `openai_math` repository folder
            # exists in the project root" - the repo was on GitHub.
            #
            # This corrects the PICK, never the menu: the menu keeps BOTH
            # families so a task can move local -> external -> local freely, and
            # nothing is removed. It only fires when the goal is external AND
            # the pick is local, and only once per step.
            try:
                from backend.agent import external_reference as _xr

                if name in _xr.LOCAL_TOOLS and not _domain_steered[0]:
                    _names = [
                        t.get("function", {}).get("name") for t in tools
                    ]
                    # Provenance, DER-NATIVE FIRST: the step's OWN envelope
                    # records the URLs that step fetched (ToolEnvelope.sources,
                    # REQ-8 AC8.1). Only when the step carries no envelope do we
                    # fall back to the conversation-level set - the envelope is
                    # the DER's per-step truth and must win.
                    _env_srcs = list(
                        getattr(getattr(item, "envelope", None), "sources", [])
                        or []
                    )
                    _srcs = _env_srcs or self._turn_sources()
                    # The predicate is goal-external AND the PICK is local - not
                    # "the menu is all local". The menu legitimately holds both
                    # families, which is what lets a task move between them.
                    _shape = _xr.domain_mismatch(goal, [name], _srcs)
                    _alt = _xr.resolving_tool(_shape) if _shape else None
                    # Params are unambiguous for BOTH steered families:
                    #   search   -> {"query": ...}  (the goal IS the query)
                    #   open_url -> {"url": ...}    (the URL is IN the goal)
                    _steer_params = None
                    if _alt == "search":
                        _steer_params = {"query": goal[:300]}
                    elif _alt == "open_url":
                        _u = _xr.first_url(goal)
                        _steer_params = {"url": _u} if _u else None
                    if _steer_params and _alt in _names:
                        _domain_steered[0] = True
                        logger.info(
                            "[DER] domain guard: goal names an EXTERNAL %s but "
                            "the pick was local (%s) -> steering to %s",
                            _shape, name, _alt,
                        )
                        name, params = _alt, _steer_params
                    elif _alt:
                        logger.info(
                            "[DER] domain guard: goal names an EXTERNAL %s but "
                            "%s is not offered/steerable - local pick %s left "
                            "alone", _shape, _alt, name,
                        )
            except Exception as _dg_exc:  # noqa: BLE001 â€” a guard never blocks a step
                logger.debug("[DER] domain guard skipped: %r", _dg_exc)
            # parallel nodes: the browser page / the screen has one driver - a
            # node claims it at its first such call and keeps it to the end.
            _claim = _node_claim_of(name)
            if _claim and _claim not in _held:
                if not _der_claim(self, _claim, item):
                    return {"success": False, "error": _ended, "error_type": "aborted"}
                _held.append(_claim)
            self._der_before_call(name, _session)
            dr = box.dispatch(
                Decision(kind=DecisionKind.TOOL, tool=name, params=params, source="run_node"),
                session_id=_session, conversation_id=self.conversation_id,
                turn_id=_turn_id, timeout_s=self._der_tool_deadline(name),
            )
            # A node stores only web search/crawl results (sources for the
            # reply): every page list from a click became a 34k-char document
            # + ~39 memory chunks (live 2026-10-03), DB writers for nothing.
            self._der_after_call(item, name, params, dr, _session, _turn_id,
                                 capture=name in self._WEB_CONTENT_TOOLS)
            raw = getattr(dr, "result", None)
            return raw if raw is not None else {"success": False, "error": getattr(dr, "error", "") or "no result"}

        goal = item.description or item.objective_anchor or ""
        # â”€â”€ mode (2026-10-08, unification) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # The node's GOAL decides its mode, exactly as it decides its domain
        # (the domain guard in _execute). Chosen ONCE here, at node entry -
        # never switched mid-step. A "direct" node answers from the model's own
        # knowledge instead of running the planned tool loop, so a simple step
        # does not pay the planning cost, and a turn is no longer locked into
        # one lane: _needs_planning is now only the TURN-LEVEL DEFAULT.
        from backend.agent import external_reference as _xr_mode

        item.mode = _xr_mode.mode_for_goal(goal, self._turn_sources())
        if item.mode == _xr_mode.DIRECT:
            return self._der_run_direct_node(item, goal, task)
        _menu = set(NODE_TOOLS) | (set(NODE_SCREEN_TOOLS) if _vision_relevant(goal) else set())
        tools = [t for t in self._get_openai_tools() if t.get("function", {}).get("name") in _menu]
        # Advisory narrowing (2026-11-06): core coding tools + the Oracle's top
        # picks, so a call does not carry the whole 17-tool menu. Full menu on
        # any failure; IRIS_NODE_TOOL_MENU_K=0 disables it.
        tools = _narrow_node_tools(tools, goal)
        # The shadow scores the menu the node's model was OFFERED, not the
        # registry's first names (which are vision tools).
        _offered = [t["function"]["name"] for t in tools]
        workdir =(getattr(self._tool_bridge, "_session_workdirs", None) or {}).get(_session, "")

        # The pre-call evidence, computed ONCE for this node: the previous
        # step's result (the most predictive signal for the next tool) and the
        # offered tools' descriptions. Both the tool_choice shadow and the
        # tool_approval consult read them.
        _lr = ""
        try:
            if _prior_results:
                _p = _prior_results[-1]
                _lr = f"{_p.get('description') or ''}: {_p.get('result') or ''}"
        except Exception:  # noqa: BLE001 â€” a shadow never needs context
            _lr = ""
        # tc-frame-v10 (2026-11-04): the option lines are the BARE tool
        # names. MEASURED by replay on the active engine (1200 recorded
        # tc-frame-v8 states, the same rows for both variants): the tools'
        # decision lines measured oof AUROC 0.6569 and the bare names
        # 0.6955, with monotonic confidence bands in both cases. The
        # instruction carries the question; the option text must not argue
        # for a tool (the same lesson as the review_verdict v9 criteria and
        # the tool_choice control labels, oracle.md 7.6).
        _hints = {n: n for n in _offered}
        _hints.update({n: n for n in ("DELEGATE", "NONE")})

        # THE STEP'S OWN STATE (tc-frame-v5 / tool_approval v3, 2026-10-11):
        # the hooks read the node's LIVE pre-call state - the calls this step
        # made so far and the last result the model saw - not `_lr` alone,
        # which is the previous STEP's result computed once per node (every
        # call of a step scored the same frame: 50.9% parity on 395 rows).
        # Read and rendered to strings AT CALL TIME: the list keeps growing.
        _node_state: Dict[str, Any] = {}
        _done_when = str(getattr(item, "expected_output", "") or "")

        def _step_so_far():
            from backend.agent.node_executor import history_text

            _c = _node_state.get("ctx")
            if _c is None:
                return "", _lr
            return history_text(_c.history), (_c.last_result_text or _lr)

        def _facts_now():
            # tc-frame-v7: the read/edit/write/run facts of THIS step, now.
            from backend.agent.node_executor import step_facts

            _c = _node_state.get("ctx")
            return step_facts(goal, _done_when, list(_c.history) if _c is not None else [],
                              workdir or "",
                              last_result=(_c.last_result_text if _c is not None else "") or "")

        # THE ORACLE DECIDES THE TOOL: before each model call, one d1 question
        # over the offered tools on the step's pre-call state, through the
        # enforcement chokepoint (enforced, else sampled). A pick is FORCED at
        # the API; the pending row is labelled by the call that follows
        # (_on_result) or flushed as "finished".
        _decided: Dict[str, Any] = {}

        def _flush_decided():
            _p = _decided.pop("row", None)
            if _p is not None:
                box.label_decided_row(_p, called=None, ok=None,
                                      session_id=self.conversation_id or "voice")

        def _choose_tool():
            _flush_decided()  # the previous pick was never called: finished
            _hist, _last = _step_so_far()
            _c = _node_state.get("ctx")
            _n = len(_c.history) if _c is not None else 0
            got = box.choose_node_tool(
                goal=goal, candidates=_offered,
                scope_key=f"{_turn_id or ''}|{getattr(item, 'step_id', '') or ''}|{goal[:80]}|{_n}",
                last_result=_last or None, option_criteria=_hints or None,
                calls_this_step=_hist or None, done_when=_done_when or None,
                step_facts=_facts_now() or None,
                step_id=getattr(item, "step_id", None), turn_id=_turn_id,
            )
            if got is None:
                return None
            # CANDIDATE COMPRESSION (2026-11-07): the Oracle ranked the menu;
            # the model picks from this shortlist. No single tool is forced, so
            # a bad rank cannot push the model into a wrong tool. The row is
            # labelled by the call that follows (shortlist_served).
            if got[1].get("route") in ("shortlist", "class"):
                _decided["row"] = got[1]
                return got[0]
            # An ENFORCED pick already cleared its calibrated threshold. A
            # SAMPLED pick acts only at raw confidence >= IRIS_ORACLE_FORCE_MIN
            # (default 0.9; measured 96.7% held at >= 0.9 on 90 decided rows).
            # Below it the model decides: an unsure pick that only narrowed
            # the menu pushed the model into the wrong tool (edit_file picks
            # at median confidence 0.46 FAILED 22 times).
            try:
                _floor = float(os.environ.get("IRIS_ORACLE_FORCE_MIN", "0.9"))
            except ValueError:
                _floor = 0.9
            if not (got[1].get("route") == "enforced"
                    or float(got[1].get("confidence") or 0.0) >= _floor):
                return None
            got[1]["binding"] = True
            _decided["row"] = got[1]
            return got[0]

        _bn_sampled: Dict[str, bool] = {}

        def _on_call(name, params):
            # PRE-call (run_node executes the same params dict after this):
            # browser_next's sampled rung may swap the element the model chose
            # for the Oracle's, labelled later by the turn verdict.
            if name != "browser_act" or not isinstance(params, dict) \
                    or params.get("element_id") is None:
                return
            try:
                from backend.agent import browser_next_shadow as _bn

                _hist0, _last0 = _step_so_far()
                pick = _bn.sampled_pick(
                    goal=goal, page_text=_last0 or "",
                    element_id=params.get("element_id"),
                    done_when=_done_when or None, calls_this_step=_hist0 or None)
                if pick is not None:
                    _orig = params.get("element_id")
                    params["element_id"] = int(pick) if isinstance(_orig, int) else pick
                    _bn_sampled["hit"] = True
            except Exception as _bn_err:  # noqa: BLE001 - the model's click stands
                logger.debug("[DER] browser_next sampled pick failed: %r", _bn_err)

        def _on_result(name, params, ok, approval_ok=None):
            # The call's OUTCOME is now known. Every node consult runs HERE,
            # post-hoc, on the PRE-CALL state: run_node calls this BEFORE it
            # appends the call and before it updates the last result, so
            # _step_so_far() still returns what the model saw before the call.
            # (2026-10-11: tool_choice and browser_next moved here from the
            # pre-call hook so their rows carry `brain_ok` - an outcome-checked
            # label and fine-tuning data, not only parity.)
            # v6 (2026-10-17): `approval_ok` is the CALL-level outcome for the
            # tool_approval label (a run_command that RAN counts as a
            # successful call whatever its exit code reported about the WORK);
            # `ok` stays the loop-level outcome every other reader uses.
            _hist, _last = _step_so_far()
            # A real tool call: a card-free turn earns its card at the bound.
            self._der_count_tool_call(item)
            # An Oracle-decided pick is labelled by what THIS call did.
            _pend = _decided.pop("row", None)
            if _pend is not None:
                # v4 (2026-10-21): the tool_choice label reads the CALL-level
                # outcome (`approval_ok`), not the loop's `ok` - the exact
                # tool_approval/v6 precedent. Measured on the grown v3 cohort:
                # binding run_command rows ranked at CHANCE (AUROC 0.4982,
                # 488 rows) because a mid-iteration pytest exit (the command
                # RAN, exit 1, the call did its job) was labeled a wrong
                # pick; 36 of 39 failed run_command calls in the logs were
                # ran-and-exited, not errored. The call-level label takes the
                # honest-key cohort from AUROC 0.657 to 0.7988 offline. For
                # every tool but run_command the two outcomes are identical.
                _label_ok = bool(approval_ok) if approval_ok is not None \
                    else bool(ok)
                box.label_decided_row(_pend, called=name, ok=_label_ok,
                                      params=params if isinstance(params, dict) else None,
                                      session_id=self.conversation_id or "voice")
            if name == "browser_act" and isinstance(params, dict) \
                    and params.get("element_id") is not None \
                    and not _bn_sampled.pop("hit", False):
                # (a sampled click is the Oracle's own element: its row is
                # already held for the turn verdict, so no parity shadow)
                try:
                    from backend.agent import browser_next_shadow as _bn

                    _bn.record_browser_next(
                        goal=goal, page_text=_last or "",
                        element_id=params.get("element_id"),
                        action=str(params.get("action") or ""),
                        done_when=_done_when or None, calls_this_step=_hist or None,
                        brain_ok=bool(ok),
                    )
                except Exception as _bn_err:  # noqa: BLE001 â€” a shadow never blocks
                    logger.debug("[DER] browser_next row failed: %r", _bn_err)
            try:
                # Same single ledger writer as the direct loop; async_=True runs
                # it on a daemon thread, so the node pays no latency.
                box.record_shadow_tool_choice(
                    goal=goal, observed_tool=name, observed_params=params,
                    candidates=_offered, last_result=_last or None,
                    option_criteria=_hints or None,
                    calls_this_step=_hist or None, done_when=_done_when or None,
                    step_facts=_facts_now() or None,
                    source="der_node", brain_ok=bool(ok),
                    session_id=self.conversation_id or "voice",
                    conversation_id=self.conversation_id or "", async_=True,
                )
            except Exception as _tc_err:  # noqa: BLE001 â€” a shadow never blocks
                logger.debug("[DER] tool_choice row failed: %r", _tc_err)

        # Eval C (owner 2026-10-02): the Brain helps a struggling tool model -
        # only when they are different models (a model cannot help itself).
        _helper = None
        try:
            # Provider AND model: Brain mercury-2.5 and tool mercury-2 share the
            # provider id "inceptionlabs", so comparing ids alone never engaged
            # the helper - a stuck node failed its step instead (live
            # 2026-10-03: 3x unchanged browser_observe -> split + recovery).
            _t = self._router.resolve("tool_execution")
            _r = self._router.resolve("reasoning")
            if (_t.id, getattr(_t, "model", None)) != (_r.id, getattr(_r, "model", None)):
                _helper = "reasoning"
        except Exception as _hr_exc:  # noqa: BLE001 - no helper, the node still runs
            logger.debug("[DER] node helper unresolved: %r", _hr_exc)
        # V8: the browser's marked screenshot reaches a model. The node's own
        # model takes it as an image when it can see; otherwise the resolved
        # vision model (brain / tool / local fallback) reads it as text.
        def _sees(role):
            from backend.agent.inference.router import supports_vision

            return supports_vision(self._router.resolve(role))

        def _look(jpeg_b64, question):
            import base64 as _b64

            from backend.agent.inference.router import resolve_vision_client

            _res, client = resolve_vision_client(self._router)
            return client.analyze_screen(_b64.b64decode(jpeg_b64), (
                "This is a screenshot of a web page. Each numbered box marks an "
                "element; the number is its element_id. Answer in at most five "
                f"short lines: {question}"
            ))

        try:
            # REQ-10/REQ-14 (Wave 5, AC14.3): one node's id per EXECUTION -
            # run_step retries, so a step can execute twice; the superseded
            # execution's claims are UNTESTED (the final execution is the
            # truth). The scope rides a contextvar on THIS node thread; the
            # close-claim probe only ever gets written TO (the closing rule
            # stays the sole judge of the loop - AC10.0's fences).
            from backend.agent import decision_engine as _de

            _key = (str(_turn_id or ""), str(getattr(item, "step_id", "") or ""))
            _exec_counts = getattr(self, "_der_node_exec_counts", None)
            if _exec_counts is None:
                _exec_counts = self._der_node_exec_counts = {}
            _exec_n = _exec_counts.get(_key, 0) + 1
            _exec_counts[_key] = _exec_n
            _exec_id = f"{_key[1]}#{_exec_n}" if _key[1] else ""
            _de.set_scope(turn_id=_turn_id, step_id=_key[1] or None,
                          node_exec_id=_exec_id or None)
            _close_probe = _de.CloseClaimProbe(
                turn_id=_turn_id or "", step_id=_key[1], node_exec_id=_exec_id,
                goal=goal)
            if _exec_n > 1:
                _close_probe.supersede_prior(f"{_key[1]}#{_exec_n - 1}")
        except Exception:  # noqa: BLE001 - measurement never blocks a node
            _close_probe = None
        try:
            # REQ-12 AC2 (T48): the tool steps are the ones that answer, and
            # this is the only executor they use. Give the node the earlier
            # statements with their producer, so a taught fact is available
            # without asking a tool to go and find it.
            try:
                from backend.agent.evidence import _memory_facts as _mf

                _step_facts = _mf(goal, getattr(self, "_memory_interface", None))
            except Exception:  # noqa: BLE001 - memory never blocks a step
                _step_facts = ""
            if _step_facts:
                self._turn_mem_prompts = int(
                    getattr(self, "_turn_mem_prompts", 0)) + 1
            _node_ctx = NodeContext(
            generate=_generate, execute=_execute,
            format_result=lambda name, raw: self._format_tool_result_for_step(raw, name),
            tools=tools, prior_results=_prior_results, task=task, workdir=workdir,
            conv_id=self.conversation_id or "", helper_role=_helper,
            on_result=_on_result, choose_tool=_choose_tool,
            on_call=_on_call,
            sees=_sees, look=_look,
            memory_facts=_step_facts,
            # the step's own criterion, its parent step, the reviewer's reason
            expected=str(getattr(item, "expected_output", "") or ""),
            parent_goal=str(getattr(item, "parent_description", "") or ""),
            review_note=str(getattr(item, "review_feedback", "") or ""),
            parallel_ok=_node_call_parallel_ok if _DER_PARALLEL else None,  # one off switch
            close_probe=_close_probe,
            )
            _node_state["ctx"] = _node_ctx
            result = run_node(goal, _node_ctx)
            _flush_decided()  # a last pick the step finished without calling
        finally:
            for _c in _held:
                _der_release(self, _c)
        # What the node actually did, for the step's physics action (REQ-8 redo).
        try:
            item.node_calls = [
                (str(c.get("tool") or ""), bool(c.get("ok"))) for c in (result.calls or [])
            ]
        except Exception:  # noqa: BLE001 - bookkeeping never fails a step
            item.node_calls = []
        # Every "what did this step do" reader goes through _step_calls(item).
        item.node_call_log = [dict(c) for c in (result.calls or [])]
        # A node's identity for repeat detection is the calls it made: its
        # item has no tool and no params (the planner emits goals only), so
        # params_digest(None, {}) was one key for EVERY node step and any node
        # could read as a repeat of another (c15, 2026-10-01: a replan storm).
        from backend.agent.tool_envelope import params_digest

        item.node_digest = params_digest("run_node", {"calls": [
            [str(c.get("tool") or ""), str(c.get("target") or "")] for c in (result.calls or [])
        ]})
        return result.as_step_result(), result.success

    def _der_run_step_execution(
        self,
        item: "QueueItem",
        context_package,
        _session: str,
        _turn_id: Optional[str],
        plan,
        queue=None,
    ) -> tuple:
        """
        Phase 4: execute a single DER step's tool/direct action.
        Returns (step_result: str, step_success: bool).
        Faithful extraction of the inline execution block from _execute_plan_der.

        Session 245 (synthesis starvation fix): ``queue`` joins the signature
        so the tool-decision evidence for tool-less steps can carry PRIOR
        completed step results â€” previously the evidence was metadata-only
        (session/turn/task_class), so a synthesis step after a successful
        crawl was decided by a model that had never seen a byte of the crawl
        output ("I am unable to access the search results", conv-36).
        """
        step_result = ""
        step_success = True
        try:
            # â”€â”€ Session 245: prior completed step results for the decision
            # evidence (Seam A of the synthesis starvation fix). Bounded per
            # result by tool-aware caps; steps without results are skipped.
            _prior_results: list = []
            if queue is not None:
                try:
                    for _pit in queue.items:
                        if _pit is item:
                            continue
                        _pr = getattr(_pit, "result", None)
                        if not _pr:
                            continue
                        _prior_results.append(
                            {
                                "step": getattr(_pit, "step_number", None),
                                "description": (getattr(_pit, "description", "") or "")[:120],
                                "result": self._smart_excerpt(
                                    _pr,
                                    _step_evidence_cap(_pit),
                                ),
                            }
                        )
                except Exception as _prio_err:
                    logger.debug("[DER] prior-result gather failed: %s", _prio_err)

            # Execution audit Phase 2: a tool-less step runs as a bounded work
            # loop (backend/agent/node_executor.py) instead of one tool picked
            # once. Both modes (owner 2026-10-03, V10: personal mode ran one
            # tool per step - no retry of a failed call, no page screenshot).
            if not item.tool:
                return self._der_run_node(item, _session, _turn_id, _prior_results,
                                          task=getattr(plan, "original_task", "") or "")

            # â”€â”€ Phase 2: dispatch (TOOL) or direct (REASON) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Set the phase gate call class so the gate knows whether to wait
            # (REASON/TOOL â†’ gated) or admit immediately (USER_TURN/SPEAK) (T3.7).
            # GRAFT is NOT high-priority (T6.4) â€” recovery-plan generation after
            # a step failure (including 429) must be gated to avoid amplification.
            if item.tool:
                set_call_class(CallClass.TOOL)
            else:
                set_call_class(CallClass.REASON)

            if item.tool and self._tool_bridge is not None:
                self._der_before_call(item.tool, _session)
                # Session-318 T18 (REQ-11 AC11.1): per-family deadline for
                # the dispatch below, plus the monotonic start stamp that
                # feeds elapsed_s and the stall warning at finalize.
                try:
                    _dispatch_deadline = self._der_tool_deadline(item.tool)
                except Exception:
                    _dispatch_deadline = 90.0
                try:
                    import time as _time_dispatch
                    item.dispatch_started_at = _time_dispatch.monotonic()
                except Exception:
                    pass
                try:
                    _dispatch_decision = Decision(
                        kind=DecisionKind.TOOL,
                        tool=item.tool,
                        params=item.params,
                    )
                    _dr = self._get_tool_box().dispatch(
                        _dispatch_decision,
                        session_id=_session,
                        conversation_id=self.conversation_id,
                        turn_id=_turn_id,
                        timeout_s=_dispatch_deadline,
                    )
                except Exception as _maybe_timeout:
                    # Session-318 T18 (REQ-11 AC11.3): deadline expiry settles
                    # honestly â€” synthetic failed DispatchResult so the normal
                    # downstream (record/call/capture/finalize) all run and the
                    # envelope stamps status=timeout via item.timed_out.
                    # Version-proof timeout check (TimeoutError aliases differ
                    # pre-3.11); anything else re-raises to the outer handler.
                    import asyncio as _aio_timeout_mod
                    import concurrent.futures as _fut_timeout_mod
                    if not isinstance(
                        _maybe_timeout,
                        (_aio_timeout_mod.TimeoutError,
                         _fut_timeout_mod.TimeoutError),
                    ):
                        raise
                    _timeout_text = (
                        f"[STEP TIMEOUT after {_dispatch_deadline:g}s "
                        f"(deadline {_dispatch_deadline:g}s) â€” tool "
                        f"{item.tool} did not settle; continuing without it. "
                        f"The worker was abandoned, not killed (threads "
                        f"cannot be aborted); tool-internal ceilings bound "
                        f"the orphan."
                    )
                    logger.warning(
                        "[DER] step %d tool %r timed out (deadline %.0fs)",
                        item.step_number, item.tool, _dispatch_deadline,
                    )
                    try:
                        item.timed_out = True
                    except Exception:
                        pass
                    try:
                        from backend.agent.write_counters import bump as _bump_dlh
                        _bump_dlh("envelope.deadline_hits")
                    except Exception:
                        pass
                    _dr = DispatchResult(
                        success=False,
                        result={"success": False, "error": _timeout_text,
                                "error_type": "timeout"},
                        error=_timeout_text,
                        error_type="timeout",
                    )
                except RuntimeError as _rte:
                    # asyncio.run() inside box may fail if an event loop is
                    # already running in this thread â€” executor fallback
                    logger.warning(
                        "[DER] box.dispatch RuntimeError for %s: %s â€” using executor",
                        item.tool, _rte,
                    )
                    import concurrent.futures as _cf
                    import asyncio as _asyncio

                    with _cf.ThreadPoolExecutor(max_workers=1) as _pool:
                        _raw_dr = _pool.submit(
                            _asyncio.run,
                            self._tool_bridge.execute_tool(
                                tool_name=item.tool,
                                params=item.params,
                                session_id=_session,
                                plan_title=plan.plan_title if plan else "",
                            ),
                        ).result(timeout=_dispatch_deadline)
                        _dr = DispatchResult(
                            success=isinstance(_raw_dr, dict) and _raw_dr.get("success") is not False,
                            result=_raw_dr,
                        )
                self._der_after_call(item, item.tool, item.params, _dr, _session, _turn_id)
                step_result = self._format_tool_result_for_step(
                    getattr(_dr, "result", None), item.tool,
                ) if _dr else ""
                if _dr and not _dr.success:
                    step_success = False
                    # A CRASHED dispatch returns DispatchResult(success=False,
                    # error=..., result=None) (tool_decision.py:2205): the tool
                    # exception was caught one level deeper, so `result` is
                    # None, `_format_tool_result_for_step` yields "", and the
                    # step reported an EMPTY failure - the message never
                    # reached the DER synthesis. The timeout path above avoids
                    # this by putting its message in `result`. Do the same
                    # here, using this function's own
                    # "[STEP ERROR: ...]" convention (see the outer except).
                    if not step_result:
                        _dr_err = getattr(_dr, "error", None)
                        if _dr_err:
                            step_result = f"[STEP ERROR: {_dr_err}]"
            else:
                # REASON (no tool) or no tool_bridge â€” direct reasoning
                step_result = self._run_step_direct(item, context_package, _session)
        except RateLimitedError:
            # Propagate rate-limit failures untouched so the DER layer can
            # record them honestly (REQ-3 AC4 / REQ-4 AC2). Do NOT wrap in a
            # string â€” the structured provider_id / retry_after fields are
            # needed by the ledger.
            raise
        except Exception as _ex_err:
            step_success = False
            step_result = f"[STEP ERROR: {_ex_err}]"
            logger.warning(
                f"[DER] Step {item.step_number} explorer error: {_ex_err}"
            )
        return step_result, step_success

    def _get_verifier(self):
        if self._VERIFIER is None:
            from backend.agent.verifier import SemanticVerifier as _SV
            AgentKernel._VERIFIER = _SV()
        return self._VERIFIER

    def _verified_fraction(self, expected: Optional[str], result: str) -> float:
        """DER Phase 0 (D0.6): fraction of checkable assertions from expected_output
        that the result satisfies. Deterministic, no LLM. Assertions split on ';'.

        Delegates to SemanticVerifier (Phase 4 LFM2.5 integration) for semantic
        entailment scoring with stub guard + substring fallback.
        """
        frac, _scorer = self._get_verifier().verified_fraction(expected, result)
        # REQ-18 AC1 (T31): correlate the scorer tag + score into the per-task
        # trace. Off the critical path; a trace failure never affects the verdict.
        # The verified_label is attached by the caller (it is only known after
        # the full _verify_step_result classification completes).
        try:
            from backend.agent.der_trace import get_der_trace

            get_der_trace(self._der_trace_task_id()).record(
                "verify",
                scorer_tag=_scorer,
                score=round(float(frac), 4),
            )
        except Exception:
            pass
        return frac

    def _verify_step_result(
        self,
        goal: str,
        expected: Optional[str],
        result: str,
        tool: Optional[str] = None,
        success: bool = False,
    ) -> str:
        """DER Phase 0 (D0.1): classify a step result.
        Returns VERIFIED | UNVERIFIED | FAILED.
        A stub pattern with no real output is ALWAYS FAILED (no silent success).

        pin_517dfcbda150: when ``tool`` is a web/crawl tool, the verdict is
        CONTENT SUFFICIENCY â€” the tool already proved it fetched pages (a
        zero-page crawl returns an error from tool_bridge), so a non-empty,
        non-error result VERIFIEDs. This terminates the crawl step as soon as
        real content exists and prevents pointless re-crawl splits.
        """
        if tool in self._TRUSTED_RESULT_TOOLS:
            # pin_42ddd255162d: display/render tools complete by SUCCESS, and
            # this check runs FIRST â€” the formatted result of the render tool
            # can be an empty/JSON-less string even on success (its dict has no
            # extractable content key), and the old position (after the
            # empty-result check) turned every successful render into a
            # verify-FAILED â†’ split â†’ children re-gathered the SAME urls while
            # the card said "rendering documents". A trusted tool that ran
            # returns "VERIFIED" unconditionally â€” its contract never returns
            # errors on the read-only render path.
            return "VERIFIED"
        if not result:
            return "FAILED"
        # Strip the marker; if nothing substantial remains, it was a bare stub -> FAILED.
        _without_marker = self._STUB_RE.sub("", result).strip()
        if not _without_marker:
            return "FAILED"
        # Execution audit B4 (2026-09-29): run_command reports success=True for
        # a command that ran and exited non-zero (REQ-19, so the output stays
        # readable). "The tool ran" is not "the step worked": a failing test
        # run was VERIFIED. A non-zero exit commits honestly as UNVERIFIED.
        if tool in self._SHELL_RESULT_TOOLS:
            _exit = re.match(r"\[exit code (-?\d+)\]", result)
            if _exit and int(_exit.group(1)) != 0:
                return "UNVERIFIED"
        if tool and tool in self._WEB_CONTENT_TOOLS:
            _low = _without_marker.lower()
            # pin_42ddd255162d: CONTENT SUFFICIENCY must not scan real page
            # text for failure words â€” web pages legitimately contain "failed
            # to"/"no usable" mid-text, and the crawl fallback result may
            # carry an informational worker-timeout note alongside real pages.
            # Session 248 FIX (live conv-53): the failure-word scan below ran
            # on the FULL combined article text (12k chars), so any news page
            # containing "failed to" anywhere FAILED the step -> split ->
            # children re-crawled the SAME query. The tool contract already
            # guarantees the error case (zero usable pages -> error payload),
            # so: error PREFIX always fails; long content always verifies;
            # only SHORT (<80 chars) non-error text may be scanned for
            # failure phrases, and even then it commits as UNVERIFIED rather
            # than triggering a re-gather split.
            if _low.startswith("error"):
                return "FAILED"
            # Session 312 (goal-result alignment, user-directed): a successful
            # fetch that never mentions the step's distinctive subject did NOT
            # serve the goal â€” conv-99 "verified" a Parakeet step with a
            # whisper.cpp dump. Distinctive terms = capitalized words in the
            # goal (proper nouns like model names); if NONE appear in the
            # result, commit honestly as UNVERIFIED so the next decision sees
            # the gap instead of believing the goal is served.
            _subj_terms = [
                w for w in re.findall(r"[A-Z][a-zA-Z0-9]{2,}", goal or "")
                if w.lower() not in {
                    "the", "and", "for", "with", "find", "search", "research",
                    "compare", "whether", "how", "its", "any", "github",
                    "documentation", "authoritative", "information",
                }
            ]
            if _subj_terms and not any(
                t.lower() in _low for t in _subj_terms
            ):
                logger.info(
                    "[DER] gather alignment MISS: goal %r â€” none of %s appear "
                    "in fetched content", goal[:80], _subj_terms[:4],
                )
                return "UNVERIFIED"
            if success:
                return "VERIFIED"
            if len(_without_marker) >= 80:
                return "VERIFIED"
            if "no usable" in _low or "failed to" in _low:
                return "FAILED"
            # Short, non-error text: weak but honest â€” commits as UNVERIFIED,
            # never triggers a re-gather split.
            return "UNVERIFIED"
        if tool in self._TRUSTED_RESULT_TOOLS:
            # pin_42ddd255162d: display/render tools complete by SUCCESS â€” a
            # rendered-card confirmation is a legit completion. The expected
            # assertion text (e.g. "a rendered document card") never matches
            # the short confirmation string, so the assertion path FAILED the
            # step and split it â€” spawning children that re-gathered web pages
            # while the card said "rendering documents".
            return "VERIFIED" if _without_marker else "FAILED"
        _frac = self._verified_fraction(expected, result)
        _expected_text = (expected or "").strip()
        if not _expected_text:
            # pin_42ddd255162d: no explicit expectation (REASON/synthesis and
            # render steps) â€” the assertion fraction is meaningless; the verdict
            # rests on SUBSTANCE: a substantial result VERIFIEDs, short text
            # commits honestly as UNVERIFIED. Only an explicit error/stub FAILs.
            # Live fix 2026-09-24 (conv-145): a real TOOL that reported
            # SUCCESS is verified BY that success - the tool performed its
            # action and said so. write_file returned
            # {"success": true, "message": "Written to eyes_note4.md",
            # "bytes": 103} - 71 chars - and the 80-char substance rule
            # marked the step UNVERIFIED even though the file was on disk and
            # the read-back succeeded. The contract then never covered its
            # required fact (covered=0) and the turn was narrated as an
            # incomplete task. The length rule still governs TOOL-LESS steps
            # (REASON/synthesis), where substance really is the only signal.
            if success and tool:
                return "VERIFIED"
            return "VERIFIED" if len(_without_marker) >= 80 else "UNVERIFIED"
        if _frac >= 0.8:
            return "VERIFIED"
        if _frac >= 0.3:
            return "UNVERIFIED"
        # Explicit expectation, low match: a SUBSTANTIAL result is still a real
        # answer â€” commit honestly as UNVERIFIED; only weak stubs FAIL.
        return "UNVERIFIED" if len(_without_marker) >= 200 else "FAILED"
