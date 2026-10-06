/**
 * The ONE Monitor page (components/dashboard/MonitorPage.tsx): the old Monitor
 * tab and the Inference console merged, nothing shown twice
 * (docs/architecture/MONITOR.md), laid out as the concept's instrument panel (tile
 * strip + panes, no settings rows). Events come in the way the app delivers them:
 * the WS hook re-dispatches every message as `iris:ws_message`.
 */
import "@testing-library/jest-dom"
import React from "react"
import { render, screen, act, fireEvent, within } from "@testing-library/react"
import { MonitorPage } from "@/components/dashboard/MonitorPage"

function ws(type: string, payload: any) {
  act(() => {
    window.dispatchEvent(new CustomEvent("iris:ws_message", { detail: { type, payload } }))
  })
}
const call = (model: string, over: Record<string, any> = {}) =>
  ws("inference_event", { model, prompt_tokens: 612, completion_tokens: 88, tps: 41, time_ms: 900, timestamp: 1_700_000_000, ...over })
const load = (action: string, model: string, profile = "reasoning") =>
  ws("model_load_event", { action, model, profile, timestamp: 1_700_000_100 })
const field = (field_id: string, value: any) => ws("update_field", { field_id, value: JSON.stringify(value) })

const rows = (c: HTMLElement) => Array.from(c.querySelectorAll("[data-area]")).map((r) => r.getAttribute("data-area"))
const rowEl = (c: HTMLElement, id: string) => c.querySelector(`[data-area="${id}"]`) as HTMLElement

describe("MonitorPage areas", () => {
  it("shows the five areas in order, and Context only in developer mode", () => {
    const { container, rerender } = render(<MonitorPage sendMessage={jest.fn()} />)
    expect(rows(container)).toEqual(["now", "stream", "usage", "logs", "diagnostics"])
    rerender(<MonitorPage sendMessage={jest.fn()} developerMode />)
    expect(rows(container)).toEqual(["now", "stream", "usage", "logs", "diagnostics", "context"])
  })

  it("Now follows load and call events, one source per value", () => {
    const { container } = render(<MonitorPage sendMessage={jest.fn()} />)
    load("loaded", "C:\\models\\qwen3-30b.gguf")
    call("qwen3-30b", { tps: 41, time_ms: 1600 })
    const now = within(rowEl(container, "now"))
    expect(now.getByText("qwen3-30b.gguf")).toBeInTheDocument()
    expect(now.getByText("41")).toBeInTheDocument() // Speed tile, big number (tok/s in its small unit)
    expect(now.getByText(/last call 1\.6 s · avg 41\.0/)).toBeInTheDocument()
    load("unloaded", "C:\\models\\qwen3-30b.gguf")
    // two model tiles (Reasoning, Tool), both without a load now
    expect(now.getAllByText("no load seen")).toHaveLength(2)
  })
})

describe("one place for each line", () => {
  it("a streamed call shows in the stream and NOT in Logs", () => {
    const send = jest.fn()
    const { container } = render(<MonitorPage sendMessage={send} />)
    call("qwen3-4b", { prompt_tokens: 612, completion_tokens: 88 })
    // The backend logs the same call as a line; Logs must hide it.
    field("system_logs", [
      { timestamp: "2026-10-06T08:41:07", level: "INFO", source: "agent", message: "[InferenceRouter] call done role=reasoning model=qwen3-4b 0.90s ok=True" },
      { timestamp: "2026-10-06T08:41:08", level: "INFO", source: "system", message: "[Timing] process_text_message (streamed): 900 ms" },
      { timestamp: "2026-10-06T08:41:09", level: "INFO", source: "agent", message: "[LocalModelManager] Model unloaded" },
      { timestamp: "2026-10-06T08:41:10", level: "INFO", source: "system", message: "hedge sent at 10.2 s" },
    ])
    const stream = within(rowEl(container, "stream"))
    const logs = within(rowEl(container, "logs"))
    expect(stream.getByText(/612 → 88/)).toBeInTheDocument()
    expect(logs.getByText(/hedge sent at 10\.2 s/)).toBeInTheDocument()
    expect(logs.queryByText(/call done/)).toBeNull()
    expect(logs.queryByText(/Timing\] process_text_message/)).toBeNull()
    expect(logs.queryByText(/Model unloaded/)).toBeNull()
    expect(logs.getByText(/3 model-call lines are in the stream, not here/)).toBeInTheDocument()
    // The call exists once on the whole page.
    expect(screen.getAllByText(/612 → 88/)).toHaveLength(1)
  })

  it("Usage shows each number once and no Recent Activity list", () => {
    const { container } = render(<MonitorPage sendMessage={jest.fn()} />)
    ws("monitor_analytics_data", {
      stats: { total_calls: 37, total_prompt_tokens: 150000, total_completion_tokens: 32400, total_tokens: 182400, total_audio_tokens: 0, estimated_cost: 0.0123, avg_latency_ms: 6100, session_duration_minutes: 12.5 },
      models: [{ model: "qwen3-4b", total_calls: 30, total_tokens: 100000, estimated_cost: 0.01, percentage: 55 }],
      latency: { count: 37, min_ms: 400, max_ms: 9000, avg_ms: 6100, p50_ms: 5800, p95_ms: 8800 },
      recent: [{ timestamp: 1_700_000_000, session_id: "s", model: "qwen3-4b", prompt_tokens: 1, completion_tokens: 1, total_tokens: 2, latency_ms: 123, mode: "conversation", estimated_cost: 0 }],
    })
    const usage = within(rowEl(container, "usage"))
    expect(usage.getAllByText("182.4K")).toHaveLength(1)
    expect(usage.getAllByText("37")).toHaveLength(1)
    expect(usage.queryByText(/Recent/i)).toBeNull()
    expect(usage.queryByText("123ms")).toBeNull()
    expect(usage.getAllByText(/Latency, average/)).toHaveLength(1)
  })

  it("Diagnostics does not repeat the models of Now or the health checks in Issues", () => {
    const { container } = render(<MonitorPage sendMessage={jest.fn()} />)
    field("system_health", [{ component: "gpu", status: "warning", message: "nvidia-smi slow", latency_ms: 0 }])
    field("troubleshoot", { issues: [], warnings: ["WARN [gpu]: nvidia-smi slow", "Swarm is disabled."], summary: "" })
    field("debug_info", ["Provider: local", "Reasoning model: qwen3", "Tool model: qwen3-4b"])
    const d = within(rowEl(container, "diagnostics"))
    expect(d.getAllByText(/nvidia-smi slow/)).toHaveLength(1)
    expect(d.getByText("Swarm is disabled.")).toBeInTheDocument()
    expect(d.getByText("Provider")).toBeInTheDocument()
    expect(d.queryByText("Reasoning model")).toBeNull()
    expect(d.queryByText("Tool model")).toBeNull()
  })
})

describe("stream controls stay reachable", () => {
  it("filter all / calls / loads", () => {
    const { container } = render(<MonitorPage sendMessage={jest.fn()} />)
    call("qwen3-4b")
    load("loaded", "qwen3-30b", "reasoning")
    const stream = within(rowEl(container, "stream"))
    expect(stream.getByText(/612 → 88/)).toBeInTheDocument()
    expect(stream.getByText(/loaded · reasoning/)).toBeInTheDocument()
    fireEvent.click(stream.getByRole("button", { name: "loads" }))
    expect(stream.queryByText(/612 → 88/)).toBeNull()
    expect(stream.getByText(/loaded · reasoning/)).toBeInTheDocument()
    fireEvent.click(stream.getByRole("button", { name: "calls" }))
    expect(stream.getByText(/612 → 88/)).toBeInTheDocument()
    expect(stream.queryByText(/loaded · reasoning/)).toBeNull()
  })

  it("pause freezes the stream, resume follows again, clear empties it", () => {
    const { container } = render(<MonitorPage sendMessage={jest.fn()} />)
    const stream = within(rowEl(container, "stream"))
    call("a-model", { prompt_tokens: 1 })
    fireEvent.click(stream.getByRole("button", { name: "Pause" }))
    call("b-model", { prompt_tokens: 2 })
    expect(stream.queryByText(/b-model/)).toBeNull()
    fireEvent.click(stream.getByRole("button", { name: "Resume" }))
    call("c-model", { prompt_tokens: 3 })
    expect(stream.getByText(/a-model/)).toBeInTheDocument()
    expect(stream.getByText(/c-model/)).toBeInTheDocument()
    fireEvent.click(stream.getByRole("button", { name: "Clear" }))
    expect(stream.getByText(/Waiting for inference events/)).toBeInTheDocument()
  })

  it("export writes the stream entries as JSON", () => {
    const { container } = render(<MonitorPage sendMessage={jest.fn()} />)
    const stream = within(rowEl(container, "stream"))
    expect(stream.getByRole("button", { name: "Export" })).toBeDisabled()
    call("a-model")
    const blobs: Blob[] = []
    ;(URL as any).createObjectURL = jest.fn((b: Blob) => { blobs.push(b); return "blob:x" })
    ;(URL as any).revokeObjectURL = jest.fn()
    const click = jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})
    fireEvent.click(stream.getByRole("button", { name: "Export" }))
    expect(click).toHaveBeenCalledTimes(1)
    expect(blobs).toHaveLength(1)
    expect(blobs[0].type).toBe("application/json")
    click.mockRestore()
  })
})

describe("lazy panes and refresh", () => {
  // jsdom has no IntersectionObserver: a stand-in lets the test decide when a
  // pane scrolls into view (panes are always on screen now, there is no "open").
  const watchers: { el: Element; cb: (hits: any[]) => void; live: boolean }[] = []
  const scrollIntoView = (area: string) =>
    watchers.filter((w) => w.live && w.el.getAttribute("data-area") === area).forEach((w) => w.cb([{ isIntersecting: true }]))
  beforeEach(() => {
    watchers.length = 0
    ;(globalThis as any).IntersectionObserver = class {
      private w: any
      constructor(cb: any) { this.w = { el: null, cb, live: true }; watchers.push(this.w) }
      observe(el: Element) { this.w.el = el }
      disconnect() { this.w.live = false }
      unobserve() {}
    }
  })
  afterEach(() => { delete (globalThis as any).IntersectionObserver })

  it("Logs and Diagnostics read the backend on first view only; refresh buttons re-ask", () => {
    const send = jest.fn()
    render(<MonitorPage sendMessage={send} />)
    const sections = () => send.mock.calls.map((c) => c[1].section_id)
    expect(sections()).toEqual(["analytics"])
    scrollIntoView("logs")
    scrollIntoView("diagnostics")
    expect(sections()).toEqual(["analytics", "logs", "diagnostics"])
    scrollIntoView("logs") // seen again: no second read
    expect(sections()).toEqual(["analytics", "logs", "diagnostics"])
    fireEvent.click(screen.getByRole("button", { name: "Run checks" }))
    expect(sections().filter((s: string) => s === "diagnostics")).toHaveLength(2)
  })

  it("Logs level chips and search still filter", () => {
    const { container } = render(<MonitorPage sendMessage={jest.fn()} />)
    field("system_logs", [{ timestamp: "2026-10-06T08:00:00", level: "INFO", source: "system", message: "boot ok" }])
    field("error_logs", [{ timestamp: "2026-10-06T08:00:01", level: "ERROR", source: "system", message: "disk bad" }])
    const logs = within(rowEl(container, "logs"))
    fireEvent.click(logs.getByRole("button", { name: "ERROR" }))
    expect(logs.getByText(/disk bad/)).toBeInTheDocument()
    expect(logs.queryByText(/boot ok/)).toBeNull()
    fireEvent.click(logs.getByRole("button", { name: "ALL" }))
    fireEvent.change(logs.getByLabelText("Filter logs"), { target: { value: "boot" } })
    expect(logs.getByText(/boot ok/)).toBeInTheDocument()
    expect(logs.queryByText(/disk bad/)).toBeNull()
  })
})

describe("open_inference_console", () => {
  it("openRow stream scrolls to and focuses the Inference stream pane, again on each request", () => {
    const scroll = jest.fn()
    ;(Element.prototype as any).scrollIntoView = scroll
    const { container, rerender } = render(<MonitorPage sendMessage={jest.fn()} openRow={null} />)
    const stream = () => rowEl(container, "stream")
    expect(scroll).not.toHaveBeenCalled()
    expect(document.activeElement).not.toBe(stream())
    rerender(<MonitorPage sendMessage={jest.fn()} openRow={{ row: "stream", n: 1 }} />)
    expect(scroll).toHaveBeenCalledTimes(1)
    expect(scroll.mock.contexts[0]).toBe(stream())
    expect(document.activeElement).toBe(stream())
    ;(document.activeElement as HTMLElement).blur()
    rerender(<MonitorPage sendMessage={jest.fn()} openRow={{ row: "stream", n: 2 }} />)
    expect(scroll).toHaveBeenCalledTimes(2)
    expect(document.activeElement).toBe(stream())
    delete (Element.prototype as any).scrollIntoView
  })
})

describe("Context pane (developer mode)", () => {
  it("counts DCP prune passes", () => {
    const { container } = render(<MonitorPage sendMessage={jest.fn()} developerMode />)
    act(() => {
      window.dispatchEvent(new CustomEvent("iris:dcp_pruned", { detail: { input_count: 10, output_count: 6, dedups: 2, errors_purged: 1, writes_superseded: 1, tokens_saved: 500 } }))
    })
    const ctx = within(rowEl(container, "context"))
    expect(ctx.getByText("Prune passes").parentElement).toHaveTextContent("1")
    expect(ctx.getByText("Tokens saved").parentElement).toHaveTextContent("500")
  })
})
