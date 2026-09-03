"""
Recall Phases — two-phase orchestrator for recall-as-cognition.

Protocol:
    Phase R (Recall): short capped completion that emits <recall .../> ops,
                      no answer. Max 256 tokens. Stop on </recall_phase>.
    Resolve:          RecallDecoder runs all ops against the live memory brain.
    Phase A (Answer): full completion with resolved spans injected as a prior
                      assistant turn so the model answers with memory "in mind".

Cost uniformity: Phase A shares the identical prefix with Phase R. On every
provider with prompt caching (Anthropic, OpenAI, llama-cpp, LM Studio, Ollama,
VPS) the Phase A prefix is a cache hit. One extra round-trip, predictable cost,
uniform across all backends.

The orchestrator is intentionally provider-agnostic. It accepts a callable
    infer_fn(messages, max_tokens, temperature, stop) -> str
so the kernel passes its own client and the phases never duplicate provider logic.

Usage:
    phases = RecallPhases(infer_fn=kernel._raw_infer, decoder=decoder)
    answer, spans = phases.run(messages, chunk_callback=cb)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .recall_decoder import RecallDecoder, ResolvedSpan, parse_recall_ops

logger = logging.getLogger(__name__)


def json_safe(obj: Any) -> Any:
    """Recursively coerce obj so it can be JSON-serialised."""
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)

# ---------------------------------------------------------------------------
# Grammar primer — appended to system prompt when recall-native mode is active
# ~60 tokens — small enough to stay in the cached prefix on all providers.
# ---------------------------------------------------------------------------

RECALL_GRAMMAR_PRIMER = (
    "\n\n"
    "Emit <recall .../> ops before answering. "
    "Ops by context: structure→coord  fact→pin query='X'  concept→semantic query='X'"
    "  pattern→similar target='X'  next-step→predict task='X'.\n"
    "Empty result: emit <recall coord/> to probe, then decompose."
)

# Cold-start / sparse instructions appended when the brain is fresh
COLD_START_HINT = (
    "Memory is empty or sparse. Use <recall coord/> to probe the coordinate graph, "
    "then decompose the task into sub-goals and recall against each."
)

# Phase R stop sequence
_RECALL_STOP = ["</recall_phase>"]

# Cap per-turn recall ops to limit Phase R cost
_MAX_OPS_PER_TURN = 6

# Maximum iterative Phase R cycles before firing Phase A
_MAX_RECALL_ITERS = 3


# ---------------------------------------------------------------------------
# Streaming provenance filter
# Strips <recalled>...</recalled> and <recall .../> spans from streaming deltas
# before they reach the user, handling chunks that split mid-tag.
# ---------------------------------------------------------------------------

class _StreamingProvenanceFilter:
    _OPEN_TAGS = ("<recalled", "<recall")
    _CLOSE_RECALLED = "</recalled>"

    def __init__(self, callback: Callable[[str], None]) -> None:
        self._cb = callback
        self._buf = ""
        self._suppressing = False  # inside <recalled>...</recalled> body

    def feed(self, chunk: str) -> None:
        self._buf += chunk
        while self._buf:
            if self._suppressing:
                end = self._buf.find(self._CLOSE_RECALLED)
                if end == -1:
                    if len(self._buf) > 4096:
                        self._buf = ""  # safety drain — tag body is too large
                    return
                self._buf = self._buf[end + len(self._CLOSE_RECALLED):]
                self._suppressing = False
            else:
                earliest = len(self._buf)
                for tag in self._OPEN_TAGS:
                    pos = self._buf.find(tag)
                    if pos != -1:
                        earliest = min(earliest, pos)

                if earliest == len(self._buf):
                    # No tag found — emit safe portion (hold back possible partial prefix)
                    safe = len(self._buf)
                    for tag in self._OPEN_TAGS:
                        for n in range(1, len(tag)):
                            if self._buf.endswith(tag[:n]):
                                safe = min(safe, len(self._buf) - n)
                    if safe > 0:
                        self._cb(self._buf[:safe])
                        self._buf = self._buf[safe:]
                    return

                if earliest > 0:
                    self._cb(self._buf[:earliest])
                    self._buf = self._buf[earliest:]

                close_idx = self._buf.find(">")
                if close_idx == -1:
                    return  # incomplete tag — wait for more chunks
                tag_body = self._buf[:close_idx + 1]
                self._buf = self._buf[close_idx + 1:]
                if tag_body.rstrip().endswith("/>"):
                    pass  # self-closing <recall .../> — discard
                else:
                    self._suppressing = True  # opening <recalled> — suppress body

    def flush(self) -> None:
        if self._buf and not self._suppressing:
            self._cb(self._buf)
        self._buf = ""
        self._suppressing = False


# ---------------------------------------------------------------------------
# RecallPhases
# ---------------------------------------------------------------------------

class RecallPhases:
    """
    Two-phase recall orchestrator.

    Args:
        infer_fn:       Callable(messages, max_tokens, temperature, stop) -> str.
                        The caller (AgentKernel) provides its own client-wrapped
                        function so we never duplicate provider logic.
        decoder:        RecallDecoder instance wired to the live MemoryInterface.
        phase_r_tokens: Max completion tokens for Phase R (default 256).
        phase_r_temp:   Temperature for Phase R (default 0.2 — low, recall intent).
        enabled:        Master switch — when False, run() is a passthrough.
    """

    def __init__(
        self,
        infer_fn: Callable,
        decoder: Optional[RecallDecoder] = None,
        phase_r_tokens: int = 256,
        phase_r_temp: float = 0.2,
        enabled: bool = True,
        memory_interface: Optional[Any] = None,
        session_id: str = "default",
    ) -> None:
        self._infer = infer_fn
        self._decoder = decoder or RecallDecoder()
        self._phase_r_tokens = phase_r_tokens
        self._phase_r_temp = phase_r_temp
        self.enabled = enabled
        self._memory = memory_interface
        self._session_id = session_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        messages: List[Dict],
        chunk_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, List[ResolvedSpan]]:
        """
        Run Phase R → resolve → Phase A.

        Returns:
            (answer, resolved_spans)  — answer is the Phase A completion with
            provenance tags stripped. resolved_spans is the list of ResolvedSpans
            for logging, audit, and DER feedback.
        """
        if not self.enabled:
            answer = self._infer(messages, max_tokens=-1, temperature=0.6, stop=[])
            return answer, []

        # ── Iterative Phase R (multi-hop recall) ─────────────────────────
        # Each iteration resolves ops and feeds results into the next Phase R,
        # allowing the model to chain recall hops before answering.
        # Terminates early when: no ops emitted, all memory empty, all high-confidence,
        # or all emitted ops were already resolved in a prior iteration (M2 dedup).
        all_spans: List[ResolvedSpan] = []
        phase_r_output = ""
        cumulative_resolved = ""
        phase_r_ran = False
        seen_op_keys: set = set()  # M2: prevent re-resolving identical ops across iters

        for _iter in range(_MAX_RECALL_ITERS):
            phase_r_messages = self._build_phase_r_messages(messages, cumulative_resolved)
            try:
                phase_r_output = self._infer(
                    phase_r_messages,
                    max_tokens=self._phase_r_tokens,
                    temperature=self._phase_r_temp,
                    stop=_RECALL_STOP,
                )
                phase_r_ran = True
            except Exception as exc:
                logger.warning("[RecallPhases] Phase R iter %d failed (%s) — stopping recall", _iter, exc)
                break

            raw_ops = parse_recall_ops(phase_r_output)[:_MAX_OPS_PER_TURN]
            # M2: discard ops already resolved in a previous iteration
            fresh_ops = []
            for o in raw_ops:
                key = (o.op_type, frozenset(o.args.items()))
                if key not in seen_op_keys:
                    seen_op_keys.add(key)
                    fresh_ops.append(o)

            if not fresh_ops:
                logger.debug("[RecallPhases] iter %d: no new ops — stopping recall loop", _iter)
                break

            iter_spans: List[ResolvedSpan] = self._decoder.resolve_all(fresh_ops)
            logger.debug("[RecallPhases] iter %d: resolved %d ops: %s",
                         _iter, len(iter_spans), [f"{s.op.op_type}={s.status}" for s in iter_spans])
            all_spans.extend(iter_spans)

            # Stop iterating when memory is empty — no value in chaining on nothing
            if not any(s.confidence > 0.0 for s in iter_spans):
                break

            resolved_block = self._decoder.format_spans_for_phase_a(iter_spans)
            if resolved_block:
                cumulative_resolved += resolved_block + "\n"

            # Stop when all spans resolved with high confidence — no further hops needed
            if all(s.confidence >= 0.6 for s in iter_spans):
                break

        if not phase_r_ran:
            # Phase R never succeeded (all iterations threw) — fall back to direct.
            # M1: log a failure episode so pattern detection learns this task class breaks recall.
            logger.warning("[RecallPhases] Phase R never succeeded — falling back to direct")
            task_text = messages[-1].get("content", "") if messages else ""
            self._log_recall_episode(task_text=task_text, spans=[], answer_summary="[phase_r_failed]",
                                     outcome_type="failure")
            answer = self._infer(messages, max_tokens=-1, temperature=0.6, stop=[])
            return answer, []

        spans = all_spans

        # ── Phase A ──────────────────────────────────────────────────────
        phase_a_messages = self._build_phase_a_messages(messages, phase_r_output, spans)
        try:
            if chunk_callback:
                # Streaming: pass a provenance-stripping wrapper
                phase_a_output = self._infer_streaming(
                    phase_a_messages,
                    max_tokens=-1,
                    temperature=0.6,
                    stop=[],
                    chunk_callback=chunk_callback,
                )
            else:
                phase_a_output = self._infer(
                    phase_a_messages,
                    max_tokens=-1,
                    temperature=0.6,
                    stop=[],
                )
        except Exception as exc:
            logger.warning("[RecallPhases] Phase A failed (%s) — returning Phase R output", exc)
            return phase_r_output, spans

        answer = self._strip_provenance(phase_a_output)

        # ── Step 5: log recall trace as episode for recursive learning ────
        # Every Phase R / Phase A pair is an episode the brain can distil into
        # recall habits. Outcome starts as "partial" — caller updates to
        # hit/miss via update_recall_outcome() once the response is evaluated.
        self._log_recall_episode(
            task_text=messages[-1].get("content", "") if messages else "",
            spans=spans,
            answer_summary=answer[:200],
        )

        return answer, spans

    # ------------------------------------------------------------------
    # Message builders
    # ------------------------------------------------------------------

    def _build_phase_r_messages(
        self, messages: List[Dict], prior_resolved: str = ""
    ) -> List[Dict]:
        """
        Phase R: identical prefix to Phase A but adds a recall directive as the
        final user turn so the model knows to emit recall ops only.
        Prefix is preserved exactly so prompt caching fires on Phase A.

        prior_resolved: formatted resolved spans from earlier iterations, injected
                        so the model knows what was already recalled and can hop further.
        """
        base = messages[:-1] if messages else []
        last_user_content = ""
        if messages and messages[-1].get("role") == "user":
            last_user_content = messages[-1].get("content", "")

        prior_block = (
            f"\nAlready recalled:\n{prior_resolved.strip()}\n"
            if prior_resolved.strip()
            else ""
        )
        phase_r_directive = (
            f"{last_user_content}\n\n"
            "<recall_phase>\n"
            f"{prior_block}"
            "Emit any additional <recall .../> ops you need. "
            "End with </recall_phase>. Do not answer yet.\n"
            "</recall_phase>"
        )
        return base + [{"role": "user", "content": phase_r_directive}]

    def _build_phase_a_messages(
        self,
        messages: List[Dict],
        phase_r_output: str,
        spans: List[ResolvedSpan],
    ) -> List[Dict]:
        """
        Phase A: same prefix as Phase R, with an assistant turn that summarises
        the recall pass, then a reinforced user turn asking for the final answer.
        The cache-shared prefix means Phase A prefix is a cache hit.
        """
        resolved_block = self._decoder.format_spans_for_phase_a(spans)
        original_question = ""
        if messages and messages[-1].get("role") == "user":
            # Extract only the original question (before any <recall_phase> directive)
            raw = messages[-1].get("content", "")
            original_question = raw.split("\n\n<recall_phase>")[0].strip()

        # Build a compact recall summary for the assistant prefill
        if resolved_block:
            recall_summary = (
                "I checked my memory and found the following context:\n"
                f"{resolved_block}"
            )
        elif phase_r_output.strip():
            # Phase R had no resolvable ops — note it and move on
            recall_summary = "I checked my memory; no prior context found for this query."
        else:
            recall_summary = ""

        # Build Phase A message list
        # Structure: [system, ...history..., recall_assistant, final_user]
        base = messages[:-1] if messages else []
        result = list(base)

        if recall_summary:
            result.append({"role": "assistant", "content": recall_summary})

        # Final user turn: explicit answer request so model doesn't loop into more recall ops
        answer_cue = original_question if original_question else (
            messages[-1].get("content", "") if messages else ""
        )
        if answer_cue:
            result.append({
                "role": "user",
                "content": f"{answer_cue}\n\n(Answer directly now — no more <recall/> ops needed.)"
            })

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _infer_streaming(
        self,
        messages: List[Dict],
        max_tokens: int,
        temperature: float,
        stop: List[str],
        chunk_callback: Callable[[str], None],
    ) -> str:
        """
        Streaming wrapper that passes provenance-stripped deltas to chunk_callback.
        The filter handles <recalled>...</recalled> and <recall.../> spans that may
        arrive split across chunk boundaries.
        Falls back to sync infer if the underlying callable doesn't support streaming.
        """
        filt = _StreamingProvenanceFilter(chunk_callback)

        def _filtered_cb(delta: str) -> None:
            filt.feed(delta)

        try:
            import inspect
            sig = inspect.signature(self._infer)
            if "chunk_callback" in sig.parameters:
                result = self._infer(
                    messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stop=stop,
                    chunk_callback=_filtered_cb,
                )
                filt.flush()
                return result
        except Exception:
            pass
        # Fallback: sync then emit whole response as one delta
        result = self._infer(messages, max_tokens=max_tokens, temperature=temperature, stop=stop)
        clean = self._strip_provenance(result)
        if clean:
            chunk_callback(clean)
        return result

    def _log_recall_episode(
        self,
        task_text: str,
        spans: List[ResolvedSpan],
        answer_summary: str,
        outcome_type: str = "partial",  # M1: accept caller-specified outcome
    ) -> None:
        """
        Persist a recall trace as an episodic memory entry.

        C2: task_summary is prefixed with the op-type sequence so that different
        recall patterns for the same question embed distinctly and are stored as
        separate rows (not merged by the 0.95-threshold dedup).  Skill genesis
        therefore sees every unique op pattern, not just the first one.

        C1: the episode ID returned by store_episode is saved as _last_episode_id
        so update_recall_outcome can update the exact right row.

        Never raises.
        """
        if self._memory is None:
            return
        try:
            from backend.memory.episodic import Episode
            ops_trace = json_safe([
                {"op": s.op.op_type, "args": s.op.args,
                 "confidence": s.confidence, "status": s.status}
                for s in spans
            ])
            # C2: unique prefix per op pattern prevents dedup merging across patterns
            ops_key = ":".join(s.op.op_type for s in spans) if spans else "empty"
            prefix = f"[recall:{ops_key}] "
            task_summary = prefix + task_text[:200 - len(prefix)]

            ep = Episode(
                session_id=self._session_id,
                task_summary=task_summary,
                full_content=(
                    f"[recall_trace]\n"
                    + "\n".join(
                        f"  {s.op.op_type}({s.op.args}) → {s.status} conf={s.confidence:.2f}"
                        for s in spans
                    )
                    + f"\n[answer]\n{answer_summary}"
                ),
                tool_sequence=ops_trace,
                outcome_type=outcome_type,
                source_channel="recall",
            )
            # C1: capture the ID so update_recall_outcome targets the exact row
            self._last_episode_id: Optional[str] = self._memory.store_episode(ep)
        except Exception as exc:
            logger.debug("[RecallPhases] episode logging failed: %s", exc)

    def update_recall_outcome(self, outcome: str) -> None:
        """
        Update the outcome of the most-recently logged recall episode.
        outcome: 'success' | 'failure' | 'partial'

        C1: updates by the stored episode ID, never by similarity search,
        so it cannot accidentally update an unrelated episode.
        Never raises.
        """
        if self._memory is None:
            return
        try:
            ep_id = getattr(self, "_last_episode_id", None)
            if not ep_id:
                return
            self._memory.episodic.db.execute(
                "UPDATE episodes SET outcome_type=? WHERE id=?",
                (outcome, ep_id),
            )
            self._memory.episodic.db.commit()
            self._last_episode_id = None  # clear so stale ID is never reused
        except Exception as exc:
            logger.debug("[RecallPhases] outcome update failed: %s", exc)

    @staticmethod
    def _strip_provenance(text: str) -> str:
        """Remove <recalled .../> and </recalled> wrapper tags from user-visible output."""
        import re
        # Strip full <recalled ...>...</recalled> blocks (the resolved spans)
        text = re.sub(r'<recalled\b[^>]*>.*?</recalled>', '', text, flags=re.DOTALL)
        # Strip bare <recalled .../> self-closing
        text = re.sub(r'<recalled\b[^/]*/>', '', text)
        # Strip <recall .../> ops that leaked into Phase A
        text = re.sub(r'<recall\b[^/]*/>', '', text)
        # Clean up leftover <thinking>...</thinking> that contains only recall artefacts
        text = re.sub(r'<thinking>\s*</thinking>', '', text, flags=re.DOTALL)
        return text.strip()


# ---------------------------------------------------------------------------
# Standalone infer_fn builder
# For testing and for cases where a simple OpenAI-compat client is available.
# ---------------------------------------------------------------------------

def make_openai_compat_infer(client, model: str):
    """
    Build an infer_fn compatible with RecallPhases from an OpenAI-compat client.

    Args:
        client:  openai.OpenAI (or compatible) instance
        model:   model name string

    Returns:
        Callable(messages, max_tokens, temperature, stop) -> str
    """
    def infer_fn(
        messages: List[Dict],
        max_tokens: int = -1,
        temperature: float = 0.6,
        stop: Optional[List[str]] = None,
        chunk_callback: Optional[Callable] = None,
    ) -> str:
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens > 0:
            kwargs["max_tokens"] = max_tokens
        if stop:
            kwargs["stop"] = stop

        if chunk_callback:
            kwargs["stream"] = True
            resp = client.chat.completions.create(**kwargs)
            full = ""
            for chunk in resp:
                delta = chunk.choices[0].delta.content or ""
                full += delta
                if delta:
                    chunk_callback(delta)
            return full
        else:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""

    return infer_fn
