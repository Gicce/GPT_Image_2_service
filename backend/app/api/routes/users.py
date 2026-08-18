from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.token import UsageLog
from app.models.content import AIModel
from app.services import billing
from app.services import runtime_token as rt

router = APIRouter()


@router.get("/me/entitlements")
async def get_account_entitlements(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """账户权益：统一现金余额 + 试用额度 + Image2 配置。"""
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    cfg = await billing.get_image2_config(db)
    price = billing.q6(billing.d(cfg.price_per_call)) if cfg and cfg.price_per_call is not None else None
    balance = billing.q6(billing.d(user.balance_usd))
    trial = billing.q6(billing.d(user.trial_credit_usd))

    return {
        "balance_usd": str(balance),
        "trial_credit_usd": str(trial),
        "total_credit_usd": str(balance + trial),
        "enabled_features": {"image": bool(cfg and cfg.is_enabled)},
        "enabled_models": ["gpt-image-2"] if cfg and cfg.is_enabled else [],
        "image2": {
            "enabled": bool(cfg and cfg.is_enabled),
            "trial_allowed": bool(cfg.trial_allowed) if cfg else False,
            "price_per_call_usd": str(price) if price else None,
            "currency": cfg.currency if cfg else "USD",
        },
    }


@router.get("/me/runtime-token")
async def get_my_runtime_token(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前账户的 Image2 Runtime Token 状态（仅脱敏信息，绝不返回明文）。

    V4.1：Token 由系统自动分配（注册试用 → 默认试用 Token；充值成功 → 默认正式 Token），
    普通用户不再提供手动领取/更换入口；绑定调整由管理员操作。
    """
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    assignment = await rt.get_user_active_assignment(db, user.id)
    if assignment is not None:
        assigned = await db.get(rt.TokenInventory, assignment.token_id)
        if assigned is not None:
            return {
                "assigned": True,
                "source": "assigned",
                **rt.token_public_dict(assigned, assigned_at=assignment.assigned_at),
            }

    master = settings.PACKYAPI_IMAGE_MASTER_TOKEN or settings.PACKYAPI_MASTER_TOKEN
    if master:
        return {
            "assigned": False,
            "source": "server_master",
            "token_id": None,
            "name": None,
            "masked_token": rt.mask_token(master),
            "is_trial": False,
            "is_disabled": False,
            "assigned_at": None,
        }
    return {"assigned": False, "source": "none", "token_id": None, "name": None,
            "masked_token": None, "is_trial": False, "is_disabled": False, "assigned_at": None}


@router.get("/me/runtime-config")
async def get_runtime_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """下发 Image2 运行时直连配置（仅 image，V4 起无 agent/postprocess）。

    优先使用当前账户绑定的 Runtime Token（须仍有效）；未绑定/失效时回落服务端 Master Token。
    仅当账户有可用额度且存在可用上游 Token 时返回 enabled。
    """
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    cfg = await billing.get_image2_config(db)

    assigned = await rt.get_user_active_token(db, user.id)
    if assigned is not None and await rt.is_token_assignable(db, assigned):
        image_token = assigned.token_value
    else:
        image_token = settings.PACKYAPI_IMAGE_MASTER_TOKEN or settings.PACKYAPI_MASTER_TOKEN

    balance = billing.d(user.balance_usd) + billing.d(user.trial_credit_usd)
    enabled = bool(
        cfg and cfg.is_enabled and image_token and user.is_active and balance > 0
    )

    image_config = {
        "enabled": enabled,
        "base_url": settings.PACKYAPI_IMAGE_BASE_URL if enabled else "",
        "token": image_token if enabled else "",
        "expires_in": 3600 if enabled else 0,
        "provider": "packyapi",
    }
    if enabled:
        image_config["model"] = billing.IMAGE2_MODEL_ID

    return {
        "image": image_config,
        # V4：agent/postprocess 已下线（Agent 全面 BYOK），保留空配置占位以便旧客户端忽略
        "agent": {"enabled": False, "base_url": "", "token": "", "expires_in": 0, "provider": None},
        "postprocess": {"enabled": False, "base_url": "", "token": "", "expires_in": 0, "provider": None},
    }


@router.get("/me")
async def get_me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.api.routes.auth import _user_info
    return await _user_info(user, db)


@router.get("/me/usage")
async def get_usage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    result = await db.execute(
        select(UsageLog)
        .where(UsageLog.user_id == user.id)
        .order_by(UsageLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "model": log.model,
            "usage_type": log.usage_type,
            "image_count": log.image_count,
            "cost_usd": str(log.cost_usd),
            "request_id": log.request_id,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]
