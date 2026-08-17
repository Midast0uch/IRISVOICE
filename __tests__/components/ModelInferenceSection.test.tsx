import "@testing-library/jest-dom";
import { render, screen, within, fireEvent } from "@testing-library/react";
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
// assert which providers appear in the Brain / Tool selectors. Also wires
// onChange so tests can drive provider/model selection.
jest.mock("@/components/ui/CustomDropdown", () => ({
  CustomDropdown: ({
    options,
    placeholder,
    onChange,
  }: {
    options: { label: string; value: string }[];
    placeholder?: string;
    onChange?: (value: string) => void;
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
              onClick: () => onChange?.(o.value),
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
  provider_presets: [
    { id: "p1", label: "GPT-4o", kind: "openai", needs_key: true, api_base_url: "https://api.openai.com/v1" },
  ],
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
    // Scope to the Brain row specifically. The mocked CustomDropdown
    // is reused by four unrelated selectors (Thinking Style / Max Response /
    // Reasoning Effort / Tool Mode) that pass raw string arrays rather than
    // {label,value} objects — those legitimately produce
    // dropdown-option-undefined nodes in this mock and are out of scope for
    // "only the chat provider is offered as a Brain option". Querying the
    // whole document conflates them with the Brain selector under test.
    const brainRow = screen.getByText("Brain").closest("div");
    expect(brainRow).not.toBeNull();
    const brainOptions = within(brainRow as HTMLElement).getAllByTestId(
      /^dropdown-option-/,
    );
    expect(brainOptions).toHaveLength(1);
  });
});

/* ------------------------------------------------------------------ */
/*  Key-leak regression — provider switch must clear the typed key     */
/* ------------------------------------------------------------------ */

describe("ModelInferenceSection — provider switch clears stale API key", () => {
  it("does not send the previous provider's key when applying a new provider", () => {
    const sendModelSelection = jest.fn();
    const props = {
      ...defaultProps,
      sendModelSelection,
      providers: [
        { id: "p1", label: "GPT-4o", kind: "openai", model: "gpt-4o", purpose: "chat" },
        { id: "p2", label: "Cohere", kind: "api", model: "command-a-plus-05-2026", purpose: "chat" },
      ],
      provider_presets: [
        { id: "p1", label: "GPT-4o", kind: "openai", needs_key: true, api_base_url: "https://api.openai.com/v1" },
        { id: "p2", label: "Cohere", kind: "api", needs_key: true, api_base_url: "https://api.cohere.ai/compatibility/v1" },
      ],
    };
    render(<ModelInferenceSection {...props} />);

    // 1. Select provider p1 (GPT-4o) and type a key for it.
    fireEvent.click(screen.getByTestId("dropdown-option-p1"));
    const keyInput = screen.getByPlaceholderText("sk-...");
    fireEvent.change(keyInput, { target: { value: "sk-gpt4o-secret" } });

    // 2. Switch to provider p2 (Cohere) WITHOUT typing a new key.
    fireEvent.click(screen.getByTestId("dropdown-option-p2"));

    // 3. Apply — the payload must NOT carry the p1 key. The key input was
    // cleared by the provider switch, so either Apply is disabled (key
    // required but empty) or it fires without api_key. Both are correct;
    // sending the stale p1 key is the bug.
    const applyBtn = screen.getByText("Apply Provider").closest("button");
    const disabled = applyBtn ? (applyBtn as HTMLButtonElement).disabled : false;
    if (disabled) {
      // Key required + cleared => Apply disabled => nothing sent. Correct.
      expect(sendModelSelection).not.toHaveBeenCalled();
    } else {
      const lastCall = sendModelSelection.mock.calls.at(-1)?.[0];
      expect(lastCall).toBeDefined();
      expect(lastCall.model_provider).toBe("p2");
      expect(lastCall.api_key).toBeUndefined();
    }
  });
});
