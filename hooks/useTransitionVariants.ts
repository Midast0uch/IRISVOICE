'use client'

import { useTransition } from '@/contexts/TransitionContext'
import { getVariantsForTransition, getStaggerDelay } from '@/lib/transitions'
import type { Variants } from 'framer-motion'

export interface TransitionVariants {
  variants: Variants
  staggerDelay: number
  transitionName: string
}

export function useTransitionVariants(): TransitionVariants {
  const { currentTransition } = useTransition()
  
  const variants = getVariantsForTransition(currentTransition)
  const staggerDelay = getStaggerDelay(currentTransition)
  
  // Convert transition type to display name
  const transitionName = currentTransition
    .split('-')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
  
  console.log('[useTransitionVariants] Current:', currentTransition, 'Stagger:', staggerDelay)
  
  return {
    variants,
    staggerDelay,
    transitionName
  }
}
