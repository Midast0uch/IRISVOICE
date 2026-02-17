'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useBrandColor } from '@/contexts/BrandColorContext';
import {
  Mic, Bot, Cpu, Settings, Palette, Activity,
  Volume2, AudioWaveform as Waveform, Brain, Database,
  Sparkles, MessageSquare, Smile,
  Wrench, Layers, Star, Keyboard, Monitor,
  Power, HardDrive, Wifi,
  Bell, Sliders, RefreshCw,
  BarChart3, FileText, Stethoscope,
  X, ChevronRight, Eye,
} from 'lucide-react';

interface DarkGlassDashboardProps {
  theme?: string;
  isOpen: boolean;
  onClose: () => void;
  fieldValues?: Record<string, Record<string, string | number | boolean>>;
  updateField?: (subnodeId: string, fieldId: string, value: any) => void;
}

const MAIN_NODES = [
  { id: 'voice', label: 'VOICE', icon: Mic },
  { id: 'agent', label: 'AGENT', icon: Bot },
  { id: 'automate', label: 'AUTO', icon: Cpu },
  { id: 'system', label: 'SYS', icon: Settings },
  { id: 'customize', label: 'CUSTOM', icon: Palette },
  { id: 'monitor', label: 'MON', icon: Activity },
];

const SUB_NODES: Record<string, { id: string; label: string; icon: any; fields: { id: string; label: string; type: string; options?: string[]; defaultValue?: any; min?: number; max?: number; unit?: string; placeholder?: string }[] }[]> = {
  voice: [
    {
      id: 'input', label: 'INPUT', icon: Mic, fields: [
        { id: 'input_device', label: 'Input Device', type: 'dropdown', options: ['Default', 'USB Microphone', 'Headset', 'Webcam'], defaultValue: 'Default' },
        { id: 'input_sensitivity', label: 'Sensitivity', type: 'slider', min: 0, max: 100, unit: '%', defaultValue: 50 },
        { id: 'noise_gate', label: 'Noise Gate', type: 'toggle', defaultValue: false },
        { id: 'vad', label: 'VAD', type: 'toggle', defaultValue: true },
      ]
    },
    {
      id: 'output', label: 'OUTPUT', icon: Volume2, fields: [
        { id: 'output_device', label: 'Output Device', type: 'dropdown', options: ['Default', 'Headphones', 'Speakers', 'HDMI'], defaultValue: 'Default' },
        { id: 'master_volume', label: 'Volume', type: 'slider', min: 0, max: 100, unit: '%', defaultValue: 70 },
      ]
    },
    {
      id: 'processing', label: 'PROCESSING', icon: Waveform, fields: [
        { id: 'noise_reduction', label: 'Noise Reduction', type: 'toggle', defaultValue: true },
        { id: 'echo_cancellation', label: 'Echo Cancel', type: 'toggle', defaultValue: true },
        { id: 'voice_enhancement', label: 'Enhancement', type: 'toggle', defaultValue: false },
        { id: 'automatic_gain', label: 'Auto Gain', type: 'toggle', defaultValue: true },
      ]
    },
    {
      id: 'model', label: 'MODEL', icon: Brain, fields: [
        { id: 'endpoint', label: 'LFM Endpoint', type: 'text', placeholder: 'http://192.168.0.32:1234', defaultValue: 'http://192.168.0.32:1234' },
        { id: 'temperature', label: 'Temperature', type: 'slider', min: 0, max: 2, defaultValue: 0.7 },
        { id: 'max_tokens', label: 'Max Tokens', type: 'slider', min: 256, max: 8192, defaultValue: 2048 },
      ]
    },
  ],
  agent: [
    {
      id: 'identity', label: 'IDENTITY', icon: Smile, fields: [
        { id: 'assistant_name', label: 'Name', type: 'text', placeholder: 'IRIS', defaultValue: 'IRIS' },
        { id: 'personality', label: 'Personality', type: 'dropdown', options: ['Professional', 'Friendly', 'Concise', 'Creative', 'Technical'], defaultValue: 'Friendly' },
        { id: 'knowledge', label: 'Knowledge', type: 'dropdown', options: ['General', 'Coding', 'Writing', 'Research'], defaultValue: 'General' },
      ]
    },
    {
      id: 'wake', label: 'WAKE', icon: Sparkles, fields: [
        { id: 'wake_phrase', label: 'Wake Phrase', type: 'text', placeholder: 'Hey Computer', defaultValue: 'Hey Computer' },
        { id: 'detection_sensitivity', label: 'Sensitivity', type: 'slider', min: 0, max: 100, defaultValue: 70, unit: '%' },
        { id: 'activation_sound', label: 'Sound', type: 'toggle', defaultValue: true },
      ]
    },
    {
      id: 'speech', label: 'SPEECH', icon: MessageSquare, fields: [
        { id: 'tts_voice', label: 'TTS Voice', type: 'dropdown', options: ['Nova', 'Alloy', 'Echo', 'Fable', 'Onyx', 'Shimmer'], defaultValue: 'Nova' },
        { id: 'speaking_rate', label: 'Rate', type: 'slider', min: 0.5, max: 2, defaultValue: 1.0, unit: 'x' },
      ]
    },
    {
      id: 'memory', label: 'MEMORY', icon: Database, fields: [
        { id: 'token_count', label: 'Tokens', type: 'text', placeholder: '0 tokens' },
        { id: 'clear_memory', label: 'Clear Memory', type: 'text', placeholder: 'Clear' },
      ]
    },
  ],
  automate: [
    {
      id: 'tools', label: 'TOOLS', icon: Wrench, fields: [
        { id: 'active_servers', label: 'Servers', type: 'text', placeholder: 'Status' },
        { id: 'tool_browser', label: 'Browser', type: 'text', placeholder: 'Browse' },
      ]
    },
    {
      id: 'vision', label: 'VISION', icon: Eye, fields: [
        { id: 'vision_enabled', label: 'Vision', type: 'toggle', defaultValue: false },
        { id: 'screen_context', label: 'Screen in Chat', type: 'toggle', defaultValue: true },
        { id: 'proactive_monitor', label: 'Proactive', type: 'toggle', defaultValue: false },
        { id: 'monitor_interval', label: 'Interval', type: 'slider', min: 5, max: 120, defaultValue: 30, unit: 's' },
        { id: 'ollama_endpoint', label: 'Endpoint', type: 'text', placeholder: 'http://localhost:11434', defaultValue: 'http://localhost:11434' },
        { id: 'vision_model', label: 'Model', type: 'dropdown', options: ['minicpm-o4.5', 'llava', 'bakllava'], defaultValue: 'minicpm-o4.5' },
      ]
    },
    {
      id: 'workflows', label: 'WORKFLOWS', icon: Layers, fields: [
        { id: 'workflow_list', label: 'Workflows', type: 'text', placeholder: 'Saved' },
        { id: 'schedule', label: 'Schedule', type: 'text', placeholder: 'Schedule' },
      ]
    },
    {
      id: 'shortcuts', label: 'SHORTCUTS', icon: Keyboard, fields: [
        { id: 'global_hotkey', label: 'Hotkey', type: 'text', placeholder: 'Ctrl+Space', defaultValue: 'Ctrl+Space' },
      ]
    },
    {
      id: 'gui', label: 'GUI AUTO', icon: Monitor, fields: [
        { id: 'ui_tars_provider', label: 'Provider', type: 'dropdown', options: ['cli_npx', 'native_python', 'api_cloud'], defaultValue: 'native_python' },
        { id: 'model_provider', label: 'Vision Model', type: 'dropdown', options: ['minicpm_ollama', 'anthropic', 'volcengine', 'local'], defaultValue: 'minicpm_ollama' },
        { id: 'max_steps', label: 'Max Steps', type: 'slider', min: 5, max: 50, defaultValue: 25 },
        { id: 'safety_confirmation', label: 'Confirm', type: 'toggle', defaultValue: true },
      ]
    },
  ],
  system: [
    {
      id: 'power', label: 'POWER', icon: Power, fields: [
        { id: 'power_profile', label: 'Profile', type: 'dropdown', options: ['Balanced', 'Performance', 'Battery'], defaultValue: 'Balanced' },
      ]
    },
    {
      id: 'display', label: 'DISPLAY', icon: Monitor, fields: [
        { id: 'brightness', label: 'Brightness', type: 'slider', min: 0, max: 100, defaultValue: 50, unit: '%' },
        { id: 'night_mode', label: 'Night Mode', type: 'toggle', defaultValue: false },
      ]
    },
    {
      id: 'storage', label: 'STORAGE', icon: HardDrive, fields: [
        { id: 'disk_usage', label: 'Usage', type: 'text', placeholder: 'Usage' },
      ]
    },
    {
      id: 'network', label: 'NETWORK', icon: Wifi, fields: [
        { id: 'wifi_toggle', label: 'WiFi', type: 'toggle', defaultValue: true },
        { id: 'vpn_connection', label: 'VPN', type: 'dropdown', options: ['None', 'Work', 'Personal'], defaultValue: 'None' },
      ]
    },
  ],
  customize: [
    {
      id: 'theme', label: 'THEME', icon: Palette, fields: [
        { id: 'theme_mode', label: 'Mode', type: 'dropdown', options: ['Dark', 'Light', 'Auto'], defaultValue: 'Dark' },
        { id: 'state_colors', label: 'State Colors', type: 'toggle', defaultValue: false },
      ]
    },
    {
      id: 'startup', label: 'STARTUP', icon: Power, fields: [
        { id: 'launch_startup', label: 'Launch at Start', type: 'toggle', defaultValue: false },
        { id: 'startup_behavior', label: 'Behavior', type: 'dropdown', options: ['Show Widget', 'Minimized', 'Hidden'], defaultValue: 'Show Widget' },
      ]
    },
    {
      id: 'behavior', label: 'BEHAVIOR', icon: Sliders, fields: [
        { id: 'confirm_destructive', label: 'Confirm', type: 'toggle', defaultValue: true },
        { id: 'auto_save', label: 'Auto Save', type: 'toggle', defaultValue: true },
      ]
    },
    {
      id: 'notifications', label: 'NOTIFS', icon: Bell, fields: [
        { id: 'dnd_toggle', label: 'Do Not Disturb', type: 'toggle', defaultValue: false },
        { id: 'notification_sound', label: 'Sound', type: 'dropdown', options: ['Default', 'Chime', 'Pulse', 'Silent'], defaultValue: 'Default' },
      ]
    },
  ],
  monitor: [
    {
      id: 'analytics', label: 'ANALYTICS', icon: BarChart3, fields: [
        { id: 'token_usage', label: 'Tokens', type: 'text', placeholder: 'Usage' },
        { id: 'response_latency', label: 'Latency', type: 'text', placeholder: 'Latency' },
      ]
    },
    {
      id: 'logs', label: 'LOGS', icon: FileText, fields: [
        { id: 'system_logs', label: 'System', type: 'text', placeholder: 'System' },
        { id: 'voice_logs', label: 'Voice', type: 'text', placeholder: 'Voice' },
      ]
    },
    {
      id: 'diagnostics', label: 'DIAG', icon: Stethoscope, fields: [
        { id: 'health_check', label: 'Health', type: 'text', placeholder: 'Run' },
        { id: 'mcp_test', label: 'MCP Test', type: 'text', placeholder: 'Test' },
      ]
    },
    {
      id: 'updates', label: 'UPDATES', icon: RefreshCw, fields: [
        { id: 'update_channel', label: 'Channel', type: 'dropdown', options: ['Stable', 'Beta', 'Nightly'], defaultValue: 'Stable' },
        { id: 'auto_update', label: 'Auto Update', type: 'toggle', defaultValue: true },
      ]
    },
  ],
};

function FieldRow({ field, glowColor, fieldValues, subnodeId, updateField }: { field: any; glowColor: string; fieldValues?: Record<string, Record<string, string | number | boolean>>; subnodeId?: string; updateField?: (subnodeId: string, fieldId: string, value: any) => void }) {
  const [localValue, setLocalValue] = useState(field.defaultValue ?? '');
  const value = fieldValues && subnodeId ? (fieldValues[subnodeId]?.[field.id] ?? field.defaultValue ?? '') : localValue;
  const setValue = fieldValues && subnodeId && updateField ? (newValue: any) => updateField(subnodeId, field.id, newValue) : setLocalValue;

  if (field.type === 'toggle') {
    return (
      <div className="flex items-center justify-between py-1">
        <span className="text-[9px] text-white/70">{field.label}</span>
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
    );
  }

  if (field.type === 'dropdown') {
    return (
      <div className="flex items-center justify-between py-1">
        <span className="text-[9px] text-white/70">{field.label}</span>
        <select
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="text-[9px] bg-white/10 border border-white/10 rounded px-1.5 py-0.5 text-white outline-none max-w-[80px]"
        >
          {field.options?.map((opt: string) => (
            <option key={opt} value={opt} className="bg-zinc-900">{opt}</option>
          ))}
        </select>
      </div>
    );
  }

  if (field.type === 'slider') {
    const min = field.min ?? 0;
    const max = field.max ?? 100;
    const pct = ((value - min) / (max - min)) * 100;
    return (
      <div className="py-1">
        <div className="flex items-center justify-between mb-0.5">
          <span className="text-[9px] text-white/70">{field.label}</span>
          <span className="text-[8px] tabular-nums" style={{ color: glowColor }}>{Math.round(value)}{field.unit || ''}</span>
        </div>
        <div
          className="relative h-1.5 bg-white/10 rounded-full cursor-pointer"
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const p = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
            const newValue = min + p * (max - min);
            setValue(newValue);
          }}
        >
          <div className="absolute left-0 top-0 h-full rounded-full" style={{ width: `${pct}%`, background: glowColor }} />
        </div>
      </div>
    );
  }

  if (field.type === 'text') {
    return (
      <div className="flex items-center justify-between py-1">
        <span className="text-[9px] text-white/70">{field.label}</span>
        <input
          type="text"
          value={value as string}
          placeholder={field.placeholder}
          onChange={(e) => setValue(e.target.value)}
          className="text-[9px] bg-white/10 border border-white/10 rounded px-1.5 py-0.5 text-white outline-none max-w-[80px] text-right"
        />
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-[9px] text-white/70">{field.label}</span>
      <span className="text-[8px] text-white/40 truncate max-w-[80px]">{field.placeholder || value || '-'}</span>
    </div>
  );
}

export function DarkGlassDashboard({ isOpen, onClose, fieldValues, updateField }: DarkGlassDashboardProps) {
  const [activeTab, setActiveTab] = useState('voice');
  const [activeSubnode, setActiveSubnode] = useState<string | null>(null);
  const { getThemeConfig } = useBrandColor();
  const theme = getThemeConfig();
  const glowColor = theme.glow.color;

  const subnodes = SUB_NODES[activeTab] || [];
  const selectedSub = activeSubnode ? subnodes.find(s => s.id === activeSubnode) : null;

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.9 }}
          transition={{ duration: 0.25, ease: 'easeOut' }}
          className="absolute inset-0 z-[300] flex items-center justify-center pointer-events-auto"
          onClick={(e) => e.stopPropagation()}
        >
          <div
            className="w-[420px] h-[420px] rounded-2xl overflow-hidden flex flex-col"
            style={{
              background: 'rgba(10, 10, 20, 0.95)',
              backdropFilter: 'blur(30px)',
              border: `1px solid ${glowColor}30`,
              boxShadow: `0 0 40px ${glowColor}15, inset 0 1px 0 rgba(255,255,255,0.05)`,
            }}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: `${glowColor}20` }}>
              <span className="text-[11px] font-semibold tracking-widest uppercase text-white/90">IRIS MENU</span>
              <button
                onClick={onClose}
                className="p-1 rounded-md hover:bg-white/10 transition-colors"
              >
                <X className="w-3.5 h-3.5 text-white/60" />
              </button>
            </div>

            {/* Tab bar - 6 main nodes */}
            <div className="flex border-b" style={{ borderColor: `${glowColor}15` }}>
              {MAIN_NODES.map(node => {
                const Icon = node.icon;
                const isActive = activeTab === node.id;
                return (
                  <button
                    key={node.id}
                    onClick={() => { setActiveTab(node.id); setActiveSubnode(null); }}
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
            <div className="flex-1 flex overflow-hidden">
              {/* Subnode list */}
              <div className="w-[105px] border-r flex-shrink-0 overflow-y-auto" style={{ borderColor: `${glowColor}10` }}>
                {subnodes.map(sub => {
                  const Icon = sub.icon;
                  const isActive = activeSubnode === sub.id;
                  return (
                    <button
                      key={sub.id}
                      onClick={() => setActiveSubnode(sub.id)}
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
              <div className="flex-1 overflow-y-auto px-3 py-2">
                <AnimatePresence mode="wait">
                  {selectedSub ? (
                    <motion.div
                      key={selectedSub.id}
                      initial={{ opacity: 0, x: 10 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: -10 }}
                      transition={{ duration: 0.15 }}
                      className="space-y-0.5"
                    >
                      <div className="flex items-center gap-1.5 mb-2 pb-1.5 border-b" style={{ borderColor: `${glowColor}15` }}>
                        {(() => { const Icon = selectedSub.icon; return <Icon className="w-3.5 h-3.5" style={{ color: glowColor }} />; })()}
                        <span className="text-[10px] font-semibold tracking-wider text-white/90">{selectedSub.label}</span>
                      </div>
                      {selectedSub.fields.map(field => (
                        <FieldRow key={field.id} field={field} glowColor={glowColor} fieldValues={fieldValues} subnodeId={selectedSub.id} updateField={updateField} />
                      ))}
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
        </motion.div>
      )}
    </AnimatePresence>
  );
}
