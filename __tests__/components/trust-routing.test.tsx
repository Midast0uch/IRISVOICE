import "@testing-library/jest-dom"
import { render, waitFor } from "@testing-library/react"
import { RichDocument } from "@/components/chat/RichDocument"
import MermaidDiagram from "@/components/chat/MermaidDiagram"

// ── Mocks ────────────────────────────────────────────────────────────────
// Brand theme context (mirrors ContextPill test).
jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({
      glow: { color: "#00c8ff" },
      shimmer: { primary: "#00c8ff" },
      glass: { blur: 8, opacity: 0.1 },
    }),
  }),
}))

// framer-motion: collapse motion.* to plain divs so we test rendering logic,
// not animation internals.
jest.mock("framer-motion", () => {
  const React = require("react")
  const passthrough = React.forwardRef((props, ref) =>
    React.createElement("div", { ...props, ref })
  )
  return { __esModule: true, motion: new Proxy({}, { get: () => passthrough }) }
})

// Avoid loading ESM-only markdown libs — the HTML branch doesn't use them.
jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children }) => <div>{children}</div>,
}))
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => null }))

// lucide-react: collapse any icon to a span (T4 doesn't assert on icons).
jest.mock("lucide-react", () => {
  const React = require("react")
  const Icon = React.forwardRef((props, ref) =>
    React.createElement("span", { ...props, ref })
  )
  return new Proxy({ __esModule: true }, { get: () => Icon })
})

// mermaid: mock defined entirely inside the factory (jest hoists the factory
// above imports, so it must not reference outer variables). render() returns a
// resolved promise so MermaidDiagram's .then() chain works.
jest.mock("mermaid", () => ({
  __esModule: true,
  default: {
    initialize: jest.fn(),
    render: jest.fn(() => Promise.resolve({ svg: "<svg id='x'></svg>" })),
  },
}))

// Grab the mocked module for assertions (stable for the file's lifetime).
const mockMermaid = require("mermaid").default

// ── T4: RichDocument untrusted HTML sanitization ──────────────────────────
describe("T4 RichDocument untrusted HTML sanitization", () => {
  it("strips <script> from untrusted html via DOMPurify", () => {
    const { container } = render(
      <RichDocument
        content={"<script>alert('xss')</script><p>hello</p>"}
        format="html"
        trust="untrusted"
      />
    )
    const html = container.innerHTML
    expect(html).not.toContain("<script>")
    expect(html).toContain("<p>hello</p>")
  })

  it("renders trusted html raw (script preserved)", () => {
    const { container } = render(
      <RichDocument
        content={"<script>alert('xss')</script><p>hi</p>"}
        format="html"
        trust="trusted"
      />
    )
    const html = container.innerHTML
    expect(html).toContain("<script>")
  })
})

// ── T5: MermaidDiagram securityLevel tracks trust ─────────────────────────
describe("T5 MermaidDiagram securityLevel by trust", () => {
  beforeEach(() => {
    mockMermaid.initialize.mockClear()
    mockMermaid.render.mockClear()
  })

  it("uses securityLevel 'strict' for untrusted diagrams", async () => {
    render(<MermaidDiagram chart="graph TD;A-->B" glowColor="#00c8ff" trust="untrusted" />)
    await waitFor(() => expect(mockMermaid.initialize).toHaveBeenCalled())
    const cfg = mockMermaid.initialize.mock.calls[0][0]
    expect(cfg.securityLevel).toBe("strict")
  })

  it("uses securityLevel 'loose' for trusted diagrams", async () => {
    render(<MermaidDiagram chart="graph TD;A-->B" glowColor="#00c8ff" trust="trusted" />)
    await waitFor(() => expect(mockMermaid.initialize).toHaveBeenCalled())
    const cfg = mockMermaid.initialize.mock.calls[0][0]
    expect(cfg.securityLevel).toBe("loose")
  })
})
