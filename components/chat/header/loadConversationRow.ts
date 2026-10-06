import type { Conversation } from "@/components/chat-view"

/**
 * One conversation by id, in chat-view's Conversation shape, for a strand or
 * thread chosen from the header that chat-view has not loaded yet (made after the
 * mount-time list, or just now by "new strand"). Same row mapping as chat-view's
 * fetchConversations. Null when the call fails.
 */
export async function loadConversationRow(id: string): Promise<Conversation | null> {
  try {
    const res = await fetch(`/api/conversations/${encodeURIComponent(id)}`, { signal: AbortSignal.timeout(8000) })
    if (!res.ok) throw new Error(`GET /api/conversations/${id} returned ${res.status}`)
    const c = await res.json()
    const msgs: any[] = c.messages || []
    const last = msgs[msgs.length - 1]?.text?.substring(0, 60) || ""
    return {
      id: c.id ?? id,
      title: c.title || `Conversation ${id.slice(-4)}`,
      preview: last,
      messages: msgs.map((m) => ({
        id: m.id,
        text: m.text || "",
        sender: m.role === "user" ? "user" : "assistant",
        timestamp: new Date(m.timestamp || Date.now()),
        thinking: m.thinking,
        turn_id: m.turn_id,
      })),
      documents: [],
      timestamp: new Date(c.updated_at || c.created_at || Date.now()),
      isPinned: !!c.pinned,
      lastMessagePreview: last,
    }
  } catch (e) {
    console.warn("[ChatHeader] loadConversationRow failed:", id, e)
    return null
  }
}
