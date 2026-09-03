# SLICE 5 — Temp Design (Option B, clarified)

> Temporary design for review **before** full implementation. Reflects user clarifications:
> merge `model_selection` + `inference_mode` into one **Model & Inference** card; keep
> **Local Model** loading as a *separate* card; brain/tool/**swarm** model selectors list
> BOTH provider models AND the loaded local model; keep `use_same_model`; swarm LLM is
> unified (local or provider).

---

## 1. Confirmed structure

```
┌─ Agent settings ────────────────────────────────────────────────┐
│                                                                   │
│  CARD A — "Model & Inference"  (merged model_selection+inference) │
│    • Provider setup (API provider)                                │
│        - Provider        [cerebras ▾]   (API-kind providers)      │
│        - API Key         [sk-…]            (showIf needs key)      │
│        - Endpoint        [url]             (showIf lmstudio/self)  │
│    • Brain (Reasoning) Model   [gemma-4-31b ▾]  ← provider + local │
│    • Use Same Model for Both  (toggle, default ON)  ← KEPT         │
│    • Tool Model               [gemma-4-31b ▾]  (showIf toggle OFF) │
│    • Inference behavior (from inference_mode):                    │
│        - Agent Thinking Style  [balanced ▾]                       │
│        - Max Response Length   [medium ▾]                          │
│        - Reasoning Effort      [balanced ▾]                       │
│        - Tool Mode             [auto ▾]                            │
│    • Active Routing (read-only summary):                         │
│        reasoning→cerebras/gemma-4-31b · tool→cerebras/gemma-4-31b │
│                                                                   │
│  CARD B — "Local Model"  (SEPARATE, unchanged loading UX)         │
│    • GGUF Model      [path ▾]   • Hardware Profile [balanced ▾]   │
│    • Context Length  [slider]  • GPU Offload      [slider]        │
│    • Status          [custom]  • Load / Unload   [buttons]        │
│    → on Load: registers instance "local" → appears in Card A      │
│      brain/tool/swarm dropdowns via provider_added                │
│                                                                   │
│  CARD C — "Swarm Setup"  (unified into router — see §9)         │
│    • Swarm LLM  [gemma-4-31b ▾]   ← provider models + local       │
│    • (rest of swarm config unchanged)                             │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

Both the **dashboard** (`dark-glass-dashboard.tsx`) and the **wheel**
(`wheel-view/SidePanel.tsx`) render these same three cards — only the chrome differs.

---

## 2. The unified model dropdown (the key UX idea)

Every model selector (brain / tool / swarm) is populated from a **merged list**:

```
option = {
  label:  "Gemma 4 31B" | "Local: llama-3-8b",
  value:  "gemma-4-31b" | "llama-3-8b",
  source: "cerebras" | "local"      // which provider instance it belongs to
}
```

Sources:
- **Provider models** — from `get_available_models` for the selected API provider
  (existing flow; dashboard line 809 / wheel line 131).
- **Loaded local model** — from `GET /api/inference/state` providers where `kind` is
  `inprocess`/`local_openai` (id `"local"`), refreshed live by the `provider_added`
  event when a GGUF loads.

Selecting an option writes a **role binding**:
```
sendMessage('set_role_binding', {
  role: 'reasoning' | 'tool_execution' | 'swarm',
  instance_id: option.source,        // "cerebras" or "local"
  model_override: option.value       // the model id
})
```
This is exactly what the backend `InferenceRouter.bind_role()` already supports
(agent_kernel.py:6982). So the UI selectors *are* the role bindings — no separate
binding UI needed.

`use_same_model = ON` → tool selector hidden; `set_role_binding('tool_execution', …)`
mirrors the brain selection.

---

## 3. Wireframes

### Dashboard — Card A "Model & Inference" (proposed)
```
Model & Inference
  Provider          [ cerebras ▾ ]          ← from /api/inference/state (API-kind)
  API Key           [ sk-…        ]         ← showIf provider needs key
  Brain (Reasoning) [ gemma-4-31b ▾ ]       ← provider models + "Local: …"
  Use Same Model    ( ● on )                ← KEPT
  Tool Model        [ gemma-4-31b ▾ ]       ← hidden when same-model ON
  ── Behavior ──
  Thinking Style    [ balanced ▾ ]
  Max Response      [ medium ▾ ]
  Reasoning Effort  [ balanced ▾ ]
  Tool Mode         [ auto ▾ ]
  ── Active Routing ──
  reasoning → cerebras / gemma-4-31b
  tool     → cerebras / gemma-4-31b
```

### Dashboard — Card B "Local Model" (separate, unchanged)
```
Local Model
  GGUF Model    [ /models/llama.gguf ▾ ]
  Profile       [ balanced ▾ ]
  Context       [ 16384 ]   GPU Offload [ -1 ]
  Status        [ UNLOADED ]
  [ Load Model ]  [ Unload Model ]
```
→ after Load: `provider_added` fires → Card A brain/tool/swarm dropdowns now show
  `Local: llama-3-8b`.

### Wheel — same three cards, rendered as cards (SidePanel.tsx)
- `models-card` becomes the merged **Model & Inference** card (provider + brain/tool +
  behavior). Provider dropdown sourced from the hook; brain/tool options = merged list.
- `local-model-card` unchanged (separate).
- `swarm-setup-card` LLM dropdown uses the merged list.

---

## 4. Data flow (single source of truth)

```
Frontend (both views)
   │  on mount: fetch('/api/inference/state')  ──► { providers, role_bindings, default_role }
   │  on provider change: sendMessage('get_available_models', {provider,…}) ──► iris:available_models
   │  on model select:    sendMessage('set_role_binding', {role, instance_id, model_override})
   │  on local Load:      sendMessage('load_local_model', {path, profile})
   ▼
Backend
   GET /api/inference/state        → router.snapshot()          (EXISTS, SLICE 4.5)
   get_available_models handler    → provider model list        (EXISTS)
   provider_added WS event         → local instance registered  (EXISTS, SLICE 3)
   set_role_binding (NEW)          → router.bind_role() + persist + broadcast role_bindings_updated
```

**New backend piece (small):** `set_role_binding` WS handler in `iris_gateway.py`:
```python
# pseudo
inst = payload['instance_id']; role = payload['role']
kernel._router.bind_role(role, inst, model_override=payload.get('model_override'))
# persist to iris_config.inference.role_bindings
# broadcast {'type':'role_bindings_updated','payload': router.snapshot()['role_bindings']}
```

---

## 5. Specific tweaks per view (file:line)

**New shared:** `components/useInferenceState.ts`
- `fetch('/api/inference/state')` → `{providers, roleBindings, defaultRole}`.
- Listen `iris:provider_added` / `iris:role_bindings_updated` → update.
- Returns merged model-option helper: `modelOptionsFor(role)` = provider models (from
  `availableModels`) + local instances (from `providers` where kind∈{inprocess,local_openai}).

**Dashboard (`dark-glass-dashboard.tsx`):**
- Delete `PROVIDER_MODELS` (647) + usages (718, 754, 795).
- Merge `model_selection` + `inference_mode` card defs in `data/cards.ts` into one
  `model_and_inference` card; keep `local_model` separate.
- `FieldRow` provider dropdown → hook providers; brain/tool/swarm dropdowns → merged
  `modelOptionsFor(role)`; on select → `set_role_binding`.
- Add Active Routing read-only summary.

**Wheel (`wheel-view/SidePanel.tsx`):**
- `models-card` → merged card; provider dropdown from hook; brain/tool options merged.
- `inference-card` fields fold into the merged card (remove as standalone).
- `swarm-setup-card` LLM dropdown → merged list.
- Add `iris:provider_added` + `iris:role_bindings_updated` listeners (mirror line 144).

**`data/cards.ts`:**
- Replace `model_selection` + `inference_mode` with single `model_and_inference`.
- Keep `local_model` and `swarm_setup` (swarm LLM dropdown options = merged).

---

## 6. Validation (goal-coupled)
1. Dashboard + wheel brain/tool/swarm dropdowns list `cerebras/gemma-4-31b` from
   `/api/inference/state` (not hardcoded) — proves the endpoint is the single source.
2. Load a GGUF → `provider_added` → `Local: <name>` appears in all three dropdowns
   without refresh.
3. Pick `Local: <name>` for Brain (swarm OFF) → `set_role_binding('reasoning','local',…)`
   → next DER plan in `backend_run.log` shows `role=reasoning instance=local` (verifies routing).
4. SWARM mode: enable Swarm → kernel routed to swarm director/worker endpoints; the Model &
   Inference role bindings become inactive (swarm takes priority). Verify `backend_run.log`
   shows swarm routing, not InferenceRouter role resolution.
4. `use_same_model` ON → tool mirrors brain; OFF → independent.
5. `npx tsc --noEmit` clean; `get_available_models` still populates provider models.

---

## 7. Confirmed decisions (user, this round)
- Q1: **Swarm LLM stays in `swarm_setup` card** — just unify its dropdown (local + provider). ✅
- Q2: **`set_role_binding` is editable now** — build the small backend handler. ✅
- Q3: **"Active Routing" summary is read-only** v1. ✅

## 8. Local-model override error handling (NEW requirement)
When a role is bound to `instance_id="local"` (or any override references a local model),
the backend MUST validate before binding:
- If no local model is currently loaded (`router.registry.get("local")` is missing / not
  `INPROCESS`/`LOCAL_OPENAI` with a live manager) → **log a clear error**
  (`[set_role_binding] rejected: local model not loaded`) and **return an appropriate error**
  response to the client (e.g. `{status:"error", message:"Local model not loaded — load a
  GGUF before binding it to '<role>'"}`). Do NOT silently bind to a dead instance.
- If the `model_override` names a model that isn't available on the chosen instance →
  log + return error.
- Same guard applies in `load_local_model` if an override/profile is invalid.
This keeps the UI honest: picking `Local: …` for a role when nothing is loaded surfaces a
real error instead of a silent routing failure.

## 9. Swarm vs new routing — VERIFIED BREAK, must unify (not keep separate)
VERIFIED by tracing every inference path: the swarm does **NOT** work with the new
`InferenceRouter` as-is.
- `agent_kernel.infer()` (582) and ALL DER/Pacman paths (`_plan_task` 3573, `_respond_direct`
  1941, `_synthesize_response` 6680, Reviewer 5561/5620/5676/5788/6461/6520) call
  `self._router.generate(role, …)` — the InferenceRouter. **None** use `configure_openai_compat`.
- Swarm start (`iris_gateway.py:1093`) only calls `kernel.configure_openai_compat(_swarm_ep)`
  — the LEGACY client. The router's instances are NEVER reconfigured for swarm.
- Therefore when swarm is ON, DER+Pacman route through the router to its instances
  (cerebras/local) and **completely bypass the swarm llama-servers**. The swarm is silently dead.

So "keep swarm separate, don't change configs" is WRONG — it would ship a broken swarm.

**Fix (unify swarm into the router):** on Start Swarm, register swarm as router instances and
bind roles so DER+Pacman flow through it:
- register instance `swarm_director` (endpoint=director_endpoint, model=director_model)
- register instance `swarm_worker`  (endpoint=workers_endpoint,  model=worker_model)
- bind `reasoning → swarm_director`, `tool_execution → swarm_worker`
- (`api_director` mode: director is an API provider instance; workers stay local)
Then `infer()` → router → swarm, consistent with single-agent mode. The Swarm Setup card's
"Start Swarm" calls this registration instead of `configure_openai_compat`.

**UI implication:** swarm is no longer a separate "priority" mode — it is a **preset of role
bindings** (director for reasoning, worker for tool). The Model & Inference "Active Routing"
summary shows `reasoning → swarm_director`, `tool → swarm_worker` when swarm is on. The
director_source + worker_model selectors remain the UI for choosing those instances.

**Backend change required (part of SLICE 5, not frontend-only):** `_handle_swarm_action` /
local-swarm config must register swarm instances in `kernel._router` + `bind_role`, replacing
the `configure_openai_compat` call. This is a small, contained backend edit.

## 10. Constraints (from user, this round)
- **No change to `dashboard-wing.tsx` design/styling.** Only the *cards* are reorganized.
  Implementation touches `DarkGlassDashboard` + `data/cards.ts` (the shell is untouched).
- **Match real wing dimensions** so content is never cut off / spilled: balanced width = 510px
  (`getSpotlightWidth()`), height = 88vh, internal `overflow-y:auto` scroll, correct padding.
  The prototype uses exactly these dimensions.
- **Swarm mode will be reworked in the future** → the Swarm Setup card is structured to stay
  adaptable. For now it maps `director_source` + `worker_model` to router instances
  (`swarm_director` / `swarm_worker`); future swarm redesign slots into the same card.
- **All dropdowns sourced from backend routing:** provider list + role bindings from
  `GET /api/inference/state`; model lists from `get_available_models`. No hardcoded
  `PROVIDER_MODELS`. Local model appears via `provider_added`.
- **api_director mode confirmed:** Director Source = API Provider → director is an API
  provider instance; workers remain local.
