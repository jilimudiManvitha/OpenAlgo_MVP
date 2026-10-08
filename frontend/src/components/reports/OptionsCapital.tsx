import { useCallback, useEffect, useRef, useState } from 'react'
import { webClient } from '@/api/client'
import { Button } from '@/components/ui/button'
import { useAuthStore } from '@/stores/authStore'

type Quote = {
  quoted_at: string
  margin_total: number
  margin_new_order: number
  sizing_requirement: number
  fingerprint?: string
}
type Leg = { symbol: string; side: number; quantity: number; lot_size: number; entry: number }
type Strategy = {
  strategy_id: string
  name: string
  allocation: number
  deployable_budget: number
  updated_at: string | null
  pending: boolean
  halted: boolean
  unprotected_shorts: number
  legs: Leg[]
  entry_snapshot: null | {
    lots_per_leg: number
    basket: Quote
    one_lot: Quote
    utilization_pct: number
  }
  charges: {
    total: number | null
    breakdown: Record<string, number>
    scope: string
    source: string | null
  }
}
type Capital = {
  allocation: number
  deployable_budget: number
  fingerprint: string
  strategies: Strategy[]
}
const url = '/market-scanner/api/options-capital'
const money = (value: number | null | undefined) =>
  value == null ? 'Unavailable' : `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
const stamp = (value: string) =>
  new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })
const failure = (error: unknown) =>
  (error as { response?: { data?: { message?: string } } })?.response?.data?.message ||
  'Unable to load capital. Check your connection and retry.'

function MarginQuote({ quote, allocation }: { quote: Quote; allocation: number }) {
  return (
    <dl className="grid gap-1 text-sm">
      <div>
        Basket requirement: <strong>{money(quote.margin_total)}</strong>
      </div>
      <div>Including existing positions: {money(quote.margin_new_order)}</div>
      <div>
        Conservative sizing amount: {money(quote.sizing_requirement)} ·{' '}
        {((100 * quote.sizing_requirement) / allocation).toFixed(1)}% of allocation
      </div>
      <div className="text-xs text-muted-foreground">Quoted {stamp(quote.quoted_at)} IST</div>
    </dl>
  )
}

export function OptionsCapital() {
  const user = useAuthStore((s) => s.user)
  return <CapitalPanel key={`${user?.username}:${user?.broker}`} broker={user?.broker} />
}

function CapitalPanel({ broker }: { broker?: string | null }) {
  const [data, setData] = useState<Capital | null>(null)
  const [quotes, setQuotes] = useState<Record<string, Quote>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const controller = useRef<AbortController | null>(null)
  const load = useCallback(async () => {
    controller.current?.abort()
    const request = new AbortController()
    controller.current = request
    setBusy('reload')
    setError('')
    setQuotes({})
    setData(null)
    try {
      const response = await webClient.get<{ data: Capital }>(url, { signal: request.signal })
      if (!request.signal.aborted) setData(response.data.data)
    } catch (err) {
      if (!request.signal.aborted) setError(failure(err))
    } finally {
      if (!request.signal.aborted) setBusy(null)
    }
  }, [])
  useEffect(() => {
    void load()
    return () => controller.current?.abort()
  }, [load])
  const quote = async (id: string) => {
    if (!data || busy) return
    const request = new AbortController()
    controller.current = request
    setBusy(id)
    setError('')
    setQuotes((old) => {
      const next = { ...old }
      delete next[id]
      return next
    })
    try {
      const response = await webClient.post<{ data: Quote }>(
        `${url}/quote`,
        {
          strategy_id: id,
          fingerprint: data.fingerprint,
        },
        { signal: request.signal }
      )
      if (!request.signal.aborted && response.data.data.fingerprint === data.fingerprint) {
        setQuotes((old) => ({ ...old, [id]: response.data.data }))
      }
    } catch (err) {
      if (!request.signal.aborted) setError(failure(err))
    } finally {
      if (!request.signal.aborted) setBusy(null)
    }
  }
  const active = data?.strategies.some((s) => s.legs.length)
  return (
    <section
      aria-label="Options capital and charges"
      className="min-w-0 rounded-xl border bg-card p-4 sm:p-6 space-y-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Options capital &amp; charges</h2>
          <p className="text-sm text-muted-foreground">
            Scheduled Sandbox strategies · saved positions · FYERS margin
          </p>
        </div>
        <Button variant="outline" onClick={() => void load()} disabled={!!busy}>
          Reload positions
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        Allocation is a strategy budget. Sandbox blocked funds use option premiums; FYERS margin
        reflects the complete basket and its hedges. Quotes are estimates at the displayed time, not
        reserved funds.
      </p>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {busy === 'reload' && <output>Loading saved baskets…</output>}
      {data && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg bg-muted/50 p-3">
              <p className="text-xs text-muted-foreground">
                {data.strategies.length} strategy allocations
              </p>
              <p className="text-xl font-semibold">{money(data.allocation)}</p>
            </div>
            <div className="rounded-lg bg-muted/50 p-3">
              <p className="text-xs text-muted-foreground">Deployable budget · 10% reserve</p>
              <p className="text-xl font-semibold">{money(data.deployable_budget)}</p>
            </div>
            <div className="rounded-lg bg-muted/50 p-3">
              <p className="text-xs text-muted-foreground">Open strategy baskets</p>
              <p className="text-xl font-semibold">
                {data.strategies.filter((s) => s.legs.length).length}
              </p>
            </div>
          </div>
          <div className="rounded-lg border p-3 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="font-medium">Combined net basket</h3>
              <Button
                size="sm"
                disabled={
                  !!busy || !active || broker !== 'fyers' || data.strategies.some((s) => s.pending)
                }
                onClick={() => void quote('combined')}
              >
                {busy === 'combined' ? 'Quoting…' : 'Get combined FYERS margin'}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Identical contracts are netted across strategies. Do not add account-inclusive
              strategy quotes together; they can include existing broker positions.
            </p>
            {quotes.combined && (
              <MarginQuote quote={quotes.combined} allocation={data.allocation} />
            )}
            {broker !== 'fyers' && (
              <p className="text-sm">Log in with FYERS to request current margin.</p>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="p-2">Strategy / basket</th>
                  <th className="p-2">Budget</th>
                  <th className="p-2">Entry sizing</th>
                  <th className="p-2">Cycle charges</th>
                  <th className="p-2">Current margin</th>
                </tr>
              </thead>
              <tbody>
                {data.strategies.map((s) => (
                  <tr key={s.strategy_id} className="border-b align-top">
                    <td className="p-2 min-w-48">
                      <p className="font-medium">{s.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {s.legs.length} open legs{s.pending ? ' · Pending orders' : ''}
                        {s.halted ? ' · Halted' : ''}
                      </p>
                      {s.unprotected_shorts > 0 && (
                        <p className="text-xs text-destructive">
                          {s.unprotected_shorts} short legs need hedge reconciliation
                        </p>
                      )}
                      <details className="mt-2">
                        <summary className="cursor-pointer">Saved quantities</summary>
                        <ul className="space-y-1 mt-2">
                          {s.legs.map((leg, i) => (
                            <li key={`${leg.symbol}:${i}`} className="text-xs">
                              {leg.side > 0 ? 'BUY' : 'SELL'} {leg.symbol} · {leg.quantity} qty /{' '}
                              {leg.quantity / leg.lot_size} lots
                            </li>
                          ))}
                        </ul>
                        <p className="text-xs text-muted-foreground mt-2">
                          Updated {s.updated_at ? `${stamp(s.updated_at)} IST` : 'Never started'}
                        </p>
                      </details>
                    </td>
                    <td className="p-2 whitespace-nowrap">
                      {money(s.allocation)}
                      <p className="text-xs text-muted-foreground">
                        Deploy {money(s.deployable_budget)}
                      </p>
                    </td>
                    <td className="p-2 min-w-48">
                      {s.entry_snapshot ? (
                        <details>
                          <summary className="cursor-pointer">
                            {s.entry_snapshot.lots_per_leg} lots / leg ·{' '}
                            {money(s.entry_snapshot.basket.sizing_requirement)}
                          </summary>
                          <MarginQuote quote={s.entry_snapshot.basket} allocation={s.allocation} />
                          <p className="text-xs mt-2">
                            One-lot sizing margin:{' '}
                            {money(s.entry_snapshot.one_lot.sizing_requirement)}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            Entry-time snapshot; adjustments can change the current basket.
                          </p>
                        </details>
                      ) : (
                        <span className="text-muted-foreground">No saved entry quote</span>
                      )}
                    </td>
                    <td className="p-2 min-w-36">
                      <details>
                        <summary className="cursor-pointer">
                          {money(s.charges.total)}
                          <span className="block text-xs text-muted-foreground">
                            Estimated · confirmed fills
                          </span>
                        </summary>
                        <p className="text-xs my-2">{s.charges.scope}</p>
                        {Object.entries(s.charges.breakdown).map(([key, value]) => (
                          <div key={key} className="flex justify-between gap-3 text-xs">
                            <span className="uppercase">{key}</span>
                            <span>{money(value)}</span>
                          </div>
                        ))}
                        {s.charges.source && (
                          <a
                            className="text-xs underline"
                            href={s.charges.source}
                            target="_blank"
                            rel="noreferrer"
                          >
                            FYERS tariff
                          </a>
                        )}
                      </details>
                    </td>
                    <td className="p-2 min-w-52">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!!busy || !s.legs.length || s.pending || broker !== 'fyers'}
                        onClick={() => void quote(s.strategy_id)}
                      >
                        {busy === s.strategy_id ? 'Quoting…' : 'Get FYERS margin'}
                      </Button>
                      {quotes[s.strategy_id] && (
                        <div className="mt-2">
                          <MarginQuote quote={quotes[s.strategy_id]} allocation={s.allocation} />
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted-foreground">
            Charges include brokerage, STT, exchange, SEBI, stamp duty, IPFT, clearing and GST.
            Estimates cover this cycle’s confirmed entries and exits; future exit costs are
            excluded. Margin API responses do not provide actual billed charges.
          </p>
        </>
      )}
    </section>
  )
}
