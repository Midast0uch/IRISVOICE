# Cross-Spec Reconciliation — Model Path Specs

Covers `local-model-provider-parity` (**S1**), `lfm25-encoder-integration` (**S2**),
`contextpill-model-switcher` (**S3**). Written 2026-07-28 after a cross-review of all three.

**Verdict: they were NOT in alignment.** Two real conflicts (M1, M2), two real ripple gaps
(M3, M4), and four coordination items. All are now resolved *in the specs* — this file is the
record of what was wrong and why, so the resolution is not silently re-litigated.

---

## M1 — Two competing config collections, both migrating the same fields ⚠️ REAL CONFLICT

**Was:** S1 added `local_providers: List[LocalProviderConfig]` and migrated the flat
`local_model_*` fields into it (S1 T1.4). S3 added `providers: dict[str, PersistedProvider]` and
**also** migrated the flat `local_model_*` fields into *that* (S3 T2.3).

**Why it mattered.** Two collections keyed differently reproduce at the config layer exactly the
split-registry problem S1 REQ-3 exists to delete — and the frontend would have two places to look
for "a provider". Worse, both migrations were specified **once-only and all-or-nothing** over the
*same source fields*. Whichever ran second would either double-migrate or find its source already
consumed, and both specs' atomicity rules would then be individually satisfied while the combined
result was inconsistent. This is the exact failure both rules were written to prevent, reached by
following both of them correctly.

**Resolved.** One collection, `InferenceConfig.providers`, keyed by id. **S1 creates it** (it lands
first) and owns local entries + the `local_model_*` migration. **S3 extends the same dict** with API
entries and owns the `api_base_url`/`api_key` migration. Ownership splits by *entry kind*, so
neither touches the other's source fields. Local entries carry no `cred_ref` — local providers are
keyless and unmetered ([`provider.py:16-22`](../backend/agent/inference/provider.py)).

Written into: S1 design § "Config collection ownership" + ripple map + T1.4; S3 REQ-5 Verified,
REQ-7 AC3, design data model + ripple map, T1.1, T2.3, sequencing notes.

---

## M2 — Encoders would appear in the settings Brain/Tool dropdowns ⚠️ REAL CONFLICT

**Was:** S2 REQ-6 AC3 states Embedding-350M and ColBERT are not bindable to `reasoning` /
`tool_execution`. S3 T3.3 filters them out of the *chat switcher*. But
[`ModelInferenceSection.tsx:80`](../components/ModelInferenceSection.tsx) builds
`providerOptions = providers.map(...)` with **no `purpose` filter** — and S1 classified that file
**CONTRACT LOCK / "keeps working unmodified" (CT-L6)**.

**Why it mattered.** S1's classification is *correct for S1* — its own additive fields genuinely
don't affect that file. It becomes wrong the moment S2 registers a non-chat provider, at which point
an embedding model is selectable as a reasoning model from settings. An implementer following S1's
ripple map would have treated the file as off-limits and shipped S2 with the bug.

This is the general hazard in per-spec ripple maps: **a NO-CHANGE claim is only valid against the
change that made it.** Verified-correct is not the same as permanently correct.

**Resolved.** S2 now owns the fix: T2.4b adds the `purpose === "chat"` filter, to land **in the same
change as T2.1** (registration), with `__tests__/ModelInferenceSection.test.tsx` asserting neither
purpose appears in either selector. S1 and S3 ripple maps both carry a forward-pointer so the
CONTRACT LOCK is not read as absolute.

---

## M3 — S1's ripple map missed two of the three fan-out sites ⚠️ REAL GAP

**Was:** S1 REQ-3 AC3 says delete the peer-kernel fan-out loops. Its ripple map named only
[`iris_gateway.py:7910`](../backend/iris_gateway.py). The code comment at `:7913-7914` explicitly
names two more — and both exist:

| Site | What |
|---|---|
| `:7910` | provider registration fan-out (was mapped) |
| `:8605-8618` | `set_role_binding` peer propagate, *"parity with set_model_selection"* (**was missing**) |
| `:6012` | `_handle_set_model_selection` (**was missing**) |
| `:1339-1407` | startup restore path calling both, with a load-bearing ordering comment (**was missing**) |

**Why it mattered.** A shared process-wide registry racing a surviving propagation loop is worse
than either alone — and `:8605` is the handler **S3's switcher writes through**, so the symptom
would have surfaced first in the newest UI and looked like a switcher bug.

**Resolved.** All three sites plus the restore path are in S1's ripple map. S3's map carries a
shared-path warning on the same handler.

---

## M4 — ContextPill's displayed number changes without a code change

**Was:** unstated anywhere. S1 REQ-5b reorders `resolve_context_window` so a loaded local model
reports its real `n_ctx`. ContextPill sources `max_tokens` from exactly that value
([`ContextPill.tsx:59-62`](../components/chat/ContextPill.tsx)).

**Why it mattered.** After S1, a 16k-loaded Mistral shows **16k instead of 32k**. Not a conflict —
it is REQ-3 AC3 ("real `max_tokens`, never hardcoded") becoming more true — but an implementer
seeing the denominator halve during S3 would reasonably suspect they broke something and "fix" it
back.

**Resolved.** S3 ripple map records it as NO CHANGE (code) / behaviour shifts, with "expect it, do
not fix it."

---

## Coordination items (no conflict, would have caused friction)

| # | Item | Resolution |
|---|---|---|
| M5 | `has_key` mis-classified in S3 as a **new** payload field | It already exists ([`provider.py:65`](../backend/agent/inference/provider.py)). S1 CT-L1 had it right. S3 corrected to NO CHANGE. |
| M6 | S3 specified building per-provider keyring storage | **Already exists** — `get_secret(self.id)` is keyed by provider id ([`provider.py:49-53`](../backend/agent/inference/provider.py)), and `ProviderInstance.api_key` is per-instance ([`:42`](../backend/agent/inference/provider.py)). The registry and keyring both already handle multiple providers; **only persistence is single-slot.** S3 T1.2 shrunk from "build a store" to "wire to the existing one" — rebuilding it would have risked the half that works. |
| M7 | All three specs claimed `bootstrap/GOALS.md` and `CADUCEAN_ARCHITECTURE.md` §9 | Domains assigned: **22** = S1, **23** = S2, **24** = S3. All three now say *append* a row to §9, not rewrite the table. |
| M8 | S1 `test_cpu_model_does_not_shrink_chat_context` vs S2 `test_encoders_do_not_shrink_chat_context` | Not duplicates — S1 uses synthetic instances (unit-level policy), S2 uses the real encoders (integration). Both kept deliberately; the same property from both sides is what catches a policy that is correct in isolation and wrong when wired. |

---

## Verified-clean seams

Checked and found consistent — no action:

- **`purpose` vocabulary** — `chat` / `embedding` / `rerank` identical across S1 REQ-2 AC3, S2 REQ-6,
  S3 T3.3.
- **Local id scheme** — `local:<model-stem>` in S1 REQ-2 AC1; S2 and S3 both defer to it rather than
  defining their own.
- **Device policy** — S1 `resolve_device_policy` is the single decision point; S2 consumes it and
  adds no second device decision.
- **GPU/CPU split** — S1 Policy Domain (chat GPU, Parakeet GPU, embedding/rerank CPU) matches S2
  REQ-6 AC4/AC5 exactly.
- **Routing mode** — S3 REQ-8 freezes `InferenceConfig.provider`; S1 and S2 neither read nor write
  it. Now stated explicitly in S1's ripple map rather than merely true.
- **Parakeet + TTS** — untouched by all three; NO CHANGE (verified) in S1, S2, and S3.
- **Harness scripts** — three distinct files, no collision.
- **`role_bindings`** — already a persisted list; all three specs read it, none reshapes it.

---

## Execution order

```
S1 Wave 0-1  ──► S1 T1.4 creates `providers` dict
                    │
     ┌──────────────┼──────────────────┐
     ▼              ▼                  ▼
S1 Wave 2-5    S3 Wave 1-2        (S3 T0.x, T3.1 anytime)
     │          persistence
     ▼              │
S2 Wave 0-3         │            S2 Wave 4 (DER) — fully parallel,
 retrieval          │                shares nothing with the rest
     │              ▼
     └────────► S3 Wave 3 (switcher — needs S1 `loaded` + S2 purpose filter)
```

The one hard ordering that is easy to get wrong: **S2 T2.4b (the purpose filter) must land with
S2 T2.1 (registration)**, not in S3's wave. Between those two tasks, encoders are bindable as
reasoning models.
