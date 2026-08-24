import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class SystemConfig(Base):
    """运行时业务配置（K-V，管理后台可改，全程留痕）。

    已知键（读取方见 services/config_service.py，缺省值以代码默认为准）：
      credits_per_cny          人民币→点数兑换率（默认 100，即 ¥1 = 100 CY 点）
      legacy_usd_to_credits    旧美元余额→点数迁移兑换率（默认 700）+ 兼容镜像回写率
      trial_feature_enabled    试用通道总开关
      trial_grant_credits      试用赠送点数（默认 500）
      trial_campaign_version   试用活动版本号
      target_margin            目标毛利率（默认 0.70）
      cost_safety_buffer       成本安全垫（默认 0.10）
      recharge_min_cny         充值下限（默认 1）
      recharge_max_cny         充值上限（默认 5000）
    """

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
