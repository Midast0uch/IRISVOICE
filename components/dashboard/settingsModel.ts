// Pure helpers for the dashboard's settings rows: the one-line summary of a
// section's current values, the "find a setting" match, the segmented-control
// rule, and the change keys. No React, no state: the dashboard passes in the
// same field values the fields read.

export interface SettingsField {
  id: string
  label: string
  type: string
  options?: (string | { label: string; value: string })[]
  defaultValue?: unknown
  unit?: string
  description?: string
  showIf?: { field: string; values: (string | boolean)[] }
}

export interface SettingsSection {
  id: string
  label: string
  fields: SettingsField[]
}

export type SectionValues = Record<string, unknown> | undefined

const MAX_SUMMARY_PARTS = 4
const MAX_TEXT_VALUE = 24
const SECRET = /key|secret|password/i

/** The current value of a field: what the field row reads. */
export function fieldValue(field: SettingsField, values: SectionValues): unknown {
  return values?.[field.id] ?? field.defaultValue ?? ''
}

/** A field with `showIf` hides while the field it depends on holds another value. */
export function isFieldVisible(field: SettingsField, values: SectionValues): boolean {
  if (!field.showIf || !values) return true
  const dep = values[field.showIf.field]
  // Only hide on an explicit value that does not match (undefined = not set yet = show).
  return dep === undefined || dep === null || field.showIf.values.includes(dep as string | boolean)
}

const optionLabel = (field: SettingsField, value: unknown): string => {
  for (const o of field.options ?? []) {
    if (typeof o === 'string') { if (o === value) return o }
    else if (o.value === value) return o.label
  }
  return String(value)
}

/** One short piece of a section summary, or null when the field says nothing to read. */
export function fieldSummary(field: SettingsField, value: unknown): string | null {
  switch (field.type) {
    case 'toggle': {
      const name = field.label.toLowerCase().split(/\s+/).slice(0, 2).join(' ')
      return `${name} ${value ? 'on' : 'off'}`
    }
    case 'slider': {
      const n = Number(value)
      return Number.isFinite(n) ? `${Math.round(n)}${field.unit ?? ''}` : null
    }
    case 'dropdown':
      return value === '' || value == null ? null : optionLabel(field, value)
    case 'text': {
      if (SECRET.test(field.id) || value === '' || value == null) return null
      const s = String(value)
      return s.length > MAX_TEXT_VALUE ? `${s.slice(0, MAX_TEXT_VALUE - 1)}…` : s
    }
    default:
      return null // button, section header, custom panel
  }
}

/** The one-line summary of a section's current values. */
export function sectionSummary(fields: SettingsField[], values: SectionValues): string {
  const parts: string[] = []
  for (const f of fields) {
    if (parts.length >= MAX_SUMMARY_PARTS) break
    if (!isFieldVisible(f, values)) continue
    const s = fieldSummary(f, fieldValue(f, values))
    if (s) parts.push(s)
  }
  return parts.join(' · ')
}

/** "Find a setting": a section matches by its name or by any field label. Case-insensitive. */
export function sectionMatches(section: SettingsSection, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return false
  return section.label.toLowerCase().includes(q) || section.fields.some((f) => f.label.toLowerCase().includes(q))
}

/** A small, fixed enum reads best as a segmented control (concept `.sg`). */
export function isSegmented(field: SettingsField, dynamicOptions: boolean): boolean {
  if (field.type !== 'dropdown' || dynamicOptions) return false
  const opts = (field.options ?? []).map((o) => (typeof o === 'string' ? o : o.label))
  return opts.length >= 2 && opts.length <= 3 && opts.every((l) => l.length <= 12)
}

/** The change key of one field. Section ids never contain a dot. */
export const changeKey = (sectionId: string, fieldId: string) => `${sectionId}.${fieldId}`
export const changeSection = (key: string) => key.slice(0, key.indexOf('.'))

/**
 * The fields the user changed since the last Apply, as a list of change keys.
 * `pristine` holds each field's value from before its first edit since Apply; a
 * field is changed only while its current value differs from that. A value never
 * set reads as the field's default, the way the field row reads it.
 */
export function changedKeys(
  pristine: Record<string, unknown>,
  values: Record<string, Record<string, unknown> | undefined>,
  defaults: Record<string, unknown> = {},
): string[] {
  return Object.keys(pristine).filter((k) => {
    const dot = k.indexOf('.')
    const now = values[k.slice(0, dot)]?.[k.slice(dot + 1)] ?? defaults[k] ?? ''
    const before = pristine[k] ?? defaults[k] ?? ''
    return !Object.is(now, before)
  })
}

// Custom panels that are lists or tables of their own (the approved-tools list, the
// learned skills). A section holding one is not a group of plain fields.
const PANEL_CUSTOM_IDS = new Set(['skills_list', 'permissions_settings'])

/**
 * The row pattern (orb, name, summary, lit hairline) is only for a group of plain
 * setting fields: selects, toggles, sliders, text. Anything else (model routing,
 * tool and skill lists) is a pane with its own layout and a small mono header.
 */
export function isPlainFieldSection(section: SettingsSection): boolean {
  if (section.id === 'model_inference') return false
  return !section.fields.some((f) => f.type === 'custom' && PANEL_CUSTOM_IDS.has(f.id))
}
