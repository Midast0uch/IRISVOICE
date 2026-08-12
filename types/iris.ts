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
  // REQ-1 (T5): agent-navigated web tabs replay the captured bytes instead of
  // a second live fetch. Set from `crawler_page_fetched` (job_id, page_number).
  captureJobId?: string          // job_id of the crawl that fetched this page
  capturePageNumber?: number     // page_number within that crawl
  captureFetchedAt?: string      // ISO timestamp (provenance, REQ-1 AC4)
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
  /** The PLANNED source set, not just its size — the plan card shows the user
   * which sources the agent intends to read before it reads them. Optional: the
   * user-initiated path and older emitters send only url_count. */
  urls?: string[]
  /** Subset of `urls` that came from vision discovery rather than the planner. */
  discovered_urls?: string[]
  session_id?: string
}
/** Sources ADDED mid-run — a broadened re-plan, or URLs the vision model found
 * by typing a query into a search engine. The plan card must APPEND these; the
 * planned set at CRAWLER_STARTED is not final. */
export interface CrawlerSourcesAddedMsg {
  type: 'crawler_sources_added'
  job_id?: string
  urls: string[]
  discovered_urls?: string[]
  query?: string
  reason?: string
}
export interface CrawlerPageMsg {
  type: 'crawler_page_fetched'
  url: string
  page_number: number
  total: number
  host?: string
  /** REQ-11 (T13): crawl provenance — lets the panel replay the captured bytes
   * (/api/browser/capture/{job_id}/{capture_page}). Sent by the agent-path WS
   * emitter (tool_bridge._crawl_ui_emitter); absent on the user-initiated path. */
  job_id?: string
  /** The capture-store ADDRESS the bytes were saved under — NOT `page_number`.
   * page_number is the run's progress counter ("reading 3 of 5"); the address is
   * where the page lives. They diverge under per-URL dispatch (each single-URL
   * fetch numbers its only page 1) and under vision escalation (many frames for
   * one URL), and building the iframe src from the counter is what made every
   * replay 404. Falls back to page_number when absent (the batch path, where the
   * two genuinely coincide). */
  capture_page?: number
  /** False when the bytes were deliberately NOT stored — a bot-challenge
   * interstitial is not persisted (REQ-4 AC2), so its frame can only 404. The
   * panel must render a "blocked by the site" state instead of a dead iframe. */
  capture_available?: boolean
  title?: string
}
/** REQ-11/12 (T17): in-flight stage message (stage: narrowing/refining/fetching). */
export interface CrawlerProgressMsg {
  type: 'crawler_progress'
  stage: string
  message: string
}
/** REQ-4/12 (T17): structured phase label from the crawl pipeline
 * (searching / extracting / citing). NOTE: the SSE transport maps the phase
 * event to msg_type `task:event` (ux_map.py CRAWLER_PHASE), so the frontend
 * also accepts that name — see useCrawl's `iris:task:event` listener. */
export interface CrawlerPhaseMsg {
  type: 'crawler_phase'
  phase: string
  phase_sequence: number
}
/** REQ-11 AC4 (T17): vision performed an action on a page — panel annotation.
 * REQ-16 AC7: OPTIONAL best-effort cursor coordinates for the frontend
 * particle-trail cursor mirror, reconstructed server-side from the Playwright
 * DOM target's bounding box (backend/vision/browser_session.py
 * `_capture_action_point`) — the vision model itself has no mouse and never
 * sees these; they exist purely for the panel overlay. click/type carry
 * x/y (normalised 0..1 fractions of the viewport) + viewport_w/viewport_h;
 * scroll carries scroll_dx/scroll_dy instead of a point (a point would drift
 * as the page scrolls under it). Absent when the bounding box could not be
 * read (best-effort — never blocks the action) or for actions with no
 * cursor-relevant point (navigate/reload/back/forward/wait). */
export interface CrawlerVisionActionMsg {
  type: 'crawler_vision_action'
  job_id: string
  url: string
  kind: string
  reason: string
  action_index: number
  total: number
  x?: number
  y?: number
  viewport_w?: number
  viewport_h?: number
  scroll_dx?: number
  scroll_dy?: number
}
/** REQ-13 AC4 (T17): a walled source was parked (non-blocking ask). The design
 * doc shape is {job_id, url, wall, question_id}; the orchestrator emits
 * {url, domain, wall_kind, run_id, question_id} — accept both spellings. */
export interface CrawlerSourceParkedMsg {
  type: 'crawler_source_parked'
  url: string
  domain?: string
  wall?: string
  wall_kind?: string
  question_id?: string
  job_id?: string
  run_id?: string
}
/** REQ-31 edge / T23: event-log TTL eviction — client must full-snapshot sync. */
export interface CrawlerSyncRequiredMsg {
  type: 'crawler_sync_required'
  session_id: string
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
  /** REQ-11 (T13): crawl provenance so the panel can link a content tab to
   * its capture bytes (/api/browser/capture/{job_id}/{page_number}). */
  job_id?: string
}
export interface CloseTabMsg {
  type: 'close_tab'
  id: string
}
export interface CrawlerErrorMsg {
  type: 'crawler_error'
  message: string
}
export interface CrawlerCompleteMsg {
  type: 'crawler_complete'
  query: string
  summary: string
  cited_markdown?: string
  credibility_top_score?: number
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

// ── Suggestion Pills ──────────────────────────────────────────────────────────
export interface Suggestion {
  message: string
  label?: string
  icon?: string
}
