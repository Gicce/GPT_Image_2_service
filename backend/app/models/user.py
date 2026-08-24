import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, DateTime, Boolean, Numeric, Integer, Text, text
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
    account_type: Mapped[str] = mapped_column(String(16), default="normal")
    trial_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 统一余额：现金余额（充值/退款入账）与试用额度（注册赠送），均为 Decimal 精确金额
    balance_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    trial_credit_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    # CY Credits（V4.2 起）：三类点数余额，1 点为原子单位，¥1 = credits_per_cny 点（system_config）
    # 消费顺序 trial → gift → paid（集中在 billing.consume_credits）。
    # balance_usd / trial_credit_usd 降级为兼容镜像：每次点数变动后按 legacy 兑换率回写，
    # 供 V4.0.9 及更旧客户端展示，不再作为业务真相。
    paid_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    trial_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    gift_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    orders: Mapped[list["Order"]] = relationship("Order", back_populates="user")
    usage_logs: Mapped[list["UsageLog"]] = relationship("UsageLog", back_populates="user")
    billing_transactions: Mapped[list["BillingTransaction"]] = relationship(
        "BillingTransaction", back_populates="user"
    )


# 历史分组余额表 user_tokens 已废弃：V4 起余额统一存放在 users.balance_usd / trial_credit_usd，
# 存量数据由启动迁移一次性搬移，代码不再引用该表。
