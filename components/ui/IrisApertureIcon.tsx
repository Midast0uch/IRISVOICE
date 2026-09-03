"use client";

import { motion } from "framer-motion";

interface IrisApertureIconProps {
  isActive: boolean;
  glowColor: string;
  fontColor: string;
  size?: number;
}

/**
 * Iris Aperture Icon Component
 * 
 * A crystalline aperture icon that morphs between diamond (✦) and aperture (✧) states.
 * Used for spotlight maximize/restore buttons in wing headers.
 * 
 * Rest State (✦): Four triangular points forming diamond shape at center
 * Active State (✧): Points expand outward 4px along diagonals, leaving square center
 * 
 * Animation: 400ms spring physics (stiffness 280, damping 25)
 */
export function IrisApertureIcon({
  isActive,
  glowColor,
  fontColor,
  size = 14
}: IrisApertureIconProps) {
  // Point animation variants
  const pointVariants = {
    rest: { x: 0, y: 0 },
    active: (direction: string) => {
      switch (direction) {
        case 'top': return { x: 0, y: -4 };
        case 'right': return { x: 4, y: 0 };
        case 'bottom': return { x: 0, y: 4 };
        case 'left': return { x: -4, y: 0 };
        default: return { x: 0, y: 0 };
      }
    }
  };

  const transition = {
    type: "spring" as const,
    stiffness: 280,
    damping: 25,
    mass: 0.8
  };

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      fill="none"
      style={{ overflow: 'visible' }}
    >
      {/* Top point - facing down */}
      <motion.polygon
        points="7,2 8.5,7 5.5,7"
        fill={isActive ? glowColor : 'none'}
        stroke={isActive ? 'none' : fontColor}
        strokeWidth={1}
        strokeLinejoin="miter"
        variants={pointVariants}
        initial="rest"
        animate={isActive ? "active" : "rest"}
        custom="top"
        transition={transition}
      />
      {/* Right point - facing left */}
      <motion.polygon
        points="12,7 7,8.5 7,5.5"
        fill={isActive ? glowColor : 'none'}
        stroke={isActive ? 'none' : fontColor}
        strokeWidth={1}
        strokeLinejoin="miter"
        variants={pointVariants}
        initial="rest"
        animate={isActive ? "active" : "rest"}
        custom="right"
        transition={transition}
      />
      {/* Bottom point - facing up */}
      <motion.polygon
        points="7,12 5.5,7 8.5,7"
        fill={isActive ? glowColor : 'none'}
        stroke={isActive ? 'none' : fontColor}
        strokeWidth={1}
        strokeLinejoin="miter"
        variants={pointVariants}
        initial="rest"
        animate={isActive ? "active" : "rest"}
        custom="bottom"
        transition={transition}
      />
      {/* Left point - facing right */}
      <motion.polygon
        points="2,7 7,5.5 7,8.5"
        fill={isActive ? glowColor : 'none'}
        stroke={isActive ? 'none' : fontColor}
        strokeWidth={1}
        strokeLinejoin="miter"
        variants={pointVariants}
        initial="rest"
        animate={isActive ? "active" : "rest"}
        custom="left"
        transition={transition}
      />
    </svg>
  );
}
