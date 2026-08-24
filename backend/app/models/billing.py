import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, DateTime, Boolean, Numeric, Integer, ForeignKey, Text, UniqueConstraint, Index, text
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
    # CY Credits 快照（V4.2 起）：unit/amount 与三类点数拆分；quote 定价冻结链路
    unit_credits: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    amount_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    trial_credits_part: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    gift_credits_part: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    paid_credits_part: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    quote_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    pricing_rule_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    pricing_rule_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("request_id", name="uq_billing_request_id"),
        Index("ix_billing_user_created", "user_id", "created_at"),
        Index("ix_billing_status_created", "status", "created_at"),
    )

    user: Mapped["User"] = relationship("User", back_populates="billing_transactions")


class PricingRule(Base):
    """定价规则（CY Credits 唯一售价来源，Price Guard 目标毛利校验）。

    - 每 (feature, model) 至多一条 enabled 规则（部分唯一索引）；编辑为原地升版本，
      历史任务经 billing_transactions 的 rule_id/version/unit_credits 快照锁定原价
    - nominal_unit_cost_rmb：单张采购成本（人民币）。上游 $1 额度 ≈ ¥1 实充的业务事实
      决定了采购成本以 RMB 记账，禁止按实时美元汇率换算 nominal USD
    - 最低售价 = nominal × (1+safety_buffer) / (1-target_margin) × credits_per_cny，按 rounding_step 向上取整
    """

    __tablename__ = "pricing_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    feature: Mapped[str] = mapped_column(String(32), nullable=False, default="image")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="gpt-image-2")
    # 可选细分维度（V1 定价为扁平单价，维度留作扩展；NULL = 匹配任意）
    mode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    quality: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    size: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    unit_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    # 成本侧配置（参与毛利计算与 Price Guard）
    provider_route: Mapped[str] = mapped_column(String(64), nullable=False, default="packyapi")
    nominal_unit_cost_rmb: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=Decimal("0.20"))
    target_margin: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.70"))
    safety_buffer: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.10"))
    rounding_step: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # 低于目标毛利强制保存（仅 super_admin）时的审计记录
    override_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    override_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    override_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index(
            "uq_pricing_rule_active",
            "feature", "model",
            unique=True,
            postgresql_where=text("enabled = true"),
        ),
    )


class CostMarginLedger(Base):
    """经营账（成本与毛利）：任务结算成功时冻结快照，供后台查账与对账。

    - 收入口径：revenue_rmb 只计 paid_credits 部分；试用/赠送点数消耗记
      promotional_value_rmb（获客/营销成本口径），避免污染付费毛利报表
    - gross_profit_rmb = revenue_rmb - actual_cost_rmb；trial/gift 类行为负值（获客成本）
    - gross_margin 仅在 revenue_rmb > 0 时有意义（NULL = 无付费收入）
    """

    __tablename__ = "cost_margin_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_transaction_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    pricing_rule_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    pricing_rule_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unit_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    charged_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    released_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # paid / trial / gift / mixed（按 billing_source）
    category: Mapped[str] = mapped_column(String(8), nullable=False, default="paid")
    credit_value_rmb: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    revenue_rmb: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"))
    promotional_value_rmb: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"))
    # 供应商快照（结算时点的路由与成本；V1 客户端直连上游，Token 归因按用户绑定快照）
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="packyapi")
    provider_route: Mapped[str] = mapped_column(String(64), nullable=False, default="packyapi")
    token_inventory_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    nominal_unit_cost_rmb: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=Decimal("0"))
    safety_buffer: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    effective_unit_cost_rmb: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"))
    actual_cost_rmb: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"))
    effective_cost_rmb: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"))
    gross_profit_rmb: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"))
    gross_margin: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    successful_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_margin_ledger_user_created", "user_id", "created_at"),
        Index("ix_margin_ledger_settled", "settled_at"),
    )
