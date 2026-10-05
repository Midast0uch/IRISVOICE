/**
 * R5 (reply-surface audit 2026-09-29): an HTML artifact never enters the app's
 * own DOM. Agent-made ("trusted") HTML was injected raw via innerHTML, so an
 * inline handler such as onerror ran with the app's origin. Every HTML body
 * renders in a sandboxed iframe WITHOUT allow-same-origin; web HTML also loses
 * its scripts and its frame allows nothing.
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
  const passthrough = React.forwardRef((props, ref) => React.createElement("div", { ...props, ref }))
  return {
    __esModule: true,
    motion: new Proxy({}, { get: () => passthrough }),
    AnimatePresence: ({ children }: { children: React.ReactNode }) =>
      React.createElement(React.Fragment, null, children),
  }
})
jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }) => <div>{children}</div> }))
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => null }))
jest.mock("lucide-react", () => {
  const React = require("react")
  const Icon = React.forwardRef((props, ref) => React.createElement("span", { ...props, ref }))
  return new Proxy({ __esModule: true }, { get: () => Icon })
})

const PAGE = "<p id='agent-page'>hi</p><img src=x onerror=\"window.__pwned=1\">"

function show(trust: string) {
  const out = render(<RichDocument content={PAGE} format="html" trust={trust} />)
  fireEvent.click(screen.getByLabelText("Expand card"))
  return out.container
}

describe("R5 HTML artifacts render in a sandboxed frame", () => {
  it("agent HTML never enters the app DOM; its frame has no same-origin access", () => {
    const c = show("trusted")
    expect(c.querySelector("#agent-page")).toBeNull()
    expect(c.querySelector("img")).toBeNull()
    const frame = c.querySelector("iframe")!
    expect(frame).not.toBeNull()
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts")
    expect(frame.getAttribute("srcdoc")).toContain("agent-page")
    expect(frame.getAttribute("srcdoc")).toContain("Content-Security-Policy")
  })

  it("web HTML is sanitized and its frame allows nothing", () => {
    const c = show("untrusted")
    const frame = c.querySelector("iframe")!
    expect(frame.getAttribute("sandbox")).toBe("")
    expect(frame.getAttribute("srcdoc")).not.toContain("onerror")
    expect(frame.getAttribute("srcdoc")).not.toContain("<script>")
  })
})
