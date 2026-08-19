/**
 * Characterization (baseline) test — frontend half of T0e, Wave 0 of
 * specs/unified-vision-routing (pins T10, CT-4).
 *
 * Pins the MODEL STATUS badge path end to end through the REAL section data
 * (data/cards.ts + data/navigation-constants.ts are NOT mocked here — the
 * badge field is declared under card id 'local-model-card' / section id
 * 'local_model', data/cards.ts:199-241, and resolved by dark-glass-dashboard
 * FieldRow via `fieldValues[sectionId]`, dark-glass-dashboard.tsx:204,263).
 *
 * Two behaviors pinned:
 *   1. T10b LANDED (REQ-7 AC1/AC2): on mount, the dashboard now sends
 *      `get_local_model_status` (reusing the existing WS handler at
 *      iris_gateway.py:685 / :8841, which had no frontend caller before
 *      this) so the badge is seeded from the backend's LIVE model-manager
 *      state instead of silently defaulting to UNLOADED. The response comes
 *      back as a `local_model_status` message; useIRISWebSocket.ts computes
 *      a status string from it and dispatches a dedicated
 *      `iris:local_model_status` event (see that file's "local_model_status"
 *      case) that dark-glass-dashboard merges into its local field-value
 *      store on every occurrence — not just the first, unlike the
 *      `contextFieldValues` seededRef merge. Because `get_local_model_status`
 *      reflects the manager's LIVE state (not the persisted config), a
 *      reload where nothing is actually listening reconciles to UNLOADED
 *      even if config still claims "loaded" (the Edge Case below).
 *   2. ALREADY FIXED (e9d2fc89): once a value lands in the field's section
 *      bucket (the shape hooks/useIRISWebSocket.ts's `local_model_status`
 *      case writes: field_values.local_model.local_model_status), the badge
 *      re-renders to reflect it. T10b must not regress this half.
 *
 * NavigationContext is mocked (as dark-glass-dashboard.apply.test.tsx does)
 * because it wraps the real WebSocket hook, which cannot run in this test
 * environment. To exercise case 2 without a live socket, the test dispatches
 * `iris:initial_state` — the same CustomEvent dark-glass-dashboard listens
 * for to merge backend-pushed field_values into its local store
 * (dark-glass-dashboard.tsx:861-877). This is the identical code path a real
 * `local_model_status` WS push ends up driving once NavigationContext's
 * `fieldValues` changes; only the transport (mocked context vs. real socket)
 * differs from production.
 */

import "@testing-library/jest-dom";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { DarkGlassDashboard } from "@/components/dark-glass-dashboard";

/* ------------------------------------------------------------------ */
/*  Mocks — mirrors __tests__/components/dark-glass-dashboard.apply.test.tsx */
/* ------------------------------------------------------------------ */

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

jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({ glow: "#00d4ff", font: "#ffffff" }),
  }),
}));

const mockSendMessage = jest.fn();
jest.mock("@/contexts/NavigationContext", () => ({
  useNavigation: () => ({
    // 'agent' so dark-glass-dashboard's mount effect sets activeTab='agent',
    // which is the category that contains the 'local_model' section
    // (data/navigation-constants.ts categoryMapping in dark-glass-dashboard.tsx:175).
    currentCategory: "agent",
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

// Child components unrelated to the badge. ModelInferenceSection is stubbed
// because its section ('model_inference') is expanded by default alongside
// 'local_model' and pulls in providers/role-binding UI out of scope here.
//
// All of these (and CustomDropdown / IrisApertureIcon below) are NAMED
// exports in dark-glass-dashboard.tsx's imports — unlike
// dark-glass-dashboard.apply.test.tsx, this file leaves @/data/cards and
// @/data/navigation-constants UNMOCKED, so the real 'agent' category
// actually reaches these components instead of them going dark behind an
// empty section list. A `() => () => null` factory (the apply test's shape)
// makes the whole mocked module a bare function; a named import off that
// module resolves to `undefined` and React throws "element type is invalid"
// the instant the real section tree tries to render one. Each mock below
// must return an object carrying the same named export.
jest.mock("@/components/ModelInferenceSection", () => ({
  ModelInferenceSection: () => null,
}));
jest.mock("@/components/wing/DashboardRenderer", () => ({
  DashboardRenderer: () => null,
}));
jest.mock("@/components/ui/CustomDropdown", () => ({
  CustomDropdown: () => null,
}));
jest.mock("@/components/ui/IrisApertureIcon", () => ({
  IrisApertureIcon: () => null,
}));
jest.mock("@/components/dashboard/ActivityPanel", () => ({
  ActivityPanel: () => null,
}));
jest.mock("@/components/dashboard/LogsPanel", () => ({
  LogsPanel: () => null,
}));
jest.mock("@/components/dashboard/InferenceConsolePanel", () => ({
  InferenceConsolePanel: () => null,
}));
jest.mock("@/components/dashboard/ModelBrowserPanel", () => ({
  ModelBrowserPanel: () => null,
}));
jest.mock("@/components/dashboard/MonitorTabContainer", () => ({
  MonitorTabContainer: () => null,
}));
jest.mock("@/components/dev/DCPStatsPanel", () => ({
  DCPStatsPanel: () => null,
}));
jest.mock("@/components/iris/browser/BrowserNavigationOverlay", () => ({
  BrowserNavigationOverlay: () => null,
}));
jest.mock("@/components/wheel-view/LearnedSkillsPanel", () => ({
  LearnedSkillsPanel: () => null,
}));
jest.mock("@/components/integrations/MarketplaceScreen", () => ({
  MarketplaceScreen: () => null,
}));

// NOTE: @/data/cards and @/data/navigation-constants are DELIBERATELY left
// unmocked — the badge's field id, defaultValue, and section resolution all
// come from the real data, which is exactly what this test pins.

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

// The 'local_model' section starts collapsed (dark-glass-dashboard.tsx:488
// only defaults 'model_inference' etc. into expandedSections, not
// 'local_model'), so the badge is not in the DOM until its header is opened.
function expandLocalModelSection() {
  fireEvent.click(screen.getByText("LOCAL MODEL"));
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("MODEL STATUS badge — T10b landed (REQ-7 AC1/AC2), was baseline T0e", () => {
  beforeEach(() => {
    mockSendMessage.mockClear();
    localStorage.clear();
  });

  it("T10b AC1: sends get_local_model_status on mount to seed the badge (INVERTED: previously nothing seeded it)", async () => {
    render(<DarkGlassDashboard />);
    await act(async () => {}); // flush mount effects

    // This is the actual fix: previously NO request seeded the badge at all.
    // Reuses the existing WS handler (iris_gateway.py:685) rather than a new
    // channel.
    expect(mockSendMessage).toHaveBeenCalledWith('get_local_model_status', {});
  });

  it("T10b AC1: before the seed reply arrives, renders the default UNLOADED without blocking first paint", async () => {
    render(<DarkGlassDashboard />);
    await act(async () => {}); // flush mount effects

    expandLocalModelSection();

    expect(screen.getByText("MODEL STATUS")).toBeInTheDocument();
    // The seed request is async (real WS round-trip in production); until the
    // reply lands the field falls back to its static defaultValue
    // ('unloaded', data/cards.ts:240). Never undefined, never a crash.
    expect(screen.getByText("UNLOADED")).toBeInTheDocument();
  });

  it("T10b AC2 (INVERTED from baseline): reload with a model loaded reads LOADED once the seeded status arrives", async () => {
    render(<DarkGlassDashboard />);
    await act(async () => {});

    expandLocalModelSection();
    expect(screen.getByText("UNLOADED")).toBeInTheDocument();

    // Simulates the `get_local_model_status` reply for a model that IS
    // resident (mgr.is_loaded() === true): useIRISWebSocket.ts's
    // "local_model_status" case computes status="loaded" and dispatches this
    // event (see hooks/useIRISWebSocket.ts's "local_model_status" case).
    await act(async () => {
      window.dispatchEvent(
        new CustomEvent("iris:local_model_status", { detail: { status: "loaded" } }),
      );
    });

    expect(screen.getByText("LOADED")).toBeInTheDocument();
    expect(screen.queryByText("UNLOADED")).not.toBeInTheDocument();
  });

  it("T10b AC3 (frontend contract only — see task report): a status of 'error' renders ERROR, not UNLOADED", async () => {
    // NOTE: this proves the frontend rendering/merge path is correct for the
    // 'error' value. It does NOT prove end-to-end reload survival: today
    // `get_local_model_status`'s response is `mgr.get_status()` verbatim,
    // which carries only `loaded: boolean` and NEVER a `status`/`error` key
    // (pinned by backend/tests/contract/test_local_model_status_baseline.py
    // ::test_get_local_model_status_response_has_no_status_key), so this
    // exact event never fires with status:"error" from THIS seam today. AC3
    // end-to-end requires the backend to surface the persisted
    // cfg.inference.local_model_status="error" (T10a) through a channel the
    // frontend actually calls on mount — out of scope for a frontend-only
    // change. See the task report for the recommended seam.
    render(<DarkGlassDashboard />);
    await act(async () => {});

    expandLocalModelSection();
    expect(screen.getByText("UNLOADED")).toBeInTheDocument();

    await act(async () => {
      window.dispatchEvent(
        new CustomEvent("iris:local_model_status", { detail: { status: "error" } }),
      );
    });

    expect(screen.getByText("ERROR")).toBeInTheDocument();
    expect(screen.queryByText("UNLOADED")).not.toBeInTheDocument();
  });

  it("Edge case: config says loaded but nothing is listening -> reconciles to UNLOADED", async () => {
    render(<DarkGlassDashboard />);
    await act(async () => {});

    expandLocalModelSection();

    // First simulate a stale "loaded" badge (e.g. left over from a prior
    // session in this same tab)...
    await act(async () => {
      window.dispatchEvent(
        new CustomEvent("iris:local_model_status", { detail: { status: "loaded" } }),
      );
    });
    expect(screen.getByText("LOADED")).toBeInTheDocument();

    // ...then the seed reply for THIS reload reports the manager's LIVE
    // state (mgr.is_loaded() === false, nothing listening) even though
    // config may still say "loaded" — get_local_model_status reflects live
    // truth, not the persisted config, so it self-reconciles.
    await act(async () => {
      window.dispatchEvent(
        new CustomEvent("iris:local_model_status", { detail: { status: "unloaded" } }),
      );
    });

    expect(screen.getByText("UNLOADED")).toBeInTheDocument();
    expect(screen.queryByText("LOADED")).not.toBeInTheDocument();
  });

  it("ALREADY FIXED (e9d2fc89): updates when a local_model_status WS push writes the local-model-card section", async () => {
    render(<DarkGlassDashboard />);
    await act(async () => {}); // flush mount effects

    expandLocalModelSection();
    expect(screen.getByText("UNLOADED")).toBeInTheDocument();

    // Simulate the field_values shape hooks/useIRISWebSocket.ts's
    // "local_model_status" case writes on a live push (lines 1284-1291):
    // both the section-id bucket FieldRow actually reads ('local_model') and
    // the legacy hyphenated key ('local-model-card') other panels read.
    await act(async () => {
      window.dispatchEvent(
        new CustomEvent("iris:initial_state", {
          detail: {
            state: {
              field_values: {
                local_model: { local_model_status: "loaded" },
                "local-model-card": { local_model_status: "loaded" },
              },
            },
          },
        }),
      );
    });

    expect(screen.getByText("LOADED")).toBeInTheDocument();
    expect(screen.queryByText("UNLOADED")).not.toBeInTheDocument();
  });
});
