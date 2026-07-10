"use client"

import React, { useMemo, lazy, Suspense } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { Components } from "react-markdown"
import { motion } from "framer-motion"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { Expand } from "lucide-react"
import DOMPurify from "dompurify"

// Lazy-load mermaid only when a ```mermaid block is present
const MermaidDiagram = lazy(() => import("./MermaidDiagram"))

interface RichDocumentProps {
  content: string
  format: "markdown" | "html" | "table" | "diagram" | "text"
  glowColor?: string
  alternatives?: string[]
  onFormatChange?: (newFormat: string) => void
  onExpand?: () => void
  // Trust-routing W3: "trusted" renders raw HTML; anything else is sanitized
  // with DOMPurify before being injected (untrusted = web/crawler-sourced).
  trust?: string
}

/**
 * RichDocument — custom Prism Glass markdown renderer (plan §4.2–4.4).
 *
 * Uses react-markdown as the parsing engine with custom-styled element
 * overrides that match the widget's Prism Glass aesthetic (dark glass cards,
 * brand-color accents, monospace labels, orbital glow).
 *
 * Adapts to react-markdown v10+ API (no `inline` prop on code component;
 * uses `node.parent.tagName === 'pre'` to detect block vs inline code).
 */
export function RichDocument({
  content,
  format,
  glowColor: glowColorProp,
  alternatives = [],
  onFormatChange,
  onExpand,
  trust,
}: RichDocumentProps) {
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const glowColor = glowColorProp ?? theme.glow.color
  const shimmerPrimary = theme.shimmer.primary
  const glassBlur = theme.glass.blur
  const glassOpacity = theme.glass.opacity

  // Detect mermaid blocks for conditional lazy loading
  const hasMermaid = useMemo(() => /```mermaid/.test(content), [content])
  // Truncate at 50,000 chars (plan §8 risk 5)
  const truncatedContent =
    content.length > 50000 ? content.slice(0, 50000) + "\n\n*[Document truncated at 50,000 characters]*" : content

  // Trust-routing W3: untrusted HTML (web/crawler-sourced) is sanitized with
  // DOMPurify before injection. Trusted HTML is rendered raw. Guarded for SSR
  // (no window) — falls back to raw content, which is only ever injected client-side.
  const sanitizedHtml = useMemo(() => {
    if (format !== "html" || trust === "trusted") return truncatedContent
    if (typeof window === "undefined") return truncatedContent
    return DOMPurify.sanitize(truncatedContent)
  }, [format, truncatedContent, trust])

  // Memoize components object so ReactMarkdown doesn't re-render on parent update
  const markdownComponents = useMemo<Components>(
    () => getMarkdownComponents(glowColor, shimmerPrimary, hasMermaid, trust),
    [glowColor, shimmerPrimary, hasMermaid, trust]
  )

  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8, scale: 0.98 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className="my-3 w-full"
    >
      <div
        className="rounded-lg overflow-hidden relative"
        style={{
          background: `linear-gradient(135deg, rgba(10,11,22,${0.6 + glassOpacity * 2}) 0%, rgba(15,16,28,${0.65 + glassOpacity * 2}) 100%)`,
          backdropFilter: `blur(${glassBlur}px)`,
          WebkitBackdropFilter: `blur(${glassBlur}px)`,
          borderLeft: `2px solid ${glowColor}`,
          border: `1px solid ${glowColor}20`,
          boxShadow: `
            inset 0 1px 1px rgba(255,255,255,0.04),
            inset 0 -1px 1px rgba(0,0,0,0.5),
            0 0 0 1px rgba(0,0,0,0.6),
            0 4px 20px rgba(0,0,0,0.4)
          `,
        }}
      >
        {/* Edge fresnel */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: `
              linear-gradient(90deg, ${shimmerPrimary}06 0%, transparent 20%, transparent 80%, ${shimmerPrimary}06 100%),
              linear-gradient(0deg, ${shimmerPrimary}04 0%, transparent 20%, transparent 80%, ${shimmerPrimary}04 100%)
            `,
            borderRadius: "10px",
          }}
        />

        <div className="relative p-3">
          {/* Document header — format badge + expand button */}
          <div className="flex items-center gap-2 mb-2.5">
            <span
              className="text-[9px] font-semibold tracking-wide uppercase px-1.5 py-0.5 rounded"
              style={{
                color: glowColor,
                backgroundColor: `${glowColor}12`,
                border: `1px solid ${glowColor}30`,
              }}
            >
              {format}
            </span>
            {onExpand && (
              <button
                onClick={onExpand}
                className="ml-auto p-1 rounded transition-all duration-150 hover:brightness-125"
                style={{
                  color: "rgba(255,255,255,0.4)",
                  backgroundColor: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.08)",
                }}
                title="Expand to panel"
              >
                <Expand size={11} />
              </button>
            )}
          </div>

          {/* Document content — scrollable, max-height 400px inline */}
          <div
            className="overflow-y-auto"
            style={{ maxHeight: 400 }}
          >
            {format === "html" ? (
              <div
                dangerouslySetInnerHTML={{ __html: sanitizedHtml }}
                style={{ color: "rgba(255,255,255,0.7)", fontSize: "11px" }}
              />
            ) : format === "text" ? (
              <p
                className="text-[11px] leading-relaxed whitespace-pre-wrap"
                style={{ color: "rgba(255,255,255,0.7)" }}
              >
                {truncatedContent}
              </p>
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {truncatedContent}
              </ReactMarkdown>
            )}
          </div>

          {/* Format alternatives — pills at bottom */}
          {alternatives.length > 0 && onFormatChange && (
            <div
              className="flex items-center gap-1.5 pt-2 mt-2 border-t"
              style={{ borderColor: "rgba(255,255,255,0.06)" }}
            >
              <span
                className="text-[8px] font-semibold tracking-wide uppercase"
                style={{ color: "rgba(255,255,255,0.25)" }}
              >
                Also as:
              </span>
              {alternatives.map((alt) => (
                <button
                  key={alt}
                  onClick={() => onFormatChange(alt)}
                  className="px-2 py-0.5 rounded text-[9px] font-medium tracking-wide transition-all duration-150 hover:brightness-125"
                  style={{
                    color: glowColor,
                    backgroundColor: `${glowColor}12`,
                    border: `1px solid ${glowColor}30`,
                  }}
                >
                  {alt}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </motion.div>
  )
}

/**
 * Returns custom-styled markdown element overrides matching the Prism Glass
 * aesthetic. Adapted for react-markdown v10+ (inline code detected via
 * node.parent.tagName instead of the removed `inline` prop).
 */
function getMarkdownComponents(
  glowColor: string,
  shimmerPrimary: string,
  hasMermaid: boolean,
  trust?: string
): Components {
  return {
    // ── Tables: glass card with brand-color header ─────────────────────
    table: ({ children }) => (
      <div
        className="my-2 rounded-lg overflow-auto"
        style={{
          background: "rgba(255,255,255,0.03)",
          border: `1px solid ${glowColor}20`,
          borderLeft: `2px solid ${glowColor}`,
        }}
      >
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: "11px",
            fontFamily: "'Courier New', Courier, monospace",
          }}
        >
          {children}
        </table>
      </div>
    ),
    thead: ({ children }) => (
      <thead
        style={{
          background: `${glowColor}15`,
          borderBottom: `1px solid ${glowColor}30`,
        }}
      >
        {children}
      </thead>
    ),
    th: ({ children }) => (
      <th
        style={{
          padding: "6px 10px",
          textAlign: "left",
          color: glowColor,
          fontWeight: 700,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          fontSize: "10px",
          textShadow: `0 0 8px ${glowColor}44`,
        }}
      >
        {children}
      </th>
    ),
    td: ({ children }) => (
      <td
        style={{
          padding: "6px 10px",
          color: "rgba(255,255,255,0.65)",
          borderBottom: "1px solid rgba(255,255,255,0.04)",
        }}
      >
        {children}
      </td>
    ),

    // ── Code: block (inside pre) vs inline ─────────────────────────---
    // In react-markdown v10+, `inline` prop was removed. Detect block code
    // by checking if the parent node is a <pre> tag.
    code: ({ node, className, children, ...props }) => {
      // react-markdown v10 `Element` type doesn't include `parent` —
      // cast to access the actual DOM/hast node parent for block detection.
      const nodeAny = node as unknown as Record<string, unknown> | undefined
      const parentTagName = (nodeAny?.parent as Record<string, unknown> | undefined)?.tagName
      const isBlock = parentTagName === "pre" || /language-/.test(className || "")
      if (!isBlock) {
        // Inline code — styled chip
        return (
          <code
            style={{
              padding: "1px 4px",
              borderRadius: "4px",
              fontSize: "10px",
              fontFamily: "'Courier New', Courier, monospace",
              color: glowColor,
              backgroundColor: `${glowColor}12`,
              border: `1px solid ${glowColor}20`,
            }}
            {...props}
          >
            {children}
          </code>
        )
      }
      // Block code — pass through to pre renderer
      return (
        <code className={className} {...props}>
          {children}
        </code>
      )
    },
    pre: ({ children }) => {
      // Detect mermaid block for lazy rendering.
      const childArray = React.Children.toArray(children)
      const firstChild = childArray[0]
      const isMermaid =
        React.isValidElement<{ className?: string; children?: React.ReactNode }>(firstChild) &&
        typeof firstChild.props.className === "string" &&
        firstChild.props.className.includes("language-mermaid") &&
        hasMermaid
      if (isMermaid) {
        return (
          <Suspense
            fallback={
              <div className="text-[10px] text-white/30 p-2 my-2">Loading diagram...</div>
            }
          >
            <MermaidDiagram chart={String(firstChild.props.children)} glowColor={glowColor} trust={trust} />
          </Suspense>
        )
      }
      return (
        <div
          className="my-2 rounded-lg overflow-hidden relative"
          style={{
            background: "rgba(0,0,0,0.4)",
            border: `1px solid ${glowColor}20`,
            borderLeft: `2px solid ${glowColor}`,
          }}
        >
          <pre
            style={{
              padding: "10px 12px",
              overflow: "auto",
              fontSize: "10px",
              fontFamily: "'Courier New', Courier, monospace",
              color: "rgba(255,255,255,0.7)",
              lineHeight: 1.5,
            }}
          >
            {children}
          </pre>
        </div>
      )
    },

    // ── Headings: monospace with brand-color glow ──────────────────────
    h1: ({ children }) => (
      <h1
        style={{
          fontSize: "14px",
          fontWeight: 700,
          fontFamily: "'Courier New', Courier, monospace",
          letterSpacing: "0.08em",
          color: glowColor,
          textShadow: `0 0 16px ${glowColor}55, 0 0 4px ${glowColor}88`,
          marginTop: "12px",
          marginBottom: "8px",
          paddingBottom: "4px",
          borderBottom: `1px solid ${glowColor}20`,
        }}
      >
        {children}
      </h1>
    ),
    h2: ({ children }) => (
      <h2
        style={{
          fontSize: "12px",
          fontWeight: 700,
          fontFamily: "'Courier New', Courier, monospace",
          letterSpacing: "0.08em",
          color: glowColor,
          textShadow: `0 0 12px ${glowColor}44`,
          marginTop: "10px",
          marginBottom: "6px",
        }}
      >
        {children}
      </h2>
    ),
    h3: ({ children }) => (
      <h3
        style={{
          fontSize: "11px",
          fontWeight: 700,
          fontFamily: "'Courier New', Courier, monospace",
          letterSpacing: "0.06em",
          color: shimmerPrimary,
          marginTop: "8px",
          marginBottom: "4px",
        }}
      >
        {children}
      </h3>
    ),

    // ── Lists: brand-color markers ────────────────────────────────────
    ul: ({ children }) => (
      <ul
        style={{
          listStyle: "none",
          padding: "4px 0 4px 16px",
          margin: "4px 0",
        }}
      >
        {children}
      </ul>
    ),
    ol: ({ children }) => (
      <ol
        style={{
          listStyle: "none",
          padding: "4px 0 4px 20px",
          margin: "4px 0",
        }}
      >
        {children}
      </ol>
    ),
    li: ({ node, children }) => {
      const nodeAny = node as unknown as Record<string, unknown> | undefined
      const parentTagName = (nodeAny?.parent as Record<string, unknown> | undefined)?.tagName
      const isOrdered = parentTagName === "ol"
      return (
        <li
          style={{
            position: "relative",
            paddingLeft: "12px",
            marginBottom: "3px",
            fontSize: "11px",
            color: "rgba(255,255,255,0.65)",
            lineHeight: 1.6,
            listStyle: "none",
          }}
        >
          <span
            style={{
              position: "absolute",
              left: isOrdered ? "-16px" : "-10px",
              color: glowColor,
              fontFamily: "'Courier New', Courier, monospace",
              fontSize: "10px",
              fontWeight: 700,
            }}
          >
            {isOrdered ? "›" : "•"}
          </span>
          {children}
        </li>
      )
    },

    // ── Blockquote: glass card with left accent strip ──────────────────
    blockquote: ({ children }) => (
      <blockquote
        style={{
          margin: "8px 0",
          padding: "8px 12px",
          borderRadius: "8px",
          background: "rgba(255,255,255,0.03)",
          borderLeft: `2px solid ${glowColor}`,
          color: "rgba(255,255,255,0.5)",
          fontStyle: "italic",
          fontSize: "11px",
        }}
      >
        {children}
      </blockquote>
    ),

    // ── Links: brand-color underline ───────────────────────────────────
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          color: glowColor,
          textDecoration: "underline",
          textDecorationColor: `${glowColor}66`,
          fontSize: "inherit",
        }}
      >
        {children}
      </a>
    ),

    // ── Horizontal rule: brand-color gradient line ─────────────────────
    hr: () => (
      <hr
        style={{
          border: "none",
          height: "1px",
          background: `linear-gradient(90deg, transparent, ${glowColor}66, transparent)`,
          margin: "12px 0",
        }}
      />
    ),

    // ── Paragraphs ────────────────────────────────────────────────────
    p: ({ children }) => (
      <p
        style={{
          fontSize: "11px",
          lineHeight: 1.6,
          color: "rgba(255,255,255,0.65)",
          margin: "6px 0",
        }}
      >
        {children}
      </p>
    ),

    // ── Strong / Em ───────────────────────────────────────────────────
    strong: ({ children }) => (
      <strong style={{ color: "rgba(255,255,255,0.85)", fontWeight: 700 }}>
        {children}
      </strong>
    ),
    em: ({ children }) => (
      <em style={{ color: shimmerPrimary, fontStyle: "italic" }}>
        {children}
      </em>
    ),

    // ── Images: glass-framed ──────────────────────────────────────────
    img: ({ src, alt }) => (
      <div
        className="my-2 rounded-lg overflow-hidden"
        style={{
          border: `1px solid ${glowColor}20`,
          padding: "4px",
          background: "rgba(255,255,255,0.02)",
        }}
      >
        <img
          src={src}
          alt={alt}
          style={{
            borderRadius: "6px",
            maxWidth: "100%",
            display: "block",
          }}
        />
      </div>
    ),
  }
}
