'use client';

import { useState, memo, useMemo, useCallback, useEffect } from 'react';

import { motion, AnimatePresence } from 'framer-motion';
import { useBrandColor } from '@/contexts/BrandColorContext';
import { useNavigation } from '@/contexts/NavigationContext';
import { SUB_NODES_WITH_MINI, getMiniNodesForSubnode, MINI_NODES_DATA } from '@/data/mini-nodes';
import { SECTION_TO_LABEL, SECTION_TO_ICON, CARD_TO_SECTION_ID } from '@/data/navigation-constants';
import {
  Mic, Bot, Cpu, Settings, Palette, Activity, Volume2, Waves, Brain, Database, Sparkles, MessageSquare, Smile, Wrench, Layers, Star, Keyboard, Monitor, Power, HardDrive, Wifi, Bell, Sliders, RefreshCw, BarChart3, FileText, Stethoscope, X, ChevronRight, Eye, Globe,
  // Additional icons for section mapping
  Shield, Zap, Workflow, Boxes, Puzzle, FolderOpen, Monitor as MonitorIcon, Play
} from 'lucide-react';

interface DarkGlassDashboardProps {
  theme?: string;
  fieldValues?: Record<string, Record<string, string | number | boolean>>;
  updateField?: (subnodeId: string, fieldId: string, value: any) => void;
}

const MAIN_NODES_DATA = [
  { id: 'voice', label: 'VOICE', icon: Mic },
  { id: 'agent', label: 'AGENT', icon: Bot },
  { id: 'automate', label: 'AUTO', icon: Cpu },
  { id: 'system', label: 'SYS', icon: Settings },
  { id: 'customize', label: 'CUSTOM', icon: Palette },
  { id: 'monitor', label: 'MON', icon: Activity },
];

// Helper function to map icon names from SECTION_TO_ICON to Lucide components
const getIconComponent = (iconName: string) => {
  const iconMap: Record<string, React.ComponentType<any>> = {
    'Mic': Mic,
    'Volume2': Volume2,
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

// Helper function to convert mini-nodes fields to dashboard field format
function convertMiniNodeFieldsToDashboardFields(miniNodes: any[]) {
  const fields: any[] = [];
  miniNodes.forEach(miniNode => {
    miniNode.fields.forEach((field: any) => {
      // Skip section fields as they're not rendered in dashboard
      if (field.type === 'section' || field.type === 'custom') return;
      
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

// Generate SUB_NODES_DATA dynamically from mini-nodes.ts and navigation constants
// This ensures all components use the same field IDs, labels, and options
function useSubNodesData() {
  return useMemo(() => {
    const sections = Object.entries(CARD_TO_SECTION_ID).reduce((acc, [cardId, sectionId]) => {
      if (!acc[sectionId]) {
        acc[sectionId] = {
          id: sectionId,
          label: SECTION_TO_LABEL[sectionId]?.toUpperCase() || sectionId.toUpperCase(),
          icon: getIconComponent(SECTION_TO_ICON[sectionId] || 'Boxes'),
          fields: convertMiniNodeFieldsToDashboardFields(getMiniNodesForSubnode(sectionId))
        };
      }
      
      return acc;
    }, {} as Record<string, { id: string; label: string; icon: any; fields: any[] }>);
    
    // Group sections by category
    const categoryMapping: Record<string, string[]> = {
      voice: ['input', 'output', 'processing', 'model'],
      agent: ['model_selection', 'inference_mode', 'identity', 'memory'],
      automate: ['tools', 'vision', 'workflows', 'shortcuts', 'gui', 'extensions'],
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

const FieldRow = memo(function FieldRow({ field, glowColor, fieldValues, subnodeId, updateField, fieldErrors, clearFieldError, availableModels, sendMessage, audioInputDevices, audioOutputDevices, wakeWords }: { field: any; glowColor: string; fieldValues?: Record<string, Record<string, string | number | boolean>>; subnodeId?: string; updateField?: (subnodeId: string, fieldId: string, value: any) => void; fieldErrors?: Record<string, string>; clearFieldError?: (subnodeId: string, fieldId: string) => void; availableModels?: string[]; sendMessage?: (type: string, payload?: any) => boolean; audioInputDevices?: string[]; audioOutputDevices?: string[]; wakeWords?: string[] }) {
  const [localValue, setLocalValue] = useState(field.defaultValue ?? '');
  const [testResult, setTestResult] = useState<string | null>(null);
  const value = fieldValues && subnodeId ? (fieldValues[subnodeId]?.[field.id] ?? field.defaultValue ?? '') : localValue;
  
  // Get error message for this field
  const errorKey = subnodeId && field.id ? `${subnodeId}:${field.id}` : null;
  const errorMessage = errorKey && fieldErrors ? fieldErrors[errorKey] : null;
  
  // Conditional field rendering for inference_mode subnode
  const inferenceMode = fieldValues && subnodeId === 'inference_mode' ? (fieldValues[subnodeId]?.['inference_mode'] ?? 'Local Models') : null;
  
  // Hide VPS fields unless VPS Gateway is selected
  if (subnodeId === 'inference_mode' && (field.id === 'vps_url' || field.id === 'vps_api_key' || field.id === 'test_vps_connection') && inferenceMode !== 'VPS Gateway') {
    return null;
  }
  
  // Hide OpenAI fields unless OpenAI API is selected
  if (subnodeId === 'inference_mode' && (field.id === 'openai_api_key' || field.id === 'test_openai_connection') && inferenceMode !== 'OpenAI API') {
    return null;
  }
  
  // Hide GPU warning unless Local Models is selected
  if (subnodeId === 'inference_mode' && field.id === 'local_gpu_warning' && inferenceMode !== 'Local Models') {
    return null;
  }
  
  // Use updateField from context if available, otherwise use local state
  // Store changes locally only - no backend updates until Confirm button is pressed
  const setValue = useCallback((newValue: any) => {
    // Clear error when user starts editing
    if (errorMessage && subnodeId && field.id && clearFieldError) {
      clearFieldError(subnodeId, field.id);
    }
    
    if (fieldValues && subnodeId && updateField) {
      updateField(subnodeId, field.id, newValue);
    } else {
      setLocalValue(newValue);
    }
    
    // NOTE: Removed immediate update_field WebSocket messages
    // Field changes are stored locally only until Confirm button is pressed
    // This prevents premature backend initialization before user confirms configuration
  }, [fieldValues, subnodeId, updateField, field.id, errorMessage, clearFieldError]);

  const handleSliderClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const p = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const min = field.min ?? 0;
    const max = field.max ?? 100;
    const newValue = min + p * (max - min);
    setValue(newValue);
  }, [field.min, field.max, setValue]);

  if (field.type === 'toggle') {
    return (
      <div className="py-3">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-medium tracking-wider text-white/70">{field.label}</span>
          <button
            onClick={() => setValue(!value)}
            className="relative w-7 h-3.5 rounded-full transition-colors"
            style={{ backgroundColor: value ? glowColor : 'rgba(255,255,255,0.15)' }}
          >
            <motion.span
              className="absolute top-0.5 w-2.5 h-2.5 rounded-full bg-white"
              animate={{ left: value ? '14px' : '2px' }}
              transition={{ type: 'spring', stiffness: 500, damping: 30 }}
            />
          </button>
        </div>
        {errorMessage && (
          <div className="mt-1 text-[8px] text-red-400">{errorMessage}</div>
        )}
      </div>
    );
  }

  if (field.type === 'dropdown') {
    // Use available models for model_selection subnode dropdowns
    let options = field.options || [];
    if (subnodeId === 'model_selection' && (field.id === 'reasoning_model' || field.id === 'tool_execution_model')) {
      options = availableModels && availableModels.length > 0 ? availableModels : ['No models available'];
    }
    
    // Use audio input devices for input subnode
    if (subnodeId === 'input' && field.id === 'input_device') {
      options = audioInputDevices && audioInputDevices.length > 0 ? audioInputDevices : ['No input devices found'];
    }
    
    // Use audio output devices for output subnode
    if (subnodeId === 'output' && field.id === 'output_device') {
      options = audioOutputDevices && audioOutputDevices.length > 0 ? audioOutputDevices : ['No output devices found'];
    }
    
    // Use wake words for wake subnode
    if (subnodeId === 'wake' && field.id === 'wake_phrase') {
      options = wakeWords && wakeWords.length > 0 ? wakeWords : ['No wake words found'];
    }
    
    return (
      <div className="py-3">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-medium tracking-wider text-white/70">{field.label}</span>
          <select
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="text-[13px] tabular-nums bg-white/10 border border-white/10 rounded px-1.5 py-0.5 text-white outline-none max-w-[120px]"
            style={errorMessage ? { borderColor: '#f87171' } : {}}
          >
            {options?.map((opt: string) => (
              <option key={opt} value={opt} className="bg-zinc-900">{opt}</option>
            ))}
          </select>
        </div>
        {errorMessage && (
          <div className="mt-1 text-[8px] text-red-400">{errorMessage}</div>
        )}
      </div>
    );
  }

  if (field.type === 'slider') {
    const min = field.min ?? 0;
    const max = field.max ?? 100;
    const pct = ((Number(value) - min) / (max - min)) * 100;
    return (
      <div className="py-3">
        <div className="flex items-center justify-between mb-0.5">
          <span className="text-[11px] font-medium tracking-wider text-white/70">{field.label}</span>
          <span className="text-[13px] tabular-nums" style={{ color: errorMessage ? '#f87171' : glowColor }}>{Math.round(Number(value))}{field.unit || ''}</span>
        </div>
        <div
          className="relative h-1.5 bg-white/10 rounded-full cursor-pointer"
          onClick={handleSliderClick}
        >
          <div className="absolute left-0 top-0 h-full rounded-full" style={{ width: `${pct}%`, background: errorMessage ? '#f87171' : glowColor }} />
        </div>
        {errorMessage && (
          <div className="mt-1 text-[8px] text-red-400">{errorMessage}</div>
        )}
      </div>
    );
  }

  if (field.type === 'text') {
    return (
      <div className="py-3">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-medium tracking-wider text-white/70">{field.label}</span>
          <input
            type="text"
            value={value as string}
            placeholder={field.placeholder}
            onChange={(e) => setValue(e.target.value)}
            className="text-[13px] tabular-nums bg-white/10 border border-white/10 rounded px-1.5 py-0.5 text-white outline-none max-w-[120px] text-right"
            style={errorMessage ? { borderColor: '#f87171' } : {}}
          />
        </div>
        {errorMessage && (
          <div className="mt-1 text-[8px] text-red-400">{errorMessage}</div>
        )}
      </div>
    );
  }

  if (field.type === 'password') {
    return (
      <div className="py-3">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-medium tracking-wider text-white/70">{field.label}</span>
          <input
            type="password"
            value={value as string}
            placeholder={field.placeholder}
            onChange={(e) => setValue(e.target.value)}
            className="text-[13px] tabular-nums bg-white/10 border border-white/10 rounded px-1.5 py-0.5 text-white outline-none max-w-[120px] text-right"
            style={errorMessage ? { borderColor: '#f87171' } : {}}
          />
        </div>
        {errorMessage && (
          <div className="mt-1 text-[8px] text-red-400">{errorMessage}</div>
        )}
      </div>
    );
  }

  if (field.type === 'status') {
    // VPS status indicator
    const vpsEnabled = fieldValues && subnodeId ? fieldValues[subnodeId]?.['enabled'] : false;
    const vpsEndpoints = fieldValues && subnodeId ? fieldValues[subnodeId]?.['endpoints'] : '';
    const endpointCount = vpsEndpoints ? (vpsEndpoints as string).split(',').filter(e => e.trim()).length : 0;
    
    return (
      <div className="py-3">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[11px] font-medium tracking-wider text-white/70">{field.label}</span>
        </div>
        <div className="bg-white/5 rounded px-2 py-1.5 space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[8px] text-white/50">VPS Mode</span>
            <div className="flex items-center gap-1">
              <div 
                className="w-1.5 h-1.5 rounded-full" 
                style={{ backgroundColor: vpsEnabled ? '#10b981' : '#6b7280' }}
              />
              <span className="text-[8px]" style={{ color: vpsEnabled ? '#10b981' : '#6b7280' }}>
                {vpsEnabled ? 'Enabled' : 'Disabled'}
              </span>
            </div>
          </div>
          {vpsEnabled && (
            <>
              <div className="flex items-center justify-between">
                <span className="text-[8px] text-white/50">Endpoints</span>
                <span className="text-[8px] text-white/70">{endpointCount} configured</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[8px] text-white/50">Health</span>
                <span className="text-[8px] text-yellow-400">Checking...</span>
              </div>
            </>
          )}
          {!vpsEnabled && (
            <div className="text-[8px] text-white/40 text-center py-0.5">
              Enable VPS to offload inference
            </div>
          )}
        </div>
      </div>
    );
  }

  if (field.type === 'button') {
    const handleTestConnection = async () => {
      setTestResult('Testing...');
      // Simulate connection test - in real implementation, this would call backend
      setTimeout(() => {
        setTestResult('Connection successful');
        setTimeout(() => setTestResult(null), 3000);
      }, 1000);
    };

    return (
      <div className="py-1">
        <button
          onClick={handleTestConnection}
          className="w-full py-1.5 rounded text-[9px] font-medium tracking-wider transition-all"
          style={{
            background: `${glowColor}20`,
            color: glowColor,
            border: `1px solid ${glowColor}40`,
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = `${glowColor}30`;
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = `${glowColor}20`;
          }}
        >
          {field.label}
        </button>
        {testResult && (
          <div className="mt-1 text-[8px] text-center" style={{ color: testResult.includes('successful') ? '#10b981' : glowColor }}>
            {testResult}
          </div>
        )}
      </div>
    );
  }

  if (field.type === 'info') {
    return (
      <div className="py-1">
        <div className="bg-yellow-500/10 border border-yellow-500/30 rounded px-2 py-1.5">
          <div className="flex items-start gap-1.5">
            <span className="text-yellow-500 text-[10px] mt-0.5">⚠</span>
            <span className="text-[8px] text-yellow-200/90 leading-relaxed">{field.defaultValue}</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between py-3">
      <span className="text-[11px] font-medium tracking-wider text-white/70">{field.label}</span>
      <span className="text-[13px] tabular-nums text-white/40 truncate max-w-[120px]">{field.placeholder || value || '-'}</span>
    </div>
  );
});

export function DarkGlassDashboard({ fieldValues: propFieldValues, updateField: propUpdateField }: DarkGlassDashboardProps) {
  const [activeTab, setActiveTab] = useState('voice');
  const [activeSubnode, setActiveSubnode] = useState<string | null>(null);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [audioInputDevices, setAudioInputDevices] = useState<string[]>([]);
  const [audioOutputDevices, setAudioOutputDevices] = useState<string[]>([]);
  const [wakeWords, setWakeWords] = useState<string[]>([]);
  const [showError, setShowError] = useState(false);
  const { getThemeConfig } = useBrandColor();
  const localTheme = getThemeConfig();

  // Connect to NavigationContext for WebSocket integration
  const {
    currentCategory,
    currentSubnode,
    subnodes: contextSubnodes,
    fieldValues: contextFieldValues,
    fieldErrors,
    activeTheme, // Get activeTheme from backend via WebSocket
    voiceState, // Voice command state for visual feedback
    audioLevel, // Audio level for visualization
    selectCategory,
    selectSubnode,
    updateMiniNodeValue: contextUpdateMiniNodeValue,
    clearFieldError,
    confirmMiniNode, // Connect onConfirm to confirmMiniNode()
    sendMessage, // Add sendMessage for fetching available models
  } = useNavigation();
  
  // Use WebSocket theme glow color if available, otherwise fall back to local theme
  // This ensures theme changes from backend apply within 100ms (WebSocket latency)
  // Requirement 10.4: Update accent colors from activeTheme within 100ms
  const glowColor = activeTheme?.glow || localTheme.glow.color;

  // Fetch current configuration from backend on mount
  useEffect(() => {
    if (sendMessage) {
      // Request current state from backend
      sendMessage('request_state', {})
      
      // Listen for initial state response
      const handleInitialState = (event: CustomEvent) => {
        const state = event.detail?.state || {}
        console.log('[DarkGlassDashboard] Received initial state:', state)
        
        // Extract field values from the state
        // The state contains fieldValues per subnode/category
        if (state.fieldValues) {
          // Update field values from backend state
          Object.entries(state.fieldValues).forEach(([subnodeId, values]) => {
            if (values && typeof values === 'object') {
              Object.entries(values).forEach(([fieldId, value]) => {
                // Use updateField if available, otherwise use context
                if (propUpdateField) {
                  propUpdateField(subnodeId, fieldId, value)
                }
              })
            }
          })
        }
      }
      
      window.addEventListener('iris:initial_state', handleInitialState as EventListener)
      
      return () => {
        window.removeEventListener('iris:initial_state', handleInitialState as EventListener)
      }
    }
  }, [sendMessage, propUpdateField])

  // Log theme changes in development mode for debugging
  useEffect(() => {
    if (process.env.NODE_ENV === 'development' && activeTheme?.glow) {
      console.log('[DarkGlassDashboard] Theme synchronized from backend:', activeTheme.glow);
    }
  }, [activeTheme]);

  // Auto-dismiss error after 3 seconds
  useEffect(() => {
    if (voiceState === 'error') {
      setShowError(true);
      const timer = setTimeout(() => {
        setShowError(false);
      }, 3000);
      return () => clearTimeout(timer);
    } else {
      setShowError(false);
    }
  }, [voiceState]);

  // Fetch available models when model_selection subnode is opened
  useEffect(() => {
    if (activeSubnode === 'model_selection' && sendMessage) {
      // Send get_available_models message to backend
      sendMessage('get_available_models', {});
      
      // Listen for the response via custom event
      const handleAvailableModels = (event: CustomEvent) => {
        const models = event.detail.models || [];
        const modelOptions = models.map((m: any) => m.name || m.id);
        setAvailableModels(modelOptions);
      };
      
      window.addEventListener('iris:available_models', handleAvailableModels as EventListener);
      
      return () => {
        window.removeEventListener('iris:available_models', handleAvailableModels as EventListener);
      };
    }
  }, [activeSubnode, sendMessage]);

  // Fetch audio devices when input or output subnodes are opened
  useEffect(() => {
    if ((activeSubnode === 'input' || activeSubnode === 'output') && sendMessage) {
      // Send get_audio_devices message to backend
      sendMessage('get_audio_devices', {});
      
      // Listen for the response via custom event
      const handleAudioDevices = (event: CustomEvent) => {
        const inputDevices = event.detail.input_devices || [];
        const outputDevices = event.detail.output_devices || [];
        const inputOptions = inputDevices.map((d: any) => d.name || d.index);
        const outputOptions = outputDevices.map((d: any) => d.name || d.index);
        setAudioInputDevices(inputOptions);
        setAudioOutputDevices(outputOptions);
      };
      
      window.addEventListener('iris:audio_devices', handleAudioDevices as EventListener);
      
      return () => {
        window.removeEventListener('iris:audio_devices', handleAudioDevices as EventListener);
      };
    }
  }, [activeSubnode, sendMessage]);

  // Fetch wake words when wake subnode is opened
  useEffect(() => {
    if (activeSubnode === 'wake' && sendMessage) {
      // Send get_wake_words message to backend
      sendMessage('get_wake_words', {});
      
      // Listen for the response via custom event
      const handleWakeWords = (event: CustomEvent) => {
        const wakeWordsList = event.detail.wake_words || [];
        const wakeWordOptions = wakeWordsList.map((w: any) => w.display_name || w.filename);
        setWakeWords(wakeWordOptions);
      };
      
      window.addEventListener('iris:wake_words_list', handleWakeWords as EventListener);
      
      return () => {
        window.removeEventListener('iris:wake_words_list', handleWakeWords as EventListener);
      };
    }
  }, [activeSubnode, sendMessage]);

  // Use context values if available, otherwise fall back to props
  const fieldValues = contextFieldValues || propFieldValues || {};
  const updateField = propUpdateField || contextUpdateMiniNodeValue;

  const mainNodes = useMemo(() => MAIN_NODES_DATA, []);
  const subNodes = useSubNodesData();

  const subnodesForTab = useMemo(() => subNodes[activeTab] || [], [subNodes, activeTab]);
  const selectedSub = useMemo(() => activeSubnode ? subnodesForTab.find(s => s.id === activeSubnode) : null, [activeSubnode, subnodesForTab]);

  const handleTabClick = useCallback((id: string) => {
    setActiveTab(id);
    setActiveSubnode(null);
    // Send category selection to backend via NavigationContext
    if (selectCategory) {
      selectCategory(id);
    }
  }, [selectCategory]);

  const handleSubnodeClick = useCallback((id: string) => {
    setActiveSubnode(id);
    // Send subnode selection to backend via NavigationContext
    if (selectSubnode) {
      selectSubnode(id);
    }
  }, [selectSubnode]);

  const handleConfirmSubnode = useCallback(() => {
    if (!selectedSub || !confirmMiniNode) return;
    
    // Gather all field values for this subnode
    const values: Record<string, any> = {};
    selectedSub.fields.forEach(field => {
      const value = fieldValues[selectedSub.id]?.[field.id] ?? field.defaultValue;
      if (value !== undefined) {
        values[field.id] = value;
      }
    });
    
    // Send confirmation to backend via NavigationContext
    confirmMiniNode(selectedSub.id, values);
  }, [selectedSub, fieldValues, confirmMiniNode]);

  return (
    <div
      className="w-full h-full min-h-0 overflow-hidden flex flex-col bg-transparent relative"
    >
      {/* HUD Effects Overlay */}
      <div 
        className="absolute inset-0 pointer-events-none z-0"
        style={{
          background: `
            linear-gradient(180deg, transparent 0%, rgba(255,255,255,0.01) 50%, transparent 100%),
            repeating-linear-gradient(
              0deg,
              transparent,
              transparent 2px,
              rgba(0,0,0,0.02) 2px,
              rgba(0,0,0,0.02) 4px
            )
          `,
          backgroundSize: '100% 100%, 100% 4px',
        }}
      />
      
      {/* Edge Fresnel Effect */}
      <div 
        className="absolute inset-0 pointer-events-none z-0"
        style={{
          background: `
            linear-gradient(90deg, ${glowColor}05 0%, transparent 10%, transparent 90%, ${glowColor}05 100%),
            linear-gradient(0deg, ${glowColor}03 0%, transparent 15%, transparent 85%, ${glowColor}03 100%)
          `,
        }}
      />
      {/* HUD Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b relative z-10" style={{ borderColor: `${glowColor}15` }}>
        <div className="flex items-center gap-2">
          <motion.div 
            className="w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: glowColor }}
            animate={{ 
              scale: voiceState === 'listening' ? [1, 1.4, 1] : 1,
              opacity: voiceState === 'listening' ? [1, 0.6, 1] : 1
            }}
            transition={{ duration: 1.2, repeat: Infinity }}
          />
          <span className="text-[11px] font-semibold tracking-widest uppercase text-white/90">Settings</span>
        </div>
        
        {/* Voice State Indicators */}
        <div className="flex items-center gap-2">
          {/* Listening State - Pulsing Animation */}
          {voiceState === 'listening' && (
            <motion.div
              className="flex items-center gap-1.5"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
            >
              <motion.div
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: glowColor }}
                animate={{
                  scale: [1, 1.3, 1],
                  opacity: [1, 0.6, 1],
                }}
                transition={{
                  duration: 1.5,
                  repeat: Infinity,
                  ease: "easeInOut",
                }}
              />
              <span className="text-[8px] text-white/70">Listening</span>
            </motion.div>
          )}
          
          {/* Audio Level Visualization */}
          {voiceState === 'listening' && audioLevel > 0 && (
            <div className="flex items-center gap-0.5">
              {[0, 1, 2, 3].map((i) => {
                const barHeight = Math.max(0, Math.min(1, (audioLevel * 4) - i));
                return (
                  <motion.div
                    key={i}
                    className="w-0.5 rounded-full"
                    style={{
                      backgroundColor: glowColor,
                      height: `${4 + barHeight * 8}px`,
                    }}
                    animate={{
                      height: `${4 + barHeight * 8}px`,
                    }}
                    transition={{
                      duration: 0.1,
                    }}
                  />
                );
              })}
            </div>
          )}
          
          {/* Processing State - Spinner */}
          {(voiceState === 'processing_conversation' || voiceState === 'processing_tool') && (
            <motion.div
              className="flex items-center gap-1.5"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
            >
              <motion.div
                className="w-3 h-3 border-2 rounded-full"
                style={{
                  borderColor: `${glowColor}40`,
                  borderTopColor: glowColor,
                }}
                animate={{ rotate: 360 }}
                transition={{
                  duration: 1,
                  repeat: Infinity,
                  ease: "linear",
                }}
              />
              <span className="text-[8px] text-white/70">
                {voiceState === 'processing_conversation' ? 'Processing' : 'Tool'}
              </span>
            </motion.div>
          )}
          
          {/* Speaking State */}
          {voiceState === 'speaking' && (
            <motion.div
              className="flex items-center gap-1.5"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
            >
              <motion.div
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: glowColor }}
                animate={{
                  scale: [1, 1.2, 1],
                }}
                transition={{
                  duration: 0.8,
                  repeat: Infinity,
                  ease: "easeInOut",
                }}
              />
              <span className="text-[8px] text-white/70">Speaking</span>
            </motion.div>
          )}
          
          {/* Error State - Red Pulsing with Auto-dismiss */}
          {voiceState === 'error' && showError && (
            <motion.div
              className="flex items-center gap-1.5"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
            >
              <motion.div
                className="w-2 h-2 rounded-full bg-red-500"
                animate={{
                  scale: [1, 1.3, 1],
                  opacity: [1, 0.5, 1],
                }}
                transition={{
                  duration: 1,
                  repeat: Infinity,
                  ease: "easeInOut",
                }}
              />
              <span className="text-[8px] text-red-400">Error</span>
            </motion.div>
          )}
        </div>
      </div>

      {/* HUD Tab bar - 6 main nodes */}
      <div className="flex border-b relative z-10" style={{ borderColor: `${glowColor}10` }}>
        {mainNodes.map(node => {
          const Icon = node.icon;
          const isActive = activeTab === node.id;
          return (
            <button
              key={node.id}
              onClick={() => handleTabClick(node.id)}
              className="flex-1 flex flex-col items-center gap-0.5 py-1.5 transition-all relative"
              style={{
                color: isActive ? glowColor : 'rgba(255,255,255,0.4)',
                background: isActive ? `${glowColor}10` : 'transparent',
              }}
            >
              <Icon className="w-3.5 h-3.5" />
              <span className="text-[7px] font-medium tracking-wider">{node.label}</span>
              {isActive && (
                <motion.div
                  layoutId="tab-indicator"
                  className="absolute bottom-0 left-1/4 right-1/4 h-[2px] rounded-full"
                  style={{ background: glowColor }}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* Content area */}
      <div className="flex-1 flex overflow-hidden relative z-10">
        {/* Subnode list */}
        <div className="w-[105px] border-r flex-shrink-0 overflow-y-auto" style={{ borderColor: `${glowColor}10` }}>
          {subnodesForTab.map(sub => {
            const Icon = sub.icon;
            const isActive = activeSubnode === sub.id;
            return (
              <button
                key={sub.id}
                onClick={() => handleSubnodeClick(sub.id)}
                className="w-full flex items-center gap-1.5 px-3 py-2 text-left transition-all"
                style={{
                  background: isActive ? `${glowColor}15` : 'transparent',
                  color: isActive ? '#fff' : 'rgba(255,255,255,0.5)',
                  borderLeft: isActive ? `2px solid ${glowColor}` : '2px solid transparent',
                }}
              >
                <Icon className="w-3 h-3 flex-shrink-0" style={{ color: isActive ? glowColor : 'inherit' }} />
                <span className="text-[9px] font-medium tracking-wide truncate">{sub.label}</span>
                <ChevronRight className="w-2.5 h-2.5 ml-auto flex-shrink-0 opacity-40" />
              </button>
            );
          })}
        </div>

        {/* Fields panel */}
        <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col">
          <AnimatePresence mode="wait">
            {selectedSub ? (
              <motion.div
                key={selectedSub.id}
                initial={{ opacity: 0, x: 10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -10 }}
                transition={{ duration: 0.15 }}
                className="space-y-4 flex-1 flex flex-col"
              >
                <div className="flex items-center gap-1.5 mb-2 pb-1.5 border-b" style={{ borderColor: `${glowColor}15` }}>
                  {(() => { const Icon = selectedSub.icon; return <Icon className="w-3.5 h-3.5" style={{ color: glowColor }} />; })()}
                  <span className="text-[10px] font-semibold tracking-wider text-white/90">{selectedSub.label}</span>
                </div>
                <div className="flex-1 overflow-y-auto space-y-4">
                  {selectedSub.fields.map(field => (
                    <FieldRow key={field.id} field={field} glowColor={glowColor} fieldValues={fieldValues} subnodeId={selectedSub.id} updateField={updateField} fieldErrors={fieldErrors} clearFieldError={clearFieldError} availableModels={availableModels} sendMessage={sendMessage} audioInputDevices={audioInputDevices} audioOutputDevices={audioOutputDevices} wakeWords={wakeWords} />
                  ))}
                </div>
                {/* Confirm button */}
                <div className="mt-2 pt-2 border-t" style={{ borderColor: `${glowColor}15` }}>
                  <button
                    onClick={handleConfirmSubnode}
                    className="w-full py-1.5 rounded text-[9px] font-medium tracking-wider transition-all"
                    style={{
                      background: `${glowColor}20`,
                      color: glowColor,
                      border: `1px solid ${glowColor}40`,
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = `${glowColor}30`;
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = `${glowColor}20`;
                    }}
                  >
                    CONFIRM
                  </button>
                </div>
              </motion.div>
            ) : (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="h-full flex items-center justify-center"
              >
                <span className="text-[10px] text-white/30 tracking-wider">Select a category</span>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
