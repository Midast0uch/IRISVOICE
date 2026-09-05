import type { TaskCard } from "@/hooks/useTaskProgress"

export const CHATVIEW_1152_TURN_ID = "b1e1c0e6-4dd"
export const CHATVIEW_1152_CONVERSATION_ID = "conv-90"

const markdownBody = `# Deterministic replay\n\nThe fixture represents the 11:52 websearch turn. It deliberately keeps the rich document body separate from the assistant's short narration so the renderer must preserve both in one response.\n\n## Findings\n\n- The document render carries the visual artifact and its stable document identity.\n- The chat message carries the same turn identity and remains the readable answer anchor.\n- The task card joins after that message rather than falling into the orphan pile.\n\n## Sources\n\nThe captured shape is deterministic and contains no network-dependent values.\n\nThe replay is fixed, so each failure points to rendering logic and never to changing source data now.`

export const CHATVIEW_1152_FIXTURE = {
  conversationId: CHATVIEW_1152_CONVERSATION_ID,
  turnId: CHATVIEW_1152_TURN_ID,
  userMessage: {
    id: "user-1152",
    text: "Search the web and summarize the result.",
    sender: "user" as const,
    timestamp: new Date("2026-09-04T15:52:00.000Z"),
  },
  assistantMessage: {
    id: CHATVIEW_1152_TURN_ID,
    text: "I found the relevant material and attached the detailed result beside this answer.",
    sender: "assistant" as const,
    timestamp: new Date("2026-09-04T15:52:31.000Z"),
  },
  documentRender: {
    type: "document:render" as const,
    conversation_id: CHATVIEW_1152_CONVERSATION_ID,
    turn_id: CHATVIEW_1152_TURN_ID,
    document_id: "doc-1152-websearch",
    format: "markdown",
    content: markdownBody,
    alternatives: ["table", "html"],
    trust: "untrusted",
  },
  chatMessage: {
    type: "chat_message" as const,
    conversation_id: CHATVIEW_1152_CONVERSATION_ID,
    turn_id: CHATVIEW_1152_TURN_ID,
    text: "I found the relevant material and attached the detailed result beside this answer.",
    sender: "assistant" as const,
    spoken: "I found the relevant material and attached the detailed result beside this answer.",
  },
  taskCard: {
    cardId: "card-1152-websearch",
    createdAt: new Date("2026-09-04T15:52:08.000Z").getTime(),
    conversationId: CHATVIEW_1152_CONVERSATION_ID,
    isWorking: false,
    currentStep: 1,
    totalSteps: 1,
    steps: [
      {
        id: "search-1",
        description: "Search and synthesize sources",
        status: "done" as const,
        toolName: "crawler_query",
      },
    ],
    responseTurnId: CHATVIEW_1152_TURN_ID,
    turnId: CHATVIEW_1152_TURN_ID,
    planTitle: "Web research",
  } satisfies TaskCard,
} as const

export const CHATVIEW_1152_MARKDOWN_LENGTH = markdownBody.length
