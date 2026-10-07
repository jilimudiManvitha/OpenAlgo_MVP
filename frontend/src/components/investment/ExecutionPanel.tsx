import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { investmentApi, investmentError, investmentKeys, investmentScope } from '@/api/investment'
import { ErrorMessage, Field, money, selectClass } from '@/components/investment/common'
import { Button } from '@/components/ui/button'
import { useInvestmentContext } from '@/pages/portfolio/PortfolioIndex'

export function ExecutionPanel() {
  const { accountId, accounts } = useInvestmentContext()
  const client = useQueryClient()
  const { mode, broker } = investmentScope()
  const label = mode === 'paper' ? 'Sandbox' : 'Live'
  const assets = useQuery({
    queryKey: ['investment', 'holdings', accountId],
    queryFn: () => investmentApi.holdings(accountId),
  })
  const capabilities = useQuery({
    queryKey: ['investment', 'execution-capabilities'],
    queryFn: investmentApi.executionCapabilities,
  })
  const history = useQuery({
    queryKey: ['investment', 'execution-orders'],
    queryFn: investmentApi.executionOrders,
  })
  const [form, setForm] = useState({
    asset_id: '',
    kind: 'order',
    action: 'BUY',
    quantity: '',
    price: '',
    trigger_price: '',
    reference_price: '',
    request_key: crypto.randomUUID(),
  })
  const [review, setReview] = useState(false)
  const estimate = useMutation({
    mutationFn: () => investmentApi.estimateOrder({ ...form, asset_id: Number(form.asset_id) }),
    onSuccess: () => setReview(true),
  })
  const submit = useMutation({
    mutationFn: () =>
      investmentApi.submitOrder({ ...form, asset_id: Number(form.asset_id), confirm: true }),
    onSuccess: () => client.invalidateQueries({ queryKey: investmentKeys.all }),
  })
  const update = (key: string, value: string) => {
    setForm((old) => ({ ...old, [key]: value, request_key: crypto.randomUUID() }))
    setReview(false)
    estimate.reset()
    submit.reset()
  }
  const asset = assets.data?.find((row) => row.id === Number(form.asset_id))
  return (
    <section className="space-y-3 rounded border p-4">
      <h3 className="font-semibold">
        {label} orders · {broker}
      </h3>
      <p className="text-sm text-muted-foreground">
        Place delivery limit orders for stocks and ETFs.{' '}
        {mode === 'live'
          ? 'Confirmed Live orders are sent to your broker.'
          : 'Sandbox orders use your simulated balance.'}{' '}
        An accepted order is not a fill. Record confirmed fills in the ledger using the broker order
        book; existing paper GTTs have their own fill import below.
      </p>
      {capabilities.data && !capabilities.data.gtt && (
        <p className="text-sm">
          Native Live GTT is unavailable for this broker’s current adapter. Regular orders are
          available.
        </p>
      )}
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          estimate.mutate()
        }}
      >
        <fieldset className="space-y-3" disabled={estimate.isPending || submit.isPending}>
          <label className="block text-sm">
            Instrument
            <select
              aria-label="Order instrument"
              required
              className={selectClass}
              value={form.asset_id}
              onChange={(e) => update('asset_id', e.target.value)}
            >
              <option value="">Choose a stock / ETF</option>
              {assets.data
                ?.filter((row) => row.asset_class === 'STOCK')
                .map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.symbol} · {accounts.find((a) => a.id === row.account_id)?.name}
                  </option>
                ))}
            </select>
          </label>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-sm">
              Order type
              <select
                aria-label="Order type"
                className={selectClass}
                value={form.kind}
                onChange={(e) => update('kind', e.target.value)}
              >
                <option value="order">Limit order</option>
                <option value="gtt" disabled={!capabilities.data?.gtt}>
                  Single GTT
                </option>
              </select>
            </label>
            <label className="text-sm">
              Action
              <select
                aria-label="Order action"
                className={selectClass}
                value={form.action}
                onChange={(e) => update('action', e.target.value)}
              >
                <option>BUY</option>
                <option>SELL</option>
              </select>
            </label>
            <Field
              label="Order quantity"
              type="number"
              step="1"
              value={form.quantity}
              onChange={(v) => update('quantity', v)}
            />
            <Field
              label="Order limit price"
              type="number"
              step="0.01"
              value={form.price}
              onChange={(v) => update('price', v)}
            />
            {form.kind === 'gtt' && (
              <>
                <Field
                  label="GTT trigger price"
                  type="number"
                  step="0.01"
                  value={form.trigger_price}
                  onChange={(v) => update('trigger_price', v)}
                />
                <Field
                  label="GTT reference price"
                  type="number"
                  step="0.01"
                  value={form.reference_price}
                  onChange={(v) => update('reference_price', v)}
                />
              </>
            )}
          </div>
          <Button disabled={estimate.isPending || submit.isPending}>Review {label} order</Button>
        </fieldset>
      </form>
      {review && (
        <div className="space-y-2 rounded border p-3" aria-live="polite">
          <p>
            {label} · {broker} · {form.action} {form.quantity} {asset?.symbol} · CNC · limit{' '}
            {money(form.price)}
            {form.kind === 'gtt' ? ` · GTT trigger ${form.trigger_price}` : ''}
          </p>
          <p className="text-sm">
            {estimate.data?.status === 'estimated'
              ? `Estimated charges: ${money(estimate.data.total)} at the limit price, excluding DP and account charges. Final fills and contract-note charges may differ.`
              : `Charge estimate unavailable: ${estimate.data?.message}`}
          </p>
          <Button disabled={submit.isPending || submit.isSuccess} onClick={() => submit.mutate()}>
            {submit.isPending
              ? 'Submitting…'
              : `Confirm ${label} ${form.kind === 'gtt' ? 'GTT' : 'order'}`}
          </Button>
          {submit.data && (
            <p>
              {submit.data.status} · {submit.data.external_id ?? 'No confirmed broker ID'} ·{' '}
              {submit.data.message}
            </p>
          )}
        </div>
      )}
      {[assets, capabilities, history, estimate, submit]
        .filter((q) => q.isError)
        .map((q, i) => (
          <ErrorMessage key={i}>{investmentError(q.error)}</ErrorMessage>
        ))}
      <div className="flex flex-wrap gap-3">
        <Button variant="outline" onClick={() => history.refetch()}>
          Refresh requests
        </Button>
        <Button asChild variant="outline">
          <Link to="/orderbook">Manage orders & GTTs</Link>
        </Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              {['Created', 'Instrument', 'Type', 'Request outcome', 'Broker ID'].map((h) => (
                <th key={h} className="p-2 text-left">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {history.data
              ?.filter((row) => !accountId || assets.data?.some((a) => a.id === row.asset_id))
              .map((row) => {
                const order = JSON.parse(row.payload)
                return (
                  <tr key={row.id} className="border-t">
                    <td className="p-2">{row.created_at}</td>
                    <td className="p-2">
                      {order.symbol} · {order.action} {order.quantity}
                    </td>
                    <td className="p-2">{row.kind}</td>
                    <td className="p-2">
                      {row.status}
                      <p className="text-xs">{row.message}</p>
                    </td>
                    <td className="p-2">{row.external_id ?? '—'}</td>
                  </tr>
                )
              })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
