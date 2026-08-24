import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, DateTime, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class ClientDevice(Base):
    """客户端设备历史（永久保留，离线不删除）。

    online 状态为派生值：Redis 心跳 key（TTL 180s）存在即在线，不落库。
    last_seen_at 一律服务器时间（heartbeat 处理时刻），绝不信任客户端时间戳。
    """

    __tablename__ = "client_devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    device_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    platform: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    client_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    heartbeat_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "device_id", name="uq_device_user_device"),
        Index("ix_device_last_seen", "last_seen_at"),
    )
