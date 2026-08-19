/**
 * Contract test: the Dashboard bottom APPLY must NOT re-send
 * model_inference / model_selection sections.
 *
 * Regression guard for the recurring cerebras<->cohere cross-contamination
 * (2026-08-16): ModelInferenceSection owns its state and live-sends every
 * change (sendModelSelection / sendRoleBinding / sendInferenceMode). The
 * bottom APPLY used to re-send localFieldValues.model_inference — whose
 * model_provider was auto-synced from a role binding that APPLY PROVIDER
 * never updates — reverting the user's provider choice to the previous one.
 *
 * Contract: APPLY sends confirm_card for ordinary sections (voice, ...) but
 * NEVER for model_inference or model_selection.
 */

import "@testing-library/jest-dom";
import { render, screen, fireEvent, act } from "@testing-library/react";
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
jest.mock("@/contexts/NavigationContext", () => ({
  useNavigation: () => ({
    currentCategory: "voice",
    fieldValues: {},
    fieldErrors: {},
    voiceState: "idle",
    selectCategory: jest.fn(),
    selectSectionWs: jest.fn(),
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
jest.mock("@/components/dashboard/InferenceConsolePanel", () => () => null);
jest.mock("@/components/dashboard/ModelBrowserPanel", () => () => null);
jest.mock("@/components/dashboard/MonitorTabContainer", () => () => null);
jest.mock("@/components/dev/DCPStatsPanel", () => () => null);
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

describe("DarkGlassDashboard APPLY — self-managed section exclusion", () => {
  beforeEach(() => {
    mockSendMessage.mockClear();
    localStorage.clear();
  });

  it("sends confirm_card for ordinary sections but NEVER model_inference/model_selection", async () => {
    render(<DarkGlassDashboard />);

    // Seed localFieldValues the way the real WS hook does: iris:initial_state
    // carries backend field_values, which the dashboard merges into its local
    // store. Include a stale model_inference entry (the pre-fix revert vector)
    // plus an ordinary section that APPLY must still persist.
    await act(async () => {
      window.dispatchEvent(
        new CustomEvent("iris:initial_state", {
          detail: {
            state: {
              field_values: {
                model_inference: { model_provider: "cohere" },
                voice: { wake_word: "iris" },
              },
            },
          },
        }),
      );
    });

    const applyButton = screen.getByRole("button", { name: "APPLY" });
    fireEvent.click(applyButton);

    // Ordinary section IS persisted...
    expect(mockSendMessage).toHaveBeenCalledWith(
      "confirm_card",
      expect.objectContaining({ section_id: "voice" }),
    );

    // ...but the self-managed sections are NEVER re-sent (the revert vector).
    const confirmCalls = mockSendMessage.mock.calls.filter(
      (c: unknown[]) => c[0] === "confirm_card",
    );
    const sectionsSent = confirmCalls.map((c: unknown[]) => (c[1] as { section_id?: string }).section_id);
    expect(sectionsSent).not.toContain("model_inference");
    expect(sectionsSent).not.toContain("model_selection");
  });
});