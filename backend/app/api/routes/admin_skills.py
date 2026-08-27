import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_admin_user
from app.models.audit import AdminAuditLog
from app.models.skill import SkillPackage
from app.services.skill_catalog import ensure_valid_package, serialize_package, validate_package_payload


router = APIRouter()


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


async def _audit(db: AsyncSession, admin: dict, action: str, detail: dict) -> None:
    db.add(AdminAuditLog(
        admin=(admin or {}).get("username") or (admin or {}).get("sub", "admin"),
        action=action,
        detail=json.dumps(detail, ensure_ascii=False),
    ))


async def _get_package(db: AsyncSession, package_id: str) -> SkillPackage:
    row = (await db.execute(select(SkillPackage).where(SkillPackage.id == package_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Skill 版本不存在")
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
            raise HTTPException(status_code=400, detail="status 不合法")
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
        raise HTTPException(status_code=409, detail="该 Skill 版本已存在") from exc
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
        raise HTTPException(status_code=409, detail="已发布版本不可修改，请创建新版本")
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
        raise HTTPException(status_code=409, detail="只有草稿版本可以发布")
    return serialize_package(await _activate_package(db, row, admin, "skill_package_published"))


@router.post("/skill-packages/{package_id}/rollback")
async def rollback_skill_package(
    package_id: str,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_package(db, package_id)
    if row.status != "archived":
        raise HTTPException(status_code=409, detail="只有已归档版本可以回滚")
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
