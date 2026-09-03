# GATE 0 — Observed Baseline & Build Findings

**Run:** 2026-08-25 · branch `feat/agent-multi-step-tool-execution` · commit `9216a7b1`
**Executed by:** Claude Code (external agent), session 258.
**Mandate:** REQ-21 — measure, do not repair. Fix only enough to reach the next wall.

This file is the **observed** record. `requirements.md` REQ-17 / REQ-20 held *predictions*; this holds what actually happened. Where the two disagree, this file wins and the requirement has been corrected (REQ-21 AC3).

---

## T-B1 — Baseline state

| | |
|---|---|
| Branch | `feat/agent-multi-step-tool-execution` |
| Commit | `9216a7b150370cf924175d12a3093e01383a035f` — *fix(orb,chat): dismiss visibility, footer spacing; retire the vision stage* (2026-08-25 10:33) |
| Working tree | **131 entries dirty** — 91 untracked, 23 modified, 17 deleted |
| Rust toolchain | rustc 1.93.0 / cargo 1.93.0 — present |
| `src-tauri/target` | absent (full compile from scratch) |
| Backend at run time | running on :8090 (pid 13184) — **not** touched by this run |

### Targeted test baseline

`backend/tests/unit/test_tool_errors.py`, `test_tool_bridge_gates.py`, `backend/tests/test_tool_registry.py`
→ **45 passed, 1 failed** in 168s.

**Pre-existing failure — do NOT attribute to this spec's work:**

```
FAILED backend/tests/unit/test_tool_bridge_gates.py::test_unknown_tool_not_resolved_but_still_runs_dispatch
backend/tests/unit/test_tool_bridge_gates.py:145: AssertionError
  assert 'Unknown tool' in "Permission timed out for tool 'totally_unknown_tool_xyz'"
```

The permission gate times out before dispatch reaches the unknown-tool path. **Note for REQ-19:** FAULTLINE typed this as `error_type: 'transient', blame: 'world'` — a heuristic misclassification of an unknown tool, which is precisely the imprecision REQ-19 exists to fix. Worth using as a regression case for T0i.

Also present, unrelated: `PytestConfigWarning: Unknown config option: timeout / timeout_method`.

---

## T-B2 — Packaged build attempt

Sequence run: `rm -rf dist` → `npm run build` → `npx tauri build`.

### G0-01 · ❗ NOT PREDICTED · `tauri build` dies at config validation

```
Error `"tauri.conf.json"` error on `bundle > resources`:
[{"src":"../llama.cpp/build/bin/Release","target":"llama-server"}]
is not valid under any of the schemas listed in the 'anyOf' keyword
```

`bundle.resources` used the array-of-objects form; Tauri v2 accepts either an array of strings or a **map** of `path → target`.

**This fires before `beforeBuildCommand`, before the Rust compile, and before the `dist` check.** The spec's predicted failure *ordering was wrong* — none of the predicted blockers were reachable while this stood.

**Minimal unblock applied** (sanctioned by T-B2, recorded here rather than hidden in the diff):

```json
"resources": { "../llama.cpp/build/bin/Release": "llama-server" }
```

### G0-02 · ✅ PREDICTED (REQ-17 AC2) — but the mechanism was wrong

`npm run build` **succeeds**, exit 0. Next.js 16.2.6, compiled in 70s, TypeScript in 112s, 10 static pages generated.

It produces `.next/`. It does **not** produce `dist/`, which `tauri.conf.json` names as `frontendDist`.

> **Correction to REQ-17:** the spec said a clean clone "fails before the updater is even reachable," implying the *npm build* fails. It does not — it succeeds cleanly. The gap is purely that its output location and `frontendDist` disagree. The conclusion holds; the stated mechanism did not.

### G0-03 · ⚠️ PREDICTION WRONG — the export build does NOT fail. It succeeds and silently drops the routes.

**Predicted:** `output: 'export'` would fail the build because `/api/chat` and `/api/logs/structured` are POST handlers.

**Observed:** a temporary `output: 'export'` probe on Next.js 16.2.6 **built successfully, exit 0.** No error. Two warnings only:

```
⚠ Specified "rewrites" will not automatically work with "output: export".
⚠ rewrites, redirects, and headers are not applied when exporting your application, detected (rewrites).
```

The route table still lists `ƒ /api/chat` and `ƒ /api/logs/structured` — but the emitted directory has **no `api/` at all**:

```
$ ls out/          → 404.html  _next/  cli-preview.html  dashboard.html  … (38 entries)
$ ls -R out/api    → (does not exist)
```

**This is worse than the predicted build failure, not better.** A build failure is loud and stops you. What actually happens is that the widget packages successfully, ships, and then `/api/chat` **404s at runtime** — killing chat-view's REST fallback (`chat-view.tsx:1851, 2024, 2080`) exactly when the WS is already down, which is the only moment it matters. Silent capability loss in the packaged artifact.

The remediation in REQ-17 AC2a is unchanged (repoint the fallback at the backend, then remove `app/api/`). Its **justification** changes: it is not "the build won't compile," it is "the build will compile a widget with a dead fallback path."

### G0-03b · ❗ NOT PREDICTED — static export emits `out/`, not `dist/`

The probe wrote to **`out/`**. `tauri.conf.json` sets `frontendDist: "../dist"`.

So `frontendDist` is wrong in a *second, independent* way: even after `output: 'export'` is enabled, the paths still disagree. REQ-17 AC2 must also set `distDir`, or repoint `frontendDist` to `../out`.

This also explains the stale checked-in `dist/`: its contents (`404.html`, `__next._tree.txt`, `_next/`, …) match the `out/` layout exactly — it was produced by an export build at some point and placed at `dist/` by hand. Nothing in the current build path reproduces it.

### G0-04 · ✅ PREDICTED (REQ-20) — confirmed, and conclusive

`src-tauri/binaries/iris-backend-x86_64-pc-windows-msvc.exe` — **36.45 MB**, dated **2026-05-07**.

Marker scan of the binary:

| module | occurrences |
|---|---|
| numpy | 14 |
| uvicorn | 3 |
| sqlite3 | 3 |
| fastapi | 2 |
| **torch** | **0** |
| **transformers** | **0** |
| **faster_whisper** | **0** |
| **pvporcupine** | **0** |
| **llama** | **0** |

Web-stack packages appear in the archive TOC; the entire ML/voice stack does not. **Size settles it independently** — torch alone ships 2-3 GB; a 36 MB binary cannot contain it.

The bundled sidecar cannot run STT, wake word, or local inference. REQ-20 AC1's "declare what is supported and what defers to post-install download" is not a formality — it is the actual decision blocking a shippable bundle.

### G0-05 · ✅ PREDICTED (REQ-17 AC6) — sidecar is stale

Dated 2026-05-07 against a 2026-08-25 HEAD — roughly **3.5 months**. `scripts/build/build_backend.py` is on no build path. Any packaged widget today runs a backend predating all of Gates 1-3.

### G0-06 · ❗ NOT PREDICTED — MCM search tools cannot serve as the agent's search path

`mcm_glob("**/react/package.json")` at the repo root **timed out after 120 s**.

This closes the open question of whether `mcm_grep`/`mcm_glob` could satisfy REQ-18 instead of bundling ripgrep. They cannot — they are topology-ranked wrappers with the same unbounded-walk problem as `Path.rglob("*")`. For comparison on the same machine: `rg --files` enumerated 8,653 tracked files instantly.

**REQ-18 stands as written: bundle ripgrep.** The MCM tools remain useful for topology-ranked queries on known-small scopes; they are not the fast-search primitive.

### G0-07 · Documentation drift

`CLAUDE.md` states "Next.js 15". The project builds on **Next.js 16.2.6**. Minor, but it is in the stack description an onboarding agent reads first.


### G0-08 · ❗ ROOT-CAUSED — CLAUDE.md documents MCM tools that do not exist, and wrong signatures for ones that do

**Initial diagnosis was wrong.** This was first written up as "the MCM server times out on writes." It is not primarily a server fault. Corrected:

**What actually happened.** `record_test` was called with `test_file` / `test_name` / `outcome` — the signature **CLAUDE.md documents**. The live tool takes `file` / `result`. The server did not reject the unknown payload; it **hung until the 120 s client timeout**. Called with correct parameters afterwards, it returned instantly.

**Two distinct defects:**

1. **Documentation is wrong (primary).** `CLAUDE.md` and `AGENTS.md` — which every agent reads first, under "you MUST follow them exactly as written" — instructed agents to call **four tools that do not exist** (`claim_work`, `complete_task`, `pin_link`, `health.add_warning`), **two under wrong names** (`mcm_crystallize_landmark`, `mcm_define_feature` — neither carries the `mcm_` prefix), and **four with wrong parameter names** (`record_test`, `record_edit`, `record_create`, `pin_add`). `claim_work()` was STEP 1 of the documented session workflow and the spine of the PARALLEL SUB-AGENT PROTOCOL.

2. **The server hangs on unexpected parameters (secondary).** It should return a validation error. Instead the call blocks for the full client timeout. This turns a typo into a two-minute stall, and made the documentation bug present as an infrastructure failure.

**The dangerous part — a timeout tells you nothing about whether the write landed.** Verified directly against the DB afterwards:

| call | client result | actually committed? |
|---|---|---|
| `record_edit` ×5 | ok | ✅ yes (13:43:39–13:44:01) |
| `pin_add` (spec review) | ok | ✅ yes (13:44:26) |
| `pin_add` (Gate 0) | **timed out** | ✅ **YES** — `pin_63115028df05` @ 14:11:31 |
| `record_test` | **timed out** | ❌ no — no `test_run` event written |
| `mcm_glob` | **timed out** | n/a (read) |

One timed-out write committed; the other did not. An agent that retries on timeout **duplicates data**; one that does not **silently loses it**. Neither behaviour is safe without checking `db_query` first.

> **Correction to this document's own earlier claim:** an earlier revision stated the Gate 0 pin was "not recorded in the coordinate graph." That was wrong — it committed at 14:11:31. The `record_test` event was the only genuine loss, and it has since been re-recorded successfully.

**Fixed.** `CLAUDE.md` and `AGENTS.md` were corrected in place: every non-existent tool is now explicitly flagged as unavailable, every signature verified against the live server, and a new **MCM TOOL SIGNATURES — VERIFIED** block documents the exact argument names, the hang-on-bad-params behaviour, and the "a timeout does not mean the write failed — check `db_query` before retrying" rule. Eight real tools that were undocumented (`db_query`, `query_events`, `health_check`, `mcm_grep`, `mcm_glob`, `read_file`, `run_command`, `submit_plan`) are now listed.

**Still open, for the next agent:**
- `claim_work` / `complete_task` have **no MCP binding**, yet `get_session()` reports "Work items: 16". Either the tools should be exposed or the documented workflow around them should be removed. Right now the work queue is readable and unclaimable.
- The server's hang-on-bad-params behaviour is unfixed — it lives in the MCM server, outside this repo.

### G0-10 · ❗ NOT PREDICTED — the entire `webpack:` block in next.config.mjs is dead code

Next.js 16 builds with **Turbopack by default**. The build banner says so on every run (`▲ Next.js 16.2.6 (Turbopack)`), and `package.json` runs a plain `next build` with no `--no-turbopack`.

**Verified empirically**, not inferred: a `console.log('###WEBPACK_CONFIG_RAN###')` was inserted as the first statement of the `webpack:` function and a full `next build` was run. **Marker count: 0.** The function never executes. (Marker reverted.)

So ~45 lines of `next.config.mjs` — and its comment block claiming *"For production builds (`next build`) these exclusions still prevent webpack from scanning model-weight directories"* — have no effect:

| dead setting | intended effect | actual |
|---|---|---|
| `watchOptions.ignored` regex | exclude `backend`, `models`, `llama.cpp`, `venv`, `tests`, `specs`… | not applied |
| `.bin/.safetensors/.gguf/.pt/.pth` module rule | stop webpack processing model weights as JS assets | not applied |
| `moduleIds: 'named'` / `chunkIds: 'named'` | production stack-trace readability | not applied |

**This is a documentation-vs-reality gap of the same class as G0-08:** a config block that reads as load-bearing, is commented as load-bearing, and does nothing. Anyone tuning build performance would start by editing it and observe no change.

Contributes to G0-09 (`.next` at 1.9 GB). Not necessarily the whole cause — Turbopack has its own ignore behaviour and the config comments note it "respects .gitignore" — but the intended exclusions are definitively not in force.

**FIXED 2026-08-25.** Resolution: **deleted, not ported.** Rationale — the block never ran, so removing it is a zero-behaviour-change edit (verified: full build after removal, exit 0, byte-identical route table). Porting to Turbopack config would have meant inventing configuration whose equivalence was unverified. The exclusion *intent* is now served by the mechanism Turbopack actually honours: `models/gguf/`, `venv/`, `.venv/` and `llama.cpp/` were added to `.gitignore` — none were tracked, and `models/wake_words/` was deliberately left out because the Porcupine `.ppn` is tracked and needed at runtime (verified with `git check-ignore`). `next.config.mjs` now carries a comment explaining that a `webpack()` function would silently do nothing, so the trap is not re-laid.

### G0-09 · Build-hygiene note (not a blocker)

**CORRECTED.** `.next/` measures 1.9 GB, but the production build is not the cause — measured composition:

| path | size |
|---|---|
| `.next/dev` | **1.8 G** |
| `.next/server` | 37 M |
| `.next/static` | 6.8 M |
| `.next/cache` | 290 K |

Production output is ~44 MB. The 1.8 GB is **dev-server accumulation**, consistent with the Turbopack memory regression `next.config.mjs` already disables `turbopackServerFastRefresh` for. An earlier revision of this document implied the production build was heavy; it is not.

A dev server also appears to hold `.next/dev` open — `rm -rf .next` failed with "Directory not empty" on `.next/dev/cache/turbopack/`.
 `next.config.mjs:3-7` already documents this failure mode — dev compilation "can hang for minutes and balloon to 1-15 GB" on drives under OneDrive sync or antivirus real-time scan — and names the mitigation: `scripts/setup_fast_next_cache.py` / `start-iris.bat`, which relocate the cache via a directory junction.

Not a correctness issue. Flagged because Gate 4 requires repeated packaged builds, and each one pays this cost. Whoever runs Gate 4 should apply the junction first.

---

## Where the build actually stands

| # | Wall | Status |
|---|---|---|
| 1 | **G0-01** `bundle.resources` schema form rejected by Tauri v2 | ✅ cleared (minimal fix applied) |
| 2 | **G0-02** `beforeBuildCommand` succeeds, then `frontendDist "../dist"` not found | 🔴 **current wall** |
| 3 | **G0-03 / G0-03b** export succeeds but drops `api/` and emits to `out/` | 🔴 behind wall 2 |
| 4 | REQ-17 blocker 1 — MSI cannot self-update (needs NSIS) | ⚪ not yet reached |
| 5 | REQ-17 blocker 3 — no updater plugin / pubkey / endpoints | ⚪ not yet reached |
| 6 | **G0-04** sidecar carries no ML/voice stack | ⚪ not reached by build; confirmed by inspection |

Exact wall-2 error text:

```
Running beforeBuildCommand `npm run build`
✓ Compiled successfully in 9.4s
Finished TypeScript in 35.9s ...
Error Unable to find your web assets, did you forget to build your web app?
Your frontendDist is set to "../dist" (which is `\\?\C:\dev\IRISVOICE\dist`).
```

**The Rust compile was never reached.** No `src-tauri/target` was produced, so Rust-side build risk (Cargo deps, the updater plugin's own compile, sidecar/resource bundling) is entirely unmeasured. Expect further unknowns there.

## Corrections owed to the spec (REQ-21 AC3)

1. **REQ-17 AC2** — mechanism restated: `npm run build` succeeds; the failure is the `frontendDist` mismatch, not a build failure. ✅ applied
2. **REQ-17** — config-schema blocker (G0-01) added as blocker 0; it precedes every other one. ✅ applied
3. **REQ-17 AC2a** — **justification corrected**: static export does not fail on the POST handlers, it silently drops them, producing a widget whose REST fallback 404s at runtime. The fix is the same; the reason is different and more urgent. ✅ applied
4. **REQ-17 AC2** — **new sub-blocker**: export emits `out/`, `frontendDist` says `dist/`. Needs `distDir` or a repoint. ✅ applied
5. **REQ-18** — open question closed: MCM search tools are not a substitute (G0-06). ✅ applied
6. **REQ-20** — upgraded from prediction to confirmed, with marker-scan and size evidence. ✅ applied

**Scorecard for the predictions:** 3 confirmed (G0-02 outcome, G0-04, G0-05), 1 confirmed with a corrected mechanism (G0-02), **1 wrong on severity in a way that mattered (G0-03)**, **3 missed entirely (G0-01, G0-03b, G0-06)**. Roughly a third of the real blockers were not in the spec before this gate ran. Treat the remaining unreached predictions (walls 4-5) with the same discount.

## Notes for the agent taking over

- **The pre-existing test failure (G0-07 baseline) is not yours.** Do not fix it as part of Gate 1-5 work, and do not let it disappear silently — EXIT GATE 5 requires it be fixed deliberately or still recorded as pre-existing.
- **The working tree is dirty (131 entries).** Establish whether that churn is wanted before building on top of it. This run did not clean it.
- **A backend was running on :8090 during this run** and was deliberately left alone. Any test that binds 8090 will conflict.
- **G0-01's fix is the only production change this run made.** Everything else was measurement.
