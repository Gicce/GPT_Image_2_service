import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class SkillPackage(Base):
    """Versioned official Skill package.

    Published rows are immutable. A new version must be created for every
    content change so clients can safely freeze a project against one version.
    """

    __tablename__ = "skill_packages"
    __table_args__ = (
        UniqueConstraint("skill_id", "version", name="uq_skill_package_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    skill_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    published_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="official")
    author_display_name: Mapped[str | None] = mapped_column(String(96), nullable=True)
    preview_sample_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_submission_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class SkillSubmission(Base):
    """Immutable community Skill snapshot submitted by a client user."""

    __tablename__ = "skill_submissions"
    __table_args__ = (
        UniqueConstraint("user_id", "local_skill_id", "revision", name="uq_skill_submission_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    local_skill_id: Mapped[str] = mapped_column(String(96), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # V4.2.3：与客户端 SkillSourceFact[] 一致的结构化事实数组（key/label/value）；
    # 旧数据可能是 dict（历史测试写入），序列化侧原样透出。
    source_facts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    authoring_meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    author_display_name: Mapped[str] = mapped_column(String(96), nullable=False, default="社区创作者")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="submitted", index=True)
    review_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_skill_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SkillSubmissionSample(Base):
    __tablename__ = "skill_submission_samples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("skill_submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation_meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    public_cover: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SkillSubmissionEvent(Base):
    __tablename__ = "skill_submission_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("skill_submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor: Mapped[str] = mapped_column(String(96), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
