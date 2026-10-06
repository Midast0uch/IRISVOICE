// Shared fixtures for the chat header tests.
import type { Strand, ThreadSummary } from "@/lib/strands/api"

export const thread = (id: string, title: string, over: Partial<ThreadSummary> = {}): ThreadSummary => ({
  id, title, pinned: false, updated_at: "2026-10-05T10:00:00Z", strand_count: 1, message_count: 4, last_preview: "", ...over,
})

export const strand = (id: string, title: string, over: Partial<Strand> = {}): Strand => ({
  id, title, tags: [], reports_to: null, updated_at: "2026-10-05T10:00:00Z", message_count: 2, ...over,
})

// jsdom has no canvas: any method is a no-op, any property assignable.
export function stubCanvas() {
  const ctx = new Proxy({}, {
    get: (t: Record<string, unknown>, k: string) => (k in t ? t[k] : k === "createLinearGradient" ? () => ({ addColorStop() {} }) : () => {}),
    set: (t: Record<string, unknown>, k: string, v: unknown) => { t[k] = v; return true },
  })
  jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation((() => ctx) as never)
}
