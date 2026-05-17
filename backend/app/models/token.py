import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Boolean, Numeric, Integer, ForeignKey, Text, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class TokenInventory(Base):
    __tablename__ = "token_inventory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_value: Mapped[str] = mapped_column(String(512), nullable=False)
    group: Mapped[str] = mapped_column(String(32), nullable=False)
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False)
    is_assigned: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_to: Mapped[str] = mapped_column(String(36), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint('token_value', 'group', name='uq_token_value_group'),)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    out_trade_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    trade_no: Mapped[str] = mapped_column(String(64), nullable=True)
    group: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    amount_cny: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    exchange_rate: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    items_json: Mapped[str] = mapped_column(Text, nullable=True)
    pay_type: Mapped[str] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    token_id: Mapped[str] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

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
