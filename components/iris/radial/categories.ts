import { Mic, Palette, Activity } from "lucide-react"
import { IconRobot, IconTopologyStar3, IconBasketCog } from "@tabler/icons-react"
import type { ComponentType } from "react"

export interface CategoryNode {
  id: string
  label: string
  icon: ComponentType<{ size?: number; className?: string }>
}

/**
 * The 6 category nodes for the C-Random Rotate winner's radial arc.
 * Icons are a mix of tabler (IconRobot, IconTopologyStar3, IconBasketCog)
 * and lucide (Mic, Palette, Activity) — matching the MenuMockups prototype.
 */
export const CATEGORIES: CategoryNode[] = [
  { id: "voice",     label: "Voice",     icon: Mic },
  { id: "agent",     label: "Agent",     icon: IconRobot },
  { id: "automate",  label: "Automate",  icon: IconTopologyStar3 },
  { id: "system",    label: "System",    icon: IconBasketCog },
  { id: "customize", label: "Customize", icon: Palette },
  { id: "monitor",   label: "Monitor",   icon: Activity },
]
