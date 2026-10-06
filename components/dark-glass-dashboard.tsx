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
import { LearnedSkillsPanel } from './wheel-view/LearnedSkillsPanel';
import { PermissionsSettingsCard } from './chat/PermissionsSettingsCard';
import { ModelBrowserPanel } from './dashboard/ModelBrowserPanel';
import { MarketplaceScreen } from './integrations/MarketplaceScreen';
import { UnifiedMarketplaceModelsSurface } from './integrations/UnifiedMarketplaceModelsSurface';
import { useLauncherMode } from '@/hooks/useLauncherMode';
import { useInferenceState } from '@/hooks/useInferenceState';
import { useCrawlContext } from '@/hooks/CrawlProvider';
import { useWorkspaceStore } from '@/stores/workspaceStore';
import { Xur } from '@/components/Xur';
import { WingMenu, type WingMenuItem } from '@/components/chrome/WingMenu';
import { ModelRoutingTable } from '@/components/dashboard/ModelRoutingTable';
import { DashboardRail, type RailPlace, type RailView } from '@/components/dashboard/DashboardRail';
import {
  changeKey, changeSection, changedKeys, isPlainFieldSection, isSegmented, sectionMatches, sectionSummary,
} from '@/components/dashboard/settingsModel';
import { useBrandPalette } from '@/hooks/useBrandPalette';
import { brandVars } from '@/components/chat/header/brandVars';
import type { Palette as BrandPalette } from '@/lib/brandPalette';

// cli-workspace-unification T7 (REQ-7 AC2): the Workspace Hub surface —
// lazy-loaded so the hub bundle only loads when the rail node is clicked.
const DeveloperWorkspace = lazy(() => import('@/components/workspace/DeveloperWorkspace'));
import { MonitorPage } from '@/components/dashboard/MonitorPage';
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
  Network as NetworkIcon, Loader, AlertTriangle, Maximize2, Minimize2
} from 'lucide-react';
import { invoke } from "@tauri-apps/api/core";
import { detachWing, reattachWing } from "@/hooks/useDetachedWing";
import { useManualDragWindow } from "@/hooks/useManualDragWindow";

// Launch the separate IRIS Launcher Tauri app (bidirectional launcher⇄widget).
const openIrisLauncher = async () => {
  try {
    await invoke("launch_launcher");
  } catch (e) {
    console.warn("[Dashboard] launch_launcher failed:", e);
  }
};

interface DarkGlassDashboardProps {
  theme?: string;
  fieldValues?: Record<string, Record<string, string | number | boolean>>;
  updateField?: (sectionId: string, fieldId: string, value: any) => void;
  onClose?: () => void;
  /** This dashboard is alone in its own detached window (?pane=dashboard). */
  isDetached?: boolean;
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

// The surfaces the rail's Surfaces view lists, in order. (The Inference console is not one
// any more: it moves into Monitor. `inference_console` still routes there.)
const SURFACE_IDS = ['hub', 'browser', 'models', 'marketplace'];

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
        step: field.step,
        description: field.description,
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
          label: SECTION_TO_LABEL[sectionId] || sectionId,
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

// Sections to persist on close: changed by the user, populated, and not the
// self-managed model sections - ModelInferenceSection live-sends those, and
// re-saving cached values reverts the user's provider (see handleApplySettings).
function unsavedSections(
  dirty: Set<string>,
  values: Record<string, Record<string, any>>,
): [string, Record<string, any>][] {
  return Array.from(dirty)
    .filter((id) => id !== 'model_inference' && id !== 'model_selection')
    .map((id) => [id, values[id]] as [string, Record<string, any>])
    .filter(([, v]) => !!v && typeof v === 'object' && Object.keys(v).length > 0);
}

const FieldRow = memo(function FieldRow({ field, glowColor, fieldValues, sectionId, updateField, fieldErrors, clearFieldError, sendMessage, audioInputDevices, audioOutputDevices, wakeWords, visionModelOptions, apiKeySaved, changed }: { field: any; glowColor: string; fieldValues?: Record<string, Record<string, string | number | boolean>>; sectionId?: string; updateField?: (sectionId: string, fieldId: string, value: any) => void; fieldErrors?: Record<string, string>; clearFieldError?: (sectionId: string, fieldId: string) => void; sendMessage?: (type: string, payload?: any) => boolean; audioInputDevices?: string[]; audioOutputDevices?: string[]; wakeWords?: string[]; visionModelOptions?: { label: string; value: string }[]; apiKeySaved?: boolean; /** The user changed this value and has not applied it: it gets the amber dot. */ changed?: boolean }) {
  const [localValue, setLocalValue] = useState(field.defaultValue ?? '');
  const value = fieldValues && sectionId ? (fieldValues[sectionId]?.[field.id] ?? field.defaultValue ?? '') : localValue;
  const [btnFeedback, setBtnFeedback] = useState<string | null>(null);
  // A slider drag shows its value at once but commits once, when the pointer lifts
  // (every commit is a live update to the backend). Keys and assistive tech commit per change.
  const [draft, setDraft] = useState<number | null>(null);
  const dragging = useRef(false);
  
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

  // Conditional visibility: hide field if showIf condition not met
  if (field.showIf && fieldValues && sectionId) {
    const depValue = fieldValues[sectionId]?.[field.showIf.field];
    // Only hide if there's an explicit value that doesn't match (undefined = not set yet = show)
    if (depValue !== undefined && depValue !== null && !field.showIf.values.includes(depValue)) return null;
  }

  // The label side of a row: name, the amber dot while it is changed, and the hint.
  const label = (
    <div className="l">
      <b>{changed && <i title="changed, not applied" />}{field.label}</b>
      {field.description && <small>{field.description}</small>}
    </div>
  );

  if (field.type === 'section') {
    return <div className="iris-fh">{field.label}</div>;
  }

  if (field.type === 'custom') {
    if (field.id === 'skills_list') {
      return (
        <div className="col-span-full mt-2 mb-4">
          <LearnedSkillsPanel glowColor={glowColor} />
        </div>
      );
    }
    // Session-331 clean swap: the Tools card renders the REAL consent surface
    // (Auto-approve toggle + mode + approved tools) instead of the legacy dead
    // `tool_confirmations` / `allowed_tools` fields. One control, backed by
    // /api/auto-approve + /api/mode + /api/approved-tools.
    if (field.id === 'permissions_settings') {
      return (
        <div className="col-span-full mt-1 mb-2">
          <PermissionsSettingsCard />
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
      <div className="iris-f wide">
        <button
          type="button"
          onClick={() => {
            setBtnFeedback("clicked");
            setTimeout(() => setBtnFeedback(null), 2000);
            if (field.action) {
              window.dispatchEvent(new CustomEvent('iris:card_action', { detail: { action: field.action, fieldId: field.id } }));
            } else {
              setValue("trigger");
            }
          }}
          className="iris-fbtn"
        >
          {btnFeedback ? `✓ ${field.label}` : field.label}
        </button>
      </div>
    );
  }

  if (field.type === 'toggle') {
    return (
      <div className="iris-f">
        {label}
        <div className="c">
          <span className="iris-tgw">{value ? 'on' : 'off'}</span>
          <button type="button" role="switch" aria-checked={!!value} aria-label={field.label} className="iris-tg" onClick={() => setValue(!value)} />
        </div>
      </div>
    );
  }

  if (field.type === 'dropdown') {
    const baseOptions = field.options || [];
    let options = baseOptions;
    if (sectionId === 'input' && field.id === 'input_device') options = audioInputDevices || [];
    if (sectionId === 'output' && field.id === 'output_device') options = audioOutputDevices || [];
    if (sectionId === 'wake' && (field.id === 'wake_word' || field.id === 'wake_phrase')) options = wakeWords && wakeWords.length > 0 ? wakeWords : (field.options || []);
    // Vision-card dropdown: list the vision-capable models from the same
    // /api/models scan the Models & Browse panel uses (value = model.path,
    // same identity as vision_fallback_ladder). The selected value lands in
    // field_values['vision']['vision_model'] and the backend uses it as the
    // preferred VLM for borrowed-server reuse (with basename fallback).
    if (sectionId === 'vision' && field.id === 'vision_model' && visionModelOptions && visionModelOptions.length > 0) {
      options = visionModelOptions;
    }
    // The CustomDropdown accepts string[] OR { label, value }[]; normalise.
    const _optObjs: { label: string; value: string }[] = options.map((o: any) =>
      typeof o === 'string' ? { label: o, value: o } : { label: String(o.label ?? o.value ?? ''), value: String(o.value ?? o.label ?? '') }
    );
    // A small fixed enum is a segmented control; a list that comes from the
    // device or the model scan stays a dropdown.
    const segmented = isSegmented(field, options !== baseOptions);

    return (
      <div className="iris-f">
        {label}
        <div className="c">
          {segmented ? (
            <div className="iris-sg" role="group" aria-label={field.label}>
              {_optObjs.map((o) => (
                <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => setValue(o.value)}>{o.label}</button>
              ))}
            </div>
          ) : (
            <CustomDropdown
              value={value}
              options={_optObjs}
              onChange={setValue}
              glowColor={glowColor}
              variant="ink"
            />
          )}
        </div>
      </div>
    );
  }

  if (field.type === 'slider') {
    const min = field.min ?? 0;
    const max = field.max ?? 100;
    const current = Number(value);
    const shown = draft ?? (Number.isFinite(current) ? current : min);
    const commit = () => {
      dragging.current = false;
      if (draft !== null) { setValue(draft); setDraft(null); }
    };
    return (
      <div className="iris-f">
        {label}
        <div className="c">
          <input
            type="range"
            className="iris-range"
            min={min}
            max={max}
            step={field.step ?? 1}
            value={shown}
            aria-label={field.label}
            onPointerDown={() => { dragging.current = true; }}
            onPointerUp={commit}
            onPointerCancel={commit}
            onChange={(e) => {
              const n = Number(e.target.value);
              if (dragging.current) setDraft(n); else setValue(n);
            }}
          />
          <span className="iris-num">{Math.round(shown)}{field.unit || ''}</span>
        </div>
      </div>
    );
  }

  if (field.type === 'text') {
    const isSecret = field.id.toLowerCase().includes('key') || field.id.toLowerCase().includes('secret') || field.id.toLowerCase().includes('password');
    // A stored key is held in the OS keyring and never echoed to the client,
    // so an EMPTY value here means "already saved", not "missing". Scoped to
    // model_selection: that is the inference provider's key. desktop_control
    // also has an `api_key` field (the UI-TARS provider's) which is NOT in the
    // inference keyring, so it must not claim to be saved.
    const keySaved = isSecret && sectionId === 'model_selection' && !!apiKeySaved && !value;
    return (
      <div className="iris-f wide">
        {label}
        <div className="c">
          <input
            type={isSecret ? 'password' : 'text'}
            value={String(value ?? '')}
            aria-label={field.label}
            placeholder={keySaved ? '••••••••••••••••' : (field.placeholder || field.label)}
            onChange={(e) => setValue(e.target.value)}
            className="iris-input"
            style={{ fontFamily: field.id.includes('url') || field.id.includes('endpoint') || field.id.includes('key') ? "'JetBrains Mono', monospace" : 'inherit' }}
          />
        </div>
        {keySaved && (
          <p className="iris-fok">Key saved — leave blank to keep it.</p>
        )}
        {errorMessage && (
          <p className="iris-ferr">{errorMessage}</p>
        )}
      </div>
    );
  }

  return (
    <div className="iris-f">
      {label}
      <div className="c"><span className="iris-num" style={{ whiteSpace: 'nowrap' }}>{value || '-'}</span></div>
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
  isDetached = false,
}: DarkGlassDashboardProps) {
  // Window drag by the header — see the note on the header element below.
  const dashboardHeaderRef = useRef<HTMLDivElement>(null)
  const { handleMouseDown: handleHeaderDragStart } = useManualDragWindow(dashboardHeaderRef)
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

  // The generic "API Key" box (section model_selection) can never show a
  // value: /api/config/save routes the key to the OS keyring and CLEARS the
  // config field, and the snapshot crosses `has_key` as a boolean only — the
  // secret itself never reaches the client (CT-S4). So the box rendered empty
  // on every open and the user re-typed a key that was already stored. This
  // resolves whether the ACTIVE provider already holds one, so the row can say
  // so instead of implying it is missing. role_bindings[].instance_id is a
  // ProviderInstance.id (router.py: "reasoning" -> "cerebras").
  const activeProviderId = role_bindings?.find((b: any) => b.role === "reasoning")?.instance_id;
  const apiKeySaved = !!providers?.find((p: any) => p.id === activeProviderId)?.has_key;

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
  // The Xur button folds the rail to orbs only (and unfolds it).
  const [isRailExpanded, setIsRailExpanded] = useState(true);
  // The rail has two views on one spine: Settings (the six tabs) and Surfaces
  // (workspace hub, browser, models, marketplace). The view follows what is on
  // screen: a surface is open, or a settings tab is.
  const railMode: RailView = activeSubApp ? 'surfaces' : 'settings';
  // The surface the Surfaces view returns to (the hub until another one is opened).
  const lastSurfaceRef = useRef('hub');
  useEffect(() => {
    if (activeSubApp && SURFACE_IDS.includes(activeSubApp)) lastSurfaceRef.current = activeSubApp;
  }, [activeSubApp]);
  // "Find a setting": searches section names and field labels across all settings places.
  const [findQuery, setFindQuery] = useState('');
  // Monitor: open_inference_console lands on the Inference stream (docs/architecture/MONITOR.md).
  const [monitorOpenRow, setMonitorOpenRow] = useState<{ row: 'stream'; n: number } | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = useCallback(() => setMenuOpen(false), []);
  const brand = useBrandPalette();
  // The dashboard's accent is the second hue; the Xur here rides in the hues from the second on.
  const xurPalette: BrandPalette = [brand[1], brand[2], brand[0]];
  const accent = brand[1];

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

  // Sections the USER changed (localUpdateField) since the last APPLY. The
  // close/unmount save writes only these. It used to treat "never applied" as
  // dirty and POST every populated section on every unmount - and React's dev
  // double-mount unmounts once at load: ~36 /api/config/save on every page
  // load (2026-10-02), including model_selection from cached values, which
  // rewrote cfg.inference.provider behind the live role binding.
  const dirtySectionsRef = useRef<Set<string>>(new Set());

  // Each field's value from BEFORE its first edit since the last Apply, keyed
  // "section.field". A field counts as changed while its value differs from this
  // (change it back and it is no longer changed). Apply clears it.
  const [pristine, setPristine] = useState<Record<string, unknown>>({});

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
    const key = changeKey(sectionId, fieldId);
    setPristine(p => (key in p ? p : { ...p, [key]: localFieldValuesRef.current[sectionId]?.[fieldId] }));
    setLocalFieldValues(prev => ({
      ...prev,
      [sectionId]: { ...(prev[sectionId] || {}), [fieldId]: value },
    }));
    // Session-331: the Tools card's two controls are NOT generic field_values —
    // they map to dedicated config keys with their own endpoints. Route them
    // there so the change actually persists and takes effect (a generic WS
    // field update would only write field_values and do nothing).
    if (sectionId === 'tools' && fieldId === 'permission_mode') {
      fetch('/api/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: value }),
      }).catch(() => {});
      return;
    }
    if (sectionId === 'tools' && fieldId === 'auto_approve') {
      fetch('/api/auto-approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_approve: !!value }),
      }).catch(() => {});
      return;
    }
    dirtySectionsRef.current.add(sectionId);
    // Live-update the backend via WebSocket (optimistic — does not block UI)
    if (wsUpdateField) wsUpdateField(sectionId, fieldId, value);
    // Also propagate to external store if provided via props
    if (propUpdateField) propUpdateField(sectionId, fieldId, value);
  }, [propUpdateField, wsUpdateField]);

  // Session-331: seed the Tools card from the REAL permission config
  // (/api/config), not generic field_values — mode and auto-approve live in
  // dedicated keys, so the dashboard must read them from the endpoint that
  // owns them. Re-fetched on mount; the POSTs above keep it in sync.
  useEffect(() => {
    let cancelled = false;
    fetch('/api/config')
      .then(r => (r.ok ? r.json() : null))
      .then((cfg: any) => {
        if (cancelled || !cfg) return;
        setLocalFieldValues(prev => ({
          ...prev,
          tools: {
            ...(prev.tools || {}),
            permission_mode: cfg.effective_mode || cfg.mode || 'developer',
            auto_approve: cfg.auto_approve === true,
          },
        }));
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

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
  // Vision-card dropdown: vision-capable models from the same /api/models scan
  // the Models & Browse panel uses (the browse panel owns the scan; we re-fetch
  // here so the dashboard can populate its own dropdown without coupling to
  // the panel's mount state). Value = model.path — same identity the backend's
  // vision_fallback_ladder uses; the backend's probe applies basename fallback
  // so a path pin matches a filename served-id on router-mode llama-servers.
  const [visionModelOptions, setVisionModelOptions] = useState<{ label: string; value: string }[]>([]);

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
      // REQ-5 (specs/local-model-lifecycle-sync): sync the resident model path
      // alongside the status so the Local Model card shows the loaded GGUF,
      // not just a LOADED badge. `model_path` is '' on unload (clear) and
      // undefined when the payload carried no path (leave unchanged).
      const modelPath = event.detail?.model_path;
      const pathUpdate =
        typeof modelPath === 'string'
          ? { local_model_path: modelPath }
          : {};
      setLocalFieldValues((prev) => ({
        ...prev,
        local_model: {
          ...(prev.local_model || {}),
          local_model_status: status,
          ...pathUpdate,
        },
        'local-model-card': {
          ...(prev['local-model-card'] || {}),
          local_model_status: status,
          ...pathUpdate,
        },
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

  // Vision-card dropdown: fetch the model scan (same endpoint the Models &
  // Browse panel uses) on mount and whenever the user lands on the automate
  // tab, filtered to vision-capable entries. Re-fetched on tab change so
  // adding a new vision model in the browse panel is reflected here. Bounded
  // fetch with abort so a backend restart doesn't wedge the UI (mirrors the
  // pattern in ModelBrowserPanel.fetchModels).
  useEffect(() => {
    let cancelled = false;
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 15000);
    (async () => {
      try {
        const res = await fetch('/api/models', { signal: ctl.signal });
        if (!res.ok) return;
        const data = await res.json();
        const models: any[] = Array.isArray(data?.models) ? data.models : [];
        const opts = models
          .filter((m) => m && m.has_vision && m.path)
          .map((m) => ({
            label: m.display_name || m.filename || m.path,
            value: m.path,
          }));
        if (!cancelled) setVisionModelOptions(opts);
      } catch {
        // Quietly degrade — the dropdown just shows the static empty list.
      } finally {
        clearTimeout(timer);
      }
    })();
    return () => {
      cancelled = true;
      ctl.abort();
    };
  }, [activeTab]);

  useEffect(() => {
    if (currentCategory && currentCategory !== 'voice' && currentCategory !== 'dashboard') {
      setActiveTab(currentCategory);
    }
  }, [currentCategory]);

  const sectionsData = useSectionsData();
  const activeSections = sectionsData[activeTab] || [];

  const handleTabChange = useCallback((tabId: string) => {
    setActiveTab(tabId);
    setActiveSubApp(null);
    setFindQuery('');
    selectSectionWs(tabId);
    // Persist so the app reopens on the same tab
    if (typeof window !== "undefined") {
      localStorage.setItem('iris_active_tab_v1', tabId)
    }
  }, [selectSectionWs]);

  const VIRTUAL_SUB_APPS = new Set(['browser', 'marketplace', 'models', 'hub']);

  const handleSubAppChange = useCallback((appId: string) => {
    // The Inference console is part of Monitor now; the old route (the
    // open_inference_console card action) lands on the Monitor tab.
    if (appId === 'inference_console') {
      handleTabChange('monitor');
      setMonitorOpenRow((r) => ({ row: 'stream', n: (r?.n ?? 0) + 1 }));
      return;
    }
    setActiveSubApp(appId);
    setFindQuery('');
    // Only send select_category for real backend categories
    if (!VIRTUAL_SUB_APPS.has(appId)) selectCategory(appId as any);
  }, [selectCategory, handleTabChange]);

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
    if (!initialSubApp) return;
    // The Inference console is part of Monitor now.
    if (initialSubApp === 'inference_console') handleSubAppChange('inference_console');
    else setActiveSubApp(initialSubApp);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a new initialSubApp navigates
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
      dirtySectionsRef.current.clear();
      setPristine({});
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
      // Closing now returns immediately; the cleanup persists the same dirty
      // sections (dirtySectionsRef is untouched on this path).
      if (sendMessage) {
        // WebSocket is instant and fire-and-forget; the HTTP keepalive POSTs in
        // the unmount cleanup are the reliable half of the pair. Only the
        // sections the user changed (dirtySectionsRef).
        unsavedSections(dirtySectionsRef.current, localFieldValues).forEach(([sectionId, values]) => {
          sendMessage('confirm_card', { section_id: sectionId, values });
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
      // Only the sections the user changed - nothing at all on a plain
      // open/close or React's dev double-mount.
      const unsaved = unsavedSections(dirtySectionsRef.current, localFieldValuesRef.current);
      if (unsaved.length === 0) return;
      savedOnCloseRef.current = true;
      dirtySectionsRef.current.clear();
      // Same shape as handleApplySettings. keepalive:true lets the request outlive unmount.
      try {
        unsaved.forEach(([sectionId, sectionValues]) => {
          fetch('/api/config/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ section_id: sectionId, card_id: sectionId, values: sectionValues }),
            keepalive: true,
          }).catch(() => { /* best-effort on close */ });
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

  // The rail's places. Settings: the six tabs, each with its count of changes not yet
  // applied. Surfaces: the four surfaces, with the telemetry the old badges showed
  // (running agent tasks, live web, tool count) from the same stores.
  const fieldDefaults = useMemo(() => {
    const d: Record<string, unknown> = {};
    for (const sections of Object.values(sectionsData)) for (const sec of sections) for (const f of sec.fields) d[changeKey(sec.id, f.id)] = f.defaultValue;
    return d;
  }, [sectionsData]);
  const changed = useMemo(() => changedKeys(pristine, fieldValues, fieldDefaults), [pristine, fieldValues, fieldDefaults]);
  const changedByPlace = useMemo(() => {
    const out: Record<string, number> = {};
    for (const [place, sections] of Object.entries(sectionsData)) {
      const ids = new Set(sections.map((sec) => sec.id));
      out[place] = changed.filter((k) => ids.has(changeSection(k))).length;
    }
    return out;
  }, [changed, sectionsData]);

  const settingsPlaces: RailPlace[] = MAIN_NODES_DATA.map((node) => ({
    id: node.id,
    label: node.label,
    badge: changedByPlace[node.id] || undefined,
    title: changedByPlace[node.id] ? `${node.label} — ${changedByPlace[node.id]} not applied` : node.label,
  }));
  const surfacePlaces: RailPlace[] = [
    {
      id: 'hub', label: 'Workspace hub',
      badge: runningAgentTasks > 0 ? runningAgentTasks : undefined,
      title: `Workspace hub — ${runningAgentTasks} running`,
    },
    {
      id: 'browser', label: 'Browser',
      badge: crawlState.active ? 'live' : undefined,
      title: crawlState.active ? 'Browser — live web' : 'Browser — web idle',
    },
    { id: 'models', label: 'Models', title: 'Browse and manage models' },
    {
      id: 'marketplace', label: 'Marketplace',
      title: mcpToolCount != null ? `Marketplace — ${mcpToolCount} tools` : 'Marketplace',
    },
  ];
  const currentPlace = activeSubApp ?? activeTab;
  const placeLabel =
    [...settingsPlaces, ...surfacePlaces].find((pl) => pl.id === currentPlace)?.label
    ?? (activeSubApp ? CATEGORY_LABELS[activeSubApp] : undefined)
    ?? CATEGORY_LABELS[activeTab]
    ?? 'Settings';

  const handleRailView = (v: RailView) => {
    if (v === railMode) return;
    if (v === 'settings') handleTabChange(activeTab);
    else handleSubAppChange(lastSurfaceRef.current);
  };
  const handleRailPlace = (id: string) => {
    if (railMode === 'settings') handleTabChange(id);
    else handleSubAppChange(id);
  };

  const reasoningModel =
    (role_bindings.find(r => r.role === 'reasoning')?.instance_id) || (localFieldValues?.local_model?.local_model_path as string) || 'No model';

  const renderNavigationRail = () => (
    <DashboardRail
      view={railMode}
      onView={handleRailView}
      places={railMode === 'settings' ? settingsPlaces : surfacePlaces}
      current={currentPlace}
      onPlace={handleRailPlace}
      folded={!isRailExpanded}
      palette={xurPalette}
      footer={
        <div className="iris-rail-foot" title={`${voiceState === 'error' ? 'Offline' : 'Online'} · Model: ${reasoningModel}`}>
          <div className="av"><User size={14} /></div>
          <div className="tx">
            <b>{voiceState === 'error' ? 'Offline' : 'Online'}</b>
            <small>Model: {reasoningModel}</small>
          </div>
        </div>
      }
    />
  );

  // The ◉ menu holds every control the old header row had, with the same handlers.
  const menuItems: WingMenuItem[] = [
    // Chat: only where the old "Open Chat" button showed.
    ...(((spotlightState === 'dashboardSpotlight' || uiState === 'dashboard_open') && onOpenChat) ? [{
      id: 'chat',
      label: 'Chat',
      title: 'Open Chat',
      glyph: <MessageSquare size={14} style={{ color: isChatOpen ? accent : undefined }} />,
      run: () => onOpenChat?.(),
    }] : []),
    // Detach / reattach — see the matching control in chat-view.
    {
      id: 'detach',
      label: isDetached ? 'Put the dashboard back' : 'Detach the wing',
      title: isDetached ? 'Put the dashboard back in the widget' : 'Move the dashboard to its own window',
      glyph: isDetached ? <Minimize2 size={14} /> : <Maximize2 size={14} />,
      run: async () => {
        if (isDetached) {
          await reattachWing('dashboard')
        } else if (await detachWing('dashboard')) {
          onClose?.()
        }
      },
    },
    {
      id: 'alerts',
      label: 'Alerts',
      title: 'Notifications',
      glyph: <Bell size={14} style={{ color: isNotificationsOpen || unreadCount > 0 ? accent : undefined }} />,
      run: () => onNotificationsClick?.(),
      hint: unreadCount > 0 ? String(unreadCount) : undefined,
      dot: unreadCount > 0,
    },
    // Open IRIS Launcher — re-open the separate launcher app if closed
    { id: 'launcher', label: 'IRIS launcher', title: 'Open IRIS Launcher', glyph: <ExternalLink size={14} />, run: () => openIrisLauncher() },
    ...(onClose ? [{ id: 'close', label: 'Close', title: 'Close Dashboard', glyph: <X size={14} />, run: () => handleCloseWithSave(), hint: 'Esc' }] : []),
  ];

  const renderHeader = () => (
    /* ref + onMouseDown make this bar the window's drag handle.
       Needed because a DETACHED dashboard wing is borderless — there is no OS
       titlebar to grab, so without this the user could open a dashboard on a
       second monitor and have no way to move it. Matches what the chat header
       already does. Buttons inside still work: useManualDragWindow only treats
       it as a drag past a 12px threshold, and swallows the click that follows
       a real drag so dragging from a button cannot also press it. */
    <div ref={dashboardHeaderRef} onMouseDown={handleHeaderDragStart} className="iris-hd-head" data-testid="dash-header" style={{ height: 52, cursor: 'grab' }}>
      {/* Live web-search pill — centred in the header, between the title and
          the ◉ menu.

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
          its content and max-w-full on the pill had nothing real to resolve
          against. Inline styles always apply, and left+right together are what
          give the band a definite width for the pill to truncate within. */}
      <div
        className="absolute inset-y-0 z-10 flex items-center justify-center pointer-events-none"
        style={{ left: 150, right: 56 }}
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

      {/* The brand Xur folds the rail to orbs only, and unfolds it. */}
      <button
        type="button"
        className="iris-hd-xbtn"
        title="Show or hide place names"
        aria-label="Show or hide place names"
        aria-expanded={isRailExpanded}
        onClick={() => setIsRailExpanded((v) => !v)}
      >
        <Xur size={40} palette={xurPalette} speed={voiceState === 'idle' ? 0.8 : 1.6} />
      </button>

      <div className="iris-dh-ttl">
        <b>{placeLabel}</b>
        <small data-testid="dash-sub">
          {activeSubApp
            ? 'surface'
            : <>
                {activeTab === 'monitor' ? 'settings · live' : 'settings'}
                {changed.length > 0 && <> · <em>{changed.length} not applied</em></>}
              </>}
        </small>
      </div>

      <WingMenu
        open={menuOpen}
        onToggle={() => setMenuOpen((o) => !o)}
        onClose={closeMenu}
        heading="Dashboard"
        ariaLabel="Dashboard controls"
        items={menuItems}
        dotColor={accent}
      />
    </div>
  );

  // The settings page: find field, rows, and the Apply bar where the chat's composer sits.
  const sectionLabelById = useMemo(() => {
    const m: Record<string, string> = {};
    for (const sections of Object.values(sectionsData)) for (const sec of sections) m[sec.id] = sec.label;
    return m;
  }, [sectionsData]);

  const renderSettingsPage = () => {
    const q = findQuery.trim();
    const changedSet = new Set(changed);
    const inferenceSummary = role_bindings.map((b) => `${b.role} ${b.model_override || b.instance_id}`).join(' · ');

    // The body of a section: its own panel (model routing) or its plain fields.
    const renderBody = (section: any) => section.id === 'model_inference' ? (
      <>
        <ModelRoutingTable providers={providers} role_bindings={role_bindings} />
        <ModelInferenceSection
          providers={providers}
          role_bindings={role_bindings}
          loading={infLoading}
          sendRoleBinding={sendRoleBinding}
          glowColor={accent}
          provider_presets={provider_presets}
          sendModelSelection={sendModelSelection}
          sendInferenceMode={sendInferenceMode}
          inferenceValues={fieldValues?.inference_mode}
          model_catalog={model_catalog}
        />
      </>
    ) : (
      (section.fields || []).map((field: any) => (
        <FieldRow key={field.id} field={field} glowColor={accent} fieldValues={fieldValues} sectionId={section.id} updateField={updateField} fieldErrors={fieldErrors} clearFieldError={clearFieldError} sendMessage={sendMessage} audioInputDevices={audioInputDevices} audioOutputDevices={audioOutputDevices} wakeWords={wakeWords} visionModelOptions={visionModelOptions} apiKeySaved={apiKeySaved} changed={changedSet.has(changeKey(section.id, field.id))} />
      ))
    );

    const renderRow = (section: any, forceOpen: boolean) => {
      const n = changed.filter((k) => changeSection(k) === section.id).length;
      const summary = section.id === 'model_inference' ? inferenceSummary : sectionSummary(section.fields || [], fieldValues?.[section.id]);
      // Not a list of plain fields (model routing, tool and skill lists): a pane with
      // its own layout and a small mono header, always open.
      if (!isPlainFieldSection(section)) {
        return (
          <section key={section.id} className="iris-pane" data-section={section.id} aria-label={section.label}>
            <h4>{section.label}{n > 0 && <span className="chg">{n} changed</span>}<small>{summary}</small></h4>
            <div className="iris-pane-body">{renderBody(section)}</div>
          </section>
        );
      }
      const isOpen = forceOpen || expandedSections.has(section.id);
      return (
        <div key={section.id} className={`iris-sec${isOpen ? ' open' : ''}`} data-section={section.id}>
          <button type="button" className="iris-srow" aria-expanded={isOpen} onClick={() => toggleSection(section.id)}>
            <span className="o" aria-hidden="true">{isOpen ? '●' : '○'}</span>
            <b>{section.label}</b>
            <small>{summary}</small>
            {n > 0 && <span className="chg">{n} changed</span>}
          </button>
          {isOpen && <div className="iris-fields">{renderBody(section)}</div>}
        </div>
      );
    };

    let body: React.ReactNode;
    if (q) {
      // Matches across every settings place (Monitor has its own page), grouped by place, shown open.
      const groups = MAIN_NODES_DATA.filter((n) => n.id !== 'monitor').map((node) => ({
        node,
        hits: (sectionsData[node.id] || []).filter((sec) => sectionMatches(sec, q)),
      })).filter((g) => g.hits.length > 0);
      body = groups.length === 0
        ? <div className="iris-empty"><b>No setting matches</b>Try a word like mic, wake, model or memory.</div>
        : groups.map((g) => (
            <div key={g.node.id} data-place-group={g.node.id}>
              <div className="iris-place-h">{g.node.label}</div>
              {g.hits.map((sec) => renderRow(sec, true))}
            </div>
          ));
    } else if (activeTab === 'monitor') {
      // Monitor tab — ONE page: Now / Inference stream / Usage / Logs / Diagnostics (+ Context in developer mode)
      body = <MonitorPage glowColor={glowColor} sendMessage={sendMessage} developerMode={irisMode === 'developer'} openRow={monitorOpenRow} />;
    } else {
      body = activeSections.length === 0
        ? <div className="iris-empty"><b>Nothing to set here</b>This place has no settings yet.</div>
        : activeSections.map((section: any) => renderRow(section, false));
    }

    const names = [...new Set(changed.map((k) => sectionLabelById[changeSection(k)] ?? SECTION_TO_LABEL[changeSection(k)] ?? changeSection(k)))].join(', ');
    return (
      <>
        <div className="iris-find">
          <input
            type="search"
            placeholder="Find a setting"
            aria-label="Find a setting"
            value={findQuery}
            onChange={(e) => setFindQuery(e.target.value)}
          />
          <small>{q ? 'all places' : 'type to find'}</small>
        </div>
        <div className="iris-dash-scroll" id="dscroll">{body}</div>
        <div className="iris-apply">
          <div className="sum" data-testid="apply-sum">
            {changed.length > 0 ? <><b>{changed.length} change{changed.length > 1 ? 's' : ''}</b> · {names}</> : 'All saved'}
          </div>
          <button
            type="button"
            className="iris-go"
            onClick={handleApplySettings}
            disabled={changed.length === 0 || applyStatus === 'applying'}
          >
            {applyStatus === 'applying' ? 'Applying…' : applyStatus === 'applied' ? '✓ Applied' : 'Apply'}
          </button>
        </div>
      </>
    );
  };

  const renderContentZone = () => (
    <div className="iris-dash-content">
    {!activeSubApp ? renderSettingsPage() : (
    <div className="flex-1 overflow-y-auto p-0">
       {activeSubApp === 'browser' ? (
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
                // T19 (REQ-3 AC3): saccadic burst flag — §...
                visionSaccadic={navOverlay.visionSaccadic}
                // T19 (REQ-10 AC10.1): current takeover, if one is open.
                takeover={navOverlay.takeover}
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
          <UnifiedMarketplaceModelsSurface key="marketplace" glowColor={glowColor} fontColor="white" sendMessage={sendMessage} />
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
    )}
    </div>
  );

  return (
    <div className="iris-dash w-full h-full min-h-0 overflow-hidden flex flex-col text-white relative" style={{ background: 'transparent', ...brandVars(brand) }}>
      {renderHeader()}
      {/* min-h-0 on the grid and on its content column is load-bearing, not
          cosmetic: a flex/grid item with overflow `visible` refuses to shrink
          below its content, so a long page grew the column and every
          `overflow-y-auto` inside it had nothing to overflow (the summary tab
          could not be scrolled). min-h-0 restores the ability to shrink. */}
      <div className="iris-dash-main" data-folded={!isRailExpanded}>
        {renderNavigationRail()}
        {renderContentZone()}
      </div>

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

