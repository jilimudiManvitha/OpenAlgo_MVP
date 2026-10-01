"""FYERS expired F&O discovery and candles, independent of the live master."""

import math
import re
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from broker.fyers.api.data import get_api_response
from database.symbol import db_session as symbol_session
from database.token_db import get_br_symbol
from services.expired_data_models import ExpiredDataError

BASE = "/data/history/fno/expired/"
IST = ZoneInfo("Asia/Kolkata")
AVAILABLE_FROM = {
    "NSE": date(2018, 10, 10),
    "BSE": date(2023, 8, 7),
    "MCX": date(2018, 10, 11),
}
RESOLUTIONS = {f"{n}m": str(n) for n in (1, 2, 3, 5, 10, 15, 20, 30, 45, 60, 120, 180, 240)}
RESOLUTIONS.update({"5s": "5S", "1h": "60", "2h": "120", "3h": "180", "4h": "240"})
BASE_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def _symbol(value, *, contract=False):
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:NSE|BSE|MCX):[A-Z0-9&_.-]{1,120}", value
    ):
        raise ExpiredDataError(
            "Provide a valid FYERS broker_symbol prefixed NSE:, BSE: or MCX:.", 400
        )
    if contract and not value.endswith(("FUT", "CE", "PE")):
        raise ExpiredDataError(
            "broker_symbol must identify an expired futures or options contract.", 400
        )
    return value


def _underlying(data):
    value = data.get("broker_symbol")
    if value is None:
        try:
            value = get_br_symbol(data["symbol"].strip().upper(), data["exchange"].strip().upper())
        finally:
            symbol_session.remove()
        if not value:
            raise ExpiredDataError(
                "Underlying not found in the master; provide its broker_symbol.", 400
            )
    return _symbol(value)


def _available(symbol, start):
    first = AVAILABLE_FROM[symbol.split(":", 1)[0]]
    if start < first:
        raise ExpiredDataError(f"Historical availability for this exchange starts on {first}.", 400)


def _bad_response():
    return ExpiredDataError("FYERS returned an invalid expired-data response.")


class BrokerExpiredData:
    def __init__(self, auth_token):
        self.auth_token = auth_token

    def _request(self, endpoint, params):
        # Shared pooled client, explicit timeout and process-wide history budget.
        # Surface 429 + Retry-After rather than blocking a request through long retries.
        response = get_api_response(
            BASE + endpoint + "?" + urlencode(params), self.auth_token, retry_429=False
        )
        if not isinstance(response, dict):
            raise _bad_response()
        if response.get("s") not in ("ok", "no_data"):
            code = response.get("code")
            status = 502
            if str(code) in ("401", "403", "-8", "-15", "-16", "-17"):
                status = 401
            elif str(code) in ("429", "-429"):
                status = 429
            elif str(code) in ("400", "404", "-50", "-300", "-99"):
                status = 400
            raise ExpiredDataError(
                response.get("message") or "FYERS expired-data request failed.",
                status,
                code,
                response.get("retry_after"),
            )
        return response

    def get_expiry_dates(self, data):
        symbol = _underlying(data)
        _available(symbol, data["start_date"])
        response = self._request(
            "expiry-dates",
            {
                "symbol": symbol,
                "range_from": data["start_date"].isoformat(),
                "range_to": data["end_date"].isoformat(),
                "date_format": 1,
            },
        )
        result = response.get("data")
        dates = result.get("expiry_dates") if isinstance(result, dict) else None
        if response["s"] != "ok" or not isinstance(dates, dict):
            raise _bad_response()
        output = {}
        for kind in ("futures", "options"):
            values = dates.get(kind)
            if not isinstance(values, list):
                raise _bad_response()
            try:
                parsed = [date.fromisoformat(value) for value in values]
                if any(not data["start_date"] <= value <= data["end_date"] for value in parsed):
                    raise ValueError("expiry outside requested range")
            except (TypeError, ValueError):
                raise _bad_response() from None
            output[kind] = sorted({value.isoformat() for value in parsed})
        return {
            "broker_symbol": symbol,
            "start_date": data["start_date"].isoformat(),
            "end_date": data["end_date"].isoformat(),
            "expiry_dates": output,
        }

    def get_contracts(self, data):
        symbol = _underlying(data)
        _available(symbol, data["expiry_date"])
        response = self._request(
            "underlying-symbols",
            {
                "symbol": symbol,
                "expiry_date": data["expiry_date"].isoformat(),
            },
        )
        result = response.get("data")
        contracts = result.get("contracts") if isinstance(result, dict) else None
        if (
            response["s"] != "ok"
            or not isinstance(contracts, dict)
            or result.get("expiry_date") != data["expiry_date"].isoformat()
        ):
            raise _bad_response()
        output = {}
        for kind, suffixes in (("futures", ("FUT",)), ("options", ("CE", "PE"))):
            values = contracts.get(kind)
            if not isinstance(values, list):
                raise _bad_response()
            for value in values:
                try:
                    _symbol(value, contract=True)
                except ExpiredDataError:
                    raise _bad_response() from None
                if not value.startswith(symbol.split(":", 1)[0] + ":") or not value.endswith(
                    suffixes
                ):
                    raise _bad_response()
            output[kind] = sorted(set(values))
        return {
            "broker_symbol": symbol,
            "expiry_date": data["expiry_date"].isoformat(),
            "contracts": output,
        }

    def get_history(self, data):
        symbol = _symbol(data["broker_symbol"], contract=True)
        _available(symbol, data["start_date"])
        resolution = RESOLUTIONS[data["interval"]]
        start, end = data["start_date"], data["end_date"]
        rows = {}
        empty_ranges = []
        while start <= end:
            stop = min(start + timedelta(days=99), end)
            response = self._request(
                "historical-data",
                {
                    "symbol": symbol,
                    "resolution": resolution,
                    "date_format": 1,
                    "range_from": start.isoformat(),
                    "range_to": stop.isoformat(),
                    "include_oi": int(data["include_oi"]),
                },
            )
            candles = self._candles(response, symbol, resolution, start, stop, data["include_oi"])
            if not candles:
                empty_ranges.append({"start_date": start.isoformat(), "end_date": stop.isoformat()})
            for row in candles:
                stamp = row["timestamp"]
                if stamp in rows and rows[stamp] != row:
                    raise ExpiredDataError("FYERS returned conflicting candles for one timestamp.")
                rows[stamp] = row
            start = stop + timedelta(days=1)
        return {
            "broker_symbol": symbol,
            "interval": data["interval"],
            "start_date": data["start_date"].isoformat(),
            "end_date": end.isoformat(),
            "data_status": "ok" if rows else "no_data",
            "empty_ranges": empty_ranges,
            "oi_included": data["include_oi"],
            "candles": [rows[stamp] for stamp in sorted(rows)],
        }

    @staticmethod
    def _candles(response, symbol, resolution, start, end, include_oi):
        candles = response.get("candles")
        if response["s"] == "no_data":
            if (
                candles not in (None, [])
                or response.get("symbol", symbol) != symbol
                or str(response.get("resolution", resolution)) != resolution
            ):
                raise _bad_response()
            return []
        columns = response.get("columns")
        required = BASE_COLUMNS + (["open_interest"] if include_oi else [])
        if (
            response.get("symbol") != symbol
            or str(response.get("resolution")) != resolution
            or response.get("schema_version") != 1
            or not isinstance(candles, list)
            or not isinstance(columns, list)
            or columns != required
        ):
            raise _bad_response()
        first = int(datetime.combine(start, time.min, IST).timestamp())
        last = int(datetime.combine(end + timedelta(days=1), time.min, IST).timestamp())
        result = []
        for candle in candles:
            if (
                not isinstance(candle, list)
                or len(candle) != len(columns)
                or any(
                    isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v)
                    for v in candle
                )
            ):
                raise _bad_response()
            row = dict(zip(columns, candle, strict=True))
            stamp = row["timestamp"]
            if (
                stamp != int(stamp)
                or not first <= stamp < last
                or min(candle[1:]) < 0
                or row["low"] > min(row["open"], row["close"])
                or row["high"] < max(row["open"], row["close"])
            ):
                raise _bad_response()
            row["timestamp"] = int(stamp)
            row["oi"] = row.pop("open_interest", 0)
            result.append(row)
        return result
