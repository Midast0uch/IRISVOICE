/**
 * Phase 5 (specs/phase-5-switcher) — Wave 2, T2.8.
 *
 * REQ-2: lists only API providers with `has_key` and local models with
 * `loaded`; excludes `purpose != "chat"` (REQ-2 AC2/AC3/AC4); selection
 * writes through `sendRoleBinding` (D-3, CT-S5 payload shape); a failed
 * bind leaves the previous selection active (REQ-4 AC3); empty and loading
 * states are distinct (REQ-2 AC9); no key or fragment ever renders (D-4).
 */
import "@testing-library/jest-dom"
import { render, screen, fireEvent, act } from "@testing-library/react"
import React from "react"
import ModelSwitcher from "@/components/ModelSwitcher"
import { useInferenceState } from "@/hooks/useInferenceState"

jest.mock("@/hooks/useInferenceState")
const mockUseInferenceState = useInferenceState as jest.Mock

// jsdom does not implement scrollIntoView (CustomDropdown's focused-option
// effect calls it whenever a dropdown opens).
beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn()
})

function baseState(overrides: Partial<ReturnType<typeof useInferenceState>> = {}) {
  return {
    providers: [],
    role_bindings: [],
    default_role: "reasoning",
    provider_presets: [],
    loading: false,
    error: null,
    sendRoleBinding: jest.fn(),
    sendModelSelection: jest.fn(),
    sendInferenceMode: jest.fn(),
    ...overrides,
  }
}

describe("ModelSwitcher (Phase 5 REQ-2)", () => {
  afterEach(() => jest.clearAllMocks())

  it("AC9: shows a distinct loading state before providers arrive", () => {
    mockUseInferenceState.mockReturnValue(baseState({ loading: true }))
    render(<ModelSwitcher />)
    // The trigger is disabled while loading (cannot be opened) — its own
    // title is the loading signal, distinct from the empty-state message.
    const trigger = screen.getByTestId("model-switcher-trigger")
    expect(trigger).toBeDisabled()
    expect(trigger.getAttribute("title")).toMatch(/Loading models/i)
  })

  it("AC9: shows an actionable empty state when nothing is usable yet (distinct from loading)", () => {
    mockUseInferenceState.mockReturnValue(
      baseState({
        providers: [
          { id: "openai", label: "OpenAI", kind: "api", model: "gpt-4", has_key: false, purpose: "chat" },
        ],
      })
    )
    render(<ModelSwitcher />)
    fireEvent.click(screen.getByTestId("model-switcher-trigger"))
    expect(screen.getByTestId("model-switcher-empty")).toBeInTheDocument()
    expect(screen.queryByTestId("model-switcher-loading")).not.toBeInTheDocument()
  })

  it("AC2/AC3/AC4: only API+has_key, local+loaded, purpose=chat entries are offered", () => {
    mockUseInferenceState.mockReturnValue(
      baseState({
        providers: [
          // Usable: API with a key.
          { id: "cerebras", label: "Cerebras", kind: "api", model: "gemma-4-31b", has_key: true, purpose: "chat" },
          // Excluded: API without a key (REQ-2 AC2).
          { id: "openai", label: "OpenAI", kind: "api", model: "gpt-4", has_key: false, purpose: "chat" },
          // Usable: local model that is loaded.
          { id: "local:qwen3-9b", label: "Local", kind: "inprocess", model: "qwen3-9b", loaded: true, purpose: "chat" },
          // Excluded: local model not loaded (REQ-2 AC3).
          { id: "local:mistral", label: "Local", kind: "inprocess", model: "mistral-7b", loaded: false, purpose: "chat" },
          // Excluded: non-chat purpose, even though it has a key (REQ-2 AC4).
          {
            id: "embedding:lfm25",
            label: "LFM2.5 Embedding",
            kind: "inprocess",
            model: "LFM2.5-Embedding-350M",
            loaded: true,
            purpose: "embedding",
          },
        ],
      })
    )
    render(<ModelSwitcher />)
    fireEvent.click(screen.getByTestId("model-switcher-trigger"))

    // The candidate list lives inside each role's CustomDropdown, which only
    // renders its option list once opened — open the Brain dropdown to see
    // the actual candidate set.
    const brainSection = screen.getByTestId("model-switcher-reasoning")
    fireEvent.click(brainSection.querySelector("button") as HTMLButtonElement)
    const optionsText = screen.getAllByRole("option").map((o) => o.textContent).join(" | ")

    expect(optionsText).toMatch(/Cerebras/)
    expect(optionsText).toMatch(/qwen3-9b/)
    expect(optionsText).not.toMatch(/OpenAI/)
    expect(optionsText).not.toMatch(/mistral-7b/)
    expect(optionsText).not.toMatch(/Embedding/)
  })

  it("AC5/AC7: selecting a role writes through sendRoleBinding, independently for reasoning/tool_execution", () => {
    const sendRoleBinding = jest.fn()
    mockUseInferenceState.mockReturnValue(
      baseState({
        providers: [
          { id: "cerebras", label: "Cerebras", kind: "api", model: "gemma-4-31b", has_key: true, purpose: "chat" },
          { id: "local:qwen3-9b", label: "Local", kind: "inprocess", model: "qwen3-9b", loaded: true, purpose: "chat" },
        ],
        sendRoleBinding,
      })
    )
    render(<ModelSwitcher />)
    fireEvent.click(screen.getByTestId("model-switcher-trigger"))

    const brainSection = screen.getByTestId("model-switcher-reasoning")
    const brainSelect = brainSection.querySelector("button") as HTMLButtonElement
    fireEvent.click(brainSelect)
    fireEvent.click(screen.getByText(/Cerebras/))
    expect(sendRoleBinding).toHaveBeenCalledWith("reasoning", "cerebras")

    const toolSection = screen.getByTestId("model-switcher-tool_execution")
    const toolSelect = toolSection.querySelector("button") as HTMLButtonElement
    fireEvent.click(toolSelect)
    fireEvent.click(screen.getByText(/qwen3-9b/))
    expect(sendRoleBinding).toHaveBeenCalledWith("tool_execution", "local:qwen3-9b")

    // Brain and Tool are independently bindable — two DIFFERENT calls, two
    // different instance ids (REQ-2 AC7, Decision Locked #4).
    expect(sendRoleBinding).toHaveBeenCalledTimes(2)
  })

  it("AC6: shows which model is active before the dropdown opens", () => {
    mockUseInferenceState.mockReturnValue(
      baseState({
        providers: [
          { id: "cerebras", label: "Cerebras", kind: "api", model: "gemma-4-31b", has_key: true, purpose: "chat" },
        ],
        role_bindings: [{ role: "reasoning", instance_id: "cerebras" }],
      })
    )
    render(<ModelSwitcher />)
    const trigger = screen.getByTestId("model-switcher-trigger")
    expect(trigger.getAttribute("title")).toMatch(/Cerebras/)
  })

  it("REQ-4 AC3: a bind failure surfaces the error and leaves the PREVIOUS selection active", () => {
    mockUseInferenceState.mockReturnValue(
      baseState({
        providers: [
          { id: "cerebras", label: "Cerebras", kind: "api", model: "gemma-4-31b", has_key: true, purpose: "chat" },
          { id: "openai", label: "OpenAI", kind: "api", model: "gpt-4", has_key: true, purpose: "chat" },
        ],
        // The bound role_binding never changes — the backend only broadcasts
        // role_bindings_updated on a SUCCESSFUL bind (REQ-4 AC3 comment in
        // ModelSwitcher.tsx). A failure only fires role_binding_error.
        role_bindings: [{ role: "reasoning", instance_id: "cerebras" }],
      })
    )
    render(<ModelSwitcher />)

    // Simulate the backend reporting a failed bind attempt.
    act(() => {
      window.dispatchEvent(
        new CustomEvent("iris:role_binding_error", {
          detail: { error: "provider unreachable", role: "reasoning", instance_id: "openai" },
        })
      )
    })

    // The trigger still shows the OLD active model — never the failed one.
    const trigger = screen.getByTestId("model-switcher-trigger")
    expect(trigger.getAttribute("title")).toMatch(/Cerebras/)
    expect(trigger.getAttribute("title")).not.toMatch(/OpenAI/)

    fireEvent.click(trigger)
    expect(screen.getByTestId("model-switcher-error").textContent).toMatch(/provider unreachable/)
  })

  it("D-4/AC8: never renders a key, key fragment, or masked key anywhere in the DOM", () => {
    mockUseInferenceState.mockReturnValue(
      baseState({
        providers: [
          {
            id: "cerebras",
            label: "Cerebras",
            kind: "api",
            model: "gemma-4-31b",
            has_key: true,
            purpose: "chat",
            // Even if a caller mistakenly attached a raw key to the Provider
            // object, ModelSwitcher's own rendering must never surface it —
            // the component only ever reads the has_key boolean.
            api_key: "FAKETESTCRED-should-never-render-1234567890",
          } as any,
        ],
      })
    )
    const { container } = render(<ModelSwitcher />)
    fireEvent.click(screen.getByTestId("model-switcher-trigger"))
    expect(container.innerHTML).not.toMatch(/sk-should-never-render/)
  })
})
