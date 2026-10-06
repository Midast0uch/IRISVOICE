"use client"

/**
 * The chat wing's top edge: one hairline with the spotlight aperture set into it,
 * centred on the top border (same place and same handler as the old aperture
 * button). It tilts with the wing (same transform) and sits outside the panel's
 * clip so the aperture is whole. Same arrangement as the dashboard wing.
 */

import React from "react"
import { motion } from "framer-motion"
import { EdgeLight } from "@/components/chrome/EdgeLight"
import { useBrandPalette } from "@/hooks/useBrandPalette"
import { useConversationTurns } from "@/lib/turns/turnStore"

const RUN = "#f2c14e" // the run colour (concept --run)

export interface ChatEdgeProps {
  glowColor: string
  isFlat: boolean
  /** The wing's tilt transform (chat-view getSpotlightTransform). */
  transform: string
  isInChatSpotlight: boolean
  onSpotlightToggle: () => void
  activeConversationId: string | null
}

export function ChatEdge({ glowColor, isFlat, transform, isInChatSpotlight, onSpotlightToggle, activeConversationId }: ChatEdgeProps) {
  const palette = useBrandPalette()
  const working = useConversationTurns(activeConversationId).some((t) => t.status === "running")
  return (
    <motion.div
      className="absolute inset-0 pointer-events-none"
      animate={isFlat ? {} : { transform }}
      transition={isFlat ? { duration: 0 } : { type: "spring", stiffness: 280, damping: 25, mass: 0.8 }}
      style={{
        zIndex: 50,
        transformOrigin: "left center",
        transformStyle: isFlat ? "flat" : "preserve-3d",
        transform: isFlat ? "rotateY(0deg) rotateX(0deg)" : undefined,
      }}
    >
      <EdgeLight
        glowColor={glowColor}
        palette={palette}
        spotlit={isInChatSpotlight}
        working={working}
        workingColor={RUN}
        onAperture={onSpotlightToggle}
        apertureTitle={isInChatSpotlight ? "Restore balanced view" : "Maximize chat"}
        isActive={isInChatSpotlight}
      />
    </motion.div>
  )
}

export default ChatEdge
