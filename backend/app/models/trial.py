import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, DateTime, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class TrialClaim(Base):
    """新用户试用永久领取记录（Claim Ledger）。

    唯一性锚点 = normalized_email（trim + lowercase），而非 user_id：
    删除账号 / 同邮箱重新注册都不能再次领取。用户注销时本表不删除。
    并发双击申请由 uq_trial_claim_email 数据库唯一约束兜底（至多一次成功）。
    """

    __tablename__ = "trial_claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    normalized_email: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id_at_claim: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    grant_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # granted = 正常领取；revoked = 管理员吊销（吊销不返还再次领取资格）
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="granted")
    campaign_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        UniqueConstraint("normalized_email", name="uq_trial_claim_email"),
    )
