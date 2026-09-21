"use client"

import React, { useMemo, useState, useRef, useEffect, lazy, Suspense } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { Components } from "react-markdown"
import { motion, AnimatePresence } from "framer-motion"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { 
  Expand, 
  ChevronDown, 
  Copy, 
  Check, 
  ExternalLink,
  Layers
} from "lucide-react"
import DOMPurify from "dompurify"

const MermaidDiagram = lazy(() => import("@/components/chat/MermaidDiagram"))

export interface RichDocumentV2Props {
  content: string
  format?: "markdown" | "html" | "table" | "diagram" | "text" | "json" | "image"
  glowColor?: string
  alternatives?: string[]
  onFormatChange?: (newFormat: string) => void
  onExpand?: () => void
  trust?: string
  sources?: {
    url: string
    title: string
    status?: "planned" | "reading" | "read" | "blocked" | "parked"
  }[]
  updated?: boolean
}

const COLLAPSED_MAX_HEIGHT = 440

export function RichDocumentV2({
  content,
  format = "markdown",
  glowColor: glowColorProp,
  alternatives = [],
  onFormatChange,
  onExpand,
  trust,
  sources,
  updated,
}: RichDocumentV2Props) {
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const glowColor = glowColorProp ?? theme.glow?.color ?? "#00d4ff"

  const [expanded, setExpanded] = useState(false)
  const [overflows, setOverflows] = useState(false)
  const [copied, setCopied] = useState(false)
  const bodyRef = useRef<HTMLDivElement>(null)

  const truncatedContent = useMemo(() => {
    return content.length > 50000
      ? content.slice(0, 50000) + "\n\n*[Document truncated at 50,000 characters]*"
      : content
  }, [content])

  const sanitizedHtml = useMemo(() => {
    if (format !== "html" || trust === "trusted") return truncatedContent
    if (typeof window === "undefined") return truncatedContent
    return DOMPurify.sanitize(truncatedContent)
  }, [format, truncatedContent, trust])

  const hasMermaid = useMemo(() => /```mermaid/.test(content), [content])

  useEffect(() => {
    const el = bodyRef.current
    if (!el) return
    const measure = () => {
      setOverflows(el.scrollHeight > COLLAPSED_MAX_HEIGHT + 10)
    }
    measure()
    if (typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [truncatedContent, format])

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // ignore
    }
  }

  // Custom Markdown Element Overrides
  const markdownComponents = useMemo<Components>(() => {
    return {
      table: ({ children }) => (
        <div
          className="my-2.5 rounded-lg overflow-x-auto border border-white/10"
          style={{ background: "rgba(0, 0, 0, 0.35)" }}
        >
          <table className="w-full text-left text-[11px] font-mono border-collapse">
            {children}
          </table>
        </div>
      ),
      thead: ({ children }) => (
        <thead className="border-b border-white/10 bg-white/[0.04]">{children}</thead>
      ),
      th: ({ children }) => (
        <th className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-cyan-300">
          {children}
        </th>
      ),
      td: ({ children }) => (
        <td className="px-3 py-1.5 text-white/75 border-b border-white/5">
          {children}
        </td>
      ),
      code: ({ node, className, children, ...props }) => {
        const nodeAny = node as unknown as Record<string, unknown> | undefined
        const parentTagName = (nodeAny?.parent as Record<string, unknown> | undefined)?.tagName
        const isBlock = parentTagName === "pre" || /language-/.test(className || "")

        if (!isBlock) {
          return (
            <code
              className="px-1.5 py-0.5 rounded text-[10px] font-mono font-medium text-cyan-300 bg-cyan-950/40 border border-cyan-500/20"
              {...props}
            >
              {children}
            </code>
          )
        }
        return <code className={className} {...props}>{children}</code>
      },
      pre: ({ children }) => {
        const childArray = React.Children.toArray(children)
        const firstChild = childArray[0]
        const isMermaid =
          React.isValidElement<{ className?: string; children?: React.ReactNode }>(firstChild) &&
          typeof firstChild.props.className === "string" &&
          firstChild.props.className.includes("language-mermaid") &&
          hasMermaid

        if (isMermaid) {
          return (
            <Suspense fallback={<div className="text-[10px] text-white/30 p-2 my-2">Loading diagram...</div>}>
              <MermaidDiagram chart={String(firstChild.props.children)} glowColor={glowColor} trust={trust} />
            </Suspense>
          )
        }

        return (
          <div className="my-2 rounded-lg overflow-hidden border border-white/10 bg-black/50">
            <pre className="p-3 text-[10.5px] font-mono text-white/85 leading-relaxed overflow-x-auto">
              {children}
            </pre>
          </div>
        )
      },
      h1: ({ children }) => (
        <h1 className="text-[13.5px] font-bold tracking-tight text-white/95 mt-3 mb-2 pb-1 border-b border-white/10">
          {children}
        </h1>
      ),
      h2: ({ children }) => (
        <h2 className="text-[12px] font-semibold text-white/90 mt-2.5 mb-1.5">
          {children}
        </h2>
      ),
      h3: ({ children }) => (
        <h3 className="text-[11px] font-medium text-cyan-300/90 mt-2 mb-1">
          {children}
        </h3>
      ),
      p: ({ children }) => (
        <p className="text-[12px] leading-relaxed text-white/80 mb-2">
          {children}
        </p>
      ),
      ul: ({ children }) => (
        <ul className="pl-4 space-y-1 my-2 text-[11.5px] text-white/75 list-disc list-outside marker:text-cyan-400">
          {children}
        </ul>
      ),
      ol: ({ children }) => (
        <ol className="pl-4 space-y-1 my-2 text-[11.5px] text-white/75 list-decimal list-outside marker:text-cyan-400 font-mono">
          {children}
        </ol>
      ),
      blockquote: ({ children }) => (
        <blockquote className="my-2 p-2.5 rounded-r-lg border-l-2 border-cyan-400 bg-white/[0.03] text-[11.5px] text-white/70 italic">
          {children}
        </blockquote>
      ),
    }
  }, [glowColor, hasMermaid, trust])

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.2 }}
      className="my-2.5 w-full"
    >
      {/* ── High-Contrast Document Panel (No clunky header banner) ── */}
      <div
        className="rounded-xl overflow-hidden relative border shadow-2xl transition-all group/doc"
        style={{
          background: "linear-gradient(160deg, rgba(8, 10, 18, 0.94) 0%, rgba(12, 14, 26, 0.96) 100%)",
          borderColor: "rgba(255, 255, 255, 0.08)",
          boxShadow: "0 6px 20px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.04)",
        }}
      >
        {/* Subtle hover actions in top-right (Copy / Expand) */}
        <div className="absolute top-2.5 right-2.5 z-10 flex items-center gap-1 opacity-60 group-hover/doc:opacity-100 transition-opacity">
          {updated && (
            <span className="text-[8px] font-mono text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/20">
              updated
            </span>
          )}

          <button
            onClick={handleCopy}
            className="p-1 rounded text-white/40 hover:text-white/80 hover:bg-white/10 transition-colors"
            title="Copy content"
          >
            {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
          </button>

          {onExpand && (
            <button
              onClick={onExpand}
              className="p-1 rounded text-white/40 hover:text-white/80 hover:bg-white/10 transition-colors"
              title="Expand to panel"
            >
              <Expand size={12} />
            </button>
          )}
        </div>

        {/* Document Body */}
        <div
          ref={bodyRef}
          className="rich-doc-body px-4 py-3.5 overflow-y-auto overflow-x-hidden"
          style={{
            maxHeight: expanded ? undefined : COLLAPSED_MAX_HEIGHT,
            overflowWrap: "anywhere",
            wordBreak: "break-word",
          }}
        >
          {format === "html" ? (
            <div dangerouslySetInnerHTML={{ __html: sanitizedHtml }} className="text-[11.5px] text-white/75" />
          ) : format === "json" ? (
            <pre className="text-[10.5px] font-mono text-white/75 leading-relaxed whitespace-pre-wrap m-0">
              {truncatedContent}
            </pre>
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {truncatedContent}
            </ReactMarkdown>
          )}
        </div>

        {/* Fade & Expand Button */}
        {overflows && !expanded && (
          <div
            className="absolute left-0 right-0 bottom-0 h-14 pointer-events-none"
            style={{
              background: "linear-gradient(to bottom, transparent, rgba(10, 12, 22, 0.96))",
            }}
          />
        )}

        {overflows && (
          <div className="relative flex justify-center pb-2 pt-1">
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 px-3 py-1 rounded-full text-[9px] font-mono uppercase tracking-wider text-cyan-300 bg-cyan-950/40 border border-cyan-500/30 hover:bg-cyan-900/40 transition-colors"
            >
              <ChevronDown
                size={10}
                style={{
                  transform: expanded ? "rotate(180deg)" : "rotate(0deg)",
                  transition: "transform 0.16s ease",
                }}
              />
              {expanded ? "Collapse" : "Show more"}
            </button>
          </div>
        )}

        {/* Sources Tray (Unobtrusive & Concise) */}
        {sources && sources.length > 0 && (
          <div className="px-4 py-2 border-t border-white/6 bg-black/20 text-[9px] font-mono text-white/40 flex items-center gap-2">
            <Layers size={10} />
            <span className="truncate">
              Sources: {sources.map((s, i) => `${i + 1}. ${s.title || s.url}`).join(" · ")}
            </span>
          </div>
        )}
      </div>
    </motion.div>
  )
}
