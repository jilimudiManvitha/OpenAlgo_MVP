"""Additive personal investment ledger. No broker orders or sandbox balance writes."""

from datetime import UTC, datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from database.engine_factory import create_db_engine
from utils.logging import get_logger

engine = create_db_engine()
db_session = scoped_session(sessionmaker(bind=engine, autoflush=False))
Base = declarative_base()
MONEY = Numeric(18, 4)
QUANTITY = Numeric(20, 6)


def now():
    return datetime.now(UTC).replace(tzinfo=None)


class InvestmentAccount(Base):
    __tablename__ = "investment_accounts"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(String(80), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    broker_label = Column(String(80), nullable=False, default="Manual")
    kind = Column(String(10), nullable=False, default="paper")
    created_at = Column(DateTime, nullable=False, default=now)
    updated_at = Column(DateTime, nullable=False, default=now, onupdate=now)


class InvestmentAsset(Base):
    __tablename__ = "investment_assets"
    __table_args__ = (UniqueConstraint("account_id", "symbol", "exchange"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(String(80), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("investment_accounts.id"), nullable=False)
    asset_class = Column(String(24), nullable=False, default="STOCK")
    name = Column(String(120), nullable=False)
    symbol = Column(String(80), nullable=False)
    exchange = Column(String(12), nullable=False)
    scheme_code = Column(String(32))
    price_source = Column(String(12), nullable=False, default="live")
    manual_price = Column(MONEY)
    price_as_of = Column(DateTime)
    notes = Column(Text, nullable=False, default="")
    is_watch_only = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=now)
    updated_at = Column(DateTime, nullable=False, default=now, onupdate=now)


class InvestmentTransaction(Base):
    __tablename__ = "investment_transactions"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(80), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("investment_assets.id"), nullable=False, index=True)
    action = Column(String(24), nullable=False)
    quantity = Column(QUANTITY, nullable=False)
    price = Column(MONEY, nullable=False)
    brokerage = Column(MONEY, nullable=False, default=0)
    stt = Column(MONEY, nullable=False, default=0)
    gst = Column(MONEY, nullable=False, default=0)
    stamp_duty = Column(MONEY, nullable=False, default=0)
    sebi = Column(MONEY, nullable=False, default=0)
    exchange_charges = Column(MONEY, nullable=False, default=0)
    corporate_ratio = Column(QUANTITY)
    trade_date = Column(Date, nullable=False)
    trade_time = Column(Time, nullable=False)
    notes = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=now)


class InvestmentLot(Base):
    """FIFO lots rebuilt atomically from the ledger; WA is computed separately."""

    __tablename__ = "investment_lots"
    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("investment_assets.id"), nullable=False, index=True)
    transaction_id = Column(Integer, ForeignKey("investment_transactions.id"), nullable=False)
    opened_at = Column(DateTime, nullable=False)
    quantity_remaining = Column(QUANTITY, nullable=False)
    cost_per_unit = Column(MONEY, nullable=False)
    quantity_closed = Column(QUANTITY, nullable=False)
    realized_gain = Column(MONEY, nullable=False)
    status = Column(String(10), nullable=False)


class InvestmentValuation(Base):
    __tablename__ = "investment_valuations"
    __table_args__ = (UniqueConstraint("asset_id", "as_of", "source"),)
    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("investment_assets.id"), nullable=False, index=True)
    price = Column(MONEY, nullable=False)
    previous_close = Column(MONEY)
    as_of = Column(DateTime, nullable=False)
    source = Column(String(24), nullable=False)
    created_at = Column(DateTime, nullable=False, default=now)


class InvestmentAssetDetails(Base):
    """Additive extension, avoiding alterations to the deployed asset table."""

    __tablename__ = "investment_asset_details"
    asset_id = Column(Integer, ForeignKey("investment_assets.id"), primary_key=True)
    details = Column(Text, nullable=False, default="{}")


class InvestmentWatchlist(Base):
    __tablename__ = "investment_watchlists"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(String(80), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    category = Column(String(24), nullable=False)


class InvestmentWatchItem(Base):
    __tablename__ = "investment_watch_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "asset_id"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(String(80), nullable=False, index=True)
    watchlist_id = Column(Integer, ForeignKey("investment_watchlists.id"), nullable=False)
    asset_id = Column(Integer, ForeignKey("investment_assets.id"), nullable=False)
    stop_price = Column(MONEY)
    target_price = Column(MONEY)


class InvestmentPaperOrder(Base):
    __tablename__ = "investment_paper_orders"
    __table_args__ = (UniqueConstraint("user_id", "request_key"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(String(80), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("investment_assets.id"), nullable=False)
    watchlist_id = Column(Integer, ForeignKey("investment_watchlists.id"), nullable=False)
    request_key = Column(String(64), nullable=False)
    payload = Column(Text, nullable=False)
    status = Column(String(24), nullable=False, default="prepared")
    gtt_id = Column(String(50))
    message = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=now)


class InvestmentPaperFill(Base):
    __tablename__ = "investment_paper_fills"
    __table_args__ = (UniqueConstraint("user_id", "order_id"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(String(80), nullable=False)
    order_id = Column(String(50), nullable=False)
    transaction_id = Column(Integer, ForeignKey("investment_transactions.id"), nullable=False)


def init_db():
    from database.db_init_helper import init_db_with_logging

    return init_db_with_logging(Base, engine, "Investment DB", get_logger(__name__))
