import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class OrderStatus:
    PENDING = "pending"
    PAID = "paid"
    ALLOCATED = "allocated"
    ASSIGNED = "assigned"
    CLOSED = "closed"
    REFUNDING = "refunding"
    REFUNDED = "refunded"
    REFUND_CHANGE = "refund_change"


class TokenInventory(Base):
    __tablename__ = "token_inventory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_value: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    package_usd: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    group: Mapped[str] = mapped_column(String(32), nullable=False, default="image")
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False)
    is_assigned: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_to: Mapped[str] = mapped_column(String(36), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    out_trade_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    trade_no: Mapped[str] = mapped_column(String(64), nullable=True)
    package_usd: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    group: Mapped[str] = mapped_column(String(128), nullable=True)
    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=True)
    amount_cny: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    exchange_rate: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    items_json: Mapped[str] = mapped_column(Text, nullable=True)
    pay_type: Mapped[str] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=OrderStatus.PENDING)
    out_refund_no: Mapped[str] = mapped_column(String(64), nullable=True)
    token_id: Mapped[str] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    allocated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    refund_requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    status_before_refund: Mapped[str] = mapped_column(String(16), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="orders")


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    usage_type: Mapped[str] = mapped_column(String(16), nullable=False)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="usage_logs")
