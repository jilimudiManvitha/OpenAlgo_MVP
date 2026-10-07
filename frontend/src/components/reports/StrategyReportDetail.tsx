import { useEffect, useState } from 'react'
import { webClient } from '@/api/client'
import { Button } from '@/components/ui/button'

type Trade = {
  symbol: string
  path: string
  side?: string | number
  direction?: string
  entry_ts: number
  exit_ts: number | null
  entry: number
  exit: number | null
  quantity: number
  stop: number | null
  target: number | null
  fees: number
  net_pnl: number
  brokerage?: number
  charge_status?: string
  charge_breakdown?: Record<string, number>
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
  bb_lower?: number
  bb_middle?: number
  vwap: number
}
type Item = { id: string; day: string; kind: string; status: string }
type Report = Item & {
  note: string
  paths: string[]
  metrics: Record<string, Record<string, number | null>>
  trades: Trade[]
  candles: Record<string, Candle[]>
  coverage: { eligible: boolean; symbol: string; reason?: string }[]
}
const money = (n: number | null | undefined) =>
  n == null ? '—' : `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
const stamp = (n: number | null) =>
  n == null ? 'Open' : new Date(n * 1000).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })

export function TradeChart({ trade, candles }: { trade: Trade; candles: Candle[] }) {
  const short = trade.direction === 'SHORT' || ['SELL', 'SHORT', -1].includes(trade.side ?? '')
  const band = short ? 'bb_lower' : 'bb_upper'
  const [ha, setHa] = useState(false)
  const [full, setFull] = useState(false)
  const data = candles.filter(
    (c) =>
      full ||
      (c.timestamp >= trade.entry_ts - 15 * 60 &&
        c.timestamp <= (trade.exit_ts ?? trade.entry_ts + 3600) + 10 * 60)
  )
  if (!data.length) return <p>No observed candles available yet.</p>
  const indicators = data
    .flatMap((c) => [c[band], c.bb_middle, c.vwap])
    .filter((n): n is number => typeof n === 'number' && Number.isFinite(n) && n > 0)
  const low = Math.min(
    trade.stop ?? trade.entry,
    trade.target ?? trade.entry,
    trade.entry,
    trade.exit ?? trade.entry,
    ...indicators,
    ...data.map((c) => (ha ? c.ha_low : c.low))
  )
  const high = Math.max(
    trade.target ?? trade.entry,
    trade.stop ?? trade.entry,
    trade.entry,
    trade.exit ?? trade.entry,
    ...indicators,
    ...data.map((c) => (ha ? c.ha_high : c.high))
  )
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
        {([band, 'bb_middle', 'vwap'] as const).map((field, index) => (
          <polyline
            key={field}
            fill="none"
            stroke={['#a855f7', '#f59e0b', '#06b6d4'][index]}
            strokeWidth="1.5"
            points={data
              .filter((c) => Number.isFinite(c[field]) && (c[field] ?? 0) > 0)
              .map((c) => `${x(c.timestamp)},${y(c[field] as number)}`)
              .join(' ')}
          >
            <title>{field}</title>
          </polyline>
        ))}
        {(
          [
            ['Entry', trade.entry, '#3b82f6'],
            ['Stop', trade.stop, '#ef4444'],
            ['Target', trade.target, '#10b981'],
          ] as const
        ).map(([label, price, color]) =>
          price == null ? null : (
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
          )
        )}
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
      <p className="text-xs text-muted-foreground">
        Purple: BB {short ? 'lower' : 'upper'} · Amber: BB middle · Cyan: VWAP. In trailing variants, Target marks the 3R
        arming level.
      </p>
      <p className="text-sm">
        {trade.symbol} · {trade.quantity} shares · Entry {stamp(trade.entry_ts)} · Exit{' '}
        {stamp(trade.exit_ts)} · {trade.reason} · Net {money(trade.net_pnl)}
      </p>
    </div>
  )
}

export function StrategyReportDetail({
  selected,
  scenario,
  chargeBasis,
}: {
  selected: string
  scenario: string
  chargeBasis: string
}) {
  const [report, setReport] = useState<Report | null>(null)
  const [path, setPath] = useState(scenario)
  const [tradeIndex, setTradeIndex] = useState(0)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!selected) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    const controller = new AbortController()
    setReport(null)
    setPath(scenario)
    setTradeIndex(0)
    async function poll() {
      try {
        const response = await webClient.get(
          `/market-scanner/api/report-journal/${encodeURIComponent(selected)}`,
          { signal: controller.signal, params: { charges: chargeBasis } }
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
  }, [selected, scenario, chargeBasis])
  const trades = report?.trades.filter((t) => t.path === path) ?? []
  const trade = trades[tradeIndex]
  const metrics = report?.metrics[path]
  const labels: [string, string, boolean][] = [
    ['gross_pnl', 'Gross P&L', true],
    ['charges', 'Trading charges', true],
    ['brokerage', 'Brokerage', true],
    ['net_pnl', 'Net P&L', true],
    ['peak_capital', 'Peak entry value (not margin)', true],
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
    <div className="min-w-0 space-y-6">
      {error && <p role="alert">{error}</p>}
      {report && (
        <div className="flex flex-wrap gap-3">
          <select
            aria-label="Detail execution scenario"
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
            <a
              href={`/market-scanner/api/report-journal/${encodeURIComponent(selected)}?download=csv&charges=${chargeBasis}`}
            >
              Download trades CSV
            </a>
          </Button>
        </div>
      )}
      {report && (
        <>
          <p className="rounded border p-3 text-sm text-muted-foreground">{report.note}</p>
          <p>
            Status: {report.status}
            {report.coverage?.length > 0 &&
              ` · ${report.coverage.filter((c) => c.eligible).length}/${report.coverage.length} eligible stock sessions`}
          </p>
          {report.coverage?.some((c) => !c.eligible) && (
            <details className="rounded border p-3 text-sm">
              <summary>Excluded stocks and data issues</summary>
              <ul className="mt-2 list-inside list-disc">
                {report.coverage
                  .filter((c) => !c.eligible)
                  .map((c) => (
                    <li key={c.symbol}>
                      {c.symbol}: {c.reason?.replaceAll('_', ' ') ?? 'Unavailable data'}
                    </li>
                  ))}
              </ul>
            </details>
          )}
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
                    'Brokerage',
                    'Charges',
                    'Fee basis',
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
                      money(t.charge_breakdown?.brokerage),
                      t.charge_status === 'unavailable' ? '—' : money(t.fees),
                      t.charge_status ?? chargeBasis,
                      t.charge_status === 'unavailable' ? '—' : money(t.net_pnl),
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
