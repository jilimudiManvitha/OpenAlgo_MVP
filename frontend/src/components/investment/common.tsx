import { type ReactNode, useId } from 'react'
import { Input } from '@/components/ui/input'

export const money = (value: string | number | null | undefined) =>
  value == null
    ? '—'
    : new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: 'INR',
        maximumFractionDigits: 2,
      }).format(Number(value))
export const percent = (value: string | null | undefined) =>
  value == null ? '—' : `${Number(value).toFixed(2)}%`
export const gainClass = (value: string | null) =>
  value == null
    ? ''
    : Number(value) >= 0
      ? 'text-green-600 dark:text-green-400'
      : 'text-red-600 dark:text-red-400'
export const selectClass = 'h-9 rounded-md border bg-background px-2 text-sm w-full'
export function Field({
  label,
  value,
  onChange,
  type = 'text',
  step,
  required = true,
}: {
  label: string
  value: string
  onChange(value: string): void
  type?: string
  step?: string
  required?: boolean
}) {
  const id = useId()
  return (
    <div className="space-y-1">
      <label className="text-sm" htmlFor={id}>
        {label}
      </label>
      <Input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        type={type}
        step={step}
        required={required}
      />
    </div>
  )
}
export function Stat({
  label,
  children,
  detail,
}: {
  label: string
  children: ReactNode
  detail?: string
}) {
  return (
    <div className="rounded-xl border bg-card p-5">
      <p className="text-sm text-muted-foreground">{label}</p>
      <div className="mt-2 text-2xl font-semibold tabular-nums">{children}</div>
      {detail && <p className="mt-1 text-xs text-muted-foreground">{detail}</p>}
    </div>
  )
}
export function ErrorMessage({ children }: { children: ReactNode }) {
  return (
    <p
      role="alert"
      className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
    >
      {children}
    </p>
  )
}
