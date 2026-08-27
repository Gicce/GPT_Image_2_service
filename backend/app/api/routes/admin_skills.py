import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_admin_user, get_super_admin_user
from app.models.audit import AdminAuditLog
from app.models.skill import SkillPackage, SkillSubmission, SkillSubmissionEvent, SkillSubmissionSample
from app.services.skill_catalog import ensure_valid_package, serialize_package, validate_package_payload


router = APIRouter()


def _fail(status: int, code: str, message: str) -> None:
    """管理端接口错误统一结构化：code（机器可读）+ message（中文文案）。"""
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


class SkillPackageCreate(BaseModel):
    skill_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-z0-9_]+$")
    version: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    domain: str = Field(min_length=1, max_length=64)
    summary: str = Field(default="", max_length=1000)
    payload: dict


class SkillPackageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    domain: str | None = Field(default=None, min_length=1, max_length=64)
    summary: str | None = Field(default=None, max_length=1000)
    payload: dict | None = None


class SubmissionReviewRequest(BaseModel):
    message: str = Field(default="", max_length=4000)


async def _audit(db: AsyncSession, admin: dict, action: str, detail: dict) -> None:
    db.add(AdminAuditLog(
        admin=(admin or {}).get("username") or (admin or {}).get("sub", "admin"),
        action=action,
        detail=json.dumps(detail, ensure_ascii=False),
    ))


async def _get_package(db: AsyncSession, package_id: str) -> SkillPackage:
    row = (await db.execute(select(SkillPackage).where(SkillPackage.id == package_id))).scalar_one_or_none()
    if not row:
        _fail(404, "SKILL_PACKAGE_NOT_FOUND", "Skill 版本不存在。")
    return row


@router.get("/skill-packages")
async def list_skill_packages(
    status: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    _admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(SkillPackage)
    if status:
        if status not in {"draft", "published", "archived"}:
            _fail(400, "SKILL_PACKAGE_STATUS_INVALID", "status 不合法。")
        query = query.where(SkillPackage.status == status)
    if domain:
        query = query.where(SkillPackage.domain == domain)
    rows = (await db.execute(
        query.order_by(SkillPackage.skill_id.asc(), SkillPackage.created_at.desc())
    )).scalars().all()
    return {"total": len(rows), "packages": [serialize_package(row) for row in rows]}


@router.post("/skill-packages")
async def create_skill_package(
    req: SkillPackageCreate,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    ensure_valid_package(req.domain, req.payload)
    row = SkillPackage(
        skill_id=req.skill_id,
        version=req.version.strip(),
        name=req.name.strip(),
        domain=req.domain,
        summary=req.summary.strip(),
        payload=req.payload,
        status="draft",
        created_by=admin.get("username") or admin.get("sub", "admin"),
    )
    db.add(row)
    await _audit(db, admin, "skill_package_created", {"skill_id": row.skill_id, "version": row.version})
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _fail(409, "SKILL_PACKAGE_DUPLICATE", "该 Skill 版本已存在。")
    await db.refresh(row)
    return serialize_package(row)


@router.put("/skill-packages/{package_id}")
async def update_skill_package(
    package_id: str,
    req: SkillPackageUpdate,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_package(db, package_id)
    if row.status != "draft":
        _fail(409, "SKILL_PACKAGE_IMMUTABLE", "已发布版本不可修改，请创建新版本。")
    next_domain = req.domain or row.domain
    next_payload = req.payload if req.payload is not None else row.payload
    ensure_valid_package(next_domain, next_payload)
    if req.name is not None:
        row.name = req.name.strip()
    if req.domain is not None:
        row.domain = req.domain
    if req.summary is not None:
        row.summary = req.summary.strip()
    if req.payload is not None:
        row.payload = req.payload
    await _audit(db, admin, "skill_package_updated", {"skill_id": row.skill_id, "version": row.version})
    await db.commit()
    await db.refresh(row)
    return serialize_package(row)


@router.post("/skill-packages/{package_id}/validate")
async def validate_skill_package(
    package_id: str,
    _admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_package(db, package_id)
    errors = validate_package_payload(row.payload)
    return {"ok": not errors, "errors": errors}


async def _activate_package(db: AsyncSession, row: SkillPackage, admin: dict, action: str) -> SkillPackage:
    ensure_valid_package(row.domain, row.payload)
    current = (await db.execute(select(SkillPackage).where(
        SkillPackage.skill_id == row.skill_id,
        SkillPackage.status == "published",
        SkillPackage.id != row.id,
    ))).scalars().all()
    for item in current:
        item.status = "archived"
    row.status = "published"
    row.published_by = admin.get("username") or admin.get("sub", "admin")
    row.published_at = datetime.now(timezone.utc)
    await _audit(db, admin, action, {
        "skill_id": row.skill_id,
        "version": row.version,
        "replaced_versions": [item.version for item in current],
    })
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/skill-packages/{package_id}/publish")
async def publish_skill_package(
    package_id: str,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_package(db, package_id)
    if row.status != "draft":
        _fail(409, "SKILL_PACKAGE_NOT_DRAFT", "只有草稿版本可以发布。")
    return serialize_package(await _activate_package(db, row, admin, "skill_package_published"))


@router.post("/skill-packages/{package_id}/rollback")
async def rollback_skill_package(
    package_id: str,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_package(db, package_id)
    if row.status != "archived":
        _fail(409, "SKILL_PACKAGE_NOT_ARCHIVED", "只有已归档版本可以回滚。")
    return serialize_package(await _activate_package(db, row, admin, "skill_package_rolled_back"))


@router.post("/skill-packages/{package_id}/archive")
async def archive_skill_package(
    package_id: str,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_package(db, package_id)
    if row.status == "archived":
        return serialize_package(row)
    row.status = "archived"
    await _audit(db, admin, "skill_package_archived", {"skill_id": row.skill_id, "version": row.version})
    await db.commit()
    await db.refresh(row)
    return serialize_package(row)


async def _get_submission(db: AsyncSession, submission_id: str) -> SkillSubmission:
    row = (await db.execute(select(SkillSubmission).where(
        SkillSubmission.id == submission_id
    ))).scalar_one_or_none()
    if not row:
        _fail(404, "SKILL_SUBMISSION_NOT_FOUND", "用户投稿不存在。")
    return row


async def _serialize_submission(db: AsyncSession, row: SkillSubmission, detail: bool = False) -> dict:
    sample_count = int(await db.scalar(select(func.count()).select_from(SkillSubmissionSample).where(
        SkillSubmissionSample.submission_id == row.id
    )) or 0)
    data = {
        "id": row.id, "user_id": row.user_id, "local_skill_id": row.local_skill_id,
        "revision": row.revision, "version": row.version, "name": row.name,
        "domain": row.domain, "summary": row.summary, "status": row.status,
        "author_display_name": row.author_display_name, "review_message": row.review_message,
        "public_skill_id": row.public_skill_id, "sample_count": sample_count,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
    }
    if detail:
        samples = (await db.execute(select(SkillSubmissionSample).where(
            SkillSubmissionSample.submission_id == row.id
        ).order_by(SkillSubmissionSample.created_at.asc()))).scalars().all()
        events = (await db.execute(select(SkillSubmissionEvent).where(
            SkillSubmissionEvent.submission_id == row.id
        ).order_by(SkillSubmissionEvent.created_at.asc()))).scalars().all()
        data.update(
            payload=row.payload, source_facts=row.source_facts, authoring_meta=row.authoring_meta,
            samples=[{
                "id": item.id, "file_name": item.file_name, "content_type": item.content_type,
                "task_id": item.task_id, "generation_meta": item.generation_meta,
                "public_cover": item.public_cover, "sha256": item.sha256,
            } for item in samples],
            events=[{
                "action": item.action, "actor": item.actor, "actor_type": item.actor_type,
                "message": item.message, "created_at": item.created_at.isoformat(),
            } for item in events],
        )
    return data


def _review_event(row: SkillSubmission, admin: dict, action: str, message: str = "") -> SkillSubmissionEvent:
    return SkillSubmissionEvent(
        submission_id=row.id, actor=admin.get("username", "admin"), actor_type="admin",
        action=action, message=message,
    )


@router.get("/skill-submissions")
async def list_skill_submissions(
    status: str | None = Query(default=None), domain: str | None = Query(default=None),
    _admin: dict = Depends(get_admin_user), db: AsyncSession = Depends(get_db),
):
    query = select(SkillSubmission)
    if status:
        query = query.where(SkillSubmission.status == status)
    if domain:
        query = query.where(SkillSubmission.domain == domain)
    rows = (await db.execute(query.order_by(SkillSubmission.updated_at.desc()))).scalars().all()
    return {"total": len(rows), "submissions": [await _serialize_submission(db, row) for row in rows]}


@router.get("/skill-submissions/{submission_id}")
async def get_skill_submission(
    submission_id: str, _admin: dict = Depends(get_admin_user), db: AsyncSession = Depends(get_db),
):
    return await _serialize_submission(db, await _get_submission(db, submission_id), True)


@router.get("/skill-submissions/samples/{sample_id}")
async def get_skill_submission_sample(
    sample_id: str, _admin: dict = Depends(get_admin_user), db: AsyncSession = Depends(get_db),
):
    sample = (await db.execute(select(SkillSubmissionSample).where(
        SkillSubmissionSample.id == sample_id
    ))).scalar_one_or_none()
    if not sample:
        _fail(404, "SKILL_SAMPLE_NOT_FOUND", "样例不存在。")
    return FileResponse(sample.file_path, media_type=sample.content_type, filename=sample.file_name)


@router.post("/skill-submissions/{submission_id}/start-review")
async def start_skill_submission_review(
    submission_id: str, admin: dict = Depends(get_admin_user), db: AsyncSession = Depends(get_db),
):
    row = await _get_submission(db, submission_id)
    if row.status != "submitted":
        _fail(409, "SKILL_SUBMISSION_STATUS_CONFLICT", "只有已提交投稿可以开始审核。")
    count = int(await db.scalar(select(func.count()).select_from(SkillSubmissionSample).where(
        SkillSubmissionSample.submission_id == row.id
    )) or 0)
    if count < 1:
        _fail(409, "SKILL_SUBMISSION_SAMPLE_REQUIRED", "投稿至少需要一张用户授权的成功生成样例。")
    row.status = "under_review"
    row.review_message = None
    row.reviewed_by = admin.get("username")
    db.add(_review_event(row, admin, "under_review"))
    await _audit(db, admin, "skill_submission_review_started", {"submission_id": row.id})
    await db.commit()
    return await _serialize_submission(db, row)


async def _finish_review(
    db: AsyncSession, row: SkillSubmission, admin: dict, status: str, action: str, message: str,
) -> dict:
    if row.status not in {"submitted", "under_review"}:
        _fail(409, "SKILL_SUBMISSION_STATUS_CONFLICT", "当前状态不允许执行该审核操作。")
    if not message.strip():
        _fail(400, "SKILL_REVIEW_MESSAGE_REQUIRED", "请填写具体审核意见。")
    row.status = status
    row.review_message = message.strip()
    row.reviewed_by = admin.get("username")
    row.reviewed_at = datetime.now(timezone.utc)
    db.add(_review_event(row, admin, action, row.review_message))
    await _audit(db, admin, f"skill_submission_{action}", {"submission_id": row.id, "message": row.review_message})
    await db.commit()
    return await _serialize_submission(db, row)


@router.post("/skill-submissions/{submission_id}/request-changes")
async def request_skill_submission_changes(
    submission_id: str, req: SubmissionReviewRequest,
    admin: dict = Depends(get_admin_user), db: AsyncSession = Depends(get_db),
):
    return await _finish_review(db, await _get_submission(db, submission_id), admin, "changes_requested", "changes_requested", req.message)


@router.post("/skill-submissions/{submission_id}/reject")
async def reject_skill_submission(
    submission_id: str, req: SubmissionReviewRequest,
    admin: dict = Depends(get_admin_user), db: AsyncSession = Depends(get_db),
):
    return await _finish_review(db, await _get_submission(db, submission_id), admin, "rejected", "rejected", req.message)


@router.post("/skill-submissions/{submission_id}/approve")
async def approve_skill_submission(
    submission_id: str, admin: dict = Depends(get_super_admin_user), db: AsyncSession = Depends(get_db),
):
    row = await _get_submission(db, submission_id)
    if row.status != "under_review":
        _fail(409, "SKILL_SUBMISSION_STATUS_CONFLICT", "只有审核中的投稿可以批准。")
    ensure_valid_package(row.domain, row.payload)
    samples = (await db.execute(select(SkillSubmissionSample).where(
        SkillSubmissionSample.submission_id == row.id
    ).order_by(SkillSubmissionSample.created_at.asc()))).scalars().all()
    if not samples:
        _fail(409, "SKILL_SUBMISSION_SAMPLE_REQUIRED", "投稿缺少授权样例。")
    cover = next((item for item in samples if item.public_cover), samples[0])
    cover.public_cover = True
    public_skill_id = row.public_skill_id or f"community_{row.user_id.replace('-', '')[:8]}_{row.local_skill_id.lower().replace('-', '_')[:48]}"
    package_payload = dict(row.payload or {})
    package_payload["availability"] = "ready"
    package = SkillPackage(
        skill_id=public_skill_id, version=row.version, name=row.name, domain=row.domain,
        status="published", summary=row.summary, payload=package_payload,
        created_by=row.author_display_name, published_by=admin.get("username"),
        published_at=datetime.now(timezone.utc), source="community",
        author_display_name=row.author_display_name, preview_sample_id=cover.id,
        source_submission_id=row.id,
    )
    db.add(package)
    row.status = "approved"
    row.public_skill_id = public_skill_id
    row.reviewed_by = admin.get("username")
    row.reviewed_at = datetime.now(timezone.utc)
    db.add(_review_event(row, admin, "approved"))
    await _audit(db, admin, "skill_submission_approved", {
        "submission_id": row.id, "skill_id": public_skill_id, "version": row.version,
    })
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        _fail(409, "SKILL_PACKAGE_DUPLICATE", "该社区 Skill 版本已经发布。")
    await db.refresh(package)
    return {"submission": await _serialize_submission(db, row), "package": serialize_package(package)}
