import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { webClient } from '@/api/client'
import { Button } from '@/components/ui/button'

type Trade = {
  symbol: string
  path: string
  entry_ts: number
  exit_ts: number | null
  entry: number
  exit: number | null
  quantity: number
  stop: number
  target: number
  fees: number
  net_pnl: number
  reason: string
}
type Candle = {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  ha_open: number
  ha_high: number
  ha_low: number
  ha_close: number
  bb_upper: number
  vwap: number
}
type Item = { id: string; day: string; kind: string; status: string }
type Report = Item & {
  note: string
  paths: string[]
  metrics: Record<string, Record<string, number | null>>
  trades: Trade[]
  candles: Record<string, Candle[]>
  coverage: { eligible: boolean; symbol: string }[]
}
const money = (n: number | null | undefined) =>
  n == null ? '—' : `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
const stamp = (n: number | null) =>
  n == null ? 'Open' : new Date(n * 1000).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })

function TradeChart({ trade, candles }: { trade: Trade; candles: Candle[] }) {
  const [ha, setHa] = useState(false)
  const [full, setFull] = useState(false)
  const data = candles.filter(
    (c) =>
      full ||
      (c.timestamp >= trade.entry_ts - 15 * 60 &&
        c.timestamp <= (trade.exit_ts ?? trade.entry_ts + 3600) + 10 * 60)
  )
  if (!data.length) return <p>No observed candles available yet.</p>
  const low = Math.min(trade.stop, ...data.map((c) => (ha ? c.ha_low : c.low)))
  const high = Math.max(trade.target, ...data.map((c) => (ha ? c.ha_high : c.high)))
  const range = Math.max(high - low, 0.01)
  const y = (n: number) => 310 - ((n - low) / range) * 275
  const x = (n: number) =>
    70 +
    ((n - data[0].timestamp) / Math.max(60, data[data.length - 1].timestamp - data[0].timestamp)) *
      810
  const width = Math.max(1, Math.min(10, 650 / data.length))
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-4">
        <label>
          <input type="checkbox" checked={ha} onChange={(e) => setHa(e.target.checked)} /> Heikin
          Ashi candles
        </label>
        <label>
          <input type="checkbox" checked={full} onChange={(e) => setFull(e.target.checked)} /> Full
          session
        </label>
      </div>
      <svg
        viewBox="0 0 1000 370"
        role="img"
        aria-label={`${trade.symbol} trade candle chart with entry, exit, stop and target`}
        className="w-full min-w-0 rounded border bg-background"
      >
        {[0, 1, 2, 3, 4].map((i) => (
          <g key={i}>
            <line
              x1="65"
              x2="895"
              y1={y(low + (range * i) / 4)}
              y2={y(low + (range * i) / 4)}
              stroke="currentColor"
              opacity="0.15"
            />
            <text x="4" y={y(low + (range * i) / 4)} fill="currentColor" fontSize="11">
              {(low + (range * i) / 4).toFixed(2)}
            </text>
          </g>
        ))}
        {data.map((c) => {
          const op = ha ? c.ha_open : c.open,
            cl = ha ? c.ha_close : c.close
          const color = cl >= op ? '#10b981' : '#ef4444'
          return (
            <g key={c.timestamp}>
              <title>
                {stamp(c.timestamp)} O {op.toFixed(2)} H {(ha ? c.ha_high : c.high).toFixed(2)} L{' '}
                {(ha ? c.ha_low : c.low).toFixed(2)} C {cl.toFixed(2)}
              </title>
              <line
                x1={x(c.timestamp)}
                x2={x(c.timestamp)}
                y1={y(ha ? c.ha_high : c.high)}
                y2={y(ha ? c.ha_low : c.low)}
                stroke={color}
              />
              <rect
                x={x(c.timestamp) - width / 2}
                y={y(Math.max(op, cl))}
                width={width}
                height={Math.max(1, Math.abs(y(op) - y(cl)))}
                fill={color}
              />
            </g>
          )
        })}
        {(
          [
            ['Entry', trade.entry, '#3b82f6'],
            ['Stop', trade.stop, '#ef4444'],
            ['Target', trade.target, '#10b981'],
          ] as const
        ).map(([label, price, color]) => (
          <g key={label}>
            <line
              x1="65"
              x2="895"
              y1={y(price)}
              y2={y(price)}
              stroke={color}
              strokeDasharray="5 4"
            />
            <text x="900" y={y(price)} fill={color} fontSize="12">
              {label} {price.toFixed(2)}
            </text>
          </g>
        ))}
        <circle cx={x(trade.entry_ts)} cy={y(trade.entry)} r="5" fill="#3b82f6">
          <title>Entry {stamp(trade.entry_ts)}</title>
        </circle>
        {trade.exit_ts && trade.exit != null && (
          <circle cx={x(trade.exit_ts)} cy={y(trade.exit)} r="5" fill="#a855f7">
            <title>Exit {stamp(trade.exit_ts)}</title>
          </circle>
        )}
        <text x="70" y="350" fill="currentColor" fontSize="12">
          {stamp(data[0].timestamp)} IST
        </text>
        <text x="650" y="350" fill="currentColor" fontSize="12">
          {stamp(data[data.length - 1].timestamp)} IST
        </text>
      </svg>
      <p className="text-sm">
        {trade.symbol} · {trade.quantity} shares · Entry {stamp(trade.entry_ts)} · Exit{' '}
        {stamp(trade.exit_ts)} · {trade.reason} · Net {money(trade.net_pnl)}
      </p>
    </div>
  )
}

export default function StrategyReports() {
  const [items, setItems] = useState<Item[]>([])
  const [selected, setSelected] = useState('')
  const [report, setReport] = useState<Report | null>(null)
  const [path, setPath] = useState('')
  const [tradeIndex, setTradeIndex] = useState(0)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    const controller = new AbortController()
    async function poll() {
      try {
        const response = await webClient.get('/market-scanner/api/reports', {
          signal: controller.signal,
        })
        if (!stopped) {
          setItems(response.data.data)
          setSelected((s) => s || response.data.data[0]?.id || '')
        }
      } catch {
        if (!stopped) setError('Unable to load reports. Check your login and connection.')
      } finally {
        if (!stopped) timer = setTimeout(poll, 15000)
      }
    }
    void poll()
    return () => {
      stopped = true
      clearTimeout(timer)
      controller.abort()
    }
  }, [])
  useEffect(() => {
    if (!selected) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    const controller = new AbortController()
    setReport(null)
    setTradeIndex(0)
    async function poll() {
      try {
        const response = await webClient.get(
          `/market-scanner/api/reports/${encodeURIComponent(selected)}`,
          { signal: controller.signal }
        )
        if (!stopped) {
          setReport(response.data.data)
          setPath((p) => (response.data.data.paths.includes(p) ? p : response.data.data.paths[0]))
          setError('')
        }
      } catch {
        if (!stopped) setError('Unable to load the selected report.')
      } finally {
        if (!stopped) timer = setTimeout(poll, 10000)
      }
    }
    void poll()
    return () => {
      stopped = true
      clearTimeout(timer)
      controller.abort()
    }
  }, [selected])
  async function schedule() {
    setBusy(true)
    try {
      await webClient.post('/market-scanner/api/paper-schedule', {})
      setMessage(
        'Paper strategy scheduled: Monday–Friday, 09:15–15:10 IST; all stocks square off at 15:05. Keep the app running and FYERS logged in. NSE calendar applies.'
      )
      setError('')
    } catch {
      setError('Scheduling failed. Check your FYERS login.')
    } finally {
      setBusy(false)
    }
  }
  const trades = report?.trades.filter((t) => t.path === path) ?? []
  const trade = trades[tradeIndex]
  const metrics = report?.metrics[path]
  const labels: [string, string, boolean][] = [
    ['gross_pnl', 'Gross P&L', true],
    ['charges', 'Estimated charges', true],
    ['net_pnl', 'Net P&L', true],
    ['peak_capital', 'Maximum capital used', true],
    ['current_capital', 'Capital still in positions', true],
    ['best_trade', 'Best trade', true],
    ['worst_trade', 'Worst trade', true],
    ['realized_drawdown', 'Realized drawdown', true],
    ['trades', 'Closed trades', false],
    ['open_trades', 'Open trades', false],
    ['win_rate', 'Win rate %', false],
    ['profit_factor', 'Profit factor', false],
    ['return_on_peak_capital', 'Net / peak capital %', false],
  ]
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Strategy Reports</h1>
          <p className="text-muted-foreground">
            Top Gain Volumes · ₹1 lakh per trade · Paper forward testing
          </p>
        </div>
        <div className="flex gap-3">
          <Button asChild variant="outline">
            <Link to="/python">Schedules</Link>
          </Button>
          <Button disabled={busy} onClick={() => void schedule()}>
            Schedule paper test
          </Button>
        </div>
      </div>
      {error && (
        <p role="alert" className="text-red-500">
          {error}
        </p>
      )}
      {message && <output>{message}</output>}
      <div className="flex flex-wrap gap-3">
        <select
          aria-label="Report session"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="rounded border bg-background p-2"
        >
          <option value="">Select a session</option>
          {items.map((i) => (
            <option key={i.id} value={i.id}>
              {i.day} · {i.kind} · {i.status}
            </option>
          ))}
        </select>
        {report && (
          <>
            <select
              aria-label="Execution scenario"
              value={path}
              onChange={(e) => {
                setPath(e.target.value)
                setTradeIndex(0)
              }}
              className="rounded border bg-background p-2"
            >
              {report.paths.map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
            <Button asChild variant="outline">
              <a href={`/market-scanner/api/reports/${encodeURIComponent(selected)}?download=csv`}>
                Download trades CSV
              </a>
            </Button>
          </>
        )}
      </div>
      {!items.length && (
        <p>No sessions recorded yet. Scheduled paper sessions will appear here automatically.</p>
      )}
      {report && (
        <>
          <p className="rounded border p-3 text-sm text-muted-foreground">{report.note}</p>
          <p>
            Status: {report.status}
            {report.coverage?.length > 0 &&
              ` · ${report.coverage.filter((c) => c.eligible).length}/${report.coverage.length} eligible stock sessions`}
          </p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {labels.map(([key, label, rupees]) => (
              <div key={key} className="rounded-lg border bg-card p-4">
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className="mt-1 text-lg font-semibold tabular-nums">
                  {rupees
                    ? money(metrics?.[key])
                    : (metrics?.[key]?.toLocaleString('en-IN', { maximumFractionDigits: 2 }) ??
                      '—')}
                </p>
              </div>
            ))}
          </div>
          {trade && (
            <section className="space-y-4 rounded-lg border p-4">
              <h2 className="text-lg font-semibold">Trade chart</h2>
              <select
                aria-label="Trade chart"
                className="max-w-full rounded border bg-background p-2"
                value={tradeIndex}
                onChange={(e) => setTradeIndex(Number(e.target.value))}
              >
                {trades.map((t, i) => (
                  <option key={`${t.symbol}-${t.entry_ts}`} value={i}>
                    {i + 1}. {t.symbol} · {stamp(t.entry_ts)} · {money(t.net_pnl)}
                  </option>
                ))}
              </select>
              <TradeChart
                key={`${selected}-${path}-${tradeIndex}`}
                trade={trade}
                candles={report.candles[trade.symbol] ?? []}
              />
            </section>
          )}
          <div className="overflow-auto rounded border">
            <table className="w-full text-left text-sm">
              <thead>
                <tr>
                  {[
                    'Stock',
                    'Entry IST',
                    'Exit IST',
                    'Qty',
                    'Entry',
                    'Exit',
                    'Charges',
                    'Net P&L',
                    'Exit reason',
                  ].map((h) => (
                    <th key={h} className="whitespace-nowrap p-3">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={`${t.symbol}-${t.entry_ts}`} className="border-t">
                    <td className="p-3">
                      <button type="button" className="underline" onClick={() => setTradeIndex(i)}>
                        {t.symbol}
                      </button>
                    </td>
                    {[
                      stamp(t.entry_ts),
                      stamp(t.exit_ts),
                      t.quantity,
                      money(t.entry),
                      money(t.exit),
                      money(t.fees),
                      money(t.net_pnl),
                      t.reason,
                    ].map((v, j) => (
                      <td key={`${t.symbol}-${j}`} className="whitespace-nowrap p-3">
                        {v}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {!trades.length && <p className="p-4">No trades for this scenario.</p>}
          </div>
        </>
      )}
    </div>
  )
}
