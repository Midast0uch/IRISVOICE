"use client"

import React from "react"

interface Provider { id: string; label: string; kind: string; model: string; has_key?: boolean; loaded?: boolean; loading?: boolean }
interface Binding { role: string; instance_id: string; model_override?: string }

/**
 * Model routing at a glance: which provider serves which role, and what each
 * provider holds, as one compact table in the ink look. Read-only; the controls
 * (ModelInferenceSection) sit under it.
 */
export function ModelRoutingTable({ providers = [], role_bindings = [] }: { providers: Provider[]; role_bindings: Binding[] }) {
  if (!providers.length) return null
  const roles = (id: string) => role_bindings.filter((b) => b.instance_id === id).map((b) => b.role)
  return (
    <table className="iris-tbl" aria-label="Model routing">
      <thead>
        <tr><th>Provider</th><th>Model</th><th>Serves</th><th>State</th></tr>
      </thead>
      <tbody>
        {providers.map((p) => {
          const serves = roles(p.id)
          const bound = role_bindings.find((b) => b.instance_id === p.id && b.model_override)
          return (
            <tr key={p.id} data-active={serves.length > 0}>
              <td>{p.label || p.id}<small>{p.kind}</small></td>
              <td>{bound?.model_override || p.model || '—'}</td>
              <td>{serves.length ? serves.join(' · ') : '—'}</td>
              <td>{p.loading ? 'loading' : p.loaded ? 'loaded' : p.has_key ? 'key saved' : 'idle'}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
