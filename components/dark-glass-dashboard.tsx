'use client';

import { useState, memo, useMemo, useCallback, useEffect, useRef } from 'react';
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
import { useLauncherMode } from '@/hooks/useLauncherMode';
import { useInferenceState } from '@/hooks/useInferenceState';
import { DCPStatsPanel } from '@/components/dev/DCPStatsPanel';
import { MonitorTabContainer } from '@/components/dashboard/MonitorTabContainer';
import { IrisApertureIcon } from '@/components/ui/IrisApertureIcon';
import { IconRobot, IconTopologyStar3, IconBasketCog } from "@tabler/icons-react";
import {
  Mic, Bot, Cpu, Settings, Palette, Activity, Volume2, Waves, Brain, Database, Sparkles, MessageSquare, Smile, Wrench, Layers, Star, Keyboard, Monitor, Power, HardDrive, Wifi, Bell, Sliders, RefreshCw, BarChart3, FileText, Stethoscope, X, ChevronRight, ChevronLeft, ChevronDown, ChevronUp, Eye, Globe,
  Shield, Zap, Workflow, Boxes, Puzzle, FolderOpen, Monitor as MonitorIcon, Play, Volume1, MicVocal,
  LayoutDashboard, ShoppingBag, Menu, User, ArrowLeft, RotateCcw, Home, ArrowRight as ArrowRightIcon, ExternalLink, History, AlertCircle, Code, FileCode, Plus as PlusIcon,
  Network as NetworkIcon
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
      agent: ['model_inference', 'local_model', 'swarm_setup', 'identity', 'memory'],
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

  const {
    providers,
    role_bindings,
    loading: infLoading,
    sendRoleBinding,
    provider_presets,
    sendModelSelection,
    sendInferenceMode,
  } = useInferenceState();

  // Persist active tab so the app restores to the last used panel on reopen
  const [activeTab, setActiveTab] = useState<string>(() => {
    if (typeof window === "undefined") return 'voice'
    return localStorage.getItem('iris_active_tab_v1') || 'voice'
  });
  const [activeSubApp, setActiveSubApp] = useState<string | null>(null);
  const [isRailExpanded, setIsRailExpanded] = useState(true);
  const [isSidebarHidden, setIsSidebarHidden] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['input', 'model_inference', 'tools', 'power', 'theme', 'analytics']));
  const [isApplying, setIsApplying] = useState(false);
  const [applyStatus, setApplyStatus] = useState<"idle" | "applying" | "applied">("idle");
  
  const [browserUrl, setBrowserUrl] = useState<string>('https://www.google.com');
  const [browserInput, setBrowserInput] = useState<string>('https://www.google.com');
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Tab system — receives open_tab / close_tab WebSocket messages
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);

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
    setActiveTabId(msg.id)
  }, [])

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

  // Listen for model-load-request events from the ModelBrowserPanel and route
  // them through the WebSocket `load_local_model` path. This is the single
  // source of truth for loading: it honors the backend load result and wires
  // the kernel to the iris_local provider (so a local model drives reasoning
  // and tool execution exactly like an API-key provider).
  useEffect(() => {
    const onModelLoadRequest = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail?.path && sendMessage) {
        sendMessage('load_local_model', {
          model_path: detail.path,
          profile: detail.profile || 'balanced',
        })
      }
    }
    window.addEventListener('model-load-request', onModelLoadRequest)
    return () => window.removeEventListener('model-load-request', onModelLoadRequest)
  }, [sendMessage])

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

    window.addEventListener('iris:initial_state',   handleInitialState   as EventListener);
    window.addEventListener('iris:available_models', handleAvailableModels as EventListener);
    window.addEventListener('iris:audio_devices',    handleAudioDevices    as EventListener);
    window.addEventListener('iris:wake_words_list',  handleWakeWords       as EventListener);

    return () => {
      window.removeEventListener('iris:initial_state',   handleInitialState   as EventListener);
      window.removeEventListener('iris:available_models', handleAvailableModels as EventListener);
      window.removeEventListener('iris:audio_devices',    handleAudioDevices    as EventListener);
      window.removeEventListener('iris:wake_words_list',  handleWakeWords       as EventListener);
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

  const VIRTUAL_SUB_APPS = new Set(['browser', 'marketplace', 'models', 'inference_console']);

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
      const allSections = Object.entries(localFieldValues).filter(
        ([_sectionId, values]) => values && typeof values === 'object' && Object.keys(values).length > 0
      );
      for (const [sectionId, sectionValues] of allSections) {
        
        // Try WebSocket first (fast path)
        if (sendMessage) {
          sendMessage('confirm_card', {
            section_id: sectionId,
            values: sectionValues,
          });
        }
        
        // Also call HTTP API as reliable fallback (works even if WebSocket is down)
        try {
          await fetch('/api/config/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              section_id: sectionId,
              card_id: sectionId,
              values: sectionValues,
            }),
          });
        } catch (fetchErr) {
          console.warn('[DarkGlassDashboard] HTTP fallback failed:', fetchErr);
        }
      }
      // Keep the button disabled for at least 2s so the backend can process
      // and guard against duplicate subprocess/server launches.
      await new Promise(r => setTimeout(r, 2000));
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
      const current = JSON.stringify(localFieldValues);
      const last = lastAppliedRef.current ? JSON.stringify(lastAppliedRef.current) : null;
      if (current !== last) {
        // Bypass the cooldown — closing is a one-shot, and we must not skip the
        // save just because the user clicked APPLY <2s ago (the backend already
        // dedupes by section_id).
        applyCooldownRef.current = false;
        await handleApplySettings();
      }
    } catch (e) {
      console.warn('[DarkGlassDashboard] save-on-close failed:', e);
    } finally {
      onClose?.();
    }
  }, [localFieldValues, handleApplySettings, onClose]);

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
    setBrowserUrl(normalized);
    setBrowserInput(normalized);
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

  const renderNavigationRail = () => (
    <motion.nav 
      initial={false}
      animate={{ 
        width: isSidebarHidden ? 0 : (isRailExpanded ? 120 : 56),
        opacity: isSidebarHidden ? 0 : 1,
        x: isSidebarHidden ? -20 : 0
      }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className="flex flex-col h-full border-r relative z-20 overflow-hidden shrink-0"
      style={{ 
        borderColor: 'rgba(255,255,255,0.05)',
        backgroundColor: 'rgba(0,0,0,0.3)'
      }}
    >
      <div className="flex h-16 items-center px-4 mb-2 gap-3 border-b border-white/[0.03]">
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

      {isRailExpanded && (
        <div className="px-3 mb-6 pt-4 flex gap-2">
          {[
            { id: 'browser', label: 'BROWSER' },
            { id: 'marketplace', label: 'MARKET' },
          ].map(node => (
            <button
              key={node.id}
              onClick={() => handleSubAppChange(node.id)}
              className="flex-1 group flex items-center justify-center h-7 rounded transition-all relative overflow-hidden border border-white/[0.05]"
              style={{ backgroundColor: activeSubApp === node.id ? `${glowColor}15` : 'rgba(255,255,255,0.02)' }}
            >
              <span className="text-[9px] font-black uppercase tracking-[0.1em] opacity-60 group-hover:opacity-100 transition-opacity">
                {node.label}
              </span>
              <div className="absolute bottom-0 left-0 right-0 h-[1px] opacity-0 group-hover:opacity-100 transition-opacity" style={{ backgroundColor: glowColor }} />
            </button>
          ))}
        </div>
      )}
      {!isRailExpanded && (
        <div className="px-2 mb-6 pt-4 flex flex-col gap-3 items-center">
           <button onClick={() => handleSubAppChange('browser')} className="text-white/30 hover:text-white"><Globe size={14} /></button>
           <button onClick={() => handleSubAppChange('marketplace')} className="text-white/30 hover:text-white"><ShoppingBag size={14} /></button>
        </div>
      )}

      <div className="h-[1px] bg-white/[0.05] mx-4 mb-4" />

      <div className="flex-1 py-1 overflow-y-auto scrollbar-hide">
        <div className="flex flex-col gap-3 px-2">
          {MAIN_NODES_DATA.filter(n => !('developerOnly' in n && n.developerOnly && irisMode !== 'developer')).map((node) => {
            const Icon = node.icon;
            const isActive = activeTab === node.id && !activeSubApp;
            const isExpanded = isRailExpanded;
            return (
              <button
                key={node.id}
                onClick={() => handleTabChange(node.id)}
                className="group w-full flex items-center justify-center transition-all duration-200 relative rounded-full"
                style={{
                  height: 34,
                  backgroundColor: isActive ? `${glowColor}2E` : 'transparent',
                  border: isActive ? `1px solid ${glowColor}40` : '1px solid transparent',
                  boxShadow: isActive ? `0 0 12px ${glowColor}26` : 'none',
                  ...(isExpanded ? { paddingLeft: 12, paddingRight: 12, justifyContent: 'flex-start' } : { width: 34, margin: '0 auto' }),
                }}
                title={isExpanded ? undefined : node.label}
              >
                <Icon className="w-4 h-4 flex-shrink-0" style={{ color: isActive ? glowColor : 'rgba(255,255,255,0.35)' }} />
                {isExpanded && (
                  <span className="ml-3 text-[10px] font-semibold tracking-wider whitespace-nowrap" style={{ color: isActive ? 'white' : 'rgba(255,255,255,0.35)' }}>
                    {node.label}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <div className="p-4 border-t" style={{ borderColor: 'rgba(255,255,255,0.05)' }}>
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
    </motion.nav>
  );

  const renderHeader = () => (
    <div className="flex h-12 items-center justify-between pl-4 pr-4 border-b shrink-0 z-30" style={{ borderColor: 'rgba(255,255,255,0.05)', backgroundColor: 'transparent' }}>
      <div className="flex items-center gap-3 flex-1">
        {(activeSubApp === 'browser' || activeSubApp === 'marketplace' || activeSubApp === 'models' || activeSubApp === 'inference_console') && isSidebarHidden && (
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
         <div className="w-full h-full p-4 md:px-10">
           <div className="w-full h-full flex flex-col bg-black/40 rounded-2xl border border-white/5 overflow-hidden backdrop-blur-md">

             {/* ── Tab bar ─────────────────────────────────────────────────── */}
             {tabs.length > 0 && (
               <div
                 className="flex items-center gap-0 border-b overflow-x-auto"
                 style={{ borderColor: 'rgba(255,255,255,0.06)', scrollbarWidth: 'none', minHeight: 36 }}
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
                   <div className="flex-1 overflow-hidden">
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
                 return (
                   <iframe
                     srcDoc={activeTab.content ?? ''}
                     className="flex-1 w-full border-none bg-white"
                     sandbox="allow-scripts allow-same-origin"
                   />
                 )
               }
               // Default — web tab or no active tab: show address bar + iframe
               return (
                 <>
                   <div className="flex items-center gap-2 px-3 h-10 border-b border-white/5 bg-black/20">
                     <button
                       onClick={() => {
                         try {
                            if (iframeRef.current?.contentWindow) {
                              window.history.back()
      }
                         } catch (e) {
                           console.warn("Cross-origin navigation blocked", e)
                         }
                       }}
                       className="p-1.5 hover:bg-white/5 rounded text-white/50 hover:text-white"
                     >
                       <ArrowLeft size={14} />
                     </button>
                     <input
                       value={activeTab?.url ?? browserInput}
                       onChange={(e) => setBrowserInput(e.target.value)}
                       onKeyDown={handleBrowserInputSubmit}
                       className="flex-1 text-[11px] rounded px-3 h-7 bg-white/5 border border-white/5 outline-none font-mono text-white"
                     />
                     <button
                       onClick={() => window.open(activeTab?.url ?? browserUrl, '_blank')}
                       className="p-1.5"
                     >
                       <ExternalLink size={14} className="text-white/50" />
                     </button>
                   </div>
                   <iframe
                     ref={iframeRef}
                     src={activeTab?.url ?? browserUrl}
                     className="flex-1 w-full border-none bg-white"
                   />
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
         <MarketplaceScreen key="marketplace" glowColor={glowColor} fontColor="white" />
        ) : activeSubApp === 'inference_console' ? (
          <InferenceConsolePanel key="inference_console" glowColor={glowColor} fontColor="white" />
        ) : activeSubApp === 'models' ? (
          <ModelBrowserPanel key="model_browser" glowColor={glowColor} fontColor="white" />
        ) : null}
    </div>
  );

  return (
    <div className="w-full h-full min-h-0 overflow-hidden flex flex-col text-white relative" style={{ background: 'transparent' }}>
      <div className="absolute inset-0 pointer-events-none opacity-20 mix-blend-overlay z-0" style={{ backgroundImage: 'url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAYAAABw4pVUAAAACXBIWXMAAAsTAAALEwEAmpwYAAABaWlDQ1BEaXNwbGF5IFAzAAB4nHWQvUvDUBTFT6tS0DqIDh0cMolD1NIKdnFoKxRFMFQFq1OafgltfCQpUnETVyn4H1jBWXCwiFRwcXAQRAcR3Zw6KbhoeN6XVNoi3sfl/Ticc7lcwBtQGSv2AijplpFMxKS11Lrke4OHnlOqZrKooiwK/v276/PR9d5PiFlNu3YQ2U9cl84ul3aeAlN//V3Vn8maGv3f1EGNGRbgkYmVbYsJ3iUeMWgp4qrgvMvHgtMunzuelWSc+JZY0gpqhrhJLKc7H/6D+J5n2yfMLn0OKytTFEUSM6cINe4XNXkYgmNK8wbcypdXUjxXwER+INsDGB1jMAkybGEHKCsBDFAIr5aJwbXKdrbbMh3b7Ctij6jr0oIFoeLlnELj0oqLYiEo+EHnQj0DSo9QmZQwTnjYSHcWFH7Yq5qxB2pORSp29+sX9m3k0/2J+MhuP4g8CJv/9T9fCZo0zjscOAAAAABJRU5ErkJggg==)' }} />
      <div className="absolute inset-0 pointer-events-none z-10" style={{ boxShadow: `inset 0 0 60px ${glowColor}05` }} />
      <div className="flex-1 flex overflow-hidden relative z-20">
        {renderNavigationRail()}
          <div className="flex-1 flex flex-col overflow-visible relative">
            {renderHeader()}
            <div className="flex-1 flex flex-col overflow-visible">
              {renderContentZone()}
            </div>
          </div>
      </div>
      {renderActionBar()}
    </div>
  );
}
