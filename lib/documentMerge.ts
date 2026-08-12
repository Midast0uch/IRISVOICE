// Pure, dependency-free merge used by document re-hydration (REQ-1/2/3).
// Kept out of chat-view.tsx so it is unit-testable without pulling in
// react-markdown / framer-motion (ESM) into the test bundle.

export interface HydratedDoc {
  document_id?: string
  format?: string
  sources?: { url: string; title: string }[]
  har_path?: string | null
  /** Which exchange produced this render. Lets a rehydrated card be paired with
   * its turn — and lets the agent say which question a previous markdown was
   * answering when it compares old findings with new ones. */
  turn_id?: string | null
}

export interface MergedRenderedDoc {
  id: string
  format: string
  content: string
  alternatives: string[]
  documentId?: string
  turnId?: string
  error: string | null
  trust?: string
  sources?: { url: string; title: string }[]
  harPath?: string | null
}

// Idempotent merge of incoming hydrated documents into the existing rendered
// list, keyed on document_id. Re-hydrating the same conversation never
// duplicates cards (REQ-3).
//
// MERGES field-by-field rather than replacing the entry. The hydration payload
// is metadata-light by design — it carries no content, because the full body is
// fetched on expand — so overwriting a card wholesale BLANKED any card that was
// already rendered with its content. A freshly synthesized answer would appear
// and then empty itself the moment hydration ran for that conversation, which is
// what "the markdown never rendered" looked like: it rendered, then lost its
// body to a metadata refresh. Incoming values win where present; existing values
// survive where the payload has nothing to say.
export function mergeRenderedDocuments(
  prev: MergedRenderedDoc[],
  docs: HydratedDoc[],
): MergedRenderedDoc[] {
  const byId = new Map(prev.map((d) => [d.documentId, d]))
  for (const d of docs) {
    if (!d.document_id) continue
    const existing = byId.get(d.document_id)
    byId.set(d.document_id, {
      ...existing,
      id: d.document_id,
      format: d.format || existing?.format || 'markdown',
      // Keep a body we already have; hydration never carries one.
      content: existing?.content ?? '',
      alternatives: existing?.alternatives ?? [],
      documentId: d.document_id,
      turnId: d.turn_id ?? existing?.turnId,
      error: null,
      trust: existing?.trust,
      sources: d.sources ?? existing?.sources ?? [],
      harPath: d.har_path ?? existing?.harPath ?? null,
    })
  }
  return Array.from(byId.values())
}
