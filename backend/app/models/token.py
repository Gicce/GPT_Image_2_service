import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, DateTime, Boolean, Numeric, Integer, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class OrderStatus:
    PENDING = "pending"
    PAID = "paid"
    # V4 起 ASSIGNED 语义 = 充值已入账（余额已增加）；沿用历史状态值以保持订单链路兼容
    ASSIGNED = "assigned"
    CLOSED = "closed"
    REFUNDING = "refunding"
    REFUNDED = "refunded"
    REFUND_CHANGE = "refund_change"

    ALL = {PENDING, PAID, ASSIGNED, CLOSED, REFUNDING, REFUNDED, REFUND_CHANGE}

    TRANSITIONS = {
        PENDING:       {PAID, CLOSED},
        PAID:          {ASSIGNED, REFUNDING},
        ASSIGNED:      {REFUNDING},
        REFUNDING:     {REFUNDED, PAID, ASSIGNED},
        CLOSED:        set(),
        REFUNDED:      set(),
        REFUND_CHANGE: {REFUNDED},
    }

    @classmethod
    def can_transition(cls, current: str, target: str) -> bool:
        return target in cls.TRANSITIONS.get(current, set())


class TokenInventory(Base):
    """统一 Runtime Token 池。

    V4 起不再按 image/chatgpt 分组：is_trial 仅用于标记“试用名额卡”（注册试用消耗），
    其余为普通库存 Token。历史 group 列保留在旧库中但不再被 ORM 引用。
    """

    __tablename__ = "token_inventory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_value: Mapped[str] = mapped_column(String(512), nullable=False)
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False)
    is_assigned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    assigned_to: Mapped[str] = mapped_column(String(36), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("token_value", name="uq_token_value"),)


class TokenAssignmentLog(Base):
    """Token 分配历史（审计）：每次 assign/release/replace 写一行，保留完整链路。"""

    __tablename__ = "token_assignment_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    # assign = 分配给 user；release = 从 user 解绑；replace 的旧/新各写一行
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    # register_trial / user_replace / admin_assign / admin_release
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Order(Base):
    """充值订单（微信支付）。历史列 group/items_json 保留旧数据，新订单不再写入。"""

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    out_trade_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    trade_no: Mapped[str] = mapped_column(String(64), nullable=True)
    group: Mapped[str] = mapped_column(String(128), nullable=True)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    amount_cny: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    items_json: Mapped[str] = mapped_column(Text, nullable=True)
    pay_type: Mapped[str] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    out_refund_no: Mapped[str] = mapped_column(String(64), nullable=True)
    token_id: Mapped[str] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    refund_requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    status_before_refund: Mapped[str] = mapped_column(String(16), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="orders")


class UsageLog(Base):
    """Image2 使用记录（settle 成功时写入，含价格快照与 request_id 幂等键）。"""

    __tablename__ = "usage_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    usage_type: Mapped[str] = mapped_column(String(16), nullable=False)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 结算时点的单价快照（per_call 模型）
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="usage_logs")
