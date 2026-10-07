"""HTTP-only ledger partitioning by account kind; background jobs remain explicit.

Core table subqueries deliberately avoid recursive ORM criteria. No schema migration
or account relabelling is needed for existing ledgers.
"""

from flask import g, has_request_context, request, session
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session, with_loader_criteria

from database import investment_db as db
from database.settings_db import get_analyze_mode
from services.investment_service import InvestmentError


def active_mode():
    from database.settings_db import db_session

    try:
        return "paper" if get_analyze_mode() else "live"
    finally:
        db_session.remove()


def begin_request():
    mode = active_mode()
    expected = request.args.get("mode")
    if expected is not None and expected != mode:
        raise InvestmentError("Trading mode changed. Reload this page before continuing.", 409)
    broker = request.args.get("broker")
    if broker is not None and broker != session.get("broker", ""):
        raise InvestmentError("Broker changed. Reload this page before continuing.", 409)
    g.investment_mode = mode
    if "/paper/" in request.path and mode != "paper":
        raise InvestmentError("Switch to Sandbox to manage paper orders.", 409)
    data = request.get_json(silent=True)
    if request.path.startswith("/investments/api/accounts") and isinstance(data, dict):
        if data.get("kind", mode) != mode:
            raise InvestmentError("Account kind must match the selected Live/Sandbox mode.", 409)


def scope():
    if not has_request_context() or not hasattr(g, "investment_mode"):
        return None
    return g.investment_mode, session.get("user", "")


@event.listens_for(Session, "do_orm_execute")
def filter_ledger(execute_state):
    current = scope()
    if current is None or not (
        execute_state.is_select or execute_state.is_update or execute_state.is_delete
    ):
        return
    mode, owner = current
    accounts = db.InvestmentAccount.__table__
    assets = db.InvestmentAsset.__table__
    account_ids = select(accounts.c.id).where(accounts.c.kind == mode, accounts.c.user_id == owner)
    asset_ids = select(assets.c.id).where(
        assets.c.account_id.in_(account_ids), assets.c.user_id == owner
    )
    options = [
        with_loader_criteria(
            db.InvestmentAccount,
            (db.InvestmentAccount.kind == mode) & (db.InvestmentAccount.user_id == owner),
        ),
        with_loader_criteria(db.InvestmentAsset, db.InvestmentAsset.id.in_(asset_ids)),
    ]
    for model in (
        db.InvestmentTransaction,
        db.InvestmentLot,
        db.InvestmentValuation,
        db.InvestmentAssetDetails,
        db.InvestmentWatchItem,
        db.InvestmentPaperOrder,
    ):
        options.append(with_loader_criteria(model, model.asset_id.in_(asset_ids)))
    execute_state.statement = execute_state.statement.options(*options)


@event.listens_for(Session, "before_flush")
def guard_account_and_shared_watches(sql_session, _context, _instances):
    current = scope()
    if current is None:
        return
    mode, _owner = current
    from database.investment_execution_db import InvestmentExecution

    for row in sql_session.dirty | sql_session.deleted:
        if not isinstance(row, db.InvestmentAsset):
            continue
        changing = row in sql_session.deleted or any(
            inspect(row).attrs[field].history.has_changes()
            for field in ("account_id", "symbol", "exchange", "asset_class")
        )
        if (
            changing
            and sql_session.query(InvestmentExecution.id).filter_by(asset_id=row.id).first()
        ):
            raise InvestmentError(
                "Instruments with order history cannot be deleted or change identity.", 409
            )
    for row in sql_session.new | sql_session.dirty:
        if isinstance(row, db.InvestmentAccount) and row.kind != mode:
            raise InvestmentError("Accounts cannot move between Live and Sandbox.", 409)
    # Category names are shared. Never delete a category's hidden instruments.
    for row in sql_session.deleted:
        if isinstance(row, db.InvestmentWatchlist):
            item, asset, account = (
                m.__table__
                for m in (db.InvestmentWatchItem, db.InvestmentAsset, db.InvestmentAccount)
            )
            hidden = sql_session.execute(
                select(item.c.id)
                .join(asset, item.c.asset_id == asset.c.id)
                .join(account, asset.c.account_id == account.c.id)
                .where(item.c.watchlist_id == row.id, account.c.kind != mode)
                .limit(1)
            ).first()
            if hidden:
                raise InvestmentError(
                    "Remove this category's instruments in both modes before deleting it.", 409
                )
