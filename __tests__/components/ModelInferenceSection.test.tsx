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

/* ------------------------------------------------------------------ */
/*  Fix 2 — unconfigured provider presets excluded from Brain/Tool     */
/* ------------------------------------------------------------------ */

describe("ModelInferenceSection — unconfigured presets excluded from Brain/Tool", () => {
  it("does NOT show catalog models from unconfigured provider presets", () => {
    // Simulate: user loaded a local GGUF → providers has local:lfm25-q4.
    // provider_presets includes ollama (with hardcoded local model catalog)
    // but ollama is NOT in the providers array — user never configured it.
    const loadedLocal = {
      id: "local:lfm25-q4",
      label: "Local: LFM2.5-Q4_K_M.gguf",
      kind: "LOCAL_OPENAI",
      model: "LFM2.5-Q4_K_M.gguf",
      loaded: true,
      purpose: "chat",
    };
    const props = {
      ...defaultProps,
      providers: [loadedLocal],
      role_bindings: [
        { role: "reasoning", instance_id: "local:lfm25-q4" },
        { role: "tool_execution", instance_id: "local:lfm25-q4" },
      ],
      provider_presets: [
        { id: "cerebras", label: "Cerebras", kind: "api", needs_key: true, api_base_url: "https://api.cerebras.ai/v1" },
        { id: "ollama", label: "Ollama", kind: "ollama", needs_key: false, api_base_url: "http://localhost:11434" },
        { id: "openai", label: "OpenAI", kind: "api", needs_key: true, api_base_url: "https://api.openai.com/v1" },
      ],
      model_catalog: {
        cerebras: [
          { id: "gemma-4-31b", name: "Gemma 4 31B" },
          { id: "llama-3.3-70b", name: "Llama 3.3 70B" },
        ],
        ollama: [
          { id: "deepseek-r1:7b", name: "DeepSeek R1 (7B)" },
          { id: "llama3.2", name: "Llama 3.2 (3B)" },
          { id: "phi4", name: "Phi-4 (14B)" },
        ],
      },
    };

    render(<ModelInferenceSection {...props} />);

    // The loaded local model should appear (it's a registered chat provider).
    expect(screen.getByText("Local: LFM2.5-Q4_K_M.gguf · LFM2.5-Q4_K_M.gguf")).toBeInTheDocument();

    // Ollama's hardcoded models must NOT appear — ollama is not registered.
    expect(screen.queryByText("Ollama · DeepSeek R1 (7B)")).not.toBeInTheDocument();
    expect(screen.queryByText("Ollama · Llama 3.2 (3B)")).not.toBeInTheDocument();
    expect(screen.queryByText("Ollama · Phi-4 (14B)")).not.toBeInTheDocument();

    // Cerebras models must NOT appear either — cerebras is not registered.
    expect(screen.queryByText("Cerebras · Gemma 4 31B")).not.toBeInTheDocument();
    expect(screen.queryByText("Cerebras · Llama 3.3 70B")).not.toBeInTheDocument();
  });

  it("shows catalog models when the provider IS registered (configured via Provider Setup)", () => {
    // Simulate: user configured cerebras via Provider Setup → it's in providers.
    const configuredCerebras = {
      id: "cerebras",
      label: "Cerebras",
      kind: "api",
      model: "gemma-4-31b",
      has_key: true,
      purpose: "chat",
    };
    const props = {
      ...defaultProps,
      providers: [configuredCerebras],
      role_bindings: [
        { role: "reasoning", instance_id: "cerebras" },
      ],
      provider_presets: [
        { id: "cerebras", label: "Cerebras", kind: "api", needs_key: true, api_base_url: "https://api.cerebras.ai/v1" },
        { id: "ollama", label: "Ollama", kind: "ollama", needs_key: false, api_base_url: "http://localhost:11434" },
      ],
      model_catalog: {
        cerebras: [
          { id: "gemma-4-31b", name: "Gemma 4 31B" },
          { id: "llama-3.3-70b", name: "Llama 3.3 70B" },
        ],
      },
    };

    render(<ModelInferenceSection {...props} />);

    // Cerebras IS registered → its catalog models should appear.
    expect(screen.getByText("Cerebras · Gemma 4 31B")).toBeInTheDocument();
    expect(screen.getByText("Cerebras · Llama 3.3 70B")).toBeInTheDocument();

    // Ollama is NOT registered → its models must NOT appear.
    expect(screen.queryByText("Ollama ·")).not.toBeInTheDocument();
  });
});
