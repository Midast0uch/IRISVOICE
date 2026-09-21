# Spec: vision-single-server — Requirements

Status: DRAFT for implementation. Created 2026-09-18, session 341.
Owner decisions locked: option 1 (one shared multimodal server; the standalone
18181 llama-server spawn path is REMOVED, ~6 min cold spawn is unacceptable).

## REQ-1 One server, borrow only
Tier-3 vision NEVER spawns a process. Vision resolves by:
- AC1: Tier 1/2 unchanged — a brain/tool provider whose served model supports
  vision is used in place (router.resolve_vision_provider existing ladder).
- AC2: Tier 3 = the shared multimodal server, discovered via
  `_discover_reusable_vision_server` and verified multimodal by a real 1x1-PNG
  round trip (existing `_probe_vision_capability`). The shared server is the
  local model server (llama.cpp router-mode, currently `LocalModelManager`
  port 8082) when it hosts a model with a projector (`--mmproj`), or any
  config provider of kind LOCAL_OPENAI/API that verifies multimodal.
- AC3: No borrowed/reusable endpoint available → hard `VisionModelUnavailable`,
  a clean user-facing "vision unavailable" — NEVER a spawn, never a silent
  text-only degrade presented as success.
- AC4: `[vision-timing]` stage lines still emit (REQ-8 of the parent spec);
  acquire acquires-instant for a borrowed server (target: acquire p95 < 2s).

## REQ-2 Spawn machinery removed
- AC1: `_spawn_vision_server_now`, single-flight `_spawn_lock/_spawn_attempt`,
  `request_warm`/`_warm_guard`, idle-stop + lease machinery sized to an OWNED
  server, owned-PID tracking (`_VISION_SERVER_PID` and ALL writers),
  `_stop_owned_vision_server`/`_kill_process_tree`, VRAM reserving/ladder scan
  used ONLY for spawn, `_probe_av_latency`, `_proc_cpu_seconds`,
  `_read_log_tail` — ALL deleted.
- AC2: `LFMVLProvider.disable()` and `iris_gateway._handle_set_vision_enabled`
  never kill a shared server; with spawn gone they are structural no-ops for
  process control.
- AC3: `_call`'s mid-lease respawn-retry gone. A shared server that dies
  mid-run = error surfaced, not a respawn.
- AC4: Lease API (`acquire_vision_lease`) either deleted or reduced to an
  always-None no-op; `fetch_vision` tolerates that. Decision: delete if the
  fetch path tolerates it without contract breakage; otherwise keep no-op.

## REQ-3 Port and config cleanup
- AC1: `vision_port` (18181) removed from iris_config.py, data/iris_config.json,
  port_checker.py, main.py, iris_gateway.py, lfm_vl_provider.py defaults.
- AC2: `start_vl.bat`/`start_vl.sh` deleted. `.env*` / README spawn refs
  removed. CHANGELOG historical entries untouched.
- AC3: Gateway error strings that say "run start_vl.bat" rewritten to
  "no shared multimodal server available".
- AC4: `IRIS_VLM_PREWARM`, `IRIS_VISION_READY_MAX_S` env knobs removed;
  `_prewarm_vlm_server` and `_warm_vision_for_search` deleted (nothing to
  warm — the shared server is already up by definition of being shared).

## REQ-4 The shared server carries the multimodal model with mmproj
- AC1: `LocalModelManager` already supports projector flags
  (`test_load_local_model_with_projector_backcompat_contract.py`). Loading
  e.g. LFM2.5-VL-3B (+ its mmproj) through the LOCAL MODEL card makes that
  server vision-borrowable with NO extra process. Verified functionally:
  borrow probe at 8082 passes only when a projector-backed model is loaded.
- AC2: Loading a TEXT-ONLY model there leaves vision unavailable (loudly).
- AC3: Shared-server load cost is paid at model load time (user-initiated),
  NEVER inline in a websearch turn — EXCEPT the P3 empty-slot provision below.
- AC4 (P3, session-342 owner decision — "auto-load, minimal risk, zero
  disruption"): WHEN the shared single-slot server has NO resident model THEN
  the vision resolver MAY load a projector-backed model via
  `LocalModelManager.load_model()` (the same code the UI Apply button runs)
  inline in the turn, bounded by `IRIS_VISION_AUTOLOAD_TIMEOUT_S`. WHEN ANY
  model is resident THEN the resolver SHALL leave it untouched — evicting a
  resident model mid-turn is the disruption this rule forbids; the user fixes
  that once by loading a projector-backed model themselves. AC4 loads are
  single-flight, opt-out via `IRIS_VISION_AUTOLOAD=0`, and degrade to AC3's
  loud unavailability on failure.

## REQ-5 Test rework (the test is the requirement)
- AC1: Spawn-pinning tests deleted: test_vision_server_spawn_cmd,
  test_vlm_spawn_baseline, test_vision_readiness_probe,
  test_vision_fallback_ladder*, test_vision_selection_baseline,
  test_vision_integration (spawn variant).
- AC2: `test_vision_server_reuse_contract` updated: C4 becomes
  "no borrow → VisionModelUnavailable, NO spawn attempted" (assert spawn path
  does not exist).
- AC3: `test_vision_lease` rewritten: no owned PID ever; borrow is never
  stopped/killed by us.
- AC4: `test_vision_routing_tier_permutations` /
  `test_vision_capability_resolution` tier-3 cases rewritten to borrowed-
  resolution semantics; `requires_load`/`takes_lease`/`model_path`/`mmproj_path`
  fields removed or redefined for tier 3.
- AC5: New contract test: LFMVLProvider module contains NO spawn symbols
  (AST scan — `Popen`, `_spawn_`, `_VISION_SERVER_PID` absent).

## REQ-6 Live verification (gate)
Run docs/LIVE_TEST_VISION_BROWSER_E2E.md end-to-end with the shared server:
- AC1: natural prompt (no tool-hint wording) completes ≤ 5 min.
- AC2: [vision-timing] lines present with acquire p95 < 2s (borrowed).
- AC3: at least one real page read visually (screenshot ≥1 per settled state),
  panel shows the crawl events, final answer content matches page content.
