"use client"

import React, { useMemo, useState, useRef, useEffect, lazy, Suspense } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { Components } from "react-markdown"
import { motion } from "framer-motion"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { Expand, ChevronDown } from "lucide-react"
import DOMPurify from "dompurify"

// Lazy-load mermaid only when a ```mermaid block is present
const MermaidDiagram = lazy(() => import("./MermaidDiagram"))

interface RichDocumentProps {
  content: string
  // "json" is what the crawler/tool-result cards actually carry. It was absent
  // from this union, so those cards fell through to the markdown renderer and
  // the type never flagged it.
  // "image" carries a URL (/api/documents/<id>/image), never the bytes: the
  // render path truncates content at 12k and the card again at 50k, so an
  // inlined data: URI would be silently CUT into a broken image.
  format: "markdown" | "html" | "table" | "diagram" | "text" | "json" | "image"
  glowColor?: string
  alternatives?: string[]
  onFormatChange?: (newFormat: string) => void
  onExpand?: () => void
  // Trust-routing W3: "trusted" renders raw HTML; anything else is sanitized
  // with DOMPurify before being injected (untrusted = web/crawler-sourced).
  trust?: string
  // Document-rehydration provenance (REQ-5): source URLs + HAR path so a
  // re-hydrated research doc shows its citations, never as bare [n].
  /** Provenance list. `status` is optional so a re-hydrated research doc (which
   * only knows its final citations) renders exactly as before, while a LIVE plan
   * card can show each source's current outcome as the run progresses. */
  sources?: {
    url: string
    title: string
    status?: "planned" | "reading" | "read" | "blocked" | "parked"
    discovered?: boolean
    reason?: string
  }[]
  harPath?: string | null
}

/** Inline height cap for a document body before it offers to expand. */
const COLLAPSED_MAX_HEIGHT = 460

/** Per-source outcome marker for the live plan card.
 *
 * A planned-but-not-yet-read source must LOOK unread: showing every source
 * identically is what let a run that actually read one page of five present as
 * though it had read all five. `blocked`/`parked` are stated outright rather
 * than omitted — a source the agent could not use is information the user needs,
 * not noise to hide (REQ-15: an answer not built on retrieved content says so). */
const _SOURCE_MARK: Record<string, { glyph: string; label: string; dim: number }> = {
  planned: { glyph: "○", label: "queued", dim: 0.45 },
  reading: { glyph: "◍", label: "reading", dim: 0.8 },
  read: { glyph: "●", label: "read", dim: 1 },
  blocked: { glyph: "⊘", label: "blocked by the site", dim: 0.5 },
  parked: { glyph: "⏸", label: "parked", dim: 0.5 },
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
  sources,
  harPath,
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

  // Alt text for a screenshot card. Prefers the captured page's URL (the tool
  // records it as the document's source), so a screen-reader user is told WHICH
  // page this is a picture of rather than just "a screenshot".
  const imageAlt = useMemo(() => {
    if (format !== "image") return ""
    const src = sources && sources.length > 0 ? sources[0] : undefined
    const where = src?.title || src?.url
    return where ? `Screenshot of ${where}` : "Screenshot captured by IRIS"
  }, [format, sources])

  // Pretty-print a JSON body. Falls back to the raw string when it does not
  // parse — a malformed payload should still be READABLE, not blank.
  const prettyJson = useMemo(() => {
    if (format !== "json") return ""
    try {
      return JSON.stringify(JSON.parse(truncatedContent), null, 2)
    } catch {
      return truncatedContent
    }
  }, [format, truncatedContent])

  // ── Height cap, and being honest about it ──────────────────────────────────
  // The body was capped at a flat 400px with `overflow-y-auto` and no other
  // signal. A 4px near-transparent scrollbar over a dark glass panel is not a
  // visible affordance, so a long answer simply looked TRUNCATED — text ending
  // mid-sentence with nothing to say there was more. That is the "text getting
  // cut off on rendered markdowns" report: the content was always there, the
  // card just never admitted it.
  //
  // Now: measure whether the body actually overflows, and only then show the
  // fade and the expand control. A short document gets no chrome at all, and
  // the cap can be lifted in place instead of forcing a trip to the panel.
  const bodyRef = useRef<HTMLDivElement>(null)
  const [expanded, setExpanded] = useState(false)
  const [overflows, setOverflows] = useState(false)

  useEffect(() => {
    const el = bodyRef.current
    if (!el) return
    const measure = () => {
      // scrollHeight vs the cap, not vs clientHeight — once expanded the two
      // are equal and the control would flicker away mid-read.
      setOverflows(el.scrollHeight > COLLAPSED_MAX_HEIGHT + 8)
    }
    measure()
    // Markdown lays out asynchronously (fonts, lazy mermaid, images), so a
    // single post-mount read under-measures. Observe instead of polling.
    if (typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [truncatedContent, format])

  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8, scale: 0.98 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className="my-3 w-full"
    >
      {/* `border` after `borderLeft` in the same style object OVERWROTE the
          2px brand edge — the shorthand wins, so the card's signature accent
          rail had silently become a flat 1px hairline on all four sides. The
          longhand now comes last, and the rail is drawn as an inset ring so it
          follows the rounded corner instead of squaring it off. */}
      <div
        className="rounded-xl overflow-hidden relative group/doc transition-shadow duration-200"
        style={{
          background: `linear-gradient(140deg, rgba(12,13,24,${0.66 + glassOpacity * 2}) 0%, rgba(16,17,30,${0.72 + glassOpacity * 2}) 100%)`,
          backdropFilter: `blur(${glassBlur}px)`,
          WebkitBackdropFilter: `blur(${glassBlur}px)`,
          border: `1px solid ${glowColor}22`,
          borderLeft: `2px solid ${glowColor}`,
          boxShadow: `
            inset 0 1px 0 rgba(255,255,255,0.06),
            inset 0 -1px 0 rgba(0,0,0,0.45),
            0 1px 0 rgba(0,0,0,0.55),
            0 6px 24px rgba(0,0,0,0.42)
          `,
        }}
      >
        {/* Top light-catch: a single hairline that reads as the glass edge
            picking up the brand colour, so the card has a defined top rather
            than fading into the message list. */}
        <div
          className="absolute top-0 left-0 right-0 h-px pointer-events-none"
          style={{
            background: `linear-gradient(90deg, ${glowColor}00, ${glowColor}66 18%, ${glowColor}22 60%, ${glowColor}00)`,
          }}
        />
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

        <div className="relative">
          {/* Document header — its own band, separated by a rule. It used to
              float directly above the body with only a margin, so the badge
              read as part of the prose. */}
          <div
            className="flex items-center gap-2 px-3 py-2 border-b"
            style={{ borderColor: "rgba(255,255,255,0.06)" }}
          >
            <span
              className="text-[9px] font-semibold tracking-[0.12em] uppercase px-1.5 py-[3px] rounded leading-none"
              style={{
                color: glowColor,
                backgroundColor: `${glowColor}14`,
                border: `1px solid ${glowColor}33`,
              }}
            >
              {format}
            </span>
            {/* Untrusted content is web-sourced and sanitized. That was only
                ever visible as a behaviour (stripped HTML), never as a fact the
                reader could see. */}
            {trust && trust !== "trusted" && (
              <span
                className="text-[8px] font-medium tracking-[0.1em] uppercase leading-none px-1.5 py-[3px] rounded"
                style={{
                  color: "rgba(255,255,255,0.38)",
                  border: "1px solid rgba(255,255,255,0.1)",
                }}
                title="Sourced from the web — HTML is sanitized before rendering"
              >
                web
              </span>
            )}
            {onExpand && (
              <button
                onClick={onExpand}
                className="ml-auto p-1 rounded transition-all duration-150 hover:brightness-125 opacity-60 group-hover/doc:opacity-100"
                style={{
                  color: "rgba(255,255,255,0.55)",
                  backgroundColor: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.08)",
                }}
                title="Expand to panel"
              >
                <Expand size={11} />
              </button>
            )}
          </div>

          {/* Document body. `overflowWrap: anywhere` is the actual fix for text
              disappearing at the right edge: a long URL or an unbroken token in
              a paragraph overflowed the card, and the card's `overflow-hidden`
              clipped it outright — the characters were painted outside the
              rounded box and simply never seen. Wrapping keeps them inside. */}
          <div
            ref={bodyRef}
            className="rich-doc-body overflow-y-auto overflow-x-hidden px-3 py-2.5 min-w-0"
            style={{
              maxHeight: expanded ? undefined : COLLAPSED_MAX_HEIGHT,
              overflowWrap: "anywhere",
              wordBreak: "break-word",
            }}
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
            ) : format === "image" ? (
              <>
              {/* A screenshot. `content` is the URL of the document's own blob.
                  Click opens it full-size in the panel via the same expand path
                  every other card uses, so an image is not a special case the
                  user has to learn. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={content}
                alt={imageAlt}
                onClick={onExpand}
                className={`w-full h-auto rounded${onExpand ? " cursor-zoom-in" : ""}`}
                style={{ border: `1px solid ${glowColor}22`, display: "block" }}
                // A screenshot that fails to load must SAY so. Left alone the
                // browser draws a broken-image glyph or nothing at all, which
                // reads as "the tool did nothing" — the same
                // silently-blank failure the empty document cards were.
                onError={(e) => {
                  const el = e.currentTarget
                  el.style.display = "none"
                  const note = el.nextElementSibling as HTMLElement | null
                  if (note) note.style.display = "block"
                }}
              />
              <p
                className="text-[10px] italic"
                style={{ color: "rgba(255,255,255,0.4)", display: "none" }}
              >
                The screenshot could not be loaded — its stored image is gone or
                was evicted.
              </p>
              </>
            ) : format === "json" ? (
              // A tool-result card is `format: "json"` and used to fall through
              // to the markdown branch, where a 16KB single-line object renders
              // as one unreadable run-on paragraph with its quotes and braces
              // treated as prose. Pretty-print it as code instead.
              <pre
                className="text-[10px] leading-relaxed whitespace-pre-wrap m-0"
                style={{
                  color: "rgba(255,255,255,0.62)",
                  fontFamily: "'Courier New', Courier, monospace",
                }}
              >
                {prettyJson}
              </pre>
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {truncatedContent}
              </ReactMarkdown>
            )}
          </div>

          {/* Fade + expand — shown ONLY when the body is genuinely taller than
              the cap, so a short document carries no false "there's more" cue.
              The fade is pointer-events-none: it must never eat a click or a
              text selection at the bottom of the body. */}
          {overflows && !expanded && (
            <div
              className="absolute left-0 right-0 pointer-events-none"
              style={{
                bottom: 0,
                height: 56,
                background:
                  "linear-gradient(to bottom, rgba(14,15,27,0) 0%, rgba(14,15,27,0.82) 70%, rgba(14,15,27,0.95) 100%)",
              }}
            />
          )}
          {overflows && (
            <div className="relative flex justify-center pb-2 -mt-1">
              <button
                onClick={() => setExpanded((v) => !v)}
                className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[9px] font-semibold tracking-[0.1em] uppercase transition-all duration-150 hover:brightness-125"
                style={{
                  color: glowColor,
                  backgroundColor: `${glowColor}14`,
                  border: `1px solid ${glowColor}33`,
                }}
              >
                <ChevronDown
                  size={10}
                  style={{
                    transform: expanded ? "rotate(180deg)" : "none",
                    transition: "transform 0.2s",
                  }}
                />
                {expanded ? "Collapse" : "Show more"}
              </button>
            </div>
          )}

          {/* Format alternatives — pills at bottom */}
          {alternatives.length > 0 && onFormatChange && (
            <div
              className="flex items-center gap-1.5 px-3 py-2 border-t"
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

          {/* Provenance — source list (REQ-5): a re-hydrated research doc shows
              its citations, never as bare [n]. Resolvable links + HAR pointer. */}
          {sources && sources.length > 0 && (
            <div
              className="px-3 py-2 border-t"
              style={{ borderColor: "rgba(255,255,255,0.06)" }}
            >
              <span
                className="text-[8px] font-semibold tracking-wide uppercase"
                style={{ color: "rgba(255,255,255,0.25)" }}
              >
                Sources
              </span>
              <ul className="mt-1 space-y-0.5">
                {sources.map((s, i) => {
                  // No status = a re-hydrated research doc listing its final
                  // citations. It renders exactly as before: no marker, full
                  // opacity. Only a LIVE plan card carries per-source outcomes.
                  const mark = s.status ? _SOURCE_MARK[s.status] : undefined
                  return (
                    <li
                      key={s.url}
                      className="text-[9px] leading-tight flex items-baseline gap-1"
                      style={mark ? { opacity: mark.dim } : undefined}
                    >
                      {mark && (
                        <span
                          aria-hidden
                          className="shrink-0"
                          style={{ color: glowColor }}
                        >
                          {mark.glyph}
                        </span>
                      )}
                      <a
                        href={s.url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="hover:brightness-125 transition-all duration-150"
                        style={{ color: glowColor }}
                        title={s.url}
                      >
                        {i + 1}. {s.title || s.url}
                      </a>
                      {/* State the outcome in WORDS, not colour alone — the
                          glyph and the dimming are both inaccessible on their
                          own, and "blocked" is exactly the fact a user must not
                          have to infer. Omitted for `read`, where the default
                          reading is already correct. */}
                      {mark && s.status !== "read" && (
                        <span
                          className="shrink-0 text-[8px] italic"
                          style={{ color: "rgba(255,255,255,0.35)" }}
                        >
                          {s.reason || mark.label}
                        </span>
                      )}
                      {s.discovered && (
                        <span
                          className="shrink-0 text-[8px]"
                          style={{ color: "rgba(255,255,255,0.25)" }}
                          title="found by searching, not from the original plan"
                        >
                          found mid-run
                        </span>
                      )}
                    </li>
                  )
                })}
              </ul>
              {harPath && (
                <p className="text-[8px] mt-1" style={{ color: "rgba(255,255,255,0.2)" }}>
                  HAR: {harPath}
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* The body used the browser's default scrollbar — a ~17px opaque bar on
          Windows, sitting inside a 4px-scrollbar design. It both looked wrong
          and stole width from the prose. Same glass treatment as the dashboard
          wing and the proxied iframes. */}
      <style jsx global>{`
        .rich-doc-body::-webkit-scrollbar {
          width: 4px;
          height: 4px;
        }
        .rich-doc-body::-webkit-scrollbar-track {
          background: rgba(255, 255, 255, 0.05);
          border-radius: 2px;
        }
        .rich-doc-body::-webkit-scrollbar-thumb {
          background: rgba(255, 255, 255, 0.2);
          border-radius: 2px;
        }
        .rich-doc-body::-webkit-scrollbar-thumb:hover {
          background: rgba(255, 255, 255, 0.3);
        }
        .rich-doc-body {
          scrollbar-width: thin;
          scrollbar-color: rgba(255, 255, 255, 0.2) rgba(255, 255, 255, 0.05);
        }
        /* Long tokens inside nested markdown (links, inline code, table cells)
           escape the body's own wrapping rules unless they are told to break —
           this is the other half of the clipped-text fix. */
        .rich-doc-body a,
        .rich-doc-body code,
        .rich-doc-body td,
        .rich-doc-body th,
        .rich-doc-body p,
        .rich-doc-body li {
          overflow-wrap: anywhere;
          word-break: break-word;
        }
      `}</style>
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
