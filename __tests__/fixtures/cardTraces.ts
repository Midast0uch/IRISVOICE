/**
 * CAPTURED CARD TRACES — verbatim wire frames, as DATA.
 *
 * specs/der-ground-truth/ REQ-19 (T27).
 *
 * PROVENANCE: transcribed MECHANICALLY (balanced-brace extraction of every
 * `dispatch({...})` literal, then evaluated) from
 * `__tests__/hooks/useTaskProgress.card-contract.test.tsx` — the session-247
 * suite that replays live conv-44 / conv-49 / conv-51 WebSocket captures.
 * 21 frames, 0 parse errors.
 *
 * WHY A COPY. That test is CONTRACT-LOCKED (specs/der-ground-truth/ design.md
 * CT-GT-6): additive-only, never weakened, never edited to accommodate a
 * malformed stream. So the frames are duplicated here as data rather than
 * refactored out of it. A later task may invert that (have the test import
 * these) — this file exists so the EMITTER can be judged without a renderer.
 *
 * DO NOT "fix" the payloads in this file. Their defects are the measurement.
 */
import type { CardFrame } from "@/lib/cards/emitterContract"

/** conv-49: the websearch trace — planner step + five crawl phase transitions. */
export const TRACE_WEBSEARCH: CardFrame[] = [
    {
      "type": "task:start",
      "task_id": "fb24d28d-f98",
      "card_id": "card_fb24d28d-f98",
      "card_relation": "new",
      "conversation_id": "conv-49",
      "steps": [
        {
          "id": "r1",
          "description": "Search web for latest breakthroughs",
          "status": "pending",
          "toolName": null
        }
      ],
      "total_steps": 1,
      "origin": "initial"
    },
    {
      "type": "tool:call",
      "card_id": "card_fb24d28d-f98",
      "conversation_id": "conv-49",
      "step_number": 1,
      "tool_name": "crawler_query"
    },
    {
      "type": "task:progress",
      "conversation_id": "conv-49",
      "description": "Searching for sources",
      "action": "Searching for sources",
      "phase": "searching",
      "phase_sequence": 1
    },
    {
      "type": "task:progress",
      "conversation_id": "conv-49",
      "description": "Reading Quantum journal paper",
      "action": "Reading Quantum journal paper (1/4)",
      "update_step": true,
      "detail": "Quantum journal",
      "detail_url": "https://quantum-journal.org/",
      "detail_progress": "1/4",
      "phase": "fetching",
      "phase_sequence": 2
    },
    {
      "type": "task:progress",
      "conversation_id": "conv-49",
      "description": "Reading Physics World",
      "action": "Reading Physics World (2/4)",
      "update_step": true,
      "detail": "Physics World",
      "detail_url": "https://physicsworld.com/",
      "detail_progress": "2/4",
      "phase": "fetching",
      "phase_sequence": 2
    },
    {
      "type": "task:progress",
      "conversation_id": "conv-49",
      "description": "Extracting content",
      "action": "Extracting content",
      "phase": "extracting",
      "phase_sequence": 3
    },
    {
      "type": "task:progress",
      "conversation_id": "conv-49",
      "description": "Citing sources",
      "action": "Citing sources",
      "phase": "citing",
      "phase_sequence": 5
    },
    {
      "type": "tool:result",
      "card_id": "card_fb24d28d-f98",
      "conversation_id": "conv-49",
      "step_number": 1
    },
    {
      "type": "task:progress",
      "card_id": "card_fb24d28d-f98",
      "conversation_id": "conv-49",
      "step_done": true,
      "step_id": "r1",
      "step_number": 1,
      "success": true
    },
    {
      "type": "task:progress",
      "conversation_id": "conv-49",
      "description": "Synthesizing answer",
      "action": "Synthesizing answer",
      "update_step": true,
      "phase": "synthesizing",
      "phase_sequence": 90
    },
    {
      "type": "task:done",
      "card_id": "card_fb24d28d-f98",
      "conversation_id": "conv-49",
      "outcome": "success",
      "steps_completed": 1,
      "total_steps": 1
    }
  ]

/** conv-49 + the C6 verify_failed graft that revises the plan mid-run. */
export const TRACE_WEBSEARCH_WITH_GRAFT: CardFrame[] = [
  ...TRACE_WEBSEARCH,
  {
      "type": "task:start",
      "task_id": "fb24d28d-f98",
      "card_id": "card_fb24d28d-f98",
      "card_relation": "continues",
      "conversation_id": "conv-49",
      "origin": "sub_loop_split",
      "steps": [
        {
          "id": "r1",
          "description": "Search web for latest breakthroughs",
          "status": "done",
          "toolName": "crawler_query",
          "stepNumber": 1
        },
        {
          "id": "r1_s1",
          "description": "child extract",
          "status": "working",
          "toolName": "crawler_query",
          "stepNumber": 1
        }
      ],
      "total_steps": 2
    },
]

/** conv-code: a DER implement task — two tool steps, no crawl phases. */
export const TRACE_CODE_TASK: CardFrame[] = [
    {
      "type": "task:start",
      "task_id": "t-code",
      "card_id": "card_code-1",
      "card_relation": "new",
      "conversation_id": "conv-code",
      "steps": [
        {
          "id": "c1",
          "description": "Run the test suite",
          "status": "pending",
          "toolName": null
        },
        {
          "id": "c2",
          "description": "Summarize results and commit fix",
          "status": "pending",
          "toolName": null
        }
      ],
      "total_steps": 2
    },
    {
      "type": "tool:call",
      "card_id": "card_code-1",
      "conversation_id": "conv-code",
      "step_number": 1,
      "tool_name": "run_command"
    },
    {
      "type": "tool:result",
      "card_id": "card_code-1",
      "conversation_id": "conv-code",
      "step_number": 1
    },
    {
      "type": "task:progress",
      "card_id": "card_code-1",
      "conversation_id": "conv-code",
      "step_done": true,
      "step_id": "c1",
      "success": true
    },
    {
      "type": "tool:call",
      "card_id": "card_code-1",
      "conversation_id": "conv-code",
      "step_number": 2,
      "tool_name": "write_file"
    },
    {
      "type": "tool:result",
      "card_id": "card_code-1",
      "conversation_id": "conv-code",
      "step_number": 2
    },
    {
      "type": "task:progress",
      "card_id": "card_code-1",
      "conversation_id": "conv-code",
      "step_done": true,
      "step_id": "c2",
      "success": true
    },
    {
      "type": "task:progress",
      "conversation_id": "conv-code",
      "description": "Synthesizing answer",
      "action": "Synthesizing answer",
      "update_step": true,
      "phase": "synthesizing",
      "phase_sequence": 90
    },
    {
      "type": "task:done",
      "card_id": "card_code-1",
      "conversation_id": "conv-code",
      "outcome": "success"
    }
  ]

export const ALL_TRACES: ReadonlyArray<{ name: string; frames: CardFrame[] }> = [
  { name: "conv-49 websearch", frames: TRACE_WEBSEARCH },
  { name: "conv-49 websearch + graft", frames: TRACE_WEBSEARCH_WITH_GRAFT },
  { name: "conv-code implement", frames: TRACE_CODE_TASK },
]
