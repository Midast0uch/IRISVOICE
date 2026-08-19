// CT-7 guard (REQ-15 / T8b): the memory event registry is the ONLY place
// that defines what a memory-activity kind looks like — label, glyph, and a
// FIXED field order the agent (and the user) learns to recognize.
import {
  MEMORY_EVENT_REGISTRY,
  RESERVED_WORMHOLE_FIELDS,
  formatMemoryEntry,
  getRegisteredMemoryKinds,
} from "@/lib/cards/memoryRegistry"

describe("memoryRegistry — CT-7", () => {
  it("every registered kind has a label, glyph and field order", () => {
    const kinds = getRegisteredMemoryKinds()
    expect(kinds.length).toBeGreaterThan(0)
    for (const kind of kinds) {
      const entry = MEMORY_EVENT_REGISTRY[kind]
      expect(entry.label).toBeTruthy()
      expect(entry.glyph).toBeTruthy()
      expect(Array.isArray(entry.fields)).toBe(true)
      expect(entry.fields.length).toBeGreaterThan(0)
    }
  })

  it("registers `learning` as the only kind emitting today, per agent_kernel.py:11403", () => {
    expect(MEMORY_EVENT_REGISTRY.learning.emitting).toBe(true)
    // signal + verified_label — the two fields the live task:learning event carries.
    expect(MEMORY_EVENT_REGISTRY.learning.fields).toEqual(["signal", "verified_label"])
  })

  it("registers recall / compress / episodic as NOT emitting yet (T8c adds the emits)", () => {
    expect(MEMORY_EVENT_REGISTRY.recall.emitting).toBe(false)
    expect(MEMORY_EVENT_REGISTRY.compress.emitting).toBe(false)
    expect(MEMORY_EVENT_REGISTRY.episodic.emitting).toBe(false)
  })

  it("fields render in the DECLARED order for the same kind every time", () => {
    const data = { verified_label: "VERIFIED", signal: "crystallized" }
    const first = formatMemoryEntry("learning", data)
    const second = formatMemoryEntry("learning", data)
    expect(first).not.toBeNull()
    const expectedOrder = MEMORY_EVENT_REGISTRY.learning.fields
    expect(first!.fields.map((f) => f.field)).toEqual(expectedOrder)
    expect(second!.fields.map((f) => f.field)).toEqual(expectedOrder)
    // Order is stable across repeated calls with differently-ordered input data.
    const reordered = formatMemoryEntry("learning", { signal: "avoided", verified_label: "FAILED" })
    expect(reordered!.fields.map((f) => f.field)).toEqual(expectedOrder)
  })

  it("an unknown kind is ignored, logs once and only once across repeated events", () => {
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {})
    const unknownKind = "__totally_unregistered_kind__"

    const first = formatMemoryEntry(unknownKind, { foo: "bar" })
    const second = formatMemoryEntry(unknownKind, { foo: "baz" })
    const third = formatMemoryEntry(unknownKind, {})

    expect(first).toBeNull()
    expect(second).toBeNull()
    expect(third).toBeNull()
    expect(warnSpy).toHaveBeenCalledTimes(1)

    warnSpy.mockRestore()
  })

  it("a missing formatter falls back to the raw value without throwing", () => {
    // `recall` has no `format` function declared.
    expect(MEMORY_EVENT_REGISTRY.recall.format).toBeUndefined()
    const data = { hex_bin_id: "0xAB12", tier: "hash", hyperedge_posterior: 0.87 }
    let result: ReturnType<typeof formatMemoryEntry> = null
    expect(() => {
      result = formatMemoryEntry("recall", data)
    }).not.toThrow()
    expect(result).not.toBeNull()
    expect(result!.fields.find((f) => f.field === "hex_bin_id")?.value).toBe("0xAB12")
    expect(result!.fields.find((f) => f.field === "tier")?.value).toBe("hash")
  })

  it("the reserved Wormhole field names are present as reserved and are NOT rendered as live data yet", () => {
    // The exact reserved vocabulary named in REQ-15 AC6.
    expect([...RESERVED_WORMHOLE_FIELDS].sort()).toEqual(
      ["elevation", "hex_bin_id", "hyperedge_posterior", "last_activated", "resonance", "tier"].sort(),
    )
    // Every reserved field is declared on the `recall` entry's fixed order...
    for (const field of RESERVED_WORMHOLE_FIELDS) {
      expect(MEMORY_EVENT_REGISTRY.recall.fields).toContain(field)
    }
    // ...but `recall` does not emit yet, so nothing renders these as live data.
    expect(MEMORY_EVENT_REGISTRY.recall.emitting).toBe(false)
  })
})
