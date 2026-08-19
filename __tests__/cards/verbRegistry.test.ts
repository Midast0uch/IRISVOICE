// CT-6 guard (REQ-14 / T8a): the verb registry is the ONLY place a tool name
// maps to a verb. These tests drive the registry against a checked-in
// snapshot of the REAL backend tool list (`tool_registry.py`) rather than a
// hand-picked sample, so a tool the registry has never heard of is caught
// here instead of at render time.
import {
  ALL_VERBS,
  FAMILY_FALLBACK_VERB,
  FAMILY_PREFIX_RULES,
  TOOL_VERB,
  VERBS_BY_FAMILY,
  resolveVerb,
} from "@/lib/cards/verbRegistry"
import toolRegistrySnapshot from "./__fixtures__/tool_registry_snapshot.json"

describe("verbRegistry — CT-6", () => {
  const fixtureTools = toolRegistrySnapshot.tools as Array<{
    name: string
    category: string
    aliases: string[]
  }>

  it("loaded a non-trivial fixture (sanity check the fixture itself is wired)", () => {
    expect(fixtureTools.length).toBeGreaterThan(40)
    expect(toolRegistrySnapshot.tool_count).toBe(fixtureTools.length)
  })

  it("resolves EVERY real registered tool name to a non-empty verb", () => {
    for (const tool of fixtureTools) {
      const verb = resolveVerb(tool.name)
      expect(verb).toBeTruthy()
      expect(verb.length).toBeGreaterThan(0)
    }
  })

  it("resolves every alias of every real tool to a non-empty verb", () => {
    for (const tool of fixtureTools) {
      for (const alias of tool.aliases) {
        const verb = resolveVerb(alias)
        expect(verb).toBeTruthy()
      }
    }
  })

  it("EVERY verb in the registry is <= 6 characters (asserted over the registry, not a hardcoded list)", () => {
    // Iterates VERBS_BY_FAMILY (the actual registry data), so a future verb
    // added there that breaks the 6-char ceiling fails HERE, not at render
    // time where it would just get clipped silently.
    //
    // COUNT UPDATED 26 -> 27 on 2026-08-19 — CALLED OUT DELIBERATELY.
    // This literal is a canary against the vocabulary growing by accident, and it
    // did its job: it caught ERASE being added. That addition was deliberate and
    // is locked as Decision 21 (delete_file must not display as PATCH, which
    // understates a destructive action). The canary is kept, not removed — bump
    // it only alongside a locked decision, never to make a red run green.
    expect(ALL_VERBS.length).toBe(27)
    for (const verb of ALL_VERBS) {
      expect(verb.length).toBeLessThanOrEqual(6)
    }
  })

  it("every verb is a real word, never an all-consonant acronym or truncation", () => {
    // A crude but effective acronym/truncation smell test: a real English verb
    // in this vocabulary always contains at least one vowel.
    for (const verb of ALL_VERBS) {
      expect(verb).toMatch(/[AEIOU]/)
    }
  })

  it("covers every family named in REQ-14 AC4", () => {
    const families = Object.keys(VERBS_BY_FAMILY).sort()
    expect(families).toEqual(
      ["dialog", "exec", "forge", "gui", "io", "media", "memory", "vcs", "vision", "web"].sort(),
    )
  })

  it("an unregistered tool in a known family falls back to the family verb", () => {
    // These names are NOT in TOOL_VERB (verified below) but match a family
    // prefix rule, simulating a future tool added to an existing family.
    const probes: Array<{ name: string; family: keyof typeof FAMILY_FALLBACK_VERB }> = [
      { name: "git_stash", family: "vcs" },
      { name: "github_list_orgs", family: "forge" },
      { name: "vision_read_pixel", family: "vision" },
      { name: "gui_scroll", family: "gui" },
    ]
    for (const probe of probes) {
      expect(TOOL_VERB[probe.name]).toBeUndefined()
      expect(resolveVerb(probe.name)).toBe(FAMILY_FALLBACK_VERB[probe.family])
    }
  })

  it("a completely unknown tool falls back to its raw name, never blank", () => {
    const verb = resolveVerb("frobnicate_widget_xyz")
    expect(verb).toBeTruthy()
    expect(verb).toBe("FROBNICATE_WIDGET_XYZ")
    // Never a blank cell (AC5), and never crashes on null/undefined input.
    expect(resolveVerb(null)).toBeTruthy()
    expect(resolveVerb(undefined)).toBeTruthy()
    expect(resolveVerb("")).toBeTruthy()
  })

  it("allows two tools to share a verb (SEARCH covers crawler_query and search)", () => {
    expect(resolveVerb("search")).toBe(resolveVerb("crawler_query"))
  })

  it("FUTURE-TOOL GUARD: every real registered tool resolves via tier 1 (registry) or tier 2 (family prefix) — never falls through to the raw-name tier", () => {
    // This is the assertion that actually catches a forgotten mapping. A tool
    // silently missing from TOOL_VERB but ALSO not matching any family prefix
    // rule would resolve via the tier-3 raw-name fallback (still non-blank,
    // so the tests above would stay green) — this test fails loudly on that
    // gap specifically, which is the signal that a real mapping was forgotten
    // rather than a deliberate fallback.
    for (const tool of fixtureTools) {
      const inRegistry = tool.name in TOOL_VERB
      const inFamily = FAMILY_PREFIX_RULES.some((r) => tool.name.startsWith(r.prefix))
      expect(inRegistry || inFamily).toBe(true)
    }
  })
})
