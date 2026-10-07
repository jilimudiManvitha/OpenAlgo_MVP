import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { TradeChart } from './StrategyReportDetail'

it('shows the lower band and includes a short stop above entry and target below price in chart bounds', () => {
  const { container } = render(<TradeChart trade={{symbol:'ABC',path:'PAPER',side:'SELL',entry_ts:1000,exit_ts:1060,
    entry:100,exit:97,quantity:10,stop:120,target:40,fees:0,net_pnl:30,reason:'TARGET'}}
    candles={[{timestamp:1000,open:100,high:101,low:98,close:99,ha_open:101,ha_high:101,ha_low:98,
      ha_close:99,bb_upper:105,bb_lower:95,bb_middle:100,vwap:103}]} />)
  expect(screen.getByText(/Purple: BB lower/)).toBeInTheDocument()
  expect(container.querySelector('polyline title')?.textContent).toBe('bb_lower')
  const labels = [...container.querySelectorAll('svg text')].map(n => n.textContent)
  expect(labels).toContain('40.00')
  expect(labels).toContain('120.00')
})
