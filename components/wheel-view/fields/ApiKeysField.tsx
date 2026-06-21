"use client"

import React, { useState, useCallback, useEffect, useRef } from "react"
import { Eye, EyeOff, Check, AlertTriangle, Key, Info } from "lucide-react"

interface ApiKeysFieldProps {
  id: string
  label: string
  value: string  // JSON string of saved keys
  glowColor: string
  sendMessage?: (type: string, payload?: any) => boolean
}

const KEY_DEFINITIONS = [
  {
    id: "picovoice_access_key",
    label: "Picovoice Access Key",
    placeholder: "PICOVOICE_ACCESS_KEY",
    required: true,
    help: "Required for wake word detection. Get a free key at console.picovoice.ai",
    link: "https://console.picovoice.ai/",
  },
  {
    id: "hf_token",
    label: "HuggingFace Token",
    placeholder: "hf_...",
    required: false,
    help: "Optional — for model downloads from HuggingFace. Get a token at huggingface.co/settings/tokens",
    link: "https://huggingface.co/settings/tokens",
  },
]

export function ApiKeysField({
  id,
  label,
  value,
  glowColor,
  sendMessage,
}: ApiKeysFieldProps) {
  // Parse existing keys from the value JSON
  const parsed = useRef<Record<string, string>>({})
  try {
    parsed.current = value ? JSON.parse(value) : {}
  } catch {
    parsed.current = {}
  }

  const [keys, setKeys] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {}
    KEY_DEFINITIONS.forEach((k) => {
      initial[k.id] = parsed.current[k.id] || ""
    })
    return initial
  })
  const [visible, setVisible] = useState<Record<string, boolean>>({})
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const hasChanges = KEY_DEFINITIONS.some(
    (k) => (keys[k.id] || "") !== (parsed.current[k.id] || "")
  )

  const handleSave = useCallback(() => {
    const missing = KEY_DEFINITIONS.filter(
      (k) => k.required && !keys[k.id]?.trim()
    )
    if (missing.length > 0) {
      setError(
        `Required keys missing: ${missing.map((k) => k.label).join(", ")}`
      )
      return
    }

    setSaving(true)
    setError(null)

    if (sendMessage) {
      sendMessage("confirm_card", {
        section_id: "api_keys",
        card_id: "api_keys_save",
        action: "save",
        values: keys,
      })
    }

    // Optimistic: show saved state after brief delay
    setTimeout(() => {
      setSaving(false)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    }, 600)
  }, [keys, sendMessage])

  // Listen for backend confirmations
  useEffect(() => {
    const handler = (event: any) => {
      const detail = event.detail
      if (!detail || detail.type !== "update_field") return
      const payload = detail.payload || {}

      // Load: backend sends current saved keys
      if (payload.field_id === "api_keys_data" && payload.value) {
        try {
          const data = typeof payload.value === "string"
            ? JSON.parse(payload.value)
            : payload.value
          const updated: Record<string, string> = {}
          KEY_DEFINITIONS.forEach((k) => {
            updated[k.id] = data[k.id] || ""
          })
          setKeys(updated)
        } catch {
          // ignore parse errors
        }
      }

      // Save confirmation
      if (payload.field_id === "api_keys_saved") {
        setSaving(false)
        setSaved(true)
        setTimeout(() => setSaved(false), 2500)
      }

      // Error
      if (payload.field_id === "api_keys_error") {
        setError(payload.value || "Failed to save keys")
        setSaving(false)
      }
    }
    window.addEventListener("iris:ws_message", handler)
    return () => window.removeEventListener("iris:ws_message", handler)
  }, [])

  const toggleVisibility = (keyId: string) => {
    setVisible((prev) => ({ ...prev, [keyId]: !prev[keyId] }))
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-1.5 mb-1">
        <Key size={12} style={{ color: glowColor }} />
        <span className="text-[10px] font-bold uppercase tracking-wider text-white/60">
          {label}
        </span>
      </div>

      {KEY_DEFINITIONS.map((keyDef) => (
        <div key={keyDef.id} className="flex flex-col gap-1">
          <label
            htmlFor={`api-key-${keyDef.id}`}
            className="text-[9px] font-bold uppercase tracking-wider text-white/40"
          >
            {keyDef.label}
            {keyDef.required && (
              <span className="text-red-400 ml-1">*</span>
            )}
          </label>
          <div className="relative">
            <input
              id={`api-key-${keyDef.id}`}
              type={visible[keyDef.id] ? "text" : "password"}
              value={keys[keyDef.id] || ""}
              onChange={(e) => {
                setKeys((prev) => ({ ...prev, [keyDef.id]: e.target.value }))
                setError(null)
              }}
              placeholder={keyDef.placeholder}
              className="w-full bg-white/[0.03] border border-white/[0.08] rounded-md px-3 py-2 pr-8 text-[11px] text-white/70 placeholder:text-white/20 font-mono focus:outline-none focus:border-white/20 transition-colors"
              style={{ borderColor: `${glowColor}15`, background: "rgba(0,0,0,0.2)" }}
            />
            <button
              type="button"
              onClick={() => toggleVisibility(keyDef.id)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60 transition-colors"
              tabIndex={-1}
            >
              {visible[keyDef.id] ? (
                <EyeOff size={13} />
              ) : (
                <Eye size={13} />
              )}
            </button>
          </div>
          <div className="flex items-start gap-1">
            <Info size={9} className="text-white/20 mt-[2px] flex-shrink-0" />
            <span className="text-[8px] text-white/25 leading-tight">
              {keyDef.help}
            </span>
          </div>
        </div>
      ))}

      {/* Status / error */}
      {error && (
        <div
          className="flex items-start gap-1.5 p-2 rounded-md text-[10px]"
          style={{
            background: "rgba(239,68,68,0.08)",
            border: "1px solid rgba(239,68,68,0.2)",
          }}
        >
          <AlertTriangle size={11} className="flex-shrink-0 mt-[1px]" style={{ color: "#ef4444" }} />
          <span style={{ color: "#ef4444cc" }}>{error}</span>
        </div>
      )}

      {/* Save button */}
      <button
        onClick={handleSave}
        disabled={saving || !hasChanges}
        className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all duration-200 disabled:opacity-40"
        style={{
          background: saved
            ? "rgba(34,197,94,0.15)"
            : hasChanges
            ? `${glowColor}20`
            : "rgba(255,255,255,0.03)",
          color: saved ? "#22c55e" : hasChanges ? glowColor : "rgba(255,255,255,0.3)",
          border: `1px solid ${
            saved
              ? "rgba(34,197,94,0.3)"
              : hasChanges
              ? `${glowColor}30`
              : "rgba(255,255,255,0.05)"
          }`,
        }}
      >
        {saved ? (
          <>
            <Check size={11} />
            Saved
          </>
        ) : saving ? (
          "Saving..."
        ) : (
          <>
            <Key size={11} />
            {hasChanges ? "Save API Keys" : "No Changes"}
          </>
        )}
      </button>

      {/* Links to key providers */}
      <div className="flex flex-col gap-1 p-2 rounded-md" style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.04)" }}>
        <span className="text-[8px] font-bold uppercase tracking-wider text-white/20 mb-0.5">
          Get API Keys
        </span>
        {KEY_DEFINITIONS.map((keyDef) => (
          <a
            key={keyDef.id}
            href={keyDef.link}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[9px] hover:underline"
            style={{ color: `${glowColor}aa` }}
          >
            {keyDef.label} → {keyDef.link.replace("https://", "")}
          </a>
        ))}
      </div>
    </div>
  )
}
