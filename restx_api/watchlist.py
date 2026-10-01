"""Application API-key watchlists for MCP and terminal clients."""

import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource

from limiter import limiter
from services.watchlist_service import manage_watchlist

api = Namespace("watchlist", description="Manage the user's saved charting watchlists")


@api.route("/", strict_slashes=False)
class WatchlistAPI(Resource):
    @limiter.limit(os.getenv("API_RATE_LIMIT", "10 per second"))
    def post(self):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return {"status": "error", "message": "A JSON object is required"}, 400
        payload = dict(payload)
        key = payload.pop("apikey", None)
        if not isinstance(key, str) or not 1 <= len(key) <= 256:
            return {"status": "error", "message": "apikey is required"}, 400
        _, body, status = manage_watchlist(payload, api_key=key)
        response = make_response(jsonify(body), status)
        response.headers["Cache-Control"] = "no-store"
        return response
