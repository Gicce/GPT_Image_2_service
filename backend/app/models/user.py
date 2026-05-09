import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Boolean, Numeric, Integer, ForeignKey, Text, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    account_type: Mapped[str] = mapped_column(String(16), default="trial")  # trial / paid
    balance_usd: Mapped[float] = mapped_column(Numeric(10, 6), default=0.0)
    api_token_id: Mapped[str] = mapped_column(String(36), ForeignKey("token_inventory.id"), nullable=True)
    trial_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    token: Mapped["TokenInventory"] = relationship("TokenInventory", foreign_keys=[api_token_id])
    orders: Mapped[list["Order"]] = relationship("Order", back_populates="user")
    usage_logs: Mapped[list["UsageLog"]] = relationship("UsageLog", back_populates="user")
