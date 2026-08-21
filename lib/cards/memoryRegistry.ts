// === MEMORY EVENT REGISTRY (REQ-15) ===
// ONE place that defines every memory-activity "kind" the card footer / header
// memory slot can show — label, glyph, FIXED field order, and how to format
// the values. The card and CLI renderer read ONLY this registry; neither one
// switches on a tool/event name (REQ-15 AC2).
//
// WHY FIXED FIELDS, FIXED ORDER (see docs/Wormhole-resonant-recall-.md
// Section 9): a recall surface rendered as variable prose "gets
// pattern-matched as noise and ignored by the agent's own downstream
// reasoning, regardless of retrieval quality." Rendering from a stable
// per-kind schema, in the same order every time, is the fix — so every kind
// here declares its `fields` once and every renderer honours that order.
//
// AC6 / FORWARD-COMPAT: `recall` reserves the planned Wormhole vocabulary
// (`tier`, `hyperedge_posterior`, `hex_bin_id`, `resonance`, `last_activated`,
// landmark `elevation`) WITHOUT implementing any recall mechanics. When that
// work lands, it edits the `recall` entry below — it does not touch a card.

export type MemoryEventKind = "learning" | "crystallized" | "recall" | "compress" | "episodic"

export interface MemoryEntry {
  kind: MemoryEventKind
  label: string
  glyph: string
  /** FIXED field order — the stable shape the agent (and the user) learns to
   *  recognize. Rendering MUST walk this array, never `Object.keys(data)`. */
  fields: string[]
  /** Optional. When absent, `formatMemoryEntry` falls back to each field's
   *  raw value (REQ-15 edge case) — a missing formatter never crashes. */
  format?: (data: Record<string, unknown>) => string
  /** True once a real backend emit site exists for this kind. `learning` is
   *  the only kind emitting today (`agent_kernel.py:11403`); `recall`,
   *  `compress` and `episodic` are registered ahead of their emits (T8c) so
   *  landing them later is a registry edit, not a card rewrite. */
  emitting: boolean
}

/** The reserved Wormhole recall vocabulary (REQ-15 AC6). Present here as
 *  DATA, not implemented — no hashing, no walking, no scorecards. */
export const RESERVED_WORMHOLE_FIELDS = [
  "hex_bin_id",
  "tier",
  "hyperedge_posterior",
  "resonance",
  "last_activated",
  "elevation",
] as const

function fmtSignal(data: Record<string, unknown>): string {
  const signal = String(data.signal ?? "")
  const verified = String(data.verified_label ?? "")
  return verified ? `${signal} (${verified})` : signal
}

export const MEMORY_EVENT_REGISTRY: Record<MemoryEventKind, MemoryEntry> = {
  // Emitting today (agent_kernel.py:11403, task:learning). Covers the
  // "avoided" / "retried" signals; "crystallized" gets its own entry below
  // so a captured skill reads distinctly in the footer.
  learning: {
    kind: "learning",
    label: "Learning",
    glyph: "◈", // ◈
    fields: ["signal", "verified_label"],
    format: fmtSignal,
    emitting: true,
  },

  // Same wire event (task:learning), signal === "crystallized" — a skill was
  // captured. Registered separately (per design.md's memory-event table) so
  // it gets its own label/glyph rather than sharing the generic "Learning"
  // wording for what is, to the user, a distinct and positive outcome.
  crystallized: {
    kind: "crystallized",
    label: "Crystallized",
    glyph: "✦", // ✦
    fields: ["signal", "verified_label"],
    format: fmtSignal,
    emitting: true,
  },

  // Emitting since T8c ( `mcm.py:161` MCM.recall() -> event bus).
  // Reserved Wormhole vocabulary — see RESERVED_WORMHOLE_FIELDS above and
  // Wormhole doc Section 9's fixed-order format:
  //   [RECALL @ hex_bin_id]
  //     tier: hash | walk
  //     hyperedge_posterior: alpha/(alpha+beta)
  //     last_activated: <relative time>
  // `resonance` (amplitude, Section 5) and landmark `elevation` (Section 7)
  // are additionally reserved per REQ-15 AC6, appended after the doc's core
  // three so the seam accepts them without reordering the header trio.
  recall: {
    kind: "recall",
    label: "Recall",
    glyph: "↻", // ↻
    fields: [...RESERVED_WORMHOLE_FIELDS],
    emitting: true,
  },

  // Emitting since T8c ( `mcm.py:86` MCM.compress()). Fields grounded
  // in MCM.compress()'s actual return dict (nbl, active_task, active_files,
  // unverified_edits, warnings, recovery_preamble, compressed_at) — a concise
  // "what got checkpointed and when" slice rather than the full payload.
  compress: {
    kind: "compress",
    label: "Compress",
    glyph: "⚙", // ⚙
    fields: ["active_task", "active_files", "compressed_at"],
    emitting: true,
  },

  // Emitting since T8c ( `agent_kernel.py:752` get_task_context()).
  // Fields grounded in `backend/memory/episodic.py`'s Episode dataclass
  // (task_summary, outcome_type, duration_ms are the fields meaningful to a
  // user-facing footer; tool_sequence / full_content are not).
  episodic: {
    kind: "episodic",
    label: "Episodic",
    glyph: "☷", // ☷
    fields: ["task_summary", "outcome_type", "duration_ms"],
    emitting: true,
  },
}

const _warnedUnknownKinds = new Set<string>()

/**
 * Format one memory event for display. Returns an ordered list of
 * `{ field, value }` pairs (the FIXED order from the registry entry) plus the
 * entry's label/glyph, or `null` if the kind is unregistered.
 *
 * REQ-15 AC5: an unregistered kind is ignored and logged ONCE — never per
 * event, so a repeating unknown kind cannot flood the log — and never
 * renders a partial entry.
 */
export function formatMemoryEntry(
  kind: string,
  data: Record<string, unknown>,
): { label: string; glyph: string; fields: Array<{ field: string; value: string }>; summary: string } | null {
  const entry = MEMORY_EVENT_REGISTRY[kind as MemoryEventKind]
  if (!entry) {
    if (!_warnedUnknownKinds.has(kind)) {
      _warnedUnknownKinds.add(kind)
      // eslint-disable-next-line no-console
      console.warn(`[memoryRegistry] unregistered memory event kind: ${kind}`)
    }
    return null
  }

  const fields = entry.fields.map((field) => {
    const raw = data[field]
    return { field, value: raw === undefined || raw === null ? "" : String(raw) }
  })

  // A missing formatter falls back to the raw per-field values, joined in
  // the same fixed order — never a crash, never a blank cell.
  const summary = entry.format
    ? entry.format(data)
    : fields.map((f) => `${f.field}: ${f.value}`).join(", ")

  return { label: entry.label, glyph: entry.glyph, fields, summary }
}

/** All registered kinds, e.g. for enumerating in a settings/debug surface. */
export function getRegisteredMemoryKinds(): MemoryEventKind[] {
  return Object.keys(MEMORY_EVENT_REGISTRY) as MemoryEventKind[]
}
