import type {
  InvestmentAccount,
  InvestmentAsset,
  InvestmentDashboard,
  InvestmentHolding,
  InvestmentTransaction,
  TransactionInput,
  InvestmentReport,
  InvestmentWatchlist,
  InvestmentPaperOrder,
} from '@/types/investment'
import { webClient } from './client'

const base = '/investments/api'
interface Envelope<T> {
  status: string
  data: T
}
const get = async <T>(path: string, params = {}): Promise<T> =>
  (await webClient.get<Envelope<T>>(`${base}${path}`, { params })).data.data
const post = async <T>(path: string, body: unknown): Promise<T> =>
  (await webClient.post<Envelope<T>>(`${base}${path}`, body)).data.data
export const investmentKeys = {
  all: ['investment'] as const,
  accounts: ['investment', 'accounts'] as const,
}
export const investmentApi = {
  accounts: () => get<InvestmentAccount[]>('/accounts'),
  saveAccount: async (data: Omit<InvestmentAccount, 'id'>, id?: number) =>
    id
      ? (await webClient.patch<Envelope<InvestmentAccount>>(`${base}/accounts/${id}`, data)).data
          .data
      : post<InvestmentAccount>('/accounts', data),
  deleteAccount: (id: number) => webClient.delete(`${base}/accounts/${id}`),
  holdings: (account_id?: number) => get<InvestmentHolding[]>('/holdings', { account_id }),
  dashboard: (account_id?: number) => get<InvestmentDashboard>('/dashboard', { account_id }),
  saveAsset: async (data: Partial<InvestmentAsset>, id?: number) =>
    id
      ? (await webClient.patch<Envelope<InvestmentAsset>>(`${base}/assets/${id}`, data)).data.data
      : post<InvestmentAsset>('/assets', data),
  deleteAsset: (id: number) => webClient.delete(`${base}/assets/${id}`),
  addTransaction: (data: TransactionInput) => post<InvestmentTransaction>('/transactions', data),
  transactions: (asset_id?: number, offset = 0) =>
    get<InvestmentTransaction[]>('/transactions', { asset_id, offset, limit: 50 }),
  deleteTransaction: (id: number) => webClient.delete(`${base}/transactions/${id}`),
  price: (id: number, price: string, as_of: string) =>
    post(`/assets/${id}/price`, { price, as_of }),
  refresh: (asset_ids?: number[]) =>
    post<{ updated: number; failed: string[]; message: string }>('/prices/refresh', { asset_ids }),
  importPrices: (csv: string, account_id?: number) =>
    post<{ updated: number; message: string }>('/prices/import', { csv, account_id }),
  report: (name: string, params: { account_id?: number; start?: string; end?: string }) =>
    get<InvestmentReport>(`/reports/${name}`, params),
  watchlists: () => get<InvestmentWatchlist[]>('/watchlists'),
  saveWatchlist: (name: string, category: string) => post('/watchlists', { name, category }),
  editWatchlist: (id: number, name: string, category: string) =>
    webClient.patch(`${base}/watchlists/${id}`, { name, category }),
  deleteWatchlist: (id: number) => webClient.delete(`${base}/watchlists/${id}`),
  watchItem: (id: number, asset_id: number, stop_price: string, target_price: string) =>
    post(`/watchlists/${id}/items`, { asset_id, stop_price, target_price }),
  deleteWatchItem: (id: number) => webClient.delete(`${base}/watch-items/${id}`),
  paperOrders: () => get<InvestmentPaperOrder[]>('/paper/gtt'),
  placePaper: (data: Record<string, unknown>) => post<InvestmentPaperOrder>('/paper/gtt', data),
  cancelPaper: (id: number) => webClient.delete(`${base}/paper/gtt/${id}`),
  syncPaper: () => post<{ updated: number; imported: number; errors: string[] }>('/paper/sync', {}),
}
export function investmentError(error: unknown): string {
  return (
    (error as { response?: { data?: { message?: string } } })?.response?.data?.message ||
    'Could not save or load investments. Please try again.'
  )
}
