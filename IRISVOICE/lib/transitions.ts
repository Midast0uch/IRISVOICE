import type { Variants, Transition, BezierDefinition } from 'framer-motion'
import type { TransitionType } from '@/contexts/TransitionContext'

// === EASING FUNCTIONS ===
const easings: Record<string, BezierDefinition> = {
  pop: [0.34, 1.56, 0.64, 1],
  smooth: [0.4, 0, 0.2, 1],
  mechanical: [1, 0, 0, 1],
  gentle: [0.25, 0.46, 0.45, 0.94],
}

// === PURE FADE ===
// Just fade in place at final position - no movement, no scale change
const pureFadeVariants: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { duration: 0.3, ease: 'linear' }
  },
  exit: {
    opacity: 0,
    transition: { duration: 0.3, ease: 'linear' }
  },
}

// === POP OUT ===
// Scale and rotate on own axis at final position - no movement from center
// Duration matches navigation timeout (1.5s) with very gradual scale animation
const popOutVariants: Variants = {
  hidden: { scale: 1, rotate: 0, opacity: 1 },
  visible: {
    scale: [1, 0.9, 0.7, 0.4, 0.2, 0.1, 0.3, 0.6, 0.9, 1.3, 1.1, 1.0],
    rotate: [0, 30, 60, 120, 240, 360, 480, 540, 600, 660, 700, 720],
    opacity: [1, 0.95, 0.85, 0.6, 0.4, 0.2, 0.5, 0.7, 0.9, 1, 1, 1],
    transition: { 
      duration: 1.5, 
      times: [0, 0.08, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.92, 1.0], 
      ease: easings.pop 
    }
  },
  exit: {
    scale: [1.0, 1.1, 1.3, 0.9, 0.6, 0.3, 0.15, 0.05, 0],
    rotate: [720, 700, 660, 600, 480, 360, 240, 120, 0],
    opacity: [1, 1, 0.9, 0.7, 0.5, 0.3, 0.15, 0.05, 0],
    transition: { 
      duration: 1.5, 
      times: [0, 0.08, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0], 
      ease: easings.pop 
    }
  },
}

// === CLOCKWORK ===
// Dial-turning motion: nodes move in circular path
// Duration matches navigation timeout (1.5s) for smooth sync
const clockworkVariants: Variants = {
  hidden: { 
    scale: 0, 
    rotate: 0, 
    opacity: 1,
  },
  visible: {
    scale: [0, 0.2, 0.4, 0.6, 0.8, 0.95, 1.02, 1],
    opacity: [0.4, 0.6, 0.8, 0.9, 1, 1, 1, 1],
    transition: { 
      duration: 1.5, 
      times: [0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1], 
      ease: easings.mechanical 
    }
  },
  exit: {
    scale: [1, 1.02, 0.95, 0.8, 0.6, 0.4, 0.2, 0],
    opacity: [1, 1, 1, 0.9, 0.8, 0.6, 0.4, 0],
    transition: { 
      duration: 1.5, 
      times: [0, 0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 1], 
      ease: easings.mechanical 
    }
  },
}

// === HOLOGRAPHIC ===
// Glitch interference effects
// Duration matches navigation timeout (1.5s) for smooth sync
const holographicVariants: Variants = {
  hidden: { 
    opacity: 0, 
    rotateX: 90,
    filter: 'hue-rotate(180deg) brightness(1)'
  },
  visible: {
    opacity: [0, 0.2, 0.5, 0.3, 0.7, 0.4, 0.8, 0.5, 0.9, 0.7, 1, 1],
    rotateX: [90, 70, 45, 30, 15, 10, 5, 3, 1, 0, 0, 0],
    rotateY: [0, 20, -15, 10, -8, 5, -3, 2, -1, 0, 0, 0],
    filter: [
      'hue-rotate(180deg) brightness(1)',
      'hue-rotate(150deg) brightness(1.2)',
      'hue-rotate(90deg) brightness(1.3)',
      'hue-rotate(120deg) brightness(1.1)',
      'hue-rotate(45deg) brightness(1.2)',
      'hue-rotate(90deg) brightness(1)',
      'hue-rotate(0deg) brightness(1.1)',
      'hue-rotate(45deg) brightness(1)',
      'hue-rotate(0deg) brightness(1.05)',
      'blur(1px)',
      'blur(0px) saturate(1.1)',
      'blur(0px) saturate(1)'
    ],
    transition: { 
      duration: 1.5, 
      times: [0, 0.08, 0.15, 0.23, 0.31, 0.4, 0.5, 0.6, 0.72, 0.85, 0.93, 1], 
      ease: 'linear' 
    }
  },
  exit: {
    opacity: [1, 0.7, 0.9, 0.5, 0.8, 0.4, 0.7, 0.3, 0.5, 0.2, 0],
    rotateX: [0, 0, 1, 3, 5, 10, 15, 30, 45, 70, 90],
    rotateY: [0, 0, 1, -2, 3, -5, 8, -10, 15, -20, 0],
    filter: [
      'blur(0px) saturate(1)',
      'blur(0px) saturate(1.1)',
      'blur(1px)',
      'hue-rotate(0deg) brightness(1.05)',
      'hue-rotate(45deg) brightness(1)',
      'hue-rotate(0deg) brightness(1.1)',
      'hue-rotate(90deg) brightness(1)',
      'hue-rotate(45deg) brightness(1.2)',
      'hue-rotate(120deg) brightness(1.1)',
      'hue-rotate(90deg) brightness(1.3)',
      'hue-rotate(180deg) brightness(1)'
    ],
    transition: { 
      duration: 1.5, 
      times: [0, 0.1, 0.18, 0.27, 0.37, 0.48, 0.58, 0.68, 0.78, 0.9, 1], 
      ease: 'linear' 
    }
  },
}

// === RADIAL SPIN (Default) ===
// Spiral emergence with rotation
const radialSpinVariants: Variants = {
  hidden: { opacity: 0, scale: 0.5 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: 1.5, ease: easings.smooth }
  },
  exit: {
    opacity: 0,
    scale: 0.5,
    transition: { duration: 1.5, ease: easings.smooth }
  },
}

// === TRANSITION MAP ===
const transitionMap: Record<TransitionType, Variants> = {
  'radial-spin': radialSpinVariants,
  'pure-fade': pureFadeVariants,
  'pop-out': popOutVariants,
  'clockwork': clockworkVariants,
  'holographic': holographicVariants,
}

export function getVariantsForTransition(type: TransitionType): Variants {
  return transitionMap[type] || radialSpinVariants
}

export function getStaggerDelay(type: TransitionType): number {
  switch (type) {
    case 'pure-fade': return 0.02
    case 'pop-out': return 0.08
    case 'clockwork': return 0.1
    case 'holographic': return 0.06
    default: return 0.1
  }
}

export function getTransitionName(type: TransitionType): string {
  const names: Record<TransitionType, string> = {
    'radial-spin': 'Radial Spin',
    'pure-fade': 'Pure Fade',
    'pop-out': 'Pop Out',
    'clockwork': 'Clockwork',
    'holographic': 'Holographic',
  }
  return names[type] || type
}

export type { Variants, Transition }
