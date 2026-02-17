"use client"

import { motion, AnimatePresence } from "framer-motion"
import { useNavigation } from "@/contexts/NavigationContext"
import { MiniNodeStack } from "./mini-node-stack"
import { getMiniNodesForSubnode } from "@/data/mini-nodes"

export function Level4View() {
  const { state } = useNavigation()
  const { selectedSub, miniNodeStack } = state

  // Use miniNodeStack from context if available, otherwise fetch from data
  const nodesToRender = miniNodeStack.length > 0 
    ? miniNodeStack 
    : (selectedSub ? getMiniNodesForSubnode(selectedSub) : [])

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className="absolute inset-0 flex items-center justify-center"
    >
      <AnimatePresence mode="wait">
        {nodesToRender.length > 0 ? (
          <motion.div
            key="stack"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
          >
            <MiniNodeStack miniNodes={nodesToRender} />
          </motion.div>
        ) : (
          <motion.div
            key="empty"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="text-white/40 text-sm"
          >
            No settings available for this category
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
