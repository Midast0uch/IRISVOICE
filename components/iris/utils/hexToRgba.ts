/**
 * Convert a hex color string to an rgba() string with the given alpha.
 *
 * Extracted from components/preview/MenuMockups.tsx (line 1296) so that
 * production components (RadialArcNodes, HexNode, etc.) can share the
 * same helper without importing the entire preview mockup file.
 *
 * @param hex   Hex color, e.g. "#00d4ff"
 * @param alpha Opacity 0–1
 */
export function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r},${g},${b},${alpha})`
}
