/**
 * MarketplaceCard Component
 * 
 * Displays a marketplace server with install button and metadata.
 * 
 * _Requirements: 8.5
 */

'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { Download, Star, Shield, Globe, Server, Loader2, Check } from 'lucide-react';
import { cn } from '@/lib/utils';

// Simple Button component since @/components/ui/button doesn't exist
const Button = React.forwardRef<HTMLButtonElement, React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'default' | 'outline' | 'ghost', size?: 'default' | 'sm' | 'lg' }>(
  ({ className, variant = 'default', size = 'default', ...props }, ref) => {
    const variants = {
      default: 'bg-purple-600 text-white hover:bg-purple-700',
      outline: 'border border-gray-500/30 bg-transparent hover:bg-white/5',
      ghost: 'hover:bg-white/5',
    };
    const sizes = {
      default: 'h-9 px-4 py-2',
      sm: 'h-8 px-3',
      lg: 'h-11 px-8',
    };
    return (
      <button
        ref={ref}
        className={cn('inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors', variants[variant], sizes[size], className)}
        {...props}
      />
    );
  }
);
Button.displayName = 'Button';

// Simple Badge component since @/components/ui/badge doesn't exist
const Badge = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement> & { variant?: 'default' | 'secondary' | 'outline' }>(
  ({ className, variant = 'default', ...props }, ref) => {
    const variants = {
      default: 'bg-purple-600/20 text-purple-300 border-purple-500/30',
      secondary: 'bg-gray-500/20 text-gray-300 border-gray-500/30',
      outline: 'border border-gray-500/30 text-gray-300',
    };
    return (
      <div
        ref={ref}
        className={cn('inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium', variants[variant], className)}
        {...props}
      />
    );
  }
);
Badge.displayName = 'Badge';

interface MarketplaceServer {
  id: string;
  name: string;
  description: string;
  publisher: string;
  version: string;
  downloads: number;
  rating: number;
  category: string;
  tags: string[];
  icon?: string;
  source: 'official' | 'community' | 'installed';
  transport: 'stdio' | 'sse' | 'websocket';
  permissions: string[];
  installed?: boolean;
}

interface MarketplaceCardProps {
  server: MarketplaceServer;
  onInstall: () => void;
  isInstalling?: boolean;
}

const SOURCE_STYLES = {
  official: {
    badge: 'bg-green-500/20 text-green-300 border-green-500/30',
    icon: Shield,
  },
  community: {
    badge: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
    icon: Globe,
  },
  installed: {
    badge: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
    icon: Check,
  },
};

const TRANSPORT_ICONS = {
  stdio: Server,
  sse: Globe,
  websocket: Globe,
};

export function MarketplaceCard({ server, onInstall, isInstalling }: MarketplaceCardProps) {
  const sourceStyle = SOURCE_STYLES[server.source];
  const SourceIcon = sourceStyle.icon;
  const TransportIcon = TRANSPORT_ICONS[server.transport];

  const formatDownloads = (count: number) => {
    if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`;
    if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
    return count.toString();
  };

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className={cn(
        'group relative overflow-hidden rounded-xl',
        'bg-gradient-to-br from-white/[0.08] to-white/[0.02]',
        'border border-white/[0.08]',
        'hover:border-white/[0.15]',
        'transition-all duration-300',
        'hover:shadow-lg hover:shadow-indigo-500/10'
      )}
    >
      {/* Edge Fresnel Effect */}
      <div className="absolute inset-0 rounded-xl opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none">
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-indigo-500/30 to-transparent" />
        <div className="absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-purple-500/30 to-transparent" />
        <div className="absolute inset-y-0 left-0 w-px bg-gradient-to-b from-transparent via-indigo-500/30 to-transparent" />
        <div className="absolute inset-y-0 right-0 w-px bg-gradient-to-b from-transparent via-purple-500/30 to-transparent" />
      </div>

      <div className="p-5 relative">
        {/* Header */}
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            {/* Icon */}
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500/20 to-purple-500/20 flex items-center justify-center border border-white/10">
              <Server className="w-6 h-6 text-indigo-300" />
            </div>
            
            {/* Title & Publisher */}
            <div>
              <h3 className="font-semibold text-white group-hover:text-indigo-300 transition-colors">
                {server.name}
              </h3>
              <p className="text-xs text-slate-400">{server.publisher}</p>
            </div>
          </div>

          {/* Source Badge */}
          <Badge variant="outline" className={cn('text-xs', sourceStyle.badge)}>
            <SourceIcon className="w-3 h-3 mr-1" />
            {server.source.charAt(0).toUpperCase() + server.source.slice(1)}
          </Badge>
        </div>

        {/* Description */}
        <p className="text-sm text-slate-400 mb-4 line-clamp-2">
          {server.description}
        </p>

        {/* Tags */}
        <div className="flex flex-wrap gap-1.5 mb-4">
          {server.tags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="px-2 py-0.5 text-xs rounded-full bg-slate-800/50 text-slate-400 border border-slate-700/50"
            >
              {tag}
            </span>
          ))}
          {server.tags.length > 3 && (
            <span className="px-2 py-0.5 text-xs rounded-full bg-slate-800/50 text-slate-400">
              +{server.tags.length - 3}
            </span>
          )}
        </div>

        {/* Stats */}
        <div className="flex items-center gap-4 text-xs text-slate-500 mb-4">
          <div className="flex items-center gap-1">
            <Download className="w-3.5 h-3.5" />
            <span>{formatDownloads(server.downloads)}</span>
          </div>
          <div className="flex items-center gap-1">
            <Star className="w-3.5 h-3.5 text-yellow-500/80" />
            <span>{server.rating.toFixed(1)}</span>
          </div>
          <div className="flex items-center gap-1">
            <TransportIcon className="w-3.5 h-3.5" />
            <span className="uppercase">{server.transport}</span>
          </div>
        </div>

        {/* Install Button */}
        <Button
          onClick={onInstall}
          disabled={isInstalling || server.installed}
          className={cn(
            'w-full transition-all duration-200',
            server.installed
              ? 'bg-green-500/20 text-green-400 border border-green-500/30 hover:bg-green-500/30'
              : 'bg-gradient-to-r from-indigo-500 to-purple-500 text-white hover:from-indigo-400 hover:to-purple-400'
          )}
        >
          {isInstalling ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Installing...
            </>
          ) : server.installed ? (
            <>
              <Check className="w-4 h-4 mr-2" />
              Installed
            </>
          ) : (
            <>
              <Download className="w-4 h-4 mr-2" />
              Install
            </>
          )}
        </Button>
      </div>
    </motion.div>
  );
}
