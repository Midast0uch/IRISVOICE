import type { CSSProperties } from "react"
import type { Palette } from "@/lib/brandPalette"

/** The concept's brand tokens (--b1..--b3), set on an overlay so the .iris-hd-* classes can use them. */
export const brandVars = (p: Palette): CSSProperties =>
  ({ "--b1": p[0], "--b2": p[1], "--b3": p[2] }) as CSSProperties
