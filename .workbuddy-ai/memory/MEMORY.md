# IRISVOICE — durable project notes

## Build and release
- `npm run build:static` under WorkBuddy needs:
  `CODEBUDDY_SAFE_DELETE_ENABLED=0 CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD=100000`
- Verify `dist/index.html` after builds; partial builds can leave broken `dist/`.
  `next build` wipes `.next` and the running dev server must be restarted.
- Tauri dev loads `http://localhost:3000`; release loads `../dist`. Release can
  ship stale frontend code even when source is fixed.
- Cargo target output is `C:\temp\tauri-build`, not `src-tauri/target`.
- Minified bundle verification must use surviving string literals, not symbol names.

## Git safety
- `git update-ref` can silently fail/delete empty `refs/heads/feat/*`; write the
  full 40-character SHA to the loose ref and verify `git rev-parse HEAD`.
- An unborn HEAD makes the whole tree appear new; compare against the real tip.
- Session 296 commit: `d8941516a53e5124ac35868a56a95ed3f145c9fc`
  (`fix: recover TTS and preserve chat cards`). Four files, +168/-21. Secret
  scan passed. Only tracked change afterward is the pre-existing `iris-launcher`
  worktree modification.

## Wake/audio facts
- Violawake threshold is 0.70; do not raise toward 0.80. Phrase peaks 0.773–0.786;
  steady silence is 0.401. Installed backbone hash and streaming embeddings are
  verified; do not re-open the hash-mismatch theory.
- Pipeline: 16 kHz, 512-sample frames, 31.25 Hz callback, one embedding/1280 samples.
- `data/hey_iris_synthesized_test.wav` is 24 kHz; resample to 16 kHz before testing.
- TTS commit d8941516: early worker spawn, spawn-measured 300s startup budget, and
  remaining-budget late-ready polling. Measured Pocket-TTS cold start was ~238s.
  Restart backend before live validation.
- `IRIS_STT_WARM_DISABLE` exists but is unset; Parakeet warm-up is expensive.
- Known stale test: `TestTTSWordEventIntegration` lacks the committed audio-pipeline
  mock and may hang; do not treat it as a VAD/model regression.

## Live logs and MCM
- Live backend logs are `.iris-logs/backend-YYYYMMDD-HHMMSS-pidN.log`.
  `backend/logs/irisvoice.log` is stale since 2026-09-03. Backend events are in
  `.iris-logs/backend-events.jsonl`; frontend structured logging is stale since
  2026-08-22, so browser console errors need live DevTools capture.
- Backend :8090 is reachable from Bash with `curl --noproxy '*'`.
- MCM `query_events` is not authoritative for edits; use disk and tests as ground truth.

## Session 296 implementation/verification
- Prism cards: ChatView preserves in-memory documents during history refresh,
  rehydrates joins by DB id or turn_id, routes document responses by payload
  conversation_id, and avoids duplicate orphan rendering.
- Task progress: generic `legacy_unknown` fabrication removed; named crawl cards
  remain supported by REQ-12.
- Provider key selection writes per-provider keys to OS keyring and clears plaintext
  config api_key. Cerebras qwen failure was 402 quota/payment, not auth.
- Validation: Python compile PASS; TypeScript PASS; targeted card/rehydration Jest
  17/17 PASS; TTS real-worker suites 12/12 PASS.

## Testing pitfalls
- On Windows, pytest-timeout can terminate the whole process. Run suspect tests by
  node id and capture output to `C:/temp/`.
- VAD tests need ~0.5s silence calibration before speech frames.
- Full frontend Jest default config is the comparison baseline; the frontend-only
  config runs a smaller subset. Historical baseline was 8 failed suites/11 tests.
