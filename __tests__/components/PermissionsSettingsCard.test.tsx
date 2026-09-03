/**
 * PermissionsSettingsCard — REQ-19 AC3/AC5, REQ-16 AC2.
 * Smoke test: renders without crashing, mocks the /api/config fetch, and
 * asserts the EFFECTIVE mode is shown (REQ-16 AC2 — the truthful current mode,
 * not merely the stored one).
 */
import "@testing-library/jest-dom"
import { render, screen, waitFor } from "@testing-library/react"
import { PermissionsSettingsCard } from "@/components/chat/PermissionsSettingsCard"

jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({
      glow: { color: "#00c8ff" },
      shimmer: { primary: "#00c8ff" },
      glass: { blur: 20, opacity: 0.18 },
    }),
  }),
}))

jest.mock("framer-motion", () => {
  const React = require("react")
  const motion = new Proxy(
    {},
    {
      get: (_t: unknown, tag: string) =>
        React.forwardRef((props: Record<string, unknown>, ref: unknown) => {
          const { children, ...rest } = props || {}
          return React.createElement(tag, { ...rest, ref }, children)
        }),
    }
  )
  return {
    motion,
    AnimatePresence: ({ children }: { children: React.ReactNode }) =>
      React.createElement(React.Fragment, null, children),
  }
})

const SAMPLE_CONFIG = {
  mode: "personal",
  effective_mode: "developer",
  approved_tools: ["write_file"],
  available_tools: ["write_file", "edit_file", "run_command"],
}

describe("PermissionsSettingsCard — REQ-19 / REQ-16", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => SAMPLE_CONFIG,
    }) as unknown as typeof fetch
  })

  afterEach(() => {
    jest.restoreAllMocks()
  })

  it("renders without crashing and shows the EFFECTIVE mode (REQ-16 AC2)", async () => {
    render(<PermissionsSettingsCard configUrl="/api/config" />)

    // Effective mode is developer even though stored mode is personal.
    await waitFor(() => {
      expect(screen.getByTestId("effective-mode")).toHaveTextContent("Developer")
    })

    // Approved tools list renders with the approved tool toggled on.
    expect(screen.getByText("write_file")).toBeInTheDocument()
    expect(screen.getByText("edit_file")).toBeInTheDocument()
    expect(screen.getByText("run_command")).toBeInTheDocument()
  })
})
