# Moved from backend/agent/agent_kernel.py by scripts/kernel_split_check.py move.
# Bodies are byte-identical to the originals (guard: kernel_split_check.py manifest --check).
from __future__ import annotations

import re
from typing import Any, Dict, Optional, List, Callable, Tuple, Sequence
import time
from backend.utils.observability import (
    TurnMetrics,
    loud_error,
    get_turn_id,
    broadcast_inference_event,
)
from backend.agent.kernel.base import (
    ResolvedWindow,
    _FILL_NO_TURN,
    logger,
)


def _fact_line(text: str) -> str:
    """The USER half of a stored turn pair, for fact-identity comparison."""
    t = str(text or "").replace("\r", "")
    if t.startswith("User:"):
        t = t[len("User:"):]
    return t.split("\nAssistant:")[0].strip().replace("\n", " ")

def _recent_user_turn_texts(db, current_text: str = "", limit: int = 8):
    """The newest user statements from the Immortus chain, newest first.

    Source is ``memory_chain.node_type='user_turn'`` (REQ-12 AC1): the chain
    records every turn, while ``context_chunks.tool_name='user_turn'`` landed
    for a few turns only and chunk pruning removed the rest (measured
    2026-10-30: 158 chain rows vs 1 chunk row after a 33-turn probe run).
    The current turn's own row is written at turn entry, so it is skipped here —
    it is not a prior fact.
    """
    try:
        rows = db.execute(
            "SELECT COALESCE(insight, content, '') FROM memory_chain "
            "WHERE node_type='user_turn' AND (stale IS NULL OR stale = 0) "
            "ORDER BY rowid DESC LIMIT ?",
            (limit + 1,),
        ).fetchall()
    except Exception:  # noqa: BLE001 - a missing table is no facts, not a crash
        return []
    out = []
    for row in rows:
        text = str((row[0] if row else "") or "").strip()
        if text.startswith("User:"):
            text = text[len("User:"):]
        text = text.split("\nAssistant:")[0].strip().replace("\n", " ")
        if not text or text == str(current_text or "").strip():
            continue
        out.append(text[:240])
        if len(out) >= limit:
            break
    return out

def _same_fact_unit(a: str, b: str, threshold: float = 0.8) -> bool:
    """Same statement restated, by identity OR by near-identical wording.

    `_same_fact_text` only recognises a few shapes ("my X is Y"); a taught fact
    phrased "Remember this for later: I prefer the color fern-alpha-... for
    status indicators" is NOT matched by it (measured 2026-10-31), yet the two
    variants share 0.89 of their tokens. High token overlap catches the restated
    fact without merging genuinely different facts (a different attribute shares
    far fewer tokens).
    """
    try:
        from backend.memory.episodic import _same_fact_text

        if _same_fact_text(a, b):
            return True
    except Exception:  # noqa: BLE001 - fall through to the overlap test
        pass
    ta = set(re.findall(r"[a-z0-9_]+", str(a or "").lower()))
    tb = set(re.findall(r"[a-z0-9_]+", str(b or "").lower()))
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= threshold

def _dedupe_fact_rows(rows):
    """rows = [(text, timestamp)]. Keep only the NEWEST statement of one fact.

    Score order is not time order: a cross-session chunk recall returns the best
    match first, and two statements of the same attribute with different values
    ("...prefer the color fern-alpha..." / "...fern-bravo...") both match. The
    model then picked either one (BT-W10-2, 2026-10-31). Sorting by the row's
    timestamp and keeping the first of each same-fact group makes the newest the
    only one that reaches the prompt.
    """
    try:
        from backend.memory.episodic import _same_fact_text  # noqa: F401
    except Exception:  # noqa: BLE001 - the overlap test below still works
        pass
    ordered = sorted(rows, key=lambda r: str(r[1] or ""), reverse=True)
    kept: list = []
    out: list = []
    for text, _ts in ordered:
        unit = _fact_line(text)
        if any(_same_fact_unit(unit, k) for k in kept):
            continue
        kept.append(unit)
        out.append(text)
    return out

def _dedupe_fact_lines(lines, against=None):
    """Keep NEWEST-first facts, dropping an older statement of the SAME fact.

    The recent-facts leg is newest-first. `_same_fact_unit` decides identity:
    `_same_fact_text` shapes OR a high token overlap. The shape test alone did
    NOT catch a taught fact ("...prefer the color fern-alpha-... for status
    indicators" vs the bravo wording), so both reached the prompt and the model
    picked the older one (BT-W10-2, 2026-10-31, after the chunk leg was already
    deduped).
    """
    kept = [_fact_line(x) for x in (against or [])]
    out = []
    for ln in lines:
        u = _fact_line(ln)
        if any(_same_fact_unit(u, k) for k in kept):
            continue
        out.append(ln)
        kept.append(u)
    return out


class ContextMixin:
    def save_context_to_store(self) -> None:
        """Persist current conversation context (history + token state) to the
        store (best-effort). Serializes the full message list so a later
        restore can rebuild the thread's conversation history."""
        try:
            from backend.agent.conversation_context_store import (
                get_context_store,
                ConversationContext,
                ConversationMessage,
            )

            store = get_context_store()
            _msgs = []
            if self._conversation_memory is not None:
                for _m in self._conversation_memory.messages:
                    _msgs.append(
                        ConversationMessage(
                            role=getattr(_m, "role", "user"),
                            content=getattr(_m, "content", "") or "",
                            timestamp=getattr(_m, "timestamp", time.time()),
                            turn_id=getattr(_m, "task_id", None),
                            sources=list(getattr(_m, "sources", None) or []),
                        )
                    )
            ctx = ConversationContext(
                conversation_id=self.conversation_id,
                messages=_msgs,
                tokens_used=getattr(self, "_tokens_used", 0),
                context_fill=getattr(self, "_context_fill", 0),
            )
            store.save(self.conversation_id, ctx)
        except Exception as exc:
            logger.warning(
                f"[AgentKernel] save_context_to_store failed "
                f"for conv={self.conversation_id}: {exc}"
            )

    def restore_context_from_store(self) -> None:
        """Restore conversation context (history + token state) from the store
        (best-effort). Rebuilds self._conversation_memory from the persisted
        message list so a resumed thread keeps its full history."""
        try:
            from backend.agent.conversation_context_store import get_context_store

            store = get_context_store()
            ctx = store.get_or_restore(self.conversation_id)
            if ctx:
                self._tokens_used = ctx.tokens_used
                self._context_fill = int(getattr(ctx, "context_fill", 0) or 0)
                if ctx.messages and self._conversation_memory is not None:
                    self._conversation_memory.clear()
                    for _m in ctx.messages:
                        # NOTE: ConversationMemory.add_message has no turn_id
                        # parameter (session 247) â€” passing one raised
                        # TypeError and made EVERY restore fail silently
                        # (best-effort except), so resumed threads came up
                        # with empty history. turn_id is store-side
                        # provenance only; the rolling window does not use it.
                        self._conversation_memory.add_message(
                            _m.role,
                            _m.content,
                        )
                logger.info(
                    f"[AgentKernel] Restored context for conv={self.conversation_id} "
                    f"(messages={len(ctx.messages)}, tokens_used={ctx.tokens_used})"
                )
        except Exception as exc:
            logger.warning(
                f"[AgentKernel] restore_context_from_store failed "
                f"for conv={self.conversation_id}: {exc}"
            )

    def _accrue_tokens(
        self,
        response_text: str,
        usage: Optional[Dict[str, Any]] = None,
        *,
        source: str = "",
    ) -> None:
        """Add this inference call's cost to the pill's real counter (D1 fix).

        The ContextPill reads ``self._tokens_used`` (see ``_emit_context_usage``),
        but nothing ever incremented it from a LIVE call â€” only
        ``restore_context_from_store`` ever set it (from a persisted snapshot),
        so a brand-new or freshly-restored turn stayed frozen at whatever it
        was restored to, through an entire real turn.

        *usage* is the REAL per-call usage dict parsed by the transport
        (``InferenceRouter.last_usage`` â€” prompt/completion/total tokens from
        the provider's own response). It always wins when present. Only when
        the provider/local model omits usage entirely do we fall back to the
        char/4 heuristic â€” and that fallback is logged as an estimate so real
        and estimated increments are never silently blended.
        """
        try:
            if usage and usage.get("total_tokens"):
                _add = int(usage["total_tokens"])
                _kind = "real"
            else:
                _add = max(1, len(response_text or "") // 4)
                _kind = "estimate"
            self._tokens_used = int(getattr(self, "_tokens_used", 0) or 0) + _add
            # Fullness (the pill): the largest single call of the latest turn. The first call of a new turn
            # replaces it; a real call counts prompt + answer, i.e. what that call put in the window.
            _turn = getattr(self, "_current_turn_id", None)
            if getattr(self, "_context_fill_turn", _FILL_NO_TURN) != _turn:
                self._context_fill_turn = _turn
                self._context_fill = _add
            else:
                self._context_fill = max(int(getattr(self, "_context_fill", 0) or 0), _add)
            logger.info(
                "[AgentKernel._accrue_tokens] +%d (%s, source=%s) tokens_used=%d",
                _add, _kind, source or "?", self._tokens_used,
            )
        except Exception as _e:  # pragma: no cover â€” accounting must never break a turn
            logger.debug("[AgentKernel._accrue_tokens] failed: %s", _e)

    def _sync_context_window(self) -> None:
        """Propagate the resolved context window to memory config + peers."""
        token_budget = self.get_effective_token_budget()
        try:
            from backend.memory.config import update_context_size

            update_context_size(token_budget)
        except Exception as _err:
            logger.warning(
                f"[AgentKernel] Failed to sync context window to memory: {_err}"
            )

    def resolve_context_window_with_source(
        self, role: str = "reasoning"
    ) -> "ResolvedWindow":
        """Resolve *role*'s effective context window, tagging the source that won.

        Precedence (REQ-2, design D-2):
          1. override      â€” user-set ``_context_window_overrides`` (highest)
          2. authoritative â€” the ACTUAL loaded local ``n_ctx`` (source of truth)
          3. table         â€” ``(provider, substring)`` registry lookup
          4. default       â€” conservative 8k, logged and tagged as a default

        The authoritative branch MUST run before the substring table: a loaded
        model's real ``n_ctx`` outranks a name-based guess. The old code ran the
        table first, so a 16k-loaded Mistral reported 32_768. Tagging the source
        is what makes an unknown window VISIBLE (REQ-2 AC4) rather than silent.

        *role* exists because Brain and Tool are independent bindings and may sit
        on models with very different windows. This method used to resolve the
        reasoning binding unconditionally, so a turn's whole budget was sized by
        the Brain even for the steps that execute on the Tool binding
        (``infer(role="EXECUTION")``). With Brain on a 256k model and Tool on an
        8k one, that budgets ~230k against a model that truncates at 8k â€” the
        silent-truncation failure this table's conservative default exists to
        prevent, reintroduced through the back door. Callers that care which
        model will actually receive the tokens must say so.
        """
        # REQ-1 AC1: the ACTIVE binding is authoritative. These properties
        # resolve it directly (2026-08-16) â€” they used to be stored fields that
        # could disagree with the binding, which is why this block once read the
        # router explicitly and treated them as a stale fallback.
        if role == "reasoning":
            provider = self._model_provider or ""
            model = self._selected_reasoning_model or ""
        else:
            model = self._model_for_role(role) or ""
            provider = ""
            _r = getattr(self, "_router", None)
            if _r is not None:
                try:
                    provider = self._provider_string_for_instance(_r.resolve(role))
                except Exception:
                    provider = ""

        # 1. User override (highest precedence)
        if model in self._context_window_overrides:
            return ResolvedWindow(self._context_window_overrides[model], "override")

        # 2. Authoritative: the live local model manager's ACTUAL loaded n_ctx.
        #    This is the source of truth for a locally-run model â€” it was
        #    launched with a specific n_ctx, and a substring guess would
        #    under/over-size the budget vs the real window.
        #
        #    Gated on the provider KIND, not on the string "local". The string
        #    map in _provider_string_for_instance sends OLLAMA -> "local",
        #    LOCAL_OPENAI -> "lmstudio" and INPROCESS -> "iris_local", so a test
        #    for "local" fired for Ollama (which has no LocalModelManager and
        #    always fell through) and NEVER for a real local model. A model
        #    loaded at 32768 then fell past the substring table to the 8192
        #    default â€” the same silent truncation the gpt-oss entry below was
        #    added to fix, reintroduced by REQ-4's id namespacing.
        if provider in ("local", "lmstudio", "iris_local"):
            try:
                from backend.agent.local_model_manager import get_local_model_manager

                mgr = get_local_model_manager()
                if getattr(mgr, "is_loaded", lambda: False)() and getattr(
                    mgr, "_current_params", None
                ):
                    _n_ctx = int(mgr._current_params.get("n_ctx", 0))
                    if _n_ctx and _n_ctx > 0:
                        return ResolvedWindow(_n_ctx, "authoritative")
            except Exception:
                pass

        # 2b. Authoritative for an API model: the window its provider publishes
        #     in its own /models list (provider_catalog.api_context_window; the
        #     gateway prefetches it off the answer path, this only reads the
        #     cache). 2026-10-02: mercury-2.5 (260000) and OpenRouter
        #     nemotron-3-super (262144) fell to the 8192 default, and the Brain
        #     answered "read_file returned no content" for a file the node read.
        _r = getattr(self, "_router", None)
        if _r is not None:
            try:
                from backend.agent.inference.provider_catalog import api_context_window

                _n_api = api_context_window(getattr(_r.resolve(role), "api_base_url", ""), model)
                if _n_api:
                    return ResolvedWindow(_n_api, "authoritative")
            except Exception:
                pass

        # 3. Table â€” (provider, substring) registry lookup, case-insensitive.
        model_lower = model.lower().strip()
        for reg_provider, reg_substring, tokens in self._KNOWN_CONTEXT_WINDOWS:
            if reg_provider == provider and (
                not reg_substring or reg_substring in model_lower
            ):
                return ResolvedWindow(tokens, "table")

        # 4. Local model manager profiles â€” config-derived guess. Treated as the
        #    table tier: better than the 8k default, but not the live loaded value.
        try:
            from backend.agent.local_model_manager import LocalModelManager

            mgr = LocalModelManager()
            for profile in mgr.profiles:
                # REQ-1 AC4: a vacuous guard on an empty profile.id
                # ("..." in model_lower is ALWAYS True) used to short-circuit
                # resolution to the first empty-id profile. Skip empty ids.
                if profile.id and (profile.id in model_lower or model_lower in profile.id):
                    return ResolvedWindow(profile.n_ctx, "table")
        except Exception:
            pass

        # 5. Safe default â€” 8k for unknown models. Tagged so it is VISIBLE, not silent.
        #    REQ-1 AC3: WARN-level, naming provider+model+source â€” loudly, not silently.
        logger.warning(
            "[AgentKernel] WARN source=default: no context window known for "
            f"provider={provider} model={model} â€” falling back to 8192"
        )
        return ResolvedWindow(8_192, "default")

    def resolve_context_window(self, role: str = "reasoning") -> int:
        """Return the effective context window (tokens) for *role*'s model.

        Thin wrapper over :meth:`resolve_context_window_with_source` that returns
        only the token count, preserving the ``int`` contract used by the 20+
        call sites (budget, work units, ContextPill denominator, Pacman filter).
        The source tag is available via ``resolve_context_window_with_source()``.

        Defaults to ``reasoning`` because that is the model the user thinks of as
        "the model" â€” it answers, and it is the right ContextPill denominator.
        Use ``resolve_turn_context_window()`` for anything sizing a budget that
        BOTH roles will spend against.
        """
        return self.resolve_context_window_with_source(role).tokens

    def resolve_turn_context_window(self) -> int:
        """Smallest context window among the roles that will serve this turn.

        A DER turn spends one budget across calls that go to the reasoning
        binding AND calls that go to the tool_execution binding. When those sit
        on different models the only safe ceiling is the SMALLER window: budget
        for the larger one and every call to the smaller silently truncates.

        This follows the rule stated throughout the window table â€” under-sizing
        is safe, over-sizing is the bug. A Brain/Tool split must not be able to
        reintroduce the overcommit by the back door (2026-08-16).
        """
        _reasoning = self.resolve_context_window("reasoning")
        try:
            _tool = self.resolve_context_window("tool_execution")
        except Exception:
            return _reasoning
        # An unbound/unknown tool role resolves to the conservative default;
        # that is a real ceiling for it, so honouring the minimum is still
        # correct. Guard only against a nonsense zero.
        if not _tool:
            return _reasoning
        if _tool != _reasoning:
            logger.info(
                "[AgentKernel] turn window = min(reasoning=%d, tool_execution=%d) "
                "= %d â€” Brain and Tool are on different models, so the budget is "
                "capped by the smaller window to avoid silent truncation",
                _reasoning, _tool, min(_reasoning, _tool),
            )
        return min(_reasoning, _tool)

    def get_effective_token_budget(self, fraction: float = 0.75) -> int:
        """Return the usable token budget as a fraction of the context window.

        We reserve 25% for the system prompt + tool definitions + response
        generation.  The fraction parameter lets callers override this.
        """
        return int(self.resolve_context_window() * fraction)

    def _emit_context_usage(self, step_number: int = 0, total_steps: int = 0) -> None:
        """Emit a `context:usage` event with the REAL per-thread token state.

        REQ-12 (Wave 9): makes the ContextPill live on EVERY model response,
        not just inside the DER loop. Single emitter so DER and non-DER paths
        share the SAME event contract (same shape, same `resolve_context_window()`
        denominator, same `self._context_fill` numerator) â€” they intertwine via
        the contract, not duplicated logic.

        - `max_tokens` = resolve_context_window() (the model in use) â€” never a
          hardcoded 128k.
        - `used_tokens` = self._context_fill: how FULL the window got in the thread's latest
          turn (its largest single call, prompt + answer, from real usage), restored per
          conversation_id like the spend. An ACTIVE or SWITCHED thread shows its own fill and
          NEVER 0; only a brand-new thread (no call yet) may report 0, which is honest.
        - `spent_tokens` = self._tokens_used, the thread's running spend (never reset).

        Fire-and-forget: EventBus failure must never crash the response path.
        """
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.CONTEXT_USAGE,
                data={
                    # How FULL the window is (owner 2026-10-26): the largest call of the thread's latest turn.
                    # It was the running spend (_tokens_used, never reset, ~20k per DER turn), so a long thread
                    # went red with nothing near the limit. The spend still travels as spent_tokens.
                    "used_tokens": int(getattr(self, "_context_fill", 0) or 0),
                    "spent_tokens": int(getattr(self, "_tokens_used", 0) or 0),
                    "max_tokens": int(self.resolve_context_window()),
                    "step_number": step_number,
                    "total_steps": total_steps,
                },
                turn_id=getattr(self, "_current_turn_id", None),
                conversation_id=self.conversation_id,
                session_id=self.session_id,
            )
        except Exception:
            pass  # EventBus is optional â€” no crash if it fails

    def set_launcher_mode(self, mode: str) -> None:
        """Set the launcher mode ('personal' or 'developer').

        In developer mode the agent's system prompt is augmented with
        PROJECT.md so the local model has full codebase context and can
        read/write source files, run git commands, and commit to
        ``iris-agent-dev``.
        """
        prev = self._launcher_mode
        self._launcher_mode = mode
        self._developer_context = None  # invalidate cached context
        logger.info(f"[AgentKernel] Launcher mode changed: {prev} â†’ {mode}")

    def _effective_launcher_mode(self) -> str:
        """The launcher mode from the persisted config, the single source of truth.

        ``set_launcher_mode`` is only ever called on the "default" kernel, and
        every conversation gets its own kernel that starts as "personal", so
        the copy on ``self`` never reached the kernel doing the work (execution
        audit B7, 2026-09-29). CapabilitySet reads data/iris_config.json per
        call, the same value the tool gates use. The stored copy is only the
        fallback when that module cannot be imported.
        """
        try:
            from backend.capabilities import CapabilitySet

            return CapabilitySet.get_mode()
        except Exception:
            return getattr(self, "_launcher_mode", "personal")

    def _build_system_prompt(self) -> str:
        """Return the full system prompt for the current launcher mode.

        Personal mode: personality system prompt only.
        Developer mode: personality prompt + PROJECT.md appended so the
        agent always knows the codebase layout and must commit to
        ``iris-agent-dev``.
        """
        base = (
            "You are IRIS, a helpful, warm, and personable AI voice assistant. "
            "Respond naturally and concisely."
        )
        if self._personality:
            try:
                base = self._personality.get_system_prompt()
            except Exception:
                pass

        if self._effective_launcher_mode() == "developer":
            _base_before_dev = base
            dev_ctx = self._get_developer_context()
            # Resolve active worktree path (set when /api/mode switches to developer)
            try:
                from backend.dev_worktree import get_active as _get_wt  # type: ignore

                _wt = _get_wt()
                worktree_path = _wt.get_path() if _wt else None
            except Exception:
                worktree_path = None

            worktree_block = (
                f"IRIS_SOURCE_DIR={worktree_path}\n"
                "You are working in an isolated copy of the IRIS source. "
                "Changes here do NOT affect the live codebase until the session "
                "ends and the user approves the diff in the Launcher.\n"
                if worktree_path
                # Owner 2026-10-01: no sandbox is created without asking. With
                # none, the agent may READ the IRIS source but must ask the user
                # (ask_user_question) before it creates a sandbox or edits IRIS.
                else "You may read the IRISVOICE source code. No isolated sandbox "
                "exists: before you edit any IRIS source file or create a sandbox, "
                "ask the user with ask_user_question and wait for the answer. "
                "Never commit to main or IRISVOICEv.3.\n"
            )

            # [13.3] Spec-mandated developer context block (keep both)
            spec_block = (
                f"You are working in an isolated copy of the IRIS source at {worktree_path}.\n"
                "Changes here do NOT affect the live codebase until approved.\n"
                "Commit your changes; they will be reviewed in the Launcher diff view.\n"
                if worktree_path
                else ""
            )

            if dev_ctx:
                base = (
                    base
                    + "\n\n"
                    + spec_block
                    + "\n"
                    + "--- DEVELOPER MODE ACTIVE ---\n"
                    + worktree_block
                    + "\n"
                    + dev_ctx
                )
            else:
                base = (
                    base
                    + "\n\n"
                    + spec_block
                    + "\n"
                    + "--- DEVELOPER MODE ACTIVE ---\n"
                    + worktree_block
                )

            # The blocks above describe the IRIS repo ("full access to the
            # IRISVOICE source", PROJECT.md, the iris-agent branch). When the
            # turn is bound to ANOTHER project folder they point the planner at
            # the wrong codebase, so they are replaced by that folder.
            _project = self._bound_external_project()
            if _project:
                base = (
                    _base_before_dev
                    + "\n\n--- DEVELOPER MODE ACTIVE ---\n"
                    + f"PROJECT FOLDER: {_project}\n"
                    + "You are working on this project, not on IRIS. Relative paths "
                    "resolve inside this folder and commands run in it.\n"
                )

            # Gate 3 T7 (REQ-9): discipline ladder + active task scope bound.
            # Injected at this single assembly point so DER workers inherit it
            # (AC4). 'off' injects nothing (AC5); failure degrades silently.
            try:
                from backend.dev.ladder import get_ladder_block

                _ladder = get_ladder_block()
                if _ladder:
                    base = base + "\n\n" + _ladder
            except Exception as _ladder_exc:
                logger.debug("[AgentKernel] ladder injection skipped: %s", _ladder_exc)

        # Execution audit B17 (2026-09-29): the EML "[COGNITIVE STATE]" and
        # "[CADUCEAN GOVERNOR]" lines were removed from the prompt. They are
        # internal control signals the model cannot act on, and the EML read
        # was a synchronous FFI call on every prompt build (20 s+ under load in
        # an eval turn). The physics still runs; it just is not narrated to the
        # model. No prompt gave the date, so the model guessed it.
        import datetime as _dt

        base += f"\n\nToday's date: {_dt.date.today().strftime('%A, %d %B %Y')}."

        # [RESPONSE FORMAT] â€” ONE TRIGGER (reply-surface audit, Phase A).
        # A card appears only when the model calls create_artifact. The five
        # earlier rules (a length rule, a `show` storage rule, a markdown
        # demotion, a keyword fallback mint, a web-format question) each guessed
        # at the same thing from a different angle and disagreed with each other
        # in live turns; the model now learns ONE rule and the code does exactly
        # that. Length is a FORMATTING question, answered by
        # _READABLE_FORMAT_RULES. The older `show` JSON still parses and
        # converts to the same call, so a prompt that still teaches it works.
        base += (
            "\n\n[RESPONSE FORMAT]\n"
            "ANSWER: plain text is the reply. It can be long, with headings, "
            "lists, tables and short code blocks. It is shown in full and is "
            "never turned into a card. NEVER shorten an answer because it is "
            "long.\n"
            "ARTIFACT: call the `create_artifact` tool when you made something to "
            "keep, reuse or open on its own: a report, a code file, a dataset, a "
            "diagram or an interactive page. Always give a title and a one-line "
            "summary. Pick the kind: document, code, data, diagram, page or "
            "image. For code give the language; for data give csv or json. To "
            "publish a new version of an artifact you already made, pass its "
            "`artifact_id`.\n"
            "BOTH: when you make an artifact, your reply says in 1-3 sentences "
            "what you made and what matters about it. Never repeat the artifact's "
            "content in the reply.\n"
            "SIGNS that mean an artifact: the user asked for a file, report, "
            "page, chart or document; the content stands alone and is longer than "
            "about 40 lines; the user will save, share or reopen it; or the "
            "content is visual. A snippet under about 15 lines stays in the "
            "answer."
        )

        return base

    def _count_tokens(self, messages: List[Dict]) -> int:
        return (
            sum(len(m.get("content") or "") for m in messages) // self._CHARS_PER_TOKEN
        )

    def _assemble_direct_context(
        self, text: str, context: List[Dict], session_id: Optional[str] = None
    ) -> List[Dict]:
        """
        Build the message list for _respond_direct using all three memory layers
        from the Context Engineering spec (CONTEXT_ENGINEERING.md Â§1â€“3):

          Layer 1 â€” Mycelium coordinate graph  â†’ already in system_prompt via
                                                  _build_system_prompt()
          Layer 2 â€” Episodic store             â†’ injected here as memory block
          Layer 3 â€” Working memory / history   â†’ token-aware full context, NOT
                                                  a hard-capped roll window

        The result is unlimited effective memory: the agent sees all context
        that fits in the budget. When history exceeds the budget, the oldest
        messages are trimmed â€” but episodic summaries from Mycelium still carry
        the gist of older sessions forward (Layer 2).

        Design rules (from spec):
          â€¢ Never drop the current user turn
          â€¢ First non-system message must be "user" (Qwen3 / most models)
          â€¢ Episodic block is a system-adjacent userâ†”assistant exchange so it
            doesn't break the alternating pattern
        """
        system_prompt = self._build_system_prompt()

        # â”€â”€ Layer 2: episodic injection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        episodic_prefix: List[Dict] = []
        try:
            if self._memory_interface is not None and hasattr(
                self._memory_interface, "episodic"
            ):
                ep_ctx = self._memory_interface.episodic.assemble_episodic_context(text)
                if ep_ctx and ep_ctx.strip():
                    # Inject as a pseudo-exchange so the message pattern stays
                    # [system, user, assistant, user, assistant, â€¦, user]
                    episodic_prefix = [
                        {
                            "role": "user",
                            "content": f"<memory>\n{ep_ctx.strip()}\n</memory>",
                        },
                        {
                            "role": "assistant",
                            "content": "Understood â€” I have that context.",
                        },
                    ]
        except Exception as _ep_exc:
            loud_error(_ep_exc, "episodic.assemble_episodic_context")

        # ── Layer 1b: the gated Mycelium profile (REQ-13 AC4) ──────────────
        episodic_prefix.extend(self._mycelium_profile_messages(text, session_id))

        # â”€â”€ Layer 3: Option B â€” DB-backed semantic context (Pacman retrieval) â”€â”€
        # Instead of a blind rolling-window crop, we retrieve the most relevant
        # conversation fragments stored by fragment_and_store().  Falls back to
        # the plain rolling window when no chunks exist yet (first turn, fresh DB).
        #
        # Recency anchor: always keep the last _RECENCY_TURNS raw turns so the
        # model can follow short-term conversational flow regardless of relevance.
        _RECENCY_TURNS = 8

        sys_tokens = len(system_prompt) // self._CHARS_PER_TOKEN
        ep_tokens = self._count_tokens(episodic_prefix)
        current_tokens = len(text) // self._CHARS_PER_TOKEN

        # â”€â”€ 3a: semantic chunk retrieval from DB â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        chunk_prefix: List[Dict] = []
        try:
            if (
                self._memory_interface is not None
                and hasattr(self._memory_interface, "episodic")
                and hasattr(self._memory_interface.episodic, "retrieve_context_chunks")
            ):
                _ctx_budget323 = int(self.resolve_context_window() * 0.6)
                _chunks = self._memory_interface.episodic.retrieve_context_chunks(
                    query=text,
                    # The TURN's session, not the kernel's fixed one: the seed
                    # and the ask can be different conversations. The kernel id
                    # is only a fallback when the caller passed none.
                    session_id=session_id or getattr(self, "session_id", None),
                    limit=6,
                    min_similarity=0.25,
                    zones=["trusted", "tool"],
                    # Token-aware: cap retrieved chunks to fit the model's real
                    # context window (reserve ~40% for prompt + response so the
                    # agent's own reasoning space isn't crowded out by memory).
                    max_context_tokens=_ctx_budget323,
                )
                # Session-323 (PACMAN membrane): reference-zone chunks carry
                # external web text â€” pulled separately and wrapped in an
                # explicit <reference_memory> tag so the reasoning prompt can
                # tell untrusted recall from trusted/tool recall. The DIRECT
                # read path (get_rendered_documents by conversation_id) stays
                # UNFILTERED â€” a read is a fetch, not a recall.
                _ref_chunks323: List[str] = []
                try:
                    _ref_chunks323 = self._memory_interface.episodic.retrieve_context_chunks(
                        query=text,
                        session_id=session_id or getattr(self, "session_id", None),
                        limit=3,
                        min_similarity=0.25,
                        zones=["reference"],
                        max_context_tokens=max(1, _ctx_budget323 // 3),
                    ) or []
                except Exception:
                    _ref_chunks323 = []
                _blocks323: List[str] = []
                # ── 3a-1: RECENT FACTS (always, bounded) ───────────────────
                # A similarity leg cannot match a broad "what do you know
                # about me" to "my card is card-0646" (no lexical overlap).
                # This READ leg keeps the newest explicit facts addressable
                # without a router heuristic. Bound: the 8 newest user turns
                # on the Immortus chain (pins live in recall_memory, not here).
                try:
                    _rf: List[str] = []
                    try:
                        _rf = _dedupe_fact_lines(
                            _recent_user_turn_texts(
                                self._memory_interface.episodic.db, str(text or "")
                            )
                        )
                    except Exception:
                        pass
                    # Newest-first, and one value per fact: the pins stay in
                    # recall_memory, not in the automatic block (a pin can be an
                    # older duplicate and compete with the newest user turn).
                    if _rf:
                        _blocks323.insert(
                            0,
                            "<recent_facts>\n- "
                            + "\n- ".join(dict.fromkeys(_rf))
                            + "\n</recent_facts>",
                        )
                except Exception as _rf_exc:  # noqa: BLE001 - never blocks a turn
                    logger.debug("[AgentKernel] recent facts skipped: %s", _rf_exc)
                # ── 3a-2: turn-start prior memory (IRIS_TURN_START_RECALL) ──
                # ON by default since 2026-10-28 (owner decision); set
                # IRIS_TURN_START_RECALL=0 to switch it off. Chain rows
                # relevant to the USER'S OWN WORDS, so a fact taught in an
                # earlier thread is in the context before the planner invents
                # steps (the per-step gate compares the STEP, and a question
                # that "looks like" a tool task never pulls its taught fact
                # in - eval m01). Same pool, same relevance gate, bounded.
                try:
                    from backend.agent.ontology_recall import (  # noqa: PLC0415
                        TURN_START_MAX_CHARS,
                        turn_start_prior_memory,
                    )
                    from backend.agent.ontology_recall import (  # noqa: PLC0415
                        resolve_mycelium_conn as _pm_resolve_conn,
                    )

                    _pm_conn = _pm_resolve_conn(self._memory_interface)
                    _pm_rows = turn_start_prior_memory(
                        _pm_conn, text,
                        session_id or getattr(self, "session_id", None),
                    )
                    _pm_lines: List[str] = []
                    _pm_used = 0
                    for _pm_r in _pm_rows:
                        _pm_line = (
                            _pm_r.get("insight")
                            or str(_pm_r.get("result") or "")[:240]
                            or str(_pm_r.get("content") or "")[:240]
                        ).strip()
                        if not _pm_line:
                            continue
                        if _pm_used + len(_pm_line) > TURN_START_MAX_CHARS:
                            break
                        _pm_lines.append(_pm_line)
                        _pm_used += len(_pm_line)
                    # A query-gated chain row can be the OLD value of a fact the
                    # recent-facts leg already has; keep only the newest.
                    _pm_lines = _dedupe_fact_lines(_pm_lines, against=_rf)
                    if _pm_lines:
                        _blocks323.append(
                            "<prior_memory>\n- "
                            + "\n- ".join(_pm_lines)
                            + "\n</prior_memory>"
                        )
                except Exception as _pm_exc:  # noqa: BLE001 - never blocks a turn
                    logger.debug("[AgentKernel] turn-start prior memory skipped: %s", _pm_exc)
                if _chunks:
                    _blocks323.append("\n---\n".join(_chunks))
                # REQ-12 AC5 (T43): a fact taught in ANOTHER conversation must
                # reach this one. Bounded to trusted user chunks; the session
                # recall above still leads and duplicates are dropped.
                try:
                    _x_rows323 = (
                        self._memory_interface.episodic.retrieve_context_chunks(
                            query=text,
                            session_id=None,
                            limit=3,
                            min_similarity=0.45,
                            chunk_types=["context_fragment"],
                            zones=["trusted"],
                            with_meta=True,
                        )
                        or []
                    )
                    # Newest statement of one fact only (BT-W10-2): the leg is
                    # score-ordered, and both values of a restated fact match.
                    _x_chunks323 = _dedupe_fact_rows([
                        (str(_r.get("content") or ""), str(_r.get("timestamp") or ""))
                        if isinstance(_r, dict) else (str(_r), "")
                        for _r in _x_rows323
                    ])
                except Exception as _x_exc:  # noqa: BLE001 - never blocks a turn
                    logger.debug("[AgentKernel] cross-session memory skipped: %s", _x_exc)
                    _x_chunks323 = []
                _seen323 = set(_chunks)
                _x_new323 = [c for c in _x_chunks323 if c not in _seen323]
                # The cross-session leg is score-ordered, not newest-ordered;
                # drop an older value of a fact the recent-facts leg has.
                _x_new323 = _dedupe_fact_lines(_x_new323, against=_rf)
                if _x_new323:
                    _blocks323.append(
                        "<cross_session_memory>\n"
                        + "\n---\n".join(_x_new323)
                        + "\n</cross_session_memory>"
                    )
                if _ref_chunks323:
                    _blocks323.append(
                        "<reference_memory>\n"
                        + "\n---\n".join(_ref_chunks323)
                        + "\n</reference_memory>"
                    )
                # ── 3a-3: file memory (REQ-9 AC4) ──────────────────────────
                # A file is an ADDRESS, not a conversation. The recall above is
                # keyed on session_id, so file chunks - which belong to no
                # session - are invisible to it. This leg is therefore
                # session-less and zone-addressed on purpose. It is probed once
                # per kernel: with no file chunks in the store it costs nothing.
                _file_present = getattr(self, "_file_memory_present", None)
                if _file_present is None:
                    try:
                        _file_present = bool(
                            self._memory_interface.episodic.db.execute(
                                "SELECT 1 FROM context_chunks"
                                " WHERE chunk_type = 'file' LIMIT 1"
                            ).fetchone()
                        )
                    except Exception:  # noqa: BLE001 - a probe never blocks a turn
                        _file_present = False
                    self._file_memory_present = _file_present
                if _file_present:
                    _file_chunks: List[str] = []
                    try:
                        _file_chunks = (
                            self._memory_interface.episodic.retrieve_context_chunks(
                                query=text,
                                session_id=None,
                                limit=3,
                                min_similarity=0.25,
                                zones=["trusted"],
                                chunk_types=["file"],
                                max_context_tokens=max(1, _ctx_budget323 // 4),
                            )
                            or []
                        )
                    except Exception as _f_exc:  # noqa: BLE001 - never blocks a turn
                        logger.debug("[AgentKernel] file memory skipped: %s", _f_exc)
                    if _file_chunks:
                        _blocks323.append(
                            "<file_memory>\n"
                            + "\n---\n".join(_file_chunks)
                            + "\n</file_memory>"
                        )
                # The exact-value rule applies whenever RECALLED memory is in
                # the prompt, not because a router labeled the turn. This
                # decouples the rule from the removed memory heuristics.
                try:
                    _mem_text = "\n".join(_blocks323)
                    if any(tag in _mem_text for tag in (
                        "<prior_memory>", "<cross_session_memory>", "<recent_facts>",
                    )):
                        system_prompt += (
                            "\n\nMEMORY ANSWER RULE: the prompt includes things the "
                            "user stated earlier. Reproduce a stored value EXACTLY "
                            "as stated, including any suffix, code, or identifier. "
                            "Do not shorten, translate, or normalize it. If stored "
                            "values disagree, use the newest user statement."
                        )
                        sys_tokens = len(system_prompt) // self._CHARS_PER_TOKEN
                except Exception as _mr_exc:  # noqa: BLE001 - never blocks a turn
                    logger.debug("[AgentKernel] memory answer rule skipped: %s", _mr_exc)
                # The exact user statements are authoritative. When they are in
                # the prompt, the derived "past successes" block can carry an
                # OLDER value of the same attribute (measured 2026-10-30:
                # BT-W10-2 answered alpha over the newer bravo). Drop the
                # derived <memory> block; the user turns + pins carry the newest.
                try:
                    _exact = "\n".join(_blocks323)
                    if any(tag in _exact for tag in (
                        "<recent_facts>", "<prior_memory>", "<cross_session_memory>",
                    )):
                        episodic_prefix[:] = [
                            m for m in episodic_prefix
                            if "<memory>" not in (m.get("content") or "")
                        ]
                except Exception as _ex_exc:  # noqa: BLE001 - never blocks a turn
                    logger.debug("[AgentKernel] derived-memory suppression skipped: %s", _ex_exc)
                if _blocks323:
                    chunk_text = "\n---\n".join(_blocks323)
                    # Inject as a pseudo-exchange so role alternation stays valid
                    chunk_prefix = [
                        {
                            "role": "user",
                            "content": f"<context_memory>\n{chunk_text}\n</context_memory>",
                        },
                        {
                            "role": "assistant",
                            "content": "Understood â€” I have those context fragments.",
                        },
                    ]
        except Exception as _ch_exc:
            loud_error(_ch_exc, "episodic.retrieve_context_chunks")

        chunk_tokens = self._count_tokens(chunk_prefix)
        budget_for_history = (
            self._DIRECT_CTX_BUDGET
            - sys_tokens
            - ep_tokens
            - chunk_tokens
            - current_tokens
        )

        # â”€â”€ 3b: recency anchor â€” last N raw turns â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        history = list(context)
        # Remove current user turn from tail if already appended
        if (
            history
            and history[-1].get("role") == "user"
            and history[-1].get("content") == text
        ):
            history = history[:-1]

        if chunk_prefix:
            # DB has relevant chunks: only keep a small recency window
            recent = (
                history[-_RECENCY_TURNS:]
                if len(history) > _RECENCY_TURNS
                else list(history)
            )
            recent_tokens = self._count_tokens(recent)
            while recent and recent_tokens > max(budget_for_history, 0):
                removed_item = recent.pop(0)
                recent_tokens -= (
                    len(removed_item.get("content") or "") // self._CHARS_PER_TOKEN
                )
            while recent and recent[0].get("role") != "user":
                recent.pop(0)
            history_block = recent
        else:
            # No chunks yet (first message / empty DB): full rolling window fallback
            history_tokens = self._count_tokens(history)
            while history and history_tokens > max(budget_for_history, 0):
                removed_item = history.pop(0)
                history_tokens -= (
                    len(removed_item.get("content") or "") // self._CHARS_PER_TOKEN
                )
            while history and history[0].get("role") != "user":
                history.pop(0)
            history_block = history

        # â”€â”€ Assemble final message list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # ── T48 observability: the RENDERED memory text this turn delivers ──
        # The gate answer depends on what the model actually sees, not on what
        # retrieval returned. Bounded to one line; never blocks a reply.
        try:
            _mem_blocks_text: List[str] = []
            for _m in (episodic_prefix + chunk_prefix):
                _c = _m.get("content") or ""
                if any(tag in _c for tag in (
                    "<memory>", "<context_memory>", "<cross_session_memory>",
                    "<prior_memory>", "<file_memory>", "<reference_memory>",
                    "<mycelium_profile>",
                )):
                    _mem_blocks_text.append(_c)
            logger.info(
                "[MEM-TEXT] session=%s path=direct query=%r mem=%s",
                session_id or getattr(self, "session_id", None),
                (text or "")[:80],
                ("\n".join(_mem_blocks_text)[:1200] or "(none)"),
            )
        except Exception:  # noqa: BLE001 - observability never blocks a reply
            pass

        messages: List[Dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(episodic_prefix)  # Layer 2: episodic summaries
        messages.extend(chunk_prefix)  # Layer 3a: semantic DB chunks
        messages.extend(history_block)  # Layer 3b: recency anchor

        # Ensure the list ends on the current user turn
        if (
            not messages
            or messages[-1].get("content") != text
            or messages[-1].get("role") != "user"
        ):
            messages.append({"role": "user", "content": text})

        # â”€â”€ Telemetry: log context assembly metrics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            _sys_chars = len(system_prompt) if system_prompt else 0
            _ep_chars = sum(len(m.get("content", "")) for m in episodic_prefix)
            _ck_chars = sum(len(m.get("content", "")) for m in chunk_prefix)
            _hist_chars = sum(len(m.get("content", "")) for m in history_block)
            _total_chars = _sys_chars + _ep_chars + _ck_chars + _hist_chars + len(text)
            _total_msgs = len(messages)
            from backend.core.logging_config import get_agent_logger

            get_agent_logger().info(
                "Context assembly",
                total_chars=_total_chars,
                total_messages=_total_msgs,
                sys_chars=_sys_chars,
                episodic_chars=_ep_chars,
                chunk_chars=_ck_chars,
                history_chars=_hist_chars,
                current_turn=len(text),
                episodic_count=len(episodic_prefix),
                chunk_count=len(chunk_prefix),
                history_turns=len(history_block),
            )
        except Exception:
            pass

        # â”€â”€ MCM Protocol: MITO tag injection + DCP prune â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if self._mcm_orch is not None:
            try:
                messages = self._mcm_orch.pre_call(messages, text)
            except Exception:
                pass  # MCM failure never blocks the response

        return messages

    @staticmethod
    def _sanitize_messages(messages: List[Dict]) -> List[Dict]:
        """
        Sanitize message list before sending to model API.

        Removes:
          - Messages whose content starts with '[IRIS error:' (garbage accumulation)
          - Non-system messages with empty/whitespace-only content
          - Consecutive same-role non-system messages (breaks API alternation rules)

        Ensures the list starts with system (or inserts an empty one) and ends
        with the current user turn.
        """
        # 1. Strip messages with error content
        cleaned = [
            m for m in messages if not m.get("content", "").startswith("[IRIS error:")
        ]

        # 2. Remove truly empty non-system messages
        cleaned = [
            m
            for m in cleaned
            if m.get("role") == "system" or (m.get("content") or "").strip()
        ]

        # 3. Collapse consecutive same-role non-system messages, and merge
        # non-first system messages into the first. mito_inject (pos 1) and
        # pacman_recall (pos 2) each add a system block beside the base
        # prompt, so the wire list routinely carries 2-3 systems â€” which
        # strict chat templates (Cerebras, llama.cpp) reject with 400
        # "System message must be at the beginning" (live 2026-09-04: killed
        # a direct answer plus topic + data extraction). Tolerant providers
        # never minded, and fewer systems are safe everywhere, so merge
        # instead of dropping: the content is load-bearing context.
        sanitized: List[Dict] = []
        _first_system_idx: int | None = None
        for m in cleaned:
            if m["role"] == "system":
                if _first_system_idx is None:
                    _first_system_idx = len(sanitized)
                    sanitized.append(m)
                else:
                    _extra = (m.get("content") or "").strip()
                    if _extra:
                        sanitized[_first_system_idx] = {
                            **sanitized[_first_system_idx],
                            "content": (
                                (sanitized[_first_system_idx].get("content") or "").rstrip()
                                + "\n\n" + _extra
                            ),
                        }
                continue
            elif not sanitized:
                # First non-system message is fine
                sanitized.append(m)
            elif sanitized[-1]["role"] == "system":
                # After system, any role is fine
                sanitized.append(m)
            elif sanitized[-1]["role"] != m["role"]:
                # Alternating roles â€” OK
                sanitized.append(m)
            # else: skip consecutive same-role non-system (keeps first of run)

        # 4. Ensure first message is system
        if sanitized and sanitized[0]["role"] != "system":
            sanitized.insert(0, {"role": "system", "content": ""})

        return sanitized

    def _mycelium_profile_messages(
        self, text: str, session_id: Optional[str]
    ) -> List[Dict[str, str]]:
        """The gated Mycelium profile as a user/assistant pair (REQ-13 AC4).

        ``_build_system_prompt()`` does NOT carry Layer 1. Read the package
        through the public API so the renderer's floor/trust/resonance gate
        applies and the task-class space subset is chosen; a mature graph only.
        Never raises: an empty list means "no profile this turn".
        """
        try:
            if self._memory_interface is None or not session_id:
                return []
            pkg, ok = self._memory_interface.get_task_context_package(text, session_id)
            prof = getattr(pkg, "mycelium_path", "") if ok else ""
            if not (prof and prof.strip()):
                return []
            return [
                {"role": "user",
                 "content": f"<mycelium_profile>\n{prof.strip()}\n</mycelium_profile>"},
                {"role": "assistant",
                 "content": "Understood — I have that profile."},
            ]
        except Exception as exc:  # noqa: BLE001 - never blocks a turn
            logger.debug("[AgentKernel] mycelium profile skipped: %s", exc)
            return []

    def _context_package_fields(self, context_package) -> Dict[str, str]:
        """The package fields the planning prompt reads (REQ-13 AC4).

        ``tier1_directives`` is hardcoded "" in MyceliumInterface, so Layer 1 is
        the package's ``mycelium_path`` (zone header + encoded path + gated
        partial profile). Reading the empty field dropped Layer 1 entirely.
        """
        fields = {"tier1": "", "preds": "", "strategy_hint": "",
                  "failure_warnings": "None"}
        if context_package is None:
            return fields
        fields["tier1"] = getattr(context_package, "mycelium_path", "") or ""
        try:
            fields["preds"] = context_package.get_tier2_predictions() or ""
        except Exception:
            pass
        try:
            hint = str(context_package.topology_primitive) or ""
            fields["strategy_hint"] = "" if hint == "unknown" else hint
        except Exception:
            pass
        try:
            fields["failure_warnings"] = context_package.get_tier3_failures() or "None"
        except Exception:
            fields["failure_warnings"] = "None"
        return fields

    def _der_bound_step_context(self, item: "QueueItem") -> None:
        """REQ-3 T8b AC4/AC5/AC6: bound the step's working context (forgetting).

        Extracted from _der_finalize_step's step-input section so the contract
        test drives the REAL code. Never raises â€” the caller's step must not
        fail on a forgetting error.

        AC4: content beyond the OQ-6 derived bound is dropped from the step's
        working context (coordinate_signal) â€” the node record is the re-read
        point.
        AC5: the per-step prompt token count is recorded (measured reduction);
        the bound is DERIVED from the REQ-1 resolved window, never a literal.
        AC6: when the node's chain write FAILED (durability drop counter > 0),
        the working context is the ONLY copy â€” never bounded/dropped.
        """
        try:
            _window = self.resolve_context_window() or 8192
            # OQ-6: 15% of the resolved window, derived â€” never a hardcoded
            # literal (a literal re-creates the 8192 collapse REQ-1 fixes).
            _step_budget = max(512, int(_window * 0.15))
            _sig = getattr(item, "coordinate_signal", "") or ""
            _step_tokens = max(1, len(_sig) // 4)  # charsâ†’tokens â‰ˆ 4:1
            # AC6: never forget content whose write failed. BUGFIX 2026-08-06:
            # the old guard `_der_chain_drops == 0 or not
            # step_id.startswith("immortus")` made AC6 vacuously true â€” the
            # `or` second clause was True for EVERY non-immortus step, so a
            # regular DER step whose chain write FAILED (drops>0) still had
            # its only copy dropped. Contract
            # test_der_t8b_forgetting_contract.py caught it. The ONLY safe
            # condition is: no drops.
            _write_ok = getattr(self, "_der_chain_drops", 0) == 0
            if _write_ok and len(_sig) > _step_budget:
                # AC4: drop the overflowing tail; the NODE RECORD (compressed)
                # is the re-read point.
                item.coordinate_signal = _sig[:_step_budget]
            if hasattr(self, "_der_step_prompt_tokens"):
                self._der_step_prompt_tokens += _step_tokens
        except Exception as _forget_exc:
            loud_error(_forget_exc, "step_forgetting_bound")
