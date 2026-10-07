import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { investmentApi, investmentError, investmentKeys } from '@/api/investment'
import { AddTransactionDialog } from '@/components/investment/AddTransactionDialog'
import {
  ErrorMessage,
  Field,
  gainClass,
  money,
  percent,
  selectClass,
} from '@/components/investment/common'
import { SymbolSearchInput } from '@/components/portfolio/SymbolSearchInput'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  assetClasses,
  assetFields,
  type AssetClass,
  type InvestmentHolding,
} from '@/types/investment'
import { useInvestmentContext } from './PortfolioIndex'

function PriceImport({ accountId }: { accountId?: number }) {
  const queryClient = useQueryClient()
  const [csv, setCsv] = useState('')
  const [fileError, setFileError] = useState('')
  const save = useMutation({
    mutationFn: () => investmentApi.importPrices(csv, accountId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: investmentKeys.all }),
  })
  return (
    <details className="rounded border p-3 text-sm">
      <summary className="cursor-pointer">Import dated prices / NAV from CSV</summary>
      <p className="my-2 text-muted-foreground">
        Headers: symbol,scheme_code,price,as_of. Use ISO timestamps with timezone, e.g.
        2026-10-01T16:00:00+05:30. Every row must match one instrument in the selected account. All
        rows succeed together.
      </p>
      <input
        aria-label="Price CSV file"
        type="file"
        accept=".csv,text/csv"
        onChange={async (e) => {
          const file = e.target.files?.[0]
          setFileError('')
          if (!file) return
          if (file.size > 256000) {
            setFileError('CSV must be under 256 KB.')
            return
          }
          try {
            setCsv(await file.text())
          } catch {
            setFileError('Could not read this file. Paste the CSV below or choose it again.')
          }
        }}
      />
      <textarea
        aria-label="Price CSV"
        className={`${selectClass} my-2 h-28 font-mono`}
        value={csv}
        onChange={(e) => setCsv(e.target.value)}
      />
      <Button disabled={save.isPending || !csv} onClick={() => save.mutate()}>
        Import valuations
      </Button>
      {save.isError && <ErrorMessage>{investmentError(save.error)}</ErrorMessage>}
      {fileError && <ErrorMessage>{fileError}</ErrorMessage>}
      {save.data && (
        <output className="block mt-2">Imported {save.data.updated} valuations.</output>
      )}
    </details>
  )
}

export default function Stocks() {
  const { assetClass: routeClass } = useParams()
  const navigate = useNavigate()
  const assetClass: AssetClass =
    routeClass && routeClass in assetClasses ? (routeClass as AssetClass) : 'STOCK'
  const isStock = assetClass === 'STOCK'
  const liability = assetClass === 'LOAN' || assetClass === 'OTHER_BORROWING'
  const { accountId, accounts } = useInvestmentContext()
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: investmentKeys.all })
  const rows = useQuery({
    queryKey: ['investment', 'holdings', accountId],
    queryFn: () => investmentApi.holdings(accountId),
    select: (data) => data.filter((row) => row.asset_class === assetClass),
  })
  const [selected, setSelected] = useState<InvestmentHolding>()
  const [assetDialog, setAssetDialog] = useState(false)
  const [editId, setEditId] = useState<number>()
  const [form, setForm] = useState({
    account_id: 0,
    symbol: '',
    name: '',
    exchange: 'NSE' as 'NSE' | 'BSE' | 'MANUAL',
    scheme_code: '',
    details: {} as Record<string, string>,
    notes: '',
    is_watch_only: false,
  })
  const [priceAsset, setPriceAsset] = useState<InvestmentHolding>()
  const [price, setPrice] = useState('')
  const [asOf, setAsOf] = useState('')
  const [historyAsset, setHistoryAsset] = useState<InvestmentHolding>()
  const [offset, setOffset] = useState(0)
  const [confirmDelete, setConfirmDelete] = useState<number>()
  const history = useQuery({
    queryKey: ['investment', 'transactions', historyAsset?.id, offset],
    queryFn: () => investmentApi.transactions(historyAsset?.id, offset),
    enabled: !!historyAsset,
  })
  const save = useMutation({
    mutationFn: () =>
      investmentApi.saveAsset(
        { ...form, asset_class: assetClass, name: form.name || form.symbol },
        editId
      ),
    onSuccess: async () => {
      await invalidate()
      setAssetDialog(false)
    },
  })
  const remove = useMutation({
    mutationFn: investmentApi.deleteAsset,
    onSuccess: async () => {
      await invalidate()
      setAssetDialog(false)
    },
  })
  const savePrice = useMutation({
    mutationFn: () => investmentApi.price(priceAsset?.id ?? 0, price, `${asOf}:00+05:30`),
    onSuccess: async () => {
      await invalidate()
      setPriceAsset(undefined)
    },
  })
  const refresh = useMutation({
    mutationFn: () => investmentApi.refresh(rows.data?.map((row) => row.id)),
    onSuccess: invalidate,
  })
  const deleteTx = useMutation({
    mutationFn: investmentApi.deleteTransaction,
    onSuccess: async () => {
      await invalidate()
      setConfirmDelete(undefined)
    },
  })
  const edit = (row?: InvestmentHolding) => {
    save.reset()
    remove.reset()
    setEditId(row?.id)
    setForm({
      account_id: row?.account_id ?? accountId ?? accounts[0]?.id ?? 0,
      symbol: row?.symbol ?? '',
      name: row?.name ?? '',
      exchange: row?.exchange ?? (isStock ? 'NSE' : 'MANUAL'),
      scheme_code: row?.scheme_code ?? '',
      details: row?.details ?? {},
      notes: row?.notes ?? '',
      is_watch_only: row?.is_watch_only ?? false,
    })
    setAssetDialog(true)
  }
  const setValuation = (row: InvestmentHolding) => {
    savePrice.reset()
    setPriceAsset(row)
    setPrice(row.price ?? '')
    const ist = new Date(Date.now() + 330 * 60_000).toISOString().slice(0, 16)
    setAsOf(ist)
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 justify-between">
        <div>
          <h2 className="text-lg font-semibold">{assetClasses[assetClass]}</h2>
          <p className="text-sm text-muted-foreground">
            {liability
              ? 'Record borrowing as Buy, principal repayment as Sell, and interest paid as Interest. Outstanding balances subtract from net worth.'
              : 'Record purchases, sales and income with a complete transaction history.'}
          </p>
        </div>
        <div className="flex gap-2">
          {isStock && (
            <Button
              variant="outline"
              disabled={refresh.isPending || !rows.data?.length}
              onClick={() => refresh.mutate()}
            >
              {refresh.isPending ? 'Refreshing…' : 'Refresh prices'}
            </Button>
          )}
          <Button disabled={!accounts.length} onClick={() => edit()}>
            {isStock ? 'Add stock' : 'Add asset'}
          </Button>
        </div>
      </div>
      {!isStock && (
        <label className="block text-sm">
          Asset class
          <select
            aria-label="Asset class"
            className={selectClass}
            value={assetClass}
            onChange={(e) => navigate(`/portfolio/assets/${e.target.value}`)}
          >
            {Object.entries(assetClasses)
              .filter(([key]) => key !== 'STOCK')
              .map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
          </select>
        </label>
      )}
      <PriceImport accountId={accountId} />
      {!accounts.length && (
        <p className="rounded border border-dashed p-6 text-sm">
          Add an account above to start recording investments.
        </p>
      )}
      {refresh.isError && <ErrorMessage>{investmentError(refresh.error)}</ErrorMessage>}
      {refresh.data && (
        <output className="block text-sm text-muted-foreground">
          Updated {refresh.data.updated} prices.
          {refresh.data.failed.length > 0 &&
            ` Could not refresh: ${refresh.data.failed.join(', ')}.`}{' '}
          {refresh.data.message}
        </output>
      )}
      {rows.isPending ? (
        <p>Loading holdings…</p>
      ) : rows.isError ? (
        <ErrorMessage>
          {investmentError(rows.error)}{' '}
          <button type="button" onClick={() => rows.refetch()} className="underline">
            Retry
          </button>
        </ErrorMessage>
      ) : rows.data.length === 0 ? (
        <p className="rounded-xl border border-dashed p-8 text-center text-muted-foreground">
          No {assetClasses[assetClass].toLowerCase()} in this account yet.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                {[
                  'Stock / Account',
                  'Quantity',
                  'Average cost',
                  'Investment cost',
                  'Latest price',
                  'Value',
                  'Unrealized P&L',
                  'Actions',
                ].map((h) => (
                  <th key={h} className="p-3 whitespace-nowrap text-left">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.data.map((row) => (
                <tr key={row.id} className="border-t">
                  <td className="p-3 whitespace-nowrap">
                    <strong>{row.symbol}</strong>
                    <p className="text-xs text-muted-foreground">
                      {row.exchange} · {accounts.find((a) => a.id === row.account_id)?.name}
                    </p>
                    {row.is_watch_only && <span className="text-xs">Watching only</span>}
                  </td>
                  <td className="p-3 text-right font-mono">
                    {Number(row.quantity).toLocaleString('en-IN', { maximumFractionDigits: 6 })}
                  </td>
                  <td className="p-3 text-right font-mono whitespace-nowrap">
                    {money(row.average_cost)}
                  </td>
                  <td className="p-3 text-right font-mono whitespace-nowrap">
                    {money(row.invested)}
                  </td>
                  <td className="p-3 whitespace-nowrap">
                    <div className="text-right font-mono">{money(row.price)}</div>
                    <p className="text-[10px] text-muted-foreground">
                      {row.valuation_source.replaceAll('_', ' ')}
                      {row.stale ? ' · stale / unverified time' : ''}
                    </p>
                    {row.price_as_of && (
                      <p className="text-[10px] text-muted-foreground">
                        {new Date(row.price_as_of).toLocaleString('en-IN', {
                          timeZone: 'Asia/Kolkata',
                        })}{' '}
                        IST
                      </p>
                    )}
                  </td>
                  <td className="p-3 text-right font-mono whitespace-nowrap">
                    {money(row.market_value)}
                  </td>
                  <td
                    className={`p-3 text-right font-mono whitespace-nowrap ${gainClass(row.unrealized_gain)}`}
                  >
                    {money(row.unrealized_gain)}
                    <p className="text-xs">{percent(row.return_percent)}</p>
                  </td>
                  <td className="p-3">
                    <div className="flex flex-wrap gap-1 min-w-48">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={row.is_watch_only}
                        onClick={() => setSelected(row)}
                      >
                        Record
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setHistoryAsset(row)
                          setOffset(0)
                          setConfirmDelete(undefined)
                          deleteTx.reset()
                        }}
                      >
                        History
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setValuation(row)}>
                        Price
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => edit(row)}>
                        Edit
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot className="border-t bg-muted/30">
              <tr>
                <td className="p-3 font-medium" colSpan={3}>
                  Total cost
                </td>
                <td className="p-3 text-right font-mono">
                  {money(rows.data.reduce((sum, row) => sum + Number(row.invested), 0))}
                </td>
                <td className="p-3 text-muted-foreground" colSpan={4}>
                  Dashboard totals exclude watch-only and closed holdings.
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {selected && (
        <AddTransactionDialog
          key={selected.id}
          asset={selected}
          onClose={() => setSelected(undefined)}
        />
      )}
      <Dialog open={assetDialog} onOpenChange={setAssetDialog}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {editId ? 'Edit' : 'Add'} {isStock ? 'stock' : 'asset'}
            </DialogTitle>
            <DialogDescription>
              Choose an account and {isStock ? 'exchange symbol' : 'asset identifier'}. Add a
              transaction separately to record ownership.
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              save.mutate()
            }}
          >
            <fieldset disabled={save.isPending || remove.isPending} className="space-y-4">
              <label className="block text-sm">
                Account
                <select
                  className={selectClass}
                  value={form.account_id}
                  onChange={(e) => setForm({ ...form, account_id: Number(e.target.value) })}
                >
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} · {a.broker_label}
                    </option>
                  ))}
                </select>
              </label>
              {isStock && (
                <label className="block text-sm">
                  Exchange
                  <select
                    className={selectClass}
                    value={form.exchange}
                    onChange={(e) =>
                      setForm({ ...form, exchange: e.target.value as 'NSE' | 'BSE', symbol: '' })
                    }
                  >
                    <option>NSE</option>
                    <option>BSE</option>
                  </select>
                </label>
              )}
              {isStock ? (
                <div className="space-y-1">
                  <p className="text-sm">Stock symbol</p>
                  <SymbolSearchInput
                    value={form.symbol}
                    exchange={form.exchange === 'BSE' ? 'BSE' : 'NSE'}
                    onSelect={(symbol) => setForm((old) => ({ ...old, symbol }))}
                  />
                </div>
              ) : (
                <Field
                  label="Asset identifier"
                  value={form.symbol}
                  onChange={(symbol) => setForm({ ...form, symbol })}
                />
              )}
              {assetClass === 'MUTUAL_FUND' && (
                <Field
                  label="Scheme code"
                  value={form.scheme_code}
                  onChange={(scheme_code) => setForm({ ...form, scheme_code })}
                  required={false}
                />
              )}
              {assetFields[assetClass].map((key) => (
                <Field
                  key={key}
                  label={key.replaceAll('_', ' ')}
                  type={key.endsWith('_date') ? 'date' : 'text'}
                  value={form.details[key] ?? ''}
                  onChange={(value) =>
                    setForm({ ...form, details: { ...form.details, [key]: value } })
                  }
                  required={false}
                />
              ))}
              <Field
                label="Display name"
                value={form.name}
                onChange={(name) => setForm({ ...form, name })}
                required={false}
              />
              <Field
                label="Notes"
                value={form.notes}
                onChange={(notes) => setForm({ ...form, notes })}
                required={false}
              />
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.is_watch_only}
                  onChange={(e) => setForm({ ...form, is_watch_only: e.target.checked })}
                />
                Watch only — no recorded holding
              </label>
            </fieldset>
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
                  Delete empty instrument
                </Button>
              )}
              <Button disabled={save.isPending || remove.isPending || !form.symbol}>
                {save.isPending ? 'Saving…' : isStock ? 'Save stock' : 'Save asset'}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!priceAsset}
        onOpenChange={(open) => {
          if (!open) setPriceAsset(undefined)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Set dated price · {priceAsset?.symbol}</DialogTitle>
            <DialogDescription>
              This valuation is labeled manual. It never changes the purchase cost.
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              savePrice.mutate()
            }}
          >
            <Field
              label="Price (₹)"
              value={price}
              onChange={setPrice}
              type="number"
              step="0.0001"
            />
            <Field
              label="Price as of (IST)"
              value={asOf}
              onChange={setAsOf}
              type="datetime-local"
            />
            {savePrice.isError && <ErrorMessage>{investmentError(savePrice.error)}</ErrorMessage>}
            <Button disabled={savePrice.isPending}>Save valuation</Button>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!historyAsset}
        onOpenChange={(open) => {
          if (!open) setHistoryAsset(undefined)
        }}
      >
        <DialogContent className="sm:max-w-3xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Transaction history · {historyAsset?.symbol}</DialogTitle>
            <DialogDescription>
              Trades are ordered by IST timestamp. Deleting an entry rebuilds the holding and will
              be rejected if it creates a historical oversell.
            </DialogDescription>
          </DialogHeader>
          {history.isPending ? (
            <p>Loading transactions…</p>
          ) : history.isError ? (
            <ErrorMessage>{investmentError(history.error)}</ErrorMessage>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      {['Date · IST', 'Action', 'Qty', 'Price', 'Notes', ''].map((label, i) => (
                        <th key={label || String(i)} className="p-2 text-left">
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {history.data?.map((tx) => (
                      <tr key={tx.id} className="border-t">
                        <td className="p-2 whitespace-nowrap">
                          {tx.trade_date} {tx.trade_time}
                        </td>
                        <td className="p-2">{tx.action}</td>
                        <td className="p-2 font-mono">{Number(tx.quantity)}</td>
                        <td className="p-2 font-mono whitespace-nowrap">{money(tx.price)}</td>
                        <td className="p-2">{tx.notes}</td>
                        <td className="p-2">
                          {confirmDelete === tx.id ? (
                            <div className="flex gap-2">
                              <Button
                                size="sm"
                                variant="destructive"
                                disabled={deleteTx.isPending}
                                onClick={() => deleteTx.mutate(tx.id)}
                              >
                                Confirm delete
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => setConfirmDelete(undefined)}
                              >
                                Cancel
                              </Button>
                            </div>
                          ) : (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setConfirmDelete(tx.id)}
                            >
                              Delete
                            </Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {history.data?.length === 0 && (
                  <p className="p-4 text-muted-foreground">No transactions recorded.</p>
                )}
              </div>
              <div className="flex justify-between">
                <Button
                  variant="outline"
                  disabled={offset === 0}
                  onClick={() => setOffset(offset - 50)}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  disabled={(history.data?.length ?? 0) < 50}
                  onClick={() => setOffset(offset + 50)}
                >
                  Next
                </Button>
              </div>
            </>
          )}
          {deleteTx.isError && <ErrorMessage>{investmentError(deleteTx.error)}</ErrorMessage>}
        </DialogContent>
      </Dialog>
    </div>
  )
}
