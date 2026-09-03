/**
 * T6 behavioral/contract test (REQ-1/2/3): idempotent document re-hydration merge.
 * Re-populating on resume/switch must NOT duplicate cards (keyed on document_id).
 */
import { mergeRenderedDocuments } from '../../lib/documentMerge'

describe('mergeRenderedDocuments (document re-hydration)', () => {
  const docA = {
    document_id: 'a',
    format: 'markdown',
    sources: [{ url: 'http://x.com/a', title: 'A' }],
    har_path: 'data/har/j1.har',
  }
  const docB = { document_id: 'b', format: 'table' }

  it('populates an empty list from a get_documents response', () => {
    const out = mergeRenderedDocuments([], [docA, docB])
    expect(out).toHaveLength(2)
    const a = out.find((d) => d.documentId === 'a')!
    expect(a.format).toBe('markdown')
    expect(a.sources).toEqual([{ url: 'http://x.com/a', title: 'A' }])
    expect(a.harPath).toBe('data/har/j1.har')
    // UI path is metadata-light; full content fetched on expand.
    expect(a.content).toBe('')
  })

  it('is idempotent — re-hydrating the same conversation never duplicates', () => {
    const once = mergeRenderedDocuments([], [docA, docB])
    const twice = mergeRenderedDocuments(once, [docA, docB])
    expect(twice).toHaveLength(2)
    expect(twice.map((d) => d.documentId).sort()).toEqual(['a', 'b'])
  })

  it('merges new documents into an existing list without dropping prior', () => {
    const base = mergeRenderedDocuments([], [docA])
    const merged = mergeRenderedDocuments(base, [docB])
    expect(merged).toHaveLength(2)
    expect(merged.map((d) => d.documentId).sort()).toEqual(['a', 'b'])
  })

  it('ignores documents without a document_id', () => {
    const out = mergeRenderedDocuments([], [{ format: 'markdown' } as any])
    expect(out).toHaveLength(0)
  })

  it('does NOT blank a card that already has its content', () => {
    // The live failure this guards: hydration is metadata-light BY DESIGN (no
    // content — the body is fetched on expand), and it used to overwrite the
    // whole entry. So a freshly synthesized answer rendered with its markdown
    // and then emptied itself the instant hydration ran for that conversation.
    // "The markdown never rendered" was actually "the markdown was erased".
    const live = mergeRenderedDocuments([], [docA])
    live[0].content = '## The synthesized guide\n\nreal body text'
    live[0].trust = 'untrusted'

    const after = mergeRenderedDocuments(live, [docA])

    expect(after).toHaveLength(1)
    expect(after[0].content).toBe('## The synthesized guide\n\nreal body text')
    expect(after[0].trust).toBe('untrusted')
  })

  it('carries turn_id through so a card can be paired with its exchange', () => {
    // turnId was hardcoded to undefined here while the store never persisted the
    // column at all, so a rehydrated document was unattributable at both ends.
    const out = mergeRenderedDocuments([], [
      { document_id: 'c', format: 'markdown', turn_id: 'turn-42' },
    ])
    expect(out[0].turnId).toBe('turn-42')
  })

  it('keeps a known turn_id when a later payload omits it', () => {
    const base = mergeRenderedDocuments([], [
      { document_id: 'd', format: 'markdown', turn_id: 'turn-7' },
    ])
    const after = mergeRenderedDocuments(base, [{ document_id: 'd', format: 'markdown' }])
    expect(after[0].turnId).toBe('turn-7')
  })

  it('uses a body the payload DOES carry instead of blanking the card', () => {
    // The WS hydration path is metadata-only and CT-DOC-1 pins it that way, so
    // this never fires today. It is pinned because the merge is the one place a
    // body can be silently discarded, and a card rendering blank while the data
    // was right there is the exact failure this module exists to prevent (live
    // conv-6: three empty JSON cards beside the markdown). If any caller ever
    // hands this function a body — a REST hydrate, a fetch-on-expand — it must
    // reach the card rather than being dropped on the floor.
    const out = mergeRenderedDocuments([], [
      { document_id: 'e', format: 'json', content: '{"real":true}' } as any,
    ])
    expect(out[0].content).toBe('{"real":true}')
  })

  it('still prefers the LIVE body over one arriving in a payload', () => {
    // Ordering matters: the live render is the full document, a payload copy may
    // be truncated for transport. A payload must never downgrade what is shown.
    const live = mergeRenderedDocuments([], [docA])
    live[0].content = '## the full synthesized guide'
    const after = mergeRenderedDocuments(live, [
      { document_id: 'a', format: 'markdown', content: 'truncated…' } as any,
    ])
    expect(after[0].content).toBe('## the full synthesized guide')
  })

  it('updates an existing card when re-hydrated with new provenance', () => {
    const base = mergeRenderedDocuments([], [docA])
    const updated = mergeRenderedDocuments(base, [
      { document_id: 'a', format: 'markdown', sources: [{ url: 'http://x.com/new', title: 'N' }], har_path: 'data/har/j2.har' },
    ])
    expect(updated).toHaveLength(1)
    expect(updated[0].sources).toEqual([{ url: 'http://x.com/new', title: 'N' }])
    expect(updated[0].harPath).toBe('data/har/j2.har')
  })
})
