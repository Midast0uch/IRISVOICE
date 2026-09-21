# Spec: vision-single-server — Design + FULL ripple map

Companion to requirements.md. This is the ripple map the removal must cover —
derived 2026-09-18 from a read-only survey at HEAD 564c1784 plus the user's
directive ("cover the entire ripple map once narrowed to one server").

## Architecture after the change

```
resolve_vision_client()                     (router.py:1327)   [KEEP]
  ├─ tier 1/2: brain/tool provider w/ vision → _DirectVisionClient   [KEEP]
  └─ tier 3:   _discover_reusable_vision_server(...)            [KEEP, now the ONLY tier-3]
       ├─ shared local model server :8082 (llama.cpp router-mode, model+mmproj)
       └─ config providers kind=LOCAL_OPENAI/API that verify multimodal
       no candidate → VisionModelUnavailable (loudly)            [REPLACE spawn]
```

The spawn chain `_discover_vision_candidates → _find_vision_model →
_compute_vision_gpu_layers → _spawn_vision_server_now` is deleted end to end.

## D1. Why one server is right
- The 6-minute cold spawn (lfm_vl_provider comment: 3.87s → >100s variance,
  ~6 min class) is paid inside a user turn. A shared server pays its load ONCE
  at user-initiated model load — vision then costs a borrow probe (~ms, cached).
- iris_gateway.py:366-382 already records the intent ('eliminate port 18181').
- Borrow machinery already exists and is contract-tested.

## D2. Structural invariant
`_VISION_SERVER_PID` is deleted entirely (not just stays-None). Idle-stop and
disable() become incapable of killing a shared server by construction.

## D3. tier-3 resolution change (router.py:726-785)
- DROP: `_find_vision_model` import/call, `VisionResolution.model_path /
  mmproj_path / requires_load / takes_lease` semantics for tier 3.
- NEW: tier 3 = run `_discover_reusable_vision_server()`; on success
  `VisionResolution(tier="fallback", provider_id=<endpoint>,
  requires_load=False, takes_lease=False)`; on none → raise
  VisionModelUnavailable.
- `_DirectVisionClient` (router.py:1200s) already serves tier 1/2; tier 3 client
  stays `LFMVLProvider` but its HTTP target is the borrowed endpoint
  (`_active_vision_base_url`). Consider unifying: after discovery, construct a
  `_DirectVisionClient` bound to the borrowed endpoint and serve ALL tiers
  through one client class. (Decision: UNIFY if it does not disturb CT pins on
  the tier ladder; otherwise keep LFMVLProvider as the tier-3 HTTP wrapper.)

## D4. RIPPLE MAP (every touchpoint, verdicts)

### backend/tools/lfm_vl_provider.py (~2268 → target ~900 lines)
- KEEP: borrow chain + `_ensure_vision_server_running` fast-path (health then
  discovery), `_notify_lifecycle` (borrowed warm/error states), `_call`,
  `health_check`, `screenshot_to_bytes`, wrappers, `get_lfm_vl_provider`,
  `LFMVLConfig` (drop base_url default to discovery).
- DELETE: everything in the explorer's §1a table (spawn, warm, idle, lease-
  timer, owned PID, kill, VRAM/ladder for spawn, AV probe, proc liveness).
- CHANGE: `_call` mid-lease respawn removed; `start()`/`disable()` become
  vision-enable toggles with NO process control.

### backend/agent/inference/router.py
- `resolve_vision_provider` tier-3 branch (:226-785 window): CHANGE per D3.
- `resolve_vision_client` (:1327): return borrowed-bound client at tier 3;
  VisionModelUnavailable propagates (already documented).

### backend/iris_gateway.py
- :201 ctor keeps `self._vision_provider = LFMVLProvider()` (health surface).
- :366-382 comment block + `IRIS_VLM_PREWARM` gate: DELETE.
- :422-458 `_prewarm_vlm_server`: DELETE.
- :460-484 `_warm_vision_for_search` + caller :478-480: DELETE.
- :8617-8654 `_resolve_vision_availability`: keep; health = borrowed endpoint.
- :9291-9298 (brain text-only rationale comment): update to new architecture.
- :10939-10966 idle-stop broadcast: DELETE; :10996-11030 lifecycle broadcast:
  KEEP (warm/error on borrow).
- :11032-11089 `_handle_set_vision_enabled`: keep as enable/disable flag; no
  process control.
- :8693/:8779/:8694/:8744/:8780 error strings + hardcoded lfm2.5-vl-3b: REWRITE.

### backend/agent/tool_bridge.py :56-61, :885-895
- keep the `_ensure_vision_server_running` call (now borrow-only); update the
  comment at :56-57.

### backend/vision/fetch_vision.py :308, :603-633
- tolerate lease=None permanently; remove respawn expectations.

### backend/vision/search_discovery.py :367-384 — KEEP (resolver).
### backend/agent/vision_guided_operator.py :60-63 — KEEP.
### backend/tools/vision_mcp_server.py :37-55 — KEEP (desktop surface).
### backend/inference_router.py :310-321 — KEEP (health_check).

### Config / ports / scripts
- iris_config.py: remove `vision_port` (69,75,86) + doc :846.
- data/iris_config.json: drop `"vision_port": 18181` (:127-131). MIGRATION:
  accept+ignore the key on load so old configs don't crash.
- port_checker.py :61,101; main.py :184-204; .env.example :44; README :807:
  remove vision port entries.
- start_vl.bat / start_vl.sh: DELETE files.
- iris_config `vision_fallback_ladder` (:342,:608) + ModelBrowserPanel.tsx
  (:79,121,352-364) + dark-glass-dashboard.tsx (:404-411,:1048) ladder UI:
  REPURPOSE to "vision-capable models the shared server can host" (it currently
  orders SPAWN candidates; after removal its only job is which model the user
  loads on the shared server) — or retire; owner call at Wave 3.

### Tests (existing = requirement, names unchanged where updated)
- DELETE: test_vision_server_spawn_cmd.py, test_vlm_spawn_baseline.py,
  test_vision_readiness_probe.py, test_vision_fallback_ladder*.py,
  test_vision_selection_baseline.py, test_vision_integration.py (spawn form),
  test_vision_fallback_ladder_model_agnostic_contract.py.
- REWRITE: test_vision_server_reuse_contract.py (C4 → no-spawn failure), \
  test_vision_lease.py (never-owned semantics), test_vision_mcp.py +
  tests/integration/test_vision_mcp.py idle/owned cases,
  test_vision_routing_tier_permutations.py tier-3 rows,
  test_vision_capability_resolution.py fallback rows,
  test_vision_hierarchy_wiring.py spies,
  test_vision_reuse_cohere_integration.py scenario A,
  test_t43_vision_gap_closure_contract.py lifecycle states.
- KEEP UNTOUCHED: test_no_direct_lfm_vl_provider_bypass.py,
  test_load_defaults_text_only.py (docstring line update only),
  test_provider_instance_vision_loaded_additive.py,
  test_scan_models_no_projector_rows_contract.py,
  test_vision_persistence_contract.py, test_vision_provenance_trust_contract.py,
  test_vision_harness_contract.py, test_vision_escalation_flag_contract.py.
- NEW: contract test — AST assert lfm_vl_provider has no spawn surface
  (`Popen`, `_spawn`, `_VISION_SERVER_PID`, `acquire_vision_lease` per REQ-2
  AC4 decision).

## D5. Failure modes & migration risk
- Old configs with vision_port: load-time tolerance, then key ignored.
- A running OLD backend must not fight a new one for unknown state: version
  marker in config bumped; iris_gateway logs architecture epoch.
- If the shared server is down mid-run: VisionModelUnavailable surfaces as a
  clean user-facing decline + recorded failed fetch; never a silent text fall-
  back masquerading as vision success (SPEAK the honest outcome).

## D6. Decisions locked
1. Tier-3 = borrowed-only, spawn deleted (owner, option 1).
2. No borrowed server → VisionModelUnavailable (loud) — explorer Open-Q A(i).
3. `_find_vision_model` deleted with spawn (B: yes).
4. `vision_port` field removed, loader tolerant (C).
5. Shared server may ALSO be registered as a LOCAL_OPENAI provider so router
   tier 1/2 can use it when it serves the brain too (D: yes — auto-register
   the LocalModelManager endpoint when its active model is multimodal).
6. Lease API: deleted if fetch_vision tolerates cleanly, else kept as
   documented no-op (decided in Wave 2; default plan: delete).
