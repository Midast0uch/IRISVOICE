/**
 * The memory surface survives a cold first read (lib/memory/api.ts fetchMemorySnapshot).
 *
 * 2026-10-24/25, live: after every backend start the app's proxy hung up on the snapshot (~30 s, "socket hang up",
 * 500 to the page) while the backend went on and cached it - the surface said "the memory is resting". A 5xx or a
 * lost connection is now asked again (every 5 s, inside the 180 s budget); a 4xx is an answer and is not.
 */
import { fetchMemorySnapshot, MemoryResting } from "@/lib/memory/api"

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as unknown as Response
const fail = (status: number) => ({ ok: false, status, json: async () => ({}) }) as unknown as Response

describe("fetchMemorySnapshot on a cold store", () => {
  const realFetch = global.fetch
  beforeEach(() => jest.useFakeTimers())
  afterEach(() => {
    jest.useRealTimers()
    global.fetch = realFetch
  })

  it("asks again after the proxy drops the read, and gets the model", async () => {
    const calls: number[] = []
    const replies: Array<() => Response> = [
      () => fail(500),                                                 // the proxy's hang-up
      () => { throw new TypeError("Failed to fetch") },               // a lost connection
      () => ok({ meta: { source: "x" } }),                             // the backend's cache
    ]
    global.fetch = jest.fn(() => {
      calls.push(Date.now())
      try { return Promise.resolve(replies.shift()!()) } catch (e) { return Promise.reject(e) }
    }) as any
    const p = fetchMemorySnapshot()
    await jest.advanceTimersByTimeAsync(11_000)
    await expect(p).resolves.toEqual({ meta: { source: "x" } })   // old code: MemoryResting on the first 500
    expect(calls).toHaveLength(3)
  })

  it("does not ask again on a 404: the backend has no reader, waiting will not help", async () => {
    global.fetch = jest.fn(() => Promise.resolve(fail(404))) as any
    await expect(fetchMemorySnapshot()).rejects.toBeInstanceOf(MemoryResting)
    expect(global.fetch).toHaveBeenCalledTimes(1)
  })
})
