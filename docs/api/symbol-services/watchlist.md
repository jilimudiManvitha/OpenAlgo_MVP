# Saved watchlists API

`POST /api/v1/watchlist` authenticates with the OpenAlgo application `apikey`.
It reads/writes the same user-owned tables as `/watchlist/api/lists` in the
charting terminal. An active broker login is not needed to manage lists;
additions require the symbol master to be populated.

```json
{
  "apikey": "<OPENALGO_API_KEY>",
  "action": "add",
  "name": "Thu",
  "symbols": "SBIN, TCS\nNSE:INFY; BSE:RELIANCE",
  "exchange": "NSE",
  "create_if_missing": false
}
```

| Action | Required fields beyond apikey/action | Behavior |
|---|---|---|
| `list` | none | Names/IDs/positions/item counts for the key owner |
| `get` | `name` | Entire list in display order |
| `create` | `name`; optional `symbols` | New empty or prefilled list; existing name → 409 |
| `add` | `name`, `symbols` | Append; preserve existing entries and skip duplicates |
| `remove` | `name`, `symbols` | Remove matching symbol/exchange pairs; preserve the rest |
| `replace` | `name`, `symbols` | Set entire contents and order; empty string/list clears |
| `rename` | `name`, `new_name` | Rename; conflicting name → 409 |
| `delete` | `name` | Delete that list and its items |

Names are exact and trimmed, up to 64 characters. `symbols` accepts pasted text
with comma/semicolon/whitespace separators, a list of strings, or objects such
as `{"symbol":"SBIN","exchange":"NSE"}`. Bare strings use `exchange`
(default NSE). `EXCHANGE:SYMBOL` overrides it. Symbols/exchanges normalize to
uppercase. Use OpenAlgo symbols, not broker-specific `NSE:SBIN-EQ` identifiers.

`create_if_missing` is permitted only for `add` and defaults to false. Unknown
fields, including `user_id`, are rejected. The owner always comes from API-key
verification. There is no arbitrary user selector.

Success is HTTP 200 with `{"status":"success","data":...}`. List details
include `id`, `name`, `position`, ordered `items`, and `changed_items` (membership
changes, not reordering). Adds report `already_present`; removals report
`not_present`. Removing a delisted/expired instrument does not require the
instrument to remain in today's master.

Limits are 250 supplied entries per request, 250 unique entries per list and
50 lists per user. Create/add/replace verify every supplied instrument before
writing. Invalid symbols return HTTP 400 with `invalid_symbols`, leaving the
entire list unchanged. Exceeding the capacity returns 409, not silent truncation.
Invalid key → 403; missing list → 404; malformed input → 400; internal errors
→ 500. Database errors do not masquerade as empty lists.

Mutations are one transaction. SQLite batch writers acquire a write reservation
before reading counts/items, so concurrent MCP clients using this API cannot
lose additions or overfill a list. All database sessions are released on
success/error. Existing browser routes remain available with their existing
session authentication; reload the chart page to see changes from MCP.

No order is placed by these endpoints. A strategy that reads a named watchlist
may use the changed instruments on its next read. No real user watchlists are
changed by the automated test suite.

MCP read tools require `read:account` over OAuth. MCP edit tools require
`write:watchlists`, which does not grant `write:orders`. Stdio tools use the
application key; `OPENALGO_MCP_READ_ONLY=1` excludes writes. Local desktop setup
does not require enabling the remote OAuth transport.
