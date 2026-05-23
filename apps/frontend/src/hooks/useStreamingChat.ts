import { useState, useRef, useCallback } from "react"

export interface Message {
  role: "user" | "assistant"
  content: string
}

interface StreamChunk {
  type: "stream_start" | "token" | "metadata" | "done" | "error" | "cancelled"
  content?: string
  error?: string
  metadata?: Record<string, unknown>
}

interface StreamingState {
  messages: Message[]
  isStreaming: boolean
  error: string | null
  currentRequestId: string | null
  tokenMetadata: Record<string, unknown> | null
}

interface SendMessageOptions {
  provider: string
  model: string
  userMessage: string
}

const BACKEND_URL = "http://localhost:8000"

export function useStreamingChat() {
  const [state, setState] = useState<StreamingState>({
    messages: [],
    isStreaming: false,
    error: null,
    currentRequestId: null,
    tokenMetadata: null,
  })

  const abortControllerRef = useRef<AbortController | null>(null)

  const sendMessage = useCallback(async ({ provider, model, userMessage }: SendMessageOptions) => {
    if (!userMessage.trim()) return

    const userMsg: Message = { role: "user", content: userMessage }

    // Optimistic UI: append user message + empty assistant placeholder
    setState(prev => ({
      ...prev,
      messages: [...prev.messages, userMsg, { role: "assistant", content: "" }],
      isStreaming: true,
      error: null,
      tokenMetadata: null,
    }))

    const abortController = new AbortController()
    abortControllerRef.current = abortController

    const conversationMessages = [...state.messages, userMsg].map(m => ({
      role: m.role,
      content: m.content,
    }))

    try {
      const response = await fetch(`${BACKEND_URL}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider,
          model,
          messages: conversationMessages,
        }),
        signal: abortController.signal,
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      let requestId: string | null = null

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // SSE events are delimited by double newlines
        const events = buffer.split("\n\n")
        buffer = events.pop() ?? "" // keep incomplete tail

        for (const event of events) {
          const dataLine = event.split("\n").find(l => l.startsWith("data: "))
          if (!dataLine) continue

          const jsonStr = dataLine.slice(6).trim()
          if (!jsonStr) continue

          let chunk: StreamChunk
          try {
            chunk = JSON.parse(jsonStr)
          } catch {
            continue
          }

          if (chunk.type === "stream_start" && chunk.metadata) {
            requestId = chunk.metadata.request_id as string
            setState(prev => ({ ...prev, currentRequestId: requestId }))
          } else if (chunk.type === "token" && chunk.content) {
            setState(prev => {
              const msgs = [...prev.messages]
              const last = msgs[msgs.length - 1]
              if (last?.role === "assistant") {
                msgs[msgs.length - 1] = { ...last, content: last.content + chunk.content }
              }
              return { ...prev, messages: msgs }
            })
          } else if (chunk.type === "metadata") {
            setState(prev => ({ ...prev, tokenMetadata: { ...prev.tokenMetadata, ...chunk.metadata } }))
          } else if (chunk.type === "done") {
            setState(prev => ({
              ...prev,
              isStreaming: false,
              currentRequestId: null,
            }))
          } else if (chunk.type === "error") {
            setState(prev => ({
              ...prev,
              isStreaming: false,
              error: chunk.error ?? "Unknown error",
              currentRequestId: null,
            }))
          } else if (chunk.type === "cancelled") {
            setState(prev => ({
              ...prev,
              isStreaming: false,
              currentRequestId: null,
              messages: prev.messages.map((m, i) =>
                i === prev.messages.length - 1 && m.role === "assistant"
                  ? { ...m, content: m.content + " [cancelled]" }
                  : m
              ),
            }))
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") {
        // Client aborted — server-side cancel was already requested via stopStreaming()
        setState(prev => ({ ...prev, isStreaming: false, currentRequestId: null }))
      } else {
        const message = err instanceof Error ? err.message : "Stream failed"
        setState(prev => ({
          ...prev,
          isStreaming: false,
          error: message,
          currentRequestId: null,
        }))
      }
    } finally {
      abortControllerRef.current = null
    }
  }, [state.messages])

  const stopStreaming = useCallback(async () => {
    const requestId = state.currentRequestId
    if (!requestId) return

    // Abort the fetch first (stops reading)
    abortControllerRef.current?.abort()

    // Tell the backend to cancel via Redis pub/sub
    try {
      await fetch(`${BACKEND_URL}/chat/cancel/${requestId}`, { method: "POST" })
    } catch {
      // Best-effort — fetch abort already stops the local stream
    }
  }, [state.currentRequestId])

  const clearMessages = useCallback(() => {
    setState(prev => ({ ...prev, messages: [], error: null, tokenMetadata: null }))
  }, [])

  return {
    messages: state.messages,
    isStreaming: state.isStreaming,
    error: state.error,
    tokenMetadata: state.tokenMetadata,
    sendMessage,
    stopStreaming,
    clearMessages,
  }
}
