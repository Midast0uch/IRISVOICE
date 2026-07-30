import "@testing-library/jest-dom";
import { render, screen, within } from "@testing-library/react";
import { ModelInferenceSection } from "@/components/ModelInferenceSection";

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

// Mock framer-motion: strip animation, just render the element.
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

// Mock CustomDropdown: render all option labels visibly so the test can
// assert which providers appear in the Brain / Tool selectors.
jest.mock("@/components/ui/CustomDropdown", () => ({
  CustomDropdown: ({
    options,
    placeholder,
  }: {
    options: { label: string; value: string }[];
    placeholder?: string;
  }) => {
    const React = require("react");
    return React.createElement(
      "div",
      { "data-testid": "mock-dropdown" },
      placeholder
        ? React.createElement("span", null, `placeholder:${placeholder}`)
        : null,
      ...(options || []).map(
        (o: { label: string; value: string }) =>
          React.createElement(
            "span",
            {
              key: o.value,
              "data-testid": `dropdown-option-${o.value}`,
            },
            o.label,
          ),
      ),
    );
  },
}));

/* ------------------------------------------------------------------ */
/*  Fixtures                                                           */
/* ------------------------------------------------------------------ */

const chatProvider = {
  id: "p1",
  label: "GPT-4o",
  kind: "openai",
  model: "gpt-4o",
  purpose: "chat",
};

const embeddingProvider = {
  id: "p2",
  label: "BGE-M3",
  kind: "bge",
  model: "bge-m3",
  purpose: "embedding",
};

const rerankProvider = {
  id: "p3",
  label: "Reranker",
  kind: "rerank",
  model: "rerank-model",
  purpose: "rerank",
};

const allProviders = [chatProvider, embeddingProvider, rerankProvider];

const defaultProps = {
  providers: allProviders,
  role_bindings: [
    { role: "reasoning", instance_id: "" },
    { role: "tool_execution", instance_id: "" },
  ],
  loading: false,
  sendRoleBinding: jest.fn(),
  glowColor: "#00c8ff",
  provider_presets: [],
  sendModelSelection: jest.fn(),
  sendInferenceMode: jest.fn(),
  inferenceValues: {},
};

/* ------------------------------------------------------------------ */
/*  Tests — REQ-6 AC3                                                  */
/* ------------------------------------------------------------------ */

describe("ModelInferenceSection — REQ-6 AC3 provider filter", () => {
  it("renders the chat provider label in dropdown options", () => {
    render(<ModelInferenceSection {...defaultProps} />);
    // The chat provider's label (with model suffix) should be visible.
    expect(screen.getByText("GPT-4o · gpt-4o")).toBeInTheDocument();
  });

  it("does NOT render embedding provider in Brain/Tool selectors", () => {
    render(<ModelInferenceSection {...defaultProps} />);
    // "BGE-M3 · bge-m3" must NOT appear anywhere in the document —
    // that would mean the embedding provider leaked into the Brain or
    // Tool selector options.
    expect(screen.queryByText("BGE-M3 · bge-m3")).not.toBeInTheDocument();
  });

  it("does NOT render rerank provider in Brain/Tool selectors", () => {
    render(<ModelInferenceSection {...defaultProps} />);
    expect(
      screen.queryByText("Reranker · rerank-model"),
    ).not.toBeInTheDocument();
  });

  it("only renders the single chat provider option", () => {
    render(<ModelInferenceSection {...defaultProps} />);
    // Scope to the Brain Model row specifically. The mocked CustomDropdown
    // is reused by four unrelated selectors (Thinking Style / Max Response /
    // Reasoning Effort / Tool Mode) that pass raw string arrays rather than
    // {label,value} objects — those legitimately produce
    // dropdown-option-undefined nodes in this mock and are out of scope for
    // "only the chat provider is offered as a Brain option". Querying the
    // whole document conflates them with the Brain selector under test.
    const brainRow = screen.getByText("Brain Model").closest("div");
    expect(brainRow).not.toBeNull();
    const brainOptions = within(brainRow as HTMLElement).getAllByTestId(
      /^dropdown-option-/,
    );
    expect(brainOptions).toHaveLength(1);
  });
});
