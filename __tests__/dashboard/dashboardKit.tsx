// Shared stand-ins for the dashboard tests. Import this file FIRST in a test file:
// its jest.mock calls must be registered before the dashboard module is required.
import React from "react"
import { render } from "@testing-library/react"
import { installCanvasStub, setHidden, setReducedMotion } from "../chrome/canvasStub"

jest.mock("framer-motion", () => {
  const R = require("react")
  const motion = new Proxy({}, {
    get: (_t: unknown, tag: string) => R.forwardRef((props: Record<string, unknown>, ref: unknown) => {
      const { children, initial, animate, exit, transition, ...rest } = props || {}
      return R.createElement(tag, { ...rest, ref }, children)
    }),
  })
  return { motion, AnimatePresence: ({ children }: { children: React.ReactNode }) => R.createElement(R.Fragment, null, children) }
})
jest.mock("lucide-react", () => {
  const R = require("react")
  return new Proxy({}, { get: (_t: unknown, name: string) => (props: Record<string, unknown>) => R.createElement("span", { "data-icon": String(name), ...props }) })
})
jest.mock("@tabler/icons-react", () => {
  const R = require("react")
  return new Proxy({}, { get: (_t: unknown, name: string) => (props: Record<string, unknown>) => R.createElement("span", { "data-icon": String(name), ...props }) })
})
jest.mock("@/contexts/BrandColorContext", () => ({ useBrandColor: () => ({ getThemeConfig: () => ({ glow: "#00d4ff", font: "#ffffff" }) }) }))

export const mockSendMessage = jest.fn()
jest.mock("@/contexts/NavigationContext", () => ({
  useNavigation: () => ({
    currentCategory: "voice", fieldValues: {}, fieldErrors: {}, voiceState: "idle",
    selectCategory: jest.fn(), selectSectionWs: jest.fn(), updateCardValue: jest.fn(), updateField: jest.fn(),
    clearFieldError: jest.fn(), confirmCard: jest.fn(), sendMessage: mockSendMessage,
  }),
}))
jest.mock("@/hooks/useLauncherMode", () => ({ useLauncherMode: () => ({ mode: "desktop" }) }))
jest.mock("@/hooks/useInferenceState", () => ({
  useInferenceState: () => ({
    providers: [{ id: "cerebras", label: "Cerebras", kind: "api", model: "gpt-oss", has_key: true }],
    role_bindings: [{ role: "reasoning", instance_id: "cerebras" }], loading: false, sendRoleBinding: jest.fn(),
    provider_presets: [], sendModelSelection: jest.fn(), sendInferenceMode: jest.fn(), model_catalog: {},
  }),
}))
jest.mock("@/hooks/CrawlProvider", () => ({ useCrawlContext: () => ({ state: { active: false, query: "", pages: [], total: 0, error: null } }) }))
jest.mock("@/hooks/useBrowserNavOverlay", () => ({ useBrowserNavOverlay: () => ({ status: "idle" }) }))
jest.mock("@/hooks/useViewProtocol", () => ({ useViewProtocol: () => ({}) }))
jest.mock("@/hooks/useActiveFrameSrc", () => ({ useActiveFrameSrc: () => "", useBrowserSurfaceSession: () => false }))
jest.mock("@/hooks/useDetachedWing", () => ({ detachWing: jest.fn(), reattachWing: jest.fn() }))
jest.mock("@/components/ModelInferenceSection", () => ({ ModelInferenceSection: () => <div data-testid="model-inference-controls" /> }))
jest.mock("@/components/chat/PermissionsSettingsCard", () => ({ PermissionsSettingsCard: () => <div data-testid="permissions-list" /> }))
jest.mock("@/components/wheel-view/LearnedSkillsPanel", () => ({ LearnedSkillsPanel: () => <div data-testid="skills-list" /> }))
jest.mock("@/components/wing/DashboardRenderer", () => ({ DashboardRenderer: () => null }))
jest.mock("@/components/ui/IrisApertureIcon", () => ({ IrisApertureIcon: () => null }))
jest.mock("@/components/dashboard/ActivityPanel", () => ({ ActivityPanel: () => null }))
jest.mock("@/components/dashboard/LogsPanel", () => ({ LogsPanel: () => null }))
jest.mock("@/components/dashboard/ModelBrowserPanel", () => ({ ModelBrowserPanel: () => <div data-testid="models-surface" /> }))
jest.mock("@/components/dashboard/MonitorTabContainer", () => ({ MonitorTabContainer: () => <div data-testid="monitor-page" /> }))
jest.mock("@/components/dev/DCPStatsPanel", () => ({ DCPStatsPanel: () => null }))
jest.mock("@/components/iris/browser/BrowserNavigationOverlay", () => ({ BrowserNavigationOverlay: () => null }))
jest.mock("@/components/integrations/MarketplaceScreen", () => ({ MarketplaceScreen: () => null }))
jest.mock("@/components/integrations/UnifiedMarketplaceModelsSurface", () => ({ UnifiedMarketplaceModelsSurface: () => <div data-testid="marketplace-surface" /> }))
jest.mock("@/components/workspace/DeveloperWorkspace", () => ({ __esModule: true, default: () => <div data-testid="hub-surface" /> }))

// eslint-disable-next-line import/first
import { DarkGlassDashboard } from "@/components/dark-glass-dashboard"

export function prepareDashboard(tab = "voice") {
  mockSendMessage.mockClear()
  localStorage.clear()
  localStorage.setItem("iris_active_tab_v1", tab)
  installCanvasStub({ w: 150, h: 600 })
  setReducedMotion(true)
  setHidden(false)
  ;(global as any).fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}), headers: { get: () => "" } })
}

export const mountDashboard = (props: React.ComponentProps<typeof DarkGlassDashboard> = {}) => render(<DarkGlassDashboard {...props} />)
