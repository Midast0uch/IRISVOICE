"use client"

import React, { useState } from "react"
import { motion } from "framer-motion"
import { Copy, Download, X, FileText } from "lucide-react"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { RichDocument } from "./RichDocument"

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
 * Wraps RichDocument in a full-height scrollable container with a toolbar:
 * copy, download, close, and format switcher.
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
  const shimmerPrimary = theme.shimmer.primary
  const glassBlur = theme.glass.blur
  const glassOpacity = theme.glass.opacity
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

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className="h-full flex flex-col"
    >
      {/* Toolbar */}
      <div
        className="flex items-center gap-2 p-3 border-b shrink-0"
        style={{
          borderColor: "rgba(255,255,255,0.06)",
          background: `linear-gradient(135deg, rgba(10,11,22,${0.6 + glassOpacity * 2}) 0%, rgba(15,16,28,${0.65 + glassOpacity * 2}) 100%)`,
          backdropFilter: `blur(${glassBlur}px)`,
          WebkitBackdropFilter: `blur(${glassBlur}px)`,
        }}
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

      {/* Document content — full scroll */}
      <div className="flex-1 overflow-y-auto p-4">
        <RichDocument
          content={content}
          format={format as "markdown" | "html" | "table" | "diagram" | "text"}
          glowColor={glowColor}
          alternatives={[]}
          trust={trust}
        />
      </div>
    </motion.div>
  )
}
