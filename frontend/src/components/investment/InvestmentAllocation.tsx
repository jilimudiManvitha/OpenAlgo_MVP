import { useState } from 'react'
import type { InvestmentHolding } from '@/types/investment'
import { money } from './common'

const colors = [
  '#3b82f6',
  '#14b8a6',
  '#f59e0b',
  '#a855f7',
  '#f43f5e',
  '#84cc16',
  '#06b6d4',
  '#f97316',
]
export function InvestmentAllocation({ holdings }: { holdings: InvestmentHolding[] }) {
  const [basis, setBasis] = useState<'invested' | 'market_value'>('invested')
  const rows = holdings.filter((row) => Number(row[basis]) > 0)
  const total = rows.reduce((sum, row) => sum + Number(row[basis]), 0)
  const liabilities = holdings.filter((row) => Number(row[basis]) < 0)
  const exposure = holdings.reduce((sum, row) => sum + Math.abs(Number(row[basis] ?? 0)), 0)
  let offset = 0
  return (
    <section className="rounded-xl border bg-card p-5 space-y-4" aria-label="Portfolio allocation">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-semibold">Allocation</h2>
        <select
          aria-label="Allocation basis"
          className="rounded border bg-background p-1 text-sm"
          value={basis}
          onChange={(e) => setBasis(e.target.value as typeof basis)}
        >
          <option value="invested">Investment cost</option>
          <option value="market_value">Latest value</option>
        </select>
      </div>
      {liabilities.length ? (
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Signed allocation as a share of gross absolute exposure. Liabilities reduce net worth.
          </p>
          {holdings
            .filter((row) => Number(row[basis]) !== 0 && row[basis] != null)
            .map((row) => (
              <div key={row.id} className="text-sm">
                <div className="flex justify-between gap-3">
                  <span>{row.symbol}</span>
                  <span>
                    {money(row[basis])} · {((Number(row[basis]) / exposure) * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="h-2 bg-muted rounded">
                  <div
                    className={`h-2 rounded ${Number(row[basis]) < 0 ? 'bg-red-500' : 'bg-blue-500'}`}
                    style={{ width: `${(Math.abs(Number(row[basis])) / exposure) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          <p className="font-medium">
            Net {money(holdings.reduce((sum, row) => sum + Number(row[basis] ?? 0), 0))}
          </p>
        </div>
      ) : total === 0 ? (
        <p className="text-sm text-muted-foreground">
          Add purchases and valuation prices to see allocation.
        </p>
      ) : (
        <div className="flex flex-wrap gap-6 items-center">
          <svg
            viewBox="0 0 120 120"
            className="w-44 h-44 shrink-0"
            role="img"
            aria-label={`${basis === 'invested' ? 'Cost' : 'Value'} allocation by holding`}
          >
            <title>Holding weights</title>
            {rows.map((row, i) => {
              const weight = (Number(row[basis]) / total) * 100
              const start = offset
              offset += weight
              return (
                <circle
                  key={row.id}
                  cx="60"
                  cy="60"
                  r="44"
                  fill="none"
                  stroke={colors[i % colors.length]}
                  strokeWidth="22"
                  pathLength="100"
                  strokeDasharray={`${weight} ${100 - weight}`}
                  strokeDashoffset={-start}
                  transform="rotate(-90 60 60)"
                >
                  <title>
                    {row.symbol}: {weight.toFixed(1)}% · {money(row[basis])}
                  </title>
                </circle>
              )
            })}
          </svg>
          <ul className="flex-1 min-w-40 space-y-2 text-sm">
            {rows.map((row, i) => (
              <li key={row.id} className="flex justify-between gap-4">
                <span>
                  <span
                    className="inline-block size-2.5 rounded-sm mr-2"
                    style={{ backgroundColor: colors[i % colors.length] }}
                  />
                  {row.symbol}
                </span>
                <span className="tabular-nums">
                  {((Number(row[basis]) / total) * 100).toFixed(1)}%
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {basis === 'market_value' && holdings.some((row) => row.market_value == null) && (
        <p className="text-xs text-amber-600">
          Unpriced holdings are excluded from this value chart.
        </p>
      )}
    </section>
  )
}
