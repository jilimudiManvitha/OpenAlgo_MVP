"""Authenticated optional expired-derivatives capability (FYERS initially)."""

import importlib

from marshmallow import ValidationError

from database.auth_db import db_session, get_auth_token_broker
from services.expired_data_models import SCHEMAS, ExpiredDataError
from utils.logging import get_logger

logger = get_logger(__name__)
METHODS = {
    "expiry-dates": "get_expiry_dates",
    "contracts": "get_contracts",
    "history": "get_history",
}


def get_expired_data(operation, data, *, api_key=None, auth_token=None, broker=None):
    """Return (success, response, HTTP status); data uses the common schemas.

    Data-only calls use actual market data even in Sandbox mode. No live master
    insertion, strategy mutation, persistence or order operation occurs here.
    """
    if operation not in SCHEMAS:
        return False, {"status": "error", "message": "Unknown expired-data operation"}, 400
    try:
        request_data = SCHEMAS[operation].load(data)
    except ValidationError as exc:
        return False, {"status": "error", "message": exc.messages}, 400
    try:
        if api_key is not None:
            try:
                auth_token, broker = get_auth_token_broker(api_key)
            finally:
                db_session.remove()
        if not auth_token or not broker:
            return (
                False,
                {"status": "error", "message": "Valid OpenAlgo API key and broker login required"},
                403,
            )
        module_name = f"broker.{broker}.api.expired_data"
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name not in (module_name, f"broker.{broker}", f"broker.{broker}.api"):
                raise
            return (
                False,
                {"status": "error", "message": f"Expired F&O data is not supported for {broker}"},
                501,
            )
        provider = module.BrokerExpiredData(auth_token)
        result = getattr(provider, METHODS[operation])(request_data)
        return True, {"status": "success", "broker": broker, "data": result}, 200
    except ExpiredDataError as exc:
        response = {"status": "error", "message": str(exc)}
        if exc.code is not None:
            response["code"] = exc.code
        if exc.retry_after is not None:
            response["retry_after"] = exc.retry_after
        return False, response, exc.status_code
    except Exception:
        logger.exception("Expired F&O data request failed")
        return False, {"status": "error", "message": "Unable to retrieve expired F&O data"}, 500
