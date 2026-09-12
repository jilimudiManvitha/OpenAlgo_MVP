import { useEffect, useState } from 'react'
import { webClient } from '@/api/client'
import { Button } from '@/components/ui/button'
import { useAuthStore } from '@/stores/authStore'

type Point = [string, number]
type Row = {
  symbol: string
  name: string
  exchange: string
  ltp: number
  previous_close: number
  change_percent: number
  volume: number | null
  volume_change_percent: number | null
  rvol: number | null
  stale: boolean
  last_trade_at: string
  quote_fetched_at: string
  sparkline?: Point[]
  baseline_status: string
}
type Tab = 'volume_shockers' | 'top_gainers' | 'top_losers'
type Category = { id: string; label: string; effective_date: string | null; source: string }
type Snapshot = Record<Tab, Row[]> & {
  enabled: boolean
  broker: string
  categories: Category[]
  matching_counts: Record<Tab, number>
  options: { lookback_days: number }
  stale: boolean
  market_open: boolean
  updated_at?: string
  state?: string
  phase?: string
  error?: string
  valid_quotes?: number
  total?: number
  valid_baselines?: number
  partial?: boolean
  baselines_processed?: number
  baseline_total?: number
  filtered_quotes: number
  timestamp_support: string
  transport?: string
  streaming_symbols?: number
  membership?: Category
}

const names: Record<Tab, string> = {
  volume_shockers: 'Volume Shockers',
  top_gainers: 'Top Gainers',
  top_losers: 'Top Losers',
}
const number = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 })
const time = (v?: string) =>
  v ? `${new Date(v).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' })} IST` : 'Waiting'
export const percent = (value: number | null) =>
  value == null || !Number.isFinite(value) ? 'N/A' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
const tone = (value: number) =>
  value > 0
    ? 'text-emerald-600 dark:text-emerald-400'
    : value < 0
      ? 'text-red-600 dark:text-red-400'
      : 'text-muted-foreground'

export function PriceSparkline({
  points = [],
  change,
  symbol,
}: {
  points?: Point[]
  change: number
  symbol: string
}) {
  if (points.length < 2)
    return <span className="text-xs text-muted-foreground">Collecting prices…</span>
  const low = Math.min(...points.map((p) => p[1])),
    high = Math.max(...points.map((p) => p[1]))
  const start = Date.parse(points[0][0]),
    end = Date.parse(points[points.length - 1][0])
  // Split disconnected observations instead of drawing across missing periods.
  const groups: string[][] = [[]]
  points.forEach((p, i) => {
    if (i && Date.parse(p[0]) - Date.parse(points[i - 1][0]) > 180000) groups.push([])
    const x = 2 + ((Date.parse(p[0]) - start) / Math.max(1, end - start)) * 116
    const y = high === low ? 18 : 33 - ((p[1] - low) / (high - low)) * 30
    groups[groups.length - 1].push(`${x},${y}`)
  })
  return (
    <svg
      role="img"
      aria-label={`${symbol} observed prices since connected, ${time(points[0][0])} to ${time(points[points.length - 1][0])}`}
      viewBox="0 0 120 36"
      className={`h-9 w-28 ${tone(change)}`}
    >
      <title>{`Price since connected · ${time(points[0][0])}–${time(points[points.length - 1][0])}`}</title>
      {groups.map((g) => (
        <polyline
          key={g[0]}
          points={g.join(' ')}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      ))}
    </svg>
  )
}

export default function MarketScanner() {
  const user = useAuthStore((s) => s.user)
  const preferenceKey = `scanner:${user?.username ?? 'session'}:${user?.broker}`
  const [tab, setTab] = useState<Tab>('volume_shockers')
  const [category, setCategory] = useState('all')
  const [search, setSearch] = useState('')
  const [minRvol, setMinRvol] = useState('1')
  const [minPrice, setMinPrice] = useState('0')
  const [maxPrice, setMaxPrice] = useState('1000000000')
  const [minVolume, setMinVolume] = useState('0')
  const [loadedFor, setLoadedFor] = useState('')
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const [clock, setClock] = useState(Date.now())
  useEffect(() => {
    try {
      const saved = localStorage.getItem(preferenceKey)
      const preferences = saved?.startsWith('{') ? JSON.parse(saved) : { category: saved || 'all' }
      setCategory(preferences.category || 'all')
      setMinRvol(preferences.minRvol ?? '1')
      setMinPrice(preferences.minPrice ?? '0')
      setMaxPrice(preferences.maxPrice ?? '1000000000')
      setMinVolume(preferences.minVolume ?? '0')
    } catch {
      setCategory('all')
    }
    setLoadedFor(preferenceKey)
    setSnapshot(null)
  }, [preferenceKey])
  useEffect(() => {
    if (loadedFor !== preferenceKey) return
    try {
      localStorage.setItem(
        preferenceKey,
        JSON.stringify({ category, minRvol, minPrice, maxPrice, minVolume })
      )
    } catch {
      /* optional browser storage */
    }
  }, [loadedFor, preferenceKey, category, minRvol, minPrice, maxPrice, minVolume])
  // biome-ignore lint/correctness/useExhaustiveDependencies: Account changes and explicit controls must abort/restart polling.
  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    const controller = new AbortController()
    async function poll() {
      try {
        const params = {
          category,
          limit: 50,
          min_rvol: Number(minRvol) || 0,
          min_price: Number(minPrice) || 0,
          max_price: Number(maxPrice),
          min_volume: Number(minVolume) || 0,
        }
        const response = await webClient.get('/market-scanner/api/live', {
          params,
          signal: controller.signal,
        })
        if (!stopped) {
          setSnapshot(response.data.data)
          setError('')
          setClock(Date.now())
        }
      } catch (e) {
        if (!stopped) setError(e instanceof Error ? e.message : 'Scanner connection interrupted')
      } finally {
        if (!stopped) timer = setTimeout(poll, 5000)
      }
    }
    void poll()
    return () => {
      stopped = true
      clearTimeout(timer)
      controller.abort()
    }
  }, [category, minRvol, minPrice, maxPrice, minVolume, revision, preferenceKey])
  useEffect(() => {
    const id = setInterval(() => setClock(Date.now()), 5000)
    return () => clearInterval(id)
  }, [])
  async function control(payload: object) {
    setBusy(true)
    try {
      await webClient.post('/market-scanner/api/live', payload)
      setRevision((v) => v + 1)
    } catch {
      setError('Could not update scanner settings. Check your session and retry.')
    } finally {
      setBusy(false)
    }
  }
  const rows = (snapshot?.[tab] ?? []).filter((r) =>
    `${r.symbol} ${r.name}`.toLowerCase().includes(search.toLowerCase())
  )
  const old = snapshot?.updated_at ? clock - Date.parse(snapshot.updated_at) > 120000 : true
  const status = error
    ? 'Connection interrupted'
    : !snapshot
      ? 'Connecting'
      : !snapshot.enabled
        ? 'Paused'
        : !snapshot.market_open
          ? 'Market closed · latest available snapshot'
          : snapshot.stale || old
            ? 'Waiting for fresh quotes'
            : snapshot.transport === 'shared_websocket_and_polling'
              ? `Live quotes · ${snapshot.streaming_symbols ?? 0} streaming · polling covers remaining stocks`
              : 'Auto refresh · 60s scan cycle'
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Market Scanner</h1>
          <p className="text-muted-foreground">NSE stocks · Today’s price and volume changes</p>
        </div>
        <Button
          disabled={busy || !snapshot}
          variant="outline"
          onClick={() => void control({ enabled: !snapshot?.enabled })}
        >
          {snapshot?.enabled ? 'Pause auto refresh' : 'Resume auto refresh'}
        </Button>
      </div>
      <section
        aria-label="Scanner status"
        aria-live="polite"
        className="rounded-lg border bg-card p-4 text-sm"
      >
        <p className="font-medium">{status}</p>
        <p className="text-muted-foreground">
          Updated {time(snapshot?.updated_at)} · Broker: {snapshot?.broker || user?.broker} ·{' '}
          {snapshot?.valid_quotes ?? 0}/{snapshot?.total ?? 0} valid quotes ·{' '}
          {snapshot?.valid_baselines ?? 0} volume baselines
        </p>
        {snapshot?.state === 'running' && (
          <p>
            Scanning: {snapshot.phase} · Baselines {snapshot.baselines_processed}/
            {snapshot.baseline_total}
          </p>
        )}
        {snapshot?.partial && (
          <p>
            Partial coverage: unavailable or stale quotes and missing baselines are excluded where
            required.
          </p>
        )}
        {snapshot?.timestamp_support === 'provider dependent' && (
          <p>
            This broker must supply trade timestamps; quotes without a verifiable session time are
            excluded.
          </p>
        )}
      </section>
      {(error || snapshot?.error) && (
        <p role="alert" className="rounded-lg border border-destructive p-3 text-destructive">
          {snapshot?.error || error}
        </p>
      )}
      <div className="flex flex-wrap gap-4 items-end">
        <label className="grid gap-1 text-sm">
          Category
          <select
            aria-label="Category"
            className="h-10 rounded-md border bg-background px-3"
            value={category}
            onChange={(e) => {
              setCategory(e.target.value)
            }}
          >
            <option value="all">All stocks</option>
            {snapshot?.categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm">
          Volume baseline
          <select
            className="h-10 rounded-md border bg-background px-3"
            value={snapshot?.options.lookback_days ?? 5}
            disabled={busy}
            onChange={(e) =>
              void control({ options: { lookback_days: Number(e.target.value), limit: 50 } })
            }
          >
            <option value={1}>Previous completed session</option>
            <option value={5}>5-session average</option>
            <option value={20}>20-session average</option>
          </select>
        </label>
        {[
          ['Minimum RVOL', minRvol, setMinRvol],
          ['Minimum price', minPrice, setMinPrice],
          ['Maximum price', maxPrice, setMaxPrice],
          ['Minimum volume', minVolume, setMinVolume],
        ].map(([label, value, set]) => (
          <label className="grid gap-1 text-sm" key={label as string}>
            {label as string}
            <input
              type="number"
              min="0"
              step="any"
              className="h-10 w-32 rounded-md border bg-background px-3"
              value={value as string}
              onChange={(e) => (set as (v: string) => void)(e.target.value)}
            />
          </label>
        ))}
      </div>
      {category !== 'all' && (
        <p className="text-xs text-muted-foreground">
          Membership: {snapshot?.membership?.effective_date || 'date unknown'} · Source:{' '}
          {snapshot?.membership?.source}
          <button
            type="button"
            className="ml-3 underline"
            onClick={() => {
              void webClient
                .post('/market-scanner/api/categories/refresh', {})
                .then(() => setRevision((v) => v + 1))
                .catch(() => setError('Membership refresh failed'))
            }}
          >
            Reimport local lists
          </button>
        </p>
      )}
      <div
        role="tablist"
        aria-label="Scanner rankings"
        className="flex flex-wrap gap-2"
        onKeyDown={(e) => {
          const keys = Object.keys(names) as Tab[]
          let index = keys.indexOf(tab)
          if (e.key === 'ArrowRight') index = (index + 1) % keys.length
          else if (e.key === 'ArrowLeft') index = (index + keys.length - 1) % keys.length
          else if (e.key === 'Home') index = 0
          else if (e.key === 'End') index = keys.length - 1
          else return
          e.preventDefault()
          setTab(keys[index])
          document.getElementById(`scanner-tab-${keys[index]}`)?.focus()
        }}
      >
        {(Object.keys(names) as Tab[]).map((t) => (
          <Button
            key={t}
            role="tab"
            id={`scanner-tab-${t}`}
            aria-controls="scanner-results"
            tabIndex={tab === t ? 0 : -1}
            aria-selected={tab === t}
            variant={tab === t ? 'default' : 'outline'}
            onClick={() => setTab(t)}
          >
            {names[t]} ({snapshot?.matching_counts[t] ?? 0})
          </Button>
        ))}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <p>
          Showing {rows.length} of the top 50 · {snapshot?.filtered_quotes ?? 0} eligible quotes in
          category
        </p>
        <input
          aria-label="Search displayed stocks"
          placeholder="Search displayed stocks…"
          className="h-10 rounded-md border bg-background px-3"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <div
        id="scanner-results"
        className="overflow-auto rounded-lg border"
        role="tabpanel"
        aria-labelledby={`scanner-tab-${tab}`}
      >
        <table className="w-full text-sm tabular-nums">
          <thead className="bg-muted text-left">
            <tr>
              {[
                'Stock',
                'Price since connected',
                'LTP',
                'Day change %',
                'Today’s volume',
                `Volume change vs ${snapshot?.options.lookback_days ?? 5}-session average`,
                'RVOL',
                'Last trade (IST)',
              ].map((h) => (
                <th className="whitespace-nowrap px-4 py-3 font-medium" key={h}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.exchange}:${r.symbol}`} className="border-t hover:bg-muted/40">
                <td className="px-4 py-3">
                  <div className="font-semibold">{r.symbol}</div>
                  <div className="max-w-52 truncate text-xs text-muted-foreground" title={r.name}>
                    {r.name}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <PriceSparkline
                    symbol={r.symbol}
                    points={r.sparkline}
                    change={r.change_percent}
                  />
                </td>
                <td className="px-4 py-3">₹{number.format(r.ltp)}</td>
                <td
                  className={`px-4 py-3 font-semibold ${tone(r.change_percent)}`}
                  title={`Previous session close: ₹${number.format(r.previous_close)}`}
                >
                  {percent(r.change_percent)}
                </td>
                <td className="px-4 py-3">{r.volume == null ? 'N/A' : number.format(r.volume)}</td>
                <td
                  className="px-4 py-3"
                  title="Today’s cumulative volume compared with prior completed full-session volume; not time-adjusted."
                >
                  {percent(r.volume_change_percent)}
                </td>
                <td className="px-4 py-3" title={r.baseline_status}>
                  {r.rvol == null ? 'N/A' : `${r.rvol.toFixed(2)}x`}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-xs">
                  {time(r.last_trade_at)}
                  {(r.stale || clock - Date.parse(r.quote_fetched_at) > 120000 || error) && (
                    <span className="ml-2 text-amber-600">Stale</span>
                  )}
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={8} className="p-10 text-center text-muted-foreground">
                  {snapshot?.stale
                    ? 'Waiting for today’s valid quotes.'
                    : 'No stocks match these filters.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Day change uses the previous trading session’s close. Volume change uses prior full
        sessions. Price lines show observed quotes only; gaps are preserved. Rankings refresh after
        each complete universe quote pass.
      </p>
    </div>
  )
}
