import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, DateTime, Numeric, Integer, ForeignKey, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class BillingTransaction(Base):
    """统一账务流水（单一真相源）。

    type:
      - IMAGE2_CHARGE      Image2 按次扣费（两阶段：RESERVED 预占 → SUCCESS/FAILED 结算）
      - IMAGE2_REFUND      Image2 计费退款（预占释放/结算回退）
      - RECHARGE           充值入账（微信支付成功）
      - RECHARGE_REFUND    充值订单退款冲正
      - ADMIN_ADJUSTMENT   管理员手工调账
      - MIGRATION          V4 余额迁移入账

    status: RESERVED / SUCCESS / FAILED / RELEASED / REFUNDED

    幂等保证：
      - IMAGE2_CHARGE 以 request_id 唯一约束保证一次请求只扣一次
      - 状态流转在行锁内做 CAS，退款/结算只生效一次
    """

    __tablename__ = "billing_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    unit_price_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    trial_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    balance_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    billing_source: Mapped[str] = mapped_column(String(8), nullable=False, default="NONE")
    balance_before: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    balance_after: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    trial_before: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    trial_after: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    related_order_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    related_usage_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("request_id", name="uq_billing_request_id"),
        Index("ix_billing_user_created", "user_id", "created_at"),
        Index("ix_billing_status_created", "status", "created_at"),
    )

    user: Mapped["User"] = relationship("User", back_populates="billing_transactions")
