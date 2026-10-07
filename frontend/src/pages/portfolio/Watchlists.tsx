import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { investmentApi, investmentError, investmentKeys } from '@/api/investment'
import { ErrorMessage, Field, money, selectClass } from '@/components/investment/common'
import { Button } from '@/components/ui/button'
import { useInvestmentContext } from './PortfolioIndex'

const categories = ['Swing', 'Positional', 'Long-term', 'ETFs', 'Mutual Funds', 'Other']
export default function Watchlists() {
  const { accountId, accounts } = useInvestmentContext()
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: investmentKeys.all })
  const watches = useQuery({
    queryKey: ['investment', 'watchlists'],
    queryFn: investmentApi.watchlists,
  })
  const assets = useQuery({
    queryKey: ['investment', 'holdings', accountId],
    queryFn: () => investmentApi.holdings(accountId),
  })
  const orders = useQuery({ queryKey: ['investment', 'paper'], queryFn: investmentApi.paperOrders })
  const [watchId, setWatchId] = useState(0)
  const [name, setName] = useState('')
  const [category, setCategory] = useState('Long-term')
  const [editId, setEditId] = useState<number>()
  const [assetId, setAssetId] = useState(0)
  const [stop, setStop] = useState('')
  const [target, setTarget] = useState('')
  const watch = watches.data?.find((w) => w.id === watchId)
  const save = useMutation({
    mutationFn: () =>
      editId
        ? investmentApi.editWatchlist(editId, name, category)
        : investmentApi.saveWatchlist(name, category),
    onSuccess: async () => {
      await invalidate()
      setName('')
      setEditId(undefined)
    },
  })
  const remove = useMutation({
    mutationFn: investmentApi.deleteWatchlist,
    onSuccess: async () => {
      await invalidate()
      setWatchId(0)
    },
  })
  const add = useMutation({
    mutationFn: () => investmentApi.watchItem(watchId, assetId, stop, target),
    onSuccess: invalidate,
  })
  const removeItem = useMutation({
    mutationFn: investmentApi.deleteWatchItem,
    onSuccess: invalidate,
  })
  const sync = useMutation({ mutationFn: investmentApi.syncPaper, onSuccess: invalidate })
  const cancel = useMutation({ mutationFn: investmentApi.cancelPaper, onSuccess: invalidate })
  const [order, setOrder] = useState({
    asset_id: '',
    action: 'BUY',
    quantity: '',
    direction: 'below',
    trigger_price: '',
    limit_price: '',
    reference_price: '',
    request_key: crypto.randomUUID(),
  })
  const updateOrder = (key: string, value: string) =>
    setOrder((old) => ({ ...old, [key]: value, request_key: crypto.randomUUID() }))
  const place = useMutation({
    mutationFn: () =>
      investmentApi.placePaper({
        ...order,
        asset_id: Number(order.asset_id),
        watchlist_id: watchId,
      }),
    onSuccess: invalidate,
  })
  const errors = [
    watches,
    assets,
    orders,
    save,
    remove,
    add,
    removeItem,
    sync,
    cancel,
    place,
  ].filter((q) => q.isError)
  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold">Categorized watchlists & paper GTT</h2>
      <p className="text-sm text-muted-foreground">
        Watching does not create a purchase. Watch SL/TP values are tracking-only, including
        mutual-fund NAV thresholds. A recorded price cannot establish a missed offline crossing.
      </p>
      {errors.map((q, i) => (
        <ErrorMessage key={i}>{investmentError(q.error)}</ErrorMessage>
      ))}
      <form
        className="flex flex-wrap gap-3 items-end rounded border p-4"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <Field label="Watchlist name" value={name} onChange={setName} />
        <label className="text-sm">
          Category
          <select
            className={selectClass}
            aria-label="Watchlist category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            {categories.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <Button disabled={save.isPending}>{editId ? 'Save watchlist' : 'Create watchlist'}</Button>
      </form>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          Selected watchlist
          <select
            className={selectClass}
            value={watchId}
            onChange={(e) => {
              setWatchId(Number(e.target.value))
              setOrder((old) => ({ ...old, asset_id: '', request_key: crypto.randomUUID() }))
              place.reset()
            }}
          >
            <option value={0}>Choose a list</option>
            {watches.data?.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name} · {w.category}
              </option>
            ))}
          </select>
        </label>
        {watch && (
          <>
            <Button
              variant="outline"
              onClick={() => {
                setEditId(watch.id)
                setName(watch.name)
                setCategory(watch.category)
              }}
            >
              Rename / categorize
            </Button>
            <Button
              variant="outline"
              disabled={remove.isPending}
              onClick={() => remove.mutate(watch.id)}
            >
              Delete list
            </Button>
          </>
        )}
      </div>
      {watch && (
        <>
          <form
            className="flex flex-wrap gap-3 items-end rounded border p-4"
            onSubmit={(e) => {
              e.preventDefault()
              add.mutate()
            }}
          >
            <label className="text-sm">
              Instrument
              <select
                className={selectClass}
                aria-label="Watch instrument"
                value={assetId}
                onChange={(e) => setAssetId(Number(e.target.value))}
              >
                <option value={0}>Choose an instrument</option>
                {assets.data?.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.symbol} · {accounts.find((ac) => ac.id === a.account_id)?.name}
                  </option>
                ))}
              </select>
            </label>
            <Field
              label="Watch stop (optional)"
              type="number"
              step="0.0001"
              value={stop}
              onChange={setStop}
              required={false}
            />
            <Field
              label="Watch target (optional)"
              type="number"
              step="0.0001"
              value={target}
              onChange={setTarget}
              required={false}
            />
            <Button disabled={add.isPending || !assetId}>Add / update watch</Button>
          </form>
          <div className="grid md:grid-cols-2 gap-3">
            {watch.items
              .filter((i) => !accountId || i.asset.account_id === accountId)
              .map((i) => (
                <article key={i.id} className="rounded border p-4 space-y-2">
                  <strong>{i.asset.symbol}</strong>
                  <p className="text-sm">
                    {i.asset.is_watch_only ? 'Watch only' : `${i.asset.quantity} recorded units`} ·{' '}
                    {money(i.asset.price)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {i.asset.valuation_source} · {i.asset.price_as_of ?? 'No price date'}
                    {i.asset.stale ? ' · stale / unverified' : ''}
                  </p>
                  <p className="text-sm">{i.observation}</p>
                  <p className="text-xs">
                    Stop {money(i.stop_price)} · Target {money(i.target_price)}
                  </p>
                  <div className="flex gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setAssetId(i.asset_id)
                        setStop(i.stop_price ?? '')
                        setTarget(i.target_price ?? '')
                      }}
                    >
                      Edit thresholds
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={removeItem.isPending}
                      onClick={() => removeItem.mutate(i.id)}
                    >
                      Remove watch
                    </Button>
                  </div>
                </article>
              ))}
          </div>
          {!watch.items.length && (
            <p>
              No instruments watched. Add an instrument in Stocks or Other assets, then choose it
              above.
            </p>
          )}
          <details className="rounded border p-4">
            <summary className="font-medium cursor-pointer">
              Create a paper GTT for this category
            </summary>
            <p className="text-sm text-muted-foreground my-3">
              Uses the existing Sandbox balance, CNC holdings and GTT monitor. Only confirmed fills
              become ledger transactions. Enter the reference price explicitly; it sets the trigger
              direction and is not an execution price. A limit order may remain unfilled. No live
              broker order is sent.
            </p>
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault()
                place.mutate()
              }}
            >
              <label className="block text-sm">
                Paper instrument
                <select
                  className={selectClass}
                  value={order.asset_id}
                  onChange={(e) => updateOrder('asset_id', e.target.value)}
                  required
                >
                  <option value="">Choose stock / ETF in a paper account</option>
                  {watch.items
                    .filter(
                      (i) =>
                        i.asset.asset_class === 'STOCK' &&
                        accounts.some((a) => a.id === i.asset.account_id && a.kind === 'paper')
                    )
                    .map((i) => (
                      <option key={i.id} value={i.asset_id}>
                        {i.asset.symbol} · {accounts.find((a) => a.id === i.asset.account_id)?.name}
                      </option>
                    ))}
                </select>
              </label>
              <div className="grid sm:grid-cols-2 gap-3">
                <label className="text-sm">
                  Action
                  <select
                    className={selectClass}
                    value={order.action}
                    onChange={(e) => updateOrder('action', e.target.value)}
                  >
                    <option>BUY</option>
                    <option>SELL</option>
                  </select>
                </label>
                <label className="text-sm">
                  Trigger direction
                  <select
                    className={selectClass}
                    value={order.direction}
                    onChange={(e) => updateOrder('direction', e.target.value)}
                  >
                    <option value="below">At or below reference</option>
                    <option value="above">At or above reference</option>
                  </select>
                </label>
                {(['quantity', 'reference_price', 'trigger_price', 'limit_price'] as const).map(
                  (k) => (
                    <Field
                      key={k}
                      label={k.replaceAll('_', ' ')}
                      type="number"
                      step={k === 'quantity' ? '1' : '0.01'}
                      value={order[k]}
                      onChange={(v) => updateOrder(k, v)}
                    />
                  )
                )}
              </div>
              <Button disabled={place.isPending}>Create paper GTT</Button>
              {place.data && (
                <output className="block text-sm">
                  {place.data.gtt_id ?? `Request ${place.data.id}`} · {place.data.status} ·{' '}
                  {place.data.message}
                </output>
              )}
            </form>
          </details>
        </>
      )}
      <section className="space-y-3">
        <div className="flex flex-wrap justify-between gap-3">
          <h3 className="font-semibold">Portfolio paper triggers</h3>
          <Button variant="outline" disabled={sync.isPending} onClick={() => sync.mutate()}>
            Refresh triggers & import confirmed fills
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          The existing Sandbox monitor continues while this page is closed. Refresh reconciles
          committed triggers and fills after a restart; uncertain dispatches are never resubmitted
          automatically.
        </p>
        {sync.data && (
          <output className="block text-sm">
            Updated {sync.data.updated}; imported {sync.data.imported} fills.
            {sync.data.errors.map((e) => (
              <p key={e}>{e}</p>
            ))}
          </output>
        )}
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr>
                {['Instrument', 'Category', 'Trigger', 'Status', 'Details', ''].map((c, i) => (
                  <th key={`${c}-${i}`} className="p-2 text-left">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {orders.data
                ?.filter((o) => !accountId || assets.data?.some((a) => a.id === o.asset_id))
                .map((o) => {
                  const data = JSON.parse(o.payload) as Record<string, string | number>
                  return (
                    <tr key={o.id} className="border-t">
                      <td className="p-2">
                        {data.symbol} · {data.action} {data.quantity}
                      </td>
                      <td className="p-2">
                        {watches.data?.find((w) => w.id === o.watchlist_id)?.name}
                      </td>
                      <td className="p-2">
                        {data.triggerprice_sl ?? data.triggerprice_tg} · limit {data.price}
                      </td>
                      <td className="p-2">{o.status}</td>
                      <td className="p-2">
                        {o.gtt_id}
                        <p className="text-xs">{o.message}</p>
                      </td>
                      <td className="p-2">
                        {o.status === 'active' && (
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={cancel.isPending}
                            onClick={() => cancel.mutate(o.id)}
                          >
                            Cancel
                          </Button>
                        )}
                      </td>
                    </tr>
                  )
                })}
            </tbody>
          </table>
          {!orders.data?.length && <p className="p-3">No portfolio paper triggers.</p>}
        </div>
      </section>
    </div>
  )
}
