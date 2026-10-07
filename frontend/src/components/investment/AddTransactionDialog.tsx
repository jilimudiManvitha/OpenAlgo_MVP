import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { investmentApi, investmentError, investmentKeys } from '@/api/investment'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { chargeFields, type InvestmentHolding, type TransactionInput } from '@/types/investment'
import { ErrorMessage, Field, money, selectClass } from './common'

export function AddTransactionDialog({
  asset,
  onClose,
}: {
  asset: InvestmentHolding
  onClose(): void
}) {
  const queryClient = useQueryClient()
  const liability = asset.asset_class === 'LOAN' || asset.asset_class === 'OTHER_BORROWING'
  const [more, setMore] = useState(false)
  const [notice, setNotice] = useState('')
  const [estimatedFor, setEstimatedFor] = useState('')
  const [form, setForm] = useState<TransactionInput>(() => ({
    asset_id: asset.id,
    action: 'BUY',
    quantity: '',
    price: '',
    trade_date: new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Kolkata',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(new Date()),
    trade_time: '09:30',
    notes: '',
    brokerage: '0',
    stt: '0',
    gst: '0',
    stamp_duty: '0',
    sebi: '0',
    exchange_charges: '0',
    corporate_ratio: '',
  }))
  const signature = [form.action, form.quantity, form.price, form.trade_date].join(':')
  const staleEstimate = Boolean(estimatedFor && estimatedFor !== signature)
  const update = (key: keyof TransactionInput, value: string) =>
    setForm((old) => ({ ...old, [key]: value }))
  const save = useMutation({
    mutationFn: () => investmentApi.addTransaction(form),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: investmentKeys.all })
      if (more) {
        setNotice('Transaction recorded. Enter the next transaction.')
        setEstimatedFor('')
        setForm((old) => ({
          ...old,
          quantity: '',
          price: '',
          notes: '',
          brokerage: '0',
          stt: '0',
          gst: '0',
          stamp_duty: '0',
          sebi: '0',
          exchange_charges: '0',
        }))
      } else onClose()
    },
  })
  const estimate = useMutation({
    mutationFn: () => investmentApi.estimateOrder({ ...form, kind: 'order' }),
    onSuccess: (result) => {
      if (result.status !== 'estimated' || !result.breakdown) {
        setNotice(result.message || 'Charge estimate unavailable.')
        return
      }
      setEstimatedFor(signature)
      const c = result.breakdown
      setForm((old) => ({
        ...old,
        brokerage: String(c.brokerage),
        stt: String(c.stt),
        gst: String(c.gst),
        stamp_duty: String(c.stamp),
        sebi: String(c.sebi),
        exchange_charges: String(Number((c.exchange + c.ipft + c.clearing).toFixed(2))),
        notes:
          `${old.notes} [Estimated charges: ${result.broker}, ${result.version}; excludes DP/account charges]`.trim(),
      }))
      setNotice(
        'Estimated charges applied for one executed delivery order. Review against the contract note when available.'
      )
    },
  })
  const amount = Number(form.quantity) * Number(form.price)
  const charges = chargeFields.reduce((sum, name) => sum + Number(form[name]), 0)
  const net = form.action === 'BUY' ? amount + charges : amount - charges
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !save.isPending) onClose()
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Record transaction · {asset.symbol}</DialogTitle>
          <DialogDescription>
            Bookkeeping entry in the selected account. Trade date and time are in IST.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            setNotice('')
            save.mutate()
          }}
          className="space-y-4"
        >
          <fieldset disabled={save.isPending || estimate.isPending} className="space-y-4">
            <label className="block text-sm">
              Action
              <select
                aria-label="Action"
                className={selectClass}
                value={form.action}
                onChange={(e) => {
                  update('action', e.target.value)
                  if (estimatedFor && !['BUY', 'SELL'].includes(e.target.value)) {
                    setEstimatedFor('')
                    setForm((old) => ({
                      ...old,
                      brokerage: '0',
                      stt: '0',
                      gst: '0',
                      stamp_duty: '0',
                      sebi: '0',
                      exchange_charges: '0',
                    }))
                    setNotice('Charges cleared for the new transaction type.')
                  }
                  if (e.target.value === 'CORPORATE_ACTION')
                    setForm((old) => ({
                      ...old,
                      action: 'CORPORATE_ACTION',
                      quantity: '1',
                      price: '0',
                      brokerage: '0',
                      stt: '0',
                      gst: '0',
                      stamp_duty: '0',
                      sebi: '0',
                      exchange_charges: '0',
                    }))
                }}
              >
                <option value="BUY">{liability ? 'Borrow principal' : 'Buy'}</option>
                <option value="SELL">{liability ? 'Repay principal' : 'Sell'}</option>
                {!liability && <option value="DIVIDEND">Dividend</option>}
                <option value="INTEREST">{liability ? 'Interest paid' : 'Interest'}</option>
                {!liability && <option value="CORPORATE_ACTION">Unit split / consolidation</option>}
              </select>
            </label>
            <div className="grid grid-cols-2 gap-4">
              <Field
                label="Trade date (IST)"
                type="date"
                value={form.trade_date}
                onChange={(v) => update('trade_date', v)}
              />
              <Field
                label="Trade time (IST)"
                type="time"
                step="1"
                value={form.trade_time}
                onChange={(v) => update('trade_time', v)}
              />
              <Field
                label="Quantity"
                type="number"
                step="0.000001"
                value={form.quantity}
                onChange={(v) => update('quantity', v)}
              />
              <Field
                label={
                  form.action === 'DIVIDEND' || form.action === 'INTEREST'
                    ? 'Cash amount per unit (₹)'
                    : 'Price per unit (₹)'
                }
                type="number"
                step="0.0001"
                value={form.price}
                onChange={(v) => update('price', v)}
              />
            </div>
            {form.action === 'CORPORATE_ACTION' && (
              <div className="space-y-2">
                <Field
                  label="New shares per old share"
                  type="number"
                  step="0.000001"
                  value={form.corporate_ratio ?? ''}
                  onChange={(v) => update('corporate_ratio', v)}
                />
                <p className="text-xs text-muted-foreground">
                  Example: 2 for a two-for-one split. Quantity must be 1, price and charges 0.
                  Describe the action in notes.
                </p>
              </div>
            )}
            {asset.asset_class === 'STOCK' && (form.action === 'BUY' || form.action === 'SELL') && (
              <Button
                type="button"
                variant="outline"
                disabled={!form.quantity || !form.price || estimate.isPending}
                onClick={() => estimate.mutate()}
              >
                Apply broker charge estimate
              </Button>
            )}
            <details className="rounded border p-3">
              <summary className="text-sm cursor-pointer">
                Detailed charges · {money(charges)}
              </summary>
              <div className="grid grid-cols-2 gap-3 mt-3">
                {chargeFields.map((name) => (
                  <Field
                    key={name}
                    label={name.replaceAll('_', ' ').toUpperCase()}
                    type="number"
                    step="0.0001"
                    value={form[name]}
                    onChange={(v) => update(name, v)}
                  />
                ))}
              </div>
            </details>
            <div className="flex justify-between text-sm">
              <span>Amount: {money(amount)}</span>
              <strong>Net amount: {money(net)}</strong>
            </div>
            <Field
              label="Notes"
              value={form.notes}
              onChange={(v) => update('notes', v)}
              required={form.action === 'CORPORATE_ACTION'}
            />
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={more} onChange={(e) => setMore(e.target.checked)} />
              Add another transaction after saving
            </label>
          </fieldset>
          {estimate.isError && <ErrorMessage>{investmentError(estimate.error)}</ErrorMessage>}
          {save.isError && <ErrorMessage>{investmentError(save.error)}</ErrorMessage>}
          {staleEstimate && (
            <ErrorMessage>
              Trade details changed. Apply the charge estimate again before saving.
            </ErrorMessage>
          )}
          {notice && <output className="block text-sm text-green-600">{notice}</output>}
          <Button disabled={save.isPending || estimate.isPending || staleEstimate}>
            {save.isPending ? 'Saving…' : 'Record transaction'}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
