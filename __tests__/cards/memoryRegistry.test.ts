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

  it("registers recall / compress / episodic as emitting (T8c wired the real emit sites)", () => {
    expect(MEMORY_EVENT_REGISTRY.recall.emitting).toBe(true)
    expect(MEMORY_EVENT_REGISTRY.compress.emitting).toBe(true)
    expect(MEMORY_EVENT_REGISTRY.episodic.emitting).toBe(true)
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
    // UPDATED 2026-08-23 (GROUND TRUTH): this test used `recall` as its
    // example of a kind with no formatter. `recall` has since GAINED one —
    // it renders the reserved Wormhole vocabulary in the fixed order
    // docs/Wormhole-resonant-recall-.md Section 9 requires. The CONTRACT under
    // test is unchanged ("a missing formatter falls back without throwing");
    // only the example moved to `compress`, which is now the kind that
    // genuinely declares none. Same assertions, same load.
    expect(MEMORY_EVENT_REGISTRY.compress.format).toBeUndefined()
    const data = { active_task: "card ordering", active_files: "3 files" }
    let result: ReturnType<typeof formatMemoryEntry> = null
    expect(() => {
      result = formatMemoryEntry("compress", data)
    }).not.toThrow()
    expect(result).not.toBeNull()
    expect(result!.fields.find((f) => f.field === "active_task")?.value).toBe("card ordering")
  })

  it("the recall formatter renders the reserved Wormhole fields in fixed order", () => {
    // The other half of the change above: `recall` now HAS a formatter, and
    // what it produces is a contract in its own right (Section 9: a recall
    // surface rendered as variable prose "gets pattern-matched as noise").
    const fmt = MEMORY_EVENT_REGISTRY.recall.format
    expect(fmt).toBeDefined()
    const out = fmt!({ hex_bin_id: "0xAB12", tier: "hash", hyperedge_posterior: 0.87 })
    // fixed ORDER, not Object.keys order
    expect(out.indexOf("tier")).toBeLessThan(out.indexOf("hyperedge_posterior"))
    expect(out).toContain("0xAB12")
    // and it degrades to something readable when no reserved field is filled
    expect(fmt!({ query: "quantum" })).toContain("quantum")
    expect(fmt!({})).toBe("memory recalled")
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
    // ...and `recall` now emits (T8c), so its reserved Wormhole fields CAN
    // render as live data in the card's memory slot.
    expect(MEMORY_EVENT_REGISTRY.recall.emitting).toBe(true)
  })
})
