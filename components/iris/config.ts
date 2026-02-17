
import { Mic, Brain, Bot, Settings, Database, Activity, Volume2, Headphones, AudioWaveform as Waveform, Link, Cpu, Sparkles, MessageSquare, Palette, Power, Keyboard, Minimize2, RefreshCw, History, FileStack, Trash2, Timer, Clock, BarChart3, DollarSign, TrendingUp, Check, Wrench, Layers, Star, Monitor, HardDrive, Wifi, Bell, Sliders, FileText, Stethoscope, Smile, Eye } from "lucide-react";
import type { ElementType } from "react";

export const SPIN_CONFIG = {
  radiusCollapsed: 0,
  radiusExpanded: 180,
  spinDuration: 1500,
  staggerDelay: 100,
  rotations: 2,
  ease: [0.4, 0, 0.2, 1] as const,
};

export const SUBMENU_CONFIG = {
  radius: 140,
  spinDuration: 1500,
  rotations: 2,
};

export const MINI_NODE_STACK_CONFIG = {
  size: 90,
  sizeConfirmed: 90,
  borderRadius: 16,
  stackDepth: 50,
  maxVisible: 4,
  offsetX: 0,
  offsetY: 0,
  distanceFromCenter: 260,
  scaleReduction: 0.08,
  padding: 16,
  fieldHeight: 36,
  fieldGap: 12,
};

export const ORBIT_CONFIG = {
  radius: 200,
  duration: 800,
  ease: [0.34, 1.56, 0.64, 1] as const,
};

export const NODE_POSITIONS = [
  { index: 0, angle: -90, id: "voice", label: "VOICE", icon: Mic, hasSubnodes: true },
  { index: 1, angle: -30, id: "agent", label: "AGENT", icon: Bot, hasSubnodes: true },
  { index: 2, angle: 30, id: "automate", label: "AUTOMATE", icon: Cpu, hasSubnodes: true },
  { index: 3, angle: 90, id: "system", label: "SYSTEM", icon: Settings, hasSubnodes: true },
  { index: 4, angle: 150, id: "customize", label: "CUSTOMIZE", icon: Palette, hasSubnodes: true },
  { index: 5, angle: 210, id: "monitor", label: "MONITOR", icon: Activity, hasSubnodes: true },
];

export const ICON_MAP: Record<string, ElementType> = {
  Mic, Brain, Bot, Settings, Database, Activity, Volume2, Headphones, Waveform,
  Link, Cpu, Sparkles, MessageSquare,
  Palette, Power, Keyboard, Minimize2, RefreshCw, History,
  FileStack, Trash2, Timer, Clock, BarChart3, DollarSign, TrendingUp,
  Wrench, Layers, Star, Monitor, HardDrive, Wifi, Bell, Sliders, FileText, Stethoscope, Smile, Eye,
};
