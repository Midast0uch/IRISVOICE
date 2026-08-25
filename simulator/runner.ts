/**
 * Vision Stage Simulator — runner (specs/vision-browser-stage REQ-12, T13).
 *
 * Executes a scenario's timed script by dispatching each step as a window
 * CustomEvent. One timeout chain per run; cancel() clears everything; the
 * runner owns NO state beyond the active timers (OPT GATE: nothing runs
 * between scenarios).
 */

import type { Scenario } from "./scenarios"

export interface RunningScenario {
  cancel: () => void
  /** Resolves when every step has fired (or the run was cancelled). */
  done: Promise<boolean>
}

export function runScenario(scenario: Scenario): RunningScenario {
  const timers: ReturnType<typeof setTimeout>[] = []
  let cancelled = false

  const done = new Promise<boolean>((resolve) => {
    if (scenario.steps.length === 0) {
      resolve(true)
      return
    }
    for (const step of scenario.steps) {
      timers.push(
        setTimeout(() => {
          if (cancelled) return
          try {
            window.dispatchEvent(new CustomEvent(step.ev, { detail: { ...step.detail } }))
          } catch {
            // A failing dispatch must never kill the remaining steps.
          }
        }, step.atMs),
      )
    }
    const last = scenario.steps[scenario.steps.length - 1]
    timers.push(setTimeout(() => resolve(!cancelled), last.atMs + 50))
  })

  return {
    done,
    cancel: () => {
      cancelled = true
      for (const t of timers) clearTimeout(t)
    },
  }
}

/** Reset helper: end any simulated run cleanly so scenarios are repeatable. */
export function resetToIdle(): void {
  window.dispatchEvent(
    new CustomEvent("iris:crawler_complete", {
      detail: { summary: "simulator reset", page_count: 0 },
    }),
  )
}
