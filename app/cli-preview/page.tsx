'use client'

import React, { useState, useRef } from 'react'

// ─── Inline SVG Icons ───
const WebIcon = ({ on }: { on: boolean }) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <line x1="2" y1="12" x2="22" y2="12" />
    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
    {!on && <line x1="4" y1="4" x2="20" y2="20" stroke="currentColor" strokeWidth="2.5" />}
  </svg>
)

const UploadIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="17 8 12 3 7 8" />
    <line x1="12" y1="3" x2="12" y2="15" />
  </svg>
)

const FolderIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
  </svg>
)

const FileIcon = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
  </svg>
)

const PlusIcon = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="5" y1="12" x2="19" y2="12" />
  </svg>
)

const ArchiveIcon = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="21 8 21 21 3 21 3 8" />
    <rect x="1" y="3" width="22" height="5" />
    <line x1="10" y1="12" x2="14" y2="12" />
  </svg>
)

const ChevronIcon = ({ up }: { up: boolean }) => (
  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    {up ? <polyline points="18 15 12 9 6 15" /> : <polyline points="6 9 12 15 18 9" />}
  </svg>
)

const BellIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
    <path d="M13.73 21a2 2 0 0 1-3.46 0" />
  </svg>
)

const HistoryIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 3v5h5" />
    <path d="M3.05 13A9 9 0 1 0 6 5.3L3 8" />
    <path d="M12 7v5l4 2" />
  </svg>
)

const DashboardIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="20" x2="18" y2="10" />
    <line x1="12" y1="20" x2="12" y2="4" />
    <line x1="6" y1="20" x2="6" y2="14" />
  </svg>
)

const CloseIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
)

const AlignJustifyIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="21" y1="10" x2="3" y2="10" />
    <line x1="21" y1="6" x2="3" y2="6" />
    <line x1="21" y1="14" x2="3" y2="14" />
    <line x1="21" y1="18" x2="3" y2="18" />
  </svg>
)

// Dashboard Rail Category Icons
const MicIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
    <line x1="12" y1="19" x2="12" y2="23" />
    <line x1="8" y1="23" x2="16" y2="23" />
  </svg>
)

const BotIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="11" width="18" height="10" rx="2" />
    <circle cx="12" cy="5" r="2" />
    <path d="M12 7v4" />
    <line x1="8" y1="16" x2="8" y2="16" />
    <line x1="16" y1="16" x2="16" y2="16" />
  </svg>
)

const NetworkIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="5" r="3" />
    <circle cx="5" cy="19" r="3" />
    <circle cx="19" cy="19" r="3" />
    <line x1="12" y1="8" x2="5" y2="16" />
    <line x1="12" y1="8" x2="19" y2="16" />
  </svg>
)

const CogIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
)

const PaletteIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="13.5" cy="6.5" r="0.5" fill="currentColor" />
    <circle cx="17.5" cy="10.5" r="0.5" fill="currentColor" />
    <circle cx="8.5" cy="7.5" r="0.5" fill="currentColor" />
    <circle cx="6.5" cy="12.5" r="0.5" fill="currentColor" />
    <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z" />
  </svg>
)

const ActivityIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
  </svg>
)

const GlobeIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <line x1="2" y1="12" x2="22" y2="12" />
    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
  </svg>
)

const ShoppingBagIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" />
    <line x1="3" y1="6" x2="21" y2="6" />
    <path d="M16 10a4 4 0 0 1-8 0" />
  </svg>
)

const WorkspaceHubIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="7" height="9" />
    <rect x="14" y="3" width="7" height="5" />
    <rect x="14" y="12" width="7" height="9" />
    <rect x="3" y="16" width="7" height="5" />
  </svg>
)

const GLOW = '#00d4ff'
const BG = '#0b0c1a'
const FONT = '#e5e5e5'

// ─── Glassmorphic Button Styling ───
const glassButtonBase: React.CSSProperties = {
  background: 'linear-gradient(135deg, rgba(5,5,12,0.9) 0%, rgba(12,12,20,0.85) 100%)',
  border: `1px solid ${FONT}80`,
  borderRadius: '9999px',
  boxShadow: `0 1px 8px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)`,
}

const glassButtonActive = (glow: string): React.CSSProperties => ({
  ...glassButtonBase,
  border: `1px solid ${glow}`,
  boxShadow: `0 0 12px ${glow}40, inset 0 1px 0 rgba(255,255,255,0.03)`,
  color: glow,
})

// ─── Real Blueprint Matrix Unicode Generator ───
interface TaskItem {
  objective: string
  thinking: string
  steps: {
    status: 'done' | 'running' | 'crystallized' | 'pending'
    verb: string
    target: string
    summary?: string
    branchLabel?: string
  }[]
  isCrystallized?: boolean
  memoryRecalled?: string
}

function renderBlueprintMatrixUnicode(task: TaskItem) {
  const border = '─'.repeat(54)
  return (
    <div className="font-mono text-[11px] leading-[17px] my-2 select-text overflow-x-auto whitespace-pre rounded bg-[#070814]/90 p-2.5 border border-cyan-500/20 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
      <div className="text-cyan-400">┌{border}┐</div>
      <div className="text-cyan-400 flex items-center gap-2">
        <span>│</span>
        <span className="font-bold text-cyan-300">TASK :</span>
        <span className="font-semibold text-white/95">{task.objective}</span>
      </div>
      {task.thinking && (
        <div className="text-cyan-400 flex items-center gap-2">
          <span>│</span>
          <span className="font-bold text-amber-300">THK  :</span>
          <span className="italic text-white/60">{task.thinking}</span>
        </div>
      )}
      <div className="text-cyan-400">├{border}┤</div>
      {task.steps.map((step, idx) => {
        const isLast = idx === task.steps.length - 1
        const rail = isLast ? ' ' : '┊'
        let orb = '○'
        let orbClass = 'text-white/30'
        let verbClass = 'text-white/90'

        if (step.status === 'running') {
          orb = '◎'
          orbClass = 'text-amber-300 font-bold animate-pulse'
          verbClass = 'text-amber-300 font-bold'
        } else if (step.status === 'done') {
          orb = '●'
          orbClass = 'text-cyan-300 font-bold'
          verbClass = 'text-cyan-300 font-bold'
        } else if (step.status === 'crystallized') {
          orb = '✦'
          orbClass = 'text-emerald-400 font-bold'
          verbClass = 'text-emerald-400 font-bold'
        }

        if (step.branchLabel) {
          return (
            <div key={idx} className="space-y-0.5">
              <div className="text-cyan-400 flex items-center gap-1.5">
                <span>│</span>
                <span className="text-white/20">┊</span>
                <span className="text-cyan-400">┌┄┄</span>
                <span className="text-purple-400 font-bold">↳ [{step.branchLabel}]</span>
                <span className="text-white/20">┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐</span>
              </div>
              <div className="text-cyan-400 flex items-center gap-2">
                <span>│</span>
                <span className="text-white/20">┊ ┊</span>
                <span className={orbClass}>{orb}</span>
                <span className={`${verbClass} w-14 inline-block`}>{step.verb.toUpperCase().padEnd(6)}</span>
                <span className="text-white/80">{step.target}</span>
              </div>
              {step.summary && (
                <div className="text-cyan-400 flex items-center gap-2">
                  <span>│</span>
                  <span className="text-white/20">┊ ┊</span>
                  <span className="text-white/40 pl-4">└─ {step.summary}</span>
                </div>
              )}
              <div className="text-cyan-400 flex items-center gap-1.5">
                <span>│</span>
                <span className="text-white/20">┊</span>
                <span className="text-white/20">└┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘</span>
              </div>
            </div>
          )
        }

        return (
          <div key={idx} className="space-y-0.5">
            <div className="text-cyan-400 flex items-center gap-2">
              <span>│</span>
              <span className="text-white/20">┊</span>
              <span className={orbClass}>{orb}</span>
              <span className={`${verbClass} w-14 inline-block`}>{step.verb.toUpperCase().padEnd(6)}</span>
              <span className="text-white/80">{step.target}</span>
            </div>
            {step.summary && (
              <div className="text-cyan-400 flex items-center gap-2">
                <span>│</span>
                <span className="text-white/20">{rail}</span>
                <span className="text-white/40 pl-4">└─ {step.summary}</span>
              </div>
            )}
            {!isLast && (
              <div className="text-cyan-400 flex items-center gap-2">
                <span>│</span>
                <span className="text-white/20">┊</span>
              </div>
            )}
          </div>
        )
      })}
      <div className="text-cyan-400">├{border}┤</div>
      <div className="text-cyan-400 flex items-center gap-2">
        <span>│</span>
        <span className="font-bold text-emerald-400">✦ CONVERGED</span>
      </div>
      <div className="text-cyan-400 flex items-center gap-2 text-[10px]">
        <span>│</span>
        <span className="text-emerald-300/80">Skill crystallized into data/memory.db (skills)</span>
      </div>
      {task.memoryRecalled && (
        <div className="text-cyan-400 flex items-center gap-2 text-[10px]">
          <span>│</span>
          <span className="text-white/40">{task.memoryRecalled}</span>
        </div>
      )}
      <div className="text-cyan-400">└{border}┘</div>
    </div>
  )
}

// ─── Main Preview Page ───
export default function CLIPreviewPage() {
  const [inputText, setInputText] = useState('')
  const [webMode, setWebMode] = useState(false)
  const [isInputFocused, setIsInputFocused] = useState(false)
  const [showModelMenu, setShowModelMenu] = useState(false)
  const [selectedModel, setSelectedModel] = useState('o4-mini')
  const [activeTab, setActiveTab] = useState<'workspace' | 'src/auth.ts'>('workspace')
  const [showArchive, setShowArchive] = useState(true)
  const [showChipsPopover, setShowChipsPopover] = useState(false)
  const [uploadHovered, setUploadHovered] = useState(false)

  // Navigation rail dual-mode & expansion state
  const [railMode, setRailMode] = useState<'surfaces' | 'settings'>('surfaces')
  const [isRailExpanded, setIsRailExpanded] = useState(true)
  const [activeSubApp, setActiveSubApp] = useState<string | null>('workspace')
  const [activeSettingsTab, setActiveSettingsTab] = useState('voice')
  const [focusPreset, setFocusPreset] = useState<'full' | 'active' | 'project' | 'compact'>('full')
  const [isHoveringBoundary, setIsHoveringBoundary] = useState(false)

  const [archivedCards] = useState([
    { id: '1', label: 'auth-tokens.ts', type: 'file' },
    { id: '2', label: 'ws-test.ts', type: 'file' },
    { id: '3', label: 'middleware.py', type: 'file' },
  ])

  const conversationTurns = [
    { messageId: 'turn-1', label: '1. Refactor auth middleware' },
    { messageId: 'turn-2', label: '2. Run test suite verification' },
    { messageId: 'turn-3', label: '3. Fix WebSocket token backoff' },
  ]

  const inputRef = useRef<HTMLTextAreaElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const sampleTask: TaskItem = {
    objective: 'Implement WebSocket Audio Streaming Resilience',
    thinking: 'Checking FastAPI disconnect lifecycle & backoff parameters...',
    steps: [
      { status: 'done', verb: 'READ', target: 'src-tauri/src/ws_client.rs', summary: 'Verified tokio reconnect backoff' },
      { status: 'done', verb: 'PATCH', target: 'hooks/useIRISWebSocket.ts', summary: 'Applied event listener deduplication' },
      {
        status: 'done',
        verb: 'SEARCH',
        target: 'FastAPI WebSocket disconnect handlers',
        summary: 'Found 3 connection lifecycle patterns',
        branchLabel: 'Sub-Loop: Docs'
      },
      { status: 'running', verb: 'EXEC', target: 'pytest tests/test_ws_resilience.py' },
    ],
    isCrystallized: true,
    memoryRecalled: 'Retrieved 2 past episodes for WebSocket reconnects',
  }

  const models = ['o4-mini', 'gpt-4o', 'claude-3-7-sonnet', 'cerebras:llama-3.3-70b', 'local:bonsai-27B']

  // Dual-Mode Surface Hubs (with Live Telemetry Badges)
  const SURFACES = [
    {
      id: 'workspace',
      label: 'Workspace Hub',
      icon: WorkspaceHubIcon,
      badge: '● 2 Running',
      badgeColor: '#f59e0b',
      title: 'Multi-Agent Kanban & Workspace Canvas'
    },
    {
      id: 'browser',
      label: 'Browser Surface',
      icon: GlobeIcon,
      badge: '● Live Web',
      badgeColor: '#00d4ff',
      title: 'Sandboxed Browser & Web Search Replay'
    },
    {
      id: 'marketplace',
      label: 'Market & Models',
      icon: ShoppingBagIcon,
      badge: '● 12 Tools',
      badgeColor: '#10b981',
      title: 'MCP Registry & Local Model Manager'
    },
  ]

  // Dual-Mode Category Settings (MAIN_NODES_DATA)
  const SETTINGS_NODES = [
    { id: 'voice', label: 'Voice Engine', icon: MicIcon },
    { id: 'agent', label: 'Agent Settings', icon: BotIcon },
    { id: 'automate', label: 'Automations', icon: NetworkIcon },
    { id: 'system', label: 'System / Hardware', icon: CogIcon },
    { id: 'customize', label: 'Customize Theme', icon: PaletteIcon },
    { id: 'monitor', label: 'Diagnostics', icon: ActivityIcon },
  ]

  const scrollToTurn = (turnId: string) => {
    setShowChipsPopover(false)
    if (scrollRef.current) {
      scrollRef.current.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }

  const cycleFocus = () => {
    const presets: ('full' | 'active' | 'project' | 'compact')[] = ['full', 'active', 'project', 'compact']
    const next = presets[(presets.indexOf(focusPreset) + 1) % presets.length]
    setFocusPreset(next)
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6" style={{ background: '#050510' }}>
      <div className="flex gap-6 items-start max-w-[1360px] w-full">

        {/* ══════════════════════════════════════════════════════════════════════════
            LEFT WING: DEVELOPER CLI CHATVIEW
            ══════════════════════════════════════════════════════════════════════════ */}
        <div
          className="relative flex flex-col overflow-hidden flex-shrink-0"
          style={{
            width: 510,
            height: '88vh',
            maxHeight: 'calc(100vh - 48px)',
            borderRadius: 12,
            background: `linear-gradient(135deg, rgba(10,11,22,0.97) 0%, rgba(6,7,14,0.99) 100%)`,
            border: `1px solid ${GLOW}20`,
            boxShadow: `
              inset 0 1px 1px rgba(255,255,255,0.05),
              inset 0 -1px 1px rgba(0,0,0,0.5),
              0 0 0 1px rgba(0,0,0,0.8),
              20px 0 60px rgba(0,0,0,0.5)
            `,
          }}
        >
          {/* Header */}
          <div
            className="flex items-center justify-between px-3 flex-shrink-0 relative z-30"
            style={{
              height: 44,
              borderBottom: `1px solid rgba(255,255,255,0.06)`,
              background: 'rgba(0,0,0,0.35)',
            }}
          >
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full" style={{ background: GLOW, boxShadow: `0 0 6px ${GLOW}` }} />
              <span className="text-[13px] font-bold tracking-wider" style={{ color: FONT }}>IRIS <span className="text-[9px] font-mono font-normal opacity-60">CLI</span></span>
              <button
                className="p-1 rounded-md transition-all"
                style={{ color: 'rgba(255,255,255,0.7)', background: `${GLOW}10`, border: `1px solid ${GLOW}20` }}
                title="Toggle Dashboard Companion"
              >
                <DashboardIcon />
              </button>
            </div>
            <div className="flex items-center gap-1">
              <button className="p-1.5 rounded transition-all text-white/60 hover:text-white"><BellIcon /></button>
              <button className="p-1.5 rounded transition-all text-white/60 hover:text-white"><HistoryIcon /></button>
              <button className="p-1.5 rounded transition-all text-white/60 hover:text-white"><CloseIcon /></button>
            </div>
          </div>

          {/* Project Folder Bar */}
          <div
            className="flex items-center justify-between px-2.5 py-1 flex-shrink-0"
            style={{
              background: 'rgba(255,255,255,0.02)',
              borderBottom: `1px solid ${GLOW}15`,
              height: 30,
            }}
          >
            <div className="flex items-center gap-1.5 overflow-x-auto scrollbar-hide">
              <button
                onClick={() => setActiveTab('workspace')}
                className="flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-medium transition-all"
                style={{
                  background: activeTab === 'workspace' ? `${GLOW}20` : 'rgba(255,255,255,0.03)',
                  border: `1px solid ${activeTab === 'workspace' ? `${GLOW}40` : 'rgba(255,255,255,0.06)'}`,
                  color: activeTab === 'workspace' ? GLOW : 'rgba(255,255,255,0.5)',
                }}
              >
                <FolderIcon />
                <span>IRISVOICE</span>
              </button>
              <button
                onClick={() => setActiveTab('src/auth.ts')}
                className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium transition-all"
                style={{
                  background: activeTab === 'src/auth.ts' ? `${GLOW}20` : 'transparent',
                  border: `1px solid ${activeTab === 'src/auth.ts' ? `${GLOW}40` : 'transparent'}`,
                  color: activeTab === 'src/auth.ts' ? GLOW : 'rgba(255,255,255,0.4)',
                }}
              >
                <FileIcon />
                <span>auth.ts</span>
              </button>
              <button
                onClick={() => alert('Opens FilePickerModal')}
                className="p-1 rounded text-[10px] transition-all flex items-center justify-center"
                style={{ color: GLOW, background: `${GLOW}15`, border: `1px solid ${GLOW}30` }}
                title="Open new project folder or file"
              >
                <PlusIcon />
              </button>
            </div>
            <button
              onClick={() => setShowArchive(v => !v)}
              className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-mono transition-all"
              style={{
                color: showArchive ? GLOW : 'rgba(255,255,255,0.3)',
                background: showArchive ? `${GLOW}10` : 'transparent',
                border: `1px solid ${showArchive ? `${GLOW}25` : 'transparent'}`,
              }}
              title="Toggle Archive Dock"
            >
              <ArchiveIcon />
              <span>{archivedCards.length}</span>
            </button>
          </div>

          {/* Unified Scroll */}
          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto px-3 py-2 scrollbar-hide relative"
            style={{ background: BG }}
          >
            <div id="turn-1" className="mb-2.5">
              <div className="flex items-start gap-2">
                <span className="text-[10px] font-mono font-bold mt-0.5 text-cyan-400">iris@dev &gt;</span>
                <span className="text-[12px] text-white/90 font-mono">refactor auth middleware with resilient backoff</span>
              </div>
            </div>

            <div className="my-1">
              <div className="text-[10px] font-mono text-white/40 mb-1 flex items-center justify-between">
                <span>EXECUTION MATRIX (Unicode Blueprint)</span>
                <span className="text-cyan-400">⏱ 0:14</span>
              </div>
              {renderBlueprintMatrixUnicode(sampleTask)}
            </div>

            <div id="turn-2" className="my-2.5 font-mono text-[11px] bg-black/40 rounded p-2 border border-white/5">
              <div className="text-emerald-400 font-bold">$ pytest tests/test_ws_resilience.py</div>
              <div className="text-white/60 leading-[18px]">
                tests/test_ws_resilience.py::test_reconnect_backoff <span className="text-emerald-400">PASSED</span><br />
                tests/test_ws_resilience.py::test_dedup_listeners <span className="text-emerald-400">PASSED</span><br />
                <span className="text-emerald-300 font-bold">2 passed in 0.84s</span>
              </div>
            </div>

            <div id="turn-3" className="mb-2">
              <span className="text-[10px] font-mono text-white/40 block mb-0.5">Assistant</span>
              <p className="text-[12px] text-white/90 leading-relaxed">
                Middleware patched with exponential backoff and deduplicated event listeners. All unit tests verified.
              </p>
            </div>
          </div>

          {/* Archive Dock */}
          {showArchive && (
            <div
              className="flex items-center gap-1.5 px-3 py-1 flex-shrink-0 overflow-x-auto"
              style={{
                background: 'rgba(0,0,0,0.5)',
                borderTop: `1px solid ${GLOW}15`,
                borderBottom: `1px solid rgba(255,255,255,0.04)`,
              }}
            >
              <div className="flex items-center gap-1 text-[9px] font-mono uppercase text-cyan-400/80 mr-1 flex-shrink-0">
                <ArchiveIcon />
                <span>Dock:</span>
              </div>
              {archivedCards.map((c) => (
                <button
                  key={c.id}
                  className="flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-mono text-white/60 hover:text-white bg-white/[0.04] hover:bg-white/[0.08] border border-white/10 transition-all flex-shrink-0"
                >
                  <FileIcon />
                  <span className="truncate max-w-[80px]">{c.label}</span>
                </button>
              ))}
            </div>
          )}

          {/* ═══ 5. ATTACHED FOOTER (Updated Order & Symmetrical Math Spacing) ═══
              Sequence: [Web: 32px] [Upload: 32px] | [Model: 116px] | [ConversationChips: 32px] [ContextPill: 174px]
              Enter icon removed to free full width for ContextPill. */}
          <div
            className="px-3 pb-3 pt-3.5 flex-shrink-0 relative z-30 border-t"
            style={{
              background: 'rgba(0,0,0,0.6)',
              borderColor: 'rgba(255,255,255,0.05)',
            }}
          >
            {/* Textarea Row */}
            <div className="relative mb-2">
              <textarea
                ref={inputRef}
                value={inputText}
                onChange={(e) => {
                  setInputText(e.target.value)
                  e.target.style.height = 'auto'
                  e.target.style.height = `${e.target.scrollHeight}px`
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    setInputText('')
                    if (inputRef.current) inputRef.current.style.height = 'auto'
                  }
                }}
                onFocus={() => setIsInputFocused(true)}
                onBlur={() => setIsInputFocused(false)}
                placeholder="Type command, /run, or ask IRIS…"
                rows={1}
                className="w-full bg-transparent border-0 py-1.5 px-1 text-[13px] focus:outline-none transition-all placeholder:text-white/30 resize-none min-h-[34px] max-h-[120px] scrollbar-hide"
                style={{
                  color: FONT,
                  borderBottomWidth: '1px',
                  borderColor: isInputFocused || inputText ? GLOW : `${GLOW}30`,
                  boxShadow: isInputFocused || inputText ? `0 1px 0 0 ${GLOW}` : 'none',
                }}
              />
            </div>

            {/* Horizontal Toolbar Row (Exact Math Spacing Across 486px Usable Width) */}
            <div
              className="flex items-center justify-between flex-shrink-0"
              style={{
                borderBottom: `1px solid ${inputText ? GLOW : `${GLOW}30`}`,
                paddingBottom: 2,
              }}
            >
              {/* Group 1: Tools (Web + Upload) = 72px */}
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  type="button"
                  onClick={() => setWebMode(v => !v)}
                  className="flex items-center justify-center w-[32px] h-[32px] transition-all flex-shrink-0"
                  style={webMode ? glassButtonActive(GLOW) : { ...glassButtonBase, color: 'rgba(255,255,255,0.5)' }}
                  title={webMode ? 'Web mode ON' : 'Web mode OFF'}
                >
                  <WebIcon on={webMode} />
                </button>

                <button
                  type="button"
                  onMouseEnter={() => setUploadHovered(true)}
                  onMouseLeave={() => setUploadHovered(false)}
                  className="flex items-center justify-center w-[32px] h-[32px] transition-all flex-shrink-0"
                  style={uploadHovered
                    ? { ...glassButtonBase, color: GLOW, boxShadow: `0 0 12px ${GLOW}30, inset 0 1px 0 rgba(255,255,255,0.03)` }
                    : { ...glassButtonBase, color: 'rgba(255,255,255,0.7)' }
                  }
                  title="Upload file"
                >
                  <UploadIcon />
                </button>
              </div>

              {/* Divider 1 */}
              <div className="flex-shrink-0 rounded-full" style={{ width: '1px', height: '20px', background: GLOW, opacity: 0.3 }} />

              {/* Group 2: Model Switcher = 116px */}
              <div className="relative flex-shrink-0" style={{ width: 116 }}>
                <button
                  type="button"
                  onClick={() => setShowModelMenu(v => !v)}
                  className="w-full flex items-center justify-between px-2.5 h-[32px] text-[11px] font-mono transition-all"
                  style={{
                    ...glassButtonBase,
                    borderRadius: '6px',
                    color: 'rgba(255,255,255,0.85)',
                    border: `1px solid ${showModelMenu ? GLOW : `${FONT}80`}`,
                  }}
                >
                  <div className="flex items-center gap-1.5 truncate">
                    <span className="text-cyan-400 font-bold text-[10px]">◈</span>
                    <span className="truncate">{selectedModel}</span>
                  </div>
                  <ChevronIcon up={showModelMenu} />
                </button>

                {showModelMenu && (
                  <div className="absolute bottom-full left-0 mb-2 rounded-lg overflow-hidden z-50 bg-[#0a0b16] border border-cyan-500/30 shadow-2xl min-w-[170px]">
                    {models.map((m) => (
                      <button
                        key={m}
                        onClick={() => { setSelectedModel(m); setShowModelMenu(false) }}
                        className="w-full text-left px-3 py-1.5 text-[11px] font-mono text-white/70 hover:text-cyan-300 hover:bg-cyan-500/10 transition-colors"
                      >
                        {m === selectedModel && <span className="text-cyan-400 mr-1">●</span>}
                        {m}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Divider 2 */}
              <div className="flex-shrink-0 rounded-full" style={{ width: '1px', height: '20px', background: GLOW, opacity: 0.3 }} />

              {/* Group 3: ConversationChips (Left of ContextPill) = 32px */}
              <div className="relative flex-shrink-0">
                <div
                  className="flex items-center justify-center w-[32px] h-[32px] flex-shrink-0 cursor-pointer"
                  style={{
                    ...glassButtonBase,
                    borderRadius: '6px',
                    color: showChipsPopover ? GLOW : 'rgba(255,255,255,0.75)',
                    border: `1px solid ${showChipsPopover ? GLOW : `${FONT}80`}`,
                  }}
                  onClick={() => setShowChipsPopover(v => !v)}
                  title="Navigate Conversation Turns (ConversationChips)"
                >
                  <AlignJustifyIcon />
                </div>

                {showChipsPopover && (
                  <div className="absolute bottom-full right-0 mb-2 w-56 rounded-lg p-1.5 z-50 bg-[#0a0b16]/98 border border-cyan-500/30 shadow-2xl">
                    <div className="text-[10px] font-bold text-cyan-300 px-2 py-1 border-b border-white/10 mb-1 flex items-center justify-between">
                      <span>CONVERSATION TURNS</span>
                      <span className="text-[9px] text-white/40 font-mono">3 turns</span>
                    </div>
                    <div className="space-y-1 max-h-40 overflow-y-auto">
                      {conversationTurns.map((turn) => (
                        <button
                          key={turn.messageId}
                          onClick={() => scrollToTurn(turn.messageId)}
                          className="w-full text-left px-2 py-1.5 rounded text-[11px] font-mono text-white/80 hover:text-cyan-300 hover:bg-cyan-500/10 transition-colors truncate block"
                        >
                          {turn.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Group 4: Context / Token Usage Pill (Expanded Width: 174px) */}
              <div
                className="flex items-center justify-between px-3 h-[32px] text-[10px] font-mono flex-shrink-0"
                style={{
                  ...glassButtonBase,
                  borderRadius: '6px',
                  width: 174,
                }}
              >
                <div className="flex items-center gap-1.5">
                  <span className="text-emerald-400 font-bold">●</span>
                  <span className="text-white/80 font-semibold">IDLE</span>
                </div>
                <span className="text-white/50 text-[9px]">0 / 128.0k tok</span>
              </div>
            </div>
          </div>
        </div>

        {/* ══════════════════════════════════════════════════════════════════════════
            RIGHT WING: DUAL-MODE DASHBOARD COMPANION (Hybrid 1 + Telemetry Badges)
            ══════════════════════════════════════════════════════════════════════════ */}
        <div
          className="relative flex flex-col overflow-hidden flex-1"
          style={{
            height: '88vh',
            maxHeight: 'calc(100vh - 48px)',
            borderRadius: 12,
            background: `linear-gradient(225deg, rgba(10,11,22,0.97) 0%, rgba(6,7,14,0.99) 100%)`,
            border: `1px solid ${GLOW}20`,
            boxShadow: `
              inset 0 1px 1px rgba(255,255,255,0.05),
              inset 0 -1px 1px rgba(0,0,0,0.5),
              0 0 0 1px rgba(0,0,0,0.8),
              -20px 0 60px rgba(0,0,0,0.5)
            `,
          }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 h-12 border-b flex-shrink-0 relative z-30" style={{ borderColor: 'rgba(255,255,255,0.05)' }}>
            <div className="flex items-center gap-2">
              <span className="text-[12px] font-bold tracking-wider text-white">DASHBOARD COMPANION</span>
              <span className="text-[9px] font-mono px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-300 border border-cyan-500/30">
                {railMode === 'surfaces' ? '✦ WORKSPACE SURFACES' : '⚙ ENGINE SETTINGS'}
              </span>
            </div>
          </div>

          <div className="flex flex-1 overflow-hidden relative z-20">
            {/* ─── UNIFIED NAV RAIL WITH INTERTWINED CHEVRON SEAM ARRAY ─── */}
            <nav
              className="flex flex-col h-full border-r overflow-visible shrink-0 transition-all duration-300 relative z-20"
              style={{
                width: isRailExpanded ? 180 : 56,
                borderColor: 'rgba(255,255,255,0.06)',
                backgroundColor: 'rgba(0,0,0,0.35)',
              }}
            >
              {/* Branding Header */}
              <div className="flex h-14 items-center justify-between px-3.5 border-b border-white/[0.04] flex-shrink-0">
                {isRailExpanded ? (
                  <span className="text-[13px] font-black tracking-[0.1em] text-white uppercase">
                    IRIS <span style={{ color: GLOW }}>VOICE</span>
                  </span>
                ) : (
                  <div className="w-full flex justify-center">
                    <div
                      className="w-5 h-5 rounded-full flex items-center justify-center transition-all duration-200"
                      style={{
                        backgroundColor: `${GLOW}25`,
                        border: `1px solid ${GLOW}60`,
                        boxShadow: `0 0 10px ${GLOW}40`,
                      }}
                    >
                      <span className="text-[8px] font-mono font-bold text-cyan-300">●</span>
                    </div>
                  </div>
                )}
              </div>

              {/* ─── SINGLE UNIFIED CHEVRON SEAM STACK + NEON LASER SHIMMER ON SEAM ─── */}
              <div
                onClick={() => setIsRailExpanded(v => !v)}
                onMouseEnter={() => setIsHoveringBoundary(true)}
                onMouseLeave={() => setIsHoveringBoundary(false)}
                className="z-50 flex items-center justify-center cursor-pointer select-none group"
                style={{
                  position: 'absolute',
                  right: -8,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  width: 16,
                  height: 44,
                }}
                title={isRailExpanded ? 'Click seam chevrons to collapse rail' : 'Click seam chevrons to expand rail'}
              >
                <svg
                  width="16"
                  height="40"
                  viewBox="0 0 16 40"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  className="transition-all duration-200"
                  style={{
                    filter: isHoveringBoundary
                      ? `drop-shadow(0 0 6px ${GLOW}) drop-shadow(0 0 2px #ffffff)`
                      : `drop-shadow(0 0 2px ${GLOW}50)`,
                  }}
                >
                  <defs>
                    {/* Laser Seam Shimmer Gradient */}
                    <linearGradient id="laserSeamShimmerGrad" x1="8" y1="0" x2="8" y2="40" gradientUnits="userSpaceOnUse">
                      <stop offset="0%" stopColor={GLOW} stopOpacity="0" />
                      <stop offset="25%" stopColor={GLOW} stopOpacity={isHoveringBoundary ? "0.85" : "0.3"} />
                      <stop offset="50%" stopColor="#ffffff" stopOpacity={isHoveringBoundary ? "1" : "0.55"} />
                      <stop offset="75%" stopColor={GLOW} stopOpacity={isHoveringBoundary ? "0.85" : "0.3"} />
                      <stop offset="100%" stopColor={GLOW} stopOpacity="0" />
                    </linearGradient>
                  </defs>

                  {/* 1. Neon Laser Shimmer Line — Directly on top of the seam line at X=8 */}
                  <line
                    x1="8"
                    y1="3"
                    x2="8"
                    y2="37"
                    stroke="url(#laserSeamShimmerGrad)"
                    strokeWidth={isHoveringBoundary ? "1.75" : "1.25"}
                    strokeLinecap="round"
                    className="transition-all duration-200"
                  />

                  {/* 2. Single Column of Tightly-Spaced Chevrons (Tips touch the seam line at X=8) */}
                  {isRailExpanded ? (
                    // EXPANDED STATE -> ALL CHEVRONS POINT LEFT (‹) TO COLLAPSE
                    <>
                      <path d="M 12 7 L 8 11 L 12 15" stroke={GLOW} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" opacity={isHoveringBoundary ? 1 : 0.7} />
                      <path d="M 12 13 L 8 17 L 12 21" stroke={GLOW} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" opacity={isHoveringBoundary ? 1 : 0.95} />
                      <path d="M 12 19 L 8 23 L 12 27" stroke={GLOW} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" opacity={isHoveringBoundary ? 1 : 0.95} />
                      <path d="M 12 25 L 8 29 L 12 33" stroke={GLOW} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" opacity={isHoveringBoundary ? 1 : 0.7} />
                    </>
                  ) : (
                    // COLLAPSED STATE -> ALL CHEVRONS POINT RIGHT (›) TO EXPAND
                    <>
                      <path d="M 4 7 L 8 11 L 4 15" stroke={GLOW} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" opacity={isHoveringBoundary ? 1 : 0.7} />
                      <path d="M 4 13 L 8 17 L 4 21" stroke={GLOW} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" opacity={isHoveringBoundary ? 1 : 0.95} />
                      <path d="M 4 19 L 8 23 L 4 27" stroke={GLOW} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" opacity={isHoveringBoundary ? 1 : 0.95} />
                      <path d="M 4 25 L 8 29 L 4 33" stroke={GLOW} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" opacity={isHoveringBoundary ? 1 : 0.7} />
                    </>
                  )}
                </svg>
              </div>

                {/* ─── TOP DUAL-MODE SEGMENTED PILL SWITCHER ─── */}
                <div className="px-2 pt-3 pb-2 flex-shrink-0">
                  {isRailExpanded ? (
                    <div
                      className="p-0.5 rounded-lg flex items-center bg-black/50 border border-white/10"
                      style={{ height: 30 }}
                    >
                      <button
                        onClick={() => setRailMode('surfaces')}
                        className={`flex-1 flex items-center justify-center gap-1.5 h-full rounded text-[9px] font-bold tracking-wider uppercase transition-all ${
                          railMode === 'surfaces'
                            ? 'bg-cyan-500/25 text-cyan-300 shadow-[0_0_8px_rgba(0,212,255,0.3)] border border-cyan-400/30'
                            : 'text-white/40 hover:text-white'
                        }`}
                      >
                        <span>✦</span>
                        <span>Surfaces</span>
                      </button>
                      <button
                        onClick={() => setRailMode('settings')}
                        className={`flex-1 flex items-center justify-center gap-1.5 h-full rounded text-[9px] font-bold tracking-wider uppercase transition-all ${
                          railMode === 'settings'
                            ? 'bg-cyan-500/25 text-cyan-300 shadow-[0_0_8px_rgba(0,212,255,0.3)] border border-cyan-400/30'
                            : 'text-white/40 hover:text-white'
                        }`}
                      >
                        <span>⚙</span>
                        <span>Settings</span>
                      </button>
                    </div>
                  ) : (
                    <div className="flex flex-col gap-1 items-center">
                      <button
                        onClick={() => setRailMode(v => v === 'surfaces' ? 'settings' : 'surfaces')}
                        className="w-8 h-8 rounded-lg flex items-center justify-center transition-all bg-black/60 border border-white/10 text-cyan-300 hover:border-cyan-400/40"
                        title={`Active mode: ${railMode}. Click to toggle.`}
                      >
                        {railMode === 'surfaces' ? <span className="text-[12px]">✦</span> : <span className="text-[12px]">⚙</span>}
                      </button>
                    </div>
                  )}
                </div>

                <div className="h-[1px] bg-white/[0.05] mx-3 mb-2" />

                {/* ─── NODE STREAM (Identical 36px Round Nodes in Both Modes) ─── */}
                <div className="flex-1 py-1 overflow-y-auto scrollbar-hide">
                  <div className="flex flex-col gap-2.5 px-2">

                    {/* Mode 1: SURFACES (Workspace, Browser, Market + Live Telemetry Badges) */}
                    {railMode === 'surfaces' && SURFACES.map((surf) => {
                      const Icon = surf.icon
                      const isActive = activeSubApp === surf.id
                      return (
                        <button
                          key={surf.id}
                          onClick={() => setActiveSubApp(surf.id)}
                          className="group w-full flex items-center transition-all duration-200 relative rounded-full"
                          style={{
                            height: 36,
                            backgroundColor: isActive ? `${GLOW}22` : 'transparent',
                            border: isActive ? `1px solid ${GLOW}50` : '1px solid transparent',
                            boxShadow: isActive ? `0 0 12px ${GLOW}26` : 'none',
                            ...(isRailExpanded
                              ? { paddingLeft: 8, paddingRight: 10, justifyContent: 'space-between' }
                              : { width: 36, margin: '0 auto', justifyContent: 'center' }),
                          }}
                          title={isRailExpanded ? undefined : `${surf.label} (${surf.badge})`}
                        >
                          <div className="flex items-center min-w-0">
                            <div
                              className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0"
                              style={{
                                backgroundColor: isActive ? `${GLOW}30` : 'rgba(255,255,255,0.04)',
                                color: isActive ? GLOW : 'rgba(255,255,255,0.5)',
                              }}
                            >
                              <Icon />
                            </div>
                            {isRailExpanded && (
                              <span
                                className="ml-2.5 text-[11px] font-semibold tracking-wide truncate"
                                style={{ color: isActive ? 'white' : 'rgba(255,255,255,0.6)' }}
                              >
                                {surf.label}
                              </span>
                            )}
                          </div>

                          {/* Live Telemetry Badge from Option 2 */}
                          {isRailExpanded && (
                            <span
                              className="text-[8px] font-mono font-bold px-1.5 py-0.5 rounded-full flex-shrink-0"
                              style={{
                                color: surf.badgeColor,
                                backgroundColor: `${surf.badgeColor}18`,
                                border: `1px solid ${surf.badgeColor}35`,
                              }}
                            >
                              {surf.badge}
                            </span>
                          )}
                        </button>
                      )
                    })}

                    {/* Mode 2: SETTINGS (All 6 MAIN_NODES_DATA with Same 36px Round Format) */}
                    {railMode === 'settings' && SETTINGS_NODES.map((node) => {
                      const Icon = node.icon
                      const isActive = activeSettingsTab === node.id && !activeSubApp
                      return (
                        <button
                          key={node.id}
                          onClick={() => { setActiveSettingsTab(node.id); setActiveSubApp(null); }}
                          className="group w-full flex items-center transition-all duration-200 relative rounded-full"
                          style={{
                            height: 36,
                            backgroundColor: isActive ? `${GLOW}22` : 'transparent',
                            border: isActive ? `1px solid ${GLOW}50` : '1px solid transparent',
                            boxShadow: isActive ? `0 0 12px ${GLOW}26` : 'none',
                            ...(isRailExpanded
                              ? { paddingLeft: 8, paddingRight: 10, justifyContent: 'flex-start' }
                              : { width: 36, margin: '0 auto', justifyContent: 'center' }),
                          }}
                          title={isRailExpanded ? undefined : node.label}
                        >
                          <div
                            className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0"
                            style={{
                              backgroundColor: isActive ? `${GLOW}30` : 'rgba(255,255,255,0.04)',
                              color: isActive ? GLOW : 'rgba(255,255,255,0.4)',
                            }}
                          >
                            <Icon />
                          </div>
                          {isRailExpanded && (
                            <span
                              className="ml-2.5 text-[11px] font-semibold tracking-wide truncate"
                              style={{ color: isActive ? 'white' : 'rgba(255,255,255,0.45)' }}
                            >
                              {node.label}
                            </span>
                          )}
                        </button>
                      )
                    })}
                  </div>
                </div>

                {/* User Profile Footer */}
                <div className="p-3 border-t flex-shrink-0" style={{ borderColor: 'rgba(255,255,255,0.05)' }}>
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className="w-7 h-7 rounded-full bg-white/5 flex items-center justify-center flex-shrink-0">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.5)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                        <circle cx="12" cy="7" r="4" />
                      </svg>
                    </div>
                    {isRailExpanded && (
                      <div className="flex flex-col min-w-0">
                        <span className="text-[10px] font-semibold text-white truncate">Online</span>
                        <span className="text-[8px] text-white/40 truncate">Model: {selectedModel}</span>
                      </div>
                    )}
                  </div>
                </div>
              </nav>

            {/* ─── ACTIVE COMPANION SURFACE ─── */}
            <div className="flex-1 p-4 overflow-y-auto space-y-4">
              {activeSubApp === 'workspace' && (
                <div className="space-y-4">
                  {/* Focus Mode Controller */}
                  <div className="flex items-center justify-between">
                    <h4 className="text-[12px] font-bold text-cyan-300">Visual Workspace Hub</h4>
                    <button
                      onClick={cycleFocus}
                      className="px-2.5 py-1 rounded text-[10px] font-mono transition-all"
                      style={{
                        background: `${GLOW}15`,
                        color: GLOW,
                        border: `1px solid ${GLOW}40`,
                      }}
                    >
                      ◈ PRESET: {focusPreset.toUpperCase()}
                    </button>
                  </div>

                  {/* Multi-Agent Kanban Board */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-[11px] font-bold text-white/80">
                      <span>Multi-Agent Task Tracking Pipeline</span>
                      <span className="text-[9px] font-mono text-amber-400">2 active workers running</span>
                    </div>
                    <div className="grid grid-cols-4 gap-2.5">
                      {[
                        { title: 'BACKLOG', color: '#6b7280', cards: [{ label: 'Port Scanner Service', agent: '—' }] },
                        {
                          title: 'IN PROGRESS',
                          color: '#f59e0b',
                          cards: [
                            { label: 'auth-middleware.ts', agent: 'agent-01 · IRISVOICE' },
                            { label: 'sqlite-optimize.py', agent: 'agent-02 · backend' }
                          ]
                        },
                        { title: 'REVIEW', color: '#3b82f6', cards: [{ label: 'ws-resilience.ts', agent: 'agent-01' }] },
                        { title: 'CRYSTALLIZED', color: '#10b981', cards: [{ label: 'reconnect-backoff', agent: '✦ memory.db' }] },
                      ].map(col => (
                        <div key={col.title} className="bg-black/40 rounded-lg p-2.5 border border-white/10 min-h-[120px]">
                          <div className="text-[9px] font-mono font-bold mb-2 tracking-wider" style={{ color: col.color }}>{col.title}</div>
                          {col.cards.map((card, i) => (
                            <div
                              key={i}
                              className="bg-white/5 p-2 rounded border border-white/5 mb-1.5 cursor-pointer hover:bg-white/[0.08] transition-all"
                              style={{ borderLeft: `2px solid ${col.color}` }}
                            >
                              <div className="text-[10px] text-white/85 font-medium">{card.label}</div>
                              <div className="text-[8px] text-white/40 mt-1 font-mono">{card.agent}</div>
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {activeSubApp === 'browser' && (
                <div className="space-y-3">
                  <h4 className="text-[12px] font-bold text-cyan-300">Sandboxed Browser Surface</h4>
                  <div className="h-56 rounded-lg bg-black/40 border border-white/10 flex items-center justify-center text-white/40 text-[11px]">
                    Live Browser with DOM capture &amp; crawler vision tracking (existing iframe preserved)
                  </div>
                </div>
              )}

              {activeSubApp === 'marketplace' && (
                <div className="space-y-3">
                  <h4 className="text-[12px] font-bold text-cyan-300">Tools, MCP Servers &amp; Model Manager</h4>
                  <div className="h-56 rounded-lg bg-black/40 border border-white/10 flex items-center justify-center text-white/40 text-[11px]">
                    MCP Server Registry, Tool Permissions &amp; GGUF Inference Manager
                  </div>
                </div>
              )}

              {!activeSubApp && (
                <div className="space-y-3">
                  <h4 className="text-[12px] font-bold text-white/80 capitalize">{activeSettingsTab} Settings</h4>
                  <div className="p-4 rounded-lg bg-black/30 border border-white/10 text-[11px] text-white/50">
                    Configuration panel for <strong className="text-white/80">{activeSettingsTab}</strong> — rendered by DarkGlassDashboard component.
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
