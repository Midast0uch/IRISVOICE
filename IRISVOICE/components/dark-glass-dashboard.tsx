'use client';

import { useState, memo, useMemo, useCallback, useEffect, useRef } from 'react';
import { CustomDropdown } from '@/components/ui/CustomDropdown';

import { motion, AnimatePresence } from 'framer-motion';
import { useBrandColor } from '@/contexts/BrandColorContext';
import { useNavigation } from '@/contexts/NavigationContext';
import type { MainCategoryId } from '@/data/navigation-ids';
import { CARDS_BY_SECTION, getCardsForSection, CARDS_DATA } from '@/data/cards';
import { SECTION_TO_LABEL, SECTION_TO_ICON, CARD_TO_SECTION_ID } from '@/data/navigation-constants';
import { ActivityPanel } from './dashboard/ActivityPanel';
import { LogsPanel } from './dashboard/LogsPanel';
import { MarketplaceScreen } from './integrations/MarketplaceScreen';
import {
  Mic, Bot, Cpu, Settings, Palette, Activity, Volume2, Waves, Brain, Database, Sparkles, MessageSquare, Smile, Wrench, Layers, Star, Keyboard, Monitor, Power, HardDrive, Wifi, Bell, Sliders, RefreshCw, BarChart3, FileText, Stethoscope, X, ChevronRight, ChevronLeft, ChevronDown, ChevronUp, Eye, Globe,
  Shield, Zap, Workflow, Boxes, Puzzle, FolderOpen, Monitor as MonitorIcon, Play, Volume1, MicVocal,
  LayoutDashboard, ShoppingBag, Menu, User, ArrowLeft, RotateCcw, Home, ArrowRight as ArrowRightIcon, ExternalLink, History, AlertCircle
} from 'lucide-react';

interface DarkGlassDashboardProps {
  theme?: string;
  fieldValues?: Record<string, Record<string, string | number | boolean>>;
  updateField?: (sectionId: string, fieldId: string, value: any) => void;
  onClose?: () => void;
  onNotificationsClick?: () => void;
  unreadCount?: number;
  spotlightState?: any; // From @/hooks/useUILayoutState
  uiState?: any;        // From @/hooks/useUILayoutState
  onOpenChat?: () => void;
}

const ACCENT_COLOR = '#00d4aa';

const MAIN_NODES_DATA = [
  { id: 'voice', label: 'Voice', icon: MicVocal },
  { id: 'agent', label: 'Agent', icon: Brain },
  { id: 'automate', label: 'Automate', icon: Workflow },
  { id: 'system', label: 'System', icon: Settings },
  { id: 'customize', label: 'Customize', icon: Palette },
  { id: 'monitor', label: 'Monitor', icon: BarChart3 },
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
      agent: ['model_selection', 'inference_mode', 'identity', 'memory'],
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

const FieldRow = memo(function FieldRow({ field, glowColor, fieldValues, sectionId, updateField, fieldErrors, clearFieldError, availableModels, sendMessage, audioInputDevices, audioOutputDevices, wakeWords }: { field: any; glowColor: string; fieldValues?: Record<string, Record<string, string | number | boolean>>; sectionId?: string; updateField?: (sectionId: string, fieldId: string, value: any) => void; fieldErrors?: Record<string, string>; clearFieldError?: (sectionId: string, fieldId: string) => void; availableModels?: string[]; sendMessage?: (type: string, payload?: any) => boolean; audioInputDevices?: string[]; audioOutputDevices?: string[]; wakeWords?: string[] }) {
  const [localValue, setLocalValue] = useState(field.defaultValue ?? '');
  const value = fieldValues && sectionId ? (fieldValues[sectionId]?.[field.id] ?? field.defaultValue ?? '') : localValue;
  
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
  }, [fieldValues, sectionId, updateField, field.id, errorMessage, clearFieldError]);

  const handleSliderClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const p = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const min = field.min ?? 0;
    const max = field.max ?? 100;
    const newValue = min + p * (max - min);
    setValue(newValue);
  }, [field.min, field.max, setValue]);

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
    return (
      <div className="py-2 col-span-full">
        <button
          onClick={() => setValue("trigger")}
          className="w-full py-2 px-3 rounded-xl text-[10px] font-bold uppercase tracking-wider transition-all"
          style={{
            background: `${glowColor}15`,
            border: `1px solid ${glowColor}44`,
            color: glowColor
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = `${glowColor}25`
            e.currentTarget.style.borderColor = `${glowColor}66`
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = `${glowColor}15`
            e.currentTarget.style.borderColor = `${glowColor}44`
          }}
        >
          {field.label}
        </button>
      </div>
    );
  }

  if (field.type === 'toggle') {
    return (
      <div className="flex items-center justify-between py-1.5 px-1">
        <span className="text-[11px] font-medium tracking-wide text-white/60">{field.label}</span>
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
    if (sectionId === 'model_selection' && (field.id === 'reasoning_model' || field.id === 'tool_model')) options = availableModels || [];
    if (sectionId === 'input' && field.id === 'input_device') options = audioInputDevices || [];
    if (sectionId === 'output' && field.id === 'output_device') options = audioOutputDevices || [];
    
    return (
      <div className="flex items-center justify-between py-2 gap-6 group/field px-1">
        <span className="text-[11px] font-semibold tracking-wide text-white/50 group-hover/field:text-white/80 transition-colors truncate">{field.label}</span>
        <div className="flex-1 max-w-[320px]">
          <CustomDropdown
            value={value}
            options={options}
            onChange={setValue}
            glowColor={glowColor}
            className="text-[10px] py-1 px-3 h-8 w-full"
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
  spotlightState,
  uiState,
  onOpenChat
}: DarkGlassDashboardProps) {
  const [activeTab, setActiveTab] = useState<string>('voice');
  const [activeSubApp, setActiveSubApp] = useState<string | null>(null);
  const [isRailExpanded, setIsRailExpanded] = useState(true);
  const [isSidebarHidden, setIsSidebarHidden] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['input', 'model_selection', 'tools', 'power', 'theme', 'analytics']));
  const [isApplying, setIsApplying] = useState(false);
  
  const [browserUrl, setBrowserUrl] = useState<string>('https://www.google.com');
  const [browserInput, setBrowserInput] = useState<string>('https://www.google.com');
  const iframeRef = useRef<HTMLIFrameElement>(null);

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
    clearFieldError,
    confirmCard,
    sendMessage,
  } = useNavigation();

  const fieldValues = propFieldValues || contextFieldValues;
  const updateField = propUpdateField || contextUpdateCardValue;

  const [availableModels] = useState<string[]>(['LFM-2-8B', 'gpt-4o', 'claude-3-5-sonnet']);
  const [audioInputDevices] = useState<string[]>(['Default Input', 'Internal Microphone']);
  const [audioOutputDevices] = useState<string[]>(['Default Output', 'Internal Speakers']);

  useEffect(() => {
    if (currentCategory && currentCategory !== 'voice' && currentCategory !== 'dashboard') {
      setActiveTab(currentCategory);
    }
  }, [currentCategory]);

  const sectionsData = useSectionsData();
  const activeSections = sectionsData[activeTab] || [];

  const handleSubAppChange = useCallback((appId: string) => {
    setActiveSubApp(appId);
    if (appId === 'browser' || appId === 'marketplace') {
      setIsSidebarHidden(true);
    } else {
      setIsSidebarHidden(false);
    }
    selectCategory(appId as any);
  }, [selectCategory]);

  const toggleSection = (sectionId: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      if (next.has(sectionId)) next.delete(sectionId);
      else next.add(sectionId);
      return next;
    });
  };

  const handleApplySettings = useCallback(async () => {
    setIsApplying(true);
    try {
      if (sendMessage && activeSections.length > 0) {
        // Send confirm_card for all sections in the current view to the backend
        for (const section of activeSections) {
          const sectionId = section.id;
          const sectionValues = fieldValues[sectionId] || {};
          sendMessage('confirm_card', { 
            section_id: sectionId, 
            values: sectionValues 
          });
          
          // Also update local confirmed state
          if (confirmCard) {
            confirmCard(sectionId, sectionValues);
          }
        }
      }
    } catch (error) {
      console.error("[DarkGlassDashboard] Apply failed:", error);
    } finally {
      setIsApplying(false);
    }
  }, [sendMessage, confirmCard, activeSections, fieldValues]);

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
  }, [selectSectionWs]);

  const renderNavigationRail = () => (
    <motion.nav 
      initial={false}
      animate={{ 
        width: isSidebarHidden ? 0 : (isRailExpanded ? 150 : 56),
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
            { id: 'marketplace', label: 'MARKET' }
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
        <div className="flex flex-col gap-5">
          {MAIN_NODES_DATA.map((node) => {
            const Icon = node.icon;
            const isActive = activeTab === node.id && !activeSubApp;
            return (
              <button
                key={node.id}
                onClick={() => handleTabChange(node.id)}
                className="group w-full flex items-center px-4 py-3 transition-colors relative"
              >
                <div className="absolute inset-y-1 inset-x-2 rounded-lg transition-colors" style={{ backgroundColor: isActive ? `${glowColor}10` : 'transparent' }} />
                <div className="relative flex items-center w-full">
                  <Icon className="w-4 h-4 flex-shrink-0" style={{ color: isActive ? glowColor : 'rgba(255,255,255,0.35)' }} />
                  {isRailExpanded && (
                    <span className="ml-3 text-[11px] font-black uppercase tracking-[0.2em]" style={{ color: isActive ? 'white' : 'rgba(255,255,255,0.4)' }}>
                      {node.label}
                    </span>
                  )}
                  {isActive && <div className="absolute -left-4 top-1 bottom-1 w-[2px]" style={{ backgroundColor: glowColor }} />}
                </div>
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
              <span className="text-[9px] text-white/40 truncate">Model: LFM-2-8B</span>
            </div>
          )}
        </div>
      </div>
    </motion.nav>
  );

  const renderHeader = () => (
    <div className="flex h-12 items-center justify-between pl-12 pr-24 border-b shrink-0 z-30" style={{ borderColor: 'rgba(255,255,255,0.05)', backgroundColor: 'transparent' }}>
      <div className="flex items-center gap-3">
        {(activeSubApp === 'browser' || activeSubApp === 'marketplace') && isSidebarHidden && (
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
      
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-0.5">
          {(spotlightState === 'dashboardSpotlight' || uiState === 'dashboard_open') && onOpenChat && (
            <button onClick={onOpenChat} className="p-2 rounded-lg transition-all group/icon" style={{ color: 'rgba(255,255,255,0.3)' }} title="Open Chat">
              <MessageSquare size={16} className="group-hover/icon:text-white transition-colors" />
            </button>
          )}
          <button onClick={onNotificationsClick} className="p-2 rounded-lg transition-all relative group/icon" style={{ color: unreadCount > 0 ? glowColor : 'rgba(255,255,255,0.3)' }}>
            <Bell size={16} className="group-hover/icon:text-white transition-colors" />
            {unreadCount > 0 && <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full" style={{ backgroundColor: glowColor }} />}
          </button>
          <button onClick={onClose} className="p-2 rounded-lg transition-all group/icon" style={{ color: 'rgba(255,255,255,0.3)' }}>
            <X size={16} className="group-hover/icon:text-white transition-colors" />
          </button>
        </div>
      </div>
    </div>
  );

  const renderActionBar = () => (
    <div className="flex items-center justify-between pl-12 pr-0 h-16 border-t bg-black/60 shrink-0 z-40" style={{ borderColor: 'rgba(255,255,255,0.05)' }}>
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/10">
          <Wifi className="w-3 h-3" style={{ color: glowColor }} />
          <span className="text-[9px] font-medium tracking-wide text-white/80">12MS</span>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/10">
          <Brain className="w-3 h-3" style={{ color: glowColor }} />
          <span className="text-[9px] font-medium tracking-wide text-white/80">LFM-2-8B READY</span>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/10">
          <Activity className="w-3 h-3" style={{ color: glowColor }} />
          <span className="text-[9px] font-medium tracking-wide text-white/80">{voiceState === 'listening' ? 'CONNECTED' : 'SYSTEM IDLE'}</span>
        </div>
      </div>
      <div className="flex items-center gap-4 ml-auto" style={{ marginRight: '52px' }}>
        <button 
          onClick={handleApplySettings} 
          disabled={isApplying} 
          className="px-8 py-2.5 rounded-lg text-[11px] font-bold tracking-wider transition-all disabled:opacity-50 text-white hover:text-black border border-white/10 hover:border-transparent" 
          style={{ 
            backgroundColor: 'transparent',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = glowColor;
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = 'transparent';
          }}
        >
          {isApplying ? 'COMMITTING...' : 'APPLY'}
        </button>
      </div>
    </div>
  );

  const renderContentZone = () => (
    <div className="flex-1 overflow-y-auto p-0">
       {!activeSubApp ? (
         <div className="w-full h-full pl-12 pr-24 py-10 space-y-3">
           {activeSections.map((section: any) => {
             const isExpanded = expandedSections.has(section.id);
             const sectionFields = section.fields || [];
             return (
               <div key={section.id} className="group/section overflow-hidden rounded-lg border transition-all mx-8" style={{ borderColor: isExpanded ? `${glowColor}30` : 'rgba(255,255,255,0.04)', backgroundColor: isExpanded ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.01)' }}>
                 <button onClick={() => toggleSection(section.id)} className="w-full h-11 px-5 flex items-center justify-between transition-all hover:bg-white/[0.04] relative group/btn">
                   <div className="flex items-center gap-3">
                     <section.icon size={14} style={{ color: isExpanded ? glowColor : 'white' }} />
                     <span className="text-[10px] font-black tracking-[0.2em] text-white/60 group-hover/btn:text-white uppercase">{section.label}</span>
                   </div>
                   <ChevronDown size={14} style={{ transform: isExpanded ? 'rotate(180deg)' : 'none', transition: 'transform 0.3s' }} className="text-white/30" />
                   <div className="absolute bottom-0 left-0 right-0 h-[2px] opacity-0 group-hover/section:opacity-100 transition-all" style={{ background: `linear-gradient(90deg, transparent, ${glowColor}, transparent)` }} />
                 </button>
                 {isExpanded && (
                   <div className="px-8 pb-8 pt-2">
                     <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-12 gap-y-2">
                       {sectionFields.map((field: any) => (
                         <FieldRow key={field.id} field={field} glowColor={glowColor} fieldValues={fieldValues} sectionId={section.id} updateField={updateField} fieldErrors={fieldErrors} clearFieldError={clearFieldError} availableModels={availableModels} />
                       ))}
                     </div>
                   </div>
                 )}
               </div>
             );
           })}
         </div>
       ) : activeSubApp === 'browser' ? (
         <div className="w-full h-full p-4 md:px-10">
           <div className="w-full h-full flex flex-col bg-black/40 rounded-2xl border border-white/5 overflow-hidden backdrop-blur-md">
            <div className="flex items-center gap-2 px-3 h-10 border-b border-white/5 bg-black/20">
              <button 
                onClick={() => {
                  try {
                    // This can fail if iframe content is cross-origin
                    if (iframeRef.current?.contentWindow) {
                      window.history.back(); // Fallback/default behavior for widget or non-iframe context
                    }
                  } catch (e) {
                    console.warn("Cross-origin navigation blocked", e);
                  }
                }} 
                className="p-1.5 hover:bg-white/5 rounded text-white/50 hover:text-white"
              >
                <ArrowLeft size={14} />
              </button>
              <input value={browserInput} onChange={(e) => setBrowserInput(e.target.value)} onKeyDown={handleBrowserInputSubmit} className="flex-1 text-[11px] rounded px-3 h-7 bg-white/5 border border-white/5 outline-none font-mono text-white" />
              <button onClick={() => window.open(browserUrl, '_blank')} className="p-1.5"><ExternalLink size={14} className="text-white/50" /></button>
            </div>
             <iframe ref={iframeRef} src={browserUrl} className="flex-1 w-full border-none bg-white" />
           </div>
         </div>
       ) : activeSubApp === 'activity' ? (
         <ActivityPanel key="activity" glowColor={glowColor} fontColor="white" />
       ) : activeSubApp === 'logs' ? (
         <LogsPanel key="logs" glowColor={glowColor} fontColor="white" />
       ) : activeSubApp === 'marketplace' ? (
         <MarketplaceScreen key="marketplace" glowColor={glowColor} fontColor="white" />
       ) : null}
    </div>
  );

  return (
    <div className="w-full h-full min-h-0 overflow-hidden flex flex-col text-white relative" style={{ background: 'transparent' }}>
      <div className="absolute inset-0 pointer-events-none opacity-20 bg-[url('/noise.png')] mix-blend-overlay z-0" />
      <div className="absolute inset-0 pointer-events-none z-10" style={{ boxShadow: `inset 0 0 60px ${glowColor}05` }} />
      <div className="flex-1 flex overflow-hidden relative z-20">
        {renderNavigationRail()}
        <div className="flex-1 flex flex-col overflow-hidden relative">
          {renderHeader()}
          <div className="flex-1 flex flex-col overflow-hidden">
            {renderContentZone()}
          </div>
        </div>
      </div>
      {renderActionBar()}
    </div>
  );
}
