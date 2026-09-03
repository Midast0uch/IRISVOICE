import React from 'react';
import { useState } from 'react';

interface TabBarProps {
  activeTab: string;
  onTabClick: (tabId: string) => void;
}

export function TabBar({ activeTab, onTabClick }: TabBarProps) {
  const [active, setActive] = useState(activeTab);
  
  return (
    <div className="flex items-center justify-center">
      {['voice', 'agent', 'automate', 'system', 'customize', 'monitor'].map(tab => (
        <button key={tab} onClick={() => onTabClick(tab)} className={`text-[12px] font-medium tracking-wider text-white/70 ${active === tab ? 'bg-primary-500' : ''}`}>
          {({'voice':'VOICE','agent':'AGENT','automate':'AUTO','system':'SYS','customize':'CUSTOM','monitor':'MON'} as Record<string,string>)[tab]}
        </button>
      ))}
    </div>
  );
}