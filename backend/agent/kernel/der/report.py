# Moved from backend/agent/agent_kernel.py by scripts/kernel_split_check.py move.
# Bodies are byte-identical to the originals (guard: kernel_split_check.py manifest --check).
from __future__ import annotations

import re
import hashlib
from backend.agent import write_counters as _write_counters
from backend.agent import row_sequence as _row_sequence
from typing import Any, Dict, Optional, List, Callable, Tuple, Sequence
import json
import time
from dataclasses import dataclass, field
from backend.agent.kernel.base import (
    DER_MAX_UNVERIFIED_REPROPOSE,
    _step_calls,
    _step_decisive_call,
    _step_evidence_cap,
    logger,
)


_CLAIMS_MISSING_RE = re.compile(
    r"\b(?:did\s+not|didn't|does\s+not|doesn't|do\s+not|could\s+not|couldn't|"
    r"unable\s+to|failed\s+to|not\s+able\s+to)\b[^.\n]{0,60}?\b(?:include|return|"
    r"contain|find|found|provide|verify|confirm|retrieve|give)\b"
    r"|\bmissing\s+information\b|\bnot\s+(?:returned|found|included|available)\b",
    re.IGNORECASE,
)

def _claims_missing(reply: str) -> bool:
    """The reply says part of the answer is missing ("the tool results did not
    include the height...", "failed to verify the year"). Module level
    (stand-in kernels)."""
    return bool(_CLAIMS_MISSING_RE.search(reply or ""))

_STUB_STOPWORDS = frozenset(
    "the and but for with are was were this that you your our they them their its has have had not "
    "can will would should could let lets just now here there what which who how".split()
)

def _short_reply_carries_results(text: str, step_results) -> bool:
    """A short synthesis is an ANSWER, not a stub, when it repeats what the steps found: at least two of its
    content words (3+ letters, not stopwords), and at least half of them, appear in the step results. A stub
    ("Let's attempt that.") says nothing the steps found. Live 2026-10-26: the correct one-sentence reply
    "My test word is a blue pelican." (31 chars) fell under the 40-char floor twice and the user got the
    deterministic "I've completed the task." close instead - the usual source of that reply."""
    words = {w for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in _STUB_STOPWORDS}
    if len(words) < 2:
        return False
    found = " ".join(str((r or {}).get("result") or "") for r in (step_results or [])).lower()
    hits = sum(1 for w in words if w in found)
    return hits >= 2 and hits * 2 >= len(words)

def _der_neighbors_block(rows) -> str:
    """K2: the "RELEVANT NEIGHBORS" text for the rows that passed the relevance
    gate; "" when there are none, so nothing is injected. Module level on
    purpose (stand-in kernels bind only some methods). Bounded: 3 rows, 160
    chars each."""
    parts = []
    for n in (rows or [])[:3]:
        text = (n.get("insight") or "").strip()
        outcome = (n.get("result") or "").strip()
        # A step row keeps its text in insight and its outcome in result
        # ("success"/"failure"); a long result is the payload head instead.
        text = "{} [{}]".format(text, outcome[:40]) if text and outcome else (text or outcome)
        if text:
            parts.append("{} ({}/{}): {}".format(
                n.get("chain_id") or "",
                n.get("topic_domain") or "?",
                n.get("execution_domain") or "?",
                text[:160],
            ))
    return " | ".join(parts)

@dataclass
class TaskContext:
    """
    Carries full context through the entire task pipeline.

    This is the single object that carries context from the user's message
    through planning, execution, and response synthesis. It prevents context
    loss at handoff points between the brain and executor models.
    """

    task_id: str  # unique per user message
    user_message: str  # original user request â€” never lost
    session_id: str
    conversation_history: List[Dict]  # snapshot of memory at task start
    conversation_id: str = "default"
    plan: Optional[Dict] = None  # brain's plan (set after planning)
    # accumulates as steps execute
    step_results: List[Dict] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    def get_results_summary(self) -> str:
        """Get a formatted summary of all step results for the brain."""
        if not self.step_results:
            return "No tool results."

        summary_parts = []
        for i, result in enumerate(self.step_results, 1):
            if isinstance(result, dict):
                if "error" in result:
                    summary_parts.append(f"Step {i}: ERROR - {result.get('error')}")
                elif result.get("success"):
                    tool_name = result.get("tool", "unknown")
                    action = result.get("action", "")
                    result_text = result.get("result", result.get("response", ""))
                    # DER evidence is bounded once, per step, by its own window
                    # (_step_evidence_cap); a second 6,000 head+tail cut here
                    # dropped the middle of a three-search node (eval r09
                    # conv-820: "the tools did not return the other two facts").
                    if not result.get("bounded"):
                        result_text = self._bounded_excerpt(result_text)
                    summary_parts.append(
                        f"Step {i}: {tool_name} ({action}): {result_text}"
                    )

        return "\n".join(summary_parts) if summary_parts else "No tool results."

    @staticmethod
    @staticmethod
    def _bounded_excerpt(text: str, cap: int = 6000) -> str:
        """Session 247 (synthesis starvation, conv-44): the old
        ``result_text[:200]`` here chopped the brain's evidence to a URL â€”
        live: 3 usable pages crawled, browser tabs full of content, and the
        synthesis still said "the tool did not retrieve the paper's content"
        because its entire view of the crawl was 200 characters. This is NOT
        pacman (pacman_store/recall were 0 that run) â€” it was a prompt-size
        guard left far too tight. Head+tail excerpt keeps the prompt bounded
        while the brain actually sees the crawl: intro sentences AND the
        closing citation block."""
        t = (text or "").strip()
        if len(t) <= cap:
            return t
        _head = t[: int(cap * 0.7)]
        _tail = t[-int(cap * 0.3):]
        return f"{_head}\n[...{len(t) - cap} chars truncated...]\n{_tail}"

# Formatting rules appended to every prompt that produces USER-FACING prose.
#
# Models do not reliably structure a long answer on their own â€” a multi-tool
# result came back as one unbroken block, which is unreadable in a chat thread
# (2026-08-16). The reply is rendered as markdown, so ask for the structure
# explicitly, and scale it: a one-line answer must NOT grow headings.
_READABLE_FORMAT_RULES = """FORMATTING (your reply is rendered as markdown in a chat thread):
- Short answer (a sentence or two)? Write it plainly. No headings, no bullets.
- Longer answer? Make it scannable instead of one block of prose:
  - open with a short sentence saying what you found
  - `##` headings to separate distinct topics
  - `-` bullets for lists of findings
  - a markdown table for field/value pairs (specs, settings, counts)
  - `backticks` for paths, commands, filenames and code
  - a blank line between blocks â€” never run sections together
- Structure only where it aids reading. Do not pad a short answer to fill it.
- Report what the tools actually returned. If something was not returned, say
  so plainly rather than filling the gap."""


class DerReportMixin:
    def _turn_sources(self, conversation_id: str = "") -> List[str]:
        """The URLs this conversation's fetches produced (provenance, 2026-10-08).

        Read from the kernel's per-conversation crawled-URL set - the same set
        ``_der_visited_block()`` renders, which (per the note at the DER dispatch
        site) SURVIVES ACROSS TURNS per conversation, so a follow-up turn sees
        the URLs the previous turn fetched. A reference whose URL is recorded
        here is grounded as EXTERNAL by the planner; without it the thread
        carries only a bare ``owner/name`` token, which reads as a local path
        (measured live: a GitHub repo was searched for in the project root).

        ``conversation_id`` lets a caller that resolved the turn's conversation
        ITSELF (the gateway, whose mapping can differ from the kernel's) read the
        right key instead of silently getting [] on a mismatch.

        Never raises: provenance must never break a turn.
        """
        try:
            return sorted(
                (getattr(self, "_der_crawled_urls", None) or {})
                .get(conversation_id or self.conversation_id or "", ()) or ()
            )
        except Exception:  # noqa: BLE001 â€” an observer never blocks a turn
            return []

    def _der_visited_block(self) -> str:
        """REQ-8 AC8.2: bounded VISITED ledger block for planning and
        continuation prompts. Pointers only â€” URLs with the step that
        fetched them (AC8.4 join keys); page bodies never enter prompts
        (AC8.3). Empty ledger renders as "" (callers omit the block).
        Most-recent-first with an explicit +N marker; refusal/exclusion
        logic always uses the FULL in-memory set, never this view."""
        try:
            from backend.agent.der_constants import LEDGER_PROMPT_MAX
            _cap = max(int(LEDGER_PROMPT_MAX), 1)
        except Exception:
            _cap = 20
        try:
            _conv = self.conversation_id or ""
            _crawled = set(
                getattr(self, "_der_crawled_urls", {}).get(_conv, set())
            )
            if not _crawled:
                return ""
            # Insertion-ordered step map (most-recent last) first, then
            # any ledger-only remainder sorted for determinism.
            _stepmap = dict(
                getattr(self, "_der_crawled_steps", {}).get(_conv, {})
            )
            _ordered = [_u for _u in _stepmap if _u in _crawled]
            _ordered += sorted(_crawled - set(_stepmap))
            _ordered = _ordered[::-1][: _cap]
            _lines = [
                "VISITED THIS TURN (do not re-fetch â€” known-only "
                "discovery = pivot: propose a different approach instead):"
            ]
            for _u in _ordered:
                _sid = _stepmap.get(_u, "")
                _lines.append(
                    f"  - {_u}" + (f" (step {_sid})" if _sid else "")
                )
            try:
                from backend.agent.write_counters import bump as _bump_ledger
                _bump_ledger("envelope.ledger_renders")
            except Exception:
                pass
            if len(_crawled) > len(_ordered):
                _lines.append(f"  (+{len(_crawled) - len(_ordered)} more)")
            return "\n".join(_lines)
        except Exception:
            return ""

    def _der_report_run_grade(self, completed_items, _turn_id, _where):
        """Session-318 T19 (AC5.6 defect fix): done+GRADE reported once per
        turn at completion, on EVERY terminal path â€” not just the
        continuation-done branch (conv-102 proved queue-exhaustion ends
        never take it: zero grade lines). Deduplicated by turn_id so the
        finalize-complete site and the continuation site never double-log.
        Deterministic O(n) over envelopes; zero LLM. Never raises."""
        try:
            _last = getattr(self, "_der_last_run_grade", None) or {}
            if _last.get("turn_id") == (_turn_id or "") and _last.get("turn_id"):
                return _last.get("grade", "")
            from backend.agent.tool_envelope import evaluate_run_grade
            from backend.agent.der_constants import LOAD_BEARING_VETO
            _envs = [
                getattr(i, "envelope", None) for i in (completed_items or [])
            ]
            # Goal contract T10 (REQ-7/REQ-8): grade from coverage when a
            # contract exists â€” C=1.0 no-blocked is a pass; any open
            # unblocked fact caps below pass; all-blocked-and-named is a
            # partial (capped). Advisory: absent contract = legacy grade.
            _gc_state = getattr(self, "_goal_contract_state", None)
            _gc_c = None
            _gc_open: List[str] = []
            _gc_blocked: List[str] = []
            if _gc_state is not None:
                try:
                    _gc_c = float(_gc_state.get("C", 0.0))
                    _gc_open = self._goal_contract_open_facts()
                    _gc_blocked = self._goal_contract_blocked_texts()
                except Exception:
                    _gc_state = None
            _grade, _reasons = evaluate_run_grade(
                [e for e in _envs if e is not None],
                load_bearing_veto=LOAD_BEARING_VETO,
                coverage=_gc_c,
                open_unblocked=_gc_open,
                blocked=_gc_blocked,
            )
            self._der_last_run_grade = {
                "turn_id": _turn_id or "", "grade": _grade,
                "reasons": list(_reasons or []),
            }
            # Wave 5 (REQ-6 AC6.3 + REQ-14 AC14.4): the OUTCOME join. Sampled
            # consults are labelled by THIS turn's grade; any deferred closing
            # claim still pending at turn end sweeps to `abandoned` (counted,
            # never a fabricated negative). Runs once per turn (the grade
            # dedup above guarantees it).
            try:
                from backend.agent import decision_engine as _de_oc

                _de_oc.resolve_turn_pending(_turn_id or "", _grade == "pass")
                _de_oc.sweep_turn_pending(_turn_id or "")
                # tc-decide-v7 (2026-11-07): flush any DECIDED tool_choice row
                # whose step never settled (early turn end, exception). The row
                # is written WITHOUT an outside_label, so a flushed row is
                # counted and never scored - two label semantics never blend.
                try:
                    from backend.agent import tool_choice_outcome_label as _tcol

                    _tc_swept = _tcol.sweep()
                    if _tcol.enabled() and _tc_swept:
                        _tcol_st = _tcol.stats()
                        logger.info(
                            "[Oracle] tool_choice step-completion label: "
                            "swept_unsettled_now=%d flushed_unsettled_total=%d "
                            "dropped_overflow=%d",
                            _tc_swept,
                            _tcol_st.get("flushed_unsettled", 0),
                            _tcol_st.get("dropped_overflow", 0),
                        )
                except Exception:  # noqa: BLE001
                    pass
                # A row the native writer failed or dropped was invisible: app_write
                # returns once it is queued (2026-11-09 audit). One stats read per
                # turn; a WARNING only when the counts grew.
                try:
                    from backend.memory.db import report_native_write_losses

                    report_native_write_losses(getattr(self, "conversation_id", "") or "")
                except Exception:  # noqa: BLE001 - a diagnostic never fails a turn
                    logger.debug("[db] native write loss report skipped")
                # the held consult rows are stamped with what the turn NEEDED,
                # not the keyword list's parity. truth = "yes" when the request
                # named a URL (by rule), else "yes" when a web tool succeeded
                # and the turn passed, "no" when it passed without the web; a
                # failed turn leaves its rows on parity. try/except: a label
                # never blocks a turn.
                try:
                    from backend.agent import explorer as _exp_wi

                    _web_used = False
                    for _wi_it in (completed_items or []):
                        _wi_t = str(getattr(_wi_it, "tool", "") or "")
                        if (
                            _wi_t == "search"
                            or _wi_t == "crawler_query"
                            or _wi_t.startswith("browser")
                        ):
                            _wi_env = getattr(_wi_it, "envelope", None)
                            if _wi_env is not None and str(
                                getattr(_wi_env, "status", "")
                            ) == "success":
                                _web_used = True
                                break
                    # v3 (2026-10-18): the DER items miss the quick-tier /
                    # crawler searches (they run OUTSIDE the DER), so research
                    # turns that used the web were labelled "no web needed"
                    # and d1's correct "yes" answers scored wrong (measured:
                    # r01-r04 passed WITH search, every row outside=no). The
                    # bridge's chokepoint flag covers every dispatch.
                    if not _web_used:
                        try:
                            from backend.agent.tool_bridge import turn_used_web

                            _web_used = turn_used_web(_turn_id or "")
                        except Exception:  # noqa: BLE001
                            pass
                    _wi_n = _exp_wi.resolve_web_intent_turn(
                        _turn_id or "", _grade == "pass", _web_used
                    )
                    if _wi_n:
                        logger.info(
                            "[Oracle] web intent label: turn=%s labelled=%d "
                            "web_used=%s grade=%s",
                            _turn_id or "?", _wi_n, _web_used, _grade,
                        )
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001 - a label never blocks the turn
                pass
            # REQ-7 AC7.2: log the counters the contract introduced, naming
            # the reader for each (AC7.4): seeded/mapped/re-added feed T4;
            # covered/blocked feed T5/T9 + grade; amendments feed T7/T8;
            # stalls/bonus feed T6/T3.
            try:
                if _gc_state is not None:
                    _gc_counters = _gc_state.get("counters") or {}
                    logger.info(
                        "[goal-contract] counters (readers T4/T5/T6/T9/grade): "
                        "seeded=%s mapped=%s readded=%s covered=%s blocked=%s "
                        "amend_user=%s amend_agent=%s stalls=%s bonus=%s "
                        "C=%.3f g=%.3f",
                        _gc_counters.get("facts_seeded", 0),
                        _gc_counters.get("facts_mapped", 0),
                        _gc_counters.get("facts_readded", 0),
                        _gc_counters.get("facts_covered", 0),
                        _gc_counters.get("facts_blocked", 0),
                        _gc_counters.get("amendments_user", 0),
                        _gc_counters.get("amendments_agent", 0),
                        _gc_counters.get("stalls", 0),
                        _gc_counters.get("bonus_passes", 0),
                        float(_gc_state.get("C", 0.0)),
                        float(_gc_state.get("g", 1.0)),
                    )
            except Exception:
                pass
            logger.info(
                "[DER] run grade: %s%s (%s)",
                _grade,
                ("; reasons: " + "; ".join(_reasons)) if _reasons else "",
                _where,
            )
            # Session-326 (goal-contract terminal-signal diag): at every grade
            # chokepoint, settle the card. The grade helper was reachable from
            # three call sites â€” _execute_plan_der (failure-settled),
            # _der_finalize_step (finalize-complete), and _der_plan_next_step
            # (continuation-done) â€” but only _execute_plan_der's
            # _emit_terminal_event emitted a card frame. Without this emit,
            # regressions where the possess motion ran without writing a
            # task:done event left the card in Active Execution forever while
            # the turn had finished; follow-ups were then routed as steering
            # (anyCardWorking=True) into a closed turn.
            self._der_emit_card_settle(_turn_id, completed_items, _grade, _where)
            return _grade
        except Exception as _grade_exc:
            logger.debug("[DER] run grade computation failed: %s", _grade_exc)
            return ""

    def _der_recall_neighborhood(self, item, session_id: str = "") -> list:
        """REQ-20 AC3 (T21): filtered ontology-neighborhood chain recall.

        Builds RecallFilters from THIS node's record (node_type + both
        domain axes) and queries the shared chain with the widen-order
        (relationship -> type -> domain, winning scope logged). Returns
        chain-row dicts, or [] on any failure â€” the step proceeds on live
        state, never an error. Cross-conversation by default (AC1b):
        thread_id ranks, never filters.

        REQ-6 AC3 (semantic gate): the recall execution is the SHARED helper
        ``run_filtered_recall`` (ontology_recall.py) â€” the gate's Tier 2 calls
        the same code path, so the widen-order and telemetry cannot drift.

        REQ-4 AC4.2 (K2): the recalled rows then pass a RELEVANCE GATE - same
        topic AND token overlap with this step's goal (no embedding on the step
        path); survivors rank by state proximity then recency; none passing ->
        [] and the step carries no neighbors block at all (owner rule
        2026-09-30: chain data enters the context only when relevant).
        """
        try:
            from backend.agent.caducean_trajectory import latest_coords_str
            from backend.agent.ontology_recall import (
                CANDIDATE_POOL,
                RecallFilters,
                gated_neighborhood,
                resolve_mycelium_conn,
            )

            _rec = getattr(item, "node_record", None) or getattr(
                item, "footprint", None
            )
            _filters = RecallFilters(
                node_type=getattr(_rec, "node_type", None)
                or getattr(item, "node_type", None),
                topic_domain=getattr(_rec, "topic_domain", None)
                or getattr(item, "topic_domain", None),
                execution_domain=getattr(_rec, "execution_domain", None)
                or getattr(item, "execution_domain", None),
                thread_id=session_id or getattr(item, "session_id", None) or None,
                limit=CANDIDATE_POOL,  # the gate keeps at most 3 of these
            )
            if not _filters.has_any:
                return []  # no ontology axes on this node â€” nothing to filter

            _conn = resolve_mycelium_conn(self._memory_interface)
            if _conn is None:
                return []

            return gated_neighborhood(
                _conn,
                _filters,
                getattr(item, "description", "") or "",
                # Called only when more than one row passed the gate.
                state_fn=lambda: latest_coords_str(
                    self._memory_interface, session_id
                ),
                keep=3,
            )
        except Exception as exc:
            logger.debug("[DER] ontology neighborhood recall failed: %s", exc)
            return []

    def _build_crawl_failure_explanation(self, plan: "CrawlPlan") -> str:
        """User-facing explanation when the crawl plan found no usable sources.

        Called from the zero-steps fallback in ``_execute_plan_der``.  Returns
        a sentence explaining *why* the agent couldn't search the web, which
        ``_plan_task`` surfaces via the structured-response speak field.
        """
        _query = getattr(plan, "title", "") or ""

        # PREFER THE REASON THE PLANNER ACTUALLY RECORDED.
        # CrawlPlanner._empty_plan writes a specific cause into `instructions`
        # (e.g. "the provider rate window was already saturated (recent 429s)
        # ... retry the search shortly") precisely so the failure is reported
        # honestly. This function used to discard it and always emit the
        # bot-blocked guess below â€” so a user hitting a 60-second rate limit
        # was told to REPHRASE THEIR QUERY, which cannot help and sends them
        # down the wrong path. Only fall back to the generic text when the
        # planner did not say why.
        _reason = (getattr(plan, "instructions", "") or "").strip()
        if _reason and "LLM planning was skipped" in _reason:
            return (
                f"The agent could not search the web for {_query!r}. {_reason}"
            )

        _msg = (
            f"The agent was unable to find accessible web sources for "
            f"{_query!r}. This can happen when all generated URLs belong to "
            f"sites that block automated crawlers (academic publishers, "
            f"login-required portals, or bot-protected domains). "
            f"Try rephrasing your query to target public, accessible sites "
            f"such as news articles or Wikipedia."
        )
        return _msg[:400]

    @staticmethod
    def _der_node_record_evidence(item) -> str:
        """REQ-8 AC1 (T26): compressed synthesis evidence from a node record.

        Session 245 ADDITION: GATHER-tool steps bypass the compression â€”
        their raw output IS the payload the synthesis must read, so a
        content_summary[:300] of a 3-page crawl guarantees the final answer
        starves. They get a bounded-but-generous raw window instead; every
        other tool keeps the compressed-record behavior unchanged. When the
        item carries no node_record (empty memory edge case, REQ-8), falls
        back to the raw result truncated to a bounded window so a step is
        never silent.
        """
        try:
            # Gather tools: raw payload window (head+tail), compression OFF.
            # Session-323: stored-read tools join the wide path â€” a rerouted
            # read delivers the SAME gathered bytes through the document
            # store, and compressing them to a node-record summary re-starves
            # the synthesis the wide gather window was built to feed.
            # What the step DID, not item.tool: a node step (tool=None) that
            # searched got the 300-char record summary, so the synthesis never
            # saw the search results (evals 2026-10-04: r01/r06/r07 0/3,
            # "the results did not return the figures"; 8/8 on 2026-10-01).
            _wide = AgentKernel._DER_GATHER_TOOLS | AgentKernel._DER_READ_TOOLS
            if any(str(c.get("tool") or "").lower() in _wide for c in _step_calls(item)):
                _raw_gather = getattr(item, "result", "") or ""
                if _raw_gather:
                    return AgentKernel._smart_excerpt(_raw_gather, _step_evidence_cap(item))
            _rec = getattr(item, "node_record", None) or getattr(
                item, "footprint", None
            )
            if _rec is not None:
                _parts = []
                _cs = getattr(_rec, "content_summary", "") or ""
                if _cs:
                    _parts.append(f"summary: {_cs[:300]}")
                _eo = getattr(_rec, "expected_output", "") or ""
                if _eo:
                    _parts.append(f"done-when: {_eo[:200]}")
                _rm = getattr(_rec, "remaining", "") or ""
                if _rm:
                    _parts.append(f"remaining: {_rm[:200]}")
                _ro = getattr(_rec, "ruled_out", "") or ""
                if _ro:
                    _parts.append(f"ruled-out: {_ro[:200]}")
                if _parts:
                    return " | ".join(_parts)
            # No node record â€” bounded raw fallback (REQ-8 edge case).
            _raw = getattr(item, "result", "") or ""
            if _raw:
                return _raw[:400]
        except Exception:
            pass
        return ""

    def _der_synthesize_outcome(
        self,
        plan,
        completed_items: list,
        queue,
        _session: str,
    ) -> str:
        """
        Phase 1.5: produce a friendly, user-facing summary when one or more
        steps failed. Explains what was accomplished, what failed, and what
        to do next. Returns "" on any failure (caller falls back to raw output).
        """
        try:
            # REQ-8 AC1 (T26): build the synthesis from COMPRESSED node records
            # (content summary / done-when / remaining / ruled-out), not the raw
            # step outputs. Keeps the final summary bounded and free of
            # interleaved tool noise, and avoids replaying raw history into the
            # model.
            _done = "\n".join(
                f"[Step {ci.step_number}] {ci.description}: "
                f"{self._der_node_record_evidence(ci) or '(no result)'}"
                for ci in completed_items
            ) or "(none)"
            _failed_lines = []
            for _fi in queue.failed_ids:
                _desc = _fi
                for _it in queue.items:
                    if _it.step_id == _fi:
                        _desc = _it.description or _fi
                        break
                _failed_lines.append(f"- {_desc}")
            _failed = "\n".join(_failed_lines) or "(none)"
            _prompt = (
                f"USER TASK: {plan.original_task}\n\n"
                f"STEPS EXECUTED:\n{_done}\n\n"
                f"STEPS THAT FAILED:\n{_failed}\n\n"
                "Provide a friendly, user-facing summary of what was accomplished, "
                "what failed, and what to do next.\n\n"
                "Cover every part of the user's request. If the results lack "
                "some asked part, say which part is missing in one line â€” "
                "never skip it in silence.\n\n"
                + _READABLE_FORMAT_RULES
            )
            # The user-facing outcome summary is THINKING -> Brain (2026-08-16).
            _res = self.infer(_prompt, role="reasoning",
                              max_tokens=self.response_max_tokens(floor=400),
                              temperature=self.response_temperature())
            _out = _res.raw_text or ""
            # Spec A6 (AC3.5): same rule as the success path - a stub answer is
            # retried ONCE with the same inputs before the deterministic close.
            _stub_floor_f = max(80, 40 * (len(completed_items) + len(queue.failed_ids)))
            if _out.strip() and len(_out.strip()) < _stub_floor_f:
                logger.warning(
                    "[DER] failure synthesis stub (%d chars < %d floor) "
                    "â€” retrying once with the same inputs",
                    len(_out.strip()), _stub_floor_f,
                )
                _res = self.infer(_prompt, role="reasoning",
                                  max_tokens=self.response_max_tokens(floor=400),
                                  temperature=self.response_temperature())
                _out = _res.raw_text or ""
            # Session-345 (live, conv-134): with thinking disabled the model
            # may answer the failure-summary prompt with the tool-call ARGS
            # JSON â€” `{"query": ..., "top_n": 10}` went straight to chat AND
            # TTS. A bare-JSON final answer is never a user-facing message;
            # reject it so the deterministic failure close takes over.
            _stripped = _out.strip()
            if _stripped.startswith("{") and _stripped.endswith("}"):
                try:
                    import json as _json
                    _parsed = _json.loads(_stripped)
                    if isinstance(_parsed, dict) and "query" in _parsed:
                        logger.warning(
                            "[DER] failure synthesis returned tool-args JSON â€” "
                            "rejecting for deterministic close"
                        )
                        return ""
                except Exception:
                    pass
            # Session-326 shield 3, failure side: same stub rule as the
            # success path â€” a stub falls through to the deterministic
            # failure close, which names every failed step by shape.
            if _out and _out.strip():
                _stub_floor = max(80, 40 * (len(completed_items) + len(queue.failed_ids)))
                if len(_out.strip()) < _stub_floor:
                    logger.warning(
                        "[DER] failure synthesis stub (%d chars < %d floor) "
                        "â€” deterministic fallback",
                        len(_out.strip()), _stub_floor,
                    )
                    return ""
            # Shield 4 (live 2026-09-25): internal narration is not a summary.
            # A failed three-file turn showed the user "We haven't performed the
            # read yet. Need to call read_file for the three files.Let's run
            # read_file." â€” the model narrated its next move instead of telling
            # the user what happened. Reject it so the deterministic failure
            # close (which names each failed step) answers instead.
            from backend.agent.artifact_policy import looks_like_internal_narration

            if looks_like_internal_narration(_out):
                logger.warning(
                    "[DER] failure synthesis is internal narration â€” "
                    "deterministic close instead: %r", _out.strip()[:140],
                )
                return ""
            return _out
        except Exception as _e:
            logger.warning("[DER] outcome synthesis failed: %s", _e)
            return ""

    def _der_synthesize_success_outcome(
        self,
        plan,
        completed_items: list,
        queue,
        _session: str,
    ) -> str:
        """
        REQ-12 (AC1/AC2/AC3): success-path synthesis.

        Consumes the SAME evidence the failure path (``_der_synthesize_outcome``)
        consumes â€” ``plan.original_task`` plus each completed step's description
        and result â€” and routes it through the previously-dead
        ``_synthesize_response`` brain synthesis (AC3 wiring), which handles the
        InferenceRouter, LM Studio, and Ollama providers. Returns "" when
        synthesis is unavailable so the caller falls back to the deterministic
        success summary (AC4). Mirrors ``_der_synthesize_outcome``'s "" contract.
        """
        # Session 245 (verb progression): announce the SYNTH phase so the
        # working step's verb leaves SEARCH and shows SYNTH while the answer
        # is being composed â€” previously synthesis was invisible on the card.
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.TASK_PROGRESS,
                data={
                    "description": "Synthesizing answer",
                    "action": "Synthesizing",
                    "update_step": True,
                    "detail": "Synthesizing answer",
                    "detail_progress": "",
                    "phase": "synthesizing",
                    "phase_sequence": 90,
                    # GROUND TRUTH T29 (REQ-17 AC4): the synthesis row is a
                    # row like any other and needs the ordering key. T27
                    # flagged this one in EVERY captured trace, including the
                    # non-crawl code task - the defect was never crawl-specific.
                    "seq": _row_sequence.seq_for(
                        self.conversation_id, "phase-synthesizing"
                    ),
                },
                session_id=_session,
                conversation_id=self.conversation_id,
            )
        except Exception:
            pass  # never block synthesis on an emit failure
        try:
            _step_results = [
                {
                    "tool": getattr(ci, "tool", None),
                    "action": getattr(ci, "description", ""),
                    # REQ-8 AC1 (T26): compressed node-record evidence instead of
                    # the raw step output. The brain synthesis reads the bounded
                    # memory record, never the full raw history.
                    "result": self._der_node_record_evidence(ci) or "",
                    "bounded": True,  # already cut to its evidence window
                    "success": True,
                }
                for ci in completed_items
            ]
            _task = TaskContext(
                task_id=_session,
                user_message=plan.original_task,
                session_id=_session,
                conversation_history=[],
                plan={"original_task": getattr(plan, "original_task", "")},
                step_results=_step_results,
            )
            _syn = self._synthesize_response(_task, _step_results)
            if _syn and _syn.strip():
                # Session-326 shield 3 (owner: understudy rule): a stub turn
                # ("Let's attempt that.") counts as a failed synthesis â€” the
                # caller then serves the deterministic per-step close, which
                # covers every step by shape. Floor scales with steps so a
                # true one-liner on a one-step ask still airs.
                _syn_text = _syn.strip()
                # 40 chars per step. The old max(80, ...) contradicted the line
                # above: it rejected a correct one-step one-liner (r02,
                # 2026-09-30: a 46-char answer, twice) and served the raw close.
                # A stub is a NON-answer ("Let's attempt that.", 19 chars), so the
                # floor is about the reply, never the plan: 40 x steps rejected a
                # correct 101-char answer on a 4-step task, twice, and served the
                # raw step dump (live 2026-10-02 run A4: "Mount Kilimanjaro has an
                # elevation of 5,895 metres, and the first recorded ascent took
                # place in 1889."). A short reply carrying a number is an answer.
                _syn_floor = 40
                if (len(_syn_text) < _syn_floor and not re.search(r"\d", _syn_text)
                        and not _short_reply_carries_results(_syn_text, _step_results)):
                    # Spec A6 (AC3.5): a stub is often a one-off (measured: a
                    # 14-token turn on r02). Retry ONCE with the same inputs
                    # before giving up; only a stub that persists falls to the
                    # deterministic close (which never prints raw sources).
                    logger.warning(
                        "[DER] success synthesis stub (%d chars < %d floor) "
                        "â€” retrying once with the same inputs: %r",
                        len(_syn_text), _syn_floor, _syn_text[:120],
                    )
                    _retry = self._synthesize_response(_task, _step_results)
                    _retry_text = (_retry or "").strip()
                    if (len(_retry_text) >= _syn_floor or re.search(r"\d", _retry_text)
                            or _short_reply_carries_results(_retry_text, _step_results)):
                        _syn_text = _retry_text
                    else:
                        logger.warning(
                            "[DER] success synthesis stub persists after retry "
                            "(%d chars < %d floor) â€” deterministic fallback",
                            len(_retry_text), _syn_floor,
                        )
                        return ""
                logger.info(
                    "[DER] success synthesis ran (REQ-12 AC1) â€” steps=%d",
                    len(completed_items),
                )
                # The goal contract proved every asked fact has evidence (each
                # fact's own name in a VERIFIED result), yet the reply says a
                # part is missing: the reply model misread its evidence (r09
                # conv-834 / conv-884: "330 metres", "May 28, 1937" were in the
                # new results). One more write, told that every part is there.
                _gc_st = getattr(self, "_goal_contract_state", None)
                if (isinstance(_gc_st, dict) and float(_gc_st.get("C", 0.0)) >= 1.0
                        and _claims_missing(_syn_text)):
                    _facts = list(getattr(_gc_st.get("contract"), "required", ()) or ())
                    logger.warning(
                        "[DER] reply claims a part is missing but all %d required facts "
                        "have evidence â€” writing once more: %r",
                        len(_facts), _syn_text[:140],
                    )
                    _task.user_message = (
                        f"{plan.original_task}\n\n(CHECK: the tool results contain "
                        "evidence for EVERY asked part: "
                        + "; ".join(str(_f)[:120] for _f in _facts)
                        + ". Find each one in the results - PRIOR RESEARCH lines "
                        "count - and answer every part.)"
                    )
                    _again = (self._synthesize_response(_task, _step_results) or "").strip()
                    if _again:
                        _syn_text = _again
                # Shield 4 (live 2026-09-25): the success summary must be an
                # answer, not the model narrating its own tools. A report card
                # opened with "The tool only returned a partial draft; it omitted
                # full sections ...". Reject narration so the deterministic
                # per-step close answers instead.
                from backend.agent.artifact_policy import looks_like_internal_narration

                if looks_like_internal_narration(_syn_text):
                    logger.warning(
                        "[DER] success synthesis is internal narration â€” "
                        "deterministic close instead: %r", _syn_text[:140],
                    )
                    return ""
                return _syn_text
            return ""
        except Exception as _e:
            logger.warning("[DER] success synthesis failed: %s", _e)
            return ""

    @staticmethod
    def _humanize_evidence(text: str) -> str:
        """A tool result the user can read.

        A tool's ``summary`` is often its own JSON envelope. Unwrap it to the
        human field (message / content / text) so the user sees
        ``Written to zz_a.md`` rather than ``{"success": true, ...}``. Anything
        that is not a JSON object passes through unchanged.
        """
        t = (text or "").strip()
        if not (t.startswith("{") and t.endswith("}")):
            return t
        try:
            import json as _json

            _obj = _json.loads(t)
        except Exception:
            return t
        if not isinstance(_obj, dict):
            return t
        for _key in ("message", "content", "text", "result"):
            _val = _obj.get(_key)
            if isinstance(_val, str) and _val.strip():
                return _val.strip()
        return t

    @staticmethod
    def _no_raw_source_dump(text: str) -> str:
        """Spec A6 (AC3.5): a gather step's raw page content is never a user answer.

        When a deterministic close would show ``--- Source: URL ---`` page text (the
        r02 reply was exactly that), show which sources were read instead. Text
        without source headers passes through unchanged.
        """
        _urls = AgentKernel._SOURCE_HEADER_RE.findall(text or "")
        if not _urls:
            return text
        _hosts: list = []
        for _u in _urls:
            _h = re.sub(r"^https?://", "", _u).split("/")[0]
            if _h and _h not in _hosts:
                _hosts.append(_h)
        return (
            f"gathered content from {len(_urls)} source(s): "
            + ", ".join(_hosts[:5])
            + " - no written answer was produced from it"
        )

    @staticmethod
    def _der_user_facing_evidence(item) -> str:
        """T8 / fix 7 (specs/tool-result-envelope REQ-2 AC2.3): user-facing
        evidence is the OUTCOME, never internal mechanics.

        This used to return ``ToolEnvelope.line()``, whose own docstring reads
        'success, mismatched, repeat of step_1 â€” try_different, doc ab12ef34'.
        It is a DIAGNOSTIC string, and live 2026-09-25 the user was shown

            - Create zz_a.md ...: success â€” proceed, doc b2299b91-2c3 | {"success": true, ...}
            - Read the contents ...: success, [idling] â€” try_different, doc 43de69cd-343 | - Tea ...

        Verdicts (proceed/retry_same/try_different), stuck shapes ([idling]) and
        doc ids belong in the ledger. The user gets the status and what the step
        actually produced. The envelope's own diagnostics stay available through
        ``ToolEnvelope.to_dict()`` for the ledger and the metrics.
        """
        _env = getattr(item, "envelope", None)
        if _env is not None:
            _summary = AgentKernel._humanize_evidence(
                str(getattr(_env, "summary", "") or "")
            )
            _error = str(getattr(_env, "error_type", "") or "").strip()
            if _summary:
                _out = f"{_summary} (error: {_error})" if _error else _summary
                return AgentKernel._smart_excerpt(
                    AgentKernel._no_raw_source_dump(_out), 400
                )
            _status = str(getattr(_env, "status", "") or "").strip()
            if _status:
                return _status
        _ev = AgentKernel._der_node_record_evidence(item)
        if _ev:
            _ev = AgentKernel._no_raw_source_dump(_ev)
        return AgentKernel._smart_excerpt(_ev, 400) if _ev else ""

    @staticmethod
    def _der_deterministic_failure_summary(plan, completed_items: list, queue) -> str:
        """User-facing 'task incomplete' message that needs NO LLM call (Part B).

        ``_der_synthesize_outcome`` relies on ``infer()`` to write the summary.
        When the model is rate-limited/unavailable â€” the exact failure that
        triggered the research step's failure â€” that synthesis returns "" and the
        user is left with silence. This deterministic fallback guarantees the
        user always gets a clear "I couldn't complete X â€” these steps failed
        (and why)" message even if the LLM is down.
        """
        try:
            _failed = []
            for _fi in queue.failed_ids:
                _desc = _fi
                _reason = ""
                for _it in queue.items:
                    if _it.step_id == _fi:
                        _desc = _it.description or _fi
                        # T8/fix 7 (AC2.3): envelope line, never raw gather.
                        _reason = AgentKernel._der_user_facing_evidence(_it)
                        break
                _failed.append(f"- {_desc}" + (f": {_reason}" if _reason else ""))
            _failed_txt = "\n".join(_failed) or "(unknown step)"
            # No step count in the reply (owner 2026-10-26): "1/1 steps finished" is
            # bookkeeping, not an answer, in personal and developer mode alike.
            return (
                f"I couldn't complete that task. The following step(s) failed:\n{_failed_txt}\n\n"
                f"If a search or source failed, try rephrasing the request or "
                f"pasting the information directly â€” I can continue from where it stopped."
            )
        except Exception as _e:
            logger.warning("[DER] deterministic failure summary failed: %s", _e)
            return (
                "I couldn't complete that task â€” one or more steps failed. "
                "Please try again or rephrase the request."
            )

    @staticmethod
    def _der_deterministic_success_summary(plan, completed_items: list, queue) -> str:
        """User-facing 'task complete' message that needs NO LLM call (REQ-12 AC4).

        Mirrors ``_der_deterministic_failure_summary``: when the brain synthesis
        is unavailable (no reasoning model / providers down), this deterministic
        summary guarantees the user gets a clear statement of what was completed
        â€” never a silent raw concatenation of step outputs.
        """
        try:
            _done_lines = []
            for _ci in completed_items:
                # T8/fix 7 (AC2.3): envelope line + run grade honesty, never
                # the raw gather window.
                _res = AgentKernel._der_user_facing_evidence(_ci)
                _done_lines.append(
                    f"- {getattr(_ci, 'description', '') or _ci}"
                    + (f": {_res}" if _res else "")
                )
            _done_txt = "\n".join(_done_lines) or "(no step output)"
            # AC5.6: report done + grade â€” recomputed statelessly from the
            # envelopes (this is a @staticmethod; no instance state, no
            # shared mutable state). A load-bearing mismatch caps the run
            # below full pass, honestly, in the user-facing fallback too.
            _grade_line = ""
            _capped = False
            try:
                from backend.agent.tool_envelope import evaluate_run_grade
                from backend.agent.der_constants import LOAD_BEARING_VETO

                _envs = [
                    getattr(_ci, "envelope", None) for _ci in completed_items
                ]
                _grade, _reasons = evaluate_run_grade(
                    [e for e in _envs if e is not None],
                    load_bearing_veto=LOAD_BEARING_VETO,
                )
                if _grade == "capped":
                    _capped = True
                    _grade_line = (
                        "\nRun grade: capped below full pass â€” "
                        + "; ".join(_reasons or [])
                        + "\n"
                    )
            except Exception:
                pass
            # AC5.6 honesty (session-334, live T3): the grade is recomputed above
            # and can say "capped ... required fact(s) open and unblocked" while
            # this summary still opened with "I've completed the task". Measured
            # 2026-09-17: grade=capped C=0.000 with an open fact, narration said
            # "I've completed the task. 1/1 steps finished." â€” a false success
            # claim. The narration MUST agree with the grade it just computed.
            if _capped:
                return (
                    f"I couldn't fully complete the task - required work remains open.\n"
                    f"{_done_txt}\n{_grade_line}\n"
                    f"What would you like me to do next?"
                )
            return (
                f"I've completed the task.\n"
                f"{_done_txt}\n{_grade_line}\n"
                f"What would you like to do next?"
            )
        except Exception as _e:
            # AC5.6 honesty: this is the failure path â€” never claim success here.
            logger.warning("[DER] deterministic success summary failed: %s", _e)
            return "I finished running the steps but couldn't verify the result. What would you like me to do next?"

    def _der_trace_task_id(self) -> str:
        """Stable per-task key for the REQ-18 trace â€” mirrors the ledger's
        task_id (conversation_id or session_id), so the trace and the ledger
        correlate on the same task."""
        return self.conversation_id or self.session_id or "unknown"

    # â”€â”€ REQ-1 AC2/AC3/AC4: per-step edge scoring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    @staticmethod
    def _der_mediator_for(item: "QueueItem") -> tuple:
        """REQ-23 (T37): resolve the MEDIATOR for a finalized step.

        Returns (mediator, source):
          - mediator: ``"<tool>:<args_hash>"`` â€” the resolved tool/action
            identifier plus a stable hash of its arguments (AC1). The args
            hash is the separator between "the same tool with materially
            different arguments" (REQ-23 edge case).
          - source:   ``"explicit"`` (tool chosen by the normal resolver /
                      plan), ``"none"`` (a pure decision/synthesis node with
                      no tool â€” recorded EXPLICITLY, never empty, per AC5).

        The DER loop resolves tools through the plan/explorer path today, so
        the source is always ``"explicit"`` or ``"none"``; the ``"predictor"``
        / ``"fallback"`` sources are reserved for the T17 mediator-ranking
        wiring, which must record WHICH chooser picked the tool or the
        learning credits the wrong one (REQ-23 edge case).

        A node step has no item.tool (HANDOFF 11 B2): its mediator is the call
        that decided it (_step_decisive_call: the last failed call, else the
        last), hashed on that call's identifying args. Reading item.tool gave
        "none" for every node, so REQ-23/REQ-26 edges never learned from one.
        """
        if isinstance(getattr(item, "node_call_log", None), list):
            _call = _step_decisive_call(item)
            if not _call or not _call.get("tool"):
                return "none", "none"
            tool, _params = str(_call["tool"]), _call.get("args") or {}
        else:
            tool = getattr(item, "tool", None) or ""
            _params = getattr(item, "params", None) or {}
        if not tool:
            return "none", "none"
        try:
            _blob = json.dumps(_params, sort_keys=True, default=str)
            _args_hash = hashlib.sha256(_blob.encode("utf-8")).hexdigest()[:12]
        except Exception:
            _args_hash = "unhashable"
        return f"{tool}:{_args_hash}", "explicit"

    def _der_emit_fan_trace(
        self, item: "QueueItem", verified_label: str, session_id: str
    ) -> None:
        """GROUND TRUTH T4 (REQ-1): one der_fan_traces row per executed node.

        Same writer, same row shape, same table as the DCP path - only the CALL
        SITE moves (REQ-1 AC3). Idempotent per (session_id, step_id) so a DCP
        run cannot double-write (AC5).

        REQ-1 AC6: the node's terminal outcome is recorded FAITHFULLY. A FAILED
        node writes a failed row - a missing row and a failed row must never be
        indistinguishable, which is the whole ambiguity this spec exists to
        remove.

        Never blocks and never raises (AC4): a swallowed failure is COUNTED so
        persistent silence becomes a number rather than an absence.
        """
        try:
            _sid = session_id or "unknown"
            _step = str(getattr(item, "step_id", "") or "unknown")
            _guard = (_sid, _step)
            _seen = getattr(self, "_fan_trace_emitted", None)
            if _seen is None:
                _seen = set()
                self._fan_trace_emitted = _seen
            if _guard in _seen:
                return
            # Bounded: a very long run must not grow this without limit.
            if len(_seen) > 4096:
                _seen.clear()
            _seen.add(_guard)

            from backend.agent.caducean_trajectory import get_trajectory_recorder

            _rec = get_trajectory_recorder(self._memory_interface)
            if _rec is None:
                _write_counters.bump("fan_trace.no_recorder")
                return

            try:
                _mediator, _ = self._der_mediator_for(item)
            except Exception:
                _mediator = str(getattr(item, "tool", "") or "unknown")
            _tool = (_mediator or "unknown").split(":", 1)[0]

            _cad = self._der_live_cad_state(_sid) or {}
            _rec.record_fan_trace(
                session_id=_sid,
                step_id=_step,
                tool=_tool,
                args_hash=str(getattr(item, "args_hash", "") or "")[:12],
                outcome=str(verified_label or "UNKNOWN"),
                u=_cad.get("u"),
                xi=_cad.get("xi"),
            )
            _write_counters.bump("fan_trace.written")
        except Exception as _ft_exc:
            _write_counters.bump("fan_trace.write_failed")
            logger.warning(
                "[DER] fan trace write FAILED (session=%s step=%s): %s",
                session_id, getattr(item, "step_id", "?"), _ft_exc,
            )

    def _der_score_step_outcome(
        self,
        item: "QueueItem",
        verified_label: str,
        session_id: str,
        step_result: str,
    ) -> None:
        """Apply this step's edge-score consequence and, for FAILED, feed the
        AVOID header.

        This is deliberately a thin wiring call, not a new scorer: the deltas
        are the SAME generic table already defined in
        ``EdgeScorer._OUTCOME_DELTAS`` (scorer.py) â€” hit=+0.05, partial=+0.02,
        miss=-0.08 â€” now applied EVIDENCE-WEIGHTED (REQ-26/T40): the first
        observation on an edge moves it fully, later observations move it
        less, so belief converges instead of oscillating.

        REQ-26 AC1 (T40c): the scored edge is the (coordinate-region,
        mediator) pair for THIS step, selected by the CALLER â€” not every
        outbound edge of every active node. The REGION is the single active
        Mycelium node whose coordinates are nearest the step's live Caducean
        position Î£ = (x, y, Î¾, u) (the same state the chain row records):
        a step's outcome updates the region it was IN, and only that region.
        Scoring every active node would re-create the global fan-out the
        amendment removes â€” a step cannot fail "in two regions at once".
        The mediator is ``_der_mediator_for(item)`` (REQ-23/T37).
        ``EdgeScorer.record_region_mediator_outcome`` finds-or-creates that
        edge and updates ONLY it, so a tool that works in one region and
        fails in another is representable (a single global score cannot
        express that).

        REQ-1 AC2: VERIFIED  -> hit-scoring only (no crystallization change â€”
                   out of scope; no per-step crystallization exists today).
        REQ-1 AC3: UNVERIFIED -> partial credit, capped at
                   DER_MAX_UNVERIFIED_REPROPOSE + 1 scored attempts per
                   step_id (the original commit plus one re-propose) so an
                   UNVERIFIED step cannot be re-proposed indefinitely to farm
                   credit. Never crystallizes (no code path does today).
        REQ-1 AC4: FAILED    -> miss-scoring, and writes an episode with
                   outcome_type="miss" via the EXISTING ``_store_task_episode``
                   path â€” the same episodic-store write used for whole-task
                   outcomes â€” so evidence.py's AVOID section (which already
                   queries ``outcome_type = 'miss'``) surfaces it on the next
                   acting-prompt assembly. No second AVOID path is added.

        Never raises to the caller (see the try/except at the call site).
        """
        if verified_label not in ("VERIFIED", "UNVERIFIED", "FAILED"):
            return

        outcome = {
            "VERIFIED": "hit",
            "UNVERIFIED": "partial",
            "FAILED": "miss",
        }[verified_label]

        if verified_label == "UNVERIFIED":
            # AC3: enforce the re-propose cap BEFORE scoring â€” this is the
            # load-bearing guard, not advisory. Lazily initialised so this
            # works regardless of how the kernel was constructed (tests build
            # AgentKernel via __new__ without running __init__).
            if not hasattr(self, "_der_unverified_credit_counts"):
                self._der_unverified_credit_counts: Dict[str, int] = {}
            _count = self._der_unverified_credit_counts.get(item.step_id, 0)
            if _count > DER_MAX_UNVERIFIED_REPROPOSE:
                logger.debug(
                    "[DER] UNVERIFIED re-propose cap reached for step %s "
                    "(> %d) â€” no further partial credit",
                    item.step_id, DER_MAX_UNVERIFIED_REPROPOSE,
                )
                return
            self._der_unverified_credit_counts[item.step_id] = _count + 1

        # GROUND TRUTH T4 (REQ-1): write the per-node EXECUTION TRACE here, at
        # the node's terminal outcome - NOT as a side effect of context
        # pruning. record_fan_trace had exactly one production caller,
        # DCP._emit_fan_traces, and DCP is never constructed by the DER loop
        # (zero importers among agent_kernel / der_loop / iris_gateway). So
        # der_fan_traces held 0 rows in production no matter how much work
        # the agent did, while caducean_trajectories accumulated 201 through
        # the SAME recorder - the connection worked, only this path was
        # orphaned. Emitted BEFORE the mycelium block on purpose: the trace
        # must not inherit the edge-scoring guard's fragility (REQ-1 AC2).
        self._der_emit_fan_trace(item, verified_label, session_id)

        myc = getattr(self._memory_interface, "_mycelium", None) if self._memory_interface else None
        if myc is not None:
            try:
                _mediator, _mediator_source = self._der_mediator_for(item)
                if _mediator == "none":
                    # REQ-23 AC5: a node with NO mediator records "none" â€”
                    # there is no (region, mediator) edge to score. Pure
                    # decision/synthesis nodes are not learning events.
                    return
                _mediator_tool = _mediator.split(":", 1)[0]
                node_ids = list(getattr(myc._registry, "get_region", myc._registry.get_active)(session_id))
                # REQ-26 AC1: the step's REGION is the ONE active node whose
                # coordinates are nearest its live Î£ position â€” not every
                # active node (that would be a fan-out in region clothing).
                try:
                    _cad = self._der_live_cad_state(session_id)
                    _cad_vec = [
                        _cad.get("x", 0.0), _cad.get("y", 0.0),
                        _cad.get("xi", 0.0), _cad.get("u", 0.0),
                    ]

                    def _dist(nid: str) -> float:
                        _n = myc._store.get_node_by_id(nid)
                        if _n is None or not _n.coordinates:
                            return float("inf")
                        _c = list(_n.coordinates)[: len(_cad_vec)]
                        _v = _cad_vec[: len(_c)]
                        return sum((a - b) ** 2 for a, b in zip(_c, _v)) ** 0.5

                    # GROUND TRUTH T1 (REQ-5 AC1): distinguish "no active
                    # nodes registered at all" from "nodes exist but none
                    # resolved". Different root causes; only one is a bug
                    # in THIS block.
                    if not node_ids:
                        _write_counters.bump("edge_scoring.no_active_nodes")
                    _region_node = min(node_ids, key=_dist) if node_ids else None
                except Exception:
                    _write_counters.bump("edge_scoring.region_resolve_degraded")
                    _region_node = node_ids[0] if node_ids else None
            except Exception:
                _write_counters.bump("edge_scoring.region_resolve_failed")
                _region_node = None
                _mediator_tool = ""
            # GROUND TRUTH T1 (REQ-5 AC1, REQ-13 AC2): this guard used to
            # skip SILENTLY. mycelium_edges holds 0 rows in production
            # while this very call site exists, so the open question is
            # whether the guard never passes, the write raises, or edge
            # state lives elsewhere. A skip and a failure are DIFFERENT
            # causes and get different names.
            if not _region_node:
                _write_counters.bump("edge_scoring.skipped_no_region")
            if not _mediator_tool:
                _write_counters.bump("edge_scoring.skipped_no_mediator")
            if _region_node and _mediator_tool:
                try:
                    from backend.memory.mycelium.scorer import EdgeScorer

                    # REQ-26 AC1/T40c: the (coordinate-region, mediator)
                    # edge for THIS step â€” never the global fan-out.
                    EdgeScorer(myc._store).record_region_mediator_outcome(
                        region_node_id=_region_node,
                        mediator=_mediator_tool,
                        outcome=outcome,
                    )
                    # The POSITIVE makes the negatives interpretable:
                    # without it, zero writes and zero attempts look
                    # identical.
                    _write_counters.bump("edge_scoring.written")
                except Exception as _edge_exc:
                    # GROUND TRUTH T1: promoted from logger.debug. A
                    # swallowed WRITE failure that nothing counts is why
                    # this table could sit empty for months unnoticed.
                    _write_counters.bump("edge_scoring.write_failed")
                    logger.warning(
                        "[DER] region-scoped edge scoring FAILED "
                        "(session=%s region=%s mediator=%s): %s",
                        session_id, _region_node, _mediator_tool, _edge_exc,
                    )

        if verified_label == "FAILED":
            try:
                self._store_task_episode(
                    task_summary=item.description or "step",
                    full_content=str(step_result)[:500],
                    outcome_type="miss",
                    tool_sequence=[
                        {"tool": c.get("tool"), "step": item.step_number,
                         "success": bool(c.get("ok", True))}
                        for c in _step_calls(item)
                    ] or [{"tool": "reasoning", "step": item.step_number}],
                    session_id=session_id,
                )
            except Exception as _ep_exc:
                logger.debug(
                    "[DER] FAILED-step AVOID episode write failed: %s", _ep_exc
                )

    def _der_topic_domain(self, text: str) -> str:
        """REQ-18 AC2/AC3 (T19): resolve free text to a registry topic_domain.

        Thin wrapper over the mycelium registry resolver (extractor.py
        ``resolve_topic_domain``) so the kernel never touches keyword patterns
        directly and unknown text resolves to the registry's ``general`` bucket
        with a logged mismatch â€” never invented free text. Lazy import keeps
        the mycelium extractor off the module import path (heavy-import rule).
        """
        try:
            from backend.memory.mycelium.extractor import resolve_topic_domain

            return resolve_topic_domain(text or "")
        except Exception as _td_exc:  # noqa: BLE001 â€” never block a step
            logger.debug(
                "[DER] topic_domain resolve failed (%s) â€” falling back to "
                "'general'",
                _td_exc,
            )
            return "general"

    def _der_execution_domain(self, from_voice: bool = False) -> str:
        """REQ-18 AC2 (T19): resolve the node's execution_domain axis.

        Registry-backed: one of ``voice | der | research`` from the ACTIVE
        winding. ``voice`` when the turn entered via voice; ``research`` when
        the task class is research-shaped (research|explore|investigate, the
        same set der_loop._decide_mode uses); otherwise ``der``. This is the
        request-domain axis â€” how the node RUNS, distinct from ``topic_domain``
        (what it is ABOUT). Unknown windings resolve to the session default
        (``der``) â€” never invented free text (REQ-18 AC3).
        """
        if from_voice:
            return "voice"
        _tc = str(getattr(self, "_der_task_class", "") or "").lower()
        # TaskClassifier labels carry a "_task" suffix ("research_task");
        # the bare set never matched them (MEMORY-INTERFACE Part II 13.2).
        if _tc.endswith("_task"):
            _tc = _tc[: -len("_task")]
        if _tc in ("research", "explore", "investigate"):
            return "research"
        return "der"

    def _generate_response(
        self,
        user_message: str,
        plan: Dict[str, Any],
        execution_results: List[Any],
        context: List[Dict[str, Any]],
    ) -> str:
        """
        Generate final response based on plan and execution results.

        Args:
            user_message: Original user message
            plan: Generated plan
            execution_results: Results from execute_plan()
            context: Conversation context

        Returns:
            Final response text
        """
        # Check if any steps failed
        has_errors = any(
            isinstance(r, dict) and ("error" in r or not r.get("success", True))
            for r in execution_results
        )

        # Build response based on results
        if has_errors:
            error_messages = [
                r.get("error", "Unknown error")
                for r in execution_results
                if isinstance(r, dict) and "error" in r
            ]
            return f"I encountered some issues: {'; '.join(error_messages)}"

        # Extract successful results
        success_results = [
            r
            for r in execution_results
            if isinstance(r, dict) and r.get("success", False)
        ]

        if not success_results:
            return "I've processed your request."

        # Format response based on results
        if len(success_results) == 1:
            result = success_results[0]
            if "response" in result:
                return result["response"]
            elif "result" in result:
                return result["result"]

        # Multiple results - summarize
        summary_parts = []
        for r in success_results:
            if "result" in r:
                summary_parts.append(
                    f"- {r.get('action', 'Action')}: {r['result'][:100]}"
                )
            elif "response" in r:
                summary_parts.append(f"- {r['response'][:100]}")

        if summary_parts:
            return "I've completed your request:\n\n" + "\n".join(summary_parts)

        return "I've processed your request."

    def _synthesize_response(
        self, task: TaskContext, execution_results: List[Any]
    ) -> str:
        """
        Synthesize response using the brain model with tool results.

        This addresses Bug 2: The brain now sees the actual tool output
        before generating the final response.

        Args:
            task: TaskContext containing user message and plan
            execution_results: Results from execute_plan()

        Returns:
            Synthesized response from the brain model
        """
        # Short-circuit: if the plan already contains a raw free-form response
        # (model didn't output JSON), return it directly without a second model call.
        if task.plan and task.plan.get("_raw_response"):
            logger.info("[AgentKernel] Using raw plan response (no synthesis needed)")
            return task.plan["_raw_response"]

        # Get results summary for the brain
        results_summary = task.get_results_summary()

        # Build synthesis prompt for the brain
        synthesis_prompt = f"""User request: {task.user_message}

Tool execution results:
{results_summary}

Based on the tool results above, provide a natural response to the user's request.
If any tools failed, address those issues in your response.
Cover every part of the user's request. If the results lack some asked part, say which part is missing in one line â€” never skip it in silence.
If a CROSS-CHECK section is present, say which facts are confirmed since the earlier date and which changed.
PRIOR RESEARCH lines are results of earlier searches: a fact found only there is NOT missing - give it with its date.

{_READABLE_FORMAT_RULES}
"""

        try:
            # Get reasoning model for synthesis â€” only use local model if it's
            # actually loaded.  Do NOT call get_reasoning_model() as a fallback here:
            # that can return a broken/unloaded stub which echoes garbage like
            # "respond_to_user" back to the user verbatim.
            reasoning_model = None
            if self._model_router and self._selected_reasoning_model:
                reasoning_model = self._model_router.models.get(
                    self._selected_reasoning_model
                )

            if reasoning_model:
                # Call the loaded local/LFM model for synthesis. In-process
                # local models never report a usage block (no HTTP response to
                # parse), so this is an ESTIMATE-only accrual (D1 item 4/5) â€”
                # there is no real number available to prefer here.
                _raw_reply = reasoning_model.generate(synthesis_prompt)
                response = self._strip_thinking(_raw_reply)
                self._accrue_tokens(
                    _raw_reply, None, source="_synthesize_response:local"
                )
                logger.info(
                    "[AgentKernel] Brain synthesized response with tool results context"
                )
                return response

            # Primary path: route synthesis through the unified InferenceRouter so
            # API providers (Cerebras, OpenAI, â€¦) are used for the brain answer,
            # not just local/Ollama models. Legacy LM Studio / Ollama branches
            # below remain as fallbacks for local-model configurations.
            #
            # REQ-8 AC3 (T26): when the ROUTER holds the primary provider (its
            # health check reports ok), a router failure degrades DIRECTLY to the
            # compressed-summary fallback â€” we do NOT replay the giant synthesis
            # prompt through the LM Studio / Ollama chain (the 429-stall
            # behaviour REQ-8 fixes). LM Studio / Ollama are only tried when the
            # router has NO bound provider (local-only configurations), where
            # they ARE the primary path.
            _router_primary = False
            try:
                if self._router is not None:
                    _router_primary = bool(
                        self._router.health_check_provider("reasoning").get("ok")
                    )
            except Exception:
                _router_primary = False
            try:
                # AC11.6 (session-319): the user-facing answer was the ONLY
                # unbounded wait left in the turn â€” no timeout here, and the
                # transport retried 3x60s beneath it, so one slow provider
                # response could stall the turn for ~3 minutes with nothing
                # watching. This bounds it. On expiry the exception path below
                # degrades to the deterministic compressed summary, which is
                # the honest outcome. Safety net BEHIND streaming (AC13.1),
                # not the primary speed mechanism.
                try:
                    from backend.agent.der_constants import DEADLINE_SYNTHESIS_S
                    _syn_deadline_s = float(DEADLINE_SYNTHESIS_S)
                except Exception:
                    _syn_deadline_s = 120.0
                _syn_text, _syn_think, _syn_tools = self._router.generate(
                    "reasoning",
                    [{"role": "user", "content": synthesis_prompt}],
                    max_tokens=self.response_max_tokens(),
                    temperature=0.6,
                    timeout_s=_syn_deadline_s,
                )
                self._accrue_tokens(
                    _syn_text, getattr(self._router, "last_usage", None),
                    source="_synthesize_response:router",
                )
                # Session-342 (live 2026-09-19): Ollama intermittently answers
                # a synthesis prompt with an EMPTY completion (HTTP 200, no
                # text) while the provider is healthy â€” observed on a working
                # run where the crawl had extracted the answer and the turn
                # degraded to "I've completed the task" anyway. A single retry
                # on the SAME prompt recovers it; without that the user sees a
                # task-status receipt instead of the answer the run found.
                # Bounded: exactly ONE retry, inside the existing deadline.
                if not _syn_text and _router_primary:
                    logger.warning(
                        "[AgentKernel] router synthesis returned empty â€” retrying "
                        "once before degrading (transient empty completion)"
                    )
                    _syn_text, _syn_think, _syn_tools = self._router.generate(
                        "reasoning",
                        [{"role": "user", "content": synthesis_prompt}],
                        max_tokens=self.response_max_tokens(),
                        temperature=0.6,
                        timeout_s=_syn_deadline_s,
                    )
                    self._accrue_tokens(
                        _syn_text, getattr(self._router, "last_usage", None),
                        source="_synthesize_response:router:retry_empty",
                    )
                if _syn_text:
                    logger.info(
                        "[AgentKernel] Brain synthesized response via InferenceRouter"
                    )
                    return self._strip_thinking(_syn_text)
                if _router_primary:
                    # Empty response from the primary provider counts as failure
                    # (the health check reports ok even when the endpoint returns
                    # nothing â€” reachability is only proven at execution time).
                    logger.warning(
                        "[AgentKernel] router (primary) returned empty synthesis â€” "
                        "degrading to compressed-summary fallback (REQ-8 AC3)"
                    )
                    return ""
            except Exception as _syn_err:
                logger.warning(
                    f"[AgentKernel] router synthesis failed: {_syn_err}"
                )
                # Session-342 (live 2026-09-19): the transport RAISES on a
                # transient empty completion ("Empty response from Ollama"),
                # never returning a falsy string â€” so the success-path retry
                # above never fired and the turn degraded to "I've completed
                # the task" while the answer sat extracted on the card. Retry
                # once on THIS shape only; any other failure degrades exactly
                # as before.
                if _router_primary and "empty response" in str(_syn_err).lower():
                    logger.warning(
                        "[AgentKernel] synthesis failed on a transient empty "
                        "completion â€” retrying once (session-342 evidence: the "
                        "same endpoint answered 688 tokens 16s earlier)"
                    )
                    try:
                        _syn_retry, _syn_retry_think, _syn_retry_tools = (
                            self._router.generate(
                                "reasoning",
                                [{"role": "user", "content": synthesis_prompt}],
                                max_tokens=self.response_max_tokens(),
                                temperature=0.6,
                                timeout_s=_syn_deadline_s,
                            )
                        )
                        self._accrue_tokens(
                            _syn_retry,
                            getattr(self._router, "last_usage", None),
                            source="_synthesize_response:router:retry_empty",
                        )
                        if _syn_retry:
                            logger.info(
                                "[AgentKernel] Brain synthesized response via "
                                "InferenceRouter (retry after empty completion)"
                            )
                            return self._strip_thinking(_syn_retry)
                    except Exception as _retry_err:
                        logger.warning(
                            f"[AgentKernel] empty-response retry failed: {_retry_err}"
                        )
                if _router_primary:
                    # REQ-8 AC3 (T26): primary provider failed â€” degrade to the
                    # deterministic compressed summary, no giant-prompt replay.
                    logger.warning(
                        "[AgentKernel] router is the primary provider and failed â€” "
                        "degrading to compressed-summary fallback (REQ-8 AC3)"
                    )
                    return ""

            # Try LM Studio synthesis
            _sel_synth = self._selected_reasoning_model or ""
            if not reasoning_model and self._is_openai_compat():
                try:
                    _lms_synth = self._get_lmstudio_client()
                    _lms_synth_resp = _lms_synth.chat.completions.create(
                        model=_sel_synth or "local-model",
                        messages=[{"role": "user", "content": synthesis_prompt}],
                        max_tokens=-1,
                        temperature=0.7,
                        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                    )
                    _synth_text = _lms_synth_resp.choices[0].message.content
                    if _synth_text:
                        logger.info("[AgentKernel] LM Studio synthesized response")
                        return self._strip_thinking(_synth_text)
                except Exception as _lms_synth_err:
                    logger.warning(
                        f"[AgentKernel] LM Studio synthesis failed: {_lms_synth_err}"
                    )

            # Try Ollama if the selected model is an Ollama model (colon-format ID)
            if not reasoning_model and ":" in _sel_synth:
                try:
                    import requests as _req

                    _r = _req.post(
                        f"{self._ollama_endpoint}/api/chat",
                        json={
                            "model": _sel_synth,
                            "messages": [{"role": "user", "content": synthesis_prompt}],
                            "stream": False,
                        },
                        timeout=60,
                    )
                    if _r.status_code == 200:
                        _synth_text = _r.json().get("message", {}).get("content", "")
                        if _synth_text:
                            logger.info("[AgentKernel] Ollama synthesized response")
                            return self._strip_thinking(_synth_text)
                except Exception as _ollama_synth_err:
                    logger.warning(
                        f"[AgentKernel] Ollama synthesis failed: {_ollama_synth_err}"
                    )

            # No model available for synthesis. Return "" instead of a generic
            # template so the REQ-12 success path falls through to the DER-shaped
            # deterministic summary (_der_deterministic_success_summary) that
            # mirrors _der_deterministic_failure_summary â€” never a silent raw
            # concatenation of step outputs (REQ-12 AC4).
            logger.warning(
                "[AgentKernel] No model for synthesis â€” returning empty "
                "(caller falls back to deterministic summary)"
            )
            return ""

        except Exception as e:
            logger.error(f"[AgentKernel] Error in brain synthesis: {e}")
            return ""
