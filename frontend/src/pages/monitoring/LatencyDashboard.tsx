import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Download, Gauge, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { webClient } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface Stats {
  total: number
  successful: number
  failed: number
  partial: number
  success_rate: number | null
  timed_successes: number
  invalid_timings: number
  avg_ms: number | null
  p50_ms: number | null
  p95_ms: number | null
  p99_ms: number | null
  max_ms: number | null
  fast_pct: number | null
  distribution: Record<string, number>
  http_ms: number | null
  other_ms: number | null
  measured_count: number
}
interface Log {
  id: number
  timestamp: string
  order_id: string
  broker: string | null
  symbol: string | null
  order_type: string
  total_latency_ms: number | null
  status: string
  error: string | null
  mode: string
  category: string
  http_ms: number | null
  other_ms: number | null
  legacy_rtt_ms: number | null
  legacy_overhead_ms: number | null
  http_calls: number | null
  timing_basis: string
}
interface Snapshot {
  as_of: string
  matched_count: number
  sample_count: number
  sample_limit: number
  truncated: boolean
  stats: Stats
  brokers: Record<string, Stats>
  operations: Record<string, Stats>
  recent: Log[]
  failures: { reason: string; count: number }[]
  notice: string
}
const ms = (n: number | null | undefined) => (n == null ? '—' : `${n.toFixed(2)} ms`)
const pct = (n: number | null | undefined) => (n == null ? '—' : `${n.toFixed(1)}%`)
const stamp = (t: string) => new Date(t).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })
const speed = (n: number | null) =>
  n == null
    ? 'Unmeasured'
    : n < 150
      ? 'Excellent'
      : n < 250
        ? 'Good'
        : n < 400
          ? 'Acceptable'
          : 'Slow'

function Comparison({ title, rows }: { title: string; rows: Record<string, Stats> }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>
          Successful request response times · identical filters and sample
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                {[
                  'Name',
                  'Requests',
                  'Failed / partial',
                  'Average',
                  'P50',
                  'P95',
                  'P99',
                  'Under 150 ms',
                  'Measured HTTP',
                  'Remaining time',
                ].map((h) => (
                  <TableHead key={h} className="whitespace-nowrap">
                    {h}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(rows).map(([name, s]) => (
                <TableRow key={name}>
                  <TableCell className="font-medium">{name}</TableCell>
                  <TableCell>{s.total}</TableCell>
                  <TableCell>
                    {s.failed} / {s.partial}
                  </TableCell>
                  <TableCell>{ms(s.avg_ms)}</TableCell>
                  <TableCell>{ms(s.p50_ms)}</TableCell>
                  <TableCell>{ms(s.p95_ms)}</TableCell>
                  <TableCell>{ms(s.p99_ms)}</TableCell>
                  <TableCell>{pct(s.fast_pct)}</TableCell>
                  <TableCell>{ms(s.http_ms)}</TableCell>
                  <TableCell>{ms(s.other_ms)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {!Object.keys(rows).length && (
          <p className="py-6 text-center text-muted-foreground">No matching requests.</p>
        )}
      </CardContent>
    </Card>
  )
}

export default function LatencyDashboard() {
  const [kind, setKind] = useState('orders'),
    [period, setPeriod] = useState('today')
  const [broker, setBroker] = useState(''),
    [operation, setOperation] = useState('')
  const [status, setStatus] = useState('all'),
    [mode, setMode] = useState('all')
  const [selected, setSelected] = useState<Log | null>(null)
  const parameters = new URLSearchParams({
    kind,
    period,
    broker,
    operation,
    status,
    mode,
  }).toString()
  const query = useQuery({
    queryKey: ['latency-dashboard', parameters],
    queryFn: async ({ signal }) =>
      (await webClient.get<Snapshot>(`/latency/api/dashboard?${parameters}`, { signal })).data,
    refetchInterval: 30000,
  })
  const data = query.data,
    s = data?.stats
  const selectClass = 'h-10 w-full rounded-md border border-input bg-background px-3 text-sm'
  const fields = [
    {
      label: 'Request category',
      value: kind,
      set: setKind,
      options: [
        ['orders', 'Order actions'],
        ['data', 'Data & account reads'],
        ['all', 'All requests'],
      ],
    },
    {
      label: 'Period',
      value: period,
      set: setPeriod,
      options: [
        ['today', 'Today (IST)'],
        ['24h', 'Last 24 hours'],
        ['7d', 'Last 7 days'],
        ['30d', 'Last 30 days'],
        ['all', 'All retained history'],
      ],
    },
    {
      label: 'Result',
      value: status,
      set: setStatus,
      options: [
        ['all', 'All results'],
        ['SUCCESS', 'Successful'],
        ['FAILED', 'Failed'],
        ['PARTIAL', 'Partial'],
      ],
    },
    {
      label: 'Mode at request',
      value: mode,
      set: setMode,
      options: [
        ['all', 'All modes'],
        ['live', 'Live'],
        ['sandbox', 'Sandbox'],
        ['unknown', 'Unknown / legacy'],
      ],
    },
  ]
  return (
    <div className="space-y-6 py-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Link to="/dashboard" aria-label="Back to dashboard">
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <Gauge className="h-6 w-6" />
            <h1 className="text-2xl font-bold">Request Latency Monitor</h1>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            Separate order actions from data reads. Measure endpoint responses, not exchange fills.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${query.isFetching ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button variant="outline" asChild>
            <a href={`/latency/export?${parameters}`}>
              <Download className="mr-2 h-4 w-4" />
              Export CSV
            </a>
          </Button>
        </div>
      </div>
      <Card>
        <CardContent className="grid gap-4 pt-6 sm:grid-cols-2 lg:grid-cols-3">
          {fields.map((f) => (
            <label key={f.label} className="space-y-2 text-sm">
              <span>{f.label}</span>
              <select
                aria-label={f.label}
                value={f.value}
                onChange={(e) => {
                  f.set(e.target.value)
                  setSelected(null)
                }}
                className={selectClass}
              >
                {f.options.map(([v, t]) => (
                  <option key={v} value={v}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
          ))}
          <label className="space-y-2 text-sm">
            <span>Broker (optional)</span>
            <input
              aria-label="Broker"
              placeholder="e.g. fyers"
              className={selectClass}
              value={broker}
              maxLength={50}
              onChange={(e) => setBroker(e.target.value.replace(/[^a-zA-Z0-9_-]/g, ''))}
            />
          </label>
          <label className="space-y-2 text-sm">
            <span>Operation (optional)</span>
            <input
              aria-label="Operation"
              placeholder="e.g. HISTORY"
              className={selectClass}
              value={operation}
              maxLength={50}
              onChange={(e) =>
                setOperation(e.target.value.replace(/[^a-zA-Z0-9_-]/g, '').toUpperCase())
              }
            />
          </label>
        </CardContent>
      </Card>
      {query.isError && (
        <div role="alert" className="rounded-md border border-destructive p-4 text-destructive">
          Could not refresh latency data.{' '}
          {data ? 'Showing the previous snapshot; its time is shown below.' : 'Please retry.'}
        </div>
      )}
      {query.isPending && <output>Loading latency snapshot…</output>}
      {data && s && (
        <>
          <p className="text-sm text-muted-foreground">
            Snapshot {stamp(data.as_of)} IST · {data.sample_count.toLocaleString('en-IN')} requests
            {data.truncated
              ? ` out of ${data.matched_count.toLocaleString('en-IN')} matching records; newest ${data.sample_limit.toLocaleString('en-IN')} only`
              : ''}
            . Cards, distribution, comparisons and export use this same bounded selection. Recent
            table shows up to 100 rows. Export captures a fresh snapshot.
          </p>
          {data.truncated && (
            <p role="note" className="rounded-md border border-amber-500 p-3">
              Sample limit reached. Narrow the period or operation to compare the complete matching
              population.
            </p>
          )}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[
              [
                'Requests tracked',
                String(s.total),
                `${s.successful} successful · ${s.failed} failed · ${s.partial} partial`,
              ],
              ['Success rate', pct(s.success_rate), 'Request outcome; not trade fill success'],
              [
                'Average response time',
                ms(s.avg_ms),
                `${s.timed_successes} successful timed requests`,
              ],
              ['Fast successful requests', pct(s.fast_pct), 'Under 150 ms · target 95%'],
            ].map(([title, value, hint]) => (
              <Card key={title}>
                <CardContent className="pt-6">
                  <p className="text-sm text-muted-foreground">{title}</p>
                  <p className="my-2 text-3xl font-bold">{value}</p>
                  <p className="text-xs text-muted-foreground">{hint}</p>
                </CardContent>
              </Card>
            ))}
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Response-time distribution</CardTitle>
              <CardDescription>
                All {s.timed_successes} successful timed requests in the selection. Failed requests
                do not improve speed scores.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
                {[
                  ['excellent', 'Excellent · under 150 ms', 'bg-green-500'],
                  ['good', 'Good · 150 to under 250 ms', 'bg-yellow-500'],
                  ['acceptable', 'Acceptable · 250 to under 400 ms', 'bg-orange-500'],
                  ['slow', 'Slow · 400 ms or more', 'bg-red-500'],
                ].map(([k, label, color]) => (
                  <div key={k}>
                    <div className="mb-2 text-sm">{label}</div>
                    <div className="h-3 overflow-hidden rounded bg-muted">
                      <div
                        className={`h-full ${color}`}
                        style={{
                          width: `${s.timed_successes ? (100 * s.distribution[k]) / s.timed_successes : 0}%`,
                        }}
                      />
                    </div>
                    <p className="mt-2 text-sm">
                      {s.distribution[k]} ·{' '}
                      {s.timed_successes ? pct((100 * s.distribution[k]) / s.timed_successes) : '—'}
                    </p>
                  </div>
                ))}
              </div>
              <p className="mt-4 text-sm text-muted-foreground">
                P50 {ms(s.p50_ms)} · P95 {ms(s.p95_ms)} · P99 {ms(s.p99_ms)} · Maximum{' '}
                {ms(s.max_ms)}
                {s.invalid_timings ? ` · ${s.invalid_timings} invalid timings excluded` : ''}
              </p>
            </CardContent>
          </Card>
          <Comparison title="Operation comparison" rows={data.operations} />
          <Comparison title="Broker comparison" rows={data.brokers} />
          <Card>
            <CardHeader>
              <CardTitle>Measurement scope</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              <p>{data.notice}</p>
              <p>
                Measured HTTP and remaining time cover {s.measured_count} successful records with
                the new instrumentation. Remaining time includes validation, rate-limit waits,
                retries and other processing; it is not a pure CPU measurement. No captured HTTP
                call does not prove that every downstream transport is instrumented. Legacy
                breakdowns are shown only in request details.
              </p>
              <p>
                Installation diagnostics may include multiple sessions. Data requests retained by
                the existing collector expire after seven days; “all retained history” cannot
                recover deleted records. Live/Sandbox is the captured request context, not the quote
                source.
              </p>
            </CardContent>
          </Card>
          {data.failures.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Failure reasons</CardTitle>
                <CardDescription>
                  Authentication and validation failures are not broker execution delays.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="space-y-3">
                  {data.failures.map((f) => (
                    <li key={f.reason} className="flex justify-between gap-4 text-sm">
                      <span className="break-words">{f.reason}</span>
                      <Badge variant="secondary">{f.count}</Badge>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
          <Card>
            <CardHeader>
              <CardTitle>Recent requests</CardTitle>
              <CardDescription>{data.recent.length} displayed · time in IST</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      {[
                        'Time',
                        'Operation',
                        'Broker / mode',
                        'Symbol',
                        'Response time',
                        'Status',
                        '',
                      ].map((h) => (
                        <TableHead key={h}>{h}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.recent.map((row) => (
                      <TableRow key={row.id}>
                        <TableCell className="whitespace-nowrap">{stamp(row.timestamp)}</TableCell>
                        <TableCell>{row.order_type}</TableCell>
                        <TableCell>
                          {row.broker || 'Unattributed'}
                          <div className="text-xs text-muted-foreground">{row.mode}</div>
                        </TableCell>
                        <TableCell>{row.symbol || '—'}</TableCell>
                        <TableCell className="whitespace-nowrap">
                          {ms(row.total_latency_ms)}
                        </TableCell>
                        <TableCell>
                          <Badge variant={row.status === 'SUCCESS' ? 'secondary' : 'destructive'}>
                            {row.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Button variant="ghost" size="sm" onClick={() => setSelected(row)}>
                            Details
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              {!data.recent.length && (
                <p className="py-8 text-center text-muted-foreground">
                  No matching requests. Select Data &amp; account reads or a wider period to inspect
                  history.
                </p>
              )}
            </CardContent>
          </Card>
        </>
      )}
      <Dialog open={!!selected} onOpenChange={() => setSelected(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Request timing breakdown</DialogTitle>
            <DialogDescription>
              {selected?.order_type} · {selected?.timestamp ? stamp(selected.timestamp) : ''} IST
            </DialogDescription>
          </DialogHeader>
          {selected && (
            <div className="space-y-4 text-sm">
              <p>
                Order/request ID:{' '}
                <span className="break-all font-mono">
                  {selected.order_id === 'unknown'
                    ? 'Not supplied / not applicable'
                    : selected.order_id}
                </span>
              </p>
              <p className="text-2xl font-semibold">
                {ms(selected.total_latency_ms)}{' '}
                <span className="text-sm text-muted-foreground">
                  {speed(selected.total_latency_ms)}
                </span>
              </p>
              <p>{selected.timing_basis}</p>
              {selected.http_ms != null ? (
                <dl className="grid grid-cols-2 gap-3">
                  <dt>Captured HTTP calls</dt>
                  <dd>{selected.http_calls}</dd>
                  <dt>Measured HTTP time</dt>
                  <dd>{ms(selected.http_ms)}</dd>
                  <dt>Remaining endpoint time</dt>
                  <dd>{ms(selected.other_ms)}</dd>
                </dl>
              ) : (
                <>
                  <p>
                    Historical attribution is uncertain: older instrumentation could keep only the
                    last HTTP call, or label the entire local endpoint as broker time.
                  </p>
                  <p>
                    Recorded legacy HTTP: {ms(selected.legacy_rtt_ms)}
                    <br />
                    Recorded legacy overhead: {ms(selected.legacy_overhead_ms)}
                  </p>
                </>
              )}
              <p className="text-muted-foreground">
                Timing starts at endpoint instrumentation and ends when the handler returns. It
                excludes earlier middleware, client network transit and asynchronous telemetry
                persistence. Broker acceptance is not an exchange fill.
              </p>
              {selected.error && <p className="break-words text-destructive">{selected.error}</p>}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
