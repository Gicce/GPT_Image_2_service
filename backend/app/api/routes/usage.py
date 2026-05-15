from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserToken
from app.models.token import TokenInventory
from app.models.content import AIModel

router = APIRouter()


class ImageUsageReport(BaseModel):
    model: str
    image_count: int = 1


class ChatUsageReport(BaseModel):
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


@router.post("/report/image")
async def report_image_usage(
    req: ImageUsageReport,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _check_trial_expired(user, db)

    model_cfg, ut = await _find_model_and_token(
        db, user, req.model, "per_call"
    )
    if not model_cfg or not model_cfg.price_per_call:
        raise HTTPException(status_code=400, detail=f"未知模型: {req.model}")
    if not ut:
        raise HTTPException(status_code=403, detail="未购买该分组套餐，请先充值")

    cost = float(model_cfg.price_per_call) * req.image_count
    if float(ut.balance_usd) < cost:
        raise HTTPException(status_code=402, detail="余额不足")

    ut.balance_usd = float(ut.balance_usd) - cost

    from app.models.token import UsageLog
    log = UsageLog(
        user_id=user.id,
        model=req.model,
        usage_type="image",
        image_count=req.image_count,
        cost_usd=cost,
    )
    db.add(log)
    await db.commit()
    return {"cost_usd": cost, "balance_usd": float(ut.balance_usd)}


@router.post("/report/chat")
async def report_chat_usage(
    req: ChatUsageReport,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _check_trial_expired(user, db)

    model_cfg, ut = await _find_model_and_token(
        db, user, req.model, "per_token"
    )
    if not model_cfg:
        raise HTTPException(status_code=400, detail=f"未知模型: {req.model}")
    if not ut:
        raise HTTPException(status_code=403, detail="未购买该分组套餐，请先充值")

    input_price = float(model_cfg.price_input or "0")
    output_price = float(model_cfg.price_output or "0")
    cache_price = float(model_cfg.price_cached or "0")

    cost = (
        req.input_tokens / 1_000 * input_price
        + req.output_tokens / 1_000 * output_price
        + req.cached_tokens / 1_000 * cache_price
    )

    if float(ut.balance_usd) < cost:
        raise HTTPException(status_code=402, detail="余额不足")

    ut.balance_usd = float(ut.balance_usd) - cost

    from app.models.token import UsageLog
    log = UsageLog(
        user_id=user.id,
        model=req.model,
        usage_type="chat",
        input_tokens=req.input_tokens,
        output_tokens=req.output_tokens,
        cached_tokens=req.cached_tokens,
        cost_usd=cost,
    )
    db.add(log)
    await db.commit()
    return {"cost_usd": cost, "balance_usd": float(ut.balance_usd)}


async def _find_model_and_token(db, user, model_name, billing_type):
    """Find model config and user's token for the model's group."""
    models_result = await db.execute(
        select(AIModel).where(AIModel.name == model_name, AIModel.billing_type == billing_type)
    )
    model_cfgs = models_result.scalars().all()
    if not model_cfgs:
        return None, None

    ut_result = await db.execute(
        select(UserToken).where(UserToken.user_id == user.id)
    )
    user_tokens = {ut.group: ut for ut in ut_result.scalars().all()}

    for cfg in model_cfgs:
        if cfg.group in user_tokens:
            return cfg, user_tokens[cfg.group]

    return model_cfgs[0], None


async def _check_trial_expired(user: User, db: AsyncSession):
    if user.account_type != "trial":
        return
    now = datetime.now(timezone.utc)
    if user.trial_expires_at and user.trial_expires_at.replace(tzinfo=timezone.utc) < now:
        user.account_type = "normal"
        await db.commit()
        raise HTTPException(status_code=403, detail="试用期已过期，请购买套餐")
