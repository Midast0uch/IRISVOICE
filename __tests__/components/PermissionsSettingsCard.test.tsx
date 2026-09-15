/**
 * PermissionsSettingsCard — REQ-19 AC3/AC5.
 *
 * Session-331 RE-SCOPE: this component now renders ONLY the standing
 * approved-tools list. The permission MODE dropdown and the AUTO-APPROVE
 * toggle moved to ordinary dashboard fields (`permission_mode` /
 * `auto_approve` in data/cards.ts), rendered by dark-glass-dashboard's native
 * row style — so they are no longer part of THIS component. The assertions
 * below test what the component still owns: it renders the approvable tools
 * from /api/config and lets each be toggled. Requirement changed (the card was
 * split for visual consistency); tests re-scoped, not weakened.
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

const SAMPLE_CONFIG = {
  mode: "personal",
  effective_mode: "developer",
  approved_tools: ["write_file"],
  available_tools: ["write_file", "edit_file", "run_command"],
  auto_approve: false,
}

describe("PermissionsSettingsCard — REQ-19", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => SAMPLE_CONFIG,
    }) as unknown as typeof fetch
  })

  afterEach(() => {
    jest.restoreAllMocks()
  })

  it("renders the approvable tools from /api/config", async () => {
    render(<PermissionsSettingsCard configUrl="/api/config" />)

    await waitFor(() => {
      expect(screen.getByText("write_file")).toBeInTheDocument()
    })
    expect(screen.getByText("edit_file")).toBeInTheDocument()
    expect(screen.getByText("run_command")).toBeInTheDocument()
  })

  it("shows an approved tool's toggle as on and an unapproved one as off", async () => {
    render(<PermissionsSettingsCard configUrl="/api/config" />)

    await waitFor(() => {
      expect(screen.getByLabelText("Approve write_file")).toBeInTheDocument()
    })
    // write_file is in approved_tools -> pressed; edit_file is not.
    expect(screen.getByLabelText("Approve write_file")).toHaveAttribute(
      "aria-pressed",
      "true",
    )
    expect(screen.getByLabelText("Approve edit_file")).toHaveAttribute(
      "aria-pressed",
      "false",
    )
  })
})
