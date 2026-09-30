# Stock category database

Imported on 2026-09-29 into `db/market_scanner_live.db`:

- 544 distinct NSE ticker strings, including historical aliases from reference lists.
- 46 scanner categories: 11 supplied broad indices, 12 sector indices, Cement,
  20 industry groups and two derived composite indices.
- 10 historical/download reference groups, stored separately and hidden from
  the scanner dropdown. Total: 56 categories and 7,134 memberships.
- All 35 symbol-list files processed; six VIX OHLC files are price history,
  excluded from this equity-membership import. Original files are unchanged.

Nifty 50 has 50 members, Next 50 has 50, Nifty 100 has 100, Nifty 200 has
200 and Nifty 500 has 500. Midcap 50/100/150, Smallcap 100/250 and Nifty 500
Multicap 50:25:25 retain their supplied memberships. LargeMidcap 250 is the
union of the supplied Nifty 100 and Midcap 150; MidSmallcap 400 is the union
of Midcap 150 and Smallcap 250. These are derived snapshots, not new downloads.

Industry groups use the `Industry` column in the supplied constituent CSVs.
They cover that source universe, not all NSE listings. Sector-index memberships
remain distinct: for example, Nifty IT has 10 members while the source-universe
Information Technology industry group has 27.

Files have no confirmed constituent effective date. Import time is recorded
separately; the scanner shows **date unknown**. The official
[sectoral](https://www.niftyindices.com/indices/equity/sectoral-indices) and
[broad-market](https://www.niftyindices.com/indices/equity/broad-based-indices)
catalogues were checked, but direct constituent downloads from Nifty Indices
and NSE archives failed/timed out. Additional official lists such as Smallcap 50,
Microcap 250 and Total Market have **not** been invented or added. This import
does not claim complete/current coverage of every official Nifty index.

Name-only sector exports resolve against exact normalized company names in the
supplied index files/read-only local NSE EQ master. Explicit short-name mappings
are in `services/stock_categories.py`; all were checked against the installed
master. The import audit retains each name-to-symbol resolution. Ambiguous or
unresolved names abort before saving. Symbol-bearing Auto data takes precedence
over its name-only duplicate. Dates, separators, the stray `Done` marker and the
`NIFTY AUTO` aggregate row are not equities. Historical tickers such as IIFLWAM
are retained in reference groups and never appended to the official Nifty 500.

## Refresh and query

From the repository root:

```sh
.venv/bin/python scripts/import_stock_categories.py --dry-run
.venv/bin/python scripts/import_stock_categories.py
```

The import command makes a consistent SQLite backup under `db/backups/` before
writing. It respects `SCANNER_LIVE_DB`; `--database` overrides that path.
`--source` and `--master-db` allow explicit alternate inputs. The scanner's
**Reimport local lists** action uses the same offline importer. Restart the
backend normally to load the updated refresh code; category options themselves
are returned dynamically from the database, so no frontend rebuild is needed.

Tables in `db/market_scanner_live.db`:

| Table | Contents |
|---|---|
| `stock_category_symbols` | Distinct exchange/symbol, available name, industry and ISIN |
| `stock_categories` | Category ID, label, type and source/hash/date metadata |
| `stock_category_memberships` | Unique category/exchange/symbol memberships |
| `stock_category_imports` | Latest 50 import audits, file hashes and name resolutions |
| `scanner_live_categories` | Compatible JSON projection used by the existing scanner |

Memberships and the scanner projection commit atomically. Repeated imports do
not duplicate stocks or memberships. Unrelated categories, broker master data,
account controls, scanner snapshots and historical candle databases are preserved.

```sql
SELECT c.id, c.label, c.kind, COUNT(m.symbol) AS members
FROM stock_categories c
JOIN stock_category_memberships m ON m.category_id = c.id
GROUP BY c.id ORDER BY c.kind, c.label;

SELECT s.symbol, s.name, s.industry, s.isin
FROM stock_category_memberships m
JOIN stock_category_symbols s USING (exchange, symbol)
WHERE m.category_id = 'nifty50' ORDER BY s.symbol;

SELECT c.label FROM stock_categories c
JOIN stock_category_memberships m ON m.category_id = c.id
WHERE m.exchange = 'NSE' AND m.symbol = 'RELIANCE';
```

The local DB and backup are runtime files, not committed source artifacts.
Rerun the importer after moving this checkout to another installation.
