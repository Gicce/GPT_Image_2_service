import json
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.security import get_admin_user
from app.core.redis import get_redis, publish_notice_update
from app.core.config import settings
from app.models.user import User
from app.models.token import (
    TokenInventory, RuntimeTokenAssignment, Order, UsageLog, OrderStatus,
    RefundRequest, RefundRequestStatus,
)
from app.models.content import Notice, AIModel
from app.models.billing import BillingTransaction
from app.models.audit import AdminAuditLog
from app.services import billing
from app.services import runtime_token as rt
from app.services import refund as refund_service

router = APIRouter()

IMAGE2_MODEL_ID = "gpt-image-2"

mask_token = rt.mask_token


async def _record_audit(db: AsyncSession, admin: dict, action: str, detail: dict):
    db.add(AdminAuditLog(
        admin=(admin or {}).get("sub", "admin"),
        action=action,
        detail=json.dumps(detail, ensure_ascii=False),
    ))


# ── Image2 配置（唯一的“模型中心”） ──────────────────────────────

class Image2ConfigUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=128)
    provider: Optional[str] = Field(default=None, max_length=32)
    is_enabled: Optional[bool] = None
    trial_allowed: Optional[bool] = None
    price_per_call_usd: Optional[Decimal] = Field(default=None, gt=0, max_digits=18, decimal_places=6)


@router.get("/image2-config")
async def get_image2_config(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    cfg = await billing.get_image2_config(db)
    if cfg is None:
        return {"exists": False}
    return {
        "exists": True,
        "id": cfg.id,
        "model_id": cfg.name,
        "display_name": cfg.display_name,
        "provider": cfg.provider,
        "enabled": cfg.is_enabled,
        "trial_enabled": cfg.trial_allowed,
        "billing_mode": "per_call",
        "price_per_call_usd": str(cfg.price_per_call) if cfg.price_per_call is not None else None,
        "currency": cfg.currency,
    }


@router.put("/image2-config")
async def update_image2_config(
    req: Image2ConfigUpdate,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """仅允许修改 Image2 配置；model_id / 计费方式 / 币种为系统固定值，价格修改写审计日志。"""
    cfg = await billing.get_image2_config(db)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Image2 配置不存在")

    changed = {}
    if req.display_name is not None and req.display_name.strip():
        cfg.display_name = req.display_name.strip()
        changed["display_name"] = cfg.display_name
    if req.provider is not None and req.provider.strip():
        cfg.provider = req.provider.strip()
        changed["provider"] = cfg.provider
    if req.is_enabled is not None:
        cfg.is_enabled = req.is_enabled
        changed["enabled"] = req.is_enabled
    if req.trial_allowed is not None:
        cfg.trial_allowed = req.trial_allowed
        changed["trial_enabled"] = req.trial_allowed
    if req.price_per_call_usd is not None:
        old_price = cfg.price_per_call
        cfg.price_per_call = billing.q6(req.price_per_call_usd)
        changed["price_per_call_usd"] = {
            "from": str(old_price) if old_price is not None else None,
            "to": str(cfg.price_per_call),
        }

    if "price_per_call_usd" in changed:
        await _record_audit(db, admin, "image2_price_update", changed)

    return {"ok": True, "changed": changed}


# ── Token 库存（统一 Runtime Token 共享池） ──────────────────────

class TokenBatchInput(BaseModel):
    tokens: list[str]
    is_trial: bool = False
    name: Optional[str] = Field(default=None, max_length=128)


# Runtime Token 合理长度下限：只拦截明显误输入，不校验具体格式（Token 格式未来可能变化）
TOKEN_MIN_LENGTH = 8


def _extract_token_value(line: str) -> str:
    """提取行内 sk- 开头的 Token 片段（支持「名称 sk-xxx」整行粘贴）；无 sk- 时整行即 Token。
    剥离复制粘贴常见带入的尾部标点。"""
    t = line.strip()
    match = re.search(r"(sk-\S+)", t)
    value = match.group(1) if match else t
    return value.rstrip(",;，；、.。)]）")


@router.post("/tokens/batch")
async def add_tokens(req: TokenBatchInput, admin: dict = Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    """批量录入：解析 → 批内去重 → 库内查重 → 新增（可命名）。
    返回完整统计（total/added/duplicate/invalid + 脱敏明细），绝不静默吞掉任何输入。"""
    added = duplicate = invalid = 0
    details: list[dict] = []
    seen: set[str] = set()
    for raw in req.tokens:
        value = _extract_token_value(raw)
        if not value:
            continue  # 空白行：不计入任何统计
        if len(value) < TOKEN_MIN_LENGTH:
            invalid += 1
            details.append({"token": mask_token(value), "reason": "invalid"})
            continue
        if value in seen:
            duplicate += 1
            details.append({"token": mask_token(value), "reason": "duplicate"})
            continue
        seen.add(value)
        # limit(1)：旧库可能存在同 token 多 group 行，scalar_one_or_none 会抛 MultipleResultsFound
        existing = await db.execute(
            select(TokenInventory.id).where(TokenInventory.token_value == value).limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            duplicate += 1
            details.append({"token": mask_token(value), "reason": "duplicate"})
            continue
        db.add(TokenInventory(
            id=str(uuid.uuid4()),
            token_value=value,
            name=req.name,
            is_trial=req.is_trial,
        ))
        added += 1

    if added:
        await _record_audit(db, admin, "token_batch_add", {
            "count": added, "is_trial": req.is_trial, "name": req.name,
        })

    return {
        "total": added + duplicate + invalid,
        "added": added,
        "duplicate": duplicate,
        "invalid": invalid,
        "details": details,
    }


@router.get("/tokens/stats")
async def get_token_stats(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    """共享 Token 池统计：总 Token / 正常 / 正式 / 试用 / 默认 / 不可用 / 活跃绑定数。"""
    async def _count(*conditions):
        result = await db.execute(
            select(func.count()).select_from(TokenInventory).where(*conditions)
        )
        return result.scalar()

    now = datetime.now(timezone.utc)
    total = await _count()
    paid = await _count(TokenInventory.is_trial == False)
    trial = await _count(TokenInventory.is_trial == True)
    defaults = await _count(TokenInventory.is_default == True)
    disabled = await _count(TokenInventory.is_disabled == True)
    expired = await _count(
        TokenInventory.is_disabled == False,
        TokenInventory.expires_at != None,
        TokenInventory.expires_at <= now,
    )
    active_bindings = (await db.execute(
        select(func.count()).select_from(RuntimeTokenAssignment).where(
            RuntimeTokenAssignment.status == "active"
        )
    )).scalar()

    return {
        "total": total,
        "available": total - disabled - expired,
        "paid": paid,
        "trial": trial,
        "defaults": defaults,
        "disabled": disabled,
        "expired": expired,
        "active_bindings": active_bindings,
    }


def _token_row(t: TokenInventory, user_count: int, used_usd, status: str) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "token_value": mask_token(t.token_value),
        "is_trial": t.is_trial,
        "is_default": t.is_default,
        "is_disabled": t.is_disabled,
        "quota_usd": str(t.quota_usd) if t.quota_usd is not None else None,
        "used_usd": str(billing.q6(billing.d(used_usd))) if used_usd is not None else None,
        "expires_at": t.expires_at.isoformat() if t.expires_at else None,
        "status": status,
        "user_count": user_count,
        "created_at": t.created_at.isoformat(),
    }


@router.get("/tokens")
async def list_tokens(
    is_trial: Optional[bool] = None,
    status: Optional[str] = None,
    is_default: Optional[bool] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    _=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """共享 Token 列表（脱敏）：名称 / 类型 / 额度 / 默认 / 状态 / 过期 / 关联用户数。

    search：匹配名称 / Token 明文片段 / 关联用户名或邮箱。
    """
    query = select(TokenInventory)
    if is_trial is not None:
        query = query.where(TokenInventory.is_trial == is_trial)
    if is_default is not None:
        query = query.where(TokenInventory.is_default == is_default)

    if search:
        s = f"%{search.strip()}%"
        uid_res = await db.execute(
            select(RuntimeTokenAssignment.token_id).where(
                RuntimeTokenAssignment.user_id.in_(
                    select(User.id).where(or_(User.username.ilike(s), User.email.ilike(s)))
                ),
                RuntimeTokenAssignment.status == "active",
            )
        )
        bound_ids = [row.token_id for row in uid_res]
        conditions = [
            TokenInventory.token_value.ilike(s),
            TokenInventory.name.ilike(s),
        ]
        if bound_ids:
            conditions.append(TokenInventory.id.in_(bound_ids))
        query = query.where(or_(*conditions))

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    page = max(1, page)
    page_size = max(1, min(200, page_size))
    result = await db.execute(
        query.order_by(TokenInventory.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    tokens = result.scalars().all()

    token_ids = [t.id for t in tokens]
    count_map: dict[str, int] = {}
    if token_ids:
        counts = await db.execute(
            select(RuntimeTokenAssignment.token_id, func.count())
            .where(
                RuntimeTokenAssignment.token_id.in_(token_ids),
                RuntimeTokenAssignment.status == "active",
            )
            .group_by(RuntimeTokenAssignment.token_id)
        )
        count_map = {row[0]: row[1] for row in counts.all()}

    rows = []
    for t in tokens:
        user_count = count_map.get(t.id, 0)
        used = await rt.get_token_used_usd(db, t.id) if t.quota_usd is not None else None
        token_status = await rt.token_effective_status(db, t, used_usd=used)
        if status is not None and token_status != status:
            continue
        rows.append(_token_row(t, user_count, used, token_status))

    return {"total": total, "page": page, "page_size": page_size, "tokens": rows}


@router.get("/tokens/{token_id}")
async def get_token_detail(
    token_id: str,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    _=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Token 详情：基本信息 + 当前关联用户列表（支持搜索，分页）。"""
    t = await db.get(TokenInventory, token_id)
    if not t:
        raise HTTPException(status_code=404, detail="Token 不存在")

    query = select(RuntimeTokenAssignment).where(
        RuntimeTokenAssignment.token_id == token_id,
        RuntimeTokenAssignment.status == "active",
    )
    if search:
        s = f"%{search.strip()}%"
        query = query.where(RuntimeTokenAssignment.user_id.in_(
            select(User.id).where(or_(User.username.ilike(s), User.email.ilike(s)))
        ))

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    page = max(1, page)
    page_size = max(1, min(200, page_size))
    result = await db.execute(
        query.order_by(RuntimeTokenAssignment.assigned_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    assignments = result.scalars().all()

    user_map: dict[str, User] = {}
    if assignments:
        ures = await db.execute(
            select(User).where(User.id.in_([a.user_id for a in assignments]))
        )
        user_map = {u.id: u for u in ures.scalars().all()}

    used = await rt.get_token_used_usd(db, token_id)
    return {
        **_token_row(t, total, used, await rt.token_effective_status(db, t, used_usd=used)),
        "users": [
            {
                "user_id": a.user_id,
                "username": user_map[a.user_id].username if a.user_id in user_map else None,
                "email": user_map[a.user_id].email if a.user_id in user_map else None,
                "account_type": user_map[a.user_id].account_type if a.user_id in user_map else None,
                "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
                "assignment_status": a.status,
            }
            for a in assignments
        ],
    }


class TokenUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    is_disabled: Optional[bool] = None
    is_trial: Optional[bool] = None
    quota_usd: Optional[Decimal] = Field(default=None, max_digits=18, decimal_places=6)
    quota_unlimited: bool = False  # True 时把 quota_usd 置 NULL（无限）
    expires_at: Optional[str] = None  # ISO 日期时间；空串 = 永久有效
    keep_expires: bool = False  # True 时不动过期时间


@router.put("/tokens/{token_id}")
async def update_token(
    token_id: str,
    req: TokenUpdate,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    t = await db.get(TokenInventory, token_id)
    if not t:
        raise HTTPException(status_code=404, detail="Token 不存在")

    changed: dict = {}
    if req.name is not None:
        t.name = req.name.strip() or None
        changed["name"] = t.name
    if req.is_disabled is not None:
        t.is_disabled = req.is_disabled
        changed["is_disabled"] = t.is_disabled
    if req.is_trial is not None:
        t.is_trial = req.is_trial
        changed["is_trial"] = t.is_trial
    if req.quota_unlimited:
        t.quota_usd = None
        changed["quota_usd"] = None
    elif req.quota_usd is not None:
        if req.quota_usd < 0:
            raise HTTPException(status_code=400, detail="额度不能为负")
        t.quota_usd = billing.q6(req.quota_usd)
        changed["quota_usd"] = str(t.quota_usd)
    if not req.keep_expires:
        if req.expires_at:
            try:
                from datetime import datetime as _dt
                t.expires_at = _dt.fromisoformat(req.expires_at.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(status_code=400, detail="过期时间格式无效")
        else:
            t.expires_at = None
        changed["expires_at"] = t.expires_at.isoformat() if t.expires_at else None

    if changed:
        await _record_audit(db, admin, "token_update", {"token_id": token_id, **changed})
    return {"ok": True, "changed": changed}


@router.post("/tokens/{token_id}/set-default")
async def set_token_default(
    token_id: str,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """设为该类型默认 Token：事务内先清同类型旧默认，再设新默认。

    只影响之后的新绑定（注册试用/支付自动绑定/管理员自动挑选），已绑定用户不迁移。
    """
    t = await db.get(TokenInventory, token_id)
    if not t:
        raise HTTPException(status_code=404, detail="Token 不存在")
    if t.is_disabled:
        raise HTTPException(status_code=400, detail="已禁用的 Token 不能设为默认")

    result = await db.execute(
        select(TokenInventory).where(
            TokenInventory.is_trial == t.is_trial,
            TokenInventory.is_default == True,
            TokenInventory.id != t.id,
        )
    )
    for old in result.scalars().all():
        old.is_default = False
    # 部分唯一索引要求同类型任一时刻至多一个 default：先落库清除旧默认再设新
    await db.flush()
    t.is_default = True
    await _record_audit(db, admin, "token_set_default", {
        "token_id": token_id, "is_trial": t.is_trial,
    })
    return {"ok": True, "is_trial": t.is_trial}


@router.delete("/tokens/{token_id}")
async def delete_token(token_id: str, admin: dict = Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(func.count()).select_from(RuntimeTokenAssignment).where(
            RuntimeTokenAssignment.token_id == token_id,
            RuntimeTokenAssignment.status == "active",
        )
    )
    active_users = result.scalar()
    if active_users > 0:
        raise HTTPException(
            status_code=400,
            detail=f"当前关联 {active_users} 个用户，禁止直接删除；请先解绑用户或改为禁用",
        )
    t = await db.get(TokenInventory, token_id)
    if not t:
        raise HTTPException(status_code=404, detail="Token 不存在")
    await db.delete(t)
    await _record_audit(db, admin, "token_delete", {"token_id": token_id})
    return {"ok": True}
# ── Notice ───────────────────────────────────────────────────────

class NoticeUpdate(BaseModel):
    content: str
    is_active: bool = True


@router.put("/notice")
async def update_notice(req: NoticeUpdate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Notice).limit(1))
    notice = result.scalar_one_or_none()
    if notice:
        notice.content = req.content
        notice.is_active = req.is_active
        notice.updated_at = datetime.now(timezone.utc)
    else:
        db.add(Notice(id=str(uuid.uuid4()), content=req.content, is_active=req.is_active))
    await db.commit()
    redis = get_redis()
    await redis.delete("notice_content")
    # 实时广播：在线客户端（SSE）收到后立即重新拉取最新通知
    await publish_notice_update()
    return {"ok": True}


@router.get("/notice")
async def get_notice_admin(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Notice).limit(1))
    notice = result.scalar_one_or_none()
    return {"content": notice.content if notice else "", "is_active": notice.is_active if notice else True}


# ── Users（统一余额） ────────────────────────────────────────────

class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    account_type: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/users")
async def list_users(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.created_at.desc()).limit(200))
    users = result.scalars().all()
    return [
        {
            "id": u.id, "username": u.username, "email": u.email,
            "account_type": u.account_type,
            "is_active": u.is_active,
            "balance_usd": str(billing.q6(billing.d(u.balance_usd))),
            "trial_credit_usd": str(billing.q6(billing.d(u.trial_credit_usd))),
            "trial_expires_at": u.trial_expires_at.isoformat() if u.trial_expires_at else None,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]


@router.get("/users/{user_id}")
async def get_user(user_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    u = result.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 可靠统计：来自 billing_transactions / usage_logs 的真实聚合
    recharge_row = await db.execute(
        select(func.coalesce(func.sum(BillingTransaction.amount_usd), 0)).where(
            BillingTransaction.user_id == user_id,
            BillingTransaction.type == billing.RECHARGE,
            BillingTransaction.status == "SUCCESS",
        )
    )
    total_recharged = recharge_row.scalar()

    spent_row = await db.execute(
        select(func.coalesce(func.sum(UsageLog.cost_usd), 0)).where(UsageLog.user_id == user_id)
    )
    total_spent = spent_row.scalar()

    usage_row = await db.execute(
        select(func.count(UsageLog.id), func.coalesce(func.sum(UsageLog.image_count), 0)).where(
            UsageLog.user_id == user_id
        )
    )
    call_count, image_count = usage_row.one()

    usage_result = await db.execute(
        select(UsageLog).where(UsageLog.user_id == user_id).order_by(UsageLog.created_at.desc()).limit(20)
    )
    usage_logs = usage_result.scalars().all()

    assignment = await rt.get_user_active_assignment(db, user_id)
    assigned = await db.get(TokenInventory, assignment.token_id) if assignment else None

    return {
        "id": u.id, "username": u.username, "email": u.email,
        "account_type": u.account_type,
        "is_active": u.is_active,
        "balance_usd": str(billing.q6(billing.d(u.balance_usd))),
        "trial_credit_usd": str(billing.q6(billing.d(u.trial_credit_usd))),
        "total_recharged_usd": str(total_recharged),
        "total_spent_usd": str(total_spent),
        "image2_call_count": call_count,
        "image2_image_count": image_count,
        "runtime_token": (
            rt.token_public_dict(assigned, assigned_at=assignment.assigned_at)
            if assigned else None
        ),
        "trial_expires_at": u.trial_expires_at.isoformat() if u.trial_expires_at else None,
        "created_at": u.created_at.isoformat(),
        "usage_logs": [
            {
                "model": log.model, "usage_type": log.usage_type,
                "image_count": log.image_count,
                "unit_price": str(log.unit_price) if log.unit_price is not None else None,
                "cost_usd": str(log.cost_usd),
                "created_at": log.created_at.isoformat(),
            }
            for log in usage_logs
        ],
    }


@router.put("/users/{user_id}")
async def update_user(user_id: str, req: UserUpdate, admin: dict = Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    u = result.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    changed = {k: v for k, v in req.model_dump(exclude_none=True).items()}
    for k, v in changed.items():
        setattr(u, k, v)
    if changed:
        await _record_audit(db, admin, "user_update", {"user_id": user_id, **changed})
    return {"ok": True}


class RuntimeTokenAssignRequest(BaseModel):
    """管理员为用户分配/更换 Runtime Token。token_id 省略时自动挑选最旧的可用正式 Token。"""
    token_id: Optional[str] = None


@router.post("/users/{user_id}/runtime-token/assign")
async def admin_assign_runtime_token(
    user_id: str,
    req: RuntimeTokenAssignRequest,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """管理员为用户分配或更换 Image2 Runtime Token（事务内完成，写分配历史 + 审计）。"""
    exists = await db.execute(select(User.id).where(User.id == user_id))
    if not exists.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="用户不存在")

    try:
        token, released = await rt.assign_runtime_token(
            db, user_id, token_id=req.token_id, source="admin_assign",
        )
    except rt.NoAvailableTokenError:
        raise HTTPException(
            status_code=409,
            detail={"code": "NO_AVAILABLE_RUNTIME_TOKEN", "message": "Token 库存中没有可用 Token，请先录入"},
        )
    except rt.TokenNotAssignableError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await _record_audit(db, admin, "runtime_token_assign", {
        "user_id": user_id,
        "token_id": token.id,
        "released_token_id": released.id if released else None,
    })

    assignment = await rt.get_user_active_assignment(db, user_id)
    return {
        "ok": True,
        "runtime_token": rt.token_public_dict(
            token, assigned_at=assignment.assigned_at if assignment else None
        ),
        "released_token_id": released.id if released else None,
    }


@router.post("/users/{user_id}/runtime-token/release")
async def admin_release_runtime_token(
    user_id: str,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """管理员解除用户当前 Runtime Token 绑定（共享池：只影响该用户）。"""
    released = await rt.release_user_token(db, user_id, source="admin_release")
    if released is None:
        raise HTTPException(status_code=400, detail="该用户当前没有绑定的 Runtime Token")
    await _record_audit(db, admin, "runtime_token_release", {
        "user_id": user_id, "token_id": released.id,
    })
    return {"ok": True, "released_token_id": released.id}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    u = result.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    await db.delete(u)
    return {"ok": True}


class BalanceAdjustRequest(BaseModel):
    balance_usd: Optional[Decimal] = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    trial_credit_usd: Optional[Decimal] = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    remark: str = Field(default="", max_length=255)


@router.put("/users/{user_id}/balance")
async def adjust_user_balance(
    user_id: str,
    req: BalanceAdjustRequest,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """管理员直接设置现金余额 / 试用额度（写 ADMIN_ADJUSTMENT 流水 + 审计）。"""
    result = await db.execute(select(User).where(User.id == user_id).with_for_update())
    u = result.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")

    detail = {}
    if req.balance_usd is not None:
        before = billing.d(u.balance_usd)
        u.balance_usd = billing.q6(req.balance_usd)
        db.add(BillingTransaction(
            user_id=user_id,
            type=billing.ADMIN_ADJUSTMENT,
            status="SUCCESS",
            amount_usd=billing.q6(billing.d(u.balance_usd) - before),
            trial_amount=Decimal("0"),
            balance_amount=billing.q6(billing.d(u.balance_usd) - before),
            billing_source="CASH",
            balance_before=before,
            balance_after=u.balance_usd,
            remark=req.remark or "admin balance adjustment",
        ))
        detail["balance_usd"] = {"from": str(before), "to": str(u.balance_usd)}
    if req.trial_credit_usd is not None:
        before = billing.d(u.trial_credit_usd)
        u.trial_credit_usd = billing.q6(req.trial_credit_usd)
        db.add(BillingTransaction(
            user_id=user_id,
            type=billing.ADMIN_ADJUSTMENT,
            status="SUCCESS",
            amount_usd=billing.q6(billing.d(u.trial_credit_usd) - before),
            trial_amount=billing.q6(billing.d(u.trial_credit_usd) - before),
            balance_amount=Decimal("0"),
            billing_source="TRIAL",
            trial_before=before,
            trial_after=u.trial_credit_usd,
            remark=req.remark or "admin trial adjustment",
        ))
        detail["trial_credit_usd"] = {"from": str(before), "to": str(u.trial_credit_usd)}

    if not detail:
        raise HTTPException(status_code=400, detail="未指定任何调整项")
    await _record_audit(db, admin, "balance_adjust", {"user_id": user_id, **detail, "remark": req.remark})

    return {
        "ok": True,
        "balance_usd": str(billing.q6(billing.d(u.balance_usd))),
        "trial_credit_usd": str(billing.q6(billing.d(u.trial_credit_usd))),
    }


# ── Billing Transactions（账务流水查询） ─────────────────────────

@router.get("/billing/transactions")
async def list_billing_transactions(
    user_id: Optional[str] = None,
    type: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    _=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(BillingTransaction)
    if user_id:
        query = query.where(BillingTransaction.user_id == user_id)
    if type:
        query = query.where(BillingTransaction.type == type)
    if status:
        query = query.where(BillingTransaction.status == status)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    page = max(1, page)
    page_size = max(1, min(200, page_size))
    result = await db.execute(
        query.order_by(BillingTransaction.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    txns = result.scalars().all()

    user_ids = list({t.user_id for t in txns})
    uname_map = {}
    if user_ids:
        ures = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
        uname_map = {row.id: row.username for row in ures}

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "transactions": [billing._txn_dict(t) | {"username": uname_map.get(t.user_id, "")} for t in txns],
    }


@router.post("/billing/transactions/{txn_id}/refund")
async def refund_billing_transaction(
    txn_id: str,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """对 Image2 SUCCESS 扣费流水执行管理员退款（幂等）。"""
    result = await billing.refund_image2_transaction(db, txn_id, reason="admin image2 refund")
    if result is None:
        raise HTTPException(status_code=404, detail="流水不存在")
    txn, _user = result
    if txn.status != "REFUNDED":
        raise HTTPException(status_code=400, detail=f"当前状态 {txn.status} 不支持退款")
    await _record_audit(db, admin, "image2_refund", {"txn_id": txn.id, "request_id": txn.request_id})
    return {"ok": True, "status": txn.status}


# ── Orders ───────────────────────────────────────────────────────

@router.get("/orders")
async def list_orders(
    status: Optional[str] = None,
    _=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """订单列表：金额成对语义（付款 CNY / 到账 USD）+ 累计退款 + 最新退款申请。"""
    query = select(Order).order_by(Order.created_at.desc()).limit(200)
    if status:
        query = select(Order).where(Order.status == status).order_by(Order.created_at.desc()).limit(200)
    result = await db.execute(query)
    orders = result.scalars().all()
    user_ids = list({o.user_id for o in orders})
    uname_map = {}
    if user_ids:
        ures = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
        uname_map = {row.id: row.username for row in ures}

    order_ids = [o.id for o in orders]
    latest_requests: dict[str, RefundRequest] = {}
    if order_ids:
        reqs = await db.execute(
            select(RefundRequest)
            .where(RefundRequest.order_id.in_(order_ids))
            .order_by(RefundRequest.requested_at.asc())
        )
        for r in reqs.scalars().all():
            latest_requests[r.order_id] = r  # asc 迭代 → 保留最新

    return [
        {
            "id": o.id, "user_id": o.user_id, "username": uname_map.get(o.user_id, ""),
            "out_trade_no": o.out_trade_no,
            "trade_no": o.trade_no,
            "group": o.group,  # 历史订单保留展示；新订单为 null
            "amount_usd": float(o.amount_usd), "amount_cny": float(o.amount_cny),
            "exchange_rate": float(o.exchange_rate) if o.exchange_rate else None,
            "refunded_cny": float(o.refunded_cny),
            "refunded_usd": float(o.refunded_usd),
            "remaining_refundable_cny": float(refund_service.fen_to_cny(refund_service.order_remaining_fen(o))),
            "pay_type": o.pay_type, "status": o.status,
            "out_refund_no": o.out_refund_no,
            "created_at": o.created_at.isoformat(),
            "paid_at": o.paid_at.isoformat() if o.paid_at else None,
            "refund_requested_at": o.refund_requested_at.isoformat() if o.refund_requested_at else None,
            "refund_request": refund_service.refund_request_public_dict(latest_requests.get(o.id)),
        }
        for o in orders
    ]


@router.get("/orders/{order_id}/refund/summary")
async def get_refund_summary(order_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    """退款审核/退款 Modal 数据：订单金额全景 + 用户余额 + 最新退款申请。"""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    user = await db.get(User, order.user_id)
    latest = await db.execute(
        select(RefundRequest)
        .where(RefundRequest.order_id == order.id)
        .order_by(RefundRequest.requested_at.desc())
        .limit(1)
    )
    req = latest.scalar_one_or_none()

    remaining_fen = refund_service.order_remaining_fen(order)
    remaining_cny = refund_service.fen_to_cny(remaining_fen)
    return {
        "order_id": order.id,
        "out_trade_no": order.out_trade_no,
        "username": user.username if user else None,
        "user_balance_usd": str(billing.q6(billing.d(user.balance_usd))) if user else None,
        "user_trial_credit_usd": str(billing.q6(billing.d(user.trial_credit_usd))) if user else None,
        "amount_usd": float(order.amount_usd),
        "amount_cny": float(order.amount_cny),
        "exchange_rate": float(order.exchange_rate) if order.exchange_rate else None,
        "refunded_cny": float(order.refunded_cny),
        "refunded_usd": float(order.refunded_usd),
        "remaining_refundable_cny": float(remaining_cny),
        "max_usd_reversal": float(refund_service.compute_usd_reversal(order, remaining_fen)),
        "order_status": order.status,
        "refund_request": refund_service.refund_request_public_dict(req),
    }


@router.post("/orders/{order_id}/close")
async def close_order(order_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status == OrderStatus.ASSIGNED:
        raise HTTPException(status_code=400, detail="已入账订单请使用退款功能")
    if order.status not in (OrderStatus.PENDING, OrderStatus.PAID):
        raise HTTPException(status_code=400, detail="只能关闭待支付或已支付订单")
    if order.status == OrderStatus.PENDING:
        try:
            from app.core.wechatpay import wechatpay_request
            path = f"/v3/pay/transactions/out-trade-no/{order.out_trade_no}/close"
            code, wx_result = await wechatpay_request(path, method="POST", data={"mchid": settings.WECHAT_MCHID})
            if code not in (200, 204):
                raise HTTPException(status_code=502, detail=f"微信关闭订单失败: {wx_result}")
        except ImportError:
            pass
    order.status = OrderStatus.CLOSED
    return {"ok": True}


class RefundReviewRequest(BaseModel):
    review_note: str = Field(default="", max_length=500)


@router.post("/orders/{order_id}/refund/approve")
async def approve_refund(
    order_id: str,
    req: RefundReviewRequest = RefundReviewRequest(),
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """批准用户退款申请：APPROVED → 调微信 → PROCESSING（微信确认 SUCCESS 才冲正）。"""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    open_req = await refund_service.get_open_request(db, order.id)
    if open_req is None:
        raise HTTPException(status_code=400, detail="该订单没有待处理的退款申请")

    admin_name = (admin or {}).get("sub", "admin")
    try:
        await refund_service.approve_refund_request(db, open_req, admin=admin_name, review_note=req.review_note or None)
        await refund_service.execute_refund(db, open_req)
        await db.commit()
    except refund_service.RefundError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        logger_exc = __import__("logging").getLogger(__name__)
        logger_exc.exception("approve refund failed for order %s", order_id)
        raise HTTPException(status_code=502, detail=f"退款执行失败: {exc}")

    await _record_audit(db, admin, "refund_approve", {
        "order_id": order.id, "out_trade_no": order.out_trade_no,
        "refund_request_id": open_req.id, "out_refund_no": open_req.out_refund_no,
        "requested_amount_fen": open_req.requested_amount_fen,
        "result_status": open_req.status,
    })
    await db.commit()

    return {
        "status": open_req.status,
        "order_status": order.status,
        "out_refund_no": open_req.out_refund_no,
        "message": (
            "微信退款已受理，等待微信确认后完成冲正"
            if open_req.status == RefundRequestStatus.PROCESSING
            else f"退款状态: {open_req.status}"
        ),
    }


@router.post("/orders/{order_id}/refund/reject")
async def reject_refund(
    order_id: str,
    req: RefundReviewRequest,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """拒绝用户退款申请：订单回到申请前状态，拒绝原因对用户可见。"""
    if not (req.review_note or "").strip():
        raise HTTPException(status_code=400, detail="拒绝退款必须填写原因")

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    open_req = await refund_service.get_open_request(db, order.id)
    if open_req is None:
        raise HTTPException(status_code=400, detail="该订单没有待处理的退款申请")

    admin_name = (admin or {}).get("sub", "admin")
    try:
        await refund_service.reject_refund_request(
            db, open_req, admin=admin_name, review_note=req.review_note.strip()
        )
        await db.commit()
    except refund_service.RefundError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    await _record_audit(db, admin, "refund_reject", {
        "order_id": order.id, "out_trade_no": order.out_trade_no,
        "refund_request_id": open_req.id, "review_note": req.review_note.strip(),
    })
    await db.commit()

    return {"status": order.status, "refund_request_status": open_req.status, "message": "退款已拒绝"}


class AdminDirectRefundRequest(BaseModel):
    refund_amount_cny: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)
    reason: str = Field(default="", max_length=255)


@router.post("/orders/{order_id}/refund")
async def admin_direct_refund(
    order_id: str,
    req: AdminDirectRefundRequest = AdminDirectRefundRequest(),
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """管理员主动退款（无需用户申请）：统一走 RefundService 执行/结算链路。"""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    admin_name = (admin or {}).get("sub", "admin")
    try:
        refund_req = await refund_service.admin_direct_refund(
            db, order,
            admin=admin_name,
            refund_amount_cny=req.refund_amount_cny,
            reason=req.reason or None,
        )
        await db.commit()
    except refund_service.RefundError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        logger_exc = __import__("logging").getLogger(__name__)
        logger_exc.exception("admin direct refund failed for order %s", order_id)
        raise HTTPException(status_code=502, detail=f"退款执行失败: {exc}")

    await _record_audit(db, admin, "admin_direct_refund", {
        "order_id": order.id, "out_trade_no": order.out_trade_no,
        "refund_request_id": refund_req.id, "out_refund_no": refund_req.out_refund_no,
        "amount_fen": refund_req.requested_amount_fen,
        "result_status": refund_req.status,
    })
    await db.commit()

    return {
        "status": refund_req.status,
        "order_status": order.status,
        "out_refund_no": refund_req.out_refund_no,
        "message": (
            "微信退款已受理，等待微信确认后完成冲正"
            if refund_req.status == RefundRequestStatus.PROCESSING
            else f"退款状态: {refund_req.status}"
        ),
    }

class OrderUpdate(BaseModel):
    status: Optional[str] = None


@router.put("/orders/{order_id}")
async def update_order(order_id: str, req: OrderUpdate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if req.status is not None:
        order.status = req.status
    return {"ok": True}


@router.delete("/orders/{order_id}")
async def delete_order(order_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status in (OrderStatus.PAID, OrderStatus.ASSIGNED):
        raise HTTPException(status_code=400, detail="已支付/已入账订单不可删除，请先退款")
    await db.delete(order)
    return {"ok": True}


class AdminCreateOrderRequest(BaseModel):
    amount_usd: float = Field(gt=0)
    user_id: Optional[str] = None


@router.post("/orders/create")
async def admin_create_order(req: AdminCreateOrderRequest, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    """管理员代客创建余额充值订单。"""
    from datetime import timedelta as _td
    from app.core.wechatpay import get_wxpay
    from app.api.routes.payment import is_wechat_pay_configured, should_use_dev_payment, _get_exchange_rate

    user_id = req.user_id
    if not user_id:
        result = await db.execute(select(User).limit(1))
        u = result.scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=400, detail="系统中没有用户，请先创建用户")
        user_id = u.id

    rate = await _get_exchange_rate()
    amount_cny = round(req.amount_usd * rate, 2)
    out_trade_no = f"CY{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"

    order = Order(
        user_id=user_id,
        out_trade_no=out_trade_no,
        amount_usd=Decimal(str(req.amount_usd)),
        amount_cny=Decimal(str(amount_cny)),
        exchange_rate=Decimal(str(rate)),
        pay_type="wxpay",
        status="pending",
    )
    db.add(order)
    await db.flush()

    if should_use_dev_payment():
        code_url = f"dev://pay/{out_trade_no}"
    else:
        if not is_wechat_pay_configured():
            raise HTTPException(status_code=500, detail="微信支付配置不完整")
        wxpay = get_wxpay()
        time_expire = (datetime.now(timezone(_td(hours=8))) + _td(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+08:00")
        code, result = await wxpay.pay(
            description="CyImagePro 余额充值",
            out_trade_no=out_trade_no,
            amount={"total": int(round(amount_cny * 100)), "currency": "CNY"},
            time_expire=time_expire,
        )
        if code != 200:
            raise HTTPException(status_code=502, detail=f"微信支付下单失败: {result}")
        code_url = result.get("code_url")

    return {
        "out_trade_no": out_trade_no,
        "code_url": code_url,
        "amount_usd": req.amount_usd,
        "amount_cny": amount_cny,
        "exchange_rate": rate,
        "status": "pending",
    }


@router.get("/orders/query_pay/{out_trade_no}")
async def admin_query_pay(out_trade_no: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    from app.core.wechatpay import get_wxpay
    from app.api.routes.payment import is_wechat_pay_configured, should_use_dev_payment
    from app.services.order_assignment import assign_paid_order, InvalidOrderStatusError

    result = await db.execute(
        select(Order).where(Order.out_trade_no == out_trade_no).with_for_update()
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "pending":
        return {"status": order.status, "out_trade_no": order.out_trade_no}

    if not should_use_dev_payment() and is_wechat_pay_configured():
        wxpay = get_wxpay()
        code, wx_result = await wxpay.query(out_trade_no=order.out_trade_no)
        if code == 200 and wx_result.get("trade_state") == "SUCCESS":
            order.status = "paid"
            order.paid_at = datetime.now(timezone.utc)
            order.trade_no = wx_result.get("transaction_id")

    if order.status == "paid":
        try:
            await assign_paid_order(db, order, auto=True)
        except InvalidOrderStatusError:
            pass

    return {"status": order.status, "out_trade_no": order.out_trade_no}


# ── Dashboard Stats ──────────────────────────────────────────────

@router.get("/stats")
async def get_stats(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    users_total = (await db.execute(select(func.count()).select_from(User))).scalar()
    orders_paid = (await db.execute(
        select(func.count()).select_from(Order).where(Order.paid_at != None)
    )).scalar()
    revenue_result = await db.execute(
        select(func.coalesce(func.sum(BillingTransaction.amount_usd), 0)).where(
            BillingTransaction.type == billing.RECHARGE,
            BillingTransaction.status == "SUCCESS",
        )
    )
    total_revenue = revenue_result.scalar()

    image2_today = (await db.execute(
        select(func.count(UsageLog.id), func.coalesce(func.sum(UsageLog.image_count), 0)).where(
            UsageLog.created_at >= day_start
        )
    )).one()
    image2_total = (await db.execute(
        select(func.count(UsageLog.id), func.coalesce(func.sum(UsageLog.image_count), 0),
               func.coalesce(func.sum(UsageLog.cost_usd), 0))
    )).one()

    # 复用 token stats
    token_stats = await get_token_stats(_=None, db=db)

    return {
        "users_total": users_total,
        "orders_paid": orders_paid,
        "total_revenue_usd": str(total_revenue),
        "image2_today": {"calls": image2_today[0], "images": image2_today[1]},
        "image2_total": {"calls": image2_total[0], "images": image2_total[1], "cost_usd": str(image2_total[2])},
        "token_stats": token_stats,
    }


# ── Audit Logs ───────────────────────────────────────────────────

@router.get("/audit-logs")
async def list_audit_logs(
    page: int = 1,
    page_size: int = 50,
    _=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(AdminAuditLog)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    result = await db.execute(
        query.order_by(AdminAuditLog.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    logs = result.scalars().all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "logs": [
            {"id": l.id, "admin": l.admin, "action": l.action, "detail": l.detail,
             "created_at": l.created_at.isoformat()}
            for l in logs
        ],
    }


# ── Admin password change ─────────────────────────────────────────

class PasswordChange(BaseModel):
    new_password: str


@router.put("/password")
async def change_admin_password(req: PasswordChange, _=Depends(get_admin_user)):
    settings.ADMIN_PASSWORD = req.new_password
    return {"ok": True, "note": "重启后失效，如需永久修改请更新 .env 文件中的 ADMIN_PASSWORD"}


# ── System Config (.env) ─────────────────────────────────────────

SENSITIVE_KEYS = {"SECRET_KEY", "ADMIN_PASSWORD", "POSTGRES_PASSWORD", "WECHAT_APIV3_KEY", "SMTP_PASSWORD", "PACKYAPI_IMAGE_MASTER_TOKEN", "PACKYAPI_MASTER_TOKEN"}
MASK = "********"

CONFIG_CATEGORIES = [
    {
        "label": "数据库",
        "icon": "database",
        "keys": ["POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"],
        "descriptions": {"POSTGRES_DB": "数据库名", "POSTGRES_USER": "数据库用户", "POSTGRES_PASSWORD": "数据库密码"},
    },
    {
        "label": "认证与安全",
        "icon": "security",
        "keys": ["SECRET_KEY", "ADMIN_USERNAME", "ADMIN_PASSWORD"],
        "descriptions": {"SECRET_KEY": "JWT 密钥", "ADMIN_USERNAME": "管理员用户名", "ADMIN_PASSWORD": "管理员密码"},
    },
    {
        "label": "微信支付",
        "icon": "wechat",
        "keys": ["WECHAT_MCHID", "WECHAT_APPID", "WECHAT_APIV3_KEY", "WECHAT_CERT_SERIAL_NO",
                 "WECHAT_PRIVATE_KEY_PATH", "WECHAT_PUBLIC_KEY_PATH", "WECHAT_PUBLIC_KEY_ID",
                 "WECHAT_NOTIFY_URL"],
        "descriptions": {"WECHAT_MCHID": "商户号", "WECHAT_APPID": "应用 ID", "WECHAT_APIV3_KEY": "APIv3 密钥",
                         "WECHAT_CERT_SERIAL_NO": "证书序列号", "WECHAT_PRIVATE_KEY_PATH": "私钥路径",
                         "WECHAT_PUBLIC_KEY_PATH": "公钥路径", "WECHAT_PUBLIC_KEY_ID": "公钥 ID",
                         "WECHAT_NOTIFY_URL": "支付回调 URL"},
    },
    {
        "label": "Runtime Token",
        "icon": "server",
        "keys": ["PACKYAPI_IMAGE_MASTER_TOKEN", "PACKYAPI_IMAGE_BASE_URL"],
        "descriptions": {"PACKYAPI_IMAGE_MASTER_TOKEN": "Image2 上游 Master Token（服务端保存）",
                         "PACKYAPI_IMAGE_BASE_URL": "Image2 上游地址"},
    },
    {
        "label": "邮件服务 (SMTP)",
        "icon": "smtp",
        "keys": ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM_NAME", "SMTP_USE_SSL"],
        "descriptions": {"SMTP_HOST": "SMTP 服务器", "SMTP_PORT": "端口", "SMTP_USER": "发件邮箱",
                         "SMTP_PASSWORD": "授权码/密码", "SMTP_FROM_NAME": "发件人名称", "SMTP_USE_SSL": "使用 SSL"},
    },
    {
        "label": "支付限额",
        "icon": "payment",
        "keys": ["PAYMENT_MIN_TOTAL_USD", "PAYMENT_MAX_TOTAL_USD", "TRIAL_CREDIT_USD"],
        "descriptions": {"PAYMENT_MIN_TOTAL_USD": "最低充值金额 ($)", "PAYMENT_MAX_TOTAL_USD": "最高充值金额 ($)",
                         "TRIAL_CREDIT_USD": "注册试用额度 ($)"},
    },
    {
        "label": "服务器",
        "icon": "server",
        "keys": ["SERVER_BASE_URL", "EXCHANGE_RATE_API", "RESERVATION_TTL_HOURS"],
        "descriptions": {"SERVER_BASE_URL": "服务器地址", "EXCHANGE_RATE_API": "汇率 API",
                         "RESERVATION_TTL_HOURS": "预占超时自动释放（小时）"},
    },
]


def _infer_field_type(key: str) -> str:
    if key in SENSITIVE_KEYS:
        return "password"
    if key.endswith("_USE_SSL"):
        return "boolean"
    if key.endswith("_PORT") or key.endswith("_MIN") or key.endswith("_MAX") or key.endswith("_EXPIRE") or key.endswith("_MINUTES") or key.endswith("_HOURS") or "_MIN_" in key or "_MAX_" in key:
        return "number"
    return "text"


def _parse_env_file(path: str) -> list[dict]:
    lines = []
    if not os.path.exists(path):
        return lines
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            stripped = line.strip()
            if not stripped:
                lines.append({"type": "blank"})
            elif stripped.startswith("#"):
                lines.append({"type": "comment", "raw": line})
            elif "=" in stripped:
                key, _, value = stripped.partition("=")
                lines.append({"type": "kv", "key": key.strip(), "value": value, "raw": line})
            else:
                lines.append({"type": "comment", "raw": line})
    return lines


def _write_env_file(path: str, parsed: list[dict], updates: dict[str, str]) -> list[str]:
    updated_keys = []
    existing_keys = set()
    for entry in parsed:
        if entry["type"] == "kv":
            existing_keys.add(entry["key"])
            if entry["key"] in updates and updates[entry["key"]] != MASK:
                old_val = entry["value"]
                entry["value"] = updates[entry["key"]]
                entry["raw"] = f"{entry['key']}={entry['value']}"
                if old_val != entry["value"]:
                    updated_keys.append(entry["key"])
    for key in updates:
        if key not in existing_keys and updates[key] != MASK:
            parsed.append({"type": "kv", "key": key, "value": updates[key], "raw": f"{key}={updates[key]}"})
            updated_keys.append(key)
    with open(path, "w", encoding="utf-8") as f:
        for entry in parsed:
            if entry["type"] == "blank":
                f.write("\n")
            else:
                f.write(entry["raw"] + "\n")
    return updated_keys


@router.get("/config")
async def get_config(_=Depends(get_admin_user)):
    env_path = os.environ.get("ENV_FILE_PATH", "/app/.env")
    if not os.path.exists(env_path):
        env_path = ".env"
    parsed = _parse_env_file(env_path)
    env_dict = {e["key"]: e["value"] for e in parsed if e["type"] == "kv"}

    categories = []
    for cat in CONFIG_CATEGORIES:
        items = []
        for key in cat["keys"]:
            raw_val = env_dict.get(key, "")
            is_sensitive = key in SENSITIVE_KEYS
            value = MASK if is_sensitive and raw_val else raw_val
            items.append({
                "key": key,
                "value": value,
                "is_sensitive": is_sensitive,
                "field_type": _infer_field_type(key),
                "description": cat["descriptions"].get(key, key),
            })
        categories.append({"label": cat["label"], "icon": cat["icon"], "items": items})

    return {"categories": categories}


class ConfigUpdateRequest(BaseModel):
    updates: dict[str, str]


@router.put("/config")
async def update_config(req: ConfigUpdateRequest, _=Depends(get_admin_user)):
    env_path = os.environ.get("ENV_FILE_PATH", "/app/.env")
    if not os.path.exists(env_path):
        env_path = ".env"

    all_known_keys = set()
    for cat in CONFIG_CATEGORIES:
        all_known_keys.update(cat["keys"])

    for key in req.updates:
        if key not in all_known_keys:
            raise HTTPException(status_code=400, detail=f"未知配置项: {key}")

    parsed = _parse_env_file(env_path)
    updated_keys = _write_env_file(env_path, parsed, req.updates)

    if updated_keys:
        from app.core.config import Settings
        for key in updated_keys:
            os.environ.pop(key, None)
        new_settings = Settings()
        for field in new_settings.model_fields:
            setattr(settings, field, getattr(new_settings, field))

    return {"ok": True, "updated_keys": updated_keys}


@router.post("/config/restart")
async def restart_backend(_=Depends(get_admin_user)):
    try:
        import docker
        client = docker.from_env()
        containers = client.containers.list(filters={"label": "com.docker.compose.service=backend"})
        if not containers:
            containers = client.containers.list(all=True, filters={"name": "backend"})
        if not containers:
            raise HTTPException(status_code=404, detail="未找到 backend 容器")
        containers[0].restart(timeout=10)
        return {"ok": True}
    except ImportError:
        raise HTTPException(status_code=500, detail="docker SDK 未安装")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"重启失败: {exc}")


# ── Online Devices ────────────────────────────────────────────────

@router.get("/online-devices")
async def list_online_devices(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    """List all currently online devices from Redis (TTL based)."""
    redis = get_redis()
    if not redis:
        return {"devices": [], "message": "Redis unavailable"}

    devices = []
    cursor = 0
    try:
        while True:
            cursor, keys = await redis.scan(cursor, match="online_device:*", count=100)
            for key in keys:
                data_str = await redis.get(key)
                if not data_str:
                    continue
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                user_id = data.get("user_id", "")
                user_email = ""
                if user_id:
                    u_result = await db.execute(select(User).where(User.id == user_id))
                    u = u_result.scalar_one_or_none()
                    if u:
                        user_email = u.email
                devices.append({
                    "device_id": data.get("device_id", ""),
                    "device_name": data.get("device_name", ""),
                    "user_id": user_id,
                    "user_email": user_email,
                    "app_version": data.get("app_version", ""),
                    "platform": data.get("platform", ""),
                    "last_seen": data.get("last_seen", ""),
                    "ip": data.get("ip", ""),
                    "server_url": data.get("server_url", ""),
                })
            if cursor == 0:
                break
    except Exception:
        logger_exc = __import__("logging").getLogger(__name__)
        logger_exc.exception("Redis scan failed")
        return {"devices": [], "message": "Redis scan failed"}

    devices.sort(key=lambda d: d.get("last_seen", ""), reverse=True)
    return {"devices": devices, "total": len(devices)}
