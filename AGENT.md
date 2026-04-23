# IRIS Voice — MCM Agent Protocol

You are working on **IRIS Voice**, a voice-controlled desktop assistant with Next.js frontend, Python FastAPI backend, and Tauri desktop shell.

## Project Context

- **Frontend**: Next.js 15, React, Tailwind CSS v4, Tauri API
- **Backend**: Python FastAPI, WebSockets, async architecture
- **Desktop**: Tauri (Rust) — borderless widget, system tray, global shortcuts
- **Audio**: Porcupine wake word, WebRTC/STT pipeline, WebSocket streaming
- **Auth**: OAuth handlers, OS keyring for secure credential storage
- **Database**: MCM SDK coordinate graph at `data/databases/coordinates.db`

## NBL Position Map (1-30)

Your NBL state is a fixed 30-integer vector (000-999). Decode positions to know state without tool calls.

| Pos | Meaning | Action Trigger |
|-----|---------|----------------|
| 1 | Landmarks | >5 = mature graph |
| 2 | Warnings | >0 → run health_check() first |
| 3 | Contracts | >3 = strong conventions |
| 4 | Sessions | — |
| 5 | Turn depth | >20 → consider compress() |
| 6 | Active files | — |
| 7-11 | Topology (CORE/ACQ/EXP/EVO/ORBIT) | CORE > 10 = stable codebase |
| 12-14 | Pins (total/permanent/decision) | — |
| 15-17 | Work items (avail/claimed/done) | avail > 0 → claim_work() |
| 18-24 | Coordinates (domain→toolpath) | <100 = weak, >700 = strong |
| 25 | Reasoning mode | 2 = event tracking active |
| 26 | Warning severity | >0 = degraded |
| 27 | Unverified edits | >0 → run tests, record_test() |
| 28 | Context pressure | >800 → prune or compress |
| 29 | Maturity | 2 = mature session |
| 30 | Tool success % | <50 = failing tools, pause |

**When to act on NBL alone (no get_session()):**
- Pos 2 > 0 → health_check()
- Pos 5 > 20 → compress()
- Pos 15 > 0 → claim_work()
- Pos 27 > 0 → record_test() for unverified edits
- Pos 28 > 800 → compress() or prune
- Pos 30 < 50 → stop and diagnose

## Prescriptive Workflow

1. **get_session()** → Decode NBL. Check topology, warnings, landmarks.
2. **navigate(file)** → Read topology BEFORE editing. Trust what it says.
3. **read file ONCE** → Extract what you need. Do NOT re-read.
4. **edit** → Make the change. Keep it minimal.
5. **verify** → Run relevant tests (see stack-specific commands below).
6. **record_edit(file)** → Track the change.
7. **record_test(file, 'pass')** → Confirm verification.
8. **pin_add(title, 'decision')** → Anchor the outcome.
9. **mcm_compress()** → Save checkpoint when task is done.

## Anti-Re-Read Rules (Proven 78% Token Reduction)

- **Read each file ONCE per task.** After reading, trust the DB.
- **After mcm_compress() + mcm_recall()**, do NOT re-read files. Use grep for specific lines.
- **After navigate(file)**, you have topology. Do NOT navigate again.
- **The DB remembers.** Check chain data and pins before re-reading.

## NBL Confidence Thresholds

- **domain > 0.5** (pos 18 > 500): You know this codebase. Navigate directly, don't explore.
- **toolpath > 0.5** (pos 24 > 500): You know the tools. Use them directly.
- **context < 0.2** (pos 22 < 200): New territory. Navigate first, then read, then edit.
- **conduct < 0.2** (pos 19 < 200): Low verification history. Run tests after every edit.

## When to Use MCP Tools

- **pin_search(query)**: Before editing, search for past decisions about this topic.
- **mcm_recall(query)**: After compression, recover what you were doing.
- **health_check()**: If you see warnings in NBL, run this first.
- **record_create(file)**: After creating a new file (not write — that's auto-recorded).

## Cross-Session Resume

If context compacts or session restarts:
1. Call **mcm_recall('previous task')** — find the pin.
2. Trust the chain data — if it says you already edited a file, verify with run_command, then record.
3. Do NOT restart from scratch.

## IRIS Voice-Specific Architecture Rules

### Frontend (Next.js)
- **Tests**: `npm test` or `npx jest`
- **Type check**: `npx tsc --noEmit`
- **Lint**: `npm run lint`
- **Component structure**: Use React Server Components where possible
- **Styling**: Tailwind CSS v4 — use `@theme` and `@import "tailwindcss"`
- **State**: React hooks, avoid global state for UI-only data

### Backend (Python FastAPI)
- **Tests**: `pytest` in backend/ or root tests/
- **Type check**: `mypy` or rely on Pydantic models
- **Async**: All I/O must be async — no blocking calls in endpoint handlers
- **WebSockets**: Use FastAPI WebSocket for real-time audio streaming
- **Auth**: OAuth via `auth_handlers/`, credentials in OS keyring only
- **Audio**: Porcupine wake word detection, streaming via WebSocket

### Desktop (Tauri/Rust)
- **Build**: `cargo build` in src-tauri/
- **Tests**: `cargo test` in src-tauri/
- **Window**: Borderless widget, system tray integration
- **Shortcuts**: Global shortcuts registered via Tauri API
- **Bridge**: Frontend ↔ Rust via Tauri commands and events

### Quality Check — Required Before Every Test Run
Verify ALL of these before running tests:
- [ ] No unnecessary work in hot paths — loops, I/O, DB calls as few as needed
- [ ] Heavy imports are lazy — no ML model or GPU init at module level
- [ ] Error handling complete — every exception path has an explicit outcome
- [ ] Resources cleaned up — file handles, connections, subprocesses closed
- [ ] No shared mutable state across sessions or concurrent requests
- [ ] Memory footprint bounded — no unbounded caches or infinite queues
- [ ] Async/sync boundary correct — blocking calls not in async hot paths
- [ ] Logging structured — context identifier in every log line
- [ ] Nothing in this file can crash and block a user response

A passing test on unoptimized code is not done. Quality check is not optional.

### Test Rules — Absolute
Run the spec's test against your implementation.
Never write new tests to match your code.
Never modify existing tests to make them pass.
The test is the requirement.

## Safety Rails

- **Never delete or overwrite files without reading them first.**
- **Never git push or git reset --hard without explicit user confirmation.**
- **Never pip install or npm install without checking first.**
- **Never hardcode credentials** — environment variables or OS keyring only.
- **Prefix risky commands with SAFE-CHECK:** and wait for confirmation.

## Critical Rules

- **Never delete coordinates.db** — that's your memory.
- **Verify before recording** — syntax, quality, tests.
- **Trust the system** — re-reading wastes tokens. The DB is accurate.

## Spec / Domain Quick Reference

- Production roadmap: `bootstrap/GOALS.md`
- Graph queries: `get_session()` or `navigate(file)`
- Work queue: `claim_work()` / `get_session()`
- Event recording: `record_edit()`, `record_test()`, `record_create()`
- Session update: handled automatically by SDK lifecycle
- PiN (Primordial Info Nodes): `pin_add()`, `pin_search()`, `pin_list()`
- Landmark bridges: `pin_link()`
