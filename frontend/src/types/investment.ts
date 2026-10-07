export type DecimalValue = string
export const assetClasses = {
  STOCK: 'Stocks & ETFs',
  MUTUAL_FUND: 'Mutual Funds',
  FIXED_INCOME: 'Fixed Income',
  BULLION: 'Bullion',
  ULIP: 'ULIPs',
  PROPERTY: 'Property',
  OTHER_ASSET: 'Other Assets',
  LOAN: 'Loans',
  OTHER_BORROWING: 'Other Borrowings',
} as const
export type AssetClass = keyof typeof assetClasses
export const assetFields: Record<AssetClass, string[]> = {
  STOCK: [],
  MUTUAL_FUND: ['fund_house', 'plan', 'folio'],
  FIXED_INCOME: ['issuer', 'maturity_date', 'interest_rate'],
  BULLION: ['metal', 'purity', 'unit'],
  ULIP: ['insurer', 'policy_number', 'maturity_date'],
  PROPERTY: ['address', 'area', 'unit'],
  OTHER_ASSET: ['description'],
  LOAN: ['lender', 'interest_rate', 'maturity_date'],
  OTHER_BORROWING: ['lender', 'description', 'maturity_date'],
}
export interface InvestmentAccount {
  id: number
  name: string
  broker_label: string
  kind: 'live' | 'paper'
}
export interface InvestmentAsset {
  id: number
  account_id: number
  asset_class: AssetClass
  name: string
  symbol: string
  exchange: 'NSE' | 'BSE' | 'MANUAL'
  scheme_code?: string | null
  details?: Record<string, string>
  notes: string
  is_watch_only: boolean
}
export interface InvestmentHolding extends InvestmentAsset {
  quantity: DecimalValue
  invested: DecimalValue
  average_cost: DecimalValue
  realized_gain: DecimalValue
  fifo_realized: DecimalValue
  income: DecimalValue
  price: DecimalValue | null
  price_as_of: string | null
  valuation_source: string
  stale: boolean
  market_value: DecimalValue | null
  unrealized_gain: DecimalValue | null
  return_percent: DecimalValue | null
  today_gain: DecimalValue | null
  days_held: number
}
export const chargeFields = [
  'brokerage',
  'stt',
  'gst',
  'stamp_duty',
  'sebi',
  'exchange_charges',
] as const
export type ChargeField = (typeof chargeFields)[number]
export type TransactionInput = {
  asset_id: number
  action: 'BUY' | 'SELL' | 'DIVIDEND' | 'INTEREST' | 'CORPORATE_ACTION'
  quantity: string
  price: string
  trade_date: string
  trade_time: string
  notes: string
  corporate_ratio?: string
} & Record<ChargeField, string>
export interface InvestmentTransaction extends TransactionInput {
  id: number
}
export interface InvestmentDashboard {
  holdings: InvestmentHolding[]
  invested: DecimalValue
  market_value: DecimalValue | null
  priced_value: DecimalValue
  unrealized_gain: DecimalValue | null
  return_percent: DecimalValue | null
  realized_gain: DecimalValue
  today_gain: DecimalValue | null
  today_percent: DecimalValue | null
  winners: number
  losers: number
  unpriced: number
  stale: number
  score: {
    quality: number | null
    diversification: number | null
    momentum: number | null
    composite: number | null
    method: string
  }
}
export interface InvestmentReport {
  name: string
  title: string
  start: string
  end: string
  method: string
  columns: string[]
  rows: Record<string, string | number | boolean | null>[]
}
export interface InvestmentWatchItem {
  id: number
  asset_id: number
  stop_price: string | null
  target_price: string | null
  asset: InvestmentHolding
  observation: string
}
export interface InvestmentWatchlist {
  id: number
  name: string
  category: string
  items: InvestmentWatchItem[]
}
export interface InvestmentPaperOrder {
  id: number
  asset_id: number
  watchlist_id: number
  status: string
  gtt_id: string | null
  message: string
  payload: string
  created_at: string
}
