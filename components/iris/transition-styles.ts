import type { Variants } from "framer-motion"
import type { TransitionStyle, ExitStyle } from "@/types/navigation"

type EasingArray = [number, number, number, number]

interface TransitionConfig {
  duration: number
  stagger: number
  easing: readonly number[]
  rotations: number
  exitStyle: ExitStyle
  speedMultiplier: number
}

interface NodePosition {
  angle: number
  radius: number
  index: number
}

function getPosition(angle: number, radius: number) {
  const rad = (angle * Math.PI) / 180
  return {
    x: Math.cos(rad) * radius,
    y: Math.sin(rad) * radius,
  }
}

export function getRadialSpinVariants(
  pos: NodePosition,
  config: TransitionConfig,
  isReverse: boolean = false
): Variants {
  const { x, y } = getPosition(pos.angle, pos.radius)
  const rotation = config.rotations * 360

  const entryDuration = config.duration / 1000
  const exitDuration = getExitDuration(config) / 1000
  const staggerDelay = (pos.index * config.stagger) / 1000

  return {
    collapsed: { 
      x: 0, 
      y: 0, 
      scale: 0.5, 
      opacity: 0, 
      rotate: 0 
    },
    expanded: {
      x,
      y,
      scale: 1,
      opacity: 1,
      rotate: rotation,
      transition: {
        duration: entryDuration,
        delay: staggerDelay,
        ease: config.easing as EasingArray,
      },
    },
    exit: {
      x: 0,
      y: 0,
      scale: 0.5,
      opacity: 0,
      rotate: isReverse ? -rotation : -360,
      transition: {
        duration: exitDuration,
        delay: staggerDelay,
        ease: config.easing as EasingArray,
      },
    },
  }
}

export function getClockworkVariants(
  pos: NodePosition,
  config: TransitionConfig,
  isReverse: boolean = false
): Variants {
  const { x, y } = getPosition(pos.angle, pos.radius)
  const steps = 12
  const stepAngle = 360 / steps

  const entryDuration = config.duration / 1000
  const exitDuration = getExitDuration(config) / 1000
  const staggerDelay = (pos.index * config.stagger) / 1000

  const scaleSteps = Array.from({ length: steps + 1 }, (_, i) => i / steps)
  const rotateSteps = Array.from({ length: steps + 1 }, (_, i) => i * stepAngle * 0.25)

  return {
    collapsed: { 
      x: 0, 
      y: 0, 
      scale: 0, 
      opacity: 0, 
      rotate: 0 
    },
    expanded: {
      x,
      y,
      scale: scaleSteps,
      opacity: 1,
      rotate: rotateSteps,
      transition: {
        duration: entryDuration,
        delay: staggerDelay,
        ease: "linear",
        times: scaleSteps,
      },
    },
    exit: {
      x: 0,
      y: 0,
      scale: [1, 0.83, 0.67, 0.5, 0.33, 0.17, 0],
      opacity: [1, 0.8, 0.6, 0.4, 0.2, 0.1, 0],
      rotate: isReverse ? [-90, -60, -45, -30, -15, -5, 0] : [0, 0, 0, 0, 0, 0, 0],
      transition: {
        duration: exitDuration,
        delay: staggerDelay,
        ease: "linear",
        times: [0, 0.17, 0.33, 0.5, 0.67, 0.83, 1],
      },
    },
  }
}

export function getSlotMachineVariants(
  pos: NodePosition,
  config: TransitionConfig,
  isReverse: boolean = false
): Variants {
  const { x, y } = getPosition(pos.angle, pos.radius)

  const entryDuration = config.duration / 1000
  const exitDuration = getExitDuration(config) / 1000
  const staggerDelay = (pos.index * config.stagger) / 1000

  return {
    collapsed: { 
      x: 0, 
      y: -50, 
      scale: 0.8, 
      opacity: 0, 
      filter: "blur(15px)" 
    },
    expanded: {
      x,
      y,
      scale: [0.8, 1.1, 0.95, 1],
      opacity: 1,
      filter: ["blur(15px)", "blur(8px)", "blur(2px)", "blur(0px)"],
      transition: {
        duration: entryDuration,
        delay: staggerDelay,
        ease: [0.68, -0.55, 0.265, 1.55] as EasingArray,
        times: [0, 0.4, 0.7, 1],
      },
    },
    exit: {
      x: 0,
      y: isReverse ? -50 : 50,
      scale: 0.8,
      opacity: 0,
      filter: "blur(15px)",
      transition: {
        duration: exitDuration,
        delay: staggerDelay,
        ease: "easeOut",
      },
    },
  }
}

export function getHolographicVariants(
  pos: NodePosition,
  config: TransitionConfig,
  isReverse: boolean = false
): Variants {
  const { x, y } = getPosition(pos.angle, pos.radius)

  const entryDuration = config.duration / 1000
  const exitDuration = getExitDuration(config) / 1000
  const staggerDelay = (pos.index * config.stagger) / 1000

  return {
    collapsed: { 
      x, 
      y, 
      scale: 0.9, 
      opacity: 0,
      filter: "brightness(2) contrast(0.5)",
    },
    expanded: {
      x,
      y,
      scale: 1,
      opacity: [0, 0.3, 0.6, 0.4, 0.8, 1],
      filter: [
        "brightness(2) contrast(0.5)",
        "brightness(1.5) contrast(0.8)",
        "brightness(1.2) contrast(1)",
        "brightness(1.3) contrast(0.9)",
        "brightness(1.1) contrast(1)",
        "brightness(1) contrast(1)",
      ],
      transition: {
        duration: entryDuration,
        delay: staggerDelay,
        ease: config.easing as EasingArray,
        times: [0, 0.2, 0.4, 0.5, 0.7, 1],
      },
    },
    exit: {
      x,
      y,
      scale: 0.9,
      opacity: [1, 0.5, 0.8, 0.3, 0],
      filter: "brightness(2) contrast(0.5)",
      transition: {
        duration: exitDuration,
        delay: staggerDelay,
        ease: "easeIn",
      },
    },
  }
}

export function getLiquidMorphVariants(
  pos: NodePosition,
  config: TransitionConfig,
  isReverse: boolean = false
): Variants {
  const { x, y } = getPosition(pos.angle, pos.radius)

  const entryDuration = config.duration / 1000
  const exitDuration = getExitDuration(config) / 1000
  const staggerDelay = (pos.index * config.stagger) / 1000

  return {
    collapsed: { 
      x: 0, 
      y: 0, 
      scale: 0, 
      opacity: 0,
      borderRadius: "50%",
    },
    expanded: {
      x,
      y,
      scale: [0, 0.3, 0.8, 1.1, 1],
      opacity: 1,
      borderRadius: ["50%", "40%", "30%", "20%", "24px"],
      transition: {
        duration: entryDuration,
        delay: staggerDelay,
        ease: [0.34, 1.56, 0.64, 1] as EasingArray,
        times: [0, 0.2, 0.5, 0.8, 1],
      },
    },
    exit: {
      x: 0,
      y: 0,
      scale: [1, 0.9, 0.5, 0],
      opacity: [1, 0.8, 0.4, 0],
      borderRadius: ["24px", "35%", "45%", "50%"],
      transition: {
        duration: exitDuration,
        delay: staggerDelay,
        ease: "easeInOut",
      },
    },
  }
}

export function getPureFadeVariants(
  pos: NodePosition,
  config: TransitionConfig,
  isReverse: boolean = false
): Variants {
  const { x, y } = getPosition(pos.angle, pos.radius)

  const entryDuration = config.duration / 1000
  const exitDuration = getExitDuration(config) / 1000

  return {
    collapsed: { 
      x, 
      y, 
      scale: 1, 
      opacity: 0 
    },
    expanded: {
      x,
      y,
      scale: 1,
      opacity: 1,
      transition: {
        duration: entryDuration,
        ease: "easeOut",
      },
    },
    exit: {
      x,
      y,
      scale: 1,
      opacity: 0,
      transition: {
        duration: exitDuration,
        ease: "easeIn",
      },
    },
  }
}

function getExitDuration(config: TransitionConfig): number {
  switch (config.exitStyle) {
    case 'fade-out':
      return 300 / config.speedMultiplier
    case 'fast-rewind':
      return config.duration / 2
    case 'symmetric':
    default:
      return config.duration * 0.6
  }
}

export function getVariantsForStyle(
  style: TransitionStyle,
  pos: NodePosition,
  config: TransitionConfig,
  isReverse: boolean = false
): Variants {
  switch (style) {
    case 'radial-spin':
      return getRadialSpinVariants(pos, config, isReverse)
    case 'clockwork':
      return getClockworkVariants(pos, config, isReverse)
    case 'slot-machine':
      return getSlotMachineVariants(pos, config, isReverse)
    case 'holographic':
      return getHolographicVariants(pos, config, isReverse)
    case 'liquid-morph':
      return getLiquidMorphVariants(pos, config, isReverse)
    case 'pure-fade':
      return getPureFadeVariants(pos, config, isReverse)
    default:
      return getRadialSpinVariants(pos, config, isReverse)
  }
}

export function getContentCounterRotation(
  style: TransitionStyle,
  rotations: number,
  duration: number,
  staggerIndex: number,
  staggerDelay: number,
  easing: readonly number[]
): Variants {
  const counterRotation = -rotations * 360

  if (style === 'radial-spin') {
    return {
      collapsed: { rotate: 0 },
      expanded: {
        rotate: counterRotation,
        transition: {
          duration: duration / 1000,
          delay: (staggerIndex * staggerDelay) / 1000,
          ease: easing as EasingArray,
        },
      },
      exit: {
        rotate: rotations * 360,
        transition: {
          duration: (duration * 0.6) / 1000,
          delay: (staggerIndex * staggerDelay) / 1000,
          ease: easing as EasingArray,
        },
      },
    }
  }

  return {
    collapsed: { rotate: 0 },
    expanded: { rotate: 0 },
    exit: { rotate: 0 },
  }
}

export interface BackButtonExitConfig {
  style: TransitionStyle
  exitStyle: ExitStyle
  duration: number
  stagger: number
  nodeCount: number
}

export function getMainToCollapsedVariants(
  pos: NodePosition,
  config: BackButtonExitConfig
): Variants {
  const { x, y } = getPosition(pos.angle, pos.radius)
  const reverseIndex = config.nodeCount - 1 - pos.index
  const staggerDelay = (reverseIndex * config.stagger) / 1000
  const duration = config.duration / 1000

  switch (config.exitStyle) {
    case 'fade-out':
      return {
        expanded: { x, y, scale: 1, opacity: 1 },
        exit: {
          x, y,
          scale: 1,
          opacity: 0,
          transition: { duration: 0.3, delay: staggerDelay * 0.5 },
        },
      }

    case 'fast-rewind':
      return {
        expanded: { x, y, scale: 1, opacity: 1, rotate: 0 },
        exit: {
          x: 0,
          y: 0,
          scale: 0.5,
          opacity: 0,
          rotate: config.style === 'radial-spin' ? -720 : 0,
          transition: { 
            duration: duration * 0.5, 
            delay: staggerDelay * 0.5,
            ease: [0.4, 0, 0.2, 1] as EasingArray,
          },
        },
      }

    case 'symmetric':
    default:
      return {
        expanded: { x, y, scale: 1, opacity: 1, rotate: 0 },
        exit: {
          x: 0,
          y: 0,
          scale: 0.5,
          opacity: 0,
          rotate: config.style === 'radial-spin' ? -360 : 0,
          transition: { 
            duration, 
            delay: staggerDelay,
            ease: [0.4, 0, 0.2, 1] as EasingArray,
          },
        },
      }
  }
}

export function getSubToMainVariants(
  pos: NodePosition,
  config: BackButtonExitConfig,
  parentRadius: number = 200
): Variants {
  const { x, y } = getPosition(pos.angle, pos.radius)
  const reverseIndex = config.nodeCount - 1 - pos.index
  const staggerDelay = (reverseIndex * config.stagger) / 1000
  const duration = config.duration / 1000

  switch (config.exitStyle) {
    case 'fade-out':
      return {
        expanded: { x, y, scale: 1, opacity: 1 },
        exit: {
          x, y,
          scale: 0.8,
          opacity: 0,
          transition: { duration: 0.3, delay: staggerDelay * 0.5 },
        },
      }

    case 'fast-rewind':
      return {
        expanded: { x, y, scale: 1, opacity: 1 },
        exit: {
          x: 0,
          y: 0,
          scale: 0,
          opacity: 0,
          rotate: config.style === 'radial-spin' ? -720 : 0,
          transition: { 
            duration: duration * 0.5, 
            delay: staggerDelay * 0.5,
            ease: [0.34, 1.56, 0.64, 1] as EasingArray,
          },
        },
      }

    case 'symmetric':
    default:
      if (config.style === 'liquid-morph') {
        return {
          expanded: { x, y, scale: 1, opacity: 1, borderRadius: '24px' },
          exit: {
            x: 0,
            y: 0,
            scale: [1, 0.8, 0],
            opacity: [1, 0.5, 0],
            borderRadius: ['24px', '40%', '50%'],
            transition: { 
              duration, 
              delay: staggerDelay,
              ease: 'easeInOut',
            },
          },
        }
      }
      return {
        expanded: { x, y, scale: 1, opacity: 1 },
        exit: {
          x: 0,
          y: 0,
          scale: 0,
          opacity: 0,
          rotate: config.style === 'radial-spin' ? -720 : 0,
          transition: { 
            duration, 
            delay: staggerDelay,
            ease: [0.4, 0, 0.2, 1] as EasingArray,
          },
        },
      }
  }
}

export function getMiniToSubVariants(
  config: BackButtonExitConfig
): Variants {
  const duration = config.duration / 1000

  switch (config.exitStyle) {
    case 'fade-out':
      return {
        expanded: { scale: 1, opacity: 1, z: 0 },
        exit: {
          scale: 0.9,
          opacity: 0,
          z: -100,
          transition: { duration: 0.3 },
        },
      }

    case 'fast-rewind':
      return {
        expanded: { scale: 1, opacity: 1, z: 0 },
        exit: {
          scale: 0,
          opacity: 0,
          z: -200,
          transition: { 
            duration: duration * 0.5,
            ease: [0.4, 0, 0.2, 1] as EasingArray,
          },
        },
      }

    case 'symmetric':
    default:
      return {
        expanded: { scale: 1, opacity: 1, z: 0 },
        exit: {
          scale: 0,
          opacity: 0,
          z: -200,
          transition: { 
            duration: duration * 0.6,
            ease: [0.4, 0, 0.2, 1] as EasingArray,
          },
        },
      }
  }
}

export function getBreadcrumbAnchorVariants(
  mainAngle: number,
  mainRadius: number,
  anchorRadius: number = 60
): Variants {
  const mainPos = getPosition(mainAngle, mainRadius)
  const anchorPos = getPosition(mainAngle, anchorRadius)

  return {
    main: {
      x: mainPos.x,
      y: mainPos.y,
      scale: 1,
      opacity: 1,
    },
    anchor: {
      x: anchorPos.x,
      y: anchorPos.y,
      scale: 0.75,
      opacity: 0.6,
      transition: {
        duration: 0.6,
        ease: [0.4, 0, 0.2, 1] as EasingArray,
      },
    },
    restore: {
      x: mainPos.x,
      y: mainPos.y,
      scale: 1,
      opacity: 1,
      transition: {
        duration: 0.5,
        ease: [0.4, 0, 0.2, 1] as EasingArray,
      },
    },
  }
}

export function getHiddenMainNodesVariants(
  angle: number,
  mainRadius: number,
  hiddenRadius: number = 280
): Variants {
  const mainPos = getPosition(angle, mainRadius)
  const hiddenPos = getPosition(angle, hiddenRadius)

  return {
    visible: {
      x: mainPos.x,
      y: mainPos.y,
      scale: 1,
      opacity: 1,
    },
    hidden: {
      x: hiddenPos.x,
      y: hiddenPos.y,
      scale: 0.8,
      opacity: 0,
      transition: {
        duration: 0.5,
        ease: [0.4, 0, 0.2, 1] as EasingArray,
      },
    },
    restore: {
      x: mainPos.x,
      y: mainPos.y,
      scale: 1,
      opacity: 1,
      transition: {
        duration: 0.6,
        ease: [0.34, 1.56, 0.64, 1] as EasingArray,
      },
    },
  }
}
