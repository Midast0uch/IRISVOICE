"use client"

import React, { useEffect, useState, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Trash2, ToggleLeft, ToggleRight, Sparkles, AlertCircle } from "lucide-react"
import { useNavigation } from "@/contexts/NavigationContext"

interface Skill {
  key: string
  name: string
  description: string
  enabled: boolean
}

interface LearnedSkillsPanelProps {
  glowColor: string
}

export const LearnedSkillsPanel: React.FC<LearnedSkillsPanelProps> = ({ glowColor }) => {
  const { sendMessage } = useNavigation()
  const [skills, setSkills] = useState<Skill[]>([])
  const [loading, setLoading] = useState(true)

  const fetchSkills = useCallback(() => {
    sendMessage("get_skills", {})
  }, [sendMessage])

  useEffect(() => {
    fetchSkills()

    const handleSkillsList = (event: CustomEvent) => {
      const payload = event.detail?.payload || {}
      setSkills(payload.skills || [])
      setLoading(false)
    }

    const handleSkillToggled = (event: CustomEvent) => {
      const { key, enabled } = event.detail?.payload || {}
      setSkills(prev => prev.map(s => s.key === key ? { ...s, enabled } : s))
    }

    const handleSkillDeleted = (event: CustomEvent) => {
      const { key } = event.detail?.payload || {}
      setSkills(prev => prev.filter(s => s.key !== key))
    }

    const handleSkillCreated = (event: CustomEvent) => {
      const skill = event.detail?.payload
      if (skill) {
        setSkills(prev => [...prev, skill].sort((a, b) => a.name.localeCompare(b.name)))
      }
    }

    const handleSkillsReloaded = () => {
      // Agent created/modified skills — re-fetch the full list
      fetchSkills()
    }

    window.addEventListener("iris:skills_list", handleSkillsList as EventListener)
    window.addEventListener("iris:skill_toggled", handleSkillToggled as EventListener)
    window.addEventListener("iris:skill_deleted", handleSkillDeleted as EventListener)
    window.addEventListener("iris:skill_created", handleSkillCreated as EventListener)
    window.addEventListener("iris:skills_reloaded", handleSkillsReloaded)

    return () => {
      window.removeEventListener("iris:skills_list", handleSkillsList as EventListener)
      window.removeEventListener("iris:skill_toggled", handleSkillToggled as EventListener)
      window.removeEventListener("iris:skill_deleted", handleSkillDeleted as EventListener)
      window.removeEventListener("iris:skill_created", handleSkillCreated as EventListener)
      window.removeEventListener("iris:skills_reloaded", handleSkillsReloaded)
    }
  }, [fetchSkills])

  const toggleSkill = (key: string, enabled: boolean) => {
    sendMessage("toggle_skill", { key, enabled: !enabled })
  }

  const deleteSkill = (key: string) => {
    if (window.confirm(`Are you sure you want to delete the skill "${key}"?`)) {
      sendMessage("delete_skill", { key })
    }
  }

  if (loading) {
    return (
      <div className="py-8 flex flex-col items-center justify-center opacity-40">
        <Sparkles className="w-5 h-5 mb-2 animate-pulse" style={{ color: glowColor }} />
        <span className="text-[9px] uppercase tracking-widest font-bold">Scanning Skills...</span>
      </div>
    )
  }

  return (
    <div className="space-y-3 pb-4">
      <AnimatePresence mode="popLayout">
        {skills.length === 0 ? (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="py-10 text-center px-4"
          >
            <div className="w-8 h-8 rounded-full bg-white/5 mx-auto mb-3 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-white/20" />
            </div>
            <span className="text-[10px] text-white/40 uppercase tracking-wider block">No Learned Skills</span>
            <p className="text-[9px] text-white/20 mt-2 leading-relaxed">
              IRIS hasn't crystallized any new workflows yet. Try asking her to help you with complex tasks!
            </p>
          </motion.div>
        ) : (
          skills.map((skill) => (
            <motion.div
              key={skill.key}
              layout
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="group relative p-3 rounded-xl border transition-all duration-300"
              style={{
                backgroundColor: skill.enabled ? `${glowColor}08` : "rgba(0,0,0,0.2)",
                borderColor: skill.enabled ? `${glowColor}25` : "rgba(255,255,255,0.05)",
              }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 mb-1">
                    <span 
                      className="text-[10px] font-black uppercase tracking-wider truncate"
                      style={{ color: skill.enabled ? "#fff" : "rgba(255,255,255,0.3)" }}
                    >
                      {skill.name}
                    </span>
                    {!skill.enabled && (
                      <span className="text-[7px] px-1 py-0.5 rounded bg-white/5 text-white/30 font-bold uppercase">Disabled</span>
                    )}
                  </div>
                  <p 
                    className="text-[9px] leading-relaxed line-clamp-2"
                    style={{ color: skill.enabled ? "rgba(255,255,255,0.5)" : "rgba(255,255,255,0.2)" }}
                  >
                    {skill.description}
                  </p>
                </div>
                
                <div className="flex flex-col gap-2 items-center">
                  <button
                    onClick={() => toggleSkill(skill.key, skill.enabled)}
                    className="p-1 rounded-lg transition-colors"
                    title={skill.enabled ? "Disable Skill" : "Enable Skill"}
                  >
                    {skill.enabled ? (
                      <ToggleRight className="w-5 h-5" style={{ color: glowColor }} />
                    ) : (
                      <ToggleLeft className="w-5 h-5 text-white/20" />
                    )}
                  </button>
                  
                  <button
                    onClick={() => deleteSkill(skill.key)}
                    className="p-1.5 rounded-lg bg-red-500/10 text-red-500/40 hover:text-red-500 hover:bg-red-500/20 transition-all opacity-0 group-hover:opacity-100"
                    title="Delete Skill"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </motion.div>
          ))
        )}
      </AnimatePresence>
    </div>
  )
}
