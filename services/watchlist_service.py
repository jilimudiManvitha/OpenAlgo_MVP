"""API-key access to the same named watchlists used by the charting terminal."""

import re

from marshmallow import Schema, ValidationError, fields, validate, validates_schema
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from database.auth_db import db_session as auth_session
from database.auth_db import verify_api_key
from database.symbol import db_session as symbol_session
from database.token_db import get_tokens_bulk
from database.watchlist_db import (
    MAX_ITEMS_PER_LIST,
    MAX_LISTS_PER_USER,
    Watchlist,
    WatchlistItem,
    _serialize,
    db_session,
)
from utils.constants import VALID_EXCHANGES
from utils.logging import get_logger

logger = get_logger(__name__)
ACTIONS = ("list", "get", "create", "add", "remove", "replace", "rename", "delete")


class WatchlistRequest(Schema):
    action = fields.String(required=True, validate=validate.OneOf(ACTIONS))
    name = fields.String(validate=validate.Length(min=1, max=64))
    new_name = fields.String(validate=validate.Length(min=1, max=64))
    symbols = fields.Raw()
    exchange = fields.String(load_default="NSE")
    create_if_missing = fields.Boolean(load_default=False)

    @validates_schema
    def validate_action(self, data, **kwargs):
        if data["action"] != "list" and not data.get("name", "").strip():
            raise ValidationError("name is required.")
        if data["action"] == "rename" and not data.get("new_name", "").strip():
            raise ValidationError("new_name is required for rename.")
        if data["action"] in ("add", "remove", "replace") and "symbols" not in data:
            raise ValidationError("symbols is required for add, remove and replace.")
        if data["action"] not in ("create", "add", "remove", "replace") and "symbols" in data:
            raise ValidationError("This action does not accept symbols.")
        if data["action"] != "rename" and "new_name" in data:
            raise ValidationError("new_name is only valid for rename.")
        if data["create_if_missing"] and data["action"] != "add":
            raise ValidationError("create_if_missing is only valid for add.")


def parse_symbols(value, exchange="NSE"):
    """Accept pasted comma/space/newline lists or structured symbol pairs."""
    if not isinstance(exchange, str) or exchange.strip().upper() not in VALID_EXCHANGES:
        raise ValidationError("Invalid default exchange.")
    default_exchange = exchange.strip().upper()
    if isinstance(value, str):
        if len(value) > 25000:
            raise ValidationError("Symbol text is too long.")
        value = [token for token in re.split(r"[,;\s]+", value.strip()) if token]
    if not isinstance(value, list) or len(value) > MAX_ITEMS_PER_LIST:
        raise ValidationError(f"Provide at most {MAX_ITEMS_PER_LIST} symbols per request.")
    result = []
    for item in value:
        if isinstance(item, str):
            parts = item.strip().upper().split(":")
            if len(parts) == 1:
                venue, symbol = default_exchange, parts[0]
            elif len(parts) == 2:
                venue, symbol = parts
            else:
                raise ValidationError("Use SYMBOL or EXCHANGE:SYMBOL.")
        elif isinstance(item, dict) and set(item) <= {"symbol", "exchange"}:
            symbol, venue = item.get("symbol"), item.get("exchange", default_exchange)
            if not isinstance(symbol, str) or not isinstance(venue, str):
                raise ValidationError("Each item needs a string symbol and exchange.")
            symbol, venue = symbol.strip().upper(), venue.strip().upper()
        else:
            raise ValidationError("Symbols must be strings or symbol/exchange objects.")
        if venue not in VALID_EXCHANGES or not re.fullmatch(r"[A-Z0-9&_.-]{1,64}", symbol):
            raise ValidationError(f"Invalid instrument: {venue}:{symbol}.")
        pair = (symbol, venue)
        if pair not in result:
            result.append(pair)
    return result


class WatchlistError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _operate(user, data, pairs):
    """Apply a complete batch in one transaction, including cap checks."""
    action = data["action"]
    session = db_session()
    try:
        # Serialize SQLite writers before reading counts/items (multiple clients).
        if action not in ("list", "get") and session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        query = session.query(Watchlist).filter_by(user_id=user)
        if action == "list":
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "position": row.position,
                    "item_count": len(row.items),
                }
                for row in query.order_by(Watchlist.position, Watchlist.id)
            ]
        name = data["name"].strip()
        row = query.filter_by(name=name).with_for_update().first()
        if row is not None and action == "create":
            raise WatchlistError(f'A watchlist named "{name}" already exists.', 409)
        if row is None:
            if action != "create" and not (action == "add" and data["create_if_missing"]):
                raise WatchlistError(f'Watchlist "{name}" not found.', 404)
            count = query.count()
            if count >= MAX_LISTS_PER_USER:
                raise WatchlistError(f"Maximum {MAX_LISTS_PER_USER} watchlists reached.", 409)
            row = Watchlist(user_id=user, name=name, position=count)
            session.add(row)
            session.flush()
        before = {(item.symbol, item.exchange) for item in row.items}
        requested = set(pairs)
        changed = 0
        if action in ("create", "add", "replace"):
            desired_count = len(requested if action == "replace" else before | requested)
            if desired_count > MAX_ITEMS_PER_LIST:
                raise WatchlistError(
                    f"Watchlist would exceed {MAX_ITEMS_PER_LIST} instruments.", 409
                )
            if action == "replace":
                # Retain existing rows where possible; this avoids uniqueness conflicts.
                for item in list(row.items):
                    if (item.symbol, item.exchange) not in requested:
                        row.items.remove(item)
                        changed += 1
            position = max((item.position for item in row.items), default=-1) + 1
            by_pair = {(item.symbol, item.exchange): item for item in row.items}
            for offset, pair in enumerate(pairs):
                item = by_pair.get(pair)
                if item is None:
                    item = WatchlistItem(
                        symbol=pair[0], exchange=pair[1], position=position + offset
                    )
                    row.items.append(item)
                    changed += 1
                if action == "replace":
                    item.position = offset
        elif action == "remove":
            for item in list(row.items):
                if (item.symbol, item.exchange) in requested:
                    row.items.remove(item)
                    changed += 1
        elif action == "rename":
            row.name = data["new_name"].strip()
        elif action == "delete":
            identifier = row.id
            session.delete(row)
            session.commit()
            return {"id": identifier, "name": name, "deleted": True}
        if action != "get":
            session.commit()
            session.refresh(row)
        result = _serialize(row)
        result["items"] = sorted(result["items"], key=lambda item: item["position"])
        result["changed_items"] = changed
        if action == "add":
            result["already_present"] = [
                f"{venue}:{symbol}" for symbol, venue in pairs if (symbol, venue) in before
            ]
        if action == "remove":
            result["not_present"] = [
                f"{venue}:{symbol}" for symbol, venue in pairs if (symbol, venue) not in before
            ]
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        db_session.remove()


def manage_watchlist(data, *, api_key):
    try:
        if not isinstance(api_key, str) or not api_key.strip():
            return False, {"status": "error", "message": "Valid OpenAlgo API key required"}, 403
        try:
            user = verify_api_key(api_key)
        finally:
            auth_session.remove()
        if not user:
            return False, {"status": "error", "message": "Invalid OpenAlgo API key"}, 403
        payload = WatchlistRequest().load(data)
        pairs = parse_symbols(payload.get("symbols", []), payload["exchange"])
        if payload["action"] in ("add", "remove") and not pairs:
            raise ValidationError("Provide at least one symbol.")
        if payload["action"] in ("create", "add", "replace") and pairs:
            try:
                tokens = get_tokens_bulk(pairs)
            finally:
                symbol_session.remove()
            invalid = [
                f"{venue}:{symbol}"
                for (symbol, venue), token in zip(pairs, tokens, strict=True)
                if token is None
            ]
            if invalid:
                return (
                    False,
                    {
                        "status": "error",
                        "message": "Some symbols are absent from the current master; nothing changed.",
                        "invalid_symbols": invalid,
                    },
                    400,
                )
        result = _operate(user, payload, pairs)
        return True, {"status": "success", "data": result}, 200
    except ValidationError as exc:
        return False, {"status": "error", "message": exc.messages}, 400
    except WatchlistError as exc:
        return False, {"status": "error", "message": str(exc)}, exc.status
    except IntegrityError:
        return (
            False,
            {
                "status": "error",
                "message": "Watchlist name or symbols conflict; refresh and retry.",
            },
            409,
        )
    except Exception:
        logger.exception("Watchlist API operation failed")
        return False, {"status": "error", "message": "Unable to update/read watchlists"}, 500
