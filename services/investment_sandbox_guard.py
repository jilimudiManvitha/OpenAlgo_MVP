"""Keep a destructive Sandbox reset from erasing long-lived portfolio exposure."""


def has_protected_portfolio(user):
    from database.sandbox_db import SandboxGTT, SandboxHoldings, SandboxOrders, SandboxPositions

    # Uses the caller's Sandbox transaction/session. No new DB or money engine.
    tagged = SandboxGTT.query.filter(
        SandboxGTT.user_id == user,
        SandboxGTT.strategy.startswith("InvestmentGTT_", autoescape=True),
    )
    if tagged.filter(SandboxGTT.gtt_status == "active").first():
        return True
    known = (
        tagged.first()
        or SandboxOrders.query.filter(
            SandboxOrders.user_id == user,
            SandboxOrders.strategy.startswith("InvestmentGTT_", autoescape=True),
        ).first()
    )
    if not known:
        return False
    return bool(
        SandboxOrders.query.filter(
            SandboxOrders.user_id == user,
            SandboxOrders.product == "CNC",
            SandboxOrders.order_status.in_(("open", "trigger pending")),
        ).first()
        or SandboxPositions.query.filter(
            SandboxPositions.user_id == user,
            SandboxPositions.product == "CNC",
            SandboxPositions.quantity != 0,
        ).first()
        or SandboxHoldings.query.filter(
            SandboxHoldings.user_id == user, SandboxHoldings.quantity != 0
        ).first()
    )
