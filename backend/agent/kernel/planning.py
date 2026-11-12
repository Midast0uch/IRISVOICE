# Moved from backend/agent/agent_kernel.py by scripts/kernel_split_check.py move.
# Bodies are byte-identical to the originals (guard: kernel_split_check.py manifest --check).
from __future__ import annotations

from typing import Any, Dict, Optional, List, Callable, Tuple, Sequence
import json
import asyncio
import time
from backend.agent.kernel.base import (
    logger,
)


def _plan_step_deps(raw_step: dict, earlier: list) -> list:
    """The edges of one planned step (parallel nodes, owner 2026-10-04):
    ["start"] (or "none") = needs no earlier result; empty or missing = the
    step before (a chain is the safe default); otherwise the named steps."""
    deps = [str(d) for d in (raw_step.get("depends_on") or []) if str(d).strip()]
    if any(d.strip().lower() in ("start", "none") for d in deps):
        return [d for d in deps if d.strip().lower() not in ("start", "none")]
    if deps:
        return deps
    return [earlier[-1].step_id] if earlier else []

# A spoken turn reaches the agent as text, so nothing told the planner or a step that IRIS heard it. Live
# 2026-10-25 22:15: "Okay. Can you hear me?" planned "Verify audio input", every step answered "I cannot
# process audio", the goal contract never covered and the Explorer added 7 steps - 99 s to the first word.
# Module level on purpose: stand-in kernels bind only some methods.
_VOICE_TURN_NOTE = (
    "CHANNEL: the user said this aloud. IRIS heard it through the microphone and speech recognition, "
    "and IRIS's reply is spoken aloud. You can hear the user."
)

def _voice_turn_note(owner) -> str:
    return _VOICE_TURN_NOTE if getattr(owner, "_turn_from_voice", False) else ""


class PlanningMixin:
    def _shadow_row_sink(self, row: Optional[dict]) -> None:
        """Persist ONE shadow-consumer row to the single-writer ledger.

        REQ-14 AC14.1 / REQ-29 (T18, T46-T49). The monitor consumers
        (`sufficient`, `done`) and the other module-sink consumers are
        SHADOW: they must write a calibration row and change no decision.
        (The surface consumers - `needs_action`, `depth_met`, `has_gaps`,
        `escalate_incomplete` - are all retired.)

        Why this method exists: the consumer modules emitted their rows to a
        sink that no production code installed, so a live session produced log
        lines and no rows. Wave 7 flips a consumer only on >= 100 measured
        rows, so the enforcement gate was unreachable without it.

        The parity pair (`chosen` vs `brain_bool`) rides the ledger's decision
        block â€” that is what lets a reader compute precision and ECE for a
        consumer that never dispatches a tool of its own.

        Never raises: an observer must never block a step (AC14.4 shape).
        """
        if not row or not isinstance(row, dict):
            return
        try:
            bridge = getattr(self, "_tool_bridge", None)
            if bridge is None or not hasattr(bridge, "record_decision"):
                return
            meta = dict(row)
            meta.setdefault("route", "shadow")
            if not meta.get("engine"):
                try:
                    from backend.agent.decision_engine import get_decision_engine

                    meta["engine"] = str(
                        getattr(get_decision_engine(), "model_id", "") or ""
                    )
                except Exception:  # noqa: BLE001 â€” attribution is best-effort
                    meta["engine"] = ""
            bridge.record_decision(
                meta, "shadow",
                session_id=str(getattr(self, "session_id", "") or "shadow"),
            )
        except Exception as exc:  # noqa: BLE001 â€” a row never blocks a step
            logger.debug("[AgentKernel] shadow row sink failed: %r", exc)

    def _get_active_goal_for(self, conversation_id: str):
        """Return the currently-active goal for this conversation, or None.

        Lazy lookup: a test double built via __new__ never runs __init__, so
        the slot may be unset. Treat that as "no in-flight goal" â€” callers
        decided at plan time what this conversation is doing.
        """
        return getattr(self, "_active_goals", {}).get(conversation_id)

    def _set_active_goal_for(self, conversation_id: str, goal) -> None:
        if not hasattr(self, "_active_goals"):
            self._active_goals = {}
        self._active_goals[conversation_id] = goal

    def apply_follow_up(self, conversation_id: str, text: str) -> bool:
        """Follow-up on the ACTIVE goal: merge new requirements into it.

        Per REQ-1 AC3 the user can revise an in-flight task mid-plan. Parser:
        parse the new instruction into (fields, target, guardrails, anchors) â€”
        anything else is semantic state. A mutation must land on the SAME
        GoalAnatomy instance (the `is` identity check is the contract)."""
        goal = self._get_active_goal_for(conversation_id)
        if goal is None:
            raise LookupError(f"no active goal for conversation {conversation_id}")
        anchor = getattr(goal, "memory_anchors", None)
        if not isinstance(anchor, dict):
            anchor = {}
            goal.memory_anchors = anchor
        anchor.setdefault("mutation_log", [])
        anchor["mutation_log"].append(text[:200])
        goal.memory_anchors = anchor
        prev_fields = [f for f in (getattr(goal, "fields", None) or []) if isinstance(f, str)]
        known = [t for t in (
            "price", "battery", "specs", "availability", "deadline", "query",
            "rating", "source", "warranty", "spec", "benchmark",
        ) if t in text.lower()]
        for t in known:
            if t not in prev_fields:
                prev_fields.append(t)
        # GoalAnatomy.mutate() returns self â€” in-place, never a branch.
        goal.mutate(fields=prev_fields)
        return True

    def _get_memory_context(self, task: str) -> str:
        """
        Get memory-augmented context for a task.

        Args:
            task: Task description

        Returns:
            Context string with memory augmentation
        """
        if self._memory_interface is None:
            return ""

        try:
            context = self._memory_interface.get_task_context(
                task=task, session_id=self.session_id
            )
        except Exception as e:
            logger.warning(f"[AgentKernel] Failed to get memory context: {e}")
            return ""

        # T8c (REQ-10 AC5): emit an episodic memory event so the card's memory
        # slot renders REAL episodic retrieval (never fabricated). Fire-and-
        # forget and OFF the inference hot path â€” a bus failure must never
        # affect the returned context.
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.MEMORY_EVENT,
                data={
                    "kind": "episodic",
                    "data": {
                        "task_summary": (task or "")[:120],
                        "outcome_type": "recall",
                        "duration_ms": 0,
                    },
                },
                session_id=self.session_id,
                # Session 245 (card-sync fix): without this the gateway stamps
                # "default" and the frontend files the event under a
                # conversation bucket the visible card is not in.
                conversation_id=self.conversation_id,
            )
        except Exception:
            pass

        return context

    def _store_task_episode(
        self,
        task_summary: str,
        full_content: str,
        outcome_type: str = "success",
        tool_sequence: Optional[List[Dict[str, Any]]] = None,
        session_id: Optional[str] = None,
        duration_ms: int = 0,
    ) -> None:
        """
        Store a task episode in memory.

        Args:
            task_summary: Brief task description
            full_content: Full conversation/task content
            outcome_type: Task outcome (success, failure, etc.)
            tool_sequence: List of tool calls made
            session_id: Session to attribute the episode to (falls back to self.session_id)
            duration_ms: Wall-clock time the task took in milliseconds
        """
        if self._memory_interface is None:
            return

        try:
            from backend.memory import Episode

            # The episode belongs to the CONVERSATION; the claim graph keeps the session the turn ran on. Live
            # 2026-10-26: every chat turn's episode was filed under the WS session ("session_iris", 185 rows) while
            # its chain rows and events were under "thread:...", so the chat's uses, a forget of the chat and the
            # memory surface could not see its episodes.
            _graph_sid = session_id or self.session_id
            episode = Episode(
                session_id=getattr(self, "conversation_id", None) or _graph_sid,
                graph_session_id=_graph_sid,
                turn_id=getattr(self, "_der_turn_id", None),
                task_summary=task_summary,
                full_content=full_content,
                tool_sequence=tool_sequence or [],
                outcome_type=outcome_type,
                duration_ms=duration_ms,
                source_channel="websocket",
                node_id="local",
                origin="local",
            )

            self._memory_interface.store_episode(episode)
            logger.debug(
                f"[AgentKernel] Stored episode for task: {task_summary[:50]}..."
            )

        except Exception as e:
            logger.warning(f"[AgentKernel] Failed to store episode: {e}")

    def _is_followup_to_task(self, text: str, context) -> bool:
        """
        Cheap rule check: does this message continue a prior task rather than
        start a fresh standalone question?  Used to keep multi-turn task flow
        in the DER loop even when the follow-up has no action verb of its own.

        Returns True when the message is short, anaphoric (references "it/that/
        them"), or a confirmation/continuation marker AND the recent context
        shows an active task.  Free (0 model calls).
        """
        t = (text or "").lower().strip()
        if not t or len(t.split()) > 25:
            return False
        # Anaphora: a pronoun with no noun is almost always a continuation.
        words = set(t.split())
        if words & set(self._ANAPHORA_PRONOUNS) and not any(
            v in t for v in self._ACTION_VERBS
        ):
            # "do it", "change that", "what about them" â€” continuation.
            if any(m in t for m in ("do", "change", "update", "edit", "what about",
                                    "how about", "send", "for", "with", "the")):
                return True
        # Explicit continuation/confirmation markers.
        if any(t.startswith(m) or f" {m} " in f" {t} " for m in self._FOLLOWUP_MARKERS):
            return True
        # Prior task context: if the last assistant turn was a plan/tool result,
        # a short user reply is overwhelmingly a follow-up, not a new question.
        if context:
            try:
                last = context[-1] if isinstance(context, (list, tuple)) else None
                if isinstance(last, dict) and last.get("role") == "assistant":
                    c = (last.get("content") or "")
                    if any(k in c.lower() for k in ("plan", "tool", "step", "task", "i'll", "i will")):
                        if len(t.split()) <= 12:
                            return True
            except Exception:
                pass
        return False

    def _classify_intent(self, text: str, context=None) -> str:
        """
        Semantic-logic-gate Tier 0 (REQ-1). Delegates to ``tier0_classify``.

        Preserves the legacy 4-class contract ("chat" | "action" | "followup" |
        "question") for any remaining callers. The authoritative structured
        decision is ``compile_dag().requires_der_kernel``, consumed by
        ``_needs_planning`` below; this method is the compatibility view.
        """
        from backend.agent.semantic_gate import Tier0Intent, tier0_classify

        _v = tier0_classify(text, context)
        return {
            Tier0Intent.CHAT: "chat",
            Tier0Intent.ACTION: "action",
            Tier0Intent.FOLLOWUP: "followup",
            Tier0Intent.QUESTION: "question",
            Tier0Intent.WEB: "action",  # legacy web intent maps to action
        }[_v.intent]

    @property
    def _gate(self):
        """Lazy SemanticLogicGate instance (T7, REQ-1/REQ-8). No model load at
        construction â€” the ontology (Tier 2) is wired via memory_interface."""
        from backend.agent.semantic_gate import SemanticLogicGate

        if getattr(self, "__gate", None) is None:
            self.__gate = SemanticLogicGate(
                tool_mode=getattr(self, "_tool_mode", "auto"),
                memory_interface=getattr(self, "_memory_interface", None),
            )
        return self.__gate

    def register_planning_hook(self, name: str, fn) -> None:
        """Planning-policy hook (REQ-8 AC3): skills/plugins/MCPs register a
        contributor/override that adjusts the draft DAGPlanGraph per task.
        Delegates to the gate's registered-policy store."""
        self._gate.register_policy(name, fn)

    def _web_mode_on(self) -> bool:
        try:
            from backend.agent.agent_gateways import get_global_internet_access

            return bool(get_global_internet_access())
        except Exception:
            return False

    def _needs_planning(self, text: str, context=None) -> bool:
        """
        Planner gate â€” the semantic logic gate (REQ-1, T7, T13).

        ``compile_dag().requires_der_kernel`` is the structured planning
        decision (REQ-8): Tier 0 (deterministic rules) -> Tier 2 (coordinate-
        graph ontology) -> the continuation lens compose the DAGPlanGraph; the
        ``_tool_mode`` policy
        (auto | ask_first | disabled) is applied INSIDE the gate; the web-mode
        gate (``_should_skip_der``) remains the final DER-skip authority
        (REQ-1 AC6).

        T13 gate-proof (tests/behavioral/test_behavioral_intent_routing.py,
        69 cases): equivalence with the legacy router on every non-compound
        prompt (zero regressions) + superiority on compound/multi-concern
        prompts (multi-lane DAGs). The legacy router is retired; this method
        is the permanent routing surface. ``_classify_intent`` remains as the
        legacy 4-class compatibility view (pinned by
        tests/behavioral/test_intent_routing_memory.py).
        """
        _g = self._gate
        _g.tool_mode = getattr(self, "_tool_mode", "auto")
        graph = _g.compile_dag(
            text, context, web_mode=self._web_mode_on(),
            developer=self._effective_launcher_mode() == "developer",
        )
        # REQ-5 AC1 (T8): stash the compiled graph for the [LAYERS] emit
        # (off the hot path â€” the TurnMetrics stamp copies a few attrs).
        self._last_gate_graph = graph
        return bool(graph.requires_der_kernel)

    def _stamp_gate_telemetry(self, metrics) -> None:
        """REQ-5 AC1 (T8): copy the last gate compilation onto the turn's
        TurnMetrics before [LAYERS] emit. Fire-and-forget; defaults when the
        gate never ran (direct calls in tests)."""
        graph = getattr(self, "_last_gate_graph", None)
        if graph is None:
            return
        lanes = ",".join(n.lane.value for n in graph.nodes) if graph.nodes else ""
        domain = graph.nodes[0].domain.value if graph.nodes else ""
        metrics.record_gate(
            domain=domain,
            lanes=lanes,
            latency_ms=graph.latency_ms,
            widen_scope=getattr(graph, "widen_scope", "") or "",
        )

    def _build_planning_prompt(
        self,
        task: str,
        tier1_directives: str = "",
        behavior_preds: str = "",
        failure_warnings: str = "None",
        skills_context: str = "",
        permissions_list: str = "",
        strategy_hint: str = "",
        task_class: str = "full",
        context: Optional[List[Dict[str, Any]]] = None,
        episodic_context: Optional[str] = None,
    ) -> str:
        """
        Build the structured planning prompt for _plan_task().
        Returns sections joined with double newlines.
        FAILURE WARNINGS appears exactly once.
        """
        sections = []

        if tier1_directives:
            sections.append(f"DIRECTIVES:\n{tier1_directives}")

        if behavior_preds:
            sections.append(f"BEHAVIOR PREDICTIONS:\n{behavior_preds}")

        sections.append(f"FAILURE WARNINGS:\n{failure_warnings or 'None'}")

        sections.append(f"TASK CLASS: {task_class}")

        if strategy_hint:
            sections.append(f"STRATEGY HINT:\n{strategy_hint}")

        if skills_context:
            sections.append(f"AVAILABLE SKILLS:\n{skills_context}")

        if permissions_list:
            sections.append(f"PERMISSIONS:\n{permissions_list}")

        sections.append(f"TASK:\n{task}")
        _voice = _voice_turn_note(self)
        if _voice:
            sections.append(_voice)

        # â”€â”€ Phase 2.1: full conversation history (no index slicing) â”€â”€
        # The active thread is passed in its entirety so the planner can resolve
        # references like "do the websearch" / "the pricing of those" back to the
        # original query from earlier turns (fixes the toggle-restoration context
        # loss). This is the whole point of the universal DER loop.
        if context:
            history_lines = []
            for msg in context:  # Entire thread history is included
                role = (msg.get("role") or "user").upper()
                content = msg.get("content") or ""
                line = f"{role}: {content}"
                # Provenance (2026-10-08): the URLs this message's references
                # came from. This COMPLETES the existing line - it is not a new
                # section - so a reference is grounded as EXTERNAL instead of
                # read as a local path (`adalso/openai-math` looks like one).
                # Cost is the URL text itself; nothing is looked up or re-fetched.
                _srcs = msg.get("sources") or []
                if _srcs:
                    line += "\n  [sources: " + ", ".join(
                        str(u) for u in _srcs[:8]
                    ) + "]"
                history_lines.append(line)
            if history_lines:
                sections.append(
                    "CONVERSATION HISTORY (full thread):\n"
                    + "\n".join(history_lines)
                )

        # â”€â”€ Phase 2.1: PACMAN semantic recall from past sessions â”€â”€
        if episodic_context:
            sections.append(
                f"RECALLED EPISODIC CONTEXT (PACMAN):\n{episodic_context}"
            )

        # REQ-8 AC8.2: visited-ledger block (pointers only).
        # Degrades to no-block on any failure â€” never break planning
        # (design.md Error Handling: ledger render failure degrades).
        try:
            _visited = self._der_visited_block()
        except Exception:
            _visited = ""
        if _visited:
            sections.append(_visited)

        return "\n\n".join(sections)

    @staticmethod
    def _iter_json_objects(raw: str):
        r"""Yield each BALANCED top-level {...} span in `raw`, in order.

        The planner used to extract its JSON with a single greedy
        ``re.search(r"\{[\s\S]+\}")``, which spans from the FIRST brace to the
        LAST one in the whole reply. That is correct only when the model emits
        exactly one object and nothing else. When it emits a preamble, a fenced
        block plus an example, or any prose containing a brace, the captured
        span is not valid JSON and the whole turn dies with "The planner
        returned no valid plan" -- measured live on 2026-08-26 as roughly half
        of all turns.

        This walks the string instead, tracking string literals and escapes so
        a brace inside a quoted value cannot close an object early.
        """
        depth = 0
        start = -1
        in_str = False
        esc = False
        for i, ch in enumerate(raw or ""):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
                continue
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}" and depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    yield raw[start : i + 1]
                    start = -1

    @staticmethod
    def _parse_planner_json(raw: str):
        """Best parseable planner object in `raw`, or None.

        Prefers a candidate that actually looks like a PLAN (carries `steps` or
        `plan_title`) over the first one that merely parses -- a model that
        prefixes its plan with a small example object would otherwise hand back
        the example.
        """
        import json as _json

        _best = None
        for _cand in AgentKernel._iter_json_objects(raw or ""):
            try:
                _obj = _json.loads(_cand)
            except Exception:
                continue
            if not isinstance(_obj, dict):
                continue
            if "steps" in _obj or "plan_title" in _obj:
                return _obj
            if _best is None:
                _best = _obj
        return _best

    @staticmethod
    def _planned_beats(data: dict, n_steps: int) -> list:
        """Clean the planner's `beats` + apply the duration gate (T12).

        Strips blanks; then the duration gate (REQ-10 AC10.10): narration
        earns airtime only when the task outlives the reply, so plans with
        fewer than 2 segments keep no beats (their reply voices everything).
        The 2-segment threshold is tunable via REQ-9 counters, not the model.
        """
        beats = [
            str(b).strip() for b in (data.get("beats", None) or [])
            if str(b or "").strip()
        ]
        if beats and n_steps < 2:
            logger.info(
                "[AgentKernel._plan_task] dropping %d beats "
                "(single-segment plan, duration gate)", len(beats)
            )
            return []
        return beats

    @staticmethod
    def _classify_provider_error(err_text: str) -> Optional[Tuple[object, str]]:
        """Map a fatal provider failure to (ErrorCode, user message).

        Billing (402) and auth (401) failures cannot heal inside the retry
        loop â€” returning them immediately saves ~10 s of doomed retries and,
        more importantly, tells the user the TRUE cause instead of the
        generic "planner returned no valid plan" (observed live 2026-09-05:
        Cerebras 402 surfaced as a planner failure on every prompt). Quota
        errors (429) are NOT fatal â€” windows roll, retries stay. Returns None
        when the error is not a recognized fatal provider failure. Codes come
        from exceptions.ErrorCode (6000-range); the code name rides in the
        user string so every failure is greppable end to end.
        """
        from backend.agent.exceptions import ErrorCode

        t = (err_text or "").lower()
        if ("402" in t and ("pay" in t or "bill" in t)) or "payment required" in t:
            return (
                ErrorCode.PROVIDER_BILLING,
                "[IRIS error] The AI provider refused the request "
                "(402 Payment Required) â€” the planner never ran, so no "
                "prompt reached a model. Switch provider in Models "
                "(local / ClinePass) or check billing, then retry. "
                "(code E_PROVIDER_BILLING)",
            )
        if (
            ("401" in t and ("unauth" in t or "invalid" in t or "key" in t or "auth" in t))
            or "unauthorized" in t
            or "invalid_api_key" in t
            or "invalid api key" in t
        ):
            return (
                ErrorCode.PROVIDER_AUTH,
                "[IRIS error] The AI provider rejected the API key (401). "
                "Check the key in settings (OS keyring), then retry. "
                "(code E_PROVIDER_AUTH)",
            )
        return None

    def _classify_plan_failure(self) -> Tuple[object, str, bool]:
        """Map the recorded plan failure to (ErrorCode, user message, fatal).

        Reads self._last_plan_failure as written by _plan_task. Fatal kinds
        (billing/auth) must fail fast â€” retries cannot heal them. Everything
        else retries and reports specifically at exhaustion, so logs and UI
        always name the true cause instead of a vague planner error.
        """
        from backend.agent.exceptions import ErrorCode

        failure = getattr(self, "_last_plan_failure", None) or {}
        kind = failure.get("kind")
        detail = (failure.get("detail") or "")
        if kind == "router":
            fatal = self._classify_provider_error(detail)
            if fatal is not None:
                return (fatal[0], fatal[1], True)
            low = detail.lower()
            if (
                "429" in low
                or "rate limit" in low
                or "rate_limit" in low
                or "quota" in low
                or "too many requests" in low
                or "overloaded" in low
            ):
                return (
                    ErrorCode.PROVIDER_QUOTA,
                    "[IRIS error] The AI provider is rate-limiting us (429) "
                    "after 3 tries â€” wait a minute for the quota window, or "
                    "switch provider. (code E_PROVIDER_QUOTA)",
                    False,
                )
            if (
                "timeout" in low
                or "timed out" in low
                or "connecterror" in low
                or "connection refused" in low
                or "connection reset" in low
                or "unreachable" in low
                or "dns" in low
            ):
                return (
                    ErrorCode.PROVIDER_TIMEOUT,
                    "[IRIS error] The AI provider request timed out or never "
                    "connected after 3 tries â€” check network/VPN/firewall, or "
                    "switch provider. (code E_PROVIDER_TIMEOUT)",
                    False,
                )
            return (
                ErrorCode.PROVIDER_ERROR,
                "[IRIS error] The provider request failed 3 times (see "
                "backend log for the status). Retry, or switch provider if "
                "it persists. (code E_PROVIDER_ERROR)",
                False,
            )
        if kind == "parse":
            return (
                ErrorCode.PLANNER_PARSE,
                "[IRIS error] The model answered 3 times but never in usable "
                "plan form. Switching models usually fixes this. "
                "(code E_PLANNER_PARSE)",
                False,
            )
        return (
            ErrorCode.PLANNER_EMPTY,
            "[IRIS error] The model returned no plan text 3 times. Retry, "
            "or switch models if it persists. (code E_PLANNER_EMPTY)",
            False,
        )

    def _plan_task(
        self,
        text: str,
        context: Optional[List[Dict[str, Any]]] = None,
        is_mature: bool = False,
        task_class: str = "full",
        context_package=None,
        mode: str = "full",
        session_id: str = "unknown",
        recall_query: Optional[str] = None,
    ) -> Optional[ExecutionPlan]:
        """
        DER-aware planning wrapper. Returns ExecutionPlan (or None on failure).
        ``recall_query``: what episodic recall searches with, when ``text`` is
        not the user's request (a re-plan directive) - default ``text``.
        Mode + maturity-aware temperature:
          debug/review  â†’ 0.0  (deterministic â€” finding bugs, not exploring)
          implement      â†’ 0.1  (low â€” structured code generation)
          research       â†’ 0.3  (higher â€” exploratory synthesis)
          default        â†’ 0.1 if mature else 0.25
        Falls back to a single-step plan on any model or parse failure.
        """
        from backend.core_models import ExecutionPlan, PlanStep
        import uuid as _uuid
        import re as _re

        _MODE_TEMPERATURES = {
            "debug": 0.0,
            "review": 0.0,
            "test": 0.0,
            "implement": 0.1,
            "quick_edit": 0.1,
            "research": 0.3,
            "spec": 0.2,
        }
        temperature = _MODE_TEMPERATURES.get(mode, 0.1 if is_mature else 0.25)

        # â”€â”€ Phase 5: Caducean-governed planning temperature â”€â”€
        # Modulate the base (mode-derived) temperature by the live Caducean
        # recommendation: COMPRESS (rec==1) -> more deterministic (lower temp);
        # EXPAND (rec==0) -> more exploratory (higher temp, capped); MAINTAIN
        # (rec==2) / unknown / TOPO_VIOLATION -> base.  Never raises.
        temperature = self._caducean_modulate_temperature(temperature, session_id)

        # Extract context package fields for the planning prompt
        tier1 = ""
        preds = ""
        strategy_hint = ""
        failure_warnings = "None"
        if context_package is not None:
            _pkg_fields = self._context_package_fields(context_package)
            tier1 = _pkg_fields["tier1"]
            preds = _pkg_fields["preds"]
            strategy_hint = _pkg_fields["strategy_hint"]
            failure_warnings = _pkg_fields["failure_warnings"]

        # Build the CAPABILITIES block.
        #
        # SIZED DOWN 2026-08-26 (session 260), measured: the previous block
        # listed every tool with its full description -- ~1,131 tokens on EVERY
        # planner call -- and instructed the planner to "set its `tool` to the
        # EXACT name below". The parser has not honoured that instruction since
        # Phase 1 (D1.3): it sets `tool=None` unconditionally, because tool
        # selection is a runtime, memory-conditioned policy owned by
        # explorer.propose. So the catalogue bought a field that was thrown
        # away, and the tool was then re-decided per step at ~4.6k tokens.
        #
        # WHAT THE BLOCK IS STILL FOR, and why it is not simply deleted: the
        # planner has to know the agent CAN do these things, or it plans
        # capable requests as trivial speak-only steps (2026-08-12: explicit
        # "use screenshot_page" requests planned as trivial). Names alone carry
        # that; the descriptions never did any work here. ~187 tokens.
        _tools_block = ""
        try:
            # Ensure the tool bridge exists BEFORE reading the tool list â€” a
            # fresh kernel has a None bridge (lazy-init only ran on the OpenAI
            # tools path), which silently yields an empty AVAILABLE TOOLS block
            # and the planner then emits tool-less speak steps (2026-08-12:
            # explicit "use screenshot_page" requests planned as trivial).
            self._ensure_tool_bridge()
            if self._tool_bridge is not None:
                _avail = self._tool_bridge.get_available_tools()
                if _avail:
                    _names = [
                        str(_t.get("name", "")) for _t in _avail
                        if _t.get("name")
                    ]
                    _tools_block = (
                        "CAPABILITIES the agent can call at execution time. "
                        "Do NOT name a tool in a step -- the runtime resolver "
                        "picks it. This list tells you what is POSSIBLE, so "
                        "plan real steps for it instead of answering directly:"
                        + chr(10) + "  " + ", ".join(_names)
                    )
        except Exception as _tb_exc:
            logger.debug("[AgentKernel._plan_task] tools block build failed: %s", _tb_exc)

        # â”€â”€ Phase 2.1: PACMAN semantic recall (best-effort, never blocks) â”€â”€
        episodic_context = ""
        try:
            if self._memory_interface is not None and hasattr(
                self._memory_interface, "episodic"
            ):
                episodic_context = (
                    self._memory_interface.episodic.assemble_episodic_context(
                        recall_query or text
                    )
                    or ""
                )
        except Exception as _ep_exc:
            logger.debug("[AgentKernel._plan_task] episodic recall failed: %s", _ep_exc)

        # Turn-start prior memory (IRIS_TURN_START_RECALL, OFF by default; A/B
        # measured 2026-10-28). Chain rows relevant to the USER'S OWN WORDS, so
        # a fact taught in an earlier thread is in the PLANNER's context
        # before any step exists. The per-step gate compares the STEP the
        # planner invents; a question that "looks like" a tool task never
        # pulls its taught fact in that way (eval m01: the question became
        # file-search steps and the fact never entered the context). FIRST
        # plan only - a re-plan's recall_query is a directive, not the
        # user's question. Same pool, same relevance gate, bounded.
        if recall_query is None:
            try:
                from backend.agent.ontology_recall import (  # noqa: PLC0415
                    TURN_START_MAX_CHARS,
                    resolve_mycelium_conn as _pm_resolve_conn,
                    turn_start_prior_memory,
                )

                _pm_conn = _pm_resolve_conn(self._memory_interface)
                _pm_rows = turn_start_prior_memory(_pm_conn, text, session_id)
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
                if _pm_lines:
                    _pm_block = (
                        "PRIOR MEMORY (facts IRIS recalls from earlier threads, "
                        "relevant to this request):\n- " + "\n- ".join(_pm_lines)
                    )
                    episodic_context = (
                        f"{episodic_context}\n\n{_pm_block}"
                        if episodic_context
                        else _pm_block
                    )
            except Exception as _pm_exc:  # noqa: BLE001 - never blocks planning
                logger.debug(
                    "[AgentKernel._plan_task] turn-start prior memory skipped: %s", _pm_exc
                )

            # REQ-12 AC5 (T43): the chain leg only sees chain rows. A fact stored
            # as a trusted user chunk in ANOTHER conversation is reached here,
            # bounded to 3 chunks in the trusted zone.
            try:
                _xs_chunks = (
                    self._memory_interface.episodic.retrieve_context_chunks(
                        query=text, session_id=None, limit=3,
                        min_similarity=0.45,
                        chunk_types=["context_fragment"], zones=["trusted"],
                    ) or []
                )
            except Exception as _xs_exc:  # noqa: BLE001 - never blocks planning
                logger.debug(
                    "[AgentKernel._plan_task] cross-session chunk recall skipped: %s",
                    _xs_exc,
                )
                _xs_chunks = []
            if _xs_chunks:
                _xs_block = (
                    "PRIOR USER FACTS (from other conversations):\n- "
                    + "\n- ".join(_xs_chunks)
                )
                episodic_context = (
                    f"{episodic_context}\n\n{_xs_block}"
                    if episodic_context else _xs_block
                )

        planning_prompt = self._build_planning_prompt(
            task=text,
            tier1_directives=tier1,
            behavior_preds=preds,
            failure_warnings=failure_warnings,
            task_class=task_class,
            strategy_hint=strategy_hint,
            context=context,
            episodic_context=episodic_context,
        )

        system_prompt = ""
        if self._personality:
            try:
                system_prompt = self._personality.get_system_prompt()
            except Exception:
                pass

        full_prompt = (
            f"{system_prompt}\n\n{planning_prompt}\n\n"
            + (f"{_tools_block}\n\n" if _tools_block else "")
            + "Respond with JSON only â€” no prose, no markdown fences:\n"
            '{"strategy":"do_it_myself|spawn_children|delegate_external",'
            '"plan_title":"short 2-3 word summary of what the plan does (e.g. \\"Search web for AI news\\")",'
            '"reasoning":"one sentence explaining the approach",'
            '"beats":["one-line direction statement","one-line time expectation"],'
            '"steps":[{"step_id":"s1","step_number":1,"description":"Search the web for the user request","expected_output":"the concrete result this step must produce","depends_on":["start"],"critical":true,"criticality":"load-bearing|supporting|cosmetic"}]}'
            "\n\n"
        "RULES:\n"
        # T12 (REQ-10 AC10.1/AC10.2/AC10.10/AC10.12): planned-beat authoring.
        # Beats are short spoken lines (direction + time/scale expectations)
        # for MULTI-SEGMENT tasks only â€” emit [] for single-step/trivial work.
        # Kept to six lines by the session-260 sizing discipline: the parser
        # reads exactly these keys, nothing decorative.
        '- "beats": 1-3 one-line narration lines (why this direction, how long '
        'it takes). NEVER narrate mechanics (subtask splitting, tool names, '
        'file-by-file). Omit entirely ([]) for single-step tasks.\n'
        "- Vary phrasing, never the same opening twice. Good: "
        '"Checking current sources â€” usually about half a minute." / '
        '"Comparing the two options, then reporting back." Bad: '
        '"I will now split this into subtasks."\n'
        "- Findings near completion belong in the reply, not beats. Name "
        "artifacts naturally (never identifiers/paths). Failure lines state "
        "the cause at direction level plus the next step.\n"
        # SIZED DOWN 2026-08-26 (session 260): the schema used to demand
        # "tool" and "params" on every step, with three RULES lines telling
        # the model how to fill them. The parser has discarded BOTH since
        # Phase 1 (D1.3) -- it hard-sets tool=None, params={} -- because
        # explorer.propose owns tool selection at execution time. So the
        # model spent OUTPUT tokens on fields that were thrown away, and
        # every extra required field was another chance to emit malformed
        # JSON. A step is a GOAL; the fields kept are the ones the parser
        # actually reads: step_id, step_number, description, expected_output,
        # depends_on, critical.
        '- Describe each step as a GOAL in "description". Do NOT name a tool; '
        'the runtime resolver picks it when the step executes.' + chr(10) +
        # expected_output (2026-10-19): every step's product was empty, so the
        # verifier had nothing to check a node step against (a node step was
        # VERIFIED whenever its calls ran, even when its own tests failed) and
        # the needs_action Oracle saw a goal with no artifact. One short clause
        # per step; the parser caps it at 200 chars.
        "- In 'expected_output', state the concrete product of the step: the "
        "exact answer, file change or number it must produce. One clause, not "
        "a restatement of the goal.\n" +
        # Parallel nodes (owner 2026-10-04): independent steps run side by
        # side, so the planner names the RESULTS a step needs. Empty = the
        # step before (the safe default); ["start"] = needs no earlier result.
        "- In 'depends_on', list the step_ids whose RESULT this step needs. A step "
        "will not start until those steps have completed. Steps that do not need "
        "each other's results run at the same time, so do not chain them. Write "
        "[\"start\"] for a step that needs no earlier result. An empty list means "
        "\"the step before\". Example - compare A and B: s1 read A [\"start\"], "
        "s2 read B [\"start\"], s3 compare them [\"s1\",\"s2\"].\n"
        # T5 (specs/tool-result-envelope, KD-9): planner declares per-step
        # criticality. One word per step â€” intent only, consumption confirms
        # it at finalize (option C). Defaults to "supporting" when omitted.
        "- In 'criticality', state how load-bearing the step is: "
        '"load-bearing" (the task fails without it), "supporting" (helps but '
        'alternatives exist), or "cosmetic" (nice to have). Omit for '
        '"supporting".\n'
        # PLAN SHAPE (2026-11-06): measured on c02_add_slugify, s1 was an
        # "inspect the existing module and project structure" step that ran
        # broad `find`/`ls -R` sweeps and the FULL test suite (17.9 s), then
        # s3 verified anyway - 56-71 s of duplicate work on a one-function
        # task. A step is a GOAL; the runtime resolves one tool for it, so
        # name the artifact, never a survey.
        "- Keep each step MINIMAL. A first step that reads ONE named file is "
        "enough. Do NOT plan a step that inspects the project structure, "
        "sweeps directories, checks git, or runs the test suite to 'see what "
        "exists'.\n"
        # PLAN SHAPE (2026-11-09): measured on c14_run_and_report ("run the
        # tests, tell me how many fail"), every plan added 1-2 steps after the
        # run that only tallied, verified or reported it ("Determine the exact
        # number of failing tests from the completed run", "Report the
        # verified failure count") - each a full tool loop that ran pytest
        # again. Over the logs: 72 'verify' and 29 'report' later steps. The
        # final reply already reports from the earlier step's result. A check
        # still follows a CHANGE (the goal contract needs that run).
        "- Do NOT plan a step that only tallies, restates or reports what an "
        "earlier step already produced; the final reply does that from the "
        "earlier result. Plan a separate check step only after a step that "
        "CHANGES a file. When the answer is the exact output of code (what a "
        "function returns, what a script prints), plan a step that RUNS it "
        "and reads the output; do not work the value out by reading.\n"
    )

        plan_raw: Optional[str] = None
        try:
            # Primary path: route planning through the unified InferenceRouter so
            # API providers (Cerebras, OpenAI, â€¦) are used â€” not just local/Ollama
            # models. Legacy LM Studio / Ollama branches below remain as fallbacks
            # for local-model configurations.
            try:
                _rt_text, _rt_think, _rt_tools = self._router.generate(
                    "reasoning",
                    [{"role": "user", "content": full_prompt}],
                    max_tokens=4096,
                    temperature=temperature,
                    # A plan is 1-3 goal steps: the default hidden reasoning
                    # (~1,300-1,650 tokens on mercury-2.5, ~4 s) bought nothing
                    # a "low" budget (~250 tokens, 2.5-3.2 s) did not; measured
                    # 2026-10-05, 6/6 valid plans. Providers without the
                    # parameter are sent the call unchanged.
                    reasoning_effort="low",
                )
                self._accrue_tokens(
                    _rt_text, getattr(self._router, "last_usage", None),
                    source="_plan_task",
                )
                if _rt_text:
                    plan_raw = _rt_text
                    logger.info(
                        "[AgentKernel._plan_task] planned via InferenceRouter"
                    )
            except Exception as _rt_err:
                logger.warning(
                    f"[AgentKernel._plan_task] router planning failed: {_rt_err}"
                )
                try:
                    self._last_plan_failure = {
                        "kind": "router",
                        "detail": str(_rt_err),
                    }
                except Exception:
                    pass
            if not plan_raw:
                if self._is_openai_compat():
                    _lms = self._get_lmstudio_client()
                    _r = _lms.chat.completions.create(
                        model=self._selected_reasoning_model or "local-model",
                        messages=[{"role": "user", "content": full_prompt}],
                        max_tokens=-1,
                        temperature=temperature,
                        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                    )
                    plan_raw = _r.choices[0].message.content
                    logger.info(
                        "[AgentKernel._plan_task] planner raw response: %s",
                        (plan_raw or "")[:600],
                    )
                elif (
                    self._selected_reasoning_model and ":" in self._selected_reasoning_model
                ):
                    import requests as _req

                    _r2 = _req.post(
                        "http://localhost:11434/api/chat",
                        json={
                            "model": self._selected_reasoning_model,
                            "messages": [{"role": "user", "content": full_prompt}],
                            "stream": False,
                        },
                        timeout=60,
                    )
                    if _r2.status_code == 200:
                        plan_raw = _r2.json().get("message", {}).get("content", "")
        except Exception as _pe:
            logger.warning(f"[AgentKernel._plan_task] inference failed: {_pe}")

        # Parse JSON â†’ ExecutionPlan
        try:
            if plan_raw:
                data = self._parse_planner_json(plan_raw)
                if data is not None:
                    logger.info(
                        "[AgentKernel._plan_task] parsed plan keys=%s "
                        "raw_steps=%s",
                        list(data.keys()),
                        len(data.get("steps", [])),
                    )
                    steps: List[Any] = []
                    for raw_step in data.get("steps", []):
                        steps.append(
                            PlanStep(
                                step_id=str(
                                    raw_step.get("step_id", str(_uuid.uuid4()))
                                ),
                                step_number=int(
                                    raw_step.get("step_number", len(steps) + 1)
                                ),
                                description=str(raw_step.get("description", "")),
                                # Phase 1 (D1.3): planner emits GOALS only. Tool
                                # selection is a runtime, memory-conditioned policy
                                # via explorer.propose â€” never pre-assigned here.
                                tool=None,
                                params={},
                                # 2026-10-19: the planner now declares the step's
                                # product. It was always empty, so verification had
                                # nothing to check and the needs_action Oracle saw
                                # a goal with no artifact. Optional: an older or
                                # non-compliant plan still parses.
                                expected_output=(
                                    str(raw_step.get("expected_output") or "").strip()[:200]
                                    or None
                                ),
                                critical=bool(raw_step.get("critical", True)),
                                depends_on=_plan_step_deps(raw_step, steps),
                                # T5 (KD-9): planner-declared criticality,
                                # validated to the locked vocabulary.
                                criticality=(
                                    str(raw_step.get("criticality", "supporting")).lower()
                                    if str(raw_step.get("criticality", "supporting")).lower()
                                    in ("load-bearing", "supporting", "cosmetic")
                                    else "supporting"
                                ),
                            )
                        )
                    # Parallel nodes (HANDOFF 11 C): the edges the planner
                    # DECLARED. Only the step count was logged, so whether plans
                    # carry real dependencies was unmeasurable.
                    logger.info(
                        "[AgentKernel._plan_task] plan edges steps=%d declared=%s",
                        len(steps), [(s.step_id, s.depends_on) for s in steps],
                    )
                    _beats = self._planned_beats(data, len(steps))
                    return ExecutionPlan(
                        plan_id=str(_uuid.uuid4()),
                        original_task=text,
                        strategy=data.get("strategy", "do_it_myself"),
                        reasoning=data.get("reasoning", ""),
                        plan_title=data.get("plan_title", ""),
                        steps=steps,
                        beats=_beats,
                    )
        except Exception as _parse_err:
            logger.warning(f"[AgentKernel._plan_task] parse failed: {_parse_err}")
            try:
                _raw_text = (plan_raw or "")
                self._last_plan_failure = {
                    "kind": "empty" if not _raw_text.strip() else "parse",
                    "detail": _raw_text[:200],
                }
            except Exception:
                pass
            # Only the LM Studio branch logged `plan_raw`, so on every other
            # provider a parse failure was unobservable -- the reason this bug
            # survived. Log what the model actually said, bounded.
            logger.warning(
                "[AgentKernel._plan_task] planner raw (first 600): %s",
                (plan_raw or "")[:600],
            )

        # Fallback: return None to signal plan error (REQ-2 â€” no silent self-do)
        try:
            if getattr(self, "_last_plan_failure", None) is None:
                # No router error and no parse attempt recorded (e.g. no
                # fallback configured and the router returned empty text):
                # the model simply produced nothing.
                self._last_plan_failure = {"kind": "empty", "detail": ""}
        except Exception:
            pass
        logger.warning(
            "[_plan_task] planner returned no valid plan for: %.150s",
            text,
        )
        return None

    def _admit_planned_beats(self, plan, *, turn_id=None, session_id=None) -> None:
        """Admit beats 2..N as pending narration + pre-synthesize them (T14).

        Hybrid pre-synthesis (REQ-10 AC10.6/AC10.7): each beat is admitted to
        the lane scheduler (pending, subsumable) and, while the lane is idle,
        synthesized immediately with the buffer held by the TTS manager.
        Playback consumes via take_held(); every other exit frees. Any skip
        or failure degrades to on-admission synthesis â€” a beat never dies
        for pre-synthesis. Never raises.
        """
        try:
            beats = list(getattr(plan, "beats", None) or [])[1:]
            if not beats:
                return
            from backend.agent.conversation_kernel import get_conversation_kernel
            from backend.agent.tts import get_tts_manager

            kernel = get_conversation_kernel()
            scheduler = getattr(kernel, "scheduler", None) if kernel else None
            if scheduler is None:
                return
            try:
                tts = get_tts_manager()
            except Exception:
                tts = None
            tid = turn_id or "unknown"
            sid = session_id or "unknown"
            lane_busy = False
            try:
                lane_busy = bool(scheduler.is_playing())
            except Exception:
                lane_busy = False
            for text in beats:
                text = (text or "").strip()
                if not text:
                    continue
                ref = None
                # Lowest-priority invariant: pre-synthesize only while the
                # lane is idle; the manager additionally try-locks, so lane
                # synthesis can never queue behind a hold job.
                if not lane_busy and tts is not None and hasattr(tts, "presynthesize_hold"):
                    try:
                        ref = tts.presynthesize_hold(tid, text)
                    except Exception:
                        ref = None
                try:
                    scheduler.add_beat(
                        text, turn_id=tid, session_id=sid,
                        kind="planned", audio_ref=ref,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[AgentKernel] planned beat admit skipped: %s", exc)
                    if ref is not None and hasattr(tts, "free_held"):
                        try:
                            tts.free_held(ref)
                        except Exception:
                            pass
        except Exception:  # noqa: BLE001 â€” narration never blocks the turn
            pass

    def _admit_first_beat(self, plan, *, turn_id=None, session_id=None) -> None:
        """Speak the first planned beat immediately (REQ-10 AC10.10, T12).

        The planning call authors direction + time beats; the first speaks
        the moment authoring completes through the narration lane. Remaining
        beats stay on the plan for the T13 beat store (pending narration is
        subsumable, so they coalesce rather than stack). Never raises: beats
        are companion speech, never load-bearing for the turn.
        """
        try:
            beats = list(getattr(plan, "beats", None) or [])
            if not beats:
                return
            text = (beats[0] or "").strip()
            if not text:
                return
            from backend.agent.conversation_kernel import get_conversation_kernel
            from backend.agent.speech_lanes import (
                KIND_PLANNED,
                NARRATION,
                Situation,
                build_node,
                route,
            )

            kernel = get_conversation_kernel()
            scheduler = getattr(kernel, "scheduler", None) if kernel else None
            if scheduler is None:
                logger.debug("[AgentKernel] first beat dropped (no lane scheduler)")
                return
            situation = Situation(
                trigger_label=NARRATION,
                source="planned-beat",
                content_shape="prose",
            )
            node = build_node(
                situation,
                route(situation),
                turn_id=turn_id or "unknown",
                session_id=session_id or "unknown",
                content={"kind": "text", "text": text},
                kind=KIND_PLANNED,
            )
            scheduler.admit(node)
            logger.info(
                "[AgentKernel] first planned beat admitted (turn=%s)", turn_id
            )
        except Exception as exc:  # noqa: BLE001 â€” narration never blocks the turn
            logger.debug("[AgentKernel] first beat admit skipped: %s", exc)

    def _is_web_search_request(self, text: str) -> bool:
        """Quick heuristic: does the user message explicitly request a web search?

        REQ-15 AC15.3 (T19): this method's private trigger list was a DUPLICATE
        of ``explorer._WEB_INTENT_TRIGGERS``. Both are now one consumer â€”
        delegated here so there is exactly one place the phrasing list lives,
        with the engine's ``web_intent`` judgment consulted first when an engine
        is available (AC15.4: the keywords remain the fallback).
        """
        try:
            from backend.agent.explorer import AUTO_ENGINE, _is_web_intent
            # The engine is passed EXPLICITLY (2026-09-27). Without it the
            # consumer's verdict is never asked for, so web_intent writes no row
            # and can never reach the Wave 7 bar. `engine=None` still means "no
            # engine" on purpose â€” this is the caller opting in.
            # turn_key: one Oracle score per (turn, goal) - five call sites ask
            # about the same goal, twice a turn (Stage B, 2026-10-05).
            return bool(_is_web_intent(
                text or "", engine=AUTO_ENGINE,
                turn_key=getattr(self, "_current_turn_id", None),
            ))
        except Exception:  # noqa: BLE001 â€” a failed check is simply "no"
            return False

    def _looks_informational(self, text: str) -> bool:
        """Conservative fact-seeking intent signal (used ONLY with web mode ON).

        _is_web_search_request() requires an explicit search phrase, which
        misses factual questions that arrive without one â€” e.g. the frontend
        strips the "websearch:" prefix, so "what are the latest NASA Mars
        rover discoveries this month?" has no trigger phrase (T36 finding
        2026-08-09). This helper catches question-word / current-info
        phrasing so the DER-skip gate does not misroute them as chit-chat.

        Deliberately narrow: it must NOT match greetings or small talk
        ("hello", "how are you", "tell me a joke") â€” those stay on the fast
        path even when web mode is ON.
        """
        if not text:
            return False
        _lower = text.lower().strip()
        _triggers = [
            # question-word openers (fact-seeking, not chit-chat)
            "what is", "what are", "what's", "what was", "when was",
            "when did", "when is", "where is", "where are", "why did",
            "why is", "how many", "how much", "how long", "how big",
            "how far", "how does", "how do", "is there", "are there",
            "what happened", "what's happening", "what's new", "who won",
            # current-info / news phrasing
            "latest", "news", "recent", "today", "this month",
            "this week", "this year", "weather", "forecast", "score",
            "election", "population", "capital of", "price of", "stock",
            "launch", "discovery", "announce", "update on", "status of",
        ]
        return any(t in _lower for t in _triggers)

    def _should_skip_der(
        self,
        plan_steps: list,
        task_clean: str,
        web_on: bool,
    ) -> bool:
        """DER-skip gate (extracted for contract testing, T36 2026-08-09).

        Returns True when the plan may be answered on the direct fast path
        without the DER card machinery:
          - empty plan (nothing to execute), or
          - voice-only plan (only speak steps) AND no web-search intent AND
            NOT (web mode ON + factual/informational question).

        The web-mode clause is the T36 fix: with internet access toggled ON,
        a factual question (which the frontend may strip of its "websearch:"
        prefix) must reach DER so the crawler path stays available. Chit-chat
        still skips DER regardless of web mode.

        F6 interaction (2026-08-12): plan steps are GOALS ONLY â€” the parse
        hardcodes ``tool=None`` and the single resolver (explorer.propose)
        assigns tools at execution time. Therefore step.tool is ALWAYS None
        for production plans, and the empty string must NOT count as a
        "voice-only" tool. With "" in the speak set, every planned task was
        misread as voice-only and DER (task card + tool execution) was
        skipped â€” an explicit "use the screenshot_page tool" prompt produced
        a trivial plan, no task card, and the empty fallback. Only
        EXPLICITLY marked speak steps are voice-only now.
        """
        _voice_only = bool(plan_steps) and all(
            (s.tool or "").lower() in ("speak", "speak_tool", "tts")
            for s in plan_steps
        )
        _is_websearch = self._is_web_search_request(task_clean)
        _informational = self._looks_informational(task_clean)
        return (
            not plan_steps
            or (
                _voice_only
                and not _is_websearch
                and not (web_on and _informational)
            )
        )

    def _empty_der_fallback_message(
        self,
        text: str,
        web_on: bool,
        der_err_text: str = "",
    ) -> str:
        """Empty-DER fallback wording (extracted for contract testing, T36 2026-08-09).

        Produces an AWARE message instead of the old blind
        "IRIS couldn't generate a response. Please try again.":
          - real upstream error detail â†’ surface it (retry / switch model)
          - search-intent turn + web OFF â†’ advise toggling internet access
          - search-intent turn + web ON â†’ honest incomplete-search message
          - otherwise â†’ neutral rephrase guidance
        Never contains the phrase "couldn't generate" (contract: it must not
        reach a chat_message content on a healthy path).
        """
        _searchy = self._is_web_search_request(text) or self._looks_informational(text)
        if der_err_text:
            return (
                f"I hit an error while working on that ({der_err_text}). "
                f"You can try again, or ask me in a different way."
            )
        if _searchy and not web_on:
            return (
                "Web search is currently disabled. You can toggle internet "
                "access on via the dashboard (the web button) to enable "
                "web features."
            )
        if _searchy:
            return (
                "I couldn't complete the web search for that â€” the search "
                "returned nothing usable. Please try again, or ask me "
                "without the web."
            )
        return (
            "I wasn't able to put together an answer for that. You can "
            "try again, or rephrase your question."
        )

    def plan_task(
        self, task_description: str, context: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Use lfm2-8b (reasoning model) for task planning with timeout and error handling.

        Args:
            task_description: User's task/query
            context: Optional conversation context

        Returns:
            Plan dictionary with steps, or error dictionary

        Raises:
            TimeoutError: If inference exceeds timeout
        """
        start_time = time.time()
        # 120s: LM Studio with a 9B model can take 30-60s for first token on cold start
        timeout_seconds = 120

        try:
            logger.info("[AgentKernel] Planning task with reasoning model...")

            # Get reasoning model
            reasoning_model = None
            if self._model_router:
                try:
                    # Use user-selected reasoning model if available
                    if self._selected_reasoning_model:
                        reasoning_model = self._model_router.models.get(
                            self._selected_reasoning_model
                        )
                        if reasoning_model:
                            logger.info(
                                f"[AgentKernel] Using user-selected reasoning model: {self._selected_reasoning_model}"
                            )
                        else:
                            # Only fall back to the default local stub when neither Ollama
                            # nor VPS will handle this request.  If ":" is in the model ID
                            # it is an Ollama model (e.g. "llama3.2:3b"); if VPS is wired
                            # the VPS block below handles it.  In those cases we MUST NOT
                            # fall back â€” the stub is broken and produces garbage output.
                            _sel_check = self._selected_reasoning_model
                            _ollama_will_handle = ":" in _sel_check
                            _vps_will_handle = bool(self._vps_gateway)
                            _lmstudio_will_handle = self._is_openai_compat()
                            if (
                                not _ollama_will_handle
                                and not _vps_will_handle
                                and not _lmstudio_will_handle
                            ):
                                logger.warning(
                                    f"[AgentKernel] Selected model {_sel_check} unavailable, "
                                    "falling back to default local model"
                                )
                                reasoning_model = (
                                    self._model_router.get_reasoning_model()
                                )
                                if reasoning_model:
                                    default_model_id = getattr(
                                        reasoning_model, "model_id", "unknown"
                                    )
                                    logger.info(
                                        f"[AgentKernel] Fallback: using default reasoning model {default_model_id}"
                                    )
                            else:
                                _dest = (
                                    "LM Studio"
                                    if _lmstudio_will_handle
                                    else ("Ollama" if _ollama_will_handle else "VPS")
                                )
                                logger.info(
                                    f"[AgentKernel] Selected model '{_sel_check}' not in local cache â€” "
                                    f"will route to {_dest}"
                                )
                                # reasoning_model stays None; inference block handles it
                    else:
                        # No model selected â€” use default reasoning model
                        reasoning_model = self._model_router.get_reasoning_model()
                        if reasoning_model:
                            default_model_id = getattr(
                                reasoning_model, "model_id", "unknown"
                            )
                            logger.info(
                                f"[AgentKernel] No model selected, using default reasoning model: {default_model_id}"
                            )
                except Exception as e:
                    logger.error(f"[AgentKernel] Error getting reasoning model: {e}")
                    return {"error": f"Failed to access reasoning model: {e}"}

            # Handle model unavailability
            if not reasoning_model:
                if self._single_model_mode and self._available_model_id:
                    # Fall back to the single available local model
                    logger.warning(
                        "[AgentKernel] Reasoning model unavailable, using fallback model"
                    )
                    try:
                        reasoning_model = self._model_router.models.get(
                            self._available_model_id
                        )
                    except Exception as e:
                        logger.error(
                            f"[AgentKernel] Error accessing fallback model: {e}"
                        )
                        return {"error": f"Failed to access fallback model: {e}"}
                elif self._is_openai_compat():
                    # LM Studio is configured â€” reasoning_model stays None; the LM Studio
                    # inference block below handles it via localhost:1234.
                    logger.info(
                        "[AgentKernel] No local model loaded; delegating planning to LM Studio"
                    )
                elif self._vps_gateway:
                    # VPS Gateway is configured â€” no local model required.
                    # reasoning_model stays None; the VPS inference block below handles it.
                    logger.info(
                        "[AgentKernel] No local reasoning model; delegating planning to VPS Gateway"
                    )
                elif self._selected_reasoning_model and self._model_router:
                    # The user confirmed a model but it isn't in _model_router.models yet.
                    # Two sub-cases:
                    # A) Ollama model â€” ID contains ":" (e.g. "llama3.2:3b")
                    #    â†’ handled in the Ollama inference block below.
                    #    NOTE: provider="local" means LFM local file, NOT Ollama.
                    #    Only ":" in the ID identifies an Ollama model.
                    # B) LFM HuggingFace model (provider="local", no ":" in ID)
                    #    â†’ trigger load_models() now so the model dict is populated.
                    _sel = self._selected_reasoning_model
                    _is_ollama = ":" in _sel  # ONLY colon-format IDs go to Ollama
                    if _is_ollama:
                        logger.info(
                            f"[AgentKernel] Ollama model '{_sel}' selected; "
                            "will infer via localhost:11434"
                        )
                        # reasoning_model stays None â€” Ollama block below handles inference
                    else:
                        # LFM lazy-load path (provider="local", model file on disk)
                        logger.info(
                            f"[AgentKernel] LFM model '{_sel}' not loaded; triggering lazy load..."
                        )
                        try:
                            self._model_router.load_models()
                            reasoning_model = self._model_router.models.get(_sel)
                            if reasoning_model is None:
                                _all = list(self._model_router.models.values())
                                if _all:
                                    reasoning_model = _all[0]
                                    logger.info(
                                        "[AgentKernel] Exact model not found after lazy load; "
                                        f"using first available: {list(self._model_router.models.keys())[0]}"
                                    )
                        except Exception as _lazy_err:
                            logger.warning(
                                f"[AgentKernel] Lazy load failed: {_lazy_err}"
                            )
                        if not reasoning_model:
                            return {
                                "error": (
                                    f"Local model '{_sel}' could not be loaded. "
                                    "Check that the model file exists in the models/ directory, "
                                    "or switch to an Ollama or VPS model in Settings â†’ Configure."
                                )
                            }
                else:
                    return {
                        "error": (
                            "No inference backend configured. "
                            "Please go to Settings â†’ Configure and select a Local, VPS, or OpenAI model."
                        )
                    }

            # Build planning prompt with personality and context
            system_prompt = ""
            if self._personality:
                try:
                    system_prompt = self._personality.get_system_prompt()
                except Exception as e:
                    logger.warning(f"[AgentKernel] Error getting system prompt: {e}")

            context_str = ""
            if context:
                context_str = "\n\nConversation Context:\n" + json.dumps(
                    context[-5:], indent=2
                )

            planning_prompt = f"""{system_prompt}

You are analyzing a user request and creating an execution plan.

Task: {task_description}{context_str}

Create a structured plan with these steps:
1. Analyze what the user wants
2. Determine if tools are needed
3. Break down into actionable steps

Respond with a JSON object:
{{
    "analysis": "brief analysis of the request",
    "requires_tools": true/false,
    "steps": [
        {{
            "step": 1,
            "action": "description",
            "tool": "tool_name or null",
            "parameters": {{}}
        }}
    ]
}}"""

            # Use VPS Gateway for inference if available, otherwise use local model
            plan_response = None
            if self._vps_gateway:
                try:
                    logger.info(
                        "[AgentKernel] Using VPS Gateway for planning inference..."
                    )
                    try:
                        plan_response = asyncio.run(
                            self._vps_gateway.infer(
                                model=self._model_router.get_reasoning_model_id()
                                or "lfm2-8b",
                                prompt=planning_prompt,
                                context={"conversation_history": context}
                                if context
                                else {},
                                params={"max_tokens": 512, "temperature": 0.2},
                                session_id=self.session_id,
                            )
                        )
                        logger.info("[AgentKernel] VPS Gateway inference complete")
                    except RuntimeError as e:
                        if "already running" in str(e):
                            logger.warning(
                                "[AgentKernel] Event loop conflict â€” falling back to local model"
                            )
                            plan_response = None
                        else:
                            raise
                except TimeoutError:
                    logger.error("[AgentKernel] VPS Gateway inference timed out")
                    raise
                except Exception as e:
                    logger.warning(
                        f"[AgentKernel] VPS Gateway inference failed, falling back to direct model: {e}"
                    )
                    plan_response = None

            # LM Studio inference (OpenAI-compatible local API at localhost:1234).
            # Triggered when provider == "lmstudio" and no prior backend produced a response.
            # Uses the openai Python client pointed at the LM Studio local server.
            if plan_response is None and self._is_openai_compat():
                try:
                    _lms = self._get_lmstudio_client()
                    _lms_resp = _lms.chat.completions.create(
                        model=self._selected_reasoning_model or "local-model",
                        messages=[{"role": "user", "content": planning_prompt}],
                        max_tokens=-1,
                        temperature=0.2,  # low temp = faster, more deterministic JSON
                        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                    )
                    plan_response = _lms_resp.choices[0].message.content
                    logger.info(
                        f"[AgentKernel] LM Studio planning inference successful "
                        f"(model: {self._selected_reasoning_model}, endpoint: {self._lmstudio_endpoint})"
                    )
                except Exception as _lms_err:
                    logger.warning(
                        f"[AgentKernel] LM Studio planning inference failed: {_lms_err}"
                    )

            # Ollama local inference â€” runs when the model ID contains ":" which is
            # the Ollama format (e.g. "llama3.2:3b", "mistral:7b", "kimi-k2.5:cloud").
            # NOTE: provider="local" means LFM local file â€” it does NOT go to Ollama.
            # Only colon-format IDs are Ollama models.
            if (
                plan_response is None
                and self._selected_reasoning_model
                and (":" in self._selected_reasoning_model)
            ):
                try:
                    import requests as _req

                    _ollama_resp = _req.post(
                        "http://localhost:11434/api/chat",
                        json={
                            "model": self._selected_reasoning_model,
                            "messages": [{"role": "user", "content": planning_prompt}],
                            "stream": False,
                        },
                        timeout=60,
                    )
                    if _ollama_resp.status_code == 200:
                        plan_response = (
                            _ollama_resp.json().get("message", {}).get("content", "")
                        )
                        logger.info(
                            f"[AgentKernel] Ollama planning inference successful "
                            f"(model: {self._selected_reasoning_model})"
                        )
                    else:
                        logger.warning(
                            f"[AgentKernel] Ollama returned HTTP {_ollama_resp.status_code} "
                            f"for model '{self._selected_reasoning_model}': "
                            f"{_ollama_resp.text[:200]}"
                        )
                except Exception as _ollama_err:
                    logger.warning(
                        f"[AgentKernel] Ollama planning inference failed: {_ollama_err}"
                    )

            # Fall back to direct model access if VPS Gateway not available or failed
            if plan_response is None:
                # If there is no local model to fall back to we cannot continue.
                if reasoning_model is None:
                    # Produce a context-aware error message.
                    _sel_err = self._selected_reasoning_model or ""
                    if self._vps_gateway:
                        _err_msg = (
                            "VPS inference failed and no local model is loaded. "
                            "Check your VPS connection or configure a local model in Settings."
                        )
                    elif ":" in _sel_err:
                        _model_name = _sel_err.split(":")[0]
                        _err_msg = (
                            f"Ollama model '{_sel_err}' is not available. "
                            f"Make sure Ollama is running and the model is pulled: "
                            f"ollama pull {_model_name}"
                        )
                    elif _sel_err:
                        _err_msg = (
                            f"Model '{_sel_err}' could not be loaded. "
                            "Check that the model file exists, or select a different model in Settings â†’ Configure."
                        )
                    else:
                        _err_msg = (
                            "No inference backend configured. "
                            "Please go to Settings â†’ Configure and select a Local, VPS, or OpenAI model."
                        )
                    return {"error": _err_msg}

                # Check timeout before loading model
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    raise TimeoutError(f"Planning timed out after {elapsed:.1f}s")

                # Load model if needed with error handling
                try:
                    if not reasoning_model.is_loaded():
                        logger.info("[AgentKernel] Loading reasoning model...")
                        reasoning_model.load()
                except Exception as e:
                    logger.error(f"[AgentKernel] Failed to load reasoning model: {e}")
                    return {"error": f"Model loading failed: {e}"}

                # Check timeout before inference
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    raise TimeoutError(f"Planning timed out after {elapsed:.1f}s")

                # Generate plan with error handling
                try:
                    plan_response = reasoning_model.generate(
                        planning_prompt, max_tokens=-1, temperature=0.2
                    )
                except Exception as e:
                    logger.error(f"[AgentKernel] Model inference failed: {e}")
                    # Attempt to restart model
                    try:
                        logger.info(
                            "[AgentKernel] Attempting to restart reasoning model..."
                        )
                        reasoning_model.unload()
                        reasoning_model.load()
                        plan_response = reasoning_model.generate(
                            planning_prompt, max_tokens=-1, temperature=0.2
                        )
                        logger.info("[AgentKernel] Model restarted successfully")
                    except Exception as restart_error:
                        logger.error(
                            f"[AgentKernel] Model restart failed: {restart_error}"
                        )
                        return {
                            "error": f"Model crashed and restart failed: {restart_error}"
                        }

            # Check timeout after inference
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Planning timed out after {elapsed:.1f}s")

            # Parse JSON response
            try:
                plan = json.loads(plan_response)
                logger.info(
                    f"[AgentKernel] Plan generated with {len(plan.get('steps', []))} steps in {elapsed:.2f}s"
                )
                return plan
            except json.JSONDecodeError:
                # Model returned free-form text rather than JSON.
                # Treat the entire response as the user-facing reply â€” do NOT use
                # "respond_to_user" as the action string because execute_step would
                # return that keyword verbatim to the frontend.
                logger.warning(
                    "[AgentKernel] Failed to parse plan as JSON, using raw text as response"
                )
                _raw_text = (
                    self._strip_thinking(plan_response)
                    if plan_response
                    else "I'm not sure how to respond to that."
                )
                return {
                    "analysis": _raw_text[:200],
                    "requires_tools": False,
                    "_raw_response": _raw_text,  # consumed by _synthesize_response
                    "steps": [
                        {
                            "step": 1,
                            "action": _raw_text,  # the ACTUAL text, not a keyword
                            "tool": None,
                            "parameters": {},
                        }
                    ],
                }

        except TimeoutError:
            logger.error(f"[AgentKernel] Planning timed out after {timeout_seconds}s")
            raise
        except Exception as e:
            error_msg = f"Error during task planning: {e}"
            logger.error(f"[AgentKernel] {error_msg}", exc_info=True)
            return {"error": error_msg}

    @staticmethod
    def _route_v2_frame(text: Optional[str], web_mode: bool) -> Dict[str, Any]:
        """The ONE frame route_v2 reads - the shadow and the site share it, so
        their rows are one cohort (route_v2/binary-v1)."""
        return {"goal": (text or "")[:200], "task_class": "personal",
                "last_result": "", "chars": len(text or ""),
                "web_mode": bool(web_mode)}

    def _route_v2_route(
        self, text: Optional[str], turn_id: Optional[str], gate_plans: bool
    ) -> Optional[bool]:
        """route_v2's decision site: True = plan (DER), False = answer direct,
        None = the gate's route stands.

        It acts (a) when the bar lets it decide (allow-list + earned bar +
        a confident answer, `oracle_acts`), or (b) on the sampled rung: a
        bounded, deterministic share of turns (`sampled_consult_ok`,
        SAMPLE_FRACTION) where its route drives the turn and the row is held
        for the turn verdict - the outcome label the parity bar lacks (on a
        parity label a "direct" pick the gate would have planned is unscored).
        One synchronous Oracle call (~0.3 s) on those turns only; any fault
        returns None, so the gate decides."""
        try:
            from backend.agent.decision_engine import (
                decides, get_decision_engine, oracle_acts, sampled_consult_ok,
                sampled_row,
            )

            _enforced = decides("route_v2") is not None
            _sampled = (not _enforced) and sampled_consult_ok(
                "route_v2", f"{turn_id or ''}|{(text or '')[:80]}")
            if not (_enforced or _sampled):
                return None
            eng = get_decision_engine()
            if eng is None:
                return None
            frame = self._route_v2_frame(text, self._web_mode_on())
            ds = eng.decide("route_v2", ["direct", "der"], frame)
            if ds is None or ds.chosen not in ("direct", "der"):
                return None
            if _enforced:
                return (ds.chosen == "der") if oracle_acts("route_v2", ds.confidence) else None
            row = sampled_row(
                "route_v2", ds.chosen, float(ds.confidence),
                engine=str(eng.model_id or ""),
                engine_latency_ms=ds.engine_latency_ms,
                brain_choice="der" if gate_plans else "direct",
                # its own cohort: outcome rows never pool with the parity
                # rows (route_v2/binary-v1) in a scoped report
                criteria_version="route_v2/outcome-v1",
                # outcome-labelled from birth: without a verdict (a live turn
                # swept unlabelled) decision_label leaves it unscored, never
                # "right" by default
                label_source="outcome",
                turn_id=str(turn_id or ""), state=frame)
            from backend.agent import turn_verdict_label as _tvl

            if not _tvl.defer(row, self._shadow_row_sink):
                self._shadow_row_sink(row)
            logger.info("[route_v2] sampled turn=%s oracle=%s gate=%s conf=%.3f",
                        turn_id, ds.chosen, "der" if gate_plans else "direct",
                        float(ds.confidence))
            return ds.chosen == "der"
        except Exception as e:  # noqa: BLE001 - the gate decides on any fault
            logger.debug("[route_v2] site failed: %r", e)
            return None

    @staticmethod
    def _caducean_modulate_temperature(base: float, session_id: str) -> float:
        """Phase 5: modulate planning temperature by the live Caducean recommendation.

        REQ-19 vocabulary: "COMPRESS"/"EXPAND"/"MAINTAIN" here are DER PHYSICS
        RECOMMENDATION CODES (ints 1/0/2) returned by ffi_caducean_recommend.
        They modulate temperature ONLY â€” they compact/expand NOTHING. Actual
        compaction is DCP message pruning (dcp.py) and mycelium condense/expand
        (scorer.py); Step Expansion is _growth_width->_split_step. See the
        REQ-19 vocabulary table in specs/long-horizon-der-execution/design.md.

        - COMPRESS (rec==1) -> more deterministic (temperature halved)
        - EXPAND   (rec==0) -> more exploratory (temperature *1.2, capped at 0.6)
        - MAINTAIN (rec==2) / unknown / TOPO_VIOLATION -> base unchanged

        Pure function of (base, session_id); never raises â€” returns ``base`` on
        any error so planning always proceeds.
        """
        try:
            from backend.gateway.iris_ffi import ffi_caducean_recommend

            _rec = ffi_caducean_recommend(session_id)
            if _rec == 1:  # COMPRESS
                return max(0.0, base * 0.5)
            if _rec == 0:  # EXPAND
                return min(0.6, base * 1.2)
        except Exception:
            pass
        return base

    def _gc_result_is_error(self, result: object) -> bool:
        """True when a settled step's result is an ERROR envelope, not output.

        Session 326 (live bug): ceiling discovery extracted "facts" from shell
        error text because a step can be VERIFIED while its result is a failed
        command. Accepts a dict envelope (``success: False`` / an ``error`` key /
        non-zero ``returncode``) or a JSON string of one. Never raises; an
        unparseable string is treated as real output (discovery is advisory, so
        a false negative is harmless while a false positive pollutes the
        ceiling with error text).
        """
        try:
            _r = result
            if isinstance(_r, str):
                _s = _r.strip()
                if _s[:1] in ("{", "["):
                    try:
                        import json as _json_err

                        _r = _json_err.loads(_s)
                    except Exception:
                        return False
                else:
                    return False
            if isinstance(_r, dict):
                if _r.get("success") is False:
                    return True
                if str(_r.get("error") or "").strip():
                    return True
                _rc = _r.get("returncode")
                if isinstance(_rc, int) and _rc != 0:
                    return True
                # A stdout that is only a shell "not recognized"/usage error is
                # still an error even when the wrapper reported success.
                _out = str(_r.get("stdout") or "").lower()
                if _out and any(
                    _m in _out
                    for _m in (
                        "is not recognized",
                        "command not found",
                        "no such file or directory",
                        "cannot find path",
                    )
                ):
                    return True
            return False
        except Exception:
            return False

    def _goal_contract_bound_cover_push(self, open_facts: List[str]) -> List[str]:
        """Bound the "cover the open required fact" push per fact.

        Each call counts one push for the first open fact. A fact pushed
        GOAL_COVER_PUSH_MAX times without being covered is BLOCKED (reason
        no_progress) and the next open fact is tried. Returns the facts still
        worth a push. Measured 2026-10-01 (eval c06): the push had no bound -
        36 pushes on a fact no step could cover, reply 366 s vs 64 s. (The
        streak gate's coverage-stall brake runs only when the user steers.)
        """
        try:
            from backend.agent.der_constants import GOAL_COVER_PUSH_MAX

            _st = getattr(self, "_goal_contract_state", None)
            if _st is None:
                return open_facts
            _pushes = _st.setdefault("cover_pushes", {})
            _left = list(open_facts)
            while _left:
                _k = str(_left[0]).strip().lower()
                if int(_pushes.get(_k, 0)) < GOAL_COVER_PUSH_MAX:
                    _pushes[_k] = int(_pushes.get(_k, 0)) + 1
                    return _left
                _blocked = _st.get("blocked") or []
                _blocked.append({
                    "fact": str(_left[0]),
                    "reason": "no_progress",
                    "evidence": f"{GOAL_COVER_PUSH_MAX} pushes, still not covered",
                })
                _st["blocked"] = _blocked
                _counters = _st.get("counters") or {}
                _counters["facts_blocked"] = len(_blocked)
                _st["counters"] = _counters
                logger.info(
                    "[goal-contract] fact BLOCKED (no_progress after %d pushes) "
                    "conv=%s: %r",
                    GOAL_COVER_PUSH_MAX, getattr(self, "conversation_id", ""),
                    str(_left[0])[:160],
                )
                _left = _left[1:]
            return []
        except Exception as _bp_exc:  # noqa: BLE001 - a bound never breaks the loop
            logger.warning("[goal-contract] cover-push bound failed: %r", _bp_exc)
            return open_facts

    def _goal_contract_cover_step(self) -> Optional[Dict]:
        """The goal of the step that covers the first open required fact, or
        None when no fact is open (or every open fact used its pushes).
        Called as a class function: a stand-in kernel without a contract
        dict gets None."""
        try:
            if not isinstance(getattr(self, "_goal_contract_state", None), dict):
                return None
            _open = AgentKernel._goal_contract_open_facts(self)
            if _open:
                _open = AgentKernel._goal_contract_bound_cover_push(self, _open)
            if not _open:
                return None
            logger.info(
                "[goal-contract] gap open (%d facts) â€” requesting "
                "work instead of finalizing: %r",
                len(_open), str(_open[0])[:160],
            )
            from backend.agent import goal_contract as _gc_cover

            return {"description": _gc_cover.cover_goal(
                _open[0], self._goal_contract_state.get("results") or ()
            )}
        except Exception as _cs_exc:  # noqa: BLE001 - doubt means no push
            logger.warning("[goal-contract] cover step failed: %r", _cs_exc)
            return None

    def _goal_contract_met(self) -> bool:
        """True when a goal contract exists, it has required facts, all are
        covered and none is blocked. Advisory; False on any doubt."""
        try:
            _st = getattr(self, "_goal_contract_state", None)
            _contract = _st.get("contract") if isinstance(_st, dict) else None
            if _contract is None or not list(_contract.required or []):
                return False
            if _st.get("blocked"):
                return False
            return not self._goal_contract_open_facts()
        except Exception:  # noqa: BLE001 â€” doubt means "not met": the consult runs
            return False

    def _goal_contract_open_facts(self) -> List[str]:
        """Goal contract T6 (REQ-3 AC3.2/AC3.6): required facts neither covered
        nor blocked. Advisory helper â€” empty when no contract exists."""
        try:
            _st = getattr(self, "_goal_contract_state", None)
            if _st is None:
                return []
            _contract = _st.get("contract")
            if _contract is None:
                return []
            _covered = {str(_c).strip().lower() for _c in _st.get("covered", [])}
            _blocked = set()
            try:
                from backend.agent import goal_contract as _gc_mod3

                for _bf in _st.get("blocked", []):
                    if isinstance(_bf, dict):
                        _blocked.add(str(_bf.get("fact", "")).strip().lower())
                    else:
                        _blocked.add(str(_bf).strip().lower())
                _open = [
                    str(_f) for _f in _contract.required
                    if str(_f).strip().lower() not in _covered
                    and str(_f).strip().lower() not in _blocked
                ]
                return _open
            except Exception:
                return [
                    str(_f) for _f in _contract.required
                    if str(_f).strip().lower() not in _covered
                ]
        except Exception:
            return []

    def _goal_contract_block_facts(
        self,
        failed_item: object = None,
        reason: str = "",
        evidence: str = "",
    ) -> List[str]:
        """Mark uncovered facts a failed step was working on as blocked (T9).

        REQ-5 AC5.1: only fires on a terminal typed Reason (via
        goal_contract.is_blocked); non-terminal failures are retried, not
        blocked. Blocked facts stay in the denominator (AC5.2, CT-GC7).
        Returns the newly blocked fact texts.
        """
        try:
            _st = getattr(self, "_goal_contract_state", None)
            if _st is None:
                return []
            from backend.agent import goal_contract as _gc_mod4

            _reason = str(reason or getattr(failed_item, "error_type", "") or "")
            if not _gc_mod4.is_blocked(_reason):
                return []
            _open = self._goal_contract_open_facts()
            if not _open:
                return []
            _step_text = " ".join([
                str(getattr(failed_item, "description", "") or ""),
                str(getattr(failed_item, "expected_output", "") or ""),
                str(evidence or ""),
            ])
            _hits = list(_gc_mod4.step_fact_hits(_open, _step_text))
            if not _hits:
                # The failed step maps to no open fact â€” name the gap against
                # the first open fact so the block is never silent.
                _hits = [str(_open[0])]
            _blocked = _st.get("blocked") or []
            _have = set()
            for _b in _blocked:
                if isinstance(_b, dict):
                    _have.add(str(_b.get("fact", "")).strip().lower())
                else:
                    _have.add(str(_b).strip().lower())
            _new: List[str] = []
            import time as _time_mod

            for _h in _hits:
                if str(_h).strip().lower() in _have:
                    continue
                _blocked.append({
                    "fact": str(_h),
                    "reason": _reason,
                    "evidence": str(evidence or "")[:200],
                })
                _new.append(str(_h))
                _have.add(str(_h).strip().lower())
            _st["blocked"] = _blocked
            try:
                _counters = _st.get("counters") or {}
                _counters["facts_blocked"] = len(_blocked)
                _st["counters"] = _counters
            except Exception:
                pass
            _task_rec = _st.get("task_record")
            if _task_rec is not None:
                try:
                    _task_rec.blocked_facts = list(_blocked)
                except Exception:
                    pass
            for _h in _new:
                logger.info(
                    "[goal-contract] fact blocked (%s): %r",
                    _reason, _h[:160],
                )
            return _new
        except Exception as _blk_exc:
            logger.debug("[goal-contract] block skipped: %s", _blk_exc)
            return []

    def _goal_contract_blocked_texts(self) -> List[str]:
        """Blocked fact texts for grade + naming (T9/T10)."""
        try:
            _st = getattr(self, "_goal_contract_state", None)
            if _st is None:
                return []
            _out: List[str] = []
            for _b in _st.get("blocked", []) or []:
                if isinstance(_b, dict):
                    _out.append(str(_b.get("fact", "")))
                else:
                    _out.append(str(_b))
            return [str(_f) for _f in _out if str(_f).strip()]
        except Exception:
            return []

    def _goal_contract_name_blocked(self, answer: str) -> str:
        """T9 AC5.3/AC5.4: the final answer names every blocked fact.

        When blocked facts exist and the answer does not already name all
        of them, the deterministic blocked-fact summary is the floor â€” the
        naming block is appended so every blocked fact is explicit. Returns
        the answer unchanged when nothing is blocked or all are named.
        Advisory: never raises.
        """
        try:
            _blocked = self._goal_contract_blocked_texts()
            if not _blocked or not (answer or "").strip():
                return answer
            from backend.agent import goal_contract as _gc_mod6

            _unnamed = [
                _f for _f in _blocked
                if not _gc_mod6.step_fact_hits((_f,), answer or "")
            ]
            if not _unnamed:
                return answer
            _lines = "\n".join(f"- {_f}" for _f in _blocked)
            _suffix = (
                "\n\nParts of your request I could not cover "
                "(blocked â€” not skipped):\n" + _lines
            )
            logger.info(
                "[goal-contract] named %d blocked fact(s) in final answer "
                "(%d were unnamed)", len(_blocked), len(_unnamed),
            )
            return str(answer or "") + _suffix
        except Exception:
            return answer

    def _goal_contract_apply_steering(self, text: str) -> bool:
        """Route user steering through amend (T7, REQ-4 AC4.1/AC4.6/AC4.7).

        Amends the task node's required set in place â€” add, remove, or
        repromote â€” without creating a second task. Writes the forward
        amendment node (derives_from, T8) and logs who/when/why (AC7.3).
        Returns True when the contract changed.
        """
        try:
            _st = getattr(self, "_goal_contract_state", None)
            if _st is None or not (text or "").strip():
                return False
            from backend.agent import goal_contract as _gc_mod5

            _parsed = _gc_mod5.parse_steering_amendment(
                text,
                list(_st["contract"].required),
                self._goal_contract_blocked_texts(),
            )
            if not any(_parsed.values()):
                return False
            import time as _time_mod2

            _old = _st["contract"]
            _new = _old
            # Repromote: drop the blocked entry so the fact is open again.
            _repromoted: List[str] = []
            for _rp in _parsed.get("repromote", ()):
                _keys = {_b["fact"].strip().lower() for _b in _st.get("blocked", [])
                         if isinstance(_b, dict)}
                _kept = [
                    _b for _b in _st.get("blocked", [])
                    if not (isinstance(_b, dict)
                            and _b.get("fact", "").strip().lower()
                            == str(_rp).strip().lower())
                ]
                if len(_kept) != len(_st.get("blocked", [])):
                    _st["blocked"] = _kept
                    _repromoted.append(str(_rp))
            if _parsed.get("add") or _parsed.get("remove"):
                _new = _gc_mod5.amend(
                    _old, add=_parsed.get("add", ()),
                    remove=_parsed.get("remove", ()),
                    source="user", reason=str(text)[:200],
                )
            if _new is _old and not _repromoted:
                return False
            _from_v = int(_old.version)
            _st["contract"] = _new
            _st["task_record"].required_facts = list(_new.required)
            _st["task_record"].contract_version = int(_new.version)
            # Forward amendment node (T8): who/when/why + version pair.
            _entry = {
                "who": "user",
                "when": _time_mod2.time(),
                "why": str(text)[:200],
                "add": list(_parsed.get("add", ())),
                "remove": list(_parsed.get("remove", ())),
                "repromote": list(_repromoted),
                "version_from": _from_v,
                "version_to": int(_new.version),
            }
            _st.setdefault("amendments", []).append(_entry)
            try:
                _counters2 = _st.get("counters") or {}
                _counters2["amendments_user"] = int(
                    _counters2.get("amendments_user", 0)) + 1
                _st["counters"] = _counters2
            except Exception:
                pass
            try:
                _writer = getattr(self, "_der_links", None)
                if _writer is not None:
                    _writer.link_derives_from(
                        f"contract-v{int(_new.version)}",
                        f"contract-v{_from_v}",
                    )
            except Exception:
                pass
            logger.info(
                "[goal-contract] amendment by user: +%d -%d repromote=%d "
                "v%d->v%d (%s)",
                len(_parsed.get("add", ())), len(_parsed.get("remove", ())),
                len(_repromoted), _from_v, int(_new.version),
                str(text)[:120],
            )
            return True
        except Exception as _am_exc:
            logger.debug("[goal-contract] steering amend skipped: %s", _am_exc)
            return False

    def _goal_contract_bonus_pass(self) -> Optional[Dict[str, str]]:
        """REQ-3 AC3.5: one bounded bonus pass over ceiling facts at C=1.0.

        Returns a goal-only continuation dict when the turn reached full
        floor coverage with uncovered ceiling facts and no bonus pass has
        run yet this turn; None otherwise. Advisory, never raises. The
        counter (REQ-7 AC7.2) is incremented here so every increment has
        exactly one writer.
        """
        try:
            _st = getattr(self, "_goal_contract_state", None)
            if _st is None:
                return None
            _counters = _st.get("counters") or {}
            if abs(float(_st.get("C", 0.0)) - 1.0) >= 1e-9:
                return None
            if int(_counters.get("bonus_passes", 0)) != 0:
                return None
            _covered_now = {
                str(_c).strip().lower() for _c in _st.get("covered", [])
            }
            _open = [
                str(_f) for _f in (_st["contract"].ceiling or ())
                if str(_f).strip().lower() not in _covered_now
            ]
            if not _open:
                return None
            _counters["bonus_passes"] = 1
            _st["counters"] = _counters
            logger.info(
                "[goal-contract] bonus pass over %d ceiling fact(s): %r",
                len(_open), str(_open[0])[:160],
            )
            return {"description": (
                "Bonus pass over an extra discovery: "
                f"{str(_open[0])[:300]}"
            )}
        except Exception:
            return None
