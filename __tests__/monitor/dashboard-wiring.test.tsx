/**
 * Wiring: the old Inference console sub-app is now the Inference stream row of
 * the Monitor page. `open_inference_console` (card action, and the
 * `initialSubApp` hand-off from app/page.tsx) must land on the Monitor tab with
 * the stream pane focused (panes are always shown; there is no open/closed). Harness mocks mirror dark-glass-dashboard.apply.test.tsx.
 */

import "@testing-library/jest-dom";
import { render, screen, act } from "@testing-library/react";
import { DarkGlassDashboard } from "@/components/dark-glass-dashboard";

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

// framer-motion: strip animation, just render the element.
jest.mock("framer-motion", () => {
  const React = require("react");
  const motion = new Proxy(
    {},
    {
      get: (_t: unknown, tag: string) =>
        React.forwardRef(
          (props: Record<string, unknown>, ref: unknown) => {
            const { children, ...rest } = props || {};
            return React.createElement(tag, { ...rest, ref }, children);
          },
        ),
    },
  );
  return {
    motion,
    AnimatePresence: ({ children }: { children: React.ReactNode }) =>
      React.createElement(React.Fragment, null, children),
  };
});

// Icon libraries: render a plain span so no SVG internals are exercised.
// Factories are fully self-contained (babel-plugin-jest-hoist forbids any
// out-of-scope reference, including calls to local helpers).
jest.mock("lucide-react", () => {
  const React = require("react");
  return new Proxy(
    {},
    {
      get: (_t: unknown, name: string) => (props: Record<string, unknown>) =>
        React.createElement("span", { "data-icon": String(name), ...props }),
    },
  );
});
jest.mock("@tabler/icons-react", () => {
  const React = require("react");
  return new Proxy(
    {},
    {
      get: (_t: unknown, name: string) => (props: Record<string, unknown>) =>
        React.createElement("span", { "data-icon": String(name), ...props }),
    },
  );
});

// Contexts
jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({ glow: "#00d4ff", font: "#ffffff" }),
  }),
}));

const mockSendMessage = jest.fn();
const mockSelectSectionWs = jest.fn();
const mockCategory = { value: "voice" };
jest.mock("@/contexts/NavigationContext", () => ({
  useNavigation: () => ({
    currentCategory: mockCategory.value,
    fieldValues: {},
    fieldErrors: {},
    voiceState: "idle",
    selectCategory: jest.fn(),
    selectSectionWs: mockSelectSectionWs,
    updateCardValue: jest.fn(),
    updateField: jest.fn(),
    clearFieldError: jest.fn(),
    confirmCard: jest.fn(),
    sendMessage: mockSendMessage,
  }),
}));

// Hooks
jest.mock("@/hooks/useLauncherMode", () => ({
  useLauncherMode: () => ({ mode: "desktop" }),
}));

jest.mock("@/hooks/useInferenceState", () => ({
  useInferenceState: () => ({
    role_bindings: [],
    loading: false,
    infLoading: false,
    sendRoleBinding: jest.fn(),
    provider_presets: [],
    sendModelSelection: jest.fn(),
    sendInferenceMode: jest.fn(),
    model_catalog: {},
  }),
}));

jest.mock("@/hooks/CrawlProvider", () => ({
  useCrawlContext: () => ({
    state: { active: false, query: "", pages: [], total: 0, error: null },
  }),
}));

jest.mock("@/hooks/useBrowserNavOverlay", () => ({
  useBrowserNavOverlay: () => ({ status: "idle" }),
}));

jest.mock("@/hooks/useViewProtocol", () => ({
  useViewProtocol: () => ({}),
}));

jest.mock("@/hooks/useActiveFrameSrc", () => ({
  useActiveFrameSrc: () => "",
  useBrowserSurfaceSession: () => false,
}));

// Child components: not needed for the APPLY contract.
jest.mock("@/components/ModelInferenceSection", () => () => null);
jest.mock("@/components/wing/DashboardRenderer", () => () => null);
jest.mock("@/components/ui/CustomDropdown", () => () => null);
jest.mock("@/components/ui/IrisApertureIcon", () => () => null);
jest.mock("@/components/dashboard/ActivityPanel", () => () => null);
jest.mock("@/components/dashboard/LogsPanel", () => () => null);
jest.mock("@/components/dashboard/ModelBrowserPanel", () => () => null);
jest.mock("@/components/iris/browser/BrowserNavigationOverlay", () => () => null);
jest.mock("@/components/wheel-view/LearnedSkillsPanel", () => () => null);
jest.mock("@/components/integrations/MarketplaceScreen", () => () => null);

// Data modules: empty so no sections render (APPLY iterates localFieldValues,
// not rendered sections).
jest.mock("@/data/cards", () => ({
  CARDS_BY_SECTION: {},
  getCardsForSection: () => [],
  CARDS_DATA: {},
}));
jest.mock("@/data/navigation-constants", () => ({
  SECTION_TO_LABEL: {},
  SECTION_TO_ICON: {},
  CARD_TO_SECTION_ID: {},
}));

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

const streamPane = () =>
  document.querySelector('[data-area="stream"]') as HTMLElement | null;

describe("open_inference_console lands on the Monitor page's stream pane", () => {
  beforeEach(() => {
    mockSendMessage.mockClear();
    mockSelectSectionWs.mockClear();
    localStorage.clear();
    (globalThis as any).fetch = jest.fn(() => Promise.resolve({ ok: false, json: async () => ({}) }));
  });

  it("card action opens the Monitor tab with the stream pane focused", async () => {
    render(<DarkGlassDashboard />);
    expect(streamPane()).toBeNull(); // voice tab: no Monitor page yet

    await act(async () => {
      window.dispatchEvent(new CustomEvent("iris:card_action", { detail: { action: "open_inference_console" } }));
    });

    expect(streamPane()).not.toBeNull();
    expect(document.activeElement).toBe(streamPane());
    expect(mockSelectSectionWs).toHaveBeenCalledWith("monitor");
    // five areas, no Context (desktop mode), no separate console surface
    expect(Array.from(document.querySelectorAll("[data-area]")).map((r) => r.getAttribute("data-area"))).toEqual([
      "now", "stream", "usage", "logs", "diagnostics",
    ]);
    expect(screen.queryByText("Inference Console")).toBeNull();
  });

  it("initialSubApp='inference_console' (hand-off from app/page.tsx) does the same", async () => {
    await act(async () => {
      render(<DarkGlassDashboard initialSubApp="inference_console" />);
    });
    expect(streamPane()).not.toBeNull();
    expect(document.activeElement).toBe(streamPane());
  });
});
