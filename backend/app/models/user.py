import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
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
    # 后台归档：保留订单/账务/用量等经营记录，同时立即禁止登录。
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # v1.0.0 账户治理：
    # - password_changed_at：密码最近修改时间（存量行为 NULL，管理后台显示"未记录"）
    # - token_version：会话撤销版本号。签发 JWT 时写入 tv，鉴权时与库值比对，
    #   不一致即 401——管理员重置密码 / 用户自助改密 / 归档 / 恢复 / 彻底删除
    #   都递增该值使全部存量 Bearer token 立即失效。默认 0 与旧 token（无 tv）兼容。
    # - purged_at/purged_by/purge_reason：彻底删除（硬删除）标记。有业务历史的账户
    #   删除时保留本行作为脱敏账务主体（FK 指向不破坏、订单/流水可追溯），
    #   username/email 改写为不可注册占位、密码哈希重写、不可恢复、不可登录。
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    purged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    purged_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    purge_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    orders: Mapped[list["Order"]] = relationship("Order", back_populates="user")
    usage_logs: Mapped[list["UsageLog"]] = relationship("UsageLog", back_populates="user")
    billing_transactions: Mapped[list["BillingTransaction"]] = relationship(
        "BillingTransaction", back_populates="user"
    )


# 历史分组余额表 user_tokens 已废弃：V4 起余额统一存放在 users.balance_usd / trial_credit_usd，
# 存量数据由启动迁移一次性搬移，代码不再引用该表。
