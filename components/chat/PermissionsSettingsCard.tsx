"use client"

import React, { useState, useEffect, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ShieldCheck, Shield, RefreshCw, Loader, Check } from "lucide-react"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { CardChassis, ChassisBadge } from "@/components/chat/CardChassis"

export type PermissionMode = "personal" | "developer"

export interface PermissionsConfig {
  mode: PermissionMode | null
  effective_mode: PermissionMode
  approved_tools: string[]
  available_tools: string[]
}

interface PermissionsSettingsCardProps {
  /** Optional override for the config endpoint (used by tests). */
  configUrl?: string
}

const MODE_LABEL: Record<PermissionMode, string> = {
  personal: "Personal",
  developer: "Developer",
}

/**
 * PermissionsSettingsCard — the standing permission-mode + approved-tools
 * settings surface (REQ-19 AC3/AC5, REQ-16 AC2). Rendered on the shared
 * Liquid Ink `CardChassis` so it reads as part of the same chat-stream system
 * as the per-tool `PermissionCard` (which this card is NOT — that one is the
 * inline per-request approval prompt; this is the settings surface).
 *
 * The card always displays the EFFECTIVE mode (REQ-16 AC2) — the truthful
 * current mode returned by the backend — not merely the stored `mode`. After
 * any toggle it re-fetches `/api/config` so the effective mode and approved
 * tools update IMMEDIATELY (REQ-19 AC5).
 */
export function PermissionsSettingsCard({
  configUrl = "/api/config",
}: PermissionsSettingsCardProps) {
  const { getThemeConfig } = useBrandColor()
  const brandTheme = getThemeConfig()
  const glowColor = brandTheme.glow.color || "#00d4ff"

  const [config, setConfig] = useState<PermissionsConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [modeBusy, setModeBusy] = useState(false)
  const [toolsBusy, setToolsBusy] = useState(false)

  const loadConfig = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(configUrl)
      if (!res.ok) throw new Error(`GET ${configUrl} returned ${res.status}`)
      const data = (await res.json()) as PermissionsConfig
      setConfig(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load permissions")
    } finally {
      setLoading(false)
    }
  }, [configUrl])

  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  const changeMode = useCallback(
    async (mode: PermissionMode) => {
      if (modeBusy || !config || config.effective_mode === mode) return
      setModeBusy(true)
      try {
        const res = await fetch("/api/mode", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode }),
        })
        if (!res.ok) throw new Error(`POST /api/mode returned ${res.status}`)
        // Re-fetch so the effective mode reflects the persisted state immediately.
        await loadConfig()
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to change mode")
      } finally {
        setModeBusy(false)
      }
    },
    [modeBusy, config, loadConfig],
  )

  const toggleTool = useCallback(
    async (tool: string) => {
      if (toolsBusy || !config) return
      const isApproved = config.approved_tools.includes(tool)
      const next = isApproved
        ? config.approved_tools.filter((t) => t !== tool)
        : [...config.approved_tools, tool]
      setToolsBusy(true)
      try {
        const res = await fetch("/api/approved-tools", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approved_tools: next }),
        })
        if (!res.ok) throw new Error(`POST /api/approved-tools returned ${res.status}`)
        // Re-fetch to confirm the persisted approved list.
        await loadConfig()
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to update approved tools")
      } finally {
        setToolsBusy(false)
      }
    },
    [toolsBusy, config, loadConfig],
  )

  const effectiveMode = config?.effective_mode ?? null
  const approvedSet = new Set(config?.approved_tools ?? [])
  const availableTools = config?.available_tools ?? []

  return (
    <CardChassis
      veinColor={glowColor}
      isActive={loading}
      collapsible={false}
      aria-label="Permissions settings"
      header={
        <>
          <span
            className="relative shrink-0"
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: `radial-gradient(circle at 35% 30%, #aef3ff, ${glowColor} 60%, #006b8a)`,
              boxShadow: `0 0 10px ${glowColor}, inset 0 0 4px rgba(255,255,255,0.6)`,
            }}
          />
          <ChassisBadge
            color={glowColor}
            background={`${glowColor}1a`}
            border={`1px solid ${glowColor}30`}
            icon={<ShieldCheck size={10} />}
          >
            Permissions
          </ChassisBadge>
        </>
      }
    >
      {loading && !config ? (
        <div className="flex items-center gap-2 text-[11px]" style={{ color: "rgba(255,255,255,0.6)" }}>
          <Loader size={12} className="animate-spin" />
          Loading permissions…
        </div>
      ) : error && !config ? (
        <div className="flex flex-col gap-2">
          <p className="text-[11px]" style={{ color: "rgba(239,68,68,0.9)" }}>
            {error}
          </p>
          <button
            type="button"
            onClick={loadConfig}
            className="flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-semibold transition-colors self-start"
            style={{ color: glowColor, border: `1px solid ${glowColor}40` }}
          >
            <RefreshCw size={11} />
            Retry
          </button>
        </div>
      ) : config ? (
        <div className="flex flex-col gap-3">
          {/* Effective mode — REQ-16 AC2: show the truthful current mode. */}
          <div className="flex items-center gap-2">
            <Shield size={12} style={{ color: glowColor }} />
            <span className="text-[10px] uppercase tracking-wide" style={{ color: "rgba(255,255,255,0.5)" }}>
              Permission mode
            </span>
            <span
              className="text-[11px] font-semibold ml-auto"
              style={{ color: glowColor }}
              data-testid="effective-mode"
            >
              {effectiveMode ? MODE_LABEL[effectiveMode] : "—"}
              <span className="text-[9px] font-normal ml-1" style={{ color: "rgba(255,255,255,0.4)" }}>
                (effective)
              </span>
            </span>
          </div>

          {/* Mode toggle — segmented control. */}
          <div className="flex items-center gap-1 p-0.5 rounded-lg" style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)" }}>
            {(["personal", "developer"] as PermissionMode[]).map((mode) => {
              const active = effectiveMode === mode
              return (
                <button
                  key={mode}
                  type="button"
                  disabled={modeBusy}
                  onClick={() => changeMode(mode)}
                  className="flex-1 py-1.5 rounded-md text-[10px] font-semibold transition-colors disabled:opacity-50"
                  style={{
                    color: active ? "#05060c" : "rgba(255,255,255,0.6)",
                    backgroundColor: active ? glowColor : "transparent",
                  }}
                  aria-pressed={active}
                >
                  {MODE_LABEL[mode]}
                </button>
              )
            })}
          </div>

          {/* Standing approved-tools list. */}
          <div className="flex flex-col gap-1">
            <span className="text-[9px] uppercase tracking-wider" style={{ color: "rgba(255,255,255,0.35)" }}>
              Approved tools
            </span>
            {availableTools.length === 0 ? (
              <p className="text-[10px]" style={{ color: "rgba(255,255,255,0.4)" }}>
                No tools available to pre-approve.
              </p>
            ) : (
              availableTools.map((tool) => {
                const on = approvedSet.has(tool)
                return (
                  <button
                    key={tool}
                    type="button"
                    disabled={toolsBusy}
                    onClick={() => toggleTool(tool)}
                    className="flex items-center gap-2 px-2 py-1.5 rounded-md transition-colors disabled:opacity-50 hover:bg-white/5"
                    style={{ border: `1px solid ${on ? `${glowColor}40` : "rgba(255,255,255,0.08)"}` }}
                    aria-pressed={on}
                  >
                    <span
                      className="w-3.5 h-3.5 rounded flex items-center justify-center shrink-0 transition-colors"
                      style={{
                        background: on ? glowColor : "rgba(255,255,255,0.08)",
                        border: `1px solid ${on ? glowColor : "rgba(255,255,255,0.2)"}`,
                      }}
                    >
                      {on && <Check size={9} style={{ color: "#05060c" }} />}
                    </span>
                    <span className="font-mono text-[10px]" style={{ color: on ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.6)" }}>
                      {tool}
                    </span>
                  </button>
                )
              })
            )}
          </div>

          {/* Inline error banner (non-fatal — config still rendered). */}
          <AnimatePresence>
            {error && (
              <motion.p
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                className="text-[10px]"
                style={{ color: "rgba(239,68,68,0.9)" }}
              >
                {error}
              </motion.p>
            )}
          </AnimatePresence>
        </div>
      ) : null}
    </CardChassis>
  )
}

export default PermissionsSettingsCard
