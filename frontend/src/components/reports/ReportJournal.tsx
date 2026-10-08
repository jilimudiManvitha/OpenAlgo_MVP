import { CalendarDays, ChevronLeft, ChevronRight, Layers, List, TrendingUp } from 'lucide-react'
import { useEffect, useState } from 'react'
import { webClient } from '@/api/client'
import { Button } from '@/components/ui/button'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { OptionsCapital } from './OptionsCapital'
import { StrategyReportDetail } from './StrategyReportDetail'

export type Metrics = {
  brokerage?: number | null
  charge_breakdown?: Record<string, number>
  unestimated_trades?: number
  open_entry_charges?: number
  gross_pnl: number
  net_pnl: number | null
  charges: number | null
  peak_capital: number
  trades: number
  total_trades: number
  open_trades: number
  entries: number
  wins: number | null
  losses: number | null
  breakeven: number | null
  win_rate: number
}
type ChargeInfo = {
  broker: string
  profile: string | null
  version: string | null
  source: string | null
  broker_inferred: boolean
  unavailable: number
}
type Stock = { symbol: string; metrics: Metrics }
type Strategy = {
  strategy_id: string
  name: string
  metrics: Metrics
  stocks: Stock[]
  reports: { id: string; status: string; note: string; charge_info?: ChargeInfo }[]
}
export type Day = { day: string; metrics: Metrics; strategies: Strategy[]; stocks: Stock[] }
type Journal = {
  charge_basis?: string
  charge_profiles?: ChargeInfo[]
  session_broker?: string
  year: number
  days: Day[]
  totals: Metrics
  streaks: { winning: number; losing: number; current: number }
  strategies: { id: string; name: string }[]
  symbols: string[]
}
const money = (n: number | null | undefined) =>
  n == null ? '—' : `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
const dateLabel = (date: string) =>
  new Date(`${date}T12:00:00`).toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
  })
const tone = (n: number | null) =>
  n == null
    ? ''
    : n > 0
      ? 'text-emerald-600 dark:text-emerald-400'
      : n < 0
        ? 'text-red-600 dark:text-red-400'
        : ''
const input = 'min-w-0 max-w-full rounded-lg border bg-background px-3 py-2 text-sm'

export function FinancialCalendar({
  year,
  days,
  selected,
  onSelect,
}: {
  charge_basis?: string
  charge_profiles?: ChargeInfo[]
  session_broker?: string
  year: number
  days: Day[]
  selected: string
  onSelect: (day: string) => void
}) {
  const byDate = new Map(days.map((day) => [day.day, day]))
  const today = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })
  const max = Math.max(1, ...days.map((d) => Math.abs(d.metrics.net_pnl ?? 0)))
  return (
    <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
      {Array.from({ length: 12 }, (_, index) => {
        const first = new Date(year, index + 3, 1)
        const month = first.getMonth(),
          y = first.getFullYear()
        const count = new Date(y, month + 1, 0).getDate()
        const prefix = `${y}-${String(month + 1).padStart(2, '0')}`
        const monthly = days.filter((d) => d.day.startsWith(prefix))
        const pnl = monthly.some((d) => d.metrics.net_pnl == null)
          ? null
          : monthly.reduce((sum, d) => sum + (d.metrics.net_pnl ?? 0), 0)
        return (
          <section
            key={prefix}
            aria-label={first.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}
            className={`min-w-0 rounded-xl border p-3 ${selected.startsWith(prefix) ? 'border-primary bg-primary/5' : 'border-transparent'}`}
          >
            <div className="mb-3 flex items-center justify-between gap-2">
              <h3 className="font-semibold">
                {first.toLocaleDateString('en-IN', { month: 'long' })}
              </h3>
              {monthly.length > 0 && (
                <span className={`text-xs tabular-nums ${tone(pnl)}`}>{money(pnl)}</span>
              )}
            </div>
            <div className="grid grid-cols-7 gap-1">
              {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((label, i) => (
                <span
                  key={`${label}-${i}`}
                  className="pb-1 text-center text-xs text-muted-foreground"
                >
                  {label}
                </span>
              ))}
              {Array.from({ length: first.getDay() }, (_, i) => (
                <span key={`space-${i}`} />
              ))}
              {Array.from({ length: count }, (_, i) => {
                const date = `${prefix}-${String(i + 1).padStart(2, '0')}`
                const day = byDate.get(date),
                  m = day?.metrics
                const strong = m && Math.abs(m.net_pnl ?? 0) >= max * 0.5
                const color = !day
                  ? 'bg-muted/60 text-muted-foreground'
                  : !m?.trades || m.net_pnl == null
                    ? 'bg-[#ede9fe] text-[#5b21b6]'
                    : m.net_pnl > 0
                      ? strong
                        ? 'bg-emerald-600 text-white'
                        : 'bg-[#d1fae5] text-[#064e3b]'
                      : m.net_pnl < 0
                        ? strong
                          ? 'bg-red-600 text-white'
                          : 'bg-[#fee2e2] text-[#7f1d1d]'
                        : 'bg-[#ede9fe] text-[#5b21b6]'
                const description = `${dateLabel(date)}: ${m ? `${money(m.net_pnl)} net P&L, ${m.trades} closed trades, ${m.wins} wins, ${m.losses} losses` : 'No report'}`
                return (
                  <button
                    key={date}
                    type="button"
                    aria-label={description}
                    aria-pressed={selected === date}
                    title={description}
                    onClick={() => onSelect(date)}
                    className={`aspect-square min-h-7 rounded-md text-xs tabular-nums transition hover:ring-2 hover:ring-primary focus-visible:outline-2 focus-visible:outline-primary ${color} ${selected === date ? 'ring-2 ring-primary' : ''} ${date === today ? 'font-bold underline underline-offset-4' : ''}`}
                  >
                    {String(i + 1).padStart(2, '0')}
                  </button>
                )
              })}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function MetricCards({ m }: { m: Metrics }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
      {[
        ['Net P&L', money(m.net_pnl)],
        ['Gross realized P&L', money(m.gross_pnl)],
        ['Trading charges¹', money(m.charges)],
        ['Brokerage', money(m.brokerage)],
        ['Closed / open trades', `${m.trades} / ${m.open_trades}`],
        ['Wins / losses / flat', `${m.wins ?? '—'} / ${m.losses ?? '—'} / ${m.breakeven ?? '—'}`],
        ['New entries today', String(m.entries)],
        ['Peak entry value', money(m.peak_capital)],
      ].map(([label, value], i) => (
        <div key={label} className="rounded-xl border bg-card p-4">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p
            className={`mt-2 text-lg font-semibold tabular-nums ${i === 0 ? tone(m.net_pnl) : ''}`}
          >
            {value}
          </p>
        </div>
      ))}
    </div>
  )
}
function StockTable({ stocks, onStock }: { stocks: Stock[]; onStock: (stock: string) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr>
            {[
              'Stock / contract',
              'Entries',
              'Closed',
              'Open',
              'Win / loss / flat',
              'Gross P&L',
              'Charges¹',
              'Net P&L',
              'Peak value²',
            ].map((h) => (
              <th
                key={h}
                className="whitespace-nowrap p-3 text-xs font-medium text-muted-foreground"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {stocks.map(({ symbol, metrics: m }) => (
            <tr key={symbol} className="border-t">
              <td className="p-3">
                <button
                  type="button"
                  className="font-medium text-primary underline-offset-4 hover:underline"
                  onClick={() => onStock(symbol)}
                >
                  {symbol}
                </button>
              </td>
              {[
                m.entries,
                m.trades,
                m.open_trades,
                `${m.wins ?? '—'} / ${m.losses ?? '—'} / ${m.breakeven ?? '—'}`,
                money(m.gross_pnl),
                money(m.charges),
                money(m.net_pnl),
                money(m.peak_capital),
              ].map((v, i) => (
                <td
                  key={`${symbol}-${i}`}
                  className={`whitespace-nowrap p-3 tabular-nums ${i === 6 ? tone(m.net_pnl) : ''}`}
                >
                  {v}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!stocks.length && (
        <p className="p-4 text-sm text-muted-foreground">No stock trades recorded.</p>
      )}
    </div>
  )
}

function ChargeBreakdown({ m }: { m: Metrics }) {
  if (!m.charge_breakdown || !Object.keys(m.charge_breakdown).length) return null
  return (
    <details className="rounded-lg border p-3 text-sm">
      <summary className="cursor-pointer">Charges breakdown · closed trades</summary>
      <div className="mt-3 flex flex-wrap gap-4">
        {Object.entries(m.charge_breakdown).map(([key, value]) => (
          <span key={key}>
            {key.toUpperCase()} <strong>{m.unestimated_trades ? '—' : money(value)}</strong>
          </span>
        ))}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Open-position entry costs (excluded from realized net): {money(m.open_entry_charges)}
      </p>
    </details>
  )
}

export default function ReportJournal() {
  const mode = useThemeStore((s) => s.appMode)
  const user = useAuthStore((s) => s.user)
  return (
    <JournalContent
      key={`${user?.username}:${user?.broker}:${mode}`}
      initialScenario={mode === 'analyzer' ? 'PAPER' : 'LIVE'}
    />
  )
}
function JournalContent({ initialScenario }: { initialScenario: string }) {
  const [capitalExpanded, setCapitalExpanded] = useState(false)
  const today = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })
  const [year, setYear] = useState(
    Number(today.slice(0, 4)) - (Number(today.slice(5, 7)) < 4 ? 1 : 0)
  )
  const [chargeBasis, setChargeBasis] = useState('estimated')
  const [scenario, setScenario] = useState(initialScenario)
  const [strategy, setStrategy] = useState('')
  const [symbol, setSymbol] = useState('')
  const [selected, setSelected] = useState(today)
  const [view, setView] = useState<'calendar' | 'list'>('calendar')
  const [data, setData] = useState<Journal | null>(null)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    setData(null)
    setError('')
    setDetail('')
    async function poll() {
      try {
        const response = await webClient.get('/market-scanner/api/report-journal', {
          params: { year, scenario, strategy, symbol, charges: chargeBasis },
          signal: controller.signal,
        })
        if (!stopped) {
          setData(response.data.data)
          setError('')
        }
      } catch {
        if (!stopped)
          setError(
            'Unable to refresh reports. Check your login and connection; any displayed figures may be stale.'
          )
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
  }, [year, scenario, strategy, symbol, chargeBasis])
  const day = data?.days.find((d) => d.day === selected)
  const selectDay = (date: string) => {
    setSelected(date)
    setDetail('')
  }
  const changeYear = (next: number) => {
    setYear(next)
    selectDay(`${next}-04-01`)
  }
  return (
    <div className="min-w-0 space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-widest text-primary">
            Trading journal
          </p>
          <h1 className="text-2xl font-semibold">Strategy Reports</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            One day. Every strategy. Every stock.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant={view === 'calendar' ? 'default' : 'outline'}
            onClick={() => setView('calendar')}
          >
            <CalendarDays className="mr-2 size-4" />
            Calendar
          </Button>
          <Button variant={view === 'list' ? 'default' : 'outline'} onClick={() => setView('list')}>
            <List className="mr-2 size-4" />
            Daily list
          </Button>
        </div>
      </header>
      {scenario === 'PAPER' && (
        <details
          className="rounded-xl border p-3"
          onToggle={(e) => setCapitalExpanded(e.currentTarget.open)}
        >
          <summary className="cursor-pointer font-medium">
            Current options capital &amp; charges
          </summary>
          <div className="mt-3">{capitalExpanded && <OptionsCapital />}</div>
        </details>
      )}
      <div className="flex flex-wrap gap-3">
        <select
          aria-label="Execution scenario"
          className={input}
          value={scenario}
          onChange={(e) => {
            setScenario(e.target.value)
            setStrategy('')
            setSymbol('')
          }}
        >
          <option value="PAPER">Sandbox · recorded sessions</option>
          <option value="LIVE">Live · recorded sessions</option>
          <option value="OLHC">Historical backtest · OLHC</option>
          <option value="OHLC">Historical backtest · OHLC</option>
        </select>
        <select
          aria-label="Strategy filter"
          className={input}
          value={strategy}
          onChange={(e) => setStrategy(e.target.value)}
        >
          <option value="">All strategies</option>
          {data?.strategies.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <select
          aria-label="Stock filter"
          className={input}
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
        >
          <option value="">All stocks / contracts</option>
          {data?.symbols.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select
          aria-label="Charges basis"
          className={input}
          value={chargeBasis}
          onChange={(e) => setChargeBasis(e.target.value)}
        >
          <option value="estimated">Broker estimates · standard retail</option>
          <option value="recorded">Original recorded fees</option>
        </select>
        {(strategy || symbol) && (
          <Button
            variant="ghost"
            onClick={() => {
              setStrategy('')
              setSymbol('')
            }}
          >
            Clear filters
          </Button>
        )}
      </div>
      {error && (
        <p
          role="alert"
          className="rounded-lg border border-destructive p-3 text-sm text-destructive"
        >
          {error}
        </p>
      )}
      {chargeBasis === 'estimated' && (
        <div className="rounded-xl border bg-muted/30 p-4 text-sm space-y-2">
          <p>
            Broker estimates · logged in with{' '}
            <strong>{data?.session_broker?.toUpperCase() || 'broker unavailable'}</strong>.
            Confirmed actual fees, when provided, take precedence.
          </p>
          <p className="text-xs text-muted-foreground">
            Net P&L, wins/losses and calendar streaks include estimated trading costs. Open-entry
            costs are shown separately; round-trip costs enter realized P&L when a trade closes.
          </p>
          {data?.charge_profiles?.map((p, i) => (
            <p key={`${p.broker}-${i}`} className="text-xs">
              <strong>{p.broker.toUpperCase() || 'Unknown broker'}</strong> ·{' '}
              {p.profile || 'Standard tariff unavailable'}
              {p.source && (
                <>
                  {' '}
                  ·{' '}
                  <a className="underline" href={p.source} target="_blank" rel="noreferrer">
                    Published tariff
                  </a>
                </>
              )}
              {p.broker_inferred && ' · Historical broker was not saved; current login is assumed.'}
              {p.unavailable > 0 &&
                ' · Some trades lack a supported tariff or execution details; their estimated net is unavailable.'}
            </p>
          ))}
        </div>
      )}
      <section className="rounded-2xl border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b p-4 md:p-6">
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-bold">
              {year}–{year + 1}
            </h2>
            <Button
              variant="outline"
              size="icon"
              aria-label="Previous financial year"
              disabled={year <= 2000}
              onClick={() => changeYear(year - 1)}
            >
              <ChevronLeft className="size-4" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              aria-label="Next financial year"
              disabled={year >= 2100}
              onClick={() => changeYear(year + 1)}
            >
              <ChevronRight className="size-4" />
            </Button>
          </div>
          {data && (
            <div className="flex flex-wrap gap-4 text-sm">
              <span>
                FY net{' '}
                <strong className={tone(data.totals.net_pnl)}>{money(data.totals.net_pnl)}</strong>
              </span>
              <span>{data.totals.trades} closed trades</span>
            </div>
          )}
        </div>
        <div className="p-3 md:p-5">
          {!data ? (
            <output className="block p-6">
              {error ? 'Reports unavailable.' : 'Loading journal…'}
            </output>
          ) : view === 'calendar' ? (
            <FinancialCalendar
              year={year}
              days={data.days}
              selected={selected}
              onSelect={selectDay}
            />
          ) : (
            <div className="space-y-2">
              {data.days.map((d) => (
                <button
                  key={d.day}
                  type="button"
                  onClick={() => selectDay(d.day)}
                  aria-pressed={selected === d.day}
                  className={`flex w-full flex-wrap items-center justify-between gap-3 rounded-xl border p-4 text-left ${selected === d.day ? 'border-primary bg-primary/5' : ''}`}
                >
                  <span className="font-medium">{dateLabel(d.day)}</span>
                  <span className="text-sm text-muted-foreground">
                    {d.strategies.length} strategies · {d.metrics.trades} closed · {d.metrics.wins}{' '}
                    wins / {d.metrics.losses} losses
                  </span>
                  <strong className={tone(d.metrics.net_pnl)}>{money(d.metrics.net_pnl)}</strong>
                </button>
              ))}
              {!data.days.length && (
                <p className="p-4">No reports for these filters in this financial year.</p>
              )}
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-4 border-t p-4 text-xs text-muted-foreground">
          <span>🟩 Profit</span>
          <span>🟥 Loss</span>
          <span>🟪 Flat / no closed trades</span>
          <span>Gray: no report</span>
          <span>Click a day to inspect it · Underlined: today</span>
        </div>
      </section>
      {data && (
        <div className="flex flex-wrap items-center gap-5 rounded-xl border bg-card p-4 text-sm">
          <TrendingUp className="size-5 text-primary" />
          <span>
            Longest winning streak <strong>{data.streaks.winning} days</strong>
          </span>
          <span>
            Longest losing streak <strong>{data.streaks.losing} days</strong>
          </span>
          <span>
            Latest streak{' '}
            <strong>
              {Math.abs(data.streaks.current)}{' '}
              {data.streaks.current < 0 ? 'losing' : data.streaks.current > 0 ? 'winning' : 'flat'}{' '}
              days
            </strong>
          </span>
          <p className="w-full text-xs text-muted-foreground">
            Selected financial year and filters. Streaks use recorded days with closed trades;
            no-trade days are skipped, breakeven breaks the streak.
          </p>
        </div>
      )}
      <section className="space-y-4" aria-label="Selected daily report">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">{dateLabel(selected)}</h2>
            <p className="text-sm text-muted-foreground">
              {day
                ? `${day.strategies.length} strategies · Combined daily performance`
                : 'No report for this date and filters.'}
            </p>
          </div>
          <input
            type="date"
            aria-label="Trading date"
            className={input}
            value={selected}
            min={`${year}-04-01`}
            max={`${year + 1}-03-31`}
            onChange={(e) => {
              if (e.target.value) selectDay(e.target.value)
            }}
          />
        </div>
        {day && (
          <>
            <MetricCards m={day.metrics} />
            {!!day.metrics.unestimated_trades && (
              <p role="alert" className="text-sm text-amber-600">
                Estimated net unavailable: {day.metrics.unestimated_trades} closed trades need
                broker/instrument data or a supported tariff.
              </p>
            )}
            <ChargeBreakdown m={day.metrics} />
            <details className="rounded-xl border bg-card">
              <summary className="cursor-pointer p-4 font-medium">
                Stocks across all selected strategies ({day.stocks.length})
              </summary>
              <StockTable
                stocks={day.stocks}
                onStock={(stock) => {
                  setSymbol(stock)
                  setView('calendar')
                }}
              />
            </details>
            <div className="space-y-3">
              {day.strategies.map((s) => (
                <details key={`${selected}-${s.strategy_id}`} className="rounded-xl border bg-card">
                  <summary className="flex cursor-pointer flex-wrap items-center gap-3 p-4">
                    <Layers className="size-4 text-primary" />
                    <span className="flex-1 font-medium">{s.name}</span>
                    <span className="text-sm text-muted-foreground">
                      {s.metrics.trades} closed · {s.metrics.wins ?? '—'}W /{' '}
                      {s.metrics.losses ?? '—'}L
                    </span>
                    <strong className={tone(s.metrics.net_pnl)}>{money(s.metrics.net_pnl)}</strong>
                  </summary>
                  <div className="space-y-4 border-t p-4">
                    <MetricCards m={s.metrics} />
                    <ChargeBreakdown m={s.metrics} />
                    <div className="flex flex-wrap items-center gap-3">
                      <Button
                        variant="outline"
                        onClick={() => {
                          setStrategy(s.strategy_id)
                          setView('calendar')
                        }}
                      >
                        View strategy calendar
                      </Button>
                      <span className="text-xs text-muted-foreground">
                        Click a stock below for its calendar.
                      </span>
                    </div>
                    <StockTable
                      stocks={s.stocks}
                      onStock={(stock) => {
                        setStrategy(s.strategy_id)
                        setSymbol(stock)
                        setView('calendar')
                      }}
                    />
                    {s.reports.map((r) => (
                      <div key={r.id} className="space-y-2 rounded-lg bg-muted/40 p-3">
                        <p className="text-sm">Status: {r.status}</p>
                        <p className="text-xs text-muted-foreground">{r.note}</p>
                        <Button
                          variant="outline"
                          onClick={() => setDetail(detail === r.id ? '' : r.id)}
                        >
                          {detail === r.id ? 'Hide' : 'Open'} individual trades & charts
                        </Button>
                        {detail === r.id && (
                          <StrategyReportDetail
                            selected={r.id}
                            scenario={scenario}
                            chargeBasis={chargeBasis}
                          />
                        )}
                      </div>
                    ))}
                  </div>
                </details>
              ))}
            </div>
          </>
        )}
      </section>
      <p className="rounded-xl border bg-muted/30 p-4 text-xs leading-relaxed text-muted-foreground">
        ¹ Estimated trading charges include brokerage, STT, GST, exchange, SEBI, stamp duty, IPFT
        and any listed clearing fee for supported NSE/NFO trades. Excludes DP, exercise/assignment,
        physical settlement, auto-square-off, financing and account fees. Estimates may differ from
        contract-note rounding. Original recorded fees remain available in the selector. ² Capital
        is peak entry value, not broker margin. Options count legs. Unrealized P&L is excluded.
      </p>
    </div>
  )
}
