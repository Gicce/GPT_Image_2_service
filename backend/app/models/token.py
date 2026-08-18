import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, DateTime, Boolean, Numeric, Integer, ForeignKey, Text, UniqueConstraint, Index, text
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
    REFUND_REQUESTED = "refund_requested"
    REFUNDING = "refunding"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"
    REFUND_CHANGE = "refund_change"

    ALL = {
        PENDING, PAID, ASSIGNED, CLOSED,
        REFUND_REQUESTED, REFUNDING, PARTIALLY_REFUNDED, REFUNDED, REFUND_CHANGE,
    }

    TRANSITIONS = {
        PENDING:       {PAID, CLOSED},
        PAID:          {ASSIGNED, REFUND_REQUESTED, REFUNDING},
        ASSIGNED:      {REFUND_REQUESTED, REFUNDING},
        # 拒绝 → 回到原状态；批准 → refunding（微信处理中）
        REFUND_REQUESTED: {REFUNDING, PAID, ASSIGNED, PARTIALLY_REFUNDED},
        # 微信退款失败/异常 → 回退可重试；成功 → refunded / partially_refunded
        REFUNDING:     {REFUNDED, PARTIALLY_REFUNDED, PAID, ASSIGNED},
        PARTIALLY_REFUNDED: {REFUND_REQUESTED, REFUNDING, REFUNDED},
        CLOSED:        set(),
        REFUNDED:      set(),
        REFUND_CHANGE: {REFUNDED},
    }

    @classmethod
    def can_transition(cls, current: str, target: str) -> bool:
        return target in cls.TRANSITIONS.get(current, set())


class TokenInventory(Base):
    """统一 Runtime Token 池（共享模式：1 Token → N Users）。

    - is_trial：Token 类型判别（False=正式 / True=试用）
    - is_default：该类型的默认 Token（每类型至多一个，由部分唯一索引保证）
    - quota_usd：NULL = 无限额度；非 NULL = 该 Token 当前关联用户累计消费上限（USD）
    - expires_at：NULL = 永久有效
    - 旧列 is_assigned/assigned_to/assigned_at 为 1:1 时代遗留，迁移后不再作为业务真相
      （真相在 runtime_token_assignments），保留仅供回滚参考。
    """

    __tablename__ = "token_inventory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_value: Mapped[str] = mapped_column(String(512), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    quota_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # 旧 1:1 列（遗留，迁移到 runtime_token_assignments 后仅作参考）
    is_assigned: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    is_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    assigned_to: Mapped[str] = mapped_column(String(36), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("token_value", name="uq_token_value"),
        # 每类型（is_trial）至多一个默认 Token
        Index(
            "uq_token_default_per_type",
            "is_trial",
            unique=True,
            postgresql_where=text("is_default = true"),
        ),
    )


class RuntimeTokenAssignment(Base):
    """Token ↔ 用户 多对多绑定（共享池核心表）。

    - 一个 Token 可绑定多个用户；一个用户同一时刻至多一个 active 绑定（部分唯一索引保证）
    - 重新绑定时复用同 (token_id, user_id) 行（历史审计走 token_assignment_logs）
    """

    __tablename__ = "runtime_token_assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("token_inventory.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    # active = 当前生效；released = 已解绑
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # register_trial / auto_paid / admin_assign / admin_release / refund_downgrade
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="admin_assign")
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("token_id", "user_id", name="uq_assignment_token_user"),
        Index(
            "uq_assignment_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )


class TokenAssignmentLog(Base):
    """Token 分配历史（审计）：每次 assign/release/replace 写一行，保留完整链路。"""

    __tablename__ = "token_assignment_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    # assign = 分配给 user；release = 从 user 解绑；replace 的旧/新各写一行
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    # register_trial / auto_paid / user_replace / admin_assign / admin_release / refund_downgrade
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Order(Base):
    """充值订单（微信支付）。历史列 group/items_json 保留旧数据，新订单不再写入。

    金额快照（退款只能引用这些快照，禁止实时汇率重算）：
    - amount_usd：到账 USD（充值额度）
    - amount_cny：微信实付人民币（元）
    - exchange_rate：下单时汇率快照
    - refunded_cny / refunded_usd：累计已退款（元 / USD 冲正），部分退款多次累计
    """

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    out_trade_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    trade_no: Mapped[str] = mapped_column(String(64), nullable=True)
    group: Mapped[str] = mapped_column(String(128), nullable=True)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    amount_cny: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    refunded_cny: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"), server_default=text("0"))
    refunded_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"), server_default=text("0"))
    items_json: Mapped[str] = mapped_column(Text, nullable=True)
    pay_type: Mapped[str] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    out_refund_no: Mapped[str] = mapped_column(String(64), nullable=True)
    token_id: Mapped[str] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    refund_requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    status_before_refund: Mapped[str] = mapped_column(String(24), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="orders")


class RefundRequestStatus:
    REQUESTED = "requested"      # 用户已提交，待管理员审核
    APPROVED = "approved"        # 管理员已批准，尚未调用微信
    PROCESSING = "processing"    # 微信退款处理中
    SUCCESS = "success"          # 微信确认退款成功（资金已冲正）
    REJECTED = "rejected"        # 管理员拒绝
    FAILED = "failed"            # 微信退款失败/异常

    ALL = {REQUESTED, APPROVED, PROCESSING, SUCCESS, REJECTED, FAILED}
    OPEN = (REQUESTED, APPROVED, PROCESSING)


class RefundRequest(Base):
    """退款申请（用户申请 / 管理员主动退款的统一载体）。

    - 一张订单同时至多一个未终态申请（部分唯一索引 uq_refund_open_per_order）
    - out_refund_no 全局唯一；同一业务退款重试复用同一单号（微信幂等）
    - 金额以人民币分（requested_amount_fen）为精确基准；USD 冲正按订单快照比例换算
    """

    __tablename__ = "refund_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id: Mapped[str] = mapped_column(String(36), ForeignKey("orders.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    # user = 用户申请；admin = 管理员主动退款
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="user")
    requested_amount_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_amount_cny: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    requested_amount_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=RefundRequestStatus.REQUESTED)
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    out_refund_no: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    wechat_refund_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index(
            "uq_refund_open_per_order",
            "order_id",
            unique=True,
            postgresql_where=text("status IN ('requested', 'approved', 'processing')"),
        ),
    )


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
