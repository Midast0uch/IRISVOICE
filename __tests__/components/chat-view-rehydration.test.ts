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
