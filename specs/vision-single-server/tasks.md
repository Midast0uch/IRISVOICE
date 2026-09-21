# Spec: vision-single-server — Tasks

Gates: run the affected test file after every task. THE TEST RULE applies —
existing tests define requirements; when the spec REPLACES an old contract,
the task list names the test rewrite explicitly (that IS the requirement change).

## Wave 1 — surgical removal (spawn gone, behavior holes allowed to exist yet)
- [ ] T1: lfm_vl_provider.py — delete spawn/warm/idle/owned-PID chain
      (design §D4). ADD nothing. Module still imports; fetch/search/operator
      entry points unchanged in signature.
- [ ] T2: NEW contract test: no-spawn-surface AST guard on lfm_vl_provider.
- [ ] T3: Delete spawn-pinning test files (design list). Green gate: remaining
      suite minus rewrites-to-come.
- Gate TG-1: `python -m pytest backend/tests -k "vision" -q` — only the tests
  DESIGNATED for rewrite may fail; list them in the gate note.

## Wave 2 — borrow-only semantics
- [ ] T4: `_ensure_vision_server_running` = health fast-path + discovery;
      no lock, no leader spawn. `VisionModelUnavailable` when nothing borrowed.
- [ ] T5: router.py tier-3 rewrite (D3): discovery-backed VisionResolution;
      drop model_path/mmproj/requires_load/takes_lease for tier 3.
- [ ] T6: Rewrite tier-3 test rows (test_vision_server_reuse_contract C4,
      test_vision_lease, tier permutations, capability resolution, hierarchy
      wiring, cohere integration scenario A, t43 lifecycle).
- Gate TG-2: all rewritten tests green; no spawns observed anywhere.

## Wave 3 — ports, config, gateway, UI ladder
- [ ] T7: remove vision_port from config files + tolerant load; delete
      start_vl.*, env knobs; rewrite gateway error strings.
- [ ] T8: iris_gateway prewarm/warm-search/idle-stop blocks removed;
      `_handle_set_vision_enabled` is a flag, not process control.
- [ ] T9: auto-register the shared multimodal server as a LOCAL_OPENAI
      provider when LocalModelManager's active model has a projector (D5-D6 #5);
      vision card dropdown pin still honored.
- Gate TG-3: boot clean, `get_vision_status` WS sane, suite green.

## Wave 4 — live gate
- [ ] T10: Load shared multimodal model via UI (LFM2.5-VL-3B + projector on
      server). Run docs/LIVE_TEST_VISION_BROWSER_E2E.md — natural prompt,
      no tool hints. Assert: [vision-timing] present, acquire p95 < 2s,
      answer grounded in visited pages, panel reflection, ≤ 5 min total.
- [ ] T11: Run the multi-prompt VLM battery (see LIVE_TEST doc §LT-7):
      price lookup, screenshot-led answer, read-a-chart page, login-wall
      ask path, form/navigation task. Each grounded + ≤ budget.
- Gate TG-4: live evidence pinned; measure_vision_latency.py baseline written
      into the criteria doc; landmark crystallized.
