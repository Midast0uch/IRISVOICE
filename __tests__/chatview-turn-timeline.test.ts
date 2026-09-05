import { buildChatTimeline } from "@/lib/chatview-turn-timeline"
import {
  CHATVIEW_1152_FIXTURE,
  CHATVIEW_1152_MARKDOWN_LENGTH,
  CHATVIEW_1152_TURN_ID,
} from "@/__tests__/fixtures/chatviewTurn1152"

describe("ChatView 11:52 deterministic turn fixture", () => {
  it("pins CT-1 document:render and CT-2 chat_message to one turn", () => {
    const { documentRender, chatMessage } = CHATVIEW_1152_FIXTURE

    expect(documentRender).toMatchObject({
      type: "document:render",
      turn_id: CHATVIEW_1152_TURN_ID,
      document_id: "doc-1152-websearch",
      format: "markdown",
      trust: "untrusted",
    })
    expect(documentRender.content.length).toBe(CHATVIEW_1152_MARKDOWN_LENGTH)
    expect(chatMessage).toMatchObject({
      type: "chat_message",
      turn_id: CHATVIEW_1152_TURN_ID,
      sender: "assistant",
    })
    expect(chatMessage.text).not.toBe(documentRender.content)
    expect(chatMessage.conversation_id).toBe(documentRender.conversation_id)
  })

  it("CT-3 joins the card immediately after its assistant anchor", () => {
    const fixture = CHATVIEW_1152_FIXTURE
    const timeline = buildChatTimeline(
      [fixture.userMessage, fixture.assistantMessage],
      [fixture.taskCard],
    )

    expect(timeline.map((entry) => entry.kind)).toEqual(["message", "message", "card"])
    expect(timeline[1]).toMatchObject({
      kind: "message",
      message: { id: CHATVIEW_1152_TURN_ID },
    })
    expect(timeline[2]).toMatchObject({
      kind: "card",
      card: { responseTurnId: CHATVIEW_1152_TURN_ID },
    })
  })

  it("never sends the matched card to the orphan fallback", () => {
    const fixture = CHATVIEW_1152_FIXTURE
    const timeline = buildChatTimeline([fixture.assistantMessage], [fixture.taskCard])
    const cardIndex = timeline.findIndex((entry) => entry.kind === "card")

    expect(cardIndex).toBe(1)
    expect(timeline[cardIndex].ts).toBe(fixture.assistantMessage.timestamp.getTime())
  })
})
