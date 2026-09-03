# IRIS Voice Session 268 — Handoff Document

**Purpose:** Record every problem hit during this session, the exact root cause, the
fix applied, file paths + line numbers, and the items that remain unfixed. Hand
to another agent for review, further fixes, and testing.

**Date:** 2026-08-28
**Branch:** `feat/agent-multi-step-tool-execution`
**Backend PID (current):** 408 (port 8090)
**Frontend dev server:** Next.js on 3000 (PID 20120, restarted)
**Widget:** iris-widget PID 8900
**Model state:** Bonsai-27B-Q1_0 still loaded (llama-server PID 11156, port 8082)

---

## 0. Session 269 Progress Update (2026-08-28, applied on top of this handoff)

### 0.1 Item 3.1 (unload blocker) — FIXED in code, pending live verification

**Root cause found (pin_d01ed2bc1983) — it was two frontend bugs, not a stale WS:**

1. **Unload confirmation re-armed the spinner.** Backend sends
   `local_model_status {loaded: false}` on unload completion — it carries NO
   `status` string. `ModelBrowserPanel`'s WS handler keyed only on
   `status === 'ready'|'loaded'|'unloaded'`, so the confirmation fell into the
   `else` branch and called `setIsLoading(true)`. After one unload the panel
   was stuck "loading".
2. **`doUnload`'s `if (isLoading) return;` then silently swallowed every
   subsequent Unload click** — no message sent (matches the empty backend
   log), no user feedback. Combined with the 98%-freeze stuck state, Unload
   was permanently unreachable. llama-server PID 11156 survived because the
   backend unload path (which is correct — terminate→kill escalation +
   `kill_orphan_servers()` by name) was never invoked.

**Fixes applied:**
- `components/dashboard/ModelBrowserPanel.tsx` — `doUnload` guards on
  `loadPhase === 'unloading'` only (unload is the escape hatch for a wedged
  load); WS handler treats `local_model_status` `loaded`-flag snapshots as
  terminal; 30s bounded unload wait → clears spinner, shows error, reconciles
  via `fetchModels()`; console diagnostics added.
- `hooks/useIRISWebSocket.ts` — `get_local_model_status` added to BOTH
  reconnect bursts (browser path + Tauri `ws:connected` path), so a terminal
  event missed during a disconnect is re-fetched (closes handoff 3.5).
- `components/chat-view.tsx:4083` — pre-existing type error fixed
  (`capturePage?: string` → `number`; canonical type is `useCrawl.ts:33`).
  `npx tsc --noEmit` is now clean.

**FINDING (pin_b2439c7e8735):** `test_load_local_model_with_projector_backcompat_contract.py`
pinned the PRE-268 projector contract and FAILED against the 1.8 fix — the
"44/44 pass" claim was wrong. Updated to pin the REVERSED contract (absent
`with_projector` = text-only brain; explicit `true` = attach; manager-level
default `True` for direct callers unchanged).

**Contract tests added:** `test_field_update_alias_contract.py` (3.6 — real
dispatcher, alias + legacy + unknown-type guard), `test_state_isolation_update_field_contract.py`
(3.7), `test_no_autounload_on_empty_path.py` (3.8 — 4 cases incl. models_directory),
`test_load_defaults_text_only.py` (3.9 — WS boundary + `--mmproj` argv layers).

**Additional findings while closing 3.6–3.9 (pins pin_b2439c7e8735, pin_c665e66cd37b):**
- `test_local_model_status_baseline.py` had 4 failures — NOT handler
  regressions. The test double's `load_model` signature predated the
  `with_projector` kwarg, so the gateway's now-always-forwarded
  `with_projector=False` raised TypeError inside the handler. Fixed the
  double (assertions untouched); all 4 pass again.
- Handoff item 3.3 is STALE: `local_model_status = "loaded"` is already
  written only inside the success branch (iris_gateway.py:8923-8948), and
  the failure branch persists `"error"` (T10a intact). No code change needed.
- Load/unload robustness across DIFFERENT models verified: `load_model()`
  kills orphans by name + escalates terminate→kill before spawning;
  switching broadcasts a "switching" state first. Item 3.4 (PID file) is
  redundant — kill-by-name covers orphaned 8082 listeners.

**Test status: 52/52 pass** across the local-model + settings contract set.

**Live verification still needed:** refresh/rebuild the widget, then
Load → Unload → confirm spinner clears, `local_model_status {loaded:false}`
arrives, llama-server dies.

### 0.2 Item 3.2 root-cause analysis (session 269, pin_ced7b0dc3b8f)

Full chain found for "agent stuck in working task card" (conv-81):

1. **browser_pool has no liveness check** — `acquire_browser`
   (`backend/vision/browser_pool.py:287-292`) only checks `_browser is None`.
   A crashed Chromium leaves a stale non-None Playwright object with a dead
   transport → every `browser.new_context()` raises
   `'NoneType' object has no attribute 'send'` (the conv-81 error) — the pool
   NEVER restarts until backend reboot. Fix: `is_connected()` check +
   restart in `acquire_browser`.
2. **Turn budget can't reach in-body hangs** — `_DER_TURN_BUDGET_S` is a
   while-condition (`agent_kernel.py:7519`), evaluated only BETWEEN steps.
   Unbounded in-body regions: sync tool dispatch (`:11702`), steering
   re-plan `_plan_task` (`:8902`, LLM, no timeout — conv-81's last message
   was the steering ack, then silence; budget would have tripped 21:54, next
   log 22:13), step reasoning, post-loop synthesis. Fix: remaining-budget
   deadline on steering re-plan + step execution.
3. **Generic error hides pool-death signature** — screenshot_page_tool
   catches the exception and returns "the page could not be captured", so
   normalize_failure classifies crashed/retryable:maybe and retries hit the
   same dead pool. Moot once fix 1 lands (retries become valid).
4. **No stuck-card reaper** — nothing ever resolves a card stuck at
   `working`. conv-81's card has been `working` since 21:44.

### 0.3 Fixes landed for the stuck-agent class (session 269, pin_b3227e6db006)

1. **Self-healing browser pool** — `acquire_browser` now detects a crashed
   Chromium via `is_connected()`, tears down stale handles, relaunches.
   Contract test `test_crashed_browser_is_restarted_on_next_acquire` pins it
   (29/29 pool+session tests pass).
2. **Turn budget reaches in-body hangs** — DER step execution runs on a
   daemon thread bounded by the REMAINING budget (timeout → honest step
   failure → graft/recovery path); the steering re-plan (`_plan_task` LLM
   call) is bounded the same way (timeout → keep current plan; the revision
   is advisory). 45+19 DER/steering tests pass.
3. **Vision ladder excludes the brain's model** (`_brain_model_paths()` in
   `lfm_vl_provider.py`) — THE "first vision call works, follow-ups fail"
   root cause: the widest-first auto ladder selected Bonsai-27B-Q1_0 (it has
   an mmproj sibling) as the VLM whenever the brain was unloaded (~7GB free
   vs ~4.5GB estimated footprint); selection flip-flopped with brain
   residency, and the 27B "vision server" starved/died against the 8GB card
   once the brain loaded. Proof: `backend/logs/vision-llama-server-20260828-144933.log`
   shows the vision server loading Bonsai-27B-Q1_0.gguf. 24/24 vision tests pass.
4. **Zombie cards reaped** — conv-81's card (terminal_state fail, pending
   steps failed with abort reason) plus 11 other `running` cards older than
   60 min. NOTE: several were ancient test fixtures leaking into the
   production DB (`data/databases/conversation_contexts.db`) — test hygiene
   issue, separate cleanup.
5. FAULTLINE verdict on the stuck case: the write side worked (crashes were
   classified `crashed`/retryable:maybe at the boundary), but (a) per its own
   §11 rule "a taxonomy without a consumer is decoration" — the read-side
   consumers (wall ledger, zero-yield cutoff) cover only crawler paths, so
   screenshot_page failures had NO reader; (b) FAULTLINE types failure
   RESULTS — a hang produces no result to classify, so the taxonomy is
   bypassed entirely, which is why the budget backstop mattered.

(Vision/websearch follow-up spec groundwork map: see MCM pin, not this doc.)


---

## 1. Problems Already Fixed (with code locations)

### 1.1 WebSocket `field_update` was rejected as "Unknown message type"

**Symptom:** Every card field edit fired
`[browser] [IRIS WebSocket] backend error: Unknown message type: field_update`
on the browser console. Every Load, Apply, and slider change in the
dashboard's settings cards went through the same broken path.

**Root cause:** The frontend (`hooks/useIRISWebSocket.ts:1938`) sends
`sendMessage("field_update", { section_id, field_id, value })`. The
backend (`backend/iris_gateway.py:765`) only routed
`["update_field", "update_theme", "confirm_card"]` → `_handle_settings`.
Two different verbs for the same intent. The settings UI writes
a `field_update` per keystroke (per `backend/utils/log_redaction.py:9`).

**Fix:**
- `backend/iris_gateway.py:765` — routes `["update_field",
  "field_update", "update_theme", "confirm_card"]`
- `backend/iris_gateway.py:1179` — `if msg_type in ("update_field",
  "field_update"):`

**Verification:** `backend/tests/contract/test_get_cards_handler.py`
passes; the `field_update` log spam stops after restart with the new
code.

---

### 1.2 IsolatedStateManager.update_field signature mismatch (4 vs 5 args)

**Symptom:**
```
TypeError: cannot unpack non-iterable NoneType object
[ERROR] backend.iris_gateway: Error handling message type field_update from client iris
```
every `field_update`, every keystroke, every Load click. This is the
ROOT cause of every "stuck loading" / "model browser broken" /
"dropdown empty" the user hit. The dashboard was unable to write any
field value back to the backend; every Load / role binding / settings
edit died at the WS handler.

**Root cause:** Two-layer facade drift.
- `iris_gateway.py:1194`: `success, update_timestamp = await
  self._state_manager.update_field(...)` — expects a tuple
- `backend/state_manager.py:64`: `return await
  state_manager.update_field(section_id, field_id, value, timestamp)` —
  passes 5 args
- `backend/sessions/state_isolation.py:100` (before fix): `def
  update_field(self, section_id, field_id, value)` — only 3 args, returned None

The facade returned None; the caller unpacked it → TypeError.

**Fix:**
- `backend/sessions/state_isolation.py:100` — signature now
  `(self, section_id, field_id, value, timestamp=None) -> tuple[bool, float]`
- `backend/sessions/state_isolation.py:144` — `return True, update_ts`

**Verification:** 44/44 contract tests pass
(`test_load_local_model_with_projector_backcompat_contract`,
`test_local_model_status_section_key_contract`,
`test_local_model_status_baseline`, `test_get_cards_handler`,
`test_screenshot_image_documents`).

---

### 1.3 Auto-unload on empty path (config poisoned by re-render)

**Symptom:** After any dashboard card remount, `local_model_status` would
flip to `unloaded` even though the model was still resident. The user
could pick Bonsai, watch it load, then on the next remount it would
unload itself. The persisted `data/iris_config.json` had
`local_model_path: ""` after a vision save — wiping the loaded
model's identity.

**Root cause:** `backend/iris_gateway.py:2072` (before fix):
```python
if (
    cfg.inference.local_model_status == "loaded"
    and path != cfg.inference.local_model_path   # ← fires on empty path
):
    await mgr.unload_model()
```
An empty path from a remounted card is ALWAYS different from the
loaded path → unload fires on every confirm that didn't carry a path.

And `backend/iris_gateway.py:2100` (before fix):
```python
if models_dir:
    cfg.inference.local_model_path = ""  # ← wiped the loaded model's identity
    mgr.set_models_directory(models_dir)
```

**Fix:** `backend/iris_gateway.py:2072-2098` — only unload when
`path and path != cfg.inference.local_model_path`; only overwrite
`local_model_path` when `path` is non-empty; never blank the path on a
`models_directory` save.

---

### 1.4 Stale `local_model_ctx: 64327` made load sit at 0%

**Symptom:** User clicks Load on Bonsai; progress never moves past
"0%"; the load never completes; the dashboard sits forever.

**Root cause:** The dashboard's slider writes whatever the deriver
picked for a different free-VRAM snapshot. Bonsai-27B-Q1_0 (~3.5GB
weights + ~0.9GB mmproj) at `ctx=64327` needs ~18GB; the user's 8GB
card has ~5GB free. The deriver tried to fit and looped
`n_ctx=19292/10654...` without ever crossing `fits=true`.

**Fix (code):** `backend/iris_config.py:427-449` —
`auto_derive_local_ctx(current_free_vram_gb)`. If the saved ctx is too
large for current boot VRAM, reset to `0` (auto-derive).

**Fix (config):** `data/iris_config.json` — `local_model_ctx: 0`,
`gpu_layers: -1`, `profile: balanced`. `0` means "trust the deriver, don't
hardcode anything."

**Opt out:** `IRIS_LOCAL_CTX_HARDCODE=1`.

---

### 1.5 Ghost provider in `inference.providers` (local:gemma kind:API)

**Symptom:** `GET /api/inference/state` returned a ghost
`local:Bonsai-27B-Q1_0` entry with `kind:API model:gemma-4-31b
endpoint:https://api.cerebras.ai/v1`. The Brain/Tool dropdown showed
"Local: Bonsai-27B-Q1_0.gguf" but routed to Cerebras. Persisted from
a prior role-binding write; never validated on save.

**Root cause:** `backend/iris_gateway.py:2063-2092` (before fix) had
no validation on the providers collection. Any role-binding write
could persist a malformed entry.

**Fix:** `backend/iris_config.py:342-426` — `validate_providers()`
schema guard. Runs on every `load_config()` AFTER env overrides,
BEFORE returning. Drops `local:*` entries whose kind is not
`INPROCESS/LOCAL_OPENAI` or whose `model_path` is empty or whose
model differs from the current `local_model_id`. Clears (not drops)
`model_path` on non-local entries.

**Verification:** Ghost `local:gemma-4-31b` removed from
`data/iris_config.json` on first load after the fix.

---

### 1.6 Stale `local_model_status="loaded"` on restart → phantom dropdown

**Symptom:** Backend restart; in-process model is gone; config still
says `local_model_status: "loaded"`; the dashboard shows a phantom
"loading model" / "loaded" state for a model that isn't resident.

**Root cause:** Nothing reset `local_model_status` on boot. The
in-process Llama dies with the backend, but the persisted flag
said the model was loaded.

**Fix:** `backend/main.py:362-377` — `Reset stale local-model status
on boot`. If `local_model_status != "unloaded"`, set to `"unloaded"`
and save. Config is now truthful on every boot.

---

### 1.7 Frontend 98% stuck / widget freeze (status 'loaded' not recognized)

**Symptom:** User loads Bonsai; progress reaches 98% and freezes; the
widget becomes non-responsive (can't click or drag); the model IS
loaded on 8082, the provider IS registered, the dropdown data IS
there, but the UI never clears its loading state. On widget refresh,
the user sees "0% loading" again.

**Root cause:** Two bugs:
1. The backend sends `local_model_status` with `status: "loaded"` on
   completion (`backend/iris_gateway.py:9037`). The frontend
   `ModelBrowserPanel.tsx:166` only recognized `status === 'ready'`:
   ```js
   if (pct >= 100 || status === 'ready' || status === 'unloaded') { ... }
   ```
   `status === 'loaded'` did not match → `setIsLoading(true)` stayed
   true → the panel never cleared.
2. When the load completes, the backend fires a burst of events
   (`provider_added`, `local_model_status` ×2, `model_load_event`,
   `_broadcast_inference_snapshot`, `get_available_models`). Each
   dispatches `iris:ws_message`, which the ModelBrowserPanel
   processes. Because the panel never cleared loading, it kept
   calling `setIsLoading(true)` on every one of those events,
   forcing repeated re-renders across the dashboard,
   ModelInferenceSection, and ModelSwitcher. That re-render storm is
   what wedged the WebView's main thread (full app freeze).

**Fix:** `components/dashboard/ModelBrowserPanel.tsx:166` — added
`status === 'loaded'` to the completion check:
```js
if (pct >= 100 || status === 'ready' || status === 'loaded' || status === 'unloaded') {
  setIsLoading(false);
  setLoadingPath('');
  setTimeout(() => fetchModels(), 500);
}
```

**NOT YET VERIFIED live** — requires a frontend rebuild / refresh to
pick up the change. The widget has been killed and restarted; the
fix is on disk.

---

### 1.8 Bonsai + mmproj crash (SIGABRT / 3-min timeout)

**Symptom:** Loading Bonsai-27B-Q1_0 with the mmproj projector
attached caused the llama-server to crash with "signal aborted" after
~3 minutes. The "98% loading" was the synthetic progress heartbeat
idling; the actual server never became ready. The dropdown never
updated.

**Root cause:** The load defaulted to attaching the vision projector
(`with_projector: true`). Bonsai + mmproj needs ~5.13GB VRAM; only
~4.93GB free (the vision server on 18181 holds ~1GB). The
llama-server with `--mmproj` couldn't fit → SIGABRT → 3-min timeout.
The preflight VRAM check (`_preflight_with_ladder`) passed at
~5.9GB free (before the vision server took its ~1GB), so the
projector was attached anyway.

**Fix:** `backend/iris_gateway.py:8735` — default
`with_projector` to `False`. The local model on 8082 is the **brain**;
vision is served **separately** by the 18181 vision server
(LFM2.5-VL-3B). Bonsai loads as a text brain; vision port stays
idle. A caller that genuinely wants a multimodal local model can
opt in with `with_projector: true` (no UI button does this today).

**Architecture statement (pin_8e40f54a98dc):**
- The local model dropdown is **load-only**, not discovery. The
  Models Browser Panel (`GET /api/models` → `scan_models()`) is the
  discovery surface.
- Server-side invariant: a vision-only model (`vision_loaded=true`,
  no chat weights) is never used as a brain. The dropdown shows
  the loaded model; the gate is at bind time.

---

## 2. Frontend State Fixes (already applied)

### 2.1 RichDocument (prism card) inline rendering

**Symptom:** Prisms (MARKDOWN|WEB cards) were bottom-stacked below
all messages, not inline with the assistant text. Scroll snapped to
the bottom of the last prism, not the conversation.

**Fix:** `components/chat-view.tsx:4005` — RichDocument cards now
render INSIDE the `msg-` wrapper, joined on `doc.turnId ===
message.id` (same pattern as task cards). Scroll `useEffect` now
depends on `[renderTimeline]` with `requestAnimationFrame` to wait
for the card to paint before snapping. Orphan fallback
(`chat-view.tsx:4162`) keeps hydration safe.

### 2.2 Empty-result websearch → plain text (not prism)

**Symptom:** An empty websearch ("I wasn't able to pull any direct
image URLs...") rendered as a `MARKDOWN|WEB` prism card. The user
wanted it as plain text inline.

**Fix:** `backend/agent/agent_kernel.py:3814` +
`backend/agent/agent_kernel.py:3966/4148` — backend guards. If
`status="loaded"` and `sources==[]` and text matches failure
phrasing (`"wasn't able to pull"`, `"Image URLs retrieved  0"`,
`"no usable direct image"`, etc.), skip the `DOCUMENT_RENDER`
emit and return as plain text. Defense-in-depth in
`chat-view.tsx:4044` (`_isEmptyResultDoc`).

### 2.3 Format pill removed from prism card

**Symptom:** Redundant "MARKDOWN" pill on every prism card.

**Fix:** `components/chat/RichDocument.tsx:188` — deleted the
`ChassisBadge {format}` block. The `web` pill + expand button
remain.

---

## 3. Items That REMAIN UNFIXED (handoff targets)

### 3.1 Unload never completes (CURRENT BLOCKER)

**Symptom:** User clicks Unload on the loaded model; the spinner
runs; nothing happens; the model is never unloaded; the
llama-server stays on 8082.

**Evidence:**
- llama-server PID 11156 still running (started 2:56 PM, never
  killed)
- `backend/logs/irisvoice.log` shows NO `unload_local_model` WS
  message received — the message never reached the backend
- Widget process (PID 8900) is responding at the OS level
  (`Responding: True`)

**Likely cause (unverified):** The frontend's Unload button is not
sending the `unload_local_model` WS message, OR the WS connection
between the widget and the backend is stale (the widget was killed
and relaunched multiple times this session; the WS reconnect
logic may not have re-attached cleanly).

**Where to look:**
- `components/dashboard/ModelBrowserPanel.tsx:230` — `doUnload()`
- `hooks/useIRISWebSocket.ts` — `sendMessage("unload_local_model", {})`
- `backend/iris_gateway.py:843-844` — `elif msg_type ==
  "unload_local_model": await
  self._handle_unload_local_model(...)`
- `backend/iris_gateway.py:9103` — `_handle_unload_local_model`
  (calls `mgr.unload_model()` which calls `kill_orphan_servers()`
  first — if THAT hangs, unload hangs)

**Suggested fix:** Add a log in the frontend when the Unload button
is clicked (`console.log("[ModelBrowser] doUnload clicked")`); add
a log in the WS hook when the message is sent; add a log in the
backend when the message is received. This will tell us whether
the message is being sent at all.

### 3.2 conv-81 stuck card / screenshot FAULTLINE coverage

**Symptom:** `card_4fde8c28-948` (Search Orca Pod Images) on
conv-81 has been stuck in `working` state since 21:44. Two
`screenshot_page` calls against `orca.wa.gov` returned
`Browser.new_context: 'NoneType' object has no attribute 'send'`
(crashed). The deriver loop never reached synthesis, so the card
never resolved.

**Backend evidence (from earlier logs):**
- `21:44:27` `screenshot_page` → `crashed`
- `21:44:44` `screenshot_page` → `crashed` (same URL)
- No subsequent `DER` log for conv-81 until 22:13
- `Steering the running task. The agent applies this at its next
  step.` is the only frontend message; the next step never
  happens because the browser pool is dead

**Per `docs/architecture/FAULTLINE.md` §8:** "Coverage is crawler
paths + auto-classification at `execute_tool`" — `screenshot_page`
goes through the boundary (`normalize_failure`) so it does get
typed (auto-classified as `crashed`, `retryable: maybe`,
`blame: self`), but the **read side** (wall ledger, zero-yield
cutoff, `IRIS_DER_TURN_BUDGET_S=600s`) only watches
`crawler_query` / `research`. The 38-min screenshot hang past the
600s budget never tripped.

**Suggested fixes:**
1. Register `screenshot_page`'s `Browser.new_context` crash as a
   FAULTLINE label with `retryable: no` (same pool death will
   never succeed on retry).
2. Make `_der_check_steering`'s consumer also fire on `crashed`
   with identical `details.raw`.
3. Move the `IRIS_DER_TURN_BUDGET_S` check into the tool-await
   path so a hung browser kills the turn, not just the gap between
   steps.

### 3.3 Stale `local_model_status` write in `_handle_load_local_model`

**Symptom:** `_handle_load_local_model` (`backend/iris_gateway.py:8927`)
sets `cfg.inference.local_model_status = "loaded"` BEFORE the model
is confirmed loaded. If the load then fails, the config still says
"loaded" even though no model is resident.

**Suggested fix:** Move the `local_model_status = "loaded"` write
into the success branch only (after `mgr.load_model()` returns
True). On failure, set to `"error"` and save.

### 3.4 Port `8082` is "in use" by the dead `llama-server` PID 11156

**Symptom:** Even after `kill_orphan_servers()` and `unload_model()`,
the 8082 listener may persist if the subprocess didn't terminate
cleanly. The current llama-server (PID 11156) has been running
since 2:56 PM and survived multiple backend restarts.

**Suggested fix:** In `unload_model()`, after
`self._process.terminate()` + `wait(timeout=5)`, if the process
is still alive, `kill()` it and `wait()`. Also: PID-file tracking
on the `local_model_manager` so a fresh backend can find and
terminate a stale llama-server from a previous run.

### 3.5 Widget reconnect after kill — WS state not always clean

**Symptom:** When the widget is killed and relaunched, the
`start_ws_client` loop reconnects, but some events sent during
the disconnect window (e.g. `local_model_status` updates) are lost.

**Suggested fix:** On WS reconnect, re-fetch
`/api/inference/state` AND re-send `get_local_model_status` /
`request_state` to re-sync the frontend. The hook already does
some of this (line 1730-1745 error handling); extend it to
re-sync on every reconnect event.

### 3.6 No contract test for `field_update` alias routing

The 5-line fix to `iris_gateway.py:765/1179` has no test pinning it.
Add `backend/tests/contract/test_field_update_alias_contract.py`:

```python
def test_field_update_routed_to_handle_settings():
    # send a field_update WS message; confirm _handle_settings is
    # called and field_value is persisted; confirm backend does NOT
    # log "Unknown message type: field_update"
    ...
```

### 3.7 No test for `IsolatedStateManager.update_field` 5-arg contract

The `state_isolation.py:100` fix has no test. Add
`backend/tests/contract/test_state_isolation_update_field_contract.py`
that asserts:
- Calling `update_field(section, field, value, timestamp=123.0)`
  returns `(True, 123.0)` and persists the value
- Calling without `timestamp` returns a tuple with `time.time()`
  inside it
- The `field_values[section][field]` is set

### 3.8 No test for the auto-unload guard (`path != ""` check)

The `iris_gateway.py:2072` fix has no test. Add
`backend/tests/contract/test_no_autounload_on_empty_path.py`:
- Confirm that an empty `path` in `local_model` confirm does NOT
  trigger `unload_model()`
- Confirm that a non-empty different path DOES trigger unload
- Confirm that a non-empty same path is a no-op

### 3.9 No test for `with_projector: false` default

The `iris_gateway.py:8735` fix has no test. Add
`backend/tests/contract/test_load_defaults_text_only.py`:
- A load without `with_projector` in the payload loads text-only
  (no `--mmproj` in the spawned command)
- `vision_loaded` is False on the resulting provider
- An explicit `with_projector: true` does attach the projector

---

## 4. File Index (all files touched this session)

### Backend
- `backend/main.py` — lifespan startup; removed auto-rehydrate
  (pin_1e00d0424c30); added boot-time status reset (1.6)
- `backend/iris_gateway.py` — `field_update` alias routing (1.1);
  auto-unload guard (1.3); `with_projector: false` default (1.8)
- `backend/agent/agent_kernel.py` — empty-result websearch
  downgrade (2.2); `_is_empty_websearch_synthesis` helper
- `backend/agent/local_model_manager.py` — DO NOT EDIT; the manager
  is correct. The bugs were in `iris_gateway.py` (entry points)
  and `iris_config.py` (validation), not here.
- `backend/iris_config.py` — `validate_providers()` (1.5);
  `auto_derive_local_ctx()` (1.4)
- `backend/sessions/state_isolation.py` — `update_field` 5-arg +
  return tuple (1.2)
- `backend/state_manager.py` — facade unchanged; relies on
  `IsolatedStateManager.update_field` returning the tuple
- `data/iris_config.json` — cleaned (provider=local,
  local_model_path=Bonsai, ctx=0/gpu=-1/balanced, ghost gemma
  removed)

### Frontend
- `components/chat-view.tsx` — RichDocument inline (2.1); empty-result
  downgrade (2.2); orphan fallback
- `components/chat/RichDocument.tsx` — format pill removed (2.3)
- `components/dashboard/ModelBrowserPanel.tsx` — 98% fix (1.7):
  recognize `status: 'loaded'` as completion
- `hooks/useIRISWebSocket.ts` — error logging hardened
- `hooks/useInferenceState.ts` — provider_added / role_bindings_updated
  handlers; no changes needed

---

## 5. Test Status

- 44/44 contract tests pass (load_local_model,
  local_model_status section, get_cards, screenshot_image_documents)
- `py_compile` clean on all modified files
- No regression tests added for the new fixes (see items 3.6-3.9)

---

## 6. Current State (as of session close)

- **Backend:** PID 408, listening on 8090
- **Frontend (Next.js dev):** PID 20120, listening on 3000
- **Widget:** iris-widget PID 8900, responding
- **Bonsai model:** llama-server PID 11156, loaded on 8082 (from
  the user's 2:56 PM load attempt; survived all restarts)
- **Provider:** `local:Bonsai-27B-Q1_0 loaded: true` registered in
  the router
- **Unload:** NOT WORKING — the unload button click does not produce
  an `unload_local_model` WS message in the backend log
- **Widget freeze:** fixed in code (`ModelBrowserPanel.tsx:166`),
  not yet verified live (requires widget refresh / rebuild)

---

## 7. Recommended Next Steps (priority order)

1. **Verify the unload fix path** — add logging at every hop
   (button click → WS send → backend receive → `kill_orphan_servers`
   → subprocess terminate). The bottleneck is either the frontend
   not sending or `kill_orphan_servers` hanging on something.
2. **Verify the 98% / freeze fix** — refresh the widget, load a
   model, confirm 100% and no freeze. If the freeze persists,
   open browser devtools and capture the actual React error / loop.
3. **Add the four contract tests** (3.6-3.9) before the next
   backend restart. They're 5-30 lines each.
4. **Close conv-81** — mark the stuck card `terminated_failed` in
   the conversation store; the FAULTLINE screenshot coverage is
   a longer-term task (3.2).
5. **Tighten `_handle_load_local_model`** (3.3) — write
   `local_model_status = "loaded"` only on success.
6. **PID-file tracking for llama-server** (3.4) — survive
   unclean subprocess termination across backend restarts.
