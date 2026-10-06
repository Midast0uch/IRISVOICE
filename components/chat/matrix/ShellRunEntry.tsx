"use client"

/**
 * A developer-mode `>cmd` in the timeline (execution audit Phase 4: "a >cmd
 * command shows as an EXEC row"): the prompt line, then a one-node matrix whose
 * EXEC row opens to the command's output. Before Phase 4 shell output went to a
 * scrollback store nothing in the chat drew, so a command looked as if it did
 * nothing.
 */
import React, { useMemo } from "react"
import type { ShellRun } from "@/lib/cli/shellRuns"
import { MatrixFrame } from "./LiveMatrix"

export function ShellRunEntry({ run, glowColor, now }: { run: ShellRun; glowColor: string; now: number }) {
  const matrix = useMemo(
    () => ({
      objective: run.command,
      steps: [
        {
          id: run.id,
          verb: "exec",
          target: run.command,
          status: run.state === "running" ? ("running" as const) : run.state === "failed" ? ("failed" as const) : ("done" as const),
          summary:
            run.state === "failed"
              ? run.output.find((l) => /^(\[exit \d+\]|Terminal error:|\^C aborted)/.test(l)) ?? "failed"
              : run.output.length
                ? `${run.output.length} line${run.output.length === 1 ? "" : "s"}`
                : undefined,
        },
      ],
      currentStep: run.state === "running" ? 0 : 1,
      totalSteps: 1,
    }),
    [run],
  )
  const details = useMemo(
    () => (run.output.length ? { [run.id]: { history: run.output.slice(-12) } } : {}),
    [run],
  )
  const elapsed = ((run.state === "running" ? now : run.lastTs) - run.ts) / 1000
  return (
    <div className="py-1 flex flex-col gap-1 min-w-0" data-shell-run={run.id}>
      <pre className="font-mono text-[12.5px] whitespace-pre-wrap break-words" style={{ color: "rgba(255,255,255,0.9)", lineHeight: 1.55 }} data-prompt-line>
        <span style={{ color: glowColor, fontWeight: 700 }}>❯ </span>&gt;{run.command}
      </pre>
      <MatrixFrame
        matrix={matrix}
        details={details}
        glowColor={glowColor}
        working={run.state === "running"}
        elapsedSec={elapsed}
        liveAction={run.output[run.output.length - 1]}
        foldWhenDone={false}
      />
    </div>
  )
}

export default ShellRunEntry
