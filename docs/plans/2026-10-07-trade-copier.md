# October 7 — isolated local Trade Copier

**Current status:** Integrated in the authorized evening local release. See the [consolidated feature map](2026-10-07-feature-implementation-status.md) for implemented behavior and remaining limits. Development-stage statements below are historical; they do not supersede this status.

**Evening integration:** Combined into the normal local build with user authorization. [Current release and restart checklist](2026-10-07-evening-combine.md) supersedes the staged-only status below.

## User request and boundary

Implement `trade_copier_production_guide.docx`, using AlgoDelta and ZuluTrade as product references. The current logged-in account is master; children can have different brokers. Both Live and Sandbox are required. Local deployment first; cloud later. User explicitly clarified that a FYERS master must support FYERS, Zerodha and Dhan children, with other brokers possible.

The dashboard/backend are **integrated in the normal local build**, and the feature is enabled in the local environment following the authorized evening combination. This creates no child and arms no copying: the user configures accounts and deliberately arms them. No real orders were sent during development or verification. Only the user starts production. Existing Portfolio/Reports/Screener behavior is documented in [Live/Sandbox features](2026-10-07-live-sandbox-features.md). Earlier isolation/build notes below record the development phase.

## Implemented

- `/trade-copier` React dashboard and navigation: master overview, child cards, copy policy and risk forms, grouped master-order activity, child filters, latency statistics, audit, review/arm, disarm and owner-wide stop.
- Session-authenticated controls with application CSRF protection. The separately opt-in bridge uses API-key authentication, explicit broker/mode validation, rate limiting and durable idempotency receipts.
- Native account-scoped **FYERS, Zerodha and Dhan** transports. Every child has its own app/client ID and access token; no changes to process-wide broker credentials. Profile verification checks the token's client ID. Credentials use the existing installation's Fernet encryption; API responses omit them.
- Other installed OpenAlgo brokers use a **separate child OpenAlgo installation** with this version of the bridge. That instance owns its broker login, app credentials and instrument database. This is the supported extension mechanism, not a claim that every broker has a native multi-account adapter or has passed live testing.
- Sandbox children have distinct `cp_<account-id>` users in the existing Sandbox engine, with separate balances/orders/positions. They need no live child credentials. The master source remains the logged-in user's Sandbox orders. Its existing broker market-data session supplies quotes.
- Fill-based (default), accepted-order/fast and hybrid copying. Quantity multipliers use decimal arithmetic and cumulative lot rounding. New fills of 4 then 10 produce child deltas of 4 and 6. Fill-based copies use MARKET orders; fast mode preserves the master order type/prices. Hybrid fast symbols are explicitly configured and only apply to MARKET orders.
- Master ingress subscribes to existing `order.update` events. Those feeds include app/web orders for brokers whose order adapters support them. Five-second orderbook/tradebook reconciliation covers missing events and brokers without push. Thus polling-only brokers do **not** have push-feed latency. Existing feed reconnection remains owned by `order_update_service`.
- Durable event/revision state, child quantity cursors, attempts, control state and audit. SQLite uses the common NullPool engine factory and **FULL synchronous commits** for the copier DB. Intent commits before broker dispatch. Repeating price modifications A→B→A→B are retained as distinct revisions; duplicate fills do not resend.
- Shared bounded executor: 16 workers, at most 256 queued/running submissions, at most 50 registered children. Mutations serialize within each child while different children run concurrently. Native pooled HTTP has a four-second deadline and no automatic mutation retries. Local caps are five mutations/second and 120/minute per child, plus broker-side limits.
- Explicit READY/AUTH_REQUIRED/DEGRADED/RATE_LIMITED states, daily session checks, broker/client identity checks, duplicate child identity rejection, and master-as-child rejection. Preflight checks token/profile, native mapping availability and positions/P&L. Broker RMS remains authoritative for actual margin/funds acceptance.
- Symbol allowlists, per-order quantity/value, daily submitted value, gross daily P&L loss stop and conservative aggregate position-quantity limits. Market notional estimates include a 5% buffer; that is not a guaranteed execution-price cap. Risk snapshots expire after 30 seconds and refresh during reconciliation. Position reservations deliberately over-count rather than under-count uncertain exposure.
- UNKNOWN for ambiguous outcomes. No blind resend. Native reconciliation matches broker ID or unique copy tag; bridge receipts recover a lost bridge HTTP acknowledgement. Unresolved cases require operator review: confirm no execution, or explicitly match an existing child broker order ID. Neither resolution resends an order.
- Propagation of cancellations and current authoritative price/quantity modifications for mapped open child orders. Cancellation arriving during placement waits for its parent receipt. A master rejection/cancel can leave already-filled child positions; there is no automatic reverse/flatten trade.
- Stop blocks queued submissions. Already-dispatched requests may finish. Stop/config changes during preflight invalidate the pending arm. Every queued attempt carries its arm generation, so re-arming cannot release stale work. Master order identities include broker/session scope to prevent ID collisions across accounts. Live/Sandbox transitions disarm through a mapped-settings listener; token changes, broker changes, stale heartbeats and day rollover fail closed. Restart always disarms and marks interrupted submissions UNKNOWN.
- Child-broker standard retail charge estimates on confirmed fills, using the existing verified brokerage engine. Unsupported broker/segment estimates show a dash. These are estimates, not contract-note charges or automatic deductions from Sandbox balances.

## Connection and instrument scope

| Child connection | Setup | Boundaries |
|---|---|---|
| FYERS native | Client ID, app ID, current access token | NSE equity symbol default; BSE/derivatives require explicit broker symbols. |
| Zerodha native | Client ID, API key, current access token | Equity symbol default; derivatives require explicit trading symbols. MCX native dispatch is blocked because quantity-unit conversion needs broker-specific handling; use a child OpenAlgo instance. |
| Dhan native | Client ID, current access token | Explicit security-ID mapping for every allowed symbol. Native SL-M is blocked; use a valid SL limit or the existing Dhan plugin through a child OpenAlgo instance. |
| Other OpenAlgo brokers | Separate installation URL + its OpenAlgo API key | Compatible bridge enabled, same mode, correctly logged-in child broker; order capabilities and internal plugin retry behavior remain broker-dependent. |

Native login uses current broker-issued access tokens. This release does not automate child OAuth authorization, renew expired tokens, or store broker passwords/TOTP seeds. Update credentials while disarmed and re-arm after preflight. Editing with credentials blank retains the existing encrypted connection. Disable children through Manage account & limits; audit history is retained.

Allowlist format is `NSE:SBIN, NSE:TCS`. Native instrument mappings are a JSON object, e.g. `{"NSE:SBIN":"3045"}` for Dhan. Verify IDs against the relevant broker's current instrument master. Derivative mappings must be updated for contract rollover; no guessed cross-broker derivative conversion occurs.

Arming baselines all existing master orders and follows **new orders only**. Orders already present at re-arm are excluded, including partial/open orders. Review and manage existing master/child exposure before re-arming. Fill-based copies can still reject due to a child's margin, permissions or market conditions. An accepted broker order ID is not a fill.

## Files and activation

- Backend: `services/trade_copier/{domain,models,adapters,engine,runtime}.py` and `blueprints/trade_copier.py`.
- Wiring: `app.py` registers the blueprint and exempts only its API-key bridge from CSRF. Importing the feature starts no executor or database writes.
- Frontend: `frontend/src/pages/TradeCopier.tsx`, `App.tsx`, `config/navigation.ts`.
- Tests/preview: `test/test_trade_copier.py`, `.development/trade-copier/{browser_server.py,verify_ui.cjs,verify_backend.py}`.

After an explicitly authorized local combine, configure these variables **on the intended installation**, build/restart at the user's chosen time:

```dotenv
TRADE_COPIER_ENABLED=TRUE
TRADE_COPIER_DATABASE_URL=sqlite:///db/trade_copier.db
# Only on a separate installation acting as a child gateway:
TRADE_COPIER_BRIDGE_ENABLED=TRUE
```

The flags default to FALSE. Opening the page while disabled explains that it is not enabled. The engine starts lazily on the first authorized copier request. A file lock allows only one local process to own the copier database; a second worker fails closed. Keep the DB on a local disk. Preserve the installation encryption pepper/salt with encrypted backups; changing encryption secrets without migration makes stored child tokens unreadable.

Do not enable the bridge on the master as a shortcut to a child account. Each gateway child needs its own instance, broker session, databases, ports and symbol master. HTTP is accepted only on localhost; remote origins require HTTPS. No endpoint redirects are followed. No actual child account credentials were entered during development.

## Verification evidence

- Combined regression: **183 passed** across Portfolio, modes, Reports, brokerage, Screener and 40 copier tests. Final focused suite: **42 copier tests passed**, including queued-work invalidation across re-arm and operator matching of late broker acknowledgements.
- Actual Flask blueprint tests cover session authorization, owner/mode partition, CSRF enforcement, wrong bridge key, replayed bridge receipts, mismatched idempotency payloads and ambiguous bridge acknowledgement.
- Native FYERS/Zerodha/Dhan request contracts are tested with fake HTTP, including scoped credentials; no live endpoint mutation was sent.
- Actual Sandbox orderbook/position reads and cross-user cancellation rejection are exercised on test-only databases.
- Desktop and 390px mobile browser flows: account creation, mixed broker form, arm review, disable editing while armed, stop, mode separation, paper credential omission, no browser exceptions/overflow.
- TypeScript project build (`tsc -b`), focused Biome/Ruff and isolated Vite output under `.development/trade-copier/dist`. Normal `frontend/dist` untouched.
- 300 repeated snapshots/duplicate events: descriptors **4 → 4**, retained traced memory **+512 bytes**, reproduced after the final engine changes. Account registries are bounded to 50, executor queue to 256; subscriptions and worker pool are removed/shut down by `close()`. Measurement and mutations: `.development/trade-copier/verification.json`.
- Mutation proofs disable the actual loss guard, owner filter and partial-fill delta calculation in memory. Each corresponding test fails as expected. Source files and production state are not modified by these proofs.
- Saved production configuration verification passes; the existing 20 schedules are preserved. Other active equity-shorts lane files are unrelated and were not edited.

Screenshots: `.development/trade-copier/artifacts/copier-desktop.png`, `copier-mobile.png`, `copier-connect.png`, `copier-sandbox-connect-mobile.png`. Their values and latency are **synthetic fixture data**, not actual broker performance.

## Remaining operational and cloud work

Real account authentication, broker app/web event delivery, broker-specific live fills/modifies/cancels, margin permissions and end-to-end latency remain unverified. Local automated tests cannot establish these. There is no promised millisecond broker execution SLA. API acceptance, exchange fill and matching execution prices are distinct.

The guide's Go executor, PostgreSQL/Redis distributed fencing, AWS/KMS, multi-replica failover, monitoring integrations, backup/restore exercises and cloud deployment are explicitly future work. The local implementation uses Python's bounded executor and SQLite to fit this application. Do not scale it to multiple cloud workers merely by changing a database URL; runtime intentionally rejects non-file SQLite until distributed leader ownership is implemented. Before any live rollout, carry out the guide's one-master/one-child checks at the operator's direction, then increase children gradually.

The bridge adapts existing broker plugins; its receipt prevents duplicate incoming requests, but cannot remove retries implemented inside individual plugins. Unknown generic-plugin submissions may require manual orderbook matching. Native adapters do not retry mutations. Broker unsupported products, missing mappings or stale sessions fail closed rather than silently changing order intent.

## References reviewed

- User's local [production guide](../../trade_copier_production_guide.docx).
- [AlgoDelta copy trading](https://www.algodelta.com/products/copy-trading): master/child groups, mixed broker connections and quantity policies. The supplied signed-in dashboard URL was not publicly readable.
- [ZuluTrade user guide](https://www.zulutrade.com/user-guide): account overview, following controls, performance and trades. Its app is JavaScript-rendered; public indexed guidance was available.
- [Zerodha order API](https://kite.trade/docs/connect/v3/orders/), [Dhan order API](https://dhanhq.co/docs/v2/orders/), [Dhan authentication/profile](https://dhanhq.co/docs/v2/authentication/), [official FYERS order reference](https://github.com/FyersDev/fyers-skills/blob/master/skills/fyers-trading/references/orders.md). UI uses OpenAlgo's own components and visual language, without copying branding/assets.

Final development state: the synthetic preview processes started for this task were stopped and reaped. No preview remains running. Production was not restarted. The user must explicitly authorize combining these isolated changes before activation.
