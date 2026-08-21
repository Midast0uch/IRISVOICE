'use client'

import { motion } from 'framer-motion'

export interface CliTool {
  name: string
  display_name: string
  when_to_use: string
  available: boolean
  reason: string | null
}

/**
 * HelpPanel — in-app command reference (REQ-20 AC5/AC6/AC7).
 *
 * Reached two ways (both local, never sent to the agent):
 *   - typing `/help` in the composer
 *   - the persistent /help affordance beside the composer
 *
 * Surfaces the EXISTING backend CLI registry (fetched from /api/dev/cli-tools)
 * — never a second hardcoded copy. Prefixes are always shown; the tool list
 * renders whatever the endpoint returned (empty in personal mode is fine).
 */
export function HelpPanel({ tools, onClose }: { tools: CliTool[]; onClose: () => void }) {
  return (
    <div
      className="my-3 mx-3 rounded-xl border border-white/10 bg-[#0b0c1a]/95 backdrop-blur p-4 shadow-xl"
      style={{ boxShadow: '0 8px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.05)' }}
      role="region"
      aria-label="Command reference"
    >
      <motion.div
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full"
        style={{}}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold tracking-wide">Command reference</h2>
          <button
            onClick={onClose}
            className="text-white/40 hover:text-white/80 text-lg leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="space-y-3 text-[12px]">
          <div>
            <div className="font-mono text-[11px] text-cyan-300">&gt; &lt;command&gt;</div>
            <div className="text-white/60">SHELL — runs literally in the shell. No LLM involved.</div>
          </div>
          <div>
            <div className="font-mono text-[11px] text-cyan-300">/run &lt;request&gt;</div>
            <div className="text-white/60">DELEGATE — IRIS picks a CLI tool and drives it for you.</div>
          </div>
        </div>

        {tools.length > 0 && (
          <div className="mt-5">
            <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2">
              Available delegate tools
            </div>
            <div className="space-y-2">
              {tools.map((t) => (
                <div key={t.name} className="rounded-lg border border-white/10 p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{t.display_name}</span>
                    {t.available ? (
                      <span className="text-[10px] text-green-400 shrink-0">available</span>
                    ) : (
                      <span className="text-[10px] text-red-400 shrink-0">
                        {t.reason || 'unavailable'}
                      </span>
                    )}
                  </div>
                  <div className="text-white/55 mt-1">{t.when_to_use}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="mt-5 text-[11px] text-white/40">
          Type <span className="font-mono text-white/70">/help</span> any time to reopen this reference.
        </div>
      </motion.div>
    </div>
  )
}

export default HelpPanel
