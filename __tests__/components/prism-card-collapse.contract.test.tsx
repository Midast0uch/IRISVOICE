/**
 * CT-6 + BT-11 (specs/reply-surface-contract REQ-6 / REQ-3 AC3, tasks T12,
 * T13, T16, T17) — prism card collapsed-by-default and in-place peek drive.
 *
 * CT-6: a prism card renders collapsed to its header row by default; the
 * chassis chevron unfolds the body IN PLACE (peek); a card with NO body
 * renders header-only with no chevron and no Expand affordance (AC5).
 * T13/AC3/AC4: the Expand icon still fires the onExpand → DocumentPanel path.
 * BT-11: one full card turn — collapsed, peek in place, expand to panel —
 * driven end to end on the real component pair (RichDocument + CardChassis).
 */

import "@testing-library/jest-dom"
import { render, screen, fireEvent } from "@testing-library/react"
import { RichDocument } from "@/components/chat/RichDocument"

// Same mock set as trust-routing.test.tsx — render logic only.
jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({
      glow: { color: "#00c8ff" },
      shimmer: { primary: "#00c8ff" },
      glass: { blur: 8, opacity: 0.1 },
    }),
  }),
}))

jest.mock("framer-motion", () => {
  const React = require("react")
  const passthrough = React.forwardRef((props, ref) =>
    React.createElement("div", { ...props, ref })
  )
  return {
    __esModule: true,
    motion: new Proxy({}, { get: () => passthrough }),
    AnimatePresence: ({ children }: { children: React.ReactNode }) =>
      React.createElement(React.Fragment, null, children),
  }
})

jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}))
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => null }))

jest.mock("lucide-react", () => {
  const React = require("react")
  const Icon = React.forwardRef((props, ref) =>
    React.createElement("span", { ...props, ref })
  )
  return new Proxy({ __esModule: true }, { get: () => Icon })
})

const BODY_MARKER = "UNIQUE-BODY-76342 — the artifact body"

const SHORT_DOC = `# Report\n\n${BODY_MARKER}`
const LONG_DOC = `${BODY_MARKER}\n\n` + "Par. ".repeat(500)

describe("CT-6 — prism card collapsed by default (REQ-6 AC1/AC2/AC7)", () => {
  it("renders collapsed: no body content, chevron present", () => {
    render(<RichDocument content={SHORT_DOC} format="markdown" />)
    expect(screen.queryByText(new RegExp("UNIQUE-BODY-76342"))).not.toBeInTheDocument()
    expect(screen.getByLabelText("Expand card")).toBeInTheDocument()
  })

  it("chevron unfolds the body IN PLACE (peek) and collapses it again", () => {
    render(<RichDocument content={LONG_DOC} format="markdown" />)
    fireEvent.click(screen.getByLabelText("Expand card"))
    expect(screen.getByText(new RegExp("UNIQUE-BODY-76342"))).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText("Collapse card"))
    expect(screen.queryByText(new RegExp("UNIQUE-BODY-76342"))).not.toBeInTheDocument()
  })

  it("a card with NO body renders header-only — no chevron, no Expand (AC5)", () => {
    const onExpand = jest.fn()
    render(<RichDocument content="   " format="markdown" onExpand={onExpand} />)
    expect(screen.queryByLabelText("Expand card")).not.toBeInTheDocument()
    expect(screen.queryByTitle("Expand to panel")).not.toBeInTheDocument()
    expect(onExpand).not.toHaveBeenCalled()
  })
})

describe("T13 — Expand icon keeps the DocumentPanel path (REQ-6 AC3/AC4)", () => {
  it("Expand icon fires onExpand while the inline card stays collapsed", () => {
    const onExpand = jest.fn()
    render(
      <RichDocument content={SHORT_DOC} format="markdown" onExpand={onExpand} />
    )
    fireEvent.click(screen.getByTitle("Expand to panel"))
    expect(onExpand).toHaveBeenCalledTimes(1)
    // The inline card itself stays in its collapsed state (panel returns to it).
    expect(screen.queryByText(new RegExp("UNIQUE-BODY-76342"))).not.toBeInTheDocument()
    expect(screen.getByLabelText("Expand card")).toBeInTheDocument()
  })
})

describe("BT-11 — one full card turn: collapsed -> peek in place -> panel", () => {
  it("drives the complete disclosure sequence", () => {
    const onExpand = jest.fn()
    render(
      <RichDocument content={SHORT_DOC} format="markdown" onExpand={onExpand} />
    )
    // 1. Arrives collapsed — thread is clean.
    expect(screen.queryByText(new RegExp("UNIQUE-BODY-76342"))).not.toBeInTheDocument()
    // 2. Peek in place via the header chevron — body appears in the thread.
    fireEvent.click(screen.getByLabelText("Expand card"))
    expect(screen.getByText(new RegExp("UNIQUE-BODY-76342"))).toBeInTheDocument()
    // 3. Full view via the Expand icon — second disclosure tier unchanged.
    fireEvent.click(screen.getByTitle("Expand to panel"))
    expect(onExpand).toHaveBeenCalledTimes(1)
  })
})

describe("REQ-13 AC5 (T18b) — partial (streaming) cards", () => {
  it("a partial card renders OPEN so the body fills visibly", () => {
    render(<RichDocument content={SHORT_DOC} format="markdown" partial />)
    expect(screen.getByText(new RegExp("UNIQUE-BODY-76342"))).toBeInTheDocument()
  })

  it("a non-partial card with the same body renders collapsed (contrast)", () => {
    render(<RichDocument content={SHORT_DOC} format="markdown" />)
    expect(screen.queryByText(new RegExp("UNIQUE-BODY-76342"))).not.toBeInTheDocument()
  })
})
