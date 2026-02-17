'use client';

import { Plus, ChevronUp, ChevronDown, Trash2, Edit3, AlertTriangle } from 'lucide-react';

interface GlassRowProps {
  level: number;
  icon?: React.ElementType;
  label: string;
  expanded?: boolean;
  onToggle?: () => void;
  actions: ('chevron' | 'trash' | 'edit' | 'warning' | 'add')[];
  warning?: string;
}

export function GlassRow({
  level,
  icon: Icon = Plus,
  label,
  expanded,
  onToggle,
  actions,
  warning,
}: GlassRowProps) {
  const levelStyles = [
    'bg-white/[0.08] border-white/10',
    'bg-white/[0.05] border-white/5',
    'bg-white/[0.03] border-white/5',
    'bg-white/[0.02] border-white/5',
  ];

  return (
    <div
      className={`group flex items-center gap-3 px-4 py-3 rounded-xl border ${levelStyles[level]}
                 hover:bg-white/[0.12] transition-all duration-200`}
    >
      {actions.includes('add') && level < 3 && (
        <button
          onClick={onToggle}
          className="p-1 rounded hover:bg-white/10 transition-colors"
        >
          <Icon className={`w-4 h-4 text-white/60 ${level === 3 ? 'opacity-0' : ''}`} />
        </button>
      )}

      <span className="flex-1 text-sm text-white/90 font-medium">{label}</span>

      {warning && (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20">
          <AlertTriangle className="w-3 h-3 text-amber-400" />
          <span className="text-xs text-amber-200">{warning}</span>
        </div>
      )}

      {actions.includes('edit') && (
        <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/70 transition-colors">
          <Edit3 className="w-3 h-3" />
          Edit Activity
        </button>
      )}

      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {actions.includes('chevron') && level < 3 && (
          <button
            onClick={onToggle}
            className="p-1.5 rounded-lg hover:bg-white/10 transition-colors"
          >
            {expanded ? (
              <ChevronUp className="w-4 h-4 text-white/60" />
            ) : (
              <ChevronDown className="w-4 h-4 text-white/60" />
            )}
          </button>
        )}
        {actions.includes('trash') && (
          <button className="p-1.5 rounded-lg hover:bg-red-500/20 hover:text-red-400 transition-colors">
            <Trash2 className="w-4 h-4 text-white/40" />
          </button>
        )}
      </div>
    </div>
  );
}
