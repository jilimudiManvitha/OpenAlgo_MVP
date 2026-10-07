import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import type {
  InvestmentAccount,
  InvestmentAsset,
  InvestmentDashboard,
  InvestmentHolding,
  InvestmentPaperOrder,
  InvestmentReport,
  InvestmentTransaction,
  InvestmentWatchlist,
  TransactionInput,
} from '@/types/investment'
import { webClient } from './client'

export const investmentScope = () => ({
  mode: useThemeStore.getState().appMode === 'analyzer' ? 'paper' : 'live',
  broker: useAuthStore.getState().user?.broker ?? '',
})
const scopedClient = {
  get: webClient.get.bind(webClient),
  post: <T>(url: string, data: unknown) =>
    webClient.post<T>(url, data, { params: investmentScope() }),
  patch: <T>(url: string, data: unknown) =>
    webClient.patch<T>(url, data, { params: investmentScope() }),
  delete: (url: string) => webClient.delete(url, { params: investmentScope() }),
}

const base = '/investments/api'
interface Envelope<T> {
  status: string
  data: T
}
const get = async <T>(path: string, params = {}): Promise<T> =>
  (
    await scopedClient.get<Envelope<T>>(`${base}${path}`, {
      params: { ...params, ...investmentScope() },
    })
  ).data.data
const post = async <T>(path: string, body: unknown): Promise<T> =>
  (await scopedClient.post<Envelope<T>>(`${base}${path}`, body)).data.data
export const investmentKeys = {
  all: ['investment'] as const,
  accounts: ['investment', 'accounts'] as const,
}
export interface ExecutionRequest {
  id: number
  asset_id: number
  kind: string
  payload: string
  status: string
  external_id?: string
  message: string
  created_at: string
}
export const investmentApi = {
  executionCapabilities: () => get<{ gtt: boolean; orders: boolean }>('/execution/capabilities'),
  executionOrders: () => get<ExecutionRequest[]>('/execution/orders'),
  submitOrder: (data: Record<string, unknown>) => post<ExecutionRequest>('/execution/orders', data),
  estimateOrder: (data: Record<string, unknown>) =>
    post<{
      status: string
      total?: number
      message?: string
      breakdown?: Record<string, number>
      broker?: string
      version?: string
    }>('/execution/estimate', data),
  accounts: () => get<InvestmentAccount[]>('/accounts'),
  saveAccount: async (data: Omit<InvestmentAccount, 'id'>, id?: number) =>
    id
      ? (await scopedClient.patch<Envelope<InvestmentAccount>>(`${base}/accounts/${id}`, data)).data
          .data
      : post<InvestmentAccount>('/accounts', data),
  deleteAccount: (id: number) => scopedClient.delete(`${base}/accounts/${id}`),
  holdings: (account_id?: number) => get<InvestmentHolding[]>('/holdings', { account_id }),
  dashboard: (account_id?: number) => get<InvestmentDashboard>('/dashboard', { account_id }),
  saveAsset: async (data: Partial<InvestmentAsset>, id?: number) =>
    id
      ? (await scopedClient.patch<Envelope<InvestmentAsset>>(`${base}/assets/${id}`, data)).data
          .data
      : post<InvestmentAsset>('/assets', data),
  deleteAsset: (id: number) => scopedClient.delete(`${base}/assets/${id}`),
  addTransaction: (data: TransactionInput) => post<InvestmentTransaction>('/transactions', data),
  transactions: (asset_id?: number, offset = 0) =>
    get<InvestmentTransaction[]>('/transactions', { asset_id, offset, limit: 50 }),
  deleteTransaction: (id: number) => scopedClient.delete(`${base}/transactions/${id}`),
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
    scopedClient.patch(`${base}/watchlists/${id}`, { name, category }),
  deleteWatchlist: (id: number) => scopedClient.delete(`${base}/watchlists/${id}`),
  watchItem: (id: number, asset_id: number, stop_price: string, target_price: string) =>
    post(`/watchlists/${id}/items`, { asset_id, stop_price, target_price }),
  deleteWatchItem: (id: number) => scopedClient.delete(`${base}/watch-items/${id}`),
  paperOrders: () => get<InvestmentPaperOrder[]>('/paper/gtt'),
  placePaper: (data: Record<string, unknown>) => post<InvestmentPaperOrder>('/paper/gtt', data),
  cancelPaper: (id: number) => scopedClient.delete(`${base}/paper/gtt/${id}`),
  syncPaper: () => post<{ updated: number; imported: number; errors: string[] }>('/paper/sync', {}),
}
export function investmentError(error: unknown): string {
  return (
    (error as { response?: { data?: { message?: string } } })?.response?.data?.message ||
    'Could not save or load investments. Please try again.'
  )
}
