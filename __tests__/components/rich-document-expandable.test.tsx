/**
 * Audit 2026-09-22 (F11) — rehydrated bodyless cards can peek.
 *
 * REQ-6 AC5 says a truly bodyless artifact gets no chrome. But a REHYDRATED
 * card (metadata-only hydration, REQ-17) DOES have a body server-side — it
 * just is not in memory. Before the fix such cards were header-only with
 * only the small Expand icon: the ONLY way to see the body was the full
 * panel. Now the chevron shows for `expandable` cards and unfolding fires
 * onPeek, which triggers the same lazy body fetch the panel uses.
 */

import "@testing-library/jest-dom"
import { render, screen, fireEvent } from "@testing-library/react"
import { RichDocument } from "@/components/chat/RichDocument"

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

describe("Rehydrated bodyless card — peek triggers the body fetch (F11)", () => {
  it("shows the chevron and fires onPeek when unfolded", () => {
    const onPeek = jest.fn()
    render(
      <RichDocument content="" format="markdown" expandable onPeek={onPeek} />
    )
    const chevron = screen.getByLabelText("Expand card")
    expect(chevron).toBeInTheDocument()
    fireEvent.click(chevron)
    expect(onPeek).toHaveBeenCalledTimes(1)
    expect(
      screen.getByText(/Stored body not in memory yet/)
    ).toBeInTheDocument()
  })

  it("stays chromeless for a truly bodyless artifact (REQ-6 AC5)", () => {
    render(<RichDocument content="" format="markdown" />)
    expect(screen.queryByLabelText("Expand card")).not.toBeInTheDocument()
  })

  it("does not fire onPeek when the body is already in memory", () => {
    const onPeek = jest.fn()
    render(
      <RichDocument
        content="# Here"
        format="markdown"
        expandable={false}
        onPeek={onPeek}
      />
    )
    fireEvent.click(screen.getByLabelText("Expand card"))
    expect(onPeek).not.toHaveBeenCalled()
  })
})
