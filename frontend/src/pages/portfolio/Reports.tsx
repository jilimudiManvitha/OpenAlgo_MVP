import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { investmentApi, investmentError, investmentScope } from '@/api/investment'
import { ErrorMessage, Field, money, selectClass } from '@/components/investment/common'
import { Button } from '@/components/ui/button'
import { useInvestmentContext } from './PortfolioIndex'

const reports = {
  transactions: 'Transaction History',
  dividends: 'Dividend Report',
  'corporate-actions': 'Corporate Action',
  performance: 'Performance Report',
  holdings: 'Holding Report',
  'capital-gains': 'Capital Gain Report',
  'profit-loss': 'Profit & Loss Statement',
  calendar: 'Transaction Calendar',
  consolidated: 'Consolidated Holding',
}

export default function Reports() {
  const { accountId } = useInvestmentContext()
  const [name, setName] = useState('holdings')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const params = { account_id: accountId, start: start || undefined, end: end || undefined }
  const query = useQuery({
    queryKey: ['investment', 'report', name, params],
    queryFn: () => investmentApi.report(name, params),
  })
  const search = new URLSearchParams({
    download: 'csv',
    ...(accountId ? { account_id: String(accountId) } : {}),
    ...(start ? { start } : {}),
    ...(end ? { end } : {}),
    ...investmentScope(),
  })
  const points =
    name === 'performance'
      ? (query.data?.rows.map((row) => ({
          date: String(row.date),
          value: row.market_value == null ? null : Number(row.market_value),
        })) ?? [])
      : []
  const values = points.flatMap((p) => (p.value == null ? [] : [p.value]))
  const min = Math.min(0, ...values),
    max = Math.max(1, ...values)
  const firstTime = Date.parse(points[0]?.date ?? '')
  const span = Math.max(1, Date.parse(points.at(-1)?.date ?? '') - firstTime)
  let penDown = false
  const curve = points
    .map((p) => {
      if (p.value == null) {
        penDown = false
        return ''
      }
      const command = penDown ? 'L' : 'M'
      penDown = true
      return `${command}${40 + ((Date.parse(p.date) - firstTime) * 720) / span},${220 - ((p.value - min) / (max - min)) * 180}`
    })
    .join(' ')
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Portfolio reports</h2>
      <div className="flex flex-wrap gap-3 items-end">
        <label className="text-sm">
          Report
          <select
            aria-label="Portfolio report"
            className={selectClass}
            value={name}
            onChange={(e) => setName(e.target.value)}
          >
            {Object.entries(reports).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <Field label="From date" type="date" value={start} onChange={setStart} required={false} />
        <Field label="To date" type="date" value={end} onChange={setEnd} required={false} />
        <Button asChild variant="outline">
          <a href={`/investments/api/reports/${name}?${search}`}>Download CSV</a>
        </Button>
      </div>
      {query.isPending ? (
        <p>Loading report…</p>
      ) : query.isError ? (
        <ErrorMessage>{investmentError(query.error)}</ErrorMessage>
      ) : (
        <>
          <p className="rounded border p-3 text-sm text-muted-foreground">
            {query.data.method} Period: {query.data.start} to {query.data.end}.
          </p>
          {name === 'performance' && points.length > 1 && (
            <section className="rounded border p-4">
              <h3 className="font-medium">Recorded net-worth curve</h3>
              <svg
                viewBox="0 0 800 260"
                role="img"
                aria-label="Recorded portfolio value by date"
                className="w-full"
              >
                <title>Recorded valuations, not live market returns</title>
                <path fill="none" stroke="currentColor" strokeWidth="2" d={curve} />
                <text x="5" y="20" fontSize="12">
                  {money(max)}
                </text>
                <text x="5" y="245" fontSize="12">
                  {points[0]?.date} — {points.at(-1)?.date}
                </text>
              </svg>
              <p className="text-xs text-muted-foreground">
                Gaps indicate missing valuations. Values include recorded deposits and withdrawals.
              </p>
            </section>
          )}
          {name === 'calendar' && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {query.data.rows.map((r, i) => (
                <div key={`${r.date}-${r.action}-${i}`} className="rounded border p-3 text-sm">
                  <strong>{r.date}</strong>
                  <p>
                    {r.action} · {r.transactions} entries
                  </p>
                  <p>{money(Number(r.amount))}</p>
                </div>
              ))}
            </div>
          )}
          <div className="overflow-auto rounded border max-h-[65vh]">
            <table className="w-full text-sm">
              <thead className="bg-muted sticky top-0">
                <tr>
                  {query.data.columns.map((c) => (
                    <th key={c} className="p-3 whitespace-nowrap text-left">
                      {c.replaceAll('_', ' ')}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {query.data.rows.map((r, i) => (
                  <tr key={String(r.id ?? i)} className="border-t">
                    {query.data.columns.map((c) => (
                      <td key={c} className="p-3 whitespace-nowrap">
                        {r[c] == null
                          ? '—'
                          : typeof r[c] === 'boolean'
                            ? r[c]
                              ? 'Yes'
                              : 'No'
                            : String(r[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {!query.data.rows.length && <p className="p-6">No records in this report period.</p>}
          </div>
        </>
      )}
    </div>
  )
}
