import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { webClient } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { OptionsCapital } from './OptionsCapital'

vi.mock('@/api/client', () => ({ webClient: { get: vi.fn(), post: vi.fn() } }))
const payload = {
  allocation: 24000000,
  deployable_budget: 21600000,
  fingerprint: 'saved-basket',
  strategies: [
    {
      strategy_id: 'condor',
      name: 'Iron Condor Current Week',
      allocation: 2000000,
      deployable_budget: 1800000,
      updated_at: '2026-10-08T09:30:00+05:30',
      pending: false,
      halted: false,
      unprotected_shorts: 0,
      entry_snapshot: null,
      legs: [{ symbol: 'NIFTY13OCT2624000CE', side: -1, quantity: 650, lot_size: 65, entry: 50 }],
      charges: {
        total: 25,
        breakdown: { brokerage: 20, gst: 5 },
        scope: 'Confirmed fills',
        source: null,
      },
    },
  ],
}
beforeEach(() => {
  vi.resetAllMocks()
  useAuthStore.getState().login('alice', 'fyers')
  vi.mocked(webClient.get).mockResolvedValue({ data: { data: payload } })
})
it('requests the complete saved basket, labels both margins and clears failed quotes', async () => {
  vi.mocked(webClient.post).mockResolvedValue({
    data: {
      data: {
        quoted_at: '2026-10-08T09:31:00+05:30',
        margin_total: 1750000,
        margin_new_order: 1600000,
        sizing_requirement: 1750000,
        fingerprint: 'saved-basket',
      },
    },
  })
  render(<OptionsCapital />)
  await screen.findByText('₹2,40,00,000')
  expect(screen.getByText('No saved entry quote')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Get FYERS margin', exact: true }))
  await screen.findByText('Including existing positions: ₹16,00,000')
  expect(webClient.post).toHaveBeenCalledWith(
    '/market-scanner/api/options-capital/quote',
    { strategy_id: 'condor', fingerprint: 'saved-basket' },
    expect.any(Object)
  )
  expect(screen.getByText('₹17,50,000')).toBeInTheDocument()
  vi.mocked(webClient.post).mockRejectedValue({
    response: { data: { message: 'Positions changed. Reload.' } },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Get FYERS margin', exact: true }))
  await screen.findByRole('alert')
  expect(screen.queryByText('Including existing positions: ₹16,00,000')).not.toBeInTheDocument()
})
it('aborts an old owner request and never displays its delayed response', async () => {
  let resolve!: (result: unknown) => void
  vi.mocked(webClient.get).mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r
      })
  )
  render(<OptionsCapital />)
  await waitFor(() => expect(webClient.get).toHaveBeenCalledTimes(1))
  const signal = vi.mocked(webClient.get).mock.calls[0][1]?.signal
  vi.mocked(webClient.get).mockResolvedValue({ data: { data: { ...payload, strategies: [] } } })
  act(() => useAuthStore.getState().login('bob', 'fyers'))
  await waitFor(() => expect(signal?.aborted).toBe(true))
  await act(async () => resolve({ data: { data: payload } }))
  expect(screen.queryByText('Iron Condor Current Week')).not.toBeInTheDocument()
})
it('disables quoting unsettled baskets and non-FYERS sessions', async () => {
  vi.mocked(webClient.get).mockResolvedValue({
    data: { data: { ...payload, strategies: [{ ...payload.strategies[0], pending: true }] } },
  })
  render(<OptionsCapital />)
  await screen.findByText('Iron Condor Current Week')
  expect(screen.getByRole('button', { name: 'Get FYERS margin', exact: true })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Get combined FYERS margin' })).toBeDisabled()
})
