# Spec: chat-communication-lanes — Design

Derived from the full trace of conv-118 (see answer-composition report). Key
mechanics at HEAD 564c1784:

- `agent_kernel.py:4188 _process_structured_response` is the SINGLE exit point.
  `show is None` branch (:4262) auto-renders when zone=reference and
  len>=300; then :4375 `_supportive_text(response)` excerpt becomes the chat
  text and `_last_spoken_text=""` lets the gateway derive speech from it.
- `_supportive_text` (:13594) = first-sentence(s) excerpt → duplicates the card.
- `parse_structured_response` (structured_response.py:35) handles JSON
  {speak, show}; tool envelopes unwrap at :4175.
- Gateway: iris_gateway.py:5867-5886 (content/spoken payload), :5985+ TTS leg,
  prepare_spoken_text (agent_kernel.py:4036) is the spoken fallback.

## D1. Three-artifact synthesis
`agent_kernel._synthesize_response` gets a three-output prompt for reference-
zone turns:
  DOCUMENT: <full content for the card, or NONE>
  CHAT: <short supportive line; assume the card is visible>
  SAY: <one sentence, sayable out loud>
Decoder with per-field fallbacks: missing CHAT → generate short highlight
from evidence titles; missing DOCUMENT → no card (text-only answer path).
Monologue screen (D2) applies before any of this is accepted.

## D2. Monologue screen (personal mode)
A small classifier over the synthesized text: rejects when the response
contains plan-narration patterns (first-person plural process talk,
tool-verbs without results: "we need to", "let's try", "the tool didn't").
On reject: one recompose attempt with a corrective instruction; second
failure → honest-decline text. All three artifacts re-derived only after the
screen passes. Log at INFO with a marker for tests.

## D3. Non-duplication rule
`_supportive_text` replaced by `_compose_supportive(document, chat_line)`:
if chat_line's first sentence is a prefix-match of the document body, reject
and recompose. The behavioral test seeds document+chat and asserts the chat
line is not a sentence-prefix of the document.

## D4. TTS no-consumer guard
iris_gateway TTS leg: track consumer attachment (existing state on the audio
queue). When no consumer: log once per turn at WARN, skip synthesis, continue
text flow. Remove per-0.5s ERROR loops. Deterministic states:
consumer-present → behave exactly as today; absent → single skip.

## D5. SpeakTool untouched
Agent-initiated speak (speak_tool.py) keeps its envelope path; only the FALL
THROUGH text (when no envelope) changes source per D1.

## Ripple map (frontend)
- Frontend needs NO behavior change: chat-view.tsx:3600-3618 already shows
  message.text; :4067-4074 handles spoken-differs; card render unchanged.
  The contract change is backend-authored content.
- useIRISWebSocket.ts: no change (payload shape stable: content + spoken).
