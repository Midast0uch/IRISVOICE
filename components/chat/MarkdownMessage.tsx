"use client"

import { useEffect, useRef } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

/**
 * MarkdownMessage — renders assistant text as MARKDOWN, with the TTS word
 * highlight applied as an OVERLAY rather than as wrapper elements.
 *
 * Why an overlay (2026-08-17). Chat messages used to render as
 * `<p>{message.text}</p>`, which collapses every newline — so the structure the
 * synthesis path is explicitly instructed to produce (headings, bullets,
 * tables) arrived as one unbroken wall of text. The obvious fix, rendering
 * markdown, collides with the old highlight, which wrapped every word in its
 * own `<motion.span>`: you cannot both parse the text into a document tree and
 * slice it into per-word spans.
 *
 * The CSS Custom Highlight API resolves it. `Highlight` paints over a live
 * `Range` without inserting anything into the DOM, so the markdown tree is
 * untouched and the highlight rides on top of it. Styled via
 * `::highlight(iris-tts-word)` in globals.css. Where unsupported, the text
 * simply renders without a highlight — never a broken layout.
 *
 * WHAT GETS HIGHLIGHTED (user rule 2026-08-17): the highlight belongs to the
 * SPOKEN text, not the body. A long answer is displayed in full and is NOT
 * highlighted — TTS gives a short summary briefing instead, and that briefing
 * is what tracks. Pass `highlightIndex >= 0` only for the element that actually
 * corresponds to what is being spoken.
 */

const HIGHLIGHT_NAME = "iris-tts-word"

/**
 * REQ-22 AC2 (2026-09-23 live finding): a model that wraps the WHOLE answer
 * — or a section of it — inside a dedicated markdown fence (```markdown,
 * ```md, or bare ```) means "this is a document", not "show my code". The
 * chat used to render that fence as raw monospace text, with the markdown
 * markers visible and the right edge clipped. Unwrap ONLY the document-class
 * fences anywhere in the body; genuine code fences (```ts, ```py, ...) stay
 * code. Render-time, so history heals on the next paint too.
 */
const _DOC_FENCE_RE = /```\s*(?:markdown|md|text)?\s*\r?\n([\s\S]*?)\r?\n?```/g

function unwrapDocumentFences(text: string): string {
  if (!text || !text.includes("```")) return text
  return text.replace(_DOC_FENCE_RE, (_whole, inner) => {
    const innerText = String(inner).trim()
    // Only unwrap when the fence actually reads like markdown prose;
    // an ast/json/shell body keeps its fence.
    const looksLikeMarkdown =
      /(^|\n)\s*#{1,6}\s|(^|\n)\s*[-*]\s|(^|\n)\s*\d+\.\s|\*\*[^*\n]+\*\*/.test(innerText)
    if (!looksLikeMarkdown) return _whole
    return innerText
  })
}

type CSSWithHighlights = {
  highlights?: {
    set: (name: string, highlight: unknown) => void
    delete: (name: string) => void
  }
}

/**
 * Paint the `activeIndex`-th whitespace-delimited word inside `containerRef`.
 *
 * Walks the rendered text nodes so the index counts words as the READER sees
 * them — markdown syntax has already been consumed by the parser, so word N
 * here is word N of the visible prose, which is what the TTS index means.
 */
function useTtsWordHighlight(
  containerRef: React.RefObject<HTMLElement | null>,
  activeIndex: number,
  enabled: boolean,
) {
  useEffect(() => {
    const cssApi =
      typeof CSS !== "undefined" ? (CSS as unknown as CSSWithHighlights) : null
    const highlights = cssApi?.highlights
    const HighlightCtor =
      typeof window !== "undefined"
        ? (window as unknown as { Highlight?: new (...r: Range[]) => unknown }).Highlight
        : undefined
    if (!highlights || !HighlightCtor) return

    const clear = () => {
      try {
        highlights.delete(HIGHLIGHT_NAME)
      } catch {
        /* nothing to clear */
      }
    }

    const container = containerRef.current
    if (!enabled || activeIndex < 0 || !container) {
      clear()
      return
    }

    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
    let seen = 0
    let range: Range | null = null
    let node: Node | null

    while ((node = walker.nextNode())) {
      const value = node.nodeValue ?? ""
      const wordRe = /\S+/g
      let match: RegExpExecArray | null
      while ((match = wordRe.exec(value))) {
        if (seen === activeIndex) {
          range = document.createRange()
          range.setStart(node, match.index)
          range.setEnd(node, match.index + match[0].length)
          break
        }
        seen++
      }
      if (range) break
    }

    if (range) {
      try {
        highlights.set(HIGHLIGHT_NAME, new HighlightCtor(range))
      } catch {
        clear()
      }
    } else {
      clear()
    }

    return clear
  }, [containerRef, activeIndex, enabled])
}

export interface MarkdownMessageProps {
  text: string
  /** Index of the word currently being spoken, or -1 for none. */
  highlightIndex?: number
  /** Only true for the message whose SPOKEN text this element renders. */
  highlightActive?: boolean
  className?: string
  /**
   * How the body reads.
   *
   * "markdown" — parsed and styled prose. Personal mode.
   * "cli"      — developer mode: the same markdown, set in the mono family at
   *              12.5 px (execution audit Phase 4: "the answer is markdown
   *              rendered in the same mono family"). It used to print the raw
   *              text, so ** and code fences showed as literal characters.
   *
   * "voice"    — personal mode's answer bubble: the same markdown in IRIS's
   *              reading serif (concept 2 `.voice`, Newsreader 16 px). Cards and
   *              documents keep "markdown".
   *
   * The TTS highlight works in all: it paints a Range over live text nodes and
   * never inserts elements, so it does not care which tree it is over.
   */
  variant?: "markdown" | "cli" | "voice"
}

export function MarkdownMessage({
  text,
  highlightIndex = -1,
  highlightActive = false,
  className = "",
  variant = "markdown",
}: MarkdownMessageProps) {
  const ref = useRef<HTMLDivElement>(null)
  useTtsWordHighlight(ref, highlightIndex, highlightActive)

  const displayText = unwrapDocumentFences(text)

  return (
    <div ref={ref} className={`iris-md ${variant === "cli" ? "iris-md-cli" : variant === "voice" ? "iris-md-voice" : ""} ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children, ...props }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
              {children}
            </a>
          ),
          // Tables get their own scroll container: the chat panel is narrow, and
          // squeezing columns until they overlap is what made them unreadable.
          // The wrapper scrolls horizontally instead, keeping column borders
          // intact (styled via .iris-md-table-wrap).
          table: ({ children, ...props }) => (
            <div className="iris-md-table-wrap">
              <table {...props}>{children}</table>
            </div>
          ),
        }}
      >
        {displayText}
      </ReactMarkdown>
    </div>
  )
}

export default MarkdownMessage
