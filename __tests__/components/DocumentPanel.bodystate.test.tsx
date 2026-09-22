/**
 * BT-12 (specs/reply-surface-contract REQ-17, tasks T28/T29): panel drive for
 * a rehydrated prism card —
 *   loading while the body fetch is in flight,
 *   body rendered (in place) once `iris:document_body` lands,
 *   unavailable + Retry when the store no longer holds the document,
 *   and the panel's inner document renders EXPANDED by default (the panel is
 *   the full view; collapsed-by-default applies to the thread card only).
 */

import "@testing-library/jest-dom"
import { render, screen, fireEvent } from "@testing-library/react"
import { DocumentPanel } from "@/components/chat/DocumentPanel"

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

jest.mock("lucide-react", () => {
  const React = require("react")
  const Icon = React.forwardRef((props, ref) =>
    React.createElement("span", { ...props, ref })
  )
  return new Proxy({ __esModule: true }, { get: () => Icon })
})

jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}))
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => null }))

const BODY = "STORED-BODY-74521 — the fetched document body"
const PROPS = {
  content: "",
  format: "markdown",
  alternatives: [] as string[],
  onClose: jest.fn(),
  onFormatChange: jest.fn(),
}

describe("BT-12 — panel body states for a rehydrated card", () => {
  it("loading: shows the fetch-in-flight line, never a blank body", () => {
    render(<DocumentPanel {...PROPS} bodyState="loading" />)
    expect(screen.getByText(/Loading the stored document/)).toBeInTheDocument()
  })

  it("unavailable: shows the explicit state and a working Retry", () => {
    const onRetry = jest.fn()
    render(<DocumentPanel {...PROPS} bodyState="unavailable" onRetry={onRetry} />)
    expect(screen.getByText(/stored document is unavailable/)).toBeInTheDocument()
    fireEvent.click(screen.getByText("Retry"))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it("ready: renders the body immediately, OPEN (never a collapsed panel)", () => {
    render(<DocumentPanel {...PROPS} content={BODY} bodyState="ready" />)
    expect(screen.getByText(new RegExp("STORED-BODY-74521"))).toBeInTheDocument()
    // REQ-6 pins collapse for the THREAD card; the panel is the expanded view.
    expect(screen.queryByLabelText("Expand card")).not.toBeInTheDocument()
  })

  it("ready without an explicit bodyState (default) renders the body", () => {
    render(<DocumentPanel {...PROPS} content={BODY} />)
    expect(screen.getByText(new RegExp("STORED-BODY-74521"))).toBeInTheDocument()
  })
})
