'use client';

import { useState, memo, useMemo, useCallback, useEffect, useRef, lazy, Suspense } from 'react';
import { CustomDropdown } from '@/components/ui/CustomDropdown';
import { ModelInferenceSection } from '@/components/ModelInferenceSection';

import { motion, AnimatePresence } from 'framer-motion';
import { useBrandColor } from '@/contexts/BrandColorContext';
import { useNavigation } from '@/contexts/NavigationContext';
import type { MainCategoryId } from '@/data/navigation-ids';
import type { Tab, TabType, OpenTabMsg, CloseTabMsg } from '@/types/iris';
import { DashboardRenderer } from '@/components/wing/DashboardRenderer';
import { CARDS_BY_SECTION, getCardsForSection, CARDS_DATA } from '@/data/cards';
import { SECTION_TO_LABEL, SECTION_TO_ICON, CARD_TO_SECTION_ID } from '@/data/navigation-constants';
import { ActivityPanel } from './dashboard/ActivityPanel';
import { LogsPanel } from './dashboard/LogsPanel';
import { InferenceConsolePanel } from './dashboard/InferenceConsolePanel';
import { LearnedSkillsPanel } from './wheel-view/LearnedSkillsPanel';
import { ModelBrowserPanel } from './dashboard/ModelBrowserPanel';
import { MarketplaceScreen } from './integrations/MarketplaceScreen';
import { UnifiedMarketplaceModelsSurface } from './integrations/UnifiedMarketplaceModelsSurface';
import { useLauncherMode } from '@/hooks/useLauncherMode';
import { useInferenceState } from '@/hooks/useInferenceState';
import { useCrawlContext } from '@/hooks/CrawlProvider';
import { useWorkspaceStore } from '@/stores/workspaceStore';

// cli-workspace-unification T7 (REQ-7 AC2): the Workspace Hub surface —
// lazy-loaded so the hub bundle only loads when the rail node is clicked.
const DeveloperWorkspace = lazy(() => import('@/components/workspace/DeveloperWorkspace'));
import { DCPStatsPanel } from '@/components/dev/DCPStatsPanel';
import { MonitorTabContainer } from '@/components/dashboard/MonitorTabContainer';
import { BrowserNavigationOverlay } from '@/components/iris/browser/BrowserNavigationOverlay';
import { VisionLifecycleChip } from '@/components/iris/browser/VisionLifecycleChip';
import { useBrowserNavOverlay, type NavOverlaySeed } from '@/hooks/useBrowserNavOverlay';
import { useViewProtocol } from '@/hooks/useViewProtocol';
import { useActiveFrameSrc, useBrowserSurfaceSession } from '@/hooks/useActiveFrameSrc';
import { IrisApertureIcon } from '@/components/ui/IrisApertureIcon';
import { IconRobot, IconTopologyStar3, IconBasketCog } from "@tabler/icons-react";
import {
  Mic, Bot, Cpu, Settings, Palette, Activity, Volume2, Waves, Brain, Database, Sparkles, MessageSquare, Smile, Wrench, Layers, Star, Keyboard, Monitor, Power, HardDrive, Wifi, Bell, Sliders, RefreshCw, BarChart3, FileText, Stethoscope, X, ChevronRight, ChevronLeft, ChevronDown, ChevronUp, Eye, Globe,
  Shield, Zap, Workflow, Boxes, Puzzle, FolderOpen, Monitor as MonitorIcon, Play, Volume1, MicVocal,
  LayoutDashboard, ShoppingBag, Menu, User, ArrowLeft, RotateCcw, Home, ArrowRight as ArrowRightIcon, ExternalLink, History, AlertCircle, Code, FileCode, Plus as PlusIcon,
  Network as NetworkIcon, Loader, AlertTriangle
} from 'lucide-react';

interface DarkGlassDashboardProps {
  theme?: string;
  fieldValues?: Record<string, Record<string, string | number | boolean>>;
  updateField?: (sectionId: string, fieldId: string, value: any) => void;
  onClose?: () => void;
  onNotificationsClick?: () => void;
  unreadCount?: number;
  isNotificationsOpen?: boolean;
  isChatOpen?: boolean;
  spotlightState?: any; // From @/hooks/useUILayoutState
  uiState?: any;        // From @/hooks/useUILayoutState
  onOpenChat?: () => void;
  initialSubApp?: string | null;
  onRequestSpotlight?: () => void;
}

const ACCENT_COLOR = '#00d4aa';

// REQ-11 (specs/vision-browser-stage, T12): ONE source of truth for the
// browser panel's chrome heights. browserChromeInset and the rendered rows
// both read these — a mismatch drifts the overlay's orb centring and top-wash
// depth (the inset feeds BrowserNavigationOverlay).
const BROWSER_TAB_STRIP_H = 36;
const BROWSER_ADDRESS_BAR_H = 36;

const MAIN_NODES_DATA = [
  { id: 'voice', label: 'Voice', icon: Mic },
  { id: 'agent', label: 'Agent', icon: IconRobot },
  { id: 'automate', label: 'Automate', icon: IconTopologyStar3 },
  { id: 'system', label: 'System', icon: IconBasketCog },
  { id: 'customize', label: 'Customize', icon: Palette },
  { id: 'monitor', label: 'Monitor', icon: Activity },
];

const CATEGORY_LABELS: Record<string, string> = {
  input: 'Input',
  output: 'Output',
  wake: 'Wake Word',
  speech: 'Speech',
  dashboard: 'Settings',
  browser: 'Browser',
  activity: 'Activity',
  logs: 'Logs',
  marketplace: 'Marketplace',
  models: 'Models',
  inference_console: 'Inference Console',
  terminal: 'Terminal',
  hub: 'Workspace Hub',
};

// Helper function to map icon names from SECTION_TO_ICON to Lucide components
const getIconComponent = (iconName: string) => {
  const iconMap: Record<string, React.ComponentType<any>> = {
    'Mic': Mic,
    'Volume2': Volume2,
    'Volume1': Volume1,
    'MicVocal': MicVocal,
    'Cpu': Cpu,
    'Brain': Brain,
    'Shield': Shield,
    'Zap': Zap,
    'Eye': Eye,
    'Workflow': Workflow,
    'Keyboard': Keyboard,
    'Monitor': Monitor,
    'Boxes': Boxes,
    'Puzzle': Puzzle,
    'FolderOpen': FolderOpen,
    'Power': Power,
    'MonitorIcon': MonitorIcon,
    'HardDrive': HardDrive,
    'Wifi': Wifi,
    'Palette': Palette,
    'Play': Play,
    'Activity': Activity,
    'FileText': FileText,
    'Stethoscope': Stethoscope,
    'RefreshCw': RefreshCw,
    'Waves': Waves,
    'Database': Database,
    'Sparkles': Sparkles,
    'MessageSquare': MessageSquare,
    'Smile': Smile,
    'Wrench': Wrench,
    'Layers': Layers,
    'Star': Star,
    'Bell': Bell,
    'Sliders': Sliders,
    'BarChart3': BarChart3,
    'Globe': Globe,
    'Bot': Bot,
    'Settings': Settings,
    'Network': NetworkIcon,
  };
  return iconMap[iconName] || Boxes;
};

// Helper function to convert card fields to dashboard field format
function convertCardFieldsToDashboardFields(cards: any[]) {
  const fields: any[] = [];
  cards.forEach(card => {
    card.fields.forEach((field: any) => {
      fields.push({
        id: field.id,
        label: field.label,
        type: field.type,
        options: field.options,
        defaultValue: field.defaultValue,
        min: field.min,
        max: field.max,
        unit: field.unit,
        placeholder: field.placeholder,
        action: field.action,
        showIf: field.showIf,
      });
    });
  });
  return fields;
}

// Generate SECTIONS_DATA dynamically from cards.ts and navigation constants
function useSectionsData() {
  return useMemo(() => {
    const sections = Object.entries(CARD_TO_SECTION_ID).reduce((acc, [cardId, sectionId]) => {
      if (!acc[sectionId]) {
        acc[sectionId] = {
          id: sectionId,
          label: SECTION_TO_LABEL[sectionId]?.toUpperCase() || sectionId.toUpperCase(),
          icon: getIconComponent(SECTION_TO_ICON[sectionId] || 'Boxes'),
          fields: convertCardFieldsToDashboardFields(getCardsForSection(sectionId))
        };
      }
      
      return acc;
    }, {} as Record<string, { id: string; label: string; icon: any; fields: any[] }>);
    
    // Group sections by category
    const categoryMapping: Record<string, string[]> = {
      voice: ['input', 'output', 'wake', 'speech'],
      dashboard: ['analytics', 'logs', 'diagnostics', 'updates'],
      browser: ['sessions'],
      activity: ['logs'],
      logs: ['analytics'],
      marketplace: ['updates'],
      agent: ['model_inference', 'local_model', 'swarm_setup', 'identity', 'memory', 'search'],
      automate: ['tools', 'vision', 'desktop_control', 'skills', 'profile'],
      system: ['power', 'display', 'storage', 'network'],
      customize: ['theme', 'startup', 'behavior', 'notifications'],
      monitor: ['analytics', 'logs', 'diagnostics', 'updates'],
    };
    
    const result: Record<string, { id: string; label: string; icon: any; fields: any[] }[]> = {};
    
    Object.entries(categoryMapping).forEach(([categoryId, sectionIds]) => {
      result[categoryId] = sectionIds
        .map(sectionId => sections[sectionId])
        .filter(Boolean);
    });
    
    return result;
  }, []);
}

// Determine field category for layout
function getFieldCategory(field: any, sectionId: string): 'config' | 'visualizer' | 'toggles' {
  const fieldId = field.id.toLowerCase();
  if (field.type === 'toggle') return 'toggles';
  if (fieldId.includes('volume') || fieldId.includes('gain') || fieldId.includes('level')) return 'visualizer';
  return 'config';
}

const FieldRow = memo(function FieldRow({ field, glowColor, fieldValues, sectionId, updateField, fieldErrors, clearFieldError, sendMessage, audioInputDevices, audioOutputDevices, wakeWords }: { field: any; glowColor: string; fieldValues?: Record<string, Record<string, string | number | boolean>>; sectionId?: string; updateField?: (sectionId: string, fieldId: string, value: any) => void; fieldErrors?: Record<string, string>; clearFieldError?: (sectionId: string, fieldId: string) => void; sendMessage?: (type: string, payload?: any) => boolean; audioInputDevices?: string[]; audioOutputDevices?: string[]; wakeWords?: string[] }) {
  const [localValue, setLocalValue] = useState(field.defaultValue ?? '');
  const value = fieldValues && sectionId ? (fieldValues[sectionId]?.[field.id] ?? field.defaultValue ?? '') : localValue;
  const [btnFeedback, setBtnFeedback] = useState<string | null>(null);
  
  const errorKey = sectionId && field.id ? `${sectionId}:${field.id}` : null;
  const errorMessage = errorKey && fieldErrors ? fieldErrors[errorKey] : null;
  
  const setValue = useCallback((newValue: any) => {
    if (errorMessage && sectionId && field.id && clearFieldError) {
      clearFieldError(sectionId, field.id);
    }

    if (fieldValues && sectionId && updateField) {
      updateField(sectionId, field.id, newValue);
    } else {
      setLocalValue(newValue);
    }

    // Refresh available models whenever the provider/inference mode changes so
    // the reasoning_model and tool_execution_model dropdowns stay in sync.
    if (sendMessage && sectionId === 'inference_mode' && field.id === 'inference_mode') {
      sendMessage('get_available_models', {});
    }
  }, [fieldValues, sectionId, updateField, field.id, errorMessage, clearFieldError, sendMessage]);

  const handleSliderClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const p = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const min = field.min ?? 0;
    const max = field.max ?? 100;
    const newValue = min + p * (max - min);
    setValue(newValue);
  }, [field.min, field.max, setValue]);

  // Conditional visibility: hide field if showIf condition not met
  if (field.showIf && fieldValues && sectionId) {
    const depValue = fieldValues[sectionId]?.[field.showIf.field];
    // Only hide if there's an explicit value that doesn't match (undefined = not set yet = show)
    if (depValue !== undefined && depValue !== null && !field.showIf.values.includes(depValue)) return null;
  }

  if (field.type === 'section') {
    return (
      <div className="pt-4 pb-1 border-b border-white/5 mb-2 col-span-full">
        <span className="text-[9px] font-black uppercase tracking-[0.2em] text-white/30">
          {field.label}
        </span>
      </div>
    );
  }

  if (field.type === 'custom') {
    if (field.id === 'skills_list') {
      return (
        <div className="col-span-full mt-2 mb-4">
          <LearnedSkillsPanel glowColor={glowColor} />
        </div>
      );
    }
    // Model status badge (local_model_status)
    if (field.id === 'local_model_status') {
      const status = (value as string) || 'unloaded';
      const statusColors: Record<string, { bg: string; border: string; text: string }> = {
        loaded: { bg: 'rgba(34,197,94,0.15)', border: 'rgba(34,197,94,0.4)', text: '#22c55e' },
        unloaded: { bg: 'rgba(148,163,184,0.15)', border: 'rgba(148,163,184,0.4)', text: '#94a3b8' },
        loading: { bg: 'rgba(59,130,246,0.15)', border: 'rgba(59,130,246,0.4)', text: '#3b82f6' },
        error: { bg: 'rgba(239,68,68,0.15)', border: 'rgba(239,68,68,0.4)', text: '#ef4444' },
      };
      const sc = statusColors[status] || statusColors.unloaded;
      return (
        <div className="py-2 col-span-full">
          <div className="flex items-center justify-between px-3 py-2 rounded-xl text-[10px] uppercase tracking-wider"
            style={{ background: sc.bg, border: `1px solid ${sc.border}` }}>
            <span style={{ color: 'rgba(255,255,255,0.5)' }}>MODEL STATUS</span>
            <span style={{ color: sc.text }}>{status.toUpperCase()}</span>
          </div>
        </div>
      );
    }
    // Swarm status badge
    if (field.id === 'swarm_status') {
      const state = (value as string) || 'inactive';
      return (
        <div className="py-2 col-span-full">
          <div className="flex items-center justify-between px-3 py-2 rounded-xl text-[10px] uppercase tracking-wider"
            style={{
              background: state === 'active' ? 'rgba(139,92,246,0.15)' : 'rgba(148,163,184,0.15)',
              border: `1px solid ${state === 'active' ? 'rgba(139,92,246,0.4)' : 'rgba(148,163,184,0.4)'}`,
            }}>
            <span style={{ color: 'rgba(255,255,255,0.5)' }}>SWARM STATE</span>
            <span style={{ color: state === 'active' ? '#8b5cf6' : '#94a3b8' }}>
              {state === 'active' ? 'ACTIVE' : 'INACTIVE'}
            </span>
          </div>
        </div>
      );
    }
    // Generic custom fallback
    return (
      <div className="py-2 col-span-full">
        <div className="flex items-center justify-between px-3 py-2 rounded-xl text-[10px] tracking-wider"
          style={{ background: `${glowColor}10`, border: `1px solid ${glowColor}30` }}>
          <span style={{ color: 'rgba(255,255,255,0.5)' }}>{field.label}</span>
          <span style={{ color: glowColor }}>{String(value || '—')}</span>
        </div>
      </div>
    );
  }

  if (field.type === 'button') {
    return (
      <div className="py-2 col-span-full">
        <button
          onClick={() => {
            setBtnFeedback("clicked");
            setTimeout(() => setBtnFeedback(null), 2000);
            if (field.action) {
              window.dispatchEvent(new CustomEvent('iris:card_action', { detail: { action: field.action, fieldId: field.id } }));
            } else {
              setValue("trigger");
            }
          }}
          className="w-full py-2 px-3 rounded-xl text-[10px] font-bold uppercase tracking-wider transition-all"
          style={{
            background: btnFeedback ? `${glowColor}30` : `${glowColor}15`,
            border: `1px solid ${btnFeedback ? glowColor : `${glowColor}44`}`,
            color: glowColor,
          }}
          onMouseEnter={e => { if (!btnFeedback) { e.currentTarget.style.background = `${glowColor}25`; e.currentTarget.style.borderColor = `${glowColor}66`; }}}
          onMouseLeave={e => { if (!btnFeedback) { e.currentTarget.style.background = `${glowColor}15`; e.currentTarget.style.borderColor = `${glowColor}44`; }}}
        >
          {btnFeedback ? `✓ ${field.label}` : field.label}
        </button>
      </div>
    );
  }

  if (field.type === 'toggle') {
    return (
      <div className="flex items-center justify-between py-1.5 px-1 gap-2">
        <span className="text-[11px] font-medium text-white/60 flex-1 min-w-0 leading-tight">{field.label}</span>
        <button
          onClick={() => setValue(!value)}
          className="relative w-8 h-4 rounded-full transition-colors"
          style={{ backgroundColor: value ? glowColor : 'rgba(255,255,255,0.1)' }}
        >
          <motion.span
            className="absolute top-0.5 w-3 h-3 rounded-full bg-white shadow-sm"
            animate={{ left: value ? '18px' : '2px' }}
          />
        </button>
      </div>
    );
  }

  if (field.type === 'dropdown') {
    let options = field.options || [];
    if (sectionId === 'input' && field.id === 'input_device') options = audioInputDevices || [];
    if (sectionId === 'output' && field.id === 'output_device') options = audioOutputDevices || [];
    if (sectionId === 'wake' && (field.id === 'wake_word' || field.id === 'wake_phrase')) options = wakeWords && wakeWords.length > 0 ? wakeWords : (field.options || []);
    
    return (
      <div className="flex items-center justify-between py-1.5 gap-3 group/field px-1">
        <span className="text-[11px] font-medium text-white/55 group-hover/field:text-white/80 transition-colors flex-shrink-0 whitespace-nowrap">{field.label}</span>
        <div className="w-[140px] flex-shrink-0">
          <CustomDropdown
            value={value}
            options={options}
            onChange={setValue}
            glowColor={glowColor}
            className="text-[10px] py-1 px-2 h-7 w-full"
          />
        </div>
      </div>
    );
  }

  if (field.type === 'slider') {
    const min = field.min ?? 0;
    const max = field.max ?? 100;
    const pct = ((Number(value) - min) / (max - min)) * 100;
    return (
      <div className="py-2 px-1">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[11px] font-medium tracking-wide text-white/60">{field.label}</span>
          <span className="text-[10px] tabular-nums" style={{ color: glowColor }}>{Math.round(Number(value))}{field.unit || ''}</span>
        </div>
        <div className="relative h-1 bg-white/5 rounded-full cursor-pointer" onClick={handleSliderClick}>
          <div className="absolute left-0 top-0 h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: glowColor }} />
        </div>
      </div>
    );
  }

  if (field.type === 'text') {
    const isSecret = field.id.toLowerCase().includes('key') || field.id.toLowerCase().includes('secret') || field.id.toLowerCase().includes('password');
    return (
      <div className="py-1.5 px-1 col-span-full">
        <label className="text-[10px] font-medium tracking-wide text-white/50 block mb-1">{field.label}</label>
        <input
          type={isSecret ? 'password' : 'text'}
          value={String(value ?? '')}
          placeholder={field.placeholder || field.label}
          onChange={(e) => setValue(e.target.value)}
          className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-[11px] text-white/90 placeholder:text-white/25 outline-none transition-all focus:border-white/25 focus:bg-white/8"
          style={{ fontFamily: field.id.includes('url') || field.id.includes('endpoint') || field.id.includes('key') ? "'JetBrains Mono', monospace" : 'inherit' }}
          onFocus={(e) => { e.currentTarget.style.borderColor = glowColor + '60'; }}
          onBlur={(e) => { e.currentTarget.style.borderColor = 'rgba(255,255,255,0.1)'; }}
        />
        {errorMessage && (
          <p className="text-[9px] text-red-400 mt-1">{errorMessage}</p>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between py-1.5 px-1">
      <span className="text-[11px] font-medium tracking-wide text-white/60">{field.label}</span>
      <span className="text-[11px] text-white/30">{value || '-'}</span>
    </div>
  );
});

export function DarkGlassDashboard({
  fieldValues: propFieldValues,
  updateField: propUpdateField,
  onClose,
  onNotificationsClick,
  unreadCount = 0,
  isNotificationsOpen = false,
  isChatOpen = false,
  spotlightState,
  uiState,
  onOpenChat,
  initialSubApp,
  onRequestSpotlight,
}: DarkGlassDashboardProps) {
  // Domain 13.3 — iris mode from launcher (personal | developer).
  // Fetches persisted mode from backend on mount; listens for real-time WS events.
  // useLauncherMode fetches /api/mode so this works even when iris-launcher ran before IRISVOICE loaded.
  const { mode: irisMode } = useLauncherMode();

  // ── REQ-12 (T17): crawl state is hoisted into CrawlProvider ABOVE this
  // component's unmount boundary (mounted in app/layout.tsx). The panel may
  // unmount/remount freely; crawl state, its listeners and the SSE fallback
  // all live up there. We consume the provider's state here instead of
  // registering our own iris:crawler_* listeners (deleted — the duplicates).
  const { state: crawlState } = useCrawlContext();

  const {
    providers,
    role_bindings,
    loading: infLoading,
    sendRoleBinding,
    provider_presets,
    sendModelSelection,
    sendInferenceMode,
    model_catalog,
  } = useInferenceState();

  // Persist active tab so the app restores to the last used panel on reopen
  const [activeTab, setActiveTab] = useState<string>(() => {
    if (typeof window === "undefined") return 'voice'
    return localStorage.getItem('iris_active_tab_v1') || 'voice'
  });
  const [activeSubApp, setActiveSubApp] = useState<string | null>(null);
  // Live web-search status, rendered as a pill in the CENTRE of the header
  // (between the sub-app title and the notification button). Owned here rather
  // than in dashboard-wing because the header lives here — the wing could only
  // render a band ABOVE the header, which is what it used to do.
  //
  // The REAL crawl state lives in CrawlProvider (useCrawl). This local state is
  // a display mirror synced from the provider (see the sync effect below); it
  // exists only so the finished-pill timeout can clear the pill without touching
  // provider state. Visuals are unchanged (REQ-11 AC3).
  const [crawler, setCrawler] = useState<{
    active: boolean
    query: string
    pagesDone: number
    pagesTotal: number
    error: string | null
  }>({ active: false, query: '', pagesDone: 0, pagesTotal: 0, error: null });
  const [isRailExpanded, setIsRailExpanded] = useState(true);
  const [isSidebarHidden, setIsSidebarHidden] = useState(false);
  // T7 (REQ-7 AC1): dual-mode rail — SURFACES (live workspaces) vs SETTINGS
  // (the 6 category nodes). Collapses to a 2-pip toggle at 56px rail width.
  const [railMode, setRailMode] = useState<'surfaces' | 'settings'>('surfaces');
  const [seamHover, setSeamHover] = useState(false);

  // ── T7 telemetry badge sources (REQ-7 AC2) — EXISTING stores only, no new
  // telemetry backend. If a source is unavailable the badge renders dimmed
  // rather than fabricating a count (design.md Error Handling).
  // [● N Running] ← workspaceStore active agent tasks (T9 store).
  const runningAgentTasks = useWorkspaceStore(
    (s) => s.agentTasks.filter((t) => t.status === 'in_progress').length
  );
  // [● N Tools] ← existing dev CLI tools endpoint (the tool registry the
  // HelpPanel already reads). Fetched once; null = unavailable → dimmed.
  const [mcpToolCount, setMcpToolCount] = useState<number | null>(null);
  useEffect(() => {
    // Guard: jsdom/test environments may not provide global fetch — the badge
    // then renders dimmed ("source unavailable"), never a fabricated count.
    if (typeof globalThis.fetch !== 'function') return;
    let cancelled = false;
    fetch('/api/dev/cli-tools')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => {
        if (!cancelled) setMcpToolCount(Array.isArray(d?.tools) ? d.tools.length : null);
      })
      .catch(() => {
        if (!cancelled) setMcpToolCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['input', 'model_inference', 'tools', 'power', 'theme', 'analytics']));
  const [isApplying, setIsApplying] = useState(false);
  const [applyStatus, setApplyStatus] = useState<"idle" | "applying" | "applied">("idle");
  
  const [browserUrl, setBrowserUrl] = useState<string>('https://www.google.com');
  const [browserInput, setBrowserInput] = useState<string>('https://www.google.com');
  // T12: panel-owned nav stack (bounded at 50). Never window.history.
  const [browserHistory, setBrowserHistory] = useState<string[]>([]);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // ── REQ-16 (T45/T46): browser-navigation overlay state machine. Consumes
  //    iris:open_tab / iris:crawler_* events; transitions feed the REQ-18
  //    trace (AC9) via iris:nav_overlay_state. Isolated in a hook for tests.
  //    NOTE: the hook emits the trace itself on every transition — do NOT also
  //    wire emitTrace into the overlay's onStateChange or each transition is
  //    recorded twice.
  //    REQ-7 (specs/vision-browser-stage): seeded from CrawlProvider so a
  //    panel mounted MID-RUN shows the current state immediately. The seed is
  //    memoized on run identity only (OPT GATE: derivation never re-runs per
  //    render beyond these four values changing).
  const navSeed = useMemo<NavOverlaySeed>(() => ({
    active: crawlState.active,
    pagesDone: crawlState.pages.length,
    pagesTotal: crawlState.total,
    subGoal: crawlState.query,
  }), [crawlState.active, crawlState.pages.length, crawlState.total, crawlState.query]);
  const { status: navOverlay } = useBrowserNavOverlay(navSeed)

  // ── REQ-4 (T9): view protocol — parent side. The sandboxed content frame
  //    speaks OUT via postMessage; BOTH checks (event.source === frame AND
  //    fixed shape) run inside the hook. Validated view state is re-emitted as
  //    `iris:view_state` so the overlay/panel consume it without ever reaching
  //    INTO the frame. Degradation (REQ-4 AC5): no script => no events, never
  //    throws.
  const { sendScrollTo } = useViewProtocol(iframeRef)

  // ── The reading surface actually reads ──────────────────────────────────
  // `sendScrollTo` was destructured here and NEVER CALLED. Every other half of
  // this feature exists — the session records where it scrolled, the event
  // reaches the panel, the particle cursor animates, the injected view-agent
  // honours a `scrollTo` command — but nothing ever sent the command, so the
  // page in the iframe never moved. The user watched a still frame with a
  // cursor drifting over it and reasonably concluded vision was not running.
  //
  // Mirror on the SEQUENCE, not the value: the model can scroll to the same
  // offset twice (a bounded page, a re-read), and a value-keyed effect would
  // silently skip the second one. Smooth, because this is something a person is
  // watching, not a jump-cut.
  const lastMirroredScrollRef = useRef(0)
  useEffect(() => {
    const seq = navOverlay.visionScrollSeq
    const top = navOverlay.visionScrollY
    if (!seq || seq === lastMirroredScrollRef.current) return
    if (typeof top !== 'number') return
    lastMirroredScrollRef.current = seq
    sendScrollTo(top, true)
  }, [navOverlay.visionScrollSeq, navOverlay.visionScrollY, sendScrollTo])

  // Tab system — receives open_tab / close_tab WebSocket messages
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);

  // REQ-1 AC2 (T5): the ACTIVE web tab's frame src. Agent-navigated pages
  // replay the captured bytes (/api/browser/capture/{job_id}/{page_number})
  // — never a second live fetch. User-typed URLs (no active tab) render
  // through the fetch proxy (/api/browser/proxy?url=...) per REQ-2.
  // The browser-surface endpoints require a token cookie; mint it before any
  // frame loads or the first request races the cookie and is refused.
  const surfaceReady = useBrowserSurfaceSession()
  const resolvedFrameSrc = useActiveFrameSrc({ tabs, activeTabId, browserUrl })
  const resolvedFrameSrcGated = surfaceReady ? resolvedFrameSrc : undefined

  // ── Browser panel: reload + honest failure reporting ───────────────────
  // The content frame is sandboxed to an opaque origin, so the panel cannot
  // read what happened inside it — a refused fetch just renders as a raw
  // error page ("Internal Server Error"), which tells the user nothing and
  // in the most common case is actively misleading: the real cause is simply
  // that web mode is off. The proxy endpoint IS same-origin (next.config
  // rewrites /api/* to the backend), so we can probe it directly, read the
  // status + X-Proxy-Error header, and say what is actually wrong.
  const [browserReloadKey, setBrowserReloadKey] = useState(0)
  const [browserIssue, setBrowserIssue] = useState<null | { kind: 'web_off' | 'offline' | 'error'; detail: string }>(null)

  const activeFrameSrc = resolvedFrameSrcGated
    ? `${resolvedFrameSrcGated}${resolvedFrameSrcGated.includes('?') ? '&' : '?'}_r=${browserReloadKey}`
    : undefined

  useEffect(() => {
    if (!resolvedFrameSrcGated) { setBrowserIssue(null); return }
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(resolvedFrameSrcGated, { method: 'GET', credentials: 'same-origin' })
        if (cancelled) return
        if (res.ok) { setBrowserIssue(null); return }
        const reason = res.headers.get('X-Proxy-Error') || ''
        if (res.status === 403 || /internet access is disabled/i.test(reason)) {
          setBrowserIssue({ kind: 'web_off', detail: reason || 'Internet access is disabled' })
        } else {
          setBrowserIssue({ kind: 'error', detail: reason || `${res.status} ${res.statusText}` })
        }
      } catch (err) {
        if (!cancelled) {
          setBrowserIssue({ kind: 'offline', detail: 'The backend is not reachable.' })
        }
      }
    })()
    return () => { cancelled = true }
  }, [resolvedFrameSrcGated, browserReloadKey])

  // Reload: re-probe and re-mount the frame. This is what the user presses
  // after flipping web mode on — the connection is established on retry.
  const handleBrowserReload = useCallback(() => {
    setBrowserIssue(null)
    setBrowserReloadKey(k => k + 1)
  }, [])

  // Height of the browser panel's own chrome (tab bar + address bar) stacked
  // above the viewport. The nav overlay needs this to centre its orb on the
  // VIEWPORT rather than on the panel box, and to extend its top wash far
  // enough that the chrome is lit as part of the same surface.
  const browserChromeInset = useMemo(() => {
    const active = tabs.find(t => t.id === activeTabId)
    const tabBar = tabs.length > 0 ? BROWSER_TAB_STRIP_H : 0
    // The address bar renders only on the default web-tab branch.
    const chromeless = active?.type === 'dashboard' || active?.type === 'code' || active?.type === 'html'
    return tabBar + (chromeless ? 0 : BROWSER_ADDRESS_BAR_H)
  }, [tabs, activeTabId]);

  const openTab = useCallback((msg: OpenTabMsg) => {
    setTabs(prev => {
      const existing = prev.findIndex(t => t.id === msg.id)
      const tab: Tab = {
        id: msg.id,
        type: msg.tab_type,
        title: msg.title,
        data: msg.data,
        url: msg.url,
        content: msg.content,
        language: msg.language,
      }
      if (existing >= 0) {
        const next = [...prev]
        next[existing] = { ...next[existing], ...tab }
        return next
      }
      return [...prev, tab]
    })
    // REQ-11 (T13): never force the ACTIVE tab to a url-less dashboard tab
    // that has nothing to show — that is how the panel got hijacked to a
    // blank/empty view while the crawl's real content lived elsewhere.
    const isContentless = msg.tab_type === 'dashboard' && !msg.url && !msg.data
    if (!isContentless) setActiveTabId(msg.id)
  }, [])

  // ── REQ-15 (specs/vision-browser-stage, T12b): ONE Live Reading surface ──
  // The old behavior opened a NEW TAB per fetched page AND auto-activated it —
  // the viewport already jumped page-to-page while the strip accumulated
  // history duplicating the PlanCard's source list. Now: one stable tab whose
  // CAPTURE PROVENANCE is rewritten per page event (useActiveFrameSrc resolves
  // the frame src from provenance, so a src swap is the only navigation
  // primitive). Replay contract unchanged: same capture bytes, same badge,
  // proxy routing for non-stored pages.
  //
  // OPT GATE: ONE ref-held coalesce timer (300ms latest-wins so concurrent
  // dispatch cannot flicker through intermediate arrivals), cleared on unmount;
  // the processed-set keeps snapshot replays idempotent.
  const LIVE_READING_TAB_ID = 'live-reading';
  const processedCrawlNavRef = useRef<Set<string>>(new Set());
  const navCoalesceRef = useRef<{
    timer: ReturnType<typeof setTimeout> | null;
    latest: null | { jobId: string; addr: number; url: string; title: string; replayable: boolean };
  }>({ timer: null, latest: null });
  // Pin mode: selecting a source pauses following; the LIVE pill resumes.
  const [pinnedSource, setPinnedSource] = useState<{ jobId: string; addr: number } | null>(null);

  useEffect(() => {
    for (const p of crawlState.pages) {
      if (!p.jobId) continue
      const addr = p.capturePage ?? p.pageNumber
      if (addr == null) continue  // no capture to show
      const key = `${p.jobId}:${addr}`
      if (processedCrawlNavRef.current.has(key)) continue
      processedCrawlNavRef.current.add(key)
      if (pinnedSource) continue // pinned: keep showing the user's selection
      navCoalesceRef.current.latest = {
        jobId: p.jobId,
        addr,
        url: p.url,
        title: p.title || p.url,
        replayable: p.captureAvailable !== false,
      }
      if (navCoalesceRef.current.timer) clearTimeout(navCoalesceRef.current.timer)
      navCoalesceRef.current.timer = setTimeout(() => {
        const l = navCoalesceRef.current.latest
        if (!l) return
        navCoalesceRef.current.latest = null
        openTab({
          id: LIVE_READING_TAB_ID,
          tab_type: 'web',
          title: l.title,
          url: l.url,
        } as OpenTabMsg)
        const provenance = l.replayable
          ? { captureJobId: l.jobId, capturePageNumber: l.addr, captureFetchedAt: new Date().toISOString() }
          : {}
        setTabs(prev => prev.map(t => (t.id === LIVE_READING_TAB_ID ? { ...t, ...provenance } : t)))
      }, 300)
    }
  }, [crawlState.pages, openTab, pinnedSource]);

  // Unmount hygiene: never leave the coalesce timer behind (OPT GATE).
  useEffect(() => () => {
    if (navCoalesceRef.current.timer) clearTimeout(navCoalesceRef.current.timer)
  }, [])

  // REQ-15 AC3: sources are browsable from the source list — RichDocument's
  // source rows dispatch this; it PINS the reading surface to that capture.
  useEffect(() => {
    const onViewSource = (e: Event) => {
      const d = (e as CustomEvent<{ job_id?: string; capture_page?: number; url?: string; title?: string }>).detail
      if (!d?.job_id || d.capture_page == null) return
      setPinnedSource({ jobId: d.job_id, addr: d.capture_page })
      openTab({
        id: LIVE_READING_TAB_ID,
        tab_type: 'web',
        title: d.title || d.url || 'Pinned source',
        url: d.url || '',
      } as OpenTabMsg)
      setTabs(prev => prev.map(t =>
        t.id === LIVE_READING_TAB_ID
          ? { ...t, captureJobId: d.job_id, capturePageNumber: d.capture_page!, captureFetchedAt: new Date().toISOString() }
          : t,
      ))
    }
    window.addEventListener('iris:view_source', onViewSource as EventListener)
    return () => window.removeEventListener('iris:view_source', onViewSource as EventListener)
  }, [openTab])

  const closeTab = useCallback((tabId: string) => {
    setTabs(prev => {
      const next = prev.filter(t => t.id !== tabId)
      return next
    })
    setActiveTabId(prev => {
      if (prev !== tabId) return prev
      // Fall back to the last remaining tab
      const remaining = tabs.filter(t => t.id !== tabId)
      return remaining.length > 0 ? remaining[remaining.length - 1].id : null
    })
  }, [tabs])

  const { getThemeConfig } = useBrandColor();
  const localTheme = getThemeConfig();

  const {
    currentCategory,
    fieldValues: contextFieldValues,
    fieldErrors,
    voiceState,
    selectCategory,
    selectSectionWs,
    updateCardValue: contextUpdateCardValue,
    updateField: wsUpdateField,
    clearFieldError,
    confirmCard,
    sendMessage,
  } = useNavigation();

  // Local field-value store — single source of truth for reads AND writes within this component.
  // Initialized from the WS-supplied contextFieldValues and kept in sync via iris:initial_state.
  // Writing through localUpdateField ensures the UI reflects user changes immediately, without
  // waiting for a backend round-trip (which only updates contextFieldValues via WS).
  //
  // Persists to localStorage under "iris-dash-field-values" to survive DashboardWing un-mounts
  // (which happen every time the user navigates away from the dashboard).
  const [localFieldValues, setLocalFieldValues] = useState<Record<string, Record<string, any>>>(
    () => {
      // 1) Check localStorage cache first (survives component unmounts)
      try {
        const cached = localStorage.getItem('iris-dash-field-values');
        if (cached) {
          const parsed = JSON.parse(cached);
          if (parsed && typeof parsed === 'object' && Object.keys(parsed).length > 0) {
            return parsed as Record<string, Record<string, any>>;
          }
        }
      } catch {}
      // 2) Fall through to WS context or empty
      return (propFieldValues || contextFieldValues || {}) as Record<string, Record<string, any>>;
    }
  );

  // Persist localFieldValues to localStorage on every change.
  useEffect(() => {
    try {
      localStorage.setItem('iris-dash-field-values', JSON.stringify(localFieldValues));
    } catch {}
  }, [localFieldValues]);

  // Seed localFieldValues once contextFieldValues arrives from the WS hook on first load.
  // Clear stale card value cache — the new provider→models mapping uses
  // {label, value} objects which can conflict with old localStorage entries.
  useEffect(() => {
    try { localStorage.removeItem('iris-card-values'); } catch {}
  }, []);

  // NOTE: model_inference / model_selection are deliberately NOT auto-synced
  // into localFieldValues anymore. ModelInferenceSection owns its state and
  // live-sends every change (sendModelSelection / sendRoleBinding /
  // sendInferenceMode); syncing model_provider here from the role binding made
  // the bottom APPLY re-send a STALE provider (the binding is not updated by
  // APPLY PROVIDER) and reverted the user's choice — the recurring
  // cerebras↔cohere cross-contamination. handleApplySettings skips these
  // sections; see the filter there.

  const seededRef = useRef(false);
  useEffect(() => {
    if (!seededRef.current && contextFieldValues && Object.keys(contextFieldValues).length > 0) {
      setLocalFieldValues((prev) => {
        // Merge WS-supplied values OVER the localStorage-backed values so a
        // reopen can never clobber the user's saved settings with backend
        // defaults. The backend only hydrates field_values that were actually
        // persisted to disk; if none were (or a section is missing), it sends
        // defaults — and a naive replace would wipe the user's localStorage.
        const merged: Record<string, Record<string, any>> = { ...contextFieldValues };
        for (const [sec, vals] of Object.entries(prev || {})) {
          merged[sec] = { ...(merged[sec] || {}), ...(vals || {}) };
        }
        return merged;
      });
      seededRef.current = true;
    }
  }, [contextFieldValues]);

  // Wire CustomEvent listeners for tab system and crawler status.
  // iris:open_tab / iris:close_tab are dispatched by useIRISWebSocket when
  // the backend sends open_tab / close_tab WS messages.
  useEffect(() => {
    const onOpenTab = (e: Event) => {
      openTab((e as CustomEvent).detail)
    }
    const onCloseTab = (e: Event) => {
      closeTab(((e as CustomEvent).detail as { id: string }).id)
      // If the browser panel isn't visible, open it so the user sees the tab
      if (activeSubApp !== 'browser') setActiveSubApp('browser')
    }
    const onOpenTabBrowser = (e: Event) => {
      onOpenTab(e)
      if (activeSubApp !== 'browser') setActiveSubApp('browser')
    }
    // REQ-12 (T17): capture-provenance attachment for web tabs is now derived
    // from CrawlProvider's pages array (see the tab-creation effect above);
    // the duplicated iris:crawler_page_fetched listener was deleted.
    window.addEventListener('iris:open_tab', onOpenTabBrowser)
    window.addEventListener('iris:close_tab', onCloseTab)
    return () => {
      window.removeEventListener('iris:open_tab', onOpenTabBrowser)
      window.removeEventListener('iris:close_tab', onCloseTab)
    }
  }, [openTab, closeTab, activeSubApp])

  // Local write handler — updates our local store so FieldRow reflects changes instantly,
  // AND sends the individual field change to the backend via WebSocket (live update).
  // This means the backend always has the latest value, not just after pressing Apply.
  const localUpdateField = useCallback((sectionId: string, fieldId: string, value: any) => {
    setLocalFieldValues(prev => ({
      ...prev,
      [sectionId]: { ...(prev[sectionId] || {}), [fieldId]: value },
    }));
    // Live-update the backend via WebSocket (optimistic — does not block UI)
    if (wsUpdateField) wsUpdateField(sectionId, fieldId, value);
    // Also propagate to external store if provided via props
    if (propUpdateField) propUpdateField(sectionId, fieldId, value);
  }, [propUpdateField, wsUpdateField]);

  // Listen for model-selected events from the ModelBrowserPanel
  useEffect(() => {
    const onModelSelected = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail?.path) {
        localUpdateField('inference_mode', 'iris_local_model_path', detail.path)
        if (detail.native_ctx) {
          localUpdateField('inference_mode', 'iris_local_ctx', detail.native_ctx)
        }
      }
    }
    window.addEventListener('model-selected', onModelSelected)
    return () => window.removeEventListener('model-selected', onModelSelected)
  }, [localUpdateField])

  // NOTE: the `model-load-request` CustomEvent listener that used to live here
  // was removed (2026-08-17). ModelBrowserPanel is rendered directly below, so
  // it now takes `sendMessage` as a prop and calls `load_local_model` itself.
  // The bounce through `window` added a failure mode and nothing else: when
  // this listener was not mounted the panel's click disappeared silently.

  const fieldValues = localFieldValues;
  const updateField = localUpdateField;

  // populated from backend available_models WS message (used by local_model section)
  const [audioInputDevices, setAudioInputDevices] = useState<string[]>(['Default Input', 'Internal Microphone']);
  const [audioOutputDevices, setAudioOutputDevices] = useState<string[]>(['Default Output', 'Internal Speakers']);
  const [wakeWords, setWakeWords] = useState<string[]>([]);

  // Request backend state on mount and sync dynamic data (models, devices, wake words)
  // Uses the same custom-event pattern as SidePanel so both views stay in sync.
  useEffect(() => {
    if (sendMessage) sendMessage('request_state', {});
    // T10b (REQ-7 AC1/AC2): seed the MODEL STATUS badge from the backend's
    // live model-manager state on mount (and on every reconnect, since this
    // effect re-runs whenever `sendMessage` identity changes). Reuses the
    // EXISTING `get_local_model_status` WS handler (iris_gateway.py:685),
    // which had no frontend caller before this. Its response comes back as
    // mgr.get_status() (loaded: boolean, no `status`/`error` key), which
    // useIRISWebSocket.ts's existing "local_model_status" fallback chain
    // already maps to loaded/unloaded correctly. Because it reflects the
    // manager's LIVE state rather than the persisted config, a reload where
    // nothing is actually listening naturally reconciles to UNLOADED even if
    // the config still claims "loaded".
    if (sendMessage) sendMessage('get_local_model_status', {});
    // REQ-5 (specs/vision-browser-stage): seed the vision lifecycle chip on
    // mount/reconnect — transitions alone miss a page reload.
    if (sendMessage) sendMessage('get_vision_status', {});

    const handleInitialState = (event: CustomEvent) => {
      const state = event.detail?.state || {};
      const fv = state.field_values || state.fieldValues;
      if (fv && typeof fv === 'object') {
        // Merge backend values into our local store so FieldRow displays them immediately.
        setLocalFieldValues(prev => {
          const next = { ...prev };
          Object.entries(fv as Record<string, any>).forEach(([sectionId, sectionValues]) => {
            if (sectionValues && typeof sectionValues === 'object') {
              next[sectionId] = { ...(next[sectionId] || {}), ...(sectionValues as Record<string, any>) };
            }
          });
          return next;
        });
        seededRef.current = true;
      }
    };

    const handleAvailableModels = (_event: CustomEvent) => {
      // available_models event is forwarded to other consumers via iris:ws_message
      // from the WS hook. No local state needed — model_inference uses useInferenceState.
    };

    const handleAudioDevices = (event: CustomEvent) => {
      const inputs  = (event.detail?.input_devices  || []).map((d: any) => d.name || d.index || d).filter(Boolean);
      const outputs = (event.detail?.output_devices || []).map((d: any) => d.name || d.index || d).filter(Boolean);
      if (inputs.length  > 0) setAudioInputDevices(inputs);
      if (outputs.length > 0) setAudioOutputDevices(outputs);
    };

    const handleWakeWords = (event: CustomEvent) => {
      const words = (event.detail?.wake_words || []).map((w: any) => w.display_name || w.filename || w).filter(Boolean);
      if (words.length > 0) setWakeWords(words);
    };

    // T10b (REQ-7 AC1/AC2): receives the computed status string dispatched by
    // useIRISWebSocket.ts's "local_model_status" case — both the seed reply
    // triggered above AND any later live push (load/unload/error) during this
    // session. Merges directly into localFieldValues so it is not dropped by
    // the one-time seededRef guard on contextFieldValues.
    const handleLocalModelStatus = (event: CustomEvent) => {
      const status = event.detail?.status;
      if (typeof status !== 'string') return;
      setLocalFieldValues((prev) => ({
        ...prev,
        local_model: { ...(prev.local_model || {}), local_model_status: status },
        'local-model-card': { ...(prev['local-model-card'] || {}), local_model_status: status },
      }));
    };

    window.addEventListener('iris:initial_state',   handleInitialState   as EventListener);
    window.addEventListener('iris:available_models', handleAvailableModels as EventListener);
    window.addEventListener('iris:audio_devices',    handleAudioDevices    as EventListener);
    window.addEventListener('iris:wake_words_list',  handleWakeWords       as EventListener);
    window.addEventListener('iris:local_model_status', handleLocalModelStatus as EventListener);

    return () => {
      window.removeEventListener('iris:initial_state',   handleInitialState   as EventListener);
      window.removeEventListener('iris:available_models', handleAvailableModels as EventListener);
      window.removeEventListener('iris:audio_devices',    handleAudioDevices    as EventListener);
      window.removeEventListener('iris:wake_words_list',  handleWakeWords       as EventListener);
      window.removeEventListener('iris:local_model_status', handleLocalModelStatus as EventListener);
    };
  }, [sendMessage]);

  // Fetch device lists and models whenever the relevant tab is active
  useEffect(() => {
    if (!sendMessage) return;
    if (activeTab === 'agent') {
      // Fetch available models for the local_model section dropdown.
      // Provider models are now sourced from GET /api/inference/state via useInferenceState().
      sendMessage('get_available_models', {});
    }
    if (activeTab === 'voice') {
      sendMessage('get_audio_devices', {});
      sendMessage('get_wake_words', {});
    }
  }, [activeTab, sendMessage, fieldValues]);

  useEffect(() => {
    if (currentCategory && currentCategory !== 'voice' && currentCategory !== 'dashboard') {
      setActiveTab(currentCategory);
    }
  }, [currentCategory]);

  const sectionsData = useSectionsData();
  const activeSections = sectionsData[activeTab] || [];

  const VIRTUAL_SUB_APPS = new Set(['browser', 'marketplace', 'models', 'inference_console', 'hub']);

  const handleSubAppChange = useCallback((appId: string) => {
    setActiveSubApp(appId);
    if (VIRTUAL_SUB_APPS.has(appId)) {
      setIsSidebarHidden(true);
    } else {
      setIsSidebarHidden(false);
      // Only send select_category for real backend categories
      selectCategory(appId as any);
    }
  }, [selectCategory]);

  // Listen for card action events (e.g., button fields with action='open_models_screen')
  useEffect(() => {
    const handler = (e: CustomEvent) => {
      const { action } = e.detail || {};
      if (action === 'open_models_screen') {
        handleSubAppChange('models');
        if (spotlightState !== 'DASHBOARD_SPOTLIGHT') {
          onRequestSpotlight?.();
        }
      } else if (action === 'open_inference_console') {
        handleSubAppChange('inference_console');
        if (spotlightState !== 'DASHBOARD_SPOTLIGHT') {
          onRequestSpotlight?.();
        }
      } else if (action === 'test_output') {
        // Test output device: send WS message to play test sound
        sendMessage?.('test_audio', { type: 'output' });
      } else if (action === 'test_input') {
        // Test input device: send WS message to capture and report mic level
        sendMessage?.('test_audio', { type: 'input' });
      } else if (action === 'load_local_model') {
        console.warn('[dashboard] load_local_model action: use Model Browser panel instead');
      } else if (action === 'unload_local_model') {
        console.warn('[dashboard] unload_local_model action: use Model Browser panel instead');
      } else if (action === 'start_swarm') {
        console.warn('[dashboard] start_swarm: swarm sub-app not wired yet');
      } else if (action === 'stop_swarm') {
        console.warn('[dashboard] stop_swarm: swarm sub-app not wired yet');
      }
    };
    window.addEventListener('iris:card_action', handler as EventListener);
    return () => window.removeEventListener('iris:card_action', handler as EventListener);
  }, [handleSubAppChange, spotlightState, onRequestSpotlight, sendMessage]);

  // ── Web search: surface the browser AT THE START of the crawl ─────────────
  // The panel used to reach the browser only when the crawl's OPEN_TAB
  // arrived — and that is emitted once, at the very END of research(), as a
  // `dashboard` summary tab. So for the whole search the user sat on whatever
  // sub-app was open, and the browser appeared just as the work finished.
  // crawler_started is the first event of the run, so switching on it puts the
  // frame up before the pages land in it.
  //
  // handleSubAppChange (not setActiveSubApp) so the sidebar collapses exactly
  // as it does when the browser is opened by hand.
  //
  // REQ-12 (T17): crawl events now flow through CrawlProvider (the duplicated
  // iris:crawler_started / iris:crawler_page_fetched / iris:crawler_complete /
  // iris:crawler_error listeners were deleted). Edge-detect the provider's
  // active flag so the browser surfaces once per crawl start.
  const wasCrawlActiveRef = useRef(false);
  useEffect(() => {
    if (crawlState.active && !wasCrawlActiveRef.current) {
      handleSubAppChange('browser')
    }
    wasCrawlActiveRef.current = crawlState.active
  }, [crawlState.active, handleSubAppChange])

  // Mirror provider crawl state into the header pill's local display state.
  // The provider (useCrawl) is the single source of truth; this local copy
  // exists so the finished-pill timeout below can clear the pill without
  // touching provider state. Visuals are unchanged (REQ-11 AC3).
  useEffect(() => {
    setCrawler({
      active: crawlState.active,
      query: crawlState.query,
      pagesDone: crawlState.pages.length,
      pagesTotal: crawlState.total,
      error: crawlState.error,
    })
  }, [crawlState.active, crawlState.query, crawlState.pages.length, crawlState.total, crawlState.error])

  // Clear a finished search's pill so a stale error does not sit in the header
  // forever. Only the settled states time out — an active crawl never does.
  useEffect(() => {
    if (crawler.active) return
    if (!crawler.error && crawler.pagesDone === 0) return
    const t = setTimeout(
      () => setCrawler({ active: false, query: '', pagesDone: 0, pagesTotal: 0, error: null }),
      crawler.error ? 6000 : 2500,
    )
    return () => clearTimeout(t)
  }, [crawler.active, crawler.error, crawler.pagesDone])

  // Navigate to a sub-app when initialSubApp is set from outside (e.g., Browse button in WheelView)
  useEffect(() => {
    if (initialSubApp) {
      setActiveSubApp(initialSubApp);
      if (['browser', 'marketplace', 'models', 'inference_console'].includes(initialSubApp)) {
        setIsSidebarHidden(true);
      }
    }
  }, [initialSubApp]);

  const toggleSection = (sectionId: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      if (next.has(sectionId)) next.delete(sectionId);
      else next.add(sectionId);
      return next;
    });
  };

  const applyCooldownRef = useRef(false);

  // Snapshot of localFieldValues captured each time handleApplySettings runs to
  // completion.  Used by handleCloseWithSave to detect unsaved changes and
  // auto-save them before navigating away.  Without this, closing the dashboard
  // via X / Escape / backdrop without clicking APPLY silently dropped every
  // setting change (voice, model, theme, etc.).
  const lastAppliedRef = useRef<Record<string, Record<string, any>> | null>(null);

  const handleApplySettings = useCallback(async () => {
    // Guard: prevent rapid re-clicks (2s cooldown on top of state guard)
    if (applyCooldownRef.current) return;
    applyCooldownRef.current = true;

    setApplyStatus("applying");
    try {
      // Send 'confirm_card' for EVERY section that has values, not just the
      // currently-visible tab.  This way voice / model / theme changes are
      // persisted regardless of which tab the user was on when they clicked APPLY.
      // model_inference / model_selection are self-managed by
      // ModelInferenceSection: it live-sends every change (sendModelSelection /
      // sendRoleBinding / sendInferenceMode) the moment it happens. Re-sending
      // them from here with localFieldValues pushes STALE values — e.g. a
      // model_provider that was auto-synced from a role binding which APPLY
      // PROVIDER never updated — and reverts the user's choice to the previous
      // provider (the recurring cerebras↔cohere cross-contamination). These
      // sections must be excluded from the APPLY loop.
      const allSections = Object.entries(localFieldValues).filter(
        ([sectionId, values]) =>
          sectionId !== 'model_inference' &&
          sectionId !== 'model_selection' &&
          values &&
          typeof values === 'object' &&
          Object.keys(values).length > 0
      );
      // Sections are independent, so save them CONCURRENTLY. This loop used to
      // await each POST in turn; measured 2026-08-26, /api/config/save answers
      // in 3-4ms warm (412ms cold), so serial cost was small but it scaled with
      // the number of sections for no reason.
      for (const [sectionId, sectionValues] of allSections) {
        // Try WebSocket first (fast path)
        if (sendMessage) {
          sendMessage('confirm_card', {
            section_id: sectionId,
            values: sectionValues,
          });
        }
      }
      await Promise.all(allSections.map(([sectionId, sectionValues]) =>
        fetch('/api/config/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            section_id: sectionId,
            card_id: sectionId,
            values: sectionValues,
          }),
        }).catch((fetchErr) => {
          console.warn('[DarkGlassDashboard] HTTP fallback failed:', fetchErr);
        })
      ));
      // The 2s guard against duplicate subprocess/server launches is enforced
      // by `applyCooldownRef`, whose timer is set in the `finally` below and
      // runs regardless of this function's duration. This used to ALSO
      // `await new Promise(r => setTimeout(r, 2000))` here, which blocked the
      // handler itself: every APPLY took at least 2s, and because
      // handleCloseWithSave awaited this function, so did every close.
      // Measured: the saves themselves take ~3-4ms each. The sleep WAS the
      // wait. Removing it does not weaken the guard — it only stops the UI
      // pretending to work for 2 seconds after the work is done.
      // Record what we just persisted so handleCloseWithSave can detect whether
      // there are further unsaved edits before the next close.
      lastAppliedRef.current = JSON.parse(JSON.stringify(localFieldValues));
    } catch (error) {
      console.error("[DarkGlassDashboard] Apply failed:", error);
    } finally {
      setIsApplying(false);
      setApplyStatus("applied");
      setTimeout(() => setApplyStatus("idle"), 2000);
      setTimeout(() => { applyCooldownRef.current = false; }, 2000);
    }
  }, [sendMessage, activeSections, localFieldValues]);

  // Close handler — auto-saves unsaved changes before navigating away.
  // Fires handleApplySettings (without the cooldown guard, since this is the
  // only chance to persist before unmount) if localFieldValues differs from
  // the last successfully-applied snapshot.  Idempotent: if nothing changed,
  // it just calls onClose.
  const handleCloseWithSave = useCallback(async () => {
    try {
      // DO NOT await the apply here. The unmount cleanup below is documented
      // as "the single chokepoint that catches EVERY close path (X button via
      // handleCloseWithSave, Escape via dashboard-wing, backdrop click,
      // navigation)" and it fires the same POSTs with keepalive:true, which is
      // precisely designed to outlive unmount. Awaiting handleApplySettings
      // here therefore bought NOTHING and cost the user the full apply
      // duration on every close — the symptom being that closing the panel
      // "seems to trigger apply and takes a considerable long time".
      //
      // Closing now returns immediately; the cleanup persists. Dirty-checking
      // still works because lastAppliedRef is untouched on this path, so the
      // cleanup sees isDirty === true and saves.
      const current = JSON.stringify(localFieldValues);
      const last = lastAppliedRef.current ? JSON.stringify(lastAppliedRef.current) : null;
      if (current !== last && sendMessage) {
        // WebSocket is instant and fire-and-forget; the HTTP keepalive POSTs in
        // the unmount cleanup are the reliable half of the pair.
        Object.entries(localFieldValues).forEach(([sectionId, values]) => {
          if (
            sectionId !== 'model_inference' &&
            sectionId !== 'model_selection' &&
            values && typeof values === 'object' &&
            Object.keys(values).length > 0
          ) {
            sendMessage('confirm_card', { section_id: sectionId, values });
          }
        });
      }
    } catch (e) {
      console.warn('[DarkGlassDashboard] save-on-close failed:', e);
    } finally {
      onClose?.();
    }
    // handleApplySettings is deliberately NOT a dependency any more: this path
    // no longer calls it. sendMessage is, because the fast-path notify above
    // uses it.
  }, [localFieldValues, sendMessage, onClose]);

  // Ref mirror of localFieldValues so the unmount cleanup (which captures a
  // stale closure) always reads the LATEST values.  Updated every render.
  const localFieldValuesRef = useRef(localFieldValues);
  localFieldValuesRef.current = localFieldValues;

  // UNMOUNT save — the single chokepoint that catches EVERY close path
  // (X button via handleCloseWithSave, Escape via dashboard-wing, backdrop
  // click, navigation).  The dashboard unmounts on all of them because
  // dashboard-wing renders it inside `{isOpen && (<DarkGlassDashboard .../>)}`.
  // Without this, closing via Escape/backdrop silently dropped unsaved settings.
  //
  // React cleanup runs synchronously and can't await, so we fire HTTP POSTs
  // directly (fire-and-forget) instead of awaiting handleApplySettings.  The
  // HTTP /api/config/save path is more reliable than WebSocket during teardown
  // because the WS may be mid-close.
  const savedOnCloseRef = useRef(false);
  useEffect(() => {
    return () => {
      if (savedOnCloseRef.current) return;  // guard against double-invoke
      const current = localFieldValuesRef.current;
      const last = lastAppliedRef.current;
      const isDirty = !last || JSON.stringify(current) !== JSON.stringify(last);
      if (!isDirty) return;
      savedOnCloseRef.current = true;
      // Fire HTTP saves for every populated section (same shape as
      // handleApplySettings).  keepalive:true lets the request outlive unmount.
      try {
        Object.entries(current).forEach(([sectionId, sectionValues]) => {
          if (sectionValues && typeof sectionValues === 'object' && Object.keys(sectionValues).length > 0) {
            fetch('/api/config/save', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ section_id: sectionId, card_id: sectionId, values: sectionValues }),
              keepalive: true,
            }).catch(() => { /* best-effort on close */ });
          }
        });
      } catch (e) {
        console.warn('[DarkGlassDashboard] unmount save failed:', e);
      }
    };
  }, []);

  const handleBrowserNavigate = (url: string) => {
    const normalized = /^https?:\/\//i.test(url) ? url : `https://${url}`;
    // T12: panel-owned nav history (REQ-2 AC1). The sandboxed frame cannot be
    // reached into, so "back" is a panel-level stack, not window.history (the
    // old call at :1395 navigated the APP, not the page).
    setBrowserHistory(prev => [...prev.slice(-49), browserUrl]);
    setBrowserUrl(normalized);
    setBrowserInput(normalized);
  };

  const handleBrowserBack = () => {
    setBrowserHistory(prev => {
      if (prev.length === 0) return prev;
      const next = [...prev];
      const previous = next.pop()!;
      setBrowserUrl(previous);
      setBrowserInput(previous);
      return next;
    });
  };

  const handleBrowserInputSubmit = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleBrowserNavigate(browserInput);
    }
  };

  const glowColor = localTheme.glow?.color || ACCENT_COLOR;

  const handleTabChange = useCallback((tabId: string) => {
    setActiveTab(tabId);
    setActiveSubApp(null);
    selectSectionWs(tabId);
    // Persist so the app reopens on the same tab
    if (typeof window !== "undefined") {
      localStorage.setItem('iris_active_tab_v1', tabId)
    }
  }, [selectSectionWs]);

  // T7 (REQ-7 AC2): SURFACES view — dedicated 36px circular orbs with live
  // ambient telemetry badges fed from EXISTING stores.
  const SURFACE_NODES = [
    {
      id: 'hub',
      label: 'Workspace Hub',
      icon: LayoutDashboard,
      badge: { text: `${runningAgentTasks} Running`, live: runningAgentTasks > 0 },
    },
    {
      id: 'browser',
      label: 'Browser Surface',
      icon: Globe,
      // [● Live Web] ← browser-surface / crawl active state (existing store).
      badge: crawlState.active
        ? { text: 'Live Web', live: true }
        : { text: 'Web Idle', live: false },
    },
    {
      id: 'marketplace',
      label: 'Marketplace & Models',
      icon: ShoppingBag,
      // [● N Tools] ← tool registry count; null source renders dimmed.
      badge:
        mcpToolCount != null
          ? { text: `${mcpToolCount} Tools`, live: mcpToolCount > 0 }
          : { text: '— Tools', live: false, dimmed: true },
    },
  ];

  const renderNavigationRail = () => (
    <motion.nav
      initial={false}
      animate={{
        width: isSidebarHidden ? 0 : (isRailExpanded ? 160 : 56),
        opacity: isSidebarHidden ? 0 : 1,
        x: isSidebarHidden ? -20 : 0
      }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className="flex flex-col h-full border-r relative z-20 overflow-visible shrink-0"
      style={{
        borderColor: 'rgba(255,255,255,0.06)',
        backgroundColor: 'rgba(0,0,0,0.3)'
      }}
    >
      {/* REQ-7 AC4: single unified <nav> container — internal scroll lists
          handle content overflow; the nav itself is overflow-visible so the
          seam affordance's right 8px is never clipped. */}

      <div className="flex h-16 items-center px-4 mb-2 gap-3 border-b border-white/[0.03] shrink-0">
        {isRailExpanded ? (
          <motion.div className="flex items-center" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <span className="text-[14px] font-black tracking-[0.1em] text-white uppercase">
              IRIS <span style={{ color: glowColor }}>VOICE</span>
            </span>
          </motion.div>
        ) : (
          <div className="w-full flex justify-center">
            <div className="w-6 h-6 rounded-full" style={{ backgroundColor: ACCENT_COLOR }} />
          </div>
        )}
      </div>

      {/* REQ-7 AC1: dual-mode segmented glass pill switch — collapses to a
          2-pip toggle [✦ | ⚙] when the rail is 56px. */}
      {isRailExpanded ? (
        <div className="px-3 mb-4 pt-1 flex gap-1 shrink-0">
          {[
            { id: 'surfaces', label: '✦ SURFACES' },
            { id: 'settings', label: '⚙ SETTINGS' },
          ].map((m) => (
            <button
              key={m.id}
              onClick={() => setRailMode(m.id as 'surfaces' | 'settings')}
              className="flex-1 h-6 rounded-full text-[8px] font-black tracking-wider transition-all"
              style={{
                background: railMode === m.id ? `${glowColor}18` : 'rgba(255,255,255,0.03)',
                color: railMode === m.id ? glowColor : 'rgba(255,255,255,0.4)',
                border: `1px solid ${railMode === m.id ? `${glowColor}35` : 'rgba(255,255,255,0.05)'}`,
              }}
            >
              {m.label}
            </button>
          ))}
        </div>
      ) : (
        <div className="px-2 mb-4 pt-1 flex flex-col gap-2 items-center shrink-0">
          <button
            onClick={() => setRailMode('surfaces')}
            title="Surfaces"
            className="w-6 h-6 rounded-full flex items-center justify-center transition-all"
            style={{
              color: railMode === 'surfaces' ? glowColor : 'rgba(255,255,255,0.35)',
              background: railMode === 'surfaces' ? `${glowColor}18` : 'transparent',
            }}
          >
            <Sparkles size={12} />
          </button>
          <button
            onClick={() => setRailMode('settings')}
            title="Settings"
            className="w-6 h-6 rounded-full flex items-center justify-center transition-all"
            style={{
              color: railMode === 'settings' ? glowColor : 'rgba(255,255,255,0.35)',
              background: railMode === 'settings' ? `${glowColor}18` : 'transparent',
            }}
          >
            <Settings size={12} />
          </button>
        </div>
      )}

      <div className="flex-1 py-1 overflow-y-auto overflow-x-hidden scrollbar-hide">
        {railMode === 'surfaces' ? (
          /* REQ-7 AC2: SURFACES — 36px circular nodes with live badges */
          <div className="flex flex-col gap-3 px-2">
            {SURFACE_NODES.map((node) => {
              const Icon = node.icon;
              const isActive = activeSubApp === node.id;
              return (
                <button
                  key={node.id}
                  onClick={() => handleSubAppChange(node.id)}
                  title={isRailExpanded ? node.label : `${node.label} — ${node.badge.text}`}
                  className="group w-full flex items-center transition-all duration-200 relative rounded-full"
                  style={{
                    height: 36,
                    backgroundColor: isActive ? `${glowColor}2E` : 'transparent',
                    border: isActive ? `1px solid ${glowColor}40` : '1px solid transparent',
                    boxShadow: isActive ? `0 0 12px ${glowColor}26` : 'none',
                    ...(isRailExpanded
                      ? { paddingLeft: 12, paddingRight: 12, justifyContent: 'flex-start', gap: 10 }
                      : { width: 36, margin: '0 auto', justifyContent: 'center' }),
                  }}
                >
                  <Icon className="w-4 h-4 flex-shrink-0" style={{ color: isActive ? glowColor : 'rgba(255,255,255,0.35)' }} />
                  {isRailExpanded && (
                    <span className="flex flex-col min-w-0">
                      <span className="text-[9px] font-semibold tracking-wide whitespace-nowrap" style={{ color: isActive ? 'white' : 'rgba(255,255,255,0.4)' }}>
                        {node.label}
                      </span>
                      <span
                        className="flex items-center gap-1 text-[8px] whitespace-nowrap"
                        style={{ color: node.badge.live ? glowColor : 'rgba(255,255,255,0.25)', opacity: 'dimmed' in node.badge && node.badge.dimmed ? 0.45 : 1 }}
                      >
                        <span
                          className="w-1 h-1 rounded-full"
                          style={{
                            background: node.badge.live ? glowColor : 'rgba(255,255,255,0.25)',
                            boxShadow: node.badge.live ? `0 0 4px ${glowColor}` : 'none',
                          }}
                        />
                        {node.badge.text}
                      </span>
                    </span>
                  )}
                  {!isRailExpanded && node.badge.live && (
                    <span
                      className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full"
                      style={{ background: glowColor, boxShadow: `0 0 4px ${glowColor}` }}
                    />
                  )}
                </button>
              );
            })}
          </div>
        ) : (
          /* REQ-7 AC3: SETTINGS — all 6 MAIN_NODES_DATA category nodes as
             36px rounded-full buttons */
          <div className="flex flex-col gap-3 px-2">
            {MAIN_NODES_DATA.map((node) => {
              const Icon = node.icon;
              const isActive = activeTab === node.id && !activeSubApp;
              return (
                <button
                  key={node.id}
                  onClick={() => handleTabChange(node.id)}
                  className="group w-full flex items-center justify-center transition-all duration-200 relative rounded-full"
                  style={{
                    height: 36,
                    backgroundColor: isActive ? `${glowColor}2E` : 'transparent',
                    border: isActive ? `1px solid ${glowColor}40` : '1px solid transparent',
                    boxShadow: isActive ? `0 0 12px ${glowColor}26` : 'none',
                    ...(isRailExpanded ? { paddingLeft: 12, paddingRight: 12, justifyContent: 'flex-start', gap: 10 } : { width: 36, margin: '0 auto' }),
                  }}
                  title={isRailExpanded ? undefined : node.label}
                >
                  <Icon className="w-4 h-4 flex-shrink-0" style={{ color: isActive ? glowColor : 'rgba(255,255,255,0.35)' }} />
                  {isRailExpanded && (
                    <span className="text-[10px] font-semibold tracking-wider whitespace-nowrap" style={{ color: isActive ? 'white' : 'rgba(255,255,255,0.35)' }}>
                      {node.label}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="p-4 border-t shrink-0" style={{ borderColor: 'rgba(255,255,255,0.05)' }}>
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 rounded-full bg-white/5 flex items-center justify-center flex-shrink-0">
            <User className="w-4 h-4 text-white/50" />
          </div>
          {isRailExpanded && (
            <div className="flex flex-col min-w-0">
              <span className="text-[11px] font-semibold text-white truncate">Online</span>
              <span className="text-[9px] text-white/40 truncate">
            Model: {(role_bindings.find(r => r.role === 'reasoning')?.instance_id) || (localFieldValues?.local_model?.local_model_path as string) || 'No model'}
          </span>
            </div>
          )}
        </div>
      </div>

      {/* REQ-7 AC5-AC7: seam-anchored chevron affordance + neon laser shimmer.
          Anchored to the rail's right boundary seam at vertical midpoint —
          with width 16 and right -8 the internal X=8 axis sits exactly on the
          1px border. Single unified column of 4 razor micro-chevrons whose
          apex tips terminate on the seam; the shimmer line ignites on hover. */}
      {!isSidebarHidden && (
        <div
          onClick={() => setIsRailExpanded((v) => !v)}
          onMouseEnter={() => setSeamHover(true)}
          onMouseLeave={() => setSeamHover(false)}
          role="button"
          aria-label={isRailExpanded ? 'Collapse navigation rail' : 'Expand navigation rail'}
          title={isRailExpanded ? 'Collapse rail' : 'Expand rail'}
          style={{
            position: 'absolute',
            right: -8,
            top: '50%',
            transform: 'translateY(-50%)',
            width: 16,
            height: 44,
            zIndex: 50,
            cursor: 'pointer',
          }}
        >
          <svg
            width="16"
            height="44"
            viewBox="0 0 16 44"
            fill="none"
            style={{
              display: 'block',
              overflow: 'visible',
              filter: seamHover
                ? `drop-shadow(0 0 6px ${glowColor}) drop-shadow(0 0 2px #ffffff)`
                : 'none',
              transition: 'filter 0.15s ease',
            }}
          >
            <defs>
              <linearGradient id="laserSeamShimmerGrad" x1="8" y1="3" x2="8" y2="37" gradientUnits="userSpaceOnUse">
                <stop offset="0%" stopColor={glowColor} stopOpacity={0} />
                <stop offset="25%" stopColor={glowColor} stopOpacity={seamHover ? 0.85 : 0.3} />
                <stop offset="50%" stopColor="#ffffff" stopOpacity={seamHover ? 1 : 0.55} />
                <stop offset="75%" stopColor={glowColor} stopOpacity={seamHover ? 0.85 : 0.3} />
                <stop offset="100%" stopColor={glowColor} stopOpacity={0} />
              </linearGradient>
            </defs>
            {/* Neon laser shimmer line down the seam axis, across the tips */}
            <line
              x1={8}
              y1={3}
              x2={8}
              y2={37}
              stroke="url(#laserSeamShimmerGrad)"
              strokeWidth={seamHover ? 1.75 : 1.25}
              strokeLinecap="round"
            />
            {/* Single unified vertical stack of 4 micro-chevrons — apex tips
                terminate on the seam (X=8). Expanded: point LEFT (collapse
                inward). Collapsed: point RIGHT (expand outward). */}
            {(isRailExpanded
              ? ['M 12 7 L 8 11 L 12 15', 'M 12 13 L 8 17 L 12 21', 'M 12 19 L 8 23 L 12 27', 'M 12 25 L 8 29 L 12 33']
              : ['M 4 7 L 8 11 L 4 15', 'M 4 13 L 8 17 L 4 21', 'M 4 19 L 8 23 L 4 27', 'M 4 25 L 8 29 L 4 33']
            ).map((d, i) => (
              <path
                key={i}
                d={d}
                stroke={glowColor}
                strokeWidth={1.3}
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="none"
                opacity={0.7 + i * 0.0833}
              />
            ))}
          </svg>
        </div>
      )}
    </motion.nav>
  );

  const renderHeader = () => (
    <div className="relative flex h-12 items-center justify-between pl-4 pr-4 border-b shrink-0 z-30" style={{ borderColor: 'rgba(255,255,255,0.05)', backgroundColor: 'transparent' }}>
      {/* Live web-search pill — centred in the header, between the sub-app
          title and the notification button.

          The pill lives inside a BAND with equal left/right insets rather than
          being centred with left-1/2. Equal insets keep it centred on the
          header exactly as before, but now it physically cannot reach the
          title or the buttons: a long query truncates instead of growing over
          them. The previous max-w-[52%] did not hold, because the text span is
          a flex child and a flex child will not shrink below its content
          width without min-w-0 — so the pill pushed past its own max-width and
          spilled across the whole header.
          pointer-events-none: this is status, not a control. */}
      {/* Insets are INLINE, not Tailwind arbitrary values: left-[124px] /
          right-[124px] did not take effect here, so the band sized itself to
          its content (measured 717px inside a 704px header) and max-w-full on
          the pill had nothing real to resolve against. Inline styles always
          apply, and left+right together are what give the band a definite
          width for the pill to truncate within. */}
      <div
        className="absolute inset-y-0 z-10 flex items-center justify-center pointer-events-none"
        style={{ left: 124, right: 124 }}
      >
      <AnimatePresence>
        {(crawler.active || crawler.error) && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.96 }}
            transition={{ type: 'spring', stiffness: 320, damping: 26, mass: 0.7 }}
            className="flex items-center gap-2 px-3 py-1 rounded-full max-w-full min-w-0"
            style={{
              color: crawler.error ? '#f87171' : glowColor,
              border: `1px solid ${crawler.error ? 'rgba(248,113,113,0.35)' : `${glowColor}33`}`,
              background: crawler.error
                ? 'linear-gradient(180deg, rgba(248,113,113,0.12) 0%, rgba(248,113,113,0.05) 100%)'
                : `linear-gradient(180deg, ${glowColor}1a 0%, ${glowColor}08 100%)`,
              boxShadow: crawler.error
                ? '0 0 12px rgba(248,113,113,0.15), inset 0 1px 0 rgba(255,255,255,0.05)'
                : `0 0 12px ${glowColor}22, inset 0 1px 0 rgba(255,255,255,0.06)`,
              backdropFilter: 'blur(8px)',
            }}
          >
            {crawler.error ? (
              <AlertTriangle size={11} className="shrink-0" />
            ) : (
              <Loader size={11} className="animate-spin shrink-0" />
            )}
            {/* min-w-0 is what actually makes `truncate` work: without it a
                flex child refuses to shrink below its content width, so a long
                query widened the pill instead of ellipsising. */}
            <span className="text-[10px] font-bold tracking-[0.14em] uppercase truncate min-w-0">
              {crawler.error
                ? crawler.error
                : crawler.query
                  ? `Searching · ${crawler.query}`
                  : 'Searching'}
            </span>
            {!crawler.error && crawler.pagesTotal > 0 && (
              <span
                className="text-[10px] font-mono tabular-nums shrink-0 pl-1.5 ml-0.5"
                style={{ opacity: 0.65, borderLeft: `1px solid ${glowColor}2e` }}
              >
                {crawler.pagesDone}/{crawler.pagesTotal}
              </span>
            )}
          </motion.div>
        )}
      </AnimatePresence>
      </div>

      <div className="flex items-center gap-3 flex-1">
        {(activeSubApp === 'browser' || activeSubApp === 'marketplace' || activeSubApp === 'models' || activeSubApp === 'inference_console' || activeSubApp === 'hub') && isSidebarHidden && (
          <button
            onClick={() => setIsSidebarHidden(false)}
            className="p-2 -ml-2 hover:bg-white/5 rounded-lg text-white/40 hover:text-white transition-colors"
            title="Show Sidebar"
          >
            <Menu size={16} />
          </button>
        )}
        <span className="text-[12px] font-black tracking-[0.2em] text-white/90 uppercase whitespace-nowrap">
          {activeSubApp ? CATEGORY_LABELS[activeSubApp] : `${CATEGORY_LABELS[activeTab] || 'SYSTEM'} HUD`}
        </span>
      </div>

      <div className="flex items-center gap-0.5 flex-1 justify-end">
        {(spotlightState === 'dashboardSpotlight' || uiState === 'dashboard_open') && onOpenChat && (
          <button
            onClick={onOpenChat}
            className="p-2 rounded-lg transition-all duration-150"
            style={{
              color: isChatOpen ? glowColor : 'rgba(255,255,255,0.75)',
              backgroundColor: isChatOpen ? `${glowColor}15` : 'transparent',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = glowColor; e.currentTarget.style.backgroundColor = isChatOpen ? `${glowColor}15` : 'rgba(255,255,255,0.05)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = isChatOpen ? glowColor : 'rgba(255,255,255,0.75)'; e.currentTarget.style.backgroundColor = isChatOpen ? `${glowColor}15` : 'transparent'; }}
            title="Open Chat"
          >
            <MessageSquare size={16} />
          </button>
        )}
        <button
          onClick={onNotificationsClick}
          className="p-2 rounded-lg transition-all duration-150 relative"
          style={{
            color: isNotificationsOpen || unreadCount > 0 ? glowColor : 'rgba(255,255,255,0.75)',
            backgroundColor: isNotificationsOpen ? `${glowColor}15` : 'transparent',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.color = glowColor; e.currentTarget.style.backgroundColor = isNotificationsOpen ? `${glowColor}15` : 'rgba(255,255,255,0.05)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = isNotificationsOpen || unreadCount > 0 ? glowColor : 'rgba(255,255,255,0.75)'; e.currentTarget.style.backgroundColor = isNotificationsOpen ? `${glowColor}15` : 'transparent'; }}
        >
          <Bell size={16} />
          {unreadCount > 0 && <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full" style={{ backgroundColor: glowColor }} />}
        </button>
        <button
          onClick={handleCloseWithSave}
          className="p-2 rounded-lg transition-all duration-150"
          style={{ color: 'rgba(255,255,255,0.75)' }}
          onMouseEnter={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.95)'; e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.75)'; e.currentTarget.style.backgroundColor = 'transparent'; }}
          title="Close Dashboard"
        >
          <X size={16} />
        </button>
      </div>
    </div>
  );

  const renderActionBar = () => (
    <div className="flex items-center justify-between pl-4 pr-4 h-16 border-t bg-black/60 shrink-0 z-40" style={{ borderColor: 'rgba(255,255,255,0.05)' }}>
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/10">
          <Wifi className="w-3 h-3" style={{ color: voiceState === 'error' ? '#ef4444' : glowColor }} />
          <span className="text-[9px] font-medium tracking-wide text-white/80">
            {voiceState === 'error' ? 'OFFLINE' : 'WS LIVE'}
          </span>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/10">
          <Brain className="w-3 h-3" style={{ color: glowColor }} />
          <span className="text-[9px] font-medium tracking-wide text-white/80">
            {((role_bindings.find(r => r.role === 'reasoning')?.instance_id) || (localFieldValues?.local_model?.local_model_path as string) || 'No model').toUpperCase()} READY
          </span>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/10">
          <Activity className="w-3 h-3" style={{ color: glowColor }} />
          <span className="text-[9px] font-medium tracking-wide text-white/80">
            {voiceState === 'listening' ? 'LISTENING'
              : voiceState === 'processing_conversation' || voiceState === 'processing_tool' ? 'PROCESSING'
              : voiceState === 'speaking' ? 'SPEAKING'
              : voiceState === 'error' ? 'ERROR'
              : 'SYSTEM IDLE'}
          </span>
        </div>
        <button 
          onClick={() => handleSubAppChange('models')}
          className="px-4 py-1.5 rounded-lg text-[9px] font-bold tracking-wider transition-all border text-white/70 hover:text-white flex items-center gap-1.5"
          style={{ borderColor: 'rgba(255,255,255,0.15)' }}
          title="Browse & Manage Models"
        >
          <HardDrive size={12} />
          MODELS
        </button>
      </div>
      <div className="flex items-center gap-4 ml-auto">
        <button 
          onClick={handleApplySettings} 
          disabled={applyStatus === "applying"} 
          className="px-8 py-2.5 rounded-lg text-[11px] font-bold tracking-wider transition-all disabled:opacity-50"
          style={{ 
            backgroundColor: applyStatus === "applied" ? `${glowColor}30` : 'transparent',
            border: `1px solid ${applyStatus === "applied" ? glowColor : 'rgba(255,255,255,0.1)'}`,
            color: applyStatus === "applied" ? glowColor : 'rgba(255,255,255,0.7)',
          }}
          onMouseEnter={(e) => { if (applyStatus !== "applied") e.currentTarget.style.backgroundColor = glowColor; e.currentTarget.style.color = '#000'; }}
          onMouseLeave={(e) => { if (applyStatus !== "applied") { e.currentTarget.style.backgroundColor = 'transparent'; e.currentTarget.style.color = 'rgba(255,255,255,0.7)'; } }}
        >
          {applyStatus === "applying" ? 'COMMITTING...' : applyStatus === "applied" ? '✓ Applied' : 'APPLY'}
        </button>
      </div>
    </div>
  );

  const renderContentZone = () => (
    <div className="flex-1 overflow-y-auto p-0">
       {!activeSubApp ? (
         <div className="w-full h-full pl-3 pr-3 py-4 space-y-2">
            {/* DCP Stats — developer mode only, shown at top of Monitor tab */}
            {activeTab === 'monitor' && irisMode === 'developer' && (
              <div className="mb-2 rounded-lg border overflow-hidden" style={{ borderColor: `${glowColor}25`, background: 'rgba(255,255,255,0.015)' }}>
                <DCPStatsPanel glowColor={glowColor} />
              </div>
            )}
            {/* Monitor tab — render tabbed panel with Analytics | Logs | Diagnostics */}
            {activeTab === 'monitor' ? (
              <MonitorTabContainer glowColor={glowColor} fontColor="white" sendMessage={sendMessage} />
            ) : (
              activeSections.map((section: any) => {
             const isExpanded = expandedSections.has(section.id);
             const sectionFields = section.fields || [];
             return (
               <div key={section.id} className="group/section overflow-visible rounded-lg border transition-all" style={{ borderColor: isExpanded ? `${glowColor}30` : 'rgba(255,255,255,0.04)', backgroundColor: isExpanded ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.01)' }}>
                 <button onClick={() => toggleSection(section.id)} className="w-full h-11 px-4 flex items-center justify-between transition-all hover:bg-white/[0.04] relative group/btn">
                   <div className="flex items-center gap-2 min-w-0">
                     <section.icon size={13} className="flex-shrink-0" style={{ color: isExpanded ? glowColor : 'white' }} />
                     <span className="text-[11px] font-bold tracking-wide text-white/70 group-hover/btn:text-white uppercase whitespace-nowrap">{section.label}</span>
                   </div>
                   <ChevronDown size={13} className="flex-shrink-0 ml-2 text-white/30" style={{ transform: isExpanded ? 'rotate(180deg)' : 'none', transition: 'transform 0.3s' }} />
                   <div className="absolute bottom-0 left-0 right-0 h-[2px] opacity-0 group-hover/section:opacity-100 transition-all" style={{ background: `linear-gradient(90deg, transparent, ${glowColor}, transparent)` }} />
                 </button>
                  {isExpanded && (
                    <div className="px-4 pb-4 pt-2">
                      {section.id === 'model_inference' ? (
                        <ModelInferenceSection
                          providers={providers}
                          role_bindings={role_bindings}
                          loading={infLoading}
                          sendRoleBinding={sendRoleBinding}
                          glowColor={glowColor}
                          provider_presets={provider_presets}
                          sendModelSelection={sendModelSelection}
                          sendInferenceMode={sendInferenceMode}
                          inferenceValues={fieldValues?.inference_mode}
                          model_catalog={model_catalog}
                        />
                      ) : (
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-6 gap-y-1">
                          {sectionFields.map((field: any) => (
                            <FieldRow key={field.id} field={field} glowColor={glowColor} fieldValues={fieldValues} sectionId={section.id} updateField={updateField} fieldErrors={fieldErrors} clearFieldError={clearFieldError} sendMessage={sendMessage} audioInputDevices={audioInputDevices} audioOutputDevices={audioOutputDevices} wakeWords={wakeWords} />
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })
            )}
           </div>
        ) : activeSubApp === 'browser' ? (
          <div className="w-full h-full p-1.5">
          {/* REQ-11 (specs/vision-browser-stage, T12): p-4/md:px-10 -> p-1.5.
              The browser viewport is the star of this surface — inherited
              padding wasted ~15% of the wing's width on margins at every
              spotlight size. Scoped to THIS branch only; no other sub-app's
              layout changes. */}
           {/* `relative` is LOAD-BEARING: the nav overlay below is
               `absolute inset-0` and must resolve against THIS card. Without
               it the overlay escaped to the content column (which includes the
               48px header) and drew a sharp-cornered rectangle inset by this
               panel's own p-4/md:px-10 padding — a separate box floating over
               the header instead of the card's own border coming alive. */}
           <div className="relative w-full h-full flex flex-col bg-black/40 rounded-2xl border border-white/5 overflow-hidden backdrop-blur-md">

             {/* REQ-16 (T46): particle-shutter navigation overlay. Traces THIS
                 card's rounded-2xl border and washes inward from it, so the
                 chrome and the viewport light as one surface. Absolutely
                 positioned + pointer-events-none; never blocks the iframe or
                 the "open externally" control. The hook emits the REQ-18 trace
                 itself — no onStateChange wiring here (that double-recorded). */}
             <BrowserNavigationOverlay
               state={navOverlay.state}
               subGoal={navOverlay.subGoal}
               pagesDone={navOverlay.pagesDone}
               pagesTotal={navOverlay.pagesTotal}
               glowColor={glowColor}
               chromeInset={browserChromeInset}
               // REQ-11 AC4: the centre orb becomes the vision cursor. Passed
               // straight through — the overlay owns the motion, this site only
               // supplies the live action.
                visionAction={navOverlay.visionAction}
                visionX={navOverlay.visionX}
                visionY={navOverlay.visionY}
                visionStep={navOverlay.visionStep}
                // REQ-9: source viewport dims for aspect-correct cursor mapping.
                visionViewportW={navOverlay.visionViewportW}
                visionViewportH={navOverlay.visionViewportH}
                // REQ-8: escalation provenance drives the "notice" beat.
                visionEscalated={navOverlay.visionEscalated}
              />

             {/* ── Tab bar ─────────────────────────────────────────────────── */}
             {tabs.length > 0 && (
               <div
                 className="browser-tab-strip flex items-center gap-0 border-b overflow-x-auto overflow-y-hidden shrink-0"
                 // A vertical wheel over a horizontal strip does nothing on
                 // Windows without shift, and there is no CSS that maps one axis
                 // to the other — the visible-scrollbar fix made the overflow
                 // reachable by dragging but the wheel still did nothing, so
                 // tabs past the edge were only reachable by keyboard. Translate
                 // the dominant wheel axis into scrollLeft, and only swallow the
                 // event when this strip can actually consume it (at either end
                 // the page keeps its normal scroll).
                 onWheel={(e) => {
                   const el = e.currentTarget
                   const max = el.scrollWidth - el.clientWidth
                   if (max <= 0) return
                   const delta =
                     Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY
                   if (!delta) return
                   const next = Math.min(max, Math.max(0, el.scrollLeft + delta))
                   if (next === el.scrollLeft) return
                   el.scrollLeft = next
                   e.preventDefault()
                 }}
                 style={{
                   borderColor: 'rgba(255,255,255,0.06)',
                   // Visible thin scrollbar so a many-tab strip can actually be
                   // scrolled on Windows (scrollbarWidth:'none' hid it entirely,
                   // and a mouse wheel cannot move a horizontal strip — tabs got
                   // "cut off" with no way to reach them; live 2026-08-12).
                   // Matches the dashboard wing's glass aesthetic: 4px, 2px
                   // radius, white/5 track, white/20 thumb (see .browser-tab-strip
                   // rules below; Firefox via scrollbarColor).
                   scrollbarWidth: 'thin',
                   scrollbarColor: 'rgba(255,255,255,0.2) rgba(255,255,255,0.05)',
                   minHeight: 36,
                   overscrollBehaviorX: 'contain',
                 }}
               >
                 {tabs.map((tab) => {
                   const isActive = tab.id === activeTabId
                   const TabIcon = tab.type === 'code' ? FileCode : tab.type === 'dashboard' ? LayoutDashboard : Globe
                   return (
                     <button
                       key={tab.id}
                       onClick={() => setActiveTabId(tab.id)}
                       className="flex items-center gap-1.5 px-3 h-9 shrink-0 text-[11px] font-medium transition-all duration-150 border-r group"
                       style={{
                         borderColor: 'rgba(255,255,255,0.05)',
                         background: isActive ? 'rgba(255,255,255,0.06)' : 'transparent',
                         color: isActive ? glowColor : 'rgba(255,255,255,0.45)',
                         borderBottom: isActive ? `1px solid ${glowColor}` : '1px solid transparent',
                       }}
                     >
                       <TabIcon size={11} />
                       <span className="max-w-[120px] truncate">{tab.title}</span>
                       {tab.modifiedThisSession && (
                         <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
                       )}
                       <span
                         onClick={(e) => { e.stopPropagation(); closeTab(tab.id) }}
                         className="ml-0.5 p-0.5 rounded opacity-0 group-hover:opacity-100 hover:bg-white/10 transition-all cursor-pointer"
                       >
                         <X size={9} className="text-white/50" />
                       </span>
                     </button>
                   )
                 })}
               </div>
             )}

             {/* ── Tab content ──────────────────────────────────────────────── */}
             {(() => {
               const activeTab = tabs.find(t => t.id === activeTabId)
               if (activeTab?.type === 'dashboard' && activeTab.data) {
                 return (
                   // overflow-y-auto: the summary tab (DashboardRenderer —
                   // the search's synthesized answer + sources) must scroll
                   // vertically like the web iframes do. Previously
                   // overflow-hidden clipped it, so a long summary could not
                   // be scrolled (live 2026-08-12).
                   <div className="browser-summary-scroll flex-1 overflow-y-auto overflow-x-hidden">
                     <DashboardRenderer data={activeTab.data} glowColor={glowColor} />
                   </div>
                 )
               }
               if (activeTab?.type === 'code') {
                 return (
                   <div className="flex-1 overflow-auto p-4">
                     <pre
                       className="text-[12px] font-mono text-white/80 whitespace-pre-wrap break-words"
                       style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}
                     >
                       {activeTab.content ?? ''}
                     </pre>
                   </div>
                 )
               }
               if (activeTab?.type === 'html') {
                 // NO allow-same-origin below. Paired with allow-scripts it lets
                 // the frame reach parent.document and strip its own sandbox
                 // attribute — the standard sandbox-escape combination. This
                 // content is agent-AUTHORED, which is not the same as trusted:
                 // the model writes it after reading crawled pages, so an
                 // instruction injected into a crawled page can reach this HTML.
                 // Treat it as untrusted like everything else downstream of the web.
                 return (
                   <iframe
                     srcDoc={activeTab.content ?? ''}
                     className="flex-1 w-full border-none bg-white"
                     sandbox="allow-scripts"
                   />
                 )
               }
               // Default — web tab or no active tab: show address bar + iframe
               return (
                 <>
                    <div
                      className="flex items-center gap-2 px-3 border-b border-white/5 bg-black/20"
                      style={{ height: BROWSER_ADDRESS_BAR_H }}
                    >
                      <button
                        onClick={handleBrowserBack}
                        disabled={browserHistory.length === 0}
                        aria-label="Back"
                        className="p-1.5 hover:bg-white/5 rounded text-white/50 hover:text-white disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-white/50"
                      >
                       <ArrowLeft size={14} />
                     </button>
                     <input
                       value={activeTab?.url ?? browserInput}
                       onChange={(e) => setBrowserInput(e.target.value)}
                       onKeyDown={handleBrowserInputSubmit}
                       className="flex-1 text-[11px] rounded px-3 h-7 bg-white/5 border border-white/5 outline-none font-mono text-white"
                     />
                     {/* REQ-1 AC4: capture provenance in panel chrome. When the
                         active tab replays captured bytes (not a live fetch),
                         show the evidence: the original URL the agent read and
                         the capture time. */}
                      {activeTab?.type === 'web' && activeTab.captureJobId && (
                        <span
                          title={`Replaying captured page (job ${activeTab.captureJobId.slice(0, 8)}) — captured ${activeTab.captureFetchedAt ?? 'during crawl'}`}
                          className="shrink-0 flex items-center gap-1 px-2 h-5 rounded text-[10px] font-mono bg-emerald-500/10 text-emerald-300/80 border border-emerald-500/20"
                        >
                          <span className="w-1 h-1 rounded-full bg-emerald-400" />
                          capture
                        </span>
                      )}
                      {/* REQ-15 AC3: when a source pin pauses live-following,
                          the LIVE pill resumes it. */}
                      {pinnedSource && (
                        <button
                          onClick={() => setPinnedSource(null)}
                          title="Resume following the agent's live reading"
                          className="shrink-0 flex items-center gap-1 px-2 h-5 rounded text-[10px] font-mono transition-colors hover:brightness-125"
                          style={{
                            background: `${glowColor}18`,
                            border: `1px solid ${glowColor}44`,
                            color: glowColor,
                          }}
                        >
                          <span className="w-1 h-1 rounded-full" style={{ background: glowColor }} />
                          LIVE
                        </button>
                      )}
                     <button
                       onClick={handleBrowserReload}
                       title="Reload"
                       className="p-1.5 hover:bg-white/5 rounded text-white/50 hover:text-white transition-colors"
                     >
                       <RotateCcw size={14} />
                     </button>
                      <button
                        onClick={() => window.open(activeTab?.url ?? browserUrl, '_blank')}
                        className="p-1.5"
                      >
                        <ExternalLink size={14} className="text-white/50" />
                      </button>
                      {/* REQ-5 (specs/vision-browser-stage, T10): lifecycle
                          chip lives INSIDE the address bar, flush right —
                          user-resolved placement (it previously floated over
                          the card corner and overlapped the buttons). */}
                      <VisionLifecycleChip glowColor={glowColor} />
                   </div>
                   {browserIssue ? (
                     /* Say WHAT is wrong instead of letting a refused fetch
                        render as a raw "Internal Server Error". The frame is
                        opaque-origin so it cannot report this itself — the
                        status comes from probing the same-origin proxy route. */
                     <div className="flex-1 w-full flex flex-col items-center justify-center gap-3 px-6 text-center">
                       <Globe size={26} className="text-white/25" />
                       {browserIssue.kind === 'web_off' ? (
                         <>
                           <div className="text-[13px] text-white/80 font-medium">Web access is turned off</div>
                           <div className="text-[11px] text-white/45 max-w-sm leading-relaxed">
                             Turn on the web toggle in the chat view, then press Reload to connect.
                           </div>
                         </>
                       ) : browserIssue.kind === 'offline' ? (
                         <>
                           <div className="text-[13px] text-white/80 font-medium">Backend not reachable</div>
                           <div className="text-[11px] text-white/45 max-w-sm leading-relaxed">
                             The IRIS backend isn&apos;t responding yet. It can take a moment to start — press Reload to retry.
                           </div>
                         </>
                       ) : (
                         <>
                           <div className="text-[13px] text-white/80 font-medium">Couldn&apos;t load this page</div>
                           <div className="text-[11px] text-white/45 max-w-sm leading-relaxed font-mono break-all">
                             {browserIssue.detail}
                           </div>
                         </>
                       )}
                       <button
                         onClick={handleBrowserReload}
                         className="mt-1 flex items-center gap-1.5 px-3 h-7 rounded text-[11px] border transition-colors"
                         style={{ borderColor: `${glowColor}33`, color: glowColor }}
                       >
                         <RotateCcw size={12} /> Reload
                       </button>
                     </div>
                   ) : (
                     <iframe
                       ref={iframeRef}
                       src={activeFrameSrc}
                       className="flex-1 w-full border-none bg-white"
                       // REQ-3 AC1/T8: opaque-origin sandbox — NO allow-same-origin
                       // (the proxied/captured content must never read the app's
                       // origin) and NO allow-top-navigation. allow-scripts lets
                       // the injected view-agent speak OUT (REQ-4) but the frame
                       // cannot reach the parent.
                       sandbox="allow-scripts"
                     />
                   )}
                 </>
               )
             })()}

           </div>
         </div>
       ) : activeSubApp === 'activity' ? (
         <ActivityPanel key="activity" glowColor={glowColor} fontColor="white" />
       ) : activeSubApp === 'logs' ? (
         <LogsPanel key="logs" glowColor={glowColor} fontColor="white" />
        ) : activeSubApp === 'marketplace' ? (
          /* T10 (REQ-9): unified Marketplace & Models surface — MCP tools and
             Local Models + HF Hub combined behind one segmented pill. */
          <UnifiedMarketplaceModelsSurface key="marketplace" glowColor={glowColor} fontColor="white" />
         ) : activeSubApp === 'inference_console' ? (
          <InferenceConsolePanel key="inference_console" glowColor={glowColor} fontColor="white" />
        ) : activeSubApp === 'models' ? (
           <ModelBrowserPanel key="model_browser" glowColor={glowColor} fontColor="white" sendMessage={sendMessage} />
        ) : activeSubApp === 'hub' ? (
          /* T7/T8/T9 (REQ-7 AC2, REQ-5, REQ-6): the Visual Workspace Hub —
             focus-mode-controlled multi-agent Kanban board. */
          <div className="w-full h-full p-3">
            <Suspense
              fallback={
                <div className="h-full flex items-center justify-center">
                  <span className="text-xs text-white/20">Loading Workspace Hub…</span>
                </div>
              }
            >
              <DeveloperWorkspace />
            </Suspense>
          </div>
         ) : null}
    </div>
  );

  return (
    <div className="w-full h-full min-h-0 overflow-hidden flex flex-col text-white relative" style={{ background: 'transparent' }}>
      <div className="absolute inset-0 pointer-events-none opacity-20 mix-blend-overlay z-0" style={{ backgroundImage: 'url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAYAAABw4pVUAAAACXBIWXMAAAsTAAALEwEAmpwYAAABaWlDQ1BEaXNwbGF5IFAzAAB4nHWQvUvDUBTFT6tS0DqIDh0cMolD1NIKdnFoKxRFMFQFq1OafgltfCQpUnETVyn4H1jBWXCwiFRwcXAQRAcR3Zw6KbhoeN6XVNoi3sfl/Ticc7lcwBtQGSv2AijplpFMxKS11Lrke4OHnlOqZrKooiwK/v276/PR9d5PiFlNu3YQ2U9cl84ul3aeAlN//V3Vn8maGv3f1EGNGRbgkYmVbYsJ3iUeMWgp4qrgvMvHgtMunzuelWSc+JZY0gpqhrhJLKc7H/6D+J5n2yfMLn0OKytTFEUSM6cINe4XNXkYgmNK8wbcypdXUjxXwER+INsDGB1jMAkybGEHKCsBDFAIr5aJwbXKdrbbMh3b7Ctij6jr0oIFoeLlnELj0oqLYiEo+EHnQj0DSo9QmZQwTnjYSHcWFH7Yq5qxB2pORSp29+sX9m3k0/2J+MhuP4g8CJv/9T9fCZo0zjscOAAAAABJRU5ErkJggg==)' }} />
      <div className="absolute inset-0 pointer-events-none z-10" style={{ boxShadow: `inset 0 0 60px ${glowColor}05` }} />
      <div className="flex-1 flex overflow-hidden relative z-20">
        {renderNavigationRail()}
          {/* min-h-0 on BOTH columns is load-bearing, not cosmetic. A flex item
              whose overflow is `visible` gets min-height:auto, meaning it
              refuses to shrink below its content — so this column grew to fit a
              long summary, renderContentZone's `flex-1` resolved against that
              inflated height, and every `overflow-y-auto` below it (the summary
              tab included) had nothing to overflow. The content was then simply
              clipped by the `overflow-hidden` wrapper above, which is exactly
              what "the summary tab cannot be scrolled" looked like: no
              scrollbar, no wheel response, text cut off at the bottom. The
              earlier fix — adding overflow-y-auto to the summary container —
              was correct and inert, because the height it scrolled within was
              never bounded. Overflow stays visible here (the header's glow and
              dropdowns depend on it); min-h-0 only restores the ability to
              shrink. */}
          <div className="flex-1 min-h-0 flex flex-col overflow-visible relative">
            {renderHeader()}
            <div className="flex-1 min-h-0 flex flex-col overflow-visible">
              {renderContentZone()}
            </div>
          </div>
      </div>
      {renderActionBar()}

      {/* Browser tab-strip scrollbar — 4px glass style matching the wing's
          SidePanel custom-scrollbar (white/5 track, white/20 thumb, 2px
          radius). Firefox uses the inline scrollbarColor; Chrome/Edge need
          these webkit rules. Applied via a global rule so it works even when
          the strip is inside the shadow-ish dashboard tree. */}
      <style jsx global>{`
        .browser-tab-strip::-webkit-scrollbar,
        .browser-summary-scroll::-webkit-scrollbar {
          height: 4px;
          width: 4px;
        }
        .browser-tab-strip::-webkit-scrollbar-track,
        .browser-summary-scroll::-webkit-scrollbar-track {
          background: rgba(255, 255, 255, 0.05);
          border-radius: 2px;
        }
        .browser-tab-strip::-webkit-scrollbar-thumb,
        .browser-summary-scroll::-webkit-scrollbar-thumb {
          background: rgba(255, 255, 255, 0.2);
          border-radius: 2px;
        }
        .browser-tab-strip::-webkit-scrollbar-thumb:hover,
        .browser-summary-scroll::-webkit-scrollbar-thumb:hover {
          background: rgba(255, 255, 255, 0.3);
        }
      `}</style>
    </div>
  );
}

