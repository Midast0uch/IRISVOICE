"use client"

import React from "react"
import { sortRows, deriveProgress } from "@/lib/cards/rowOrder"
import TaskListCard from "@/components/chat/TaskListCard"
import {
  renderBlueprintCellMatrixCLI,
  type TaskCardProps,
  type TaskStepItem,
} from "@/lib/cli/CLITaskProgressRenderer"
import type { TaskCard } from "@/hooks/useTaskProgress"

// ── cli-workspace-unification T4 (REQ-3): TaskCard → Blueprint Matrix ──────
// The GUI card (TaskListCard) and the ASCII renderer must describe the SAME
// task from the SAME store (useTaskProgress cards); only ONE renders per mode
// (pin_d222bf18dc6b). This conversion never re-maps verbs locally — the
// backend tool name flows straight into resolveVerb() (T8a contract).

function taskStepStatusToMatrix(status: TaskCard["steps"][number]["status"]): TaskStepItem["status"] {
  switch (status) {
    case "working": return "running"
    case "done": return "done"
    case "fail":
    case "error": return "failed"
    case "vetoed": return "rerouted"
    default: return "pending" // pending / skipped / unknown
  }
}

function taskCardToMatrixProps(card: TaskCard): TaskCardProps {
  return {
    objective: card.planTitle || card.currentAction || "Task",
    // GROUND TRUTH REQ-20 AC2: render in the AUTHORITATIVE order, derived from
    // the shared key — not inherited from whatever array position the GUI card
    // happened to hand over.
    steps: sortRows(card.steps).map((s): TaskStepItem => ({
      id: s.id,
      // REQ-20 AC1: carry the key through. Dropping it here is what left the
      // CLI unable to even detect a bad order.
      seq: s.seq,
      verb: s.toolName || "exec",
      target: s.activeDetail
        ? `${s.description} — ${s.activeDetail}${s.activeProgress ? ` (${s.activeProgress})` : ""}`
        : s.description,
      status: taskStepStatusToMatrix(s.status),
      summary: s.resultPreview,
      // branchLabel stays free-form backend data ("Diving Deeper" etc.) —
      // never the literal "Sub-Loop" (task-card-v2 CT-9).
      branchLabel: undefined,
    })),
    // REQ-20 AC3: the progress pair, from the SAME derivation the GUI counter
    // and the XurOrb ring read.
    ...deriveProgress(card.steps, card.totalSteps),
    isThinking: card.isWorking && !card.currentAction,
    currentThought: card.currentAction,
    isCrystallized: card.learningSignal === "crystallized" || card.terminalState === "done",
    memoryEvents: (card.memoryEvents || []).map((m) => ({
      direction:
        String(m.kind).includes("cryst")
          ? "crystallize"
          : String(m.kind).includes("store") || String(m.kind).includes("compress")
            ? "store"
            : "retrieve",
      engine: "episodic" as const,
      detail: typeof m.data?.detail === "string" ? m.data.detail : String(m.kind || "memory activity"),
      timestamp: m.at,
    })),
  }
}

export interface TaskCardEntryProps {
  card: TaskCard
  isDeveloper: boolean
  glowColor: string
  matrixElapsedSec: number
}

export function TaskCardEntry({
  card,
  isDeveloper,
  glowColor,
  matrixElapsedSec,
}: TaskCardEntryProps) {
    return isDeveloper ? (
      <div key={`card-${card.cardId}`} className="py-1">
        <pre
          className="font-mono text-[9px] leading-[1.35] overflow-x-auto whitespace-pre"
          style={{ color: 'rgba(255,255,255,0.85)' }}
        >
          {renderBlueprintCellMatrixCLI(taskCardToMatrixProps(card), false)
            .split("\n")
            .map((ln, i) =>
              ln.includes("TASK :") ? (
                <span key={i} style={{ color: glowColor }}>{ln}{"\n"}</span>
              ) : (
                <span key={i}>{ln}{"\n"}</span>
              )
            )}
        </pre>
        {/* REQ-3 AC2: elapsed running timer while live */}
        {card.isWorking && (
          <div className="font-mono text-[9px] mt-0.5" style={{ color: glowColor }}>
            ⏱ {String(Math.floor(matrixElapsedSec / 60)).padStart(2, "0")}:
            {String(matrixElapsedSec % 60).padStart(2, "0")}
          </div>
        )}
      </div>
    ) : (
      <TaskListCard
        key={card.cardId}
        cardId={card.cardId}
        steps={card.steps}
        turnId={card.turnId}
        mode={card.mode}
        planTitle={card.planTitle}
        learningSignal={card.learningSignal}
        memoryEvents={card.memoryEvents}
        currentAction={card.currentAction}
        /* Session 245 (pin_07b780e7ce21): structured crawl
           phase rotates the working step's verb.
         * Session 246: the THK stream comes from the card's
           own bounded action history (real progress frames,
           REQ-10 AC4). NOTE: the previous expression read
           `entry.message?.thinking` here, but `entry` is
           narrowed to the card kind in this branch — a
           latent TS error from session 245's parse-check-
           only pass. Streamed reasoning stays visible on
           the assistant message itself. */
        phase={card.phase}
        durationSec={card.durationSec}
        cardActive={card.isWorking}
        // T21 (REQ-22, wave 4): goal-directed enrichment —
        // the card's reduced goal/snippet/schema/verification
        // aggregate fields. All optional; the card renders
        // nothing for absent payloads.
        goalSnippet={card.goalSnippet}
        extractedSchema={card.extractedSchema}
        batchMetrics={card.batchMetrics}
        temporalDelta={card.temporalDelta}
        verifiedFields={card.verifiedFields}
        thoughtStream={card.isWorking ? (card.actionStream ?? undefined) : undefined}
      />
    )
}
