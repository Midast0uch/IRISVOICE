# Spec: Vision Server — Current-State Audit & Reconciliation

**Date:** 2026-07-19
**Trigger:** User reported the agent called `take_screenshot` (which opened/errored) instead of
doing an exa web search for an info-seeking request ("find the speed demons of the ocean").
Investigation revealed the vision server path is stale and has multiple conflicting
implementations. User requested a spec to verify the vision server against current code
before trusting any `take_screenshot` / screen-monitor feature.

**Status:** AUDIT COMPLETE. No code changes made in this spec. Implementation tasks are
proposed (T1–T12) for a follow-up execution session.

---

## 1. What the vision server is supposed to do (from landmarks + code)

- The vision server is a **Llama-CPP-backed VL model** (`vision_mcp_server.py` → `lfm_vl_provider.py`)
  that lets IRIS *see the screen* (describe live frame, detect UI elements, validate actions).
- **Lifecycle (per user + code):** it is NOT always running. It **starts on demand** when the
  agent requests a vision-associated tool, and is **killed when idle/done** (idle-timeout +
  explicit `stop()`). Two start mechanisms exist (see §3).
- Tools exposed by `vision_mcp_server.py`: `vision.describe_live_frame`, `vision.detect_element`,
  `vision.validate_action`, `vision.health`, `vision.stop`, `vision.restart`, `vision.status`.
- `tool_bridge.execute_vision_tool()` maps friendly names (`vision_get_context`,
  `vision_detect_element`, `vision_validate_action`) → `vision.describe_live_frame` etc.

## 2. Audit findings (read against current code)

### F1 — `take_screenshot` has a DUPLICATE, CONFLICTING registration (STALE)
`tool_registry.py` registers `take_screenshot` **twice**:
- Line 252: `ToolSpec(name="take_screenshot", ..., mcp_tool="vision.describe_live_frame", executor="gui", category="vision")`
- Line 280: `ToolSpec(name="take_screenshot", ..., executor="gui", category="vision")` — **no `mcp_tool`**

The second registration wins (last-registered), so the `mcp_tool="vision.describe_live_frame"`
hint is **silently dropped**. This is a latent bug: the registry no longer knows the tool maps
to the vision server. **Fix:** collapse to ONE registration carrying the correct `mcp_tool` + a
description that steers info-seeking away from it (see F4).

### F2 — THREE `take_screenshot` implementations, no single source of truth (STALE/ARCH)
- `automation/operator.py:145` — native GUI operator `take_screenshot(save_path)` → `OperatorResult`
- `mcp/gui_automation_server.py:221` — `gui_automation` MCP server `_take_screenshot`
- `tools/vision_mcp_server.py:118` — `vision.describe_live_frame` (the VL-model path)

The agent's `take_screenshot` (executor="gui") currently routes via `execute_gui_tool` →
`execute_vision_tool("vision_get_context")` → `vision.describe_live_frame`. This is the VL-model
path, which is correct for "IRIS sees the screen" but **bypasses the native operator** that can
actually save a PNG. Need a decision: does `take_screenshot` return a description (VL) or a PNG
(native)? Currently it returns a VL description framed as a screenshot — ambiguous.

### F3 — Two vision-start mechanisms, possibly divergent (STALE)
- `iris_gateway._handle_set_vision_enabled` (line 8734) calls `vl.start()` **eagerly** when the
  user toggles Vision Enabled.
- `lfm_vl_provider._ensure_vision_server_running()` starts it **lazily** on first tool use.

If the user has Vision disabled, the eager path won't run, but the lazy path (`_ensure_vision_server_running`)
should still boot it on `take_screenshot`. The `take_screenshot` fix added in this session calls
`_ensure_vision_server_running()` — consistent with the lazy model. **Verify** the two don't
conflict (double-start is harmless if idempotent; confirm idempotency).

### F4 — `take_screenshot` description invites misuse (ROOT CAUSE of the reported bug)
Original description: `"Take a screenshot of the current screen"` — too generic. The LLM reached
for it on an **info-seeking** request. The session fix rewrote it to steer toward `web_search` for
"find information." This is correct but should be **locked in the spec** so it isn't reverted.

### F5 — `start_screen_monitor` registered but thinly wired (PARTIAL)
- Registered `tool_registry.py:293` (executor="gui", category="vision").
- `execute_gui_tool` now handles it (returns "handled by vision system") but does NOT actually
  start monitoring or call any vision tool. The vision server has no `start_monitor` tool
  (`vision_mcp_server.py` tool list: describe/detect/validate/health/stop/restart/status — no
  monitor). So `start_screen_monitor` is a **no-op stub**. Either implement it (vision server
  needs a monitor tool) or remove it from the registry to avoid a phantom tool.

### F6 — Existing test `test_vision_mcp.py` is STALE relative to current interfaces
Last run ~session 150 (≈12 sessions ago). It tests `vision_mcp_server` singleton + idle lifecycle
+ `describe_live_frame`. It does NOT cover: `take_screenshot` routing, `start_screen_monitor`,
the dual-start mechanisms, or the `tool_bridge.execute_vision_tool` mapping. Needs refresh +
extension before the vision path is trusted.

### F7 — `execute_gui_tool` `take_screenshot` branch depends on `execute_vision_tool` existing
Verified: `execute_vision_tool(tool_name, params, session_id)` exists (line 495) and routes
`vision_get_context` → `vision.describe_live_frame`. The session fix's call
`self.execute_vision_tool("vision_get_context", {}, session_id)` is **valid against current code**.
(Good — the fix is not broken, but it is UNVERIFIED at runtime and the vision server itself may
be stale per F2/F5.)

## 3. Decisions required (do not re-litigate without cause)

- **D1:** `take_screenshot` returns a **VL description** (vision.describe_live_frame), NOT a raw
  PNG. Rationale: IRIS "seeing" the screen = describing it for reasoning, not file I/O. (If a PNG
  is ever needed, add a separate `save_screenshot` tool.)
- **D2:** Single registration for `take_screenshot` (collapse F1), carrying `mcp_tool` + the
  steering description (F4).
- **D3:** Keep BOTH start mechanisms (eager toggle + lazy `_ensure_vision_server_running`); confirm
  idempotent. `take_screenshot` must call the lazy ensure so it works even with Vision toggled off.
- **D4:** `start_screen_monitor` → either implement a real monitor tool in `vision_mcp_server.py`
  or remove it from the registry (no phantom tools).
- **D5:** `web_search` (exa) remains the tool for info-seeking; `take_screenshot` is ONLY for
  "user wants IRIS to see/control the screen." This is the guard that prevents the reported bug.

## 4. Proposed implementation tasks (follow-up session)

- **T1:** Collapse duplicate `take_screenshot` registration (F1) → single ToolSpec with `mcp_tool`
  + steering description (F4/D2).
- **T2:** Verify `_ensure_vision_server_running()` idempotency with `_handle_set_vision_enabled`
  eager start (F3/D3); add a test.
- **T3:** Decide + implement `start_screen_monitor` (F5/D4): add `vision.start_monitor` tool OR
  remove from registry. If implemented, wire `execute_gui_tool` to call it.
- **T4:** Add contract test: `take_screenshot` → `execute_vision_tool("vision_get_context")` →
  `vision.describe_live_frame`, with vision server started on demand (covers F7).
- **T5:** Refresh `test_vision_mcp.py` (F6): extend to cover dual-start, idle-kill, and the
  `tool_bridge` mapping.
- **T6:** Add behavioral test: info-seeking prompt ("find X") resolves to `web_search`, NOT
  `take_screenshot` (locks D5 / prevents regression of the reported bug).
- **T7:** Document the vision lifecycle (start-on-request / kill-when-idle) in AGENTS.md so future
  sessions don't assume the server is always up.
- **T8:** Run full backend suite; confirm no regression from T1–T6.
- **T9:** Commit vision reconciliation (separate commit from the chat-error fixes).
- **T10:** Crystallize a landmark for the vision-server reconciliation.

## 5. Ripple-effect map (what else this touches)

- `iris_gateway.py` (`_handle_set_vision_enabled`) — F3 start mechanism.
- `automation/operator.py`, `mcp/gui_automation_server.py` — F2 native screenshot paths (out of
  scope unless D1 changes).
- `agent/tool_registry.py` — F1/F5 registrations.
- `agent/tool_bridge.py` — F7 routing (already edited this session; verify).
- `tests/test_vision_mcp.py` — F6 stale test.
- Frontend `useIRISWebSocket.ts` — consumes vision events; no change expected.

## 6. Verification gate (all must pass before landmark)

- [ ] `take_screenshot` routes to `vision.describe_live_frame` and starts the server on demand.
- [ ] No duplicate `take_screenshot` registration; `mcp_tool` preserved.
- [ ] `start_screen_monitor` either works or is removed (no phantom tool).
- [ ] Info-seeking prompt resolves to `web_search`, never `take_screenshot` (behavioral test).
- [ ] `test_vision_mcp.py` green + new contract/behavioral tests green.
- [ ] Full backend suite green.
