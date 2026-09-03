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
   * "cli"      — the raw text, monospaced and preformatted, the way a terminal
   *              prints it. Developer mode. Task cards there already render as
   *              a monospaced matrix, so a proportional, markdown-styled answer
   *              between two CLI blocks was the odd one out.
   *
   * The TTS highlight works in both: it paints a Range over live text nodes and
   * never inserts elements, so it does not care which tree it is over.
   */
  variant?: "markdown" | "cli"
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

  if (variant === "cli") {
    return (
      <div ref={ref} className={`iris-cli ${className}`}>
        <pre
          className="font-mono text-[11px] leading-[1.5] whitespace-pre-wrap break-words"
          style={{ color: "rgba(255,255,255,0.86)" }}
        >
          {text}
        </pre>
      </div>
    )
  }

  return (
    <div ref={ref} className={`iris-md ${className}`}>
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
        {text}
      </ReactMarkdown>
    </div>
  )
}

export default MarkdownMessage
