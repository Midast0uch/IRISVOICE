'use client'

import React, { useState, useEffect, useRef, useMemo } from 'react'
import { 
  Play, Pause, RotateCcw, Sparkles, Terminal, Layers, Copy, Check
} from 'lucide-react'
import { Xur } from '@/components/Xur'
import { TaskCardProps } from '@/temp/task-card-redesign/TaskListCard.v2'
import { VariantMonolith } from '@/temp/task-card-redesign/variants/VariantMonolith'
import { VariantLiquidInk } from '@/temp/task-card-redesign/variants/VariantLiquidInk'
import { 
  renderDoubleTrackPipelineCLI,
  renderBlueprintCellMatrixCLI 
} from '@/temp/task-card-redesign/CLITaskProgressRenderer'

// ── ANSI → HTML Color Converter ──
const ANSI_COLOR_MAP: Record<string, string> = {
  '0': '', '1': '', '2': '', '3': '', '4': '',
  '30': '#1a1a2e', '31': '#ef4444', '32': '#22c55e', '33': '#eab308',
  '34': '#3b82f6', '35': '#a855f7', '36': '#06b6d4', '37': '#e2e8f0',
  '90': '#64748b',
  '91': '#f87171', '92': '#4ade80', '93': '#facc15',
  '94': '#60a5fa', '95': '#c084fc', '96': '#22d3ee', '97': '#f8fafc',
}

function ansiToHtml(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = []
  const regex = /\x1b\[([0-9;]*)m/g
  let lastIndex = 0
  let color = ''
  let bold = false
  let dim = false
  let italic = false
  let partKey = 0

  const matches = [...text.matchAll(regex)]
  for (const match of matches) {
    const beforeText = text.slice(lastIndex, match.index)
    if (beforeText) {
      const style: React.CSSProperties = {}
      if (color) style.color = color
      if (bold) style.fontWeight = 700
      if (dim) style.opacity = 0.5
      if (italic) style.fontStyle = 'italic'
      parts.push(<span key={partKey++} style={Object.keys(style).length > 0 ? style : undefined}>{beforeText}</span>)
    }
    const codes = match[1].split(';').filter(Boolean)
    for (const code of codes) {
      if (code === '0') { color = ''; bold = false; dim = false; italic = false }
      else if (code === '1') bold = true
      else if (code === '2') dim = true
      else if (code === '3') italic = true
      else if (ANSI_COLOR_MAP[code]) color = ANSI_COLOR_MAP[code]
    }
    lastIndex = (match.index ?? 0) + match[0].length
  }
  const remainder = text.slice(lastIndex)
  if (remainder) {
    const style: React.CSSProperties = {}
    if (color) style.color = color
    if (bold) style.fontWeight = 700
    if (dim) style.opacity = 0.5
    if (italic) style.fontStyle = 'italic'
    parts.push(<span key={partKey++} style={Object.keys(style).length > 0 ? style : undefined}>{remainder}</span>)
  }
  return parts
}

function AnsiTerminal({ text }: { text: string }) {
  const lines = text.split('\n')
  return <>{lines.map((line, i) => <div key={i}>{ansiToHtml(line)}</div>)}</>
}

export default function TaskPreviewPage() {
  const [isPlaying, setIsPlaying] = useState(false)
  const [simStep, setSimStep] = useState(0)
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)
  const timerRef = useRef<NodeJS.Timeout | null>(null)

  const [globalElapsed, setGlobalElapsed] = useState(0)
  const globalTimerStart = useRef<number | null>(null)

  const [scenario, setScenario] = useState<TaskCardProps>({
    objective: 'Implement WebSocket Audio Streaming Resilience',
    steps: [], isThinking: false, currentThought: '', thoughtHistory: '',
    isCrystallized: false, memoryEvents: [],
  })

  const isWorking = scenario.isThinking || (scenario.steps || []).some((s) => s.status === 'running')

  useEffect(() => {
    if (!isWorking) return
    if (!globalTimerStart.current) globalTimerStart.current = Date.now()
    const t0 = globalTimerStart.current
    const iv = setInterval(() => setGlobalElapsed(Math.floor((Date.now() - t0) / 1000)), 1000)
    return () => clearInterval(iv)
  }, [isWorking])
  const globalTimerLabel = `${Math.floor(globalElapsed / 60)}:${String(globalElapsed % 60).padStart(2, '0')}`

  const runSimulationStep = (stepIndex: number) => {
    if (stepIndex === 0) { globalTimerStart.current = null; setGlobalElapsed(0) }
    else if (stepIndex === 1 && !globalTimerStart.current) { globalTimerStart.current = Date.now() }

    const base = { objective: 'Implement WebSocket Audio Streaming Resilience' }
    const scenarios: Record<number, TaskCardProps> = {
      0: { ...base, steps: [], isThinking: false, currentThought: '', thoughtHistory: '', isCrystallized: false, memoryEvents: [] },
      1: { ...base, steps: [], isThinking: true, currentThought: 'Recalling past WebSocket recovery episodes from memory.db...', thoughtHistory: '', isCrystallized: false,
        memoryEvents: [{ direction: 'retrieve', engine: 'episodic', detail: 'Retrieved 2 past episodes for WebSocket reconnects' }] },
      2: { ...base, steps: [
        { id: 's1', verb: 'read', target: 'src-tauri/src/ws_client.rs', status: 'running' },
      ], isThinking: false, currentThought: '', thoughtHistory: '', isCrystallized: false,
        memoryEvents: [{ direction: 'retrieve', engine: 'episodic', detail: 'Retrieved 2 past episodes for WebSocket reconnects' }] },
      3: { ...base, steps: [
        { id: 's1', verb: 'read', target: 'src-tauri/src/ws_client.rs', status: 'done', summary: 'Verified tokio reconnect backoff' },
        { id: 's2', verb: 'patch', target: 'hooks/useIRISWebSocket.ts', status: 'running' },
      ], isThinking: false, currentThought: '', thoughtHistory: '', isCrystallized: false,
        memoryEvents: [{ direction: 'store', engine: 'episodic', detail: 'Stored working context snapshot into memory.db' }] },
      4: { ...base, steps: [
        { id: 's1', verb: 'read', target: 'src-tauri/src/ws_client.rs', status: 'done', summary: 'Verified tokio reconnect backoff' },
        { id: 's2', verb: 'patch', target: 'hooks/useIRISWebSocket.ts', status: 'done', summary: 'Applied event listener deduplication' },
        { id: 's3', verb: 'search', target: 'FastAPI WebSocket disconnect handlers', status: 'running', branchLabel: 'Sub-Loop: Docs' },
      ], isThinking: false, currentThought: '', thoughtHistory: '', isCrystallized: false,
        memoryEvents: [{ direction: 'store', engine: 'episodic', detail: 'Stored working context snapshot into memory.db' }] },
      5: { ...base, steps: [
        { id: 's1', verb: 'read', target: 'src-tauri/src/ws_client.rs', status: 'done', summary: 'Verified tokio reconnect backoff' },
        { id: 's2', verb: 'patch', target: 'hooks/useIRISWebSocket.ts', status: 'done', summary: 'Applied event listener deduplication' },
        { id: 's3', verb: 'search', target: 'FastAPI WebSocket disconnect handlers', status: 'done', branchLabel: 'Sub-Loop: Docs', summary: 'Found 3 connection lifecycle patterns' },
        { id: 's4', verb: 'exec', target: 'pytest tests/test_ws_resilience.py', status: 'running' },
      ], isThinking: false, currentThought: '', thoughtHistory: '', isCrystallized: false,
        memoryEvents: [{ direction: 'store', engine: 'episodic', detail: 'Stored working context snapshot into memory.db' }] },
      6: { ...base, steps: [
        { id: 's1', verb: 'read', target: 'src-tauri/src/ws_client.rs', status: 'done', summary: 'Verified tokio reconnect backoff' },
        { id: 's2', verb: 'patch', target: 'hooks/useIRISWebSocket.ts', status: 'done', summary: 'Applied event listener deduplication' },
        { id: 's3', verb: 'search', target: 'FastAPI WebSocket disconnect handlers', status: 'done', branchLabel: 'Sub-Loop: Docs', summary: 'Found 3 connection lifecycle patterns' },
        { id: 's4', verb: 'exec', target: 'pytest tests/test_ws_resilience.py', status: 'crystallized', summary: 'All resilience tests passed' },
      ], isThinking: false, currentThought: '', thoughtHistory: '', isCrystallized: true,
        memoryEvents: [{ direction: 'crystallize', engine: 'coordinates', detail: 'Crystallized verified pattern into memory skills store' }] },
    }
    setScenario(scenarios[stepIndex] || scenarios[0])
  }

  useEffect(() => {
    if (isPlaying) {
      timerRef.current = setInterval(() => {
        setSimStep((prev) => { const next = (prev + 1) % 7; runSimulationStep(next); return next })
      }, 2500)
    } else { if (timerRef.current) clearInterval(timerRef.current) }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [isPlaying])

  const handleStepClick = (idx: number) => { setIsPlaying(false); setSimStep(idx); runSimulationStep(idx) }

  const cliOutputs = useMemo(() => [
    { 
      id: 'pipeline', 
      title: 'Flow Pipeline', 
      subtitle: 'Directional flow connectors (══▶, ●═▶, ◆═▶) with enclosed sub-loops',
      output: renderDoubleTrackPipelineCLI(scenario, true), 
      tag: 'Flow Pipeline' 
    },
    { 
      id: 'blueprint', 
      title: 'Blueprint Matrix', 
      subtitle: 'Dotted vertical guide rails (┊) + hairline sub-chambers (┄)',
      output: renderBlueprintCellMatrixCLI(scenario, true), 
      tag: 'Blueprint Matrix' 
    },
  ], [scenario])

  const handleCopy = (text: string, index: number) => {
    navigator.clipboard.writeText(text.replace(/\x1b\[[0-9;]*m/g, ''))
    setCopiedIndex(index); setTimeout(() => setCopiedIndex(null), 2000)
  }

  const guiVariants = [
    { 
      name: 'Chat View Stream (Industrial Precision)', 
      tag: 'Flagship Chassis', 
      Component: VariantMonolith, 
      desc: 'Precision carbon chassis with fixed-width verb grid and XurOrb orbital micro-indicators' 
    },
    { 
      name: 'Liquid Ink', 
      tag: 'Fluid Vein Chassis', 
      Component: VariantLiquidInk, 
      desc: 'Deep ink plate with pulsing warm accent vein, expanding ripple indicators, and bracketed counter' 
    },
  ]

  return (
    <main
      style={{ position: 'absolute', top: 0, left: 0, width: '100vw', height: '100vh',
        overflowY: 'auto', overflowX: 'hidden', background: '#0a0d18', color: '#f8fafc' }}
      className="p-6 pb-36"
    >
      {/* ── STICKY CONTROLS ── */}
      <div className="sticky top-0 z-30 max-w-6xl mx-auto mb-8 bg-[#0a0d18]/95 backdrop-blur-md pb-4 pt-2 border-b border-white/10">
        <div className="flex items-center justify-between pb-3">
          <div className="flex items-center gap-3">
            <Xur size={22} color="#00d4ff" speed={1.5} />
            <div>
              <h1 className="text-base font-bold tracking-tight text-white">IRIS Task Progress Showcase</h1>
              <p className="text-xs text-white/50">Final Selected Designs: 2 GUI Card Concepts + 2 CLI Terminal Containers</p>
            </div>
          </div>
        </div>

        <div className="p-3.5 rounded-xl bg-black/50 border border-white/10 flex flex-wrap items-center justify-between gap-3 shadow-lg">
          <div className="flex items-center gap-2">
            <button onClick={() => setIsPlaying(!isPlaying)}
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium text-black bg-cyan-400 hover:bg-cyan-300 transition-colors shadow-md"
            >
              {isPlaying ? <Pause size={12} /> : <Play size={12} />}
              <span>{isPlaying ? 'Pause' : 'Auto Play'}</span>
            </button>
            <button onClick={() => handleStepClick(0)}
              className="p-1.5 rounded-lg text-white/50 hover:text-white bg-white/5 hover:bg-white/10 transition-colors" title="Reset"
            >
              <RotateCcw size={13} />
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-1.5 text-[11px] font-mono">
            {[
              { idx: 0, label: '0. Ready' }, { idx: 1, label: '1. ↙ Recall' },
              { idx: 2, label: '2. Read' }, { idx: 3, label: '3. ↗ Patch' },
              { idx: 4, label: '4. Sub-Loop' }, { idx: 5, label: '5. Test' },
              { idx: 6, label: '6. ✦ Crystallize' },
            ].map((st) => (
              <button key={st.idx} onClick={() => handleStepClick(st.idx)}
                className={`px-2.5 py-1 rounded transition-colors ${
                  simStep === st.idx ? 'text-cyan-300 bg-cyan-500/20 border border-cyan-500/40 font-semibold' : 'text-white/45 hover:text-white/80 bg-white/5'
                }`}>{st.label}</button>
            ))}
          </div>

          <div className="flex items-center gap-2 text-[10.5px] font-mono text-white/40 border-l border-white/10 pl-3">
            <a href="#gui-section" className="text-cyan-300 font-semibold hover:underline">GUI Cards</a>
            <a href="#cli-section" className="text-emerald-300 font-semibold hover:underline">CLI Terminal</a>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto space-y-12">

        {/* ═══ SECTION 1: GUI CARD VARIANTS ═══ */}
        <section id="gui-section" className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 shadow-[0_0_8px_rgba(0,212,255,0.8)]" />
              <h2 className="text-sm font-mono font-bold uppercase tracking-widest text-cyan-300">
                1. GUI Card Designs (Chat View Stream)
              </h2>
            </div>
            <span className="text-[11px] font-mono text-white/40">2 Final Concepts · Live State Sync</span>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            {guiVariants.map((v) => (
              <div key={v.name} className="space-y-3">
                <div className="text-[11px] font-mono flex items-center justify-between px-1">
                  <span className="flex items-center gap-2">
                    <Layers size={12} className="text-cyan-300/60" />
                    <span className="text-white/80 font-semibold">{v.name}</span>
                  </span>
                  <span className="text-[9.5px] font-bold uppercase text-cyan-300 bg-cyan-500/15 border border-cyan-500/30 px-2 py-0.5 rounded-md">
                    {v.tag}
                  </span>
                </div>
                <div className="p-5 rounded-xl bg-black/40 border border-white/8 space-y-3 shadow-xl">
                  <div className="flex justify-end">
                    <div className="max-w-[85%] rounded-xl px-3.5 py-2 text-xs text-white/90 bg-white/[0.08] border border-white/10 font-sans">
                      Make the WebSocket connection in Tauri survive sleep/wake.
                    </div>
                  </div>
                  <v.Component {...scenario} />
                </div>
                <p className="text-[10.5px] font-mono text-white/40 px-1">{v.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ═══ DIVIDER ═══ */}
        <div className="relative my-12">
          <div className="absolute inset-0 flex items-center" aria-hidden="true">
            <div className="w-full border-t border-cyan-500/25" />
          </div>
          <div className="relative flex justify-center">
            <span className="bg-[#0a0d18] px-5 text-xs font-mono font-bold uppercase tracking-widest text-cyan-300 border border-cyan-500/40 rounded-full py-1.5 shadow-[0_0_20px_rgba(0,212,255,0.25)] flex items-center gap-2">
              <Terminal size={14} className="text-cyan-400 animate-pulse" /> 
              DEVELOPER CLI TERMINAL FORMATS (2 SELECTED OPTIONS)
            </span>
          </div>
        </div>

        {/* ═══ SECTION 2: CLI VARIANTS ═══ */}
        <section id="cli-section" className="space-y-8">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(34,197,94,0.8)]" />
              <h2 className="text-sm font-mono font-bold uppercase tracking-widest text-emerald-300">
                2. Developer CLI Terminal Outputs (Flow Pipeline & Blueprint Matrix)
              </h2>
            </div>
            <span className="text-[11px] font-mono text-white/40">Stacked Context Footers · Pure Semantic</span>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            {cliOutputs.map((cli, idx) => (
              <div key={cli.id} className="rounded-xl overflow-hidden border border-white/12 bg-[#070913] shadow-2xl flex flex-col">
                {/* Titlebar */}
                <div className="flex items-center justify-between px-3.5 py-2 bg-[#0e121e] border-b border-white/8 select-none">
                  <div className="flex items-center gap-2">
                    <div className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-full bg-[#ff5f56] border border-[#e0443e]" />
                      <span className="w-2.5 h-2.5 rounded-full bg-[#ffbd2e] border border-[#dea123]" />
                      <span className="w-2.5 h-2.5 rounded-full bg-[#27c93f] border border-[#1aab29]" />
                    </div>
                    <span className="text-[11px] font-mono text-white/50 ml-2">iris@dev-mode: ~/IRISVOICE</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[9.5px] font-mono font-semibold px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">{cli.tag}</span>
                    <button onClick={() => handleCopy(cli.output, idx)}
                      className="p-1 rounded text-white/40 hover:text-white hover:bg-white/10 transition-colors" title="Copy plain text"
                    >
                      {copiedIndex === idx ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                    </button>
                  </div>
                </div>

                {/* Prompt */}
                <div className="px-4 pt-3 pb-1 text-[11px] font-mono text-white/40 flex items-center gap-2 bg-[#070913]">
                  <span className="text-cyan-400 font-bold">$</span>
                  <span className="text-white/70">iris task watch --live</span>
                </div>

                {/* ANSI → HTML Canvas */}
                <div className="p-4 pt-2 font-mono text-[11px] leading-relaxed text-white/90 flex-1 min-h-[320px] max-h-[400px] overflow-y-auto whitespace-pre-wrap select-text">
                  <AnsiTerminal text={cli.output} />
                </div>

                {/* Footer with Single Global Timer */}
                <div className="px-3.5 py-1.5 bg-[#0b0e18] border-t border-white/6 flex items-center justify-between text-[10px] font-mono text-white/35">
                  <div className="flex items-center gap-2">
                    <span className={`w-1.5 h-1.5 rounded-full ${isWorking ? 'bg-amber-400 animate-pulse' : scenario.isCrystallized ? 'bg-emerald-400' : 'bg-white/30'}`} />
                    <span>{cli.title}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    {(isWorking || globalElapsed > 0) && (
                      <span className={`tabular-nums ${isWorking ? 'text-amber-300/80' : 'text-white/40'}`}>⏱ {globalTimerLabel}</span>
                    )}
                    <span>UTF-8 · LIVE</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

      </div>
    </main>
  )
}
