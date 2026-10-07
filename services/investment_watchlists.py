"""Categorized instrument watches; thresholds never place an order."""

from decimal import Decimal

from database.investment_db import InvestmentPaperOrder as PaperOrder
from database.investment_db import InvestmentWatchItem as Item
from database.investment_db import InvestmentWatchlist as Watchlist
from services import investment_service as s

CATEGORIES = ("Swing", "Positional", "Long-term", "ETFs", "Mutual Funds", "Other")


def lists(user):
    holdings = {row["id"]: row for row in s.holdings(user)}
    with s.transaction() as session:
        output = []
        for watch in session.query(Watchlist).filter_by(user_id=user).order_by(Watchlist.id):
            items = []
            for item in session.query(Item).filter_by(watchlist_id=watch.id, user_id=user):
                asset = holdings[item.asset_id]
                price = Decimal(asset["price"]) if asset["price"] is not None else None
                observation = "No dated price available"
                if price is not None:
                    observation = "Latest recorded price within thresholds"
                    if item.stop_price is not None and price <= item.stop_price:
                        observation = "Latest recorded price at/below watch stop"
                    if item.target_price is not None and price >= item.target_price:
                        observation = "Latest recorded price at/above watch target"
                items.append({**s.serialize(item), "asset": asset, "observation": observation})
            output.append({**s.serialize(watch), "items": items})
        return output


def save(user, payload, record_id=None):
    with s.transaction(True) as session:
        watch = (
            s.owned(session, Watchlist, user, record_id) if record_id else Watchlist(user_id=user)
        )
        if not record_id:
            if session.query(Watchlist).filter_by(user_id=user).count() >= 50:
                raise s.InvestmentError("Maximum 50 watchlists", 409)
            session.add(watch)
        watch.name = s.string(payload.get("name", watch.name), "name")
        watch.category = payload.get("category", watch.category)
        if watch.category not in CATEGORIES:
            raise s.InvestmentError("Choose a supported watchlist category")
        session.flush()
        return s.serialize(watch)


def remove(user, record_id):
    with s.transaction(True) as session:
        watch = s.owned(session, Watchlist, user, record_id)
        if session.query(PaperOrder).filter_by(watchlist_id=watch.id).first():
            raise s.InvestmentError("Watchlists with paper-order history are preserved", 409)
        session.query(Item).filter_by(watchlist_id=watch.id).delete()
        session.delete(watch)


def save_item(user, watchlist_id, payload):
    with s.transaction(True) as session:
        watch = s.owned(session, Watchlist, user, watchlist_id)
        asset = s.owned(session, s.Asset, user, payload.get("asset_id"))
        row = session.query(Item).filter_by(watchlist_id=watch.id, asset_id=asset.id).first()
        if row is None:
            row = Item(user_id=user, watchlist_id=watch.id, asset_id=asset.id)
            session.add(row)
        row.stop_price = (
            s.decimal(payload["stop_price"], "stop_price", positive=True)
            if payload.get("stop_price")
            else None
        )
        row.target_price = (
            s.decimal(payload["target_price"], "target_price", positive=True)
            if payload.get("target_price")
            else None
        )
        if row.stop_price and row.target_price and row.stop_price >= row.target_price:
            raise s.InvestmentError("Watch stop must be below watch target")
        session.flush()
        return s.serialize(row)


def remove_item(user, record_id):
    with s.transaction(True) as session:
        session.delete(s.owned(session, Item, user, record_id))
