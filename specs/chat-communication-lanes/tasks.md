# Spec: chat-communication-lanes — Tasks

- [ ] T1: Monologue screen + recompose fallback in _synthesize_response
      (agent_kernel.py:17534). Unit: synthetic responses (monologue, clean,
      borderline) → correct accept/reject; contract: accepted text contains no
      plan-narration markers.
- [ ] T2: Three-artifact decoder + prompt contract ([RESPONSE FORMAT] updated,
      parser gains third field, back-compat with two-field {speak,show}).
      Contract tests on parse + on auto-render path receiving triples.
- [ ] T3: Auto-render split wired (4262-4380): card=document, chat=supportive,
      spoken=spoken through _finalize_response. Behavioral test: seeded
      evidence → synthesized turn → chat line is NOT a sentence-prefix of the
      document; spoken is the short line.
- [ ] T4: Gateway persistence + payload uses supportive line (5867-5918);
      spoken honored when kernel sets it (5870 does not overwrite kernel
      choice).
- [x] T5: TTS no-consumer guard (one WARN per turn, no flood). Unit:
      no-consumer turn → exactly one skip log; consumer turn → unchanged.
      DONE 2026-09-19 (session 342, P6): `IRISGateway` gained
      `_tts_no_consumer_latch` + `_tts_no_consumer_skip/_latch_set`; wired into
      `_put_chunk` (`iris_gateway.py`) — the stall trip now latches the turn
      (WARN once) and same-turn chunks fail fast with no log; a different turn
      id clears the latch, a 60 s age cap retries once. Latency fix: a repeated
      no-consumer speak attempt now costs one chunk instead of the full 5 s
      stall. Test: backend/tests/unit/test_tts_no_consumer_guard.py (4 tests).
- Gate CL-G: run agent/narration-adjacent suites + new tests green, then one
  live websearch verifying REQ-5 AC1 end to end.
