/**
 * Mycelium Network Task & Execution Types
 * Inspired by biological fungal mycelium: Hyphae (filaments), Spores (nodes),
 * Nutrients (data blocks), Branching (sub-loops/swarm), and Crystallization (landmarks).
 */

export type MyceliumPhaseState = "EXPAND" | "COMPRESS" | "STABLE"

export type NodeEnergyState =
  | "dormant"       // Queued in hypha network (○)
  | "pulsing"       // Actively executing / energized (Xur particle orbit)
  | "crystallized"  // Completed & permanently anchored as landmark (● emerald)
  | "fused"         // Completed & merged into main stem (● cyan/blue)
  | "rerouted"      // Avoided obstacle / diverted hypha (● amber)
  | "wilted"        // Failed / dead-end branch (✖ rose)

export type ActionFamily = "io" | "network" | "exec" | "reasoning" | "swarm" | "system"

export interface ActionMetadata {
  verb: string
  target?: string
  family: ActionFamily
  rawToolName?: string
}

export interface NutrientBlock {
  id: string
  label: string          // e.g. "AST-Tree", "Web-Crawl", "Patch-Diff"
  summary: string        // e.g. "14 interfaces, 3 classes exported"
  format?: string
}

export interface MyceliumNode {
  id: string
  verb: string           // e.g. "read", "patch", "crawl", "exec", "synthesize"
  target: string         // e.g. "components/chat-view.tsx", "docs.astral.sh"
  state: NodeEnergyState
  durationMs?: number
  
  // ── Hypha Connections & Branching ──
  branchId?: string      // If node belongs to a parallel hypha branch (Sub-Loop or Swarm)
  branchLabel?: string   // e.g. "Crawler Branch" or "Sub-Loop #2"
  dependsOnNodeId?: string // Upstream node feeding this spore
  nutrientOut?: NutrientBlock // Output nutrient produced by this node
  
  // Dynamic live progress
  liveDetail?: string    // e.g. "parsing tokens 120/450..."
  errorReason?: string   // If wilted or rerouted
}

export interface HyphaBranch {
  branchId: string
  label: string          // e.g. "AST-Explorer" or "Sub-Loop: Retry Patch"
  sporeColor: string     // Color tint of this hypha filament
  isActive: boolean
  isSwarm?: boolean      // Whether driven by parallel swarm worker
}

export interface MyceliumTaskState {
  taskId: string
  turnId?: string
  objective: string      // The root goal (e.g. "Refactor Task Progress to Mycelium Network")
  
  // ── Living Network Graph ──
  nodes: MyceliumNode[]
  branches: HyphaBranch[]
  
  // ── Thinking / Spore Nucleus ──
  isThinking: boolean
  currentThought: string // Live streaming thought filament
  thoughtHistory: string // Accumulated reasoning trace
  
  // ── Caducean Energy & RL Dynamics (Biological Effects) ──
  phaseState: MyceliumPhaseState // EXPAND (wide breathing) vs COMPRESS (tight focus)
  hasCrystallized: boolean       // Permanent landmark captured
  hasRerouted: boolean           // Avoided an obstacle
  energyPulseSpeed: number       // Xur nucleus speed (0.6 - 2.5)
  
  createdAt: number
  completedAt?: number
}

export interface CLIFormatOptions {
  useColor?: boolean
  verbosity?: "compact" | "normal" | "detailed"
  showThinking?: boolean
  width?: number
}
