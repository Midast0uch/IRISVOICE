/**
 * Memory -> chat (MEMORY-UX-PLAN 4.6, lib/memory/api requestChatTurn / takeChatTurn).
 *
 * The memory's "back to the turn in chat" fires while the chat wing may be closed: the page opens the wing and the
 * chat view, mounted later, must still find the request. One request, taken once; a malformed one never lands.
 */
import { requestChatTurn, takeChatTurn } from "@/lib/memory/api"

describe("the memory's request for a chat turn", () => {
  afterEach(() => { takeChatTurn() })

  it("waits for a chat view that mounts later, and is taken once", () => {
    const heard = jest.fn()
    window.addEventListener("iris:chat_request", heard)
    requestChatTurn({ conversationId: "conv-1585", turnId: "e996b6b0-481" })
    window.removeEventListener("iris:chat_request", heard)
    expect(heard).toHaveBeenCalledTimes(1)                                   // a mounted chat view hears it at once
    expect(takeChatTurn()).toEqual({ conversationId: "conv-1585", turnId: "e996b6b0-481" })
    expect(takeChatTurn()).toBeNull()                                         // never twice
  })

  it("opens a strand at its end when no turn is named, and ignores a request without a conversation", () => {
    requestChatTurn({ conversationId: "conv-1", turnId: "" })
    expect(takeChatTurn()).toEqual({ conversationId: "conv-1", turnId: undefined })
    requestChatTurn({ turnId: "t" })
    requestChatTurn(null)
    expect(takeChatTurn()).toBeNull()
  })
})
