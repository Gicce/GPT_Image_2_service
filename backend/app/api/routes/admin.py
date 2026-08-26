import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, delete
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
from app.models.billing import BillingTransaction, PricingRule, CostMarginLedger
from app.models.audit import AdminAuditLog
from app.models.device import ClientDevice
from app.services import billing
from app.services import runtime_token as rt
from app.services import refund as refund_service
from app.services import config_service
from app.services import pricing as pricing_service
from app.services import credits_migration
from app.core.security import get_super_admin_user

router = APIRouter()

logger = logging.getLogger(__name__)

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
            "archived_at": u.archived_at.isoformat() if u.archived_at else None,
            "archived_by": u.archived_by,
            "paid_credits": u.paid_credits,
            "trial_credits": u.trial_credits,
            "gift_credits": u.gift_credits,
            "total_credits": u.paid_credits + u.trial_credits + u.gift_credits,
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

    recharge_cr_row = await db.execute(
        select(func.coalesce(func.sum(BillingTransaction.amount_credits), 0)).where(
            BillingTransaction.user_id == user_id,
            BillingTransaction.type == billing.RECHARGE,
            BillingTransaction.status == "SUCCESS",
        )
    )
    total_recharged_credits = recharge_cr_row.scalar()

    spent_row = await db.execute(
        select(func.coalesce(func.sum(UsageLog.cost_usd), 0)).where(UsageLog.user_id == user_id)
    )
    total_spent = spent_row.scalar()

    spent_cr_row = await db.execute(
        select(func.coalesce(func.sum(UsageLog.cost_credits), 0)).where(UsageLog.user_id == user_id)
    )
    total_spent_credits = spent_cr_row.scalar()

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
        "archived_at": u.archived_at.isoformat() if u.archived_at else None,
        "archived_by": u.archived_by,
        "paid_credits": u.paid_credits,
        "trial_credits": u.trial_credits,
        "gift_credits": u.gift_credits,
        "total_credits": u.paid_credits + u.trial_credits + u.gift_credits,
        "balance_usd": str(billing.q6(billing.d(u.balance_usd))),
        "trial_credit_usd": str(billing.q6(billing.d(u.trial_credit_usd))),
        "total_recharged_usd": str(total_recharged),
        "total_recharged_credits": total_recharged_credits,
        "total_spent_usd": str(total_spent),
        "total_spent_credits": total_spent_credits,
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
                "unit_credits": log.unit_credits,
                "cost_credits": log.cost_credits,
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


async def _user_deletion_preview(db: AsyncSession, user_id: str) -> dict:
    """判断用户可物理清理还是必须归档；设备/Token 绑定不算经营历史。"""
    counters = {
        "orders": Order,
        "refund_requests": RefundRequest,
        "billing_transactions": BillingTransaction,
        "usage_logs": UsageLog,
        "cost_margin_ledger": CostMarginLedger,
    }
    blockers = {}
    for name, model in counters.items():
        count = (await db.execute(
            select(func.count()).select_from(model).where(model.user_id == user_id)
        )).scalar() or 0
        blockers[name] = count
    has_business_history = any(blockers.values())
    return {
        "mode": "archive" if has_business_history else "purge",
        "blockers": blockers,
        "has_business_history": has_business_history,
    }


@router.get("/users/{user_id}/deletion-preview")
async def get_user_deletion_preview(
    user_id: str,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    preview = await _user_deletion_preview(db, user_id)
    await _record_audit(db, admin, "user_deletion_preview", {
        "user_id": user_id, "mode": preview["mode"], "blockers": preview["blockers"],
    })
    return {"user_id": user_id, "username": u.username, **preview}


class UserArchiveRequest(BaseModel):
    reason: str = Field(default="", max_length=255)


@router.post("/users/{user_id}/archive")
async def archive_user(
    user_id: str,
    req: UserArchiveRequest,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if u.archived_at is None:
        released = await rt.release_user_token(db, user_id, source="admin_archive")
        u.is_active = False
        u.archived_at = datetime.now(timezone.utc)
        u.archived_by = admin.get("username", "admin")
        await _record_audit(db, admin, "user_archived", {
            "user_id": user_id,
            "username": u.username,
            "reason": req.reason.strip(),
            "released_token_id": released.id if released else None,
        })
    return {
        "ok": True,
        "mode": "archive",
        "archived_at": u.archived_at.isoformat() if u.archived_at else None,
    }


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    preview = await _user_deletion_preview(db, user_id)
    if preview["has_business_history"]:
        await _record_audit(db, admin, "user_purge_blocked", {
            "user_id": user_id, "username": u.username, "blockers": preview["blockers"],
        })
        # HTTPException 会触发请求事务回滚；失败预检审计必须先独立落盘。
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "USER_PURGE_BLOCKED",
                "message": "该账户存在业务历史，不能彻底删除，请改为归档账户",
                "suggested_action": "archive",
                "blockers": preview["blockers"],
            },
        )

    # 仅清理运行数据；trial_claims 与 token_assignment_logs 永久保留。
    await db.execute(delete(ClientDevice).where(ClientDevice.user_id == user_id))
    await db.execute(delete(RuntimeTokenAssignment).where(RuntimeTokenAssignment.user_id == user_id))
    redis = get_redis()
    if redis:
        async for key in redis.scan_iter(match=f"online_device:{user_id}:*"):
            await redis.delete(key)
    audit_detail = {"user_id": user_id, "username": u.username, "email": u.email}
    await db.execute(delete(User).where(User.id == user_id))
    await _record_audit(db, admin, "user_purged", audit_detail)
    return {"ok": True, "mode": "purge"}


class BalanceAdjustRequest(BaseModel):
    """管理员直接设置点数余额（绝对值），写 ADMIN_ADJUSTMENT 流水 + 审计。"""
    paid_credits: Optional[int] = Field(default=None, ge=0)
    trial_credits: Optional[int] = Field(default=None, ge=0)
    gift_credits: Optional[int] = Field(default=None, ge=0)
    # 兼容旧字段（管理后台旧表单）：按 legacy 兑换率折算为点数后设置
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
    """管理员直接设置 paid/trial/gift 点数（写 ADMIN_ADJUSTMENT 流水 + 审计）。"""
    from app.services import config_service

    result = await db.execute(select(User).where(User.id == user_id).with_for_update())
    u = result.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")

    legacy_rate = await config_service.get_legacy_usd_to_credits(db)
    rate = Decimal(legacy_rate)

    def _usd_to_credits(v: Decimal) -> int:
        from decimal import ROUND_HALF_UP
        return int((billing.d(v) * rate).to_integral_value(rounding=ROUND_HALF_UP))

    paid_target = (
        _usd_to_credits(req.balance_usd) if req.balance_usd is not None
        else req.paid_credits
    )
    trial_target = (
        _usd_to_credits(req.trial_credit_usd) if req.trial_credit_usd is not None
        else req.trial_credits
    )
    gift_target = req.gift_credits

    detail = {}
    for name, target, part in (
        ("paid_credits", paid_target, "paid"),
        ("trial_credits", trial_target, "trial"),
        ("gift_credits", gift_target, "gift"),
    ):
        if target is None:
            continue
        before = getattr(u, name)
        if before == target:
            continue
        setattr(u, name, int(target))
        delta = int(target) - before
        db.add(BillingTransaction(
            user_id=user_id,
            type=billing.ADMIN_ADJUSTMENT,
            status="SUCCESS",
            amount_credits=abs(delta),
            paid_credits_part=max(delta, 0) if part == "paid" else 0,
            trial_credits_part=max(delta, 0) if part == "trial" else 0,
            gift_credits_part=max(delta, 0) if part == "gift" else 0,
            billing_source=part.upper() if delta > 0 else "NONE",
            remark=req.remark or f"admin {name} adjustment ({'+' if delta > 0 else ''}{delta})",
        ))
        detail[name] = {"from": before, "to": target}

    if not detail:
        raise HTTPException(status_code=400, detail="未指定任何调整项（或与当前值相同）")

    billing.sync_legacy_mirrors(u, legacy_rate)
    await _record_audit(db, admin, "balance_adjust", {"user_id": user_id, **detail, "remark": req.remark})

    return {
        "ok": True,
        "paid_credits": u.paid_credits,
        "trial_credits": u.trial_credits,
        "gift_credits": u.gift_credits,
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
    recharged_credits_result = await db.execute(
        select(func.coalesce(func.sum(BillingTransaction.amount_credits), 0)).where(
            BillingTransaction.type == billing.RECHARGE,
            BillingTransaction.status == "SUCCESS",
        )
    )
    total_recharged_credits = recharged_credits_result.scalar()

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

    pending_refunds = (await db.execute(
        select(func.count()).select_from(RefundRequest)
        .where(RefundRequest.status == RefundRequestStatus.REQUESTED)
    )).scalar()

    online_devices = 0
    redis = get_redis()
    if redis:
        try:
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor, match="online_device:*", count=200)
                online_devices += len(keys)
                if cursor == 0:
                    break
        except Exception:
            logger.exception("stats: online device scan failed")

    return {
        "users_total": users_total,
        "orders_paid": orders_paid,
        "total_revenue_usd": str(total_revenue),
        "total_recharged_credits": total_recharged_credits,
        "image2_today": {"calls": image2_today[0], "images": image2_today[1]},
        "image2_total": {"calls": image2_total[0], "images": image2_total[1], "cost_usd": str(image2_total[2])},
        "token_stats": token_stats,
        "pending_refunds": pending_refunds,
        "online_devices": online_devices,
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
# 旧 env 密码修改端点（PUT /api/admin/password）已在 V4.0.2 移除：
# 管理员密码改为数据库 bcrypt 存储，本人修改走 PUT /api/admin/admins/me/password，
# 超级管理员重置他人密码走 PUT /api/admin/admins/{id}/password（见 admin_accounts.py）。


# ── System Config (.env) ─────────────────────────────────────────

SENSITIVE_KEYS = {"SECRET_KEY", "POSTGRES_PASSWORD", "WECHAT_APIV3_KEY", "SMTP_PASSWORD", "PACKYAPI_IMAGE_MASTER_TOKEN", "PACKYAPI_MASTER_TOKEN"}
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
        "keys": ["SECRET_KEY"],
        "descriptions": {"SECRET_KEY": "JWT 密钥（管理员账户请在“管理员与登录”中维护）"},
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
    except Exception:
        logger.exception("backend container restart failed")
        raise HTTPException(status_code=500, detail="服务重启失败，请检查容器状态")


# ── Devices（客户端设备历史） ─────────────────────────────────────

@router.get("/online-devices")
async def list_online_devices(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    """兼容入口：仅返回当前在线设备（= /devices?status=online）。"""
    data = await list_devices(status="online", db=db)
    return {"devices": data["devices"], "total": data["online_count"],
            "generated_at": data["generated_at"]}


@router.get("/devices")
async def list_devices(
    status: Optional[str] = None,
    user_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    _=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """客户端设备历史（永久保留，离线不删除）。

    - 真相来源 client_devices 表；online 状态 = Redis 心跳 key 存在（TTL 180s）
    - seconds_since_seen 由服务器时钟计算且恒 >= 0（前端禁止自行用本地时钟求差，
      杜绝「-28 秒前」：任何时钟偏移都不会透出负数）
    """
    if status not in (None, "", "all", "online", "offline"):
        raise HTTPException(status_code=400, detail="status 仅支持 all/online/offline")

    redis = get_redis()
    online_keys: set[str] = set()
    try:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match="online_device:*", count=100)
            for key in keys:
                # key = online_device:{user_id}:{device_id}
                parts = key.split(":", 2)
                if len(parts) == 3:
                    online_keys.add((parts[1], parts[2]))
            if cursor == 0:
                break
    except Exception:
        logger.exception("redis scan for devices failed (treat all as offline)")

    query = select(ClientDevice)
    if user_id:
        query = query.where(ClientDevice.user_id == user_id)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()

    page = max(1, page)
    page_size = max(1, min(200, page_size))
    result = await db.execute(
        query.order_by(ClientDevice.last_seen_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    devices = result.scalars().all()

    user_ids = list({d.user_id for d in devices})
    uname_map: dict[str, str] = {}
    if user_ids:
        ures = await db.execute(select(User.id, User.username, User.email).where(User.id.in_(user_ids)))
        uname_map = {row.id: (row.username, row.email) for row in ures}

    now = datetime.now(timezone.utc)
    rows = []
    online_count_total = 0
    # 全表 online 数（分页前）：Redis key 数即在线设备数
    for uid, did in online_keys:
        online_count_total += 1

    for d in devices:
        online = (d.user_id, d.device_id) in online_keys
        last_seen = d.last_seen_at if d.last_seen_at.tzinfo else d.last_seen_at.replace(tzinfo=timezone.utc)
        seconds = int((now - last_seen).total_seconds())
        username, email = uname_map.get(d.user_id, ("", ""))
        rows.append({
            "user_id": d.user_id,
            "username": username,
            "user_email": email,
            "device_id": d.device_id,
            "device_name": d.device_name or "",
            "platform": d.platform or "",
            "client_version": d.client_version or "",
            "first_seen_at": d.first_seen_at.isoformat() if d.first_seen_at else None,
            "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
            "last_ip": d.last_ip or "",
            "heartbeat_count": d.heartbeat_count,
            "online": online,
            "status": "online" if online else "offline",
            "seconds_since_seen": max(0, seconds),
            # 兼容别名（旧后台页面/旧测试）
            "last_seen": d.last_seen_at.isoformat() if d.last_seen_at else None,
            "app_version": d.client_version or "",
            "ttl_seconds": max(0, 180 - max(0, seconds)) if online else 0,
        })

    if status == "online":
        rows = [r for r in rows if r["online"]]
    elif status == "offline":
        rows = [r for r in rows if not r["online"]]

    return {
        "devices": rows,
        "total": total,
        "online_count": online_count_total,
        "history_count": total,
        "page": page,
        "page_size": page_size,
        "generated_at": now.isoformat(),
    }


# ── Pricing Rules（定价规则 + Price Guard） ───────────────────────

class PricingRuleUpdate(BaseModel):
    unit_credits: int = Field(gt=0, le=100000)
    nominal_unit_cost_rmb: Decimal = Field(ge=0, max_digits=10, decimal_places=6)
    target_margin: Decimal = Field(gt=0, lt=1, max_digits=5, decimal_places=4)
    safety_buffer: Decimal = Field(ge=0, lt=1, max_digits=5, decimal_places=4)
    rounding_step: int = Field(default=10, ge=1, le=1000)
    provider_route: str = Field(default="packyapi", max_length=64)
    enabled: bool = True
    # 低于目标毛利强制保存（仅 super_admin）
    force: bool = False
    override_reason: Optional[str] = Field(default=None, max_length=255)


def _rule_dict(rule: PricingRule, preview: dict | None = None) -> dict:
    out = {
        "id": rule.id,
        "feature": rule.feature,
        "model": rule.model,
        "unit_credits": rule.unit_credits,
        "enabled": rule.enabled,
        "version": rule.version,
        "provider_route": rule.provider_route,
        "nominal_unit_cost_rmb": str(rule.nominal_unit_cost_rmb),
        "target_margin": str(rule.target_margin),
        "safety_buffer": str(rule.safety_buffer),
        "rounding_step": rule.rounding_step,
        "effective_from": rule.effective_from.isoformat() if rule.effective_from else None,
        "override_by": rule.override_by,
        "override_at": rule.override_at.isoformat() if rule.override_at else None,
        "override_reason": rule.override_reason,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }
    if preview is not None:
        out["margin_preview"] = preview
    return out


@router.get("/pricing/rules")
async def list_pricing_rules(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    rules = (await db.execute(select(PricingRule).order_by(PricingRule.feature, PricingRule.model))).scalars().all()
    credits_per_cny = await config_service.get_credits_per_cny(db)
    return {
        "credits_per_cny": credits_per_cny,
        "rules": [
            _rule_dict(r, pricing_service.margin_math(
                r.unit_credits, r.nominal_unit_cost_rmb, r.target_margin,
                r.safety_buffer, credits_per_cny, r.rounding_step,
            ))
            for r in rules
        ],
    }


@router.post("/pricing/rules/preview")
async def preview_pricing(
    req: PricingRuleUpdate,
    _=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """编辑表单实时测算（Price Guard 同一套公式，保存前即可见毛利/最低售价）。"""
    credits_per_cny = await config_service.get_credits_per_cny(db)
    return pricing_service.margin_math(
        req.unit_credits, req.nominal_unit_cost_rmb, req.target_margin,
        req.safety_buffer, credits_per_cny, req.rounding_step,
    )


@router.put("/pricing/rules/{rule_id}")
async def update_pricing_rule(
    rule_id: str,
    req: PricingRuleUpdate,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """修改定价：原地升版本（历史任务经流水快照锁定原价）。

    Price Guard：预计毛利率低于目标 → 普通管理员 403 拒绝；
    super_admin 携 force=true + override_reason 可强制保存（留痕）。
    """
    rule = await db.get(PricingRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="定价规则不存在")

    credits_per_cny = await config_service.get_credits_per_cny(db)
    preview = pricing_service.margin_math(
        req.unit_credits, req.nominal_unit_cost_rmb, req.target_margin,
        req.safety_buffer, credits_per_cny, req.rounding_step,
    )

    if preview["below_target"]:
        if not req.force:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "BELOW_TARGET_MARGIN",
                    "message": (
                        f"低于目标毛利：预计毛利率 {preview['gross_margin']}，"
                        f"目标 {preview['target_margin']}；建议最低售价 {preview['min_unit_credits']} 点"
                    ),
                    "margin_preview": preview,
                },
            )
        if admin.get("role") != "super_admin":
            raise HTTPException(
                status_code=403,
                detail={"code": "OVERRIDE_REQUIRES_SUPER_ADMIN",
                        "message": "低于目标毛利的强制保存仅限超级管理员"},
            )
        if not (req.override_reason or "").strip():
            raise HTTPException(
                status_code=400,
                detail={"code": "OVERRIDE_REASON_REQUIRED", "message": "强制保存必须填写原因"},
            )

    old = {
        "unit_credits": rule.unit_credits,
        "nominal_unit_cost_rmb": str(rule.nominal_unit_cost_rmb),
        "target_margin": str(rule.target_margin),
        "safety_buffer": str(rule.safety_buffer),
    }
    rule.unit_credits = req.unit_credits
    rule.nominal_unit_cost_rmb = req.nominal_unit_cost_rmb
    rule.target_margin = req.target_margin
    rule.safety_buffer = req.safety_buffer
    rule.rounding_step = req.rounding_step
    rule.provider_route = req.provider_route
    rule.enabled = req.enabled
    rule.version = (rule.version or 1) + 1
    rule.effective_from = datetime.now(timezone.utc)
    if req.force:
        rule.override_by = admin.get("sub", "admin")
        rule.override_at = datetime.now(timezone.utc)
        rule.override_reason = req.override_reason

    await _record_audit(db, admin, "pricing_rule_update", {
        "rule_id": rule.id, "from": old,
        "to": {"unit_credits": rule.unit_credits,
               "nominal_unit_cost_rmb": str(rule.nominal_unit_cost_rmb),
               "target_margin": str(rule.target_margin),
               "safety_buffer": str(rule.safety_buffer)},
        "force_override": req.force,
        "override_reason": req.override_reason,
        "margin_preview": preview,
    })

    return {"ok": True, "rule": _rule_dict(rule, preview)}


# ── Cost & Margin Ledger（经营账查询） ────────────────────────────

def _ledger_row_dict(row: CostMarginLedger, username: str = "") -> dict:
    return {
        "id": row.id,
        "billing_transaction_id": row.billing_transaction_id,
        "request_id": row.request_id,
        "user_id": row.user_id,
        "username": username,
        "pricing_rule_id": row.pricing_rule_id,
        "pricing_rule_version": row.pricing_rule_version,
        "unit_credits": row.unit_credits,
        "reserved_credits": row.reserved_credits,
        "charged_credits": row.charged_credits,
        "released_credits": row.released_credits,
        "category": row.category,
        "credit_value_rmb": str(row.credit_value_rmb),
        "revenue_rmb": str(row.revenue_rmb),
        "promotional_value_rmb": str(row.promotional_value_rmb),
        "provider": row.provider,
        "provider_route": row.provider_route,
        "token_inventory_id": row.token_inventory_id,
        "nominal_unit_cost_rmb": str(row.nominal_unit_cost_rmb),
        "safety_buffer": str(row.safety_buffer),
        "effective_unit_cost_rmb": str(row.effective_unit_cost_rmb),
        "actual_cost_rmb": str(row.actual_cost_rmb),
        "effective_cost_rmb": str(row.effective_cost_rmb),
        "gross_profit_rmb": str(row.gross_profit_rmb),
        "gross_margin": str(row.gross_margin) if row.gross_margin is not None else None,
        "successful_units": row.successful_units,
        "failed_units": row.failed_units,
        "settled_at": row.settled_at.isoformat() if row.settled_at else None,
    }


def _ledger_filters(
    query,
    user_id: Optional[str], request_id: Optional[str], provider_route: Optional[str],
    category: Optional[str], min_margin: Optional[float], max_margin: Optional[float],
    start: Optional[datetime], end: Optional[datetime],
):
    if user_id:
        query = query.where(CostMarginLedger.user_id == user_id)
    if request_id:
        query = query.where(CostMarginLedger.request_id == request_id)
    if provider_route:
        query = query.where(CostMarginLedger.provider_route == provider_route)
    if category:
        query = query.where(CostMarginLedger.category == category)
    if min_margin is not None:
        query = query.where(CostMarginLedger.gross_margin >= Decimal(str(min_margin)))
    if max_margin is not None:
        query = query.where(CostMarginLedger.gross_margin <= Decimal(str(max_margin)))
    if start:
        query = query.where(CostMarginLedger.settled_at >= start)
    if end:
        query = query.where(CostMarginLedger.settled_at < end)
    return query


@router.get("/margin/ledger")
async def list_margin_ledger(
    user_id: Optional[str] = None,
    request_id: Optional[str] = None,
    provider_route: Optional[str] = None,
    category: Optional[str] = None,
    min_margin: Optional[float] = None,
    max_margin: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    _=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    def _parse_date(value: str) -> datetime:
        try:
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")

    start = _parse_date(start_date) if start_date else None
    end = (_parse_date(end_date) + timedelta(days=1)) if end_date else None

    base = select(CostMarginLedger)
    base = _ledger_filters(base, user_id, request_id, provider_route, category,
                           min_margin, max_margin, start, end)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar()
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    rows = (await db.execute(
        base.order_by(CostMarginLedger.settled_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    user_ids = list({r.user_id for r in rows})
    uname_map: dict[str, str] = {}
    if user_ids:
        ures = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
        uname_map = {row.id: row.username for row in ures}

    agg = _ledger_filters(
        select(
            func.coalesce(func.sum(CostMarginLedger.revenue_rmb), 0),
            func.coalesce(func.sum(CostMarginLedger.promotional_value_rmb), 0),
            func.coalesce(func.sum(CostMarginLedger.actual_cost_rmb), 0),
            func.coalesce(func.sum(CostMarginLedger.gross_profit_rmb), 0),
            func.coalesce(func.sum(CostMarginLedger.charged_credits), 0),
            func.coalesce(func.sum(CostMarginLedger.successful_units), 0),
        ), user_id, request_id, provider_route, category,
        min_margin, max_margin, start, end,
    )
    revenue, promo, cost, profit, credits, units = (await db.execute(agg)).one()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "records": [_ledger_row_dict(r, uname_map.get(r.user_id, "")) for r in rows],
        "summary": {
            "revenue_rmb": str(revenue),
            "promotional_value_rmb": str(promo),
            "actual_cost_rmb": str(cost),
            "gross_profit_rmb": str(profit),
            "gross_margin": str(
                (profit / revenue).quantize(Decimal("0.0001"))
            ) if revenue and revenue > 0 else None,
            "charged_credits": credits,
            "successful_units": units,
        },
    }


# ── System Config（业务配置 K-V） ─────────────────────────────────

@router.get("/system-config")
async def get_system_config(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    configs = await config_service.all_configs(db)
    stored = {c.key: {"value": c.value,
                      "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                      "updated_by": c.updated_by} for c in configs}
    return {
        "configs": [
            {
                "key": key,
                "value": stored.get(key, {}).get("value", default),
                "default": default,
                "description": config_service.CONFIG_DESCRIPTIONS.get(key, ""),
                "updated_at": stored.get(key, {}).get("updated_at"),
                "updated_by": stored.get(key, {}).get("updated_by"),
            }
            for key, default in config_service.DEFAULTS.items()
        ]
    }


class ConfigUpdateRequest(BaseModel):
    key: str = Field(max_length=64)
    value: str = Field(max_length=255)
    reason: Optional[str] = Field(default=None, max_length=255)


@router.put("/system-config")
async def update_system_config(
    req: ConfigUpdateRequest,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """修改业务配置（兑换率/试用/毛利参数）。值合法性校验 + 审计。"""
    key = req.key.strip()
    value = req.value.strip()
    if key not in config_service.DEFAULTS:
        raise HTTPException(status_code=400, detail=f"未知配置键: {key}")

    # 严格校验（非法值 400，绝不静默吞掉）
    from decimal import InvalidOperation
    try:
        if key in config_service.INT_KEYS:
            if int(value) <= 0 and key in ("credits_per_cny", "legacy_usd_to_credits",
                                            "trial_grant_credits", "trial_campaign_version"):
                raise ValueError("必须为正整数")
        elif key in config_service.DECIMAL_KEYS:
            parsed = Decimal(value)
            if not (Decimal("0") < parsed < Decimal("1")):
                raise ValueError("必须为 0~1 之间的小数")
        elif key in config_service.BOOL_KEYS:
            if value.lower() not in ("true", "false"):
                raise ValueError("必须为 true/false")
    except (ValueError, InvalidOperation):
        raise HTTPException(status_code=400, detail=f"配置值非法: {key}={value}")

    await config_service.set_config(db, key, value, updated_by=admin.get("sub", "admin"))
    await _record_audit(db, admin, "system_config_update", {
        "key": key, "value": value, "reason": req.reason,
    })
    return {"ok": True, "key": key, "value": value}


# ── Credits Migration（旧余额迁移，生产须 super_admin 确认） ──────

class CreditsMigrationRequest(BaseModel):
    action: str = Field(pattern="^(preview|apply)$")


@router.post("/billing/credits-migration")
async def run_credits_migration(
    req: CreditsMigrationRequest,
    admin: dict = Depends(get_super_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """旧美元余额 → CY 点数迁移（preview 只读 / apply 正式执行）。

    生产环境部署后必须先 preview 核对报告（用户数/旧总余额/总点数/异常数），
    无异常再 apply。幂等：已执行过则跳过。
    """
    if req.action == "preview":
        return await credits_migration.preview_credits_migration(db)

    if settings.APP_ENV == "production":
        report = await credits_migration.preview_credits_migration(db)
        if not report["applied"] and (
            report["anomaly_count"] > 0
            or report["converted_count"] != report["user_count"]
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "MIGRATION_ANOMALY", "message": "存在异常用户，禁止迁移",
                        "report": report},
            )

    report = await credits_migration.apply_credits_migration(db)
    await _record_audit(db, admin, "credits_migration_apply", {
        "executed": report.get("executed"),
        "migrated_count": report.get("migrated_count"),
        "total_paid_credits": report.get("total_paid_credits"),
        "total_trial_credits": report.get("total_trial_credits"),
        "total_balance_usd": report.get("total_balance_usd"),
    })
    return report
