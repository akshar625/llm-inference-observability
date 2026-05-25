import { useEffect, useState } from "react"
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"

import { API_BASE } from "@/lib/api"

type Overview = {
  total_requests: number
  total_errors: number
  total_cancelled: number
  success_rate: number
  error_rate: number
  cancellation_rate: number
  avg_latency_ms: number
  total_cost_usd: number
  total_tokens_in: number
  total_tokens_out: number
  active_streams: number
}

type Bucket = {
  timestamp: string
  requests: number
  errors: number
  cancelled: number
  avg_latency_ms: number
  total_cost_usd: number
  tokens_out: number
}

type Percentiles = {
  duration_ms: { p50: number | null; p95: number | null; p99: number | null }
  ttft_ms: { p50: number | null; p95: number | null; p99: number | null }
  avg_tokens_per_second: number | null
  sample_size: number
}

type ProviderRow = {
  provider: string
  model: string
  requests: number
  errors: number
  error_rate: number
  avg_latency_ms: number
  total_cost_usd: number
  tokens_in: number
  tokens_out: number
}

type LogEvent = {
  event_id: string
  conversation_id: string | null
  provider: string
  model: string
  started_at: string
  duration_ms: number | null
  ttft_ms: number | null
  tokens_in: number | null
  tokens_out: number | null
  estimated_cost_usd: number | null
  status: string
  pii_detected: boolean
  prompt_preview: string
}

export function DashboardPage() {
  const [window, setWindow] = useState("24h")
  const [overview, setOverview] = useState<Overview | null>(null)
  const [series, setSeries] = useState<Bucket[]>([])
  const [percentiles, setPercentiles] = useState<Percentiles | null>(null)
  const [providers, setProviders] = useState<ProviderRow[]>([])
  const [logs, setLogs] = useState<LogEvent[]>([])
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)

  const load = async () => {
    try {
      const [o, t, p, prov, l] = await Promise.all([
        fetch(`${API_BASE}/metrics/overview?window=${window}`).then(r => r.json()),
        fetch(`${API_BASE}/metrics/timeseries?window=${window}`).then(r => r.json()),
        fetch(`${API_BASE}/metrics/percentiles?window=1h`).then(r => r.json()),
        fetch(`${API_BASE}/metrics/by-provider?window=${window}`).then(r => r.json()),
        fetch(`${API_BASE}/logs/recent?limit=50`).then(r => r.json()),
      ])
      setOverview(o)
      setSeries(t.buckets)
      setPercentiles(p)
      setProviders(prov.breakdown)
      setLogs(l.events)
      setUpdatedAt(new Date())
    } catch (e) {
      console.error("Dashboard load failed:", e)
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 15_000)
    return () => clearInterval(id)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [window])

  const fmtTime = (ts: string) =>
    new Date(ts).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
  const fmtHour = (ts: string) =>
    new Date(ts).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })

  return (
    <ScrollArea className="flex-1">
      <div className="p-6 space-y-6 max-w-7xl mx-auto w-full">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold">Observability</h1>
            {updatedAt && (
              <p className="text-xs text-muted-foreground mt-1">
                Auto-refreshes every 15s — last update {updatedAt.toLocaleTimeString()}
              </p>
            )}
          </div>
          <Select value={window} onValueChange={setWindow}>
            <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="1h">Last 1h</SelectItem>
              <SelectItem value="24h">Last 24h</SelectItem>
              <SelectItem value="7d">Last 7d</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Overview cards */}
        {overview && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard label="Requests" value={overview.total_requests.toLocaleString()} />
            <StatCard label="Success rate" value={`${(overview.success_rate * 100).toFixed(1)}%`} />
            <StatCard label="Avg latency" value={`${(overview.avg_latency_ms / 1000).toFixed(2)}s`} />
            <StatCard label="Total cost" value={`$${overview.total_cost_usd.toFixed(4)}`} />
            <StatCard label="Active streams" value={overview.active_streams.toString()} />
            <StatCard label="Errors" value={overview.total_errors.toString()} tone={overview.total_errors > 0 ? "destructive" : undefined} />
            <StatCard label="Cancelled" value={overview.total_cancelled.toString()} />
            <StatCard label="Tokens out" value={overview.total_tokens_out.toLocaleString()} />
          </div>
        )}

        {/* Percentiles */}
        {percentiles && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">
                Latency percentiles
                <span className="text-xs text-muted-foreground ml-2 font-normal">
                  live · last 1h · {percentiles.sample_size} samples
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Metric label="duration p50" value={percentiles.duration_ms.p50 ? `${percentiles.duration_ms.p50}ms` : "—"} />
              <Metric label="duration p95" value={percentiles.duration_ms.p95 ? `${percentiles.duration_ms.p95}ms` : "—"} />
              <Metric label="duration p99" value={percentiles.duration_ms.p99 ? `${percentiles.duration_ms.p99}ms` : "—"} />
              <Metric label="avg tokens/s" value={percentiles.avg_tokens_per_second ? percentiles.avg_tokens_per_second.toString() : "—"} />
              <Metric label="TTFT p50" value={percentiles.ttft_ms.p50 ? `${percentiles.ttft_ms.p50}ms` : "—"} />
              <Metric label="TTFT p95" value={percentiles.ttft_ms.p95 ? `${percentiles.ttft_ms.p95}ms` : "—"} />
              <Metric label="TTFT p99" value={percentiles.ttft_ms.p99 ? `${percentiles.ttft_ms.p99}ms` : "—"} />
            </CardContent>
          </Card>
        )}

        {/* Charts 2×2 */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <ChartCard title="Requests per hour">
            <BarChart data={series}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="timestamp" tickFormatter={fmtHour} fontSize={11} />
              <YAxis fontSize={11} />
              <Tooltip labelFormatter={fmtTime} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="requests" stackId="a" fill="#3b82f6" name="success" />
              <Bar dataKey="errors" stackId="a" fill="#ef4444" name="errors" />
              <Bar dataKey="cancelled" stackId="a" fill="#f59e0b" name="cancelled" />
            </BarChart>
          </ChartCard>

          <ChartCard title="Avg latency (ms)">
            <LineChart data={series}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="timestamp" tickFormatter={fmtHour} fontSize={11} />
              <YAxis fontSize={11} />
              <Tooltip labelFormatter={fmtTime} />
              <Line type="monotone" dataKey="avg_latency_ms" stroke="#10b981" strokeWidth={2} dot={false} />
            </LineChart>
          </ChartCard>

          <ChartCard title="Tokens out per hour">
            <BarChart data={series}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="timestamp" tickFormatter={fmtHour} fontSize={11} />
              <YAxis fontSize={11} />
              <Tooltip labelFormatter={fmtTime} />
              <Bar dataKey="tokens_out" fill="#8b5cf6" />
            </BarChart>
          </ChartCard>

          <ChartCard title="Cost per hour ($)">
            <LineChart data={series}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="timestamp" tickFormatter={fmtHour} fontSize={11} />
              <YAxis fontSize={11} tickFormatter={(v: number) => `$${v.toFixed(4)}`} />
              <Tooltip labelFormatter={fmtTime} formatter={(v: number) => `$${v.toFixed(6)}`} />
              <Line type="monotone" dataKey="total_cost_usd" stroke="#f59e0b" strokeWidth={2} dot={false} />
            </LineChart>
          </ChartCard>
        </div>

        {/* Provider breakdown */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">By provider / model</CardTitle>
          </CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground text-xs uppercase tracking-wider">
                  <th className="py-2 font-medium">Provider</th>
                  <th className="py-2 font-medium">Model</th>
                  <th className="py-2 font-medium text-right">Requests</th>
                  <th className="py-2 font-medium text-right">Error %</th>
                  <th className="py-2 font-medium text-right">Avg latency</th>
                  <th className="py-2 font-medium text-right">Tokens out</th>
                  <th className="py-2 font-medium text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {providers.map(p => (
                  <tr key={`${p.provider}-${p.model}`} className="border-b hover:bg-muted/30">
                    <td className="py-2 font-medium">{p.provider}</td>
                    <td className="py-2 font-mono text-xs">{p.model}</td>
                    <td className="py-2 text-right">{p.requests.toLocaleString()}</td>
                    <td className={`py-2 text-right ${p.error_rate > 0 ? "text-destructive" : ""}`}>
                      {(p.error_rate * 100).toFixed(1)}%
                    </td>
                    <td className="py-2 text-right">{(p.avg_latency_ms / 1000).toFixed(2)}s</td>
                    <td className="py-2 text-right">{p.tokens_out.toLocaleString()}</td>
                    <td className="py-2 text-right">${p.total_cost_usd.toFixed(4)}</td>
                  </tr>
                ))}
                {providers.length === 0 && (
                  <tr><td colSpan={7} className="py-8 text-center text-muted-foreground">No data in this window</td></tr>
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>

        {/* Recent events */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Recent inference events</CardTitle>
          </CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground text-xs uppercase tracking-wider">
                  <th className="py-2 font-medium">Time</th>
                  <th className="py-2 font-medium">Status</th>
                  <th className="py-2 font-medium">Provider</th>
                  <th className="py-2 font-medium text-right">Latency</th>
                  <th className="py-2 font-medium text-right">TTFT</th>
                  <th className="py-2 font-medium text-right">Tokens in/out</th>
                  <th className="py-2 font-medium">Prompt</th>
                  <th className="py-2 font-medium text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {logs.map(e => (
                  <tr key={e.event_id} className="border-b hover:bg-muted/30">
                    <td className="py-2 text-xs">{fmtTime(e.started_at)}</td>
                    <td className={`py-2 text-xs font-medium ${
                      e.status === "success" ? "text-green-600" :
                      e.status === "error" ? "text-destructive" :
                      e.status === "cancelled" ? "text-amber-600" : ""
                    }`}>{e.status}</td>
                    <td className="py-2 text-xs">{e.provider}</td>
                    <td className="py-2 text-right text-xs">{e.duration_ms ? `${e.duration_ms}ms` : "—"}</td>
                    <td className="py-2 text-right text-xs">{e.ttft_ms ? `${e.ttft_ms}ms` : "—"}</td>
                    <td className="py-2 text-right text-xs">{e.tokens_in ?? "—"} / {e.tokens_out ?? "—"}</td>
                    <td className="py-2 text-xs max-w-xs truncate">
                      {e.pii_detected && <span className="text-amber-600 mr-1" title="PII redacted">⚠</span>}
                      {e.prompt_preview}
                    </td>
                    <td className="py-2 text-right text-xs">
                      {e.estimated_cost_usd ? `$${e.estimated_cost_usd.toFixed(6)}` : "—"}
                    </td>
                  </tr>
                ))}
                {logs.length === 0 && (
                  <tr><td colSpan={8} className="py-8 text-center text-muted-foreground">No events yet</td></tr>
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>
    </ScrollArea>
  )
}

function StatCard({ label, value, tone }: { label: string; value: string; tone?: "destructive" }) {
  return (
    <Card>
      <CardContent className="pt-6 pb-5">
        <div className="text-xs text-muted-foreground uppercase tracking-wider">{label}</div>
        <div className={`text-2xl font-semibold mt-1 ${tone === "destructive" ? "text-destructive" : ""}`}>
          {value}
        </div>
      </CardContent>
    </Card>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold mt-0.5">{value}</div>
    </div>
  )
}

function ChartCard({ title, children }: { title: string; children: React.ReactElement }) {
  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">{title}</CardTitle></CardHeader>
      <CardContent className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
