import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { webClient } from '@/api/client'
import ReportJournal, { type Day, FinancialCalendar, type Metrics } from './ReportJournal'

vi.mock('@/api/client', () => ({ webClient: { get: vi.fn() } }))
vi.mock('./StrategyReportDetail', () => ({ StrategyReportDetail: () => <p>Individual detail</p> }))
const m: Metrics = {
  gross_pnl: 120,
  net_pnl: 100,
  charges: 20,
  peak_capital: 1000,
  trades: 3,
  total_trades: 3,
  open_trades: 0,
  entries: 3,
  wins: 2,
  losses: 1,
  breakeven: 0,
  win_rate: 66.67,
}
const day: Day = {
  day: '2026-10-07',
  metrics: m,
  stocks: [{ symbol: 'SBIN', metrics: m }],
  strategies: [
    {
      strategy_id: 'fixed',
      name: 'Fixed 3R',
      metrics: m,
      stocks: [{ symbol: 'SBIN', metrics: m }],
      reports: [{ id: 'fixed-day', status: 'complete', note: 'Recorded session' }],
    },
  ],
}
const payload = {
  year: 2026,
  days: [day],
  totals: m,
  strategies: [{ id: 'fixed', name: 'Fixed 3R' }],
  symbols: ['SBIN'],
  streaks: { winning: 2, losing: 1, current: 2 },
}
beforeEach(() => {
  vi.mocked(webClient.get).mockReset()
  vi.mocked(webClient.get).mockResolvedValue({ data: { data: payload } })
})
describe('financial calendar', () => {
  it('lays out April through March and includes leap day with accessible selection', () => {
    const onSelect = vi.fn()
    render(<FinancialCalendar year={2027} days={[]} selected="2028-02-29" onSelect={onSelect} />)
    const month = screen.getByRole('region', { name: 'February 2028' })
    const leap = within(month).getByRole('button', { name: /29 February 2028/ })
    expect(leap).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(leap)
    expect(onSelect).toHaveBeenCalledWith('2028-02-29')
    expect(screen.getAllByRole('region')).toHaveLength(12)
  })
  it('distinguishes absent reports from closed-trade performance', () => {
    render(<FinancialCalendar year={2026} days={[day]} selected={day.day} onSelect={() => {}} />)
    expect(
      screen.getByRole('button', {
        name: /07 October 2026: ₹100 net P&L, 3 closed trades, 2 wins, 1 losses/,
      })
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /08 October 2026: No report/ })).toBeInTheDocument()
  })
})
describe('journal workflow', () => {
  it('groups by date, expands strategy and switches to a stock calendar', async () => {
    render(<ReportJournal />)
    await screen.findByText('FY net')
    fireEvent.click(screen.getByRole('button', { name: /07 October 2026:/ }))
    fireEvent.click(screen.getByText('Fixed 3R', { selector: 'span' }))
    const daily = screen.getByRole('region', { name: 'Selected daily report' })
    expect(within(daily).getAllByText('Closed / open trades')).toHaveLength(2)
    const stockButtons = within(daily).getAllByRole('button', { name: 'SBIN' })
    fireEvent.click(stockButtons.at(-1)!)
    await waitFor(() =>
      expect(webClient.get).toHaveBeenLastCalledWith(
        '/market-scanner/api/report-journal',
        expect.objectContaining({
          params: expect.objectContaining({ strategy: 'fixed', symbol: 'SBIN' }),
        })
      )
    )
  })
  it('offers a combined daily list and separate scenarios', async () => {
    render(<ReportJournal />)
    await screen.findByText('FY net')
    fireEvent.click(screen.getByRole('button', { name: 'Daily list' }))
    expect(
      screen.getByRole('button', { name: /07 October 2026.*1 strategies/ })
    ).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Execution scenario'), { target: { value: 'OHLC' } })
    await waitFor(() =>
      expect(webClient.get).toHaveBeenLastCalledWith(
        '/market-scanner/api/report-journal',
        expect.objectContaining({ params: expect.objectContaining({ scenario: 'OHLC' }) })
      )
    )
  })
  it('shows connection failures instead of presenting zero totals', async () => {
    vi.mocked(webClient.get).mockRejectedValue(new Error('offline'))
    render(<ReportJournal />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to refresh reports')
    expect(screen.queryByText('FY net')).not.toBeInTheDocument()
  })
})

it('switches charges basis and offers live reports without changing execution mode', async () => {
  render(<ReportJournal />)
  await screen.findByText('FY net')
  expect(screen.getByLabelText('Charges basis')).toHaveValue('estimated')
  fireEvent.change(screen.getByLabelText('Charges basis'), { target: { value: 'recorded' } })
  await waitFor(() =>
    expect(webClient.get).toHaveBeenLastCalledWith(
      '/market-scanner/api/report-journal',
      expect.objectContaining({ params: expect.objectContaining({ charges: 'recorded' }) })
    )
  )
  fireEvent.change(screen.getByLabelText('Execution scenario'), { target: { value: 'LIVE' } })
  await waitFor(() =>
    expect(webClient.get).toHaveBeenLastCalledWith(
      '/market-scanner/api/report-journal',
      expect.objectContaining({ params: expect.objectContaining({ scenario: 'LIVE' }) })
    )
  )
})

it('labels inferred broker and unavailable estimates instead of showing zero-cost profit', async () => {
  vi.mocked(webClient.get).mockResolvedValue({
    data: {
      data: {
        ...payload,
        session_broker: 'other',
        charge_profiles: [
          { broker: 'other', profile: null, broker_inferred: true, unavailable: 1 },
        ],
        totals: { ...m, net_pnl: null },
        days: [{ ...day, metrics: { ...m, net_pnl: null, unestimated_trades: 1 } }],
      },
    },
  })
  render(<ReportJournal />)
  await screen.findByText(/Historical broker was not saved/)
  expect(screen.getByText(/Standard tariff unavailable/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /07 October 2026:/ }))
  expect(screen.getByRole('alert')).toHaveTextContent('Estimated net unavailable')
})

it('follows global mode and clears strategy filters on a broker change', async () => {
  const { useThemeStore } = await import('@/stores/themeStore')
  const { useAuthStore } = await import('@/stores/authStore')
  const { act } = await import('@testing-library/react')
  act(() => useThemeStore.setState({ appMode: 'analyzer' }))
  render(<ReportJournal />)
  await screen.findByText('FY net')
  expect(screen.getByLabelText('Execution scenario')).toHaveValue('PAPER')
  fireEvent.change(screen.getByLabelText('Strategy filter'), { target: { value: 'fixed' } })
  act(() => useThemeStore.setState({ appMode: 'live' }))
  await waitFor(() =>
    expect(webClient.get).toHaveBeenLastCalledWith(
      '/market-scanner/api/report-journal',
      expect.objectContaining({
        params: expect.objectContaining({ scenario: 'LIVE', strategy: '' }),
      })
    )
  )
  await screen.findByText('FY net')
  fireEvent.change(screen.getByLabelText('Stock filter'), { target: { value: 'SBIN' } })
  act(() =>
    useAuthStore.setState({ user: { username: 'alice', broker: 'dhan', isLoggedIn: true } })
  )
  await waitFor(() =>
    expect(webClient.get).toHaveBeenLastCalledWith(
      '/market-scanner/api/report-journal',
      expect.objectContaining({ params: expect.objectContaining({ scenario: 'LIVE', symbol: '' }) })
    )
  )
})
