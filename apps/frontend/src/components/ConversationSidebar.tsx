import { useEffect, useState, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"

import { API_BASE } from "@/lib/api"

type Conversation = {
  id: string
  title: string | null
  status: string
  created_at: string
  updated_at: string
}

type Props = {
  currentConversationId: string | null
  onSelectConversation: (id: string) => void
  onNewConversation: () => void
  refreshKey: number
}

function formatTime(iso: string): string {
  const diffMin = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (diffMin < 1) return "just now"
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  return new Date(iso).toLocaleDateString()
}

export function ConversationSidebar({
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  refreshKey,
}: Props) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [loading, setLoading] = useState(false)

  const fetchConversations = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/conversations`)
      const data: Conversation[] = await res.json()
      setConversations(data)
    } catch (e) {
      console.error("Failed to fetch conversations:", e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchConversations()
  }, [fetchConversations, refreshKey])

  return (
    <aside className="w-64 border-r flex flex-col h-full shrink-0">
      <div className="p-4 border-b">
        {/* <span className="font-semibold text-base tracking-tight block mb-3">Lio</span> */}
        <Button onClick={onNewConversation} className="w-full" variant="outline" size="sm">
          + New Conversation
        </Button>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-2 space-y-0.5">
          {loading && conversations.length === 0 ? (
            <p className="text-xs text-muted-foreground px-2 py-3">Loading…</p>
          ) : conversations.length === 0 ? (
            <p className="text-xs text-muted-foreground px-2 py-3">No conversations yet</p>
          ) : (
            conversations.map(c => (
              <button
                key={c.id}
                onClick={() => onSelectConversation(c.id)}
                className={`w-full text-left px-3 py-2 rounded-md text-sm hover:bg-muted transition-colors ${
                  c.id === currentConversationId ? "bg-muted font-medium" : ""
                }`}
              >
                <div className="truncate">
                  {c.title ?? `Chat ${c.id.slice(0, 8)}`}
                </div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  {formatTime(c.updated_at)}
                </div>
              </button>
            ))
          )}
        </div>
      </ScrollArea>
    </aside>
  )
}
