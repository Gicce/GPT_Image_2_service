from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.token import UsageLog
from app.models.content import AIModel

router = APIRouter()

# Pricing constants (USD)
PRICE_IMAGE = {
    "gpt-image-2": 0.040,
}
PRICE_CHAT_INPUT_PER_M = {
    "gpt-4.5": 1.0,
    "gpt-4o": 2.5,
}
PRICE_CHAT_OUTPUT_PER_M = {
    "gpt-4.5": 6.0,
    "gpt-4o": 10.0,
}
PRICE_CHAT_CACHE_PER_M = {
    "gpt-4.5": 0.1,
    "gpt-4o": 0.25,
}


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
    # Check trial restrictions
    _check_trial_access(user, req.model)

    price_per_image = PRICE_IMAGE.get(req.model)
    if price_per_image is None:
        # Try to get from DB model config
        result = await db.execute(select(AIModel).where(AIModel.name == req.model))
        model_cfg = result.scalar_one_or_none()
        if model_cfg and model_cfg.price_per_image:
            price_per_image = float(model_cfg.price_per_image)
        else:
            raise HTTPException(status_code=400, detail=f"未知模型: {req.model}")

    cost = price_per_image * req.image_count

    if float(user.balance_usd) < cost:
        raise HTTPException(status_code=402, detail="余额不足")

    user.balance_usd = float(user.balance_usd) - cost
    log = UsageLog(
        user_id=user.id,
        model=req.model,
        usage_type="image",
        image_count=req.image_count,
        cost_usd=cost,
    )
    db.add(log)
    return {"cost_usd": cost, "balance_usd": float(user.balance_usd)}


@router.post("/report/chat")
async def report_chat_usage(
    req: ChatUsageReport,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _check_trial_access(user, req.model)

    input_price = PRICE_CHAT_INPUT_PER_M.get(req.model, 1.0)
    output_price = PRICE_CHAT_OUTPUT_PER_M.get(req.model, 6.0)
    cache_price = PRICE_CHAT_CACHE_PER_M.get(req.model, 0.1)

    cost = (
        req.input_tokens / 1_000_000 * input_price
        + req.output_tokens / 1_000_000 * output_price
        + req.cached_tokens / 1_000_000 * cache_price
    )

    if float(user.balance_usd) < cost:
        raise HTTPException(status_code=402, detail="余额不足")

    user.balance_usd = float(user.balance_usd) - cost
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
    return {"cost_usd": cost, "balance_usd": float(user.balance_usd)}


def _check_trial_access(user: User, model: str):
    if user.account_type != "trial":
        return
    now = datetime.now(timezone.utc)
    if user.trial_expires_at and user.trial_expires_at.replace(tzinfo=timezone.utc) < now:
        raise HTTPException(status_code=403, detail="试用期已过期，请购买套餐")
    if model not in ("gpt-image-2",):
        raise HTTPException(status_code=403, detail="试用账号仅支持 gpt-image-2 模型")
