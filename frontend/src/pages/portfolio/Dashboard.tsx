import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { investmentApi, investmentError } from '@/api/investment'
import { ErrorMessage, gainClass, money, percent, Stat } from '@/components/investment/common'
import { InvestmentAllocation } from '@/components/investment/InvestmentAllocation'
import { Button } from '@/components/ui/button'
import { useInvestmentContext } from './PortfolioIndex'

export default function InvestmentDashboard() {
  const { accountId } = useInvestmentContext()
  const query = useQuery({
    queryKey: ['investment', 'dashboard', accountId],
    queryFn: () => investmentApi.dashboard(accountId),
  })
  if (query.isPending) return <p>Loading portfolio…</p>
  if (query.isError)
    return (
      <ErrorMessage>
        {investmentError(query.error)}{' '}
        <button type="button" onClick={() => query.refetch()} className="underline">
          Retry
        </button>
      </ErrorMessage>
    )
  const data = query.data
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <Stat label="Investment cost" detail="Weighted average, including charges">
          {money(data.invested)}
        </Stat>
        <Stat
          label="Net portfolio value"
          detail={
            data.unpriced
              ? `${data.unpriced} holdings need a valuation`
              : `${data.holdings.length} open holdings`
          }
        >
          {money(data.market_value)}
        </Stat>
        <Stat label="Unrealized gain" detail={percent(data.return_percent)}>
          <span className={gainClass(data.unrealized_gain)}>{money(data.unrealized_gain)}</span>
        </Stat>
        <Stat label="Realized gain & income" detail="Weighted average realization">
          {money(data.realized_gain)}
        </Stat>
      </div>
      <div className="grid sm:grid-cols-3 gap-4">
        <Stat
          label="Today's change"
          detail={
            data.today_gain == null
              ? 'Requires current timestamped broker quotes'
              : percent(data.today_percent)
          }
        >
          {money(data.today_gain)}
        </Stat>
        <Stat label="Holdings in profit">{data.winners}</Stat>
        <Stat label="Holdings in loss">{data.losers}</Stat>
      </div>
      {data.stale > 0 && (
        <output className="block rounded-md bg-amber-500/10 p-3 text-sm">
          {data.stale} holding prices are manual, stale or lack a market timestamp. Prices show
          their source and date in each asset page. Loans and borrowings subtract from all totals.
        </output>
      )}
      {data.holdings.length === 0 && (
        <section className="rounded-xl border border-dashed p-8 text-center space-y-3">
          <h2 className="font-semibold">Start your investment ledger</h2>
          <p className="text-sm text-muted-foreground">
            Create an account, add a stock and record its purchase. Existing sandbox holdings stay
            in the sandbox.
          </p>
          <Button asChild>
            <Link to="/portfolio/stocks">Go to Stocks</Link>
          </Button>
        </section>
      )}
      <div className="grid lg:grid-cols-2 gap-6">
        <InvestmentAllocation holdings={data.holdings} />
        <section className="rounded-xl border bg-card p-5 space-y-4">
          <h2 className="font-semibold">Portfolio measures</h2>
          {[
            ['Quality proxy', data.score.quality],
            ['Diversification', data.score.diversification],
            ['Momentum', data.score.momentum],
            ['Composite', data.score.composite],
          ].map(([label, value]) => (
            <div className="flex justify-between text-sm" key={String(label)}>
              <span>{label}</span>
              <span className="font-mono">
                {value == null ? 'Not available' : `${value} / 100`}
              </span>
            </div>
          ))}
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">How these measures are calculated</summary>
            <p className="mt-2">{data.score.method}</p>
          </details>
        </section>
      </div>
    </div>
  )
}
