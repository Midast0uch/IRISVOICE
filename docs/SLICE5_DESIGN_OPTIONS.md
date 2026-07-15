# SLICE 5 — Frontend Unification: Design Options

**Goal (from user):** Unify the *data source* for model/inference selection so both the
dashboard and the wheel-view pull from one live backend source (`GET /api/inference/state`
+ `get_available_models`). Keep the existing cards; improve UX *structure*. Do **not**
abandon the current frontend design.

**Backend already done (SLICE 1–4):**
- `GET /api/inference/state` → `{ providers:[{id,label,kind,model,api_base_url}],
  role_bindings:[{role,instance_id,model_override}], default_role }`
- `provider_added` WS event fires when a local model loads (payload = provider dict).
- Router holds `role_bindings` (reasoning→instance, tool_execution→instance) — but the
  UI currently never shows or edits them.

---

## 1. Current state — the drift

| Concern | Dashboard (`dark-glass-dashboard.tsx`) | Wheel (`wheel-view/SidePanel.tsx`) |
|---|---|---|
| Provider list | **Hardcoded** `PROVIDER_MODELS` (line 647) | From `get_available_models` event (line 131) |
| Model dropdowns | `availableModels` from backend, but `PROVIDER_MODELS` overrides as fallback (line 754) | `availableModels` from backend (line 263) |
| `model_selection` card | `models-card`: provider, api_key, use_same_model, reasoning_model, tool_model, lmstudio_endpoint | same `models-card` |
| `inference_mode` card | `inference-card`: thinking style, response length, reasoning effort, tool mode | same `inference-card` |
| Role bindings | **Not shown** | **Not shown** |
| Local model | `local_model` section (load/unload) | `local-model-card` |
| `provider_added` | **Not consumed** | **Not consumed** |

Both render the *same* `data/cards.ts` definitions (`model_selection`→`models-card`,
`inference_mode`→`inference-card`, `local_model`→`local-model-card`). The divergence is
purely in *where the option lists come from* and *missing role-binding UI*.

---

## 2. Design options

### Option A — Shared inference-state hook + live "Active Routing" header  ⭐ RECOMMENDED
Add one hook `useInferenceState()` that:
- `fetch('/api/inference/state')` on mount → `providers`, `roleBindings`, `defaultRole`.
- Subscribes to `iris:provider_added` / `iris:provider_removed` custom events (bridged
  from the WS `provider_added` message) → live provider list.

Both views keep their cards but:
- Provider dropdown options come from the hook (not `PROVIDER_MODELS`).
- A compact **Active Routing** header shows the live state: `Provider: cerebras ·
  reasoning→cerebras · tool_execution→cerebras`.
- A small **Role Bindings** control lets the user assign which provider instance handles
  `reasoning` vs `tool_execution` (writes via a new `set_role_binding` WS message →
  `router.bind_role`).
- Local model appears automatically via `provider_added`.

**Dashboard tweaks:** delete `PROVIDER_MODELS` (647); `FieldRow` provider dropdown uses
hook; add Active Routing header above `model_selection`; add role-binding rows.
**Wheel tweaks:** `models-card` provider dropdown uses hook; `inference-card` shows role
bindings; add `iris:provider_added` listener (like the existing `iris:available_models`
listener at line 144).

### Option B — Merge `model_selection` + `inference_mode` into one card
Combine `models-card` + `inference-card` into a single `model_and_inference` card
(provider, api_key, models, role bindings, thinking style, tool mode). Rendered identically
in both views. Bigger change to `data/cards.ts` + both renderers; loses the separate
"inference behavior" card the user may like.

### Option C — Shared `ModelSelectionPanel` component
Extract a self-contained component (provider + model + role UI) used by both views. Most
reusable, largest refactor (touches both 30–70KB files, rewires `FieldRow`/`renderField`).

**Recommendation: Option A.** It matches "unify the data source, keep the cards," is the
lowest-risk, and directly validates the backend optimization (the endpoint is now the single
source both views read). Options B/C can be layered later if desired.

---

## 3. Wireframes (Option A)

### Dashboard — `model_selection` section (today → proposed)
```
TODAY                                     PROPOSED (Option A)
─────────────────────────────────         ─────────────────────────────────
Models                                    Models
  Provider        [OpenCodeGo ▾]            Active Routing: cerebras
  API Key         [sk-…         ]             reasoning → cerebras ▾
  Use Same Model  (toggle on)                tool_exec → cerebras ▾
  Reasoning Model  [GLM 5.1 ▾]             ─────────────────────────────────
  Tool Model       [GLM 5.1 ▾]             Provider        [cerebras ▾]   ← from /api/inference/state
                                            API Key         [sk-…     ]
                                            Use Same Model  (toggle on)
                                            Reasoning Model  [gemma-4-31b ▾] ← from get_available_models
                                            Tool Model       [gemma-4-31b ▾]
```
The "Active Routing" header + role-binding rows are the UX improvement: the user *sees* the
live routing the backend is actually using, and can reassign roles without hunting through
config.

### Wheel — `models-card` / `inference-card` (today → proposed)
```
TODAY (models-card)                        PROPOSED (models-card)
─────────────────────────────────         ─────────────────────────────────
Provider        [OpenCodeGo ▾]            Active Routing: cerebras
Reasoning Model  [No models… ]            Provider        [cerebras ▾]   ← from hook
Tool Model       [No models… ]            Reasoning Model  [gemma-4-31b ▾]
                                           Tool Model       [gemma-4-31b ▾]

TODAY (inference-card)                     PROPOSED (inference-card)
─────────────────────────────────         ─────────────────────────────────
Agent Thinking  [balanced ▾]              Agent Thinking  [balanced ▾]
Max Response    [medium ▾]                 Max Response    [medium ▾]
Reasoning Effort[balanced ▾]              Reasoning Effort[balanced ▾]
Tool Mode       [auto ▾]                   Tool Mode       [auto ▾]
                                           ── Role Bindings ──
                                           reasoning → [cerebras ▾]
                                           tool_exec→ [cerebras ▾]
```
Wheel tweak: `models-card` provider dropdown sourced from the hook; `inference-card` gains
the role-binding rows; add `iris:provider_added` listener so a loaded local model shows up
without a refresh.

---

## 4. Specific code-level tweaks per view

**New shared file:** `components/useInferenceState.ts`
- `fetch('/api/inference/state')` → `{providers, roleBindings, defaultRole}`.
- `window.addEventListener('iris:provider_added', …)` → append provider; bridge the WS
  `provider_added` message → custom event in the WS bridge (one small addition).
- Returns `{ providers, roleBindings, defaultRole, loading }`.

**Dashboard (`dark-glass-dashboard.tsx`):**
- Remove `PROVIDER_MODELS` const (647) and its usages (718, 754, 795).
- `FieldRow` provider dropdown: options = `useInferenceState().providers` (mapped to
  `{label, value}`).
- Above `model_selection` section: render Active Routing header + role-binding `<select>`s
  that call `sendMessage('set_role_binding', {role, instance_id})`.

**Wheel (`wheel-view/SidePanel.tsx`):**
- `models-card`: provider dropdown options = hook providers (replace the static
  `cards.ts` options or override like the model-dropdown override at 263).
- `inference-card`: append role-binding rows from hook.
- Add `iris:provider_added` listener (mirror 144) so local models appear live.

**Backend (small, enables role editing):** add `set_role_binding` WS handler in
`iris_gateway.py` → `kernel._router.bind_role(role, instance_id, model_override)` + persist
to config + broadcast `role_bindings_updated`. (This is the only new backend piece; the
read endpoint already exists.)

---

## 5. Validation (goal-coupled — proves the optimization works)
1. **Source-of-truth:** dashboard + wheel provider dropdowns list `cerebras` from
   `GET /api/inference/state`, NOT from a hardcoded list. (Confirms the endpoint is the
   single source — the optimization's purpose.)
2. **Live local model:** load a GGUF model → `provider_added` fires → both views show the
   local instance in the provider dropdown without refresh.
3. **Role bindings:** UI shows `reasoning→cerebras`, `tool_execution→cerebras`; reassign
   `reasoning→local` via `set_role_binding` → backend router resolves `reasoning` to the
   local instance on the next DER plan (verifiable in `backend_run.log`
   `[InferenceRouter] role=reasoning instance=local`).
4. **No regression:** `npx tsc --noEmit` clean; existing `get_available_models` flow still
   populates model dropdowns.

---

## Open questions for deliberation
- Q1: Should role bindings be **editable** in v1 (needs `set_role_binding` backend) or
  **read-only** display first? (Recommend: editable — it's the meaningful UX win and small.)
- Q2: Keep `inference_mode`/`inference-card` as a *separate* card (Option A) or merge into
  one card (Option B)? (Recommend: keep separate per "keep the cards.")
- Q3: Where does the "Active Routing" header live — top of `model_selection` only, or a
  persistent strip in both views?
