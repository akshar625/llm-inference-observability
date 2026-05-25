import { useState, useRef, useCallback } from "react"

export type Message = { role: "user" | "assistant"; content: string }

type StreamChunk = {
  type: "stream_start" | "token" | "metadata" | "done" | "error" | "cancelled"
  content?: string | null
  error?: string | null
  metadata?: Record<string, unknown> | null
}

import { API_BASE } from "@/lib/api"

export function useStreamingChat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tokenMetadata, setTokenMetadata] = useState<Record<string, unknown> | null>(null)

  const requestIdRef = useRef<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const send = useCallback(async (userMessage: string, provider: string, model: string) => {
    const requestId = crypto.randomUUID()
    requestIdRef.current = requestId
    setError(null)
    setTokenMetadata(null)

    setMessages(prev => [
      ...prev,
      { role: "user", content: userMessage },
      { role: "assistant", content: "" },
    ])
    setStreaming(true)
    abortRef.current = new AbortController()

    try {
      const response = await fetch(`${API_BASE}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider,
          model,
          conversation_id: conversationId,
          content: userMessage,
          request_id: requestId,
        }),
        signal: abortRef.current.signal,
      })

      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split("\n\n")
        buffer = events.pop() ?? ""

        for (const event of events) {
          const line = event.trim()
          if (!line.startsWith("data: ")) continue
          let chunk: StreamChunk
          try {
            chunk = JSON.parse(line.slice(6))
          } catch {
            continue
          }

          if (chunk.type === "stream_start" && chunk.metadata?.conversation_id) {
            setConversationId(chunk.metadata.conversation_id as string)
          } else if (chunk.type === "token" && chunk.content) {
            setMessages(prev => {
              const updated = [...prev]
              updated[updated.length - 1] = {
                ...updated[updated.length - 1],
                content: updated[updated.length - 1].content + chunk.content,
              }
              return updated
            })
          } else if (chunk.type === "metadata" && chunk.metadata) {
            setTokenMetadata(prev => ({ ...prev, ...chunk.metadata }))
          } else if (chunk.type === "error") {
            setError(chunk.error ?? "Unknown error")
          } else if (chunk.type === "cancelled") {
            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              updated[updated.length - 1] = {
                ...last,
                content: last.content + "\n\n_[generation cancelled]_",
              }
              return updated
            })
          }
        }
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name !== "AbortError") {
        setError(e.message ?? "Stream failed")
      }
    } finally {
      setStreaming(false)
      requestIdRef.current = null
      abortRef.current = null
    }
  }, [conversationId])

  const cancel = useCallback(async () => {
    const requestId = requestIdRef.current
    if (!requestId) return
    try {
      await fetch(`${API_BASE}/chat/cancel/${requestId}`, { method: "POST" })
    } catch { /* best-effort */ }
    abortRef.current?.abort()
  }, [])

  const loadConversation = useCallback(async (id: string) => {
    try {
      const res = await fetch(`${API_BASE}/conversations/${id}/messages`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setMessages(data.messages.map((m: { role: string; content: string }) => ({
        role: m.role as "user" | "assistant",
        content: m.content,
      })))
      setConversationId(id)
      setError(null)
      setTokenMetadata(null)
    } catch (e: unknown) {
      setError(`Failed to load conversation: ${e instanceof Error ? e.message : String(e)}`)
    }
  }, [])

  const newConversation = useCallback(() => {
    setMessages([])
    setConversationId(null)
    setError(null)
    setTokenMetadata(null)
  }, [])

  return {
    messages,
    conversationId,
    streaming,
    error,
    tokenMetadata,
    send,
    cancel,
    loadConversation,
    newConversation,
  }
}
