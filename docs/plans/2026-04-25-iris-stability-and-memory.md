# IRIS Stability + Memory Optimization Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix three UI bugs (wing overflow, dashboard styling regression, DCP stats placement), swap the vision model to LFM2.5-VL-450M, and stop the idle backend memory churn so the widget doesn't spike or crash before the user touches it.

**Architecture:** Two surfaces — frontend (Next.js wings inside a Tauri shell at `C:/Users/midas/Desktop/dev/`) and backend (FastAPI at `C:/Users/midas/Desktop/dev/backend/`). The backend is the heavy offender: pre-warm scans, mycelium maintenance loops, MCP health pings, and a wake-word frame loop all fire whether or not the user is doing anything. We'll make every background worker idle-aware, defer the pre-warm scan to first use, and add a memory watchdog so a runaway worker can't crash the widget. Vision swap is a config-only change (llama-server still hosts the GGUF, only the model id changes) plus old file cleanup.

**Tech Stack:** Next.js 15, React, Tailwind v4, Tauri (Rust), Python FastAPI, llama.cpp/llama-server, HuggingFace Hub.

---

## Critical Files (read these BEFORE touching anything)

| File | Why it matters |
|---|---|
| `components/chat-view.tsx:954` | Wing root — `height: '88vh'`, no outer overflow clip |
| `components/dashboard-wing.tsx:206,215` | Same shape as ChatWing — same overflow bug |
| `components/dark-glass-dashboard.tsx` | The dashboard content; no DCP code present today (verified via grep) |
| `src-tauri/src/main.rs:27-32` | Tauri window: resizable=true, no max size — frontend can ask for any size |
| `app/page.tsx:113-119` | Where the frontend requests window resizes |
| `backend/main.py:124-410` | Lifespan startup — every background task lives here |
| `backend/main.py:396-410` | `_prewarm_model_cache()` — fires 30 s after startup, scans GGUF dir |
| `backend/memory/distillation.py:28-31` | Idle-aware (10 min idle, 4 h cooldown, polls every 5 min) |
| `backend/memory/retention.py:62,79-87` | 60 s startup delay, then runs every `retention.run_interval_hours` |
| `backend/ws_manager.py:158` | Per-client heartbeat task |
| `backend/mcp/server_manager.py:229` | Per-MCP-server health-check loop |
| `backend/agent/agent_kernel.py:751-782` | LM Studio prewarm daemon thread |
| `backend/iris_gateway.py:95` | LFMVLProvider() instantiated at startup (HTTP client only) |
| `backend/tools/lfm_vl_provider.py:2,16,57,86` | Model identifier: `"lfm2.5-vl"` |
| `start_vl.sh:14-16,27,34` | Hard-coded `LFM2.5-VL-1.6B` paths + HF download commands |
| `bootstrap/GOALS.md` Domain 16 | Where the elevated optimization priority lives |

---

## Task 1 — Wing overflow fix (chat-view + dashboard-wing)

**Files:**
- Modify: `components/chat-view.tsx:944-960` (outer motion.div)
- Modify: `components/dashboard-wing.tsx:198-215` (outer motion.div)

**Step 1 — Read both files, lines ±20 around the cited lines.** Confirm the outer container uses `height: '88vh'` and the inner glass panel uses `h-full overflow-hidden`. Confirm there is no `overflow: 'hidden'` on the outer container.

**Step 2 — Add `overflow: 'hidden'` to the outer motion.div style object** in both files. Also clamp the height so it can never exceed the Tauri window:
```ts
// BEFORE
style={{
  height: '88vh',
  perspective: '800px',
  zIndex: getSpotlightZIndex(),
}}

// AFTER
style={{
  height: 'min(88vh, calc(100vh - 24px))',  // never exceeds viewport
  maxHeight: 'calc(100vh - 24px)',
  overflow: 'hidden',                        // clip at the wing boundary
  perspective: '800px',
  zIndex: getSpotlightZIndex(),
}}
```
Apply identical change to both files.

**Step 3 — In the Tauri shell, lock body overflow.** Open `app/page.tsx` (or `app/layout.tsx`) and verify `<body>` / root has `overflow: hidden` and `height: 100vh`. If not, add to the global stylesheet (`app/globals.css` or `styles/globals.css`):
```css
html, body { height: 100vh; overflow: hidden; overscroll-behavior: none; }
```

**Step 4 — Manual verification.**
1. `pnpm dev` from repo root, then `pnpm tauri dev` (or just `cargo tauri dev`).
2. Open chat wing, scroll to bottom of message list — wing must NOT scroll past the window frame.
3. Repeat with dashboard wing.
4. Resize the Tauri window smaller than 88 vh's worth of content — content must scroll INSIDE the wing, not push the wing outside.

**Step 5 — Commit.**
```
git add components/chat-view.tsx components/dashboard-wing.tsx app/globals.css
git commit -m "fix(wings): clip wings to Tauri window bounds, prevent body overflow"
```

---

## Task 2 — Dashboard styling parity + DCPStatsPanel placement

**Context:** Explorer found the wing wrappers (`chat-view.tsx` vs `dashboard-wing.tsx`) have identical glass styling. The user reports the *contents* of the dashboard look unstyled vs the chat. So the regression is inside `dark-glass-dashboard.tsx`, not the wing wrapper. Also: `DCPStatsPanel` does NOT exist in the current tree (`grep DCPStatsPanel components/ → 0 hits`). It needs to be created and dropped into the metric-card grid.

**Files:**
- Read: `components/dark-glass-dashboard.tsx` (whole file — it's the only place that needs styling work)
- Create: `components/dev/DCPStatsPanel.tsx`
- Modify: `components/dark-glass-dashboard.tsx` (insert DCPStatsPanel into metric-card area)
- Read for parity reference: `components/chat-view.tsx:962-987` (the glass card the user wants mirrored)

**Step 1 — Diff the dashboard against chat for styling.** Read `dark-glass-dashboard.tsx` end-to-end. Identify the section that should look like a metric-card grid (likely the section that shows stats/cards near the top). Compare its container classes/inline styles to the ChatView glass card on lines 962-987 (`backdropFilter: blur(40px)`, gradient background, rounded corners, border with glow color, inset/outer shadow). Report the diff in a comment in your scratch notes.

**Step 2 — Patch the dashboard to match.** Add the missing properties (likely `backdropFilter`, gradient bg, border, rounded `12px`, box-shadow Fresnel) to the offending container so each card visually matches a chat glass card.

**Step 3 — Create `components/dev/DCPStatsPanel.tsx`:**
```tsx
"use client";
import { useEffect, useState } from "react";

type DCPStats = {
  pruneCount: number;
  tokensSaved: number;
  lastDedups: number;
  lastErrorsPurged: number;
  lastWritesSuperseded: number;
};

const ZERO: DCPStats = { pruneCount: 0, tokensSaved: 0, lastDedups: 0, lastErrorsPurged: 0, lastWritesSuperseded: 0 };

export function DCPStatsPanel() {
  const [s, setS] = useState<DCPStats>(ZERO);
  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent).detail ?? {};
      setS(prev => ({
        pruneCount: prev.pruneCount + 1,
        tokensSaved: prev.tokensSaved + (d.tokens_saved ?? 0),
        lastDedups: d.dedups ?? 0,
        lastErrorsPurged: d.errors_purged ?? 0,
        lastWritesSuperseded: d.writes_superseded ?? 0,
      }));
    };
    window.addEventListener("iris:dcp_pruned", handler);
    return () => window.removeEventListener("iris:dcp_pruned", handler);
  }, []);

  return (
    <div className="p-4 rounded-xl border border-white/10 bg-white/5 backdrop-blur-md">
      <div className="text-xs uppercase tracking-wider text-white/60 mb-2">DCP — Context Pruner</div>
      <div className="grid grid-cols-2 gap-2 text-xs text-white/80">
        <div>Prunes: <b>{s.pruneCount}</b></div>
        <div>Tokens saved: <b>{s.tokensSaved.toLocaleString()}</b></div>
        <div>Dedups (last): <b>{s.lastDedups}</b></div>
        <div>Errors purged: <b>{s.lastErrorsPurged}</b></div>
        <div className="col-span-2">Writes superseded: <b>{s.lastWritesSuperseded}</b></div>
      </div>
    </div>
  );
}
```

**Step 4 — Mount DCPStatsPanel in the metric-card grid only in developer mode.** In `dark-glass-dashboard.tsx`, find the metric-card grid (or whatever the top stats section is) and add as a sibling card:
```tsx
import { DCPStatsPanel } from "@/components/dev/DCPStatsPanel";
// inside the grid, gated by mode:
{mode === "developer" && <DCPStatsPanel />}
```
If mode isn't already piped into this component, get it from `useApp()` or whatever existing context provides launcher mode. Do not wire a new prop chain.

**Step 5 — Wire the WS event.** Confirm `hooks/useIRISWebSocket.ts` already forwards `dcp_pruned` as a `iris:dcp_pruned` CustomEvent (per prior session summary it should). If not, add it. One-liner:
```ts
case "dcp_pruned":
  window.dispatchEvent(new CustomEvent("iris:dcp_pruned", { detail: msg.data }));
  break;
```

**Step 6 — Visual verification.** `pnpm dev` + open dashboard wing in dev mode. Confirm:
- Each card visually matches a chat glass card (rounded, blurred, bordered, glowing).
- DCPStatsPanel appears in the metric grid.
- After running 2-3 chat turns with tool calls, `Prunes` increments live.

**Step 7 — Commit.**
```
git add components/dark-glass-dashboard.tsx components/dev/DCPStatsPanel.tsx hooks/useIRISWebSocket.ts
git commit -m "fix(dashboard): restore glass styling parity, add DCPStatsPanel to metric grid"
```

---

## Task 3 — Vision model swap: LFM2.5-VL-1.6B → LFM2.5-VL-450M

**Files:**
- Modify: `start_vl.sh:14-16,27,34` (paths + HF download commands)
- Modify: `backend/tools/lfm_vl_provider.py:2,16,57,86` (docstrings + served model id stays `"lfm2.5-vl"` — it's just llama-server's `--alias`)
- Create: `scripts/uninstall_old_vl.py` (deletes `~/models/LFM2.5-VL-1.6B/` and HF cache for that repo)
- Modify: `bootstrap/GOALS.md` Domain 12 (or whichever owns vision) — note the model swap

**Step 1 — Confirm exact HF repo name for the 450M variant.** Check `https://huggingface.co/LiquidAI` for the 450M GGUF repo. Most likely `LiquidAI/LFM2.5-VL-450M-GGUF`. If the repo name differs, use the actual one. Do NOT guess silently — verify with a `huggingface_hub.HfApi().model_info(...)` quick check in the implementer step.

**Step 2 — Update `start_vl.sh`:**
```bash
MODEL_DIR="$HOME/models/LFM2.5-VL-450M"
MODEL="$MODEL_DIR/LFM2.5-VL-450M-Q4_0.gguf"
MMPROJ="$MODEL_DIR/mmproj-LFM2.5-VL-450M-Q4_0.gguf"
```
Update both download command echoes accordingly (lines 27 and 34). The llama-server `--alias` flag (added below if not present) keeps the served name as `lfm2.5-vl` so the backend doesn't change.

**Step 3 — Add llama-server alias flag** (so backend's `"model": "lfm2.5-vl"` payload still matches):
```bash
llama-server \
    --model "$MODEL" \
    --mmproj "$MMPROJ" \
    --alias lfm2.5-vl \
    --port 8081 \
    --n-gpu-layers 99 \
    ...
```

**Step 4 — Add a Windows-friendly equivalent.** `start_vl.sh` is bash only. The user is on Windows (per CLAUDE.md). Create `scripts/start_vl.ps1` with the same logic for PowerShell.

**Step 5 — Update docstrings in `backend/tools/lfm_vl_provider.py`:**
- Line 2: `LFM2.5-VL Vision Provider` → `LFM2.5-VL-450M Vision Provider`
- Line 16: `"""Configuration for LFM2.5-VL vision provider."""` → `"""Configuration for LFM2.5-VL-450M vision provider."""`
- Line 57 docstring: same
- **Line 86 (`"model": "lfm2.5-vl"`) stays unchanged** — that matches the `--alias`

**Step 6 — Create `scripts/uninstall_old_vl.py`:**
```python
"""Removes LFM2.5-VL-1.6B model files + HF cache. Idempotent."""
import shutil, os
from pathlib import Path

OLD_MODEL_DIR = Path.home() / "models" / "LFM2.5-VL-1.6B"
HF_CACHE = Path.home() / ".cache" / "huggingface" / "hub" / "models--LiquidAI--LFM2.5-VL-1.6B-GGUF"

removed = []
for p in (OLD_MODEL_DIR, HF_CACHE):
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
        removed.append(str(p))

print(f"Removed {len(removed)} path(s):")
for r in removed:
    print(f"  - {r}")
if not removed:
    print("Nothing to remove — old model already gone.")
```

**Step 7 — Run uninstall + download new model.** From a shell:
```
python scripts/uninstall_old_vl.py
python -c "from huggingface_hub import hf_hub_download; \
  hf_hub_download('LiquidAI/LFM2.5-VL-450M-GGUF','LFM2.5-VL-450M-Q4_0.gguf', \
    local_dir=str(__import__('pathlib').Path.home()/'models'/'LFM2.5-VL-450M'))"
python -c "from huggingface_hub import hf_hub_download; \
  hf_hub_download('LiquidAI/LFM2.5-VL-450M-GGUF','mmproj-LFM2.5-VL-450M-Q4_0.gguf', \
    local_dir=str(__import__('pathlib').Path.home()/'models'/'LFM2.5-VL-450M'))"
```
Use the existing HF token from env (`HF_TOKEN`). If `huggingface_hub` complains about auth, run `huggingface-cli login` first.

**Step 8 — Verify end-to-end.** Start the new vision server:
```
pwsh scripts/start_vl.ps1   # or: bash start_vl.sh on Linux
```
Then from Python:
```
import requests
r = requests.get("http://localhost:8081/v1/models", timeout=5)
print(r.json())
```
Expect to see `lfm2.5-vl` (the alias) in the response. Send a quick image describe through `backend/tools/lfm_vl_provider.py`'s public function and confirm it returns text.

**Step 9 — Commit.**
```
git add start_vl.sh scripts/start_vl.ps1 scripts/uninstall_old_vl.py backend/tools/lfm_vl_provider.py bootstrap/GOALS.md
git commit -m "feat(vision): swap LFM2.5-VL-1.6B → LFM2.5-VL-450M, add uninstall script + Windows starter"
```

---

## Task 4 — Backend memory baseline (measure BEFORE optimizing)

**Why first:** We can't claim a "fix" without numbers. Capture a 5-minute idle profile so we can prove the next tasks reduced memory.

**Files:**
- Create: `scripts/profile_backend_idle.py`

**Step 1 — Write the profiler:**
```python
"""Records psutil RSS / VMS / CPU% of all iris-backend* processes every 5s for 5 min.
Writes CSV to backend/logs/idle_profile_<UTC>.csv."""
import csv, time, datetime, psutil
from pathlib import Path

OUT = Path("backend/logs"); OUT.mkdir(parents=True, exist_ok=True)
fname = OUT / f"idle_profile_{datetime.datetime.utcnow():%Y%m%dT%H%M%S}.csv"
DURATION_S = 300; INTERVAL_S = 5

def matches(p):
    try:
        n = (p.name() or "").lower()
        return "iris-backend" in n or ("python" in n and any("backend.main" in c for c in p.cmdline()))
    except Exception:
        return False

with fname.open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["ts", "pid", "name", "rss_mb", "vms_mb", "cpu_pct", "num_threads", "num_fds"])
    end = time.time() + DURATION_S
    while time.time() < end:
        for p in psutil.process_iter(["pid", "name"]):
            if not matches(p): continue
            try:
                m = p.memory_info(); cpu = p.cpu_percent(interval=None)
                fds = p.num_fds() if hasattr(p, "num_fds") else 0
                w.writerow([datetime.datetime.utcnow().isoformat(), p.pid, p.name(),
                            m.rss/1e6, m.vms/1e6, cpu, p.num_threads(), fds])
            except (psutil.NoSuchProcess, psutil.AccessDenied): pass
        f.flush(); time.sleep(INTERVAL_S)
print(f"Wrote {fname}")
```

**Step 2 — Run the profile against current code (DO NOT touch anything else first).**
1. Restart backend (`python start-backend.py`).
2. Wait 60 s for first-tick noise to settle.
3. `python scripts/profile_backend_idle.py`
4. Save the CSV — call it `BASELINE`. We'll compare against it after Tasks 5-7.

**Step 3 — Quick sanity stats.** Eyeball the BASELINE CSV. Note:
- RSS at t=0, t=60s, t=300s. Are there step-ups?
- Any process with CPU% > 1 while idle? That's the symptom.
- Thread count drift over 5 min — should be flat.

Record the three numbers in the commit body so we have a benchmark.

**Step 4 — Commit.**
```
git add scripts/profile_backend_idle.py
git commit -m "perf(memory): add idle profiler, capture baseline (RSS t0=X t60=Y t300=Z MB)"
```

---

## Task 5 — Defer the 30 s pre-warm scan to first use

**Files:**
- Modify: `backend/main.py:396-410`
- Modify: `backend/agent/local_model_manager.py` (whichever method exposes `scan_models`)

**Step 1 — Read `backend/main.py:380-415`** to confirm the call site of `_prewarm_model_cache()`.

**Step 2 — Delete the 30 s background scan.** Remove the `asyncio.ensure_future(_prewarm_model_cache())` line. The model manager already caches `scan_models()` results — the first call from the UI (when the user opens the Models screen) will populate it. Cold-start cost on first open: ~150-300 ms of fs I/O. Acceptable.

**Step 3 — Add a tiny lazy wrapper in `local_model_manager.py`:** ensure `scan_models()` is idempotent and the result is memoized for 60 s. (Likely already true — verify.)

**Step 4 — Re-run profiler, save as `TASK5`. Diff against BASELINE.** Expect: no t=30s RSS bump, smaller VMS.

**Step 5 — Commit.**
```
git add backend/main.py backend/agent/local_model_manager.py
git commit -m "perf(memory): drop 30s prewarm GGUF scan, lazy-load on first Models open"
```

---

## Task 6 — Make every background worker truly idle-aware

**Files:**
- Modify: `backend/memory/distillation.py:28-31` (already 10-min idle, but check what "idle" means — must be NO inflight requests, not just no chat)
- Modify: `backend/memory/retention.py:62,79-87` (gate on idle flag)
- Modify: `backend/mcp/server_manager.py:229` (health check loop — increase interval, only ping when MCP is in use)
- Modify: `backend/agent/agent_kernel.py:751-782` (LMStudio prewarm — only run if user has selected an LM Studio model)
- Modify: `backend/ws_manager.py:158` (heartbeat — confirm it doesn't allocate; it shouldn't)

**Step 1 — Add a single `IdleTracker` to `backend/core/idle_tracker.py`:**
```python
"""Single source of truth for 'is the user/agent active?'.
Active = any inflight HTTP request OR open WS message in last N seconds."""
import asyncio, time
from contextlib import contextmanager

class IdleTracker:
    def __init__(self, idle_threshold_s: float = 60.0):
        self._inflight = 0
        self._last_active = time.monotonic()
        self._lock = asyncio.Lock()
        self._threshold = idle_threshold_s

    async def begin(self):
        async with self._lock:
            self._inflight += 1
            self._last_active = time.monotonic()

    async def end(self):
        async with self._lock:
            self._inflight = max(0, self._inflight - 1)
            self._last_active = time.monotonic()

    def is_idle(self) -> bool:
        return self._inflight == 0 and (time.monotonic() - self._last_active) > self._threshold

_singleton: IdleTracker | None = None
def get_idle_tracker() -> IdleTracker:
    global _singleton
    if _singleton is None: _singleton = IdleTracker()
    return _singleton
```

**Step 2 — Wire into FastAPI middleware** (`backend/main.py` lifespan setup):
```python
from backend.core.idle_tracker import get_idle_tracker

@app.middleware("http")
async def _track_inflight(request, call_next):
    tracker = get_idle_tracker()
    await tracker.begin()
    try:
        return await call_next(request)
    finally:
        await tracker.end()
```
Also wire into the WS message handler — call `tracker.begin()` / `end()` around message processing.

**Step 3 — Gate distillation, retention, MCP-health, LMStudio-prewarm on `tracker.is_idle()`.** Each worker checks `if not get_idle_tracker().is_idle(): await asyncio.sleep(60); continue`. This means:
- Distillation only runs when user has been quiet ≥60 s AND no inflight requests
- Retention same
- MCP health checks defer when user is mid-call
- LMStudio prewarm waits for a quiet moment

**Step 4 — Increase MCP health-check interval default from whatever it is today to 60 s.** Find `health_check_interval` default in `backend/mcp/server_manager.py` or its config. Bump to 60.

**Step 5 — Gate LMStudio prewarm on actual model selection.** In `backend/agent/agent_kernel.py:751-782`, wrap the prewarm in:
```python
selected = self._model_router.get_active_model_kind()  # whatever the actual API is
if selected != "lmstudio":
    return  # no point prewarming a backend the user isn't using
```

**Step 6 — Re-run profiler, save as `TASK6`. Diff against TASK5.** Expect: zero CPU% during the full 5 min; flat RSS.

**Step 7 — Commit.**
```
git add backend/core/idle_tracker.py backend/main.py backend/memory/distillation.py backend/memory/retention.py backend/mcp/server_manager.py backend/agent/agent_kernel.py backend/ws_manager.py
git commit -m "perf(memory): central IdleTracker — gate all background workers on user inactivity"
```

---

## Task 7 — Memory watchdog with kill switch

**Files:**
- Create: `backend/core/memory_watchdog.py`
- Modify: `backend/main.py` (start watchdog at lifespan startup)

**Step 1 — Write the watchdog:**
```python
"""Monitors backend RSS. If it exceeds soft cap, log + run mycelium maintenance.
If hard cap, gracefully restart background workers (signal them to drop caches)."""
import asyncio, os, logging, psutil
log = logging.getLogger("backend.memory.watchdog")

SOFT_CAP_MB = int(os.getenv("IRIS_MEM_SOFT_MB", "800"))
HARD_CAP_MB = int(os.getenv("IRIS_MEM_HARD_MB", "1400"))
POLL_S = 30

async def watchdog_loop(on_soft, on_hard):
    p = psutil.Process()
    while True:
        try:
            rss_mb = p.memory_info().rss / 1e6
            if rss_mb > HARD_CAP_MB:
                log.error(f"[WATCHDOG] HARD cap {rss_mb:.0f}MB > {HARD_CAP_MB}MB — calling on_hard")
                await on_hard()
            elif rss_mb > SOFT_CAP_MB:
                log.warning(f"[WATCHDOG] SOFT cap {rss_mb:.0f}MB > {SOFT_CAP_MB}MB — calling on_soft")
                await on_soft()
        except Exception as e:
            log.exception(f"[WATCHDOG] poll failed: {e}")
        await asyncio.sleep(POLL_S)
```

**Step 2 — Wire into `backend/main.py` lifespan:**
```python
from backend.core.memory_watchdog import watchdog_loop

async def _on_soft():
    # call mycelium maintenance, gc.collect()
    import gc; gc.collect()
    if mycelium := get_mycelium():
        mycelium.run_maintenance()

async def _on_hard():
    await _on_soft()
    # also drop in-process LLM if loaded
    if mgr := get_local_model_manager():
        mgr.unload_active_model()

app.state.watchdog_task = asyncio.create_task(watchdog_loop(_on_soft, _on_hard))
```

**Step 3 — Verify by forcing memory pressure.** In a Python REPL against the running backend:
```
import requests; [requests.get("http://localhost:8000/api/heavy") for _ in range(50)]
```
Watch the log for `[WATCHDOG] SOFT cap` then `[WATCHDOG] HARD cap` then `gc.collect()` reducing RSS.

**Step 4 — Commit.**
```
git add backend/core/memory_watchdog.py backend/main.py
git commit -m "feat(memory): RSS watchdog with soft/hard caps + auto mycelium maintenance"
```

---

## Task 8 — Elevate backend optimization in GOALS.md

**Files:**
- Modify: `bootstrap/GOALS.md`

**Step 1 — Read Domain 16 (Memory hygiene + sidecar architecture).** Confirm structure (item ids 16.1-16.5 from prior session).

**Step 2 — Insert at top of Domain 16 a `PRIORITY: P0` flag** with a paragraph explaining: idle memory churn was crashing the widget; Tasks 4-7 of plan `2026-04-25-iris-stability-and-memory.md` close this. Mark 16.1-16.5 with current statuses based on this plan's outcomes.

**Step 3 — Add new items 16.6 (idle tracker), 16.7 (memory watchdog), 16.8 (vision swap to 450M), 16.9 (UI overflow fix), 16.10 (DCPStatsPanel + dashboard parity)** with status `DONE` once each task lands.

**Step 4 — Record to MCM SDK** (NOT bootstrap/record_event.py per CLAUDE.md). Use `scripts/record_gate2_to_mcm.py` as the template. Record:
- pin_add for the optimization milestone
- record_edit for each modified file
- pin_link tying the milestone pin to the edit events

**Step 5 — Commit GOALS.md only** (MCM SDK writes go to `data/database/coordinate.db` which is gitignored — verify it is).
```
git add bootstrap/GOALS.md
git commit -m "docs(goals): elevate Domain 16 to P0, log idle-tracker + watchdog + VL-450M swap"
```

---

## Task 9 — Final verification + push

**Step 1 — Run full profiler one more time, save as `FINAL`. Diff vs BASELINE.** Expect:
- RSS at t=0: roughly the same (startup cost is the same)
- RSS at t=300: significantly lower (no compounding background allocations)
- CPU%: 0 across all samples after t=60s
- Thread count: flat
- No `iris-backend*` orphan processes after a clean Tauri exit (verify with `Get-Process iris-backend*` in PowerShell)

**Step 2 — Smoke test.** Launch full app: `python start-backend.py` in one terminal, `pnpm dev` + `cargo tauri dev` in another. Open the launcher → pick mode → widget appears. Open dashboard wing — confirm:
- No overflow past frame
- Cards have glass parity
- DCPStatsPanel visible in dev mode
- Vision: send an image to the agent, confirm caption returns from LFM2.5-VL-450M

**Step 3 — Push.**
```
git push origin <current-branch>
```

---

## Out of Scope This Pass

- PyInstaller `--onedir` migration (Domain 16.2). Tracked, not blocking idle memory.
- Rust-native backend rewrite (Domain 16.5). Massive lift, not in this plan.
- Merge launcher + widget into one exe (Domain 15.6). Separate plan.
- Linux build (needs Linux hardware, not in this plan).
