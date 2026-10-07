"""Durable order intents; additive tables registered with Investment Base."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from database.investment_db import Base, now


class InvestmentExecution(Base):
    __tablename__ = "investment_executions"
    __table_args__ = (UniqueConstraint("user_id", "request_key"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(String(80), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("investment_assets.id"), nullable=False)
    broker = Column(String(40), nullable=False)
    mode = Column(String(10), nullable=False)
    request_key = Column(String(64), nullable=False)
    kind = Column(String(10), nullable=False)
    payload = Column(Text, nullable=False)
    status = Column(String(24), nullable=False)
    external_id = Column(String(100))
    message = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=now)
