from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.skill import SkillPackage
from app.services.skill_catalog import catalog_etag, serialize_package


router = APIRouter()


async def _published_packages(db: AsyncSession, domain: str | None = None) -> list[SkillPackage]:
    query = select(SkillPackage).where(SkillPackage.status == "published")
    if domain:
        query = query.where(SkillPackage.domain == domain)
    rows = (await db.execute(
        query.order_by(SkillPackage.skill_id.asc(), SkillPackage.published_at.desc(), SkillPackage.updated_at.desc())
    )).scalars().all()
    latest: dict[str, SkillPackage] = {}
    for row in rows:
        latest.setdefault(row.skill_id, row)
    return list(latest.values())


@router.get("/catalog")
async def get_skill_catalog(
    response: Response,
    domain: str | None = Query(default=None),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    db: AsyncSession = Depends(get_db),
):
    rows = await _published_packages(db, domain)
    packages = [serialize_package(row, include_payload=False) for row in rows]
    etag = catalog_etag(packages)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=300"
    if if_none_match == etag:
        response.status_code = 304
        return None
    return {"catalog_version": etag.strip('"'), "packages": packages}


@router.get("/{skill_id}/versions/{version}")
async def get_skill_package(
    skill_id: str,
    version: str,
    response: Response,
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(SkillPackage).where(
        SkillPackage.skill_id == skill_id,
        SkillPackage.version == version,
        SkillPackage.status == "published",
    ))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Skill 版本不存在或尚未发布")
    payload = serialize_package(row)
    etag = catalog_etag([payload])
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=300"
    if if_none_match == etag:
        response.status_code = 304
        return None
    return payload
