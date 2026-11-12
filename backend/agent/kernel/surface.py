# Moved from backend/agent/agent_kernel.py by scripts/kernel_split_check.py move.
# Bodies are byte-identical to the originals (guard: kernel_split_check.py manifest --check).
from __future__ import annotations

import re
import os
from backend.agent.mcm_protocol.actions.pacman_fragment import is_external_tool
from backend.agent.call_context import (
    CallClass,
    set_call_class,
    restores_call_class,
)
from backend.agent import write_counters as _write_counters
from backend.agent import row_sequence as _row_sequence
from typing import Any, Dict, Optional, List, Callable, Tuple, Sequence
import json
from backend.agent.kernel.base import (
    _emit_event,
    _step_calls,
    _step_tool,
    logger,
)


def _stamp_row_seq(steps: list, conversation_id: Optional[str]) -> list:
    """GROUND TRUTH T29 (REQ-17 AC1/AC6): give every planner row its stable,
    backend-owned ordering key.

    Row identity is the step id, so re-emitting a row (revision, graft, split)
    returns the key it already has and the card never renumbers. A row whose id
    cannot be determined gets seq 0 and is COUNTED - per REQ-17 AC6 a missing
    key is a recorded contract violation, never a silent sort-to-the-end.

    Never raises: an ordering key that could break a task:start emit would be
    worse than the disorder it fixes.
    """
    try:
        if not isinstance(steps, list):
            return steps
        out = []
        for s in steps:
            if not isinstance(s, dict):
                out.append(s)
                continue
            rid = s.get("id") or s.get("step_id")
            seq = _row_sequence.seq_for(conversation_id, rid)
            if not seq:
                _write_counters.bump("row_seq.missing_on_planner_row")
            # Copy rather than mutate: callers reuse their step dicts, and a
            # payload builder that mutates its input is its own defect class.
            out.append({**s, "seq": seq})
        return out
    except Exception:
        _write_counters.bump("row_seq.stamp_failed")
        return steps


class SurfaceMixin:
    @staticmethod
    def _is_document_content(text: str) -> bool:
        """Heuristic: True if *text* looks like a document/code excerpt rather than
        a conversational reply.  Document content gets summarised for TTS;
        conversational replies are spoken verbatim.
        """
        import re

        lines = text.splitlines()
        # Markdown headings (# / ## / etc.)
        if any(re.match(r"^#{1,6}\s", ln) for ln in lines):
            return True
        # Fenced code blocks (at least one opening fence)
        if text.count("```") >= 2:
            return True
        # Three or more bullet / numbered list items
        list_items = sum(1 for ln in lines if re.match(r"^\s*[-*â€¢]\s|^\s*\d+\.\s", ln))
        if list_items >= 3:
            return True
        # Long, dense multi-paragraph text (>10 non-empty lines, avg >8 words/line)
        non_empty = [ln for ln in lines if ln.strip()]
        if len(non_empty) > 10:
            avg_words = sum(len(ln.split()) for ln in non_empty) / len(non_empty)
            if avg_words > 8:
                return True
        return False

    def spoken_brief_needed(self, full_response: str) -> bool:
        """True when an answer is long enough that speaking its FIRST SENTENCE
        misrepresents it (REQ-28 AC1).

        Counts the same way prepare_spoken_text does -- after code and markdown
        are stripped -- so the two agree about what "long" means.
        """
        if not full_response:
            return False
        try:
            import re as _re

            cleaned = _re.sub(r"```[\s\S]*?```", "", full_response)
            cleaned = _re.sub(r"`[^`]+`", "", cleaned)
            return len(cleaned.split()) > self.SPOKEN_BRIEF_WORD_THRESHOLD
        except Exception:  # noqa: BLE001 -- never fail a turn over TTS shape
            return False

    def stream_spoken_brief(
        self,
        full_response: str,
        on_sentence: Callable[[str], None],
        max_words: int = 70,
    ) -> str:
        """Generate a spoken brief of `full_response`, one SENTENCE at a time.

        REQ-28 AC1/AC3/AC4. Every complete sentence is handed to `on_sentence`
        the moment it finishes generating, rather than at the end. The caller
        feeds those sentences into the TTS queue, so audio starts on sentence
        one while the rest is still being written -- without that, a brief
        generated after the body would land noticeably late and out of step
        with the text the user is already reading.

        Returns the full brief, or "" on any failure. Never raises: the caller
        falls back to prepare_spoken_text, and a silent turn is worse than a
        blunt one.
        """
        if not full_response or self._router is None:
            return ""

        _buf: list = []
        _emitted: list = []
        _pending = {"text": ""}

        def _on_chunk(chunk: str) -> None:
            if not chunk:
                return
            _buf.append(chunk)
            _pending["text"] += chunk
            # Flush on sentence boundaries only. A half sentence spoken aloud
            # is worse than a slightly later one, and the TTS queue batches by
            # sentence anyway.
            while True:
                _cut = -1
                for _mark in (". ", "! ", "? ",
                              "." + '\n', "!" + '\n', "?" + '\n'):
                    _i = _pending["text"].find(_mark)
                    if _i != -1 and (_cut == -1 or _i < _cut):
                        _cut = _i
                if _cut == -1:
                    break
                _sentence = _pending["text"][: _cut + 1].strip()
                _pending["text"] = _pending["text"][_cut + 2 :]
                if _sentence:
                    _emitted.append(_sentence)
                    try:
                        on_sentence(_sentence)
                    except Exception as _cb_exc:  # noqa: BLE001
                        logger.debug("[brief] sentence callback failed: %s", _cb_exc)

        _messages = [
            {
                "role": "system",
                "content": (
                    "You write the SPOKEN version of an answer the user is "
                    "already reading. Give the substance and the CONCLUSION, "
                    f"not the opening. Under {max_words} words, plain "
                    "conversational sentences, no markdown, no lists, no code, "
                    "no preamble such as 'here is a summary'. Speak as the "
                    "assistant continuing the conversation."
                ),
            },
            {"role": "user", "content": full_response[:8000]},
        ]
        try:
            from backend.voice.tts_normalizer import normalize_text

            # Capture reasoning SEPARATELY. Some models (observed live
            # 2026-08-26 with command-a-plus-05-2026) stream everything through
            # `reasoning_content` and leave `content` empty; the dispatcher's
            # reasoning fallback then returns the RAW THINKING as the answer,
            # deliberately skipping preamble stripping. A brief built from that
            # is the model's meta-commentary -- measured: "The user gave a
            # description of WebSocket handshake. The instruction: 'You write
            # the SPOKEN version...'" -- i.e. our own prompt read back aloud.
            _reasoning_seen: list = []

            def _on_reasoning(chunk: str) -> None:
                if chunk:
                    _reasoning_seen.append(chunk)

            _text, _thinking, _ = self._router.generate(
                "reasoning", _messages, tools=None,
                max_tokens=max(120, max_words * 2), temperature=0.2,
                chunk_callback=_on_chunk,
                reasoning_callback=_on_reasoning,
            )
            # Whatever the stream did not end on a boundary is still a sentence.
            _tail = (_pending["text"] or "").strip()
            if _tail:
                _emitted.append(_tail)
                try:
                    on_sentence(_tail)
                except Exception:  # noqa: BLE001
                    pass
            _full = " ".join(_emitted).strip() or (_text or "").strip()
            # Reject a "brief" that is really the reasoning fallback. Nothing
            # arrived on the CONTENT stream and the returned text matches what
            # came back as reasoning -> this is thinking, not an answer. Speak
            # the truncation instead; a blunt spoken line beats reading our own
            # system prompt to the user.
            _reasoning_text = "".join(_reasoning_seen).strip()
            if not _emitted and _reasoning_text and _full[:120] == _reasoning_text[:120]:
                logger.warning(
                    "[brief] discarded reasoning-fallback output (%d chars); "
                    "the model answered via reasoning_content, not content",
                    len(_full),
                )
                return ""
            # Whether the brief actually STREAMED decides whether audio can
            # start before generation ends. A router that returns the whole
            # string without invoking the chunk callback still produces a
            # correct brief, but the early-audio property is lost -- and that
            # is invisible unless it is stated.
            logger.info(
                "[brief] streamed=%s sentences=%d chars=%d",
                bool(_emitted), len(_emitted), len(_full or ""),
            )
            try:
                self._accrue_tokens(
                    _full, getattr(self._router, "last_usage", None),
                    source="stream_spoken_brief",
                )
            except Exception:  # noqa: BLE001
                pass
            return normalize_text(_full) if _full else ""
        except Exception as _exc:  # noqa: BLE001
            logger.warning("[brief] spoken brief generation failed: %s", _exc)
            return ""

    def prepare_spoken_text(self, full_response: str, user_message: str = "") -> str:
        """
        Returns ONLY the text that should be sent to the TTS engine (F5-TTS).
        Full response is ALWAYS sent separately via text_response.

        Conversational-first design: IRIS speaks a short, natural summary.
        The full response is always visible in ChatView â€” voice is a companion,
        not a reader.  Thresholds keep spoken output under ~20-25 seconds.

        No second LLM call â€” direct text processing keeps first-audio latency
        to synthesis time only (~1-2s warm, ~40s cold F5-TTS).

        Rules (applied after code/markdown is stripped):
          â‰¤ 60 words  â†’ spoken verbatim (always â€” short answers, confirmations)
          61-120 words, conversational â†’ spoken verbatim (user asked, answer given)
          61-120 words, document-like â†’ first sentence + "in the chat window"
          > 120 words â†’ first sentence to boundary (â‰¤ 60 words) + "in the chat window"
        """
        import re as _re
        from backend.voice.tts_normalizer import normalize_text

        # Strip code fences and their content entirely â€” code is unreadable aloud
        cleaned = _re.sub(r"```[\s\S]*?```", "", full_response)
        # Strip inline code
        cleaned = _re.sub(r"`[^`]+`", "", cleaned)
        # Strip markdown headers (#, ##, etc.)
        cleaned = _re.sub(r"^#{1,6}\s+", "", cleaned, flags=_re.MULTILINE)
        # Strip bold/italic markers
        cleaned = _re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", cleaned)
        # Strip bullet dashes/asterisks at line start
        cleaned = _re.sub(r"^\s*[-*â€¢]\s+", "", cleaned, flags=_re.MULTILINE)
        # Collapse whitespace
        cleaned = " ".join(cleaned.split())

        had_code = "```" in full_response
        is_doc = self._is_document_content(full_response)
        word_count = len(cleaned.split())

        # Short response â€” always spoken verbatim (~0-15s at 150 wpm)
        if word_count <= 60:
            spoken = normalize_text(cleaned)
            if had_code:
                spoken += " The full code is in the chat window."
            return spoken

        # Medium conversational response â€” spoken in full if not document-like (~15-25s)
        if word_count <= 120 and not is_doc and not had_code:
            return normalize_text(cleaned)

        # Document, code, or long response â€” speak first sentence(s) up to 60 words
        words = cleaned.split()
        truncated = " ".join(words[:60])
        # Walk back to last sentence boundary to avoid mid-sentence cut
        last_boundary = max(
            truncated.rfind(". "),
            truncated.rfind("! "),
            truncated.rfind("? "),
        )
        if last_boundary > 25:
            truncated = truncated[: last_boundary + 1]

        spoken = normalize_text(truncated)
        if had_code:
            spoken += " The full code is in the chat window."
        else:
            spoken += " Full response in the chat window."
        return spoken

    def _finalize_response(
        self, display: str, spoken: Optional[str] = None
    ) -> str:
        """Single exit for :meth:`_process_structured_response`.

        THE RULE (user, 2026-08-16): the FULL text goes to the thread, the
        spoken line goes to TTS, and a card is only for a stored artifact.
        Every return in ``_process_structured_response`` goes through here, so
        the rule is enforced in ONE place instead of at nine separate returns.
        Three of those returns had each caused the same truncation bug in turn
        (``return speak``; the card branch owning the content; the speak-tool
        ``spoken`` field) â€” the shape, not the individual returns, was the bug.

        ``spoken`` is the agent's own TTS line when it supplied one. It is
        always assigned (empty when absent) so a previous turn's line can never
        leak into this one.
        """
        # The prompt's ANSWER: format label, copied by the model, never reaches
        # the user: one leading label is dropped from the display text and the
        # spoken line here â€” the single exit every reply path goes through
        # (recorded live 2026-10-06, test_answer_marker_strip_contract).
        from backend.agent.artifact_policy import strip_leading_answer_marker

        display = strip_leading_answer_marker(display or "")
        self._last_spoken_text = strip_leading_answer_marker((spoken or "").strip())
        # D3 (2026-10-31): a memory deletion is only true when a tool performed
        # it this turn. The measured failure: "Done - I've wiped your locker
        # code from memory" with the pin still in the store and no tool event.
        # The guard corrects the display text AND the spoken line, so the user
        # never hears a deletion that did not happen.
        try:
            from backend.agent.artifact_policy import (
                enforce_memory_deletion_claims,
            )

            _bridge = getattr(self, "_tool_bridge", None)
            _delete_ran = bool(
                _bridge is not None
                and _bridge.forget_ran_since(
                    getattr(self, "_turn_session_id", None) or "",
                    getattr(self, "_turn_started_monotonic", 0.0),
                )
            )
            _display_fixed, _spoken_fixed, _claims = (
                enforce_memory_deletion_claims(
                    display,
                    self._last_spoken_text,
                    delete_ran=_delete_ran,
                )
            )
            if _claims:
                logger.warning(
                    "[ClaimGuard] turn %s claimed a memory deletion no tool "
                    "performed; rewrote %d sentence(s)",
                    getattr(self, "_turn_session_id", None),
                    _claims,
                )
                display, self._last_spoken_text = _display_fixed, _spoken_fixed
        except Exception as _claim_exc:  # noqa: BLE001 — never block a reply
            logger.debug("[ClaimGuard] skipped: %s", _claim_exc)
        if display or self._last_spoken_text:
            # Taxonomy DELIVERY: the reply reached the user (lengths only, never the text).
            _emit_event(
                self, "ANSWER_GIVEN", thread_id=getattr(self, "_turn_session_id", None),
                payload={"display_chars": len(display or ""),
                         "spoken_chars": len(self._last_spoken_text)},
            )
        return display or ""

    @staticmethod
    def _unwrap_tool_envelope(response: str) -> Tuple[str, Optional[str]]:
        """Return ``(display_text, spoken_line)`` for a tool-result envelope.

        The DER path can hand back a TOOL RESULT as its final output. The speak
        tool returns ``{"status": "ok", "utterance_id": ..., "spoken": text}``
        â€” JSON with neither ``speak`` nor ``show``, so
        ``parse_structured_response`` reports it as unstructured.

        When the envelope also carries a written answer (a longer
        text/content/response field), that is the display text and ``spoken``
        stays the TTS line. Otherwise the spoken text is both â€” it is the only
        text there is, and it must be shown in full.

        Returns ``(response, None)`` when this is not a tool envelope, so the
        caller falls through to the plain-text path unchanged.
        """
        try:
            parsed = json.loads(response)
        except (json.JSONDecodeError, TypeError, ValueError):
            return (response, None)
        if not isinstance(parsed, dict) or "spoken" not in parsed:
            return (response, None)
        spoken = parsed.get("spoken")
        if not isinstance(spoken, str):
            return (response, None)
        display = spoken
        for _key in ("text", "content", "response", "display", "answer"):
            _val = parsed.get(_key)
            if isinstance(_val, str) and len(_val.strip()) > len(display.strip()):
                display = _val
        return (display, spoken)

    def _process_structured_response(
        self,
        response: Optional[str],
        turn_id: Optional[str] = None,
        conversation_id: str = "default",
    ) -> str:
        """Apply the Issue C.1 speak/show contract to a final LLM response.

        ONE RULE, ONE EXIT (2026-08-17). Returns the text for the thread and
        assigns the TTS line to ``self._last_spoken_text``; a card renders only
        for a stored artifact. Every exit goes through
        :meth:`_finalize_response` â€” three separate returns each caused the same
        truncation in turn, so the exits are now consolidated rather than
        patched individually.

        Every path, and what it returns:

        ==============================  ==========================  ===========
        input                           display (return)            card
        ==============================  ==========================  ===========
        empty                           ``""``                      no
        tool envelope (``spoken``)      written answer, else        no
                                        the spoken text IN FULL
        plain text                      the text unchanged          no
        ``show`` revising a document    ``""``                      revised
        ``show`` + ``speak``            the ``speak`` line          yes
        ``show``, card emit failed      the full show content       no
        ``show`` with no ``speak``      supportive excerpt          yes
        ==============================  ==========================  ===========

        The distinction that drives it is decided by the AGENT, not inferred
        here: ``show`` is the older spelling of ``create_artifact`` ("this is
        something to keep â€” store it"), so it converts to the same call, renders
        a card and the thread keeps the spoken line. Everything else is
        conversation and goes to the thread as text, in full, however long. The
        [RESPONSE FORMAT] prompt in :meth:`_build_system_prompt` is the other
        half of this contract; the two must be read together.

        Content lives in exactly one place. With a card, that place is the card
        and the document store. Without one, it is the chat message â€” which is
        why no path here may shorten it.
        """
        if not response:
            return response or ""

        # Reset the per-response render flag; create_artifact sets it True when a
        # DOCUMENT_RENDER is emitted. It decides the bubble below (speak when a
        # card carries the content, the full text when it did not).
        self._last_render_emitted = False
        # Reset the per-response spoken line. Set at every exit by
        # _finalize_response, so a stale value from a previous turn can never
        # be spoken even on the paths that supply no spoken line.
        self._last_spoken_text = ""

        from backend.agent.structured_response import parse_structured_response

        speak, show = parse_structured_response(response)

        # â”€â”€ Tool-result envelope â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # ROOT CAUSE of the last truncation (2026-08-16, fixed 2026-08-17):
        # a speak-tool result reaches here as {"status", "utterance_id",
        # "spoken"}. It has neither `speak` nor `show`, so it fell into the
        # plain-text branch below and _supportive_text excerpted the RAW JSON â€”
        # an 887-char answer displayed and persisted as 55 chars.
        #
        # A handler for the "spoken" field DID exist, but it sat AFTER the
        # `show is None` return, so it could never run. That is why the earlier
        # spot-fix appeared to "return raw JSON": the branch it patched was
        # dead. Unwrapping HERE â€” before any return â€” is the fix. The dead
        # branch is gone.
        # Internal narration never reaches the user, on any lane. A leading
        # planning paragraph is dropped when a real answer follows it â€” the
        # thread text AND a card body both (a report card used to open with
        # "The tool only returned a partial draft; it omitted full sections ...",
        # and a failed turn showed "Need to call read_file ... Let's run
        # read_file." as if it were an answer). Owner, 2026-09-25.
        from backend.agent.artifact_policy import strip_leading_narration

        response = strip_leading_narration(response or "")
        if isinstance(show, dict) and isinstance(show.get("content"), str):
            show = {**show, "content": strip_leading_narration(show["content"])}

        if speak is None and show is None:
            _display, _spoken = self._unwrap_tool_envelope(response)
            if _spoken is not None:
                return self._finalize_response(_display, _spoken)

        if show is None:
            # â”€â”€ Plain-text response â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # A PLAIN REPLY IS THE ANSWER (reply-surface audit, Phase A). No
            # DOCUMENT_RENDER is emitted on this path - ever: not for length, not
            # for structure, not for a document-shaped body, and not because the
            # ask used a build verb. The 2026-07-31 length/zone auto-render
            # fabricated cards for long answers AND excerpted the bubble (deleted
            # 2026-09-21); the 2026-09-25 fallback mint (an artifact ask + a
            # document-shaped body -> a card made after the fact) and its
            # `show_omitted_on_artifact` calibration log are deleted with this
            # change: a card now appears only when the model CALLS
            # create_artifact (or sends the older `show` payload, which
            # converts to the same call). The text goes to the thread unchanged.
            self._log_surface(
                turn_id=turn_id,
                lane="plain",
                had_show=False,
                bubble_source="full_text",
                card_suppressed_reason="no_show_payload",
            )
            # T4 (REQ-8): pass `speak` through so the TTS lane is the agent's
            # own line when it supplied one; the gateway's prepare_spoken_text
            # fallback (:4036) covers the common plain case.
            return self._finalize_response(response, speak)

        # â”€â”€ `show` is the older spelling of create_artifact â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # A `show` payload converts to the SAME call the tool makes, so a card
        # has one door: create_artifact stores on the real DocumentDataStore and
        # emits DOCUMENT_RENDER with title, kind, summary, language, format,
        # content, document_id, turn_id, card_id, conversation_id and trust.
        # `show` is a card by definition (the model chose to keep it): there is
        # no body-shape demotion any more, and a `show` with no title or summary
        # gets them derived below rather than rendering a label-less card.
        #
        # An empty body, a tool-result envelope, or a failed emit leaves
        # `_last_render_emitted` False, so the full show content falls back into
        # the thread (it is the only copy then) - the answer is never lost.
        from backend.agent.artifact_policy import (
            ARTIFACT_KINDS,
            card_title_from_content,
            first_sentence,
            kind_for_show_format,
        )

        _show_content = show.get("content", "") or ""
        _show_title = str(show.get("title") or "").strip()
        if not _show_title:
            _show_title = card_title_from_content(_show_content)
            if _show_title == "Document":
                # Nothing in the body names it; the ask does, in short form.
                _show_title = (
                    first_sentence(getattr(self, "_current_task_text", "") or "", 60)
                    or _show_title
                )
        _show_kind = str(show.get("kind") or "").strip().lower()
        if _show_kind not in ARTIFACT_KINDS:
            _show_kind = kind_for_show_format(show.get("format"))
        _show_summary = (
            str(show.get("summary") or "").strip()
            or first_sentence(speak or "", 140)
            or _show_title
        )
        _show_extra = {
            k: v
            for k, v in show.items()
            if k not in ("title", "kind", "summary", "content", "document_id", "language")
        }
        _made = self.create_artifact(
            title=_show_title,
            kind=_show_kind,
            summary=_show_summary,
            content=_show_content,
            language=show.get("language"),
            # Phase 4 (chat-card-redesign): a `show` carrying an existing
            # document_id revises that document in place (bumped revision +
            # updated:True) instead of rendering a new card.
            artifact_id=show.get("document_id"),
            turn_id=turn_id,
            conversation_id=conversation_id,
            extra=_show_extra,
        )
        if _made.get("revised"):
            # The card was revised in place - it owns the content. The agent's
            # spoken line still reaches TTS.
            return self._finalize_response("", speak)

        if speak is not None:
            # Issue C.2: also deliver the spoken summary to external channels
            # (Telegram, MCP).  Local TTS already handles it via sentence_queue,
            # so we only forward externally here (no second local utterance).
            try:
                from backend.agent.tools.speak_broadcaster import get_speak_broadcaster

                get_speak_broadcaster().forward_external(speak)
            except Exception as exc:
                logger.warning("[AgentKernel] speak broadcast failed: %s", exc)
            # CONTENT LIVES IN EXACTLY ONE PLACE (2026-08-16, user rule).
            #
            # A document render is for an ARTIFACT â€” search results, generated
            # markdown, a plan, code â€” something stored in the document store to
            # be opened again later. When one is rendered, the card owns the
            # content and the chat keeps the agent's conversational line, so the
            # thread is not a wall of duplicated markdown.
            #
            # When NO card was rendered, the chat message is the only place the
            # answer exists, so it must carry the FULL text. Returning `speak`
            # unconditionally (the old behaviour) is what silently discarded a
            # 1492-char answer down to a 201-char summary.
            #
            # `_last_render_emitted` is set at the actual emit above, so this
            # asks "did a card really render?" rather than assuming one did.
            # Bubble = the agent's `speak` line (specs/reply-surface-contract
            # REQ-3 / T3): the card owns the content, the bubble carries the
            # conversational line â€” never an excerpt of the card body. Only
            # when the emit itself failed does the full show content fall
            # back into the thread (it is the only copy then).
            if getattr(self, "_last_render_emitted", False):
                self._log_surface(
                    turn_id=turn_id,
                    lane="card_plus_summary",
                    had_show=True,
                    bubble_source="speak",
                )
                return self._finalize_response(speak or "", speak)
            self._log_surface(
                turn_id=turn_id,
                lane="card",
                had_show=True,
                bubble_source="full_text",
            )
            return self._finalize_response(
                (show.get("content") or "").strip() or speak, speak
            )
        # speak is None and a `show` payload exists. The card carries the
        # content; returning the raw JSON here would speak it and show it as
        # the assistant's message.
        #
        # The speak-tool "spoken" handler that used to sit here was DEAD CODE â€”
        # reaching it required `show` to be a dict AND the same JSON to carry a
        # top-level "spoken", which the speak tool never produces. Its real
        # payload is unwrapped at the top of this function now.
        #
        # REQ-3 / T3 (reply-surface-contract): `_supportive_text` is used ONLY
        # when no `speak` line exists. With a card rendered, the bubble gets a
        # short supportive excerpt so the thread is not empty; with the emit
        # failed, the full show content reaches the thread instead.
        if getattr(self, "_last_render_emitted", False):
            self._log_surface(
                turn_id=turn_id,
                lane="card_plus_summary",
                had_show=True,
                bubble_source="derived_excerpt",
            )
            return self._finalize_response(
                self._supportive_text(show.get("content") or "")
            )
        self._log_surface(
            turn_id=turn_id,
            lane="card",
            had_show=True,
            bubble_source="full_text",
        )
        return self._finalize_response(show.get("content") or "")

    # â”€â”€ W4: canonical document-data storage â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _get_document_store(self):
        """Return the DocumentDataStore for this kernel's memory DB, or None."""
        try:
            from backend.agent.document_store import DocumentDataStore

            return DocumentDataStore.get_for(self._memory_interface)
        except Exception as exc:
            logger.warning("[AgentKernel] document store unavailable: %s", exc)
            return None

    @staticmethod
    def _extract_sources_from_raw(content: str) -> list:
        """Extract {url,title} sources from a raw crawler_query blob (REQ-5).

        Tolerant of shape: prefers '--- Source: <url> ---' markers (observed in
        live crawler output) and falls back to any http(s) URL. Returns [] on
        failure â€” never raises into the store path (design risk: malformed JSON
        -> empty sources, store still succeeds).
        """
        import re

        sources: list = []
        try:
            if not content:
                return sources
            seen: set = set()
            for m in re.finditer(r"---?\s*Source:\s*(\S+)\s*---?", content):
                url = m.group(1)
                if url.startswith("http") and url not in seen:
                    seen.add(url)
                    sources.append({"url": url, "title": url})
            if sources:
                return sources
            for m in re.finditer(r"https?://[^\s\"'<>]+", content):
                url = m.group(0)
                if url not in seen:
                    seen.add(url)
                    sources.append({"url": url, "title": url})
        except Exception:
            pass
        return sources

    @staticmethod
    def _apply_trust_ceiling(trust: str, content_origin: str) -> str:
        """REQ-18 AC3: vision-derived content is never stored above the trust of
        equivalent crawled web content (which is ``untrusted``).

        Extracted as a pure function so the ceiling is directly assertable and
        so there is exactly ONE place that decides it. A caller passing
        ``trust="trusted"`` for vision output is downgraded, not honoured â€”
        provenance beats the caller's claim.
        """
        if content_origin in ("vision", "reconciled") and trust != "untrusted":
            logger.info(
                "[AgentKernel] document_data trust ceiling: origin=%s trust=%s "
                "-> untrusted (REQ-18 AC3)", content_origin, trust,
            )
            return "untrusted"
        return trust

    def _store_document_data(
        self,
        document_id: str,
        show: dict,
        trust: str,
        turn_id: Optional[str],
        conversation_id: str,
        card_id: Optional[str] = None,
    ) -> None:
        """Persist a document's canonical DATA (not its render) keyed by document_id.

        Two coordinated homes (plan W4):
          * Mycelium (episodic.fragment_and_store) â€” semantically retrievable
            later via mcm_recall / pacman_recall, scoped by zone (trust).
          * Immortus 4D chain (immortus_chain_append) â€” placed in the reasoning
            trajectory via coords_from->coords_to so it "finds its place".

        The rendered ``content`` is only a view derived on demand; the stored
        source of truth is the canonical {format, content, alternatives}.
        All failures are swallowed â€” storage must never block the render.
        """
        import json

        fmt = show.get("format", "markdown")
        content = show.get("content", "")
        # W5 (G1): store the actual rendered content of each alternative format.
        # The LLM may emit `variants: {format: content}` in one response; we
        # always also register the primary format's content as a variant so a
        # reformat to the original format is deterministic too.
        variants = dict(show.get("variants", {}) or {})
        variants[fmt] = content

        # REQ-18 AC2/AC3: provenance travels with the content, and vision-derived
        # content is never stored at a HIGHER trust than equivalent crawled web
        # content. The ceiling is enforced HERE, at the single choke point every
        # document passes through, rather than at each call site â€” one guard
        # cannot be forgotten by a future caller. ContentOrigin previously lived
        # only inside frame_extraction.py and never reached the store at all, so
        # vision output was indistinguishable from DOM text once persisted.
        content_origin = str(show.get("content_origin") or "crawl")
        trust = self._apply_trust_ceiling(trust, content_origin)

        canonical = {
            "document_id": document_id,
            "format": fmt,
            "content": content,
            "variants": variants,
            "alternatives": show.get("alternatives", []),
            "trust": trust,
            "content_origin": content_origin,
            "conversation_id": conversation_id,
            "turn_id": turn_id,
        }
        canonical_text = json.dumps(canonical, ensure_ascii=False)
        zone = "reference" if trust == "untrusted" else "trusted"

        # â”€â”€ Immortus 4D chain coordinate (computed early; used by W8 seed + Immortus) â”€â”€
        # coords_from = the agent's actual reasoning-state coordinate at the
        # moment this document was produced (sourced from the Caducean
        # trajectory recorder). This is what lets W7/O1 do trajectory-proximity
        # recall ("data gathered while thinking like this") instead of a flat
        # append. None (NULL on the row) if no trajectory has been recorded yet
        # (REQ-4 AC4.1: never "" as a stand-in for unknown).
        coords_from: Optional[str] = None
        try:
            from backend.agent.caducean_trajectory import (
                format_coords,
                get_trajectory_recorder,
            )

            # REQ-4: Primary lookup = recording session id (self.session_id);
            # fallback = conversation_id (REST path where they coincide).
            # Use getattr for safety (test-only __new__ paths may skip __init__).
            _lookup_id = getattr(self, "session_id", None) or conversation_id
            _coord = get_trajectory_recorder(
                self._memory_interface
            ).get_latest_coordinate(_lookup_id)
            # Fallback: if primary didn't match and differs from conversation_id,
            # try conversation_id directly (REQ-4 AC3 / REST-path).
            if _coord is None and _lookup_id != conversation_id:
                _coord = get_trajectory_recorder(
                    self._memory_interface
                ).get_latest_coordinate(conversation_id)
            if _coord is not None:
                coords_from = format_coords(
                    _coord["x"], _coord["y"], _coord["xi"], _coord["u"]
                )
        except Exception as exc:
            logger.warning("[AgentKernel] document_data coord lookup failed: %s", exc)

        # â”€â”€ Wave 0/1 provenance linkage (REQ-5/REQ-13) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Persist source_document_id / sources / har_path so documents rehydrate
        # with provenance. Tolerant of shape: malformed input -> empty sources,
        # store still succeeds (design risk).
        source_document_id = show.get("source_document_id")
        sources = show.get("sources")
        har_path = show.get("har_path")
        # Provenance linkage (2026-10-08): where the fetched EVIDENCE actually
        # lives. `har_path` is NULL for every live crawl - measured: 0 "HAR
        # write" in the log that contains a successful crawl - because the live
        # path writes per-page captures under data/captures/<job_id>/ instead
        # (capture_store). The crawl result ALREADY carries `job_id`
        # (tool_bridge: "The returned dict carries job_id"), and it is the same
        # id the HAR filename would use, so the path is DERIVED here rather than
        # threaded through another layer. Linking to the captures already on
        # disk - never writing a second copy of the same evidence.
        capture_path = show.get("capture_path")
        if not capture_path:
            _cap_job = show.get("job_id")
            if _cap_job:
                try:
                    from backend.crawler.capture_store import (
                        _captures_dir,
                        _safe_job,
                    )

                    capture_path = os.path.join(
                        _captures_dir(), _safe_job(str(_cap_job))
                    )
                except Exception:  # noqa: BLE001 â€” linkage is best-effort
                    capture_path = None
        source_tool = show.get("source_tool")

        if source_tool == "crawler_query":
            if fmt == "json":
                # Raw crawler_query result row: extract sources from content.
                if sources is None:
                    sources = self._extract_sources_from_raw(content)
            else:
                # Synthesized show reusing a crawl: link to the most recent raw
                # JSON row in this conversation and inherit its provenance.
                if not source_document_id:
                    try:
                        store0 = self._get_document_store()
                        if store0 is not None:
                            raw_rows = store0.list_for_conversation(
                                conversation_id, metadata_only=False
                            )
                            raw = next(
                                (r for r in reversed(raw_rows)
                                 if r.get("format") == "json"),
                                None,
                            )
                            if raw is not None:
                                source_document_id = raw.get("document_id")
                                if not sources and raw.get("sources"):
                                    sources = raw["sources"]
                                if not har_path and raw.get("har_path"):
                                    har_path = raw["har_path"]
                    except Exception:
                        pass

        # â”€â”€ DocumentDataStore: source-of-truth keyed by document_id (G4) â”€â”€â”€â”€
        _doc_stored = False
        try:
            store = self._get_document_store()
            if store is not None:
                store.store(
                    document_id=document_id,
                    conversation_id=conversation_id,
                    fmt=fmt,
                    content=content,
                    variants=variants,
                    alternatives=show.get("alternatives", []),
                    trust=trust,
                    source_document_id=source_document_id,
                    sources=sources,
                    har_path=har_path,
                    capture_path=capture_path,
                    # _store_document_data has always TAKEN turn_id and never
                    # passed it on, so every stored document was unattributable:
                    # a rehydrated card could not be paired with the exchange
                    # that produced it, which is why the answer text and its card
                    # both rendered, neither aware of the other.
                    turn_id=turn_id,
                    # create_artifact (Phase A): the stored row carries the
                    # card's lifecycle id and its title/kind/summary, so a reload
                    # shows the same card instead of re-deriving the label.
                    card_id=card_id,
                    title=show.get("title"),
                    kind=show.get("kind"),
                    summary=show.get("summary"),
                    language=show.get("language"),
                )
                _doc_stored = True
        except Exception as exc:
            logger.warning("[AgentKernel] document_data store failed: %s", exc)
        # Taxonomy DELIVERY: a document was produced (ids and sizes only, never content).
        _emit_event(
            self, "ARTIFACT_PRODUCED", thread_id=getattr(self, "_turn_session_id", None),
            payload={"document_id": str(document_id), "format": fmt,
                     "chars": len(content or ""), "trust": trust, "stored": _doc_stored},
        )

        # Session 245 (live memory footer): surface the DOCUMENT STORE on the
        # card's footer â€” a websearch's crawled content landing in
        # document_data + episodic chunks is exactly the memory activity the
        # user wants to see while execution happens. outcome_type distinguishes
        # it from step stores / recall.
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.MEMORY_EVENT,
                data={
                    "kind": "episodic",
                    "task_summary": f"Document stored: {str(document_id)[:40]} ({len(canonical_text)} chars)",
                    "outcome_type": "document_store",
                    "duration_ms": 0,
                },
                session_id=self.session_id,
                conversation_id=conversation_id,
            )
        except Exception:
            pass  # never block the document store on an emit failure

        # â”€â”€ Mycelium: semantic/episodic store â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # OFF THE CRITICAL PATH (2026-08-17, same rule as the pacman_fragment
        # mediator). Storing means embedding, and the CPU-only encoder costs
        # ~5 s per 1 KB chunk â€” a 14-chunk document blocked the DER loop for
        # ~50-90 s per step. Measured live: three inter-step gaps of 88 s, 72 s
        # and 84 s accounted for 244 s of a 311 s turn, while the mediator's own
        # fragments (already async) filed in the background without stalling it.
        #
        # Same background writer, so ALL filing is uniform: one serialized
        # worker, a bounded queue, and a FILED / FILE FAILED / QUEUE FULL log
        # line for every job (user rule: nothing waits on the filing, but it
        # must be trackable if it breaks).
        try:
            mi = getattr(self, "_memory_interface", None)
            if mi is not None and getattr(mi, "episodic", None) is not None:
                from backend.agent.mcm_protocol.actions.pacman_fragment import (
                    _submit_fragment_job,
                )

                _episodic = mi.episodic
                _submit_fragment_job(
                    lambda: _episodic.fragment_and_store(
                        canonical_text,
                        conversation_id,
                        chunk_type="document_data",
                        zone=zone,
                    ),
                    f"document_data/{document_id} ({len(canonical_text)} chars)",
                )
        except Exception as exc:
            logger.warning("[AgentKernel] document_data Mycelium store failed: %s", exc)

        # â”€â”€ Mycelium: seed document data as a trust-routed context node (W8/O2) â”€â”€
        # So trusted, frequently-referenced data can crystallize into a permanent
        # landmark at PERMANENCE_THRESHOLD. Trust routing is CellWall-enforced
        # inside the interface â€” never bypassed. coords_from is the agent's real
        # reasoning-state coordinate ("x,y,xi,u"); the interface parses it.
        try:
            if mi is not None and hasattr(mi, "ingest_document_data"):
                mi.ingest_document_data(
                    content=canonical_text,
                    trust=trust,
                    session_id=conversation_id,
                    coords=coords_from,
                    label=document_id,
                )
        except Exception as exc:
            logger.warning("[AgentKernel] document_data Mycelium seed failed: %s", exc)



        # OFF THE CRITICAL PATH. This is a durability/audit write, not part of
        # producing the answer â€” but it ran INLINE on the DER thread after every
        # tool result. A live stack dump caught the thread parked in
        # ffi_immortus_chain_append -> SQLite right after a web search returned,
        # so a finished crawl looked hung and its UI events never surfaced.
        # `canonical_text` carries the full rendered document (for a crawl, the
        # page content), so the cost scales with how much the search found.
        #
        # NOTE this is the SECOND such write on the same path â€” tool_bridge's
        # _record_tool_event had the identical problem and was moved off-thread
        # first; fixing it simply revealed this one underneath. If a third
        # appears, the pattern (not the instance) is what needs addressing.
        #
        # The chain row is the document's place in TIME (created_at) and in
        # reasoning state (coords): a REFERENCE to the payload, never the
        # payload. document_data holds the document; retrieve_documents_by_
        # trajectory rehydrates it by file_path. Copying canonical_text here
        # (content + variants, i.e. the document twice) grew single chain rows
        # to 841 MB (S12). Written on the ordered durability lane, not a
        # thread per row.
        try:
            from backend.gateway.iris_ffi import ffi_immortus_chain_append
            from backend.utils.durability_queue import submit as _durability_submit

            _chain_ref = json.dumps({
                "document_id": document_id,
                "format": fmt,
                "trust": trust,
                "content_origin": content_origin,
                "conversation_id": conversation_id,
                "turn_id": turn_id,
                "chars": len(content) if isinstance(content, str) else 0,
                "head": content[:400] if isinstance(content, str) else "",
            }, ensure_ascii=False)

            def _append_chain() -> None:
                try:
                    ffi_immortus_chain_append(
                        thread_id=conversation_id,
                        result=_chain_ref,
                        coords_from=coords_from,
                        # A document lands at a point in reasoning state: it
                        # does not move the state, so the transition ends
                        # where it began.
                        coords_to=coords_from,
                        nbl_outcome="document_render",
                        insight=fmt,
                        file_path=document_id,
                        landmark_id="",
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[AgentKernel] document_data Immortus store failed: %s", exc)

            _durability_submit(f"immortus-doc:{document_id}", _append_chain)
        except Exception as exc:
            logger.warning("[AgentKernel] document_data Immortus dispatch failed: %s", exc)

    def _prism_card_id_for(self, document_id: str) -> str:
        """REQ-10 (reply-surface-contract T20): the prism card_id for a
        document, minted ONCE and reused across every event of that card's
        lifetime (update, reformat). ``document_id`` stays the artifact-store
        key (AC3); ``card_id`` is the lifecycle key. Distinct namespace from
        task cards (``card_doc_*``) so the two systems can never collide.
        In-memory + bounded (200 docs): a reload mints fresh ids; content
        identity survives via document_id. Never raises.
        """
        # Session 365 FIX: `uuid.uuid4()` below was used without an import in
        # this scope (every other `import uuid` in this module is local to a
        # different function), so the outer `except` silently returned the
        # `card_doc_<document_id>` fallback on every call and the mint-once
        # mapping write below it never executed.
        import uuid

        try:
            mapping = getattr(self, "_prism_card_by_doc", None)
            if mapping is None:
                mapping = {}
                self._prism_card_by_doc = mapping
            existing = mapping.get(document_id)
            if existing:
                return existing
            # 2026-09-22 (audit): after a reload the map is empty â€” the
            # stored row can carry the id. Consult the store first.
            try:
                store = self._get_document_store()
                row = store.get(document_id) if store is not None else None
                _stored_id = (row or {}).get("card_id")
                if row is not None and isinstance(_stored_id, str) and _stored_id:
                    mapping[document_id] = _stored_id
                    return _stored_id
            except Exception:
                pass
            card_id = f"card_doc_{uuid.uuid4().hex[:16]}"
            mapping[document_id] = card_id
            if len(mapping) > 200:
                for old in list(mapping)[:50]:
                    mapping.pop(old, None)
            return card_id
        except Exception:  # noqa: BLE001 â€” ids must never block a render
            return f"card_doc_{document_id}"

    def create_artifact(
        self,
        title: str,
        kind: str,
        summary: str,
        content: str,
        language: Optional[str] = None,
        artifact_id: Optional[str] = None,
        *,
        turn_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> dict:
        """THE ONLY DOOR TO A CARD (reply-surface audit, Phase A).

        The model calls this (tool ``create_artifact``) when it made something
        to keep, reuse or open on its own; the older `{speak, show}` payload
        converts to the same call in :meth:`_process_structured_response`. It
        stores the artifact on the REAL DocumentDataStore (title, kind, summary,
        language and the card_id ride the row, so a reload shows the same card)
        and emits DOCUMENT_RENDER with title, kind, summary, language, format,
        content, document_id, turn_id, card_id, conversation_id and trust.

        ``artifact_id`` publishes a new version of an existing artifact through
        :meth:`update_document` (same card_id, ``updated`` and ``revision`` on
        the event); an unknown id is a fresh artifact. ``extra`` carries the
        `show` payload's other keys (alternatives, variants, sources, har_path,
        source_tool, content_origin, source_document_id; ``format`` overrides
        the format the kind implies, so a `show` keeps its own). Never raises:
        returns ``{"success": True, "artifact_id", "version", "card_id"}`` or
        ``{"success": False, "error"}``.
        """
        from backend.agent.artifact_policy import (
            ARTIFACT_KINDS,
            ARTIFACT_TITLE_MAX,
            artifact_format_and_body,
            is_tool_result_envelope,
        )

        def _refuse(reason: str) -> dict:
            logger.info(
                "[AgentKernel] create_artifact refused turn=%s: %s",
                turn_id or "unknown", reason,
            )
            return {"success": False, "error": reason}

        try:
            title = title.strip() if isinstance(title, str) else ""
            summary = " ".join(summary.split()) if isinstance(summary, str) else ""
            _missing = [
                name
                for name, val in (
                    ("title", title),
                    ("summary", summary),
                    ("content", content),
                )
                if not (isinstance(val, str) and val.strip())
            ]
            if _missing:
                return _refuse(
                    "create_artifact needs " + ", ".join(_missing)
                    + " - an artifact always has a title, a one-line summary "
                    "and a body"
                )
            kind = str(kind or "").strip().lower()
            if kind not in ARTIFACT_KINDS:
                return _refuse(
                    f"create_artifact kind must be one of {', '.join(ARTIFACT_KINDS)}"
                )
            # A tool result is not an artifact: it must not become a card, or
            # the thread fills with JSON receipts (live 2026-09-25).
            if is_tool_result_envelope(content):
                return _refuse(
                    "create_artifact content is a tool-call result envelope, not "
                    "an artifact - keep it in your reply text"
                )
            if len(title) > ARTIFACT_TITLE_MAX:
                logger.info(
                    "[AgentKernel] create_artifact title cut %d -> %d chars turn=%s",
                    len(title), ARTIFACT_TITLE_MAX, turn_id or "unknown",
                )
                title = title[:ARTIFACT_TITLE_MAX].rstrip()
            language = (str(language).strip() or None) if language else None

            extra = dict(extra or {})
            fmt, body = artifact_format_and_body(kind, content, language)
            if extra.get("format"):
                # A `show` names its own format; that choice wins over the one
                # the kind implies, and its body is stored as sent.
                fmt, body = str(extra["format"]), content
            conversation_id = (
                conversation_id or getattr(self, "conversation_id", None) or "default"
            )
            turn_id = turn_id or getattr(self, "_current_turn_id", None)
            # Trust-routing W3: 'untrusted' when this turn touched external/web
            # sources, else 'trusted'. The frontend sanitizes html/mermaid when
            # trust != 'trusted'.
            trust = extra.get("trust") or (
                "untrusted" if self._pacman_zone_for_turn() == "reference" else "trusted"
            )

            if artifact_id and self.update_document(
                artifact_id,
                content=body,
                fmt=fmt,
                trust=trust,
                turn_id=turn_id,
                conversation_id=conversation_id,
                alternatives=extra.get("alternatives") or [],
                title=title,
                kind=kind,
                summary=summary,
                language=language,
            ):
                _row = None
                _store = self._get_document_store()
                if _store is not None:
                    _row = _store.get(artifact_id)
                self._note_artifact_emitted(body, turn_id)
                return {
                    "success": True,
                    "artifact_id": artifact_id,
                    "version": ((_row or {}).get("revision") or 0) + 1,
                    "card_id": self._prism_card_id_for(artifact_id),
                    "revised": True,
                }

            import uuid

            # A caller that stored a BLOB first (screenshot_page: the image is
            # keyed by the document id, so the row and its picture live and die
            # together) hands that id in; everyone else gets a fresh one.
            document_id = str(extra.pop("document_id", "") or uuid.uuid4())
            # REQ-10 AC1/AC2 (reply-surface-contract T20): every prism card
            # carries a stable lifecycle id alongside the document store key,
            # minted once here and reused by update/reformat.
            card_id = self._prism_card_id_for(document_id)
            show = {
                **extra,
                "format": fmt,
                "content": body,
                "title": title,
                "kind": kind,
                "summary": summary,
                "language": language,
            }
            # W4: persist the canonical DATA keyed by document_id BEFORE the
            # render so provenance (sources / har_path, possibly inherited from
            # a linked raw crawler row) can ride the render payload (REQ-6 / D2).
            self._store_document_data(
                document_id=document_id,
                show=show,
                trust=trust,
                turn_id=turn_id,
                conversation_id=conversation_id,
                card_id=card_id,
            )
            _render_sources = show.get("sources")
            _render_har = show.get("har_path")
            if _render_sources is None or _render_har is None:
                try:
                    _store = self._get_document_store()
                    _row = _store.get(document_id) if _store is not None else None
                    if _row is not None:
                        if _render_sources is None:
                            _render_sources = _row.get("sources") or []
                        if _render_har is None:
                            _render_har = _row.get("har_path")
                except Exception:  # noqa: BLE001 - provenance never blocks a card
                    pass

            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            try:
                get_event_bus().emit(
                    IRISStreamEvent.DOCUMENT_RENDER,
                    data={
                        "title": title,
                        "kind": kind,
                        "summary": summary,
                        "language": language,
                        "format": fmt,
                        "content": body,
                        "alternatives": show.get("alternatives", []),
                        "trust": trust,
                        "document_id": document_id,
                        "turn_id": turn_id,
                        "conversation_id": conversation_id,
                        "card_id": card_id,  # REQ-10 AC2: stable lifecycle id
                        "sources": _render_sources or [],
                        "har_path": _render_har,
                        # REQ-13 AC5 / T18b (reply-surface-contract): the partial
                        # channel discriminator. False = the FINAL whole-body
                        # emit. A future partial emit MUST carry the same stable
                        # document_id on its FIRST partial so the frontend
                        # updates the card in place.
                        "partial": False,
                    },
                    turn_id=turn_id,
                    conversation_id=conversation_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[AgentKernel] DOCUMENT_RENDER emit failed: %s", exc)
                return {
                    "success": False,
                    "error": "the artifact was stored but could not be shown",
                    "artifact_id": document_id,
                }
            self._note_artifact_emitted(body, turn_id)
            logger.info(
                "[AgentKernel] create_artifact conv=%s doc=%s card=%s kind=%s title=%r",
                conversation_id, document_id, card_id, kind, title,
            )
            return {
                "success": True,
                "artifact_id": document_id,
                "version": 1,
                "card_id": card_id,
            }
        except Exception as exc:  # noqa: BLE001 - a card is never worth a failed reply
            logger.warning("[AgentKernel] create_artifact failed: %s", exc)
            return {"success": False, "error": str(exc)}

    def _note_artifact_emitted(self, body: str, turn_id: Optional[str]) -> None:
        """Bookkeeping after create_artifact put a card on the wire.

        Marks that a card rendered this turn (it decides the bubble in
        :meth:`_process_structured_response`) and stamps time-to-card on the
        turn's [LAYERS] line. (The Oracle's `presentation` observer that ran
        here was retired 2026-11-10.) Never raises.
        """
        self._last_render_emitted = True
        # REQ-13 AC4: time-to-card on this turn's [LAYERS] line.
        _metrics = getattr(self, "_active_turn_metrics", None)
        _mark = getattr(_metrics, "mark_card", None)
        if callable(_mark):
            try:
                _mark()
            except Exception:  # noqa: BLE001 - telemetry never blocks
                pass

    def update_document(self, document_id, content, fmt=None, trust=None, turn_id=None, conversation_id=None, alternatives=None, title=None, kind=None, summary=None, language=None):
        """Phase 4 (chat-card-redesign): revise an already-rendered document.

        Updates the canonical data in DocumentDataStore (keyed by document_id;
        revision bumped) and re-emits DOCUMENT_RENDER with ``updated: True`` so the
        frontend reflects the edit in place (with an 'Updated' indicator) instead
        of appending a new card.  Returns the document_id, or None if the id is
        unknown (caller should then do a fresh render).

        ``title``/``kind``/``summary``/``language`` (create_artifact, Phase A)
        replace the artifact's identity only when given; otherwise the version
        keeps the ones it was made with.
        """
        try:
            from backend.agent.document_store import DocumentDataStore
            # `self._memory` never existed on the real kernel (only test
            # stand-ins set it), so every revision raised AttributeError, was
            # swallowed below and returned None - a revising `show` always
            # minted a SECOND card. The store hangs off the memory interface.
            store = DocumentDataStore.get_for(getattr(self, "_memory_interface", None))
            if store is None:
                return None
            existing = store.get(document_id)
            if existing is None:
                return None
            new_fmt = fmt or existing.get("format") or "markdown"
            variants = dict(existing.get("variants") or {})
            variants[new_fmt] = content
            store.update(
                document_id=document_id,
                content=content,
                fmt=new_fmt,
                variants=variants,
                trust=trust or existing.get("trust") or "trusted",
                title=title, kind=kind, summary=summary, language=language,
            )
            revision = (existing.get("revision") or 0) + 1
            payload = {
                "format": new_fmt,
                "content": content,
                "alternatives": alternatives if alternatives is not None else (existing.get("alternatives") or []),
                "trust": trust or existing.get("trust") or "trusted",
                "document_id": document_id,
                "turn_id": turn_id or existing.get("turn_id"),
                "conversation_id": conversation_id or self.conversation_id,
                # REQ-10 AC4 (reply-surface-contract T20): an in-place revision
                # reuses the SAME prism card_id minted at the original emit.
                "card_id": self._prism_card_id_for(document_id),
                "updated": True,
                "revision": revision,
                "sources": existing.get("sources") or [],
                "har_path": existing.get("har_path"),
                "title": title or existing.get("title"),
                "kind": kind or existing.get("kind"),
                "summary": summary or existing.get("summary"),
                "language": language or existing.get("language"),
            }
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                get_event_bus().emit(
                    IRISStreamEvent.DOCUMENT_RENDER,
                    data=payload,
                    turn_id=payload["turn_id"],
                    conversation_id=payload["conversation_id"],
                )
            except Exception as exc:
                logger.warning("[AgentKernel] DOCUMENT_RENDER(update) emit failed: %s", exc)
            return document_id
        except Exception as exc:
            logger.warning(f"[AgentKernel] update_document failed: {exc}")
            return None

    @staticmethod
    def _json_default(obj: Any) -> Any:
        """json.dumps ``default=`` for tool-result payloads that carry
        non-JSON-native objects (D4e â€” e.g. crawler CredibilityMap nested
        inside a web_search/crawler_query result dict, which raised "Object
        of type CredibilityMap is not JSON serializable" and dropped the
        whole DER tool-result capture).

        Dataclasses (CredibilityMap included) serialize field-by-field via
        asdict() so the JSON stays structured (per_source/unsourced_claims/
        top_score), not an opaque repr string. Falls back to vars()/str()
        for plain objects so nothing this touches can raise again.
        """
        import dataclasses
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
        return str(obj)

    def _is_capture_worthy(self, tool_name: str, result: Any) -> bool:
        """Cheap, deterministic gate (no I/O, no LLM) for whether to persist a result.

        * None / empty results are skipped.
        * Explicit error payloads ({"error": ...}) are skipped.
        * Very short results (< _MIN_CAPTURE_CHARS) are skipped as trivial.
        * Results carrying a numeric relevance/score below _RELEVANCE_THRESHOLD
          are skipped (low-signal).
        """
        if result is None:
            return False
        # A store READ returns documents that are already stored. Capturing it
        # made a new document holding the full content of every earlier one,
        # which the next read nested and escaped again: 37 memory_chain rows
        # grew to 4.84 GB of data/memory.db (rows up to 841 MB, 2026-09-30).
        if tool_name in self._DER_READ_TOOLS:
            return False
        if isinstance(result, dict):
            if "error" in result:
                return False
            score = result.get("relevance") or result.get("score")
            if isinstance(score, (int, float)) and float(score) < self._RELEVANCE_THRESHOLD:
                return False
            payload = result
        else:
            payload = result
        import json

        text = (
            payload if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False, default=self._json_default)
        )
        if len(text) < self._MIN_CAPTURE_CHARS:
            return False
        return True

    def _capture_tool_result(
        self,
        tool_name: str,
        result: Any,
        conversation_id: str,
        turn_id: Optional[str] = None,
        session_id: str = "unknown",
    ) -> Optional[str]:
        """Persist a tool result into the document store so it becomes reformat-able.

        Trust-routing (W2/W3): external tools (web_search, crawler_query) are
        stored as ``untrusted``; everything else (e.g. read_file) as ``trusted``.
        Returns the new document_id, or None when the result was skipped by the
        capture-worthiness gate. All failures are swallowed â€” capture must never
        block the tool result from reaching the agent.
        """
        # â”€â”€ ChatCard redesign (pin_9e97e21340e7): external/web tool results are
        # captured into the document store (reformat-able). Capture is NOT a
        # render: a card appears only when the agent calls create_artifact (or
        # sends the older `show` payload, which converts to the same call).
        # The "how would you like these presented?" question that used to fire
        # after a web turn without a `show` was deleted (reply-surface audit,
        # Phase A): a plain answer is the answer.
        is_external = is_external_tool(tool_name)

        if not self._is_capture_worthy(tool_name, result):
            return None
        import uuid

        import json

        document_id = str(uuid.uuid4())
        fmt = "json" if isinstance(result, (dict, list)) else "text"
        content = (
            json.dumps(result, ensure_ascii=False, default=self._json_default)
            if isinstance(result, (dict, list)) else str(result)
        )
        show = {
            "format": fmt,
            "content": content,
            "variants": {fmt: content},
            "source_tool": tool_name,
        }
        # Thread provenance (HAR path) from the crawl result into the stored show
        # so the raw JSON row carries it (REQ-13). Tolerant of result shape:
        # dict (serialized) or CrawlResult object. Never raises.
        if isinstance(result, dict):
            if result.get("har_path"):
                show["har_path"] = result["har_path"]
            if result.get("sources"):
                show["sources"] = result["sources"]
        elif hasattr(result, "har_path"):
            show["har_path"] = result.har_path
        trust = "untrusted" if is_external else "trusted"
        try:
            self._store_document_data(document_id, show, trust, turn_id, conversation_id)
        except Exception as exc:
            logger.warning("[AgentKernel] tool-result capture failed: %s", exc)
            return None
        # pin: the capture-time deterministic DOCUMENT_RENDER (old pin
        # 517dfcbda150) was REMOVED by user decision â€” it popped a card on EVERY
        # web-tool commit (every crawl mid-research), not just the final answer.
        return document_id

    def reformat_document(
        self,
        document_id: Optional[str] = None,
        content: Optional[str] = None,
        target_format: str = "",
        conversation_id: str = "default",
        turn_id: Optional[str] = None,
        original_format: Optional[str] = None,
        trust: Optional[str] = None,
    ) -> Optional[str]:
        """Re-render a previously generated document in a different format.

        W5 (data-centric): the primary path retrieves the document's canonical
        data + stored variants by ``document_id`` (the frontend sends only
        ``{document_id, target_format}`` â€” no client ``content``).  Deterministic
        first (G1): if ``target_format`` is already a stored variant, it is
        returned with **zero LLM calls**.  Only genuinely new formats invoke the
        LLM on the canonical data, and the result is cached as a new variant.

        A ``content``-based fallback (pre-W5) remains for direct/legacy callers;
        it always goes through the LLM.

        ``trust`` (trust-routing W3) is carried through so a reformatted
        document keeps the original's trust level.  Returns the new content, or
        None on failure.  Issue D.2.
        """
        if not target_format:
            return None

        # â”€â”€ W5 primary path: retrieve by document_id â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if document_id:
            store = self._get_document_store()
            doc = store.get(document_id) if store is not None else None
            orig_fmt = original_format or (doc.get("format") if doc else None)
            if doc is None:
                logger.warning(
                    "[AgentKernel] reformat_document: document_id %s not found",
                    document_id,
                )
                return None
            stored_trust = doc.get("trust") or trust or "trusted"

            # Deterministic-first (G1): stored variant -> no LLM.
            variant = store.get_variant(document_id, target_format) if store else None
            if variant is not None:
                payload = {
                    "format": target_format,
                    "content": variant,
                    "alternatives": doc.get("alternatives") or [],
                    "trust": stored_trust,
                    "document_id": document_id,
                    "turn_id": turn_id,
                    "conversation_id": conversation_id,
                    "reformatted": True,
                    # REQ-10 AC4 (T20): a reformat reuses the SAME card_id.
                    "card_id": self._prism_card_id_for(document_id),
                    "sources": doc.get("sources") or [],
                    "har_path": doc.get("har_path"),
                    # Phase A: a reformat is the SAME card, so it keeps the
                    # title/kind/summary it was made with.
                    "title": doc.get("title"),
                    "kind": doc.get("kind"),
                    "summary": doc.get("summary"),
                }
                try:
                    from backend.agent.event_bus import get_event_bus, IRISStreamEvent

                    get_event_bus().emit(
                        IRISStreamEvent.DOCUMENT_RENDER,
                        data=payload,
                        turn_id=turn_id,
                        conversation_id=conversation_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "[AgentKernel] DOCUMENT_RENDER (reformat) emit failed: %s", exc
                    )
                self._record_reformat_edge(store, orig_fmt, target_format)
                return variant

            # No stored variant -> LLM reformat on the canonical data.
            content = doc.get("content", "")
            original_format = original_format or doc.get("format")

        # â”€â”€ LLM reformat path (W5 new format, or legacy content fallback) â”€â”€â”€
        if not content:
            return None
        prompt = (
            "Reformat the following document as " + target_format + ". "
            "Preserve all information and meaning. "
            'Respond with JSON: {"show": {"format": "' + target_format + '", '
            '"content": "<reformatted text>", "alternatives": ["<other formats>"]}} '
            "or, if plain text is clearer, just return the reformatted text.\n\n"
            "DOCUMENT:\n" + content
        )
        try:
            reformatted = self._respond_direct(prompt, context=[])
        except Exception as exc:
            logger.warning("[AgentKernel] reformat_document LLM call failed: %s", exc)
            return None
        if not reformatted:
            return None

        from backend.agent.structured_response import build_reformat_payload

        payload = build_reformat_payload(
            reformatted,
            target_format=target_format,
            turn_id=turn_id,
            conversation_id=conversation_id,
            original_format=original_format,
            trust=trust,
        )
        # T6: reformat payload preserves document_id + trust.
        if document_id:
            payload["document_id"] = document_id
            # REQ-10 AC4 (T20): the reformat rides the same prism card_id.
            payload["card_id"] = self._prism_card_id_for(document_id)
            # Phase A: ...and the title/kind/summary the artifact was made with.
            for _k in ("title", "kind", "summary"):
                payload[_k] = (doc or {}).get(_k)
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.DOCUMENT_RENDER,
                data=payload,
                turn_id=turn_id,
                conversation_id=conversation_id,
            )
        except Exception as exc:
            logger.warning(
                "[AgentKernel] DOCUMENT_RENDER (reformat) emit failed: %s", exc
            )
        # Cache the new variant so future reformats are deterministic (G1).
        if document_id:
            try:
                store = self._get_document_store()
                if store is not None:
                    store.add_variant(document_id, target_format, payload.get("content", ""))
            except Exception as exc:
                logger.warning("[AgentKernel] reformat variant cache failed: %s", exc)
        self._record_reformat_edge(self._get_document_store(), original_format, target_format)
        return payload["content"]

    def _record_reformat_edge(self, store, from_format, to_format):
        """Safely reinforce a reformat pheromone edge (W10/O4)."""
        if store is None or not from_format or not to_format:
            return
        try:
            store.record_reformat(from_format, to_format)
        except Exception as exc:
            logger.warning("[AgentKernel] reformat edge record failed: %s", exc)

    def suggest_reformat(self, document_id: str, conversation_id: str = "default") -> Optional[str]:
        """Proactively suggest the next format for a document (W10/O4 substrate).

        Returns the most-reinforced target format for the document's current
        format (from the reformat pheromone edges), or None if no signal yet.
        This is the primitive the agent/UI uses to *offer* a reformat of a
        frequently-touched doc type.
        """
        try:
            store = self._get_document_store()
            if store is None:
                return None
            doc = store.get(document_id)
            if doc is None:
                return None
            return store.predict_next_format(doc.get("format"))
        except Exception as exc:
            logger.warning("[AgentKernel] suggest_reformat failed: %s", exc)
            return None

    def vocalize_document(
        self,
        document_id: str,
        target_format: str = "text",
        conversation_id: str = "default",
        turn_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Cross-modal synergy (W10/O4): speak a reformatted view of a document.

        Reformats the stored document to ``target_format`` (reusing W5's
        data-centric reformat) and vocalizes the result via the SpeakTool
        (existing TTS channel). Fire-and-forget â€” returns the speak status.
        """
        content = self.reformat_document(
            document_id=document_id,
            target_format=target_format,
            conversation_id=conversation_id,
            turn_id=turn_id,
        )
        if not content:
            return {"status": "error", "reason": "no content to speak"}
        try:
            from backend.agent.tools.speak_tool import get_speak_tool

            return get_speak_tool().speak(content)
        except Exception as exc:
            logger.warning("[AgentKernel] vocalize_document failed: %s", exc)
            return {"status": "error", "reason": str(exc)}

    def diagram_document(
        self,
        document_id: str,
        conversation_id: str = "default",
        turn_id: Optional[str] = None,
    ) -> Optional[str]:
        """Cross-modal synergy (W10/O4): return a diagram view of a document.

        Reuses reformat_document's existing ``diagram`` (mermaid) format â€” the
        "turn data into a diagram" synergy without a separate Vision generator.
        Returns the mermaid/diagram content, or None on failure.
        """
        return self.reformat_document(
            document_id=document_id,
            target_format="diagram",
            conversation_id=conversation_id,
            turn_id=turn_id,
        )

    def retrieve_documents_by_trajectory(
        self,
        coords: Sequence[float],
        threshold: float = 1.0,
        limit: int = 10,
        conversation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """O1 (W7): return document data produced in a *similar reasoning state*.

        Queries the Immortus 4D chain by coordinate proximity (not embedding
        cosine) and returns the canonical document data for document entries
        (``nbl_outcome='document_render'``, ``file_path`` set). This is the novel
        primitive: "data gathered while thinking like this."  Fire-and-forget â€”
        returns [] on any failure.
        """
        try:
            import json
            from backend.gateway.iris_ffi import ffi_immortus_chain_query_by_coordinate

            entries = ffi_immortus_chain_query_by_coordinate(
                coords,
                threshold=threshold,
                limit=limit,
                thread_id=conversation_id,
                nbl_outcome="document_render",
            )
            docs = []
            _store = None
            for e in entries:
                if not e.get("file_path"):
                    continue
                try:
                    data = json.loads(e.get("result") or "{}")
                except Exception:
                    data = {}
                # The chain row is a reference (S12); the document itself
                # lives in document_data, keyed by the row's file_path.
                try:
                    if _store is None:
                        _store = self._get_document_store()
                    _full = _store.get(e["file_path"]) if _store is not None else None
                except Exception:
                    _full = None
                if _full:
                    data = {**data, **_full}
                data["_distance"] = e.get("distance")
                docs.append(data)
            return docs
        except Exception as exc:
            logger.warning("[AgentKernel] trajectory doc retrieval failed: %s", exc)
            return []

    def _der_emit_card_settle(self, _turn_id, completed_items, _grade, _where):
        """Settle the task card when the goal contract's grade fires.

        Session-326 (owner directive, 2026-09-12): the grade is the terminal
        authority â€” the loop's "done" signal. The card is only a display. If
        the grade never reaches the card, a card stays Active Execution
        forever. ember.

        Idempotent per turn: emits once, then marks emitted. Never raises â€”
        a display-frame must never block a terminal.
        """
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
        except Exception:
            return  # bus unavailable

        _emitted = getattr(self, "_der_card_terminal_emitted", None)
        if _emitted is None:
            _emitted = set()
            self._der_card_terminal_emitted = _emitted
        _key = _turn_id or "<none>"
        if _key in _emitted:
            return

        card_id = None
        try:
            _env = self._card_envelope(_turn_id)
            if isinstance(_env, dict):
                card_id = _env.get("card_id")
        except Exception:
            pass
        if not card_id:
            # No card was created this turn â€” nothing to settle.
            _emitted.add(_key)
            return

        outcome = "success" if _grade == "pass" else "partial" if \
            _grade == "partial" else "failure"
        try:
            get_event_bus().emit(
                IRISStreamEvent.TASK_DONE if outcome in ("success", "partial")
                else IRISStreamEvent.TASK_FAIL,
                data={
                    "task_id": _key,
                    "card_id": card_id,
                    "outcome": outcome,
                    "steps_completed": len(completed_items or []),
                    "conversation_id": getattr(self, "conversation_id", None),
                },
                turn_id=_turn_id,
                conversation_id=getattr(self, "conversation_id", None),
                session_id=getattr(self, "session_id", None) or "default",
            )
            _emitted.add(_key)
        except Exception:
            # Never block the grade on a display frame.
            pass

    @restores_call_class
    def _save_card_footprint(self, plan, completed_items, outcome: str,
                             card_id: Optional[str] = None) -> None:
        """GROUND TRUTH T6 (REQ-3): one footprint per terminal card.

        REQ-3 AC2 keeps the module's never-raise guarantee AND counts failures,
        so a persistent silent failure becomes a number rather than an absence -
        the exact ambiguity that let this store sit empty unnoticed.
        """
        try:
            if not self._memory_interface:
                _write_counters.bump("footprint.no_memory_interface")
                return
            # card_id is captured at turn end when this runs on the lane (the
            # next turn may already have changed _active_card_id).
            _card_id = card_id or getattr(self, "_active_card_id", None)
            if not _card_id:
                _write_counters.bump("footprint.no_card_id")
                return

            from backend.memory.card_footprint import save_card_footprint

            _steps, _tools, _files = [], [], []
            for _ci in (completed_items or []):
                _calls = _step_calls(_ci)  # what the step actually did
                _steps.append({
                    "step_id": str(getattr(_ci, "step_id", "") or ""),
                    "description": str(getattr(_ci, "description", "") or "")[:200],
                    "tool": str(_step_tool(_ci) or ""),
                })
                for _c in _calls:
                    _tool = str(_c.get("tool") or "")
                    if _tool and _tool not in _tools:
                        _tools.append(_tool)
                    _args = _c.get("args") or {}
                    for _k in ("path", "file_path", "file"):
                        _v = _args.get(_k)
                        if isinstance(_v, str) and _v and _v not in _files:
                            _files.append(_v)

            # REQ-3 edge case / card_footprint.py:48-52: the TERMINAL state
            # actually reached, never a fabricated success. "partial" has no slot
            # in the module's converged|failed|abandoned|unknown vocabulary, and
            # calling it converged would be a lie - so it maps to "unknown",
            # which also keeps it out of chain extraction (wormhole REQ-34 AC4
            # extracts only from converged).
            _outcome = {
                "success": "converged",
                "failure": "failed",
                "cancelled": "abandoned",
            }.get(str(outcome), "unknown")

            _ok = save_card_footprint(
                memory=self._memory_interface,
                card_id=str(_card_id),
                conversation_id=str(self.conversation_id or ""),
                objective=self._effective_plan_title(plan),
                steps=_steps,
                tools_used=_tools,
                files_touched=_files,
                outcome=_outcome,
            )
            _write_counters.bump(
                "footprint.written" if _ok else "footprint.write_failed"
            )
        except Exception as _fp_exc:
            _write_counters.bump("footprint.write_failed")
            logger.warning("[DER] card footprint write FAILED: %s", _fp_exc)

    @staticmethod
    def _task_start_payload(
        *,
        task_id: str,
        description: str,
        plan_title: str,
        mode: str,
        steps: list,
        total_steps: int,
        origin: str,
        card_id: str,
        card_relation: str,
        conversation_id: Optional[str],
        agent_id: Optional[str] = None,
        project_id: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> dict:
        """The ``task:start`` payload contract (REQ-14 / T23; REQ-3 / T1).

        ONE construction point for every ``task:start`` emit so the
        merge-by-id contract keys (useTaskProgress.ts:210-227 â€”
        task_id / description / plan_title / mode / steps / total_steps)
        stay identical across sites, plus ``origin`` distinguishing the
        initial announcement from revisions: ``"initial"`` (both initial
        emits), ``"sub_loop_split"`` (REQ-4/REQ-13 split), ``"user_steering"``
        (REQ-15), or ``"amendment"``. REQ-18's trace reads ``origin`` to
        attribute a revision.

        T1 (REQ-3): ADDITIVE ONLY â€” ``card_id`` / ``card_relation`` /
        ``conversation_id`` are the three new keys; nothing about the seven
        keys above changed. Kept a @staticmethod on purpose: identity
        resolution (``_resolve_card_identity``, which needs kernel state)
        stays a separate, independently-testable step, and every caller
        resolves it before building this payload.

        cli-workspace-unification T9a (REQ-5 AC1): ADDITIVE ONLY â€”
        ``agent_id`` (kernel session identity) and ``project_id`` (active
        project folder scope) join the same single construction point, so
        every emit site inherits the multi-agent Kanban tags for free. The
        frontend never fabricates them; when ``project_id`` is unknown
        (no active project scope set on the kernel) consumers fall back to
        conversationId-only keying.

        Session 244 (cardâ†”response inline join): ADDITIVE ONLY â€”
        ``turn_id`` (the kernel's current response turn id,
        ``self._current_turn_id``) joins the payload so the frontend can
        render a card INLINE with the assistant message it belongs to â€”
        the same join documents already use (message.id === turn_id).
        Absent on legacy replays; consumers fall back to bottom-stacking.
        """
        # GROUND TRUTH T28/T29 (REQ-17): stamp the backend-owned ordering
        # key on every row, HERE, at the one construction point every
        # task:start emit already funnels through. ADDITIVE ONLY - no
        # existing key changes, and the planner's own step_number is left
        # untouched as a display concern (REQ-17 AC5).
        #
        # Memoized per row id, so a revision / graft / split re-emitting an
        # existing row returns that row's ORIGINAL key and cannot renumber
        # the card (REQ-17 AC4). T27 measured the alternative: the captured
        # graft trace collided r1 and r1_s1 on key 1.
        steps = _stamp_row_seq(steps, conversation_id)
        return {
            "task_id": task_id,
            "description": description,
            "plan_title": plan_title,
            "mode": mode,
            "steps": steps,
            "total_steps": total_steps,
            "origin": origin,
            "card_id": card_id,
            "card_relation": card_relation,
            "conversation_id": conversation_id,
            "agent_id": agent_id,
            "project_id": project_id,
            "turn_id": turn_id,
        }

    @staticmethod
    def _effective_plan_title(plan: Any) -> str:
        """pin_07b780e7ce21: the objective title must arrive RELIABLY on every
        ``task:start`` / card snapshot â€” the LLM planner sometimes omits
        ``plan_title`` from its JSON, which left search cards with no dominant
        header (the frontend fell back to steps[0].description). When the
        planner title is empty, derive one from the original task so the
        frontend always has a real objective to render; the 80-char wire
        budget every call site already used is unchanged."""
        title = str(getattr(plan, "plan_title", "") or "").strip()
        if title:
            return title[:80]
        return str(getattr(plan, "original_task", "") or "")[:80]

    def _multiagent_tags(self) -> dict:
        """T9a (REQ-5 AC1): the ``(agent_id, project_id)`` Kanban tags,
        resolved ONCE here so every ``task:start`` call site spreads the
        same dict. ``agent_id`` is the kernel session identity;
        ``project_id`` is the active project folder scope â€” ``None`` until
        a project scope is set on the kernel (consumers then fall back to
        conversationId-only keying per design.md Error Handling)."""
        return {
            "agent_id": getattr(self, "session_id", None)
            or getattr(self, "conversation_id", None),
            "project_id": getattr(self, "active_project_id", None),
        }

    def _register_card(self, task_id: str, card_id: str) -> None:
        """Bind ``task_id -> card_id`` in the per-kernel registry (REQ-3/T2).

        Bounded at ``_CARD_REGISTRY_CAP`` â€” evicts the oldest insertion first
        (dict preserves insertion order) so a long-running kernel process
        cannot leak memory one entry per DER task forever.
        """
        if task_id in self._card_by_task:
            return
        if len(self._card_by_task) >= self._CARD_REGISTRY_CAP:
            oldest_task_id = next(iter(self._card_by_task))
            del self._card_by_task[oldest_task_id]
        self._card_by_task[task_id] = card_id

    def _resolve_card_identity(self, task_id: str, origin: str) -> tuple:
        """REQ-3 AC2/AC3/AC5 (T2): decide ``card_id`` / ``card_relation`` for
        one ``task:start`` emit, entirely from backend state.

        a. ``task_id`` already registered -> same card_id, "continues". This
           is the known double-emit case: the early LLM-plan skeleton then
           the DER queue emit for one task (REQ-3 edge case â€” no flicker).
        b. ``origin != "initial"`` and there is an active card -> register
           ``task_id`` against the ACTIVE card and continue it. Written as
           "not initial" ON PURPOSE, rather than an explicit membership test
           against sub_loop_split / user_steering / amendment: a non-initial
           origin is by definition a revision of a running task, so a future
           fifth origin still continues the card instead of silently
           starting a new one. A sub-loop split CONTINUES the parent card â€”
           a branch WITHIN a card, never a second card.
        c. otherwise -> a genuinely new task; mint ``card_{task_id}``,
           register it, make it the active card, return "new".

        Never raises â€” a resolution failure logs and falls back to a fresh,
        unregistered card_id rather than breaking the task:start emit.
        """
        try:
            if not task_id:
                logger.warning(
                    "[AgentKernel] card identity: empty task_id (origin=%s conv=%s) "
                    "â€” minting an unregistered card; continuation will not track it",
                    origin, self.conversation_id,
                )
                import uuid as _uuid
                return f"card_unknown_{_uuid.uuid4().hex[:8]}", "new"

            existing = self._card_by_task.get(task_id)
            if existing is not None:
                logger.info(
                    "[AgentKernel] card identity: task=%s origin=%s conv=%s -> "
                    "continues existing card=%s (double-emit)",
                    task_id, origin, self.conversation_id, existing,
                )
                return existing, "continues"

            if origin != "initial" and self._active_card_id is not None:
                card_id = self._active_card_id
                self._register_card(task_id, card_id)
                logger.info(
                    "[AgentKernel] card identity: task=%s origin=%s conv=%s -> "
                    "continues active card=%s (non-initial origin revises "
                    "the running task)",
                    task_id, origin, self.conversation_id, card_id,
                )
                return card_id, "continues"

            card_id = f"card_{task_id}"
            self._register_card(task_id, card_id)
            self._active_card_id = card_id
            logger.info(
                "[AgentKernel] card identity: task=%s origin=%s conv=%s -> "
                "new card=%s",
                task_id, origin, self.conversation_id, card_id,
            )
            return card_id, "new"
        except Exception as _card_exc:  # noqa: BLE001 â€” never break a task emit
            logger.warning(
                "[AgentKernel] card identity resolution failed "
                "(task=%s origin=%s conv=%s): %s",
                task_id, origin, self.conversation_id, _card_exc,
            )
            return f"card_{task_id or 'unknown'}", "new"

    def _card_envelope(
        self,
        task_id: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> dict:
        """REQ-3 AC6 (T2): keep ``card_id`` stable across every event of a
        card's lifetime, not just ``task:start``. LOOKS UP (never registers)
        the card already bound to ``task_id`` and returns the pair to merge
        into a lifecycle emit dict (tool:call, tool:result, task:done/fail,
        task:progress). Unknown id -> ``card_id`` is None â€” a wrong id is
        worse than a missing one (REQ-10 AC5: unknown is inert, never an
        error). Never raises.

        REQ-10 (reply-surface-contract T20): prism cards resolve through
        ``_prism_card_by_doc`` â€” pass ``document_id`` so the same envelope
        machinery can address a document card's lifecycle.
        """
        try:
            card_id = self._card_by_task.get(task_id) if task_id else None
            if card_id is None and document_id:
                card_id = getattr(self, "_prism_card_by_doc", {}).get(document_id)
        except Exception:
            card_id = None
        return {"card_id": card_id, "conversation_id": self.conversation_id}

    @staticmethod
    def _queue_steps_snapshot(queue) -> list:
        """T4a (REQ-4 AC1/AC5): the FULL, cumulative step list + derived
        status, for card PERSISTENCE â€” distinct from the task:start WIRE
        payload, which for revision origins (user_steering/amendment)
        intentionally emits only the delta for the frontend's merge-by-id
        reducer (useTaskProgress.ts). A persisted card has no earlier
        partial payload to merge against, so persistence always walks
        ``queue.items`` (already cumulative by the time any revision emits)
        and derives status from completed_ids/failed_ids/vetoed_ids rather
        than reusing the wire delta. Never raises â€” a malformed queue
        persists as "no steps" rather than breaking the emit it rides on.
        """
        try:
            return [
                {
                    "id": it.step_id,
                    "description": it.description,
                    # Session 247: step_number rides the snapshot so the
                    # frontend can render rows in SEMANTIC order. Live-discovered
                    # children (grafts) used to land out of order after a
                    # task:start merge because insertion order != execution
                    # order.
                    "stepNumber": it.step_number,
                    "status": (
                        "done" if it.step_id in queue.completed_ids
                        else "failed" if it.step_id in queue.failed_ids
                        else "vetoed" if it.step_id in queue.vetoed_ids
                        else "pending"
                    ),
                    "toolName": _step_tool(it),
                    # Session 312 (conv-98 smoke): persist the distilled
                    # outcome so a revisited card shows what each step found,
                    # not just its status. Same envelope as live rows (C3/F9)
                    # so stored and live can never drift; excerpted so a
                    # crawl dump can't bloat the store.
                    "result_summary": (
                        AgentKernel._smart_excerpt(
                            AgentKernel._format_tool_result(
                                getattr(it, "result", "") or ""
                            ),
                            300,
                        )
                        or None
                    ),
                }
                for it in queue.items
            ]
        except Exception:
            return []

    def _persist_card_snapshot(
        self,
        *,
        card_id: Optional[str],
        conversation_id: Optional[str],
        card_relation: str = "new",
        plan_title: Optional[str] = None,
        mode: Optional[str] = None,
        steps: Optional[list] = None,
        total_steps: int = 0,
        terminal_state: str = "running",
    ) -> None:
        """T4a (REQ-4 AC1/AC5): mirror one card lifecycle moment
        (task:start, a task:progress step transition, or task:done/fail)
        into the persistent card store.

        ONE construction point, called from every emit site that carries
        card identity (mirrors ``_task_start_payload``'s pattern), so the
        shape handed to ``CardState``/``CardStepSnapshot`` never drifts
        between call sites.

        NON-BLOCKING: hands the snapshot to
        ``conversation_context_store.enqueue_card_write`` â€” a bounded,
        coalescing background queue â€” rather than calling
        ``store.save_card()`` (synchronous SQLite) directly. These emit
        sites run on the DER worker thread (iris_gateway.py's
        ``run_in_executor`` pool), not inside a coroutine, so there is no
        event loop to offload to; the queue's own background thread is the
        offload.

        Missing ``card_id``/``conversation_id`` (unknown task_id, no active
        card) is a no-op â€” there is nothing to persist. Never raises: a
        persistence failure must never block a card emit or a user
        response.

        Card gate (owner bound, 2026-09-25): a turn below the card bound writes
        NOTHING here, at any lifecycle moment, so a short exchange cannot
        reappear as a card after a reload. The marker is set per conversation
        when the DER plan is known, and the next card-bearing turn clears it.
        """
        _suppressed_turn = getattr(self, "_suppressed_card_turn", None)
        if _suppressed_turn:
            from backend.agent.artifact_policy import card_suppressed

            if card_suppressed(_suppressed_turn):
                return
        try:
            if not card_id or not conversation_id:
                return
            from backend.agent.conversation_context_store import (
                CardState,
                CardStepSnapshot,
                enqueue_card_write,
            )

            _steps = [
                CardStepSnapshot(
                    id=str(s.get("id", "")),
                    description=str(s.get("description", "")),
                    status=str(s.get("status", "pending")),
                    tool_name=s.get("toolName") or s.get("tool_name"),
                    # Session 246 (@-card-mentions): persist the distilled
                    # outcome so a referenced card carries its findings.
                    result_summary=(
                        s.get("resultPreview")
                        or s.get("result_summary")
                        or s.get("summary")
                    ),
                )
                for s in (steps or [])
            ]
            _done = sum(1 for s in _steps if s.status not in ("pending",))
            enqueue_card_write(
                CardState(
                    card_id=card_id,
                    conversation_id=conversation_id,
                    card_relation=card_relation,
                    plan_title=plan_title,
                    mode=mode,
                    steps=_steps,
                    current_step=_done,
                    total_steps=total_steps or len(_steps),
                    terminal_state=terminal_state,
                )
            )
        except Exception as exc:  # noqa: BLE001 â€” persistence must never block a card emit
            logger.debug(
                "[AgentKernel] card persistence skipped (card_id=%s): %s",
                card_id, exc,
            )

    def _der_count_tool_call(self, item=None) -> None:
        """One real tool call finished in this turn. At the
        MIN_TOOL_STEPS_FOR_CARD-th call a card-free turn EARNS its card: the
        gate is released and the card starts with the steps' state so far.
        Runs on node threads; never raises, never blocks the node."""
        hold = getattr(self, "_der_card_hold", None)
        if not hold:
            return
        try:
            from backend.agent.artifact_policy import (
                MIN_TOOL_STEPS_FOR_CARD,
                release_card_for_turn,
            )

            with hold["lock"]:
                hold["calls"] += 1
                if hold["calls"] < MIN_TOOL_STEPS_FOR_CARD or hold.get("released"):
                    return
                hold["released"] = True
            _turn_id, queue, plan = hold["turn"], hold["queue"], hold["plan"]
            if getattr(self, "_suppressed_card_turn", None) != _turn_id:
                return  # the turn ended or another turn began
            release_card_for_turn(_turn_id, self.conversation_id)
            self._suppressed_card_turn = None
            _done, _failed = set(queue.completed_ids), set(queue.failed_ids)
            _running = getattr(item, "step_id", None)
            steps = [
                {
                    "id": it.step_id,
                    "description": it.description,
                    "status": ("done" if it.step_id in _done
                               else "failed" if it.step_id in _failed
                               else "running" if it.step_id == _running
                               else "pending"),
                    "stepNumber": it.step_number,
                    "toolName": _step_tool(it),
                }
                for it in list(queue.items)
            ]
            _card_id, _ = self._resolve_card_identity(_turn_id, "initial")
            _mode = queue.mode.value if getattr(queue, "mode", None) else "full"
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.TASK_START,
                data=self._task_start_payload(
                    task_id=_turn_id,
                    description=(getattr(plan, "original_task", "") or "")[:120],
                    plan_title=self._effective_plan_title(plan),
                    mode=_mode,
                    steps=steps,
                    total_steps=len(steps),
                    origin="initial",
                    card_id=_card_id,
                    # The frontend never saw this card: it starts one.
                    card_relation="new",
                    conversation_id=self.conversation_id,
                    turn_id=_turn_id,
                    **self._multiagent_tags(),
                ),
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
                session_id=hold["session"],
            )
            self._persist_card_snapshot(
                card_id=_card_id,
                conversation_id=self.conversation_id,
                card_relation="new",
                plan_title=self._effective_plan_title(plan),
                mode=_mode,
                steps=self._queue_steps_snapshot(queue),
                total_steps=len(queue.items),
                terminal_state="running",
            )
            logger.info(
                "[AgentKernel] task card earned at tool call %d (bound >=%d) turn=%s",
                hold["calls"], MIN_TOOL_STEPS_FOR_CARD, _turn_id,
            )
        except Exception as exc:  # noqa: BLE001 - a card never blocks the work
            logger.warning("[AgentKernel] card release failed: %r", exc)

    def _log_surface(
        self,
        *,
        turn_id: Optional[str],
        lane: str,
        had_show: bool,
        bubble_source: str,
        card_suppressed_reason: Optional[str] = None,
    ) -> None:
        """Per-turn surface decision log (specs/reply-surface-contract REQ-9).

        One structured line per reply: the lane chosen (plain / card /
        card_plus_summary), whether a `show` payload was present, and where
        the bubble text came from. `card_suppressed_reason` marks the distinct
        "card suppressed" signals (AC2) â€” "no_show_payload" on plain turns and
        "empty_websearch_synthesis" on the show-downgrade path. Logging only:
        REQ-9 AC3 keeps instrumentation off the critical path. Never raises.
        """
        try:
            logger.info(
                "[AgentKernel] surface_decision turn=%s lane=%s had_show=%s "
                "bubble_source=%s card_suppressed_reason=%s",
                turn_id or "unknown",
                lane,
                had_show,
                bubble_source,
                card_suppressed_reason or "-",
            )
        except Exception:  # noqa: BLE001 â€” instrumentation never blocks
            pass

    def _emit_reply_progressively(
        self,
        response: str,
        turn_id: str,
        chunk_callback=None,
    ) -> None:
        """Speak-first progressive reply (specs/reply-surface-contract REQ-13
        AC1/AC3, task T18).

        The bubble and TTS must NOT wait for the document. So the agent's
        `speak` line is the FIRST chunk downstream; the `show` body follows as
        the seam's DOCUMENT_RENDER (single whole-body emit â€” the bound
        providers do not stream a partial card, per the spec's fallback rules;
        the partial channel in T18b exists for when they do).

        Chunk discipline:
          - plain text (no `show`): the full text is the ONE chunk (unchanged
            from the previous single-chunk path).
          - `show` + `speak`: `speak` is the FIRST (and only) text chunk; the
            card body streams via the render event, never in the text stream â€”
            pre-contract this path sent the raw structured JSON into the TTS
            sentence queue.
          - `show` without `speak`: no text chunk; the seam supplies the
            supportive excerpt as the final bubble.

        Always emits the force-flush sentinel (``""``) last â€” the sentence
        queue terminates on it. Never raises.
        """
        if not response or chunk_callback is None:
            return
        try:
            chunk_text: Optional[str] = None
            try:
                from backend.agent.structured_response import (
                    parse_structured_response,
                )

                speak, show = parse_structured_response(response)
                if speak:
                    chunk_text = speak
                elif show is None:
                    chunk_text = response
            except Exception:  # noqa: BLE001 â€” parse failure -> plain fallback
                chunk_text = response
            if chunk_text:
                chunk_callback(chunk_text)
            chunk_callback("")  # force-flush end-of-stream
        except Exception:  # noqa: BLE001 â€” a streaming failure never kills a turn
            logger.warning(
                "[AgentKernel] progressive reply emit failed turn=%s",
                turn_id or "unknown",
            )

    @staticmethod
    def _supportive_text(text: str, max_chars: int = 200) -> str:
        """First-sentence excerpt for the supportive spoken/chat bubble.

        The prism card carries the FULL synthesized document; the text/speech
        response is a short complement (first 1-2 sentences, ~max_chars) so the
        bubble and the card never duplicate each other (user contract
        2026-07-31: text supports the rendered document). Strips markdown
        decorations lightly. Returns '' when nothing usable remains.
        """
        _t = (text or "").strip()
        if not _t:
            return ""
        # Light markdown strip for a clean spoken excerpt.
        _t = re.sub(r"```[\s\S]*?```", " ", _t)
        _t = re.sub(r"^#{1,6}\s*", "", _t, flags=re.MULTILINE)
        _t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", _t)  # images
        _t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", _t)  # links -> label
        _t = re.sub(r"[*_`>|]", " ", _t)
        _t = re.sub(r"\s+", " ", _t).strip()
        if not _t:
            return ""
        _parts = re.split(r"(?<=[.!?])\s+", _t)
        _out = ""
        for _p in _parts:
            if _out and len(_out) + len(_p) > max_chars:
                break
            _out = (_out + " " + _p).strip()
            if len(_out) >= max_chars * 0.7:
                break
        if not _out:
            _out = _t[:max_chars]
        if len(_out) > max_chars:
            _out = _out[:max_chars].rstrip() + "â€¦"
        return _out
