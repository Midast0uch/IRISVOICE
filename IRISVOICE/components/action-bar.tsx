'use client';

import { motion } from 'framer-motion';
import { useBrandColor } from '@/contexts/BrandColorContext';
import {
  Activity,
  Wifi,
  Zap,
  Shield,
  Cpu,
  HardDrive,
  Globe,
  Battery,
  Thermometer,
  Clock,
  AlertCircle,
  CheckCircle2,
} from 'lucide-react';

interface StatusItem {
  icon: React.ComponentType<any>;
  label: string;
  value?: string | number;
  status?: 'good' | 'warning' | 'error' | 'neutral';
}

export function ActionBar({ statusItems = [] }: { statusItems?: StatusItem[] }) {
  const { getThemeConfig } = useBrandColor();
  const localTheme = getThemeConfig();
  
  return (
    <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-4 py-2 rounded-full backdrop-blur-xl border">
      {/* Status Indicators */}
      {statusItems.map((item, index) => {
        const Icon = item.icon;
        const statusColors: Record<string, string> = {
          good: '#10b981',
          warning: '#f59e0b',
          error: '#ef4444',
          neutral: 'rgba(255,255,255,0.6)',
        };
        
        return (
          <motion.div
            key={index}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white/5 border border-white/10"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.05 }}
          >
            <Icon className="w-3 h-3" style={{ color: item.status ? statusColors[item.status] : localTheme.glow.color || 'rgba(255,255,255,0.6)' }} />
            {item.value && (
              <span className="text-[9px] font-medium tracking-wide text-white/80">
                {typeof item.value === 'number' ? item.value.toFixed(1) : item.value}
              </span>
            )}
          </motion.div>
        );
      })}

      {/* Divider */}
      <div className="w-px h-4 bg-white/20" />

      {/* System Health Summary */}
      <motion.div
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white/5 border border-white/10"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <Activity className="w-3 h-3" style={{ color: localTheme.glow.color || 'rgba(255,255,255,0.6)' }} />
        <span className="text-[9px] font-medium tracking-wide text-white/80">
          System Healthy
        </span>
      </motion.div>
    </div>
  );
}
