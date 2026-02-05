'use client';

import { useState } from 'react';
import { MenuWindowButton } from '@/components/menu-window-button';
import { DarkGlassDashboard } from '@/components/dark-glass-dashboard';

export default function MenuWindowPage() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="min-h-screen bg-black flex items-center justify-center">
      {/* Menu Window Button - positioned in corner, outside main UI */}
      <MenuWindowButton onClick={() => setIsOpen(!isOpen)} isOpen={isOpen} />

      {/* Test indicator to show this is isolated */}
      <div className="text-white/20 text-sm absolute bottom-4 left-4">
        Isolated Test Environment - Menu Window Component
      </div>

      {/* Dark Glass Dashboard Widget */}
      <DarkGlassDashboard
        theme="nebula"
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
      />
    </div>
  );
}
