# LLM Routing — Current State (as-built, post-refactor)

> Purpose: an accurate map of how IRIS Voice decides *which model* and *which
> transport* handles an inference request AFTER the routing refactor
> (session 154, 2026-07-15). The legacy design is archived in git history; this
> document describes the live code.
>
> Sources: `backend/agent/inference/{provider,registry,roles,transport,router,keyring}.py`,
> `backend/agent/agent_kernel.py`, `backend/iris_gateway.py`, `data/iris_config.json`.

---

## 1. The 10,000-foot view

```
Frontend (dark-glass-dashboard.tsx / wheel-view/SidePanel.tsx)
   Models card → confirm_card {section_id:"model_selection", values}
                  + load_local_model {model_path, profile}
        │ (WebSocket)
        ▼
iris_gateway.py
   _handle_set_model_selection → kernel.set_model_selection(...)     (router sync)
   _handle_load_local_model    → router.add_provider(local) + provider_added event
        │
        ▼
AgentKernel  (self._router = InferenceRouter(load_config())  in __init__)
   infer(role, …)            → self._router.generate(role, …)   # DER loop
   _respond_direct._call(…)  → self._router.generate(role, …)   # agentic loop
   _plan_task / _synthesize_response → router.generate(role, …) # DER planning + synthesis
   set_model_selection(…)    → router.add_provider + router.bind_role
        │
        ▼
InferenceRouter  (backend/agent/inference/router.py)   ← SINGLE SOURCE OF TRUTH
   _registry   : ProviderRegistry      (named instances: API + local + ollama)
   _roles      : RoleBindingTable      (role → instance_id, case-insensitive)
   _transports : cached per (kind, endpoint)
   default_role fallback → "reasoning" for unbound roles (e.g. "EXECUTION")
        │ generate(role, messages, tools):
        │    inst = roles.resolve(role)               # role → instance (fallback to default)
        │    t    = build_transport(inst.kind, inst)  # instance → transport
        │    return t.generate(inst.model, messages, tools)
        ▼
   ┌────────────────┬──────────────────┬────────────────┬────────────────┐
   │ApiHttpxTransport│OpenAICompat       │InProcess       │Ollama          │
   │(Cerebras/OpenAI │Transport          │Transport       │Transport        │
   │ /… over httpx)  │(LM Studio/vllm/   │(local model    │(Ollama native) │
   │                 │ llama.cpp)        │ manager)       │                │
   └────────────────┴──────────────────┴────────────────┴────────────────┘
        each transport implemented ONCE, reused by every role/instance
```

---

## 2. Provider instances & kinds

`ProviderInstance = {id, label, kind, model, api_base_url}`.
`kind ∈ API | LOCAL_OPENAI | INPROCESS | OLLAMA` (`backend/agent/inference/provider.py`).

At kernel init, `InferenceRouter._apply_config` **synthesizes a default `cerebras`
instance** from the legacy flat `iris_config.json` (`inference.provider` /
`reasoning_model` / `api_base_url` / `api_key`) and binds it to `reasoning` +
`tool_execution`. So a config with `provider=cerebras` makes the DER loop use
Cerebras with **no UI interaction** — the old `local-model` fallback is gone.

The router also accepts the target schema `inference.provider_registry` +
`inference.role_bindings` (applied when present, taking precedence over the
legacy flat schema).

---

## 3. Entry points — all converge on `router.generate`

- `infer()` (DER `Reviewer` / `_run_step_direct`) → `self._router.generate(role, …)`.
- `_respond_direct()._call()` → `self._router.generate(role, …)`.
- `_plan_task()` → router branch is **PRIMARY** (legacy LM Studio / Ollama fallbacks retained).
- `_synthesize_response()` → router branch is **PRIMARY**.

`generate(role, …)` resolves `role → instance → transport` and returns
`(text, thinking, tool_calls)` — the same shape the legacy paths returned.

---

## 4. Role resolution & default fallback

`RoleBindingTable.resolve` is **case-insensitive** (`REASONING` == `reasoning`).
`InferenceRouter.resolve` falls back to `default_role` (`reasoning`) for unbound
roles — so DER's `"EXECUTION"` role resolves to the `cerebras` instance instead
of raising. This fixed the prior bug where an unbound role crashed inference
(`No provider instance bound to role 'EXECUTION'`).

---

## 5. Local model loading → registry instance

`load_local_model` (gateway `_handle_load_local_model`, the live handler after a
broken duplicate was removed) loads the GGUF via `LocalModelManager`, then:

- builds `ProviderInstance(id="local", kind=INPROCESS if mgr._llm else LOCAL_OPENAI,
  model=<stem>, api_base_url="" if inprocess else mgr.ENDPOINT)`,
- `router.add_provider(inst)`,
- `router.set_inprocess_manager(mgr)` for the in-process path,
- broadcasts `provider_added` so frontends can refresh their dropdowns.

The frontend (SLICE 5) will bind roles to `"local"` via `set_model_selection` /
the `provider_added` event.

> Note: a second, broken `_handle_load_local_model` (calling `mgr.load_model` with a
> non-existent API: `gpu_layers` / `context_length` / `hardware_profile`) previously
> *shadowed* the correct handler and made local loading crash with `TypeError`. It was
> deleted; the correct handler (kernel-wiring + correct API) is now live.

---

## 6. Model selection wiring

`confirm_card` (section `model_selection`) →
`kernel.set_model_selection(reasoning, tool, provider, api_base_url=…)`.
`set_model_selection` updates legacy fields AND syncs the router:

```python
self._router.add_provider(ProviderInstance(
    id=model_provider, label=model_provider, kind=_kind,
    model=reasoning_model,
    api_base_url=api_base_url or getattr(self, '_api_base_url', '') or ""))
self._router.bind_role("reasoning", model_provider)
self._router.bind_role("tool_execution", model_provider, model_override=tool_execution_model)
```

The `api_base_url` passthrough ensures the router instance carries the *selected*
provider's endpoint (not the previously configured one). `PROVIDER_ENDPOINTS` is
retained as the named-provider endpoint lookup used by `configure_api`.

---

## 7. Config (`data/iris_config.json` → `iris_config.py`)

- `inference.provider` (`"cerebras"`), `inference.reasoning_model` (`"gemma-4-31b"`),
  `inference.api_base_url` (`"https://api.cerebras.ai/v1"`), `inference.api_key`
  (or OS keyring, per-provider id).
- `routing.mode` (`SINGLE_API` | `SINGLE_LOCAL` | …) — a `str, Enum` (`RoutingMode`).
- Target schema `inference.provider_registry` + `inference.role_bindings` is also
  honoured when present.

---

## 8. What changed vs the legacy design

1. **One entry point** (`router.generate`) replaces the divergent `infer()` LiteLLM
   path and `_respond_direct()` httpx path.
2. **One transport per kind**, implemented once, reused by every role/instance.
3. **Single source of truth**: `InferenceRouter` holds registry + roles;
   `set_model_selection` / `configure_*` delegate to it.
4. **No silent local fallback**: unbound roles fall back to the configured default
   (`reasoning` → cerebras), not `local-model`.
5. **Local = first-class instance** registered on load + `provider_added` broadcast.
6. **Case-insensitive roles** + default-role fallback.

---

## 9. Remaining (SLICE 5, frontend)

The two frontend schemas (`model_selection` in `dark-glass-dashboard.tsx`,
`inference_mode` in `wheel-view/SidePanel.tsx`) are **not yet unified** into one
`ModelSelectionPanel`. The backend is ready (registry + `provider_added` event);
the frontend unification is the outstanding item. See `LLM_ROUTING_TARGET.md`
§Migration steps 9–12.

---

## 10. Evidence index (file:line)

| Concern | Location |
|---------|----------|
| InferenceRouter | `backend/agent/inference/router.py:70` |
| default_role fallback | `backend/agent/inference/router.py:176` |
| generate → transport | `backend/agent/inference/router.py:307` |
| ProviderInstance / ProviderKind | `backend/agent/inference/provider.py:25,16` |
| ProviderRegistry | `backend/agent/inference/registry.py:16` |
| RoleBindingTable (case-insensitive) | `backend/agent/inference/roles.py` |
| AgentKernel._router init | `backend/agent/agent_kernel.py:255` |
| infer → router.generate | `backend/agent/agent_kernel.py:582` |
| _respond_direct → router.generate | `backend/agent/agent_kernel.py:1941` |
| _plan_task router branch | `backend/agent/agent_kernel.py:3573` |
| _synthesize_response router branch | `backend/agent/agent_kernel.py:6680` |
| set_model_selection → router sync | `backend/agent/agent_kernel.py:6877,6977` |
| load_local_model → registry + provider_added | `backend/iris_gateway.py:7310` (live handler) |
| confirm_card → set_model_selection | `backend/iris_gateway.py:1242,1257` |
| PROVIDER_ENDPOINTS (retained) | `backend/iris_gateway.py:1271` |
