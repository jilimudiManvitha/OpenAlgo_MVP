import {
  Activity,
  ArrowRight,
  Copy,
  Network,
  Plus,
  RefreshCw,
  ShieldCheck,
  Square,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { webClient } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'

type Child = {
  id: string
  name: string
  broker: string
  client_id: string
  enabled: boolean
  health: string
  copy_mode: string
  multiplier: number
  max_quantity: number
  max_order_value: number
  max_daily_value: number
  max_daily_loss: number
  max_position_quantity: number
  symbols: string[]
  fast_symbols: string[]
  verified_until: number
}
type Attempt = {
  id: string
  account_id: string
  master_orderid: string
  action: string
  status: string
  order: { symbol: string; exchange: string; action: string; quantity: number; pricetype: string }
  broker_orderid: string
  message: string
  created: number
  dispatch_ms: number | null
  response_ms: number | null
  estimated_charges: Record<string, number> | null
  filled: number
  average_price: number
}
type State = {
  mode: string
  broker: string
  armed: boolean
  killed: boolean
  note: string
  heartbeat: number
  accounts: Child[]
  attempts: Attempt[]
  audit: { action: string; detail: string; created: number }[]
  latency: { p50: number | null; p95: number | null; p99: number | null; samples: number }
}
const empty: Omit<Child, 'id' | 'health' | 'verified_until'> = {
  name: '',
  broker: 'fyers',
  client_id: '',
  enabled: true,
  copy_mode: 'fill',
  multiplier: 1,
  max_quantity: 1000,
  max_order_value: 100000,
  max_daily_value: 500000,
  max_daily_loss: 5000,
  max_position_quantity: 2000,
  symbols: ['NSE:SBIN'],
  fast_symbols: [],
}
const selectClass = 'flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm'
const money = (n: number) =>
  new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(n)
const stamp = (n: number) => new Date(n * 1000).toLocaleTimeString('en-IN', { hour12: false })
function errorText(e: unknown) {
  const x = e as { response?: { data?: { message?: string } }; message?: string }
  return x.response?.data?.message || x.message || 'Request failed'
}
function Status({ value }: { value: string }) {
  return (
    <Badge
      variant={
        ['READY', 'COMPLETE', 'ACKNOWLEDGED'].includes(value)
          ? 'default'
          : ['UNKNOWN', 'REJECTED', 'DEGRADED', 'AUTH_REQUIRED'].includes(value)
            ? 'destructive'
            : 'secondary'
      }
    >
      {value.replaceAll('_', ' ')}
    </Badge>
  )
}

export default function TradeCopier() {
  const { user } = useAuthStore()
  const broker = user?.broker
  const appMode = useThemeStore((s) => s.appMode)
  return (
    <Copier
      key={`${user?.username}:${broker}:${appMode}`}
      broker={broker || ''}
      mode={appMode === 'analyzer' ? 'paper' : 'live'}
    />
  )
}

function Copier({ broker, mode }: { broker: string; mode: string }) {
  const [state, setState] = useState<State | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState<Child | 'new' | null>(null)
  const [confirm, setConfirm] = useState<'arm' | Attempt | null>(null)
  const [resolvedOrderId, setResolvedOrderId] = useState('')
  const [tab, setTab] = useState<'activity' | 'audit'>('activity')
  const [filter, setFilter] = useState('all')
  const params = { mode, broker }
  const read = async () => {
    const r = await webClient.get('/trade-copier/api/state', { params })
    setState(r.data.data)
  }
  useEffect(() => {
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const r = await webClient.get('/trade-copier/api/state', { params: { mode, broker } })
        if (!disposed) {
          setState(r.data.data)
          setError('')
        }
      } catch (e) {
        if (!disposed) setError(errorText(e))
      }
      if (!disposed) timer = setTimeout(poll, 3000)
    }
    void poll()
    return () => {
      disposed = true
      clearTimeout(timer)
    }
  }, [mode, broker])
  const act = async (path: string, data = {}) => {
    setBusy(true)
    setError('')
    try {
      await webClient.post(`/trade-copier/api/${path}`, data, { params })
      await read()
      setConfirm(null)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const children = state?.accounts || []
  const attempts = state?.attempts || []
  const unresolved = attempts.filter((a) => a.status === 'UNKNOWN').length
  const ready = children.filter(
    (a) => a.enabled && a.health === 'READY' && a.verified_until * 1000 > Date.now()
  ).length
  const byMaster = new Map<string, Attempt[]>()
  for (const a of attempts.filter((a) => filter === 'all' || a.account_id === filter)) {
    const rows = byMaster.get(a.master_orderid) || []
    rows.push(a)
    byMaster.set(a.master_orderid, rows)
  }
  const childName = (id: string) => children.find((c) => c.id === id)?.name || 'Child account'
  return (
    <div className="mx-auto max-w-[1500px] space-y-6 p-4 md:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            <Network className="h-4 w-4" /> Connected accounts
          </div>
          <h1 className="text-3xl font-semibold tracking-tight">Trade Copier</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            One master. Your connected accounts. Every copy accounted for.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={mode === 'live' ? 'destructive' : 'secondary'}>
            {mode === 'live' ? 'LIVE · Real orders' : 'SANDBOX · Paper orders'}
          </Badge>
          <Button variant="outline" disabled={busy || !state} onClick={() => void act('reconcile')}>
            <RefreshCw className="mr-2 h-4 w-4" /> Reconcile
          </Button>
          <Button
            variant="destructive"
            disabled={busy || !state}
            onClick={() => void act('control', { action: 'kill' })}
          >
            <Square className="mr-2 h-4 w-4" /> Stop copying
          </Button>
        </div>
      </div>
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive"
        >
          {error}
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ['Connected children', String(children.length), `${ready} ready to copy`],
          [
            'Copying status',
            state?.armed ? 'Armed' : state?.killed ? 'Stopped' : 'Disarmed',
            state?.note || 'Loading connection status',
          ],
          [
            'Dispatch latency · p95',
            state?.latency.p95 != null ? `${state.latency.p95} ms` : '—',
            'Master receipt → child dispatch; excludes broker/network delay',
          ],
          ['Needs attention', String(unresolved), 'Uncertain outcomes pause the affected child'],
        ].map(([label, value, note]) => (
          <div key={label} className="rounded-xl border bg-card p-5">
            <div className="text-sm text-muted-foreground">{label}</div>
            <div className="my-2 text-2xl font-semibold tabular-nums">{value}</div>
            <div className="text-xs leading-relaxed text-muted-foreground">{note}</div>
          </div>
        ))}
      </div>
      <section className="overflow-hidden rounded-xl border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b bg-muted/20 p-5">
          <div className="flex items-center gap-4">
            <div className="rounded-xl bg-primary/10 p-3 text-primary">
              <Network className="h-6 w-6" />
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                Master account
              </div>
              <h2 className="mt-1 text-lg font-semibold">My {broker.toUpperCase()} account</h2>
              <p className="text-xs text-muted-foreground">
                {mode === 'paper'
                  ? 'Follows this account’s OpenAlgo Sandbox orders'
                  : 'Follows broker app, web and API orders through the order feed'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <ArrowRight className="hidden h-5 w-5 text-muted-foreground sm:block" />
            <Badge variant="outline">
              {children.filter((c) => c.enabled).length} enabled children
            </Badge>
            <Button
              disabled={busy || !state || !children.some((c) => c.enabled)}
              variant={state?.armed ? 'outline' : 'default'}
              onClick={() =>
                state?.armed ? void act('control', { action: 'disarm' }) : setConfirm('arm')
              }
            >
              {state?.armed ? 'Disarm' : 'Review & arm'}
            </Button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <ShieldCheck className="h-3.5 w-3.5" /> Encrypted account credentials
          </span>
          <span className="flex items-center gap-1.5">
            <Copy className="h-3.5 w-3.5" /> Duplicate protection
          </span>
          <span className="flex items-center gap-1.5">
            <Zap className="h-3.5 w-3.5" /> Concurrent child execution
          </span>
          <span>
            Last reconciliation: {state?.heartbeat ? stamp(state.heartbeat) : 'Not yet run'}
          </span>
        </div>
      </section>
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">Child accounts</h2>
            <p className="text-sm text-muted-foreground">
              Set quantity and risk limits separately for each account.
            </p>
          </div>
          <Button disabled={busy || state?.armed || !state} onClick={() => setEditing('new')}>
            <Plus className="mr-2 h-4 w-4" /> Add child
          </Button>
        </div>
        {!children.length && (
          <div className="rounded-xl border border-dashed p-10 text-center">
            <Network className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
            <h3 className="font-medium">Connect your first child account</h3>
            <p className="mx-auto mt-2 max-w-lg text-sm text-muted-foreground">
              Use native FYERS, Zerodha or Dhan credentials, or connect a separate OpenAlgo
              installation for another broker. Sandbox children use separate paper balances.
            </p>
          </div>
        )}
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {children.map((c) => (
            <div key={c.id} className="rounded-xl border bg-card p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold">{c.name}</h3>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {c.broker.toUpperCase()} · {c.client_id}
                  </p>
                </div>
                <Status value={!c.enabled ? 'DISABLED' : c.health} />
              </div>
              <div className="my-5 grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-xs text-muted-foreground">Copy mode</span>
                  <p className="mt-1 capitalize">
                    {c.copy_mode === 'fill'
                      ? 'New fills'
                      : c.copy_mode === 'fast'
                        ? 'Accepted orders'
                        : 'Hybrid'}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Quantity</span>
                  <p className="mt-1 font-semibold">{c.multiplier}× master</p>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Per order cap</span>
                  <p className="mt-1">{money(c.max_order_value)}</p>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Daily loss stop</span>
                  <p className="mt-1 text-destructive">{money(c.max_daily_loss)}</p>
                </div>
              </div>
              <div className="mb-4 flex flex-wrap gap-1">
                {c.symbols.slice(0, 5).map((s) => (
                  <Badge key={s} variant="outline">
                    {s}
                  </Badge>
                ))}
                {c.symbols.length > 5 && <Badge variant="outline">+{c.symbols.length - 5}</Badge>}
              </div>
              <Button
                className="w-full"
                variant="outline"
                disabled={busy || state?.armed}
                onClick={() => setEditing(c)}
              >
                Manage account & limits
              </Button>
            </div>
          ))}
        </div>
      </section>
      <section className="rounded-xl border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b p-4">
          <div className="flex gap-2">
            <Button
              size="sm"
              variant={tab === 'activity' ? 'secondary' : 'ghost'}
              onClick={() => setTab('activity')}
            >
              <Activity className="mr-2 h-4 w-4" /> Copy activity
            </Button>
            <Button
              size="sm"
              variant={tab === 'audit' ? 'secondary' : 'ghost'}
              onClick={() => setTab('audit')}
            >
              Audit trail
            </Button>
          </div>
          <select
            aria-label="Filter child account"
            className={`${selectClass} max-w-[230px]`}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">All child accounts</option>
            {children.map((c) => (
              <option value={c.id} key={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        {tab === 'activity' ? (
          <div className="divide-y">
            {!byMaster.size && (
              <p className="p-10 text-center text-sm text-muted-foreground">
                New master orders will appear here after copying is armed.
              </p>
            )}
            {Array.from(byMaster).map(([id, rows]) => (
              <details key={id} open className="p-4">
                <summary className="cursor-pointer text-sm font-medium">
                  {rows[0].order.symbol}{' '}
                  <span className="ml-2 text-muted-foreground">
                    {rows[0].order.exchange} · Master #{id} · {rows.length} actions
                  </span>
                </summary>
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full min-w-[780px] text-left text-sm">
                    <thead className="text-xs text-muted-foreground">
                      <tr>
                        {[
                          'Child account',
                          'Action',
                          'Order',
                          'Status',
                          'Filled',
                          'Est. charges',
                          'Dispatch / response',
                          'Broker ID',
                        ].map((h) => (
                          <th key={h} className="pb-3 pr-4 font-medium">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((a) => (
                        <tr key={a.id} className="border-t">
                          <td className="py-3 pr-4">
                            {childName(a.account_id)}
                            <div className="text-xs text-muted-foreground">{stamp(a.created)}</div>
                          </td>
                          <td className="pr-4">{a.action}</td>
                          <td className="pr-4">
                            {a.order.action} {a.order.quantity}
                            <div className="text-xs text-muted-foreground">{a.order.pricetype}</div>
                          </td>
                          <td className="max-w-64 pr-4">
                            <Status value={a.status} />
                            {a.message && (
                              <p className="mt-1 text-xs text-muted-foreground">{a.message}</p>
                            )}
                            {a.status === 'UNKNOWN' && (
                              <Button
                                size="sm"
                                variant="link"
                                className="h-auto p-0"
                                onClick={() => {
                                  setResolvedOrderId('')
                                  setConfirm(a)
                                }}
                              >
                                Resolve outcome
                              </Button>
                            )}
                          </td>
                          <td className="pr-4 tabular-nums">{a.filled}</td>
                          <td className="pr-4 tabular-nums">
                            {a.estimated_charges
                              ? money(
                                  Object.values(a.estimated_charges).reduce((sum, n) => sum + n, 0)
                                )
                              : '—'}
                          </td>
                          <td className="pr-4 text-xs tabular-nums">
                            {a.dispatch_ms?.toFixed(1) ?? '—'} / {a.response_ms?.toFixed(1) ?? '—'}{' '}
                            ms
                          </td>
                          <td className="font-mono text-xs">{a.broker_orderid || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            ))}
          </div>
        ) : (
          <div className="divide-y">
            {!state?.audit.length && (
              <p className="p-8 text-sm text-muted-foreground">
                Account and system changes will be recorded here.
              </p>
            )}
            {state?.audit.map((a, i) => (
              <div key={`${a.created}-${i}`} className="flex flex-wrap gap-4 p-4 text-sm">
                <time className="text-muted-foreground">{stamp(a.created)}</time>
                <span className="font-medium">{a.action.replaceAll('_', ' ')}</span>
                <span className="break-all text-muted-foreground">{a.detail}</span>
              </div>
            ))}
          </div>
        )}
        <div className="border-t p-3 text-xs text-muted-foreground">
          Shows the latest 250 attempts and 100 audit entries. Dispatch latency is local processing
          time; execution price and fill timing depend on each broker.
        </div>
      </section>
      <p className="text-xs leading-relaxed text-muted-foreground">
        Arming starts with new orders; existing master orders are excluded. A stop blocks new
        submissions; requests already sent may complete. Cancelled or rejected master orders can
        leave filled child positions, which must be reviewed in the child account.
      </p>
      <Dialog
        open={confirm !== null}
        onOpenChange={(open) => {
          if (!open && !busy) setConfirm(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {confirm === 'arm'
                ? `Arm ${mode === 'live' ? 'Live' : 'Sandbox'} copying?`
                : 'Resolve an uncertain outcome'}
            </DialogTitle>
            <DialogDescription>
              {confirm === 'arm'
                ? `${children.filter((c) => c.enabled).length} enabled child accounts will follow NEW master orders. ${mode === 'live' ? 'This authorizes real broker orders in the connected child accounts.' : 'Orders stay in separate Sandbox child balances.'} Preflight checks every child session and risk snapshot first.`
                : 'First reconcile and inspect the child broker orderbook. Only mark “Not executed” if you have verified that no order was created. This does not resend the order.'}
            </DialogDescription>
          </DialogHeader>
          {confirm === 'arm' && (
            <div className="space-y-2 text-sm">
              {children
                .filter((c) => c.enabled)
                .map((c) => (
                  <div key={c.id} className="flex justify-between rounded border p-3">
                    <span>
                      {c.name} · {c.broker}
                    </span>
                    <span>
                      {c.multiplier}× · {c.copy_mode}
                    </span>
                  </div>
                ))}
            </div>
          )}
          {confirm && confirm !== 'arm' && (
            <div className="space-y-2">
              <Label htmlFor="resolved-broker-id">Executed? Match the child broker order ID</Label>
              <Input
                id="resolved-broker-id"
                value={resolvedOrderId}
                onChange={(e) => setResolvedOrderId(e.target.value)}
              />
              <Button
                variant="outline"
                disabled={busy || !resolvedOrderId.trim()}
                onClick={() =>
                  void act(`resolve/${confirm.id}`, {
                    resolution: 'confirmed_executed',
                    broker_orderid: resolvedOrderId.trim(),
                    confirm: true,
                  })
                }
              >
                Confirm executed & match order
              </Button>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setConfirm(null)}>
              Cancel
            </Button>
            <Button
              disabled={busy}
              variant={mode === 'live' ? 'destructive' : 'default'}
              onClick={() =>
                confirm === 'arm'
                  ? void act('control', { action: 'arm', confirm: true })
                  : confirm &&
                    void act(`resolve/${confirm.id}`, {
                      resolution: 'confirmed_not_placed',
                      confirm: true,
                    })
              }
            >
              {busy ? 'Checking…' : confirm === 'arm' ? 'Confirm & arm' : 'Confirmed: not executed'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {editing && (
        <ChildDialog
          mode={mode}
          child={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSave={async (data) => {
            if (editing !== 'new')
              await webClient.patch(`/trade-copier/api/accounts/${editing.id}`, data, { params })
            else await webClient.post('/trade-copier/api/accounts', data, { params })
            await read()
            setEditing(null)
          }}
        />
      )}
    </div>
  )
}

function ChildDialog({
  mode,
  child,
  onClose,
  onSave,
}: {
  mode: string
  child: Child | null
  onClose: () => void
  onSave: (data: unknown) => Promise<void>
}) {
  const [form, setForm] = useState(child || empty)
  const [connection, setConnection] = useState('native')
  const [appId, setAppId] = useState('')
  const [token, setToken] = useState('')
  const [url, setUrl] = useState('')
  const [mappings, setMappings] = useState('{}')
  const [symbols, setSymbols] = useState(form.symbols.join(', '))
  const [fast, setFast] = useState(form.fast_symbols.join(', '))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = (key: string, value: string | number | boolean) =>
    setForm((f) => ({ ...f, [key]: value }))
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const credentials =
        mode === 'live' && token
          ? connection === 'native'
            ? { connection, app_id: appId, access_token: token, instruments: JSON.parse(mappings) }
            : { connection, url, api_key: token }
          : {}
      await onSave({
        ...form,
        symbols: symbols
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        fast_symbols: fast
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        credentials,
      })
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose()
      }}
    >
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{child ? 'Manage child account' : 'Connect a child account'}</DialogTitle>
          <DialogDescription>
            {mode === 'paper'
              ? 'Each child has its own Sandbox balance and orders. No broker credentials are needed.'
              : 'Use an authorized broker access token. Tokens are encrypted and never returned to the browser. Keep credentials blank when editing to retain the existing connection.'}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="child-name">Account name</Label>
              <Input
                id="child-name"
                required
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                placeholder="Family account"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="child-client">Broker client ID</Label>
              <Input
                id="child-client"
                required
                disabled={!!child}
                value={form.client_id}
                onChange={(e) => set('client_id', e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="child-broker">Broker</Label>
              <Input
                id="child-broker"
                required
                disabled={!!child}
                value={form.broker}
                onChange={(e) => set('broker', e.target.value.toLowerCase())}
                list="copier-brokers"
              />
              <datalist id="copier-brokers">
                <option value="fyers" />
                <option value="zerodha" />
                <option value="dhan" />
                <option value="angel" />
                <option value="upstox" />
              </datalist>
            </div>
            <div className="space-y-2">
              <Label htmlFor="copy-mode">Copy mode</Label>
              <select
                id="copy-mode"
                className={selectClass}
                value={form.copy_mode}
                onChange={(e) => set('copy_mode', e.target.value)}
              >
                <option value="fill">New fills (recommended)</option>
                <option value="fast">Accepted orders (fast)</option>
                <option value="hybrid">Hybrid</option>
              </select>
            </div>
          </div>
          {mode === 'live' && (
            <fieldset className="space-y-3 rounded-lg border p-4">
              <legend className="px-1 text-sm font-medium">Connection</legend>
              <select
                aria-label="Connection type"
                className={selectClass}
                value={connection}
                onChange={(e) => setConnection(e.target.value)}
              >
                <option value="native">Native · FYERS / Zerodha / Dhan</option>
                <option value="openalgo">OpenAlgo child · any supported broker</option>
              </select>
              {connection === 'native' ? (
                <>
                  <Label htmlFor="child-app">Broker app ID / API key</Label>
                  <Input
                    id="child-app"
                    autoComplete="off"
                    value={appId}
                    onChange={(e) => setAppId(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Dhan uses its client ID; app ID can be blank.
                  </p>
                </>
              ) : (
                <>
                  <Label htmlFor="child-url">Child OpenAlgo address</Label>
                  <Input
                    id="child-url"
                    type="url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="http://127.0.0.1:5020"
                  />
                  <p className="text-xs text-muted-foreground">
                    A separate child installation with the Trade Copier bridge enabled. Log that
                    instance into the child’s broker and select the same Live/Sandbox mode.
                  </p>
                </>
              )}
              <Label htmlFor="child-token">
                {connection === 'native' ? 'Access token' : 'Child OpenAlgo API key'}
              </Label>
              <Input
                id="child-token"
                type="password"
                autoComplete="new-password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                required={!child}
              />
              {connection === 'native' && (
                <details>
                  <summary className="cursor-pointer text-sm">Broker instrument mappings</summary>
                  <p className="my-2 text-xs text-muted-foreground">
                    Dhan requires security IDs. Derivatives require explicit broker symbols. Use the
                    broker’s current instrument master; missing mappings block copying. Example:{' '}
                    {'{"NSE:SBIN":"3045"}'} for Dhan.
                  </p>
                  <textarea
                    aria-label="Instrument mappings"
                    className="min-h-24 w-full rounded border bg-background p-2 font-mono text-xs"
                    value={mappings}
                    onChange={(e) => setMappings(e.target.value)}
                  />
                </details>
              )}
            </fieldset>
          )}
          <div className="space-y-2">
            <Label htmlFor="allowed-symbols">Allowed symbols (comma separated)</Label>
            <Input
              id="allowed-symbols"
              value={symbols}
              onChange={(e) => setSymbols(e.target.value)}
              placeholder="NSE:SBIN, NSE:TCS"
            />
          </div>
          {form.copy_mode === 'hybrid' && (
            <div className="space-y-2">
              <Label htmlFor="fast-symbols">Fast MARKET symbols</Label>
              <Input id="fast-symbols" value={fast} onChange={(e) => setFast(e.target.value)} />
              <p className="text-xs text-muted-foreground">
                Other symbols and order types copy new fills.
              </p>
            </div>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            {(
              [
                ['multiplier', 'Quantity multiplier'],
                ['max_quantity', 'Maximum quantity per order'],
                ['max_order_value', 'Maximum order value (₹)'],
                ['max_daily_value', 'Maximum daily order value (₹)'],
                ['max_daily_loss', 'Daily loss stop (₹)'],
                ['max_position_quantity', 'Maximum account position quantity'],
              ] as const
            ).map(([key, label]) => (
              <div key={key} className="space-y-2">
                <Label htmlFor={`cp-${key}`}>{label}</Label>
                <Input
                  id={`cp-${key}`}
                  type="number"
                  min={key === 'multiplier' ? '.01' : '1'}
                  step={key === 'multiplier' ? '.01' : '1'}
                  required
                  value={form[key]}
                  onChange={(e) => set(key, Number(e.target.value))}
                />
              </div>
            ))}
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => set('enabled', e.target.checked)}
            />{' '}
            Enable this child when copying is armed
          </label>
          <p className="text-xs text-muted-foreground">
            Quantities round down to complete exchange lots. Fast mode can fill children before the
            master fills. Risk limits block new orders; they do not automatically flatten positions.
          </p>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={busy} onClick={onClose}>
              Cancel
            </Button>
            <Button disabled={busy} type="submit">
              {busy ? 'Saving…' : 'Save child account'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
