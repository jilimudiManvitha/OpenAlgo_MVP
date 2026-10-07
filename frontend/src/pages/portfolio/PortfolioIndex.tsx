import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useOutletContext } from 'react-router'
import { investmentApi, investmentError, investmentKeys } from '@/api/investment'
import { ErrorMessage, Field, selectClass } from '@/components/investment/common'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import type { InvestmentAccount } from '@/types/investment'

interface PortfolioContext {
  accountId?: number
  accounts: InvestmentAccount[]
}
export const useInvestmentContext = () => useOutletContext<PortfolioContext>()
export default function PortfolioIndex() {
  const mode = useThemeStore((s) => s.appMode)
  const user = useAuthStore((s) => s.user)
  return <PortfolioScope key={`${user?.username}:${user?.broker}:${mode}`} />
}
function PortfolioScope() {
  const [client] = useState(() => new QueryClient())
  useEffect(
    () => () => {
      void client.cancelQueries()
      client.clear()
    },
    [client]
  )
  return (
    <QueryClientProvider client={client}>
      <PortfolioContent />
    </QueryClientProvider>
  )
}
function PortfolioContent() {
  const mode = useThemeStore((s) => s.appMode)
  const accountKind = mode === 'analyzer' ? 'paper' : 'live'
  const { pathname } = useLocation()
  const queryClient = useQueryClient()
  const accounts = useQuery({ queryKey: investmentKeys.accounts, queryFn: investmentApi.accounts })
  const [accountId, setAccountId] = useState<number>()
  const [open, setOpen] = useState(false)
  const [editId, setEditId] = useState<number>()
  const [name, setName] = useState('')
  const [broker, setBroker] = useState('Manual')
  const [kind, setKind] = useState<'paper' | 'live'>(accountKind)
  const save = useMutation({
    mutationFn: () => investmentApi.saveAccount({ name, broker_label: broker, kind }, editId),
    onSuccess: async (row) => {
      await queryClient.invalidateQueries({ queryKey: investmentKeys.all })
      setAccountId(row.id)
      setOpen(false)
    },
  })
  const remove = useMutation({
    mutationFn: investmentApi.deleteAccount,
    onSuccess: async () => {
      setAccountId(undefined)
      await queryClient.invalidateQueries({ queryKey: investmentKeys.all })
      setOpen(false)
    },
  })
  const showAccount = (row?: InvestmentAccount) => {
    setEditId(row?.id)
    setName(row?.name ?? '')
    setBroker(row?.broker_label ?? 'Manual')
    setKind(row?.kind ?? accountKind)
    save.reset()
    remove.reset()
    setOpen(true)
  }
  return (
    <section className="mx-auto max-w-7xl space-y-6 p-4 md:p-6">
      <header className="flex flex-wrap justify-between items-start gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Investment Portfolio</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {mode === 'analyzer' ? 'Sandbox' : 'Live'} accounts, purchases and dated valuations.
          </p>
        </div>
        <Button onClick={() => showAccount()}>Add account</Button>
      </header>
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="investment-account" className="text-sm font-medium">
          My accounts
        </label>
        <select
          id="investment-account"
          className={`${selectClass} max-w-64`}
          value={accountId ?? ''}
          onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : undefined)}
        >
          <option value="">All accounts</option>
          {accounts.data?.map((row) => (
            <option key={row.id} value={row.id}>
              {row.name} · {row.broker_label}
            </option>
          ))}
        </select>
        {accountId && (
          <Button
            variant="outline"
            onClick={() => showAccount(accounts.data?.find((row) => row.id === accountId))}
          >
            Manage account
          </Button>
        )}
      </div>
      <nav aria-label="Portfolio pages" className="flex flex-wrap gap-4 border-b pb-3">
        {[
          ['/portfolio', 'Dashboard'],
          ['/portfolio/stocks', 'Stocks & ETFs'],
          ['/portfolio/assets/MUTUAL_FUND', 'Other assets'],
          ['/portfolio/reports', 'Reports'],
          ['/portfolio/watchlists', 'Watchlists & orders'],
        ].map(([to, label]) => (
          <NavLink
            key={to}
            to={to}
            end
            className={({ isActive }) =>
              isActive || (to.includes('/assets/') && pathname.startsWith('/portfolio/assets/'))
                ? 'font-semibold text-primary'
                : 'text-muted-foreground'
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
      {accounts.isError ? (
        <ErrorMessage>
          {investmentError(accounts.error)}{' '}
          <button type="button" className="underline" onClick={() => accounts.refetch()}>
            Retry
          </button>
        </ErrorMessage>
      ) : accounts.isPending ? (
        <p>Loading accounts…</p>
      ) : (
        <Outlet context={{ accountId, accounts: accounts.data }} />
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editId ? 'Manage account' : 'Add account'}</DialogTitle>
            <DialogDescription>
              Broker labels organize your records. Recording a transaction does not submit an order.
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              save.mutate()
            }}
          >
            <Field label="Account name" value={name} onChange={setName} />
            <Field label="Broker label" value={broker} onChange={setBroker} />
            <label className="block text-sm">
              Account kind
              <select
                className={selectClass}
                value={kind}
                disabled
                onChange={(e) => setKind(e.target.value as typeof kind)}
              >
                <option value="paper">Paper</option>
                <option value="live">Live investments</option>
              </select>
            </label>
            {(save.isError || remove.isError) && (
              <ErrorMessage>{investmentError(save.error ?? remove.error)}</ErrorMessage>
            )}
            <div className="flex justify-between gap-2">
              {editId && (
                <Button
                  type="button"
                  variant="destructive"
                  disabled={remove.isPending || save.isPending}
                  onClick={() => remove.mutate(editId)}
                >
                  Delete empty account
                </Button>
              )}
              <Button disabled={save.isPending || remove.isPending}>
                {save.isPending ? 'Saving…' : 'Save account'}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  )
}
