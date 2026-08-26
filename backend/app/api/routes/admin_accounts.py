"""管理员账户管理（V4.0.2）。

与客户端用户（users 表）严格隔离：
- /admins/me 系列面向当前登录管理员本人（任何角色）
- 其余端点仅 super_admin 可用（管理员管理）
- 第一版不提供物理删除，仅启用/禁用
"""

import json
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import (
    get_admin_user, get_super_admin_user,
    hash_password, verify_password, _validate_bcrypt_password,
)
from app.models.admin_user import AdminUser
from app.models.audit import AdminAuditLog

router = APIRouter()

VALID_ROLES = ("super_admin", "admin")

MIN_PASSWORD_LENGTH = 10


class AdminCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(default="", max_length=64)
    password: str
    role: str = "admin"


class AdminUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=64)
    display_name: str | None = Field(default=None, max_length=64)
    role: str | None = None
    is_active: bool | None = None


class SelfPasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    new_password: str


def _validate_admin_password(password: str) -> None:
    _validate_bcrypt_password(password)
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"密码长度至少 {MIN_PASSWORD_LENGTH} 位，建议使用密码管理器生成的长密码",
        )


async def _record_audit(db: AsyncSession, admin_username: str, action: str, detail: dict):
    db.add(AdminAuditLog(
        admin=admin_username[:64],
        action=action,
        detail=json.dumps(detail, ensure_ascii=False),
    ))


async def _count_active_super_admins(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).select_from(AdminUser)
        .where(AdminUser.role == "super_admin", AdminUser.is_active.is_(True))
    )
    return result.scalar() or 0


def _admin_info(a: AdminUser) -> dict:
    return {
        "id": a.id,
        "username": a.username,
        "display_name": a.display_name,
        "role": a.role,
        "is_active": a.is_active,
        "must_change_password": a.must_change_password,
        "last_login_at": a.last_login_at.isoformat() if a.last_login_at else None,
        "password_changed_at": a.password_changed_at.isoformat() if a.password_changed_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


async def _get_admin_or_404(db: AsyncSession, admin_id: str) -> AdminUser:
    result = await db.execute(select(AdminUser).where(AdminUser.id == admin_id))
    admin = result.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=404, detail="管理员不存在")
    return admin


# ── 本人信息 / 修改自己的密码 ────────────────────────────────────

@router.get("/admins/me")
async def get_my_profile(
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AdminUser).where(AdminUser.id == admin["id"]))
    me = result.scalar_one_or_none()
    if not me or not me.is_active:
        raise HTTPException(status_code=401, detail="无效的认证信息")
    return _admin_info(me)


@router.put("/admins/me/password")
async def change_my_password(
    req: SelfPasswordChangeRequest,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AdminUser).where(AdminUser.id == admin["id"]))
    me = result.scalar_one_or_none()
    if not me or not me.is_active:
        raise HTTPException(status_code=401, detail="无效的认证信息")

    if not verify_password(req.current_password, me.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确")

    _validate_admin_password(req.new_password)
    me.password_hash = hash_password(req.new_password)
    me.password_changed_at = datetime.now(timezone.utc)
    me.must_change_password = False
    await _record_audit(db, me.username, "admin_password_changed", {"admin_id": me.id})
    await db.commit()
    return {"ok": True, "message": "密码修改成功，请使用新密码重新登录"}


# ── 管理员管理（仅 super_admin） ─────────────────────────────────

@router.get("/admins")
async def list_admins(
    _admin: dict = Depends(get_super_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AdminUser).order_by(AdminUser.created_at.asc()))
    admins = result.scalars().all()
    return {"total": len(admins), "admins": [_admin_info(a) for a in admins]}


@router.get("/admin-login-logs")
async def list_admin_login_logs(
    result: str | None = None,
    username: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    page: int = 1,
    page_size: int = 50,
    _admin: dict = Depends(get_super_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """管理员登录成功/失败审计；IP 与 UA 仅超级管理员可见。"""
    actions = ["admin_login_success", "admin_login_failed"]
    if result == "success":
        actions = ["admin_login_success"]
    elif result == "failed":
        actions = ["admin_login_failed"]
    elif result not in (None, "", "all"):
        raise HTTPException(status_code=400, detail="result 必须为 success、failed 或 all")

    query = select(AdminAuditLog).where(AdminAuditLog.action.in_(actions))
    if username:
        query = query.where(AdminAuditLog.admin.ilike(f"%{username.strip()}%"))

    def _date(value: str) -> datetime:
        try:
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc

    if start_date:
        query = query.where(AdminAuditLog.created_at >= _date(start_date))
    if end_date:
        query = query.where(AdminAuditLog.created_at < _date(end_date) + timedelta(days=1))

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    rows = (await db.execute(
        query.order_by(AdminAuditLog.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    def _row(log: AdminAuditLog) -> dict:
        try:
            detail = json.loads(log.detail or "{}")
        except (TypeError, json.JSONDecodeError):
            detail = {}
        return {
            "id": log.id,
            "username": log.admin,
            "result": "success" if log.action == "admin_login_success" else "failed",
            "reason": detail.get("reason"),
            "ip": detail.get("ip", ""),
            "user_agent": detail.get("ua", ""),
            "created_at": log.created_at.isoformat(),
        }

    return {"total": total, "page": page, "page_size": page_size, "logs": [_row(row) for row in rows]}


@router.post("/admins")
async def create_admin(
    req: AdminCreateRequest,
    admin: dict = Depends(get_super_admin_user),
    db: AsyncSession = Depends(get_db),
):
    username = req.username.strip().lower()
    if not (3 <= len(username) <= 64):
        raise HTTPException(status_code=400, detail="用户名长度需在 3-64 位之间")
    if req.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="角色必须为 super_admin 或 admin")
    _validate_admin_password(req.password)

    existing = await db.execute(select(AdminUser).where(AdminUser.username == username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    new_admin = AdminUser(
        id=str(uuid.uuid4()),
        username=username,
        display_name=req.display_name.strip(),
        password_hash=hash_password(req.password),
        role=req.role,
        is_active=True,
        password_changed_at=datetime.now(timezone.utc),
    )
    db.add(new_admin)
    await _record_audit(db, admin["username"], "admin_created", {
        "target_id": new_admin.id, "username": username, "role": req.role,
    })
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="用户名已存在")
    return _admin_info(new_admin)


@router.put("/admins/{admin_id}")
async def update_admin(
    admin_id: str,
    req: AdminUpdateRequest,
    admin: dict = Depends(get_super_admin_user),
    db: AsyncSession = Depends(get_db),
):
    target = await _get_admin_or_404(db, admin_id)
    changed = {}

    if req.username is not None:
        username = req.username.strip().lower()
        if username != target.username:
            if not (3 <= len(username) <= 64):
                raise HTTPException(status_code=400, detail="用户名长度需在 3-64 位之间")
            existing = await db.execute(select(AdminUser).where(AdminUser.username == username))
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="用户名已存在")
            target.username = username
            changed["username"] = username

    if req.display_name is not None and req.display_name != target.display_name:
        target.display_name = req.display_name.strip()
        changed["display_name"] = target.display_name

    if req.role is not None and req.role != target.role:
        if req.role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail="角色必须为 super_admin 或 admin")
        if target.role == "super_admin" and req.role != "super_admin":
            if await _count_active_super_admins(db) <= 1:
                raise HTTPException(status_code=400, detail="系统必须保留至少一个启用的超级管理员")
        target.role = req.role
        changed["role"] = req.role

    if req.is_active is not None and req.is_active != target.is_active:
        if not req.is_active:
            if target.id == admin["id"]:
                raise HTTPException(status_code=400, detail="不能禁用当前登录的自己的账户")
            if target.role == "super_admin" and await _count_active_super_admins(db) <= 1:
                raise HTTPException(status_code=400, detail="系统必须保留至少一个启用的超级管理员")
        target.is_active = req.is_active
        changed["is_active"] = req.is_active

    if not changed:
        return _admin_info(target)

    await _record_audit(db, admin["username"], "admin_updated", {"target_id": target.id, **changed})
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="用户名已存在")
    return _admin_info(target)


@router.put("/admins/{admin_id}/password")
async def reset_admin_password(
    admin_id: str,
    req: ResetPasswordRequest,
    admin: dict = Depends(get_super_admin_user),
    db: AsyncSession = Depends(get_db),
):
    target = await _get_admin_or_404(db, admin_id)
    _validate_admin_password(req.new_password)
    target.password_hash = hash_password(req.new_password)
    target.password_changed_at = datetime.now(timezone.utc)
    # 强制目标管理员下次登录后先修改密码
    target.must_change_password = True
    await _record_audit(db, admin["username"], "admin_password_reset", {
        "target_id": target.id, "username": target.username,
    })
    await db.commit()
    return {"ok": True, "message": "密码已重置，目标管理员下次登录需修改密码"}
