"""Estimate fees only for fills newly imported by an explicit Sandbox sync.

Existing fills and manually recorded charges are preserved. Legacy paper links
lack broker provenance, so the current logged-in broker assumption is recorded.
"""

from decimal import Decimal

from services import investment_paper as paper
from services import investment_service as s
from services.investment_execution import estimate


def reconcile(user, broker):
    with s.transaction() as session:
        before = {row.transaction_id for row in session.query(s.PaperFill).filter_by(user_id=user)}
    result = paper.reconcile(user)
    with s.transaction(True) as session:
        fills = session.query(s.PaperFill).filter_by(user_id=user).all()
        for fill in fills:
            if fill.transaction_id in before:
                continue
            tx = s.owned(session, s.Transaction, user, fill.transaction_id)
            if any(getattr(tx, key) for key in s.CHARGES):
                continue
            asset = s.owned(session, s.Asset, user, tx.asset_id)
            fee = estimate(
                broker,
                {
                    "quantity": float(tx.quantity),
                    "price": float(tx.price),
                    "action": tx.action,
                    "exchange": asset.exchange,
                },
                str(tx.trade_date),
            )
            if fee["status"] != "estimated":
                tx.notes += f" · Charges unavailable: {fee['message']}"
                result["errors"].append(
                    f"Fill {fill.order_id}: charges unavailable; enter contract-note charges manually."
                )
                continue
            c = fee["breakdown"]
            mapped = {
                "brokerage": c["brokerage"],
                "stt": c["stt"],
                "gst": c["gst"],
                "stamp_duty": c["stamp"],
                "sebi": c["sebi"],
                "exchange_charges": round(c["exchange"] + c["ipft"] + c["clearing"], 2),
            }
            for key, value in mapped.items():
                setattr(tx, key, Decimal(str(value)))
            tx.notes += (
                f" · Estimated charges: assumed current broker {broker}, {fee['version']}; "
                "excludes DP/account charges"
            )
            session.flush()
            s.rebuild(session, asset)
    return result
