/**
 * The one-line meta of an artifact card: "kind · size/rows · time". Pure.
 * Only what the document really carries: no size for an image, no time for a
 * document that came back from history without one.
 */
export interface MetaDoc {
  format: string
  content: string
  title?: string
  /** ms since epoch the card was made or last updated (live cards only). */
  createdAt?: number
}

const KIND: Record<string, string> = {
  markdown: "document",
  text: "text",
  html: "page",
  table: "table",
  diagram: "diagram",
  json: "data",
  image: "image",
}

export function artifactKind(format: string): string {
  return KIND[format] || "document"
}

function tableRows(content: string): number | null {
  try {
    const v = JSON.parse(content)
    if (Array.isArray(v)) return v.length
    if (v && Array.isArray((v as { rows?: unknown[] }).rows)) return (v as { rows: unknown[] }).rows.length
  } catch {
    /* not JSON: a markdown table */
  }
  const lines = content.split("\n").filter((l) => /^\s*\|/.test(l))
  return lines.length ? Math.max(0, lines.length - 2) : null
}

export function artifactSize(doc: MetaDoc): string | null {
  const c = doc.content || ""
  if (!c.trim() || doc.format === "image") return null
  if (doc.format === "table") {
    const n = tableRows(c)
    return n === null ? null : `${n} row${n === 1 ? "" : "s"}`
  }
  if (doc.format === "html" || doc.format === "json") {
    const kb = c.length / 1024
    return kb < 1 ? `${c.length} B` : `${kb < 10 ? kb.toFixed(1) : Math.round(kb)} KB`
  }
  const words = c.trim().split(/\s+/).length
  return `${words} word${words === 1 ? "" : "s"}`
}

export function relativeTime(at: number | undefined, now: number = Date.now()): string | null {
  if (typeof at !== "number" || !Number.isFinite(at)) return null
  const s = Math.max(0, Math.round((now - at) / 1000))
  if (s < 45) return "just now"
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h} h ago`
  return new Date(at).toLocaleDateString()
}

export function artifactMeta(doc: MetaDoc, now?: number): string {
  return [artifactKind(doc.format), artifactSize(doc), relativeTime(doc.createdAt, now)].filter(Boolean).join(" · ")
}
