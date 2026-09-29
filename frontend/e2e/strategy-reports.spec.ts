import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'
test.use({ channel: 'chrome' })

// Offline UI integration: actual saved research data, explicitly mocked auth/API.
const root = resolve(process.cwd(), '..')
const report = JSON.parse(execFileSync(resolve(root, '.venv/Scripts/python.exe'), ['-c',
  "import sqlite3; c=sqlite3.connect('file:db/scanner_strategy_reports.db?mode=ro',uri=True); r=c.execute(\"select payload from reports where id='backtest-2026-09-28'\").fetchone(); print(r[0]); c.close()"], { cwd: root, maxBuffer: 30 * 1024 * 1024 }).toString())

test('saved report charts, scenarios, CSV and responsive layout', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => localStorage.setItem('openalgo-auth', JSON.stringify({ state: { isAuthenticated: true, user: { username: 'fixture', broker: 'fyers', isLoggedIn: true, loginTime: new Date().toISOString() } }, version: 0 })))
  await page.route('**/auth/session-status', route => route.fulfill({ json: { status: 'success', logged_in: true, user: 'fixture', broker: 'fyers' } }))
  await page.route('**/auth/csrf-token', route => route.fulfill({ json: { csrf_token: 'test-fixture' } }))
  await page.route('**/market-scanner/api/reports', route => route.fulfill({ json: { status: 'success', data: [{ id: report.id, day: report.day, kind: report.kind, status: report.status }] } }))
  await page.route('**/market-scanner/api/reports/backtest-2026-09-28*', route => route.fulfill({ json: { status: 'success', data: report } }))
  await page.goto('/strategy-reports')
  await expect(page.getByRole('heading', { name: 'Strategy Reports', exact: true })).toBeVisible()
  await expect(page.getByRole('img', { name: /trade candle chart/ })).toBeVisible()
  await expect(page.getByText('₹73,586.69', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Download trades CSV' })).toHaveAttribute('href', /download=csv/)
  await page.getByLabel('Execution scenario').selectOption('OHLC')
  await expect(page.getByText('₹73,698.56', { exact: true })).toBeVisible()
  await page.getByLabel('Trade chart', { exact: true }).selectOption('10')
  await page.getByLabel('Heikin Ashi candles').check()
  await page.getByLabel('Full session').check()
  await expect(page.getByRole('img', { name: /trade candle chart/ })).toBeVisible()
  await page.screenshot({ path: 'test-results/strategy-reports-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('heading', { name: 'Strategy Reports', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await page.screenshot({ path: 'test-results/strategy-reports-mobile.png', fullPage: true })
  expect(errors).toEqual([])
})

test('scanner sort controls send filters and refresh without clearing rows', async ({ page }) => {
  await page.route('**/auth/session-status', route => route.fulfill({ json: { status: 'success', logged_in: true, user: 'fixture', broker: 'fyers' } }))
  const queries: URLSearchParams[] = []
  await page.route('**/market-scanner/api/live*', route => {
    const params = new URL(route.request().url()).searchParams
    queries.push(params)
    const row = { symbol: 'ABC', name: 'ABC Limited', exchange: 'NSE', ltp: 110, previous_close: 100, change_percent: 10, volume: 2000, volume_change_percent: 100, rvol: 2, stale: false, last_trade_at: new Date().toISOString(), quote_fetched_at: new Date().toISOString(), baseline_status: 'ready' }
    return route.fulfill({ json: { status: 'success', data: { enabled: true, broker: 'fyers', categories: [], options: { lookback_days: 5 }, market_open: true, stale: false, updated_at: new Date().toISOString(), volume_shockers: [row], top_gainers: [row], top_losers: [], matching_counts: { volume_shockers: 1, top_gainers: 1, top_losers: 0 }, filtered_quotes: 1, transport: 'shared_websocket_and_polling', streaming_symbols: 2680 } } })
  })
  await page.goto('/market-scanner')
  await expect(page.getByText('ABC Limited', { exact: true })).toBeVisible()
  await page.getByLabel('Volume shocker sort').selectOption('change_percent')
  await page.getByLabel('Sort direction').selectOption('asc')
  await page.getByLabel('Positive day change only').check()
  await expect.poll(() => queries.at(-1)?.get('positive_only')).toBe('true')
  expect(queries.at(-1)?.get('shocker_sort')).toBe('change_percent')
  expect(queries.at(-1)?.get('sort_order')).toBe('asc')
  const before = queries.length
  await expect.poll(() => queries.length, { timeout: 2500 }).toBeGreaterThan(before)
  await expect(page.getByText('ABC Limited', { exact: true })).toBeVisible()
  await page.getByLabel('Volume shocker sort').selectOption('volume')
  await page.getByLabel('Sort direction').selectOption('desc')
  await expect.poll(() => queries.at(-1)?.get('sort_order')).toBe('desc')
  expect(queries.at(-1)?.get('shocker_sort')).toBe('volume')
})
