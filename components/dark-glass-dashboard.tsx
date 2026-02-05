'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { DashboardThemeProvider, DashboardTheme } from '@/contexts/DashboardThemeContext';
import { TiltContainer } from './tilt-container';
import { DashboardSidebar } from './dashboard-sidebar';
import { DashboardHeader } from './dashboard-header';
import { DashboardContent } from './dashboard-content';

interface DarkGlassDashboardProps {
  theme?: DashboardTheme;
  isOpen: boolean;
  onClose: () => void;
}

export function DarkGlassDashboard({ theme = 'nebula', isOpen, onClose }: DarkGlassDashboardProps) {
  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3 }}
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/80 backdrop-blur-sm"
          onClick={onClose}
        >
          <DashboardThemeProvider theme={theme}>
            <TiltContainer>
              <div
                className="w-[1000px] h-[700px] rounded-3xl overflow-hidden
                           bg-zinc-950/80 backdrop-blur-2xl
                           border border-white/10
                           shadow-[0_50px_100px_-20px_rgba(0,0,0,0.8)]
                           flex"
                onClick={(e) => e.stopPropagation()}
              >
                {/* Sidebar */}
                <DashboardSidebar />

                {/* Main Content */}
                <div className="flex-1 flex flex-col bg-black/20">
                  <DashboardHeader />
                  <DashboardContent />
                </div>
              </div>
            </TiltContainer>
          </DashboardThemeProvider>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
