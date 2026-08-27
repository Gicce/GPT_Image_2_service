"""Authenticated community Skill submissions and user-owned samples."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.skill import SkillSubmission, SkillSubmissionEvent, SkillSubmissionSample
from app.models.user import User
from app.services.skill_catalog import ensure_valid_package


logger = logging.getLogger(__name__)

router = APIRouter()
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/(?:home|Users|var|etc|opt)/)", re.IGNORECASE)
SECRET_RE = re.compile(r"(?:api[_ -]?key|access[_ -]?token|secret[_ -]?key|bearer\s+[A-Za-z0-9._-]{12,})", re.IGNORECASE)
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


class SourceFactItem(BaseModel):
    """与客户端 SkillSourceFact 一致的结构化事实行（key/label/value）。"""

    key: str = Field(min_length=1, max_length=96)
    label: str = Field(min_length=1, max_length=96)
    value: str = Field(min_length=1, max_length=4000)
    immutable: bool = True


class SubmissionCreate(BaseModel):
    local_skill_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9_-]+$")
    revision: int = Field(ge=1)
    version: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    domain: str = Field(min_length=1, max_length=64)
    summary: str = Field(default="", max_length=1000)
    payload: dict
    source_facts: list[SourceFactItem] = Field(default_factory=list)
    authoring_meta: dict
    author_display_name: str | None = Field(default=None, max_length=96)


class SubmissionRevision(SubmissionCreate):
    pass


def _fail(status: int, code: str, message: str, **extra) -> None:
    """所有接口错误统一结构化：code（机器可读）+ message（面向用户的中文文案）。"""
    detail: dict = {"code": code, "message": message}
    detail.update(extra)
    raise HTTPException(status_code=status, detail=detail)


def _scan_public_payload(value: Any, path: str = "payload") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            errors.extend(_scan_public_payload(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(_scan_public_payload(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        if LOCAL_PATH_RE.search(value):
            errors.append(f"{path} 含本地文件路径")
        if SECRET_RE.search(value):
            errors.append(f"{path} 可能含密钥或 Token")
        if IP_RE.search(value):
            errors.append(f"{path} 含服务器地址")
    return errors


def _validate_submission(req: SubmissionCreate) -> None:
    ensure_valid_package(req.domain, req.payload)
    errors = _scan_public_payload(req.payload)
    for index, fact in enumerate(req.source_facts):
        errors.extend(_scan_public_payload(fact.value, f"source_facts[{index}].value"))
    meta = req.authoring_meta or {}
    if not meta.get("model") or not meta.get("confirmed_at"):
        errors.append("公开投稿必须完成 AI 通用化并由用户确认")
    if meta.get("source_revision") != req.revision:
        errors.append("AI 通用化结果与当前项目修订不一致")
    if errors:
        _fail(400, "SKILL_SUBMISSION_UNSAFE", "投稿内容包含不安全信息，已拒绝提交。", errors=errors)


def _event(row: SkillSubmission, actor: str, actor_type: str, action: str, message: str = "") -> SkillSubmissionEvent:
    return SkillSubmissionEvent(
        submission_id=row.id, actor=actor[:96], actor_type=actor_type,
        action=action, message=message[:4000],
    )


async def _owned(db: AsyncSession, submission_id: str, user: User) -> SkillSubmission:
    row = (await db.execute(select(SkillSubmission).where(
        SkillSubmission.id == submission_id, SkillSubmission.user_id == user.id,
    ))).scalar_one_or_none()
    if not row:
        _fail(404, "SKILL_SUBMISSION_NOT_FOUND", "投稿不存在或已被撤回。")
    return row


async def _sample_count(db: AsyncSession, submission_id: str) -> int:
    value = await db.scalar(select(func.count()).select_from(SkillSubmissionSample).where(
        SkillSubmissionSample.submission_id == submission_id
    ))
    return int(value or 0)


async def serialize_submission(db: AsyncSession, row: SkillSubmission, include_payload: bool = False) -> dict:
    data = {
        "id": row.id, "local_skill_id": row.local_skill_id, "revision": row.revision,
        "version": row.version, "name": row.name, "domain": row.domain,
        "summary": row.summary, "status": row.status, "review_message": row.review_message,
        "author_display_name": row.author_display_name, "public_skill_id": row.public_skill_id,
        "sample_count": await _sample_count(db, row.id),
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
    }
    if include_payload:
        data.update(payload=row.payload, source_facts=row.source_facts, authoring_meta=row.authoring_meta)
    return data


def _same_content(existing: SkillSubmission, req: SubmissionCreate) -> bool:
    """内容一致性判定：零样例投稿恢复复用已有记录的前提。"""
    return (
        existing.name == req.name.strip()
        and existing.summary == req.summary.strip()
        and existing.version == req.version
        and existing.domain == req.domain
        and existing.payload == req.payload
    )


@router.post("/submissions")
async def create_submission(
    req: SubmissionCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    _validate_submission(req)
    existing = (await db.execute(select(SkillSubmission).where(
        SkillSubmission.user_id == user.id,
        SkillSubmission.local_skill_id == req.local_skill_id,
        SkillSubmission.revision == req.revision,
    ))).scalar_one_or_none()
    if existing:
        # 可恢复场景：上次投稿记录已创建但样例上传失败（零样例），且内容一致 → 返回已有投稿，
        # 客户端继续上传缺失样例，绝不产生重复投稿。
        resumable = (
            existing.status in {"submitted", "changes_requested"}
            and await _sample_count(db, existing.id) == 0
            and _same_content(existing, req)
        )
        if resumable:
            db.add(_event(existing, user.username, "user", "resumed", "零样例投稿恢复，继续上传样例"))
            existing.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(existing)
            return await serialize_submission(db, existing, True)
        _fail(
            409, "SKILL_SUBMISSION_DUPLICATE",
            "当前修订已经投稿。将载入已有投稿状态；如需修改内容请创建新修订。",
            submission_id=existing.id, sample_count=await _sample_count(db, existing.id),
        )
    row = SkillSubmission(
        user_id=user.id, local_skill_id=req.local_skill_id, revision=req.revision,
        version=req.version, name=req.name.strip(), domain=req.domain,
        summary=req.summary.strip(), payload=req.payload,
        source_facts=[fact.model_dump() for fact in req.source_facts],
        authoring_meta=req.authoring_meta,
        author_display_name=(req.author_display_name or user.username or "社区创作者").strip(),
    )
    db.add(row)
    await db.flush()
    db.add(_event(row, user.username, "user", "submitted"))
    await db.commit()
    await db.refresh(row)
    return await serialize_submission(db, row, True)


@router.post("/submissions/{submission_id}/samples")
async def upload_submission_sample(
    submission_id: str,
    image: UploadFile = File(...),
    task_id: str | None = Form(default=None),
    metadata_json: str = Form(default="{}"),
    public_cover: bool = Form(default=False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _owned(db, submission_id, user)
    if row.status not in {"submitted", "changes_requested"}:
        _fail(409, "SKILL_SAMPLE_STATUS_CONFLICT", "当前审核状态不允许补充样例。")
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        _fail(400, "SKILL_SAMPLE_TYPE_UNSUPPORTED", "样例仅支持 PNG、JPEG 或 WebP。")
    data = await image.read(settings.SKILL_SAMPLE_MAX_BYTES + 1)
    if not data:
        _fail(400, "SKILL_SAMPLE_EMPTY", "样例文件为空。")
    if len(data) > settings.SKILL_SAMPLE_MAX_BYTES:
        _fail(413, "SKILL_SAMPLE_TOO_LARGE", "样例图片过大，请压缩后重试。")
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        logger.warning("invalid sample metadata_json: %r", metadata_json[:200])
        _fail(400, "SKILL_SAMPLE_META_INVALID", "样例参数格式不正确。")
    if not isinstance(metadata, dict):
        _fail(400, "SKILL_SAMPLE_META_INVALID", "样例参数必须是对象。")
    suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[image.content_type]
    sample_id = str(uuid.uuid4())
    root = Path(settings.SKILL_SAMPLE_DIR).resolve()
    target_dir = root / row.id
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("cannot create skill sample dir %s", target_dir)
        _fail(500, "SKILL_SAMPLE_WRITE_FAILED", "样例目录不可用，请联系管理员。")
    target = (target_dir / f"{sample_id}{suffix}").resolve()
    if root not in target.parents:
        _fail(400, "SKILL_SAMPLE_PATH_INVALID", "样例保存路径无效。")
    # 原子写入：先写临时文件再 rename；DB 提交失败时清理最终文件，保证库与文件系统一致。
    tmp = target_dir / f".{sample_id}.uploading"
    try:
        with tmp.open("wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except OSError:
        logger.exception("cannot persist skill sample %s", target)
        tmp.unlink(missing_ok=True)
        _fail(500, "SKILL_SAMPLE_WRITE_FAILED", "样例保存失败，请稍后重试。")
    sample = SkillSubmissionSample(
        id=sample_id, submission_id=row.id, file_path=str(target),
        file_name=(image.filename or f"sample{suffix}")[:255], content_type=image.content_type,
        sha256=hashlib.sha256(data).hexdigest(), task_id=(task_id or "")[:64] or None,
        generation_meta=metadata, public_cover=public_cover,
    )
    db.add(sample)
    db.add(_event(row, user.username, "user", "sample_added", sample.id))
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        target.unlink(missing_ok=True)
        _fail(500, "SKILL_SAMPLE_DB_FAILED", "样例登记失败，请稍后重试。")
    return {"id": sample.id, "public_cover": sample.public_cover}


@router.get("/mine")
async def list_my_submissions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(SkillSubmission).where(
        SkillSubmission.user_id == user.id
    ).order_by(SkillSubmission.updated_at.desc()))).scalars().all()
    return {"total": len(rows), "submissions": [await serialize_submission(db, row) for row in rows]}


@router.get("/submissions/{submission_id}")
async def get_my_submission(
    submission_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await serialize_submission(db, await _owned(db, submission_id, user), True)


@router.post("/submissions/{submission_id}/withdraw")
async def withdraw_submission(
    submission_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    row = await _owned(db, submission_id, user)
    if row.status not in {"submitted", "changes_requested"}:
        _fail(409, "SKILL_SUBMISSION_STATUS_CONFLICT", "当前状态不能撤回。")
    row.status = "withdrawn"
    row.updated_at = datetime.now(timezone.utc)
    db.add(_event(row, user.username, "user", "withdrawn"))
    await db.commit()
    return await serialize_submission(db, row)


@router.post("/submissions/{submission_id}/revisions")
async def create_submission_revision(
    submission_id: str, req: SubmissionRevision,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    previous = await _owned(db, submission_id, user)
    if previous.status not in {"changes_requested", "rejected", "withdrawn"}:
        _fail(409, "SKILL_SUBMISSION_STATUS_CONFLICT", "只有需修改、已拒绝或已撤回投稿可以提交新修订。")
    if req.local_skill_id != previous.local_skill_id or req.revision <= previous.revision:
        _fail(400, "SKILL_SUBMISSION_REVISION_INVALID", "新修订必须沿用同一 Skill 且修订号递增。")
    return await create_submission(req, user, db)
