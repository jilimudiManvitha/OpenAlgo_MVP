"""Nine ledger reports and atomic CSV valuations; no broker/order side effects."""

import csv
import io
import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select

from services import investment_service as s

REPORTS = {
    "transactions": "Transaction History",
    "dividends": "Dividend Report",
    "corporate-actions": "Corporate Action",
    "performance": "Performance Report",
    "holdings": "Holding Report",
    "capital-gains": "Capital Gain Report",
    "profit-loss": "Profit & Loss Statement",
    "calendar": "Transaction Calendar",
    "consolidated": "Consolidated Holding",
}


def timestamp(value):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.astimezone(UTC).replace(tzinfo=None) > s.now() + timedelta(
            minutes=1
        ):
            raise ValueError
        return stamp.astimezone(UTC).replace(tzinfo=None)
    except (AttributeError, TypeError, ValueError):
        raise s.InvestmentError("as_of must be a non-future ISO timestamp with timezone") from None


def import_prices(user, content, account_id=None):
    if not isinstance(content, str) or len(content.encode()) > 256_000:
        raise s.InvestmentError("CSV must be text under 256 KB")
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
    try:
        headers = reader.fieldnames
    except csv.Error:
        raise s.InvestmentError("Malformed CSV headers") from None
    if not headers or len(headers) != 4 or set(headers) != {
        "symbol",
        "scheme_code",
        "price",
        "as_of",
    }:
        raise s.InvestmentError("CSV headers must be symbol,scheme_code,price,as_of")
    try:
        rows = list(reader)
    except csv.Error:
        raise s.InvestmentError("Malformed CSV") from None
    if not 1 <= len(rows) <= 500:
        raise s.InvestmentError("Import between 1 and 500 valuation rows")
    with s.transaction(True) as session:
        query = select(s.Asset).where(s.Asset.user_id == user)
        if account_id is not None:
            s.owned(session, s.Account, user, account_id)
            query = query.where(s.Asset.account_id == s.identifier(account_id))
        assets = list(session.scalars(query))
        seen = set()
        for index, row in enumerate(rows, 2):
            if None in row or any(v is None for v in row.values()):
                raise s.InvestmentError(f"CSV row {index}: incorrect number of fields")
            symbol, scheme = row["symbol"].strip().upper(), row["scheme_code"].strip()
            matches = [
                a
                for a in assets
                if (symbol or scheme)
                and (not symbol or a.symbol == symbol)
                and (not scheme or a.scheme_code == scheme)
            ]
            if len(matches) != 1:
                raise s.InvestmentError(
                    f"CSV row {index}: instrument missing or ambiguous; select its account"
                )
            asset = matches[0]
            price = s.decimal(row["price"], f"row {index} price", positive=True)
            stamp = timestamp(row["as_of"])
            key = (asset.id, stamp)
            if key in seen:
                raise s.InvestmentError(f"CSV row {index}: duplicate instrument/timestamp")
            seen.add(key)
            valuation = (
                session.query(s.Valuation)
                .filter_by(asset_id=asset.id, as_of=stamp, source="manual")
                .first()
            )
            if valuation is None:
                valuation = s.Valuation(asset_id=asset.id, as_of=stamp, source="manual")
                session.add(valuation)
            valuation.price = price
            if asset.price_as_of is None or stamp >= asset.price_as_of:
                asset.manual_price, asset.price_as_of = price, stamp
        session.flush()
    return {"updated": len(rows), "source": "manual", "message": "All valuations imported together"}


def date_range(start, end):
    try:
        end = date.fromisoformat(end) if end else datetime.now(s.IST).date()
        start = date.fromisoformat(start) if start else end - timedelta(days=89)
        if start > end or end > datetime.now(s.IST).date() or (end - start).days > 366:
            raise ValueError
        return start, end
    except (TypeError, ValueError):
        raise s.InvestmentError(
            "Choose a valid report period of at most 367 days, ending today or earlier"
        ) from None


def build(user, name, account_id=None, start=None, end=None):
    if name not in REPORTS:
        raise s.InvestmentError("Report not found", 404)
    start, end = date_range(start, end)
    current = s.holdings(user, account_id)
    assets = {row["id"]: row for row in current}
    with s.transaction() as session:
        query = select(s.Transaction).where(
            s.Transaction.user_id == user, s.Transaction.asset_id.in_(assets)
        )
        txs = list(
            session.scalars(
                query.order_by(
                    s.Transaction.trade_date, s.Transaction.trade_time, s.Transaction.id
                ).limit(50001)
            )
        )
        if len(txs) > 50000:
            raise s.InvestmentError(
                "Select a smaller account for this report (50,000 transaction limit)"
            )
        selected = [row for row in txs if start <= row.trade_date <= end]
        rows = []
        method = "Ledger entries and recorded valuations. Dates and times are IST."
        if name in ("holdings", "consolidated"):
            rows = current
            method = "Current holdings using exactly the dashboard valuation service; date range does not change this snapshot. Liabilities are negative."
            if name == "consolidated":
                merged = {}
                for row in current:
                    if row["is_watch_only"] or Decimal(row["quantity"]) == 0:
                        continue
                    key = (row["asset_class"], row["symbol"], row["exchange"], row["scheme_code"])
                    dest = merged.setdefault(
                        key,
                        {
                            "asset_class": key[0],
                            "symbol": key[1],
                            "exchange": key[2],
                            "scheme_code": key[3],
                            "accounts": 0,
                            "quantity": s.ZERO,
                            "invested": s.ZERO,
                            "market_value": s.ZERO,
                            "unrealized_gain": s.ZERO,
                        },
                    )
                    dest["accounts"] += 1
                    for field in ("quantity", "invested", "market_value", "unrealized_gain"):
                        dest[field] = (
                            None
                            if row[field] is None or dest[field] is None
                            else dest[field] + Decimal(row[field])
                        )
                rows = [
                    {
                        k: (format(v, ".6f") if k == "quantity" else s.money(v))
                        if isinstance(v, Decimal)
                        else v
                        for k, v in row.items()
                    }
                    for row in merged.values()
                ]
        elif name == "capital-gains":
            for asset_id, asset in assets.items():
                state = s.replay([t for t in txs if t.asset_id == asset_id])
                for allocation in state["realizations"]:
                    if str(start) <= allocation["sold_on"] <= str(end):
                        sign = -1 if asset["asset_class"] in s.LIABILITIES else 1
                        rows.append(
                            {
                                "symbol": asset["symbol"],
                                "account_id": asset["account_id"],
                                **allocation,
                                "gain": s.money(Decimal(allocation["gain"]) * sign),
                            }
                        )
            method = "FIFO lot allocations with transaction charges. This is a realization ledger, not a tax computation: exemptions, tax rates and indexation are not applied."
        elif name == "profit-loss":
            for asset_id, asset in assets.items():
                all_rows = [t for t in txs if t.asset_id == asset_id]
                before = s.replay([t for t in all_rows if t.trade_date < start])
                after = s.replay([t for t in all_rows if t.trade_date <= end])
                sign = -1 if asset["asset_class"] in s.LIABILITIES else 1
                rows.append(
                    {
                        "symbol": asset["symbol"],
                        "account_id": asset["account_id"],
                        **{
                            k: s.money((after[k] - before[k]) * sign)
                            for k in (
                                "trading_realized",
                                "income",
                                "realized_gain",
                                "fifo_realized",
                            )
                        },
                    }
                )
            method = "Realizations and income in the selected period; weighted-average and FIFO trading gains are separate. Liability interest is an expense."
        elif name == "performance":
            if len(txs) > 5000:
                raise s.InvestmentError(
                    "Performance supports up to 5,000 transactions per selected account"
                )
            vals = list(
                session.scalars(
                    select(s.Valuation)
                    .where(s.Valuation.asset_id.in_(assets))
                    .order_by(s.Valuation.as_of)
                    .limit(50001)
                )
            )
            if len(vals) > 50000:
                raise s.InvestmentError(
                    "Performance supports up to 50,000 recorded valuations per selected account"
                )
            transactions_by_asset = {key: [] for key in assets}
            valuations_by_asset = {key: [] for key in assets}
            for entry in txs:
                transactions_by_asset[entry.asset_id].append(entry)
            for entry in vals:
                valuations_by_asset[entry.asset_id].append(entry)
            days = sorted(
                {start, end}
                | {t.trade_date for t in selected}
                | {
                    v.as_of.replace(tzinfo=UTC).astimezone(s.IST).date()
                    for v in vals
                    if start <= v.as_of.replace(tzinfo=UTC).astimezone(s.IST).date() <= end
                }
            )
            for day in days:
                value = cost = realized = s.ZERO
                missing = 0
                price_dates = []
                for asset_id, asset in assets.items():
                    history = [t for t in transactions_by_asset[asset_id] if t.trade_date <= day]
                    state = s.replay(history)
                    sign = -1 if asset["asset_class"] in s.LIABILITIES else 1
                    cost += state["invested"] * sign
                    realized += state["realized_gain"] * sign
                    if not state["quantity"]:
                        continue
                    cutoff = (
                        datetime.combine(day + timedelta(days=1), time(), s.IST)
                        .astimezone(UTC)
                        .replace(tzinfo=None)
                    )
                    observed = [v for v in valuations_by_asset[asset_id] if v.as_of < cutoff]
                    if not observed or not s.valuation_matches_units(observed[-1], history):
                        missing += 1
                    else:
                        value += state["quantity"] * observed[-1].price * sign
                        price_dates.append(observed[-1].as_of)
                rows.append(
                    {
                        "date": str(day),
                        "invested": s.money(cost),
                        "market_value": None if missing else s.money(value),
                        "realized_gain": s.money(realized),
                        "total_gain": None if missing else s.money(value - cost + realized),
                        "unpriced": missing,
                        "oldest_price_as_of": min(price_dates).isoformat() + "Z"
                        if price_dates
                        else None,
                        "newest_price_as_of": max(price_dates).isoformat() + "Z"
                        if price_dates
                        else None,
                    }
                )
            method = "Recorded valuation curve at transaction/valuation dates. Last-known prices are carried with their recorded dates, not market marks. Deposits are not returns; no fabricated TWR/XIRR."
        else:
            if name == "dividends":
                selected = [t for t in selected if t.action == "DIVIDEND"]
            if name == "corporate-actions":
                selected = [t for t in selected if t.action == "CORPORATE_ACTION"]
            for t in selected:
                asset = assets[t.asset_id]
                rows.append(
                    {
                        **s.serialize(t),
                        "symbol": asset["symbol"],
                        "asset_class": asset["asset_class"],
                        "account_id": asset["account_id"],
                        "amount": s.money(t.quantity * t.price),
                        "charges": s.money(sum((getattr(t, k) for k in s.CHARGES), s.ZERO)),
                    }
                )
            if name == "calendar":
                grouped = {}
                for row in rows:
                    key = (row["trade_date"], row["action"])
                    dest = grouped.setdefault(
                        key, {"date": key[0], "action": key[1], "transactions": 0, "amount": s.ZERO}
                    )
                    dest["transactions"] += 1
                    dest["amount"] += Decimal(row["amount"])
                rows = [{**r, "amount": s.money(r["amount"])} for r in grouped.values()]
        # Keep the output table flat, reusable by web/mobile and CSV.
        rows = [{k: v for k, v in row.items() if not isinstance(v, (dict, list))} for row in rows]
        columns = list(dict.fromkeys(k for row in rows for k in row))
        return {
            "name": name,
            "title": REPORTS[name],
            "start": str(start),
            "end": str(end),
            "method": method,
            "columns": columns,
            "rows": rows,
        }


def csv_export(report):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=report["columns"])
    writer.writeheader()
    for row in report["rows"]:
        cleaned = {}
        for key, value in row.items():
            if (
                isinstance(value, str)
                and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
                and not re.fullmatch(r"-?\d+(\.\d+)?", value)
            ):
                value = "'" + value
            cleaned[key] = value
        writer.writerow(cleaned)
    return output.getvalue()
