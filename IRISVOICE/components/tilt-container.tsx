'use client';

import { motion, useMotionValue, useSpring, useTransform } from 'framer-motion';
import { ReactNode, useCallback } from 'react';
import { useDashboardTheme, dashboardThemes } from '@/contexts/DashboardThemeContext';

interface TiltContainerProps {
  children: ReactNode;
  className?: string;
}

export function TiltContainer({ children, className = '' }: TiltContainerProps) {
  const theme = useDashboardTheme();
  const t = dashboardThemes[theme];

  const x = useMotionValue(0);
  const y = useMotionValue(0);

  const mouseX = useSpring(x, { stiffness: 150, damping: 20 });
  const mouseY = useSpring(y, { stiffness: 150, damping: 20 });

  const rotateX = useTransform(mouseY, [-0.5, 0.5], [12, 2]);
  const rotateY = useTransform(mouseX, [-0.5, 0.5], [-18, -6]);

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    x.set((e.clientX - centerX) / rect.width);
    y.set((e.clientY - centerY) / rect.height);
  }, [x, y]);

  const handleMouseLeave = useCallback(() => {
    x.set(0);
    y.set(0);
  }, [x, y]);

  return (
    <div
      className="relative flex items-center justify-center"
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      style={{ perspective: 2000 }}
    >
      {/* Ambient Glow */}
      <div
        className={`absolute inset-0 ${t.ambient} blur-[120px] rounded-full pointer-events-none`}
        style={{ transform: 'translateZ(-100px)' }}
      />

      <motion.div
        initial={{ opacity: 0, rotateX: 15, rotateY: -15, scale: 0.9 }}
        animate={{ opacity: 1, rotateX: 8, rotateY: -12, scale: 1 }}
        style={{
          rotateX,
          rotateY,
          transformStyle: 'preserve-3d',
        }}
        transition={{ duration: 1, ease: 'easeOut' }}
        whileHover={{ scale: 1.02 }}
        className={`relative ${className}`}
      >
        {children}
      </motion.div>
    </div>
  );
}
