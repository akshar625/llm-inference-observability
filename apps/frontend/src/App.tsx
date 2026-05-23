import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useStreamingChat } from "@/hooks/useStreamingChat"

const BACKEND_URL = "http://localhost:8000"

interface ProviderModel {
  id: string
  name: string
  context_window: number
  max_tokens_default: number
  supports_streaming: boolean
}

interface Provider {
  id: string
  name: string
  models: ProviderModel[]
}

interface BackendConfig {
  providers: Provider[]
  defaults: { temperature: number; max_tokens: number }
}

export default function App() {
  const [config, setConfig] = useState<BackendConfig | null>(null)
  const [selectedProvider, setSelectedProvider] = useState<string>("")
  const [selectedModel, setSelectedModel] = useState<string>("")
  const [input, setInput] = useState("")
  const bottomRef = useRef<HTMLDivElement>(null)

  const { messages, isStreaming, error, tokenMetadata, sendMessage, stopStreaming, clearMessages } =
    useStreamingChat()

  useEffect(() => {
    fetch(`${BACKEND_URL}/config`)
      .then(r => r.json())
      .then((data: BackendConfig) => {
        setConfig(data)
        if (data.providers.length > 0) {
          const first = data.providers[0]
          setSelectedProvider(first.id)
          setSelectedModel(first.models[0]?.id ?? "")
        }
      })
      .catch(() => {/* backend not up yet — user will see empty selects */})
  }, [])

  // Auto-scroll to bottom when messages update
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const availableModels =
    config?.providers.find(p => p.id === selectedProvider)?.models ?? []

  const handleProviderChange = (value: string) => {
    setSelectedProvider(value)
    const provider = config?.providers.find(p => p.id === value)
    setSelectedModel(provider?.models[0]?.id ?? "")
  }

  const handleSend = () => {
    if (!input.trim() || isStreaming || !selectedProvider || !selectedModel) return
    const msg = input
    setInput("")
    sendMessage({ provider: selectedProvider, model: selectedModel, userMessage: msg })
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-screen bg-background text-foreground">
      {/* Header */}
      <header className="border-b px-6 py-3 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-base tracking-tight">LLM Inference Observatory</span>
        </div>
        <div className="flex items-center gap-3">
          {config ? (
            <>
              <Select value={selectedProvider} onValueChange={handleProviderChange}>
                <SelectTrigger className="w-44 h-8 text-xs">
                  <SelectValue placeholder="Provider" />
                </SelectTrigger>
                <SelectContent>
                  {config.providers.map(p => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select value={selectedModel} onValueChange={setSelectedModel}>
                <SelectTrigger className="w-44 h-8 text-xs">
                  <SelectValue placeholder="Model" />
                </SelectTrigger>
                <SelectContent>
                  {availableModels.map(m => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </>
          ) : (
            <span className="text-xs text-muted-foreground">Connecting to backend…</span>
          )}
          <Button variant="ghost" size="sm" className="text-xs" onClick={clearMessages}>
            Clear
          </Button>
        </div>
      </header>

      {/* Message list */}
      <ScrollArea className="flex-1 px-4">
        <div className="max-w-3xl mx-auto py-6 space-y-4">
          {messages.length === 0 && (
            <div className="text-center text-muted-foreground text-sm mt-24">
              Select a provider and model, then send a message.
            </div>
          )}

          {messages.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[75%] rounded-xl px-4 py-2.5 text-sm whitespace-pre-wrap break-words ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-foreground"
                }`}
              >
                {msg.content}
                {/* Blinking cursor while the last assistant message is still streaming */}
                {msg.role === "assistant" && isStreaming && i === messages.length - 1 && (
                  <span className="ml-0.5 inline-block w-0.5 h-3.5 bg-current animate-pulse" />
                )}
              </div>
            </div>
          ))}

          {/* Token metadata badge */}
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

      {/* Input area */}
      <div className="border-t px-4 py-3 shrink-0">
        <div className="max-w-3xl mx-auto flex gap-2 items-end">
          <Textarea
            className="resize-none min-h-[44px] max-h-40 text-sm"
            placeholder="Type a message… (Enter to send, Shift+Enter for newline)"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
            rows={1}
          />
          {isStreaming ? (
            <Button variant="destructive" size="sm" onClick={stopStreaming} className="shrink-0 h-11">
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
    </div>
  )
}
