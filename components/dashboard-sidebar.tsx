'use client';

import {
  LayoutDashboard,
  BookOpen,
  FileText,
  Image as ImageIcon,
  CheckSquare,
  Settings,
  LogOut,
  User,
} from 'lucide-react';
import { useDashboardTheme, dashboardThemes } from '@/contexts/DashboardThemeContext';

interface NavItemProps {
  icon: React.ElementType;
  label: string;
  active?: boolean;
  badge?: string;
}

function NavItem({ icon: Icon, label, active = false, badge }: NavItemProps) {
  const theme = useDashboardTheme();
  const t = dashboardThemes[theme];

  return (
    <button
      className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all
                 ${active
          ? `bg-white/10 text-white border border-${t.primary}/30`
          : 'text-white/60 hover:bg-white/5 hover:text-white'}`}
    >
      <Icon className="w-5 h-5" />
      <span className="flex-1 text-left">{label}</span>
      {badge && (
        <span className={`px-2 py-0.5 rounded-full ${t.accent} text-xs`}>{badge}</span>
      )}
    </button>
  );
}

export function DashboardSidebar() {
  const theme = useDashboardTheme();
  const t = dashboardThemes[theme];

  return (
    <div className="w-60 bg-black/40 border-r border-white/5 flex flex-col p-6">
      {/* Logo */}
      <div className="flex items-center gap-3 mb-10">
        <div className="text-xl font-bold text-white tracking-tight">Labs.</div>
        <div className={`w-2 h-2 rounded-full bg-${t.primary} animate-pulse`} />
      </div>

      {/* Navigation */}
      <nav className="space-y-1 flex-1">
        <NavItem icon={LayoutDashboard} label="Dashboard" />
        <NavItem icon={BookOpen} label="Courses" active />
        <NavItem icon={FileText} label="Content" />
        <NavItem icon={ImageIcon} label="Media" />
        <NavItem icon={CheckSquare} label="My Tasks" badge="3" />

        <div className="my-6 border-t border-white/10" />

        <NavItem icon={Settings} label="Settings" />
        <NavItem icon={LogOut} label="Log Out" />
      </nav>

      {/* User Profile */}
      <div className="mt-auto pt-6 border-t border-white/10">
        <div className="flex items-center gap-3">
          <div
            className={`w-10 h-10 rounded-full bg-gradient-to-br from-${t.primary} to-zinc-800 flex items-center justify-center`}
          >
            <User className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="text-sm font-medium text-white">Neuer Nutzer</div>
            <div className="text-xs text-white/40">Administrator</div>
          </div>
        </div>
      </div>
    </div>
  );
}
