import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, DateTime, Boolean, Text, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Notice(Base):
    __tablename__ = "notices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AIModel(Base):
    """V4 起系统仅有 gpt-image-2 一个收费模型，本表只保存这一行配置。

    历史列（group / model_type / price_input 等）在旧库中保留但不再被 ORM 引用；
    新库由 create_all 直接按本定义建表。
    """

    __tablename__ = "ai_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="OpenAI")
    billing_type: Mapped[str] = mapped_column(String(16), nullable=False, default="per_call")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    trial_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    price_per_call: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")

    __table_args__ = (UniqueConstraint("name", name="uq_model_name"),)


# 历史表 prompts / groups（Prompt 资产库、服务分组）已废弃：
# 代码不再引用；旧库中的表与数据保留作历史归档，不做物理 DROP。
