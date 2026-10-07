"""Session-authenticated investment bookkeeping; CSRF handled by the application."""

from datetime import datetime

from flask import Blueprint, Response, jsonify, request, session

from services import investment_service as service
from utils.session import check_session_validity

investments_bp = Blueprint("investments", __name__, url_prefix="/investments/api")


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise service.InvestmentError("A JSON object is required")
    return data


def user():
    owner = session.get("user")
    if not owner:
        raise service.InvestmentError("Sign in to access investments", 401)
    return owner


def result(data=None, status=200):
    return jsonify(status="success", data=data), status


@investments_bp.errorhandler(service.InvestmentError)
def invalid(error):
    return jsonify(status="error", message=str(error)), error.status


@investments_bp.teardown_request
def cleanup(_error):
    service.db_session.remove()


@investments_bp.route("/accounts", methods=["GET", "POST"])
@check_session_validity
def accounts():
    if request.method == "GET":
        return result(service.accounts(user()))
    return result(service.save_account(user(), payload()), 201)


@investments_bp.route("/accounts/<int:record_id>", methods=["PATCH", "DELETE"])
@check_session_validity
def account(record_id):
    if request.method == "PATCH":
        return result(service.save_account(user(), payload(), record_id))
    service.delete_account(user(), record_id)
    return result()


@investments_bp.route("/assets", methods=["GET", "POST"])
@check_session_validity
def assets():
    if request.method == "GET":
        return result(service.assets(user(), request.args.get("account_id")))
    return result(service.save_asset(user(), payload()), 201)


@investments_bp.route("/assets/<int:record_id>", methods=["PATCH", "DELETE"])
@check_session_validity
def asset(record_id):
    if request.method == "PATCH":
        return result(service.save_asset(user(), payload(), record_id))
    service.delete_asset(user(), record_id)
    return result()


@investments_bp.get("/holdings")
@check_session_validity
def holdings():
    return result(service.holdings(user(), request.args.get("account_id")))


@investments_bp.get("/holdings/<int:record_id>")
@check_session_validity
def holding(record_id):
    return result(service.holdings(user(), asset_id=record_id)[0])


@investments_bp.route("/transactions", methods=["GET", "POST"])
@check_session_validity
def transactions():
    if request.method == "POST":
        return result(service.save_transaction(user(), payload()), 201)
    try:
        limit, offset = int(request.args.get("limit", 200)), int(request.args.get("offset", 0))
        if limit < 1 or offset < 0:
            raise ValueError
    except ValueError:
        raise service.InvestmentError("Invalid pagination") from None
    return result(service.transactions(user(), request.args.get("asset_id"), limit, offset))


@investments_bp.delete("/transactions/<int:record_id>")
@check_session_validity
def delete_transaction(record_id):
    service.delete_transaction(user(), record_id)
    return result()


@investments_bp.post("/assets/<int:record_id>/price")
@check_session_validity
def price(record_id):
    data = payload()
    try:
        as_of = datetime.fromisoformat(data["as_of"].replace("Z", "+00:00"))
        if as_of.tzinfo is None:
            raise ValueError
    except (KeyError, AttributeError, TypeError, ValueError):
        raise service.InvestmentError("Price timestamp must include a timezone") from None
    return result(service.set_price(user(), record_id, data.get("price"), as_of))


@investments_bp.post("/prices/refresh")
@check_session_validity
def refresh():
    ids = payload().get("asset_ids")
    if ids is not None and (not isinstance(ids, list) or len(ids) > service.MAX_ASSETS):
        raise service.InvestmentError("asset_ids must be a list of at most 100 IDs")
    return result(service.refresh_prices(user(), session.get("broker"), ids))


@investments_bp.get("/dashboard")
@check_session_validity
def dashboard():
    return result(service.dashboard(user(), request.args.get("account_id")))


@investments_bp.get("/asset-classes")
@check_session_validity
def asset_classes():
    user()
    return result(service.ASSET_CLASSES)


@investments_bp.post("/prices/import")
@check_session_validity
def price_import():
    from services.investment_reports import import_prices

    data = payload()
    return result(import_prices(user(), data.get("csv"), data.get("account_id")))


@investments_bp.get("/reports/<name>")
@check_session_validity
def report(name):
    from services.investment_reports import build, csv_export

    data = build(
        user(),
        name,
        request.args.get("account_id"),
        request.args.get("start"),
        request.args.get("end"),
    )
    if request.args.get("download") == "csv":
        return Response(
            csv_export(data),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="investment-{name}.csv"'},
        )
    return result(data)


@investments_bp.route("/watchlists", methods=["GET", "POST"])
@check_session_validity
def watchlists():
    from services import investment_watchlists as watches

    return result(
        watches.lists(user()) if request.method == "GET" else watches.save(user(), payload())
    )


@investments_bp.route("/watchlists/<int:record_id>", methods=["PATCH", "DELETE"])
@check_session_validity
def watchlist(record_id):
    from services import investment_watchlists as watches

    if request.method == "DELETE":
        watches.remove(user(), record_id)
        return result()
    return result(watches.save(user(), payload(), record_id))


@investments_bp.post("/watchlists/<int:record_id>/items")
@check_session_validity
def watch_item(record_id):
    from services.investment_watchlists import save_item

    return result(save_item(user(), record_id, payload()))


@investments_bp.delete("/watch-items/<int:record_id>")
@check_session_validity
def delete_watch_item(record_id):
    from services.investment_watchlists import remove_item

    remove_item(user(), record_id)
    return result()


@investments_bp.route("/paper/gtt", methods=["GET", "POST"])
@check_session_validity
def paper_gtt():
    from services import investment_paper as paper

    return result(
        paper.orders(user()) if request.method == "GET" else paper.place(user(), payload())
    )


@investments_bp.post("/paper/sync")
@check_session_validity
def paper_sync():
    from services.investment_paper import reconcile

    return result(reconcile(user()))


@investments_bp.delete("/paper/gtt/<int:record_id>")
@check_session_validity
def cancel_paper_gtt(record_id):
    from services.investment_paper import cancel

    return result(cancel(user(), record_id))
