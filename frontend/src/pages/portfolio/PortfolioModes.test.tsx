import { useQuery } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { investmentApi } from '@/api/investment'
import { ExecutionPanel } from '@/components/investment/ExecutionPanel'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import PortfolioIndex, { useInvestmentContext } from './PortfolioIndex'

vi.mock('@/api/investment', async (original) => {
  const real = await original<typeof import('@/api/investment')>()
  return {
    ...real,
    investmentApi: {
      ...real.investmentApi,
      accounts: vi.fn(),
      holdings: vi.fn(),
      executionCapabilities: vi.fn(),
      executionOrders: vi.fn(),
      estimateOrder: vi.fn(),
      submitOrder: vi.fn(),
    },
  }
})
function Probe() {
  const { accounts } = useInvestmentContext()
  const rows = useQuery({
    queryKey: ['investment', 'holdings'],
    queryFn: () => investmentApi.holdings(),
  })
  return (
    <>
      <p>{accounts.map((a) => a.name).join(',')}</p>
      <p>{rows.data?.map((a) => a.symbol).join(',')}</p>
    </>
  )
}
function mount(child: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={['/portfolio']}>
      <Routes>
        <Route path="/portfolio" element={<PortfolioIndex />}>
          <Route index element={child} />
        </Route>
      </Routes>
    </MemoryRouter>
  )
}
beforeEach(() => {
  vi.clearAllMocks()
  useThemeStore.setState({ appMode: 'analyzer' })
  useAuthStore.setState({ user: { username: 'alice', broker: 'fyers', isLoggedIn: true } })
  vi.mocked(investmentApi.accounts).mockImplementation(async () => [
    {
      id: useThemeStore.getState().appMode === 'analyzer' ? 1 : 2,
      name: useThemeStore.getState().appMode === 'analyzer' ? 'Paper savings' : 'Real savings',
      kind: useThemeStore.getState().appMode === 'analyzer' ? 'paper' : 'live',
      broker_label: 'FYERS',
    },
  ])
  vi.mocked(investmentApi.holdings).mockImplementation(async () => [
    {
      id: 1,
      account_id: 1,
      asset_class: 'STOCK',
      symbol: useThemeStore.getState().appMode === 'analyzer' ? 'PAPER_SBIN' : 'LIVE_SBIN',
      exchange: 'NSE',
    } as Awaited<ReturnType<typeof investmentApi.holdings>>[number],
  ])
  vi.mocked(investmentApi.executionCapabilities).mockResolvedValue({ orders: true, gtt: true })
  vi.mocked(investmentApi.executionOrders).mockResolvedValue([])
  vi.mocked(investmentApi.estimateOrder).mockResolvedValue({ status: 'estimated', total: 23.1 })
  vi.mocked(investmentApi.submitOrder).mockResolvedValue({
    id: 1,
    asset_id: 1,
    kind: 'order',
    payload: '{}',
    status: 'accepted',
    external_id: 'fixture',
    message: 'Accepted',
    created_at: '',
  })
})
describe('Portfolio mode boundary', () => {
  it('replaces accounts, cached holdings and an open account form on mode switch', async () => {
    mount(<Probe />)
    await screen.findByText('PAPER_SBIN')
    fireEvent.click(screen.getByRole('button', { name: 'Add account' }))
    expect(screen.getByRole('dialog')).toBeVisible()
    act(() => useThemeStore.setState({ appMode: 'live' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByText('PAPER_SBIN')).not.toBeInTheDocument()
    await screen.findByText('LIVE_SBIN')
    expect(screen.queryByRole('option', { name: /Paper savings/ })).not.toBeInTheDocument()
    expect(investmentApi.holdings).toHaveBeenCalledTimes(2)
    expect(investmentApi.submitOrder).not.toHaveBeenCalled()
  })
  it('requires review and explicit confirmation, then does not double-submit', async () => {
    mount(<ExecutionPanel />)
    await screen.findByRole('option', { name: /PAPER_SBIN/ })
    fireEvent.change(screen.getByLabelText('Order instrument'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Order quantity'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Order limit price'), { target: { value: '100' } })
    fireEvent.click(screen.getByRole('button', { name: 'Review Sandbox order' }))
    await screen.findByRole('button', { name: 'Confirm Sandbox order' })
    expect(investmentApi.submitOrder).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Sandbox order' }))
    await waitFor(() => expect(investmentApi.submitOrder).toHaveBeenCalledOnce())
    expect(investmentApi.submitOrder).toHaveBeenCalledWith(
      expect.objectContaining({ confirm: true, quantity: '2', price: '100', asset_id: 1 })
    )
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Confirm Sandbox order' })).toBeDisabled()
    )
  })
  it('clears a reviewed ticket when switching mode or broker', async () => {
    mount(<ExecutionPanel />)
    await screen.findByRole('option', { name: /PAPER_SBIN/ })
    fireEvent.change(screen.getByLabelText('Order instrument'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Order quantity'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Order limit price'), { target: { value: '100' } })
    fireEvent.click(screen.getByRole('button', { name: 'Review Sandbox order' }))
    await screen.findByRole('button', { name: 'Confirm Sandbox order' })
    act(() => useThemeStore.setState({ appMode: 'live' }))
    await screen.findByRole('button', { name: 'Review Live order' })
    expect(screen.queryByRole('button', { name: /Confirm/ })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Order quantity')).toHaveValue(null)
    fireEvent.change(screen.getByLabelText('Order quantity'), { target: { value: '8' } })
    act(() =>
      useAuthStore.setState({ user: { username: 'alice', broker: 'dhan', isLoggedIn: true } })
    )
    await screen.findByText('Live orders · dhan')
    expect(screen.getByLabelText('Order quantity')).toHaveValue(null)
    expect(investmentApi.submitOrder).not.toHaveBeenCalled()
  })
})
