# Spec: chat-communication-lanes — Requirements

Created 2026-09-18, session 341. Triggered by live test LT-1 run 1
(pin_6914b03ca391): the completed websearch delivered a 105-char internal
monologue as chat+TTS, while the full monologue became the document card.

## The three surfaces (the contract)
1. CARD (document): the full content of what the agent found/did.
2. CHAT TEXT: a short SUPPORTIVE addition that assumes the card exists —
   status, highlight, what to notice — NEVER a copy of the card's opening
   sentences.
3. SPOKEN (TTS): its own shortest sayable line. Distinct from the chat text.
   If the chat text is short enough, TTS may equal it; it must never be a
   truncation of a truncation.

## REQ-1 No internal monologue reaches the user (personal mode)
- AC1: A synthesized answer containing chain-of-thought / plan-narration
  ("We need to browse further", "Let's try opening again", tool references)
  is detected and RE-COMPOSED or rejected before it can become chat/spoken.
- AC2: The stub/stub-ish floor (agent_kernel.py:13237-13244) cannot pass
  planning text. Monologue markers are filtered in `_synthesize_response`
  output validation (agent_kernel.py:17534 area).
- AC3: If recomposition fails, user gets an honest "I couldn't put that
  together" + the card if one exists; never raw monologue.

## REQ-2 Three-way split from one synthesis
- AC1: `_der_synthesize_success_outcome` / `_synthesize_response` produce
  THREE artifacts: {document (may be empty), supportive chat line, spoken line}.
- AC2: Auto-render path (agent_kernel.py:4262-4380): card=document; chat=
  supportive line; spoken=spoken line — wired through `_finalize_response`
  so `_last_spoken_text` carries the spoken line.
- AC3: Explicit {"speak","show"} path (agent_kernel.py:4512-4541) extended to
  a third field (e.g. "show","tell","say": document, supportive, spoken) —
  prompt contract in _build_system_prompt [RESPONSE FORMAT] updated; parser
  (structured_response.py) accepts the new shape; old two-field shape still
  parses (migrate: speak→spoken, supportive defaults to speak).
- AC4: `_supportive_text` (13594) is no longer a first-sentences excerpt of
  the document; it selects/generates the supportive line and asserts
  `supportive != document[:len(supportive)]`-class duplication.

## REQ-3 Gateway delivery honors the split
- AC1: iris_gateway.py:5867-5886: chat_message payload content = supportive
  line; spoken = kernel's spoken line; never `prepare_spoken_text(chat)` when
  the kernel already supplied a spoken line.
- AC2: Persistence (5900-5918) stores the supportive line as the turn text.
- AC3: A websearch that produced a card ends with chat text + card both
  present and non-duplicative (behavioral test).

## REQ-4 TTS no-consumer guard + flood fix
- AC1: The "TTS audio queue stayed full (consumer gone)" flood (observed ~25s
  of ERROR spam at 11:14) is eliminated: when no audio consumer is attached,
  synthesis SKIPS once (log once per turn, at WARN) — no per-frame retries.
- AC2: Speaking still works when a consumer IS attached (existing tests).

## REQ-5 Live evidence
- AC1: After implementation, a live websearch run shows: card with full
  content, chat line that adds to rather than repeats the card, and TTS line
  distinct-or-equal by design. Recorded in docs/LIVE_TEST_VISION_BROWSER_E2E
  run notes.
