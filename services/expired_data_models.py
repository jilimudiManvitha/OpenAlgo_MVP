"""Broker-independent request contract for expired derivatives market data."""

from datetime import datetime
from zoneinfo import ZoneInfo

from marshmallow import Schema, ValidationError, fields, validate, validates_schema

INTERVALS = (
    "5s",
    "1m",
    "2m",
    "3m",
    "5m",
    "10m",
    "15m",
    "20m",
    "30m",
    "45m",
    "60m",
    "120m",
    "180m",
    "240m",
    "1h",
    "2h",
    "3h",
    "4h",
)


class UnderlyingSchema(Schema):
    symbol = fields.String(validate=validate.Length(min=1, max=128))
    exchange = fields.String(validate=validate.Length(min=1, max=20))
    broker_symbol = fields.String(validate=validate.Length(min=1, max=128))

    @validates_schema
    def identifier(self, data, **kwargs):
        raw = "broker_symbol" in data
        common = "symbol" in data or "exchange" in data
        if raw == common or (common and not {"symbol", "exchange"} <= data.keys()):
            raise ValidationError("Provide either broker_symbol or both symbol and exchange.")


class DateRangeSchema(Schema):
    start_date = fields.Date(required=True, format="%Y-%m-%d")
    end_date = fields.Date(required=True, format="%Y-%m-%d")

    @validates_schema
    def date_range(self, data, **kwargs):
        start, end = data["start_date"], data["end_date"]
        if start > end:
            raise ValidationError("start_date must not be after end_date.")
        if (end - start).days + 1 > 366:
            raise ValidationError("Request at most 366 inclusive calendar days at a time.")
        if end > datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise ValidationError("end_date must not be in the future.")


class ExpiredExpirySchema(UnderlyingSchema, DateRangeSchema):
    pass


class ExpiredContractsSchema(UnderlyingSchema):
    expiry_date = fields.Date(required=True, format="%Y-%m-%d")

    @validates_schema
    def expired(self, data, **kwargs):
        if data["expiry_date"] >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise ValidationError("expiry_date must be before today in Asia/Kolkata.")


class ExpiredHistorySchema(DateRangeSchema):
    # Opaque provider-issued identifier from contracts; never use today's master.
    broker_symbol = fields.String(required=True, validate=validate.Length(min=1, max=128))
    interval = fields.String(required=True, validate=validate.OneOf(INTERVALS))
    include_oi = fields.Boolean(load_default=True)
    include_greeks = fields.Boolean(load_default=False, validate=validate.Equal(False))

    @validates_schema
    def seconds_window(self, data, **kwargs):
        if data["interval"] == "5s" and (data["end_date"] - data["start_date"]).days >= 30:
            raise ValidationError("5s requests are limited to 30 calendar days per OpenAlgo call.")


SCHEMAS = {
    "expiry-dates": ExpiredExpirySchema(),
    "contracts": ExpiredContractsSchema(),
    "history": ExpiredHistorySchema(),
}


class ExpiredDataError(Exception):
    """A classified provider failure that must not become an empty success."""

    def __init__(self, message, status_code=502, code=None, retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retry_after = retry_after
