// IRIS shared type definitions
// Domain 14 — CLI Toolkit + Web Crawler
// All types consumed by: ConversationChips, DashboardRenderer, dashboard-wing, chat-view, WS hooks

// ── Tab System ────────────────────────────────────────────────────────────────
export type TabType = 'code' | 'web' | 'html' | 'dashboard'

export interface Tab {
  id: string                     // UUID, stable across open_tab updates
  type: TabType
  title: string
  data?: DashboardData           // 'dashboard' tabs
  url?: string                   // 'web' tabs — iframe src
  content?: string               // 'code' | 'html' tabs — raw content
  language?: string              // 'code' tabs — syntax highlight hint (e.g. "python", "tsx")
  modifiedThisSession?: boolean  // 'code' tabs — show amber dot indicator
}

// ── Dashboard Data Schema ─────────────────────────────────────────────────────
export interface DashboardData {
  title: string
  query: string
  timestamp: string              // ISO 8601
  summary: string                // 1-2 sentences shown below header
  crawled_pages: number          // for footer "Crawled N pages"
  duration_ms: number            // for footer "Xms"
  sections: DashboardSection[]
  pin_id?: string                // set after PiN is anchored — enables ★ Save
}

export type DashboardSection =
  | MetricsSection
  | TableSection
  | CardsSection
  | ChartSection

export interface MetricsSection {
  type: 'metrics'
  items: MetricItem[]
}
export interface MetricItem {
  label: string
  value: string
  delta?: string                 // e.g. "+12%" or "-3 points"
  trend?: 'up' | 'down' | 'flat'
}

export interface TableSection {
  type: 'table'
  title?: string
  headers: string[]
  rows: string[][]
}

export interface CardsSection {
  type: 'cards'
  title?: string
  items: CardItem[]
}
export interface CardItem {
  title: string
  subtitle?: string
  body: string
  url?: string
  tag?: string
}

export interface ChartSection {
  type: 'chart'
  title?: string
  chart_type: 'bar' | 'line' | 'pie'
  labels: string[]
  datasets: { label: string; values: number[] }[]
}

// ── Conversation Chips ────────────────────────────────────────────────────────
// Populated from existing ChatView messages state (sender === 'user').
// No backend. No LLM. Pure front-end history navigation.
export interface ConversationChip {
  messageId: string              // matches message.id in ChatView
  label: string                  // first 30 chars of message.text, truncated with …
  index: number                  // sequential position in thread (0 = first)
}

// ── Developer Mode State ──────────────────────────────────────────────────────
export interface DevModeState {
  isDevMode: boolean
  workDir: string
  activeTool: string | null
  model: string
}

// ── Crawler Status ────────────────────────────────────────────────────────────
export type CrawlerState = 'idle' | 'planning' | 'crawling' | 'extracting'
export interface CrawlerStatus {
  state: CrawlerState
  urlCount: number
  pagesDone: number
}

// ── File Activity (developer mode only) ──────────────────────────────────────
export type FileChangeType = 'edit' | 'create' | 'delete'
export interface FileActivityEvent {
  path: string
  change: FileChangeType
  timestamp: number              // Date.now()
}

// ── WebSocket Message Shapes (server → client) ───────────────────────────────
export interface CrawlerStartedMsg {
  type: 'crawler_started'
  query: string
  url_count: number
}
export interface CrawlerPageMsg {
  type: 'crawler_page_fetched'
  url: string
  page_number: number
  total: number
}
export interface OpenTabMsg {
  type: 'open_tab'
  tab_type: TabType
  id: string
  title: string
  data?: DashboardData
  url?: string
  content?: string
  language?: string
}
export interface CloseTabMsg {
  type: 'close_tab'
  id: string
}
export interface CrawlerErrorMsg {
  type: 'crawler_error'
  message: string
}
export interface CliActivityMsg {
  type: 'cli_activity'
  tool_name: string
  workdir: string
}
export interface CliStartedMsg {
  type: 'cli_started'
  tool_name: string
  proc_id: string
}
export interface CliOutputMsg {
  type: 'cli_output'
  line: string
  proc_id: string
}
export interface FileActivityMsg {
  type: 'file_activity'
  path: string
  change: FileChangeType
}
