'use client';

import { useState, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Lock, Unlock, ChevronRight } from 'lucide-react';
import { useBrandColor } from '@/contexts/BrandColorContext';

interface MenuWindowSliderProps {
  onUnlock: () => void;
  isOpen: boolean;
  onClose: () => void;
}

export function MenuWindowSlider({ onUnlock, isOpen, onClose }: MenuWindowSliderProps) {
  const { getThemeConfig } = useBrandColor();
  const theme = getThemeConfig();
  const glowColor = theme.glow.color;
  
  const [isDragging, setIsDragging] = useState(false);
  const [sliderPosition, setSliderPosition] = useState(0);
  const [isUnlocked, setIsUnlocked] = useState(false);
  const sliderRef = useRef<HTMLDivElement>(null);
  const startXRef = useRef(0);
  const sliderWidth = 80;    // 2x bigger than tiny
  const handleWidth = 24;   // 2x bigger handle
  const unlockThreshold = sliderWidth - handleWidth - 4;

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (isOpen) return;
    e.preventDefault();
    setIsDragging(true);
    startXRef.current = e.clientX - sliderPosition;
  }, [isOpen, sliderPosition]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging) return;
    e.preventDefault();
    const newPosition = Math.max(0, Math.min(e.clientX - startXRef.current, unlockThreshold));
    setSliderPosition(newPosition);
    
    if (newPosition >= unlockThreshold && !isUnlocked) {
      setIsUnlocked(true);
      onUnlock();
    }
  }, [isDragging, unlockThreshold, isUnlocked, onUnlock]);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
    if (!isUnlocked) {
      // Spring back if not unlocked
      setSliderPosition(0);
    }
  }, [isUnlocked]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (isOpen) return;
    setIsDragging(true);
    startXRef.current = e.touches[0].clientX - sliderPosition;
  }, [isOpen, sliderPosition]);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (!isDragging) return;
    const newPosition = Math.max(0, Math.min(e.touches[0].clientX - startXRef.current, unlockThreshold));
    setSliderPosition(newPosition);
    
    if (newPosition >= unlockThreshold && !isUnlocked) {
      setIsUnlocked(true);
      onUnlock();
    }
  }, [isDragging, unlockThreshold, isUnlocked, onUnlock]);

  const handleTouchEnd = useCallback(() => {
    setIsDragging(false);
    if (!isUnlocked) {
      setSliderPosition(0);
    }
  }, [isUnlocked]);

  const handleClose = () => {
    setIsUnlocked(false);
    setSliderPosition(0);
    onClose();
  };

  return (
    <div className="flex flex-col items-center gap-1">
      <AnimatePresence mode="wait">
        {!isOpen ? (
          <motion.div
            key="slider"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            className="relative"
          >
            {/* Slider Track - Theme Tinted Liquid Metal Style - THIN & RECTANGULAR */}
            <div
              ref={sliderRef}
              className="relative h-4 rounded overflow-hidden cursor-pointer"
              style={{ 
                width: sliderWidth,
                background: `linear-gradient(90deg, 
                  ${glowColor.replace(')', ', 0.1)')} 0%, 
                  ${glowColor.replace(')', ', 0.15)')} 20%, 
                  ${glowColor.replace(')', ', 0.2)')} 40%, 
                  ${glowColor.replace(')', ', 0.15)')} 60%, 
                  ${glowColor.replace(')', ', 0.1)')} 80%,
                  rgba(0,0,0,0.1) 100%)`,
                boxShadow: `0 0 6px ${glowColor.replace(')', ', 0.2)')}, inset 0 1px 0.5px ${glowColor.replace(')', ', 0.1)')}`,
                border: `0.5px solid ${glowColor.replace(')', ', 0.25)')}`,
              }}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              onTouchMove={handleTouchMove}
              onTouchEnd={handleTouchEnd}
            >
              {/* Background text - Drag to Open inside the track */}
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-white/50 text-[7px] font-medium tracking-wider uppercase flex items-center gap-0.5">
                  <Lock className="w-2.5 h-2.5" />
                  Menu
                </span>
              </div>

              {/* Progress fill - Theme Tinted Liquid Metal */}
              <motion.div
                className="absolute left-0 top-0 h-full"
                style={{ 
                  width: sliderPosition + handleWidth,
                  background: `linear-gradient(90deg, 
                    ${glowColor.replace(')', ', 0.4)')} 0%, 
                    ${glowColor.replace(')', ', 0.6)')} 50%, 
                    ${glowColor.replace(')', ', 0.4)')} 100%)`,
                  boxShadow: `0 0 8px ${glowColor.replace(')', ', 0.4)')}`,
                }}
              />

              {/* Slider Handle - Theme Tinted - THINNER */}
              <motion.div
                className="absolute top-0.5 h-3 rounded shadow flex items-center justify-center cursor-grab active:cursor-grabbing"
                style={{
                  width: handleWidth,
                  x: sliderPosition,
                  touchAction: 'none',
                  background: `linear-gradient(135deg, ${glowColor.replace(')', ', 0.9)')}, #ffffff)`,
                  boxShadow: `0 0 8px ${glowColor.replace(')', ', 0.5)')}`,
                }}
                onMouseDown={handleMouseDown}
                onTouchStart={handleTouchStart}
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
              >
                <ChevronRight className="w-2.5 h-2.5" style={{ color: glowColor }} />
              </motion.div>
            </div>
          </motion.div>
        ) : (
          <motion.button
            key="close"
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.8 }}
            onClick={handleClose}
            className="px-4 py-2 rounded-lg backdrop-blur-md border text-sm font-medium flex items-center gap-2 transition-all duration-200"
            style={{
              background: `linear-gradient(135deg, ${glowColor.replace(')', ', 0.2)')}, ${glowColor.replace(')', ', 0.1)')})`,
              borderColor: `${glowColor.replace(')', ', 0.3)')}`,
              color: '#ffffff',
            }}
          >
            <Unlock className="w-4 h-4" />
            Close Menu
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}
