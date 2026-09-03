# Tasks: Model Selection Authority

> Each task links to a requirement. DONE = 20-cycle real-backend soak green + existing provider trio green + dropdown shows loaded local model. NOT THIS = touching STT/TTS/wake-word, paid-API verification, frontend redesign, transport retry policy.

## Wave 0 — Discovery (blocks Wave 1 scope)
- [ ] T0 (REQ-4): Locate the loaded-local-model dropdown break — trace scan → registry → snapshot → `buildModelOptions` with a loaded model present; classify REAL GAP vs already-wired. Files: `local_model_manager` scan, `inference/registry`, `status_snapshot.py:123`, `ModelInferenceSection.tsx:140-166` — RIPPLE: determines whether Wave 1 touches frontend at all.

## Wave 1 — Authority core (backend)
- [ ] T1 (REQ-5, REQ-3): Schema — `provider_selected_at` on InferenceConfig + per-binding stamps, migration default 0.0 — `iris_config.py:277` — RIPPLE: `configure_logging`-style readers unaffected (additive field); old configs load unchanged.
- [ ] T2 (REQ-1, REQ-5): Choke-point — stamp + persist + broadcast on every explicit bind path (`set_model_selection` preserve=False, confirm_card switch branch, `set_role_binding`) + one authority-chain log line — `agent_kernel.py:14383`, `iris_gateway.py:1613/6815` — RIPPLE: frontend senders unchanged (NO CHANGE verified); snapshot shape extended (CT-SNAPSHOT-1).
- [ ] T3 (REQ-3): Boot restore — newer-record-wins + bind-iff-empty, replacing the flat-stale heuristic — `main.py:604-642` — RIPPLE: router seed logic untouched (still skip-if-bound); relies on T1 stamps.
- [ ] T4 (REQ-4): Local-visibility fix per T0 findings — RIPPLE: per T0 map; if frontend-only, a NO-CHANGE-verified backend + targeted component fix.
- [ ] T4b (REQ-2): Swarm-defer seam — switch during swarm persists timestamped intent + snapshot flag + authority log (application itself belongs to the swarm spec) — RIPPLE: gateway emit path only; no swarm logic.

## Wave 2 — Contracts (after T1–T3 land)
- [ ] T5 (REQ-1, REQ-2, REQ-6): `tests/contract/test_selection_authority.py` — CT-ROLE-1, CT-SNAPSHOT-1, CT-AUTHORITY-1, CT-PERSIST-1, echo-preserves-splits, catalog-guard — RIPPLE: locks interfaces for `ModelInferenceSection`, `ModelSwitcher`, `WheelView`, `SidePanel` senders.
- [ ] T6 (REQ-2): Existing trio green unmodified — `test_provider_switch_keeps_own_model`, `test_provider_survives_restart`, `test_chat_row_and_card_agree` — RIPPLE: proves no behavior drift in covered paths.

## Wave 3 — Real verification (after T5–T6 green)
- [ ] T7 (REQ-1, REQ-3): Standing harness `scripts/validate_model_selection_e2e.py` — real backend + real local GGUF + real WS: switch → turn served locally (no `api.*` POST) → restart → bindings persist → fresh-client remount (zero sends) → no drift; 20-cycle soak — RIPPLE: exercises gateway, kernel, router, config, snapshot together (seam coverage unit tests cannot give).
- [ ] T8 (REQ-4): Local-model e2e — load GGUF → snapshot contains instance → dropdown options (assert via `/api/inference/state` + option-builder logic) → select → local turn, zero API spend → unload mid-binding → visible fallback + user message, keys retained on switch-back.
- [ ] T9 (REQ-2, REQ-3): Negative matrix — stale-flat-vs-fresh-bindings both directions, corrupt config, unknown-instance bind, empty-model APPLY, downgrade field-drop — each asserts the specified safe outcome.

## Wave 4 — Lock-in
- [ ] T10: Docs — `docs/architecture/audio-pipeline.md` selection section? No — correct home is the inference/model docs + this spec's Decisions Locked; update `backend/core/README.md`-style config docs for the new field. Record MCM events + pin + landmark.

## Dependency / parallelization notes
- T0 first — it alone can change Wave 1's frontend scope.
- T1 → T2 → T3 is sequential (schema, then writers, then restore).
- T4 parallels T1–T3 once T0 has mapped it (different files unless T0 says otherwise).
- T5 needs T1–T3 code shapes final; T6 runs anytime (no code changes).
- T7 needs a GGUF on disk (Phase 0 confirms which; LFM2.5-8B preferred) + backend launchable; no API keys anywhere in the loop.
- Contract tests (T5) and the harness (T7) share assertion vocabulary (binding equality, authority-line presence) — intertwined by construction.
