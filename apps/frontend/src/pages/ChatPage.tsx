import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"
import { ConversationSidebar } from "@/components/ConversationSidebar"
import { useStreamingChat } from "@/hooks/useStreamingChat"
import { API_BASE } from "@/lib/api"

interface ProviderModel { id: string; name: string }
interface Provider { id: string; name: string; models: ProviderModel[] }
interface BackendConfig {
  providers: Provider[]
  defaults: { temperature: number; max_tokens: number }
}

export function ChatPage() {
  const [config, setConfig] = useState<BackendConfig | null>(null)
  const [selectedProvider, setSelectedProvider] = useState<string>("")
  const [selectedModel, setSelectedModel] = useState<string>("")
  const [input, setInput] = useState("")
  const [sidebarRefresh, setSidebarRefresh] = useState(0)
  const bottomRef = useRef<HTMLDivElement>(null)

  const {
    messages,
    conversationId,
    streaming,
    error,
    tokenMetadata,
    send,
    cancel,
    loadConversation,
    newConversation,
  } = useStreamingChat()

  useEffect(() => {
    fetch(`${API_BASE}/config`)
      .then(r => r.json())
      .then((data: BackendConfig) => {
        setConfig(data)
        if (data.providers.length > 0) {
          const first = data.providers[0]
          setSelectedProvider(first.id)
          setSelectedModel(first.models[0]?.id ?? "")
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!streaming && conversationId) {
      setSidebarRefresh(k => k + 1)
    }
  }, [streaming, conversationId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const availableModels = config?.providers.find(p => p.id === selectedProvider)?.models ?? []

  const handleProviderChange = (value: string) => {
    setSelectedProvider(value)
    const provider = config?.providers.find(p => p.id === value)
    setSelectedModel(provider?.models[0]?.id ?? "")
  }

  const handleSend = () => {
    if (!input.trim() || streaming || !selectedProvider || !selectedModel) return
    const msg = input
    setInput("")
    send(msg, selectedProvider, selectedModel)
  }

  const handleSelectConversation = (id: string) => {
    if (id === conversationId) return
    loadConversation(id)
  }

  const handleNewConversation = () => {
    newConversation()
    setSidebarRefresh(k => k + 1)
  }

  return (
    <div className="flex flex-1 min-h-0">
      <ConversationSidebar
        currentConversationId={conversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        refreshKey={sidebarRefresh}
      />

      <main className="flex-1 flex flex-col min-w-0">
        <header className="border-b px-4 py-3 flex items-center gap-3 shrink-0">
          {config ? (
            <>
              <Select value={selectedProvider} onValueChange={handleProviderChange}>
                <SelectTrigger className="w-44 h-8 text-xs">
                  <SelectValue placeholder="Provider" />
                </SelectTrigger>
                <SelectContent>
                  {config.providers.map(p => (
                    <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select value={selectedModel} onValueChange={setSelectedModel}>
                <SelectTrigger className="w-52 h-8 text-xs">
                  <SelectValue placeholder="Model" />
                </SelectTrigger>
                <SelectContent>
                  {availableModels.map(m => (
                    <SelectItem key={m.id} value={m.id}>{m.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </>
          ) : (
            <span className="text-xs text-muted-foreground">Connecting to backend…</span>
          )}

          {conversationId && (
            <div className="ml-auto text-xs text-muted-foreground font-mono">
              {conversationId.slice(0, 8)}
            </div>
          )}
        </header>

        <ScrollArea className="flex-1 px-4">
          <div className="max-w-3xl mx-auto py-6 space-y-4">
            {messages.length === 0 && !streaming && (
              <div className="text-center text-muted-foreground text-sm mt-24">
                Start a conversation
              </div>
            )}

            {messages.map((m, i) => (
              <div key={i} className={`flex flex-col ${m.role === "user" ? "items-end" : "items-start"}`}>
                <div className={`max-w-[75%] rounded-xl px-4 py-2.5 text-sm whitespace-pre-wrap break-words ${
                  m.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-foreground"
                }`}>
                  {m.content}
                  {m.role === "assistant" && streaming && i === messages.length - 1 && (
                    <span className="ml-0.5 inline-block w-0.5 h-3.5 bg-current animate-pulse" />
                  )}
                </div>
                {m.role === "assistant" && m.status === "interrupted" && (
                  <span className="mt-1 text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5">
                    Interrupted
                  </span>
                )}
              </div>
            ))}

            {tokenMetadata && (
              <div className="flex justify-start">
                <span className="text-xs text-muted-foreground bg-muted rounded px-2 py-1">
                  in: {String(tokenMetadata.input_tokens ?? "—")} &nbsp;|&nbsp; out:{" "}
                  {String(tokenMetadata.output_tokens ?? "—")}
                </span>
              </div>
            )}

            {error && (
              <div className="text-xs text-destructive bg-destructive/10 rounded px-3 py-2">
                {error}
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        </ScrollArea>

        <div className="border-t px-4 py-3 shrink-0">
          <div className="max-w-3xl mx-auto flex gap-2 items-end">
            <Textarea
              className="resize-none min-h-[44px] max-h-40 text-sm"
              placeholder="Type a message… (Enter to send, Shift+Enter for newline)"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              disabled={streaming}
              rows={1}
            />
            {streaming ? (
              <Button variant="destructive" size="sm" onClick={cancel} className="shrink-0 h-11">
                Stop
              </Button>
            ) : (
              <Button
                size="sm"
                onClick={handleSend}
                disabled={!input.trim() || !selectedProvider || !selectedModel}
                className="shrink-0 h-11"
              >
                Send
              </Button>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
