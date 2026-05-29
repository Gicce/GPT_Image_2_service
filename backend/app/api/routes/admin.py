import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import get_admin_user
from app.models.content import AIModel, Notice, Prompt
from app.models.token import Order, TokenInventory, UsageLog
from app.models.user import User

router = APIRouter()


class TokenBatchInput(BaseModel):
    tokens: list[str]
    package_usd: int
    group: str = "image"
    is_trial: bool = False


class NoticeUpdate(BaseModel):
    content: str


class PromptCreate(BaseModel):
    category: str
    title: str
    content: str
    sort_order: int = 0


class PromptUpdate(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class ModelCreate(BaseModel):
    name: str
    display_name: str
    provider: str = "OpenAI"
    billing_type: Optional[str] = None
    model_type: str
    group: Optional[str] = None
    is_enabled: bool = True
    trial_allowed: bool = False
    price_input: Optional[str] = None
    price_output: Optional[str] = None
    price_cached: Optional[str] = None
    price_per_call: Optional[str] = None
    price_per_image: Optional[str] = None
    price_input_per_m: Optional[str] = None
    price_output_per_m: Optional[str] = None
    price_cached_per_m: Optional[str] = None
    sort_order: int = 0
    context_window: int = 32768
    supports_tools: bool = False
    supports_vision: bool = False


class ModelUpdate(BaseModel):
    display_name: Optional[str] = None
    provider: Optional[str] = None
    billing_type: Optional[str] = None
    model_type: Optional[str] = None
    group: Optional[str] = None
    is_enabled: Optional[bool] = None
    trial_allowed: Optional[bool] = None
    price_input: Optional[str] = None
    price_output: Optional[str] = None
    price_cached: Optional[str] = None
    price_per_call: Optional[str] = None
    price_per_image: Optional[str] = None
    price_input_per_m: Optional[str] = None
    price_output_per_m: Optional[str] = None
    price_cached_per_m: Optional[str] = None
    sort_order: Optional[int] = None
    context_window: Optional[int] = None
    supports_tools: Optional[bool] = None
    supports_vision: Optional[bool] = None


class PasswordChange(BaseModel):
    new_password: str


@router.post("/tokens/batch")
async def add_tokens(req: TokenBatchInput, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    if req.package_usd not in (1, 10, 20, 50, 100) and not req.is_trial:
        raise HTTPException(status_code=400, detail="Invalid package_usd")
    added = 0
    for token_value in req.tokens:
        token_value = token_value.strip()
        if not token_value:
            continue
        existing = await db.execute(select(TokenInventory).where(TokenInventory.token_value == token_value))
        if existing.scalar_one_or_none():
            continue
        db.add(
            TokenInventory(
                id=str(uuid.uuid4()),
                token_value=token_value,
                package_usd=req.package_usd,
                group=req.group,
                is_trial=req.is_trial,
            )
        )
        added += 1
    await db.commit()
    return {"added": added}


@router.get("/tokens/stock")
async def get_stock(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(TokenInventory.group, func.count())
            .where(TokenInventory.is_assigned == False)
            .group_by(TokenInventory.group)
        )
    ).all()
    return {group or "image": count for group, count in rows}


@router.put("/notice")
async def update_notice(req: NoticeUpdate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    notice = (await db.execute(select(Notice).limit(1))).scalar_one_or_none()
    if notice:
        notice.content = req.content
        notice.updated_at = datetime.now(timezone.utc)
    else:
        db.add(Notice(id=str(uuid.uuid4()), content=req.content))
    redis = get_redis()
    await redis.delete("notice_content")
    await db.commit()
    return {"ok": True}


@router.get("/notice")
async def get_notice_admin(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    notice = (await db.execute(select(Notice).limit(1))).scalar_one_or_none()
    return {"content": notice.content if notice else ""}


@router.get("/prompts")
async def list_prompts(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Prompt).order_by(Prompt.category, Prompt.sort_order, Prompt.created_at))
    prompts = result.scalars().all()
    return [
        {
            "id": prompt.id,
            "category": prompt.category,
            "title": prompt.title,
            "content": prompt.content,
            "sort_order": prompt.sort_order,
            "is_active": prompt.is_active,
        }
        for prompt in prompts
    ]


@router.post("/prompts")
async def create_prompt(req: PromptCreate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    prompt = Prompt(id=str(uuid.uuid4()), **req.model_dump())
    db.add(prompt)
    await db.commit()
    return {"id": prompt.id}


@router.put("/prompts/{prompt_id}")
async def update_prompt(prompt_id: str, req: PromptUpdate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    prompt = (await db.execute(select(Prompt).where(Prompt.id == prompt_id))).scalar_one_or_none()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    for key, value in req.model_dump(exclude_none=True).items():
        setattr(prompt, key, value)
    await db.commit()
    return {"ok": True}


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    prompt = (await db.execute(select(Prompt).where(Prompt.id == prompt_id))).scalar_one_or_none()
    if prompt:
        await db.delete(prompt)
        await db.commit()
    return {"ok": True}


@router.get("/models")
async def list_models(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    models = (await db.execute(select(AIModel).order_by(AIModel.sort_order, AIModel.name))).scalars().all()
    return [
        {
            "id": model.id,
            "name": model.name,
            "display_name": model.display_name,
            "provider": model.provider,
            "billing_type": model.billing_type,
            "model_type": model.model_type,
            "group": model.group,
            "is_enabled": model.is_enabled,
            "trial_allowed": model.trial_allowed,
            "price_input": model.price_input,
            "price_output": model.price_output,
            "price_cached": model.price_cached,
            "price_per_call": model.price_per_call,
            "price_per_image": model.price_per_image,
            "price_input_per_m": model.price_input_per_m,
            "price_output_per_m": model.price_output_per_m,
            "price_cached_per_m": model.price_cached_per_m,
            "sort_order": model.sort_order,
            "context_window": model.context_window,
            "supports_tools": model.supports_tools,
            "supports_vision": model.supports_vision,
        }
        for model in models
    ]


@router.post("/models")
async def create_model(req: ModelCreate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    model = AIModel(id=str(uuid.uuid4()), **req.model_dump())
    db.add(model)
    await db.commit()
    return {"id": model.id}


@router.put("/models/{model_id}")
async def update_model(model_id: str, req: ModelUpdate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    model = (await db.execute(select(AIModel).where(AIModel.id == model_id))).scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    for key, value in req.model_dump(exclude_none=True).items():
        setattr(model, key, value)
    await db.commit()
    return {"ok": True}


@router.delete("/models/{model_id}")
async def delete_model(model_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    model = (await db.execute(select(AIModel).where(AIModel.id == model_id))).scalar_one_or_none()
    if model:
        await db.delete(model)
        await db.commit()
    return {"ok": True}


@router.get("/users")
async def list_users(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    users = (await db.execute(select(User).order_by(User.created_at.desc()).limit(200))).scalars().all()
    return [
        {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "account_type": user.account_type,
            "balance_usd": float(user.balance_usd),
            "is_active": user.is_active,
            "trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }
        for user in users
    ]


@router.get("/orders")
async def list_orders(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    orders = (await db.execute(select(Order).order_by(Order.created_at.desc()).limit(200))).scalars().all()
    user_ids = list({order.user_id for order in orders})
    usernames = {}
    if user_ids:
        rows = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
        usernames = {row.id: row.username for row in rows}
    return [
        {
            "id": order.id,
            "user_id": order.user_id,
            "username": usernames.get(order.user_id, ""),
            "out_trade_no": order.out_trade_no,
            "package_usd": order.package_usd,
            "group": order.group,
            "amount_usd": float(order.amount_usd or 0),
            "amount_cny": float(order.amount_cny),
            "exchange_rate": float(order.exchange_rate) if order.exchange_rate else None,
            "pay_type": order.pay_type,
            "status": order.status,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "paid_at": order.paid_at.isoformat() if order.paid_at else None,
            "allocated_at": order.allocated_at.isoformat() if order.allocated_at else None,
        }
        for order in orders
    ]


@router.get("/usage")
async def list_usage(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    logs = (await db.execute(select(UsageLog).order_by(UsageLog.created_at.desc()).limit(200))).scalars().all()
    return [
        {
            "id": log.id,
            "user_id": log.user_id,
            "model": log.model,
            "usage_type": log.usage_type,
            "image_count": log.image_count,
            "input_tokens": log.input_tokens,
            "output_tokens": log.output_tokens,
            "cached_tokens": log.cached_tokens,
            "cost_usd": float(log.cost_usd),
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


@router.put("/password")
async def change_admin_password(req: PasswordChange, _=Depends(get_admin_user)):
    settings.ADMIN_PASSWORD = req.new_password
    return {"ok": True, "note": "This only updates the in-memory value. Update .env for persistence."}
