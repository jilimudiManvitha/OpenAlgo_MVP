"""Copier-owned durable state; never shares the broker authentication tables."""

from sqlalchemy import Boolean, Column, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Account(Base):
    __tablename__ = "copier_accounts"
    id = Column(String, primary_key=True)
    owner = Column(String, nullable=False, index=True)
    mode = Column(String, nullable=False)
    name = Column(String, nullable=False)
    broker = Column(String, nullable=False)
    client_id = Column(String, nullable=False)
    secret = Column(Text, nullable=False, default="")
    enabled = Column(Boolean, default=True, nullable=False)
    health = Column(String, default="AUTH_REQUIRED", nullable=False)
    verified_identity = Column(String, default="", nullable=False)
    verified_until = Column(Float, default=0, nullable=False)
    config = Column(Text, nullable=False)
    __table_args__ = (UniqueConstraint("owner", "mode", "broker", "client_id"),)


class Control(Base):
    __tablename__ = "copier_control"
    key = Column(String, primary_key=True)
    owner = Column(String, nullable=False)
    mode = Column(String, nullable=False)
    broker = Column(String, nullable=False)
    armed = Column(Boolean, default=False, nullable=False)
    killed = Column(Boolean, default=False, nullable=False)
    day = Column(String, default="", nullable=False)
    note = Column(String, default="Disarmed", nullable=False)
    heartbeat = Column(Float, default=0, nullable=False)
    generation = Column(Integer, default=0, nullable=False)
    identity = Column(Text, default="[]", nullable=False)


class MasterState(Base):
    __tablename__ = "copier_master_state"
    key = Column(String, primary_key=True)
    scope = Column(String, nullable=False, index=True)
    orderid = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    baseline = Column(Boolean, default=False, nullable=False)
    revision = Column(Integer, default=0, nullable=False)


class EventRecord(Base):
    __tablename__ = "copier_events"
    id = Column(String, primary_key=True)
    scope = Column(String, nullable=False, index=True)
    orderid = Column(String, nullable=False)
    received = Column(Float, nullable=False)
    payload = Column(Text, nullable=False)


class Cursor(Base):
    __tablename__ = "copier_cursors"
    key = Column(String, primary_key=True)
    target = Column(Integer, default=0, nullable=False)


class Attempt(Base):
    __tablename__ = "copier_attempts"
    id = Column(String, primary_key=True)
    owner = Column(String, nullable=False, index=True)
    mode = Column(String, nullable=False)
    account_id = Column(String, nullable=False, index=True)
    event_id = Column(String, nullable=False)
    generation = Column(Integer, nullable=False)
    master_orderid = Column(String, nullable=False)
    master_key = Column(String, nullable=False, index=True)
    day = Column(String, nullable=False)
    action = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    status = Column(String, nullable=False)
    broker_orderid = Column(String, default="", nullable=False)
    message = Column(String, default="", nullable=False)
    created = Column(Float, nullable=False)
    submitted = Column(Float, nullable=True)
    completed = Column(Float, nullable=True)
    dispatch_ms = Column(Float, nullable=True)
    response_ms = Column(Float, nullable=True)
    notional = Column(Float, default=0, nullable=False)
    filled = Column(Integer, default=0, nullable=False)
    average_price = Column(Float, default=0, nullable=False)


class Audit(Base):
    __tablename__ = "copier_audit"
    id = Column(Integer, primary_key=True)
    owner = Column(String, nullable=False, index=True)
    mode = Column(String, nullable=False)
    action = Column(String, nullable=False)
    detail = Column(String, nullable=False)
    created = Column(Float, nullable=False)


class BridgeReceipt(Base):
    __tablename__ = "copier_bridge_receipts"
    key = Column(String, primary_key=True)
    owner = Column(String, nullable=False)
    mode = Column(String, nullable=False)
    fingerprint = Column(String, nullable=False)
    result = Column(Text, nullable=False)
    created = Column(Float, nullable=False)
