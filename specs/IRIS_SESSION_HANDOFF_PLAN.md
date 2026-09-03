# IRIS Launcher → Widget Session Handoff Plan

## Status
Draft v1.0 — ready for review before implementation

## Problem Statement

The Launcher and Widget are now decoupled processes (Phase 1 complete). They currently share state only through the Python backend API. This works for mode/identity, but it does **not** provide:

1. A secure session token handoff from Launcher to Widget
2. Biometric-gated access to the Widget
3. A production-ready way for the packaged Tauri Launcher to authorize the packaged Tauri Widget

The MEMORY_SEPARATION.md spec calls for OS keychain-based session handoff. This plan defines how to implement that **without restricting ongoing development or manual testing**.

## Core Principle: Dev-First, Never Blocking

> **No implementation in this plan may require biometric auth, a secure store, or a packaged Tauri build to run the app in dev mode.**

Every feature must have a dev fallback so development and manual testing continue uninterrupted.

---

## Architecture

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│   IRIS Launcher │         │   OS Keychain   │         │   IRIS Widget   │
│   (Tauri/Vite)  │────────▶│  (shared store) │────────▶│  (Next.js/      │
│                 │  write  │                 │  read   │   Tauri)        │
└─────────────────┘         └─────────────────┘         └─────────────────┘
         │                                                       │
         │                                                       │
         ▼                                                       ▼
┌─────────────────┐                                 ┌─────────────────┐
│  Python Backend │◀────────────────────────────────│  Python Backend │
│   (port 8000)   │      mode / identity / state    │   (port 8000)   │
└─────────────────┘                                 └─────────────────┘
```

### What goes in the keychain?

| Field | Purpose | Lifetime |
|-------|---------|----------|
| `session_token` | JWT-style opaque token proving the Launcher authorized this session | 24 hours, refreshed on use |
| `mode` | `personal` or `developer` | same as token |
| `node_id` | Post-quantum identity handle | same as token |
| `key_fingerprint` | Hash of the backend encryption key (binds session to this install) | same as token |

The backend encryption key (`IRIS_Memory_Foundation`) stays backend-only. The Launcher never touches it.

---

## Three Runtime Modes

The implementation must support three modes cleanly:

### Mode A — Dev Web (Vite + Next.js in browser)
- **Biometric**: skipped
- **Keychain**: not used
- **Handoff**: via existing backend API + URL params for non-sensitive data
- **Usage**: primary day-to-day development and manual testing

### Mode B — Dev Tauri (Tauri windows, but dev/debug)
- **Biometric**: optional, controlled by env flag `IRIS_REQUIRE_BIOMETRIC=0`
- **Keychain**: used for session token if available, otherwise falls back to backend API
- **Handoff**: Tauri secure store → Widget reads via Tauri API
- **Usage**: testing packaged behavior without blocking on auth

### Mode C — Production Tauri (packaged builds)
- **Biometric**: required unless disabled by user in settings
- **Keychain**: required for session token
- **Handoff**: mandatory Tauri secure store
- **Usage**: end-user packaged builds

---

## Implementation Phases

### Phase 1 — Shared Session Schema (no UI changes)

**Goal**: Define the contract so Launcher and Widget agree on token format.

**Tasks**:
1. Create `shared/types/session.ts` (or `contracts/session.ts`) with:
   ```ts
   export interface IrisSession {
     token: string;           // opaque JWT, signed by backend
     mode: "personal" | "developer";
     nodeId?: string;
     keyFingerprint: string;
     issuedAt: number;
     expiresAt: number;
   }
   ```
2. Add backend endpoint `POST /auth/session` that:
   - Accepts `{ mode, identity_proof? }`
   - Validates identity (biometric proof in prod, dev override in dev)
   - Returns `IrisSession`
3. Add backend endpoint `GET /auth/session/validate` that verifies the token.

**Dev impact**: none. New endpoints, no callers yet.

**Manual testing**: can test endpoints with curl/Postman.

---

### Phase 2 — Launcher Writes Token (opt-in)

**Goal**: Launcher can obtain and store a session token.

**Tasks**:
1. Add Tauri secure-store plugin to `iris-launcher/src-tauri/Cargo.toml` (only affects Tauri build).
2. Add Tauri command `store_session(session: IrisSession) -> Result<(), String>` that writes to OS keychain.
3. Update `ModeSelectPage.tsx`:
   - On mode select, call `POST /auth/session` to get a token.
   - If running in Tauri, call `store_session` to persist it.
   - Always fall back to existing backend `setMode` flow.
4. Add env flag `IRIS_REQUIRE_BIOMETRIC` (default `false` in dev).
   - When `false`, skip biometric prompt.
   - When `true` and no biometric, show settings message (don't block).

**Dev impact**: minimal. The secure-store plugin only loads in Tauri. Web dev uses backend fallback.

**Manual testing**:
- Web dev: mode select still works exactly as before.
- Tauri dev: token is stored if secure store is available.

---

### Phase 3 — Widget Reads Token (with fallback)

**Goal**: Widget reads the session token from the keychain on init, but degrades gracefully.

**Tasks**:
1. Add Tauri secure-store plugin to `src-tauri/Cargo.toml` (Widget Tauri).
2. Add Tauri command `read_session() -> Result<Option<IrisSession>, String>`.
3. Update Widget initialization:
   - On app mount, try `read_session()`.
   - If token exists and is valid, use it.
   - If no token or invalid, fall back to existing backend API auth.
   - In web dev, always use backend API fallback.
4. Add `try/catch` around every keychain call — never block startup on keychain failure.

**Dev impact**: minimal. Web dev never calls Tauri commands.

**Manual testing**:
- Web dev: Widget loads via backend as before.
- Tauri dev: Widget reads token if stored.

---

### Phase 4 — Biometric Gate (production-only)

**Goal**: Require biometric approval before Launcher writes the token.

**Tasks**:
1. Implement Tauri command `verify_biometric() -> Result<bool, String>` using OS APIs:
   - Windows: Windows Hello via `webauthn` or Tauri plugin
   - macOS: Touch ID / LocalAuthentication
   - Linux: fprintd / PAM (optional, can be disabled)
2. In `ModeSelectPage.tsx`:
   - If `IRIS_REQUIRE_BIOMETRIC=true`, call `verify_biometric()` before requesting session token.
   - If biometric fails, allow user to disable biometric in settings (opt-out).
3. Store a `biometric_enabled` flag in backend settings.

**Dev impact**: zero. Biometric is only required when the flag is explicitly enabled.

**Manual testing**: test biometric flow only when `IRIS_REQUIRE_BIOMETRIC=1` is set.

---

### Phase 5 — Remove Legacy Spawn Path

**Goal**: Clean up the old `launch_iris_widget` command.

**Tasks**:
1. Delete the `launch_iris_widget` command from `iris-launcher/src-tauri/src/main.rs` (already done in Phase 1).
2. Delete the `launch_iris_widget` references from frontend (already done in Phase 1).
3. Remove the `IRIS_WIDGET_PATH` environment handling.
4. Document the new launch flow:
   - Dev: start backend, start widget, start launcher, open widget from launcher
   - Production: OS launches Widget independently; Launcher writes token; Widget reads token

**Dev impact**: none. The spawn path was already removed.

---

## Development Workflow (preserved)

### Daily dev commands

```bash
# Terminal 1 — backend
python start-backend.py

# Terminal 2 — widget
node node_modules/next/dist/bin/next dev -H 0.0.0.0 -p 3000

# Terminal 3 — launcher
cd iris-launcher
node node_modules/vite/bin/vite.js --port 8080 --host
```

### Test packaged behavior without blocking

```bash
# Tauri dev with biometric skipped
$env:IRIS_REQUIRE_BIOMETRIC="0"
npm run tauri dev
```

### Test production biometric flow

```bash
# Tauri dev with biometric required
$env:IRIS_REQUIRE_BIOMETRIC="1"
npm run tauri dev
```

---

## Manual Test Checklist

| Test | Mode | Expected Result |
|------|------|-----------------|
| Web dev: select mode → open widget | Dev web | Works with backend API only, no keychain |
| Tauri dev: select mode → open widget | Dev Tauri, `IRIS_REQUIRE_BIOMETRIC=0` | Token stored and read |
| Tauri dev: biometric prompt | Dev Tauri, `IRIS_REQUIRE_BIOMETRIC=1` | Prompts for Windows Hello, then stores token |
| Widget without token | Any | Falls back to backend API, no crash |
| Widget with expired token | Any | Refreshes token or falls back |
| Backend restart | Any | Widget reconnects via existing API |

---

## Open Questions

1. **Token signer**: Should the backend sign the session token, or should the Launcher sign it?
   - *Recommendation*: Backend signs it. Launcher only forwards it.

2. **Token refresh**: Should the Widget refresh the token automatically, or should it expire and require re-auth?
   - *Recommendation*: 24h expiry; Widget can refresh via backend if still authorized.

3. **Identity binding**: Should the session token be bound to the biometric key fingerprint?
   - *Recommendation*: Bind to `keyFingerprint` so a token is useless on another machine.

4. **Browser dev**: Should we support keychain-less token handoff via a local HTTP endpoint?
   - *Recommendation*: Yes. `GET /auth/session` endpoint returns the current valid session for the same-origin Widget.

---

## Files to Create/Modify

### New files
- `shared/types/session.ts`
- `backend/routers/auth.py` (or extend existing auth router)
- `docs/IRIS_SESSION_HANDOFF.md` (this doc)

### Modified files
- `backend/main.py` — add `/auth/session` endpoints
- `iris-launcher/src-tauri/Cargo.toml` — add secure-store plugin
- `iris-launcher/src-tauri/src/main.rs` — add `store_session` and `verify_biometric` commands
- `iris-launcher/src/pages/ModeSelectPage.tsx` — request and store token
- `src-tauri/Cargo.toml` — add secure-store plugin
- `src-tauri/src/main.rs` — add `read_session` command
- `app/layout.tsx` or Widget init — read token on startup

---

## Success Criteria

- [ ] Dev web mode works unchanged (no Tauri, no keychain, no biometric)
- [ ] Dev Tauri mode stores/reads session token without biometric prompt
- [ ] Prod Tauri mode requires biometric approval before opening Widget
- [ ] Widget never crashes if token is missing or invalid
- [ ] Session token is bound to this install (won't work if copied to another machine)
- [ ] Backend startup remains under 15 seconds (Phase 2 lazy-import fix preserved)
- [ ] All existing manual tests continue to pass

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Tauri secure store plugin breaks dev web build | Plugin is only loaded in Tauri; web build uses backend fallback |
| Biometric API unavailable on some machines | Allow opt-out in settings; fall back to backend API |
| Keychain read fails on Linux | Skip keychain, use backend API fallback |
| Session token expires during use | Widget refreshes token or falls back to backend |
| This work blocks ongoing development | Each phase is opt-in; dev default remains unchanged |

---

## Next Step

Review this plan. Once approved, start with **Phase 1** (shared session schema + backend endpoints) because it has zero impact on the current dev workflow.
