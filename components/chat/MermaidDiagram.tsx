"use client"

import { useEffect, useRef, useState } from "react"
import mermaid from "mermaid"

interface MermaidDiagramProps {
  chart: string
  glowColor: string
  // Trust-routing W3: untrusted diagrams (web/crawler-sourced) render with
  // securityLevel "strict" to block embedded scripts/click handlers.
  trust?: string
}

export default function MermaidDiagram({ chart, glowColor, trust }: MermaidDiagramProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [svg, setSvg] = useState<string>("")
  const [error, setError] = useState<string>("")

  useEffect(() => {
    let cancelled = false
    // Re-initialize per render so securityLevel tracks the document's trust.
    // Trusted diagrams keep "loose" (allows richer interactivity); untrusted
    // diagrams use "strict" to neutralize script injection via chart markup.
    mermaid.initialize({
      startOnLoad: false,
      theme: "dark",
      // Phase 5.1 / chat-card-redesign §2.8: drive diagram chrome from the
      // active brand glowColor instead of a hardcoded hex so the diagram
      // shifts with the orb/theme like every other card.
      themeVariables: {
        primaryColor: "#0a0b16",
        primaryTextColor: "#ffffff",
        primaryBorderColor: glowColor,
        lineColor: glowColor,
        secondaryColor: "#0f101c",
        tertiaryColor: "#15162a",
        background: "#0a0b16",
        mainBkg: "#0a0b16",
        nodeBorder: glowColor,
        clusterBkg: "#0a0b16",
        titleColor: glowColor,
        edgeLabelBackground: "#0a0b16",
      },
      securityLevel: trust === "trusted" ? "loose" : "strict",
    })
    const id = `mermaid-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    mermaid
      .render(id, chart)
      .then((result) => {
        if (!cancelled) setSvg(result.svg)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Diagram render failed")
      })
    return () => {
      cancelled = true
    }
  }, [chart, trust])

  if (error) {
    return (
      <div
        className="p-2 rounded-lg text-[10px] font-mono my-2"
        style={{
          color: "rgba(239,68,68,0.7)",
          background: "rgba(239,68,68,0.06)",
          border: "1px solid rgba(239,68,68,0.2)",
        }}
      >
        Diagram error: {error}
      </div>
    )
  }

  return (
    // chat-card-redesign §2.8: wrap the diagram in the same Prism Glass card
    // as RichDocument/DocumentPanel so it matches the document family.
    <div
      ref={containerRef}
      className="my-2 flex justify-center rounded-lg overflow-hidden relative"
      style={{
        background:
          "linear-gradient(135deg, rgba(10,11,22,0.6) 0%, rgba(15,16,28,0.65) 100%)",
        backdropFilter: "blur(24px)",
        WebkitBackdropFilter: "blur(24px)",
        borderLeft: `2px solid ${glowColor}`,
        border: `1px solid ${glowColor}20`,
        color: glowColor,
      }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
