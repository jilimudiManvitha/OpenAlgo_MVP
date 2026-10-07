import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { investmentApi } from '@/api/investment'
import { AddTransactionDialog } from '@/components/investment/AddTransactionDialog'
import { InvestmentAllocation } from '@/components/investment/InvestmentAllocation'
import type { InvestmentDashboard, InvestmentHolding } from '@/types/investment'
import Dashboard from './Dashboard'
import Stocks from './Stocks'
import Reports from './Reports'

vi.mock('./PortfolioIndex', () => ({
  useInvestmentContext: () => ({
    accountId: 1,
    accounts: [{ id: 1, name: 'Personal', broker_label: 'Manual', kind: 'paper' }],
  }),
}))
vi.mock('@/api/investment', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/api/investment')>()
  return {
    ...real,
    investmentApi: {
      ...real.investmentApi,
      dashboard: vi.fn(),
      holdings: vi.fn(),
      addTransaction: vi.fn(),
      report: vi.fn(),
    },
  }
})
const holding: InvestmentHolding = {
  id: 1,
  account_id: 1,
  asset_class: 'STOCK',
  name: 'Ather',
  symbol: 'ATHER',
  exchange: 'NSE',
  notes: '',
  is_watch_only: false,
  quantity: '100.000000',
  invested: '100000.0000',
  average_cost: '1000.0000',
  realized_gain: '0',
  fifo_realized: '0',
  income: '0',
  price: '1100',
  price_as_of: '2026-10-01T10:00:00Z',
  valuation_source: 'manual',
  stale: true,
  market_value: '110000',
  unrealized_gain: '10000',
  return_percent: '10',
  today_gain: null,
  days_held: 30,
}
const dashboard: InvestmentDashboard = {
  holdings: [holding],
  invested: '100000',
  market_value: '110000',
  priced_value: '110000',
  unrealized_gain: '10000',
  return_percent: '10',
  realized_gain: '0',
  today_gain: null,
  today_percent: null,
  winners: 1,
  losers: 0,
  unpriced: 0,
  stale: 1,
  score: {
    quality: 0,
    diversification: 0,
    momentum: null,
    composite: null,
    method: 'Documented score',
  },
}
function mount(child: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{child}</MemoryRouter>
    </QueryClientProvider>
  )
}
beforeEach(() => {
  vi.clearAllMocks()
})
describe('Investment portfolio', () => {
  it('shows the Ather valuation, unchanged cost and unavailable daily change honestly', async () => {
    vi.mocked(investmentApi.dashboard).mockResolvedValue(dashboard)
    mount(<Dashboard />)
    expect(await screen.findByText('₹1,00,000.00')).toBeVisible()
    expect(screen.getByText('₹1,10,000.00')).toBeVisible()
    expect(screen.getByText('₹10,000.00')).toBeVisible()
    expect(screen.getByText('10.00%')).toBeVisible()
    expect(screen.getByText(/Requires current timestamped/)).toBeVisible()
    expect(screen.getByText(/manual, stale or lack/)).toBeVisible()
  })
  it('does not turn a failed portfolio request into an empty state', async () => {
    vi.mocked(investmentApi.dashboard).mockRejectedValue({
      response: { data: { message: 'Database unavailable' } },
    })
    mount(<Dashboard />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Database unavailable')
    expect(screen.queryByText('Start your investment ledger')).not.toBeInTheDocument()
  })
  it('shows dated prices and keeps watch-only purchases disabled', async () => {
    vi.mocked(investmentApi.holdings).mockResolvedValue([
      { ...holding, is_watch_only: true, quantity: '0' },
    ])
    mount(<Stocks />)
    expect(await screen.findByText('Watching only')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Record', exact: true })).toBeDisabled()
    expect(screen.getByText(/manual · stale/)).toBeVisible()
  })
  it('preserves transaction input when the server rejects an oversell', async () => {
    const user = userEvent.setup()
    vi.mocked(investmentApi.addTransaction).mockRejectedValue({
      response: { data: { message: 'Sale exceeds the quantity held at this trade timestamp' } },
    })
    const close = vi.fn()
    mount(<AddTransactionDialog asset={holding} onClose={close} />)
    await user.selectOptions(screen.getByLabelText('Action'), 'SELL')
    await user.type(screen.getByLabelText('Quantity'), '101')
    await user.type(screen.getByLabelText('Price per unit (₹)'), '1100')
    await user.click(screen.getByRole('button', { name: 'Record transaction' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Sale exceeds')
    expect(screen.getByLabelText('Quantity')).toHaveValue(101)
    expect(close).not.toHaveBeenCalled()
    expect(investmentApi.addTransaction).toHaveBeenCalledWith(
      expect.objectContaining({
        asset_id: 1,
        action: 'SELL',
        quantity: '101',
        price: '1100',
        brokerage: '0',
      })
    )
  })
  it('switches allocation and discloses an unpriced holding', async () => {
    const user = userEvent.setup()
    mount(
      <InvestmentAllocation
        holdings={[holding, { ...holding, id: 2, symbol: 'SBIN', market_value: null }]}
      />
    )
    const section = screen.getByRole('region', { name: 'Portfolio allocation' })
    expect(within(section).getAllByText('50.0%')).toHaveLength(2)
    await user.selectOptions(screen.getByLabelText('Allocation basis'), 'market_value')
    expect(within(section).getByText('100.0%')).toBeVisible()
    expect(screen.getByText(/Unpriced holdings are excluded/)).toBeVisible()
  })
  it('labels liability actions and prevents a dividend or split entry', () => {
    mount(<AddTransactionDialog asset={{ ...holding, asset_class: 'LOAN' }} onClose={vi.fn()} />)
    expect(screen.getByRole('option', { name: 'Borrow principal' })).toBeVisible()
    expect(screen.getByRole('option', { name: 'Repay principal' })).toBeVisible()
    expect(screen.queryByRole('option', { name: 'Dividend' })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /split/ })).not.toBeInTheDocument()
  })
  it('preserves gaps in performance valuations and applies report filters to CSV', async () => {
    const user = userEvent.setup()
    vi.mocked(investmentApi.report).mockResolvedValue({
      name: 'performance',
      title: 'Performance',
      start: '2026-09-01',
      end: '2026-09-04',
      method: 'Recorded values',
      columns: ['date', 'market_value'],
      rows: [
        { date: '2026-09-01', market_value: '100' },
        { date: '2026-09-02', market_value: null },
        { date: '2026-09-03', market_value: '110' },
        { date: '2026-09-04', market_value: '115' },
      ],
    })
    mount(<Reports />)
    await user.selectOptions(screen.getByLabelText('Portfolio report'), 'performance')
    const chart = await screen.findByRole('img', { name: 'Recorded portfolio value by date' })
    const path = chart.querySelector('path')?.getAttribute('d') ?? ''
    expect(path.match(/M/g)).toHaveLength(2)
    expect(path.match(/L/g)).toHaveLength(1)
    expect(screen.getByRole('link', { name: 'Download CSV' })).toHaveAttribute(
      'href',
      expect.stringContaining('reports/performance?download=csv&account_id=1')
    )
  })
})
