from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Optional
import uuid

from app.core.database import get_db
from app.core.security import get_admin_user
from app.core.redis import get_redis
from app.core.config import settings
from app.core.security import hash_password
from app.models.user import User
from app.models.token import TokenInventory, Order, UsageLog
from app.models.content import Notice, Prompt, AIModel

router = APIRouter()


# ── Token Inventory ──────────────────────────────────────────────

class TokenBatchInput(BaseModel):
    tokens: list[str]
    package_usd: int
    is_trial: bool = False


@router.post("/tokens/batch")
async def add_tokens(req: TokenBatchInput, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    if req.package_usd not in (1, 10, 20, 50, 100) and not req.is_trial:
        raise HTTPException(status_code=400, detail="无效套餐金额")
    added = 0
    for t in req.tokens:
        t = t.strip()
        if not t:
            continue
        existing = await db.execute(select(TokenInventory).where(TokenInventory.token_value == t))
        if existing.scalar_one_or_none():
            continue
        db.add(TokenInventory(
            id=str(uuid.uuid4()),
            token_value=t,
            package_usd=req.package_usd,
            is_trial=req.is_trial,
        ))
        added += 1
    return {"added": added}


@router.get("/tokens/stock")
async def get_stock(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    packages = [1, 10, 20, 50, 100]
    result = {}
    for pkg in packages:
        rows = await db.execute(
            select(func.count()).select_from(TokenInventory).where(
                TokenInventory.package_usd == pkg,
                TokenInventory.is_assigned == False,
            )
        )
        result[str(pkg)] = rows.scalar()
    return result


# ── Notice ───────────────────────────────────────────────────────

class NoticeUpdate(BaseModel):
    content: str


@router.put("/notice")
async def update_notice(req: NoticeUpdate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Notice).limit(1))
    notice = result.scalar_one_or_none()
    if notice:
        notice.content = req.content
        notice.updated_at = datetime.now(timezone.utc)
    else:
        db.add(Notice(id=str(uuid.uuid4()), content=req.content))
    # Invalidate Redis cache
    redis = get_redis()
    await redis.delete("notice_content")
    return {"ok": True}


@router.get("/notice")
async def get_notice_admin(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Notice).limit(1))
    notice = result.scalar_one_or_none()
    return {"content": notice.content if notice else ""}


# ── Prompts ──────────────────────────────────────────────────────

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


@router.get("/prompts")
async def list_prompts(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Prompt).order_by(Prompt.category, Prompt.sort_order))
    prompts = result.scalars().all()
    return [{"id": p.id, "category": p.category, "title": p.title, "content": p.content,
             "sort_order": p.sort_order, "is_active": p.is_active} for p in prompts]


@router.post("/prompts")
async def create_prompt(req: PromptCreate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    p = Prompt(id=str(uuid.uuid4()), **req.model_dump())
    db.add(p)
    await db.flush()
    return {"id": p.id}


@router.put("/prompts/{prompt_id}")
async def update_prompt(prompt_id: str, req: PromptUpdate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Prompt).where(Prompt.id == prompt_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="提示词不存在")
    for k, v in req.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    return {"ok": True}


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Prompt).where(Prompt.id == prompt_id))
    p = result.scalar_one_or_none()
    if p:
        await db.delete(p)
    return {"ok": True}


# ── AI Models ────────────────────────────────────────────────────

class ModelCreate(BaseModel):
    name: str
    display_name: str
    model_type: str
    is_enabled: bool = True
    trial_allowed: bool = False
    price_per_image: Optional[float] = None
    price_input_per_m: Optional[float] = None
    price_output_per_m: Optional[float] = None
    price_cached_per_m: Optional[float] = None
    sort_order: int = 0


class ModelUpdate(BaseModel):
    display_name: Optional[str] = None
    is_enabled: Optional[bool] = None
    trial_allowed: Optional[bool] = None
    price_per_image: Optional[float] = None
    price_input_per_m: Optional[float] = None
    price_output_per_m: Optional[float] = None
    price_cached_per_m: Optional[float] = None
    sort_order: Optional[int] = None


@router.get("/models")
async def list_models(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AIModel).order_by(AIModel.sort_order))
    return [{"id": m.id, "name": m.name, "display_name": m.display_name, "model_type": m.model_type,
             "is_enabled": m.is_enabled, "trial_allowed": m.trial_allowed,
             "price_per_image": m.price_per_image, "price_input_per_m": m.price_input_per_m,
             "price_output_per_m": m.price_output_per_m, "price_cached_per_m": m.price_cached_per_m,
             "sort_order": m.sort_order}
            for m in result.scalars().all()]


@router.post("/models")
async def create_model(req: ModelCreate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    m = AIModel(id=str(uuid.uuid4()), **req.model_dump())
    db.add(m)
    await db.flush()
    return {"id": m.id}


@router.put("/models/{model_id}")
async def update_model(model_id: str, req: ModelUpdate, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AIModel).where(AIModel.id == model_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="模型不存在")
    for k, v in req.model_dump(exclude_none=True).items():
        setattr(m, k, v)
    return {"ok": True}


@router.delete("/models/{model_id}")
async def delete_model(model_id: str, _=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AIModel).where(AIModel.id == model_id))
    m = result.scalar_one_or_none()
    if m:
        await db.delete(m)
    return {"ok": True}


# ── Users ────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.created_at.desc()).limit(200))
    users = result.scalars().all()
    return [{"id": u.id, "username": u.username, "email": u.email,
             "account_type": u.account_type, "balance_usd": float(u.balance_usd),
             "is_active": u.is_active,
             "trial_expires_at": u.trial_expires_at.isoformat() if u.trial_expires_at else None,
             "created_at": u.created_at.isoformat()} for u in users]


# ── Orders ───────────────────────────────────────────────────────

@router.get("/orders")
async def list_orders(_=Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).order_by(Order.created_at.desc()).limit(200))
    orders = result.scalars().all()
    # Fetch usernames in one query
    user_ids = list({o.user_id for o in orders})
    uname_map = {}
    if user_ids:
        ures = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
        uname_map = {row.id: row.username for row in ures}
    return [{"id": o.id, "user_id": o.user_id, "username": uname_map.get(o.user_id, ""),
             "out_trade_no": o.out_trade_no,
             "package_usd": o.package_usd, "amount_cny": float(o.amount_cny),
             "exchange_rate": float(o.exchange_rate) if o.exchange_rate else None,
             "pay_type": o.pay_type, "status": o.status,
             "created_at": o.created_at.isoformat(),
             "paid_at": o.paid_at.isoformat() if o.paid_at else None} for o in orders]


# ── Admin password change ─────────────────────────────────────────

class PasswordChange(BaseModel):
    new_password: str


@router.put("/password")
async def change_admin_password(req: PasswordChange, _=Depends(get_admin_user)):
    # Update in-memory settings (persists until restart; for permanent change use .env)
    settings.ADMIN_PASSWORD = req.new_password
    return {"ok": True, "note": "重启后失效，如需永久修改请更新 .env 文件中的 ADMIN_PASSWORD"}
