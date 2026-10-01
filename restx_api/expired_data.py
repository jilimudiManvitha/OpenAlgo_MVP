"""Common REST access to optional broker expired-derivatives data."""

import math
import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource

from limiter import limiter
from services.expired_data_service import get_expired_data

api = Namespace("expired", description="Expired futures/options discovery and historical data")
API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")


def _post(operation):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {"status": "error", "message": "A JSON object is required"}, 400
    payload = dict(payload)
    api_key = payload.pop("apikey", None)
    if not isinstance(api_key, str) or not 1 <= len(api_key.strip()) <= 256:
        return {"status": "error", "message": "apikey is required"}, 400
    _, body, status = get_expired_data(operation, payload, api_key=api_key)
    response = make_response(jsonify(body), status)
    response.headers["Cache-Control"] = "no-store"
    if status == 429 and isinstance(body.get("retry_after"), (int, float)):
        delay = body["retry_after"]
        if math.isfinite(delay):
            response.headers["Retry-After"] = str(max(1, math.ceil(delay)))
    return response


@api.route("/expiry-dates", strict_slashes=False)
class ExpiredExpiryDates(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Find available historical futures and options expiry dates."""
        return _post("expiry-dates")


@api.route("/contracts", strict_slashes=False)
class ExpiredContracts(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Discover provider-issued expired contract identifiers."""
        return _post("contracts")


@api.route("/history", strict_slashes=False)
class ExpiredHistory(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get intraday expired-contract OHLCV and optional open interest."""
        return _post("history")
