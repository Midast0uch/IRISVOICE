'use client';

import { ChevronLeft, Bell, HelpCircle } from 'lucide-react';
import { useDashboardTheme, dashboardThemes } from '@/contexts/DashboardThemeContext';

export function DashboardHeader() {
  const theme = useDashboardTheme();
  const t = dashboardThemes[theme];

  return (
    <header className="h-16 border-b border-white/5 flex items-center justify-between px-8">
      <div className="flex items-center gap-4">
        <button className="flex items-center gap-2 text-white/60 hover:text-white transition-colors">
          <ChevronLeft className="w-4 h-4" />
          <span className="text-sm">Back to All Courses</span>
        </button>
      </div>

      <div className="flex items-center gap-4">
        <button className="p-2 rounded-lg hover:bg-white/5 transition-colors">
          <HelpCircle className="w-5 h-5 text-white/60" />
        </button>
        <button className="p-2 rounded-lg hover:bg-white/5 transition-colors relative">
          <Bell className="w-5 h-5 text-white/60" />
          <div className={`absolute top-1.5 right-1.5 w-2 h-2 bg-${t.primary} rounded-full`} />
        </button>
      </div>
    </header>
  );
}
