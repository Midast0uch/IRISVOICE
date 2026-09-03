"use client"

import React, { useState } from "react"
import { Copy, Download, X, FileText } from "lucide-react"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { RichDocument } from "./RichDocument"
// T11a (REQ-2 AC6): the expanded document panel renders on the SAME Liquid Ink
// chassis as the inline `RichDocument` card it expands from, so expanding a
// document does not change the surface mid-interaction. CT-10 pins this import.
import { CardChassis } from "@/components/chat/CardChassis"

interface DocumentPanelProps {
  content: string
  format: string
  alternatives: string[]
  glowColor?: string
  onClose: () => void
  onFormatChange: (newFormat: string) => void
  // Trust-routing W3: forwarded to RichDocument for HTML sanitization.
  trust?: string
}

/**
 * DocumentPanel — full-panel document viewer for the dashboard wing (plan §4.6).
 *
 * Wraps RichDocument on the shared Liquid Ink `CardChassis` (T11a). The toolbar
 * (copy / download / close / format switcher) is the chassis header; the
 * document body is the chassis body and scrolls inside the panel. The chassis
 * supplies the surface, vein and padding, so the expanded view is visually
 * continuous with the inline card.
 */
export function DocumentPanel({
  content,
  format,
  alternatives,
  glowColor: glowColorProp,
  onClose,
  onFormatChange,
  trust,
}: DocumentPanelProps) {
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const glowColor = glowColorProp ?? theme.glow.color
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(content).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleDownload = () => {
    const ext = format === "html" ? "html" : "md"
    const blob = new Blob([content], { type: "text/plain" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `iris-document.${ext}`
    a.click()
    URL.revokeObjectURL(url)
  }

  const toolbar = (
    <div
      className="flex items-center gap-2 border-b shrink-0"
      style={{ borderColor: "rgba(255,255,255,0.06)" }}
    >
      <FileText size={14} style={{ color: glowColor }} />
      <span
        className="text-[10px] font-semibold tracking-wide uppercase"
        style={{ color: glowColor }}
      >
        Document
      </span>
      <span
        className="text-[9px] px-1.5 py-0.5 rounded"
        style={{
          color: glowColor,
          backgroundColor: `${glowColor}12`,
          border: `1px solid ${glowColor}30`,
        }}
      >
        {format}
      </span>

      {/* Format switcher */}
      {alternatives.length > 0 && (
        <div className="flex items-center gap-1 ml-2">
          {alternatives.map((alt) => (
            <button
              key={alt}
              onClick={() => onFormatChange(alt)}
              className="px-2 py-0.5 rounded text-[9px] font-medium tracking-wide transition-all duration-150 hover:brightness-125"
              style={{
                color: alt === format ? glowColor : "rgba(255,255,255,0.4)",
                backgroundColor:
                  alt === format ? `${glowColor}12` : "rgba(255,255,255,0.03)",
                border:
                  alt === format
                    ? `1px solid ${glowColor}30`
                    : "1px solid rgba(255,255,255,0.06)",
              }}
            >
              {alt}
            </button>
          ))}
        </div>
      )}

      <div className="ml-auto flex items-center gap-1.5">
        <button
          onClick={handleCopy}
          className="p-1.5 rounded transition-all duration-150 hover:brightness-125"
          style={{
            color: copied ? "#22c55e" : "rgba(255,255,255,0.4)",
            backgroundColor: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.08)",
          }}
          title="Copy"
        >
          <Copy size={11} />
        </button>
        <button
          onClick={handleDownload}
          className="p-1.5 rounded transition-all duration-150 hover:brightness-125"
          style={{
            color: "rgba(255,255,255,0.4)",
            backgroundColor: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.08)",
          }}
          title="Download"
        >
          <Download size={11} />
        </button>
        <button
          onClick={onClose}
          className="p-1.5 rounded transition-all duration-150 hover:brightness-125"
          style={{
            color: "rgba(255,255,255,0.4)",
            backgroundColor: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.08)",
          }}
          title="Close"
        >
          <X size={11} />
        </button>
      </div>
    </div>
  )

  return (
    <CardChassis
      veinColor={glowColor}
      header={toolbar}
      collapsible={false}
      fill
      className="h-full"
      aria-label="Expanded document"
    >
      <RichDocument
        content={content}
        format={format as "markdown" | "html" | "table" | "diagram" | "text"}
        glowColor={glowColor}
        alternatives={[]}
        trust={trust}
      />
    </CardChassis>
  )
}
