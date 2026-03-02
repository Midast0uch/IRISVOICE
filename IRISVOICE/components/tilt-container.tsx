'use client';

import { ReactNode } from 'react';

interface PerspectiveContainerProps {
  children: ReactNode;
  perspective?: number;
  className?: string;
}

/**
 * PerspectiveContainer - Provides 3D perspective context for child elements
 * 
 * This container establishes the perspective origin for 3D transforms without
 * interfering with motion animations. Children can use CSS transforms for tilt
 * while Framer Motion handles position/opacity animations independently.
 * 
 * Usage:
 * <PerspectiveContainer perspective={1200}>
 *   <motion.div
 *     initial={{ x: -100, opacity: 0 }}
 *     animate={{ x: 0, opacity: 1 }}
 *     style={{ transform: 'rotateY(8deg)' }}
 *   >
 *     Content
 *   </motion.div>
 * </PerspectiveContainer>
 */
export function PerspectiveContainer({ 
  children, 
  perspective = 1200,
  className = '' 
}: PerspectiveContainerProps) {
  return (
    <div
      className={`relative w-full h-full ${className}`}
      style={{
        perspective: `${perspective}px`,
        perspectiveOrigin: 'center center',
      }}
    >
      {children}
    </div>
  );
}

interface WingContainerProps {
  children: ReactNode;
  side: 'left' | 'right';
  className?: string;
}

/**
 * WingContainer - Pre-configured container for ChatWing and DashboardWing
 * 
 * Applies the correct 3D tilt based on side (left/right) while maintaining
 * separation between CSS transforms (tilt) and motion animations (position).
 */
export function WingContainer({ children, side, className = '' }: WingContainerProps) {
  const tiltDeg = side === 'left' ? 8 : -8;
  const origin = side === 'left' ? 'left center' : 'right center';
  
  return (
    <div
      className={`h-full w-full ${className}`}
      style={{
        transform: `rotateY(${tiltDeg}deg) rotateX(2deg)`,
        transformOrigin: origin,
        transformStyle: 'preserve-3d',
      }}
    >
      {children}
    </div>
  );
}
