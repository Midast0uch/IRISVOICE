# LLM Routing — Target State (clean modular design, v2)

> Companion to `LLM_ROUTING_CURRENT.md`. Revised after user decisions (session 154):
> - **Backend + Frontend together** in one pass.
> - **Provider registry + per-role bind** (users add N named provider instances; each
>   role binds to any instance independently).
> - **Local = first-class, multi-load** provider instance.
> - **Unify** the two frontend schemas (`model_selection` + `inference_mode`) into one
>   schema + one shared `ModelSelectionPanel` used by both `dark-glass-dashboard` and
>   `wheel-view`.
> - **Per-provider keyring** credentials.
> - **N roles** (not 2): roles are capability slots the **reasoning/brain agent** uses
>   to spawn a **swarm of subagents**; each subagent is bound to a provider instance
>   (API *or* local). Defined roles + organization make it easy for the brain to call
>   them.
>
> DER and Pacman logic are **not** touched — they call `router.generate(role, …)`.

---

## 0. Status (2026-07-15, session 154)

**Backend routing refactor: COMPLETE & verified running.**
- ✅ Steps 1–8 (backend) implemented: `backend/agent/inference/` package,
  `InferenceRouter` in `AgentKernel.__init__`, `infer()` / `_respond_direct()` /
  `_plan_task` / `_synthesize_response` → `router.generate`, `set_model_selection`
  → router sync (with `api_base_url` passthrough), `load_local_model` →
  `router.add_provider` + `provider_added` broadcast, legacy flat config
  synthesized into a default `cerebras` instance bound to `reasoning`+`tool_execution`.
- ✅ DER loop verified using Cerebras (`ApiHttpxTransport model=gemma-4-31b`) with
  **no `local-model` fallback** (prior session + live backend on :8090).
- ⚠️ Step 8 (gateway unify): both `set_model_selection` and the `model_selection` /
  `inference_mode` confirm handlers route to `router` via `set_model_selection`.
  `PROVIDER_ENDPOINTS` is **retained** as the named-provider endpoint lookup (not yet
  collapsed into `ProviderKind`); the router instance carries the correct per-instance
  `api_base_url` via the `set_model_selection` passthrough.
- ⏳ Steps 9–12 (frontend, SLICE 5): **NOT started.** The two frontend schemas
  (`model_selection` in `dark-glass-dashboard.tsx`, `inference_mode` in
  `wheel-view/SidePanel.tsx`) are not yet unified into one `ModelSelectionPanel`.
  Backend is ready (`provider_added` event emitted on local load).
- ⏳ Swarm / subagent orchestration (§5): design in place; not yet wired to spawn
  subagents via `router.generate(role)`.

DER and Pacman logic are **not** touched — they call `router.generate(role, …)`.

---

## 1. Design principles

1. **Provider instances are named, not just "API".** A `ProviderInstance` =
   `{id, label, kind, model, credentials_ref}`. `kind` ∈
   `API | LOCAL_OPENAI | INPROCESS | OLLAMA`. This is what enables
   `reasoning=cerebras` + `tool=openai` + `subagent=local-llama` simultaneously.
2. **Roles are capability slots, bound to instances.** A `RoleBinding` =
   `{role, instance_id, model_override?}`. The brain agent has a catalog of roles
   (reasoning, tool_execution, researcher, coder, critic, …) and resolves each to a
   provider instance at call time. **N roles, extensible, no hardcoded 2.**
3. **One `InferenceRouter` is the single source of truth.** Holds the
   `ProviderRegistry` + `RoleBinding` table. `generate(role, messages, tools)` resolves
   `role → instance → transport` and calls `transport.generate(...)`.
4. **One transport per kind**, implemented once, reused by every role/instance.
5. **Local models are first-class instances.** Loading a local model
   (`load_local_model`) *creates* a `ProviderInstance` (kind `INPROCESS` or
   `LOCAL_OPENAI`) in the registry. Multiple locals can be loaded and bound to
   different roles. Loading lifecycle is the local transport's concern, orthogonal to routing.
6. **Config is the default; UI confirm overrides; both funnel through one method.**
   `iris_config.json` holds the `provider_registry` + `role_bindings`. Auto-applied at
   init; UI `confirm_card` overrides per binding.
7. **Credentials in OS keyring, per provider id.** Config holds only `id` + `api_base_url`.
8. **Frontend: one schema, one shared panel.** Both `dark-glass-dashboard` and
   `wheel-view` render the *same* `ModelSelectionPanel` from the *same* schema. The
   current `model_selection` vs `inference_mode` divergence is collapsed.
9. **DER / Pacman untouched.**

---

## 2. Core concepts

```python
# backend/agent/inference/provider.py
class ProviderKind(str, Enum):
    API         = "api"          # OpenAI-compatible cloud (cerebras, openai, cohere, …)
    LOCAL_OPENAI= "local_openai" # LM Studio / vllm / llama.cpp served over OpenAI API
    INPROCESS   = "inprocess"    # in-process local model manager (iris_local)
    OLLAMA      = "ollama"       # Ollama native API

@dataclass
class ProviderInstance:
    id: str                 # "cerebras", "openai", "local-llama-8b", …
    label: str
    kind: ProviderKind
    model: str | None       # default model for this instance
    api_base_url: str = ""  # for API / LOCAL_OPENAI
    # credentials live in OS keyring keyed by `id`; never in config

# backend/agent/inference/registry.py
class ProviderRegistry:
    def add(self, inst: ProviderInstance): ...
    def get(self, id: str) -> ProviderInstance: ...
    def list(self) -> list[ProviderInstance]: ...
    def remove(self, id: str): ...

# backend/agent/inference/roles.py
@dataclass
class RoleBinding:
    role: str               # "reasoning", "tool_execution", "researcher", "coder", …
    instance_id: str
    model_override: str | None = None

class RoleBindingTable:
    def bind(self, role: str, instance_id: str, model_override=None): ...
    def resolve(self, role: str) -> ProviderInstance: ...   # raises clear error if unbound
    def list(self) -> list[RoleBinding]: ...
```

---

## 3. Component map

```
Frontend (dark-glass-dashboard.tsx  +  wheel-view/SidePanel.tsx)
   both render the SAME <ModelSelectionPanel/> from the SAME schema
      │
      │ confirm_card { section_id:"model_registry", values:{ providers:[…], roles:[…] } }
      │ confirm_card { section_id:"model_selection", values:{ reasoning:{instance}, tool:{instance}, … } }
      ▼
iris_gateway.py  _handle_set_model_selection / _handle_set_registry
      │  → kernel.router.registry.add(...) / kernel.router.roles.bind(...)
      ▼
AgentKernel
   self._router = InferenceRouter(config)        # SSOT, built in __init__
      │
      │  infer(role="reasoning", prompt)        → router.generate("reasoning", …)
      │  _respond_direct(...)                   → router.generate(role, …)
      │  brain/swarm agent: router.generate("researcher", …)   # subagent spawn
      │  set_model_selection / configure_*      → router.apply_selection(…)  (thin delegates)
      ▼
InferenceRouter  (backend/agent/inference/router.py)
   _registry : ProviderRegistry      # named instances (API + local + ollama)
   _roles    : RoleBindingTable      # role → instance_id
   _transports: dict[ProviderKind, Transport]   # one per kind, cached
      │
      │ generate(role, messages, tools):
      │    inst = self._roles.resolve(role)          # role → instance
      │    t    = self._transport(inst.kind, inst)   # instance → transport
      │    return t.generate(inst.model, messages, tools)
      ▼
   ┌──────────────┬──────────────┬──────────────┬──────────────┐
   │ApiHttpxTransport│OpenAICompat │InProcess     │Ollama        │
   │(Cerebras/     │Transport      │Transport      │Transport     │
   │ OpenAI/…)     │(LM Studio/    │(local model   │(Ollama       │
   │               │ vllm/llama.cpp)│ manager)     │ native)      │
   └──────────────┴──────────────┴──────────────┴──────────────┘
        each transport implemented ONCE, reused by every role/instance
```

---

## 4. How separation is maintained

- **API vs local**: enforced at the *transport boundary*. An API instance uses
  `ApiHttpxTransport` (HTTP→provider). A local instance uses `InProcessTransport`
  or `OpenAICompatTransport`. The router resolves each role → its transport; the two
  never share state. Local-model *loading* (GPU RAM) is the local transport's own
  lifecycle, orthogonal to routing.
- **Using both at once**: `reasoning → API(cerebras)` and
  `tool_execution → INPROCESS(local)` are two independent `generate()` calls. No
  global "mode" forces uniformity.
- **Multiple API providers at once**: instances are *named* (`cerebras`, `openai`).
  `reasoning → cerebras`, `tool → openai` are two distinct instances, each with its
  own keyring key + base url. The registry holds them; roles reference by id.

---

## 5. Swarm / subagent orchestration (the brain agent)

The reasoning/brain agent orchestrates a swarm. Each subagent is a **role** bound to
a provider instance. The brain queries `router.roles.list()` to discover available
capabilities, then calls `router.generate(role, …)` to spawn a subagent with that
role's model (API or local). Example default role set:

| Role            | Default instance | Notes |
|-----------------|------------------|-------|
| `reasoning`     | `cerebras`       | the brain itself |
| `tool_execution`| `local-llama-8b` | runs tools locally, cheap/fast |
| `researcher`    | `openai`         | deep web/research subagent |
| `coder`         | `cerebras`       | code-gen subagent |
| `critic`        | `local-llama-8b` | local review subagent |

Adding a role = adding a `RoleBinding`; adding a subagent type = binding a role to a
(new or existing) instance. **No code change needed to add roles** — the table is data.

---

## 6. Local model loading as instance creation

```
ModelBrowserPanel (frontend) → user picks local model + profile
   → sendMessage('load_local_model', {model_path, profile})
      │
      ▼
iris_gateway / kernel: load local model into GPU via local manager
   → kernel.router.registry.add(ProviderInstance(
         id=f"local-{slug}", label=model_name, kind=INPROCESS, model=model_name))
   → emit 'provider_added' so both frontends refresh their dropdowns
```

The loaded model now appears as a selectable instance in **every** role dropdown
(reasoning, tool, researcher, …). Multiple locals can be loaded → multiple instances →
bound to different roles.

---

## 7. Config schema (`data/iris_config.json`)

```jsonc
{
  "inference": {
    "provider_registry": [
      { "id": "cerebras", "label": "Cerebras", "kind": "api",
        "model": "gemma-4-31b", "api_base_url": "https://api.cerebras.ai/v1" },
      { "id": "openai", "label": "OpenAI", "kind": "api",
        "model": "gpt-oss-120b", "api_base_url": "https://api.openai.com/v1" },
      { "id": "local-llama-8b", "label": "Llama 3.1 8B (local)", "kind": "inprocess",
        "model": "llama-3.1-8b" }
    ],
    "role_bindings": [
      { "role": "reasoning",      "instance_id": "cerebras" },
      { "role": "tool_execution", "instance_id": "local-llama-8b" },
      { "role": "researcher",     "instance_id": "openai" },
      { "role": "coder",          "instance_id": "cerebras" },
      { "role": "critic",         "instance_id": "local-llama-8b" }
    ]
  },
  "routing": { "mode": "ROLE_BOUND" }
}
```

Keys are stored in OS keyring keyed by `provider_registry[].id` (e.g.
`iris_voice:provider:cerebras`). Config holds no secrets.

---

## 8. Frontend: one schema, one shared panel

- **Single schema** (`@/data/cards` or a new `@/data/modelSelection`):
  `provider_registry` (list of instances) + `role_bindings` (role → instance).
  The legacy `model_selection.model_provider` and `inference_mode`
  (Local/OpenAI/VPS) vocabularies are **deleted**; both frontends read the new schema.
- **One shared `<ModelSelectionPanel/>`** component (new file, e.g.
  `components/model/ModelSelectionPanel.tsx`) rendered by BOTH
  `dark-glass-dashboard.tsx` and `wheel-view/SidePanel.tsx`. It renders:
  - **Providers** section: add/edit/remove provider instances (kind, label, model,
    api_base_url; api_key goes to keyring via a `save_provider_secret` WS/HTTP call).
  - **Roles** section: for each known role, a dropdown of provider instances + a model
    field. Binding writes `role_bindings`.
  - **Local models**: `ModelBrowserPanel` loads a model → `provider_added` event →
    instance appears in every role dropdown automatically.
- `confirm_card` payload shape:
  `{ section_id: "model_registry", values: { providers:[…], roles:[…] } }`.
- `PROVIDER_MODELS` hardcoded map in `dark-glass-dashboard.tsx` moves into the
  backend (`get_available_models` already returns per-provider models); frontend just
  renders what the backend sends per instance.

---

## 9. Migration steps (current → target)

**Progress:** Backend steps 1–8 ✅ implemented & verified. Frontend steps 9–12 ⏳
pending (SLICE 5). Swarm (§5) design-only.

**Backend (additive first, then wire):**
1. New `backend/agent/inference/` package: `provider.py` (ProviderKind,
   ProviderInstance), `registry.py` (ProviderRegistry), `roles.py` (RoleBindingTable),
   `transport.py` (Transport protocol + ApiHttpx/OpenAICompat/InProcess/Ollama),
   `router.py` (InferenceRouter), `keyring.py` (per-provider secret get/set).
2. `InferenceRouter.__init__(config)` builds registry + roles from
   `config.inference` (auto-apply default). Absorbs session-154's
   `_apply_configured_inference`.
3. `AgentKernel.infer()` → `self._router.generate("reasoning", …)`.
4. `AgentKernel._respond_direct()` `_call` → `self._router.generate(role, …)`; delete
   `config_mode` / `_is_openai_compat` / `_is_api_provider` branching.
5. `set_model_selection` + `configure_*` → thin delegates to
   `router.registry.add` / `router.roles.bind`.
6. `load_local_model` handler → `router.registry.add(local instance)` + emit
   `provider_added`.
7. Collapse `ModelRouter.InferenceMode` into `ProviderKind` (keep local *loading* inside
   `InProcessTransport` / local manager; `ModelRouter` deleted or reduced).
8. Gateway: unify `_handle_set_model_selection` + any `inference_mode` handler into
   `router.registry` / `router.roles` ops; `PROVIDER_ENDPOINTS` → `ProviderKind` +
   per-instance `api_base_url`.

**Frontend:**
9. New `components/model/ModelSelectionPanel.tsx` (shared).
10. `dark-glass-dashboard.tsx` + `wheel-view/SidePanel.tsx` render it; delete their
    separate model-selection logic + the `inference_mode` (Local/OpenAI/VPS) schema.
11. `PROVIDER_MODELS` map removed; models come from backend per instance.
12. `ModelBrowserPanel` load → `provider_added` refresh.

**DER / Pacman:** no changes.

---

## 10. Verification

- Unit: `InferenceRouter.generate` routes `reasoning→cerebras` (ApiHttpx) and
  `tool_execution→local` (InProcess) with fake transports; `roles.resolve` raises a
  clear error when a role is unbound; `registry.add` then `roles.bind` then `generate`
  works for a freshly-loaded local instance.
- Integration (live): start backend, drive DER via WS `text_message`
  `payload:{text:…}`; confirm log shows the bound provider's transport (e.g.
  `ApiHttpxTransport model=gemma-4-31b api_base=https://api.cerebras.ai/v1` for
  reasoning) and **no** `local-model` fallback. Load a local model, bind `tool` to it,
  confirm a tool step uses the local transport.
- Regression: a config with no providers leaves roles unbound; `generate` raises a
  clear "no model configured for role X" error (no silent local fallback).
- Frontend: both `dark-glass-dashboard` and `wheel-view` show identical model-selection
  UI; adding a provider instance makes it appear in every role dropdown in both views.
