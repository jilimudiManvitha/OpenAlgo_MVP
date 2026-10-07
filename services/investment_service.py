"""Decimal ledger, atomic replay, owner-scoped CRUD and explicit dated valuations.

A recorded transaction is bookkeeping only. This module never submits orders.
FIFO lots coexist with weighted-average holdings; backdated edits replay both.
"""

import json
import math
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from database.investment_db import (
    InvestmentAccount as Account,
)
from database.investment_db import (
    InvestmentAsset as Asset,
)
from database.investment_db import (
    InvestmentAssetDetails as Details,
)
from database.investment_db import (
    InvestmentLot as Lot,
)
from database.investment_db import (
    InvestmentPaperFill as PaperFill,
)
from database.investment_db import (
    InvestmentPaperOrder as PaperOrder,
)
from database.investment_db import (
    InvestmentTransaction as Transaction,
)
from database.investment_db import (
    InvestmentValuation as Valuation,
)
from database.investment_db import (
    InvestmentWatchItem as WatchItem,
)
from database.investment_db import (
    db_session,
    now,
)

ZERO = Decimal("0")
CHARGES = ("brokerage", "stt", "gst", "stamp_duty", "sebi", "exchange_charges")
IST = ZoneInfo("Asia/Kolkata")
MAX_ASSETS = 100
MAX_TRANSACTIONS = 10000
ASSET_CLASSES = {
    "STOCK": (),
    "MUTUAL_FUND": ("fund_house", "plan", "folio"),
    "FIXED_INCOME": ("issuer", "maturity_date", "interest_rate"),
    "BULLION": ("metal", "purity", "unit"),
    "ULIP": ("insurer", "policy_number", "maturity_date"),
    "PROPERTY": ("address", "area", "unit"),
    "OTHER_ASSET": ("description",),
    "LOAN": ("lender", "interest_rate", "maturity_date"),
    "OTHER_BORROWING": ("lender", "description", "maturity_date"),
}
LIABILITIES = {"LOAN", "OTHER_BORROWING"}


class InvestmentError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def decimal(value, field, places=4, positive=False):
    try:
        if isinstance(value, bool):
            raise ValueError
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result >= Decimal("1000000000000"):
            raise ValueError
        if result != result.quantize(Decimal(1).scaleb(-places)) or (positive and result == 0):
            raise ValueError
        return result
    except (ValueError, InvalidOperation):
        raise InvestmentError(
            f"{field} must be a {'positive' if positive else 'nonnegative'} number with at most {places} decimal places"
        ) from None


def string(value, field, maximum=80, required=True):
    if (
        not isinstance(value, str)
        or len(value.strip()) > maximum
        or (required and not value.strip())
    ):
        raise InvestmentError(
            f"{field} must be text of 1–{maximum} characters"
            if required
            else f"{field} must be text up to {maximum} characters"
        )
    return value.strip()


def identifier(value):
    if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
        raise InvestmentError("Invalid record ID")
    return int(value)


def serialize(row):
    output = {}
    for column in row.__table__.columns:
        if column.name == "user_id":
            continue
        value = getattr(row, column.name)
        if isinstance(value, Decimal):
            value = format(value, "f")
        elif isinstance(value, (date, datetime, time)):
            value = value.isoformat()
        output[column.name] = value
    return output


def asset_data(session, asset):
    details = session.get(Details, asset.id)
    return {**serialize(asset), "details": json.loads(details.details) if details else {}}


@contextmanager
def transaction(write=False):
    session = db_session()
    try:
        if write and session.bind.dialect.name == "sqlite":
            # Serializes read/replay/write, including simultaneous sells and backdated edits.
            session.execute(text("BEGIN IMMEDIATE"))
        yield session
        if write:
            session.commit()
    except IntegrityError:
        session.rollback()
        raise InvestmentError("That account or instrument already exists", 409) from None
    except Exception:
        session.rollback()
        raise
    finally:
        db_session.remove()


def owned(session, model, user, record_id):
    statement = select(model).where(model.id == identifier(record_id), model.user_id == user)
    row = session.execute(statement.with_for_update()).scalar_one_or_none()
    if row is None:
        raise InvestmentError("Record not found", 404)
    return row


def records(session, asset_id):
    return session.scalars(
        select(Transaction)
        .where(Transaction.asset_id == asset_id)
        .order_by(Transaction.trade_date, Transaction.trade_time, Transaction.id)
    ).all()


def replay(rows):
    """Pure chronological replay. Costs stay Decimal until presentation, never float."""
    qty = cost = realized = income = fifo_realized = ZERO
    lots = []
    realizations = []
    for row in rows:
        q, price = row.quantity, row.price
        charges = sum((getattr(row, name) for name in CHARGES), ZERO)
        if row.action == "BUY":
            basis = q * price + charges
            qty += q
            cost += basis
            if qty >= Decimal("100000000000000") or cost >= Decimal("100000000000000"):
                raise InvestmentError("Holding exceeds supported ledger precision")
            lots.append(
                {
                    "transaction_id": row.id,
                    "opened_at": datetime.combine(row.trade_date, row.trade_time),
                    "quantity_remaining": q,
                    "cost_per_unit": basis / q,
                    "quantity_closed": ZERO,
                    "realized_gain": ZERO,
                }
            )
        elif row.action == "SELL":
            if q > qty:
                raise InvestmentError("Sale exceeds the quantity held at this trade timestamp", 409)
            average = cost / qty
            realized += q * (price - average) - charges
            cost -= q * average
            qty -= q
            left = q
            for lot in lots:
                taken = min(left, lot["quantity_remaining"])
                gain = taken * (price - charges / q - lot["cost_per_unit"])
                lot["quantity_remaining"] -= taken
                lot["quantity_closed"] += taken
                lot["realized_gain"] += gain
                fifo_realized += gain
                if taken:
                    realizations.append(
                        {
                            "buy_transaction_id": lot["transaction_id"],
                            "sell_transaction_id": row.id,
                            "bought_on": lot["opened_at"].date().isoformat(),
                            "sold_on": row.trade_date.isoformat(),
                            "quantity": format(taken, "f"),
                            "cost": money(taken * lot["cost_per_unit"]),
                            "proceeds": money(taken * (price - charges / q)),
                            "gain": money(gain),
                            "days_held": (row.trade_date - lot["opened_at"].date()).days,
                        }
                    )
                left -= taken
                if left == 0:
                    break
            if qty == 0:
                cost = ZERO
        elif row.action in ("DIVIDEND", "INTEREST"):
            income += q * price - charges
        elif row.action == "CORPORATE_ACTION":
            ratio = row.corporate_ratio
            if not ratio or qty == 0:
                raise InvestmentError(
                    "A split requires an existing holding and a positive new-to-old ratio", 409
                )
            # Explicit split: preserve remaining cost and opening dates in both policies.
            for lot in lots:
                changed = lot["quantity_remaining"] * ratio
                if changed != changed.quantize(Decimal(".000001")):
                    raise InvestmentError(
                        "Split creates fractional units beyond six decimal places"
                    )
                lot["quantity_remaining"] = changed
                lot["cost_per_unit"] /= ratio
            qty *= ratio
            if qty >= Decimal("100000000000000"):
                raise InvestmentError("Split exceeds supported quantity precision")
    actual_qty = sum((lot["quantity_remaining"] for lot in lots), ZERO)
    assert actual_qty == qty
    return {
        "quantity": actual_qty,
        "invested": cost,
        "average_cost": cost / qty if qty else ZERO,
        "realized_gain": realized + income,
        "trading_realized": realized,
        "income": income,
        "fifo_realized": fifo_realized,
        "lots": lots,
        "realizations": realizations,
    }


def rebuild(session, asset):
    state = replay(records(session, asset.id))
    session.query(Lot).filter_by(asset_id=asset.id).delete(synchronize_session=False)
    for lot in state["lots"]:
        session.add(
            Lot(asset_id=asset.id, **lot, status="open" if lot["quantity_remaining"] else "closed")
        )
    session.flush()
    return state


def accounts(user):
    with transaction() as session:
        return [
            serialize(row)
            for row in session.scalars(
                select(Account).where(Account.user_id == user).order_by(Account.id)
            )
        ]


def save_account(user, payload, record_id=None):
    with transaction(True) as session:
        if record_id is not None:
            row = owned(session, Account, user, record_id)
        else:
            if session.query(Account).filter_by(user_id=user).count() >= 50:
                raise InvestmentError("Maximum 50 accounts", 409)
            row = Account(user_id=user)
            session.add(row)
        row.name = string(payload.get("name", row.name), "name")
        row.broker_label = string(
            payload.get("broker_label", row.broker_label or "Manual"), "broker_label"
        )
        row.kind = payload.get("kind", row.kind or "paper")
        if row.kind not in ("paper", "live"):
            raise InvestmentError("kind must be paper or live (informational label)")
        session.flush()
        return serialize(row)


def delete_account(user, record_id):
    with transaction(True) as session:
        row = owned(session, Account, user, record_id)
        if session.query(Asset).filter_by(account_id=row.id).first():
            raise InvestmentError("Remove the account’s instruments first", 409)
        session.delete(row)


def assets(user, account_id=None):
    with transaction() as session:
        query = select(Asset).where(Asset.user_id == user)
        if account_id is not None:
            owned(session, Account, user, account_id)
            query = query.where(Asset.account_id == identifier(account_id))
        return [asset_data(session, row) for row in session.scalars(query.order_by(Asset.id))]


def save_asset(user, payload, record_id=None):
    with transaction(True) as session:
        if record_id is not None:
            row = owned(session, Asset, user, record_id)
            # Financial identity is immutable after any ledger entry.
            if (
                records(session, row.id)
                or session.query(PaperOrder).filter_by(asset_id=row.id).first()
            ):
                for key in ("account_id", "symbol", "exchange", "asset_class", "scheme_code"):
                    if key in payload and str(payload[key] or "") != str(getattr(row, key) or ""):
                        raise InvestmentError(
                            "An instrument with transactions cannot change identity", 409
                        )
        else:
            if session.query(Asset).filter_by(user_id=user).count() >= MAX_ASSETS:
                raise InvestmentError(f"Maximum {MAX_ASSETS} instruments", 409)
            row = Asset(user_id=user)
            session.add(row)
        account = owned(session, Account, user, payload.get("account_id", row.account_id))
        row.account_id = account.id
        row.asset_class = payload.get("asset_class", row.asset_class or "STOCK")
        if row.asset_class not in ASSET_CLASSES:
            raise InvestmentError("Unsupported asset class")
        row.symbol = string(payload.get("symbol", row.symbol), "symbol").upper()
        row.exchange = string(
            payload.get(
                "exchange", row.exchange or ("NSE" if row.asset_class == "STOCK" else "MANUAL")
            ),
            "exchange",
            12,
        ).upper()
        if row.asset_class == "STOCK" and row.exchange not in ("NSE", "BSE"):
            raise InvestmentError("Stocks require NSE or BSE")
        if row.asset_class != "STOCK" and row.exchange != "MANUAL":
            raise InvestmentError("Non-stock assets use MANUAL valuations")
        row.scheme_code = (
            string(payload.get("scheme_code", row.scheme_code or ""), "scheme_code", 32, False)
            or None
        )
        row.name = string(payload.get("name", row.name or row.symbol), "name", 120)
        row.notes = string(payload.get("notes", row.notes or ""), "notes", 2000, False)
        watch = payload.get("is_watch_only", row.is_watch_only or False)
        if not isinstance(watch, bool):
            raise InvestmentError("is_watch_only must be boolean")
        if watch and record_id is not None and records(session, row.id):
            raise InvestmentError("An instrument with transactions cannot become watch-only", 409)
        row.is_watch_only = watch
        row.price_source = "live" if row.asset_class == "STOCK" else "manual"
        session.flush()
        if "details" in payload:
            details = payload["details"]
            if not isinstance(details, dict) or set(details) - set(ASSET_CLASSES[row.asset_class]):
                raise InvestmentError("Unsupported fields for this asset class")
            cleaned = {k: string(v, k, 300, False) for k, v in details.items()}
            for key in ("maturity_date",):
                if cleaned.get(key):
                    try:
                        date.fromisoformat(cleaned[key])
                    except ValueError:
                        raise InvestmentError("Invalid maturity date") from None
            if cleaned.get("interest_rate"):
                decimal(cleaned["interest_rate"], "interest_rate")
            record = session.get(Details, row.id)
            if record is None:
                record = Details(asset_id=row.id)
                session.add(record)
            record.details = json.dumps(cleaned)
            session.flush()
        return asset_data(session, row)


def delete_asset(user, record_id):
    with transaction(True) as session:
        row = owned(session, Asset, user, record_id)
        if records(session, row.id):
            raise InvestmentError(
                "Remove transactions explicitly before deleting this instrument", 409
            )
        if session.query(PaperOrder).filter_by(asset_id=row.id).first():
            raise InvestmentError("An instrument with paper-order history cannot be deleted", 409)
        session.query(WatchItem).filter_by(asset_id=row.id).delete()
        session.query(Details).filter_by(asset_id=row.id).delete()
        session.query(Valuation).filter_by(asset_id=row.id).delete()
        session.query(Lot).filter_by(asset_id=row.id).delete()
        session.delete(row)


def save_transaction(user, payload):
    with transaction(True) as session:
        asset = owned(session, Asset, user, payload.get("asset_id"))
        if asset.is_watch_only:
            raise InvestmentError(
                "Convert this watch-only instrument before recording a purchase", 409
            )
        if session.query(Transaction).filter_by(asset_id=asset.id).count() >= MAX_TRANSACTIONS:
            raise InvestmentError("Maximum transaction count reached", 409)
        action = payload.get("action")
        if action not in ("BUY", "SELL", "DIVIDEND", "INTEREST", "CORPORATE_ACTION"):
            raise InvestmentError("Unsupported transaction action")
        if asset.asset_class in LIABILITIES and action in ("DIVIDEND", "CORPORATE_ACTION"):
            raise InvestmentError(
                "Liabilities support borrowing (BUY), repayment (SELL) and interest paid"
            )
        try:
            day = date.fromisoformat(payload["trade_date"])
            clock = time.fromisoformat(payload["trade_time"])
            if clock.tzinfo is not None or clock.microsecond or day > datetime.now(IST).date():
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise InvestmentError(
                "A valid trade date and time in IST are required; future dates are not allowed"
            ) from None
        q = decimal(payload.get("quantity"), "quantity", 6, True)
        price = decimal(payload.get("price"), "price", positive=action != "CORPORATE_ACTION")
        fees = {name: decimal(payload.get(name, "0"), name) for name in CHARGES}
        if q * price + sum(fees.values(), ZERO) >= Decimal("100000000000000"):
            raise InvestmentError("Transaction amount exceeds supported ledger precision")
        notes = string(payload.get("notes", ""), "notes", 2000, False)
        ratio = None
        if action == "CORPORATE_ACTION":
            ratio = decimal(payload.get("corporate_ratio"), "corporate_ratio", 6, True)
            if not notes or price != 0 or any(fees.values()) or q != 1:
                raise InvestmentError(
                    "Split: quantity 1, price/charges 0, ratio and explanatory notes required"
                )
        row = Transaction(
            user_id=user,
            asset_id=asset.id,
            action=action,
            quantity=q,
            price=price,
            trade_date=day,
            trade_time=clock,
            notes=notes,
            corporate_ratio=ratio,
            **fees,
        )
        session.add(row)
        session.flush()
        rebuild(session, asset)
        return serialize(row)


def delete_transaction(user, record_id):
    with transaction(True) as session:
        row = owned(session, Transaction, user, record_id)
        if session.query(PaperFill).filter_by(transaction_id=row.id).first():
            raise InvestmentError("Confirmed sandbox fills cannot be deleted from the ledger", 409)
        asset = owned(session, Asset, user, row.asset_id)
        session.query(Lot).filter_by(asset_id=asset.id).delete(synchronize_session=False)
        session.delete(row)
        session.flush()
        rebuild(session, asset)  # A deletion that causes a historical oversell rolls back.


def transactions(user, asset_id=None, limit=200, offset=0):
    with transaction() as session:
        query = select(Transaction).where(Transaction.user_id == user)
        if asset_id is not None:
            owned(session, Asset, user, asset_id)
            query = query.where(Transaction.asset_id == identifier(asset_id))
        return [
            serialize(row)
            for row in session.scalars(
                query.order_by(
                    Transaction.trade_date.desc(),
                    Transaction.trade_time.desc(),
                    Transaction.id.desc(),
                )
                .limit(min(limit, 500))
                .offset(offset)
            )
        ]


def set_price(user, asset_id, price, as_of, source="manual", previous_close=None):
    price = decimal(price, "price", positive=True)
    previous_close = (
        decimal(previous_close, "previous_close", positive=True)
        if previous_close is not None
        else None
    )
    if as_of.tzinfo:
        as_of = as_of.astimezone(UTC).replace(tzinfo=None)
    if as_of > now() + timedelta(minutes=1):
        raise InvestmentError("Valuation cannot be in the future")
    with transaction(True) as session:
        asset = owned(session, Asset, user, asset_id)
        row = (
            session.query(Valuation)
            .filter_by(asset_id=asset.id, as_of=as_of, source=source)
            .first()
        )
        if row is None:
            row = Valuation(asset_id=asset.id, as_of=as_of, source=source)
            session.add(row)
        row.price, row.previous_close = price, previous_close
        if source == "manual":
            asset.manual_price, asset.price_as_of = price, as_of
        session.flush()
        return serialize(row)


def money(value):
    return format(value.quantize(Decimal(".0001")), "f") if value is not None else None


def valuation_matches_units(valuation, transactions):
    """A price before a recorded split cannot value the post-split units."""
    if valuation is None:
        return False
    observed = valuation.as_of.replace(tzinfo=UTC).astimezone(IST).replace(tzinfo=None)
    return not any(
        row.action == "CORPORATE_ACTION"
        and datetime.combine(row.trade_date, row.trade_time) > observed
        for row in transactions
    )


def holdings(user, account_id=None, asset_id=None):
    with transaction() as session:
        query = select(Asset).where(Asset.user_id == user)
        if account_id is not None:
            owned(session, Account, user, account_id)
            query = query.where(Asset.account_id == identifier(account_id))
        if asset_id is not None:
            owned(session, Asset, user, asset_id)
            query = query.where(Asset.id == identifier(asset_id))
        output = []
        for asset in session.scalars(query.order_by(Asset.id)):
            history = records(session, asset.id)
            state = replay(history)
            liability = asset.asset_class in LIABILITIES
            if liability:
                for key in (
                    "invested",
                    "realized_gain",
                    "trading_realized",
                    "income",
                    "fifo_realized",
                ):
                    state[key] = -state[key]
            valuation = session.scalars(
                select(Valuation)
                .where(Valuation.asset_id == asset.id)
                .order_by(Valuation.as_of.desc(), Valuation.id.desc())
                .limit(1)
            ).first()
            if not valuation_matches_units(valuation, history):
                valuation = None
            price = valuation.price if valuation else None
            stale = (
                not valuation
                or valuation.source != "broker_timestamp"
                or now() - valuation.as_of > timedelta(minutes=5)
            )
            value = (
                state["quantity"] * price * (-1 if liability else 1) if price is not None else None
            )
            pnl = value - state["invested"] if value is not None else None
            # Only a dated, current broker quote can support today's change.
            today = None
            if valuation and not stale and valuation.previous_close:
                today = state["quantity"] * (price - valuation.previous_close)
            first = min(
                (lot["opened_at"] for lot in state["lots"] if lot["quantity_remaining"]),
                default=None,
            )
            output.append(
                {
                    **asset_data(session, asset),
                    "is_liability": liability,
                    **{
                        key: money(val)
                        for key, val in state.items()
                        if key not in ("lots", "realizations")
                    },
                    "quantity": format(state["quantity"].quantize(Decimal(".000001")), "f"),
                    "price": money(price),
                    "market_value": money(value),
                    "unrealized_gain": money(pnl),
                    "return_percent": money(pnl / abs(state["invested"]) * 100)
                    if pnl is not None and state["invested"]
                    else None,
                    "today_gain": money(today),
                    "price_as_of": valuation.as_of.isoformat() + "Z" if valuation else None,
                    "valuation_source": valuation.source if valuation else "unpriced",
                    "stale": stale,
                    "days_held": (datetime.now(IST).date() - first.date()).days if first else 0,
                }
            )
        return output


def dashboard(user, account_id=None):
    all_holdings = holdings(user, account_id)
    rows = [
        row for row in all_holdings if Decimal(row["quantity"]) > 0 and not row["is_watch_only"]
    ]
    invested = sum((Decimal(row["invested"]) for row in rows), ZERO)
    valued = [row for row in rows if row["market_value"] is not None]
    complete = len(rows) == len(valued)
    value = sum((Decimal(row["market_value"]) for row in valued), ZERO)
    pnl = value - invested if complete else None
    all_today = bool(rows) and all(row["today_gain"] is not None for row in rows)
    today = sum((Decimal(row["today_gain"]) for row in rows), ZERO) if all_today else None
    score_rows = [row for row in rows if not row["is_liability"] and Decimal(row["invested"]) > 0]
    gross_cost = sum((Decimal(row["invested"]) for row in score_rows), ZERO)
    weights = (
        [float(Decimal(row["invested"]) / gross_cost) for row in score_rows] if gross_cost else []
    )
    hhi = sum(w * w for w in weights)
    entropy = -sum(w * math.log(w) for w in weights if w > 0)
    diversification = 100 * entropy / math.log(10) if weights else 0
    return {
        "holdings": rows,
        "invested": money(invested),
        "market_value": money(value) if complete else None,
        "priced_value": money(value),
        "unrealized_gain": money(pnl),
        "return_percent": money(pnl / abs(invested) * 100)
        if pnl is not None and invested
        else None,
        "today_gain": money(today),
        "today_percent": money(today / (value - today) * 100)
        if today is not None and value != today
        else None,
        "realized_gain": money(sum((Decimal(r["realized_gain"]) for r in all_holdings), ZERO)),
        "winners": sum(Decimal(r["unrealized_gain"]) > 0 for r in valued),
        "losers": sum(Decimal(r["unrealized_gain"]) < 0 for r in valued),
        "unpriced": len(rows) - len(valued),
        "stale": sum(r["stale"] for r in rows),
        "score": portfolio_score(user, score_rows, weights, hhi, diversification),
    }


def portfolio_score(user, rows, weights, hhi, diversification):
    defensive = sum(
        w for row, w in zip(rows, weights, strict=True) if row["asset_class"] == "FIXED_INCOME"
    )
    quality = 50 * (1 - hhi) + 50 * defensive if weights else None
    diversity = min(100, diversification) if weights else None
    returns = []
    with transaction() as session:
        for row in rows:
            latest = session.scalars(
                select(Valuation)
                .where(Valuation.asset_id == row["id"])
                .order_by(Valuation.as_of.desc())
                .limit(1)
            ).first()
            if latest is None or now() - latest.as_of > timedelta(days=1):
                break
            cutoff = latest.as_of - timedelta(days=30)
            previous = session.scalars(
                select(Valuation)
                .where(
                    Valuation.asset_id == row["id"],
                    Valuation.as_of <= cutoff,
                    Valuation.as_of >= cutoff - timedelta(days=7),
                )
                .order_by(Valuation.as_of.desc())
                .limit(1)
            ).first()
            if previous is None:
                break
            # Unadjusted price histories crossing a split cannot support momentum.
            splits = (
                session.query(Transaction)
                .filter(
                    Transaction.asset_id == row["id"],
                    Transaction.action == "CORPORATE_ACTION",
                    Transaction.trade_date >= previous.as_of.date(),
                )
                .count()
            )
            if splits:
                break
            returns.append(float(latest.price / previous.price - 1))
    momentum = composite = None
    if weights and len(returns) == len(weights):
        mean = sum(w * r for w, r in zip(weights, returns, strict=True))
        dispersion = math.sqrt(
            sum(w * (r - mean) ** 2 for w, r in zip(weights, returns, strict=True))
        )
        momentum = max(0, min(100, 50 + 500 * mean - 100 * dispersion))
        composite = 0.4 * quality + 0.3 * diversity + 0.3 * momentum
    return {
        "quality": round(quality, 1) if quality is not None else None,
        "diversification": round(diversity, 1) if diversity is not None else None,
        "momentum": round(momentum, 1) if momentum is not None else None,
        "composite": round(composite, 1) if composite is not None else None,
        "method": "Cost-weighted allocation measures on positive assets, excluding liabilities, not fundamental ratings: quality = 50 × (1 − sum of squared weights) + 50 × fixed-income cost share. Diversification = 100 × weight entropy / ln(10), capped at 100. Momentum = clamp(50 + 500 × weighted 30-day price return − 100 × return standard deviation, 0, 100). Composite = 40% quality + 30% diversification + 30% momentum. Momentum needs every holding’s latest price within one day and a 30–37-day prior price, with no intervening split. Missing inputs show unavailable. Manual prices are included as recorded, not independently verified.",
    }


def refresh_prices(user, broker, asset_ids=None):
    """Explicit bounded refresh; quotes without provider timestamps remain dated snapshots."""
    from database.auth_db import get_auth_token
    from services.quotes_service import get_quotes

    token = get_auth_token(user)
    if not token or not broker:
        raise InvestmentError("Sign in to your broker to refresh prices", 409)
    selected = assets(user)
    if asset_ids is not None:
        ids = {identifier(value) for value in asset_ids}
        if ids - {row["id"] for row in selected}:
            raise InvestmentError("Record not found", 404)
        selected = [row for row in selected if row["id"] in ids]
    selected = [row for row in selected if row["asset_class"] == "STOCK"]
    failures, updated = [], 0
    for asset in selected:
        try:
            ok, response, _ = get_quotes(
                asset["symbol"], asset["exchange"], auth_token=token, broker=broker
            )
            if not ok:
                failures.append(asset["symbol"])
                continue
            data = response["data"]
            # Normalized quotes don't guarantee a provider timestamp. Never invent one.
            set_price(
                user,
                asset["id"],
                data["ltp"],
                now(),
                source="broker_snapshot",
                previous_close=data.get("prev_close") or None,
            )
            updated += 1
        except (InvestmentError, KeyError, TypeError):
            failures.append(asset["symbol"])
    return {
        "updated": updated,
        "failed": failures,
        "message": "Broker snapshots carry fetch time; trade timestamps are unavailable. Last saved prices remain visible on failure.",
    }
